"""Documentos de viaje (app/documentos.py, app/documentos_api.py, app/documentos_cifrado.py): tipos por firma, topes,
PDF con contenido activo, cupo, aislamiento entre personas, borrado y reemplazo con su objeto, cifrado, sección apagada
en Railway sin bucket o sin clave, cabeceras, modo prueba, retención y avisos. Almacén en disco (tmp), sin red."""
import base64
import datetime as dt
import os
import uuid
import zlib

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient

from app import config, db, documentos, documentos_api, documentos_cifrado, limites, sandbox
from app.estadia import FIN_DE_LA_ESTADIA
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
CLAVE = base64.b64encode(os.urandom(32)).decode()
META = {"tipo": "pasaporte", "titulo": "Pasaporte", "notas": ""}


def _variables_docs(monkeypatch, **valores):
    for nombre in ("ENDPOINT", "BUCKET", "KEY_ID", "SECRET", "REGION"):
        monkeypatch.setattr(config, f"DOCS_S3_{nombre}", valores.get(nombre, ""))


def _limpiar():
    with sandbox.real(), db.conn() as c:
        c.execute("DELETE FROM viajes_documentos")


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOCS_DIR", tmp_path)
    monkeypatch.setattr(config, "DOCS_ENC_KEY", CLAVE)
    monkeypatch.setattr(config, "EN_PRODUCCION", False)
    _variables_docs(monkeypatch)
    with TestClient(app) as c:
        c.A = login_headers(c)
        c.B = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        c.dir = tmp_path
        limites.reiniciar_todo()
        documentos_api._subidas.reiniciar()
        documentos_api._descargas.reiniciar()
        _limpiar()
        yield c
        _limpiar()


def subir(cli, headers, datos=JPEG, mime="image/jpeg", **meta):
    return cli.post("/api/viajes/documentos", headers=headers, data={**META, **meta},
                    files={"archivo": ("pasaporte-juan-perez.jpg", datos, mime)})


def objetos(base):
    return [p for p in base.rglob("*") if p.is_file()]


def _clave_en_base(id_):
    with sandbox.real(), db.conn() as c:
        return c.execute("SELECT archivo_clave FROM viajes_documentos WHERE id=%s", (id_,)).fetchone()["archivo_clave"]


# ---------- alta, lectura y cabeceras ----------

def test_alta_guarda_cifrado_y_se_lee_por_proxy_con_cabeceras_privadas(cli):
    r = subir(cli, cli.A, vence="2030-01-01", notas="Renovar en 2029")
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["tipo"] == "pasaporte" and doc["archivo_tipo"] == "image/jpeg" and doc["bytes"] == len(JPEG)
    assert "archivo_clave" not in doc
    [objeto] = objetos(cli.dir)
    crudo = objeto.read_bytes()
    assert JPEG not in crudo and crudo[0] == documentos_cifrado.VERSION   # en el almacén solo hay bytes cifrados
    clave = _clave_en_base(doc["id"])
    assert clave.startswith("documentos/") and TEST_USER not in clave and "pasaporte" not in clave and ".jpg" not in clave
    r = cli.get(f"/api/viajes/documentos/{doc['id']}/archivo", headers=cli.A)
    assert r.status_code == 200 and r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"] == 'inline; filename="documento.jpg"'
    assert "sandbox" in r.headers["content-security-policy"]


def test_la_lista_trae_solo_metadatos_y_no_se_cachea(cli):
    subir(cli, cli.A)
    r = cli.get("/api/viajes/documentos", headers=cli.A)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "private, no-store" and r.headers["x-content-type-options"] == "nosniff"
    [doc] = r.json()["documentos"]
    assert "archivo_clave" not in doc and doc["titulo"] == "Pasaporte"
    assert r.json()["max"] == documentos.MAX_POR_USUARIO


def test_pdf_limpio_se_baja_como_adjunto(cli):
    r = subir(cli, cli.A, PDF, "application/pdf", tipo="seguro", titulo="Seguro")
    assert r.status_code == 201, r.text
    r = cli.get(f"/api/viajes/documentos/{r.json()['id']}/archivo", headers=cli.A)
    assert r.content == PDF and r.headers["content-disposition"] == 'attachment; filename="documento.pdf"'


def test_sin_sesion_no_hay_nada(cli):
    assert cli.get("/api/viajes/documentos").status_code == 401


# ---------- validaciones ----------

def test_firma_invalida_se_rechaza_aunque_diga_ser_jpeg(cli):
    r = subir(cli, cli.A, b"<html><script>alert(1)</script></html>", "image/jpeg")
    assert r.status_code == 415
    assert objetos(cli.dir) == []


def test_firma_valida_de_png(cli):
    assert subir(cli, cli.A, PNG, "image/png").status_code == 201


def test_mas_de_8_mb_da_413(cli):
    grande = JPEG + b"\x00" * (documentos.ARCHIVO_MAX_BYTES + 1)
    assert subir(cli, cli.A, grande).status_code == 413
    assert objetos(cli.dir) == []


@pytest.mark.parametrize("malo", [
    PDF.replace(b"/Type /Catalog", b"/Type /Catalog /OpenAction << /S /JavaScript /JS (app.alert(1)) >>"),
    PDF.replace(b"/Type /Catalog", b"/Type /Catalog /OpenAction << /S /J#61vaScript >>"),
    PDF.replace(b"/Type /Catalog", b"/Type /Catalog /Names << /EmbeddedFiles 3 0 R >>"),
    PDF.replace(b"/Type /Catalog", b"/Type /Catalog /OpenAction << /S /Launch /F (cmd.exe) >>"),
    PDF + b"4 0 obj\n<< /Type /ObjStm /Filter /FlateDecode >>\nstream\n"
    + zlib.compress(b"<< /S /JavaScript /JS (x) >>") + b"\nendstream\nendobj\n",
])
def test_pdf_con_javascript_o_adjuntos_se_rechaza(cli, malo):
    assert subir(cli, cli.A, malo, "application/pdf").status_code == 415
    assert objetos(cli.dir) == []


def test_nombres_parecidos_no_disparan_falsos_positivos():
    assert not documentos.pdf_con_contenido_activo(PDF + b"<< /JSON 1 /JBIG2Decode 2 >>")


def test_metadatos_invalidos_dan_422(cli):
    assert subir(cli, cli.A, tipo="cualquiera").status_code == 422
    assert subir(cli, cli.A, titulo="x" * 81).status_code == 422
    assert subir(cli, cli.A, notas="x" * 501).status_code == 422
    assert subir(cli, cli.A, vuelo_id="no-existe").status_code == 422
    assert objetos(cli.dir) == []


def test_cupo_de_subidas_da_429(cli, monkeypatch):
    monkeypatch.setattr(documentos_api, "_subidas", limites.Limite(2, limites.VENTANA_LARGA))
    assert subir(cli, cli.A).status_code == 201
    assert subir(cli, cli.A).status_code == 201
    assert subir(cli, cli.A).status_code == 429


def test_maximo_de_documentos_por_persona(cli, monkeypatch):
    monkeypatch.setattr(documentos, "MAX_POR_USUARIO", 1)
    assert subir(cli, cli.A).status_code == 201
    assert subir(cli, cli.A).status_code == 409
    assert len(objetos(cli.dir)) == 1


def test_si_falla_el_alta_en_la_base_se_borra_el_objeto(cli, monkeypatch):
    def falla(*_a, **_k):
        raise RuntimeError("base caída")

    monkeypatch.setattr(documentos, "insertar", falla)
    with TestClient(app, raise_server_exceptions=False) as c:
        assert subir(c, cli.A).status_code == 500
    assert objetos(cli.dir) == []


# ---------- aislamiento ----------

def test_un_documento_ajeno_da_404_igual_que_uno_inexistente(cli):
    id_ = subir(cli, cli.A).json()["id"]
    inexistente = str(uuid.uuid4())
    for ruta in (f"/api/viajes/documentos/{id_}/archivo", f"/api/viajes/documentos/{inexistente}/archivo"):
        r = cli.get(ruta, headers=cli.B)
        assert r.status_code == 404 and r.json() == {"detail": "Documento no encontrado"}
    assert cli.put(f"/api/viajes/documentos/{id_}", headers=cli.B, json=META).status_code == 404
    assert cli.put(f"/api/viajes/documentos/{id_}/archivo", headers=cli.B,
                   files={"archivo": ("x.png", PNG, "image/png")}).status_code == 404
    assert cli.delete(f"/api/viajes/documentos/{id_}", headers=cli.B).status_code == 404
    assert cli.get("/api/viajes/documentos", headers=cli.B).json()["documentos"] == []
    assert cli.get(f"/api/viajes/documentos/{id_}/archivo", headers=cli.A).content == JPEG
    assert len(objetos(cli.dir)) == 1


# ---------- edición, reemplazo y borrado ----------

def test_editar_metadatos(cli):
    id_ = subir(cli, cli.A).json()["id"]
    r = cli.put(f"/api/viajes/documentos/{id_}", headers=cli.A,
                json={"tipo": "esta_visa", "titulo": "ESTA", "vence": "2028-05-01", "notas": "aprobada"})
    assert r.status_code == 200 and r.json()["tipo"] == "esta_visa" and r.json()["vence"] == "2028-05-01"


def test_reemplazar_el_archivo_borra_el_anterior(cli):
    id_ = subir(cli, cli.A).json()["id"]
    anterior = _clave_en_base(id_)
    r = cli.put(f"/api/viajes/documentos/{id_}/archivo", headers=cli.A, files={"archivo": ("x.png", PNG, "image/png")})
    assert r.status_code == 200 and r.json()["archivo_tipo"] == "image/png"
    assert _clave_en_base(id_) != anterior
    assert not (cli.dir / anterior).exists() and len(objetos(cli.dir)) == 1
    assert cli.get(f"/api/viajes/documentos/{id_}/archivo", headers=cli.A).content == PNG


def test_borrar_quita_la_fila_y_el_objeto(cli):
    id_ = subir(cli, cli.A).json()["id"]
    assert cli.delete(f"/api/viajes/documentos/{id_}", headers=cli.A).status_code == 200
    assert cli.get("/api/viajes/documentos", headers=cli.A).json()["documentos"] == []
    assert objetos(cli.dir) == []


def test_borrar_todos_solo_toca_lo_propio(cli):
    subir(cli, cli.A)
    subir(cli, cli.A, PNG, "image/png")
    subir(cli, cli.B)
    r = cli.delete("/api/viajes/documentos", headers=cli.A)
    assert r.json()["borrados"] == 2
    assert len(cli.get("/api/viajes/documentos", headers=cli.B).json()["documentos"]) == 1
    assert len(objetos(cli.dir)) == 1


def test_un_objeto_adulterado_no_se_sirve(cli):
    id_ = subir(cli, cli.A).json()["id"]
    [objeto] = objetos(cli.dir)
    crudo = bytearray(objeto.read_bytes())
    crudo[-1] ^= 1
    objeto.write_bytes(bytes(crudo))
    assert cli.get(f"/api/viajes/documentos/{id_}/archivo", headers=cli.A).status_code == 502


# ---------- cifrado ----------

def test_cifrado_ida_y_vuelta_con_nonce_distinto_y_aad():
    key = os.urandom(32)
    a = documentos_cifrado.cifrar(b"pasaporte", "documentos/x/1", key)
    b = documentos_cifrado.cifrar(b"pasaporte", "documentos/x/1", key)
    assert a != b and a[1:13] != b[1:13]
    assert documentos_cifrado.descifrar(a, "documentos/x/1", key) == b"pasaporte"
    with pytest.raises(InvalidTag):
        documentos_cifrado.descifrar(a, "documentos/x/2", key)
    with pytest.raises(InvalidTag):
        documentos_cifrado.descifrar(a, "documentos/x/1", os.urandom(32))
    with pytest.raises(documentos_cifrado.FormatoDesconocido):
        documentos_cifrado.descifrar(b"\x09" + a[1:], "documentos/x/1", key)


def test_la_clave_tiene_que_ser_de_32_bytes_en_base64(monkeypatch):
    for mala in ("", "no-es-base64!!", base64.b64encode(b"corta").decode()):
        monkeypatch.setattr(config, "DOCS_ENC_KEY", mala)
        assert documentos_cifrado.clave() is None
    monkeypatch.setattr(config, "DOCS_ENC_KEY", CLAVE)
    assert len(documentos_cifrado.clave()) == 32


def test_la_carpeta_no_muestra_el_usuario_y_es_estable():
    key = os.urandom(32)
    carpeta = documentos_cifrado.carpeta("ale", key)
    assert carpeta == documentos_cifrado.carpeta("ale", key) != documentos_cifrado.carpeta("otro", key)
    assert "ale" not in carpeta and len(carpeta) == documentos_cifrado.LARGO_CARPETA


# ---------- sección apagada ----------

def test_en_railway_sin_clave_responde_503(cli, monkeypatch):
    monkeypatch.setattr(config, "EN_PRODUCCION", True)
    _variables_docs(monkeypatch, ENDPOINT="https://s3.example.test", BUCKET="b", KEY_ID="k", SECRET="s", REGION="auto")
    monkeypatch.setattr(config, "DOCS_ENC_KEY", "")
    r = cli.get("/api/viajes/documentos", headers=cli.A)
    assert r.status_code == 503 and "no están activos" in r.json()["detail"]
    assert subir(cli, cli.A).status_code == 503


def test_en_railway_sin_bucket_responde_503_y_no_cae_al_disco(cli, monkeypatch):
    monkeypatch.setattr(config, "EN_PRODUCCION", True)
    assert cli.get("/api/viajes/documentos", headers=cli.A).status_code == 503
    assert subir(cli, cli.A).status_code == 503
    assert objetos(cli.dir) == []


def test_en_railway_con_bucket_usa_s3_y_no_el_disco(monkeypatch):
    monkeypatch.setattr(config, "EN_PRODUCCION", True)
    monkeypatch.setattr(config, "DOCS_ENC_KEY", CLAVE)
    _variables_docs(monkeypatch, ENDPOINT="https://s3.example.test", BUCKET="b", KEY_ID="k", SECRET="s", REGION="auto")
    assert documentos.disponible()
    assert isinstance(documentos.almacen(), documentos.tickets_almacen.AlmacenS3)


def test_al_arrancar_en_railway_avisa_solo_nombres(monkeypatch, caplog):
    monkeypatch.setattr(config, "EN_PRODUCCION", True)
    _variables_docs(monkeypatch, SECRET="no-se-loguea")
    monkeypatch.setattr(config, "DOCS_ENC_KEY", "")
    documentos.verificar_configuracion()
    assert "DOCS_S3_BUCKET" in caplog.text and "DOCS_ENC_KEY" in caplog.text and "no-se-loguea" not in caplog.text


# ---------- modo prueba ----------

def test_modo_prueba_usa_prefijo_propio_y_se_limpia_con_los_datos_de_prueba(cli):
    username = f"doc_{uuid.uuid4().hex[:6]}"
    assert cli.post("/api/admin/users", headers=cli.B, json={"username": username, "password": "docpass1234"}).status_code == 200
    usuario = login_headers(cli, username, "docpass1234")
    assert cli.put(f"/api/admin/users/{username}/sandbox", headers=cli.B, json={"active": True}).status_code == 200
    id_ = subir(cli, usuario).json()["id"]
    with sandbox.real(), db.conn() as c:
        clave = c.execute(f"SELECT archivo_clave FROM {sandbox.schema_prueba()}.viajes_documentos WHERE id=%s",
                          (id_,)).fetchone()["archivo_clave"]
        assert c.execute("SELECT count(*) AS n FROM viajes_documentos WHERE id=%s", (id_,)).fetchone()["n"] == 0
    assert clave.startswith("prueba/documentos/") and (cli.dir / clave).exists()
    assert cli.delete("/api/admin/sandbox/data", headers=cli.B).status_code == 200
    assert not (cli.dir / clave).exists()


# ---------- retención ----------

def test_el_borrado_automatico_espera_30_dias_despues_del_viaje(cli):
    subir(cli, cli.A)
    limite = FIN_DE_LA_ESTADIA + dt.timedelta(days=documentos.RETENCION_DIAS)
    assert documentos.purgar_si_toca(limite - dt.timedelta(minutes=1)) == 0
    assert len(objetos(cli.dir)) == 1
    assert documentos.purgar_si_toca(limite) == 1
    assert objetos(cli.dir) == []
    assert cli.get("/api/viajes/documentos", headers=cli.A).json()["documentos"] == []


# ---------- vencimientos y avisos ----------

FIN = FIN_DE_LA_ESTADIA.date()


@pytest.mark.parametrize(("tipo", "vence", "alerta"), [
    ("esta_visa", FIN, True),
    ("esta_visa", FIN + dt.timedelta(days=1), False),
    ("pasaporte", FIN + dt.timedelta(days=90), True),
    ("pasaporte", dt.date(FIN.year + 1, 6, FIN.day), False),
    ("seguro", None, False),
])
def test_alerta_de_vencimiento(tipo, vence, alerta):
    assert bool(documentos.alerta_vencimiento({"tipo": tipo, "vence": vence})) is alerta


def test_un_aviso_sin_datos_del_documento_y_respetando_el_silencio(cli):
    subir(cli, cli.A, tipo="esta_visa", titulo="ESTA de Juan", vence=FIN.isoformat(), notas="nro 123")
    de_dia = FIN_DE_LA_ESTADIA.replace(day=1, hour=10)
    [(clave, msg)] = documentos.avisos(TEST_USER, de_dia)
    assert clave.startswith("docvence:") and msg["url"] == "/#/viajes/documentos"
    assert "Juan" not in str(msg) and "123" not in str(msg) and "ESTA" not in str(msg)
    assert documentos.avisos(TEST_USER, de_dia.replace(hour=3)) == []           # de noche no
    assert documentos.avisos(TEST_USER, FIN_DE_LA_ESTADIA) == []                # terminado el viaje, no
    assert documentos.avisos(TEST_ADMIN, de_dia) == []                         # cada uno lo suyo

"""Control de gastos (app/gastos.py, app/gastos_api.py): sync idempotente, conflictos, borrado lógico, aislamiento entre
personas, conversión ARS→USD con cotización congelada, totales, export CSV, fotos y validaciones. Sin red ni catálogo."""
import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import config, cotizacion, db, gastos, gastos_api, gastos_links, limites, tickets_almacen
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

TARJETA_RESPALDO = float(cotizacion.RESPALDO["tarjeta"])

# Relativo a hoy: el servidor recorta los updated_at adelantados (reloj mal puesto), así que no puede ser una fecha futura.
T0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=3)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"\r\n\n\x00\xff" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 20


def entrada(**kw):
    base = {"client_id": str(uuid.uuid4()), "fecha": "2026-12-01", "monto": 10, "moneda": "USD",
            "categoria": "comida", "nota": "", "reintegrable": False, "compartido": False,
            "updated_at": T0.isoformat(), "deleted_at": None}
    return {**base, **kw}


def _limpiar():
    with db.conn() as c:
        c.execute("DELETE FROM gastos")
        c.execute("DELETE FROM gastos_presupuesto")
        c.execute("DELETE FROM cotizaciones")


def poner_cotizacion(oficial=1000, blue=1200, tarjeta=1300):
    with db.conn() as c:
        c.execute("INSERT INTO cotizaciones (oficial, blue, tarjeta) VALUES (%s, %s, %s)", (oficial, blue, tarjeta))


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.TICKETS_DIR", tmp_path)
    monkeypatch.setattr("app.cotizacion._ultima_consulta_ok", None)
    with TestClient(app) as c:
        c.A = login_headers(c)
        c.B = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        limites.reiniciar_todo()
        gastos_api._syncs.reiniciar()
        gastos_api._fotos.reiniciar()
        _limpiar()
        poner_cotizacion()
        yield c
        _limpiar()


def sync(cli, headers, *cambios, desde=None):
    r = cli.post("/api/gastos/sync", headers=headers, json={"cambios": list(cambios), "desde": desde})
    assert r.status_code == 200, r.text
    return r.json()


def foto(cli, headers, client_id, datos=JPEG, tipo="image/jpeg", campo="foto"):
    return cli.post(f"/api/gastos/{client_id}/foto", headers=headers, files={campo: ("lo-que-sea.exe", datos, tipo)})


def borrar(cli, g, headers=None):
    marca = (T0 + timedelta(hours=1)).isoformat()
    return sync(cli, headers or cli.A, {**g, "updated_at": marca, "deleted_at": marca})


# ---------- sync ----------

def test_sync_crea_el_gasto_y_congela_las_tres_cotizaciones(cli):
    g = entrada(monto=13000, moneda="ARS")
    r = sync(cli, cli.A, g)
    assert r["aplicados"] == [g["client_id"]]
    creado = r["cambios"][0]
    assert (creado["cotizacion_oficial"], creado["cotizacion_blue"], creado["cotizacion_tarjeta"]) == (1000, 1200, 1300)
    assert creado["monto_usd"] == 10.0  # 13000 ARS / 1300 de tarjeta


def test_un_gasto_en_dolares_no_se_convierte(cli):
    r = sync(cli, cli.A, entrada(monto=25.5, moneda="USD"))
    assert r["cambios"][0]["monto_usd"] == 25.5


def test_la_cotizacion_congelada_no_cambia_cuando_el_dolar_se_mueve(cli):
    viejo = entrada(monto=13000, moneda="ARS")
    sync(cli, cli.A, viejo)
    poner_cotizacion(oficial=2000, blue=2400, tarjeta=2600)
    nuevo = entrada(monto=13000, moneda="ARS")
    sync(cli, cli.A, nuevo)
    por_id = {g["client_id"]: g for g in cli.get("/api/gastos", headers=cli.A).json()["gastos"]}
    assert por_id[viejo["client_id"]]["monto_usd"] == 10.0 and por_id[viejo["client_id"]]["cotizacion_tarjeta"] == 1300
    assert por_id[nuevo["client_id"]]["monto_usd"] == 5.0 and por_id[nuevo["client_id"]]["cotizacion_tarjeta"] == 2600


def test_editar_el_monto_usa_la_cotizacion_congelada_del_gasto(cli):
    g = entrada(monto=13000, moneda="ARS")
    sync(cli, cli.A, g)
    poner_cotizacion(tarjeta=2600)
    r = sync(cli, cli.A, {**g, "monto": 26000, "updated_at": (T0 + timedelta(hours=1)).isoformat()})
    assert r["cambios"][0]["monto_usd"] == 20.0 and r["cambios"][0]["cotizacion_tarjeta"] == 1300


def test_reenviar_lo_mismo_no_duplica(cli):
    g = entrada()
    sync(cli, cli.A, g)
    r = sync(cli, cli.A, g)
    assert r["aplicados"] == [g["client_id"]]
    assert len(cli.get("/api/gastos", headers=cli.A).json()["gastos"]) == 1


def test_gana_el_updated_at_mas_nuevo_y_el_perdedor_vuelve_con_la_version_del_servidor(cli):
    g = entrada(monto=10)
    sync(cli, cli.A, g)
    viejo = sync(cli, cli.A, {**g, "monto": 99, "updated_at": (T0 - timedelta(hours=1)).isoformat()},
                 desde=datetime.now(UTC).isoformat())
    assert viejo["aplicados"] == []
    assert [c["monto"] for c in viejo["cambios"]] == [10.0]  # llega aunque sea anterior a 'desde'
    nuevo = sync(cli, cli.A, {**g, "monto": 30, "updated_at": (T0 + timedelta(hours=1)).isoformat()})
    assert nuevo["aplicados"] == [g["client_id"]]
    assert cli.get("/api/gastos", headers=cli.A).json()["gastos"][0]["monto"] == 30.0


def test_un_reloj_adelantado_no_gana_para_siempre(cli):
    g = entrada()
    r = sync(cli, cli.A, {**g, "updated_at": "2099-01-01T00:00:00Z"})
    assert datetime.fromisoformat(r["cambios"][0]["updated_at"]) < datetime.now(UTC) + timedelta(hours=1)


def test_borrado_logico_sale_de_la_lista_y_de_los_totales_pero_viaja_en_el_sync(cli):
    g = entrada(monto=10)
    primero = sync(cli, cli.A, g)
    marca = (T0 + timedelta(hours=1)).isoformat()
    r = sync(cli, cli.A, {**g, "updated_at": marca, "deleted_at": marca}, desde=primero["ahora"])
    assert r["cambios"][0]["deleted_at"] is not None
    listado = cli.get("/api/gastos", headers=cli.A).json()
    assert listado["gastos"] == [] and listado["totales"]["usd"] == 0
    with db.conn() as c:  # sigue en la base
        assert c.execute("SELECT count(*) AS n FROM gastos").fetchone()["n"] == 1


def test_sync_devuelve_solo_lo_modificado_desde(cli, monkeypatch):
    monkeypatch.setattr(gastos, "SOLAPAMIENTO", timedelta(0))
    primero = sync(cli, cli.A, entrada())
    assert len(primero["cambios"]) == 1
    assert sync(cli, cli.A, desde=primero["ahora"])["cambios"] == []
    otro = entrada()
    assert [c["client_id"] for c in sync(cli, cli.A, otro, desde=primero["ahora"])["cambios"]] == [otro["client_id"]]


def test_un_gasto_de_otro_dispositivo_llega_con_desde_nulo(cli):
    sync(cli, cli.A, entrada(), entrada())
    assert len(sync(cli, cli.A, desde=None)["cambios"]) == 2


def test_sync_acepta_a_lo_sumo_200_cambios(cli):
    r = cli.post("/api/gastos/sync", headers=cli.A, json={"cambios": [entrada() for _ in range(201)], "desde": None})
    assert r.status_code == 422


def test_sync_tiene_limite_de_pedidos(cli, monkeypatch):
    monkeypatch.setattr(gastos_api, "_syncs", limites.Limite(2, 60))
    sync(cli, cli.A)
    sync(cli, cli.A)
    assert cli.post("/api/gastos/sync", headers=cli.A, json={"cambios": [], "desde": None}).status_code == 429


# ---------- aislamiento ----------

def test_cada_persona_ve_solo_sus_gastos_y_su_foto(cli):
    g = entrada(reintegrable=True, compartido=True)
    sync(cli, cli.A, g)
    assert foto(cli, cli.A, g["client_id"]).status_code == 200
    assert cli.get("/api/gastos", headers=cli.B).json()["gastos"] == []
    assert cli.get("/api/gastos/compartidos", headers=cli.B).json()["gastos"] == []
    assert cli.get(f"/api/gastos/{g['client_id']}/foto", headers=cli.B).status_code == 404
    assert foto(cli, cli.B, g["client_id"]).status_code == 404
    assert "comida" not in cli.get("/api/gastos/export.csv", headers=cli.B).text
    assert cli.get(f"/api/gastos/{g['client_id']}/foto", headers=cli.A).status_code == 200


def test_el_mismo_client_id_en_dos_cuentas_son_dos_gastos_y_B_no_pisa_a_A(cli):
    g = entrada(monto=10)
    sync(cli, cli.A, g)
    sync(cli, cli.B, {**g, "monto": 77, "updated_at": (T0 + timedelta(days=1)).isoformat()})
    assert cli.get("/api/gastos", headers=cli.A).json()["gastos"][0]["monto"] == 10.0
    assert cli.get("/api/gastos", headers=cli.B).json()["gastos"][0]["monto"] == 77.0


@pytest.mark.parametrize(("metodo", "ruta"), [("get", "/api/gastos"), ("get", "/api/gastos/cotizacion"),
                                              ("post", "/api/gastos/sync"), ("get", "/api/gastos/export.csv"),
                                              ("get", "/api/gastos/compartidos"), ("put", "/api/gastos/presupuesto"),
                                              ("get", f"/api/gastos/{uuid.uuid4()}/foto")])
def test_todo_exige_sesion(cli, metodo, ruta):
    assert getattr(cli, metodo)(ruta).status_code == 401


# ---------- lectura y totales ----------

def test_totales_por_dia_y_por_categoria_en_usd(cli):
    sync(cli, cli.A,
         entrada(monto=10, fecha="2026-12-01", categoria="comida"),
         entrada(monto=13000, moneda="ARS", fecha="2026-12-01", categoria="comida"),
         entrada(monto=5, fecha="2026-12-02", categoria="shows"))
    t = cli.get("/api/gastos", headers=cli.A).json()["totales"]
    assert t == {"usd": 25.0, "por_categoria": {"comida": 20.0, "shows": 5.0},
                 "por_dia": {"2026-12-01": 20.0, "2026-12-02": 5.0}}


def test_el_listado_se_filtra_por_rango_de_fechas(cli):
    sync(cli, cli.A, entrada(fecha="2026-12-01"), entrada(fecha="2026-12-03"), entrada(fecha="2026-12-05"))
    r = cli.get("/api/gastos", headers=cli.A, params={"desde": "2026-12-02", "hasta": "2026-12-04"}).json()
    assert [g["fecha"] for g in r["gastos"]] == ["2026-12-03"] and r["totales"]["usd"] == 10.0


def test_cotizacion_actual(cli):
    r = cli.get("/api/gastos/cotizacion", headers=cli.A).json()
    assert (r["oficial"], r["blue"], r["tarjeta"]) == (1000, 1200, 1300) and r["at"]


def test_presupuesto_se_guarda_y_viaja_en_el_listado(cli):
    assert cli.get("/api/gastos", headers=cli.A).json()["presupuesto"] == {"total_usd": None, "diario_usd": None,
                                                                          "por_categoria": {}}
    cuerpo = {"total_usd": 1500, "diario_usd": 200, "por_categoria": {"comida": 400.5}}
    assert cli.put("/api/gastos/presupuesto", headers=cli.A, json=cuerpo).status_code == 200
    assert cli.get("/api/gastos", headers=cli.A).json()["presupuesto"] == cuerpo
    assert cli.get("/api/gastos", headers=cli.B).json()["presupuesto"]["total_usd"] is None


@pytest.mark.parametrize("cuerpo", [{"total_usd": -1, "diario_usd": 1, "por_categoria": {}},
                                    {"total_usd": 1, "diario_usd": 1, "por_categoria": {"joyas": 5}},
                                    {"total_usd": 1, "diario_usd": 1, "por_categoria": {"comida": -5}}])
def test_presupuesto_invalido(cli, cuerpo):
    assert cli.put("/api/gastos/presupuesto", headers=cli.A, json=cuerpo).status_code == 422


def test_compartidos_lista_solo_los_marcados_y_no_borrados_con_su_total(cli):
    quitado = entrada(compartido=True)
    sync(cli, cli.A, entrada(monto=10, compartido=True), entrada(monto=5, compartido=False), quitado)
    borrar(cli, quitado)
    r = cli.get("/api/gastos/compartidos", headers=cli.A).json()
    assert len(r["gastos"]) == 1 and r["total_usd"] == 10.0


# ---------- export ----------

def test_el_csv_trae_solo_reintegrables_no_borrados_con_bom_y_link_absoluto(cli):
    con_foto = entrada(monto=13000, moneda="ARS", categoria="transporte", nota="Uber al Venetian", reintegrable=True)
    quitado = entrada(reintegrable=True, nota="borrado")
    sync(cli, cli.A, con_foto, quitado, entrada(nota="personal", reintegrable=False))
    borrar(cli, quitado)
    foto(cli, cli.A, con_foto["client_id"])
    r = cli.get("/api/gastos/export.csv", headers=cli.A)
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    assert r.content.startswith(b"\xef\xbb\xbf")
    filas = r.content.decode("utf-8-sig").splitlines()
    assert len(filas) == 2  # encabezado + el único reintegrable vigente
    *resto, link = filas[1].split(";")
    assert resto == ["2026-12-01", "transporte - Uber al Venetian", "ARS", "13000,00", "10,00", "1300,0000"]
    assert link.startswith("http://testserver/api/gastos/foto-firmada/")


def test_el_csv_neutraliza_celdas_que_excel_leeria_como_formula(cli):
    sync(cli, cli.A, entrada(nota='=HYPERLINK("http://x")', reintegrable=True))
    texto = cli.get("/api/gastos/export.csv", headers=cli.A).content.decode("utf-8-sig")
    concepto = list(csv.reader(io.StringIO(texto), delimiter=";"))[1][1]
    assert concepto == 'comida - =HYPERLINK("http://x")'  # arranca con la categoría: nunca con = + - @
    assert gastos._celda("=1+1") == "'=1+1" and gastos._celda("-5") == "'-5" and gastos._celda("comida") == "comida"


# ---------- validaciones ----------

@pytest.mark.parametrize("cambio", [{"monto": -5}, {"monto": 0}, {"monto": "abc"}, {"monto": 0.004}, {"monto": 1e12},
                                    {"moneda": "EUR"}, {"categoria": "joyas"}, {"fecha": "2026-13-45"},
                                    {"nota": "x" * 501}, {"client_id": "no-es-uuid"},
                                    {"updated_at": "2026-12-01T10:00:00"}],  # sin zona horaria
                         ids=["negativo", "cero", "texto", "menos-de-un-centavo", "enorme", "moneda", "categoria",
                              "fecha", "nota-larga", "client_id", "sin-zona"])
def test_sync_rechaza_gastos_invalidos(cli, cambio):
    r = cli.post("/api/gastos/sync", headers=cli.A, json={"cambios": [entrada(**cambio)], "desde": None})
    assert r.status_code == 200 and r.json()["cambios"] == [] and len(r.json()["rechazados"]) == 1
    assert cli.get("/api/gastos", headers=cli.A).json()["gastos"] == []


def test_el_monto_se_redondea_a_centavos(cli):
    assert sync(cli, cli.A, entrada(monto=12.345))["cambios"][0]["monto"] == 12.35


def test_los_campos_que_decide_el_servidor_se_ignoran(cli):
    r = sync(cli, cli.A, entrada(monto_usd=999, cotizacion_tarjeta=1, foto_url="/x"))["cambios"][0]
    assert r["monto_usd"] == 10.0 and r["cotizacion_tarjeta"] == 1300 and r["foto_url"] is None


# ---------- fotos ----------

@pytest.mark.parametrize(("datos", "tipo"), [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")])
def test_la_foto_se_guarda_y_vuelve_igual(cli, datos, tipo):
    g = entrada()
    sync(cli, cli.A, g)
    r = foto(cli, cli.A, g["client_id"], datos, tipo)
    assert r.status_code == 200 and r.json()["foto_url"].startswith(f"/api/gastos/{g['client_id']}/foto?v=")
    vuelta = cli.get(r.json()["foto_url"], headers=cli.A)
    assert vuelta.content == datos and vuelta.headers["content-type"] == tipo
    assert vuelta.headers["x-content-type-options"] == "nosniff"
    assert cli.get("/api/gastos", headers=cli.A).json()["gastos"][0]["foto_url"] == r.json()["foto_url"]


def test_la_clave_del_objeto_sale_del_usuario_y_el_client_id_no_del_nombre_del_cliente(cli, tmp_path):
    g = entrada()
    sync(cli, cli.A, g)
    foto(cli, cli.A, g["client_id"])
    assert [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()] == [
        f"tickets/{TEST_USER}/{g['client_id']}.jpg"]


def test_cambiar_la_foto_por_otro_formato_borra_la_anterior(cli, tmp_path):
    g = entrada()
    sync(cli, cli.A, g)
    foto(cli, cli.A, g["client_id"], JPEG, "image/jpeg")
    foto(cli, cli.A, g["client_id"], PNG, "image/png")
    assert [p.suffix for p in tmp_path.rglob("*") if p.is_file()] == [".png"]


def test_sincronizar_despues_no_pisa_la_foto(cli):
    g = entrada()
    sync(cli, cli.A, g)
    foto(cli, cli.A, g["client_id"])
    r = sync(cli, cli.A, {**g, "monto": 11, "updated_at": (T0 + timedelta(hours=1)).isoformat()})
    assert r["cambios"][0]["foto_url"].startswith(f"/api/gastos/{g['client_id']}/foto?v=")


@pytest.mark.parametrize(("datos", "tipo"), [(b"esto es texto, no una imagen", "image/jpeg"),
                                             (b"GIF89a" + b"\x00" * 20, "image/gif"),
                                             (PNG, "image/jpeg"),                       # declara una cosa y es otra
                                             (b"<html><script>1</script>", "image/png")],
                         ids=["texto", "gif", "tipo-no-coincide", "html"])
def test_la_foto_que_no_es_imagen_se_rechaza_por_sus_bytes(cli, datos, tipo):
    g = entrada()
    sync(cli, cli.A, g)
    assert foto(cli, cli.A, g["client_id"], datos, tipo).status_code == 415
    assert cli.get(f"/api/gastos/{g['client_id']}/foto", headers=cli.A).status_code == 404


def test_la_foto_de_mas_de_2_mb_se_rechaza(cli):
    g = entrada()
    sync(cli, cli.A, g)
    grande = JPEG + b"\x00" * (2 * 1024 * 1024)
    assert foto(cli, cli.A, g["client_id"], grande).status_code == 413
    justo = JPEG + b"\x00" * (2 * 1024 * 1024 - len(JPEG))
    assert foto(cli, cli.A, g["client_id"], justo).status_code == 200


def test_la_foto_sin_el_campo_foto_es_un_error_claro(cli):
    g = entrada()
    sync(cli, cli.A, g)
    assert foto(cli, cli.A, g["client_id"], campo="archivo").status_code == 422
    assert cli.post(f"/api/gastos/{g['client_id']}/foto", headers=cli.A, content=JPEG).status_code == 422


def test_foto_de_un_gasto_que_no_existe_o_esta_borrado(cli):
    assert foto(cli, cli.A, uuid.uuid4()).status_code == 404
    g = entrada()
    sync(cli, cli.A, g)
    borrar(cli, g)
    assert foto(cli, cli.A, g["client_id"]).status_code == 404


def test_si_el_almacen_falla_responde_502_y_no_guarda_la_clave(cli, monkeypatch):
    class Roto:
        def guardar(self, *args):
            raise OSError("disco lleno")

    monkeypatch.setattr("app.tickets_almacen.obtener", lambda: Roto())
    g = entrada()
    sync(cli, cli.A, g)
    assert foto(cli, cli.A, g["client_id"]).status_code == 502
    assert cli.get("/api/gastos", headers=cli.A).json()["gastos"][0]["foto_url"] is None


# ---------- links firmados a la foto (los del CSV de reintegros) ----------

def _con_foto(cli, **kw):
    g = entrada(reintegrable=True, **kw)
    sync(cli, cli.A, g)
    foto(cli, cli.A, g["client_id"])
    return g


def _link_del_csv(cli):
    texto = cli.get("/api/gastos/export.csv", headers=cli.A).content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(texto), delimiter=";"))[1][-1].removeprefix("http://testserver")


def test_el_link_del_csv_abre_la_foto_sin_sesion(cli):
    _con_foto(cli)
    r = cli.get(_link_del_csv(cli))  # sin Authorization
    assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_el_link_vence_a_los_90_dias_por_defecto(cli, monkeypatch):
    _con_foto(cli)
    ruta = _link_del_csv(cli)
    ahora = gastos_links._ahora()
    monkeypatch.setattr(gastos_links, "_ahora", lambda: ahora + 29 * 86400)
    assert cli.get(ruta).status_code == 200
    monkeypatch.setattr(gastos_links, "_ahora", lambda: ahora + 31 * 86400)
    assert cli.get(ruta).status_code == 404


def test_el_vencimiento_es_configurable(cli, monkeypatch):
    _con_foto(cli)
    monkeypatch.setattr(config, "FOTOS_LINK_DIAS", 1)
    ruta = _link_del_csv(cli)
    ahora = gastos_links._ahora()
    monkeypatch.setattr(gastos_links, "_ahora", lambda: ahora + 2 * 86400)
    assert cli.get(ruta).status_code == 404


@pytest.mark.parametrize("adulterar", [
    lambda t: t[:-2] + ("AA" if t[-2:] != "AA" else "BB"),                # firma distinta
    lambda t: t.split(".")[0] + "." + t.split(".")[1][::-1],              # firma al revés
    lambda t: t.split(".")[0],                                            # sin firma
    lambda t: "." + t.split(".")[1],                                      # sin payload
    lambda t: "basura",
    lambda t: "",
], ids=["firma", "firma-al-reves", "sin-firma", "sin-payload", "basura", "vacio"])
def test_un_token_adulterado_da_404(cli, adulterar):
    _con_foto(cli)
    token = _link_del_csv(cli).rsplit("/", 1)[1]
    assert cli.get(f"/api/gastos/foto-firmada/{adulterar(token)}").status_code == 404


def test_cambiar_el_payload_para_apuntar_a_otro_usuario_o_gasto_invalida_la_firma(cli):
    g = _con_foto(cli)
    token = _link_del_csv(cli).rsplit("/", 1)[1]
    firma = token.split(".")[1]
    for otro in (f"{TEST_ADMIN}\n{g['client_id']}\n9999999999", f"{TEST_USER}\n{uuid.uuid4()}\n9999999999"):
        falso = f"{gastos_links._b64(otro.encode())}.{firma}"
        assert cli.get(f"/api/gastos/foto-firmada/{falso}").status_code == 404


def test_un_token_firmado_con_otra_clave_no_vale(cli, monkeypatch):
    g = _con_foto(cli)
    monkeypatch.setattr(config, "FOTOS_LINK_SECRET", "otra-clave")
    ajeno = gastos_links.firmar(TEST_USER, g["client_id"])
    monkeypatch.setattr(config, "FOTOS_LINK_SECRET", "")
    assert cli.get(f"/api/gastos/foto-firmada/{ajeno}").status_code == 404


def test_el_link_de_un_gasto_borrado_da_404(cli):
    g = _con_foto(cli)
    ruta = _link_del_csv(cli)
    assert cli.get(ruta).status_code == 200
    borrar(cli, g)
    assert cli.get(ruta).status_code == 404


def test_un_gasto_sin_foto_da_404(cli):
    g = entrada()
    sync(cli, cli.A, g)
    assert cli.get(gastos_links.ruta_firmada(TEST_USER, g["client_id"])).status_code == 404


def test_no_se_pueden_enumerar_fotos_de_otros(cli):
    g = _con_foto(cli)
    # Ni siquiera un token bien firmado para otra persona devuelve la foto de A: se busca por (usuario, client_id).
    assert cli.get(gastos_links.ruta_firmada(TEST_ADMIN, g["client_id"])).status_code == 404
    assert cli.get(f"/api/gastos/foto-firmada/{uuid.uuid4()}").status_code == 404
    assert cli.get(f"/api/gastos/{g['client_id']}/foto").status_code == 401  # la ruta con sesión sigue cerrada


def test_sin_secreto_propio_la_clave_se_deriva_de_la_base_y_con_secreto_cambia(monkeypatch):
    monkeypatch.setattr(config, "FOTOS_LINK_SECRET", "")
    derivada = gastos_links._clave()
    assert gastos_links.verificar(gastos_links.firmar("ale", uuid.uuid4()))[0] == "ale"
    monkeypatch.setattr(config, "FOTOS_LINK_SECRET", "propio")
    assert gastos_links._clave() != derivada
    monkeypatch.setattr(config, "FOTOS_LINK_SECRET", "")
    monkeypatch.setattr(config, "DATABASE_URL", "")
    with pytest.raises(RuntimeError):
        gastos_links.firmar("ale", uuid.uuid4())


# ---------- sync: cursor, tope, rechazos por gasto ----------

def _fecha(texto):
    return datetime.fromisoformat(texto)


def test_el_cursor_vuelve_con_solapamiento_y_no_pierde_una_transaccion_concurrente(cli):
    r = sync(cli, cli.A, entrada())
    ahora = _fecha(r["ahora"])
    assert ahora <= datetime.now(UTC) - gastos.SOLAPAMIENTO + timedelta(seconds=1)
    # Una transacción que empezó antes del cierre y confirmó después deja su sincronizado_at por detrás del cursor.
    concurrente = entrada()
    sync(cli, cli.B, concurrente)
    with db.conn() as c:
        c.execute("UPDATE gastos SET sincronizado_at = %s, username = %s WHERE client_id = %s",
                  (ahora + timedelta(seconds=2), TEST_USER, concurrente["client_id"]))
    visto = sync(cli, cli.A, desde=r["ahora"])
    assert concurrente["client_id"] in [c["client_id"] for c in visto["cambios"]]


def test_reenviar_con_el_solapamiento_es_idempotente(cli):
    g = entrada()
    r = sync(cli, cli.A, g)
    otra = sync(cli, cli.A, g, desde=r["ahora"])
    assert [c["client_id"] for c in otra["cambios"]] == [g["client_id"]]
    assert len(cli.get("/api/gastos", headers=cli.A).json()["gastos"]) == 1


def test_sin_corte_hay_mas_es_falso(cli):
    r = sync(cli, cli.A, entrada())
    assert r["hay_mas"] is False and r["rechazados"] == []


def test_cuando_se_corta_por_el_tope_hay_mas_y_el_cursor_es_el_de_la_ultima_fila(cli, monkeypatch):
    monkeypatch.setattr(gastos, "CAMBIOS_MAX_RESPUESTA", 3)
    ids = []
    for _ in range(5):
        g = entrada()
        ids.append(g["client_id"])
        sync(cli, cli.A, g)
    primera = sync(cli, cli.A)
    assert primera["hay_mas"] is True and len(primera["cambios"]) == 3
    with db.conn() as c:
        ultimo = c.execute("SELECT sincronizado_at FROM gastos WHERE client_id = %s",
                           (primera["cambios"][-1]["client_id"],)).fetchone()["sincronizado_at"]
    assert _fecha(primera["ahora"]) == ultimo
    recibidos = {c["client_id"] for c in primera["cambios"]}
    pagina = primera
    for _ in range(5):  # el cliente repite enseguida con desde=ahora hasta que no haya más
        if not pagina["hay_mas"]:
            break
        pagina = sync(cli, cli.A, desde=pagina["ahora"])
        recibidos |= {c["client_id"] for c in pagina["cambios"]}
    assert pagina["hay_mas"] is False and recibidos == set(ids)


def test_un_gasto_invalido_no_tumba_al_resto_y_se_informa_por_client_id(cli):
    bueno = entrada()
    malo = entrada(monto=-5)
    r = cli.post("/api/gastos/sync", headers=cli.A, json={
        "cambios": [bueno, malo, "no soy un gasto", {"monto": 3}, entrada(categoria="joyas")], "desde": None})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert [c["client_id"] for c in cuerpo["cambios"]] == [bueno["client_id"]]
    assert cuerpo["aplicados"] == [bueno["client_id"]]
    rechazados = cuerpo["rechazados"]
    assert len(rechazados) == 4
    assert rechazados[0]["client_id"] == malo["client_id"] and rechazados[0]["error"]
    assert rechazados[1]["client_id"] is None and rechazados[2]["client_id"] is None
    assert all(isinstance(x["error"], str) and x["error"] for x in rechazados)
    assert len(cli.get("/api/gastos", headers=cli.A).json()["gastos"]) == 1


def test_el_client_id_no_uuid_de_un_rechazado_vuelve_tal_cual_o_nulo(cli):
    r = cli.post("/api/gastos/sync", headers=cli.A, json={
        "cambios": [entrada(client_id="no-es-uuid"), entrada(client_id=7)], "desde": None})
    assert [x["client_id"] for x in r.json()["rechazados"]] == ["no-es-uuid", None]


def test_los_mensajes_de_rechazo_estan_en_castellano_y_no_filtran_el_valor(cli):
    r = cli.post("/api/gastos/sync", headers=cli.A, json={"cambios": [entrada(monto="secreto-abc")], "desde": None})
    error = r.json()["rechazados"][0]["error"]
    assert "monto" in error.lower() and "secreto-abc" not in error


# ---------- cotización congelada: a la fecha del gasto y marca de estimada ----------

def _cotizacion_en(at, oficial, tarjeta):
    with db.conn() as c:
        c.execute("INSERT INTO cotizaciones (at, oficial, blue, tarjeta) VALUES (%s, %s, %s, %s)",
                  (at, oficial, oficial + 100, tarjeta))


def test_el_gasto_congela_la_cotizacion_vigente_a_su_fecha_no_la_del_dia_que_se_sincroniza(cli):
    with db.conn() as c:
        c.execute("DELETE FROM cotizaciones")
    ahora = datetime.now(UTC)
    _cotizacion_en(ahora - timedelta(days=7), 1000, 1300)   # la del día del gasto
    _cotizacion_en(ahora - timedelta(days=5), 1100, 1430)   # la del día que se sincroniza
    del_martes = sync(cli, cli.A, entrada(fecha=(ahora.date() - timedelta(days=7)).isoformat(), moneda="ARS",
                                          monto=1300))["cambios"][0]
    assert del_martes["cotizacion_tarjeta"] == 1300 and del_martes["monto_usd"] == 1
    de_hoy = sync(cli, cli.A, entrada(fecha=ahora.date().isoformat(), moneda="ARS", monto=1430))["cambios"][-1]
    assert de_hoy["cotizacion_tarjeta"] == 1430


def test_con_la_tabla_vacia_se_usa_el_respaldo_y_el_gasto_queda_marcado(cli):
    with db.conn() as c:
        c.execute("DELETE FROM cotizaciones")
    g = sync(cli, cli.A, entrada())["cambios"][0]
    assert g["cotizacion_tarjeta"] == TARJETA_RESPALDO and g["cotizacion_estimada"] is True


def test_una_cotizacion_fresca_no_marca_el_gasto(cli):
    assert sync(cli, cli.A, entrada())["cambios"][0]["cotizacion_estimada"] is False


def test_una_cotizacion_de_mas_de_48_horas_marca_el_gasto(cli):
    with db.conn() as c:
        c.execute("DELETE FROM cotizaciones")
    _cotizacion_en(datetime.now(UTC) - timedelta(hours=60), 1000, 1300)
    assert sync(cli, cli.A, entrada())["cambios"][0]["cotizacion_estimada"] is True


def test_el_gasto_ya_guardado_conserva_su_marca_al_editarlo(cli):
    with db.conn() as c:
        c.execute("DELETE FROM cotizaciones")
    g = entrada()
    sync(cli, cli.A, g)
    poner_cotizacion()
    r = sync(cli, cli.A, {**g, "monto": 11, "updated_at": (T0 + timedelta(hours=1)).isoformat()})
    assert r["cambios"][0]["cotizacion_estimada"] is True and r["cambios"][0]["cotizacion_tarjeta"] == TARJETA_RESPALDO


def test_la_cotizacion_informa_su_antiguedad_y_si_es_de_respaldo(cli):
    hoy = cli.get("/api/gastos/cotizacion", headers=cli.A).json()
    assert hoy["es_respaldo"] is False and isinstance(hoy["edad_min"], int) and 0 <= hoy["edad_min"] < 5
    with db.conn() as c:
        c.execute("DELETE FROM cotizaciones")
    vacia = cli.get("/api/gastos/cotizacion", headers=cli.A).json()
    assert vacia["es_respaldo"] is True and vacia["edad_min"] is None and vacia["tarjeta"] == TARJETA_RESPALDO


# ---------- fotos: ?v=, borrado y orden de reemplazo ----------

def test_la_url_de_la_foto_cambia_al_reemplazarla(cli):
    g = entrada()
    sync(cli, cli.A, g)
    primera = foto(cli, cli.A, g["client_id"], JPEG).json()["foto_url"]
    segunda = foto(cli, cli.A, g["client_id"], JPEG + b"x").json()["foto_url"]
    assert primera.startswith(f"/api/gastos/{g['client_id']}/foto?v=") and primera != segunda
    assert cli.get("/api/gastos", headers=cli.A).json()["gastos"][0]["foto_url"] == segunda
    assert cli.get(segunda, headers=cli.A).status_code == 200


def test_borrar_el_gasto_borra_la_foto_del_almacen(cli, tmp_path):
    g = entrada()
    sync(cli, cli.A, g)
    foto(cli, cli.A, g["client_id"])
    borrar(cli, g)
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_si_el_almacen_falla_al_borrar_el_gasto_se_borra_igual(cli, monkeypatch, caplog):
    g = entrada()
    sync(cli, cli.A, g)
    foto(cli, cli.A, g["client_id"])

    class Roto:
        def borrar(self, clave):
            raise OSError("bucket caído")

    monkeypatch.setattr("app.tickets_almacen.obtener", lambda: Roto())
    r = borrar(cli, g)
    assert r["cambios"][0]["deleted_at"] is not None
    assert cli.get("/api/gastos", headers=cli.A).json()["gastos"] == []
    assert "bucket caído" in caplog.text


def test_al_reemplazar_si_falla_borrar_la_vieja_la_nueva_queda_anotada(cli, monkeypatch, tmp_path):
    g = entrada()
    sync(cli, cli.A, g)
    foto(cli, cli.A, g["client_id"], JPEG, "image/jpeg")
    original = tickets_almacen.AlmacenLocal.borrar

    def borrar_roto(self, clave):
        raise OSError("sin permiso")

    monkeypatch.setattr(tickets_almacen.AlmacenLocal, "borrar", borrar_roto)
    r = foto(cli, cli.A, g["client_id"], PNG, "image/png")
    monkeypatch.setattr(tickets_almacen.AlmacenLocal, "borrar", original)
    assert r.status_code == 200
    vuelta = cli.get(r.json()["foto_url"], headers=cli.A)
    assert vuelta.status_code == 200 and vuelta.content == PNG


def test_si_falla_guardar_la_nueva_la_vieja_sigue_en_pie(cli, monkeypatch, tmp_path):
    g = entrada()
    sync(cli, cli.A, g)
    foto(cli, cli.A, g["client_id"], JPEG, "image/jpeg")
    monkeypatch.setattr(tickets_almacen.AlmacenLocal, "guardar", lambda *a: (_ for _ in ()).throw(OSError("lleno")))
    assert foto(cli, cli.A, g["client_id"], PNG, "image/png").status_code == 502
    assert cli.get(f"/api/gastos/{g['client_id']}/foto", headers=cli.A).content == JPEG


def test_si_el_objeto_no_esta_en_el_almacen_se_loguea_claro(cli, caplog, tmp_path):
    g = entrada()
    sync(cli, cli.A, g)
    foto(cli, cli.A, g["client_id"])
    for p in tmp_path.rglob("*.jpg"):
        p.unlink()
    assert cli.get(f"/api/gastos/{g['client_id']}/foto", headers=cli.A).status_code == 404
    assert any(x.levelname == "ERROR" and str(g["client_id"]) in x.getMessage() for x in caplog.records)


# ---------- links firmados ----------

def test_los_links_duran_30_dias_por_defecto():
    assert config.FOTOS_LINK_DIAS == 30


def test_en_produccion_sin_fotos_link_secret_avisa_en_el_log(monkeypatch, caplog):
    monkeypatch.setattr(config, "EN_PRODUCCION", True)
    monkeypatch.setattr(config, "FOTOS_LINK_SECRET", "")
    gastos_links.verificar_configuracion()
    assert any(x.levelname == "WARNING" and "FOTOS_LINK_SECRET" in x.getMessage() for x in caplog.records)


def test_con_secreto_o_fuera_de_produccion_no_avisa(monkeypatch, caplog):
    monkeypatch.setattr(config, "EN_PRODUCCION", True)
    monkeypatch.setattr(config, "FOTOS_LINK_SECRET", "propio")
    gastos_links.verificar_configuracion()
    monkeypatch.setattr(config, "EN_PRODUCCION", False)
    monkeypatch.setattr(config, "FOTOS_LINK_SECRET", "")
    gastos_links.verificar_configuracion()
    assert "FOTOS_LINK_SECRET" not in caplog.text

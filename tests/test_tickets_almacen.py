"""Almacén de fotos de ticket: disco local, S3 con firma SigV4 (sin red: httpx con transporte falso) y elección según config."""
from datetime import UTC, datetime

import httpx
import pytest

from app import config, tickets_almacen
from app.tickets_almacen import AlmacenLocal, AlmacenS3

ID = "7b0c3a52-6f6f-4c1e-9b1d-0a5d3c2e9f10"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def test_la_clave_incluye_usuario_y_client_id_y_nunca_un_nombre_de_cliente():
    assert tickets_almacen.clave_foto("ale", ID, "image/jpeg") == f"tickets/ale/{ID}.jpg"


def test_un_usuario_con_caracteres_raros_no_arma_otra_ruta():
    clave = tickets_almacen.clave_foto("../../etc", ID, "image/png")
    assert clave.startswith("tickets/") and "../" not in clave and clave.count("/") == 2


def test_local_guarda_lee_y_borra(tmp_path):
    almacen = AlmacenLocal(tmp_path)
    clave = tickets_almacen.clave_foto("ale", ID, "image/jpeg")
    almacen.guardar(clave, JPEG, "image/jpeg")
    assert almacen.leer(clave) == JPEG
    almacen.borrar(clave)
    assert almacen.leer(clave) is None


def test_local_rechaza_claves_que_se_salen_del_directorio(tmp_path):
    with pytest.raises(ValueError):
        AlmacenLocal(tmp_path).guardar("../afuera.jpg", JPEG, "image/jpeg")


def test_firma_sigv4_coincide_con_el_ejemplo_de_la_documentacion_de_aws():
    # GET Object con Range de la documentación de SigV4 para S3 (claves de ejemplo públicas de AWS).
    headers = tickets_almacen.firmar(
        "GET", "examplebucket.s3.amazonaws.com", "/test.txt", {"Range": "bytes=0-9"},
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        datetime(2013, 5, 24, tzinfo=UTC), "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "us-east-1")
    assert headers["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")


def _s3(manejador):
    return AlmacenS3("https://storage.example.test", "bucket-t", "KEYID", "SECRETO", "auto",
                     httpx.Client(transport=httpx.MockTransport(manejador)))


def test_s3_guarda_con_pedido_firmado_a_la_url_del_bucket():
    vistos = []

    def manejador(req: httpx.Request):
        vistos.append(req)
        return httpx.Response(200)

    _s3(manejador).guardar(f"tickets/ale/{ID}.jpg", JPEG, "image/jpeg")
    req = vistos[0]
    assert req.method == "PUT"
    assert str(req.url) == f"https://bucket-t.storage.example.test/tickets/ale/{ID}.jpg"
    assert req.content == JPEG
    assert req.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=KEYID/")
    assert "content-type" in req.headers["authorization"] and "x-amz-content-sha256" in req.headers


def test_s3_lee_y_devuelve_none_si_no_existe():
    assert _s3(lambda r: httpx.Response(200, content=JPEG)).leer("k.jpg") == JPEG
    assert _s3(lambda r: httpx.Response(404)).leer("k.jpg") is None


def test_s3_propaga_los_errores_de_permisos():
    with pytest.raises(httpx.HTTPStatusError):
        _s3(lambda r: httpx.Response(403)).guardar("k.jpg", JPEG, "image/jpeg")


def test_s3_borrar_tolera_que_ya_no_este():
    _s3(lambda r: httpx.Response(404)).borrar("k.jpg")


def test_obtener_usa_disco_sin_variables_y_s3_con_las_cinco(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TICKETS_DIR", tmp_path)
    for nombre in ("ENDPOINT", "BUCKET", "KEY_ID", "SECRET", "REGION"):
        monkeypatch.setattr(config, f"TICKETS_S3_{nombre}", "")
    assert isinstance(tickets_almacen.obtener(), AlmacenLocal)
    monkeypatch.setattr(tickets_almacen, "_s3", None)
    for nombre, valor in (("ENDPOINT", "https://s3.example.test"), ("BUCKET", "b"), ("KEY_ID", "k"),
                          ("SECRET", "s"), ("REGION", "auto")):
        monkeypatch.setattr(config, f"TICKETS_S3_{nombre}", valor)
    assert isinstance(tickets_almacen.obtener(), AlmacenS3)
    monkeypatch.setattr(config, "TICKETS_S3_SECRET", "")  # falta una: vuelve al disco
    assert isinstance(tickets_almacen.obtener(), AlmacenLocal)

"""Compresión gzip de las respuestas: sí para lo grande y comprimible, no para lo chico ni lo ya comprimido."""
import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from app import config
from app.main import GzipSelectivo, app

mini = FastAPI()
mini.add_middleware(GzipSelectivo)


@mini.get("/_test/json-grande")
def _json_grande():
    return {"items": [{"titulo": "Charla de ejemplo", "n": i} for i in range(200)]}


@mini.get("/_test/json-chico")
def _json_chico():
    return {"ok": True}


@mini.get("/_test/audio.mp3")
def _audio():
    return Response(b"\x00" * 5000, media_type="audio/mpeg")


@pytest.fixture(scope="module")
def c():
    return TestClient(mini)


@pytest.fixture(scope="module")
def pwa():
    # Sin `with`: no corre el lifespan, estos pedidos no tocan la base.
    return TestClient(app)


def test_json_grande_sale_con_gzip(c):
    r = c.get("/_test/json-grande", headers={"Accept-Encoding": "gzip"})

    assert r.headers["content-encoding"] == "gzip"
    assert len(r.json()["items"]) == 200  # el cliente lo descomprime solo
    assert "Accept-Encoding" in r.headers["vary"]


def test_json_chico_no_se_comprime(c):
    r = c.get("/_test/json-chico", headers={"Accept-Encoding": "gzip"})

    assert "content-encoding" not in r.headers
    assert r.json() == {"ok": True}


def test_sin_accept_encoding_gzip_no_se_comprime(c):
    r = c.get("/_test/json-grande", headers={"Accept-Encoding": "identity"})

    assert "content-encoding" not in r.headers


def test_audio_no_se_comprime_aunque_sea_grande(c):
    r = c.get("/_test/audio.mp3", headers={"Accept-Encoding": "gzip"})

    assert "content-encoding" not in r.headers
    assert len(r.content) == 5000


def test_pedido_con_range_no_se_comprime(c):
    r = c.get("/_test/json-grande", headers={"Accept-Encoding": "gzip", "Range": "bytes=0-"})

    assert "content-encoding" not in r.headers


def test_las_cabeceras_de_seguridad_siguen_en_la_respuesta_comprimida(pwa):
    r = pwa.get("/sw.js", headers={"Accept-Encoding": "gzip"})

    assert r.headers["content-encoding"] == "gzip"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in r.headers


def test_los_archivos_de_la_pwa_grandes_se_comprimen_y_las_imagenes_no(pwa):
    grandes = sorted(p for p in config.WEB_DIR.rglob("*.js") if p.stat().st_size > 2000)
    assert grandes, "la PWA debería tener algún JS de más de 2 KB"
    r = pwa.get("/" + grandes[0].relative_to(config.WEB_DIR).as_posix(), headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip"

    for imagen in sorted(config.WEB_DIR.rglob("*.png"))[:1]:
        r = pwa.get("/" + imagen.relative_to(config.WEB_DIR).as_posix(), headers={"Accept-Encoding": "gzip"})
        assert "content-encoding" not in r.headers

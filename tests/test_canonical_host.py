"""www.<dominio> redirige al dominio sin www (passkeys y Web Push quedan atados a un solo origen). No usa el catálogo."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.canonical_host import WwwRedirectMiddleware


def _cliente(base_url: str) -> TestClient:
    mini = FastAPI()

    @mini.api_route("/api/eco", methods=["GET", "POST"])
    def eco():
        return {"ok": True}

    mini.add_middleware(WwwRedirectMiddleware)
    return TestClient(mini, base_url=base_url, follow_redirects=False)


def test_www_redirige_al_dominio_sin_www_conservando_ruta_y_query():
    r = _cliente("https://www.reinventar.app").get("/api/eco?q=bedrock%20agents&dia=2")

    assert r.status_code == 308
    assert r.headers["location"] == "https://reinventar.app/api/eco?q=bedrock%20agents&dia=2"


def test_www_redirige_tambien_los_post_con_308():
    r = _cliente("https://WWW.reinventar.app").post("/api/eco", json={"x": 1})

    assert r.status_code == 308
    assert r.headers["location"] == "https://reinventar.app/api/eco"


def test_el_dominio_sin_www_no_redirige():
    r = _cliente("https://reinventar.app").get("/api/eco")

    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_el_dominio_de_railway_no_redirige():
    r = _cliente("https://reinventar-production.up.railway.app").get("/api/eco")

    assert r.status_code == 200

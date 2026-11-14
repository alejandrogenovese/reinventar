"""De punta a punta: detrás del proxy, la app ve el esquema https y arma sus URLs y orígenes con él.

La app no tiene hoy una ruta propia que redirija (el montaje de la PWA en "/" corta antes el redirect de barra final y
los directorios de web/ no tienen index.html), así que se usa una ruta de prueba sobre el app real, con todos sus
middlewares, que devuelve lo mismo que usan los redirects de Starlette y las passkeys.
"""
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app import passkey_api
from app.main import app


@pytest.fixture(scope="module")
def c():
    async def sonda(request: Request):
        rp_id, origen = passkey_api._rp(request)
        return {"url": str(request.url_for("sonda")), "origen": origen, "rp_id": rp_id, "ip": request.client.host}

    app.add_api_route("/_sonda_esquema", sonda, name="sonda", include_in_schema=False)
    ruta = app.router.routes.pop()
    app.router.routes.insert(0, ruta)  # antes del montaje de la PWA en "/", que se come todo lo demás
    try:
        with TestClient(app, base_url="http://app.test") as cliente:
            yield cliente
    finally:
        app.router.routes.remove(ruta)


def test_con_x_forwarded_proto_https_las_urls_y_el_origen_salen_en_https(c):
    r = c.get("/_sonda_esquema", headers={"X-Forwarded-Proto": "https"}).json()

    assert r["url"] == "https://app.test/_sonda_esquema"
    assert r["origen"] == "https://app.test"


def test_sin_x_forwarded_proto_se_conserva_el_esquema_del_pedido(c):
    r = c.get("/_sonda_esquema").json()

    assert r["url"] == "http://app.test/_sonda_esquema"


def test_un_x_forwarded_for_falso_no_cambia_la_ip_del_peer(c):
    sin_falso = c.get("/_sonda_esquema").json()["ip"]
    con_falso = c.get("/_sonda_esquema", headers={"X-Forwarded-For": "1.1.1.1"}).json()["ip"]

    assert con_falso == sin_falso != "1.1.1.1"

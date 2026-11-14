"""El esquema sale de X-Forwarded-Proto y la IP del cliente no se toca."""
import pytest

from app.esquema_proxy import EsquemaProxyMiddleware


async def _correr(headers, tipo="http", esquema_inicial="http"):
    visto = {}

    async def app(scope, receive, send):
        visto.update(scope)

    scope = {"type": tipo, "scheme": esquema_inicial, "client": ("100.64.0.9", 1), "headers": headers}
    await EsquemaProxyMiddleware(app)(scope, None, None)
    return visto


@pytest.mark.anyio
async def test_toma_https_del_x_forwarded_proto():
    visto = await _correr([(b"x-forwarded-proto", b"https")])

    assert visto["scheme"] == "https"


@pytest.mark.anyio
async def test_no_toca_la_ip_ni_aunque_venga_un_x_forwarded_for_falso():
    visto = await _correr([(b"x-forwarded-proto", b"https"), (b"x-forwarded-for", b"1.1.1.1")])

    assert visto["client"] == ("100.64.0.9", 1)


@pytest.mark.anyio
@pytest.mark.parametrize("valor", [b"ftp", b"", b"javascript"])
async def test_ignora_valores_que_no_son_http_ni_https(valor):
    visto = await _correr([(b"x-forwarded-proto", valor)])

    assert visto["scheme"] == "http"


@pytest.mark.anyio
async def test_websocket_usa_wss():
    visto = await _correr([(b"x-forwarded-proto", b"https")], tipo="websocket", esquema_inicial="ws")

    assert visto["scheme"] == "wss"

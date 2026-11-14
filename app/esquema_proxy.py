"""Esquema (http/https) detrás del proxy de Railway, sin confiar en ninguna IP.

uvicorn con --proxy-headers reescribe el esquema Y la IP del cliente desde los headers X-Forwarded-*; con
--forwarded-allow-ips='*' la IP sale del X-Forwarded-For que manda el cliente. Por eso el Dockerfile corre con
--no-proxy-headers y este middleware toma solo X-Forwarded-Proto (lo necesitan los redirects de Starlette, que arman
la URL con el esquema del pedido, y el origen de las passkeys cuando WEBAUTHN_ORIGIN no está definido).
Spoofear el esquema no da nada: no entra en ningún límite ni decisión de seguridad.
"""
ESQUEMAS = {b"http": "http", b"https": "https"}


class EsquemaProxyMiddleware:
    """ASGI puro: pone scope["scheme"] según X-Forwarded-Proto si es http o https; si no, lo deja como está."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            for nombre, valor in scope.get("headers") or []:
                if nombre == b"x-forwarded-proto":
                    esquema = ESQUEMAS.get(valor.split(b",")[0].strip().lower())
                    if esquema:
                        scope = {**scope, "scheme": esquema if scope["type"] == "http" else esquema.replace("http", "ws")}
                    break
        await self.app(scope, receive, send)

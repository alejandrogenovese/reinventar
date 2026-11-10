"""Redirige www.<dominio> a <dominio>: las passkeys aceptan un solo origen (WEBAUTHN_ORIGIN) y las suscripciones
de Web Push quedan atadas al dominio donde se activaron, así que la app se usa siempre desde el dominio sin www."""
from urllib.parse import quote

WWW = "www."


def _host(scope) -> str:
    for name, value in scope.get("headers") or []:
        if name == b"host":
            return value.decode("latin-1")
    return ""


class WwwRedirectMiddleware:
    """ASGI puro: si el pedido llega por www., contesta 308 (conserva método y cuerpo) a la misma URL sin www."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        host = _host(scope)
        if scope["type"] != "http" or not host.lower().startswith(WWW):
            return await self.app(scope, receive, send)
        query = scope.get("query_string", b"").decode("latin-1")
        location = f"https://{host[len(WWW):]}{quote(scope.get('path', '/'))}" + (f"?{query}" if query else "")
        await send({"type": "http.response.start", "status": 308,
                    "headers": [(b"location", location.encode("latin-1")), (b"content-length", b"0")]})
        await send({"type": "http.response.body", "body": b""})

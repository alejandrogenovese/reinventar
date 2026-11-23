"""Cabeceras de seguridad en todas las respuestas (PWA y API).

- Content-Security-Policy: solo scripts propios, el script inline de index.html (por su hash, calculado al arrancar) y
  Google Maps. Si alguna vez entra un XSS, no puede cargar scripts de otro lado ni mandar el token a otro dominio.
- frame-ancestors 'none' y X-Frame-Options: la app no se puede embeber en un iframe ajeno (clickjacking sobre admin).
- nosniff, Referrer-Policy, Permissions-Policy (micrófono y ubicación solo para la app) y HSTS.

CSP_MODO=report la pasa a Content-Security-Policy-Report-Only (por si algo de Google Maps se rompe en producción y
hay que destrabarlo sin deploy); CSP_MODO=off la saca.
"""
import base64
import hashlib
import re

from . import config, demos

_GOOGLE = "https://*.googleapis.com https://*.gstatic.com https://*.google.com"


def _hashes_inline() -> str:
    try:
        html = (config.WEB_DIR / "index.html").read_text(encoding="utf-8")
    except OSError:
        return ""
    bloques = re.findall(r"<script>(.*?)</script>", html, re.S)
    return " ".join(hash_csp(b) for b in bloques)


def politica() -> str:
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' {_hashes_inline()} {_GOOGLE}",
        "style-src 'self' 'unsafe-inline'",  # Google Maps inyecta estilos inline
        "font-src 'self'",  # las tipografías se sirven desde /fonts
        "img-src 'self' data: blob: https:",  # imágenes de eventos (Luma y otras) y teselas del mapa
        " ".join(filter(None, ["media-src 'self'", demos.origen_publico()])),  # videos de /demos/, solo de su bucket
        f"connect-src 'self' {_GOOGLE}",
        "worker-src 'self' blob:",
        "frame-src https://*.google.com",
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


def hash_csp(bloque: str) -> str:
    return f"'sha256-{base64.b64encode(hashlib.sha256(bloque.encode()).digest()).decode()}'"


def politica_pagina_publica(estilo: str) -> str:
    """CSP de las páginas públicas sin sesión (el resumen compartido, /c/<token>): nada de afuera, ningún script inline,
    solo el <style> de la página (por su hash) y scripts propios. El contenido viene de un LLM: aunque se escapara mal,
    no podría correr nada."""
    return "; ".join([
        "default-src 'none'",
        "script-src 'self'",
        f"style-src {hash_csp(estilo)}",
        "img-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ])


def cabeceras() -> list[tuple[bytes, bytes]]:
    fijas = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"permissions-policy", b"microphone=(self), geolocation=(self), camera=()"),
        (b"strict-transport-security", b"max-age=31536000"),
    ]
    if config.CSP_MODO == "off":
        return fijas
    nombre = b"content-security-policy-report-only" if config.CSP_MODO == "report" else b"content-security-policy"
    return fijas + [(nombre, politica().encode())]


class CabecerasMiddleware:
    """ASGI puro (como los otros middlewares de app.main): suma las cabeceras al arrancar cada respuesta."""

    def __init__(self, app):
        self.app = app
        self._cabeceras = cabeceras()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                mensaje.setdefault("headers", [])
                presentes = {k.lower() for k, _ in mensaje["headers"]}
                mensaje["headers"] = list(mensaje["headers"]) + [(k, v) for k, v in self._cabeceras if k not in presentes]
            await send(mensaje)

        return await self.app(scope, receive, enviar)

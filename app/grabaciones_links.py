"""Links públicos que vencen al resumen de una grabación (/c/<token>): se abren sin sesión, de solo lectura.

Calcado de app/gastos_links.py: el token es base64url(sid \\n vencimiento) + "." + base64url(HMAC-SHA256 del payload).
El sid va dentro de lo firmado, así que sin la clave no se puede fabricar un link a otra grabación ni enumerarlas.
La clave sale de FOTOS_LINK_SECRET (o, si falta, de DATABASE_URL) pasada por un HMAC con un contexto propio: aunque
el secreto sea el mismo, un token de foto de ticket no verifica como token de grabación ni al revés. Cualquier falla
(adulterado, vencido, de otro contexto) devuelve None y la ruta responde siempre el mismo 404.
"""
import base64
import binascii
import hashlib
import hmac
import time

from . import config

SEGUNDOS_POR_DIA = 86400
CONTEXTO_DERIVACION = b"reinventar-grabacion-link-v1"
LARGO_MAXIMO_TOKEN = 200  # un token real mide ~90 caracteres: más que esto ni se intenta decodificar


def _clave() -> bytes:
    base = config.FOTOS_LINK_SECRET or config.DATABASE_URL
    if not base:
        raise RuntimeError("Falta FOTOS_LINK_SECRET (y no hay DATABASE_URL para derivarlo)")
    return hmac.new(base.encode(), CONTEXTO_DERIVACION, hashlib.sha256).digest()


def _ahora() -> int:
    return int(time.time())


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def _desb64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _firma(payload: bytes) -> bytes:
    return hmac.new(_clave(), payload, hashlib.sha256).digest()


def firmar(sid: str) -> tuple[str, int]:
    """(token, vencimiento en epoch) para la grabación sid."""
    vence = _ahora() + int(config.GRABACION_LINK_DIAS * SEGUNDOS_POR_DIA)
    payload = f"{sid}\n{vence}".encode()
    return f"{_b64(payload)}.{_b64(_firma(payload))}", vence


def verificar(token: str) -> str | None:
    """El sid si el token es auténtico y no venció; None en cualquier otro caso."""
    if len(token) > LARGO_MAXIMO_TOKEN:
        return None
    try:
        cuerpo, firma = token.split(".")
        payload = _desb64(cuerpo)
        if not hmac.compare_digest(_firma(payload), _desb64(firma)):
            return None
        sid, vence = payload.decode().split("\n")
        if int(vence) <= _ahora():
            return None
        return sid
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


def ruta(token: str) -> str:
    return f"/c/{token}"

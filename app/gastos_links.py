"""Links firmados a la foto de un ticket, para el CSV de reintegros: se abren sin sesión (los ve quien recibe el CSV).

El token es base64url(usuario \\n client_id \\n vencimiento) + "." + base64url(HMAC-SHA256 del payload). Sin la clave no se
puede fabricar un token para otro gasto, así que no se pueden enumerar fotos ajenas. La clave es FOTOS_LINK_SECRET; si no
está, se deriva de DATABASE_URL (que ya es un secreto del servicio): funciona sin configurar nada, pero cambiar la
contraseña de la base invalida los links ya emitidos. Cualquier falla de verificación se trata igual (404 en la API).
"""
import base64
import binascii
import hashlib
import hmac
import logging
import time
from uuid import UUID

from . import config

log = logging.getLogger("reinventar.gastos")

SEGUNDOS_POR_DIA = 86400
CONTEXTO_DERIVACION = b"reinventar-gastos-foto-link-v1"


def verificar_configuracion() -> None:
    """Al arrancar en producción: sin FOTOS_LINK_SECRET la clave sale de DATABASE_URL, y si Railway rota esa contraseña
    todos los links ya emitidos dejan de andar."""
    if config.EN_PRODUCCION and not config.FOTOS_LINK_SECRET:
        log.warning("Falta FOTOS_LINK_SECRET: los links de fotos del CSV se firman con una clave derivada de "
                    "DATABASE_URL y mueren si cambia la contraseña de la base")


def _clave() -> bytes:
    if config.FOTOS_LINK_SECRET:
        return config.FOTOS_LINK_SECRET.encode()
    if not config.DATABASE_URL:
        raise RuntimeError("Falta FOTOS_LINK_SECRET (y no hay DATABASE_URL para derivarlo)")
    return hmac.new(config.DATABASE_URL.encode(), CONTEXTO_DERIVACION, hashlib.sha256).digest()


def _ahora() -> int:
    return int(time.time())


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def _desb64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _firma(payload: bytes) -> bytes:
    return hmac.new(_clave(), payload, hashlib.sha256).digest()


def firmar(username: str, client_id: UUID | str) -> str:
    vence = _ahora() + int(config.FOTOS_LINK_DIAS * SEGUNDOS_POR_DIA)
    payload = f"{username}\n{client_id}\n{vence}".encode()
    return f"{_b64(payload)}.{_b64(_firma(payload))}"


def verificar(token: str) -> tuple[str, UUID] | None:
    """(usuario, client_id) si el token es auténtico y no venció; None en cualquier otro caso."""
    try:
        cuerpo, firma = token.split(".")
        payload = _desb64(cuerpo)
        if not hmac.compare_digest(_firma(payload), _desb64(firma)):
            return None
        username, client_id, vence = payload.decode().rsplit("\n", 2)
        if int(vence) <= _ahora():
            return None
        return username, UUID(client_id)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


def ruta_firmada(username: str, client_id: UUID | str) -> str:
    return f"/api/gastos/foto-firmada/{firmar(username, client_id)}"

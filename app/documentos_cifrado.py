"""Cifrado de aplicación de los documentos de viaje: el bucket solo ve bytes cifrados, nunca un pasaporte.

AES-256-GCM con DOCS_ENC_KEY (32 bytes en base64). Cada objeto lleva su nonce aleatorio y se autentica contra su clave
en el bucket (AAD): un objeto copiado a otra clave, o adulterado, no se descifra.

Formato: 1 byte de versión + nonce (12 bytes) + texto cifrado con el tag. La versión deja rotar la clave o el algoritmo
más adelante sin adivinar qué hay guardado (hoy solo existe la 1).

La carpeta de cada persona en el bucket es un HMAC corto de su usuario, con una subclave derivada de DOCS_ENC_KEY: el
nombre de usuario no queda a la vista en el bucket.
"""
import base64
import binascii
import hashlib
import hmac
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import config

VERSION = 1
LARGO_CLAVE = 32
LARGO_NONCE = 12
LARGO_CARPETA = 16          # hex del HMAC del usuario: 64 bits, sobra para no chocar entre las personas del viaje
_INFO_CARPETA = b"reinventar documentos carpeta v1"


class FormatoDesconocido(ValueError):
    """El objeto no empieza con una versión conocida (o está truncado)."""


def clave() -> bytes | None:
    """La clave de DOCS_ENC_KEY, o None si falta o no son 32 bytes en base64 (el valor jamás se loguea)."""
    texto = config.DOCS_ENC_KEY
    if not texto:
        return None
    try:
        crudo = base64.b64decode(texto, validate=True)
    except (binascii.Error, ValueError):
        return None
    return crudo if len(crudo) == LARGO_CLAVE else None


def cifrar(datos: bytes, aad: str, key: bytes) -> bytes:
    nonce = os.urandom(LARGO_NONCE)
    return bytes([VERSION]) + nonce + AESGCM(key).encrypt(nonce, datos, aad.encode())


def descifrar(blob: bytes, aad: str, key: bytes) -> bytes:
    """Los bytes originales. Si el objeto fue adulterado o la AAD no coincide, cryptography tira InvalidTag."""
    if len(blob) < 1 + LARGO_NONCE or blob[0] != VERSION:
        raise FormatoDesconocido("versión de documento desconocida")
    return AESGCM(key).decrypt(blob[1:1 + LARGO_NONCE], blob[1 + LARGO_NONCE:], aad.encode())


def carpeta(username: str, key: bytes) -> str:
    """HMAC corto del usuario (hex), con una subclave propia: no se usa la clave de cifrado para dos cosas."""
    subclave = HKDF(algorithm=hashes.SHA256(), length=LARGO_CLAVE, salt=None, info=_INFO_CARPETA).derive(key)
    return hmac.new(subclave, username.encode(), hashlib.sha256).hexdigest()[:LARGO_CARPETA]

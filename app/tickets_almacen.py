"""Dónde viven las fotos de ticket: un bucket S3-compatible (el de Railway) o, sin configurarlo, el disco local.

Las dos implementaciones guardan, leen y borran bytes por clave. La clave la arma el servidor (usuario + client_id del
gasto + extensión según los bytes): jamás sale del nombre de archivo que manda el cliente.
S3 se habla con SigV4 firmado a mano sobre httpx, sin sumar boto3.
"""
import hashlib
import hmac
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urlparse

import httpx

from . import config

log = logging.getLogger("reinventar.tickets")

TIMEOUT_SEGUNDOS = 20
EXTENSIONES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def clave_foto(username: str, client_id: str, tipo: str) -> str:
    """tickets/<usuario>/<client_id>.<ext>. El usuario va codificado para que ningún carácter raro arme otra ruta."""
    return f"tickets/{quote(username, safe='')}/{client_id}.{EXTENSIONES[tipo]}"


class Almacen(Protocol):
    def guardar(self, clave: str, datos: bytes, tipo: str) -> None: ...
    def leer(self, clave: str) -> bytes | None: ...
    def borrar(self, clave: str) -> None: ...


class AlmacenLocal:
    """Disco local (TICKETS_DIR): para desarrollo y tests. En producción el disco del contenedor no es duradero."""

    def __init__(self, base: Path):
        self.base = base.resolve()

    def _ruta(self, clave: str) -> Path:
        ruta = (self.base / clave).resolve()
        if not ruta.is_relative_to(self.base):
            raise ValueError("clave fuera del directorio de tickets")
        return ruta

    def guardar(self, clave: str, datos: bytes, tipo: str) -> None:
        ruta = self._ruta(clave)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(datos)

    def leer(self, clave: str) -> bytes | None:
        ruta = self._ruta(clave)
        return ruta.read_bytes() if ruta.is_file() else None

    def borrar(self, clave: str) -> None:
        self._ruta(clave).unlink(missing_ok=True)


def _hmac(clave: bytes, mensaje: str) -> bytes:
    return hmac.new(clave, mensaje.encode(), hashlib.sha256).digest()


def firmar(metodo: str, host: str, ruta: str, headers: dict[str, str], payload_sha256: str, ahora: datetime,
           key_id: str, secret: str, region: str) -> dict[str, str]:
    """Headers de un pedido S3 firmado con AWS SigV4 (sin query string). `headers` son los que además de host,
    x-amz-content-sha256 y x-amz-date entran en la firma. Devuelve todos los headers a mandar, con Authorization."""
    marca = ahora.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    dia = marca[:8]
    firmados = {**{k.lower(): v.strip() for k, v in headers.items()}, "host": host,
                "x-amz-content-sha256": payload_sha256, "x-amz-date": marca}
    nombres = sorted(firmados)
    canonico_headers = "".join(f"{n}:{firmados[n]}\n" for n in nombres)
    lista = ";".join(nombres)
    canonico = "\n".join([metodo, quote(ruta, safe="/-_.~"), "", canonico_headers, lista, payload_sha256])
    alcance = f"{dia}/{region}/s3/aws4_request"
    a_firmar = "\n".join(["AWS4-HMAC-SHA256", marca, alcance, hashlib.sha256(canonico.encode()).hexdigest()])
    k = _hmac(_hmac(_hmac(_hmac(("AWS4" + secret).encode(), dia), region), "s3"), "aws4_request")
    firma = hmac.new(k, a_firmar.encode(), hashlib.sha256).hexdigest()
    firmados["authorization"] = (f"AWS4-HMAC-SHA256 Credential={key_id}/{alcance}, SignedHeaders={lista}, "
                                 f"Signature={firma}")
    return firmados


class AlmacenS3:
    """Bucket S3-compatible en estilo virtual-hosted (https://<bucket>.<endpoint>/<clave>), el que usan los buckets de
    Railway. Cada operación es un pedido firmado; los errores de red o de permisos se propagan (el endpoint los
    convierte en un 502 con mensaje claro)."""

    def __init__(self, endpoint: str, bucket: str, key_id: str, secret: str, region: str,
                 cliente: httpx.Client | None = None):
        anfitrion = urlparse(endpoint if "//" in endpoint else f"https://{endpoint}").netloc
        self.host = f"{bucket}.{anfitrion}"
        self.key_id, self.secret, self.region = key_id, secret, region
        self.cliente = cliente or httpx.Client(timeout=TIMEOUT_SEGUNDOS)

    def _pedir(self, metodo: str, clave: str, datos: bytes = b"", tipo: str | None = None) -> httpx.Response:
        ruta = "/" + clave
        extra = {"content-type": tipo} if tipo else {}
        headers = firmar(metodo, self.host, ruta, extra, hashlib.sha256(datos).hexdigest(), datetime.now(UTC),
                         self.key_id, self.secret, self.region)
        headers.pop("host")  # httpx lo arma solo desde la URL
        return self.cliente.request(metodo, f"https://{self.host}{quote(ruta, safe='/-_.~')}", headers=headers,
                                    content=datos if metodo == "PUT" else None)

    def guardar(self, clave: str, datos: bytes, tipo: str) -> None:
        self._pedir("PUT", clave, datos, tipo).raise_for_status()

    def leer(self, clave: str) -> bytes | None:
        r = self._pedir("GET", clave)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content

    def borrar(self, clave: str) -> None:
        r = self._pedir("DELETE", clave)
        if r.status_code != 404:
            r.raise_for_status()


_VARIABLES_S3 = (("TICKETS_S3_ENDPOINT", "ENDPOINT"), ("TICKETS_S3_BUCKET", "BUCKET"), ("TICKETS_S3_KEY_ID", "KEY_ID"),
                 ("TICKETS_S3_SECRET", "SECRET"), ("TICKETS_S3_REGION", "REGION"))


def verificar_configuracion() -> None:
    """Al arrancar: un bucket configurado a medias, o ninguno en producción, hace que las fotos caigan al disco del
    contenedor, que se pierde en cada deploy. Se avisa con un error (solo nombres de variables, nunca valores)."""
    faltan = [nombre for nombre, sufijo in _VARIABLES_S3 if not getattr(config, f"TICKETS_S3_{sufijo}")]
    if 0 < len(faltan) < len(_VARIABLES_S3):
        log.error("Bucket de tickets configurado a medias: faltan %s. Las fotos se guardan en el disco del contenedor "
                  "y se pierden en el próximo deploy.", ", ".join(faltan))
    elif faltan and config.EN_PRODUCCION:
        log.error("No hay bucket para las fotos de tickets (TICKETS_S3_*): se guardan en el disco del contenedor y se "
                  "pierden en el próximo deploy.")


def s3_configurado() -> bool:
    return all((config.TICKETS_S3_ENDPOINT, config.TICKETS_S3_BUCKET, config.TICKETS_S3_KEY_ID,
                config.TICKETS_S3_SECRET, config.TICKETS_S3_REGION))


_s3: AlmacenS3 | None = None


def obtener() -> Almacen:
    """S3 si están las cinco variables TICKETS_S3_*; si no, disco local."""
    global _s3
    if not s3_configurado():
        return AlmacenLocal(config.TICKETS_DIR)
    if _s3 is None:
        _s3 = AlmacenS3(config.TICKETS_S3_ENDPOINT, config.TICKETS_S3_BUCKET, config.TICKETS_S3_KEY_ID,
                        config.TICKETS_S3_SECRET, config.TICKETS_S3_REGION)
    return _s3

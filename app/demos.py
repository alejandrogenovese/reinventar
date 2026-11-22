"""Videos demo de la galería pública (/demos/): viven en su propio bucket S3-compatible, que sigue privado.

En el bucket hay un `index.json` con la lista de demos y, por cada una, `<feature>.mp4` y `<feature>.jpg`. La galería
recibe links firmados que vencen: el navegador baja los videos directo del bucket sin pasar por la app.
Sin las cinco variables DEMOS_S3_* no hay bucket y la galería dice que todavía no hay demos.
"""
import json
import re
import time
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, Field, TypeAdapter, field_validator

from . import config
from .tickets_almacen import AlmacenS3

CLAVE_INDICE = "index.json"
# Nombres de archivo que se aceptan en el bucket: el id de la feature (kebab-case) y la extensión. Nada de rutas.
NOMBRE_ARCHIVO = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.(mp4|jpg)$")
TIPOS = {"mp4": "video/mp4", "jpg": "image/jpeg"}
CACHE_INDICE_S = 300
SEGUNDOS_POR_HORA = 3600


class Demo(BaseModel):
    feature: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=60)
    titulo: str = Field(min_length=1, max_length=80)
    beneficio: str = Field(default="", max_length=140)
    duracion_s: int = Field(ge=1, le=600)
    video: str
    poster: str
    # Alternativa en texto del video (no tiene audio): lo que muestra cada escena, en orden.
    pasos: list[Annotated[str, Field(min_length=1, max_length=140)]] = Field(default_factory=list, max_length=15)

    @field_validator("video", "poster")
    @classmethod
    def _archivo_del_bucket(cls, v: str) -> str:
        if not NOMBRE_ARCHIVO.match(v):
            raise ValueError("Tiene que ser un archivo del bucket de demos (<feature>.mp4 o <feature>.jpg)")
        return v


LISTA_DEMOS = TypeAdapter(list[Demo])


class IndiceInvalido(Exception):
    """El index.json del bucket no se pudo leer o no tiene la forma esperada."""


def configurado() -> bool:
    return all((config.DEMOS_S3_ENDPOINT, config.DEMOS_S3_BUCKET, config.DEMOS_S3_KEY_ID, config.DEMOS_S3_SECRET,
                config.DEMOS_S3_REGION))


_s3: AlmacenS3 | None = None


def obtener() -> AlmacenS3 | None:
    """El bucket de demos, o None si falta alguna variable DEMOS_S3_*."""
    global _s3
    if not configurado():
        return None
    if _s3 is None:
        _s3 = AlmacenS3(config.DEMOS_S3_ENDPOINT, config.DEMOS_S3_BUCKET, config.DEMOS_S3_KEY_ID,
                        config.DEMOS_S3_SECRET, config.DEMOS_S3_REGION)
    return _s3


def origen_publico() -> str | None:
    """https://<bucket>.<endpoint>: el único origen del que la CSP deja reproducir videos."""
    almacen = obtener()
    return f"https://{almacen.host}" if almacen else None


_cache: dict = {"en": 0.0, "demos": None}


def olvidar_indice() -> None:
    _cache.update(en=0.0, demos=None)


def leer_indice(almacen) -> list[Demo]:
    """El índice del bucket, cacheado unos minutos (la galería es pública y no tiene que pegarle al bucket cada vez)."""
    if _cache["demos"] is not None and time.monotonic() - _cache["en"] < CACHE_INDICE_S:
        return _cache["demos"]
    crudo = almacen.leer(CLAVE_INDICE)
    try:
        demos = LISTA_DEMOS.validate_python(json.loads(crudo)) if crudo else []
    except ValueError as e:
        raise IndiceInvalido(str(e)) from e
    _cache.update(en=time.monotonic(), demos=demos)
    return demos


def guardar_indice(almacen, demos: list[Demo]) -> None:
    datos = json.dumps([d.model_dump() for d in demos], ensure_ascii=False).encode()
    almacen.guardar(CLAVE_INDICE, datos, "application/json")
    olvidar_indice()


def con_links(almacen, demos: list[Demo]) -> list[dict]:
    """Cada demo con links firmados. La firma arranca en la hora en punto: dentro de la misma hora el link no cambia y
    el navegador puede reusar lo que ya bajó. Vence a las DEMOS_LINK_HORAS (más lo que va de la hora)."""
    ahora = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    segundos = int(config.DEMOS_LINK_HORAS * SEGUNDOS_POR_HORA) + SEGUNDOS_POR_HORA
    return [d.model_dump() | {"video": almacen.url_firmada(d.video, segundos, ahora),
                              "poster": almacen.url_firmada(d.poster, segundos, ahora)} for d in demos]


def tipo_de(nombre: str) -> str:
    return TIPOS[nombre.rsplit(".", 1)[1]]

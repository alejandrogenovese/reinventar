"""Endpoints de los documentos de viaje (app/documentos.py). Todo exige sesión, cada persona ve solo lo suyo y un id
ajeno da el mismo 404 que uno inexistente. No hay links públicos ni firmados: el archivo sale siempre por acá.

Con la sección apagada (sin bucket o sin clave de cifrado en Railway) todo responde 503 con un mensaje claro.
"""
import datetime as dt
import hashlib
import logging
from typing import Literal
from uuid import UUID

import httpx
from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from . import cuerpo, documentos, documentos_cifrado, limites
from .auth import auth

log = logging.getLogger("reinventar.documentos")

MULTIPART_SOBRANTE = 64 * 1024
SUBIDAS_POR_HORA = 60
DESCARGAS_POR_VENTANA = 200
MSG_APAGADO = "Los documentos de viaje no están activos en este servidor."
MSG_PESO = "El archivo pesa más de 8 MB"
MSG_TIPO = "El archivo tiene que ser una foto (JPEG, PNG o WebP) o un PDF"
SIN_CACHE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}

_subidas = limites.Limite(SUBIDAS_POR_HORA, limites.VENTANA_LARGA)
_descargas = limites.Limite(DESCARGAS_POR_VENTANA, limites.VENTANA_CORTA)


def _sin_cache(response: Response) -> None:
    response.headers.update(SIN_CACHE)


def _exigir_disponible() -> None:
    if not documentos.disponible():
        raise HTTPException(503, MSG_APAGADO)


router = APIRouter(prefix="/api/viajes/documentos",
                   dependencies=[Depends(auth), Depends(_sin_cache), Depends(_exigir_disponible)])


class Meta(BaseModel):
    tipo: Literal[documentos.TIPOS]  # type: ignore[valid-type]
    titulo: str = Field(min_length=1, max_length=documentos.TITULO_MAX)
    vence: dt.date | None = None
    notas: str = Field("", max_length=documentos.NOTAS_MAX)
    vuelo_id: str | None = Field(None, max_length=64)

    @field_validator("titulo", "notas", mode="before")
    @classmethod
    def _recortar(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("vence", "vuelo_id", mode="before")
    @classmethod
    def _vacio_es_nada(cls, v):
        return None if v == "" else v


def _vista(doc: dict) -> dict:
    """Lo que ve el teléfono: metadatos y la alerta de vencimiento. Nunca la clave del objeto."""
    publico = {k: v for k, v in doc.items() if k != "archivo_clave"}
    return {**publico, "alerta": documentos.alerta_vencimiento(doc)}


def _meta_valida(username: str, meta: Meta) -> dict:
    datos = meta.model_dump()
    if datos["vuelo_id"] and not documentos.vuelo_existe(username, datos["vuelo_id"]):
        raise HTTPException(422, "Ese vuelo no existe")
    return datos


def _doc_o_404(username: str, id_: UUID) -> dict:
    doc = documentos.obtener(username, id_)
    if doc is None:
        raise HTTPException(404, "Documento no encontrado")
    return doc


def _validar_archivo(declarado: str, datos: bytes) -> str:
    if len(datos) > documentos.ARCHIVO_MAX_BYTES:
        raise HTTPException(413, MSG_PESO)
    real = documentos.tipo_por_firma(datos)
    if real is None or declarado not in (*documentos.TIPOS_ARCHIVO, "application/octet-stream"):
        raise HTTPException(415, MSG_TIPO)
    if real == documentos.TIPO_PDF and documentos.pdf_con_contenido_activo(datos):
        raise HTTPException(415, "Ese PDF trae código o archivos adentro y no se puede guardar. Probá con una foto o "
                                 "con otro PDF (por ejemplo, imprimiéndolo a PDF).")
    return real


async def _leer_partes(request: Request) -> dict[str, tuple[str, bytes]]:
    datos = await cuerpo.leer_con_tope(request, documentos.ARCHIVO_MAX_BYTES + MULTIPART_SOBRANTE, MSG_PESO)
    partes = cuerpo.partes_multipart(request.headers.get("content-type", ""), datos)
    if partes is None or "archivo" not in partes:
        raise HTTPException(422, "Falta el campo «archivo»")
    return partes


def _subir(username: str, datos: bytes, tipo: str) -> dict:
    """Cifra y sube; devuelve lo que se anota en la base."""
    try:
        clave = documentos.guardar_archivo(username, datos)
    except documentos.NoDisponible as e:
        raise HTTPException(503, MSG_APAGADO) from e
    except (httpx.HTTPError, OSError) as e:
        log.error("No se pudo guardar un documento de viaje (%s)", documentos.error_corto(e))
        raise HTTPException(502, "No se pudo guardar el archivo. Probá de nuevo en un rato.") from e
    return {"clave": clave, "tipo": tipo, "bytes": len(datos), "sha256": hashlib.sha256(datos).hexdigest()}


def _deshacer_subida(clave: str, e: Exception) -> None:
    """La base no anotó el archivo: se borra el objeto recién subido. Se loguea solo el tipo de error (el detalle de un
    error de Postgres puede traer la fila, con título y notas) y no se encadena la excepción."""
    documentos.borrar_objeto(clave)
    log.error("No se pudo anotar un documento de viaje (%s)", type(e).__name__)
    raise HTTPException(500, "No se pudo guardar el documento. Probá de nuevo en un rato.") from None


@router.get("")
def listar(username: str = Depends(auth)):
    return {"documentos": [_vista(d) for d in documentos.listar(username)], "max": documentos.MAX_POR_USUARIO,
            "tipos": list(documentos.TIPOS), "borrado_automatico": documentos.borrado_automatico().date().isoformat()}


@router.post("", status_code=201)
async def crear(request: Request, username: str = Depends(auth)):
    limites.exigir_cupo(_subidas, username, "subida de documentos")
    partes = await _leer_partes(request)
    campos = {k: v.decode("utf-8", "replace") for k, (_, v) in partes.items() if k in Meta.model_fields}
    try:
        meta = Meta(**campos)
    except ValidationError as e:
        raise HTTPException(422, "Revisá el tipo, el título (hasta 80 letras) y las notas (hasta 500).") from e
    declarado, datos = partes["archivo"]
    tipo = _validar_archivo(declarado, datos)
    return await run_in_threadpool(_crear, username, meta, tipo, datos)


def _crear(username: str, meta: Meta, tipo: str, datos: bytes) -> dict:
    datos_meta = _meta_valida(username, meta)
    if documentos.cantidad(username) >= documentos.MAX_POR_USUARIO:
        raise HTTPException(409, f"Ya tenés {documentos.MAX_POR_USUARIO} documentos: borrá alguno para subir otro.")
    archivo = _subir(username, datos, tipo)
    try:
        doc = documentos.insertar(username, datos_meta, archivo)
    except Exception as e:  # noqa: BLE001 — se deshace la subida y se corta con un error genérico
        _deshacer_subida(archivo["clave"], e)
    if doc is None:  # otro pedido llenó el cupo entre el chequeo y el alta
        documentos.borrar_objeto(archivo["clave"])
        raise HTTPException(409, f"Ya tenés {documentos.MAX_POR_USUARIO} documentos: borrá alguno para subir otro.")
    return _vista(doc)


@router.put("/{id_}")
def editar(id_: UUID, body: Meta, username: str = Depends(auth)):
    doc = documentos.actualizar_meta(username, id_, _meta_valida(username, body))
    if doc is None:
        raise HTTPException(404, "Documento no encontrado")
    return _vista(doc)


@router.put("/{id_}/archivo")
async def reemplazar(id_: UUID, request: Request, username: str = Depends(auth)):
    limites.exigir_cupo(_subidas, username, "subida de documentos")
    declarado, datos = (await _leer_partes(request))["archivo"]
    tipo = _validar_archivo(declarado, datos)
    return await run_in_threadpool(_reemplazar, username, id_, tipo, datos)


def _reemplazar(username: str, id_: UUID, tipo: str, datos: bytes) -> dict:
    _doc_o_404(username, id_)
    archivo = _subir(username, datos, tipo)
    try:
        anterior = documentos.reemplazar_archivo(username, id_, archivo)
    except Exception as e:  # noqa: BLE001 — se deshace la subida y se corta con un error genérico
        _deshacer_subida(archivo["clave"], e)
    if anterior is None:  # lo borraron mientras subía
        documentos.borrar_objeto(archivo["clave"])
        raise HTTPException(404, "Documento no encontrado")
    documentos.borrar_objeto(anterior)  # recién con el nuevo anotado: si esto falla no se pierde nada
    return _vista(_doc_o_404(username, id_))


@router.get("/{id_}/archivo")
def ver_archivo(id_: UUID, username: str = Depends(auth)):
    limites.exigir_cupo(_descargas, username, "descarga de documentos")
    doc = _doc_o_404(username, id_)
    try:
        datos = documentos.leer_archivo(doc["archivo_clave"])
    except documentos.NoDisponible as e:
        raise HTTPException(503, MSG_APAGADO) from e
    except (httpx.HTTPError, OSError) as e:
        log.error("No se pudo leer un documento de viaje (%s)", documentos.error_corto(e))
        raise HTTPException(502, "No se pudo traer el archivo. Probá de nuevo en un rato.") from e
    except (InvalidTag, documentos_cifrado.FormatoDesconocido) as e:
        log.error("Un documento de viaje no se pudo descifrar (%s)", type(e).__name__)
        raise HTTPException(502, "El archivo no se pudo abrir. Probá subirlo de nuevo.") from e
    tipo = documentos.tipo_por_firma(datos) if datos else None
    if tipo is None:
        log.error("Falta en el almacén el archivo de un documento de viaje")
        raise HTTPException(404, "Este documento no tiene archivo")
    modo = "attachment" if tipo == documentos.TIPO_PDF else "inline"
    return Response(datos, media_type=tipo, headers={
        **SIN_CACHE,
        "Content-Disposition": f'{modo}; filename="documento.{documentos.EXTENSIONES[tipo]}"',
        "Content-Security-Policy": "default-src 'none'; sandbox",
    })


@router.delete("/{id_}")
def borrar(id_: UUID, username: str = Depends(auth)):
    if not documentos.borrar(username, id_):
        raise HTTPException(404, "Documento no encontrado")
    return {"ok": True}


@router.delete("")
def borrar_todos(username: str = Depends(auth)):
    return {"ok": True, "borrados": documentos.borrar_todos(username)}


def al_arrancar() -> None:
    documentos.verificar_configuracion()

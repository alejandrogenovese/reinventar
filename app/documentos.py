"""Documentos de viaje privados (pasaporte, ESTA o visa, seguro, reservas, entrada de re:Invent, tarjeta de embarque).

- Archivo: cifrado en la app (app/documentos_cifrado.py) y guardado en un bucket propio (DOCS_S3_*), con clave
  documentos/<HMAC del usuario>/<uuid>: sin nombre de archivo, tipo ni datos personales. En modo prueba, bajo prueba/.
- Metadatos: tabla viajes_documentos (schema real o de prueba, como el resto de los datos del usuario).
- En Railway sin bucket o sin DOCS_ENC_KEY la sección queda apagada: nunca cae al disco efímero del contenedor.
- Retención: todo se borra solo RETENCION_DIAS después del fin de la estadía (app/estadia.py), en la vuelta de push.
Nunca se loguean claves de objetos, nombres de archivo ni metadatos de un documento.
"""
import calendar
import datetime as dt
import hashlib
import logging
import re
import uuid
import zlib

import httpx

from . import config, db, documentos_cifrado, recordatorio, sandbox, tickets_almacen
from .estadia import FIN_DE_LA_ESTADIA

log = logging.getLogger("reinventar.documentos")

TIPOS = ("pasaporte", "esta_visa", "seguro", "reserva", "entrada_reinvent", "tarjeta_embarque", "otro")
MAX_POR_USUARIO = 30
ARCHIVO_MAX_BYTES = 8 * 1024 * 1024
TITULO_MAX = 80
NOTAS_MAX = 500
RETENCION_DIAS = 30
MESES_PASAPORTE = 6             # muchos países piden el pasaporte vigente 6 meses después de la salida
TIPO_PDF = "application/pdf"
TIPOS_ARCHIVO = ("image/jpeg", "image/png", "image/webp", TIPO_PDF)
EXTENSIONES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", TIPO_PDF: "pdf"}
TTL_AVISO = 6 * 3600

DOCS = tickets_almacen.JuegoS3("DOCS_S3", "DOCS_DIR")

COLUMNAS = "id, tipo, titulo, vence, notas, vuelo_id, archivo_tipo, bytes, sha256, creado, actualizado"


class NoDisponible(Exception):
    """Falta el bucket o la clave de cifrado: la sección está apagada."""


# ---------- configuración y almacén ----------

def disponible() -> bool:
    if documentos_cifrado.clave() is None:
        return False
    return DOCS.configurado() or not config.EN_PRODUCCION


_s3: tuple[tuple[str, ...], tickets_almacen.AlmacenS3] | None = None


def almacen() -> tickets_almacen.Almacen:
    """El bucket DOCS_S3_*; sin él, solo fuera de Railway, la carpeta DOCS_DIR (dev y tests)."""
    global _s3
    if not DOCS.configurado():
        if config.EN_PRODUCCION:
            raise NoDisponible
        return DOCS.local()
    valores = DOCS.valores()
    if _s3 is None or _s3[0] != valores:
        _s3 = (valores, DOCS.crear_s3())
    return _s3[1]


def _clave_cifrado() -> bytes:
    key = documentos_cifrado.clave()
    if key is None:
        raise NoDisponible
    return key


def verificar_configuracion() -> None:
    """Al arrancar, en Railway: avisa qué falta (solo nombres de variables, nunca valores)."""
    if not config.EN_PRODUCCION:
        return
    faltan = DOCS.faltantes() + ([] if documentos_cifrado.clave() else ["DOCS_ENC_KEY (32 bytes en base64)"])
    if faltan:
        log.error("Documentos de viaje apagados: faltan %s.", ", ".join(faltan))


def nueva_clave_objeto(username: str) -> str:
    prefijo = "prueba/" if sandbox.actual() else ""
    return f"{prefijo}documentos/{documentos_cifrado.carpeta(username, _clave_cifrado())}/{uuid.uuid4()}"


def error_corto(e: Exception) -> str:
    """Para el log: el tipo y, si es HTTP, el código. Nunca el mensaje (las URLs de S3 llevan la clave del objeto)."""
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    return type(e).__name__


def guardar_archivo(username: str, datos: bytes) -> str:
    """Cifra y sube. Devuelve la clave del objeto. Los errores de red o permisos se propagan (el endpoint da 502)."""
    clave = nueva_clave_objeto(username)
    almacen().guardar(clave, documentos_cifrado.cifrar(datos, clave, _clave_cifrado()), "application/octet-stream")
    return clave


def leer_archivo(clave: str) -> bytes | None:
    blob = almacen().leer(clave)
    return None if blob is None else documentos_cifrado.descifrar(blob, clave, _clave_cifrado())


def borrar_objeto(clave: str) -> bool:
    """Best effort: si falla queda un objeto cifrado huérfano; se loguea sin la clave."""
    try:
        almacen().borrar(clave)
        return True
    except (httpx.HTTPError, OSError, ValueError, NoDisponible) as e:
        log.warning("No se pudo borrar un archivo de documentos (%s)", error_corto(e))
        return False


# ---------- validación del archivo ----------

def tipo_por_firma(datos: bytes) -> str | None:
    """JPEG, PNG, WebP o PDF según los primeros bytes (no se confía en el Content-Type del cliente)."""
    if datos.startswith(b"%PDF-"):
        return TIPO_PDF
    if datos.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp"
    return None


# Nombres de PDF que ejecutan algo o meten otro archivo. /OpenAction o /AA solo hacen daño si disparan uno de estos.
_NOMBRES_PELIGROSOS = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/EmbeddedFiles", b"/RichMedia")
_FIN_DE_NOMBRE = frozenset(b" \t\r\n\f\x00()<>[]{}/%")
_ESCAPE_NOMBRE = re.compile(rb"#([0-9A-Fa-f]{2})")
_DESCOMPRIMIDO_MAX = 64 * 1024 * 1024   # tope de lo que se infla buscando en los streams (bomba de compresión)
_STREAMS_MAX = 5000


def _tiene_nombre(datos: bytes, nombre: bytes) -> bool:
    inicio = datos.find(nombre)
    while inicio >= 0:
        fin = inicio + len(nombre)
        if fin >= len(datos) or datos[fin] in _FIN_DE_NOMBRE:
            return True
        inicio = datos.find(nombre, fin)
    return False


def _peligroso(datos: bytes) -> bool:
    normal = _ESCAPE_NOMBRE.sub(lambda m: bytes([int(m.group(1), 16)]), datos)   # /J#61vaScript = /JavaScript
    return any(_tiene_nombre(normal, n) for n in _NOMBRES_PELIGROSOS)


def _streams(datos: bytes):
    """El contenido de cada stream ... endstream (búsqueda lineal, sin regex)."""
    pos = 0
    for _ in range(_STREAMS_MAX):
        inicio = datos.find(b"stream", pos)
        if inicio < 0:
            return
        cuerpo = inicio + len(b"stream")
        cuerpo += 2 if datos[cuerpo:cuerpo + 2] == b"\r\n" else 1 if datos[cuerpo:cuerpo + 1] in (b"\n", b"\r") else 0
        fin = datos.find(b"endstream", cuerpo)
        if fin < 0:
            return
        yield datos[cuerpo:fin]
        pos = fin + len(b"endstream")


def pdf_con_contenido_activo(datos: bytes) -> bool:
    """True si el PDF tiene JavaScript, acciones de lanzar programas o archivos embebidos, en claro o dentro de streams
    comprimidos (FlateDecode, incluidos los object streams). Si inflar pasa del tope, se rechaza por las dudas."""
    if _peligroso(datos):
        return True
    total = 0
    for crudo in _streams(datos):
        inflador = zlib.decompressobj()
        try:
            plano = inflador.decompress(crudo, _DESCOMPRIMIDO_MAX - total + 1)
        except zlib.error:
            continue
        total += len(plano)
        if total > _DESCOMPRIMIDO_MAX or _peligroso(plano):
            return True
    return False


# ---------- metadatos (tabla viajes_documentos) ----------

def _fila(r) -> dict:
    d = dict(r)
    d["id"] = str(d["id"])
    return d


def listar(username: str) -> list[dict]:
    with db.conn() as c:
        filas = c.execute(f"SELECT {COLUMNAS} FROM viajes_documentos WHERE username=%s ORDER BY tipo, creado",
                          (username,)).fetchall()
    return [_fila(r) for r in filas]


def obtener(username: str, id_: uuid.UUID) -> dict | None:
    with db.conn() as c:
        r = c.execute(f"SELECT {COLUMNAS}, archivo_clave FROM viajes_documentos WHERE username=%s AND id=%s",
                      (username, id_)).fetchone()
    return _fila(r) if r else None


def cantidad(username: str) -> int:
    with db.conn() as c:
        return c.execute("SELECT count(*) AS n FROM viajes_documentos WHERE username=%s", (username,)).fetchone()["n"]


def vuelo_existe(username: str, vuelo_id: str) -> bool:
    with db.conn() as c:
        return c.execute("SELECT 1 FROM viajes_vuelos WHERE username=%s AND id=%s", (username, vuelo_id)).fetchone() is not None


def insertar(username: str, meta: dict, archivo: dict) -> dict | None:
    """Inserta solo si la persona todavía no llegó al máximo (en la misma sentencia). None si ya estaba llena."""
    id_ = uuid.uuid4()
    with db.conn() as c:
        r = c.execute(
            "INSERT INTO viajes_documentos (username, id, tipo, titulo, vence, notas, vuelo_id, archivo_clave, "
            "archivo_tipo, bytes, sha256) SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s "
            "WHERE (SELECT count(*) FROM viajes_documentos WHERE username=%s) < %s RETURNING id",
            (username, id_, meta["tipo"], meta["titulo"], meta["vence"], meta["notas"], meta["vuelo_id"],
             archivo["clave"], archivo["tipo"], archivo["bytes"], archivo["sha256"], username, MAX_POR_USUARIO),
        ).fetchone()
    return obtener(username, id_) if r else None


def actualizar_meta(username: str, id_: uuid.UUID, meta: dict) -> dict | None:
    with db.conn() as c:
        n = c.execute("UPDATE viajes_documentos SET tipo=%s, titulo=%s, vence=%s, notas=%s, vuelo_id=%s, "
                      "actualizado=now() WHERE username=%s AND id=%s",
                      (meta["tipo"], meta["titulo"], meta["vence"], meta["notas"], meta["vuelo_id"], username,
                       id_)).rowcount
    return obtener(username, id_) if n else None


def reemplazar_archivo(username: str, id_: uuid.UUID, archivo: dict) -> str | None:
    """Anota el archivo nuevo. Devuelve la clave del anterior (para borrarlo) o None si el documento no existe."""
    with db.conn() as c:
        r = c.execute("SELECT archivo_clave FROM viajes_documentos WHERE username=%s AND id=%s FOR UPDATE",
                      (username, id_)).fetchone()
        if r is None:
            return None
        c.execute("UPDATE viajes_documentos SET archivo_clave=%s, archivo_tipo=%s, bytes=%s, sha256=%s, "
                  "actualizado=now() WHERE username=%s AND id=%s",
                  (archivo["clave"], archivo["tipo"], archivo["bytes"], archivo["sha256"], username, id_))
    return r["archivo_clave"]


def borrar(username: str, id_: uuid.UUID) -> bool:
    with db.conn() as c:
        r = c.execute("DELETE FROM viajes_documentos WHERE username=%s AND id=%s RETURNING archivo_clave",
                      (username, id_)).fetchone()
    if r is None:
        return False
    borrar_objeto(r["archivo_clave"])
    return True


def borrar_todos(username: str) -> int:
    with db.conn() as c:
        claves = [r["archivo_clave"] for r in c.execute(
            "DELETE FROM viajes_documentos WHERE username=%s RETURNING archivo_clave", (username,)).fetchall()]
    for clave in claves:
        borrar_objeto(clave)
    return len(claves)


def borrar_objetos_prueba() -> int:
    """Los archivos de los documentos cargados en modo prueba (los llama Admin › Borrar datos de prueba antes de vaciar
    las tablas: después ya no se sabría qué objetos eran)."""
    with sandbox.real(), db.conn() as c:
        claves = [r["archivo_clave"] for r in c.execute(
            f"SELECT archivo_clave FROM {sandbox.schema_prueba()}.viajes_documentos").fetchall()]
    return sum(borrar_objeto(clave) for clave in claves)


# ---------- retención ----------

def borrado_automatico() -> dt.datetime:
    return FIN_DE_LA_ESTADIA + dt.timedelta(days=RETENCION_DIAS)


def purgar_si_toca(now: dt.datetime) -> int:
    """Pasado el plazo de retención, borra todos los documentos (schema real y de prueba) con sus archivos. Antes del
    plazo no consulta nada. Lo llama la vuelta de push (app/push.tick)."""
    if now < borrado_automatico():
        return 0
    claves: list[str] = []
    with sandbox.real(), db.conn() as c:
        for schema in (config.DB_SCHEMA, sandbox.schema_prueba()):
            claves += [r["archivo_clave"] for r in c.execute(
                f"DELETE FROM {schema}.viajes_documentos RETURNING archivo_clave").fetchall()]
    for clave in claves:
        borrar_objeto(clave)
    if claves:
        log.info("Retención: se borraron %d documentos de viaje", len(claves))
    return len(claves)


# ---------- vencimientos y avisos ----------

def _mas_meses(fecha: dt.date, meses: int) -> dt.date:
    """La misma fecha `meses` después; si ese mes es más corto, su último día."""
    mes = fecha.month - 1 + meses
    anio, mes = fecha.year + mes // 12, mes % 12 + 1
    return dt.date(anio, mes, min(fecha.day, calendar.monthrange(anio, mes)[1]))


def alerta_vencimiento(doc: dict) -> str | None:
    """Texto de alerta si el documento vence durante el viaje (o el pasaporte antes de 6 meses después); si no, None."""
    vence = doc.get("vence")
    if not vence:
        return None
    fin = FIN_DE_LA_ESTADIA.date()
    if vence <= fin:
        return "Vence antes de que termine el viaje"
    if doc["tipo"] == "pasaporte" and vence < _mas_meses(fin, MESES_PASAPORTE):
        return "Vence antes de 6 meses después del viaje: revisá si te lo piden"
    return None


def avisos(username: str, now: dt.datetime) -> list[tuple[str, dict]]:
    """Un solo aviso si hay documentos con alerta de vencimiento, hasta el fin de la estadía y fuera del silencio. La
    clave cambia si cambia el conjunto de documentos con alerta. El texto no lleva ningún dato del documento."""
    if now >= FIN_DE_LA_ESTADIA or recordatorio.en_silencio(now):
        return []
    ids = sorted(d["id"] for d in listar(username) if alerta_vencimiento(d))
    if not ids:
        return []
    clave = "docvence:" + hashlib.sha256(",".join(ids).encode()).hexdigest()[:16]
    return [(clave, {"title": "Revisá tus documentos de viaje", "body": "Hay algo para mirar antes de viajar.",
                     "url": "/#/viajes/documentos", "ttl": TTL_AVISO})]

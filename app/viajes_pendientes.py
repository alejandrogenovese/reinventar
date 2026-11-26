"""Checklist de pendientes del viaje (#/viajes/pendientes): una lista sugerida (SUGERIDOS) que se siembra sola la primera
vez que la persona abre la pantalla, más los que agrega ella. Todo se edita y se borra.

Los sugeridos se siembran con su clave estable: el UNIQUE (username, clave_sugerido) hace que sembrar de nuevo no los
duplique. Borrar un sugerido no lo elimina: le pone borrado_en, así la próxima siembra lo encuentra y no lo vuelve a
agregar. Un sugerido nuevo que se sume acá le aparece a todos la próxima vez que abran la pantalla.
Los avisos (fecha límite y el resumen de los días previos) los arma app/viajes_avisos.pendientes.
"""
import datetime as dt
import time
import uuid

from . import db

LARGO_MAX_TEXTO = 120
TOPE_POR_PERSONA = 100
ORDEN_MAX = 10_000

# (clave estable, texto). La clave no cambia nunca: es lo que evita volver a sembrar uno que la persona borró.
SUGERIDOS = (
    ("esta", "Tener la ESTA o la visa aprobada"),
    ("pasaporte", "Pasaporte vigente hasta 6 meses después del viaje"),
    ("seguro", "Contratar el seguro de viaje"),
    ("esim", "Comprar la eSIM o el chip para usar datos allá"),
    ("checkin_united", "Hacer el check-in web de United (abre 24 h antes)"),
    ("badge", "Tener la entrada de re:Invent y saber dónde retirar el badge"),
    ("banco", "Avisar al banco y a las tarjetas que viajás"),
    ("vuelos_hotel", "Cargar los vuelos y el hotel en la app"),
    ("dolares", "Llevar dólares en efectivo"),
    ("documentos", "Subir los documentos del viaje a la app"),
    # Fuentes consultadas el 25/11/2026: know-before-you-go de re:Invent (la foto), formulario OM-121 de ARCA
    # (https://arca.gob.ar/viajeros/ayuda/regimen-equipaje.asp) y enchufes de EE. UU.: tipos A y B, 120 V. Lo de la
    # tarjeta en dólares no tiene fuente oficial (solo notas de prensa): va como sugerencia, a confirmar con el banco.
    ("enchufe", "Llevar un adaptador de enchufe tipo A (en EE. UU. son tipo A y B, 120 V)"),
    ("foto_reinvent", "Subir tu foto al portal de registro de re:Invent: el retiro del badge es más rápido"),
    ("om121", "Declarar la notebook y los equipos en la Aduana al salir (formulario OM-121 de ARCA)"),
    ("tarjeta_dolares", "Evaluar pagar el resumen de la tarjeta con dólares propios (puede evitar la percepción: confirmalo con tu banco)"),
    ("swag", "Dejar lugar en la valija para el swag"),
)

_COLUMNAS = "id, texto, fecha_limite, hecho_en, orden, origen, clave_sugerido, vuelo_id, documento_id"


def _nuevo_id() -> str:
    return uuid.uuid4().hex[:12]


def _publico(r: dict) -> dict:
    return {"id": r["id"], "texto": r["texto"],
            "fecha_limite": r["fecha_limite"].isoformat() if r["fecha_limite"] else None,
            "hecho": r["hecho_en"] is not None,
            "hecho_en": r["hecho_en"].isoformat() if r["hecho_en"] else None,
            "orden": r["orden"], "origen": r["origen"], "vuelo_id": r["vuelo_id"], "documento_id": r["documento_id"]}


def sembrar(username: str) -> None:
    """Agrega los sugeridos que la persona todavía no tiene (ni tuvo: los borrados quedan marcados). Idempotente."""
    ahora = time.time()
    filas = [(username, _nuevo_id(), texto, i, clave, ahora) for i, (clave, texto) in enumerate(SUGERIDOS)]
    with db.conn() as c, c.cursor() as cur:
        cur.executemany("INSERT INTO viajes_pendientes (username,id,texto,orden,origen,clave_sugerido,creado) "
                        "VALUES (%s,%s,%s,%s,'sugerido',%s,%s) ON CONFLICT (username, clave_sugerido) DO NOTHING", filas)


def listar_filas(username: str) -> list[dict]:
    """Los pendientes vivos (sin los sugeridos borrados), en orden."""
    with db.conn() as c:
        return [dict(r) for r in c.execute(
            f"SELECT {_COLUMNAS} FROM viajes_pendientes WHERE username=%s AND borrado_en IS NULL "
            "ORDER BY orden, creado, id", (username,)).fetchall()]


def listar(username: str) -> dict:
    """Lo que ve la pantalla: siembra si hace falta y devuelve la lista con el resumen."""
    sembrar(username)
    items = [_publico(r) for r in listar_filas(username)]
    return {"pendientes": items, "resumen": resumen(items)}


def resumen(items: list[dict]) -> dict:
    return {"hechos": sum(1 for x in items if x["hecho"]), "total": len(items)}


def get(username: str, id_: str) -> dict | None:
    with db.conn() as c:
        r = c.execute(f"SELECT {_COLUMNAS} FROM viajes_pendientes WHERE username=%s AND id=%s AND borrado_en IS NULL",
                      (username, id_)).fetchone()
    return _publico(dict(r)) if r else None


def agregar(username: str, texto: str, fecha_limite: dt.date | None) -> dict | None:
    """Un pendiente propio, al final de la lista. None si ya tiene demasiados."""
    id_ = _nuevo_id()
    with db.conn() as c:
        r = c.execute("SELECT COUNT(*) AS n, COALESCE(MAX(orden), -1) AS ultimo FROM viajes_pendientes "
                      "WHERE username=%s AND borrado_en IS NULL", (username,)).fetchone()
        if r["n"] >= TOPE_POR_PERSONA:
            return None
        c.execute("INSERT INTO viajes_pendientes (username,id,texto,fecha_limite,orden,origen,creado) "
                  "VALUES (%s,%s,%s,%s,%s,'propio',%s)",
                  (username, id_, texto, fecha_limite, min(r["ultimo"] + 1, ORDEN_MAX), time.time()))
    return get(username, id_)


CAMPOS_EDITABLES = ("texto", "fecha_limite", "orden")


def actualizar(username: str, id_: str, campos: dict) -> dict | None:
    """Cambia solo los campos que vienen (fecha_limite=None la borra). None si no existe o no es de esta persona."""
    columnas = [k for k in CAMPOS_EDITABLES if k in campos]
    if columnas:
        with db.conn() as c:
            c.execute(f"UPDATE viajes_pendientes SET {', '.join(f'{k}=%s' for k in columnas)} "
                      "WHERE username=%s AND id=%s AND borrado_en IS NULL",
                      (*(campos[k] for k in columnas), username, id_))
    return get(username, id_)


def marcar_hecho(username: str, id_: str, hecho: bool) -> dict | None:
    """Tilda o destilda. Tildar uno ya tildado conserva la hora en que se hizo."""
    with db.conn() as c:
        c.execute("UPDATE viajes_pendientes SET hecho_en = CASE WHEN %s THEN COALESCE(hecho_en, now()) END "
                  "WHERE username=%s AND id=%s AND borrado_en IS NULL", (hecho, username, id_))
    return get(username, id_)


def borrar(username: str, id_: str) -> bool:
    """Un propio se borra; un sugerido queda marcado (si no, la próxima siembra lo traería de vuelta)."""
    with db.conn() as c:
        if c.execute("UPDATE viajes_pendientes SET borrado_en = now() WHERE username=%s AND id=%s "
                     "AND origen='sugerido' AND borrado_en IS NULL", (username, id_)).rowcount:
            return True
        return c.execute("DELETE FROM viajes_pendientes WHERE username=%s AND id=%s AND origen='propio'",
                         (username, id_)).rowcount == 1


def sin_hacer(username: str) -> list[dict]:
    """Los que faltan (para los avisos)."""
    return [r for r in listar_filas(username) if r["hecho_en"] is None]

"""Ofertas de la semana de re:Invent: lo que se cargó a mano (comida, happy hours, outlets) y las bajas de precio de
shows de Ticketmaster. Las lee la pantalla Ofertas (app/ofertas_api.py) y las avisa app/ofertas_avisos.py.

- Manuales: las carga un admin con su vigencia (desde/hasta). El push sale cuando arranca.
- Bajas de precio: cada 6 h se guarda el precio mínimo (USD, de priceRanges: lo lee app/ticketmaster.py) de cada función
  de la semana. Es oferta si el mínimo actual bajó 15 % o US$ 20 contra el máximo de los últimos 7 días. Si Ticketmaster
  no trae precio, no hay oferta: nada se inventa.
- Fuente: interfaz mínima (`Fuente`). Para sumar otra (Goldstar) alcanza con una clase con `nombre` y `ofertas(ahora)`
  y agregarla en `fuentes_activas()`.

Las tablas son de todos: se leen y escriben siempre en el schema real, aunque el pedido venga de alguien en modo prueba.
"""
import datetime as dt
import logging
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Protocol

import psycopg

from . import config, db, pg, sandbox, ticketmaster

log = logging.getLogger("reinventar.ofertas")

CATEGORIAS = {"shows": "Shows", "comida": "Comida", "compras": "Compras y outlets", "otros": "Otros"}
REFERENCIA_DIAS = 7            # la baja se mide contra el máximo de estos días
SNAPSHOTS_DIAS = 14            # y los snapshots se borran a los 14
ESTADOS_EN_VENTA = {"onsale", "rescheduled"}
FUENTE_TICKETMASTER = "ticketmaster"
FUENTE_MANUAL = "manual"
_COLUMNAS = ("id", "fuente", "categoria", "titulo", "lugar", "desde", "hasta", "link", "nota", "id_show", "precio_antes",
             "precio_ahora", "creado")


@dataclass(frozen=True)
class Oferta:
    id: str
    fuente: str
    categoria: str
    titulo: str
    lugar: str
    desde: dt.datetime
    hasta: dt.datetime | None
    link: str | None
    nota: str
    id_show: str | None
    precio_antes: Decimal | None
    precio_ahora: Decimal | None
    creado: float

    def a_json(self) -> dict:
        d = asdict(self)
        d.update(desde=self.desde.isoformat(), hasta=self.hasta.isoformat() if self.hasta else None,
                 precio_antes=float(self.precio_antes) if self.precio_antes is not None else None,
                 precio_ahora=float(self.precio_ahora) if self.precio_ahora is not None else None,
                 categoria_nombre=CATEGORIAS.get(self.categoria, self.categoria))
        return d


class Fuente(Protocol):
    nombre: str

    def ofertas(self, ahora: dt.datetime) -> list[Oferta]: ...


# ---------- bajas de precio (puro) ----------

def baja_de_precio(historial: list[tuple[float, Decimal]], ahora_ts: float) -> tuple[Decimal, Decimal] | None:
    """(precio de referencia, precio actual) si el último precio bajó lo suficiente contra el máximo de los últimos 7
    días; None si no hay un precio anterior o la baja es chica."""
    ordenado = sorted(historial)
    if len(ordenado) < 2:
        return None
    *anteriores, (_, actual) = ordenado
    recientes = [p for t, p in anteriores if t >= ahora_ts - REFERENCIA_DIAS * 86400]
    if not recientes:
        return None
    referencia = max(recientes)
    caida = referencia - actual
    if caida <= 0:
        return None
    if caida >= referencia * Decimal(str(config.OFERTAS_BAJA_PORCENTAJE)) / 100 or caida >= Decimal(str(config.OFERTAS_BAJA_USD)):
        return referencia, actual
    return None


def ofertas_de_bajas(funciones: list[dict], historial: dict[str, list[tuple[float, Decimal]]], ahora: dt.datetime) -> list[Oferta]:
    """Las funciones en venta, que no empezaron y bajaron de precio, como ofertas de la categoría shows."""
    out = []
    for f in funciones:
        if f.get("precio_desde") is None or f["estado"] not in ESTADOS_EN_VENTA or f["inicio"] <= ahora:
            continue
        baja = baja_de_precio(historial.get(f["id_funcion"], []), ahora.timestamp())
        if not baja:
            continue
        antes, actual = baja
        out.append(Oferta(id=f"tm-{f['id_funcion']}-{int(actual * 100)}", fuente=FUENTE_TICKETMASTER, categoria="shows",
                          titulo=f["nombre"], lugar=f["sala"], desde=ahora, hasta=f["inicio"], link=f.get("url"), nota="",
                          id_show=f.get("id_show"), precio_antes=antes, precio_ahora=actual, creado=ahora.timestamp()))
    return out


# ---------- base (siempre el schema real) ----------

def _oferta(fila: dict) -> Oferta:
    return Oferta(**{c: fila[c] for c in _COLUMNAS})


_SELECT = f"SELECT {', '.join(_COLUMNAS)} FROM oferta"


@sandbox.en_real
def guardar(o: Oferta) -> bool:
    """True si es nueva (la misma id no se guarda dos veces)."""
    marcadores = ", ".join(["%s"] * len(_COLUMNAS))
    with db.conn() as c:
        return c.execute(f"INSERT INTO oferta ({', '.join(_COLUMNAS)}) VALUES ({marcadores}) ON CONFLICT (id) DO NOTHING",
                         tuple(getattr(o, col) for col in _COLUMNAS)).rowcount == 1


@sandbox.en_real
def crear_manual(datos: dict, ahora: dt.datetime) -> Oferta:
    o = Oferta(id=f"m-{uuid.uuid4().hex[:10]}", fuente=FUENTE_MANUAL, categoria=datos["categoria"], titulo=datos["titulo"],
               lugar=datos.get("lugar") or "", desde=datos["desde"], hasta=datos.get("hasta"), link=datos.get("link"),
               nota=datos.get("nota") or "", id_show=None, precio_antes=None, precio_ahora=None, creado=ahora.timestamp())
    guardar(o)
    return o


@sandbox.en_real
def obtener(id_oferta: str) -> Oferta | None:
    with db.conn() as c:
        fila = c.execute(f"{_SELECT} WHERE id=%s", (id_oferta,)).fetchone()
    return _oferta(fila) if fila else None


@sandbox.en_real
def vigentes(ahora: dt.datetime, categoria: str | None = None) -> list[Oferta]:
    """Las que ya arrancaron y no vencieron, las más nuevas primero."""
    with db.conn() as c:
        filas = c.execute(f"{_SELECT} WHERE desde <= %s AND (hasta IS NULL OR hasta > %s) "
                          "AND (%s::text IS NULL OR categoria = %s) ORDER BY desde DESC, id", (ahora, ahora, categoria, categoria)).fetchall()
    return [_oferta(f) for f in filas]


@sandbox.en_real
def todas() -> list[Oferta]:
    with db.conn() as c:
        return [_oferta(f) for f in c.execute(f"{_SELECT} ORDER BY desde DESC, id").fetchall()]


@sandbox.en_real
def borrar(id_oferta: str) -> bool:
    with db.conn() as c:
        return c.execute("DELETE FROM oferta WHERE id=%s", (id_oferta,)).rowcount == 1


def preferencias(username: str) -> dict:
    with db.conn() as c:
        fila = c.execute("SELECT ofertas, ofertas_categorias FROM preferencias_avisos WHERE username=%s", (username,)).fetchone()
    if not fila:
        return {"activas": False, "categorias": list(CATEGORIAS)}
    return {"activas": fila["ofertas"], "categorias": [k for k in CATEGORIAS if k in fila["ofertas_categorias"]]}


def guardar_preferencias(username: str, activas: bool, categorias: list[str]) -> dict:
    elegidas = [k for k in CATEGORIAS if k in categorias]
    with db.conn() as c:
        c.execute("INSERT INTO preferencias_avisos (username, ofertas, ofertas_categorias, updated_at) VALUES (%s,%s,%s,extract(epoch from now())) "
                  "ON CONFLICT (username) DO UPDATE SET ofertas=EXCLUDED.ofertas, ofertas_categorias=EXCLUDED.ofertas_categorias",
                  (username, activas, elegidas))
    return preferencias(username)


# ---------- Ticketmaster: snapshots de precio ----------

_FUNCIONES_SQL = """
SELECT id_funcion, id_show, nombre, sala, url, estado, inicio, precio_desde
FROM reinvent.show_funcion
WHERE precio_desde IS NOT NULL AND inicio > now() AND inicio BETWEEN %s AND %s
"""


@sandbox.en_real
def funciones_de_ticketmaster() -> list[dict]:
    """Las funciones de la semana con precio (reinvent.show_funcion). Sin la key o sin la tabla, ninguna."""
    if not config.TICKETMASTER_API_KEY:
        return []
    try:
        with pg.pool().connection() as c:
            return c.execute(pg.catalogo(_FUNCIONES_SQL), (ticketmaster.DESDE, ticketmaster.HASTA)).fetchall()
    except psycopg.errors.UndefinedTable:
        log.warning("reinvent.show_funcion no existe todavía: sin ofertas de shows")
        return []


@sandbox.en_real
def guardar_snapshots(funciones: list[dict], tomado: float) -> None:
    filas = [(f["id_funcion"], tomado, f["precio_desde"]) for f in funciones if f.get("precio_desde") is not None]
    with db.conn() as c, c.cursor() as cur:
        cur.executemany("INSERT INTO precio_snapshot (id_funcion, tomado, precio) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", filas)


@sandbox.en_real
def historial(ids: list[str], desde_ts: float) -> dict[str, list[tuple[float, Decimal]]]:
    out: dict[str, list[tuple[float, Decimal]]] = {}
    with db.conn() as c:
        filas = c.execute("SELECT id_funcion, tomado, precio FROM precio_snapshot WHERE id_funcion = ANY(%s) AND tomado >= %s "
                          "ORDER BY tomado", (ids, desde_ts)).fetchall()
    for f in filas:
        out.setdefault(f["id_funcion"], []).append((f["tomado"], f["precio"]))
    return out


class FuenteTicketmaster:
    nombre = FUENTE_TICKETMASTER

    def __init__(self, funciones: Callable[[], list[dict]] = funciones_de_ticketmaster):
        self._funciones = funciones

    def ofertas(self, ahora: dt.datetime) -> list[Oferta]:
        funciones = self._funciones()
        ts = ahora.timestamp()
        guardar_snapshots(funciones, ts)
        ids = [f["id_funcion"] for f in funciones]
        return ofertas_de_bajas(funciones, historial(ids, ts - REFERENCIA_DIAS * 86400), ahora)


def fuentes_activas() -> list[Fuente]:
    return [FuenteTicketmaster()]


# ---------- el job ----------

@sandbox.en_real
def _ultima_corrida(fuente: str) -> float | None:
    with db.conn() as c:
        fila = c.execute("SELECT ultimo FROM oferta_job WHERE fuente=%s", (fuente,)).fetchone()
    return fila["ultimo"] if fila else None


@sandbox.en_real
def _marcar_corrida(fuente: str, ts: float) -> None:
    with db.conn() as c:
        c.execute("INSERT INTO oferta_job (fuente, ultimo) VALUES (%s,%s) ON CONFLICT (fuente) DO UPDATE SET ultimo=EXCLUDED.ultimo",
                  (fuente, ts))


@sandbox.en_real
def _purgar(ts: float) -> None:
    with db.conn() as c:
        c.execute("DELETE FROM precio_snapshot WHERE tomado < %s", (ts - SNAPSHOTS_DIAS * 86400,))


def correr_si_toca(ahora: dt.datetime, fuentes: list[Fuente] | None = None) -> int:
    """Pide las ofertas de cada fuente si pasaron OFERTAS_SNAPSHOT_HORAS desde la última vez, y guarda las nuevas.
    Devuelve cuántas ofertas nuevas entraron. Una fuente que falla no frena a las otras."""
    ts, nuevas = ahora.timestamp(), 0
    for fuente in fuentes if fuentes is not None else fuentes_activas():
        ultima = _ultima_corrida(fuente.nombre)
        if ultima is not None and ts - ultima < config.OFERTAS_SNAPSHOT_HORAS * 3600:
            continue
        try:
            nuevas += sum(guardar(o) for o in fuente.ofertas(ahora))
        except Exception:  # noqa: BLE001 — una fuente caída no corta el hilo de avisos
            log.exception("la fuente de ofertas %s falló", fuente.nombre)
            continue
        _marcar_corrida(fuente.nombre, ts)
    _purgar(ts)
    return nuevas


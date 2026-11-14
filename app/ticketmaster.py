"""Shows de Ticketmaster (Discovery API v2): conciertos, espectáculos, deportes y actividades en Las Vegas durante
re:Invent. Los pide la revisión automática (app/eventos_auto.py) y quedan en reinvent.show_funcion.

- Un pedido paginado por revisión: toda el área de Las Vegas (dmaId 319), del 29/11 al 4/12 en hora de Las Vegas. Si
  Ticketmaster dice que hay 1000 o más (lo máximo que deja paginar), se pide un día por vez.
- Limpieza: afuera estacionamiento, upgrades, paquetes, vouchers, lo que no tiene sala u hora, los pases de varios días
  y la reventa. Cada función guarda su show (artista o nombre + sala) para agruparlas en la lista.
- Estados: canceled, postponed, rescheduled y offsale se guardan tal cual (los avisos salen de app/eventos_avisos.py y
  de app/changes.py). Una función que deja de aparecer no se cancela: se consulta sola antes de tocarla.

La key va en la URL y Ticketmaster la repite en el cuerpo del 429: acá nunca se loguea una URL ni un cuerpo de error,
los errores llevan solo el código HTTP, y el logger de httpx (que loguea cada URL en INFO) queda en WARNING.
"""
import datetime as dt
import hashlib
import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import astuple, dataclass, field, fields
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("reinventar.ticketmaster")
# httpx loguea "HTTP Request: GET <url completa>" en INFO, y la URL lleva la key.
logging.getLogger("httpx").setLevel(logging.WARNING)

FUENTE = "ticketmaster"
URL_EVENTOS = "https://app.ticketmaster.com/discovery/v2/events.json"
URL_EVENTO = "https://app.ticketmaster.com/discovery/v2/events/{}.json"
DMA_LAS_VEGAS = 319
DESDE = dt.datetime(2026, 11, 29, 8, tzinfo=dt.UTC)          # 29/11 00:00 en Las Vegas
HASTA = dt.datetime(2026, 12, 5, 7, 59, 59, tzinfo=dt.UTC)   # 4/12 23:59:59 en Las Vegas
SEGMENTOS = {  # ids públicos de la Discovery API [verificar con la key]
    "KZFzniwnSyZfZ7v7nJ": "Music",
    "KZFzniwnSyZfZ7v7nE": "Sports",
    "KZFzniwnSyZfZ7v7na": "Arts & Theatre",
    "KZFzniwnSyZfZ7v7n1": "Miscellaneous",
}
POR_PAGINA = 200
TOPE_PAGINABLE = 1000          # Ticketmaster no deja pasar de size * page = 1000
MAX_CONSULTAS_SUELTAS = 40     # funciones que dejaron de aparecer, consultadas una por una en cada revisión
MIN_PROPORCION = 0.5           # si vino menos que esto de lo que venía, no se consulta ninguna faltante
_ID_VALIDO = re.compile(r"^[\w-]{1,64}$")

TIPOS = ("musica", "teatro", "comedia", "deportes", "actividades")
_TIPO_POR_SEGMENTO = {"Music": "musica", "Sports": "deportes", "Arts & Theatre": "teatro",
                      "Miscellaneous": "actividades"}
ESTADOS = {"onsale": "onsale", "offsale": "offsale", "canceled": "canceled", "cancelled": "canceled",
           "postponed": "postponed", "rescheduled": "rescheduled"}
# Clasificaciones que no son un show: productos que Ticketmaster vende como "eventos" [verificar].
_CLASES_RUIDO = {"upsell", "parking", "add-on", "addon", "add on"}
_NOMBRE_RUIDO = re.compile(r"parking|upgrade|vip\s+package|voucher|gift\s*card|souvenir|add-on", re.I)
_FUENTES_REVENTA = {"tmr", "ticketmaster resale"}


class ErrorTicketmaster(Exception):
    """Ticketmaster no respondió bien. El mensaje nunca lleva la URL ni el cuerpo (los dos pueden traer la key)."""


class NoExiste(ErrorTicketmaster):
    """404: la función ya no está en Ticketmaster."""


@dataclass(frozen=True)
class Funcion:
    id_funcion: str
    id_show: str
    nombre: str
    artista: str | None
    tipo: str
    sala: str
    direccion: str | None
    lat: float | None
    lng: float | None
    inicio: dt.datetime
    estado: str
    precio_desde: Decimal | None
    imagen_url: str | None
    url: str | None


COLUMNAS = tuple(f.name for f in fields(Funcion))


@dataclass(frozen=True)
class Lectura:
    funciones: tuple[Funcion, ...] = ()
    sueltas: dict[str, Funcion | None] = field(default_factory=dict)  # id → función actualizada, o None si dio 404
    partida: bool = False                                                # se pidió un día por vez
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# ---------- pedidos ----------

def sin_key(texto: str) -> str:
    """Por las dudas: tapa cualquier apikey=... de un texto antes de loguearlo o guardarlo."""
    return re.sub(r"(apikey=)[^&\s'\"]+", r"\1***", texto, flags=re.I)


def _pedir(http: httpx.Client, url: str, params: dict, key: str) -> dict:
    try:
        r = http.get(url, params={**params, "apikey": key})
    except httpx.HTTPError as e:
        raise ErrorTicketmaster(f"sin respuesta ({type(e).__name__})") from None
    if r.status_code == 404:
        raise NoExiste("HTTP 404")
    if r.status_code >= 400:
        raise ErrorTicketmaster(f"HTTP {r.status_code}")  # sin el cuerpo: el 429 repite la key
    try:
        datos = r.json()
    except ValueError:
        raise ErrorTicketmaster("respuesta que no es JSON") from None
    if not isinstance(datos, dict):
        raise ErrorTicketmaster("respuesta inesperada")
    return datos


def _iso(momento: dt.datetime) -> str:
    return momento.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def consulta(desde: dt.datetime, hasta: dt.datetime) -> dict:
    return {"dmaId": DMA_LAS_VEGAS, "startDateTime": _iso(desde), "endDateTime": _iso(hasta),
            "segmentId": ",".join(SEGMENTOS), "size": POR_PAGINA, "sort": "date,asc"}


def _paginas(http, key, desde, hasta, pausa) -> tuple[list[dict], int]:
    """(eventos crudos, totalElements) de un rango, hasta donde deja paginar Ticketmaster."""
    eventos, total = [], 0
    for pagina in range(TOPE_PAGINABLE // POR_PAGINA):
        if pagina:
            pausa()
        datos = _pedir(http, URL_EVENTOS, {**consulta(desde, hasta), "page": pagina}, key)
        info = datos.get("page") or {}
        total = int(info.get("totalElements") or 0)
        eventos += (datos.get("_embedded") or {}).get("events") or []
        if pagina + 1 >= int(info.get("totalPages") or 0):
            break
    return eventos, total


def dias(desde: dt.datetime = DESDE, hasta: dt.datetime = HASTA) -> list[tuple[dt.datetime, dt.datetime]]:
    """Los rangos de un día (de Las Vegas) entre desde y hasta."""
    rangos, inicio = [], desde
    while inicio < hasta:
        fin = min(inicio + dt.timedelta(days=1, seconds=-1), hasta)
        rangos.append((inicio, fin))
        inicio += dt.timedelta(days=1)
    return rangos


def bajar(http: httpx.Client, key: str, pausa: Callable[[], None]) -> tuple[list[dict], bool]:
    """(eventos crudos de toda la semana, si hubo que partir por día)."""
    eventos, total = _paginas(http, key, DESDE, HASTA, pausa)
    if total < TOPE_PAGINABLE:
        return eventos, False
    log.info("ticketmaster: %d funciones en la semana, se pide un día por vez", total)
    todos = []
    for desde, hasta in dias():
        pausa()
        del_dia, total_dia = _paginas(http, key, desde, hasta, pausa)
        if total_dia >= TOPE_PAGINABLE:
            log.warning("ticketmaster: %s trae %d funciones; quedan las primeras %d", desde.date(), total_dia,
                        TOPE_PAGINABLE)
        todos += del_dia
    return todos, True


# ---------- limpieza ----------

def _nombre(clase: dict | None) -> str:
    return str((clase or {}).get("name") or "").strip()


def _clasificacion(ev: dict) -> dict:
    clases = [c for c in ev.get("classifications") or [] if isinstance(c, dict)]
    return next((c for c in clases if c.get("primary")), clases[0] if clases else {})


def _es_reventa(ev: dict) -> bool:
    fuente = ev.get("source")
    nombre = fuente.get("name") if isinstance(fuente, dict) else fuente
    return str(nombre or "").strip().lower() in _FUENTES_REVENTA


def _venue(ev: dict) -> dict | None:
    venues = ((ev.get("_embedded") or {}).get("venues") or [])
    v = venues[0] if venues and isinstance(venues[0], dict) else None
    return v if v and v.get("id") and _nombre(v) else None


def descarte(ev: dict) -> str | None:
    """Por qué no es un show que sirva (None si sirve)."""
    if not isinstance(ev, dict) or not ev.get("id") or not ev.get("name"):
        return "incompleto"
    c = _clasificacion(ev)
    clases = {_nombre(c.get(k)).lower() for k in ("type", "subType", "genre", "subGenre")}
    # "Undefined" solo cuenta en el segmento: Ticketmaster lo pone de tipo y género en muchísimos shows normales.
    if clases & _CLASES_RUIDO or _nombre(c.get("segment")).lower() == "undefined":
        return "clasificación"
    if _NOMBRE_RUIDO.search(ev["name"]):
        return "nombre"
    if not _venue(ev):
        return "sin sala"
    fechas = ev.get("dates") or {}
    inicio = fechas.get("start") or {}
    if inicio.get("noSpecificTime") or inicio.get("timeTBA") or inicio.get("dateTBA") or not inicio.get("dateTime"):
        return "sin hora"
    if fechas.get("spanMultipleDays"):
        return "varios días"
    if _es_reventa(ev):
        return "reventa"
    return None


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes.lower()).strip()


def id_show(ev: dict) -> str:
    """El show de una función: su artista (o el nombre normalizado si no tiene) en esa sala."""
    atracciones = (ev.get("_embedded") or {}).get("attractions") or []
    clave = f"a:{atracciones[0]['id']}" if atracciones and atracciones[0].get("id") else f"n:{_plano(ev['name'])}"
    return hashlib.sha1(f"{clave}|{_venue(ev)['id']}".encode()).hexdigest()[:12]


def tipo(ev: dict) -> str:
    c = _clasificacion(ev)
    if _nombre(c.get("genre")).lower() == "comedy":
        return "comedia"
    return _TIPO_POR_SEGMENTO.get(_nombre(c.get("segment")), "actividades")


def _https(url) -> str | None:
    return url if isinstance(url, str) and urlsplit(url).scheme == "https" and urlsplit(url).netloc else None


def imagen(ev: dict) -> str | None:
    """La imagen 16:9 más chica que llene una tarjeta (de 640 px de ancho para arriba), o la más grande que haya."""
    imagenes = [i for i in ev.get("images") or [] if isinstance(i, dict) and _https(i.get("url"))]
    if not imagenes:
        return None
    ancho = lambda i: int(i.get("width") or 0)  # noqa: E731
    anchas = [i for i in imagenes if i.get("ratio") == "16_9"] or imagenes
    grandes = [i for i in anchas if ancho(i) >= 640]
    elegida = min(grandes, key=ancho) if grandes else max(anchas, key=ancho)
    return elegida["url"]


def precio_desde(ev: dict) -> Decimal | None:
    """El mínimo en dólares, solo si Ticketmaster trae precios."""
    minimos = []
    for p in ev.get("priceRanges") or []:
        if not isinstance(p, dict) or (p.get("currency") or "USD") != "USD":
            continue
        try:
            valor = Decimal(str(p.get("min")))
        except InvalidOperation:
            continue
        if valor.is_finite() and valor > 0:
            minimos.append(valor)
    return min(minimos).quantize(Decimal("0.01")) if minimos else None


def _coordenada(texto) -> float | None:
    try:
        return round(float(texto), 6)
    except (TypeError, ValueError):
        return None


def _direccion(v: dict) -> str | None:
    partes = [(v.get("address") or {}).get("line1"), (v.get("city") or {}).get("name")]
    return ", ".join(p.strip() for p in partes if isinstance(p, str) and p.strip()) or None


def funcion(ev: dict) -> Funcion | None:
    """La función limpia, o None si es ruido."""
    if descarte(ev):
        return None
    v, fechas = _venue(ev), ev["dates"]
    atracciones = (ev.get("_embedded") or {}).get("attractions") or []
    ubicacion = v.get("location") or {}
    estado = ESTADOS.get(str((fechas.get("status") or {}).get("code") or "").lower(), "onsale")
    return Funcion(
        id_funcion=str(ev["id"]), id_show=id_show(ev), nombre=str(ev["name"]).strip(),
        artista=_nombre(atracciones[0]) or None if atracciones else None, tipo=tipo(ev), sala=_nombre(v),
        direccion=_direccion(v), lat=_coordenada(ubicacion.get("latitude")), lng=_coordenada(ubicacion.get("longitude")),
        inicio=dt.datetime.fromisoformat(fechas["start"]["dateTime"].replace("Z", "+00:00")).astimezone(dt.UTC),
        estado=estado, precio_desde=precio_desde(ev), imagen_url=imagen(ev), url=_https(ev.get("url")))


def limpiar(eventos: list[dict]) -> list[Funcion]:
    """Funciones limpias, sin repetidas: el mismo id una vez, y el mismo show a la misma hora una vez (la reventa
    publica la misma función con otro id)."""
    vistas, por_horario, out = set(), set(), []
    for ev in eventos:
        f = funcion(ev)
        if not f or f.id_funcion in vistas or (f.id_show, f.inicio) in por_horario:
            continue
        vistas.add(f.id_funcion)
        por_horario.add((f.id_show, f.inicio))
        out.append(f)
    return out


# ---------- revisión ----------

def faltantes(funciones: tuple[Funcion, ...], actuales: dict, ahora: dt.datetime) -> list[str]:
    """Funciones futuras de la base que no vinieron en esta lectura (y no están canceladas)."""
    leidas = {f.id_funcion for f in funciones}
    return sorted(i for i, a in actuales.items()
                  if i not in leidas and a["inicio"] > ahora and a["estado"] != "canceled")


def consultar_sueltas(http, key, ids: list[str], pausa) -> dict[str, Funcion | None]:
    """Cada faltante, una por una: la función como está ahora (otra fecha, cancelada…), None si ya no existe (404).
    Lo que no se pudo consultar no entra (queda como estaba)."""
    sueltas: dict[str, Funcion | None] = {}
    for i in ids[:MAX_CONSULTAS_SUELTAS]:
        if not _ID_VALIDO.match(i):
            continue
        pausa()
        try:
            ev = _pedir(http, URL_EVENTO.format(i), {}, key)
        except NoExiste:
            sueltas[i] = None
            continue
        except ErrorTicketmaster as e:
            log.info("ticketmaster: no pude consultar la función %s: %s", i, e)
            continue
        if f := funcion(ev):
            sueltas[i] = f
    return sueltas


def leer(http: httpx.Client, key: str, actuales: dict, total_previo: int | None, ahora: dt.datetime,
         pausa: Callable[[], None]) -> Lectura:
    """Una lectura completa: la semana, y las funciones que faltan consultadas una por una."""
    try:
        crudos, partida = bajar(http, key, pausa)
    except (ErrorTicketmaster, ValueError, KeyError, TypeError) as e:
        error = sin_key(str(e)) if isinstance(e, ErrorTicketmaster) else type(e).__name__
        log.warning("fuente ticketmaster: %s", error)
        return Lectura(error=error)
    funciones = tuple(limpiar(crudos))
    futuras = sum(f.inicio > ahora for f in funciones)
    if total_previo and futuras < MIN_PROPORCION * total_previo:
        log.warning("ticketmaster trajo %d funciones (antes %d): no se consulta ninguna faltante", futuras, total_previo)
        return Lectura(funciones, partida=partida)
    return Lectura(funciones, consultar_sueltas(http, key, faltantes(funciones, actuales, ahora), pausa), partida)


_LEER_SQL = f"SELECT {', '.join(COLUMNAS)} FROM show_funcion"


def leer_actuales(cur) -> dict[str, dict]:
    """Las funciones guardadas (con el search_path del schema destino). UndefinedTable si falta la migración 009."""
    return {f[0]: dict(zip(COLUMNAS, f, strict=True)) for f in cur.execute(_LEER_SQL).fetchall()}


def _igual(f: Funcion, actual: dict) -> bool:
    def norm(c, v):
        if v is None:
            return None
        if c in ("lat", "lng"):
            return round(float(v), 6)
        if c == "precio_desde":
            return Decimal(v).quantize(Decimal("0.01"))
        return v
    return all(norm(c, getattr(f, c)) == norm(c, actual[c]) for c in COLUMNAS)


_UPSERT = (f"INSERT INTO show_funcion ({', '.join(COLUMNAS)}) VALUES ({', '.join(['%s'] * len(COLUMNAS))}) "
           f"ON CONFLICT (id_funcion) DO UPDATE SET "
           f"{', '.join(f'{c} = EXCLUDED.{c}' for c in COLUMNAS[1:])}, actualizado = now()")
DIAS_HASTA_BORRAR = 1


def guardar(cur, lectura: Lectura, actuales: dict, ahora: dt.datetime) -> dict:
    """Escribe lo nuevo y lo que cambió, cancela lo que ya no existe y borra lo que pasó hace más de un día. Devuelve
    el conteo para evento_revision."""
    conteo = {"total": 0, "nuevos": 0, "cambiados": 0, "cancelados": 0, "pendientes": 0}
    if not lectura.ok:
        return conteo
    conteo["total"] = sum(f.inicio > ahora for f in lectura.funciones)
    a_guardar = [*lectura.funciones, *(f for f in lectura.sueltas.values() if f)]
    for f in a_guardar:
        actual = actuales.get(f.id_funcion)
        if actual and _igual(f, actual):
            continue
        cur.execute(_UPSERT, astuple(f))
        if not actual:
            conteo["nuevos"] += 1
            continue
        conteo["cambiados"] += 1
        if f.estado == "canceled" and actual["estado"] != "canceled":
            conteo["cancelados"] += 1
    for i, f in lectura.sueltas.items():
        if f is None and i in actuales and actuales[i]["estado"] != "canceled":
            cur.execute("UPDATE show_funcion SET estado = 'canceled', actualizado = now() WHERE id_funcion = %s", (i,))
            conteo["cancelados"] += 1
    cur.execute("DELETE FROM show_funcion WHERE inicio < %s", (ahora - dt.timedelta(days=DIAS_HASTA_BORRAR),))
    return conteo

"""Lectura de eventos de networking desde sus fuentes (funciones puras, sin base ni red).

- Luma: el export (entries[] con name, start_at, cover_url, coordinate, href, event_api_id) o el calendario público
  (api.lu.ma/calendar/get-items) traen lo básico; la página pública del evento (JSON en <script id="__NEXT_DATA__">)
  suma fin, dirección, descripción, anotados, precio y aprobación.
- conferenceparties.com: una tabla HTML por día (hora, sponsor, nombre con link, lugar). Los que llevan a Luma se
  completan con la página de Luma; el resto queda con lo que dice la tabla.
- Página suelta (un link que pega el admin): título, descripción, imagen y datos estructurados (og:*, JSON-LD).
"""
import datetime as dt
import hashlib
import html as html_lib
import json
import re
from dataclasses import dataclass, replace
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .travel import metros

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
TZ_VEGAS = ZoneInfo("America/Los_Angeles")
_HOSTS_LUMA = ("luma.com", "lu.ma", "www.luma.com")


@dataclass(frozen=True)
class Evento:
    id_evento: str
    plataforma: str
    url: str
    nombre: str
    inicio: dt.datetime
    fin: dt.datetime | None = None
    imagen_url: str | None = None
    lat: float | None = None
    lng: float | None = None
    lugar: str | None = None
    direccion: str | None = None
    direccion_exacta: bool = False
    google_place_id: str | None = None
    descripcion: str | None = None
    anotados: int | None = None
    lleno: bool = False
    precio: str | None = None
    requiere_aprobacion: bool = False


def _fecha(valor: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(valor.replace("Z", "+00:00")) if valor else None


def desde_json_luma(entrada: dict) -> Evento:
    coord = entrada.get("coordinate") or {}
    return Evento(
        id_evento=entrada["event_api_id"], plataforma="luma", url=entrada["href"], nombre=entrada["name"].strip(),
        inicio=_fecha(entrada["start_at"]), imagen_url=entrada.get("cover_url"),
        lat=coord.get("latitude"), lng=coord.get("longitude"))


def slug_luma(url: str | None) -> str | None:
    """'https://luma.com/abc123?utm=x' → 'abc123'; None si no es un link a un evento de Luma."""
    if not url:
        return None
    partes = urlsplit(url if "://" in url else f"https://{url}")
    camino = partes.path.strip("/")
    if partes.hostname not in _HOSTS_LUMA or not camino or "/" in camino:
        return None
    return camino.lower()


def url_luma(slug: str) -> str:
    return f"https://luma.com/{slug}"


def desde_item_calendario(entrada: dict) -> Evento:
    """Un item de api.lu.ma/calendar/get-items (entries[].event)."""
    ev = entrada["event"]
    coord = ev.get("coordinate") or {}
    return Evento(
        id_evento=ev["api_id"], plataforma="luma", url=url_luma(ev["url"]), nombre=ev["name"].strip(),
        inicio=_fecha(ev["start_at"]), fin=_fecha(ev.get("end_at")), imagen_url=ev.get("cover_url"),
        lat=coord.get("latitude"), lng=coord.get("longitude"))


def desde_pagina_luma(html: str) -> Evento | None:
    """El evento completo a partir de su página pública de Luma (el objeto event tiene la forma del calendario).
    None si la página no tiene los datos esperados."""
    m = _NEXT_DATA.search(html or "")
    try:
        ev = desde_item_calendario({"event": json.loads(m.group(1))["props"]["pageProps"]["initialData"]["data"]["event"]}) \
            if m else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return completar_con_pagina_luma(ev, html) if ev else None


def texto_de_mirror(nodo: dict | list | None) -> str:
    """Texto plano de una descripción en formato ProseMirror (párrafos separados por línea en blanco)."""
    if not nodo:
        return ""
    if isinstance(nodo, list):
        return "".join(texto_de_mirror(n) for n in nodo)
    tipo = nodo.get("type")
    if tipo == "text":
        return nodo.get("text", "")
    if tipo == "hard_break":
        return "\n"
    interior = texto_de_mirror(nodo.get("content"))
    if tipo == "list_item":
        return f"- {interior.strip()}\n"
    if tipo in ("paragraph", "heading", "bullet_list", "ordered_list", "blockquote"):
        return interior.strip() + "\n\n"
    return interior


def _precio(tickets: list[dict]) -> tuple[str | None, bool]:
    """("Gratis" | "USD 50" | None, requiere aprobación) a partir de los tipos de entrada."""
    if not tickets:
        return None, False
    aprobacion = any(t.get("require_approval") for t in tickets)
    pagos = [t for t in tickets if t.get("type") != "free" and t.get("cents")]
    if not pagos:
        return "Gratis", aprobacion
    barata = min(pagos, key=lambda t: t["cents"])
    return f"{(barata.get('currency') or 'usd').upper()} {barata['cents'] / 100:g}", aprobacion


def completar_con_pagina_luma(ev: Evento, html: str) -> Evento:
    """Suma lo que trae la página pública. Si la página no tiene los datos esperados, devuelve el evento como estaba."""
    m = _NEXT_DATA.search(html or "")
    if not m:
        return ev
    try:
        data = json.loads(m.group(1))["props"]["pageProps"]["initialData"]["data"]
        evento = data["event"]
    except (ValueError, KeyError, TypeError):
        return ev
    geo = evento.get("geo_address_info") or {}
    lugar = geo.get("address")
    exacta = bool(lugar) and lugar != geo.get("city")  # solo la ciudad = la dirección se ve al anotarte
    lugar_coord = geo.get("place_coordinate") or {}
    precio, aprobacion = _precio(data.get("ticket_types") or [])
    return replace(
        ev,
        fin=_fecha(evento.get("end_at")) or ev.fin,
        lugar=lugar if exacta else None,
        direccion=geo.get("full_address") if exacta else None,
        direccion_exacta=exacta,
        google_place_id=geo.get("place_id") if exacta else None,
        lat=lugar_coord.get("latitude", ev.lat) if exacta else ev.lat,
        lng=lugar_coord.get("longitude", ev.lng) if exacta else ev.lng,
        descripcion=texto_de_mirror(data.get("description_mirror")).strip() or None,
        anotados=data.get("guest_count"),
        lleno=bool(data.get("sold_out")),
        precio=precio,
        requiere_aprobacion=aprobacion,
    )


def sede_mas_cercana(ev: Evento, sedes: list[tuple[int, float, float]]) -> tuple[int | None, int | None]:
    """(id_sede, metros) de la sede de re:Invent más cercana; (None, None) sin coordenadas."""
    if ev.lat is None or not sedes:
        return None, None
    id_sede, dist = min(((i, metros((ev.lat, ev.lng), (lat, lng))) for i, lat, lng in sedes), key=lambda t: t[1])
    return id_sede, round(dist)


# ---------- conferenceparties.com ----------

_FILA = re.compile(r"<tr\b.*?</tr>", re.S)
_DIA = re.compile(r"<h2>\s*\w+\s*-\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})\s*</h2>")
_CELDA = re.compile(r'<td class="column-(\d)"[^>]*>(.*?)</td>', re.S)
_LINK = re.compile(r'<a\s[^>]*href="([^"]+)"', re.S)
_ETIQUETA = re.compile(r"<[^>]+>")
_TOOLTIP = re.compile(r"<span class='tooltips.*?</span>", re.S)
_HORA = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?\s*–\s*(?:(\d{1,2})(?::(\d{2}))?\s*(AM|PM))?", re.I)
_SIN_DIRECCION = ("register to see address", "tbd", "tba")
HORA_TARDE_POR_DEFECTO = 18  # "Evening–"


def _texto(fragmento: str) -> list[str]:
    """Las líneas de texto de una celda (cada <br> separa una línea)."""
    sin_tooltip = _TOOLTIP.sub("", fragmento)
    lineas = re.split(r"<br\s*/?>", sin_tooltip)
    return [t for t in (html_lib.unescape(_ETIQUETA.sub("", x)).strip() for x in lineas) if t]


def _a_24(hora: int, minutos: int, meridiano: str | None) -> tuple[int, int]:
    if meridiano and meridiano.upper() == "PM" and hora != 12:
        hora += 12
    elif meridiano and meridiano.upper() == "AM" and hora == 12:
        hora = 0
    return hora, minutos


def horario(texto: str, dia: dt.date) -> tuple[dt.datetime, dt.datetime | None] | None:
    """'6–9PM' → (18:00, 21:00) en hora de Las Vegas; '7PM–1AM' termina al otro día; '6PM–' sin fin."""
    m = _HORA.search(texto or "")
    if not m:
        return (dt.datetime.combine(dia, dt.time(HORA_TARDE_POR_DEFECTO), TZ_VEGAS), None) \
            if "evening" in (texto or "").lower() else None
    h1, m1, mer1, h2, m2, mer2 = m.groups()
    fin_hm = _a_24(int(h2), int(m2 or 0), mer2) if h2 else None
    ini_hm = _a_24(int(h1), int(m1 or 0), mer1 or mer2)
    if not mer1 and fin_hm and ini_hm > fin_hm and ini_hm[0] >= 12:  # "11–1PM": empieza a la mañana
        ini_hm = (ini_hm[0] - 12, ini_hm[1])
    if not 0 <= ini_hm[0] < 24 or (fin_hm and not 0 <= fin_hm[0] < 24):
        return None
    inicio = dt.datetime.combine(dia, dt.time(*ini_hm), TZ_VEGAS)
    if not fin_hm:
        return inicio, None
    fin = dt.datetime.combine(dia, dt.time(*fin_hm), TZ_VEGAS)
    return inicio, fin if fin > inicio else fin + dt.timedelta(days=1)


def _id_conferenceparties(url: str, nombre: str, dia: dt.date) -> str:
    return "cp-" + hashlib.sha256(f"{url}|{nombre.lower()}|{dia.isoformat()}".encode()).hexdigest()[:12]


def _evento_de_fila(celdas: dict[str, str], dia: dt.date, pagina: str) -> Evento | None:
    nombre = (_texto(celdas.get("3", "")) or [""])[0].rstrip(" -–")
    cuando = horario(" ".join(_texto(celdas.get("1", ""))), dia)
    if not nombre or not cuando:
        return None
    link = _LINK.search(celdas.get("3", ""))
    url = html_lib.unescape(link.group(1)) if link else pagina
    if not url.startswith("https://"):
        url = pagina
    lugar = _texto(celdas.get("4", ""))
    if lugar and lugar[0].lower() in _SIN_DIRECCION:
        lugar = []
    sponsor = " ".join(_texto(celdas.get("2", "")))
    slug = slug_luma(url)
    return Evento(
        id_evento=f"luma-{slug}" if slug else _id_conferenceparties(url, nombre, dia),
        plataforma="luma" if slug else "conferenceparties", url=url_luma(slug) if slug else url, nombre=nombre,
        inicio=cuando[0], fin=cuando[1], lugar=lugar[0] if lugar else None,
        direccion=" · ".join(lugar[1:]) or None if lugar else None,
        descripcion=f"Sponsor: {sponsor}" if sponsor else None)


def desde_conferenceparties(html: str, pagina: str) -> list[Evento]:
    """Los eventos de la tabla (sin repetidos). Los que llevan a Luma salen con id luma-<slug> hasta completarlos."""
    eventos: dict[str, Evento] = {}
    dia = None
    for fila in _FILA.findall(html or ""):
        if m := _DIA.search(fila):
            dia = dt.datetime.strptime(re.sub(r"\s+", " ", m.group(1)), "%B %d, %Y").date()
            continue
        celdas = dict(_CELDA.findall(fila))
        if dia is None or "5" not in celdas or "<b>Time</b>" in fila:
            continue
        if ev := _evento_de_fila(celdas, dia, pagina):
            eventos.setdefault(ev.id_evento, ev)
    return list(eventos.values())


# ---------- página suelta ----------

_META = re.compile(r'<meta\s+[^>]*(?:property|name)="(og:[a-z_:]+|description)"[^>]*content="([^"]*)"', re.I)
_META_INV = re.compile(r'<meta\s+[^>]*content="([^"]*)"[^>]*(?:property|name)="(og:[a-z_:]+|description)"', re.I)
_TITULO = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_JSONLD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_SCRIPTS = re.compile(r"<(script|style|noscript|svg)\b.*?</\1>", re.S | re.I)
MAX_TEXTO_PAGINA = 6000


def _eventos_jsonld(nodo) -> list[dict]:
    if isinstance(nodo, list):
        return [e for n in nodo for e in _eventos_jsonld(n)]
    if not isinstance(nodo, dict):
        return []
    tipo = nodo.get("@type")
    tipos = tipo if isinstance(tipo, list) else [tipo]
    propios = [nodo] if any(isinstance(t, str) and t.endswith("Event") for t in tipos) else []
    return propios + _eventos_jsonld(nodo.get("@graph"))


def datos_de_pagina(html: str) -> dict:
    """Lo que se puede sacar sin LLM de una página cualquiera: título, descripción, imagen, el primer Event de JSON-LD
    (si tiene) y el texto visible recortado (para que el LLM saque fecha, hora y lugar)."""
    html = html or ""
    meta = {k.lower(): html_lib.unescape(v).strip() for k, v in _META.findall(html)}
    meta |= {k.lower(): html_lib.unescape(v).strip() for v, k in _META_INV.findall(html) if k.lower() not in meta}
    titulo = _TITULO.search(html)
    evento_ld = {}
    for bloque in _JSONLD.findall(html):
        try:
            encontrados = _eventos_jsonld(json.loads(bloque))
        except ValueError:
            continue
        if encontrados:
            evento_ld = encontrados[0]
            break
    texto = html_lib.unescape(_ETIQUETA.sub(" ", _SCRIPTS.sub(" ", html)))
    imagen = meta.get("og:image")
    return {
        "titulo": meta.get("og:title") or (html_lib.unescape(titulo.group(1)).strip() if titulo else None),
        "descripcion": meta.get("og:description") or meta.get("description"),
        "imagen": imagen if imagen and imagen.startswith("https://") else None,
        "jsonld": evento_ld,
        "texto": re.sub(r"\s+", " ", texto).strip()[:MAX_TEXTO_PAGINA],
    }


# ---------- sede por el texto del lugar ----------

# Lugares conocidos que no nombran a la sede: el texto que aparece → la sede del maestro (reinvent.sede).
_ALIAS_SEDES = {"palazzo": "Venetian", "canal shoppes": "Venetian", "forum shops": "Caesars Palace",
                "encore": "Wynn/Encore", "wynn": "Wynn/Encore"}


def sede_por_texto(ev: Evento, sedes: list[tuple[int, str, float, float]]) -> Evento:
    """Para un evento sin coordenadas, ubica la sede de re:Invent que nombra el lugar ("Delmonico · The Venetian" →
    Venetian) y le pone sus coordenadas (aproximadas: direccion_exacta queda en False). Sin coincidencia, igual."""
    if ev.lat is not None:
        return ev
    texto = " ".join(filter(None, (ev.lugar, ev.direccion))).lower()
    if not texto:
        return ev
    por_nombre = {nombre: (lat, lng) for _i, nombre, lat, lng in sedes}
    claves = {**{n.lower(): n for n in por_nombre}, **{p.lower(): n for n in por_nombre for p in n.split("/")},
              **{a: n for a, n in _ALIAS_SEDES.items() if n in por_nombre}}
    for clave in sorted(claves, key=len, reverse=True):
        if re.search(rf"\b{re.escape(clave)}\b", texto):
            lat, lng = por_nombre[claves[clave]]
            return replace(ev, lat=lat, lng=lng)
    return ev

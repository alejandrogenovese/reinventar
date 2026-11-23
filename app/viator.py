"""Excursiones de Viator (Partner API v2, acceso Basic de afiliado) para la pestaña Excursiones de Actividades.

- Búsqueda: POST /products/search en el destino Las Vegas, para los días de la estadía (app/estadia.py), de a 50
  productos por página. Los términos piden paginar solo cuando la persona pide más: la primera página sale al abrir la
  pestaña y las siguientes con «Ver más», hasta MAX_PAGINAS.
- Cache: solo en memoria y por 1 h, que es lo máximo que dejan guardar una búsqueda. Nada va a la base.
- Categorías: GET /products/tags (los términos dejan cachearlo una semana) da el árbol de tags; cada producto cae en la
  primera categoría que matchee alguno de sus tags o sus ancestros. Si no hay tags, la lista va sin agrupar.
- La clave va en el header exp-api-key: nunca se loguea, los errores llevan solo el código HTTP, y el logger de httpx
  queda en WARNING como en app/ticketmaster.py.

Docs: https://docs.viator.com/partner-api/technical/ y
https://partnerresources.viator.com/travel-commerce/technical-guide/
"""
import datetime as dt
import logging
import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from . import config
from .estadia import FIN_DE_LA_ESTADIA, INICIO_DE_LA_ESTADIA, TZ_VEGAS

log = logging.getLogger("reinventar.viator")
logging.getLogger("httpx").setLevel(logging.WARNING)

URL_BASE = "https://api.viator.com/partner"   # sandbox: https://api.sandbox.viator.com/partner
URL_BUSQUEDA = f"{URL_BASE}/products/search"
URL_TAGS = f"{URL_BASE}/products/tags"
DESTINO_LAS_VEGAS = "684"                      # viator.com/Las-Vegas/d684 [verificar con la key en /destinations]
MONEDA = "USD"
IDIOMA = "es"
POR_PAGINA = 50                                # máximo que acepta /products/search
MAX_PAGINAS = 4                                # 200 excursiones alcanzan para una semana
TIMEOUT_S = 15
TTL_BUSQUEDA_S = 3600                          # los términos permiten cachear una búsqueda hasta 1 h
TTL_TAGS_S = 7 * 24 * 3600                     # y los tags una semana
ANCHO_FOTO = 480                               # la variante de foto más chica que llegue a este ancho
HOSTS_VIATOR = ("viator.com", "www.viator.com")

# (clave, nombre en pantalla, palabras del nombre en inglés del tag o de sus ancestros). Gana la primera que matchea.
CATEGORIAS = (
    ("excursiones", "Excursiones de un día", ("day trip",)),
    ("aire_libre", "Aire libre", ("outdoor", "nature", "hiking", "national park")),
    ("atracciones", "Atracciones", ("attraction", "ticket", "museum", "pass")),
    ("tours", "Tours y paseos", ("tour", "sightseeing", "cruise")),
)
OTRAS = ("otras", "Otras actividades")


class ViatorNoDisponible(RuntimeError):
    """Viator no respondió bien. El mensaje nunca lleva la clave ni el cuerpo de la respuesta."""


class SinClave(ViatorNoDisponible):
    """Falta VIATOR_API_KEY: la pestaña no se muestra."""


_cache_busqueda: dict[int, tuple[float, dict]] = {}
_cache_tags: dict[str, tuple[float, dict[int, dict]]] = {}
_lock = threading.Lock()


def reiniciar() -> None:
    """Para los tests."""
    with _lock:
        _cache_busqueda.clear()
        _cache_tags.clear()


def habilitado() -> bool:
    return bool(config.VIATOR_API_KEY)


def _headers() -> dict:
    if not config.VIATOR_API_KEY:
        raise SinClave("Falta VIATOR_API_KEY")
    return {"exp-api-key": config.VIATOR_API_KEY, "Accept": "application/json;version=2.0",
            "Accept-Language": IDIOMA, "Content-Type": "application/json"}


def _respuesta(r: httpx.Response) -> dict:
    if r.status_code != 200:
        raise ViatorNoDisponible(f"Viator respondió {r.status_code}")
    try:
        return r.json()
    except ValueError as e:
        raise ViatorNoDisponible("Viator respondió algo que no es JSON") from e


# ---- parseo -------------------------------------------------------------------------------------------------------
def _foto(imagenes: list[dict]) -> str | None:
    """La portada (o la primera), en la variante más chica que llegue a ANCHO_FOTO (si ninguna llega, la más grande)."""
    if not imagenes:
        return None
    portada = next((i for i in imagenes if i.get("isCover")), imagenes[0])
    variantes = sorted((v for v in portada.get("variants") or [] if _url_segura(v.get("url"))),
                       key=lambda v: v.get("width") or 0)
    if not variantes:
        return None
    return next((v for v in variantes if (v.get("width") or 0) >= ANCHO_FOTO), variantes[-1])["url"]


def _url_segura(url: object) -> bool:
    return isinstance(url, str) and url.startswith("https://")


def _link_viator(url: object) -> str | None:
    """El productUrl va tal cual (lleva los parámetros de afiliado), pero solo si es https y de viator.com."""
    if not _url_segura(url):
        return None
    host = urlsplit(url).hostname or ""
    return url if host in HOSTS_VIATOR or host.endswith(".viator.com") else None


def _duracion(d: dict | None) -> tuple[int | None, int | None]:
    d = d or {}
    if d.get("fixedDurationInMinutes"):
        return d["fixedDurationInMinutes"], d["fixedDurationInMinutes"]
    return d.get("variableDurationFromMinutes"), d.get("variableDurationToMinutes")


def leer_producto(p: dict) -> dict | None:
    """Sin código, título o link de reserva no sirve: se descarta."""
    link = _link_viator(p.get("productUrl"))
    if not p.get("productCode") or not p.get("title") or not link:
        return None
    resenas = p.get("reviews") or {}
    pricing = p.get("pricing") or {}
    desde, hasta = _duracion(p.get("duration"))
    return {"codigo": p["productCode"], "titulo": p["title"], "foto": _foto(p.get("images") or []),
            "precio_desde": (pricing.get("summary") or {}).get("fromPrice"), "moneda": pricing.get("currency") or MONEDA,
            "rating": resenas.get("combinedAverageRating"), "resenas": resenas.get("totalReviews") or 0,
            "minutos_desde": desde, "minutos_hasta": hasta, "url": link,
            "tags": [t for t in p.get("tags") or [] if isinstance(t, int)]}


def leer_busqueda(data: dict) -> dict:
    productos = [x for p in data.get("products") or [] if (x := leer_producto(p))]
    return {"productos": productos, "total": int(data.get("totalCount") or 0)}


def leer_tags(data: dict | list) -> dict[int, dict]:
    """{tagId: {nombre (en inglés, para clasificar), padres}}. Acepta la lista sola o {"tags": [...]}."""
    tags = data.get("tags") if isinstance(data, dict) else data
    out = {}
    for t in tags or []:
        if not isinstance(t.get("tagId"), int):
            continue
        nombres = t.get("allNamesByLocale") or {}
        out[t["tagId"]] = {"nombre": (nombres.get("en") or next(iter(nombres.values()), "")).lower(),
                           "padres": [x for x in t.get("parentTagIds") or [] if isinstance(x, int)]}
    return out


def _con_ancestros(tag: int, arbol: dict[int, dict]) -> list[int]:
    vistos, pendientes = [], [tag]
    while pendientes:
        actual = pendientes.pop(0)
        if actual in vistos or actual not in arbol:
            continue
        vistos.append(actual)
        pendientes.extend(arbol[actual]["padres"])
    return vistos


def categoria(tags: list[int], arbol: dict[int, dict]) -> tuple[str, str]:
    nombres = [arbol[t]["nombre"] for tag in tags for t in _con_ancestros(tag, arbol)]
    for clave, titulo, palabras in CATEGORIAS:
        if any(p in n for n in nombres for p in palabras):
            return clave, titulo
    return OTRAS


def agrupar(productos: list[dict], arbol: dict[int, dict]) -> list[dict] | None:
    """Grupos en el orden de CATEGORIAS; None si no hay con qué agrupar (sin árbol o ningún producto con tags)."""
    if not arbol or not any(p["tags"] for p in productos):
        return None
    por_clave: dict[str, dict] = {}
    for p in productos:
        clave, titulo = categoria(p["tags"], arbol)
        por_clave.setdefault(clave, {"clave": clave, "titulo": titulo, "productos": []})["productos"].append(p)
    orden = [c[0] for c in CATEGORIAS] + [OTRAS[0]]
    return [por_clave[c] for c in orden if c in por_clave]


# ---- pedidos ------------------------------------------------------------------------------------------------------
def _fechas(hoy: dt.date) -> tuple[str, str]:
    """Del primer día de la estadía (o de hoy, si ya arrancó) al último."""
    desde = max(INICIO_DE_LA_ESTADIA.date(), hoy)
    return desde.isoformat(), max(desde, FIN_DE_LA_ESTADIA.date()).isoformat()


def cuerpo_busqueda(pagina: int, hoy: dt.date) -> dict:
    desde, hasta = _fechas(hoy)
    return {"filtering": {"destination": DESTINO_LAS_VEGAS, "startDate": desde, "endDate": hasta},
            "sorting": {"sort": "DEFAULT"},
            "pagination": {"start": 1 + (pagina - 1) * POR_PAGINA, "count": POR_PAGINA},
            "currency": MONEDA}


def _post(url: str, body: dict) -> dict:
    try:
        r = httpx.post(url, json=body, headers=_headers(), timeout=TIMEOUT_S)
    except httpx.HTTPError as e:
        raise ViatorNoDisponible(f"Sin conexión con Viator ({type(e).__name__})") from e
    return _respuesta(r)


def _get(url: str) -> dict | list:
    try:
        r = httpx.get(url, headers=_headers(), timeout=TIMEOUT_S)
    except httpx.HTTPError as e:
        raise ViatorNoDisponible(f"Sin conexión con Viator ({type(e).__name__})") from e
    return _respuesta(r)


def _arbol_de_tags(reloj: Callable[[], float]) -> dict[int, dict]:
    """Si los tags fallan, la lista va sin agrupar: no es motivo para no mostrar excursiones."""
    with _lock:
        hit = _cache_tags.get("arbol")
    if hit and reloj() - hit[0] < TTL_TAGS_S:
        return hit[1]
    try:
        arbol = leer_tags(_get(URL_TAGS))
    except ViatorNoDisponible as e:
        log.info("Viator: sin tags para agrupar (%s)", e)
        return {}
    with _lock:
        _cache_tags["arbol"] = (reloj(), arbol)
    return arbol


def excursiones(pagina: int = 1, reloj: Callable[[], float] = time.monotonic,
                hoy: dt.date | None = None) -> dict:
    """Una página de excursiones, agrupadas si se puede. Levanta SinClave o ViatorNoDisponible."""
    if not 1 <= pagina <= MAX_PAGINAS:
        raise ValueError("página fuera de rango")
    with _lock:
        hit = _cache_busqueda.get(pagina)
    if hit and reloj() - hit[0] < TTL_BUSQUEDA_S:
        return hit[1]
    hoy = hoy or dt.datetime.now(TZ_VEGAS).date()
    busqueda = leer_busqueda(_post(URL_BUSQUEDA, cuerpo_busqueda(pagina, hoy)))
    hay_mas = pagina < MAX_PAGINAS and pagina * POR_PAGINA < busqueda["total"]
    resultado = {**busqueda, "pagina": pagina, "hay_mas": hay_mas,
                 "grupos": agrupar(busqueda["productos"], _arbol_de_tags(reloj))}
    if busqueda["productos"]:  # una respuesta vacía puede ser un hipo: no se queda una hora
        with _lock:
            _cache_busqueda[pagina] = (reloj(), resultado)
    return resultado

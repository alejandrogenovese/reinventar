"""Clima de Las Vegas para Hoy: lo de ahora, máxima y mínima de hoy, mañana y pasado, y un consejo si hace falta.

Fuente: la API del National Weather Service (https://www.weather.gov/documentation/services-web-api), gratis y sin
clave. Pide un User-Agent que identifique a la app: va uno genérico, sin mails ni datos de nadie. Endpoints:
- /points/{lat},{lon}: de las coordenadas a la grilla de pronóstico (oficina VEF). Trae las URLs de los otros dos.
- forecast: períodos de 12 h (día y noche) de los próximos siete días. Da la máxima (el de día) y la mínima (la noche).
- forecastHourly: períodos de una hora. Da la temperatura de ahora y el viento de las próximas 24 h.

Caché: solo pide el servidor (el navegador nunca llama a NWS) y guarda el resumen en memoria. Respeta el Cache-Control
de NWS (max-age): no vuelve a pedir antes de que venza, y tampoco antes de CACHE_MIN ni después de CACHE_MAX. El punto
(/points) se guarda lo que diga su max-age (hoy, un día). Si NWS falla, sigue con el último resumen mientras tenga menos
de VIGENCIA_MAX; si no hay, devuelve None (Hoy no muestra el clima) y no insiste hasta PAUSA_FALLO. Un solo pedido a NWS a
la vez y con PRESUPUESTO_S para los tres GET: mientras tanto, los demás se llevan lo guardado (aunque esté vencido) sin
esperar. Si un período viene con una forma rara, sigue con el último resumen bueno en vez de dar 500.

Proveedor (CLIMA_PROVIDER): nws (default), fake (tests: datos fijos, no sale nada) u off. El logger de httpx queda en
WARNING, como en app/rutas.py.
"""
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx

from . import config

log = logging.getLogger("reinventar.clima")
logging.getLogger("httpx").setLevel(logging.WARNING)

# Centro aproximado del Strip entre las sedes de re:Invent: a mitad de camino entre el MGM Grand (36.1025, -115.1697,
# punta sur) y el Venetian/Wynn (36.1212 a 36.1264, -115.17, punta norte), a la altura de Caesars Palace y el Forum. NWS
# lo ubica en la grilla VEF 121,96. Dentro del Strip la diferencia de pronóstico entre sedes es despreciable.
LAT, LON = 36.115, -115.17
BASE_NWS = "https://api.weather.gov/"
URL_PUNTO = f"{BASE_NWS}points/{LAT},{LON}"
USER_AGENT = "ReinventAR/1.3 (app del viaje)"
CABECERAS = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
ZONA = ZoneInfo("America/Los_Angeles")
TIMEOUT = httpx.Timeout(5.0, connect=3.0)
PRESUPUESTO_S = 6.0                   # tope total para los tres GET: el teléfono corta antes y el clima es accesorio
ESPERA_LOCK_S = PRESUPUESTO_S + 1     # sin nada guardado, cuánto espera un pedido a que otro termine de traerlo

CACHE_MIN = timedelta(minutes=30)     # no se pide más seguido que esto, aunque NWS diga menos
CACHE_MAX = timedelta(hours=3)        # ni se espera más que esto, aunque NWS diga más
PUNTO_MAX = timedelta(days=1)         # NWS pide volver a /points de vez en cuando: la grilla puede cambiar
PAUSA_FALLO = timedelta(minutes=5)    # después de un error no se insiste en ráfaga (un pedido por usuario)
VIGENCIA_MAX = timedelta(hours=6)     # un resumen más viejo que esto ya no se muestra

DIAS = 3                              # hoy, mañana y pasado
FRESCO_C = 10                         # mínima por debajo de esto: abrigo a la noche
VIENTO_FUERTE_KMH = 32                # unos 20 mph sostenidos: se siente y vuela todo
LLUVIA_PCT = 40                       # probabilidad desde la que vale llevar paraguas
KMH_POR_MPH = 1.609344

CONSEJO_FRESCO = "Fresco a la noche: llevá abrigo"
CONSEJO_VIENTO = "Viento fuerte: llevá campera rompeviento"
CONSEJO_LLUVIA = "Puede llover: llevá paraguas"

# shortForecast de NWS → castellano. Lo que no está se muestra en inglés, tal cual.
TRADUCCIONES = {
    "sunny": "Soleado", "mostly sunny": "Mayormente soleado", "partly sunny": "Parcialmente soleado",
    "clear": "Despejado", "mostly clear": "Mayormente despejado", "partly cloudy": "Parcialmente nublado",
    "mostly cloudy": "Mayormente nublado", "cloudy": "Nublado", "increasing clouds": "Nubosidad en aumento",
    "decreasing clouds": "Nubosidad en disminución", "becoming sunny": "Se despeja",
    "rain": "Lluvia", "light rain": "Lluvia débil", "rain likely": "Lluvia probable", "chance rain": "Posible lluvia",
    "slight chance rain": "Poca chance de lluvia", "rain showers": "Chaparrones",
    "rain showers likely": "Chaparrones probables", "chance rain showers": "Posibles chaparrones",
    "slight chance rain showers": "Algún chaparrón aislado", "showers and thunderstorms": "Tormentas",
    "showers and thunderstorms likely": "Tormentas probables", "chance showers and thunderstorms": "Posibles tormentas",
    "slight chance showers and thunderstorms": "Alguna tormenta aislada", "drizzle": "Llovizna",
    "snow": "Nieve", "chance snow": "Posible nieve", "rain and snow": "Lluvia y nieve", "frost": "Helada",
    "patchy fog": "Niebla aislada", "fog": "Niebla", "haze": "Neblina", "smoke": "Humo", "areas of smoke": "Humo",
    "blowing dust": "Polvo en suspensión", "areas of blowing dust": "Polvo en suspensión", "windy": "Ventoso",
    "breezy": "Algo de viento",
}
_ENTONCES = re.compile(r"\s+then\s+", re.IGNORECASE)
_NUMERO = re.compile(r"\d+(?:\.\d+)?")


def traducir(corto: str | None) -> str:
    """«Chance Rain Showers then Mostly Sunny» → «Posibles chaparrones y después mayormente soleado». Si alguna parte
    no está en la tabla, el original."""
    texto = (corto or "").strip()
    partes = [TRADUCCIONES.get(p.strip().lower()) for p in _ENTONCES.split(texto)] if texto else []
    if not partes or not all(partes):
        return texto
    return " y después ".join([partes[0], *(p[0].lower() + p[1:] for p in partes[1:])])


def a_celsius(temp: float | None, unidad: str | None = "F") -> int | None:
    if temp is None:
        return None
    return round((temp - 32) * 5 / 9) if (unidad or "F").upper() == "F" else round(temp)


def viento_kmh(texto: str | None) -> int | None:
    """«5 to 10 mph» → 16 (el mayor, en km/h). Sin número, None."""
    numeros = [float(n) for n in _NUMERO.findall(texto or "")]
    if not numeros:
        return None
    return round(max(numeros) * (1 if "km" in (texto or "").lower() else KMH_POR_MPH))


def _hora(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(ZONA)


def _lluvia(p: dict) -> int:
    return int((p.get("probabilityOfPrecipitation") or {}).get("value") or 0)


def _vigentes(periodos: list[dict], ahora: datetime) -> list[dict]:
    """Los períodos que no terminaron: NWS puede servir un pronóstico que todavía trae «Today» de esta mañana."""
    return [p for p in periodos if _hora(p["endTime"]) > ahora]


def _dia(fecha, periodos: list[dict]) -> dict | None:
    """Máxima (el período de día) y mínima (la noche que empieza esa fecha) de una fecha de Las Vegas."""
    del_dia = [p for p in periodos if _hora(p["startTime"]).date() == fecha]
    dia = next((p for p in del_dia if p.get("isDaytime")), None)
    noche = next((p for p in del_dia if not p.get("isDaytime")), None)
    if not dia and not noche:
        return None
    base = dia or noche
    return {"fecha": fecha.isoformat(),
            "max_c": a_celsius(dia["temperature"], dia.get("temperatureUnit")) if dia else None,
            "min_c": a_celsius(noche["temperature"], noche.get("temperatureUnit")) if noche else None,
            "descripcion": traducir(base.get("shortForecast")),
            "lluvia_pct": max(_lluvia(p) for p in del_dia)}


def _consejos(hoy: dict | None, viento_max: int | None) -> list[str]:
    if not hoy:
        return []
    consejos = []
    if hoy["min_c"] is not None and hoy["min_c"] < FRESCO_C:
        consejos.append(CONSEJO_FRESCO)
    if viento_max is not None and viento_max >= VIENTO_FUERTE_KMH:
        consejos.append(CONSEJO_VIENTO)
    if hoy["lluvia_pct"] >= LLUVIA_PCT:
        consejos.append(CONSEJO_LLUVIA)
    return consejos


def resumir(pronostico: list[dict], por_hora: list[dict], ahora: datetime) -> dict | None:
    """El resumen para Hoy a partir de los períodos de forecast y forecastHourly. None si no queda nada vigente."""
    ahora = ahora.astimezone(ZONA)
    periodos = _vigentes(pronostico, ahora)
    horas = _vigentes(por_hora, ahora)
    if not periodos and not horas:
        return None
    dias = [d for d in (_dia(ahora.date() + timedelta(days=i), periodos) for i in range(DIAS)) if d]
    actual = horas[0] if horas else None
    proximas = [viento_kmh(p.get("windSpeed")) for p in horas[:24]]
    viento_max = max((v for v in proximas if v is not None), default=None)
    hoy = dias[0] if dias and dias[0]["fecha"] == ahora.date().isoformat() else None
    return {
        "ahora": {"temp_c": a_celsius(actual["temperature"], actual.get("temperatureUnit")),
                  "descripcion": traducir(actual.get("shortForecast")),
                  "viento_kmh": viento_kmh(actual.get("windSpeed")),
                  "desde": _hora(actual["startTime"]).strftime("%H:%M")} if actual else None,
        "dias": dias,
        "consejos": _consejos(hoy, viento_max),
        "actualizado": ahora.isoformat(timespec="minutes"),
        "zona": str(ZONA),
        "fuente": "National Weather Service",
    }


# ---------- NWS ----------

def max_age(respuesta: httpx.Response) -> timedelta | None:
    """El max-age de Cache-Control; si no hay, lo que falta para Expires. None si no dice nada."""
    m = re.search(r"(?:^|,)\s*max-age=(\d+)", respuesta.headers.get("cache-control", ""))
    if m:
        return timedelta(seconds=int(m.group(1)))
    try:
        vence = parsedate_to_datetime(respuesta.headers["expires"])
        return max(timedelta(0), vence - datetime.now(vence.tzinfo))
    except (KeyError, TypeError, ValueError):
        return None


def _get(cliente: httpx.Client, url: str, limite: float) -> tuple[dict, timedelta | None]:
    """GET con lo que queda del presupuesto total (`limite`, en time.monotonic)."""
    restante = limite - time.monotonic()
    if restante <= 0:
        raise httpx.TimeoutException("Se pasó el presupuesto de tiempo para NWS")
    r = cliente.get(url, headers=CABECERAS, timeout=httpx.Timeout(min(TIMEOUT.read, restante),
                                                                   connect=min(TIMEOUT.connect, restante)))
    r.raise_for_status()
    return r.json()["properties"], max_age(r)


class _Estado:
    def __init__(self):
        self.lock = threading.Lock()
        self.punto: dict | None = None          # {forecast, forecastHourly}
        self.punto_vence: datetime | None = None
        self.datos: tuple[list, list] | None = None   # (períodos de forecast, de forecastHourly)
        self.datos_at: datetime | None = None
        self.datos_vence: datetime | None = None
        self.pausa_hasta: datetime | None = None
        self.resumen_ok: dict | None = None     # el último resumen que salió bien, por si uno nuevo no se puede armar


_estado = _Estado()


def reiniciar() -> None:
    """Olvida la caché (para los tests)."""
    global _estado
    _estado = _Estado()


def _entre(valor: timedelta | None, minimo: timedelta, maximo: timedelta) -> timedelta:
    return min(max(valor or minimo, minimo), maximo)


def _pedir_nws(cliente: httpx.Client, ahora: datetime) -> None:
    """Trae punto, pronóstico y por hora dentro de PRESUPUESTO_S. Solo toca el estado si salió todo bien."""
    e = _estado
    limite = time.monotonic() + PRESUPUESTO_S
    punto, punto_vence = e.punto, e.punto_vence
    if punto is None or punto_vence is None or ahora >= punto_vence:
        props, edad = _get(cliente, URL_PUNTO, limite)
        punto = {"forecast": props["forecast"], "forecastHourly": props["forecastHourly"]}
        if not all(isinstance(u, str) and u.startswith(BASE_NWS) for u in punto.values()):
            raise ValueError("URL de pronóstico fuera de api.weather.gov")  # solo se sigue lo que apunta a NWS
        punto_vence = ahora + _entre(edad, CACHE_MIN, PUNTO_MAX)
        e.punto, e.punto_vence = punto, punto_vence
    pronostico, edad_p = _get(cliente, punto["forecast"], limite)
    por_hora, edad_h = _get(cliente, punto["forecastHourly"], limite)
    edades = [x for x in (edad_p, edad_h) if x is not None]
    nuevos = (list(pronostico["periods"]), list(por_hora["periods"]))
    e.datos, e.datos_at = nuevos, ahora
    e.datos_vence = ahora + _entre(max(edades) if edades else None, CACHE_MIN, CACHE_MAX)


def _reciente(ahora: datetime) -> tuple[list, list] | None:
    e = _estado
    return e.datos if e.datos and e.datos_at and ahora - e.datos_at < VIGENCIA_MAX else None


def _refrescar(ahora: datetime, cliente: httpx.Client | None) -> None:
    e = _estado
    propio = cliente is None
    # Sin redirecciones: solo se habla con api.weather.gov, y un 3xx a otro lado cuenta como falla.
    cliente = cliente or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        _pedir_nws(cliente, ahora)
        e.pausa_hasta = None
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as err:
        log.warning("No se pudo actualizar el clima de NWS (%s): sigo con el último", type(err).__name__)
        e.pausa_hasta = ahora + PAUSA_FALLO
        if isinstance(err, httpx.HTTPStatusError) and err.response.status_code == 404:
            e.punto = None  # la grilla cambió: la próxima vez se vuelve a preguntar a /points
    finally:
        if propio:
            cliente.close()


def _datos_nws(ahora: datetime, cliente: httpx.Client | None) -> tuple[list, list] | None:
    """Lo guardado si vale; si no, lo trae. Un solo pedido a NWS a la vez: con algo guardado (aunque vencido) los demás
    no esperan y se llevan eso; sin nada, esperan un rato corto a que el que está pidiendo termine."""
    e = _estado
    if e.datos and e.datos_vence and ahora < e.datos_vence:
        return e.datos
    if e.pausa_hasta and ahora < e.pausa_hasta:
        return _reciente(ahora)
    hay_algo = _reciente(ahora) is not None
    if not (e.lock.acquire(blocking=False) if hay_algo else e.lock.acquire(timeout=ESPERA_LOCK_S)):
        return _reciente(ahora)
    try:
        vigente = e.datos and e.datos_vence and ahora < e.datos_vence   # otro lo trajo mientras se esperaba
        en_pausa = e.pausa_hasta and ahora < e.pausa_hasta
        if not vigente and not en_pausa:
            _refrescar(ahora, cliente)
    finally:
        e.lock.release()
    return _reciente(ahora)


def _periodo(inicio: datetime, horas: int, temp: int, dia: bool, corto: str, viento: str, lluvia: int = 0) -> dict:
    return {"startTime": inicio.isoformat(), "endTime": (inicio + timedelta(hours=horas)).isoformat(),
            "isDaytime": dia, "temperature": temp, "temperatureUnit": "F", "windSpeed": viento,
            "shortForecast": corto, "probabilityOfPrecipitation": {"value": lluvia}}


def datos_fake(ahora: datetime) -> tuple[list, list]:
    """Períodos con la forma de NWS alrededor de `ahora`: días de 61 °F (16 °C) y noches de 44 °F (7 °C)."""
    hoy = datetime.combine(ahora.astimezone(ZONA).date(), datetime.min.time(), tzinfo=ZONA)
    pronostico = []
    for i in range(DIAS + 1):
        dia = hoy + timedelta(days=i, hours=6)
        pronostico += [_periodo(dia, 12, 61 + i, True, "Sunny" if i % 2 == 0 else "Partly Cloudy", "5 to 10 mph"),
                       _periodo(dia + timedelta(hours=12), 12, 44, False, "Mostly Clear", "5 mph")]
    inicio = ahora.astimezone(ZONA).replace(minute=0, second=0, microsecond=0)
    por_hora = [_periodo(inicio + timedelta(hours=i), 1, 58, True, "Sunny", "8 mph") for i in range(24)]
    return pronostico, por_hora


def _resumen_bueno(ahora: datetime) -> dict | None:
    ok = _estado.resumen_ok
    return ok if ok and ahora - datetime.fromisoformat(ok["actualizado"]) < VIGENCIA_MAX else None


def obtener(ahora: datetime | None = None, cliente: httpx.Client | None = None) -> dict | None:
    """El resumen del clima (ver resumir) o None si está apagado o NWS no respondió y no hay uno reciente."""
    ahora = ahora or datetime.now(ZONA)
    proveedor = config.CLIMA_PROVIDER
    if proveedor == "off":
        return None
    if proveedor == "fake":
        return resumir(*datos_fake(ahora), ahora)
    datos = _datos_nws(ahora, cliente)
    datos_at = _estado.datos_at
    if not datos or datos_at is None:
        return None
    try:
        resumen = resumir(*datos, ahora)
    except (KeyError, TypeError, ValueError, AttributeError) as err:  # un período con forma rara no da 500
        log.warning("No se pudo armar el resumen del clima (%s): sigo con el último", type(err).__name__)
        return _resumen_bueno(ahora)
    if resumen is None:
        return None
    resumen = {**resumen, "actualizado": datos_at.astimezone(ZONA).isoformat(timespec="minutes")}
    _estado.resumen_ok = resumen
    return resumen

"""La mejor forma de ir de una sede de re:Invent a otra: no solo «14 min caminando», también el shuttle, el monorail o
el puente que conviene.

Dos fuentes:
- Atajos fijos (ATAJOS, más abajo): datos públicos de AWS y del Monorail, sin API. Sirven en cualquier lado (armado
  guiado, «está llena») y no cuestan nada.
- Google Routes API (computeRouteMatrix, a pie y en transporte público) bajo demanda, solo para las pocas charlas que
  sugiere «está llena» (app/lleno_api.py): tiempo real caminando y, si ningún atajo fijo cubre el par, si el
  transporte público ahorra bastante.

Caché y términos de Google: las Service Specific Terms de Google Maps Platform, sección 20.3 (Routes API), solo
permiten cachear latitud y longitud hasta 30 días; el resto del contenido (duraciones, distancias) cae en la
prohibición general de pre-fetch, caché o guardado (Terms of Service 3.2.3(b)). Por eso acá NO se guarda nada: ni en la
base ni en memoria. Cada pedido de «está llena» hace una consulta (una matriz 1×N) y la descarta al responder. Lo único
que se recuerda es que Google falló, por un minuto, para no insistir en ráfaga (no es contenido de Google). El texto se
muestra sin mapa, que la 20.1 permite.
  https://cloud.google.com/maps-platform/terms/maps-service-terms (20. Routes API)
  https://cloud.google.com/maps-platform/terms (3.2.3 Restrictions Against Misusing the Services)

Proveedor (RUTAS_PROVIDER): google (default; sin GOOGLE_MAPS_API_KEY queda apagado), fake (tests: no sale nada, usa
app/travel.py) u off. Si la API falla o tarda, se cae a lo de siempre (app/travel.py) sin romper nada. La clave va en el
header X-Goog-Api-Key: nunca se loguea, los errores llevan solo el código HTTP y el logger de httpx queda en WARNING
como en app/viator.py.
"""
import logging
import math
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass

import httpx

from . import config, travel, venues

log = logging.getLogger("reinventar.rutas")
logging.getLogger("httpx").setLevel(logging.WARNING)

URL_MATRIZ = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
CAMPOS = "originIndex,destinationIndex,duration,distanceMeters,condition"
TIMEOUT_S = 4                 # es para una pantalla que ya está abierta: mejor sin dato que tarde
PAUSA_FALLO_S = 60            # después de un error no se insiste por un minuto
UMBRAL_TRANSPORTE_MIN = 20    # hasta acá se camina; más lejos se busca otra forma
AHORRO_MIN_COLECTIVO = 10     # el transporte público se sugiere solo si ahorra al menos esto

MGM, FORUM, PALACE, WYNN, VENETIAN = "MGM Grand", "Caesars Forum", "Caesars Palace", "Wynn/Encore", "Venetian"

# Fuentes de los atajos (consultadas el 25/11/2026):
FUENTE_FAQ_2026 = "https://aws.amazon.com/events/reinvent/faqs/"
#   «Shuttles travel between properties and run continuously during conference hours.» «Badge holders can also take the
#   Las Vegas Monorail for free by showing their badges». Sedes: Caesars Forum, Caesars Palace, Encore, MGM Grand,
#   The Venetian y Wynn.
FUENTE_RECORRIDOS_2025 = "https://aws.amazon.com/resources/analyst-summit"
#   (guía de 2025) «re:Invent campus shuttles connect most properties, except Wynn and The Venetian, and Caesars Forum
#   and The Venetian.» Monorail en «MGM Station, Horseshoe/Paris Station, Flamingo/Caesars Palace Station and Harrah's/
#   The LINQ Station (Caesars Forum)». «A bridge connects Wynn and The Venetian». «Encore and Wynn are connected
#   internally». «A temporary walkway links Caesars Forum and The Venetian (available during Expo hours only)»: es de
#   2025 y no está confirmada para 2026, así que no se muestra.
FUENTE_MONORAIL = "https://www.lvmonorail.com/"
#   Siete estaciones, un tren cada 4 a 8 minutos. MGM Grand → Harrah's/LINQ son unos 4,5 min de viaje
#   (https://en.wikipedia.org/wiki/Las_Vegas_Monorail, minutos programados por estación).


@dataclass(frozen=True)
class Atajo:
    sedes: frozenset[str]
    texto: str     # corto, para ir después de «X min caminando · »
    fuente: str


ATAJOS = (
    Atajo(frozenset({MGM, FORUM}), "o monorail gratis con badge (MGM Grand ↔ Harrah's/LINQ, al lado del Forum)",
          FUENTE_FAQ_2026),
    Atajo(frozenset({WYNN, VENETIAN}), "por el puente Wynn–Venetian", FUENTE_RECORRIDOS_2025),
)
# Pares de sedes del campus sin shuttle (2025): se camina.
SIN_SHUTTLE = (frozenset({WYNN, VENETIAN}), frozenset({FORUM, VENETIAN}))
CAMPUS = frozenset({MGM, FORUM, PALACE, WYNN, VENETIAN})
TEXTO_SHUTTLE = "o shuttle de re:Invent (con badge)"


@dataclass(frozen=True)
class Medicion:
    """Lo que dice Google para un destino. None donde no hay ruta."""
    caminando_min: int | None
    caminando_m: int | None
    transporte_min: int | None


def atajo_fijo(origen: str | None, destino: str | None, caminando_min: int | None) -> str | None:
    """La recomendación sin API: el atajo del par, o el shuttle si es lejos y hay. None si conviene caminar y listo."""
    if not origen or not destino or origen == destino:
        return None
    par = frozenset({origen, destino})
    atajo = next((a for a in ATAJOS if a.sedes == par), None)
    if atajo:
        return atajo.texto
    lejos = caminando_min is not None and caminando_min > UMBRAL_TRANSPORTE_MIN
    if lejos and par <= CAMPUS and par not in SIN_SHUTTLE:
        return TEXTO_SHUTTLE
    return None


def recomendar(origen: str | None, destino: str | None, caminando_min: int | None,
               transporte_min: int | None = None) -> str | None:
    """El atajo fijo si hay; si no, el transporte público de Google cuando ahorra al menos AHORRO_MIN_COLECTIVO."""
    fijo = atajo_fijo(origen, destino, caminando_min)
    if fijo or caminando_min is None or transporte_min is None:
        return fijo
    if caminando_min > UMBRAL_TRANSPORTE_MIN and caminando_min - transporte_min >= AHORRO_MIN_COLECTIVO:
        return f"o transporte público ~{transporte_min} min"
    return None


# ---- Google Routes API ---------------------------------------------------------------------------------------------
_fallo_hasta = 0.0
_lock = threading.Lock()


def reiniciar() -> None:
    """Para los tests."""
    global _fallo_hasta
    with _lock:
        _fallo_hasta = 0.0


def _proveedor() -> str:
    p = config.RUTAS_PROVIDER
    if p == "google" and not config.GOOGLE_MAPS_API_KEY:
        return "off"
    return p


def _headers() -> dict:
    h = {"X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY, "X-Goog-FieldMask": CAMPOS}
    if config.WEBAUTHN_ORIGIN:  # la key del navegador está restringida por sitio web: Google mira el Referer
        h["Referer"] = config.WEBAUTHN_ORIGIN.rstrip("/") + "/"
    return h


def _punto(sede: dict) -> dict:
    return {"waypoint": {"location": {"latLng": {"latitude": sede["lat"], "longitude": sede["lng"]}}}}


def armar_pedido(origen: dict, destinos: list[dict], modo: str) -> dict:
    return {"origins": [_punto(origen)], "destinations": [_punto(d) for d in destinos], "travelMode": modo}


def leer_matriz(elementos: list[dict]) -> dict[int, tuple[int, int]]:
    """{índice de destino: (minutos, metros)} de los elementos con ruta. Google omite los campos en cero."""
    out = {}
    for e in elementos:
        if e.get("condition") != "ROUTE_EXISTS" or "duration" not in e:
            continue
        segundos = int(str(e["duration"]).removesuffix("s"))
        out[e.get("destinationIndex", 0)] = (max(1, math.ceil(segundos / 60)), int(e.get("distanceMeters", 0)))
    return out


def _pedir(pedido: dict) -> list[dict]:
    r = httpx.post(URL_MATRIZ, json=pedido, headers=_headers(), timeout=TIMEOUT_S)
    if r.status_code != 200:
        raise RuntimeError(f"Routes API respondió {r.status_code}")
    datos = r.json()
    if not isinstance(datos, list):
        raise RuntimeError("Routes API respondió algo que no es una lista")
    return datos


def _matriz(origen: dict, destinos: list[dict], modo: str) -> dict[int, tuple[int, int]] | None:
    """La matriz 1×N, o None si Google falla (y por un minuto no se vuelve a probar)."""
    global _fallo_hasta
    if time.monotonic() < _fallo_hasta:
        return None
    try:
        return leer_matriz(_pedir(armar_pedido(origen, destinos, modo)))
    except (httpx.HTTPError, RuntimeError, ValueError, TypeError, AttributeError) as e:
        # Solo el tipo y el código: ni la clave ni el pedido.
        log.warning("Routes API no disponible: %s", e if isinstance(e, RuntimeError) else type(e).__name__)
        with _lock:
            _fallo_hasta = time.monotonic() + PAUSA_FALLO_S
        return None


def _fake(origen: dict, destinos: list[dict]) -> dict[int, Medicion]:
    """Modo tests: los pares medidos de app/travel.py (los estimados no cuentan), sin transporte público. No sale nada a
    la red."""
    out = {}
    for d in destinos:
        v = travel.viaje(origen["id"], d["id"])
        medido = v is not None and not v.estimado
        out[d["id"]] = Medicion(v.minutos if medido else None, travel.metros_caminando(origen["id"], d["id"]), None)
    return out


def medir(id_origen: int | None, ids_destino: Iterable[int | None]) -> dict[int, Medicion]:
    """Caminando (y en transporte público donde ningún atajo fijo cubre el par) de una sede a otras, por id de destino.
    Sin proveedor, sin coordenadas o si Google falla: {} y quien llama sigue con app/travel.py."""
    proveedor, origen = _proveedor(), venues.by_id(id_origen)
    if proveedor == "off" or not origen or origen["lat"] is None:
        return {}
    destinos = [d for i in dict.fromkeys(ids_destino) if i != id_origen and (d := venues.by_id(i)) and d["lat"] is not None]
    if not destinos:
        return {}
    if proveedor == "fake":
        return _fake(origen, destinos)
    caminando = _matriz(origen, destinos, "WALK")
    if caminando is None:
        return {}
    # Transporte público solo donde es lejos y no hay atajo fijo (ni shuttle): así casi nunca se pide.
    lejos_sin_atajo = [i for i, d in enumerate(destinos) if i in caminando
                       and caminando[i][0] > UMBRAL_TRANSPORTE_MIN
                       and atajo_fijo(origen["name"], d["name"], caminando[i][0]) is None]
    transporte = _matriz(origen, [destinos[i] for i in lejos_sin_atajo], "TRANSIT") if lejos_sin_atajo else None
    transporte_min = {lejos_sin_atajo[j]: minutos for j, (minutos, _) in (transporte or {}).items()}
    return {d["id"]: Medicion(*caminando.get(i, (None, None)), transporte_min.get(i)) for i, d in enumerate(destinos)}

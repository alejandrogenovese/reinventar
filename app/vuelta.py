"""La vuelta desde Las Vegas: a qué hora salir del hotel para el vuelo que sale de LAS. Misma cuenta que web/js/vuelta.js
(la tarjeta del vuelo); tests/test_vuelta.py verifica que las constantes coincidan. Lo usa «Próximo» (app/proximo.py).

Salir = salida − anticipación (3 h internacional, 2 h doméstico) − ~25 min de traslado desde el Strip.
Fuente de la anticipación (26/11/2026): https://www.harryreidairport.com/get-ready-for-your-flight («Please arrive at
least 2 hours before your scheduled departure» doméstico; «at least 3 hours» internacional). El traslado es una
estimación propia, no un dato oficial.
"""
import datetime as dt

from . import vuelos

ZONA_LAS_VEGAS = "America/Los_Angeles"
ANTICIPACION_INTERNACIONAL_MIN = 180
ANTICIPACION_DOMESTICO_MIN = 120
TRASLADO_STRIP_MIN = 25

# Con destino en uno de estos el vuelo es doméstico; cualquier otro, o desconocido, cuenta como internacional.
AEROPUERTOS_EEUU = frozenset({"ATL", "BOS", "CLT", "DEN", "DFW", "DTW", "EWR", "IAD", "IAH", "JFK",
                              "LAX", "MCO", "MIA", "MSP", "ORD", "PHX", "SAN", "SEA", "SFO", "SLC"})


def sale_de_las_vegas(v: dict) -> bool:
    """Zona del Pacífico y la ciudad elegida es Las Vegas (Los Ángeles comparte zona). Un vuelo viejo sin ciudad usa el
    nombre de la zona, que para America/Los_Angeles es «Las Vegas»."""
    ciudad = v.get("ciudad") or vuelos.ZONAS.get(v.get("zona") or "", "")
    return v.get("zona") == ZONA_LAS_VEGAS and "las vegas" in ciudad.lower()


def es_internacional(v: dict) -> bool:
    return (v.get("destino_iata") or "").upper() not in AEROPUERTOS_EEUU


def anticipacion_min(v: dict) -> int:
    return ANTICIPACION_INTERNACIONAL_MIN if es_internacional(v) else ANTICIPACION_DOMESTICO_MIN


def salir_al_aeropuerto(v: dict) -> dt.datetime | None:
    """Cuándo salir del hotel (con zona), o None si el vuelo no sale de Las Vegas, no tiene hora o está cancelado."""
    if not sale_de_las_vegas(v) or (v.get("estado") or "").lower().startswith("cancel"):
        return None
    sale = vuelos.salida(v)
    if not sale:
        return None
    return sale - dt.timedelta(minutes=anticipacion_min(v) + TRASLADO_STRIP_MIN)

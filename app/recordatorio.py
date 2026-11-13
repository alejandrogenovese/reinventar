"""Recordatorio "¿la grabás?": que nadie se olvide de grabar una charla a la que fue. Funciones puras (sin base ni red).

- Regla A (en app/push.py): el aviso "X empieza en N min" de una charla fijada suma "¿La grabás?" y abre la grabación.
- Regla B: entre 2 y 6 min después del inicio, si nadie está grabando esa charla, un aviso para grabarla. Va siempre a
  las charlas fijadas; a las del itinerario sin fijar, solo si la sede reciente es la de la charla (sin ubicación sería spam).
- Regla C: con una sede reciente distinta a la de la charla, si la caminata es de 15 min o más no se avisa (se fue a
  otro lado); si es menos, el texto dice dónde está.
- Nunca en horario de silencio (22 a 7 en Las Vegas), con la preferencia apagada ni más de uno cada 30 min.

La sede reciente la manda el celular como número de sede (nunca coordenadas) y solo con la app abierta: ver
app/ubicacion_api.py. Una PWA no tiene GPS en segundo plano.
"""
import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

VENTANA_DESDE_MIN = 2           # minutos después del inicio desde los que se avisa
VENTANA_HASTA_MIN = 6           # y hasta cuándo: un corte del servidor de 1 o 2 min no pierde el aviso
UBICACION_VIGENCIA_MIN = 45     # una sede reportada hace más que esto cuenta como "sin dato"
UBICACION_BORRADO_MIN = 120     # y a las 2 h se borra de la base
ENFRIAMIENTO_MIN = 30           # como mucho un recordatorio de grabar cada 30 min por persona
LEJOS_MIN = 15                  # caminata desde la sede reciente a partir de la cual no se avisa
HORARIO_SILENCIO = (22, 7)      # (desde, hasta) en hora de Las Vegas
TTL_SEGUNDOS = 600              # un "¿la grabás?" que llega 40 min tarde no sirve
GRABACION_RECIENTE_MIN = 20     # una grabación de esa charla creada hace menos que esto cuenta como "ya la graban"
CHUNK_ACTIVO_MIN = 3            # o una en curso que subió audio hace menos que esto
PREFIJO = "rec:"                # clave en push_sent (sirve también para el enfriamiento)
ACCION_GRABAR = "grabar"


@dataclass(frozen=True)
class Preferencias:
    grabar: bool = True         # "Recordarme grabar"
    ubicacion: bool = False     # "Usar en qué sede estoy para los avisos": apagado por defecto


@dataclass(frozen=True)
class Sede:
    id: int
    nombre: str


def en_silencio(now: dt.datetime) -> bool:
    desde, hasta = HORARIO_SILENCIO
    return now.hour >= desde or now.hour < hasta


def url_grabar(code: str) -> str:
    return f"/#/grabar-charla/{code}"


def con_grabar(key: str, code: str, msg: dict) -> dict:
    """El mensaje con lo que abre la grabación: URL (iPhone solo tiene el toque), acción "Grabar" (Chrome) y tag propio."""
    url = url_grabar(code)
    return {**msg, "url": url, "recordUrl": url, "tag": key,
            "actions": [{"action": ACCION_GRABAR, "title": "Grabar"}]}


def _minutos_desde_inicio(c: dict, now: dt.datetime) -> float | None:
    if c.get("day") != now.strftime("%Y-%m-%d") or not c.get("start"):
        return None
    inicio = dt.datetime.fromisoformat(f"{c['day']}T{c['start']}").replace(tzinfo=now.tzinfo)
    return (now - inicio).total_seconds() / 60


def _sala(c: dict) -> str:
    return (c.get("venue") or {}).get("detail") or ""


def _hotel(c: dict) -> str:
    return (c.get("venue") or {}).get("hotel") or ""


def _mensaje(c: dict, sede: Sede | None, viaje_min: Callable[[int, int], int | None]) -> dict | None:
    """Texto según la sede reciente (reglas B y C), o None si no corresponde avisar."""
    titulo, hotel, sala = c["title"], _hotel(c), _sala(c)
    sede_charla = c.get("id_sede")
    if sede is None or sede_charla is None:
        if not c.get("locked"):
            return None  # sin ubicación, avisar de algo no fijado es spam
        donde = f" en {hotel}" if hotel else ""
        return {"title": f"Empezó {titulo}{donde}", "body": " · ".join(filter(None, (sala, "Tocá para grabar")))}
    if sede.id == sede_charla:
        return {"title": f"Estás en {sede.nombre}: ¿grabás {titulo}?",
                "body": " · ".join(filter(None, ("Ya empezó", sala, "Tocá para grabar")))}
    if not c.get("locked"):
        return None
    minutos = viaje_min(sede.id, sede_charla)
    if minutos is None or minutos >= LEJOS_MIN:
        return None  # se fue a otro lado
    return {"title": f"{titulo} ya empezó en {hotel} (estás en {sede.nombre})",
            "body": " · ".join(filter(None, (sala, f"{minutos} min caminando", "Tocá para grabar")))}


def recordatorios(cards: list[dict], now: dt.datetime, *, sede: Sede | None, prefs: Preferencias,
                  grabando: Callable[[str], bool], viaje_min: Callable[[int, int], int | None],
                  minutos_desde_ultimo: float | None) -> list[tuple[str, dict]]:
    """[(clave, mensaje)] de la regla B/C: como mucho uno por vuelta.

    cards: charlas del itinerario (con `id_sede` de su sede); sede: la reciente y vigente, o None; grabando(code): si
    alguien ya graba esa charla; viaje_min(origen, destino): minutos caminando; minutos_desde_ultimo: desde el último
    recordatorio de grabar que se le mandó (None = nunca).
    """
    if not prefs.grabar or en_silencio(now):
        return []
    if minutos_desde_ultimo is not None and minutos_desde_ultimo < ENFRIAMIENTO_MIN:
        return []
    for c in cards:
        if c.get("kind", "talk") != "talk":
            continue
        desde_inicio = _minutos_desde_inicio(c, now)
        if desde_inicio is None or not VENTANA_DESDE_MIN <= desde_inicio <= VENTANA_HASTA_MIN:
            continue
        msg = _mensaje(c, sede, viaje_min)
        if msg is None or grabando(c["code"]):
            continue
        key = f"{PREFIJO}{c['code']}:{c['day']}"
        return [(key, {**con_grabar(key, c["code"], msg), "ttl": TTL_SEGUNDOS})]
    return []

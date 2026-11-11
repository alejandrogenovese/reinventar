"""A qué hora estar y a qué hora irse, para los avisos (push, Hoy y el calendario .ics).

- Charla sin reserva en el portal de AWS: hay que estar COLA_SIN_RESERVA minutos antes (fila de walk-up).
- Charla de la que la persona eligió salir antes (armado guiado): se va salir_antes minutos antes del fin.
Los eventos (de la sección o propios) no tienen cola.
"""
from .guided import COLA_SIN_RESERVA, hhmm, minutos


def needs_queue(card: dict) -> bool:
    return card.get("kind", "talk") == "talk" and not card.get("reservada")


def arrive_by(card: dict) -> str:
    """Hora a la que hay que estar: el inicio, o COLA_SIN_RESERVA antes si hay que hacer la cola."""
    inicio = minutos(card["start"])
    return hhmm(inicio - COLA_SIN_RESERVA) if needs_queue(card) else card["start"]


def leave_early_at(card: dict) -> str | None:
    """Hora a la que se va antes de que termine (para llegar a la siguiente), o None si se queda hasta el final."""
    if not card.get("salir_antes") or not card.get("end"):
        return None
    return hhmm(minutos(card["end"]) - card["salir_antes"])

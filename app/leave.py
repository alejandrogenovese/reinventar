"""A qué hora estar y a qué hora irse, para los avisos (push, Hoy y el calendario .ics).

- Charla sin reserva en el portal de AWS: hay que estar COLA_SIN_RESERVA minutos antes (fila de walk-up).
- Charla reservada: hay que entrar RESERVA_LIBERA_MIN minutos antes o el lugar se libera para la fila de walk-up (FAQ
  oficial, consultado el 25/11/2026: https://aws.amazon.com/events/reinvent/faqs/).
- Charla de la que la persona eligió salir antes (armado guiado): se va salir_antes minutos antes del fin.
Los eventos (de la sección o propios) no tienen cola.
"""
from .guided import COLA_SIN_RESERVA, hhmm, minutos

RESERVA_LIBERA_MIN = 10
MINUTOS_DIA = 24 * 60


def _hora(total: int) -> str:
    """HH:MM dando la vuelta al día: una charla a las 00:05 con 30 min de cola da 23:35, no «-1:55»."""
    return hhmm(total % MINUTOS_DIA)


def needs_queue(card: dict) -> bool:
    return card.get("kind", "talk") == "talk" and not card.get("reservada")


def arrive_by(card: dict) -> str:
    """Hora a la que hay que estar: el inicio, o COLA_SIN_RESERVA antes si hay que hacer la cola."""
    inicio = minutos(card["start"])
    return _hora(inicio - COLA_SIN_RESERVA) if needs_queue(card) else card["start"]


def entrar_antes(card: dict) -> str | None:
    """Hora límite para entrar con reserva (después se libera el lugar), o None si no es una charla reservada."""
    if card.get("kind", "talk") != "talk" or not card.get("reservada") or not card.get("start"):
        return None
    return _hora(minutos(card["start"]) - RESERVA_LIBERA_MIN)


def leave_early_at(card: dict) -> str | None:
    """Hora a la que se va antes de que termine (para llegar a la siguiente), o None si se queda hasta el final."""
    if not card.get("salir_antes") or not card.get("end"):
        return None
    return _hora(minutos(card["end"]) - card["salir_antes"])

"""A qué hora estar y a qué hora irse, para los avisos (push, Hoy y el calendario .ics).

- Charla solo por cola (walk-up): hay que estar COLA_SIN_RESERVA minutos antes.
- Charla que se reserva y no tenés reservada: COLA_SIN_LUGAR minutos antes, a ver si quedan lugares libres.
- Charla reservada: hay que entrar RESERVA_LIBERA_MIN minutos antes o el lugar se libera para la fila de walk-up (FAQ
  oficial, consultado el 25/11/2026: https://aws.amazon.com/events/reinvent/faqs/).
Cuánto antes en cada caso: guided.cola_min.
- Charla de la que la persona eligió salir antes (armado guiado): se va salir_antes minutos antes del fin.
Los eventos (de la sección o propios) no tienen cola.
"""
from .guided import cola_min, hhmm, minutos

RESERVA_LIBERA_MIN = 10
MINUTOS_DIA = 24 * 60


def _hora(total: int) -> str:
    """HH:MM dando la vuelta al día: una charla a las 00:05 con 30 min de cola da 23:35, no «-1:55»."""
    return hhmm(total % MINUTOS_DIA)


def needs_queue(card: dict) -> bool:
    return card.get("kind", "talk") == "talk" and not card.get("reservada")


def arrive_by(card: dict) -> str:
    """Hora a la que hay que estar: el inicio menos la cola (guided.cola_min)."""
    return _hora(minutos(card["start"]) - cola_min(card))


def sin_lugar_seguro(card: dict) -> bool:
    """Se reserva y no la tenés reservada: entrás con los lugares que sobren."""
    return needs_queue(card) and not card.get("walk_in")


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

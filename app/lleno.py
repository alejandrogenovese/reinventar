"""«Está llena / hay mucha cola»: avisos de la gente en la puerta de la charla, más una pista con lo que ya sabemos.

AWS no publica cuántos lugares quedan sin el login de alguien registrado, así que no se consulta: lo cuentan quienes
están ahí. Cada persona deja como mucho un aviso por horario (si lo cambia, se pisa), solo desde un rato antes de que
empiece hasta que termina. Un aviso vale VIGENCIA_MIN y se borra a las BORRADO_H. Nunca se muestra quién avisó.

La pista sale del catálogo: si es solo por cola (walk-up) o si la sala es chica.
"""
import datetime as dt

from . import itinerary

VIGENCIA_MIN = 60
BORRADO_H = 6
ABRE_ANTES_MIN = 45   # se puede avisar desde este rato antes de que empiece (la cola se arma antes)
SALA_CHICA = 80       # lugares: con esto o menos, conviene llegar con tiempo
CODIGOS_POR_PEDIDO = 30


def pista(card: dict) -> str | None:
    """Lo que dice el catálogo sobre conseguir lugar, o None si no hay nada que decir."""
    if card.get("walk_in"):
        return "Sin reserva: se entra por orden de llegada"
    seats = card.get("seats")
    if seats and seats <= SALA_CHICA:
        return f"Sala chica ({seats} lugares): llegá con tiempo"
    return None


def _fin_min(session: dict, instance: dict) -> int:
    if instance.get("en"):
        return itinerary._minutes(instance["en"])
    return itinerary._minutes(instance["st"]) + itinerary._duration(session.get("type") or "")


def abierto(session: dict, instance: dict, ahora: dt.datetime) -> bool:
    """Si se puede avisar ahora: el mismo día, desde ABRE_ANTES_MIN antes de empezar hasta que termina."""
    if not instance.get("st") or instance.get("d") != ahora.strftime("%Y-%m-%d"):
        return False
    minuto = ahora.hour * 60 + ahora.minute
    return itinerary._minutes(instance["st"]) - ABRE_ANTES_MIN <= minuto < _fin_min(session, instance)


def resumen(filas: list[dict], username: str, ahora_ts: float) -> dict:
    """Avisos vigentes de un horario: cuántos por estado, hace cuántos minutos el último y qué avisó esta persona."""
    vigentes = [f for f in filas if f["creado"] >= ahora_ts - VIGENCIA_MIN * 60]
    ultimo = max((f["creado"] for f in vigentes), default=None)
    return {
        "lleno": sum(f["estado"] == "lleno" for f in vigentes),
        "cola": sum(f["estado"] == "cola" for f in vigentes),
        "hace_min": int((ahora_ts - ultimo) // 60) if ultimo is not None else None,
        "mio": next((f["estado"] for f in vigentes if f["username"] == username), None),
    }

"""Anuncios sin reserva: keynotes, mainstage, lanzamientos y «What's new» a los que se entra por la cola.

Criterio (sobre el catálogo en memoria, sin SQL por pedido):
- horario walk-up («Walk up only session») y charla no sponsoreada;
- tipo Keynote, Mainstage, Breakout o Lightning;
- y Keynote o Mainstage, o marcada «New launch», o con «What's new», «[NEW LAUNCH]» o «latest innovations» en el título.

Inicio muestra las del día que todavía no terminaron (o empezaron hace poco) y no están en el itinerario; si ya no
queda ninguna hoy (de noche, o antes del evento), las del próximo día con anuncios.
"""
import re
from datetime import datetime

from . import catalog, itinerary, leave, talks

NIVEL_KEYNOTE, NIVEL_MAINSTAGE, NIVEL_LANZAMIENTO, NIVEL_NOVEDADES = 1, 2, 3, 4
TIPOS = frozenset({"Keynote", "Mainstage", "Breakout session", "Lightning talk"})
_TIPOS_PRINCIPALES = {"Keynote": NIVEL_KEYNOTE, "Mainstage": NIVEL_MAINSTAGE}
_TITULO_NOVEDADES = re.compile(r"what's new|\[new launch\]|latest innovations", re.IGNORECASE)

# Una charla que empezó hace menos de esto todavía sirve: se puede entrar (o grabar) aunque sea tarde.
MINUTOS_TOLERANCIA = 10
LIMITE_INICIO = 5
FILTRO_BUSCAR = "Anuncios sin reserva"  # valor de la faceta «anuncio» en Buscar (app/explore.py)


def nivel(session: dict, instance: dict) -> int | None:
    """Nivel del anuncio (1 keynote · 2 mainstage · 3 lanzamiento · 4 novedades) o None si no es anuncio sin reserva."""
    tipo = session.get("type")
    if not instance.get("walk") or session.get("sponsored") or tipo not in TIPOS:
        return None
    if tipo in _TIPOS_PRINCIPALES:
        return _TIPOS_PRINCIPALES[tipo]
    if session.get("newlaunch"):
        return NIVEL_LANZAMIENTO
    if _TITULO_NOVEDADES.search(session.get("title") or ""):
        return NIVEL_NOVEDADES
    return None


def todos() -> list[tuple[dict, dict, int]]:
    """(charla, horario, nivel) de cada anuncio sin reserva del catálogo, en orden de día y hora."""
    out = [(s, i, n) for s in catalog.all_sessions() for i in s.get("instances", []) if (n := nivel(s, i))]
    return sorted(out, key=lambda t: (t[1]["d"], t[1]["st"], t[2]))


def _fin(session: dict, instance: dict) -> str:
    """Fin del horario: el del catálogo o, si falta, estimado por tipo (como el itinerario)."""
    if instance.get("en"):
        return instance["en"]
    total = itinerary._minutes(instance["st"]) + itinerary._duration(session.get("type") or "")
    return f"{total // 60:02d}:{total % 60:02d}"


def _sigue_en_pie(session: dict, instance: dict, minuto: int) -> bool:
    """No terminó y no empezó hace más de MINUTOS_TOLERANCIA."""
    inicio, fin = itinerary._minutes(instance["st"]), itinerary._minutes(_fin(session, instance))
    return minuto < fin and minuto < inicio + MINUTOS_TOLERANCIA


def _tarjeta(session: dict, instance: dict, nivel_: int, minuto: int | None) -> dict:
    card = catalog.card(session, instance)
    end = _fin(session, instance)
    inicio = itinerary._minutes(card["start"])
    en_curso = minuto is not None and inicio <= minuto < itinerary._minutes(end)
    return {**card, "nivel": nivel_, "end": end, "cola_desde": leave.arrive_by(card), "en_curso": en_curso,
            "recording_kind": talks.recording_kind(card.get("type"))}


def del_dia(now: datetime, excluir: set[str], limite: int = LIMITE_INICIO) -> dict:
    """Anuncios para Inicio: los que quedan hoy o, si no queda ninguno, los del próximo día con anuncios.

    `now` es la hora local del evento; `excluir`, códigos de horario o de charla que ya están en el itinerario.
    Devuelve {day, is_today, items (hasta `limite`), total}; day es None si no queda ningún anuncio.
    """
    hoy, minuto = now.strftime("%Y-%m-%d"), now.hour * 60 + now.minute
    candidatos = [(s, i, n) for s, i, n in todos() if i["c"] not in excluir and s["base"] not in excluir]

    de_hoy = [(s, i, n) for s, i, n in candidatos if i["d"] == hoy and _sigue_en_pie(s, i, minuto)]
    if de_hoy:
        dia, elegidos, reloj = hoy, de_hoy, minuto
    else:
        proximos = [t for t in candidatos if t[1]["d"] > hoy]
        if not proximos:
            return {"day": None, "is_today": False, "items": [], "total": 0}
        dia = proximos[0][1]["d"]
        elegidos, reloj = [t for t in proximos if t[1]["d"] == dia], None

    items = [_tarjeta(s, i, n, reloj) for s, i, n in elegidos[:limite]]
    return {"day": dia, "is_today": dia == hoy, "items": items, "total": len(elegidos)}

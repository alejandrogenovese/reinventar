"""Charlas repetidas: "Otros horarios", "Cambiar a este" y "Me la perdí" (qué opciones quedan).

521 charlas tienen más de un horario (la mayoría chalk talks, workshops y builders' sessions, de cupo chico). Si te
perdiste una, primero se ofrecen sus otros horarios (los que no chocan con lo que tenés, primero) y después charlas
parecidas que empiezan pronto, usando las etiquetas oficiales y las extraídas del resumen.
"""
import datetime as dt

from . import catalog, db, itinerary, knowledge, sandbox

SIMILAR_WINDOW = dt.timedelta(hours=4)
SIMILAR_LIMIT = 5


def _starts(card: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{card['day']}T{card['start']}").replace(tzinfo=sandbox.EVENT_TZ)


def _mine(username: str) -> list[dict]:
    return [c for d in itinerary.get_current(username)["days"] for c in d["sessions"]]


def _clashes(card: dict, mine: list[dict], skip_base: str) -> list[str]:
    """Títulos de lo que el usuario tiene ese día y se superpone (sin contar la misma charla)."""
    span = itinerary._span({**card, "end": itinerary._end(card)})
    return [m["title"] for m in mine if m["day"] == card["day"] and m.get("start") and m["base"] != skip_base
            and (s := itinerary._span(m))[0] < span[1] and span[0] < s[1]]


def options(username: str, code: str) -> dict | None:
    """{talk, repeats, similar} para "Me la perdí". None si el código no existe."""
    found = catalog.get_instance(code)
    if not found:
        return None
    session, instance = found
    now = sandbox.ahora()
    mine = _mine(username)
    in_itinerary = {m["code"] for m in mine}

    repeats = []
    for inst in sorted(session["instances"], key=lambda i: (i["d"], i["st"])):
        card = catalog.card(session, inst)
        if inst["c"] == code or _starts(card) <= now:
            continue
        repeats.append({**card, "clashes": _clashes(card, mine, session["base"]), "in_itinerary": inst["c"] in in_itinerary})
    repeats.sort(key=lambda c: (bool(c["clashes"]), c["day"], c["start"]))

    similar = []
    for score, other in knowledge.related_scored(session):
        upcoming = [c for i in other.get("instances", []) if now < _starts(c := catalog.card(other, i)) <= now + SIMILAR_WINDOW]
        if upcoming:
            first = min(upcoming, key=_starts)
            similar.append((score, {**first, "clashes": _clashes(first, mine, other["base"]),
                                    "in_itinerary": first["code"] in in_itinerary}))
    similar.sort(key=lambda sc: (-sc[0], sc[1]["day"], sc[1]["start"]))
    return {"talk": catalog.card(session, instance), "repeats": repeats, "similar": [c for _, c in similar[:SIMILAR_LIMIT]]}


def swap(username: str, code: str, to: str) -> dict:
    """Cambia un horario del itinerario por otro de la misma charla, conservando si estaba fijado."""
    old = next((it for it in db.list_itinerary_items(username) if it["code"] == code), None)
    new = catalog.get_instance(to)
    if not old or not new:
        raise ValueError("Horario inexistente")
    session, instance = new
    if session["base"] != old["base"]:
        raise ValueError("Ese horario es de otra charla")
    db.remove_item(username, code)
    db.add_item(username, to, session["base"], instance["d"], instance["st"], locked=bool(old["locked"]),
                reason=old.get("reason"), snapshot=itinerary.snapshot(catalog.card(session, instance)))
    return itinerary.get_current(username)

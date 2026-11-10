"""Avisos de cambios sobre lo que el usuario tiene en el itinerario: AWS movió una charla de sala u horario, la dio de
baja o le cambió el código, o un evento se llenó.

No hace falta una tarea programada: cada ítem guarda cómo era al agregarlo (itinerary.snapshot) y acá se compara con el
catálogo actual (que cambia con cada sync). "Entendido" actualiza la foto, o quita el ítem si ya no existe.
"""
import datetime as dt

from . import db, itinerary


def _when(snap: dict) -> str:
    day = dt.date.fromisoformat(snap["day"]) if snap.get("day") else None
    if not day:
        return snap.get("start") or ""
    nombre = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")[day.weekday()]
    return f"{nombre} {day.day}/{day.month} {snap.get('start') or ''}".strip()


def diff(old: dict, new: dict) -> list[str]:
    """Mensajes para el usuario sobre lo que cambió entre dos fotos del mismo ítem."""
    title = new.get("title") or old.get("title")
    out = []
    if (old.get("day"), old.get("start")) != (new.get("day"), new.get("start")):
        out.append(f"Cambió el horario de «{title}»: era {_when(old)}, ahora {_when(new)}.")
    if old.get("venue") and new.get("venue") and old["venue"] != new["venue"]:
        out.append(f"«{title}» cambió de lugar: ahora es en {new['venue']} (antes: {old['venue']}).")
    if new.get("full") and not old.get("full"):
        out.append(f"«{title}» se llenó: revisá tu lugar o la lista de espera.")
    return out


def pending(username: str) -> list[dict]:
    """[{code, kind, title, messages, gone}] de lo que cambió y el usuario todavía no vio."""
    out = []
    for it in db.list_itinerary_items(username):
        card = itinerary._item_card(it)
        old = it.get("snapshot")
        if old is None:  # ítems de antes de esta función: la foto arranca ahora, sin aviso
            if card:
                db.set_item_snapshot(username, it["code"], itinerary.snapshot(card))
            continue
        if card is None:
            out.append({"code": it["code"], "kind": it.get("kind") or "talk", "title": old.get("title"), "gone": True,
                        "messages": [f"«{old.get('title')}» ya no figura en el catálogo: puede haberse dado de baja o "
                                     "cambiado de código. Buscala de nuevo."]})
            continue
        messages = diff(old, itinerary.snapshot(card))
        if messages:
            out.append({"code": it["code"], "kind": it.get("kind") or "talk", "title": card["title"], "gone": False,
                        "messages": messages})
    return out


def acknowledge(username: str, codes: list[str]) -> list[dict]:
    """El usuario vio los avisos: se actualiza la foto (o se quita del itinerario lo que ya no existe)."""
    wanted = set(codes)
    for it in db.list_itinerary_items(username):
        if it["code"] not in wanted:
            continue
        card = itinerary._item_card(it)
        if card:
            db.set_item_snapshot(username, it["code"], itinerary.snapshot(card))
        else:
            db.remove_item(username, it["code"])
    return pending(username)

"""Motor de itinerario: prefiltro determinístico -> LLM elige y justifica -> se resuelven choques de horario."""
import logging

from . import catalog, config, db, llm, prompts

log = logging.getLogger("reinventar.itinerary")

_DEFAULT_MINUTES = 60
# AWS no publica la duración de cada sesión en el feed; se estima por tipo para poder detectar choques de horario.
_DURATION_BY_TYPE = {
    "Keynote": 120, "Workshop": 120, "Lab": 120, "Bootcamp": 240,
    "Chalk talk": 60, "Breakout session": 60, "Builders' session": 60,
    "Code talk": 60, "Gamified learning": 60, "Exam prep": 90,
    "Lightning talk": 20, "Featured experience": 60, "Event service": 60,
}


def _duration(session_type: str) -> int:
    return _DURATION_BY_TYPE.get(session_type, _DEFAULT_MINUTES)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _overlaps(day: str, start: str, duration: int, taken: list[tuple[str, int, int]]) -> bool:
    s = _minutes(start)
    return any(t_day == day and s < t_start + t_dur and t_start < s + duration for t_day, t_start, t_dur in taken)


def _build_response(items: list[dict]) -> dict:
    days: dict[str, list[dict]] = {}
    for it in items:
        found = catalog.get_instance(it["code"])
        if not found:
            continue
        session, instance = found
        c = catalog.card(session, instance)
        c["locked"] = bool(it.get("locked"))
        c["reason"] = it.get("reason")
        days.setdefault(c["day"], []).append(c)
    for day_items in days.values():
        day_items.sort(key=lambda c: c["start"] or "")
    ordered = [{"day": d, "sessions": days[d]} for d in sorted(days)]
    return {"days": ordered, "total": sum(len(d["sessions"]) for d in ordered)}


def get_current() -> dict:
    result = _build_response(db.list_itinerary_items())
    result["skipped"] = []
    result["notes"] = ""
    return result


def generate(profile: dict, prompt: str) -> dict:
    db.save_profile(profile.get("role", ""), profile.get("experience", ""), profile.get("interests") or [], prompt or "")

    locked = [it for it in db.list_itinerary_items() if it["locked"]]
    locked_bases = set()
    taken: list[tuple[str, int, int]] = []
    confirmed_cards = []
    for it in locked:
        found = catalog.get_instance(it["code"])
        if not found:
            continue
        session, instance = found
        locked_bases.add(session["base"])
        taken.append((instance["d"], _minutes(instance["st"]), _duration(session.get("type"))))
        confirmed_cards.append(catalog.card(session, instance))

    candidates = [c for c in catalog.prefilter(profile, prompt, config.ITINERARY_CANDIDATE_LIMIT) if c["base"] not in locked_bases]
    if not candidates:
        raise ValueError("No encontramos sesiones que calcen con tu perfil. Probá con un prompt más amplio.")

    raw = llm.complete(config.ITINERARY_MODEL, prompts.ITINERARY_SYSTEM, prompts.itinerary_user(profile, prompt, candidates, confirmed_cards), 4000)
    try:
        parsed = llm.parse_json(raw)
    except ValueError:
        log.error("El LLM (%s) no devolvió JSON. Primeros 500 caracteres: %r", config.ITINERARY_MODEL, raw[:500])
        raise

    accepted, skipped = [], []
    for pick in parsed.get("picks", []):
        session = catalog.get_session(pick.get("base", ""))
        if not session:
            continue
        duration = _duration(session.get("type"))
        chosen = next(
            (inst for inst in sorted(session["instances"], key=lambda i: (i["d"], i["st"]))
             if not _overlaps(inst["d"], inst["st"], duration, taken)),
            None,
        )
        if not chosen:
            skipped.append({"base": session["base"], "title": session["title"], "reason": "No quedaba un horario libre sin superposición."})
            continue
        taken.append((chosen["d"], _minutes(chosen["st"]), duration))
        accepted.append({"code": chosen["c"], "base": session["base"], "day": chosen["d"], "start": chosen["st"], "reason": pick.get("reason", "")})

    db.replace_itinerary_items(accepted)
    result = _build_response(db.list_itinerary_items())
    result["skipped"] = skipped
    result["notes"] = parsed.get("notes", "")
    return result


def add_manual(code: str) -> dict:
    found = catalog.get_instance(code)
    if not found:
        raise ValueError("Código de sesión inexistente")
    session, instance = found
    db.add_item(code, session["base"], instance["d"], instance["st"], locked=True)
    return get_current()


def set_lock(code: str, locked: bool) -> dict:
    db.set_item_locked(code, locked)
    return get_current()


def remove(code: str) -> dict:
    db.remove_item(code)
    return get_current()

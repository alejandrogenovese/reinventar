"""Catálogo de sesiones de re:Invent: se carga una sola vez en memoria y se indexa/filtra desde ahí."""
import re

from . import config, venues

_sessions: list[dict] | None = None

_STOPWORDS = {
    "de", "la", "el", "en", "y", "a", "que", "los", "las", "un", "una", "con", "para", "del", "por", "su",
    "the", "and", "for", "with", "that", "this", "from", "are", "our",
}


class CatalogUnavailable(Exception):
    """El JSON del catálogo no está en CATALOG_PATH (normal si todavía no se subió al Volume de Railway)."""


def load(path=None) -> None:
    global _sessions
    import json

    try:
        with open(path or config.CATALOG_PATH, encoding="utf-8") as f:
            _sessions = json.load(f)
    except OSError as e:
        raise CatalogUnavailable(str(e)) from e


def _data() -> list[dict]:
    if _sessions is None:
        load()
    return _sessions


def _split(field: str | None) -> list[str]:
    return [x.strip() for x in (field or "").split(";") if x.strip()]


def get_session(base: str) -> dict | None:
    return next((s for s in _data() if s["base"] == base), None)


def get_instance(code: str) -> tuple[dict, dict] | None:
    for s in _data():
        for inst in s.get("instances", []):
            if inst["c"] == code:
                return s, inst
    return None


def card(session: dict, instance: dict) -> dict:
    """Una sesión + una de sus instancias, aplanadas para el frontend (lista, mapa, itinerario)."""
    return {
        "code": instance["c"],
        "base": session["base"],
        "title": session["title"],
        "type": session.get("type"),
        "level": session.get("level"),
        "topic": _split(session.get("topic")),
        "aoi": _split(session.get("aoi")),
        "services": _split(session.get("services")),
        "speakers": session.get("speakers"),
        "abstract": session.get("abstract"),
        "newlaunch": bool(session.get("newlaunch")),
        "day": instance.get("d"),
        "start": instance.get("st"),
        "seats": instance.get("seats"),
        "walk_in": bool(instance.get("walk")),
        "venue": venues.resolve(instance.get("v", "")),
    }


def facets() -> dict:
    """Valores distintos con conteo, para armar el cuestionario y los filtros de búsqueda."""
    def top(counter: dict[str, int]) -> list[dict]:
        return [{"value": k, "count": v} for k, v in sorted(counter.items(), key=lambda kv: -kv[1]) if k]

    types, levels, topics, aois, hotels, dates = {}, {}, {}, {}, {}, {}
    for s in _data():
        types[s.get("type", "")] = types.get(s.get("type", ""), 0) + 1
        levels[s.get("level", "")] = levels.get(s.get("level", ""), 0) + 1
        for t in _split(s.get("topic")):
            topics[t] = topics.get(t, 0) + 1
        for a in _split(s.get("aoi")):
            aois[a] = aois.get(a, 0) + 1
        for inst in s.get("instances", []):
            hotel = (inst.get("v") or "").split("|")[0].strip()
            if hotel:
                hotels[hotel] = hotels.get(hotel, 0) + 1
            if inst.get("d"):
                dates[inst["d"]] = dates.get(inst["d"], 0) + 1

    return {
        "types": top(types), "levels": top(levels), "topics": top(topics), "aois": top(aois),
        "venues": top(hotels),
        "dates": [{"value": d, "count": dates[d]} for d in sorted(dates)],
    }


def search(q=None, day=None, venue=None, topic=None, aoi=None, level=None, kind=None, limit=100) -> list[dict]:
    q = (q or "").strip().lower()
    out = []
    for s in _data():
        if kind and s.get("type") != kind:
            continue
        if level and s.get("level") != level:
            continue
        if topic and topic not in _split(s.get("topic")):
            continue
        if aoi and aoi not in _split(s.get("aoi")):
            continue
        if q and q not in s.get("title", "").lower() and q not in (s.get("abstract") or "").lower():
            continue
        for inst in s.get("instances", []):
            if day and inst.get("d") != day:
                continue
            if venue and not (inst.get("v") or "").startswith(venue):
                continue
            out.append(card(s, inst))
            if len(out) >= limit:
                return out
    return out


def _terms(*texts: str) -> set[str]:
    words = re.findall(r"[a-záéíóúñ0-9]{3,}", " ".join(texts).lower())
    return {w for w in words if w not in _STOPWORDS}


def prefilter(profile: dict, prompt: str, limit: int) -> list[dict]:
    """Ranking determinístico por keywords: acota el catálogo antes de llamar al LLM (son 1759 sesiones, no entran todas)."""
    terms = _terms(profile.get("role", ""), profile.get("experience", ""), prompt or "")
    interests = set(profile.get("interests") or [])
    scored = []
    for s in _data():
        title = s.get("title", "").lower()
        abstract = (s.get("abstract") or "").lower()
        services = (s.get("services") or "").lower()
        topic_aoi = set(_split(s.get("topic")) + _split(s.get("aoi")))
        score = 0.0
        for t in terms:
            if t in title:
                score += 3
            if t in abstract:
                score += 1
            if t in services:
                score += 1
        if interests & topic_aoi:
            score += 4 * len(interests & topic_aoi)
        score += min(s.get("score", 0), 25) * 0.08  # desempate leve con el score propio del catálogo
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [
        {**s, "topic": _split(s.get("topic")), "aoi": _split(s.get("aoi")), "relevance": round(sc, 1)}
        for sc, s in scored[:limit]
    ]

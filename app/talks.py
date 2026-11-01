"""Vínculo entre una grabación y la charla del catálogo: elegirla al grabar y darle contexto al resumen.

El código de la grabación (sessions.code) es el código del horario (ARC407, ANT320-R1) o el de la charla (base).
"""
import logging

from . import catalog, search

log = logging.getLogger("reinventar.talks")

PICK_LIMIT = 8
ABSTRACT_LIMIT = 1500
_KIND_BY_TYPE = {
    "Keynote": "Keynote",
    "Chalk talk": "Chalk talk",
    "Workshop": "Workshop", "Builders' session": "Workshop", "Code talk": "Workshop", "Lab": "Workshop", "Bootcamp": "Workshop",
}


def normalize_code(code: str | None) -> str | None:
    return (code or "").strip().upper() or None


def recording_kind(session_type: str | None) -> str:
    """Tipo de grabación (guía del resumen) según el tipo de charla del catálogo."""
    return _KIND_BY_TYPE.get(session_type or "", "Breakout")


def resolve(code: str | None) -> tuple[dict, dict | None] | None:
    """(charla, horario) del código; el horario es None si el código es el de la charla y no tiene horarios."""
    code = normalize_code(code)
    if not code:
        return None
    try:
        found = catalog.get_instance(code)
        if found:
            return found
        session = catalog.get_session(code)
    except catalog.CatalogUnavailable as e:
        log.warning("Catálogo no disponible para resolver %s: %s", code, e)
        return None
    if not session:
        return None
    instances = session.get("instances") or []
    return session, (instances[0] if instances else None)


def link(code: str | None) -> dict | None:
    found = resolve(code)
    return {"base": found[0]["base"], "title": found[0]["title"]} if found else None


def _pick_card(session: dict, instance: dict) -> dict:
    return {**catalog.card(session, instance), "recording_kind": recording_kind(session.get("type"))}


def _code_matches(q: str) -> list[tuple[dict, dict]]:
    exact, prefix = [], []
    for s in catalog.all_sessions():
        for inst in s.get("instances", []):
            if inst["c"] == q:
                exact.append((s, inst))
            elif inst["c"].startswith(q) or s["base"].startswith(q):
                prefix.append((s, inst))
    return exact + prefix


def pick(q: str) -> list[dict]:
    """Horarios para elegir al grabar: por código (exacto, después prefijo) y por título.
    La búsqueda por tema/significado solo entra si no hubo ninguna coincidencia directa (si no, mete ruido)."""
    candidates = _code_matches(normalize_code(q))
    needle = catalog.fold(q.strip())
    by_title = [s for s in catalog.all_sessions() if needle in catalog.fold(s.get("title"))]
    if not candidates and not by_title:
        by_title = search.hybrid(q, PICK_LIMIT)
    for s in by_title:
        candidates += [(s, inst) for inst in s.get("instances", [])]
    seen, out = set(), []
    for s, inst in candidates:
        if inst["c"] not in seen:
            seen.add(inst["c"])
            out.append(_pick_card(s, inst))
        if len(out) == PICK_LIMIT:
            break
    return out


def _speaker_lines(session: dict) -> list[str]:
    return [f"{p['name']} — {', '.join(x for x in (p.get('title'), p.get('company')) if x) or 'sin cargo cargado'}"
            for p in session.get("people", [])]


def context(code: str | None) -> str:
    """Datos oficiales de la charla para el prompt del resumen ("" si el código no está en el catálogo)."""
    found = resolve(code)
    if not found:
        return ""
    s = found[0]
    lines = [
        f"Código: {s['base']}",
        f"Título oficial: {s['title']}",
        f"Tipo: {s.get('type') or '—'}" + (f" · Nivel {s['level']}" if s.get("level") else ""),
        "Speakers: " + ("; ".join(_speaker_lines(s)) or (s.get("speakers") or "sin datos")),
        f"Servicios: {', '.join(catalog.split_field(s.get('services'))) or '—'}",
        f"Tópicos: {', '.join(catalog.split_field(s.get('topic'))) or '—'}",
        f"Abstract oficial: {(s.get('abstract') or '—')[:ABSTRACT_LIMIT]}",
    ]
    return "\n".join(lines)


def proper_names(code: str | None) -> list[str]:
    """Nombres de speakers, empresas y servicios, para que la traducción los escriba bien."""
    found = resolve(code)
    if not found:
        return []
    s = found[0]
    people = s.get("people", [])
    names = [p["name"] for p in people] + [p["company"] for p in people if p.get("company")]
    return list(dict.fromkeys(names + catalog.split_field(s.get("services"))))

"""Catálogo de sesiones de re:Invent: se carga una sola vez desde Postgres (schema reinvent) y se indexa/filtra en memoria.

Cada sesión conserva la forma que tenía el JSON original (base, title, topic "a;b", instances [{c,d,st,v,seats,walk}])
y suma "people": los speakers en orden, con cargo, empresa, industria y sector.
"""
import logging
import re

import psycopg

from . import pg, sectors, venues

log = logging.getLogger("reinventar.catalog")

_sessions: list[dict] | None = None

_STOPWORDS = {
    "de", "la", "el", "en", "y", "a", "que", "los", "las", "un", "una", "con", "para", "del", "por", "su",
    "the", "and", "for", "with", "that", "this", "from", "are", "our",
}

# Una fila por sesión; horarios y speakers vienen agregados como JSON. sector_industria está en el schema de la app.
_LOAD_SQL = """
WITH people AS (
  SELECT ss.id_speech,
         jsonb_agg(jsonb_build_object(
           'id', sk.id_speaker, 'name', sk.nombre,
           'title', p.cargo_actual, 'seniority', p.seniority, 'linkedin', p.linkedin_url, 'match', p.calidad_match,
           'company_id', e.id_empresa, 'company', coalesce(e.nombre, ss.empresa_original),
           'industry', e.industria, 'sector', si.sector, 'is_amazon', coalesce(e.es_amazon, false)
         ) ORDER BY ss.orden) AS people
  FROM reinvent.speech_speaker ss
  JOIN reinvent.speaker sk ON sk.id_speaker = ss.id_speaker
  LEFT JOIN reinvent.speaker_perfil p ON p.id_speaker = ss.id_speaker
  LEFT JOIN reinvent.empresa e ON e.id_empresa = ss.id_empresa
  LEFT JOIN sector_industria si ON si.industria = e.industria
  GROUP BY ss.id_speech
), instances AS (
  SELECT id_speech,
         min(fecha + hora_inicio) AS first_at,
         jsonb_agg(jsonb_build_object(
           'c', codigo, 'd', fecha::text, 'st', to_char(hora_inicio, 'HH24:MI'),
           'v', sede || coalesce('|' || replace(sala, ' · ', '|'), ''), 'seats', cupo, 'walk', walk_up
         ) ORDER BY fecha, hora_inicio) AS instances
  FROM reinvent.speech_horario
  GROUP BY id_speech
)
SELECT s.id_speech AS base, s.titulo AS title, s.tipo AS type, coalesce(s.nivel::text, '') AS level,
       array_to_string(s.topicos, ';') AS topic, array_to_string(s.servicios, ';') AS services,
       coalesce(s.area_interes, '') AS aoi, s.formato AS features, s.es_lanzamiento AS newlaunch,
       s.speakers_original AS speakers, s.resumen AS abstract,
       coalesce(i.instances, '[]'::jsonb) AS instances, coalesce(p.people, '[]'::jsonb) AS people
FROM reinvent.speech s
LEFT JOIN instances i ON i.id_speech = s.id_speech
LEFT JOIN people p ON p.id_speech = s.id_speech
ORDER BY i.first_at NULLS LAST, s.id_speech
"""


class CatalogUnavailable(Exception):
    """El schema reinvent no está cargado en Postgres (correr scripts/sync_to_railway.sh) o la base no responde."""


def load() -> int:
    """(Re)carga el catálogo desde Postgres; devuelve la cantidad de sesiones."""
    global _sessions
    try:
        with pg.pool().connection() as c:
            sectors.ensure(c)  # el join con sector_industria no puede depender de que db.init() haya corrido antes
            rows = c.execute(_LOAD_SQL).fetchall()
    except (psycopg.Error, pg.DatabaseNotConfigured) as e:
        raise CatalogUnavailable(str(e)) from e
    if not rows:
        raise CatalogUnavailable("reinvent.speech está vacía")
    _sessions = [dict(r) for r in rows]
    log.info("Catálogo cargado desde Postgres: %d sesiones", len(_sessions))
    return len(_sessions)


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
        "people": session.get("people", []),
        "abstract": session.get("abstract"),
        "newlaunch": bool(session.get("newlaunch")),
        "day": instance.get("d"),
        "start": instance.get("st"),
        "seats": instance.get("seats"),
        "walk_in": bool(instance.get("walk")),
        "venue": venues.resolve(instance.get("v", "")),
    }


def _sectors(session: dict) -> set[str]:
    return {p["sector"] for p in session.get("people", []) if p.get("sector")}


def facets() -> dict:
    """Valores distintos con conteo, para armar el cuestionario y los filtros de búsqueda."""
    def top(counter: dict[str, int]) -> list[dict]:
        return [{"value": k, "count": v} for k, v in sorted(counter.items(), key=lambda kv: -kv[1]) if k]

    types, levels, topics, aois, hotels, dates, sectors = {}, {}, {}, {}, {}, {}, {}
    for s in _data():
        types[s.get("type", "")] = types.get(s.get("type", ""), 0) + 1
        levels[s.get("level", "")] = levels.get(s.get("level", ""), 0) + 1
        for t in _split(s.get("topic")):
            topics[t] = topics.get(t, 0) + 1
        for a in _split(s.get("aoi")):
            aois[a] = aois.get(a, 0) + 1
        for sector in _sectors(s):
            sectors[sector] = sectors.get(sector, 0) + 1
        for inst in s.get("instances", []):
            hotel = (inst.get("v") or "").split("|")[0].strip()
            if hotel:
                hotels[hotel] = hotels.get(hotel, 0) + 1
            if inst.get("d"):
                dates[inst["d"]] = dates.get(inst["d"], 0) + 1

    return {
        "types": top(types), "levels": top(levels), "topics": top(topics), "aois": top(aois),
        "venues": top(hotels), "sectors": top(sectors),
        "dates": [{"value": d, "count": dates[d]} for d in sorted(dates)],
    }


def _matches(q: str, session: dict) -> bool:
    """Texto libre: título, resumen, speakers (nombre) y su empresa/industria/sector/cargo."""
    names = " ".join(p.get("name") or "" for p in session.get("people", [])).lower()
    return any(q in text for text in (session.get("title", "").lower(), (session.get("abstract") or "").lower(),
                                      names, _people_text(session)))


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
        if q and not _matches(q, s):
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


def _people_text(session: dict) -> str:
    """Empresas, industrias, sectores y cargos de los speakers, para que "banca" o "Nubank" encuentren la charla."""
    fields = ("company", "industry", "sector", "title")
    return " ".join(str(p.get(f) or "") for p in session.get("people", []) for f in fields).lower()


def prefilter(profile: dict, prompt: str, limit: int) -> list[dict]:
    """Ranking determinístico por keywords: acota el catálogo antes de llamar al LLM (son 1759 sesiones, no entran todas)."""
    terms = _terms(profile.get("role", ""), profile.get("experience", ""), prompt or "")
    interests = set(profile.get("interests") or [])
    scored = []
    for s in _data():
        title = s.get("title", "").lower()
        abstract = (s.get("abstract") or "").lower()
        services = (s.get("services") or "").lower()
        people = _people_text(s)
        topic_aoi = set(_split(s.get("topic")) + _split(s.get("aoi")))
        score = 0.0
        for t in terms:
            if t in title:
                score += 3
            if t in people:
                score += 2
            if t in abstract:
                score += 1
            if t in services:
                score += 1
        if interests & topic_aoi:
            score += 4 * len(interests & topic_aoi)
        scored.append((score, s))
    # Orden estable: a igual puntaje queda el orden por fecha, así un perfil sin señales igual recibe candidatas.
    scored.sort(key=lambda x: -x[0])
    return [
        {**s, "topic": _split(s.get("topic")), "aoi": _split(s.get("aoi")), "relevance": round(sc, 1)}
        for sc, s in scored[:limit]
    ]

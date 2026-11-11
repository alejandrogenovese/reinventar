"""Catálogo de sesiones de re:Invent: se carga una sola vez desde Postgres (schema reinvent) y se indexa/filtra en memoria.

Cada sesión conserva la forma que tenía el JSON original (base, title, topic "a;b", instances [{c,d,st,v,seats,walk}])
y suma "people": los speakers en orden, con cargo, empresa, industria y sector.
"""
import logging
import unicodedata

import psycopg

from . import pg, sandbox, sectors, travel, venues

log = logging.getLogger("reinventar.catalog")

_sessions: list[dict] | None = None


# Una fila por sesión; horarios y speakers vienen agregados como JSON. sector_industria está en el schema de la app.
_LOAD_SQL = """
WITH people AS (
  SELECT ss.id_speech,
         jsonb_agg(jsonb_build_object(
           'id', sk.id_speaker, 'name', sk.nombre,
           -- un perfil descartado es de un homónimo: no se usan sus datos
           'title', CASE WHEN p.calidad_match IS DISTINCT FROM 'descartado' THEN p.cargo_actual END,
           'seniority', CASE WHEN p.calidad_match IS DISTINCT FROM 'descartado' THEN p.seniority END,
           'linkedin', CASE WHEN p.calidad_match IS DISTINCT FROM 'descartado' THEN p.linkedin_url END,
           'match', p.calidad_match,
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
  SELECT h.id_speech,
         min(h.fecha + h.hora_inicio) AS first_at,
         jsonb_agg(jsonb_build_object(
           'c', h.codigo, 'd', h.fecha::text, 'st', to_char(h.hora_inicio, 'HH24:MI'),
           'v', sd.nombre || coalesce('|' || replace(h.sala, ' · ', '|'), ''), 'seats', h.cupo, 'walk', h.walk_up
         ) ORDER BY h.fecha, h.hora_inicio) AS instances
  FROM reinvent.speech_horario h
  JOIN reinvent.sede sd ON sd.id_sede = h.id_sede
  GROUP BY h.id_speech
)
SELECT s.id_speech AS base, s.titulo AS title, s.tipo AS type, coalesce(s.nivel::text, '') AS level,
       array_to_string(s.topicos, ';') AS topic,
       -- servicios oficiales + los que menciona el resumen (extraer_claves.py), sin repetir
       array_to_string(ARRAY(SELECT DISTINCT unnest(s.servicios || coalesce(s.servicios_mencionados, '{}'))
                             ORDER BY 1), ';') AS services,
       array_to_string(s.tecnologias, ';') AS tech, array_to_string(s.conceptos, ';') AS concepts,
       array_to_string(s.conceptos_en, ';') AS concepts_en, array_to_string(s.enfoque, ';') AS focus,
       coalesce(s.area_interes, '') AS aoi, s.formato AS features, s.es_lanzamiento AS newlaunch,
       s.speakers_original AS speakers, s.resumen AS abstract, s.resumen_es AS abstract_es,
       coalesce(i.instances, '[]'::jsonb) AS instances, coalesce(p.people, '[]'::jsonb) AS people
FROM reinvent.speech s
LEFT JOIN instances i ON i.id_speech = s.id_speech
LEFT JOIN people p ON p.id_speech = s.id_speech
ORDER BY i.first_at NULLS LAST, s.id_speech
"""


class CatalogUnavailable(Exception):
    """El schema reinvent no está cargado en Postgres (correr scripts/sync_to_railway.sh) o la base no responde."""


@sandbox.en_real
def load() -> int:
    """(Re)carga el catálogo desde Postgres; devuelve la cantidad de sesiones."""
    global _sessions
    try:
        with pg.pool().connection() as c:
            sectors.ensure(c)  # el join con sector_industria no puede depender de que db.init() haya corrido antes
            rows = c.execute(_LOAD_SQL).fetchall()
            venues.load(c.execute(venues.LOAD_SQL).fetchall())
            # sede_tiempo llega con el sync del catálogo: si todavía no está, los viajes se estiman por línea recta.
            tiempos = c.execute(travel.LOAD_SQL).fetchall() if c.execute(travel.EXISTE_SQL).fetchone()["existe"] else []
            travel.load(tiempos)
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


def all_sessions() -> list[dict]:
    """Todas las sesiones cargadas (solo lectura: no modificar los dicts)."""
    return _data()


def first_card(session: dict) -> dict | None:
    """Card de la primera instancia (la más temprana) de una sesión, para listados de fichas."""
    instances = session.get("instances") or []
    return card(session, instances[0]) if instances else None


def _split(field: str | None) -> list[str]:
    return [x.strip() for x in (field or "").split(";") if x.strip()]


split_field = _split  # "a;b" -> ["a", "b"], para otros módulos


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
        "tech": _split(session.get("tech")),
        "concepts": _split(session.get("concepts")),
        "focus": _split(session.get("focus")),
        "speakers": session.get("speakers"),
        "people": session.get("people", []),
        "abstract": session.get("abstract"),
        "abstract_es": session.get("abstract_es"),  # traducción al castellano (None si todavía no se tradujo)
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


def fold(text: str | None) -> str:
    """Minúsculas y sin tildes: 'Itaú' y 'itau' son lo mismo para buscar."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _keys_text(session: dict) -> str:
    """Claves extraídas del resumen (tecnologías y conceptos en castellano e inglés), para la búsqueda por texto."""
    # " · " separa las claves: una búsqueda por frase no debe calzar pegando el final de una con el principio de otra.
    return " · ".join(v for k in ("tech", "concepts", "concepts_en") for v in _split(session.get(k)))


def _matches(q: str, session: dict) -> bool:
    """Texto libre (q ya pasado por fold): título, resumen, speakers (nombre) y su empresa/industria/sector/cargo."""
    names = " ".join(p.get("name") or "" for p in session.get("people", []))
    texts = (session.get("title"), session.get("abstract"), session.get("abstract_es"), _keys_text(session), names,
             _people_text(session))
    return any(q in fold(text) for text in texts)


def search(q=None, day=None, venue=None, topic=None, aoi=None, level=None, kind=None, limit=100) -> list[dict]:
    q = fold((q or "").strip())
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


def _people_text(session: dict) -> str:
    """Empresas, industrias, sectores y cargos de los speakers, para que "banca" o "Nubank" encuentren la charla."""
    fields = ("company", "industry", "sector", "title")
    return " ".join(str(p.get(f) or "") for p in session.get("people", []) for f in fields).lower()

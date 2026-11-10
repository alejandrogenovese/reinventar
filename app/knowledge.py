"""Fichas de charla, speaker y empresa: se navegan entre sí (charla → speaker → empresa → otras charlas).

Charlas, speakers en cada charla y empresas salen del catálogo ya cargado en memoria; solo el perfil completo
del speaker (trayectoria, educación, skills) y los datos de la empresa se leen de Postgres.
"""
from . import catalog, db, pg, talks

RELATED_LIMIT = 6
COMPANY_TALKS_LIMIT = 50
COMPANY_PEOPLE_LIMIT = 100
SEARCH_LIMIT = 10
_SHARED_COMPANY_WEIGHT = 3

_index: dict | None = None
_index_source: list | None = None


def _build_index(sessions: list[dict]) -> dict:
    people, companies = {}, {}
    for s in sessions:
        for p in s.get("people", []):
            person = people.setdefault(p["id"], {**p, "talks": 0})
            person["talks"] += 1
            if p.get("company_id"):
                company = companies.setdefault(p["company_id"], {
                    "id": p["company_id"], "name": p["company"], "industry": p.get("industry"),
                    "sector": p.get("sector"), "is_amazon": p.get("is_amazon"), "bases": set()})
                company["bases"].add(s["base"])
    for company in companies.values():
        company["talks"] = len(company["bases"])
    return {"people": people, "companies": companies}


def _idx() -> dict:
    """Índice de personas y empresas; se rearma solo si el catálogo se recargó."""
    global _index, _index_source
    sessions = catalog.all_sessions()
    if _index is None or _index_source is not sessions:
        _index, _index_source = _build_index(sessions), sessions
    return _index


def _person_summary(p: dict) -> dict:
    keys = ("id", "name", "title", "seniority", "company", "company_id", "sector", "is_amazon")
    return {k: p.get(k) for k in keys}


def _talks_of(predicate) -> list[dict]:
    return [card for s in catalog.all_sessions() if predicate(s) and (card := catalog.first_card(s))]


def _tags(session: dict) -> set[str]:
    """Etiquetas para medir afinidad: las oficiales de AWS y las extraídas del resumen (conceptos y tecnologías)."""
    return set(catalog.split_field(session.get("topic")) + catalog.split_field(session.get("aoi"))
               + catalog.split_field(session.get("services")) + catalog.split_field(session.get("concepts"))
               + catalog.split_field(session.get("tech")))


# --- charla ----------------------------------------------------------------------------------

def related_scored(session: dict) -> list[tuple[int, dict]]:
    """(puntaje, sesión) de las charlas parecidas, de mayor a menor: etiquetas en común y, con más peso, empresas en
    común (sin contar Amazon). La usan "Charlas relacionadas" y "Me la perdí" (app/missed.py)."""
    tags = _tags(session)
    companies = {p["company_id"] for p in session.get("people", []) if p.get("company_id") and not p.get("is_amazon")}
    scored = []
    for other in catalog.all_sessions():
        if other["base"] == session["base"]:
            continue
        other_companies = {p["company_id"] for p in other.get("people", []) if p.get("company_id")}
        score = len(tags & _tags(other)) + _SHARED_COMPANY_WEIGHT * len(companies & other_companies)
        if score:
            scored.append((score, other))
    scored.sort(key=lambda x: -x[0])
    return scored


def _related(session: dict) -> list[dict]:
    return [card for _, other in related_scored(session)[:RELATED_LIMIT] if (card := catalog.first_card(other))]


def speech_detail(base: str) -> dict | None:
    session = catalog.get_session(base)
    if not session:
        return None
    instances = [catalog.card(session, i) for i in session.get("instances", [])]
    head = instances[0] if instances else catalog.card(session, {"c": base})
    codes = {base} | {i["c"] for i in session.get("instances", [])}
    return {**head, "instances": instances, "related": _related(session), "recordings": db.recordings_for(codes),
            "recording_kind": talks.recording_kind(session.get("type"))}


# --- speaker ---------------------------------------------------------------------------------

_SPEAKER_SQL = """
SELECT sk.id_speaker, sk.nombre, p.encontrado, p.cargo_actual, p.empresa_actual, p.seniority, p.cargo_desde,
       p.industria_empresa, p.headline, p.ubicacion, p.linkedin_url, p.github_url, p.x_handle, p.skills,
       p.otros_roles_actuales, p.trayectoria, p.educacion, p.fuente, p.fecha_consulta, p.calidad_match
FROM reinvent.speaker sk
LEFT JOIN reinvent.speaker_perfil p ON p.id_speaker = sk.id_speaker
WHERE sk.id_speaker = %s
"""


def _profile(r: dict) -> dict:
    """Perfil profesional (Crustdata). Uno descartado es de otra persona con el mismo nombre: no se muestra.
    Uno a revisar se muestra con aviso (unverified): puede no ser esta persona."""
    if r["calidad_match"] == "descartado":
        return {"found": False, "match": "descartado", "unverified": False, "experience": [], "education": [], "skills": []}
    return {
        "unverified": r["calidad_match"] == "revisar",
        "found": bool(r["encontrado"]), "title": r["cargo_actual"], "current_company": r["empresa_actual"],
        "seniority": r["seniority"], "since": r["cargo_desde"].isoformat() if r["cargo_desde"] else None,
        "industry": r["industria_empresa"], "headline": r["headline"], "location": r["ubicacion"],
        "linkedin": r["linkedin_url"], "github": r["github_url"], "x": r["x_handle"], "skills": r["skills"] or [],
        "other_roles": r["otros_roles_actuales"], "experience": r["trayectoria"] or [], "education": r["educacion"] or [],
        "source": r["fuente"], "consulted": r["fecha_consulta"].isoformat() if r["fecha_consulta"] else None,
        "match": r["calidad_match"],
    }


def speaker_detail(speaker_id: int) -> dict | None:
    with pg.pool().connection() as c:
        r = c.execute(_SPEAKER_SQL, (speaker_id,)).fetchone()
    if not r:
        return None
    talks = _talks_of(lambda s: any(p["id"] == speaker_id for p in s.get("people", [])))
    co_speakers = {p["id"]: _person_summary(p) for t in talks for p in t["people"] if p["id"] != speaker_id}
    in_catalog = _idx()["people"].get(speaker_id, {})
    company = {"id": in_catalog.get("company_id"), "name": in_catalog.get("company"),
               "industry": in_catalog.get("industry"), "sector": in_catalog.get("sector")}
    return {
        "id": r["id_speaker"], "name": r["nombre"],
        "profile": _profile(r) if r["encontrado"] is not None else None,
        "company": company, "talks": talks, "co_speakers": list(co_speakers.values()),
    }


# --- empresa ---------------------------------------------------------------------------------

_EMPRESA_SQL = """
SELECT e.id_empresa, e.nombre, e.grupo, e.industria, e.es_amazon, si.sector
FROM reinvent.empresa e
LEFT JOIN sector_industria si ON si.industria = e.industria
WHERE e.id_empresa = %s
"""


def empresa_detail(empresa_id: int) -> dict | None:
    with pg.pool().connection() as c:
        r = c.execute(_EMPRESA_SQL, (empresa_id,)).fetchone()
    if not r:
        return None
    talks = _talks_of(lambda s: any(p.get("company_id") == empresa_id for p in s.get("people", [])))
    people = sorted((p for p in _idx()["people"].values() if p.get("company_id") == empresa_id), key=lambda p: -p["talks"])
    return {
        "id": r["id_empresa"], "name": r["nombre"], "group": r["grupo"], "industry": r["industria"],
        "sector": r["sector"], "is_amazon": r["es_amazon"],
        "people": [{**_person_summary(p), "talks": p["talks"]} for p in people[:COMPANY_PEOPLE_LIMIT]],
        "people_total": len(people),
        "talks": talks[:COMPANY_TALKS_LIMIT], "talks_total": len(talks),
    }


# --- buscador de entidades -------------------------------------------------------------------

def search_entities(q: str) -> dict:
    """Personas y empresas cuyo nombre contiene q (sin tildes ni mayúsculas), las más presentes primero."""
    needle = catalog.fold(q.strip())
    idx = _idx()
    speakers = sorted((p for p in idx["people"].values() if needle in catalog.fold(p["name"])), key=lambda p: -p["talks"])
    companies = sorted((c for c in idx["companies"].values() if needle in catalog.fold(c["name"])), key=lambda c: -c["talks"])
    return {
        "speakers": [{**_person_summary(p), "talks": p["talks"]} for p in speakers[:SEARCH_LIMIT]],
        "companies": [{k: c[k] for k in ("id", "name", "industry", "sector", "is_amazon", "talks")} for c in companies[:SEARCH_LIMIT]],
    }

"""Briefing para conversar con un speaker o una empresa en el evento.

Junta lo que hay en el catálogo (perfil, trayectoria, charlas, gente de la empresa), el perfil del usuario (rol e
intereses del itinerario) y los resúmenes de sus grabaciones de esas charlas; el LLM arma la ficha.
Se cachea por usuario y entidad: se regenera solo si cambió lo que se le manda al LLM o si se pide explícitamente.
"""
import hashlib
import json
import logging
import time

from . import ask, catalog, config, db, knowledge, langfuse_scores, llm, pg, prompts, trazas
from . import llm_router
from .llm_router import Tarea

log = logging.getLogger("reinventar.briefing")

KINDS = ("speaker", "empresa")
BRIEFING_MAX_TOKENS = 6000
TALKS_LIMIT = 8
PEOPLE_LIMIT = 12
EXPERIENCE_LIMIT = 6
SKILLS_LIMIT = 15
ABSTRACT_LIMIT = 500

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS briefings (
  username   TEXT NOT NULL,
  kind       TEXT NOT NULL,
  entity_id  BIGINT NOT NULL,
  input_hash TEXT NOT NULL,
  content    JSONB NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (username, kind, entity_id)
)"""


class BriefingUnavailable(Exception):
    """El LLM no respondió o no devolvió una ficha válida."""


# --- datos de la entidad, en texto para el prompt ------------------------------------------------
def _talk_lines(talks: list[dict], exclude_person: int | None = None) -> list[str]:
    lines = []
    for t in talks[:TALKS_LIMIT]:
        others = ", ".join(f"{p['name']} ({p.get('company') or '—'})" for p in t.get("people", []) if p.get("id") != exclude_person)
        lines.append(f"- [{t['base']}] {t['title']} ({t.get('type') or '—'})"
                     + (f" — con {others}" if others else "") + f" — {(t.get('abstract') or '')[:ABSTRACT_LIMIT]}")
    return lines


def _speaker_text(sp: dict) -> str:
    p = sp.get("profile") or {}
    company = sp.get("company") or {}
    lines = [
        f"Speaker: {sp['name']}",
        f"Cargo: {p.get('title') or '—'} — {company.get('name') or p.get('current_company') or '—'}"
        f" ({' › '.join(x for x in (company.get('sector'), company.get('industry')) if x) or 'sin sector'})",
        f"Seniority: {p.get('seniority') or '—'} · Ubicación: {p.get('location') or '—'}",
        f"Headline: {p.get('headline') or '—'}",
        f"Coincidencia del perfil encontrado con la persona: {p.get('match') or 'sin dato'}"
        + ("" if p.get("found") else " (no se encontró perfil profesional)"),
    ]
    if p.get("experience"):
        lines.append("Trayectoria:")
        lines += [f"- {x.get('cargo') or '—'} · {x.get('empresa') or '—'} ({x.get('desde') or '?'} – {x.get('hasta') or 'hoy'})"
                  for x in p["experience"][:EXPERIENCE_LIMIT]]
    if p.get("education"):
        lines.append("Educación: " + "; ".join(" — ".join(x for x in (e.get("titulo"), e.get("institucion")) if x) for e in p["education"]))
    if p.get("skills"):
        lines.append("Skills: " + ", ".join(p["skills"][:SKILLS_LIMIT]))
    lines.append(f"Charlas en re:Invent ({len(sp['talks'])}):")
    lines += _talk_lines(sp["talks"], exclude_person=sp["id"])
    return "\n".join(lines)


def _empresa_text(e: dict) -> str:
    lines = [
        f"Empresa: {e['name']}" + (f" (grupo {e['group']})" if e.get("group") and e["group"] != e["name"] else ""),
        f"Sector: {' › '.join(x for x in (e.get('sector'), e.get('industry')) if x) or 'sin clasificar'}"
        + (" · es Amazon/AWS" if e.get("is_amazon") else ""),
        f"Personas que vienen ({e['people_total']}):",
    ]
    lines += [f"- {p['name']} — {p.get('title') or '—'} ({p['talks']} charla{'s' if p['talks'] != 1 else ''})"
              for p in e["people"][:PEOPLE_LIMIT]]
    lines.append(f"Charlas en re:Invent ({e['talks_total']}):")
    lines += _talk_lines(e["talks"])
    return "\n".join(lines)


def _entity(kind: str, entity_id: int) -> tuple[str, list[dict]] | None:
    """(texto para el prompt, charlas) o None si no existe."""
    detail = knowledge.speaker_detail(entity_id) if kind == "speaker" else knowledge.empresa_detail(entity_id)
    if not detail:
        return None
    text = _speaker_text(detail) if kind == "speaker" else _empresa_text(detail)
    return text, detail["talks"]


def _recordings_text(talks: list[dict]) -> str:
    """Resúmenes de las grabaciones (listas) de esas charlas: lo que realmente se dijo."""
    codes = set()
    for t in talks:
        session = catalog.get_session(t["base"]) or {}
        codes |= {t["base"]} | {i["c"] for i in session.get("instances", [])}
    lines = []
    for r in db.ready_summaries_for(codes):
        sm = r["summary"] or {}
        points = "; ".join(sm.get("key_points") or [])
        lines.append(f"- [{r['code']}] {sm.get('tldr') or ''}" + (f" Puntos: {points}" if points else ""))
    return "\n".join(lines)


def _profile_text(profile: dict, ficha: str | None = None) -> str:
    """Quién pregunta: la ficha de la entrevista guiada si la completó (más rica), si no el perfil del armado rápido."""
    if ficha:
        return ficha
    return "\n".join([
        f"Rol: {profile.get('role') or '(sin especificar)'}",
        f"Experiencia: {profile.get('experience') or '(sin especificar)'}",
        f"Intereses: {', '.join(profile.get('interests') or []) or '(ninguno)'}",
        f"Lo que busca en el evento: {profile.get('prompt') or '(sin especificar)'}",
    ])


# --- caché ---------------------------------------------------------------------------------------
def _load(username: str, kind: str, entity_id: int) -> dict | None:
    with pg.pool().connection() as c:
        c.execute(_TABLE_SQL)
        return c.execute("SELECT input_hash, content, created_at FROM briefings WHERE username=%s AND kind=%s AND entity_id=%s",
                         (username, kind, entity_id)).fetchone()


def _save(username: str, kind: str, entity_id: int, input_hash: str, content: dict) -> float:
    now = time.time()
    with pg.pool().connection() as c:
        c.execute(_TABLE_SQL)
        c.execute(
            """INSERT INTO briefings (username, kind, entity_id, input_hash, content, created_at) VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (username, kind, entity_id)
               DO UPDATE SET input_hash=EXCLUDED.input_hash, content=EXCLUDED.content, created_at=EXCLUDED.created_at""",
            (username, kind, entity_id, input_hash, json.dumps(content, ensure_ascii=False), now),
        )
    return now


# --- LLM -----------------------------------------------------------------------------------------
def _valid(parsed: dict) -> bool:
    return isinstance(parsed, dict) and bool(parsed.get("quien")) and isinstance(parsed.get("temas"), list)


def _ask(user: str) -> dict:
    with trazas.abrir():
        try:
            raw = llm.complete(Tarea.BRIEFING, prompts.BRIEFING_SYSTEM, user, BRIEFING_MAX_TOKENS)
            parsed = llm.parse_json_puntuado(raw)
        except Exception as e:
            log.exception("No se pudo generar el briefing (tarea %s)", Tarea.BRIEFING)
            raise BriefingUnavailable from e
        # Los códigos que cita la ficha ([ARC407]) tienen que existir en el catálogo.
        langfuse_scores.puntuar("codigos_inventados", len(ask.codigos_inventados(json.dumps(parsed, ensure_ascii=False))))
    if not _valid(parsed):
        log.error("Briefing sin la forma esperada: %r", str(parsed)[:300])
        raise BriefingUnavailable
    return parsed


def get(username: str, kind: str, entity_id: int, refresh: bool = False) -> dict | None:
    """{"briefing", "cached", "created_at"}; None si la entidad no existe."""
    entity = _entity(kind, entity_id)
    if entity is None:
        return None
    text, talks = entity
    profile = _profile_text(db.get_profile(username) or {}, db.get_interview(username)["ficha_texto"])
    user = prompts.briefing_user(kind, text, profile, _recordings_text(talks))
    input_hash = hashlib.sha256(f"{llm_router.modelo(Tarea.BRIEFING, config.LLM_PROVIDER)}\n{user}".encode()).hexdigest()

    cached = None if refresh else _load(username, kind, entity_id)
    if cached and cached["input_hash"] == input_hash:
        return {"briefing": cached["content"], "cached": True, "created_at": cached["created_at"]}
    content = _ask(user)
    return {"briefing": content, "cached": False, "created_at": _save(username, kind, entity_id, input_hash, content)}

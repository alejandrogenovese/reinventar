"""Chat de búsqueda: la pregunta se responde con las charlas del catálogo que trae la búsqueda híbrida (citadas por
código, [ARC407]) y con lo que se dijo en las grabaciones (app/fragmentos.py, citado como [G1], [G2]…)."""
import logging
import re

from . import catalog, fragmentos, llm, prompts, search
from .llm_router import Tarea

log = logging.getLogger("reinventar.ask")

ASK_CANDIDATES = 24
ASK_MAX_TOKENS = 1500
EXTRA_SESSIONS = 5  # además de las citadas, otras candidatas para seguir mirando
ASK_FRAGMENTOS = 6  # momentos de las grabaciones que se le pasan al LLM (~150 tokens cada uno)
_CODE = re.compile(r"\[([A-Z0-9][A-Z0-9-]{2,19})\]")
_MOMENTO = re.compile(r"\[G(\d{1,2})\]")


class AskUnavailable(Exception):
    """El LLM no respondió (caído, sin key, timeout)."""


def _cited(text: str) -> list[str]:
    """Códigos citados que existen y tienen horario, sin repetir y en orden de aparición."""
    real = (b for b in _CODE.findall(text) if (s := catalog.get_session(b)) and s.get("instances"))
    return list(dict.fromkeys(real))


def _momentos(question: str) -> list[dict]:
    """Fragmentos de las grabaciones para la pregunta. Si la búsqueda falla, el chat sigue solo con el catálogo."""
    try:
        return fragmentos.buscar(question, ASK_FRAGMENTOS)
    except Exception:
        log.exception("No se pudo buscar en lo grabado; el chat responde solo con el catálogo")
        return []


def _momentos_citados(text: str, momentos: list[dict]) -> list[dict]:
    """Los fragmentos citados como [G1], [G2]… que existen, sin repetir y en orden de aparición."""
    numeros = dict.fromkeys(int(n) for n in _MOMENTO.findall(text) if 1 <= int(n) <= len(momentos))
    return [{"ref": f"G{n}", **momentos[n - 1]} for n in numeros]


def answer(question: str, ficha: str | None = None) -> dict:
    """ficha: la de la entrevista guiada de quien pregunta, para priorizar lo que le sirve (None si no la tiene)."""
    hits = search.hybrid(question, ASK_CANDIDATES)
    momentos = _momentos(question)
    try:
        text = llm.complete(Tarea.CHAT, prompts.ASK_SYSTEM, prompts.ask_user(question, hits, ficha, momentos),
                            ASK_MAX_TOKENS).strip()
    except Exception as e:
        log.exception("El chat de búsqueda no pudo consultar al LLM (tarea %s)", Tarea.CHAT)
        raise AskUnavailable from e
    cited = _cited(text)
    extra = [s["base"] for s in hits if s["base"] not in cited and s.get("instances")][:EXTRA_SESSIONS]
    sessions = [catalog.first_card(catalog.get_session(base)) for base in cited + extra]
    return {"answer": text, "cited": cited, "sessions": sessions, "momentos": _momentos_citados(text, momentos)}

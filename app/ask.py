"""Chat de búsqueda: la pregunta se responde con las charlas que trae la búsqueda híbrida, citadas por código."""
import logging
import re

from . import catalog, config, llm, prompts, search

log = logging.getLogger("reinventar.ask")

ASK_CANDIDATES = 24
ASK_MAX_TOKENS = 1500
EXTRA_SESSIONS = 5  # además de las citadas, otras candidatas para seguir mirando
_CODE = re.compile(r"\[([A-Z0-9][A-Z0-9-]{2,19})\]")


class AskUnavailable(Exception):
    """El LLM no respondió (caído, sin key, timeout)."""


def _cited(text: str) -> list[str]:
    """Códigos citados que existen y tienen horario, sin repetir y en orden de aparición."""
    real = (b for b in _CODE.findall(text) if (s := catalog.get_session(b)) and s.get("instances"))
    return list(dict.fromkeys(real))


def answer(question: str) -> dict:
    hits = search.hybrid(question, ASK_CANDIDATES)
    try:
        text = llm.complete(config.ASK_MODEL, prompts.ASK_SYSTEM, prompts.ask_user(question, hits), ASK_MAX_TOKENS).strip()
    except Exception as e:
        log.exception("El chat de búsqueda no pudo consultar al LLM (%s)", config.ASK_MODEL)
        raise AskUnavailable from e
    cited = _cited(text)
    extra = [s["base"] for s in hits if s["base"] not in cited and s.get("instances")][:EXTRA_SESSIONS]
    sessions = [catalog.first_card(catalog.get_session(base)) for base in cited + extra]
    return {"answer": text, "cited": cited, "sessions": sessions}

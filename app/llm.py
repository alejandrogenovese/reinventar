"""Cliente LLM intercambiable: Claude directo o un endpoint OpenAI-compatible (LiteLLM)."""
import json
import logging
import re

import httpx

from . import config

log = logging.getLogger("reinventar.llm")
_anthropic = None


def complete(model: str, system: str, user: str, max_tokens: int = 8000) -> str:
    p = config.LLM_PROVIDER
    if p == "anthropic":
        return _claude(model, system, user, max_tokens)
    if p == "openai":
        return _openai(model, system, user, max_tokens)
    if p == "fake":
        return _fake(system, user)
    raise ValueError(f"LLM_PROVIDER desconocido: {p}")


def _claude(model, system, user, max_tokens):
    global _anthropic
    import anthropic

    if _anthropic is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("Falta ANTHROPIC_API_KEY")
        _anthropic = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=4, timeout=600)
    msg = _anthropic.messages.create(
        model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}]
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    if not text:
        kinds = [getattr(b, "type", "?") for b in msg.content]
        log.warning("Claude devolvió sin texto (model=%s, stop_reason=%s, bloques=%s)", model, msg.stop_reason, kinds)
    return text


def _openai(model, system, user, max_tokens):
    if not config.LLM_BASE_URL:
        raise RuntimeError("Falta LLM_BASE_URL")
    r = httpx.post(
        f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
        json={"model": model, "max_tokens": max_tokens,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        timeout=600,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"LLM {r.status_code}: {r.text[:500]}")
    return r.json()["choices"][0]["message"]["content"]


def _fake(system, user):
    if "[[" in user:  # traducción
        ids = re.findall(r"\[\[(\d+)\]\]", user)
        return "\n".join(f"[[{i}]] Hoy lanzamos la función {i} de Amazon S3." for i in ids)
    if "Candidatas disponibles" in user:  # itinerario
        bases = re.findall(r"- (\w+) \[", user)
        return json.dumps({
            "picks": [{"base": b, "reason": "Calza con tu perfil (fake)."} for b in bases[:3]],
            "notes": "Selección de prueba.",
        })
    return json.dumps({
        "tldr": "Resumen de prueba.",
        "announcements": [{"service": "Amazon S3", "text": "nueva función de prueba."}],
        "key_points": ["Punto uno.", "Punto dos."],
        "services": ["Amazon S3"],
        "quotes": [{"time": "00:00:05", "text": "Hoy lanzamos…"}],
        "takeaways": ["Evaluarlo para el Journey to Cloud."],
    })


def parse_json(text: str) -> dict:
    """Extrae el primer objeto JSON de la respuesta (tolera ```json …``` alrededor)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("La respuesta del LLM no trae JSON")
    return json.loads(m.group(0))

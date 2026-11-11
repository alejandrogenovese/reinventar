"""Cliente LLM intercambiable: Claude directo o un endpoint OpenAI-compatible (LiteLLM)."""
import json
import logging
import re

import httpx

from . import config, sandbox

log = logging.getLogger("reinventar.llm")
_anthropic = None


def complete(model: str, system: str, user: str, max_tokens: int = 8000) -> str:
    p = sandbox.proveedor_llm()
    if p == "anthropic":
        return _claude(model, system, user, max_tokens)
    if p == "openai":
        return _openai(model, system, user, max_tokens)
    if p == "fake":
        return _fake(system, user)
    raise ValueError(f"LLM_PROVIDER desconocido: {p}")


DEFAULT_EFFORT = "medium"
_THINKING_OFF_MODELS = ("claude-sonnet-5-5",)


def thinking_params(model: str) -> dict:
    """Cada modelo acepta una configuración de thinking distinta; la equivocada es un 400.

    - Sonnet 5.5: no acepta {"type": "disabled"}; se apaga con "between_tools" (sólo piensa entre tools, y no usamos).
    - Opus 5.5 y el resto: el thinking no se puede apagar ("between_tools" y "disabled" dan 400); se omite
      y se fija el effort (en Opus 5.5 el default ya es medium, se explicita para que no cambie sin aviso).
    """
    if model.startswith(_THINKING_OFF_MODELS):
        return {"thinking": {"type": "between_tools"}}
    return {"output_config": {"effort": DEFAULT_EFFORT}}


def _claude(model, system, user, max_tokens):
    global _anthropic
    import anthropic

    if _anthropic is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("Falta ANTHROPIC_API_KEY")
        _anthropic = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=4, timeout=600)
    msg = _anthropic.messages.create(
        model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}],
        # extra_body porque "thinking"/"output_config" no son parámetros tipados en anthropic==0.40.0.
        extra_body=thinking_params(model),
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


_FAKE_SERVICE = "Amazon S3"  # servicio que devuelve el LLM falso de los tests


def _fake(system, user):
    if user.startswith("Grupo 0:"):  # nombres de temas emergentes
        ids = re.findall(r"^Grupo (\d+):", user, re.M)
        return json.dumps({"groups": [{"id": int(i), "name": f"Tema {i}"} for i in ids]})
    if "Pedido de filtros:" in user:  # filtros en lenguaje natural
        return json.dumps({"filters": {"sector": ["Finanzas"]}, "q": ""})
    if user.startswith("Entidad a preparar:"):  # briefing
        return json.dumps({
            "quien": "Persona de prueba (fake).", "empresa_y_aws": "Empresa de prueba.", "en_reinvent": "Charla de prueba.",
            "temas": [{"tema": "Tema de prueba", "por_que": "Porque sí."}] * 3, "preguntas": ["¿Pregunta?"], "cuidado": "",
        })
    if user.startswith("Pregunta:"):  # chat de búsqueda
        codes = re.findall(r"^\[([\w-]+)\]", user, re.M)[:2]
        return "Te recomiendo " + " y ".join(f"[{c}]" for c in codes) + " (fake)."
    if user.startswith("Eventos para resumir:"):  # eventos de networking
        items = json.loads(user.split("\n", 1)[1])["eventos"]
        return json.dumps({"eventos": [{"id": i["id"], "resumen_es": f"Evento {i['id']} de prueba.", "tipo": "happy hour",
                                        "temas": ["observabilidad"], "organizadores": ["Acme"]} for i in items]})
    if user.startswith("Charlas para extraer claves:"):  # claves del resumen
        items = json.loads(user.split("\n", 1)[1])["charlas"]
        return json.dumps({"charlas": [{"id": i["id"], "servicios": [_FAKE_SERVICE], "tecnologias": ["Apache Iceberg"],
                                        "conceptos": ["gobierno de datos"], "conceptos_en": ["data governance"],
                                        "enfoque": ["arquitectura", "inventado"]} for i in items]})
    if user.startswith("Resúmenes a traducir:"):  # resúmenes del catálogo
        items = json.loads(user.split("\n", 1)[1])["resumenes"]
        return json.dumps({"traducciones": [{"id": i["id"], "texto": f"Traducción de {i['id']}."} for i in items]})
    if "[[" in user:  # traducción
        ids = re.findall(r"\[\[(\d+)\]\]", user)
        return "\n".join(f"[[{i}]] Hoy lanzamos la función {i} de {_FAKE_SERVICE}." for i in ids)
    if user.startswith("Entrevista para repreguntar:"):
        return json.dumps({"repreguntas": ["¿Quiénes consultan los datos: personas o sistemas?"]})
    if user.startswith("Entrevista para la ficha:"):
        return json.dumps({"resumen": "Persona de prueba (fake).", "evitar": [],
                           "prioridades": [{"tema": "Tema de prueba", "peso": 3, "claves": [_FAKE_SERVICE]}],
                           "consulta_busqueda": "data architecture on AWS"})
    if "Candidatas disponibles" in user:  # itinerario
        bases = re.findall(r"- (\w+) \[", user)
        return json.dumps({
            "picks": [{"base": b, "reason": "Calza con tu perfil (fake)."} for b in bases[:3]],
            "notes": "Selección de prueba.",
        })
    return json.dumps({
        "tldr": "Resumen de prueba.",
        "announcements": [{"service": _FAKE_SERVICE, "text": "nueva función de prueba."}],
        "key_points": ["Punto uno.", "Punto dos."],
        "services": [_FAKE_SERVICE],
        "quotes": [{"time": "00:00:05", "text": "Hoy lanzamos…"}],
        "takeaways": ["Evaluarlo para el Journey to Cloud."],
    })


def parse_json(text: str) -> dict:
    """Extrae el primer objeto JSON de la respuesta (tolera ```json …``` alrededor)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("La respuesta del LLM no trae JSON")
    return json.loads(m.group(0))

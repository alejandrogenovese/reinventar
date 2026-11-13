"""Speech-to-text intercambiable. Devuelve segmentos [{start, end, text}] en segundos.

- openai: un endpoint compatible con OpenAI (hoy Groq) con STT_BASE_URL, STT_API_KEY y STT_MODEL.
- litellm: el mismo gateway que el LLM (LLM_BASE_URL y LLM_API_KEY), con el alias de cada uso (stt-charlas, stt-voz),
  el uso como tag y el usuario del pedido, igual que las tareas del LLM.
"""
import json
from pathlib import Path

import httpx

from . import config, llm_router, sandbox, trazas
from .llm_router import UsoSTT

# Vocabulario que se le pasa a Whisper como "prompt": sin contexto confunde nombres propios ("lighthouse" por lakehouse,
# "Neptium" por Neptune, "Tranium" por Trainium). Va escrito como el texto esperado, en el idioma de cada uso.
LARGO_MAXIMO_VOCABULARIO = 600  # Whisper solo mira los últimos ~224 tokens del prompt
VOCABULARIO: dict[UsoSTT, str] = {
    UsoSTT.CHARLAS: (
        "AWS re:Invent session about Amazon Bedrock, AgentCore, SageMaker, Amazon Q, Kiro, Trainium, Inferentia, "
        "Graviton, Nova, S3, S3 Tables, Apache Iceberg, lakehouse, Redshift, Aurora, DynamoDB, Neptune, OpenSearch, "
        "Glue, Athena, EMR, Lake Formation, DataZone, Kinesis, MSK, Lambda, EKS, Fargate, IAM and agentic AI."
    ),
    UsoSTT.VOZ: (
        "Respuestas sobre arquitectura de datos en AWS: migración de Teradata a la nube, Redshift, un lakehouse con "
        "Apache Iceberg y S3, Glue, Athena, EMR, Lake Formation, DataZone, Neptune para grafos, SageMaker, Bedrock, "
        "agentes de IA, gobierno de datos y disponibilizar los datos para los analistas de negocio."
    ),
}


def transcribe(path: Path, offset: float, language: str | None = None, uso: UsoSTT = UsoSTT.CHARLAS) -> list[dict]:
    """language: código ISO (por defecto STT_LANGUAGE, el de las charlas; la entrevista pasa "es")."""
    provider = sandbox.proveedor_stt()
    language = language or config.STT_LANGUAGE
    if provider == "openai":
        segs = _openai_compatible(path, language, config.STT_BASE_URL, config.STT_API_KEY, config.STT_MODEL,
                                  {"prompt": VOCABULARIO[uso]})
    elif provider == "litellm":
        segs = _openai_compatible(path, language, config.LLM_BASE_URL, config.LLM_API_KEY,
                                  llm_router.modelo_stt(uso, provider), {"prompt": VOCABULARIO[uso], **_metadata(uso)})
    elif provider == "local":
        segs = _faster_whisper(path, language)
    elif provider == "fake":
        segs = _fake(path)
    else:
        raise ValueError(f"STT_PROVIDER desconocido: {provider}")
    return [{"start": s["start"] + offset, "end": s["end"] + offset, "text": s["text"].strip()} for s in segs if s["text"].strip()]


def _metadata(uso: UsoSTT) -> dict:
    """Campos extra del form para el gateway: el uso como tag y la traza de Langfuse (app/trazas.py), serializada
    porque va en un form. La voz de la entrevista va a la sesión de la entrevista; las charlas, a la de la grabación."""
    tag = llm_router.alias_stt(uso)
    usuario = llm_router.usuario_actual()
    flujo = trazas.FLUJO_ENTREVISTA if uso == UsoSTT.VOZ else "grabacion"
    meta = trazas.metadata(tag, VOCABULARIO[uso], flujo)
    return {"metadata": json.dumps(meta), **({"user": usuario} if usuario else {})}


def _openai_compatible(path: Path, language: str, base_url: str, api_key: str | None, model: str,
                       extra: dict | None = None) -> list[dict]:
    if not api_key:
        raise RuntimeError("Falta la clave del STT (STT_API_KEY, o LLM_API_KEY con el gateway)")
    if not base_url:
        raise RuntimeError("Falta la URL del STT (STT_BASE_URL, o LLM_BASE_URL con el gateway)")
    with path.open("rb") as f:
        r = httpx.post(
            f"{base_url.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data={"model": model, "language": language, "response_format": "verbose_json", "temperature": "0",
                  **(extra or {})},
            files={"file": (path.name, f, "audio/ogg")},
            timeout=httpx.Timeout(600, connect=20),
        )
    if r.status_code >= 400:
        raise RuntimeError(f"STT {r.status_code}: {r.text[:500]}")
    body = r.json()
    segs = body.get("segments")
    if not segs:  # algunos modelos no devuelven segmentos: un solo bloque
        return [{"start": 0.0, "end": float(body.get("duration") or 0), "text": body.get("text", "")}]
    return [{"start": float(s["start"]), "end": float(s["end"]), "text": s["text"]} for s in segs]


_model = None


def _faster_whisper(path: Path, language: str) -> list[dict]:
    global _model
    from faster_whisper import WhisperModel  # opcional: pip install faster-whisper

    if _model is None:
        _model = WhisperModel(config.STT_MODEL if "/" in config.STT_MODEL or config.STT_MODEL.startswith("large") else "large-v3-turbo",
                              device="cpu", compute_type="int8")
    segments, _ = _model.transcribe(str(path), language=language, vad_filter=True)
    return [{"start": s.start, "end": s.end, "text": s.text} for s in segments]


def _fake(path: Path) -> list[dict]:
    from .audio import duration

    d = duration(path)
    out, t, i = [], 0.0, 0
    while t < d:
        out.append({"start": t, "end": min(d, t + 5), "text": f"Today we are launching Amazon S3 feature number {i}."})
        t += 5
        i += 1
    return out

"""Scores de calidad en Langfuse: la app ya sabe cuándo algo salió mal (JSON roto, líneas que el modelo se comió,
códigos inventados) y lo manda como score sobre la traza de esa llamada (app/trazas.py).

- Sin LANGFUSE_PUBLIC_KEY y LANGFUSE_SECRET_KEY no hace nada.
- Solo puntúa llamadas que fueron por el gateway LiteLLM: las demás (Claude directo, fake) no tienen traza en Langfuse.
- Va en un thread aparte, con timeout corto: nunca frena ni rompe el pedido. Los errores se loguean sin datos sensibles
  (ni claves ni el cuerpo de la respuesta).
"""
import logging
import threading

import httpx

from . import config, sandbox, trazas

log = logging.getLogger("reinventar.langfuse")

TIMEOUT_SEGUNDOS = 5
_RUTA = "/api/public/scores"


def _activo() -> bool:
    return bool(config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY)


def _mandar(cuerpo: dict) -> None:
    try:
        r = httpx.post(f"{config.LANGFUSE_HOST.rstrip('/')}{_RUTA}", json=cuerpo,
                       auth=(config.LANGFUSE_PUBLIC_KEY, config.LANGFUSE_SECRET_KEY), timeout=TIMEOUT_SEGUNDOS)
        if r.status_code >= 400:
            log.warning("Langfuse rechazó el score %s (HTTP %d)", cuerpo["name"], r.status_code)
    except Exception as e:  # noqa: BLE001 - un score perdido no puede romper nada
        log.warning("No se pudo mandar el score %s a Langfuse: %s", cuerpo["name"], type(e).__name__)


def enviar(trace_id: str, nombre: str, valor: float, comentario: str | None = None) -> threading.Thread | None:
    """Manda el score en segundo plano. Devuelve el thread (para esperarlo en los tests) o None si no hay claves."""
    if not _activo():
        return None
    cuerpo = {"traceId": trace_id, "name": nombre, "value": valor, "dataType": "NUMERIC",
              **({"comment": comentario} if comentario else {})}
    hilo = threading.Thread(target=_mandar, args=(cuerpo,), name="langfuse-score", daemon=True)
    hilo.start()
    return hilo


def puntuar(nombre: str, valor: float) -> threading.Thread | None:
    """Score sobre la traza abierta (trazas.abrir). Sin traza o sin gateway, nada."""
    traza = trazas.actual()
    if traza is None or sandbox.proveedor_llm() != "litellm":
        return None
    return enviar(traza.trace_id, nombre, valor)

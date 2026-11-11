"""Router de tareas del LLM: cada parte de la app pide su tarea y el router decide qué modelo usa.

- Con LLM_PROVIDER=litellm, cada tarea va a su alias en el gateway (infra/litellm/config.yaml: "rx-<tarea>"). Cambiar el
  modelo de una parte es cambiar ese alias y reiniciar LiteLLM, sin deployar la app.
- Con el proveedor directo (anthropic u openai), cada tarea usa el modelo de hoy (las variables *_MODEL de config).
- LLM_RUTA_<TAREA> fuerza el modelo de una tarea (para probar uno nuevo sin tocar el gateway).
Cada llamada lleva la tarea como tag y el usuario (contextvar que fija el middleware de app.main), así el consumo de cada
parte se ve por separado en el panel de LiteLLM y en Langfuse.
"""
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum

from . import config


class Tarea(StrEnum):
    RESUMEN = "resumen"                          # resumen de una grabación
    TRADUCCION = "traduccion"                    # traducción en vivo de la transcripción
    ENTREVISTA = "entrevista"                    # repreguntas y ficha del armado guiado
    ITINERARIO = "itinerario"                    # armado rápido
    RAZONES = "razones"                          # por qué te sirve cada opción del armado guiado
    CHAT = "chat"                                # chat de búsqueda
    FILTROS = "filtros"                          # filtros en lenguaje natural (Explorar)
    TEMAS = "temas"                              # nombres de los temas emergentes
    BRIEFING = "briefing"                        # ficha para charlar con un speaker o empresa
    CATALOGO = "catalogo"                        # scripts: claves del resumen y eventos de networking
    CATALOGO_TRADUCCION = "catalogo-traduccion"  # script: traducción de los resúmenes del catálogo


# Modelo directo de cada tarea (sin gateway): el de hoy, con las mismas variables de siempre.
_DIRECTO: dict[Tarea, Callable[[], str]] = {
    Tarea.RESUMEN: lambda: config.SUMMARY_MODEL,
    Tarea.TRADUCCION: lambda: config.TRANSLATE_MODEL,
    Tarea.ENTREVISTA: lambda: config.ITINERARY_MODEL,
    Tarea.ITINERARIO: lambda: config.ITINERARY_MODEL,
    Tarea.RAZONES: lambda: config.GUIDED_MODEL,
    Tarea.CHAT: lambda: config.ASK_MODEL,
    Tarea.FILTROS: lambda: config.ASK_MODEL,
    Tarea.TEMAS: lambda: config.ASK_MODEL,
    Tarea.BRIEFING: lambda: config.BRIEFING_MODEL,
    Tarea.CATALOGO: lambda: config.EXTRACT_MODEL,
    Tarea.CATALOGO_TRADUCCION: lambda: config.TRANSLATE_MODEL,
}

_usuario: ContextVar[str | None] = ContextVar("llm_usuario", default=None)


def alias(tarea: Tarea) -> str:
    """Nombre del modelo de la tarea en el gateway (model_name en infra/litellm/config.yaml)."""
    return f"rx-{tarea.value}"


def modelo(tarea: Tarea, proveedor: str) -> str:
    forzado = os.environ.get(f"LLM_RUTA_{tarea.name}")
    if forzado:
        return forzado
    return alias(tarea) if proveedor == "litellm" else _DIRECTO[tarea]()


@contextmanager
def como_usuario(username: str | None) -> Iterator[None]:
    """Las llamadas al LLM dentro del bloque quedan a nombre de este usuario (trazas y gasto por persona)."""
    token = _usuario.set(username)
    try:
        yield
    finally:
        _usuario.reset(token)


def usuario_actual() -> str | None:
    return _usuario.get()

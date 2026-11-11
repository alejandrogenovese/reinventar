"""Entrevista del itinerario guiado ("Te conocemos"): respuestas, repreguntas del LLM y la ficha de la persona.

Las respuestas se guardan de a una (la PWA muestra una pregunta por pantalla) en itinerary_profile.respuestas. Con las
8 obligatorias completas, el LLM hace hasta 2 repreguntas y arma la ficha: resumen, prioridades con claves de búsqueda
y una consulta para la búsqueda semántica. Lo que la persona eligió explícitamente (nivel, formatos, industria, ritmo)
no lo decide el LLM: se copia de las respuestas.
"""
import logging
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from . import llm, prompts
from .llm_router import Tarea

log = logging.getLogger("reinventar.interview")

Industria = Literal["banca", "retail", "salud", "gobierno", "tech", "otra"]
Anios = Literal["0-2", "3-5", "6-10", "+10"]
Origen = Literal["desarrollo", "infra/ops", "datos", "seguridad", "negocio", "otro"]
NivelCharla = Literal[100, 200, 300, 400, 500]
Formato = Literal["Breakout session", "Chalk talk", "Workshop", "Builders' session", "Code talk", "Lightning talk",
                  "Keynote"]
Objetivo = Literal["aprender algo puntual", "ver el roadmap", "casos de clientes", "networking", "conocer proveedores"]
CharlasPorDia = Literal["3-4", "5-6", "todas"]
Corto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]

OBLIGATORIAS = ("rol", "dia_a_dia", "equipo", "desafio", "trayectoria", "nivel", "tecnologias", "objetivos")
MIN_DIA_A_DIA = 80   # caracteres: lo suficiente para que el LLM entienda qué hace
MIN_DESAFIO = 60
MAX_REPREGUNTAS = 2
MAX_VOZ_BYTES = 10 * 1024 * 1024  # ~10 min de opus: sobra para una respuesta
IDIOMA_VOZ = "es"                 # el STT de las charlas está en inglés; la entrevista se responde en castellano


class Rol(BaseModel):
    texto: str = Field(min_length=2, max_length=200)
    industria: Industria


class Equipo(BaseModel):
    lidera: bool
    personas: int | None = Field(None, ge=1, le=1000)
    perfiles: str = Field("", max_length=300)


class Trayectoria(BaseModel):
    anios: Anios
    origen: list[Origen] = Field(min_length=1, max_length=6)


class Nivel(BaseModel):
    niveles: list[NivelCharla] = Field(min_length=1, max_length=5)
    formatos: list[Formato] = Field(default_factory=list, max_length=7)


class Ritmo(BaseModel):
    charlas_por_dia: CharlasPorDia = "5-6"
    almuerzo: bool = True
    eventos_noche: bool = True


class Repregunta(BaseModel):
    pregunta: str = Field(min_length=1, max_length=300)
    respuesta: str = Field("", max_length=1500)


class Respuestas(BaseModel):
    """Todas opcionales: se guardan de a una. faltantes() dice qué obligatorias quedan."""
    model_config = ConfigDict(extra="forbid")

    rol: Rol | None = None
    dia_a_dia: str | None = Field(None, max_length=2000)
    equipo: Equipo | None = None
    desafio: str | None = Field(None, max_length=2000)
    trayectoria: Trayectoria | None = None
    nivel: Nivel | None = None
    tecnologias: list[Corto] | None = Field(None, max_length=40)
    objetivos: list[Objetivo] | None = Field(None, max_length=5)
    evitar: str | None = Field(None, max_length=500)
    ritmo: Ritmo | None = None
    repreguntas: list[Repregunta] | None = Field(None, max_length=MAX_REPREGUNTAS)


class Prioridad(BaseModel):
    tema: str = Field(min_length=1, max_length=80)
    peso: int = Field(ge=1, le=3)
    claves: list[Corto] = Field(default_factory=list, max_length=12)


class Ficha(BaseModel):
    resumen: str = Field(min_length=1, max_length=1500)
    prioridades: list[Prioridad] = Field(min_length=1, max_length=8)
    nivel: list[NivelCharla] = Field(min_length=1, max_length=5)
    formatos: list[Formato] = Field(default_factory=list, max_length=7)
    evitar: list[Corto] = Field(default_factory=list, max_length=10)
    industria: Industria
    ritmo: Ritmo
    consulta_busqueda: str = Field(min_length=1, max_length=600)


class EntrevistaIncompleta(ValueError):
    pass


class FichaInvalida(RuntimeError):
    """El LLM no devolvió una ficha usable."""


def _texto_corto(valor: str | None, minimo: int) -> bool:
    return len((valor or "").strip()) < minimo


def faltantes(r: Respuestas) -> list[str]:
    """Obligatorias sin responder (o respondidas a medias), en el orden de la entrevista."""
    falta = {
        "rol": r.rol is None,
        "dia_a_dia": _texto_corto(r.dia_a_dia, MIN_DIA_A_DIA),
        "equipo": r.equipo is None or (r.equipo.lidera and r.equipo.personas is None),
        "desafio": _texto_corto(r.desafio, MIN_DESAFIO),
        "trayectoria": r.trayectoria is None,
        "nivel": r.nivel is None,
        "tecnologias": not r.tecnologias,
        "objetivos": not r.objetivos,
    }
    return [k for k in OBLIGATORIAS if falta[k]]


def combinar(actuales: dict | None, nuevas: Respuestas) -> Respuestas:
    """Suma lo que llegó a lo que ya estaba (sin pisar lo que no vino) y valida el resultado."""
    return Respuestas(**{**(actuales or {}), **nuevas.model_dump(exclude_unset=True)})


def exigir_completas(r: Respuestas) -> None:
    falta = faltantes(r)
    if falta:
        raise EntrevistaIncompleta(f"Faltan respuestas obligatorias: {', '.join(falta)}")


# ---------- texto para el LLM ----------

def _equipo(e: Equipo) -> str:
    if not e.lidera:
        return "No lidera un equipo"
    return f"Lidera un equipo de {e.personas} personas" + (f" ({e.perfiles})" if e.perfiles else "")


def respuestas_a_texto(r: Respuestas) -> str:
    lineas = [
        f"Rol: {r.rol.texto} · industria: {r.rol.industria}" if r.rol else None,
        f"Día a día: {r.dia_a_dia}" if r.dia_a_dia else None,
        f"Equipo: {_equipo(r.equipo)}" if r.equipo else None,
        f"Desafío principal: {r.desafio}" if r.desafio else None,
        f"Trayectoria: {r.trayectoria.anios} años · viene de {', '.join(r.trayectoria.origen)}" if r.trayectoria else None,
        f"Nivel técnico buscado: {', '.join(map(str, r.nivel.niveles))}"
        + (f" · formatos preferidos: {', '.join(r.nivel.formatos)}" if r.nivel.formatos else "") if r.nivel else None,
        f"Usa hoy: {', '.join(r.tecnologias)}" if r.tecnologias else None,
        f"Qué se quiere llevar: {', '.join(r.objetivos)}" if r.objetivos else None,
        f"Quiere evitar: {r.evitar}" if r.evitar else None,
    ]
    lineas += [f"Repregunta: {q.pregunta}\nRespuesta: {q.respuesta}" for q in (r.repreguntas or []) if q.respuesta]
    return "\n".join(x for x in lineas if x)


def _bolitas(peso: int) -> str:
    return "●" * peso + "○" * (3 - peso)


def ficha_a_texto(f: Ficha) -> str:
    """La ficha en texto, para sumarla a los prompts (armado, chat de búsqueda, briefing)."""
    prioridades = "\n".join(f"  {_bolitas(p.peso)} {p.tema}" + (f" ({', '.join(p.claves)})" if p.claves else "")
                            for p in f.prioridades)
    ritmo = (f"{f.ritmo.charlas_por_dia} charlas por día, {'con' if f.ritmo.almuerzo else 'sin'} almuerzo, "
             f"{'con' if f.ritmo.eventos_noche else 'sin'} eventos a la noche")
    lineas = [
        f.resumen,
        f"Industria: {f.industria}",
        f"Prioridades:\n{prioridades}",
        f"Nivel: {'-'.join(map(str, f.nivel))}" + (f" · prefiere: {', '.join(f.formatos)}" if f.formatos else ""),
        f"Evitar: {', '.join(f.evitar)}" if f.evitar else None,
        f"Ritmo: {ritmo}",
    ]
    return "\n".join(x for x in lineas if x)


# ---------- LLM ----------

def repreguntas(r: Respuestas) -> list[Repregunta]:
    """Hasta 2 repreguntas. Son opcionales: si el LLM falla, se sigue sin ellas."""
    exigir_completas(r)
    try:
        data = llm.parse_json(llm.complete(Tarea.ENTREVISTA, prompts.INTERVIEW_FOLLOWUP_SYSTEM,
                                           prompts.interview_followup_user(respuestas_a_texto(r)), max_tokens=2000))
        return [Repregunta(pregunta=str(q)[:300]) for q in data.get("repreguntas", []) if str(q).strip()][:MAX_REPREGUNTAS]
    except Exception as e:  # noqa: BLE001 - cualquier falla del LLM deja la entrevista sin repreguntas, no la frena
        log.warning("No se pudieron generar las repreguntas: %s", e)
        return []


def armar_ficha(data: dict, r: Respuestas) -> Ficha:
    """Ficha con lo que redactó el LLM + lo que la persona eligió explícitamente (eso no lo cambia el LLM)."""
    return Ficha(
        resumen=data.get("resumen", ""),
        prioridades=data.get("prioridades", []),
        evitar=data.get("evitar", []),
        consulta_busqueda=data.get("consulta_busqueda", ""),
        nivel=r.nivel.niveles,
        formatos=r.nivel.formatos,
        industria=r.rol.industria,
        ritmo=r.ritmo or Ritmo(),
    )


def generar_ficha(r: Respuestas) -> Ficha:
    exigir_completas(r)
    texto = llm.complete(Tarea.ENTREVISTA, prompts.PROFILE_FICHA_SYSTEM,
                         prompts.profile_ficha_user(respuestas_a_texto(r)), max_tokens=4000)
    try:
        return armar_ficha(llm.parse_json(texto), r)
    except (ValueError, ValidationError) as e:
        log.warning("Ficha inválida del LLM: %s", e)
        raise FichaInvalida("No pude armar la ficha; probá de nuevo.") from e

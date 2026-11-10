"""Filtrar en lenguaje natural: "fintechs hablando de agentes el martes" → filtros del explorador.

El LLM solo propone; cada faceta y cada valor se validan contra los valores reales del catálogo (sin tildes ni
mayúsculas) y se devuelven con la grafía canónica. Lo que no existe se informa en "ignored". Nunca se arma SQL.
"""
import datetime
import logging

from . import catalog, config, explore, llm, prompts

log = logging.getLogger("reinventar.nl_filters")

NL_MAX_TOKENS = 2000
Q_LIMIT = 200
VALUES_PER_FACET = 20
_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_LABELS = {
    "tema": "Tema emergente (grupo de charlas parecidas)",
    "sector": "Sector de la empresa", "industria": "Industria de la empresa", "empresa": "Empresa de los speakers",
    "seniority": "Seniority de los speakers", "topico": "Tópico", "area": "Área de interés", "servicio": "Servicio de AWS",
    "tecnologia": "Tecnología que no es de AWS (Iceberg, MCP, dbt…)", "concepto": "Concepto que trata la charla",
    "enfoque": "Enfoque (novedades, arquitectura, caso de cliente, práctica guiada…)",
    "tipo": "Tipo de sesión", "nivel": "Nivel (100 introductorio … 500 experto)", "lanzamiento": "Es un lanzamiento nuevo",
    "dia": "Día", "sede": "Sede (hotel)",
}


class NLFiltersUnavailable(Exception):
    """El LLM no respondió o no devolvió JSON."""


def day_label(day: str) -> str:
    return f"{day} ({_WEEKDAYS[datetime.date.fromisoformat(day).weekday()]})"


def _allowed() -> dict[str, list[str]]:
    """Valores reales de cada faceta (de las más frecuentes a las menos)."""
    facets = explore.explore({}, limit=1)["facets"]
    return {f: [v["value"] for v in facets.get(f, [])] for f in explore.FACETS}


def _catalog_text(allowed: dict[str, list[str]]) -> str:
    lines = []
    for facet, values in allowed.items():
        shown = [day_label(v) for v in values] if facet == "dia" else values
        lines.append(f"{facet} — {_LABELS.get(facet, facet)}: {' | '.join(shown)}")
    return "\n".join(lines)


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    return [value] if value is not None else []


def _validate(proposed: dict, allowed: dict[str, list[str]]) -> tuple[dict[str, list[str]], list[str]]:
    filters, ignored = {}, []
    for facet, values in (proposed if isinstance(proposed, dict) else {}).items():
        canonical = {catalog.fold(v): v for v in allowed.get(facet, [])}
        for value in _as_list(values):
            match = canonical.get(catalog.fold(str(value))) if facet in allowed else None
            if match is None:
                ignored.append(f"{facet}: {value}")
            elif match not in filters.get(facet, []):
                filters[facet] = [*filters.get(facet, []), match][:VALUES_PER_FACET]
    return filters, ignored


def parse(text: str) -> dict:
    """{"filters": {faceta: [valores]}, "q": texto libre restante, "ignored": ["faceta: valor"]}."""
    allowed = _allowed()
    try:
        raw = llm.complete(config.ASK_MODEL, prompts.NL_FILTERS_SYSTEM, prompts.nl_filters_user(_catalog_text(allowed), text), NL_MAX_TOKENS)
        proposed = llm.parse_json(raw)
    except Exception as e:
        log.exception("No se pudo traducir a filtros (pedido de %d caracteres)", len(text))
        raise NLFiltersUnavailable from e
    filters, ignored = _validate(proposed.get("filters"), allowed)
    q = proposed.get("q")
    return {"filters": filters, "q": q.strip()[:Q_LIMIT] if isinstance(q, str) else "", "ignored": ignored}

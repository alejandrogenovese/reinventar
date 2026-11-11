"""Fichas navegables (charla, speaker, empresa) y buscador de personas/empresas."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import ask, briefing, db, explore, knowledge, nl_filters, talks
from .auth import auth

router = APIRouter(prefix="/api/k", dependencies=[Depends(auth)])


def _or_404(value, what: str):
    if value is None:
        raise HTTPException(404, f"{what} inexistente")
    return value


@router.get("/speech/{base}")
def speech(base: str):
    return _or_404(knowledge.speech_detail(base), "Charla")


@router.get("/speaker/{speaker_id}")
def speaker(speaker_id: int):
    return _or_404(knowledge.speaker_detail(speaker_id), "Speaker")


@router.get("/empresa/{empresa_id}")
def empresa(empresa_id: int):
    return _or_404(knowledge.empresa_detail(empresa_id), "Empresa")


class ExploreQuery(BaseModel):
    filters: dict[str, list[str]] = Field(default_factory=dict)
    q: Optional[str] = Field(None, max_length=200)
    group_by: Optional[str] = None
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)


@router.post("/explore")
def explore_catalog(body: ExploreQuery):
    unknown = (set(body.filters) | ({body.group_by} if body.group_by else set())) - set(explore.FACETS)
    if unknown:
        raise HTTPException(422, f"Faceta desconocida: {', '.join(sorted(unknown))}")
    filters = {facet: set(values[:50]) for facet, values in body.filters.items() if values}
    return explore.explore(filters, body.q or "", body.group_by, body.limit, body.offset)


@router.get("/talks/pick")
def pick_talk(q: str = Query(min_length=2, max_length=80)):
    """Para grabar: horarios por código o título, con el tipo de grabación sugerido."""
    return talks.pick(q)


class ParseQuery(BaseModel):
    text: str = Field(min_length=2, max_length=300)


@router.post("/explore/parse")
def parse_filters(body: ParseQuery):
    """Pedido en lenguaje natural → filtros validados contra los valores reales (se aplican después con /explore)."""
    try:
        return nl_filters.parse(body.text.strip())
    except nl_filters.NLFiltersUnavailable:
        raise HTTPException(502, "No pude interpretar el pedido ahora. Probá con los filtros de abajo.") from None


@router.get("/search/entities")
def search_entities(q: str = Query(min_length=2, max_length=80)):
    return knowledge.search_entities(q)


class AskQuery(BaseModel):
    q: str = Field(min_length=2, max_length=500)


@router.post("/ask")
def ask_catalog(body: AskQuery, username: str = Depends(auth)):
    try:
        return ask.answer(body.q.strip(), db.get_interview(username)["ficha_texto"])
    except ask.AskUnavailable:
        raise HTTPException(502, "No pude responder ahora. Probá de nuevo en un rato o usá Explorar.") from None


class BriefingQuery(BaseModel):
    kind: Literal["speaker", "empresa"]
    id: int = Field(ge=1)
    refresh: bool = False


@router.post("/briefing")
def make_briefing(body: BriefingQuery, username: str = Depends(auth)):
    """Ficha para conversar con un speaker o empresa, cruzada con el perfil de quien la pide (en caché por usuario)."""
    try:
        result = briefing.get(username, body.kind, body.id, body.refresh)
    except briefing.BriefingUnavailable:
        raise HTTPException(502, "No pude preparar la ficha ahora. Probá de nuevo en un rato.") from None
    return _or_404(result, "Speaker" if body.kind == "speaker" else "Empresa")

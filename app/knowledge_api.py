"""Fichas navegables (charla, speaker, empresa) y buscador de personas/empresas."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import explore, knowledge
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


@router.get("/search/entities")
def search_entities(q: str = Query(min_length=2, max_length=80)):
    return knowledge.search_entities(q)

"""Fichas navegables (charla, speaker, empresa) y buscador de personas/empresas."""
from fastapi import APIRouter, Depends, HTTPException, Query

from . import knowledge
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


@router.get("/search/entities")
def search_entities(q: str = Query(min_length=2, max_length=80)):
    return knowledge.search_entities(q)

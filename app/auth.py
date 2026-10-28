"""Autenticación por token de sesión: Depends(auth) resuelve el token a un username (o 401)."""
from typing import Optional

from fastapi import Header, HTTPException

from . import db


def auth(authorization: Optional[str] = Header(None)) -> str:
    token = (authorization or "").removeprefix("Bearer ").strip()
    username = token and db.resolve_auth_token(token)
    if not username:
        raise HTTPException(401, "Sesión inválida o vencida")
    return username

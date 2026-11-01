"""Autenticación por token de sesión: Depends(auth) resuelve el token a un username (o 401); Depends(admin) exige ADMIN_USERS."""
from typing import Optional

from fastapi import Depends, Header, HTTPException

from . import config, db


def bearer(authorization: Optional[str]) -> str:
    return (authorization or "").removeprefix("Bearer ").strip()


def auth(authorization: Optional[str] = Header(None)) -> str:
    token = bearer(authorization)
    username = token and db.resolve_auth_token(token)
    if not username:
        raise HTTPException(401, "Sesión inválida o vencida")
    return username


def is_admin(username: str) -> bool:
    return username in config.ADMIN_USERS


def admin(username: str = Depends(auth)) -> str:
    if not is_admin(username):
        raise HTTPException(403, "Solo para administradores")
    return username

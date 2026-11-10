"""Autenticación por token de sesión: Depends(auth) resuelve el token a un username (o 401); Depends(admin) exige ADMIN_USERS."""
from typing import Optional

from fastapi import Depends, Header, HTTPException

from . import config, db, sandbox


def bearer(authorization: Optional[str]) -> str:
    return (authorization or "").removeprefix("Bearer ").strip()


def auth(authorization: Optional[str] = Header(None)) -> str:
    token = bearer(authorization)
    username = token and db.resolve_auth_token(token)
    if not username:
        raise HTTPException(401, "Sesión inválida o vencida")
    return username


def sandbox_for_token(token: str):
    """El sandbox del dueño del token si está en modo prueba (None si no, o si el token no vale).
    Lo usa el middleware de app.main en cada pedido; se lee siempre del schema real."""
    if not token:
        return None
    with sandbox.real():
        username = db.resolve_auth_token(token)
        return sandbox.desde_usuario(db.get_user(username)) if username else None


def is_admin(username: str) -> bool:
    return username in config.ADMIN_USERS


def admin(username: str = Depends(auth)) -> str:
    if not is_admin(username):
        raise HTTPException(403, "Solo para administradores")
    return username

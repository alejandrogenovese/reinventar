"""Autenticación por token de sesión: Depends(auth) resuelve el token a un username (o 401); Depends(admin) exige ADMIN_USERS."""
import time
from typing import Optional

from fastapi import Depends, Header, HTTPException

from . import config, db, sandbox


def bearer(authorization: Optional[str]) -> str:
    return (authorization or "").removeprefix("Bearer ").strip()


# Detalle del 403 cuando la persona todavía tiene la contraseña temporal: la PWA lo reconoce y la manda a cambiarla.
DEBE_CAMBIAR_CONTRASENA = "must_change_password"
# Para registrar una passkey hace falta haber entrado con la contraseña hace poco (no alcanza con un token viejo).
LOGIN_RECIENTE_SEGUNDOS = 15 * 60


def _sesion(authorization: Optional[str]) -> dict:
    token = bearer(authorization)
    sesion = token and db.resolve_session(token)
    if not sesion:
        raise HTTPException(401, "Sesión inválida o vencida")
    return sesion


def auth_pendiente(authorization: Optional[str] = Header(None)) -> str:
    """Como auth, pero acepta a quien todavía tiene que cambiar la contraseña temporal. Solo para /api/me y
    /api/password: todo lo demás exige haberla cambiado."""
    return _sesion(authorization)["username"]


def auth(authorization: Optional[str] = Header(None)) -> str:
    sesion = _sesion(authorization)
    if sesion["must_change_password"]:
        raise HTTPException(403, DEBE_CAMBIAR_CONTRASENA)
    return sesion["username"]


def login_reciente(authorization: Optional[str] = Header(None)) -> str:
    """auth, y además que la sesión se haya abierto hace menos de LOGIN_RECIENTE_SEGUNDOS."""
    username = auth(authorization)
    if _sesion(authorization)["created_at"] < time.time() - LOGIN_RECIENTE_SEGUNDOS:
        raise HTTPException(403, "Para agregar Face ID / huella, cerrá sesión y volvé a entrar con tu contraseña.")
    return username


def context_for_token(token: str):
    """(usuario, sandbox) del dueño del token: el sandbox si está en modo prueba (None si no) y el usuario para las
    trazas del LLM. (None, None) si el token no vale. Lo usa el middleware de app.main en cada pedido; se lee siempre
    del schema real."""
    if not token:
        return None, None
    with sandbox.real():
        username = db.resolve_auth_token(token)
        return (username, sandbox.desde_usuario(db.get_user(username))) if username else (None, None)


def is_admin(username: str) -> bool:
    return username in config.ADMIN_USERS


def admin(username: str = Depends(auth)) -> str:
    if not is_admin(username):
        raise HTTPException(403, "Solo para administradores")
    return username

"""Autenticación por token de sesión: Depends(auth) resuelve el token a un username (o 401); Depends(admin) exige ADMIN_USERS."""
import time

from fastapi import Depends, Header, HTTPException, Request

from . import config, db, sandbox


def bearer(authorization: str | None) -> str:
    return (authorization or "").removeprefix("Bearer ").strip()


# Detalle del 403 cuando la persona todavía tiene la contraseña temporal: la PWA lo reconoce y la manda a cambiarla.
DEBE_CAMBIAR_CONTRASENA = "must_change_password"
# Para registrar una passkey hace falta haber entrado con la contraseña hace poco (no alcanza con un token viejo).
LOGIN_RECIENTE_SEGUNDOS = 15 * 60


# Clave, dentro de scope["state"], donde queda la sesión ya resuelta del pedido en curso.
_CLAVE_SESION = "sesion_resuelta"


def resolver_sesion(scope: dict, token: str) -> dict | None:
    """{username, must_change_password, created_at} del dueño del token, o None si no vale. Resuelve contra la base
    una sola vez por pedido: el resultado (también el "no vale") queda en scope["state"], y el middleware del sandbox,
    Depends(auth) y login_reciente lo reusan. Está atado al token, así que un token distinto no lo hereda."""
    estado = scope.setdefault("state", {})
    guardado = estado.get(_CLAVE_SESION)
    if guardado and guardado[0] == token:
        return guardado[1]
    sesion = (db.resolve_session(token) if token else None) or None
    estado[_CLAVE_SESION] = (token, sesion)
    return sesion


def _sesion(request: Request, authorization: str | None) -> dict:
    sesion = resolver_sesion(request.scope, bearer(authorization))
    if not sesion:
        raise HTTPException(401, "Sesión inválida o vencida")
    return sesion


def auth_pendiente(request: Request, authorization: str | None = Header(None)) -> str:
    """Como auth, pero acepta a quien todavía tiene que cambiar la contraseña temporal. Solo para /api/me y
    /api/password: todo lo demás exige haberla cambiado."""
    return _sesion(request, authorization)["username"]


def auth(request: Request, authorization: str | None = Header(None)) -> str:
    sesion = _sesion(request, authorization)
    if sesion["must_change_password"]:
        raise HTTPException(403, DEBE_CAMBIAR_CONTRASENA)
    return sesion["username"]


def login_reciente(request: Request, username: str = Depends(auth), authorization: str | None = Header(None)) -> str:
    """auth, y además que la sesión se haya abierto hace menos de LOGIN_RECIENTE_SEGUNDOS."""
    if _sesion(request, authorization)["created_at"] < time.time() - LOGIN_RECIENTE_SEGUNDOS:
        raise HTTPException(403, "Para agregar Face ID / huella, cerrá sesión y volvé a entrar con tu contraseña.")
    return username


def context_for_token(token: str, scope: dict | None = None):
    """(usuario, sandbox) del dueño del token: el sandbox si está en modo prueba (None si no) y el usuario para las
    trazas del LLM. (None, None) si el token no vale. Lo usa el middleware de app.main en cada pedido, que le pasa su
    scope para dejar ahí la sesión resuelta; se lee siempre del schema real."""
    if not token:
        return None, None
    with sandbox.real():
        sesion = resolver_sesion(scope if scope is not None else {}, token)
        username = sesion["username"] if sesion else None
        return (username, sandbox.desde_usuario(db.get_user(username))) if username else (None, None)


def is_admin(username: str) -> bool:
    return username in config.ADMIN_USERS


def admin(username: str = Depends(auth)) -> str:
    if not is_admin(username):
        raise HTTPException(403, "Solo para administradores")
    return username

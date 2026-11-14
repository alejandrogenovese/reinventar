"""Login/logout, perfil de sesión y cambio de contraseña."""
import functools
import ipaddress
import logging
import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import config, db, limites, passkeys_db, passwords, sandbox, venues
from .auth import auth_pendiente, bearer, is_admin

router = APIRouter()
log = logging.getLogger("reinventar.auth")


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=config.PASSWORD_MIN_LENGTH, max_length=200)


def _session_info(user: dict) -> dict:
    sb = sandbox.desde_usuario(user)
    return {
        "username": user["username"],
        "must_change_password": user["must_change_password"],
        "is_admin": is_admin(user["username"]),
        "sandbox": sandbox.info(sb, venues.by_id(sb.id_sede) if sb else None),
    }


def issue_session(user: dict) -> dict:
    """Emite un token de sesión para un usuario ya autenticado (contraseña o passkey)."""
    token = secrets.token_hex(32)
    db.create_auth_token(token, user["username"])
    return {"token": token, **_session_info(user)}


# Hash de relleno: si el usuario no existe se verifica igual contra esto, así la respuesta tarda lo mismo y no se
# puede saber por el tiempo qué usuarios existen.
_SALT_RELLENO, _HASH_RELLENO = passwords.hash_password(secrets.token_hex(16))


# Header donde el proxy de Railway deja la IP real del cliente (documentado en "Specs & Limits": X-Real-IP). Es
# configurable por si el proveedor cambia. El X-Forwarded-For no se usa: el cliente puede mandarlo con lo que quiera.
HEADER_IP_CLIENTE = os.environ.get("IP_CLIENTE_HEADER", "X-Real-IP").strip().lower()


@functools.cache
def _avisar_sin_header(header: str) -> None:
    """Una sola vez por proceso (functools.cache): sin este header, detrás del proxy todos comparten la IP del peer y los
    límites por IP (login, passkeys) pasan a ser un único balde global."""
    log.warning("Falta el header %s (o no es una IP): los límites por IP usan la IP del peer, que detrás del proxy es "
                "la misma para todos. Revisá IP_CLIENTE_HEADER y lo que manda el proxy.", header)


def ip_cliente(request: Request) -> str:
    """IP del cliente para los límites por IP: la del header del proxy si es una IP válida; si no, la del peer.
    El Dockerfile corre uvicorn con --no-proxy-headers, así que request.client es siempre el peer real y ningún
    X-Forwarded-For que mande el cliente lo cambia."""
    valor = request.headers.get(HEADER_IP_CLIENTE, "").strip()
    try:
        return str(ipaddress.ip_address(valor))
    except ValueError:
        _avisar_sin_header(HEADER_IP_CLIENTE)
        return request.client.host if request.client else "?"


@router.post("/api/login")
def login(body: Login, request: Request):
    username, ip = body.username.strip().lower(), ip_cliente(request)
    if limites.fallos_usuario.excedido(username) or limites.fallos_ip.excedido(ip):
        raise limites.demasiados_intentos()
    user = db.get_user(body.username.strip())
    salt, password_hash = (user["salt"], user["password_hash"]) if user else (_SALT_RELLENO, _HASH_RELLENO)
    valida = passwords.verify_password(body.password, salt, password_hash)
    if not user or not user["is_active"] or not valida:
        limites.fallos_usuario.sumar(username)
        limites.fallos_ip.sumar(ip)
        raise HTTPException(401, "Usuario o contraseña inválidos")
    limites.fallos_usuario.limpiar(username)
    return issue_session(user)


@router.post("/api/logout")
def logout(authorization: str | None = Header(None)):
    token = bearer(authorization)
    if token:
        db.delete_auth_token(token)
    return {"ok": True}


@router.get("/api/me")
def me(username: str = Depends(auth_pendiente)):
    return {"ok": True, **_session_info(db.get_user(username))}


@router.post("/api/password")
def change_password(body: PasswordChange, username: str = Depends(auth_pendiente),
                    authorization: str | None = Header(None)):
    user = db.get_user(username)
    if not passwords.verify_password(body.current_password, user["salt"], user["password_hash"]):
        raise HTTPException(400, "La contraseña actual no es correcta")
    if body.new_password == body.current_password:
        raise HTTPException(400, "La contraseña nueva tiene que ser distinta de la actual")
    salt, password_hash = passwords.hash_password(body.new_password)
    db.set_password(username, salt, password_hash, must_change_password=False)
    db.revoke_tokens(username, except_token=bearer(authorization))  # cierra la sesión en los otros celulares
    passkeys_db.delete_all(username)  # una passkey agregada por quien tenía la contraseña vieja no sobrevive
    return {"ok": True}

"""Login/logout, perfil de sesión y cambio de contraseña."""
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from . import config, db, passwords, sandbox, venues
from .auth import auth, bearer, is_admin

router = APIRouter()


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


@router.post("/api/login")
def login(body: Login):
    user = db.get_user(body.username.strip())
    if not user or not user["is_active"] or not passwords.verify_password(body.password, user["salt"], user["password_hash"]):
        raise HTTPException(401, "Usuario o contraseña inválidos")
    return issue_session(user)


@router.post("/api/logout")
def logout(authorization: Optional[str] = Header(None)):
    token = bearer(authorization)
    if token:
        db.delete_auth_token(token)
    return {"ok": True}


@router.get("/api/me")
def me(username: str = Depends(auth)):
    return {"ok": True, **_session_info(db.get_user(username))}


@router.post("/api/password")
def change_password(body: PasswordChange, username: str = Depends(auth), authorization: Optional[str] = Header(None)):
    user = db.get_user(username)
    if not passwords.verify_password(body.current_password, user["salt"], user["password_hash"]):
        raise HTTPException(400, "La contraseña actual no es correcta")
    if body.new_password == body.current_password:
        raise HTTPException(400, "La contraseña nueva tiene que ser distinta de la actual")
    salt, password_hash = passwords.hash_password(body.new_password)
    db.set_password(username, salt, password_hash, must_change_password=False)
    db.revoke_tokens(username, except_token=bearer(authorization))  # cierra la sesión en los otros celulares
    return {"ok": True}

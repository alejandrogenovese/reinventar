"""Módulo de admin (solo ADMIN_USERS): gestión de usuarios y uso de la app."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import config, db, passwords
from .auth import admin, is_admin

router = APIRouter(prefix="/api/admin")

_USERNAME = re.compile(r"^[a-z0-9_.-]{2,40}$")


class NewUser(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=config.PASSWORD_MIN_LENGTH, max_length=200)


class ResetPassword(BaseModel):
    password: str = Field(min_length=config.PASSWORD_MIN_LENGTH, max_length=200)


class SetActive(BaseModel):
    active: bool


def _user_or_404(username: str) -> dict:
    user = db.get_user(username)
    if not user:
        raise HTTPException(404, "Usuario inexistente")
    return user


@router.get("/users")
def list_users(_admin: str = Depends(admin)):
    return {"users": [{**u, "is_admin": is_admin(u["username"])} for u in db.list_users()]}


@router.post("/users")
def create_user(body: NewUser, _admin: str = Depends(admin)):
    username = body.username.strip().lower()
    if not _USERNAME.match(username):
        raise HTTPException(422, "Usuario: 2 a 40 caracteres, solo minúsculas, números, punto, guion o guion bajo")
    if db.get_user(username):
        raise HTTPException(409, "Ese usuario ya existe")
    salt, password_hash = passwords.hash_password(body.password)
    db.create_user(username, salt, password_hash, must_change_password=True)
    return {"ok": True, "username": username}


@router.post("/users/{username}/reset-password")
def reset_password(username: str, body: ResetPassword, _admin: str = Depends(admin)):
    _user_or_404(username)
    salt, password_hash = passwords.hash_password(body.password)
    db.set_password(username, salt, password_hash, must_change_password=True)
    db.revoke_tokens(username)
    return {"ok": True}


@router.post("/users/{username}/active")
def set_active(username: str, body: SetActive, current: str = Depends(admin)):
    _user_or_404(username)
    if username == current and not body.active:
        raise HTTPException(400, "No podés desactivar tu propio usuario")
    db.set_user_active(username, body.active)
    if not body.active:
        db.revoke_tokens(username)
    return {"ok": True}


@router.delete("/users/{username}/sessions")
def revoke_sessions(username: str, _admin: str = Depends(admin)):
    _user_or_404(username)
    db.revoke_tokens(username)
    return {"ok": True}


@router.get("/usage")
def usage(_admin: str = Depends(admin)):
    return {
        "recordings_by_status": db.recordings_by_status(),
        "recent_errors": db.recent_errors(),
        "users": db.list_users(),
    }

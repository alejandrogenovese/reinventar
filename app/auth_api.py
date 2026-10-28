"""Login/logout: valida usuario+contraseña y emite/revoca tokens de sesión."""
import secrets
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import db, passwords

router = APIRouter()


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


@router.post("/api/login")
def login(body: Login):
    user = db.get_user(body.username.strip())
    if not user or not passwords.verify_password(body.password, user["salt"], user["password_hash"]):
        raise HTTPException(401, "Usuario o contraseña inválidos")
    token = secrets.token_hex(32)
    db.create_auth_token(token, user["username"])
    return {"token": token, "username": user["username"]}


@router.post("/api/logout")
def logout(authorization: Optional[str] = Header(None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token:
        db.delete_auth_token(token)
    return {"ok": True}

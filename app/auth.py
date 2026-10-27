"""Autenticación por token compartido: Depends(auth) protege todas las rutas de datos."""
import hmac
from typing import Optional

from fastapi import Header, HTTPException

from . import config


def auth(authorization: Optional[str] = Header(None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not config.APP_TOKEN or not hmac.compare_digest(token, config.APP_TOKEN):
        raise HTTPException(401, "Token inválido")

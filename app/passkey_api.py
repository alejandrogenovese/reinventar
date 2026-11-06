"""Passkeys (WebAuthn): Face ID / Touch ID en iPhone, huella o desbloqueo facial en Android.

El celular guarda la clave privada y solo firma un challenge; el servidor guarda la clave pública.
Login sin usuario (credencial descubrible): el navegador ofrece las passkeys de este dominio.
"""
import json
import logging
from typing import Optional

import webauthn
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from . import config, db
from . import passkeys_db as store
from .auth import auth
from .auth_api import issue_session

log = logging.getLogger("reinventar.passkey")
router = APIRouter()

RP_NAME = "ReinventAR"


class RegisterVerify(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    credential: dict
    device: Optional[str] = Field(None, max_length=80)


class LoginVerify(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    credential: dict


def _rp(request: Request) -> tuple[str, str]:
    """(rp_id, origin): el dominio al que quedan atadas las passkeys y el origen esperado en la firma."""
    rp_id = config.WEBAUTHN_RP_ID or request.url.hostname
    origin = config.WEBAUTHN_ORIGIN or f"{request.url.scheme}://{request.url.netloc}"
    return rp_id, origin


def _options(options) -> dict:
    return json.loads(webauthn.options_to_json(options))


@router.post("/api/passkey/register/options")
def register_options(request: Request, username: str = Depends(auth)):
    rp_id, _ = _rp(request)
    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_name=username,
        user_id=username.encode(),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(p["id"])) for p in store.list_passkeys(username)
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    challenge_id = store.save_challenge("register", options.challenge, username)
    return {"challenge_id": challenge_id, "options": _options(options)}


@router.post("/api/passkey/register/verify")
def register_verify(body: RegisterVerify, request: Request, username: str = Depends(auth)):
    challenge = store.pop_challenge(body.challenge_id, "register", username)
    if challenge is None:
        raise HTTPException(400, "El pedido venció; probá de nuevo")
    rp_id, origin = _rp(request)
    try:
        verified = webauthn.verify_registration_response(
            credential=body.credential, expected_challenge=challenge, expected_rp_id=rp_id,
            expected_origin=origin, require_user_verification=True,
        )
    except WebAuthnException as e:
        log.warning("Registro de passkey rechazado para %s: %s", username, type(e).__name__)  # el mensaje trae datos del navegador
        raise HTTPException(400, "No se pudo verificar el Face ID / huella") from e
    store.add_passkey(
        bytes_to_base64url(verified.credential_id), username, verified.credential_public_key,
        verified.sign_count, body.device,
    )
    return {"ok": True}


@router.post("/api/passkey/login/options")
def login_options(request: Request):
    rp_id, _ = _rp(request)
    options = webauthn.generate_authentication_options(
        rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED
    )
    return {"challenge_id": store.save_challenge("login", options.challenge), "options": _options(options)}


@router.post("/api/passkey/login/verify")
def login_verify(body: LoginVerify, request: Request):
    challenge = store.pop_challenge(body.challenge_id, "login")
    if challenge is None:
        raise HTTPException(400, "El pedido venció; probá de nuevo")
    passkey = store.get_passkey(str(body.credential.get("id", "")))
    user = passkey and db.get_user(passkey["username"])
    if not user or not user["is_active"]:
        raise HTTPException(401, "Esta passkey no está registrada en ReinventAR")
    rp_id, origin = _rp(request)
    try:
        verified = webauthn.verify_authentication_response(
            credential=body.credential, expected_challenge=challenge, expected_rp_id=rp_id, expected_origin=origin,
            credential_public_key=bytes(passkey["public_key"]), credential_current_sign_count=passkey["sign_count"],
            require_user_verification=True,
        )
    except WebAuthnException as e:
        log.warning("Login con passkey rechazado para %s: %s", passkey["username"], type(e).__name__)
        raise HTTPException(401, "No se pudo verificar el Face ID / huella") from e
    store.touch_passkey(passkey["id"], verified.new_sign_count)
    return issue_session(user)


@router.get("/api/passkeys")
def my_passkeys(username: str = Depends(auth)):
    return {"passkeys": store.list_passkeys(username)}


@router.delete("/api/passkeys/{credential_id}")
def delete_passkey(credential_id: str, username: str = Depends(auth)):
    if not store.delete_passkey(username, credential_id):
        raise HTTPException(404, "Passkey inexistente")
    return {"ok": True}

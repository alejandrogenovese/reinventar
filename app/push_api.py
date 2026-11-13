"""API de Web Push: clave pública, alta y baja de la suscripción del dispositivo, y notificación de prueba."""
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from . import config, db, push
from .auth import auth

router = APIRouter(prefix="/api/push")


class Keys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=10, max_length=100)


# Servicios de push de los navegadores. El servidor le hace POST al endpoint de cada suscripción: si se aceptara
# cualquier URL, un usuario podría hacer que el servidor le pegue a servicios internos (SSRF).
PUSH_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com")
PUSH_SUFIJOS = (".push.apple.com", ".notify.windows.com", ".push.services.mozilla.com")


def es_servicio_push(endpoint: str) -> bool:
    partes = urlsplit(endpoint)
    host = (partes.hostname or "").lower()
    return (partes.scheme == "https" and partes.port in (None, 443)
            and (host in PUSH_HOSTS or host.endswith(PUSH_SUFIJOS)))


class Subscription(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000, pattern=r"^https://")
    keys: Keys

    @field_validator("endpoint")
    @classmethod
    def _servicio_conocido(cls, v: str) -> str:
        if not es_servicio_push(v):
            raise ValueError("El endpoint no es de un servicio de notificaciones conocido")
        return v


class Unsubscribe(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)


@router.get("/key")
def public_key(_username: str = Depends(auth)):
    return {"key": config.VAPID_PUBLIC_KEY or None}


@router.post("/subscribe")
def subscribe(body: Subscription, username: str = Depends(auth)):
    if not push.enabled():
        raise HTTPException(503, "Las notificaciones no están configuradas en el servidor")
    db.save_push_subscription(username, body.endpoint, body.keys.p256dh, body.keys.auth)
    return {"ok": True}


@router.post("/unsubscribe")
def unsubscribe(body: Unsubscribe, username: str = Depends(auth)):
    db.delete_push_subscription(body.endpoint, username)
    return {"ok": True}


@router.post("/test")
def test_notification(username: str = Depends(auth)):
    if not push.enabled():
        raise HTTPException(503, "Las notificaciones no están configuradas en el servidor")
    delivered = push.notify(username, {"title": "ReinventAR", "body": "Así te van a llegar los avisos de lo que fijaste.",
                                       "url": "/#/"})
    if not delivered:
        raise HTTPException(404, "No hay ningún dispositivo con las notificaciones activas")
    return {"ok": True, "devices": delivered}

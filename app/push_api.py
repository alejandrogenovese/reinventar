"""API de Web Push: clave pública, alta y baja de la suscripción del dispositivo, y notificación de prueba."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import config, db, push
from .auth import auth

router = APIRouter(prefix="/api/push")


class Keys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=10, max_length=100)


class Subscription(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000, pattern=r"^https://")
    keys: Keys


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

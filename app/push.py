"""Notificaciones en el celular con la app cerrada (Web Push), sin dependencias nuevas: solo `cryptography`.

- Cifrado del mensaje: RFC 8291 (aes128gcm, RFC 8188). Firma del servidor: VAPID (RFC 8292, JWT ES256).
- Claves: VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY (base64url, generar con `python -m app.push`) y VAPID_SUBJECT.
- Cada minuto, para quienes activaron las notificaciones: "Salí para…" (20 min antes de lo fijado: el servidor no conoce
  la ubicación), "Empieza en 5 min" y los cambios del itinerario (app/changes.py). Cada aviso sale una sola vez.
  En modo prueba usa el reloj simulado del usuario.
En iPhone funciona solo con la app instalada en la pantalla de inicio (iOS 16.4 o posterior).
"""
import base64
import datetime as dt
import hashlib
import json
import logging
import os
import struct
import threading
import time
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import changes, config, db, itinerary, sandbox

log = logging.getLogger("reinventar.push")
TICK_SECONDS = 60
LEAVE_LEAD_MIN = 20
START_NOTICE_MIN = 5
RECORD_SIZE = 4096
TTL_SECONDS = 3600


# ---------- base64url y claves ----------

def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _raw_public(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def generate_vapid_keys() -> tuple[str, str]:
    """(pública, privada) en base64url: la pública va al navegador (applicationServerKey)."""
    private = ec.generate_private_key(ec.SECP256R1())
    return b64u(_raw_public(private.public_key())), b64u(private.private_numbers().private_value.to_bytes(32, "big"))


def _vapid_private() -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(unb64u(config.VAPID_PRIVATE_KEY), "big"), ec.SECP256R1())


def enabled() -> bool:
    return bool(config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY)


# ---------- RFC 8291 + VAPID ----------

def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
            server_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """Cuerpo cifrado para el push service (Content-Encoding: aes128gcm). salt y server_key solo para tests."""
    ua_public = unb64u(p256dh)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(server_key.public_key())
    ecdh = server_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    ikm = _hkdf(unb64u(auth), ecdh, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # \x02 = último (y único) registro
    return salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public + ciphertext


def vapid_authorization(endpoint: str, now: float | None = None) -> str:
    parts = urlsplit(endpoint)
    header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64u(json.dumps({"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now or time.time()) + 12 * 3600),
                              "sub": config.VAPID_SUBJECT}, separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode()
    r, s = decode_dss_signature(_vapid_private().sign(signing_input, ec.ECDSA(hashes.SHA256())))
    jwt = f"{header}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={jwt}, k={config.VAPID_PUBLIC_KEY}"


def send(sub: dict, message: dict, http: httpx.Client | None = None) -> int:
    """Manda un aviso a una suscripción. Devuelve el status; 404/410 = suscripción vencida (se borra)."""
    body = encrypt(json.dumps(message, ensure_ascii=False).encode(), sub["p256dh"], sub["auth"])
    headers = {"Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": str(TTL_SECONDS),
               "Urgency": "high", "Authorization": vapid_authorization(sub["endpoint"])}
    r = (http or httpx).post(sub["endpoint"], content=body, headers=headers, timeout=15)
    if r.status_code in (404, 410):
        db.delete_push_subscription(sub["endpoint"])
    elif r.status_code >= 400:
        log.warning("push %s respondió %s: %s", urlsplit(sub["endpoint"]).netloc, r.status_code, r.text[:200])
    return r.status_code


def notify(username: str, message: dict) -> int:
    """Manda el aviso a todos los dispositivos del usuario; devuelve a cuántos llegó."""
    return sum(send(sub, message) < 300 for sub in db.push_subscriptions(username))


# ---------- qué avisar ----------

def _start(card: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{card['day']}T{card['start']}").replace(tzinfo=sandbox.EVENT_TZ)


def _notice(c: dict, now: dt.datetime) -> tuple[str, dict] | None:
    """Aviso de "salí" o "empieza" para algo fijado del itinerario, si corresponde ahora."""
    if not (c.get("locked") and c.get("start")):
        return None
    minutes = (_start(c) - now).total_seconds() / 60
    venue = c.get("venue") or {}
    where = " · ".join(filter(None, (venue.get("hotel"), venue.get("detail"))))
    url = f"/#/evento/{c['code']}" if c.get("kind") == "event" else f"/#/charla/{c['base']}"
    if START_NOTICE_MIN < minutes <= LEAVE_LEAD_MIN:
        return (f"leave:{c['code']}:{c['day']}",
                {"title": f"Salí para {c['title']}", "body": f"Empieza a las {c['start']} · {where}", "url": url})
    if 0 < minutes <= START_NOTICE_MIN:
        return (f"start:{c['code']}:{c['day']}",
                {"title": f"{c['title']} empieza en {round(minutes)} min", "body": where, "url": url})
    return None


def due(username: str, now: dt.datetime) -> list[tuple[str, dict]]:
    """[(clave única, mensaje)] de lo que corresponde avisar ahora a este usuario."""
    cards = (c for day in itinerary.get_current(username)["days"] for c in day["sessions"])
    out = [n for c in cards if (n := _notice(c, now))]
    for ch in changes.pending(username):
        key = "change:" + hashlib.sha256(json.dumps([ch["code"], ch["messages"]]).encode()).hexdigest()[:16]
        out.append((key, {"title": "Cambió algo de tu itinerario", "body": " ".join(ch["messages"]), "url": "/#/itinerario"}))
    return out


def tick() -> int:
    """Una vuelta: avisa lo que corresponde a cada usuario suscripto. Devuelve cuántos avisos salieron."""
    sent = 0
    with sandbox.real():
        users = db.push_usernames()
    for username in users:
        with sandbox.real():
            sb = sandbox.desde_usuario(db.get_user(username))
        with sandbox.activar(sb):  # en modo prueba: su reloj simulado y su schema de prueba
            for key, message in due(username, sandbox.ahora()):
                if not db.mark_push_sent(username, key):
                    continue  # ya avisado
                if notify(username, message):
                    sent += 1
                else:
                    db.unmark_push_sent(username, key)  # no llegó a ningún dispositivo: se reintenta la próxima vuelta
    return sent


def _loop():
    while True:
        try:
            tick()
        except Exception:  # noqa: BLE001 — un error de una vuelta no corta las siguientes
            log.exception("vuelta de avisos falló")
        time.sleep(TICK_SECONDS)


def start_worker() -> None:
    if enabled():
        threading.Thread(target=_loop, name="push", daemon=True).start()
    else:
        log.info("Web Push deshabilitado: faltan VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY")


if __name__ == "__main__":
    pub, priv = generate_vapid_keys()
    print(f"VAPID_PUBLIC_KEY={pub}\nVAPID_PRIVATE_KEY={priv}\nVAPID_SUBJECT=mailto:<tu mail>")

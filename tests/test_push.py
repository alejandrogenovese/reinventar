"""Web Push: cifrado RFC 8291 (ida y vuelta con el lado del navegador), firma VAPID, qué avisar y que salga una sola vez."""
import base64
import datetime as dt
import json
import os
import struct

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient

from app import config, events, push, sandbox
from app.main import app
from tests.conftest import TEST_USER, login_headers


def _navegador():
    """Claves de un navegador suscripto: (privada, p256dh, auth)."""
    private = ec.generate_private_key(ec.SECP256R1())
    return private, push.b64u(push._raw_public(private.public_key())), push.b64u(os.urandom(16))


def _descifrar(body: bytes, ua_private, auth: str) -> bytes:
    """Lo que hace el navegador al recibir el push (RFC 8291 §3.4 + RFC 8188)."""
    salt, rs, idlen = body[:16], *struct.unpack("!IB", body[16:21])
    as_public, ciphertext = body[21:21 + idlen], body[21 + idlen:]
    assert rs == 4096
    ua_public = push._raw_public(ua_private.public_key())
    ecdh = ua_private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    ikm = push._hkdf(push.unb64u(auth), ecdh, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = push._hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = push._hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    return AESGCM(cek).decrypt(nonce, ciphertext, None)


def test_el_navegador_descifra_el_mensaje():
    ua_private, p256dh, auth = _navegador()

    plano = _descifrar(push.encrypt(b'{"title":"Hola"}', p256dh, auth), ua_private, auth)

    assert plano == b'{"title":"Hola"}\x02'


def test_la_firma_vapid_se_verifica_con_la_clave_publica(monkeypatch):
    pub, priv = push.generate_vapid_keys()
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", pub)
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", priv)

    header = push.vapid_authorization("https://fcm.googleapis.com/fcm/send/abc", now=1_000_000)

    t, k = header.removeprefix("vapid t=").split(", k=")
    head, claims, sig = t.split(".")
    raw = push.unb64u(sig)
    clave = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.unb64u(k))
    clave.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                 f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # tira si la firma no vale
    assert json.loads(base64.urlsafe_b64decode(claims + "==")) == {
        "aud": "https://fcm.googleapis.com", "exp": 1_000_000 + 12 * 3600, "sub": config.VAPID_SUBJECT}


# ---------- qué avisar y cuándo ----------

def _evento(start):
    return {"kind": "event", "code": "evt-push", "base": "evt-push", "title": "Happy Hour", "day": "2026-12-01",
            "start": start, "end": "21:00", "venue": {"hotel": "Topgolf", "detail": "", "lat": 36.1, "lng": -115.16}}


@pytest.fixture
def cli(monkeypatch):
    pub, priv = push.generate_vapid_keys()
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", pub)
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", priv)
    with TestClient(app) as c:
        monkeypatch.setattr(events, "_events", {"evt-push": _evento("18:00")})
        c.H = login_headers(c)
        c.post("/api/itinerary/items", headers=c.H, json={"code": "evt-push"})
        yield c
        c.delete("/api/itinerary/items/evt-push", headers=c.H)
        c.post("/api/push/unsubscribe", headers=c.H, json={"endpoint": "https://fcm.googleapis.com/fcm/send/1"})


def _ahora(hhmm):
    return dt.datetime.fromisoformat(f"2026-12-01T{hhmm}").replace(tzinfo=sandbox.EVENT_TZ)


def test_avisa_salir_20_min_antes_y_empezar_5_min_antes(cli):
    assert [k for k, _ in push.due(TEST_USER, _ahora("17:30"))] == []
    assert push.due(TEST_USER, _ahora("17:45"))[0][1]["title"] == "Salí para Happy Hour"
    assert push.due(TEST_USER, _ahora("17:57"))[0][1]["title"] == "Happy Hour empieza en 3 min"


def test_cada_aviso_sale_una_sola_vez(cli, monkeypatch):
    enviados = []
    monkeypatch.setattr(push, "send", lambda sub, msg, http=None, ttl=push.TTL_SECONDS: enviados.append(msg) or 201)
    monkeypatch.setattr(push.sandbox, "ahora", lambda tz=None: _ahora("17:45"))
    sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/1", "keys": {"p256dh": "x" * 87, "auth": "y" * 22}}
    assert cli.post("/api/push/subscribe", headers=cli.H, json=sub).status_code == 200

    push.tick()
    push.tick()

    assert [m["title"] for m in enviados] == ["Salí para Happy Hour"]


def test_la_suscripcion_exige_https(cli):
    sub = {"endpoint": "http://push.example/1", "keys": {"p256dh": "x" * 87, "auth": "y" * 22}}

    assert cli.post("/api/push/subscribe", headers=cli.H, json=sub).status_code == 422

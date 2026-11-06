"""Passkeys (Face ID / huella): registro y login. La verificación criptográfica de webauthn se reemplaza por un doble."""
import uuid
from types import SimpleNamespace

import pytest
import webauthn
from fastapi.testclient import TestClient

from app import db, passwords
from app.main import app
from tests.conftest import login_headers


def _new_user(must_change=False):
    username = f"p_{uuid.uuid4().hex[:8]}"
    salt, h = passwords.hash_password("inicial123")
    db.create_user(username, salt, h, must_change_password=must_change)
    return username


@pytest.fixture
def fake_webauthn(monkeypatch):
    """Acepta cualquier credencial y devuelve datos fijos; guarda con qué argumentos se llamó."""
    calls = {}

    def fake_register(**kw):
        calls["register"] = kw
        return SimpleNamespace(credential_id=calls["cred_id"], credential_public_key=b"pk", sign_count=0)

    def fake_auth(**kw):
        calls["auth"] = kw
        return SimpleNamespace(new_sign_count=kw["credential_current_sign_count"] + 1)

    monkeypatch.setattr(webauthn, "verify_registration_response", fake_register)
    monkeypatch.setattr(webauthn, "verify_authentication_response", fake_auth)
    return calls


def _credential(cred_id: bytes) -> dict:
    return {"id": webauthn.helpers.bytes_to_base64url(cred_id), "type": "public-key", "response": {}}


def _register(c, headers, fake, cred_id: bytes, device="iPhone de prueba"):
    fake["cred_id"] = cred_id
    opts = c.post("/api/passkey/register/options", headers=headers).json()
    return opts, c.post("/api/passkey/register/verify", headers=headers,
                        json={"challenge_id": opts["challenge_id"], "credential": _credential(cred_id), "device": device})


def _login(c, cred_id: bytes):
    opts = c.post("/api/passkey/login/options").json()
    return c.post("/api/passkey/login/verify", json={"challenge_id": opts["challenge_id"], "credential": _credential(cred_id)})


def test_registro_requiere_sesion():
    with TestClient(app) as c:
        assert c.post("/api/passkey/register/options").status_code == 401


def test_registrar_y_entrar_con_passkey(fake_webauthn):
    with TestClient(app) as c:
        username = _new_user()
        H = login_headers(c, username, "inicial123")
        cred_id = uuid.uuid4().bytes

        opts, reg = _register(c, H, fake_webauthn, cred_id)
        login = _login(c, cred_id)

        assert opts["options"]["user"]["name"] == username
        assert reg.status_code == 200, reg.text
        assert login.status_code == 200, login.text
        body = login.json()
        assert body["username"] == username and body["token"]
        assert c.get("/api/me", headers={"Authorization": f"Bearer {body['token']}"}).status_code == 200
        assert fake_webauthn["auth"]["credential_public_key"] == b"pk"


def test_login_actualiza_el_contador_de_firmas(fake_webauthn):
    with TestClient(app) as c:
        username = _new_user()
        H = login_headers(c, username, "inicial123")
        cred_id = uuid.uuid4().bytes
        _register(c, H, fake_webauthn, cred_id)

        _login(c, cred_id)
        _login(c, cred_id)

        assert fake_webauthn["auth"]["credential_current_sign_count"] == 1


def test_challenge_se_usa_una_sola_vez(fake_webauthn):
    with TestClient(app) as c:
        username = _new_user()
        H = login_headers(c, username, "inicial123")
        cred_id = uuid.uuid4().bytes
        _register(c, H, fake_webauthn, cred_id)
        opts = c.post("/api/passkey/login/options").json()
        body = {"challenge_id": opts["challenge_id"], "credential": _credential(cred_id)}

        first = c.post("/api/passkey/login/verify", json=body)
        again = c.post("/api/passkey/login/verify", json=body)

        assert (first.status_code, again.status_code) == (200, 400)


def test_credencial_desconocida_o_usuario_desactivado_no_entra(fake_webauthn):
    with TestClient(app) as c:
        username = _new_user()
        H = login_headers(c, username, "inicial123")
        cred_id = uuid.uuid4().bytes
        _register(c, H, fake_webauthn, cred_id)

        desconocida = _login(c, uuid.uuid4().bytes)
        db.set_user_active(username, False)
        desactivado = _login(c, cred_id)

        assert (desconocida.status_code, desactivado.status_code) == (401, 401)


def test_listar_y_borrar_mis_passkeys(fake_webauthn):
    with TestClient(app) as c:
        username = _new_user()
        H = login_headers(c, username, "inicial123")
        cred_id = uuid.uuid4().bytes
        _register(c, H, fake_webauthn, cred_id, device="Pixel")

        mine = c.get("/api/passkeys", headers=H).json()["passkeys"]
        otro = login_headers(c, _new_user(), "inicial123")
        ajeno = c.delete(f"/api/passkeys/{mine[0]['id']}", headers=otro)
        borrado = c.delete(f"/api/passkeys/{mine[0]['id']}", headers=H)

        assert [p["device"] for p in mine] == ["Pixel"]
        assert (ajeno.status_code, borrado.status_code) == (404, 200)
        assert c.get("/api/passkeys", headers=H).json()["passkeys"] == []
        assert _login(c, cred_id).status_code == 401


# --- de punta a punta con firma real (sin dobles) ---------------------------------------------

class SoftAuthenticator:
    """Autenticador de plataforma mínimo: ES256, attestation 'none', con user presence + user verification (Face ID)."""

    def __init__(self):
        from cryptography.hazmat.primitives.asymmetric import ec

        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = uuid.uuid4().bytes
        self.counter = 0

    @staticmethod
    def _client_data(kind, challenge, origin):
        import json

        return json.dumps({"type": kind, "challenge": challenge, "origin": origin}).encode()

    def create(self, options, origin):
        import hashlib

        import cbor2

        nums = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})
        auth_data = (hashlib.sha256(options["rp"]["id"].encode()).digest() + bytes([0x45]) + (0).to_bytes(4, "big")
                     + bytes(16) + len(self.cred_id).to_bytes(2, "big") + self.cred_id + cose)
        b64 = webauthn.helpers.bytes_to_base64url
        return {"id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key", "response": {
            "clientDataJSON": b64(self._client_data("webauthn.create", options["challenge"], origin)),
            "attestationObject": b64(cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data}))}}

    def get(self, options, origin):
        import hashlib

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec

        self.counter += 1
        auth_data = hashlib.sha256(options["rpId"].encode()).digest() + bytes([0x05]) + self.counter.to_bytes(4, "big")
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        b64 = webauthn.helpers.bytes_to_base64url
        return {"id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key", "response": {
            "authenticatorData": b64(auth_data), "clientDataJSON": b64(client_data), "signature": b64(signature)}}


def test_punta_a_punta_con_firma_real():
    origin = "http://testserver"
    device = SoftAuthenticator()
    with TestClient(app) as c:
        username = _new_user()
        H = login_headers(c, username, "inicial123")

        reg = c.post("/api/passkey/register/options", headers=H).json()
        registered = c.post("/api/passkey/register/verify", headers=H, json={
            "challenge_id": reg["challenge_id"], "credential": device.create(reg["options"], origin), "device": "soft"})
        logins = []
        for _ in range(2):
            opts = c.post("/api/passkey/login/options").json()
            logins.append(c.post("/api/passkey/login/verify", json={
                "challenge_id": opts["challenge_id"], "credential": device.get(opts["options"], origin)}))
        impostor = SoftAuthenticator()
        impostor.cred_id = device.cred_id  # misma credencial, otra clave privada
        impostor.counter = 100  # contador válido: solo falla la firma
        opts = c.post("/api/passkey/login/options").json()
        forged = c.post("/api/passkey/login/verify", json={
            "challenge_id": opts["challenge_id"], "credential": impostor.get(opts["options"], origin)})

        assert registered.status_code == 200, registered.text
        assert [r.status_code for r in logins] == [200, 200], [r.text for r in logins]
        assert logins[0].json()["username"] == username
        assert forged.status_code == 401


def test_rechazo_de_passkey_loguea_en_una_sola_linea(monkeypatch, caplog):
    def rejects(**kw):
        raise webauthn.helpers.exceptions.InvalidRegistrationResponse("origen inesperado\nINFO falso: login ok")

    monkeypatch.setattr(webauthn, "verify_registration_response", rejects)
    with TestClient(app) as c:
        headers = login_headers(c)
        opts = c.post("/api/passkey/register/options", headers=headers).json()
        r = c.post("/api/passkey/register/verify", headers=headers,
                   json={"challenge_id": opts["challenge_id"], "credential": _credential(b"x"), "device": "d"})

    assert r.status_code == 400
    rejected = [rec.getMessage() for rec in caplog.records if "rechazado" in rec.getMessage()]
    assert rejected and all("\n" not in m for m in rejected)  # datos del navegador sin saltos de línea: no se falsean entradas

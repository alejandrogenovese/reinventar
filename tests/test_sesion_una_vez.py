"""El token se resuelve una sola vez por pedido: el middleware del sandbox, Depends(auth) y login_reciente comparten la
sesión resuelta en vez de ir cada uno a la base."""
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import db, passwords
from app.main import app


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as cliente:
        yield cliente


@pytest.fixture
def resoluciones(monkeypatch):
    """Lista con el token de cada llamada a db.resolve_session."""
    llamadas = []
    original = db.resolve_session

    def contada(token, ahora=None):
        llamadas.append(token)
        return original(token, ahora)

    monkeypatch.setattr(db, "resolve_session", contada)
    return llamadas


def _login(c, must_change=False):
    username = f"u_{uuid.uuid4().hex[:8]}"
    salt, h = passwords.hash_password("clave12345")
    db.create_user(username, salt, h, must_change_password=must_change)
    r = c.post("/api/login", json={"username": username, "password": "clave12345"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    return username, token, {"Authorization": f"Bearer {token}"}


def test_un_endpoint_con_auth_resuelve_el_token_una_vez(c, resoluciones):
    _, token, headers = _login(c)
    resoluciones.clear()

    assert c.get("/api/sessions", headers=headers).status_code == 200

    assert resoluciones == [token]


def test_login_reciente_resuelve_el_token_una_vez(c, resoluciones):
    _, token, headers = _login(c)
    resoluciones.clear()

    assert c.post("/api/passkey/register/options", headers=headers).status_code == 200

    assert resoluciones == [token]


def test_un_endpoint_de_admin_resuelve_el_token_una_vez(c, resoluciones):
    from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

    headers = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    resoluciones.clear()

    assert c.get("/api/admin/check", headers=headers).status_code == 200

    assert len(resoluciones) == 1


def test_token_invalido_se_resuelve_una_vez_y_da_401(c, resoluciones):
    r = c.get("/api/sessions", headers={"Authorization": "Bearer token-que-no-existe"})

    assert r.status_code == 401
    assert resoluciones == ["token-que-no-existe"]


def test_un_pedido_nuevo_vuelve_a_resolver_el_token(c, resoluciones):
    _, token, headers = _login(c)
    resoluciones.clear()

    c.get("/api/sessions", headers=headers)
    c.get("/api/sessions", headers=headers)

    assert resoluciones == [token, token]


def test_login_reciente_sigue_exigiendo_un_login_de_hace_menos_de_15_minutos(c, resoluciones):
    _, token, headers = _login(c)
    with db.conn() as cx:
        cx.execute("UPDATE auth_tokens SET created_at=%s WHERE token=%s", (time.time() - 3600, db.hash_token(token)))
    resoluciones.clear()

    r = c.post("/api/passkey/register/options", headers=headers)

    assert r.status_code == 403
    assert resoluciones == [token]


def test_con_contrasena_temporal_se_sigue_rechazando_en_auth_y_aceptando_en_me(c, resoluciones):
    _, token, headers = _login(c, must_change=True)
    resoluciones.clear()

    assert c.get("/api/sessions", headers=headers).status_code == 403
    assert c.get("/api/me", headers=headers).status_code == 200

    assert resoluciones == [token, token]

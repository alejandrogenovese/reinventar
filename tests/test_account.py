"""Cambio de contraseña obligatorio en el primer ingreso y módulo de admin."""
import uuid

from fastapi.testclient import TestClient

from app import db, passwords
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers


def _new_user(password="inicial123", must_change=True):
    username = f"u_{uuid.uuid4().hex[:8]}"
    salt, h = passwords.hash_password(password)
    db.create_user(username, salt, h, must_change_password=must_change)
    return username, password


def _admin(c):
    return login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)


def test_login_informa_que_hay_que_cambiar_la_contraseña():
    with TestClient(app) as c:
        username, password = _new_user()

        r = c.post("/api/login", json={"username": username, "password": password}).json()

        assert r["must_change_password"] is True
        assert r["is_admin"] is False


def test_cambiar_contraseña_apaga_el_flag_y_revoca_otras_sesiones():
    with TestClient(app) as c:
        username, password = _new_user()
        otra = login_headers(c, username, password)
        actual = login_headers(c, username, password)

        r = c.post("/api/password", headers=actual, json={"current_password": password, "new_password": "nuevaclave99"})

        assert r.status_code == 200, r.text
        assert c.get("/api/me", headers=actual).json()["must_change_password"] is False
        assert c.get("/api/me", headers=otra).status_code == 401
        assert c.post("/api/login", json={"username": username, "password": "nuevaclave99"}).status_code == 200


def test_cambiar_contraseña_rechaza_actual_incorrecta_o_nueva_corta():
    with TestClient(app) as c:
        username, password = _new_user()
        H = login_headers(c, username, password)

        mal_actual = c.post("/api/password", headers=H, json={"current_password": "nope", "new_password": "nuevaclave99"})
        corta = c.post("/api/password", headers=H, json={"current_password": password, "new_password": "corta"})
        igual = c.post("/api/password", headers=H, json={"current_password": password, "new_password": password})

        assert (mal_actual.status_code, corta.status_code, igual.status_code) == (400, 422, 400)


def test_admin_es_solo_para_admin_users():
    with TestClient(app) as c:
        username, password = _new_user(must_change=False)

        assert c.get("/api/admin/users", headers=login_headers(c, username, password)).status_code == 403
        assert c.get("/api/admin/users", headers=_admin(c)).status_code == 200
        assert c.get("/api/me", headers=_admin(c)).json()["is_admin"] is True


def test_admin_crea_usuario_que_debe_cambiar_la_contraseña():
    with TestClient(app) as c:
        username = f"n_{uuid.uuid4().hex[:6]}"

        r = c.post("/api/admin/users", headers=_admin(c), json={"username": username, "password": "temporal123"})
        duplicado = c.post("/api/admin/users", headers=_admin(c), json={"username": username, "password": "temporal123"})

        assert r.status_code == 200, r.text
        assert duplicado.status_code == 409
        login = c.post("/api/login", json={"username": username, "password": "temporal123"}).json()
        assert login["must_change_password"] is True
        listado = {u["username"]: u for u in c.get("/api/admin/users", headers=_admin(c)).json()["users"]}
        assert listado[username]["is_active"] is True


def test_admin_resetea_contraseña_y_revoca_sesiones():
    with TestClient(app) as c:
        username, password = _new_user(must_change=False)
        H = login_headers(c, username, password)

        r = c.post(f"/api/admin/users/{username}/reset-password", headers=_admin(c), json={"password": "reseteada123"})

        assert r.status_code == 200, r.text
        assert c.get("/api/me", headers=H).status_code == 401
        assert c.post("/api/login", json={"username": username, "password": password}).status_code == 401
        assert c.post("/api/login", json={"username": username, "password": "reseteada123"}).json()["must_change_password"] is True


def test_admin_desactiva_usuario_y_no_puede_desactivarse_a_si_mismo():
    with TestClient(app) as c:
        username, password = _new_user(must_change=False)
        H = login_headers(c, username, password)

        r = c.post(f"/api/admin/users/{username}/active", headers=_admin(c), json={"active": False})
        propio = c.post(f"/api/admin/users/{TEST_ADMIN}/active", headers=_admin(c), json={"active": False})

        assert r.status_code == 200, r.text
        assert propio.status_code == 400
        assert c.get("/api/me", headers=H).status_code == 401
        assert c.post("/api/login", json={"username": username, "password": password}).status_code == 401

        c.post(f"/api/admin/users/{username}/active", headers=_admin(c), json={"active": True})
        assert c.post("/api/login", json={"username": username, "password": password}).status_code == 200


def test_admin_usuario_inexistente_da_404():
    with TestClient(app) as c:
        r = c.post("/api/admin/users/no_existe_xyz/reset-password", headers=_admin(c), json={"password": "reseteada123"})

        assert r.status_code == 404


def test_admin_uso_resume_grabaciones_e_itinerarios():
    with TestClient(app) as c:
        r = c.get("/api/admin/usage", headers=_admin(c))

        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"recordings_by_status", "recent_errors", "users"}

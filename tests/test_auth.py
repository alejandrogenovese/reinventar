"""Tests de login/logout y de que el itinerario quede separado por usuario."""
from fastapi.testclient import TestClient

from app import db, passwords
from app.main import app
from tests.conftest import TEST_USER, login_headers


def test_login_y_logout():
    with TestClient(app) as c:
        assert c.post("/api/login", json={"username": TEST_USER, "password": "contraseña incorrecta"}).status_code == 401

        H = login_headers(c)
        assert c.get("/api/me", headers=H).json()["username"] == TEST_USER

        assert c.post("/api/logout", headers=H).status_code == 200
        assert c.get("/api/me", headers=H).status_code == 401


def test_itinerarios_quedan_separados_por_usuario():
    with TestClient(app) as c:
        if not db.get_user("otra_persona"):
            salt, h = passwords.hash_password("otracontra123")
            db.create_user("otra_persona", salt, h)

        h1 = login_headers(c)
        h2 = login_headers(c, "otra_persona", "otracontra123")

        r1 = c.post("/api/itinerary/generate", headers=h1, json={"profile": {"role": "a", "experience": "", "interests": ["Artificial Intelligence"]}, "prompt": "x"})
        r2 = c.post("/api/itinerary/generate", headers=h2, json={"profile": {"role": "b", "experience": "", "interests": ["Security & Identity"]}, "prompt": "y"})
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text

        def codes(headers):
            return {s["code"] for day in c.get("/api/itinerary", headers=headers).json()["days"] for s in day["sessions"]}

        items1, items2 = codes(h1), codes(h2)
        assert items1 and items2

        # borrar una sesión del itinerario de un usuario no toca al del otro
        code1 = next(iter(items1))
        assert c.delete(f"/api/itinerary/items/{code1}", headers=h1).status_code == 200
        assert code1 not in codes(h1)
        assert codes(h2) == items2

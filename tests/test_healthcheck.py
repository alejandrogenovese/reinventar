"""Chequeo funcional de Admin: corre, informa cada parte y no deja datos de prueba ni toca lo real. Usa el catálogo local."""
from fastapi.testclient import TestClient

from app import db, healthcheck, sandbox
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers


def test_el_chequeo_informa_cada_parte_y_lo_esencial_da_ok():
    with TestClient(app) as c:
        checks = {ch["name"]: ch for ch in c.get("/api/admin/check", headers=login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)).json()["checks"]}

    assert set(checks) == {name for name, _ in healthcheck.CHECKS}
    for name in ("Catálogo", "Búsqueda", "Explorar", "Datos de prueba aislados", "Reloj simulado y Hoy", "LLM"):
        assert checks[name]["ok"], checks[name]


def test_el_chequeo_no_deja_nada_en_el_itinerario_de_prueba_ni_en_el_real():
    with TestClient(app):
        healthcheck.run_all()
        with sandbox.activar(sandbox.Sandbox(healthcheck.CHECK_USER)):
            assert db.list_itinerary_items(healthcheck.CHECK_USER) == []
        assert db.list_itinerary_items(healthcheck.CHECK_USER) == []


def test_solo_admin():
    with TestClient(app) as c:
        assert c.get("/api/admin/check", headers=login_headers(c)).status_code == 403

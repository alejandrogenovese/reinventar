"""Modo prueba por usuario: lo prende un admin y lo que hace ese usuario va al schema de prueba, sin tocar sus datos reales."""
import datetime as dt
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import config, pg, pipeline, sandbox, venues
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

PASSWORD = "sandboxpass123"


@pytest.fixture
def cli():
    with TestClient(app) as c:
        admin = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        username = f"sb_{uuid.uuid4().hex[:6]}"
        assert c.post("/api/admin/users", headers=admin, json={"username": username, "password": PASSWORD}).status_code == 200
        c.admin, c.username, c.user = admin, username, login_headers(c, username, PASSWORD)
        yield c


def _sandbox(c, **body):
    return c.put(f"/api/admin/users/{c.username}/sandbox", headers=c.admin, json={"active": True, **body})


def _count(schema: str, table: str, where: str, *params) -> int:
    with sandbox.real(), pg.pool().connection() as conn:
        return conn.execute(f"SELECT count(*) AS n FROM {schema}.{table} WHERE {where}", params).fetchone()["n"]


def test_lo_que_crea_en_modo_prueba_va_al_schema_de_prueba(cli):
    assert _sandbox(cli).status_code == 200

    sid = cli.post("/api/sessions", headers=cli.user, json={"title": "Prueba", "kind": "Breakout"}).json()["id"]

    assert _count(sandbox.schema_prueba(), "sessions", "id = %s", sid) == 1
    assert _count(config.DB_SCHEMA, "sessions", "id = %s", sid) == 0


def test_al_apagarlo_vuelve_a_ver_sus_datos_reales_intactos(cli):
    real_sid = cli.post("/api/sessions", headers=cli.user, json={"title": "Real", "kind": "Breakout"}).json()["id"]
    _sandbox(cli)
    cli.post("/api/sessions", headers=cli.user, json={"title": "Prueba", "kind": "Breakout"})

    cli.put(f"/api/admin/users/{cli.username}/sandbox", headers=cli.admin, json={"active": False})

    titles = {s["id"]: s["title"] for s in cli.get("/api/sessions", headers=cli.user).json()}
    assert titles.get(real_sid) == "Real"
    assert "Prueba" not in titles.values()


def test_me_informa_el_modo_prueba_con_reloj_y_ubicacion_simulados(cli, monkeypatch):
    # Sin depender del catálogo (en CI no está): una sede de prueba en el maestro en memoria.
    monkeypatch.setattr(venues, "_by_id", {7: {"id": 7, "name": "Venetian", "lat": 36.1216, "lng": -115.1691}})
    _sandbox(cli, clock="2026-12-01T13:40:00", venue_id=7)

    info = cli.get("/api/me", headers=cli.user).json()["sandbox"]

    assert info["location"]["name"] == "Venetian"
    assert info["now"].startswith("2026-12-01T13:40")
    assert (info["stt"], info["llm"], info["simulated_clock"]) == ("fake", "fake", True)


def test_un_usuario_normal_no_tiene_sandbox(cli):
    assert cli.get("/api/me", headers=cli.user).json()["sandbox"] is None


def test_avanzar_el_reloj_simulado(cli):
    _sandbox(cli, clock="2026-12-01T13:40:00")

    r = cli.post(f"/api/admin/users/{cli.username}/sandbox/advance", headers=cli.admin, json={"minutes": 15})

    assert r.json()["sandbox"]["now"].startswith("2026-12-01T13:55")


def test_solo_un_admin_lo_puede_prender(cli):
    r = cli.put(f"/api/admin/users/{cli.username}/sandbox", headers=cli.user, json={"active": True})

    assert r.status_code == 403


def test_sede_inexistente_se_rechaza(cli):
    assert _sandbox(cli, venue_id=999).status_code == 422


def test_borrar_datos_de_prueba_no_toca_lo_real(cli):
    real_sid = cli.post("/api/sessions", headers=cli.user, json={"title": "Real", "kind": "Breakout"}).json()["id"]
    _sandbox(cli)
    cli.post("/api/sessions", headers=cli.user, json={"title": "Prueba", "kind": "Breakout"})

    assert cli.delete("/api/admin/sandbox/data", headers=cli.admin).status_code == 200

    assert _count(sandbox.schema_prueba(), "sessions", "true") == 0
    assert _count(config.DB_SCHEMA, "sessions", "id = %s", real_sid) == 1


def test_proveedores_fake_en_sandbox_aunque_produccion_use_los_reales(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "STT_PROVIDER", "openai")

    with sandbox.activar(sandbox.Sandbox("x", stt="fake", llm="real")):
        assert (sandbox.proveedor_stt(), sandbox.proveedor_llm()) == ("fake", "anthropic")
    assert sandbox.proveedor_llm() == "anthropic"


def test_el_reloj_simulado_avanza_con_el_tiempo_real():
    inicio = dt.datetime(2026, 12, 1, 13, 40, tzinfo=sandbox.EVENT_TZ)
    sb = sandbox.Sandbox("x", reloj=inicio, reloj_fijado=time.time() - 90)

    with sandbox.activar(sb):
        transcurrido = sandbox.ahora() - inicio

    assert dt.timedelta(seconds=89) < transcurrido < dt.timedelta(seconds=95)


def test_el_pipeline_procesa_en_el_contexto_de_quien_encolo(monkeypatch):
    encolados = []
    monkeypatch.setattr(pipeline, "_q", type("Q", (), {"put": lambda self, item: encolados.append(item)})())
    monkeypatch.setattr(pipeline.db, "update_session", lambda *a, **k: None)
    sb = sandbox.Sandbox("x")

    with sandbox.activar(sb):
        pipeline.enqueue("s1")

    assert encolados == [("s1", sb, None)]  # sin usuario en el contexto (el del pedido lo pone el middleware)

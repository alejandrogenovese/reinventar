"""Avisos de cambios sobre el itinerario: horario, lugar, lleno y bajas. Con eventos falsos (no necesita el catálogo)."""
import pytest
from fastapi.testclient import TestClient

from app import changes, events
from app.main import app
from tests.conftest import login_headers


def _evento(day="2026-12-01", start="18:00", hotel="Topgolf", full=False, code="evt-cambia"):
    return {"kind": "event", "code": code, "base": code, "title": "Happy Hour", "type": "happy hour", "day": day,
            "start": start, "end": "21:00", "venue": {"hotel": hotel, "detail": "", "lat": 36.1, "lng": -115.16},
            "full": full}


@pytest.fixture
def cli(monkeypatch):
    with TestClient(app) as c:
        monkeypatch.setattr(events, "_events", {"evt-cambia": _evento()})
        c.H = login_headers(c)
        c.post("/api/itinerary/items", headers=c.H, json={"code": "evt-cambia"})
        yield c
        c.delete("/api/itinerary/items/evt-cambia", headers=c.H)


def test_sin_cambios_no_hay_avisos(cli):
    assert cli.get("/api/itinerary/changes", headers=cli.H).json()["changes"] == []


def test_cambio_de_horario_lugar_y_lleno_se_avisa(cli, monkeypatch):
    monkeypatch.setattr(events, "_events", {"evt-cambia": _evento(day="2026-12-02", start="19:00", hotel="TAO", full=True)})

    msgs = cli.get("/api/itinerary/changes", headers=cli.H).json()["changes"][0]["messages"]

    assert any("era mar 1/12 18:00, ahora mié 2/12 19:00" in m for m in msgs)
    assert any("ahora es en TAO (antes: Topgolf)" in m for m in msgs)
    assert any("se llenó" in m for m in msgs)


def test_entendido_actualiza_la_foto_y_no_vuelve_a_avisar(cli, monkeypatch):
    monkeypatch.setattr(events, "_events", {"evt-cambia": _evento(start="19:30")})

    r = cli.post("/api/itinerary/changes/ack", headers=cli.H, json={"codes": ["evt-cambia"]}).json()

    assert r["changes"] == []
    assert cli.get("/api/itinerary/changes", headers=cli.H).json()["changes"] == []


def test_lo_que_desaparecio_se_avisa_y_entendido_lo_quita(cli, monkeypatch):
    monkeypatch.setattr(events, "_events", {})

    pend = cli.get("/api/itinerary/changes", headers=cli.H).json()["changes"]
    assert pend[0]["gone"] is True

    cli.post("/api/itinerary/changes/ack", headers=cli.H, json={"codes": ["evt-cambia"]})
    assert cli.get("/api/itinerary/changes", headers=cli.H).json()["changes"] == []


def test_diff_ignora_lo_que_no_cambio():
    foto = {"title": "X", "day": "2026-12-01", "start": "10:00", "venue": "MGM Grand · L3", "full": False}

    assert changes.diff(foto, dict(foto)) == []

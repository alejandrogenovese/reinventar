"""Eventos en la app: API, dentro del itinerario (fijados), superposiciones con charlas y "Hoy". Usa el catálogo local."""
import pytest
from fastapi.testclient import TestClient

from app import catalog, events, itinerary, today
from app.main import app
from tests.conftest import TEST_USER, login_headers


def _evento(code, day, start, end, title="Happy Hour"):
    return {"kind": "event", "code": code, "base": code, "title": title, "type": "happy hour", "day": day,
            "start": start, "end": end, "venue": {"hotel": "Topgolf", "detail": "", "lat": 36.1, "lng": -115.16},
            "image": None, "summary": "Resumen.", "url": "https://luma.com/x", "organizers": [], "topics": []}


@pytest.fixture
def talk():
    """Una charla real del catálogo local: (código de horario, día, inicio)."""
    session = next(s for s in catalog.all_sessions() if s.get("instances"))
    inst = session["instances"][0]
    return inst["c"], inst["d"], inst["st"]


@pytest.fixture
def cli(monkeypatch, talk):
    code, day, start = talk
    with TestClient(app) as c:  # el arranque recarga los eventos de la base: se reemplazan después
        monkeypatch.setattr(events, "_events", {
            "evt-choca": _evento("evt-choca", day, start, "23:59", "Fiesta que choca"),
            "evt-noche": _evento("evt-noche", day, "23:30", "01:00", "After de medianoche")})
        c.H = login_headers(c)
        for d in itinerary.get_current(TEST_USER)["days"]:
            for s in d["sessions"]:
                c.delete(f"/api/itinerary/items/{s['code']}", headers=c.H)
        yield c


def test_la_api_lista_los_eventos_por_dia(cli):
    days = cli.get("/api/events", headers=cli.H).json()["days"]

    assert [e["code"] for d in days for e in d["events"]] == ["evt-choca", "evt-noche"]
    assert all(e["in_itinerary"] is False for d in days for e in d["events"])


def test_un_evento_entra_al_itinerario_fijado(cli):
    r = cli.post("/api/itinerary/items", headers=cli.H, json={"code": "evt-noche"}).json()

    item = next(s for d in r["days"] for s in d["sessions"] if s["code"] == "evt-noche")
    assert (item["kind"], item["locked"], item["end"]) == ("event", True, "01:00")


def test_evento_y_charla_superpuestos_se_marcan(cli, talk):
    code, _, _ = talk
    cli.post("/api/itinerary/items", headers=cli.H, json={"code": code})
    r = cli.post("/api/itinerary/items", headers=cli.H, json={"code": "evt-choca"}).json()

    sessions = {s["code"]: s for d in r["days"] for s in d["sessions"]}
    assert sessions["evt-choca"]["overlaps"] == [sessions[code]["title"]]
    assert cli.get("/api/events/evt-choca", headers=cli.H).json()["clashes"][0]["code"] == code


def test_evento_que_termina_pasada_la_medianoche_no_rompe_las_superposiciones():
    a = {"start": "23:30", "end": "01:00"}

    assert itinerary._span(a) == (23 * 60 + 30, 24 * 60)


def test_hoy_usa_el_fin_del_evento(talk):
    _, day, _ = talk
    ev = _evento("evt-x", day, "19:00", "22:30")

    plan = today.plan([{"day": day, "sessions": [{**ev, "end": "22:30"}]}],
                      today.datetime.fromisoformat(f"{day}T20:00:00"))

    assert (plan["now"]["code"], plan["now"]["end"]) == ("evt-x", "22:30")


def test_evento_inexistente_da_404(cli):
    assert cli.get("/api/events/evt-nada", headers=cli.H).status_code == 404

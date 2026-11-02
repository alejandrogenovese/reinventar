"""Pantalla Hoy: qué charla del itinerario está pasando y cuál sigue (hora de Las Vegas)."""
from datetime import datetime

from fastapi.testclient import TestClient

from app import catalog, today
from app.main import app
from tests.conftest import login_headers


def _s(code, day, start, type_="Breakout session"):
    return {"code": code, "day": day, "start": start, "type": type_, "title": code}


DAYS = [
    {"day": "2026-12-01", "sessions": [_s("A", "2026-12-01", "09:00"), _s("B", "2026-12-01", "11:00"), _s("C", "2026-12-01", "14:00")]},
    {"day": "2026-12-02", "sessions": [_s("D", "2026-12-02", "10:00", "Workshop")]},
]


def test_durante_una_charla_la_marca_como_ahora_y_la_siguiente_como_proxima():
    r = today.plan(DAYS, datetime(2026, 12, 1, 9, 30))

    assert r["date"] == "2026-12-01"
    assert r["now"]["code"] == "A" and r["now"]["end"] == "10:00"
    assert r["next"]["code"] == "B"
    assert [s["code"] for s in r["later"]] == ["C"]


def test_entre_charlas_no_hay_ahora_y_la_proxima_es_la_siguiente_del_dia():
    r = today.plan(DAYS, datetime(2026, 12, 1, 10, 30))

    assert r["now"] is None
    assert r["next"]["code"] == "B"
    assert [s["code"] for s in r["later"]] == ["C"]


def test_la_duracion_se_estima_por_tipo():
    r = today.plan(DAYS, datetime(2026, 12, 2, 11, 30))

    assert r["now"]["code"] == "D" and r["now"]["end"] == "12:00"
    assert r["now"]["recording_kind"] == "Workshop"


def test_terminado_el_dia_apunta_al_proximo_dia_con_charlas():
    r = today.plan(DAYS, datetime(2026, 12, 1, 18, 0))

    assert r["now"] is None and r["next"] is None and r["later"] == []
    assert r["upcoming"]["day"] == "2026-12-02"
    assert r["upcoming"]["first"]["code"] == "D"


def test_antes_del_evento_apunta_al_primer_dia():
    r = today.plan(DAYS, datetime(2026, 11, 1, 12, 0))

    assert r["upcoming"]["day"] == "2026-12-01"


def test_sin_itinerario_devuelve_todo_vacio():
    r = today.plan([], datetime(2026, 12, 1, 9, 0))

    assert r == {"date": "2026-12-01", "time": "09:00", "now": None, "next": None, "later": [], "upcoming": None}


def test_no_modifica_las_cards_del_itinerario():
    today.plan(DAYS, datetime(2026, 12, 1, 9, 30))

    assert "end" not in DAYS[0]["sessions"][0]


def test_endpoint_hoy_requiere_login_y_responde_con_el_itinerario():
    with TestClient(app) as c:
        assert c.get("/api/today").status_code == 401
        H = login_headers(c)
        code = catalog.search(limit=1, q="s3")[0]["code"]
        assert c.post("/api/itinerary/items", headers=H, json={"code": code}).status_code == 200

        r = c.get("/api/today", headers=H)

        assert r.status_code == 200
        assert set(r.json()) == {"date", "time", "now", "next", "later", "upcoming"}
        c.delete(f"/api/itinerary/items/{code}", headers=H)

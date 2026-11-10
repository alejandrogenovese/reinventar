"""Charlas repetidas: "Me la perdí" (otros horarios y parecidas) y "Cambiar a este". Usa el catálogo local."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import catalog, missed, sandbox
from app.main import app
from tests.conftest import TEST_USER, login_headers


@pytest.fixture
def repetida():
    """Una charla con al menos 3 horarios en días distintos."""
    return next(s for s in catalog.all_sessions() if len({i["d"] for i in s.get("instances", [])}) >= 3)


@pytest.fixture
def cli():
    with TestClient(app) as c:
        c.H = login_headers(c)
        yield c
        for d in c.get("/api/itinerary", headers=c.H).json()["days"]:
            for s in d["sessions"]:
                c.delete(f"/api/itinerary/items/{s['code']}", headers=c.H)


def _antes_de(inst, monkeypatch, horas=1):
    momento = dt.datetime.fromisoformat(f"{inst['d']}T{inst['st']}").replace(tzinfo=sandbox.EVENT_TZ) - dt.timedelta(hours=horas)
    monkeypatch.setattr(missed.sandbox, "ahora", lambda tz=None: momento)


def test_me_la_perdi_ofrece_los_otros_horarios_futuros(cli, repetida, monkeypatch):
    primero, *resto = sorted(repetida["instances"], key=lambda i: (i["d"], i["st"]))
    cli.post("/api/itinerary/items", headers=cli.H, json={"code": primero["c"]})
    _antes_de(primero, monkeypatch, horas=-2)  # ya pasó el primero

    r = cli.get(f"/api/itinerary/missed/{primero['c']}", headers=cli.H).json()

    assert primero["c"] not in [c["code"] for c in r["repeats"]]
    assert {c["code"] for c in r["repeats"]} <= {i["c"] for i in resto}
    assert r["repeats"]


def test_parecidas_solo_las_que_empiezan_pronto(repetida, monkeypatch):
    inst = repetida["instances"][0]
    _antes_de(inst, monkeypatch, horas=0)

    opciones = missed.options(TEST_USER, inst["c"])

    ahora = missed.sandbox.ahora()
    for c in opciones["similar"]:
        empieza = dt.datetime.fromisoformat(f"{c['day']}T{c['start']}").replace(tzinfo=sandbox.EVENT_TZ)
        assert ahora < empieza <= ahora + missed.SIMILAR_WINDOW


def test_cambiar_a_otro_horario_conserva_el_pin(cli, repetida):
    primero, segundo = sorted(repetida["instances"], key=lambda i: (i["d"], i["st"]))[:2]
    cli.post("/api/itinerary/items", headers=cli.H, json={"code": primero["c"]})

    r = cli.post(f"/api/itinerary/items/{primero['c']}/swap", headers=cli.H, json={"to": segundo["c"]}).json()

    codes = {s["code"]: s for d in r["days"] for s in d["sessions"]}
    assert primero["c"] not in codes
    assert codes[segundo["c"]]["locked"] is True


def test_no_se_puede_cambiar_a_un_horario_de_otra_charla(cli, repetida):
    otra = next(s for s in catalog.all_sessions() if s["base"] != repetida["base"] and s.get("instances"))
    cli.post("/api/itinerary/items", headers=cli.H, json={"code": repetida["instances"][0]["c"]})

    r = cli.post(f"/api/itinerary/items/{repetida['instances'][0]['c']}/swap", headers=cli.H,
                 json={"to": otra["instances"][0]["c"]})

    assert r.status_code == 400


def test_codigo_inexistente_da_404(cli):
    assert cli.get("/api/itinerary/missed/NOPE999", headers=cli.H).status_code == 404

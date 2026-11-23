"""Qué charlas publica AWS en YouTube (app/catalog.py) y que la API lo exponga como en_youtube, con un catálogo
chico en memoria (corre en CI)."""
import pytest
from fastapi.testclient import TestClient

from app import catalog, db
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

DIA = "2026-12-01"


@pytest.mark.parametrize("tipo", ["Keynote", "Mainstage", "Breakout session", " Breakout session ", "Breakout Session",
                                  "KEYNOTE"])
def test_keynotes_mainstage_y_breakouts_salen_en_youtube(tipo):
    assert catalog.se_publica_en_youtube(tipo) is True


@pytest.mark.parametrize("tipo", ["Chalk talk", "Code talk", "Lightning talk", "Workshop", "Builders' session", "Lab",
                                  "Meetup", "Gamified learning", "Bootcamp", "Exam prep", "Featured experience",
                                  "", "   ", None, "Tipo nuevo", "breakout"])
def test_el_resto_y_lo_vacio_o_desconocido_no(tipo):
    assert catalog.se_publica_en_youtube(tipo) is False


def _s(base, tipo):
    return {"base": base, "title": f"Charla {base}", "type": tipo, "level": "300", "topic": "", "aoi": "",
            "services": "", "tech": "", "concepts": "", "concepts_en": "", "focus": "", "speakers": "", "people": [],
            "abstract": "", "abstract_es": None, "newlaunch": False,
            "instances": [{"c": base, "d": DIA, "st": "10:00", "v": "MGM Grand|Level 3", "seats": 100, "walk": True}]}


CATALOGO = [_s("ANT301", "Breakout session"), _s("ANT302", "Chalk talk"), _s("KEY001", "Keynote")]


def test_la_tarjeta_de_la_charla_trae_en_youtube():
    assert catalog.card(CATALOGO[0], CATALOGO[0]["instances"][0])["en_youtube"] is True
    assert catalog.card(CATALOGO[1], CATALOGO[1]["instances"][0])["en_youtube"] is False


@pytest.fixture
def client(monkeypatch):
    with TestClient(app) as c:
        monkeypatch.setattr(catalog, "_sessions", CATALOGO)
        yield c


@pytest.fixture
def headers(client):
    h = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    yield h
    for it in db.list_itinerary_items(TEST_ADMIN):
        db.remove_item(TEST_ADMIN, it["code"])


def test_el_itinerario_expone_en_youtube_por_charla(client, headers):
    for code in ("ANT301", "ANT302", "KEY001"):
        assert client.post("/api/itinerary/items", headers=headers, json={"code": code}).status_code == 200

    r = client.get("/api/itinerary", headers=headers)

    assert r.status_code == 200
    charlas = {s["code"]: s["en_youtube"] for d in r.json()["days"] for s in d["sessions"]}
    assert charlas == {"ANT301": True, "ANT302": False, "KEY001": True}

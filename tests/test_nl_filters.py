"""Filtrar en lenguaje natural: el LLM propone filtros, que se validan contra los valores reales de cada faceta."""
import json

from fastapi.testclient import TestClient

from app import llm, nl_filters, prompts
from app.main import app
from tests.conftest import login_headers


def _llm_returns(monkeypatch, payload):
    calls = []

    def fake(model, system, user, *a, **k):
        calls.append((system, user))
        return json.dumps(payload)

    monkeypatch.setattr(llm, "complete", fake)
    return calls


def _parse(c, H, text):
    r = c.post("/api/k/explore/parse", headers=H, json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_requiere_sesion_y_texto_valido():
    with TestClient(app) as c:
        assert c.post("/api/k/explore/parse", json={"text": "bancos"}).status_code == 401
        H = login_headers(c)
        assert c.post("/api/k/explore/parse", headers=H, json={"text": "a"}).status_code == 422
        assert c.post("/api/k/explore/parse", headers=H, json={"text": "x" * 400}).status_code == 422


def test_traduce_a_filtros_con_los_valores_exactos_del_catalogo(monkeypatch):
    _llm_returns(monkeypatch, {
        "filters": {"sector": ["finanzas"], "dia": ["2026-12-01"], "area": ["agentic ai"], "empresa": ["NUBANK"]},
        "q": "bedrock",
    })
    with TestClient(app) as c:
        body = _parse(c, login_headers(c), "fintechs como Nubank hablando de agentes con Bedrock el martes")

        assert body["filters"] == {"sector": ["Finanzas"], "dia": ["2026-12-01"], "area": ["Agentic AI"], "empresa": ["Nubank"]}
        assert body["q"] == "bedrock" and body["ignored"] == []


def test_descarta_facetas_y_valores_que_no_existen(monkeypatch):
    _llm_returns(monkeypatch, {"filters": {"precio": ["barato"], "sector": ["Marte", "Salud"]}, "q": ""})
    with TestClient(app) as c:
        body = _parse(c, login_headers(c), "charlas baratas de salud en marte")

        assert body["filters"] == {"sector": ["Salud"]}
        assert set(body["ignored"]) == {"precio: barato", "sector: Marte"}


def test_el_prompt_lista_los_dias_con_su_nombre_y_los_valores_validos(monkeypatch):
    calls = _llm_returns(monkeypatch, {"filters": {}, "q": ""})
    with TestClient(app) as c:
        _parse(c, login_headers(c), "lo del martes")

    system, user = calls[0]
    assert system == prompts.NL_FILTERS_SYSTEM
    assert "2026-12-01 (martes)" in user and "Finanzas" in user and "Nubank" in user
    assert user.rstrip().endswith("lo del martes")


def test_los_filtros_devueltos_sirven_tal_cual_para_explorar(monkeypatch):
    _llm_returns(monkeypatch, {"filters": {"sector": ["Finanzas"], "topico": ["Artificial Intelligence"]}, "q": ""})
    with TestClient(app) as c:
        H = login_headers(c)
        parsed = _parse(c, H, "bancos e inteligencia artificial")

        r = c.post("/api/k/explore", headers=H, json={"filters": parsed["filters"], "q": parsed["q"]})

        assert r.status_code == 200 and r.json()["total"] > 0


def test_respuesta_rara_del_llm_no_rompe(monkeypatch):
    _llm_returns(monkeypatch, {"filters": {"sector": "Finanzas", "dia": [3]}, "q": None})
    with TestClient(app) as c:
        body = _parse(c, login_headers(c), "bancos")

        assert body["filters"] == {"sector": ["Finanzas"]} and body["q"] == ""


def test_con_el_llm_caido_da_502(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("timeout")

    monkeypatch.setattr(llm, "complete", boom)
    with TestClient(app) as c:
        assert c.post("/api/k/explore/parse", headers=login_headers(c), json={"text": "bancos"}).status_code == 502


def test_nombres_de_los_dias():
    assert nl_filters.day_label("2026-11-30") == "2026-11-30 (lunes)"
    assert nl_filters.day_label("2026-12-03") == "2026-12-03 (jueves)"

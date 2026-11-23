"""Buscar escribiendo el código de una charla («Key002», «AIM204»): el texto buscable incluye los códigos de todos los
horarios, y un texto con forma de código no pasa por el LLM. Catálogo armado a mano: no necesita el real."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import catalog, explore, nl_filters
from app.main import app
from tests.conftest import login_headers


def _s(base, title, *codigos):
    return {"base": base, "title": title, "type": "Breakout session", "level": "200", "people": [],
            "instances": [{"c": c, "d": "2026-12-01", "st": f"{9 + i}:00", "v": "Venetian|Hall A"}
                          for i, c in enumerate(codigos)]}


CATALOGO = [
    _s("KEY002", "Opening keynote", "KEY002"),
    _s("AIM204", "Agents in production", "AIM204", "AIM204-R1", "AIM204-R2"),
    _s("SEC301", "Fine-grained access", "SEC301"),
]


@pytest.fixture(autouse=True)
def _catalogo_a_mano(monkeypatch):
    monkeypatch.setattr(catalog, "_sessions", CATALOGO)
    monkeypatch.setattr(explore, "_entries", None)


def _codigos(resultados):
    return {r["code"] for r in resultados}


# ---------- el texto buscable lleva los códigos ----------

@pytest.mark.parametrize("q", ["key002", "KEY002", "Key002"])
def test_catalog_search_encuentra_la_charla_por_su_codigo(q):
    assert _codigos(catalog.search(q=q)) == {"KEY002"}


@pytest.mark.parametrize("q", ["aim204", "AIM204", "aim204-r1", "aim204-R2"])
def test_catalog_search_encuentra_la_charla_con_sufijo_de_repeticion(q):
    assert _codigos(catalog.search(q=q)) >= {"AIM204"}


@pytest.mark.parametrize("q", ["key002", "KEY002", "aim204", "AIM204", "aim204-r1"])
def test_explore_encuentra_la_charla_por_su_codigo(q):
    assert explore.explore({}, q=q)["total"] == 1


def test_un_codigo_que_no_existe_no_encuentra_nada():
    assert explore.explore({}, q="zzz999")["total"] == 0
    assert catalog.search(q="zzz999") == []


def test_buscar_por_titulo_sigue_andando():
    assert explore.explore({}, q="agents")["total"] == 1


# ---------- un código no pasa por el LLM ----------

@pytest.fixture
def sin_llm(monkeypatch):
    llamadas = []

    def complete(*a, **k):
        llamadas.append(a)
        return "esto no es JSON"

    monkeypatch.setattr(nl_filters, "llm", SimpleNamespace(complete=complete, parse_json_puntuado=json.loads))
    monkeypatch.setattr(nl_filters, "_allowed", lambda: {})
    return llamadas


@pytest.mark.parametrize("texto", ["KEY002", "key002", "AIM204", " aim204 ", "AIM204-R1", "aim204-r12", "ABC123-S", "IND3313", "AIM2205-S", "SVC003-D0"])
def test_un_codigo_devuelve_filtros_vacios_sin_llamar_al_llm(sin_llm, texto):
    assert nl_filters.parse(texto) == {"filters": {}, "q": "", "ignored": []}
    assert sin_llm == []


@pytest.mark.parametrize("texto", ["bedrock", "AIM20456", "AI204", "aim 204", "AIM204-X1", "agentes AIM204"])
def test_lo_que_no_es_un_codigo_sigue_yendo_al_llm(sin_llm, texto):
    with pytest.raises(nl_filters.NLFiltersUnavailable):
        nl_filters.parse(texto)

    assert len(sin_llm) == 1


def test_el_endpoint_responde_200_con_un_codigo_y_502_si_el_llm_no_trae_json(sin_llm):
    with TestClient(app) as c:
        H = login_headers(c)

        codigo = c.post("/api/k/explore/parse", headers=H, json={"text": "AIM204"})
        frase = c.post("/api/k/explore/parse", headers=H, json={"text": "charlas de bancos"})

    assert (codigo.status_code, codigo.json()) == (200, {"filters": {}, "q": "", "ignored": []})
    assert frase.status_code == 502

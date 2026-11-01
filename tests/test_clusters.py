"""Agrupaciones emergentes: k-means sobre los embeddings de las charlas, nombradas por el LLM, como faceta "tema"."""
import json
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import catalog, clusters, llm, pg, search
from app.main import app
from tests.conftest import login_headers


def _naming_llm(monkeypatch):
    calls = []

    def fake(model, system, user, *a, **k):
        calls.append(user)
        ids = re.findall(r"^Grupo (\d+):", user, re.M)
        return json.dumps({"groups": [{"id": int(i), "name": f"Tema {i}"} for i in ids]})

    monkeypatch.setattr(llm, "complete", fake)
    return calls


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    catalog.load()
    search.ensure_index()
    with pg.pool().connection() as c:
        c.execute("DROP TABLE IF EXISTS speech_cluster")
    clusters.reset()


def test_kmeans_es_deterministico_y_separa_grupos_obvios():
    rng = np.random.default_rng(0)
    a = rng.normal([1, 0, 0], 0.05, (20, 3))
    b = rng.normal([0, 1, 0], 0.05, (20, 3))
    X = np.vstack([a, b])
    X /= np.linalg.norm(X, axis=1, keepdims=True)

    labels1, _ = clusters.kmeans(X, 2)
    labels2, _ = clusters.kmeans(X, 2)

    assert labels1.tolist() == labels2.tolist()
    assert len(set(labels1[:20])) == 1 and len(set(labels1[20:])) == 1 and labels1[0] != labels1[20]


def test_cada_charla_queda_en_un_tema_con_nombre_del_llm(monkeypatch):
    _naming_llm(monkeypatch)

    clusters.ensure()

    labels = {s["base"]: clusters.label_for(s["base"]) for s in catalog.all_sessions()}
    assert all(labels.values())
    assert 1 < len(set(labels.values())) <= clusters.CLUSTER_COUNT
    assert all(label.startswith("Tema ") for label in labels.values())


def test_los_temas_quedan_guardados_y_no_se_vuelve_a_llamar_al_llm(monkeypatch):
    calls = _naming_llm(monkeypatch)
    clusters.ensure()
    first = {s["base"]: clusters.label_for(s["base"]) for s in catalog.all_sessions()}
    clusters.reset()

    clusters.ensure()

    assert len(calls) == 1
    assert {s["base"]: clusters.label_for(s["base"]) for s in catalog.all_sessions()} == first


def test_si_el_llm_falla_usa_nombres_de_respaldo_y_no_los_guarda(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("caído")

    monkeypatch.setattr(llm, "complete", boom)

    clusters.ensure()

    assert all(clusters.label_for(s["base"]) for s in catalog.all_sessions())
    with pg.pool().connection() as c:
        assert c.execute("SELECT count(*) AS n FROM speech_cluster").fetchone()["n"] == 0


def test_sin_embeddings_no_hay_temas(monkeypatch):
    monkeypatch.setattr(search, "ready_vectors", lambda: None)

    clusters.ensure()

    assert clusters.label_for(catalog.all_sessions()[0]["base"]) is None


def test_tema_es_una_faceta_del_explorador(monkeypatch):
    _naming_llm(monkeypatch)
    clusters.ensure()
    with TestClient(app) as c:
        H = login_headers(c)
        catalog.load()
        search.ensure_index()
        clusters.ensure()

        body = c.post("/api/k/explore", headers=H, json={}).json()
        tema = body["facets"]["tema"][0]["value"]
        filtered = c.post("/api/k/explore", headers=H, json={"filters": {"tema": [tema]}, "limit": 500}).json()

        assert filtered["total"] == body["facets"]["tema"][0]["count"]
        assert all(clusters.label_for(r["base"]) == tema for r in filtered["results"])

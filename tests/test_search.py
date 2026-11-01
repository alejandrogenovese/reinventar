"""Búsqueda híbrida (embeddings + BM25 con RRF), vectores persistidos y chat de búsqueda sobre el catálogo."""
import pytest
from fastapi.testclient import TestClient

from app import catalog, embeddings, llm, pg, search
from app.main import app
from tests.conftest import login_headers


def _bases(hits):
    return [s["base"] for s in hits]


@pytest.fixture(scope="module", autouse=True)
def _index():
    catalog.load()
    search.ensure_index()


def test_encuentra_por_tema():
    hits = search.hybrid("data mesh governance", limit=5)

    assert {"ARC407", "ANT320"} & set(_bases(hits))


def test_encuentra_por_empresa_del_speaker():
    hits = search.hybrid("Nubank", limit=3)

    assert any(p.get("company") == "Nubank" for s in hits for p in s["people"])


def test_ignora_tildes_y_mayusculas():
    assert _bases(search.hybrid("itaú", limit=3)) == _bases(search.hybrid("ITAU", limit=3))


def test_sin_consulta_ni_intereses_devuelve_el_orden_del_catalogo():
    hits = search.hybrid("", limit=10)

    assert _bases(hits) == [s["base"] for s in catalog.all_sessions()[:10]]


def test_los_intereses_suben_las_charlas_de_ese_topico():
    hits = search.hybrid("", limit=5, interests=["Artificial Intelligence"])

    assert all("Artificial Intelligence" in catalog.split_field(s["topic"]) for s in hits)


def test_los_vectores_quedan_guardados_y_no_se_recalculan(monkeypatch):
    with pg.pool().connection() as c:
        stored = c.execute("SELECT count(*) AS n FROM speech_embedding WHERE model = %s", (embeddings.model_name(),)).fetchone()["n"]
    calls = []
    monkeypatch.setattr(embeddings, "embed", lambda texts: calls.append(texts) or embeddings.fake_embed(texts))

    search.ensure_index(force=True)

    assert stored == len(catalog.all_sessions())
    assert calls == []


def test_solo_se_recalcula_la_charla_que_cambio(monkeypatch):
    with pg.pool().connection() as c:
        c.execute("UPDATE speech_embedding SET doc_hash = 'viejo' WHERE id_speech = 'ARC407'")
    calls = []
    monkeypatch.setattr(embeddings, "embed", lambda texts: calls.append(texts) or embeddings.fake_embed(texts))

    search.ensure_index(force=True)

    assert len(calls) == 1 and len(calls[0]) == 1 and "Data mesh at scale" in calls[0][0]


def test_sin_embeddings_igual_busca_por_palabras(monkeypatch):
    monkeypatch.setattr(search, "_vectors", lambda: None)

    hits = search.hybrid("Nubank", limit=3)

    assert any(p.get("company") == "Nubank" for p in hits[0]["people"])


def test_prefilter_usa_la_busqueda_hibrida_y_siempre_devuelve_candidatas():
    con_pedido = search.prefilter({"role": "Arquitecto de datos", "experience": "", "interests": []}, "data mesh governance", limit=20)
    sin_senales = search.prefilter({"role": "", "experience": "", "interests": []}, "", limit=20)

    assert {"ARC407", "ANT320"} & set(_bases(con_pedido))
    assert len(sin_senales) == 20


# --- chat de búsqueda -------------------------------------------------------------
def test_preguntar_requiere_sesion():
    with TestClient(app) as c:
        assert c.post("/api/k/ask", json={"q": "data mesh"}).status_code == 401


def test_preguntar_valida_la_pregunta():
    with TestClient(app) as c:
        H = login_headers(c)

        assert c.post("/api/k/ask", headers=H, json={"q": "a"}).status_code == 422
        assert c.post("/api/k/ask", headers=H, json={"q": "x" * 600}).status_code == 422


def test_preguntar_responde_citando_charlas_reales():
    with TestClient(app) as c:
        H = login_headers(c)

        r = c.post("/api/k/ask", headers=H, json={"q": "¿qué charlas hay sobre data mesh y gobierno?"})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["answer"]
        assert body["cited"] and all(catalog.get_session(b) for b in body["cited"])
        assert [s["base"] for s in body["sessions"]][: len(body["cited"])] == body["cited"]
        assert all(s["code"] for s in body["sessions"])


def test_preguntar_ignora_codigos_inventados(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "Mirá [NOEXISTE1] y también [ARC407].")
    with TestClient(app) as c:
        H = login_headers(c)

        body = c.post("/api/k/ask", headers=H, json={"q": "data mesh at scale experian"}).json()

        assert body["cited"] == ["ARC407"]


def test_preguntar_con_el_llm_caido_da_un_error_claro(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("timeout")

    monkeypatch.setattr(llm, "complete", boom)
    with TestClient(app) as c:
        H = login_headers(c)

        r = c.post("/api/k/ask", headers=H, json={"q": "data mesh"})

        assert r.status_code == 502
        assert "timeout" not in r.json()["detail"]

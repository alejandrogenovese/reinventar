"""Grabación enganchada a la charla real: elegirla del catálogo, contexto en el resumen y vínculo en ambos sentidos."""
from fastapi.testclient import TestClient

from app import db, llm, pipeline, prompts, talks
from app.main import app
from tests.conftest import login_headers


def _pick(c, H, q):
    r = c.get("/api/k/talks/pick", headers=H, params={"q": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_elegir_charla_requiere_sesion_y_largo_minimo():
    with TestClient(app) as c:
        assert c.get("/api/k/talks/pick", params={"q": "ARC407"}).status_code == 401
        assert c.get("/api/k/talks/pick", headers=login_headers(c), params={"q": "a"}).status_code == 422


def test_elegir_charla_por_codigo_aunque_venga_en_minusculas():
    with TestClient(app) as c:
        rows = _pick(c, login_headers(c), "arc407")

        assert rows[0]["code"] == "ARC407"
        assert rows[0]["title"].startswith("Data mesh at scale")
        assert rows[0]["recording_kind"] == "Breakout"


def test_elegir_charla_por_titulo():
    with TestClient(app) as c:
        rows = _pick(c, login_headers(c), "data mesh at scale")

        assert "ARC407" in {r["base"] for r in rows}
        assert len(rows) <= talks.PICK_LIMIT


def test_tipo_de_grabacion_segun_el_tipo_de_charla():
    assert talks.recording_kind("Keynote") == "Keynote"
    assert talks.recording_kind("Chalk talk") == "Chalk talk"
    assert talks.recording_kind("Builders' session") == "Workshop"
    assert talks.recording_kind("Breakout session") == "Breakout"
    assert talks.recording_kind(None) == "Breakout"


def test_contexto_oficial_de_la_charla():
    context = talks.context("ARC407")

    assert "Data mesh at scale" in context
    assert "Mohammed Ali Syed" in context and "Experian" in context
    assert talks.context("NOEXISTE") == "" and talks.context(None) == ""


def test_el_resumen_y_la_traduccion_reciben_el_contexto_de_la_charla(monkeypatch):
    s = db.create_session("Data mesh", "Breakout", code="ARC407")
    db.replace_blocks(s["id"], [{"start": 0, "end": 5, "en": "Welcome to data mesh at Experian."}])
    calls = []
    real = llm.complete
    monkeypatch.setattr(llm, "complete", lambda model, system, user, *a: calls.append((system, user)) or real(model, system, user, *a))

    pipeline.process(s["id"])

    translate_user = next(u for sy, u in calls if sy == prompts.TRANSLATE_SYSTEM)
    summary_user = next(u for sy, u in calls if sy == prompts.SUMMARY_SYSTEM)
    assert "Mohammed Ali Syed" in translate_user
    assert "Contexto oficial" in summary_user and "Experian" in summary_user
    assert db.get_session(s["id"])["status"] == "ready"


def test_sin_codigo_el_resumen_sale_igual(monkeypatch):
    s = db.create_session("Charla de pasillo", "Breakout")
    db.replace_blocks(s["id"], [{"start": 0, "end": 5, "en": "Hello."}])

    pipeline.process(s["id"])

    assert db.get_session(s["id"])["status"] == "ready"


def test_el_codigo_se_guarda_normalizado_y_la_grabacion_linkea_a_la_charla():
    with TestClient(app) as c:
        H = login_headers(c)

        s = c.post("/api/sessions", headers=H, json={"title": "Data mesh", "kind": "Breakout", "code": " arc407 "}).json()
        sin = c.post("/api/sessions", headers=H, json={"title": "Libre", "kind": "Breakout", "code": "ZZZ999"}).json()
        detail = c.get(f"/api/sessions/{s['id']}", headers=H).json()

        assert s["code"] == "ARC407"
        assert detail["talk"] == {"base": "ARC407", "title": detail["talk"]["title"]}
        assert detail["talk"]["title"].startswith("Data mesh at scale")
        assert c.get(f"/api/sessions/{sin['id']}", headers=H).json()["talk"] is None


def test_la_ficha_de_la_charla_muestra_sus_grabaciones():
    with TestClient(app) as c:
        H = login_headers(c)
        s = c.post("/api/sessions", headers=H, json={"title": "Mi grabación de ARC407", "kind": "Breakout", "code": "ARC407"}).json()

        body = c.get("/api/k/speech/ARC407", headers=H).json()

        assert s["id"] in {r["id"] for r in body["recordings"]}
        assert {"id", "title", "status", "created_at"} <= set(body["recordings"][0])


def test_si_el_codigo_coincide_no_mezcla_resultados_por_significado():
    with TestClient(app) as c:
        rows = _pick(c, login_headers(c), "ant320")

        assert rows and all(r["base"] == "ANT320" for r in rows)

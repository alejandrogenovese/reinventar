"""Tests del catálogo y del motor de itinerario (LLM_PROVIDER=fake, no consume APIs)."""
import json

from fastapi.testclient import TestClient

from app import catalog, itinerary, llm
from app.main import app

H = {"Authorization": "Bearer secreto"}


def test_catalog_facets_y_busqueda():
    meta = catalog.facets()
    assert meta["topics"] and meta["venues"] and meta["dates"]

    rows = catalog.search(q="lakehouse", limit=5)
    assert rows
    assert all("lakehouse" in r["title"].lower() or "lakehouse" in (r["abstract"] or "").lower() for r in rows)


def test_prefilter_prioriza_intereses_elegidos():
    con_interes = catalog.prefilter({"role": "", "experience": "", "interests": ["Artificial Intelligence"]}, "", limit=10)
    assert con_interes
    assert all("Artificial Intelligence" in c["topic"] for c in con_interes[:3])


def test_flujo_completo_de_itinerario():
    with TestClient(app) as c:
        assert c.get("/api/itinerary").status_code == 401

        profile = {"role": "Arquitecto de datos", "experience": "Senior", "interests": ["Artificial Intelligence"]}
        r = c.post("/api/itinerary/generate", headers=H, json={"profile": profile, "prompt": "gobierno de datos y agentic AI"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["days"] and data["total"] > 0
        first_code = data["days"][0]["sessions"][0]["code"]

        # bloquear una sesión y regenerar: tiene que sobrevivir
        assert c.post(f"/api/itinerary/items/{first_code}/lock", headers=H).status_code == 200
        r2 = c.post("/api/itinerary/generate", headers=H, json={"profile": profile, "prompt": "gobierno de datos y agentic AI"})
        codes_after = {s["code"] for day in r2.json()["days"] for s in day["sessions"]}
        assert first_code in codes_after

        # agregar manualmente otra sesión del catálogo
        other = catalog.search(limit=1, q="s3")[0]["code"]
        assert c.post("/api/itinerary/items", headers=H, json={"code": other}).status_code == 200
        codes = {s["code"] for day in c.get("/api/itinerary", headers=H).json()["days"] for s in day["sessions"]}
        assert other in codes

        # quitarla
        assert c.delete(f"/api/itinerary/items/{other}", headers=H).status_code == 200
        codes = {s["code"] for day in c.get("/api/itinerary", headers=H).json()["days"] for s in day["sessions"]}
        assert other not in codes


def test_ask_llm_reintenta_si_el_primer_intento_no_trae_json(monkeypatch):
    calls = []

    def fake_complete(model, system, user, max_tokens=8000):
        calls.append(user)
        return "" if len(calls) == 1 else json.dumps({"picks": [], "notes": "ok tras reintentar"})

    monkeypatch.setattr(llm, "complete", fake_complete)
    candidate = {"base": "X", "title": "t", "type": "Breakout session", "level": "200", "topic": [], "aoi": [], "abstract": "", "instances": []}
    result = itinerary._ask_llm({"role": "", "experience": "", "interests": []}, "x", [candidate], [])

    assert result["notes"] == "ok tras reintentar"
    assert len(calls) == 2
    assert "no cumplió el formato" in calls[1]


def test_ask_llm_falla_con_mensaje_claro_tras_dos_intentos(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "No puedo ayudar con eso.")
    try:
        itinerary._ask_llm({"role": "", "experience": "", "interests": []}, "x", [], [])
        assert False, "tenía que fallar"
    except ValueError as e:
        assert "2 intentos" in str(e)
        assert "No puedo ayudar" in str(e)


def test_generate_resuelve_choques_de_horario(monkeypatch):
    # Sólo sirven sesiones de una única instancia: si tuvieran una segunda, el motor podría
    # esquivar el choque eligiendo ese otro horario en vez de descartar la sesión.
    rows = catalog.search(limit=5000)
    counts = {}
    for row in rows:
        counts[row["base"]] = counts.get(row["base"], 0) + 1

    seen, clash = {}, None
    for row in rows:
        if counts[row["base"]] != 1:
            continue
        key = (row["day"], row["start"])
        if key in seen and seen[key] != row["base"]:
            clash = (seen[key], row["base"])
            break
        seen[key] = row["base"]
    assert clash, "no se encontró un choque de horario de prueba en el catálogo"

    picks = [{"base": clash[0], "reason": "x"}, {"base": clash[1], "reason": "y"}]
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps({"picks": picks, "notes": "n"}))

    with TestClient(app) as c:
        r = c.post("/api/itinerary/generate", headers=H, json={"profile": {"role": "x", "experience": "", "interests": []}, "prompt": "x"})
        assert r.status_code == 200, r.text
        data = r.json()
        kept = {s["base"] for day in data["days"] for s in day["sessions"]}
        assert len(kept & set(clash)) == 1
        assert any(s["base"] in clash for s in data["skipped"])

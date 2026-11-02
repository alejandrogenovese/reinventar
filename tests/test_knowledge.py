"""Fichas navegables: charla → speaker → empresa, y buscador de personas/empresas."""
from fastapi.testclient import TestClient

from app import pg
from app.main import app
from tests.conftest import login_headers


def _id(sql: str, value: str) -> int:
    with pg.pool().connection() as c:
        return c.execute(sql, (value,)).fetchone()["id"]


def _speaker_id(name: str) -> int:
    return _id("SELECT id_speaker AS id FROM reinvent.speaker WHERE nombre = %s", name)


def _empresa_id(name: str) -> int:
    return _id("SELECT id_empresa AS id FROM reinvent.empresa WHERE nombre = %s", name)


def test_fichas_requieren_sesion():
    with TestClient(app) as c:
        for path in ("/api/k/speech/ARC407", "/api/k/speaker/1", "/api/k/empresa/1", "/api/k/search/entities?q=aws"):
            assert c.get(path).status_code == 401, path


def test_ficha_de_charla_con_horarios_speakers_y_relacionadas():
    with TestClient(app) as c:
        H = login_headers(c)

        r = c.get("/api/k/speech/ARC407", headers=H)
        missing = c.get("/api/k/speech/NOEXISTE", headers=H)

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["base"] == "ARC407" and body["title"].startswith("Data mesh at scale")
        assert [i["code"] for i in body["instances"]] == ["ARC407"]
        assert [p["name"] for p in body["people"]][1] == "Mohammed Ali Syed"
        assert body["related"] and "ARC407" not in {s["base"] for s in body["related"]}
        assert body["recording_kind"] == "Breakout"  # el botón Grabar crea la sesión con este tipo
        assert missing.status_code == 404


def test_ficha_de_speaker_con_perfil_charlas_y_cospeakers():
    with TestClient(app) as c:
        H = login_headers(c)
        speaker_id = _speaker_id("Mohammed Ali Syed")

        r = c.get(f"/api/k/speaker/{speaker_id}", headers=H)
        missing = c.get("/api/k/speaker/999999999", headers=H)

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "Mohammed Ali Syed"
        assert body["profile"]["title"] == "Data Engineering Director"
        assert body["profile"]["experience"] and body["profile"]["education"]
        assert body["company"]["name"] == "Experian"
        assert "ARC407" in {s["base"] for s in body["talks"]}
        assert "Romi Patel" in {p["name"] for p in body["co_speakers"]}
        assert missing.status_code == 404


def test_ficha_de_empresa_con_gente_y_charlas():
    with TestClient(app) as c:
        H = login_headers(c)

        experian = c.get(f"/api/k/empresa/{_empresa_id('Experian')}", headers=H).json()
        aws = c.get(f"/api/k/empresa/{_empresa_id('AWS')}", headers=H).json()
        missing = c.get("/api/k/empresa/999999999", headers=H)

        assert (experian["name"], experian["sector"], experian["industry"]) == ("Experian", "Tecnología", "Información y analítica de negocio")
        assert "Mohammed Ali Syed" in {p["name"] for p in experian["people"]}
        assert "ARC407" in {s["base"] for s in experian["talks"]}
        assert experian["talks_total"] == len(experian["talks"])
        assert aws["talks_total"] > len(aws["talks"]) and len(aws["talks"]) <= 50
        assert missing.status_code == 404


def test_buscador_de_personas_y_empresas():
    with TestClient(app) as c:
        H = login_headers(c)

        empresas = c.get("/api/k/search/entities?q=nuban", headers=H).json()
        personas = c.get("/api/k/search/entities?q=mohammed ali", headers=H).json()
        corta = c.get("/api/k/search/entities?q=a", headers=H)

        assert "Nubank" in {e["name"] for e in empresas["companies"]}
        assert "Mohammed Ali Syed" in {p["name"] for p in personas["speakers"]}
        assert all("talks" in p for p in personas["speakers"])
        assert corta.status_code == 422

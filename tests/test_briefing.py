"""Briefing para conversar con un speaker o una empresa: datos del catálogo + perfil del usuario + grabaciones, con caché."""
import json
import uuid

from fastapi.testclient import TestClient

from app import briefing, db, llm, passwords, pg, prompts
from app.main import app
from tests.conftest import login_headers

FAKE = {
    "quien": "Director de Data Engineering en Experian.",
    "empresa_y_aws": "Experian usa AWS para su data mesh.",
    "en_reinvent": "Presenta [ARC407] sobre data mesh a escala.",
    "temas": [{"tema": "Data contracts", "por_que": "Lo estás llevando al banco."}] * 3,
    "preguntas": ["¿Cómo gobiernan los dominios?"],
    "cuidado": "",
}


def _id(sql: str, value: str) -> int:
    with pg.pool().connection() as c:
        return c.execute(sql, (value,)).fetchone()["id"]


def _speaker_id(name="Mohammed Ali Syed") -> int:
    return _id("SELECT id_speaker AS id FROM reinvent.speaker WHERE nombre = %s", name)


def _empresa_id(name="Experian") -> int:
    return _id("SELECT id_empresa AS id FROM reinvent.empresa WHERE nombre = %s", name)


def _new_user(c):
    """Usuario propio: la caché es por usuario y otros tests no la tienen que pisar."""
    username = f"brief_{uuid.uuid4().hex[:6]}"
    salt, password_hash = passwords.hash_password("brief12345")
    db.create_user(username, salt, password_hash, must_change_password=False)
    return username, login_headers(c, username, "brief12345")


def _recording_llm(monkeypatch, response=None):
    calls = []

    def fake(model, system, user, *a, **k):
        calls.append((system, user))
        return json.dumps(response or FAKE)

    monkeypatch.setattr(llm, "complete", fake)
    return calls


def test_briefing_requiere_sesion():
    with TestClient(app) as c:
        assert c.post("/api/k/briefing", json={"kind": "speaker", "id": 1}).status_code == 401


def test_briefing_valida_tipo_y_existencia():
    with TestClient(app) as c:
        H = login_headers(c)

        assert c.post("/api/k/briefing", headers=H, json={"kind": "planeta", "id": 1}).status_code == 422
        assert c.post("/api/k/briefing", headers=H, json={"kind": "speaker", "id": 999999999}).status_code == 404


def test_briefing_de_speaker_cruza_su_perfil_con_el_del_usuario(monkeypatch):
    calls = _recording_llm(monkeypatch)
    with TestClient(app) as c:
        username, H = _new_user(c)
        db.save_profile(username, "Arquitecto de datos en un banco", "Senior", ["Analytics"], "data mesh")

        r = c.post("/api/k/briefing", headers=H, json={"kind": "speaker", "id": _speaker_id()})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["briefing"]["temas"] and body["cached"] is False
        system, user = calls[0]
        assert system == prompts.BRIEFING_SYSTEM
        assert "Mohammed Ali Syed" in user and "Experian" in user and "ARC407" in user
        assert "Arquitecto de datos en un banco" in user


def test_briefing_queda_en_cache_por_usuario_y_se_puede_regenerar(monkeypatch):
    calls = _recording_llm(monkeypatch)
    with TestClient(app) as c:
        _, H = _new_user(c)
        _, otro = _new_user(c)
        body = {"kind": "speaker", "id": _speaker_id()}

        first = c.post("/api/k/briefing", headers=H, json=body).json()
        second = c.post("/api/k/briefing", headers=H, json=body).json()
        de_otro = c.post("/api/k/briefing", headers=otro, json=body).json()
        regenerado = c.post("/api/k/briefing", headers=H, json={**body, "refresh": True}).json()

        assert (first["cached"], second["cached"], de_otro["cached"], regenerado["cached"]) == (False, True, False, False)
        assert second["briefing"] == first["briefing"]
        assert len(calls) == 3


def test_si_cambia_el_perfil_del_usuario_se_regenera(monkeypatch):
    calls = _recording_llm(monkeypatch)
    with TestClient(app) as c:
        username, H = _new_user(c)
        body = {"kind": "speaker", "id": _speaker_id()}

        c.post("/api/k/briefing", headers=H, json=body)
        db.save_profile(username, "CTO", "", [], "")
        again = c.post("/api/k/briefing", headers=H, json=body).json()

        assert again["cached"] is False and len(calls) == 2


def test_briefing_de_empresa(monkeypatch):
    calls = _recording_llm(monkeypatch)
    with TestClient(app) as c:
        _, H = _new_user(c)

        r = c.post("/api/k/briefing", headers=H, json={"kind": "empresa", "id": _empresa_id()})

        assert r.status_code == 200, r.text
        assert "Experian" in calls[0][1] and "Mohammed Ali Syed" in calls[0][1]


def test_briefing_usa_el_resumen_de_tus_grabaciones_de_sus_charlas(monkeypatch):
    calls = _recording_llm(monkeypatch)
    s = db.create_session("ARC407 grabada", "Breakout", code="ARC407")
    db.update_session(s["id"], status="ready", summary={"tldr": "Contaron cómo federan dominios con Lake Formation."})
    with TestClient(app) as c:
        _, H = _new_user(c)

        c.post("/api/k/briefing", headers=H, json={"kind": "speaker", "id": _speaker_id()})

        assert "federan dominios con Lake Formation" in calls[0][1]


def test_briefing_con_el_llm_caido_o_respuesta_invalida_da_502(monkeypatch):
    with TestClient(app) as c:
        _, H = _new_user(c)
        body = {"kind": "speaker", "id": _speaker_id()}

        monkeypatch.setattr(llm, "complete", lambda *a, **k: "no es json")
        invalida = c.post("/api/k/briefing", headers=H, json=body)

        def boom(*a, **k):
            raise RuntimeError("timeout secreto")

        monkeypatch.setattr(llm, "complete", boom)
        caido = c.post("/api/k/briefing", headers=H, json=body)

        assert invalida.status_code == 502 and caido.status_code == 502
        assert "secreto" not in caido.json()["detail"]


def test_tipos_de_briefing():
    assert set(briefing.KINDS) == {"speaker", "empresa"}

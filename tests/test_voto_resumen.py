"""👍/👎 del resumen de una grabación: el voto en la base, el score en Langfuse y la pantalla. Corre en CI (sin APIs)."""
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, db, langfuse_scores, trazas, voto_resumen_api
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

RESUMEN = {"tldr": "Iceberg en S3 Tables", "key_points": ["uno"]}


@pytest.fixture
def scores(monkeypatch):
    """Lo que se mandaría a Langfuse: ("enviar", trace_id, nombre, valor, id_score) o ("borrar", id_score)."""
    vistos = []
    monkeypatch.setattr(langfuse_scores, "enviar", lambda trace_id, nombre, valor, comentario=None, id_score=None:
                        vistos.append(("enviar", trace_id, nombre, valor, id_score)))
    monkeypatch.setattr(langfuse_scores, "borrar", lambda id_score: vistos.append(("borrar", id_score)))
    return vistos


@pytest.fixture
def cli():
    with TestClient(app) as c:
        c.H = login_headers(c)
        c.H2 = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        c.sid = db.create_session("Lakehouse con Iceberg", "Chalk talk", "ANT301", created_by=TEST_USER)["id"]
        db.update_session(c.sid, status="ready", summary=RESUMEN)
        yield c
        db.delete_session(c.sid)


def test_votar_guarda_el_voto_y_lo_manda_a_langfuse(cli, scores):
    r = cli.put(f"/api/sessions/{cli.sid}/voto", headers=cli.H, json={"util": True})
    assert r.status_code == 200, r.text
    assert r.json() == {"si": 1, "no": 0, "mio": True}
    assert scores == [("enviar", trazas.id_grabacion(cli.sid), "util", 1.0,
                       voto_resumen_api.id_score(cli.sid, TEST_USER))]

    otro = cli.get(f"/api/sessions/{cli.sid}", headers=cli.H2).json()["voto"]
    assert otro == {"si": 1, "no": 0, "mio": None}  # el otro ve el conteo, no qué votó cada uno


def test_cambiar_el_voto_lo_pisa_y_retirarlo_borra_el_score(cli, scores):
    cli.put(f"/api/sessions/{cli.sid}/voto", headers=cli.H, json={"util": True})
    r = cli.put(f"/api/sessions/{cli.sid}/voto", headers=cli.H, json={"util": False})
    assert r.json() == {"si": 0, "no": 1, "mio": False}
    assert scores[-1][3] == 0.0 and scores[-1][4] == scores[0][4]  # mismo id: Langfuse pisa el score anterior

    r = cli.delete(f"/api/sessions/{cli.sid}/voto", headers=cli.H)
    assert r.json() == {"si": 0, "no": 0, "mio": None}
    assert scores[-1] == ("borrar", voto_resumen_api.id_score(cli.sid, TEST_USER))


def test_el_id_del_score_es_uno_por_persona_y_no_lleva_el_usuario():
    a, b = voto_resumen_api.id_score("s1", "ana"), voto_resumen_api.id_score("s1", "beto")
    assert a != b and "ana" not in a and a.startswith(trazas.id_grabacion("s1"))


def test_sin_resumen_no_se_vota_y_valida_el_cuerpo(cli, scores):
    db.update_session(cli.sid, status="transcribing", summary=None)
    assert cli.put(f"/api/sessions/{cli.sid}/voto", headers=cli.H, json={"util": True}).status_code == 409
    assert cli.put("/api/sessions/noexiste/voto", headers=cli.H, json={"util": True}).status_code == 404
    db.update_session(cli.sid, status="ready", summary=RESUMEN)
    assert cli.put(f"/api/sessions/{cli.sid}/voto", headers=cli.H, json={"util": "quizás"}).status_code == 422
    assert cli.put(f"/api/sessions/{cli.sid}/voto", headers=cli.H, json={"util": True, "x": 1}).status_code == 422
    assert cli.put(f"/api/sessions/{cli.sid}/voto", json={"util": True}).status_code == 401
    assert scores == []


def test_borrar_la_grabacion_borra_sus_votos(cli, scores):
    cli.put(f"/api/sessions/{cli.sid}/voto", headers=cli.H, json={"util": True})
    db.delete_session(cli.sid)
    assert db.votos_resumen(cli.sid, TEST_USER) == {"si": 0, "no": 0, "mio": None}


def test_borrar_el_score_en_langfuse_usa_el_id_y_no_rompe(monkeypatch):
    monkeypatch.setattr(config, "LANGFUSE_PUBLIC_KEY", "pk-lf-prueba")
    monkeypatch.setattr(config, "LANGFUSE_SECRET_KEY", "sk-lf-prueba")
    monkeypatch.setattr(config, "LANGFUSE_HOST", "https://langfuse.prueba/")
    pedidos = []

    def delete(url, auth, timeout):
        pedidos.append(url)
        raise httpx.ConnectError("caído")

    monkeypatch.setattr(langfuse_scores.httpx, "delete", delete)
    langfuse_scores.borrar("t1-util-abc").join()
    assert pedidos == ["https://langfuse.prueba/api/public/scores/t1-util-abc"]


def test_el_detalle_muestra_los_botones_debajo_del_resumen():
    js = (Path(__file__).resolve().parent.parent / "web" / "js" / "detail.js").read_text()
    assert "VotoResumen(id, s.voto)" in js and "¿Te sirvió este resumen?" in js


def test_el_score_es_el_que_muestra_el_tablero_de_llm():
    from app import langfuse_metricas
    assert voto_resumen_api.NOMBRE_SCORE in langfuse_metricas.SCORES

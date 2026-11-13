"""Audio sin voz: Whisper no devuelve vacío, inventa "Thank you.". Se descarta lo inventado, la grabación avisa que no
se escuchó voz y la pantalla de grabación avisa si no llega sonido al micrófono. No llama a ninguna API."""
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import audio, config, db, pipeline, stt
from app.main import app
from tests.conftest import login_headers

JS_APP = (Path(__file__).resolve().parent.parent / "web" / "js" / "app.js").read_text()
STYLES = (Path(__file__).resolve().parent.parent / "web" / "styles.css").read_text()


# ---------- es_silencio ----------

@pytest.mark.parametrize("texto", ["Thank you.", " thank you!", "Thanks for watching!", "you", "Bye.",
                                   "Gracias.", "Subtítulos realizados por la comunidad de Amara.org"])
def test_las_frases_que_whisper_inventa_sobre_el_silencio(texto):
    assert stt.es_silencio({"text": texto})


def test_la_regla_de_whisper_mucha_no_habla_y_poca_confianza():
    assert stt.es_silencio({"text": "So the", "no_speech_prob": 0.9, "avg_logprob": -1.4})
    assert not stt.es_silencio({"text": "So the", "no_speech_prob": 0.9, "avg_logprob": -0.3})  # confiado: es voz
    assert not stt.es_silencio({"text": "So the", "no_speech_prob": 0.1, "avg_logprob": -1.4})


def test_el_habla_real_no_se_descarta():
    assert not stt.es_silencio({"text": "Thank you all for coming to this session on Iceberg.",
                                "no_speech_prob": 0.01, "avg_logprob": -0.2})
    assert not stt.es_silencio({"text": "Today we launch S3 Tables."})  # sin métricas (otros proveedores)


# ---------- transcribe ----------

@pytest.fixture
def gateway(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STT_PROVIDER", "litellm")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://litellm.railway.internal:4000")
    monkeypatch.setattr(config, "LLM_API_KEY", "clave-de-prueba")
    respuesta = {}
    monkeypatch.setattr(stt.httpx, "post", lambda *a, **k: httpx.Response(200, json=respuesta))
    p = tmp_path / "a.ogg"
    p.write_bytes(b"audio")
    return respuesta, p


def test_transcribe_descarta_lo_inventado_y_deja_la_voz(gateway):
    respuesta, path = gateway
    respuesta["segments"] = [
        {"start": 0, "end": 4, "text": " Welcome to re:Invent.", "no_speech_prob": 0.02, "avg_logprob": -0.2},
        {"start": 4, "end": 30, "text": " Thank you.", "no_speech_prob": 0.8, "avg_logprob": -0.9},
    ]

    assert [s["text"] for s in stt.transcribe(path, 0)] == ["Welcome to re:Invent."]


def test_un_audio_en_silencio_da_cero_segmentos(gateway):
    respuesta, path = gateway
    respuesta.update(text=" Thank you.", duration=90.0)  # sin segmentos: un solo bloque

    assert stt.transcribe(path, 0) == []


# ---------- la grabación ----------

def test_una_grabacion_sin_voz_avisa_que_no_se_escucho(monkeypatch, tmp_path):
    db.init()
    s = db.create_session("Charla muda", "Breakout")
    pedazo = tmp_path / "p.ogg"
    pedazo.write_bytes(b"audio")
    monkeypatch.setattr(db, "chunk_index", lambda sid: {0: 1})
    monkeypatch.setattr(audio, "assemble", lambda sid, parts: pedazo)
    monkeypatch.setattr(audio, "duration", lambda path: 90.0)
    monkeypatch.setattr(audio, "split", lambda path, secs: [(0.0, pedazo)])
    monkeypatch.setattr(stt, "_fake", lambda path: [{"start": 0.0, "end": 90.0, "text": "Thank you."}])

    with pytest.raises(RuntimeError, match="No se escuchó voz"):
        pipeline.process(s["id"])


def test_la_voz_de_la_entrevista_en_silencio_pide_repetir(monkeypatch):
    monkeypatch.setattr(stt, "_fake", lambda path: [{"start": 0.0, "end": 3.0, "text": "Gracias."}])

    with TestClient(app) as client:
        headers = login_headers(client)
        r = client.post("/api/itinerary/interview/voz", headers={**headers, "Content-Type": "audio/webm"},
                        content=b"audio")

    assert r.status_code == 422
    assert "No se escuchó voz" in r.json()["detail"]


# ---------- la pantalla de grabación ----------

def test_grabando_sin_sonido_aparece_un_aviso_visible():
    assert re.search(r"const SILENCE_WARN_MS = \d+", JS_APP)
    assert "METER_SILENT" in JS_APP and "No llega sonido al micrófono" in JS_APP
    assert 'class: "notice warn"' in JS_APP
    assert ".notice.warn" in STYLES and ".notice[hidden]" in STYLES

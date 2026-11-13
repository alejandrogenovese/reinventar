"""STT por el gateway LiteLLM: cada uso (charlas, voz) va a su alias, con tag y usuario, y se leen los segmentos.
No llama a ninguna API (corre en CI)."""
import json
from pathlib import Path

import httpx
import pytest
import yaml

from app import config, healthcheck, llm_router, stt
from app.llm_router import UsoSTT

LITELLM_CONFIG = Path(__file__).resolve().parent.parent / "infra" / "litellm" / "config.yaml"
VERBOSE = {"text": "hola mundo", "duration": 4.0,
           "segments": [{"start": 0.0, "end": 2.0, "text": " hola"}, {"start": 2.0, "end": 4.0, "text": " mundo"}]}


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setattr(config, "STT_PROVIDER", "litellm")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://litellm.railway.internal:4000")
    monkeypatch.setattr(config, "LLM_API_KEY", "clave-de-prueba")
    pedidos = []

    def post(url, headers, data, files, timeout):
        pedidos.append((url, headers, data))
        return httpx.Response(200, json=VERBOSE)

    monkeypatch.setattr(stt.httpx, "post", post)
    return pedidos


@pytest.fixture
def audio(tmp_path):
    p = tmp_path / "a.ogg"
    p.write_bytes(b"audio")
    return p


def test_cada_uso_tiene_su_alias_en_la_config_por_groq():
    modelos = {m["model_name"]: m for m in yaml.safe_load(LITELLM_CONFIG.read_text())["model_list"]}

    for uso in UsoSTT:
        m = modelos[llm_router.alias_stt(uso)]
        # El completo, no el turbo: el turbo se equivoca más con nombres propios (Neptune, lakehouse).
        assert m["litellm_params"]["model"] == "groq/whisper-large-v3"
        assert m["litellm_params"]["api_key"] == "os.environ/GROQ_API_KEY"
        assert m["model_info"]["mode"] == "audio_transcription"
        assert m["litellm_params"]["input_cost_per_second"] > 0  # si no, el gasto del STT figura en $0


def test_las_charlas_van_a_su_alias_con_tag_usuario_y_segmentos(gateway, audio):
    with llm_router.como_usuario("ale"):
        segs = stt.transcribe(audio, 60)

    url, headers, data = gateway[0]
    assert url == "http://litellm.railway.internal:4000/audio/transcriptions"
    assert headers["Authorization"] == "Bearer clave-de-prueba"
    assert (data["model"], data["language"], data["response_format"], data["user"]) == ("stt-charlas", "en", "verbose_json", "ale")
    meta = json.loads(data["metadata"])
    assert meta["tags"][0] == "stt-charlas" and meta["trace_user_id"] == "ale"
    assert segs == [{"start": 60.0, "end": 62.0, "text": "hola"}, {"start": 62.0, "end": 64.0, "text": "mundo"}]


def test_la_voz_de_la_entrevista_usa_su_alias_en_castellano(gateway, audio):
    stt.transcribe(audio, 0, language="es", uso=UsoSTT.VOZ)

    _, _, data = gateway[0]
    assert (data["model"], data["language"]) == ("stt-voz", "es")
    assert "user" not in data  # sin usuario en el contexto (p. ej. un proceso de fondo), no se manda


def test_directo_sigue_usando_el_modelo_de_siempre(monkeypatch):
    monkeypatch.delenv("LLM_RUTA_STT_CHARLAS", raising=False)
    assert llm_router.modelo_stt(UsoSTT.CHARLAS, "openai") == config.STT_MODEL
    monkeypatch.setenv("LLM_RUTA_STT_CHARLAS", "stt-charlas-scribe")
    assert llm_router.modelo_stt(UsoSTT.CHARLAS, "litellm") == "stt-charlas-scribe"


def test_un_error_del_gateway_se_informa(gateway, audio, monkeypatch):
    monkeypatch.setattr(stt.httpx, "post", lambda *a, **k: httpx.Response(400, text="modelo inexistente"))

    with pytest.raises(RuntimeError, match="STT 400"):
        stt.transcribe(audio, 0)


def test_el_chequeo_del_stt_mira_el_gateway(monkeypatch):
    monkeypatch.setattr(config, "STT_PROVIDER", "litellm")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setattr(config, "LLM_API_KEY", "k")
    monkeypatch.setattr(healthcheck.httpx, "get", lambda *a, **k: httpx.Response(200, json={}))
    assert "responde" in healthcheck._stt()

    monkeypatch.setattr(config, "LLM_API_KEY", None)
    with pytest.raises(AssertionError, match="sin LLM_BASE_URL o LLM_API_KEY"):
        healthcheck._stt()


def test_la_grabacion_se_procesa_a_nombre_de_quien_la_encolo(monkeypatch):
    from app import db, pipeline

    vistos, cola = [], []
    monkeypatch.setattr(db, "update_session", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_q", type("Cola", (), {"put": lambda self, t: cola.append(t)})())
    monkeypatch.setattr(pipeline, "process", lambda sid: vistos.append((sid, llm_router.usuario_actual())))

    with llm_router.como_usuario("ale"):
        pipeline.enqueue("s1")
    pipeline._procesar(*cola[0])  # fuera del pedido: el usuario viaja en la cola

    assert vistos == [("s1", "ale")] and llm_router.usuario_actual() is None


@pytest.mark.parametrize("uso, palabras", [
    (UsoSTT.CHARLAS, ["Trainium", "SageMaker", "Bedrock", "lakehouse"]),
    (UsoSTT.VOZ, ["lakehouse", "Neptune", "Redshift", "Teradata", "disponibilizar"]),
])
def test_cada_uso_le_pasa_su_vocabulario_al_stt(gateway, audio, uso, palabras):
    stt.transcribe(audio, 0, uso=uso)

    prompt = gateway[0][2]["prompt"]
    assert all(p in prompt for p in palabras)
    assert len(prompt) <= stt.LARGO_MAXIMO_VOCABULARIO  # Whisper solo mira los últimos ~224 tokens del prompt


def test_directo_tambien_pasa_el_vocabulario(monkeypatch, audio):
    pedidos = []
    monkeypatch.setattr(config, "STT_PROVIDER", "openai")
    monkeypatch.setattr(config, "STT_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(config, "STT_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(stt.httpx, "post", lambda url, headers, data, files, timeout: pedidos.append(data) or httpx.Response(200, json=VERBOSE))

    stt.transcribe(audio, 0, language="es", uso=UsoSTT.VOZ)

    assert pedidos[0]["prompt"] == stt.VOCABULARIO[UsoSTT.VOZ]

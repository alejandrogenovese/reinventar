"""El userId de Langfuse (trace_user_id) en todos los caminos que llaman al LLM o al STT: con una persona detrás del
pedido va su username; en los trabajos sin persona, un id fijo «sistema:<trabajo>» para poder filtrarlos.
No llama a ninguna API: el gateway es un httpx falso y el resto va en modo fake."""
import json
import queue

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, eventos_auto, healthcheck, llm, llm_router, lotes_llm, pipeline, sandbox, search, stt, trazas
from app.llm_router import Tarea
from tests.conftest import login_headers


@pytest.fixture
def gateway_llm(monkeypatch):
    """LLM por el gateway: devuelve el cuerpo completo de cada pedido."""
    pedidos = []

    def post(url, headers, json, timeout):
        pedidos.append(json)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(config, "LLM_PROVIDER", "litellm")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setattr(config, "LLM_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(llm.httpx, "post", post)
    return pedidos


@pytest.fixture
def gateway_stt(monkeypatch, tmp_path):
    """STT por el gateway: devuelve (audio, campos del form de cada pedido)."""
    pedidos = []

    def post(url, headers, data, files, timeout):
        pedidos.append(data)
        return httpx.Response(200, json={"segments": [{"start": 0, "end": 1, "text": "hola"}]})

    monkeypatch.setattr(config, "STT_PROVIDER", "litellm")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setattr(config, "LLM_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(stt.httpx, "post", post)
    audio = tmp_path / "a.ogg"
    audio.write_bytes(b"audio")
    return audio, pedidos


# ---------- el helper ----------

def test_como_sistema_deja_un_usuario_reconocible_y_lo_suelta_al_salir():
    with llm_router.como_sistema("eventos-auto"):
        assert llm_router.usuario_actual() == "sistema:eventos-auto"
    assert llm_router.usuario_actual() is None


# ---------- formato que espera LiteLLM ----------

def test_el_llm_manda_el_mismo_usuario_en_trace_user_id_y_en_user(gateway_llm):
    with llm_router.como_usuario("ale"):
        llm.complete(Tarea.CHAT, "sistema", "pregunta", 100)

    cuerpo = gateway_llm[0]
    assert cuerpo["metadata"]["trace_user_id"] == "ale"
    assert cuerpo["user"] == "ale"


def test_el_stt_manda_el_mismo_usuario_en_trace_user_id_y_en_user(gateway_stt):
    audio, pedidos = gateway_stt
    with llm_router.como_usuario("ale"):
        stt.transcribe(audio, 0)

    assert json.loads(pedidos[0]["metadata"])["trace_user_id"] == "ale"
    assert pedidos[0]["user"] == "ale"


def test_sin_usuario_no_se_manda_ni_trace_user_id_ni_user(gateway_llm):
    llm.complete(Tarea.CHAT, "sistema", "pregunta", 100)

    assert "trace_user_id" not in gateway_llm[0]["metadata"]
    assert "user" not in gateway_llm[0]


# ---------- trabajos sin persona ----------

def test_el_healthcheck_va_a_nombre_de_sistema_healthcheck(monkeypatch):
    vistos = []
    monkeypatch.setattr(healthcheck.llm, "complete", lambda *a: vistos.append(llm_router.usuario_actual()))

    healthcheck._llm()

    assert vistos == ["sistema:healthcheck"]


def test_la_revision_de_eventos_va_a_nombre_de_sistema_eventos_auto(monkeypatch):
    vistos = []
    monkeypatch.setattr(eventos_auto, "revisar", lambda **kw: vistos.append(llm_router.usuario_actual()) or {})
    monkeypatch.setattr(eventos_auto.events, "load", lambda: None)
    monkeypatch.setattr(eventos_auto.shows, "load", lambda: None)

    eventos_auto.revisar_ahora()

    assert vistos == ["sistema:eventos-auto"]
    assert llm_router.usuario_actual() is None


def test_el_armado_de_temas_va_a_nombre_de_sistema_temas(monkeypatch):
    from app import clusters

    vistos = []
    monkeypatch.setattr(search, "ensure_index", lambda: None)
    monkeypatch.setattr(clusters, "ensure", lambda: vistos.append(llm_router.usuario_actual()))
    monkeypatch.setattr(search.embeddings, "devolver_memoria", lambda: None)

    search._warm()

    assert vistos == ["sistema:temas"]


def test_los_lotes_en_paralelo_conservan_el_usuario_y_la_traza():
    vistos = []

    def llamar(lote):
        vistos.append((llm_router.usuario_actual(), trazas.actual()))

    traza = trazas.Traza(nombre="x")
    with llm_router.como_sistema("eventos-auto"), trazas.abrir(traza):
        lotes_llm.procesar([[1], [2], [3]], llamar, lambda _l, _r: None, hilos=3, describir=str, avisar=print)

    assert vistos == [("sistema:eventos-auto", traza)] * 3


# ---------- grabaciones ----------

def test_al_arrancar_las_grabaciones_a_medias_vuelven_a_nombre_de_quien_las_grabo(monkeypatch):
    cola = queue.Queue()
    monkeypatch.setattr(pipeline, "_q", cola)
    monkeypatch.setattr(pipeline.db, "sessions_in", lambda estados: ["s1", "s2"])
    monkeypatch.setattr(pipeline.db, "get_session", lambda sid: {"created_by": "ale"} if sid == "s1" else {"created_by": None})

    pipeline.reencolar_pendientes()

    trabajos = [cola.get_nowait() for _ in range(cola.qsize())]
    reales = {sid: usuario for sid, contexto, usuario in trabajos if contexto is None}
    assert reales == {"s1": "ale", "s2": "sistema:pipeline"}


def test_el_reintento_desde_la_api_encola_a_nombre_de_quien_lo_pide(monkeypatch):
    from app.main import app

    cola = []
    with TestClient(app) as client:
        headers = login_headers(client)
        sid = client.post("/api/sessions", json={"title": "Charla", "kind": "Breakout"}, headers=headers).json()["id"]
        monkeypatch.setattr(pipeline, "_q", type("Cola", (), {"put": lambda self, t: cola.append(t)})())

        r = client.post(f"/api/sessions/{sid}/retry", headers=headers)

    assert r.status_code == 200
    assert cola == [(sid, sandbox.actual(), "tester")]

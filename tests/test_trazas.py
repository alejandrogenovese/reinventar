"""Metadata de Langfuse (app/trazas.py): trazas agrupadas por flujo, versión del prompt y de la app, entorno, modo prueba
y privacidad. No llama a ninguna API: el gateway es un httpx falso."""
import hashlib
import json
import re

import httpx
import pytest

from app import __version__, config, healthcheck, llm, llm_router, pipeline, sandbox, stt, trazas
from app.llm_router import Tarea, UsoSTT


def _hoy() -> str:
    return sandbox.ahora().date().isoformat()


@pytest.fixture
def gateway_llm(monkeypatch):
    """LLM por el gateway: devuelve la metadata de cada pedido."""
    pedidos = []

    def post(url, headers, json, timeout):
        pedidos.append(json["metadata"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(config, "LLM_PROVIDER", "litellm")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setattr(config, "LLM_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(llm.httpx, "post", post)
    return pedidos


@pytest.fixture
def gateway_stt(monkeypatch, tmp_path):
    """STT por el gateway: devuelve (archivo de audio, metadatas de cada pedido, deserializadas)."""
    pedidos = []

    def post(url, headers, data, files, timeout):
        pedidos.append(json.loads(data["metadata"]))
        return httpx.Response(200, json={"text": "hola", "duration": 1.0})

    monkeypatch.setattr(config, "STT_PROVIDER", "litellm")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setattr(config, "LLM_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(stt.httpx, "post", post)
    audio = tmp_path / "a.ogg"
    audio.write_bytes(b"audio")
    return audio, pedidos


# ---------- metadata de cada flujo ----------

def test_sin_contexto_cada_llamada_es_su_traza_con_la_sesion_del_dia(gateway_llm):
    with llm_router.como_usuario("ale"):
        llm.complete(Tarea.CHAT, "sistema del chat", "pregunta", 100)
        llm.complete(Tarea.CHAT, "sistema del chat", "otra pregunta", 100)

    a, b = gateway_llm
    assert re.fullmatch(r"[0-9a-f]{32}", a["trace_id"])
    assert a["trace_id"] != b["trace_id"]
    assert a["trace_name"] == "chat"
    assert a["generation_name"] == "chat"
    assert a["session_id"] == f"chat-ale-{_hoy()}"
    assert b["session_id"] == a["session_id"]
    assert a["trace_release"] == __version__
    assert a["version"] == trazas.hash_prompt("sistema del chat")
    assert a["tags"] == ["chat", "dev"]
    assert a["trace_user_id"] == "ale"
    assert "mask_input" not in a
    assert "mask_output" not in a
    assert "trace_metadata" not in a


def test_sin_usuario_la_sesion_es_del_flujo_y_el_dia(gateway_llm):
    llm.complete(Tarea.TEMAS, "s", "u", 10)

    meta = gateway_llm[0]
    assert meta["session_id"] == f"temas-{_hoy()}"
    assert "trace_user_id" not in meta


def test_dentro_de_un_contexto_las_llamadas_comparten_la_traza(gateway_llm):
    with trazas.abrir(trazas.Traza(metadata={"candidatas": 24})) as traza:
        llm.complete(Tarea.CHAT, "s", "u", 10)
        llm.complete(Tarea.CHAT, "s", "u", 10)

    assert [m["trace_id"] for m in gateway_llm] == [traza.trace_id] * 2
    assert gateway_llm[0]["trace_metadata"] == {"candidatas": 24}
    assert trazas.actual() is None


def test_la_entrevista_no_guarda_ni_la_entrada_ni_la_salida(gateway_llm):
    """La salida (repreguntas y ficha) repite lo que contestó la persona: se enmascara igual que la entrada."""
    with llm_router.como_usuario("ale"):
        llm.complete(Tarea.ENTREVISTA, "s", "mis respuestas", 10)

    meta = gateway_llm[0]
    assert meta["mask_input"] is True
    assert meta["mask_output"] is True
    assert meta["session_id"] == f"entrevista-ale-{_hoy()}"


def test_las_razones_no_guardan_ni_la_ficha_ni_la_salida(gateway_llm):
    llm.complete(Tarea.RAZONES, "s", "la ficha", 10)

    assert gateway_llm[0]["mask_input"] is True
    assert gateway_llm[0]["mask_output"] is True


@pytest.mark.parametrize("tarea", [Tarea.CHAT, Tarea.BRIEFING, Tarea.ITINERARIO])
def test_con_la_ficha_no_se_guarda_la_entrada_pero_si_la_salida(gateway_llm, tarea):
    with trazas.abrir(trazas.Traza(con_ficha=True)):
        llm.complete(tarea, "s", "pregunta + ficha", 10)
    llm.complete(tarea, "s", "pregunta sin ficha", 10)

    con_ficha, sin_ficha = gateway_llm
    assert con_ficha["mask_input"] is True
    assert "mask_output" not in con_ficha
    assert "mask_input" not in sin_ficha


def test_la_voz_de_la_entrevista_va_enmascarada_y_en_la_sesion_de_la_entrevista(gateway_stt):
    audio, pedidos = gateway_stt
    with llm_router.como_usuario("ale"):
        stt.transcribe(audio, 0, uso=UsoSTT.VOZ)

    meta = pedidos[0]
    assert meta["mask_output"] is True  # lo sensible es la salida: la respuesta transcripta
    assert meta["mask_input"] is True
    assert meta["trace_name"] == "stt-voz"
    assert meta["tags"][0] == "stt-voz"
    assert meta["session_id"] == f"entrevista-ale-{_hoy()}"
    assert meta["version"] == trazas.hash_prompt(stt.VOCABULARIO[UsoSTT.VOZ])


def test_las_charlas_no_van_enmascaradas(gateway_stt):
    audio, pedidos = gateway_stt
    stt.transcribe(audio, 0)

    assert "mask_input" not in pedidos[0]
    assert "mask_output" not in pedidos[0]


# ---------- versión del prompt ----------

def test_el_hash_cambia_solo_si_cambia_el_prompt():
    mismo_prompt = "prompt v1"
    otra_copia = "".join(["prompt", " v1"])  # mismo texto, otro objeto: el hash depende del contenido

    assert trazas.hash_prompt(mismo_prompt) == trazas.hash_prompt(otra_copia)
    assert trazas.hash_prompt(mismo_prompt) != trazas.hash_prompt("prompt v2")
    assert re.fullmatch(r"[0-9a-f]{8}", trazas.hash_prompt("prompt v1"))


def test_la_version_de_cada_tarea_sale_de_su_prompt_de_sistema(gateway_llm):
    llm.complete(Tarea.CHAT, "prompt A", "u1", 10)
    llm.complete(Tarea.CHAT, "prompt A", "otro pedido", 10)
    llm.complete(Tarea.CHAT, "prompt B", "u1", 10)

    a, a2, b = (m["version"] for m in gateway_llm)
    assert a == a2
    assert a != b


# ---------- entorno y modo prueba ----------

def test_en_produccion_va_el_tag_prod(gateway_llm, monkeypatch):
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "production")
    llm.complete(Tarea.CHAT, "s", "u", 10)

    assert gateway_llm[0]["tags"] == ["chat", "prod"]


def test_en_modo_prueba_va_el_tag_prueba(gateway_llm):
    with sandbox.activar(sandbox.Sandbox(username="ale", llm="real")):
        llm.complete(Tarea.CHAT, "s", "u", 10)

    assert gateway_llm[0]["tags"] == ["chat", "dev", "prueba"]


# ---------- grabaciones: una sola traza ----------

def test_el_trace_id_de_la_grabacion_es_deterministico():
    esperado = hashlib.sha256(b"grabacion-s1").hexdigest()[:32]

    assert trazas.id_grabacion("s1") == esperado
    assert trazas.id_grabacion("s2") != esperado


def test_el_stt_de_una_grabacion_va_a_la_traza_de_la_grabacion(gateway_stt):
    audio, pedidos = gateway_stt
    with trazas.abrir(trazas.de_grabacion("s1", "ARC407", "Breakout")):
        stt.transcribe(audio, 0)

    meta = pedidos[0]
    assert meta["trace_id"] == trazas.id_grabacion("s1")
    assert (meta["trace_name"], meta["session_id"]) == ("grabacion", "grabacion-s1")
    assert meta["trace_metadata"] == {"codigo": "ARC407", "tipo": "Breakout"}
    assert meta["generation_name"] == "stt-charlas"


def test_el_procesamiento_de_la_grabacion_abre_su_traza(monkeypatch):
    vistas = []
    monkeypatch.setattr(pipeline.db, "get_session", lambda sid: {"code": "ARC407", "kind": "Breakout", "title": "x"})
    monkeypatch.setattr(pipeline, "_etapas", lambda sid, s: vistas.append(trazas.actual()))

    pipeline.process("s1")

    assert vistas == [trazas.de_grabacion("s1", "ARC407", "Breakout")]
    assert trazas.actual() is None


# ---------- healthcheck ----------

def test_el_healthcheck_no_se_mezcla_con_el_chat(monkeypatch):
    vistas = []
    monkeypatch.setattr(healthcheck.llm, "complete", lambda tarea, *a: vistas.append(trazas.metadata(tarea.value, "s")))

    healthcheck._llm()

    meta = vistas[0]
    assert meta["trace_name"] == "healthcheck"
    assert meta["session_id"] == "healthcheck"
    assert "prueba" in meta["tags"]

"""Router de tareas del LLM: cada parte de la app pide su tarea; el router decide el modelo (alias de LiteLLM o modelo
directo) y cada llamada va con su tag y su usuario para ver el consumo por parte. No llama a ninguna API (corre en CI)."""
import re
from pathlib import Path

import httpx
import pytest
import yaml

from app import config, llm, llm_router
from app.llm_router import Tarea

ROOT = Path(__file__).resolve().parent.parent
LITELLM_CONFIG = ROOT / "infra" / "litellm" / "config.yaml"


def test_cada_tarea_tiene_su_alias_en_la_config_de_litellm():
    aliases = {m["model_name"] for m in yaml.safe_load(LITELLM_CONFIG.read_text())["model_list"]}

    assert {llm_router.alias(t) for t in Tarea} <= aliases


def test_la_config_de_litellm_no_tiene_secretos():
    texto = LITELLM_CONFIG.read_text()

    assert not re.search(r"sk-[A-Za-z0-9-]{10,}|pk-lf-|sk-lf-", texto)
    assert all(v.startswith("os.environ/") for v in re.findall(r"(?:api_key|master_key|database_url):\s*(\S+)", texto))


def test_ninguna_llamada_pide_un_modelo_suelto():
    # Todas las partes pasan por el router: llm.complete(Tarea.X, …), nunca llm.complete(config.ALGO_MODEL, …).
    fuentes = [*ROOT.joinpath("app").glob("*.py"), *ROOT.joinpath("scripts").glob("*.py")]
    sueltas = [f"{p.name}: {m}" for p in fuentes for m in re.findall(r"(?:llm\.complete|completar)\(\s*config\.\w+", p.read_text())]

    assert sueltas == []


def test_con_litellm_usa_el_alias_y_directo_usa_el_modelo_de_hoy(monkeypatch):
    assert llm_router.modelo(Tarea.RESUMEN, "litellm") == "rx-resumen"
    assert llm_router.modelo(Tarea.RESUMEN, "anthropic") == config.SUMMARY_MODEL
    assert llm_router.modelo(Tarea.FILTROS, "anthropic") == config.ASK_MODEL  # hoy comparte modelo con el chat


def test_se_puede_forzar_el_modelo_de_una_tarea(monkeypatch):
    monkeypatch.setenv("LLM_RUTA_RAZONES", "rx-razones-haiku")

    assert llm_router.modelo(Tarea.RAZONES, "litellm") == "rx-razones-haiku"
    assert llm_router.modelo(Tarea.CHAT, "litellm") == "rx-chat"


def test_el_usuario_viaja_en_el_contexto():
    assert llm_router.usuario_actual() is None
    with llm_router.como_usuario("ale"):
        assert llm_router.usuario_actual() == "ale"
    assert llm_router.usuario_actual() is None


def test_por_litellm_cada_llamada_lleva_su_tag_y_su_usuario(monkeypatch):
    pedidos = []

    def post(url, headers, json, timeout):
        pedidos.append((url, headers, json))
        return httpx.Response(200, json={"choices": [{"message": {"content": "hola"}}]})

    monkeypatch.setattr(config, "LLM_PROVIDER", "litellm")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://litellm.railway.internal:4000/")
    monkeypatch.setattr(config, "LLM_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(llm.httpx, "post", post)

    with llm_router.como_usuario("ale"):
        assert llm.complete(Tarea.RAZONES, "sistema", "pedido", 100) == "hola"

    url, headers, body = pedidos[0]
    assert url == "http://litellm.railway.internal:4000/chat/completions"
    assert headers["Authorization"] == "Bearer clave-de-prueba"
    assert (body["model"], body["user"], body["max_tokens"]) == ("rx-razones", "ale", 100)
    assert body["metadata"]["tags"] == ["razones"]
    assert (body["metadata"]["trace_name"], body["metadata"]["trace_user_id"]) == ("razones", "ale")


def test_por_litellm_un_error_del_gateway_se_informa(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "litellm")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: httpx.Response(429, text="rate limit"))

    with pytest.raises(RuntimeError, match="LLM 429"):
        llm.complete(Tarea.CHAT, "s", "u", 10)


def test_el_pedido_llega_al_llm_a_nombre_del_usuario_del_token(monkeypatch):
    from fastapi.testclient import TestClient

    from app import search
    from app.main import app
    from tests.conftest import TEST_USER, login_headers

    vistos = []
    monkeypatch.setattr(search, "hybrid", lambda q, n: [])
    monkeypatch.setattr(llm, "complete", lambda tarea, *a, **k: vistos.append((tarea, llm_router.usuario_actual())) or "ok")
    with TestClient(app) as c:
        r = c.post("/api/k/ask", headers=login_headers(c), json={"q": "grafos"})

    assert r.status_code == 200
    # Al arrancar, un hilo en segundo plano puede nombrar temas (sin usuario): solo interesa la llamada del chat.
    assert [v for v in vistos if v[0] == Tarea.CHAT] == [(Tarea.CHAT, TEST_USER)]


def test_el_chequeo_avisa_si_el_gateway_no_responde(monkeypatch):
    from app import healthcheck

    monkeypatch.setattr(config, "LLM_PROVIDER", "litellm")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setattr(healthcheck.httpx, "get", lambda *a, **k: httpx.Response(200, json={"status": "ok"}))
    assert "responde" in healthcheck._llm()

    def caido(*a, **k):
        raise httpx.ConnectError("sin red")
    monkeypatch.setattr(healthcheck.httpx, "get", caido)
    with pytest.raises(AssertionError, match="LiteLLM no responde"):
        healthcheck._llm()

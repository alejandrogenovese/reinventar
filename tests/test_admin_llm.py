"""Tablero de LLM del portal de admin (/api/admin/llm) con la API de Langfuse falsa: nunca sale a la red."""
import datetime as dt
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, langfuse_metricas
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

HOST = "https://langfuse.test"
AHORA = dt.datetime.now(dt.timezone.utc)
HOY = AHORA.date().isoformat()


def _filas(query: dict) -> list[dict]:
    """Respuestas con la forma de /api/public/v2/metrics para cada consulta del tablero."""
    dims = [d["field"] for d in query["dimensions"]]
    if query["view"] == "scores-numeric":
        if dims == ["name"]:
            return [{"name": "json_valido", "avg_value": 0.9, "count_count": "10"},
                    {"name": "otro_score", "avg_value": 1, "count_count": "3"}]
        return [{"count_count": "13"}]
    if dims == ["name", "level"]:
        return [{"name": "chat", "level": "DEFAULT", "count_count": "40"},
                {"name": "chat", "level": "ERROR", "count_count": "2"},
                {"name": "traduccion", "level": "ERROR", "count_count": "1"}]
    if dims == ["name"] and query.get("timeDimension"):
        return [{"name": "chat", "time_dimension": f"{HOY}T00:00:00.000Z", "sum_totalCost": "0.5"},
                {"name": "traduccion", "time_dimension": f"{HOY}T00:00:00.000Z", "sum_totalCost": 1.25}]
    if dims == ["name"]:
        return [{"name": "chat", "sum_totalCost": 0.5, "count_count": "42", "p50_latency": 1200.4, "p95_latency": 5300},
                {"name": "traduccion", "sum_totalCost": 1.25, "count_count": "10", "p50_latency": 9000, "p95_latency": 20000}]
    if query["filters"]:  # trazas del mes (observaciones raíz): las consultas por tarea ya respondieron arriba
        return [{"count_count": "300"}]
    return [{"sum_totalCost": "7.5", "count_count": "1000"}]  # mes completo


class FakeLangfuse:
    """Reemplaza httpx.get: registra cada llamada y contesta como Langfuse."""

    def __init__(self, error: Exception | None = None, status: int = 200):
        self.llamadas: list[tuple[str, dict | None, tuple]] = []
        self.error, self.status = error, status

    def __call__(self, url, params=None, auth=None, timeout=None):
        self.llamadas.append((url, params, auth))
        if self.error:
            raise self.error
        req = httpx.Request("GET", url)
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "no"}, request=req)
        if url.endswith("/api/public/projects"):
            return httpx.Response(200, json={"data": [{"id": "proy123", "name": "reinventar"}]}, request=req)
        return httpx.Response(200, json={"data": _filas(json.loads(params["query"]))}, request=req)


@pytest.fixture
def langfuse(monkeypatch):
    monkeypatch.setattr(config, "LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setattr(config, "LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setattr(config, "LANGFUSE_HOST", HOST)
    fake = FakeLangfuse()
    monkeypatch.setattr(langfuse_metricas.httpx, "get", fake)
    langfuse_metricas.limpiar_cache()
    yield fake
    langfuse_metricas.limpiar_cache()


def _admin(c):
    return login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)


def test_tablero_pide_admin(langfuse):
    with TestClient(app) as c:
        assert c.get("/api/admin/llm").status_code == 401
        assert c.get("/api/admin/llm", headers=login_headers(c)).status_code == 403
    assert langfuse.llamadas == []


def test_tablero_arma_costo_demora_errores_scores_y_unidades(langfuse):
    with TestClient(app) as c:
        r = c.get("/api/admin/llm", headers=_admin(c))

    assert r.status_code == 200
    d = r.json()
    assert d["disponible"] is True
    assert d["url"] == f"{HOST}/project/proy123"
    traduccion, chat = d["tareas"]  # ordenadas por costo
    assert traduccion == {"tarea": "traduccion", "costo": 1.25, "llamadas": 10, "p50_ms": 9000, "p95_ms": 20000, "errores": 1}
    assert chat["errores"] == 2 and chat["p50_ms"] == 1200 and chat["llamadas"] == 42
    assert d["costo_semana"] == 1.75 and d["errores_semana"] == 3
    assert len(d["costo_por_dia"]) == 7
    assert d["costo_por_dia"][-1] == {"dia": HOY, "costo": 1.75, "por_tarea": {"chat": 0.5, "traduccion": 1.25}}
    assert all(dia["costo"] == 0 for dia in d["costo_por_dia"][:-1])
    assert d["scores"] == [{"nombre": "json_valido", "promedio": 0.9, "cantidad": 10}]
    assert d["mes"]["costo"] == 7.5
    assert d["mes"]["unidades"] == 1000 + 300 + 13
    assert d["mes"]["unidades_estimadas"] is True
    assert d["mes"]["unidades_cota_superior"] is True
    assert d["mes"]["limite_unidades"] == 50_000


def test_tablero_usa_basic_auth_y_las_claves_no_llegan_al_navegador(langfuse):
    with TestClient(app) as c:
        cuerpo = c.get("/api/admin/llm", headers=_admin(c)).text

    assert {auth for _, _, auth in langfuse.llamadas} == {("pk-lf-test", "sk-lf-test")}
    assert all(url.startswith(HOST) for url, _, _ in langfuse.llamadas)
    assert any(url == f"{HOST}/api/public/v2/metrics" for url, _, _ in langfuse.llamadas)
    assert "pk-lf-test" not in cuerpo and "sk-lf-test" not in cuerpo


def test_tablero_usa_la_cache_y_no_vuelve_a_llamar(langfuse):
    with TestClient(app) as c:
        primero = c.get("/api/admin/llm", headers=_admin(c)).json()
        llamadas = len(langfuse.llamadas)
        segundo = c.get("/api/admin/llm", headers=_admin(c)).json()

    assert llamadas > 0
    assert len(langfuse.llamadas) == llamadas
    assert segundo == primero


def test_tablero_sin_claves_no_esta_disponible(langfuse, monkeypatch):
    monkeypatch.setattr(config, "LANGFUSE_SECRET_KEY", "")
    with TestClient(app) as c:
        d = c.get("/api/admin/llm", headers=_admin(c)).json()

    assert d["disponible"] is False and "claves" in d["motivo"]
    assert langfuse.llamadas == []


@pytest.mark.parametrize("error, motivo", [
    (httpx.ConnectError("sin red"), "conectar"),
    (httpx.ReadTimeout("lento"), "tardó"),
])
def test_tablero_con_error_de_red_no_esta_disponible(langfuse, error, motivo):
    langfuse.error = error
    with TestClient(app) as c:
        d = c.get("/api/admin/llm", headers=_admin(c)).json()

    assert d["disponible"] is False and motivo in d["motivo"]
    assert d["url"] == HOST


def test_tablero_con_claves_rechazadas_lo_dice(langfuse):
    langfuse.status = 401
    with TestClient(app) as c:
        d = c.get("/api/admin/llm", headers=_admin(c)).json()

    assert d["disponible"] is False and "rechazó las claves" in d["motivo"]


def test_consultas_usan_la_api_v2_con_los_ultimos_7_dias():
    qs = langfuse_metricas.consultas(AHORA)

    assert qs["por_dia"]["timeDimension"] == {"granularity": "day"}
    assert {m["aggregation"] for m in qs["por_tarea"]["metrics"] if m["measure"] == "latency"} == {"p50", "p95"}
    desde = dt.datetime.fromisoformat(qs["por_tarea"]["fromTimestamp"].replace("Z", "+00:00"))
    assert (AHORA - desde).days == 7
    assert qs["mes"]["fromTimestamp"].startswith(AHORA.strftime("%Y-%m-01T00:00:00"))


def test_las_llamadas_se_agrupan_por_la_tarea_y_cuentan_solo_generaciones_sin_modo_prueba():
    """Con una traza por grabación, el nombre de la traza ya no es la tarea: la tarea es el nombre de la observación."""
    qs = langfuse_metricas.consultas(AHORA)

    for nombre in ("por_tarea", "niveles", "por_dia"):
        dimensiones = [d["field"] for d in qs[nombre]["dimensions"]]
        assert "traceName" not in dimensiones
        assert dimensiones[0] == "name"
        assert langfuse_metricas.FILTRO_GENERACIONES in qs[nombre]["filters"]
        assert langfuse_metricas.FILTRO_SIN_PRUEBA in qs[nombre]["filters"]
    assert qs["scores"]["filters"] == [langfuse_metricas.FILTRO_SIN_PRUEBA]


def test_el_mes_cuenta_todo_el_trafico_incluido_el_modo_prueba():
    qs = langfuse_metricas.consultas(AHORA)

    assert qs["mes"]["filters"] == []
    assert qs["mes_scores"]["filters"] == []
    assert langfuse_metricas.FILTRO_SIN_PRUEBA not in qs["mes_trazas"]["filters"]


def test_los_filtros_tienen_la_forma_de_la_api_v2():
    generaciones = langfuse_metricas.FILTRO_GENERACIONES
    sin_prueba = langfuse_metricas.FILTRO_SIN_PRUEBA

    assert generaciones == {"column": "type", "operator": "=", "value": "GENERATION", "type": "string"}
    assert sin_prueba == {"column": "tags", "operator": "none of", "value": ["prueba"], "type": "arrayOptions"}

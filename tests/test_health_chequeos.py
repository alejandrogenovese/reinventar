"""/health: los chequeos de monitoreo ("chequeos" y "todo_ok") no cambian el código de estado, que sigue dependiendo
solo de Postgres y disco. Sin red: el gateway LiteLLM se simula y la base también."""
import logging
import threading
import time
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from app import catalog, config, cotizacion, db, estado, healthcheck, pg, pipeline, push, salud
from app.main import app

TODOS = {"pipeline", "push", "catalogo", "revision_catalogo", "revision_eventos", "cotizacion", "llm_gateway",
         "llm_reciente", "grabaciones_error", "disco_libre"}


class _Conexion:
    def execute(self, sql, *args):
        return None


class _Pool:
    def __init__(self, error=None):
        self.error = error

    @contextmanager
    def connection(self, timeout=None):
        if self.error:
            raise self.error
        yield _Conexion()


@pytest.fixture(autouse=True)
def _todo_sano(monkeypatch, tmp_path):
    """Punto de partida: Postgres y disco andan y todos los chequeos dan true. Cada test rompe uno."""
    salud.limpiar_cache()
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pg, "pool", lambda: _Pool())
    monkeypatch.setattr(pipeline, "vivo", lambda: True)
    monkeypatch.setattr(push, "enabled", lambda: False)
    monkeypatch.setattr(catalog, "_sessions", [{"base": "ARC407"}])
    monkeypatch.setattr(config, "EVENTOS_AUTO", False)
    monkeypatch.setattr(cotizacion, "ultima", lambda: None)  # sin historial: la de respaldo
    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(db, "errores_desde", lambda desde: 0)
    monkeypatch.setattr(salud, "uso_disco", lambda ruta: 0.1)  # no depende de cuán lleno esté el disco de la máquina
    estado.reiniciar_fallas_llm()
    yield
    salud.limpiar_cache()
    estado.reiniciar_fallas_llm()


@pytest.fixture
def cliente():
    return TestClient(app)  # sin `with`: no corre el lifespan ni arranca hilos


class _Gateway:
    """Reemplaza httpx.get: cuenta las llamadas y contesta lo pedido (o explota, sin red)."""

    def __init__(self, status=200, error=None):
        self.status, self.error, self.urls, self.timeouts = status, error, [], []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        self.timeouts.append(timeout)
        if self.error:
            raise self.error
        return httpx.Response(self.status, text="I'm alive!")


def _con_litellm(monkeypatch, gateway, base="http://gateway.interno:4000/v1"):
    monkeypatch.setattr(config, "LLM_PROVIDER", "litellm")
    monkeypatch.setattr(config, "LLM_BASE_URL", base)
    monkeypatch.setattr(healthcheck.httpx, "get", gateway)
    return gateway


def test_todo_sano_da_todo_ok_y_cada_chequeo_en_true(cliente):
    r = cliente.get("/health")

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["chequeos"] == dict.fromkeys(TODOS, True)
    assert cuerpo["todo_ok"] is True
    assert cuerpo["pipeline"] is True  # la clave de siempre sigue arriba para el monitor actual


@pytest.mark.parametrize(("chequeo", "romper"), [
    ("pipeline", lambda mp: mp.setattr(pipeline, "vivo", lambda: False)),
    ("catalogo", lambda mp: mp.setattr(catalog, "_sessions", None)),
    ("cotizacion", lambda mp: mp.setattr(cotizacion, "ultima", lambda: 1 / 0)),
    ("revision_catalogo", lambda mp: mp.setattr(config, "EVENTOS_AUTO", True)),
    ("llm_gateway", lambda mp: _con_litellm(mp, _Gateway(status=503))),
    ("llm_reciente", lambda mp: [estado.registrar_falla_llm("real") for _ in range(estado.FALLAS_LLM_PARA_CAIDA)]),
    ("grabaciones_error", lambda mp: mp.setattr(db, "errores_desde", lambda desde: estado.ERRORES_PARA_CAIDA)),
    ("disco_libre", lambda mp: mp.setattr(salud, "uso_disco", lambda ruta: salud.DISCO_USO_MAX)),
])
def test_un_chequeo_en_false_baja_todo_ok_pero_no_el_status(cliente, monkeypatch, chequeo, romper):
    romper(monkeypatch)

    r = cliente.get("/health")

    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["chequeos"][chequeo] is False
    assert r.json()["todo_ok"] is False


def test_postgres_caido_sigue_dando_503_y_todo_ok_false(cliente, monkeypatch):
    monkeypatch.setattr(pg, "pool", lambda: _Pool(error=RuntimeError("caída")))

    r = cliente.get("/health")

    assert r.status_code == 503
    assert r.json()["fallas"] == ["postgres"]
    assert r.json()["todo_ok"] is False


def test_la_respuesta_no_filtra_la_url_del_gateway(cliente, monkeypatch):
    _con_litellm(monkeypatch, _Gateway(error=httpx.ConnectError("sin ruta")), base="http://secreto.interno:4000")

    r = cliente.get("/health")

    assert r.json()["chequeos"]["llm_gateway"] is False
    assert "secreto" not in r.text


# ---------- push ----------

def test_push_apagado_por_config_no_es_falla(monkeypatch):
    monkeypatch.setattr(push, "enabled", lambda: False)

    assert salud.push_al_dia() is True


def test_push_con_latido_reciente_esta_al_dia(monkeypatch):
    monkeypatch.setattr(push, "enabled", lambda: True)
    monkeypatch.setattr(push, "_latido", 1000.0)

    assert salud.push_al_dia(ahora=1000.0 + salud.PUSH_SIN_VUELTA_MAX_S - 1) is True
    assert salud.push_al_dia(ahora=1000.0 + salud.PUSH_SIN_VUELTA_MAX_S) is False


def test_push_late_al_empezar_la_vuelta_aunque_tarde(monkeypatch):
    monkeypatch.setattr(push, "enabled", lambda: True)
    monkeypatch.setattr(push, "_latido", None)
    monkeypatch.setattr(push, "TICK_SECONDS", 0)
    reloj = [1000.0]
    monkeypatch.setattr(push.time, "monotonic", lambda: reloj[0])
    vista_en_la_vuelta = []

    def vuelta_larga():
        vista_en_la_vuelta.append(push.latido())
        raise SystemExit  # corta el while True del hilo después de una vuelta

    monkeypatch.setattr(push, "tick", vuelta_larga)
    with pytest.raises(SystemExit):
        push._loop()

    assert vista_en_la_vuelta == [1000.0]  # latió antes de empezar
    assert salud.push_al_dia(ahora=1000.0 + 15 * 60) is True  # una vuelta de 15 min no es un hilo muerto
    assert salud.PUSH_SIN_VUELTA_MAX_S == 20 * 60


def test_push_prendido_sin_hilo_es_falla(monkeypatch):
    monkeypatch.setattr(push, "enabled", lambda: True)
    monkeypatch.setattr(push, "_latido", None)

    assert salud.push_al_dia() is False


def test_cada_vuelta_de_push_deja_el_latido_y_una_vez_por_hora_el_resumen(monkeypatch, caplog):
    monkeypatch.setattr(push, "_latido", None)
    monkeypatch.setattr(push, "_enviados_desde_resumen", 0)
    monkeypatch.setattr(push, "_ultimo_resumen", None)
    caplog.set_level(logging.INFO, logger="reinventar.push")

    push.registrar_vuelta(2, ahora=100.0)
    push.registrar_vuelta(3, ahora=100.0 + push.RESUMEN_CADA_S - 1)
    assert push.latido() == 100.0 + push.RESUMEN_CADA_S - 1
    assert "enviados" not in caplog.text

    push.registrar_vuelta(1, ahora=100.0 + push.RESUMEN_CADA_S)
    assert "6 enviados en la última hora" in caplog.text
    assert push._enviados_desde_resumen == 0


# ---------- revisiones de catálogo y eventos ----------

def _hilo_falso(nombre):
    parar = threading.Event()
    hilo = threading.Thread(target=parar.wait, name=nombre, daemon=True)
    hilo.start()
    return hilo, parar


@pytest.mark.parametrize("nombre", ["charlas-auto", "eventos-auto"])
def test_revision_con_eventos_auto_mira_que_el_hilo_este_vivo(monkeypatch, nombre):
    monkeypatch.setattr(config, "EVENTOS_AUTO", True)
    assert salud.revision_viva(nombre) is False

    hilo, parar = _hilo_falso(nombre)
    try:
        assert salud.revision_viva(nombre) is True
    finally:
        parar.set()
        hilo.join()


def test_revision_apagada_por_config_no_es_falla(monkeypatch):
    monkeypatch.setattr(config, "EVENTOS_AUTO", False)

    assert salud.revision_viva("eventos-auto") is True


def test_revision_de_eventos_en_el_health(cliente, monkeypatch):
    monkeypatch.setattr(config, "EVENTOS_AUTO", True)
    hilo, parar = _hilo_falso("charlas-auto")
    try:
        chequeos = cliente.get("/health").json()["chequeos"]
    finally:
        parar.set()
        hilo.join()

    assert chequeos["revision_catalogo"] is True
    assert chequeos["revision_eventos"] is False


# ---------- catálogo y cotización ----------

def test_catalogo_no_va_a_la_base_si_no_esta_cargado(monkeypatch):
    monkeypatch.setattr(catalog, "_sessions", None)
    monkeypatch.setattr(catalog, "load", lambda: pytest.fail("/health no tiene que cargar el catálogo"))

    assert catalog.cargadas() == 0


def test_cotizacion_de_respaldo_cuenta_como_disponible(cliente):
    assert cotizacion.ultima() is None

    assert cliente.get("/health").json()["chequeos"]["cotizacion"] is True


# ---------- gateway LiteLLM ----------

def test_sin_litellm_no_hay_gateway_que_mirar(cliente, monkeypatch):
    monkeypatch.setattr(healthcheck.httpx, "get", lambda *a, **k: pytest.fail("no tiene que llamar a nada"))

    assert cliente.get("/health").json()["chequeos"]["llm_gateway"] is True


def test_gateway_usa_liveliness_en_la_raiz_con_timeout_corto(cliente, monkeypatch):
    gateway = _con_litellm(monkeypatch, _Gateway())

    assert cliente.get("/health").json()["chequeos"]["llm_gateway"] is True
    assert gateway.urls == ["http://gateway.interno:4000/health/liveliness"]
    assert gateway.timeouts == [salud.LLM_GATEWAY_TIMEOUT_S]
    assert salud.LLM_GATEWAY_TIMEOUT_S <= 2


def test_gateway_queda_cacheado(cliente, monkeypatch):
    gateway = _con_litellm(monkeypatch, _Gateway())

    for _ in range(3):
        assert cliente.get("/health").json()["chequeos"]["llm_gateway"] is True

    assert len(gateway.urls) == 1


def test_gateway_caido_tambien_queda_cacheado_y_se_reprueba_al_vencer(cliente, monkeypatch):
    gateway = _con_litellm(monkeypatch, _Gateway(error=httpx.ConnectTimeout("timeout")))
    reloj = [1000.0]
    monkeypatch.setattr(salud.time, "monotonic", lambda: reloj[0])

    assert cliente.get("/health").json()["chequeos"]["llm_gateway"] is False
    gateway.error = None
    assert cliente.get("/health").json()["chequeos"]["llm_gateway"] is False  # todavía del caché
    reloj[0] += salud.CACHE_S

    assert cliente.get("/health").json()["chequeos"]["llm_gateway"] is True
    assert len(gateway.urls) == 2


def test_gateway_colgado_no_cuelga_el_health(cliente, monkeypatch):
    monkeypatch.setattr(salud, "LLM_GATEWAY_TIMEOUT_S", 0.1)
    soltar = threading.Event()
    _con_litellm(monkeypatch, lambda url, timeout=None: soltar.wait(30) and httpx.Response(200))

    inicio = time.monotonic()
    try:
        r = cliente.get("/health")
    finally:
        soltar.set()  # libera el ejecutor del gateway para los demás tests

    assert time.monotonic() - inicio < 10  # colgado de verdad serían 30 s: con margen para una máquina lenta
    assert r.status_code == 200
    assert r.json()["chequeos"]["llm_gateway"] is False


def test_health_con_cache_no_espera_al_gateway(cliente, monkeypatch):
    gateway = _con_litellm(monkeypatch, _Gateway())
    cliente.get("/health")  # llena el caché
    monkeypatch.setattr(healthcheck.httpx, "get", lambda *a, **k: pytest.fail("con caché no se llama al gateway"))

    assert cliente.get("/health").json()["chequeos"]["llm_gateway"] is True
    assert len(gateway.urls) == 1


def test_si_los_chequeos_explotan_da_200_con_todo_ok_false(cliente, monkeypatch):
    monkeypatch.setattr(catalog, "cargadas", lambda: 1 / 0)

    r = cliente.get("/health")

    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["chequeos"] == {}
    assert r.json()["todo_ok"] is False
    assert isinstance(r.json()["pipeline"], bool)

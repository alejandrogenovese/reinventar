"""Monitoreo y robustez para el evento: chequeos nuevos de /health (fallas del LLM, grabaciones con error, disco), tope
de tiempo de ffmpeg, TTL corto de los avisos inmediatos, pool de Postgres que prueba las conexiones y el vigía de los
procesos de fondo. Sin red ni base: todo se simula."""
import asyncio
import datetime as dt
import subprocess
from collections import namedtuple

import pytest
from psycopg_pool import ConnectionPool

from app import audio, config, db, estado, pg, pipeline, push, salud, sandbox, vigia

DIA = "2026-12-01"


@pytest.fixture(autouse=True)
def _limpio():
    salud.limpiar_cache()
    estado.reiniciar_fallas_llm()
    yield
    salud.limpiar_cache()
    estado.reiniciar_fallas_llm()


# ---------- llm_reciente ----------

def test_una_falla_aislada_del_llm_no_da_alarma():
    estado.registrar_falla_llm("real", ahora=1000.0)

    assert salud.llm_reciente(ahora=1000.0) is True


def test_varias_fallas_recientes_del_llm_dan_false():
    for i in range(estado.FALLAS_LLM_PARA_CAIDA):
        estado.registrar_falla_llm("real", ahora=1000.0 + i)

    assert salud.llm_reciente(ahora=1000.0 + 10) is False


def test_las_fallas_viejas_del_llm_ya_no_cuentan():
    for _ in range(estado.FALLAS_LLM_PARA_CAIDA):
        estado.registrar_falla_llm("real", ahora=1000.0)

    assert salud.llm_reciente(ahora=1000.0 + estado.VENTANA_FALLAS_LLM_S + 1) is True


def test_las_fallas_del_modo_prueba_no_tinen_el_health():
    for _ in range(estado.FALLAS_LLM_PARA_CAIDA):
        estado.registrar_falla_llm("prueba", ahora=1000.0)

    assert salud.llm_reciente(ahora=1000.0) is True


# ---------- grabaciones_error ----------

def _grabaciones(monkeypatch, errores):
    pedidos = []
    monkeypatch.setattr(db, "errores_desde", lambda desde: pedidos.append(desde) or errores)
    return pedidos


def test_un_error_aislado_de_grabacion_no_da_alarma(monkeypatch):
    _grabaciones(monkeypatch, 1)

    assert asyncio.run(salud.grabaciones_sin_errores()) is True


def test_varios_errores_de_grabacion_en_la_ultima_hora_dan_false(monkeypatch):
    pedidos = _grabaciones(monkeypatch, estado.ERRORES_PARA_CAIDA)

    assert asyncio.run(salud.grabaciones_sin_errores()) is False
    assert salud.time.time() - pedidos[0] == pytest.approx(estado.VENTANA_ERRORES_S, abs=5)


def test_grabaciones_queda_cacheado(monkeypatch):
    pedidos = _grabaciones(monkeypatch, 0)

    for _ in range(3):
        assert asyncio.run(salud.grabaciones_sin_errores()) is True

    assert len(pedidos) == 1


def test_base_caida_en_grabaciones_da_false_sin_explotar(monkeypatch):
    def caida(desde):
        raise RuntimeError("sin base")

    monkeypatch.setattr(db, "errores_desde", caida)

    assert asyncio.run(salud.grabaciones_sin_errores()) is False


# ---------- disco_libre ----------

Uso = namedtuple("Uso", "total used free")


@pytest.mark.parametrize(("usado", "esperado"), [(50, True), (84, True), (85, False), (99, False)])
def test_disco_libre_segun_el_uso_del_volumen(monkeypatch, tmp_path, usado, esperado):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(salud.shutil, "disk_usage", lambda ruta: Uso(100, usado, 100 - usado))

    assert asyncio.run(salud.disco_libre()) is esperado


def test_disco_mira_el_volumen_de_datos(monkeypatch, tmp_path):
    rutas = []
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(salud.shutil, "disk_usage", lambda ruta: rutas.append(ruta) or Uso(100, 10, 90))

    assert asyncio.run(salud.disco_libre()) is True
    assert rutas == [tmp_path]
    assert salud.DISCO_USO_MAX == 0.85


# ---------- ffmpeg con timeout ----------

def test_ffmpeg_tiene_tope_de_tiempo(monkeypatch):
    llamadas = []

    def run(cmd, **kw):
        llamadas.append(kw)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(audio.subprocess, "run", run)

    audio._run(["ffmpeg", "-version"])

    assert llamadas[0]["timeout"] == audio.FFMPEG_TIMEOUT_S == 600


def test_ffmpeg_colgado_termina_en_error_de_la_sesion(monkeypatch):
    def colgado(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(audio.subprocess, "run", colgado)
    monkeypatch.setattr(pipeline, "process", lambda sid: audio._run(["ffmpeg", "-i", "x.webm"]))
    marcas = []
    monkeypatch.setattr(db, "update_session", lambda sid, **kw: marcas.append((sid, kw)))
    monkeypatch.setattr(db, "get_session", lambda sid: {"reintentos_auto": 0})

    pipeline._procesar("s1", None, None)  # no tira: el worker sigue con la próxima de la cola

    # Un ffmpeg colgado es transitorio: la sesión queda en error con el reintento automático agendado.
    (sid, campos), = marcas
    assert sid == "s1"
    assert (campos["status"], campos["error"], campos["progress"]) == ("error", pipeline.ERROR_REINTENTO_AUTO, None)
    assert campos["reintento_auto_at"] is not None


# ---------- TTL de los avisos inmediatos ----------

def _card(code, start, end, salir_antes=0):
    return {"kind": "talk", "code": code, "base": code, "title": f"Charla {code}", "day": DIA, "start": start,
            "end": end, "locked": True, "reservada": False, "salir_antes": salir_antes,
            "venue": {"hotel": "MGM Grand", "detail": "Level 3"}}


def _ahora(hhmm):
    return dt.datetime.fromisoformat(f"{DIA}T{hhmm}").replace(tzinfo=sandbox.EVENT_TZ)


@pytest.mark.parametrize(("cards", "hhmm", "prefijo"), [
    ([_card("A", "10:00", "11:00")], "09:15", "leave:"),
    ([_card("A", "10:00", "11:00")], "09:57", "start:"),
    ([_card("A", "08:30", "09:30", salir_antes=4), _card("B", "10:00", "11:00")], "09:22", "early:"),
])
def test_avisos_inmediatos_viven_15_min(cards, hhmm, prefijo):
    avisos = dict(push.day_notices(cards, _ahora(hhmm), grabar=True))

    mensaje = next(m for k, m in avisos.items() if k.startswith(prefijo))
    assert mensaje["ttl"] == push.TTL_AVISO_INMEDIATO_S == 900


def test_el_ttl_no_viaja_al_celular(monkeypatch):
    enviados = []
    monkeypatch.setattr(db, "push_subscriptions", lambda u: [{"endpoint": "https://push.ejemplo/x"}])
    monkeypatch.setattr(push, "send", lambda sub, msg, http=None, ttl=push.TTL_SECONDS: enviados.append((msg, ttl)) or 201)
    _, mensaje = push.day_notices([_card("A", "10:00", "11:00")], _ahora("09:57"))[0]

    push.notify_cada_uno("tester", mensaje)

    assert enviados[0][1] == push.TTL_AVISO_INMEDIATO_S
    assert "ttl" not in enviados[0][0]


# ---------- pool de Postgres ----------

def test_el_pool_prueba_cada_conexion_antes_de_prestarla(monkeypatch):
    creados = []

    class _PoolFalso:
        check_connection = ConnectionPool.check_connection

        def __init__(self, *a, **kw):
            creados.append(kw)

    monkeypatch.setattr(pg, "ConnectionPool", _PoolFalso)
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://falso/base")

    pg._crear(False)

    assert creados[0]["check"] is ConnectionPool.check_connection


# ---------- vigía ----------

def test_vigia_reinicia_recien_a_la_tercera_falla_seguida():
    seguidas, reiniciar = 0, False
    for _ in range(vigia.FALLAS_SEGUIDAS - 1):
        seguidas, reiniciar = vigia.siguiente(seguidas, ("push",))
        assert reiniciar is False

    assert vigia.siguiente(seguidas, ("push",)) == (vigia.FALLAS_SEGUIDAS, True)


def test_vigia_un_chequeo_sano_vuelve_la_cuenta_a_cero():
    assert vigia.siguiente(vigia.FALLAS_SEGUIDAS - 1, ()) == (0, False)


def test_vigia_sale_con_codigo_1_y_deja_el_motivo(caplog):
    salidas = []

    seguidas = 0
    for _ in range(vigia.FALLAS_SEGUIDAS):
        seguidas = vigia.vuelta(seguidas, mirar=lambda: ("pipeline",), salir=salidas.append)

    assert salidas == [1]
    assert "pipeline" in caplog.text


def test_vigia_no_sale_si_todo_anda():
    salidas = []

    seguidas = 0
    for _ in range(vigia.FALLAS_SEGUIDAS * 2):
        seguidas = vigia.vuelta(seguidas, mirar=lambda: (), salir=salidas.append)

    assert salidas == []
    assert seguidas == 0


def test_vigia_con_chequeo_que_explota_no_reinicia():
    salidas = []

    def explota():
        raise RuntimeError("x")

    assert vigia.vuelta(2, mirar=explota, salir=salidas.append) == 2
    assert salidas == []


def test_vigia_mira_pipeline_y_push(monkeypatch):
    monkeypatch.setattr(pipeline, "vivo", lambda: False)
    monkeypatch.setattr(salud, "push_al_dia", lambda: True)
    assert vigia.motivos() == ("pipeline",)

    monkeypatch.setattr(pipeline, "vivo", lambda: True)
    monkeypatch.setattr(salud, "push_al_dia", lambda: False)
    assert vigia.motivos() == ("push",)


def test_vigia_tiene_gracia_al_arrancar_y_mira_cada_minuto():
    assert vigia.GRACIA_S >= 3 * 60
    assert vigia.INTERVALO_S == 60
    assert vigia.FALLAS_SEGUIDAS == 3


def test_vigia_apagado_por_config_no_arranca_hilo(monkeypatch):
    monkeypatch.setattr(config, "VIGIA", False)
    monkeypatch.setattr(vigia, "_started", False)
    monkeypatch.setattr(vigia.threading, "Thread", lambda *a, **k: pytest.fail("no tiene que arrancar el hilo"))

    vigia.start_worker()

    assert vigia._started is False


def test_vigia_prendido_arranca_un_hilo_daemon(monkeypatch):
    hilos = []

    class _Hilo:
        def __init__(self, target, name, daemon):
            hilos.append((name, daemon))

        def start(self):
            pass

    monkeypatch.setattr(config, "VIGIA", True)
    monkeypatch.setattr(vigia, "_started", False)
    monkeypatch.setattr(vigia.threading, "Thread", _Hilo)

    vigia.start_worker()
    vigia.start_worker()  # una sola vez

    assert hilos == [(vigia.NOMBRE_HILO, True)]


def test_los_tests_corren_sin_vigia():
    assert config.VIGIA is False

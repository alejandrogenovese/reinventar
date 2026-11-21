"""Cotización del dólar (app/cotizacion.py): Bluelytics con httpx mockeado, historial con umbral y respaldo si la API cae."""
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, cotizacion, db
from app.main import app


def _respuesta(oficial=1000.0, blue=1200.0):
    return {"oficial": {"value_avg": oficial, "value_sell": oficial, "value_buy": oficial - 10},
            "blue": {"value_avg": blue, "value_sell": blue, "value_buy": blue - 20}}


def _cliente(manejador):
    return httpx.Client(transport=httpx.MockTransport(manejador))


def _ok(**kwargs):
    return _cliente(lambda r: httpx.Response(200, json=_respuesta(**kwargs)))


def _sin_red(_request):
    raise httpx.ConnectError("sin red")


@pytest.fixture(autouse=True)
def base_limpia(monkeypatch):
    monkeypatch.setattr(config, "TARJETA_FACTOR", 1.3)
    monkeypatch.setattr(cotizacion, "_ultima_consulta_ok", None)
    with TestClient(app):  # corre el lifespan: crea las tablas
        with db.conn() as c:
            c.execute("DELETE FROM cotizaciones")
        yield
        with db.conn() as c:
            c.execute("DELETE FROM cotizaciones")


def _filas():
    with db.conn() as c:
        return c.execute("SELECT oficial, blue, tarjeta FROM cotizaciones ORDER BY id").fetchall()


def test_guarda_oficial_blue_y_tarjeta_como_oficial_por_el_factor():
    assert cotizacion.refrescar(_ok()) is True
    assert _filas() == [{"oficial": Decimal("1000"), "blue": Decimal("1200"), "tarjeta": Decimal("1300")}]


def test_actual_devuelve_la_ultima_guardada():
    cotizacion.refrescar(_ok(oficial=1000.0, blue=1200.0))
    cotizacion.refrescar(_ok(oficial=1100.0, blue=1300.0))
    actual = cotizacion.actual()
    assert (actual["oficial"], actual["blue"], actual["tarjeta"]) == (1100, 1300, 1430)
    assert actual["at"] is not None


def test_no_suma_fila_si_se_movio_menos_de_un_decimo_por_ciento():
    cotizacion.refrescar(_ok(oficial=1000.0, blue=1200.0))
    cotizacion.refrescar(_ok(oficial=1000.5, blue=1200.5))  # +0,05 % y +0,04 %
    assert len(_filas()) == 1


def test_suma_fila_si_alguna_se_movio_mas_de_un_decimo_por_ciento():
    cotizacion.refrescar(_ok(oficial=1000.0, blue=1200.0))
    cotizacion.refrescar(_ok(oficial=1000.0, blue=1203.0))  # el blue +0,25 %
    assert len(_filas()) == 2


@pytest.mark.parametrize("manejador", [
    lambda r: httpx.Response(500),
    lambda r: httpx.Response(200, text="no es json"),
    lambda r: httpx.Response(200, json={"oficial": {"value_sell": 1000}}),          # falta el blue
    lambda r: httpx.Response(200, json=_respuesta(oficial=0)),                       # cotización inservible
    _sin_red,
], ids=["500", "no-json", "sin-blue", "cero", "sin-red"])
def test_con_la_api_caida_se_queda_con_la_ultima_guardada(manejador):
    cotizacion.refrescar(_ok())
    assert cotizacion.refrescar(_cliente(manejador)) is False
    assert len(_filas()) == 1
    assert cotizacion.actual()["oficial"] == 1000


def test_sin_ninguna_guardada_usa_el_respaldo_en_codigo():
    assert cotizacion.refrescar(_cliente(lambda r: httpx.Response(503))) is False
    actual = cotizacion.actual()
    assert actual["oficial"] == cotizacion.RESPALDO["oficial"] and actual["at"] is None


def test_el_worker_no_arranca_si_esta_apagado(monkeypatch):
    monkeypatch.setattr(config, "COTIZACION_AUTO", False)
    cotizacion.start_worker()  # no debe lanzar el hilo ni pegarle a la red


def test_una_consulta_exitosa_sin_movimiento_rejuvenece_la_cotizacion():
    cotizacion.refrescar(_ok())
    with db.conn() as c:
        c.execute("UPDATE cotizaciones SET at = now() - interval '5 hours'")
    cotizacion._ultima_consulta_ok = None
    assert cotizacion.edad_min(cotizacion.actual()) >= 300
    cotizacion.refrescar(_ok())  # mismo valor: no suma fila, pero la API respondió
    assert len(_filas()) == 1
    assert cotizacion.edad_min(cotizacion.actual()) < 5


def test_la_antiguedad_es_nula_para_el_respaldo():
    actual = cotizacion.actual()
    assert actual["at"] is None and cotizacion.edad_min(actual) is None


def test_vigente_en_elige_la_ultima_anterior_al_fin_del_dia_del_gasto():
    ahora = datetime.now(UTC)
    with db.conn() as c:
        c.execute("INSERT INTO cotizaciones (at, oficial, blue, tarjeta) VALUES (%s, 1000, 1100, 1300)",
                  (ahora - timedelta(days=9),))
        c.execute("INSERT INTO cotizaciones (at, oficial, blue, tarjeta) VALUES (%s, 1200, 1300, 1560)",
                  (ahora - timedelta(days=1),))
    vieja = cotizacion.vigente_en(ahora.date() - timedelta(days=6))
    assert vieja["oficial"] == 1000 and vieja["estimada"] is True      # la de hace 9 días: más de 48 h hasta esa fecha
    hoy = cotizacion.vigente_en(ahora.date())
    assert hoy["oficial"] == 1200 and hoy["estimada"] is False
    assert hoy["respaldo"] is False


def test_vigente_en_sin_historial_es_respaldo_y_estimada():
    r = cotizacion.vigente_en(datetime.now(UTC).date())
    assert r["respaldo"] is True and r["estimada"] is True and r["tarjeta"] == cotizacion.RESPALDO["tarjeta"]


def test_el_worker_arranca_y_refresca_al_iniciar_si_esta_prendido(monkeypatch):
    llamadas = []
    monkeypatch.setattr(config, "COTIZACION_AUTO", True)
    monkeypatch.setattr(cotizacion.threading, "Thread", lambda target, **kw: SimpleNamespace(
        start=lambda: llamadas.append(target)))
    cotizacion.start_worker()
    assert len(llamadas) == 1


def test_cotizacion_auto_no_depende_de_stt_provider():
    entorno = {k: v for k, v in os.environ.items() if k != "COTIZACION_AUTO"}
    r = subprocess.run([sys.executable, "-c", "from app import config; print(config.COTIZACION_AUTO)"],
                       env={**entorno, "STT_PROVIDER": "fake"}, capture_output=True, text=True, check=True)
    assert r.stdout.strip() == "True"


def test_en_los_tests_la_cotizacion_automatica_esta_apagada():
    assert config.COTIZACION_AUTO is False

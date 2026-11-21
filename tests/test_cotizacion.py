"""Cotización del dólar (app/cotizacion.py): Bluelytics con httpx mockeado, historial con umbral y respaldo si la API cae."""
from decimal import Decimal

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

"""Ofertas en vivo de Viator: búsqueda con el flag SPECIAL_OFFER, qué cuenta como rebajado (fromPriceBeforeDiscount >
fromPrice), cache de 1 h en memoria (nada en la base) y que la pantalla Ofertas no se rompa si Viator falla o no hay
clave. httpx va mockeado con el mismo falso de tests/test_viator.py: nunca se le pega a Viator."""
import logging

import httpx
import pytest

from app import config, viator
from tests import test_viator as base
from tests.test_viator import ANTES_DEL_VIAJE, CLAVE, Reloj, Resp

# Los mismos fixtures que tests/test_viator.py: clave de prueba, cache limpia y httpx falso.
_limpio, api_viator, client = base._limpio, base.api_viator, base.client

URL_AFILIADO = "https://www.viator.com/tours/Las-Vegas/Grand-Canyon/d684-5502GRAND?pid=P1&mcid=42&medium=api"


def _producto(codigo: str, antes, ahora, **cambios) -> dict:
    base = {"productCode": codigo, "title": f"Excursión {codigo}", "productUrl": URL_AFILIADO,
            "pricing": {"summary": {"fromPrice": ahora, "fromPriceBeforeDiscount": antes}, "currency": "USD"}}
    return {**base, **cambios}


CON_DESCUENTOS = {"products": [
    _producto("CHICO", 100, 90),        # -10 %
    _producto("GRANDE", 200, 120),      # -40 %
    _producto("IGUAL", 50, 50),         # sin descuento real: Viator repite fromPrice
    _producto("SINANTES", None, 70),
    _producto("SUBE", 80, 95),
    _producto("TEXTO", "200", "100"),
], "totalCount": 6}


# ---- parseo -------------------------------------------------------------------------------------------------------
def test_solo_entran_las_rebajadas_y_primero_las_de_mayor_descuento():
    ofertas = viator.leer_ofertas(CON_DESCUENTOS)
    assert [o["codigo"] for o in ofertas] == ["GRANDE", "CHICO"]
    assert ofertas[0] == {"codigo": "GRANDE", "titulo": "Excursión GRANDE", "foto": None, "url": URL_AFILIADO,
                          "moneda": "USD", "precio_antes": 200, "precio_ahora": 120, "descuento": 40}


def test_el_link_tiene_que_ser_de_viator():
    otro = _producto("X", 100, 50, productUrl="https://estafa.example.com/x")
    assert viator.leer_oferta(otro) is None


def test_se_queda_con_las_de_mayor_descuento_hasta_el_tope():
    data = {"products": [_producto(f"P{i}", 100, 100 - i) for i in range(1, 40)]}
    ofertas = viator.leer_ofertas(data)
    assert len(ofertas) == viator.MAX_OFERTAS
    assert ofertas[0]["codigo"] == "P39"


@pytest.mark.parametrize("data", [["lista"], {"products": "texto"}, {"products": [{"productCode": "X", "pricing": "gratis"}]}])
def test_forma_inesperada_es_viator_no_disponible(data):
    with pytest.raises(viator.ViatorNoDisponible):
        viator.leer_ofertas(data)


def test_la_busqueda_pide_solo_special_offer_en_las_fechas_de_la_estadia():
    cuerpo = viator.cuerpo_ofertas(ANTES_DEL_VIAJE)
    assert cuerpo["filtering"] == {"destination": "684", "startDate": "2026-11-29", "endDate": "2026-12-07",
                                   "flags": ["SPECIAL_OFFER"]}
    assert cuerpo["pagination"] == {"start": 1, "count": viator.POR_PAGINA}


# ---- pedidos y cache ----------------------------------------------------------------------------------------------
def _posts(api):
    return [p for p in api.pedidos if p["metodo"] == "POST"]


def test_cache_de_una_hora_en_memoria_y_aparte_de_las_excursiones(api_viator):
    reloj = Reloj()
    api_viator.busqueda = Resp(200, CON_DESCUENTOS)
    primera = viator.ofertas(reloj=reloj, hoy=ANTES_DEL_VIAJE)
    reloj.t += viator.TTL_BUSQUEDA_S - 1
    assert viator.ofertas(reloj=reloj, hoy=ANTES_DEL_VIAJE) == primera
    assert len(_posts(api_viator)) == 1
    assert _posts(api_viator)[0]["json"]["filtering"]["flags"] == ["SPECIAL_OFFER"]
    viator.excursiones(1, reloj=reloj, hoy=ANTES_DEL_VIAJE)  # la página 1 de Excursiones no pisa a las ofertas
    assert "flags" not in _posts(api_viator)[1]["json"]["filtering"]
    reloj.t += 2  # pasó la hora: se vuelve a pedir
    viator.ofertas(reloj=reloj, hoy=ANTES_DEL_VIAJE)
    assert len(_posts(api_viator)) == 3


def test_sin_descuentos_o_con_error_se_recuerda_solo_un_minuto(api_viator):
    reloj = Reloj()
    api_viator.busqueda = Resp(200, {"products": [_producto("IGUAL", 50, 50)]})
    assert viator.ofertas(reloj=reloj, hoy=ANTES_DEL_VIAJE) == []
    assert viator.ofertas(reloj=reloj, hoy=ANTES_DEL_VIAJE) == []
    assert len(_posts(api_viator)) == 1
    reloj.t += viator.TTL_FALLO_S + 1
    api_viator.busqueda = Resp(500, {})
    for _ in range(3):
        with pytest.raises(viator.ViatorNoDisponible):
            viator.ofertas(reloj=reloj, hoy=ANTES_DEL_VIAJE)
    assert len(_posts(api_viator)) == 2


# ---- endpoint -----------------------------------------------------------------------------------------------------
def test_endpoint_devuelve_las_ofertas_en_vivo(client, api_viator):
    api_viator.busqueda = Resp(200, CON_DESCUENTOS)
    r = client.get("/api/ofertas/en-vivo")
    assert r.status_code == 200
    assert [o["codigo"] for o in r.json()["ofertas"]] == ["GRANDE", "CHICO"]


@pytest.mark.parametrize("falla", [Resp(500, {}), Resp(401, {"message": f"bad key {CLAVE}"}), httpx.ConnectError(CLAVE)])
def test_endpoint_si_viator_falla_devuelve_vacio_sin_romper_ni_loguear_la_clave(client, api_viator, caplog, falla):
    api_viator.busqueda = falla
    with caplog.at_level(logging.DEBUG):
        r = client.get("/api/ofertas/en-vivo")
    assert r.status_code == 200 and r.json() == {"ofertas": []}
    assert CLAVE not in caplog.text


def test_endpoint_sin_clave_no_pide_nada(client, api_viator, monkeypatch):
    monkeypatch.setattr(config, "VIATOR_API_KEY", None)
    assert client.get("/api/ofertas/en-vivo").json() == {"ofertas": []}
    assert api_viator.pedidos == []


def test_endpoint_pide_sesion(api_viator):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as anonimo:
        assert anonimo.get("/api/ofertas/en-vivo").status_code == 401
    assert api_viator.pedidos == []

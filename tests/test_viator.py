"""Excursiones de Viator: parseo de /products/search y /products/tags (respuestas grabadas en tests/fixtures, armadas
según la documentación), agrupado por categoría, cache de 1 h, falta de clave y errores HTTP. httpx va mockeado: estos
tests nunca le pegan a Viator."""
import datetime as dt
import json
import logging
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import actividades_api, config, viator
from app.main import app
from tests.conftest import login_headers

FIXTURES = Path(__file__).parent / "fixtures"
BUSQUEDA = json.loads((FIXTURES / "viator_busqueda.json").read_text())
TAGS = json.loads((FIXTURES / "viator_tags.json").read_text())
CLAVE = "clave-viator-de-prueba"
ANTES_DEL_VIAJE = dt.date(2026, 11, 23)


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Resp:
    def __init__(self, status: int, data=None):
        self.status_code, self._data, self.text = status, data, json.dumps(data)

    def json(self):
        if self._data is None:
            raise ValueError("sin JSON")
        return self._data


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    actividades_api.reiniciar()
    monkeypatch.setattr(config, "VIATOR_API_KEY", CLAVE)
    yield
    actividades_api.reiniciar()


@pytest.fixture
def api_viator(monkeypatch):
    """Reemplaza httpx.post/get de viator.py y guarda cada pedido."""
    class Falso:
        pedidos: list[dict] = []
        busqueda = Resp(200, BUSQUEDA)
        tags = Resp(200, TAGS)

    def post(url, json=None, headers=None, timeout=None):
        Falso.pedidos.append({"metodo": "POST", "url": url, "json": json, "headers": headers})
        if isinstance(Falso.busqueda, Exception):
            raise Falso.busqueda
        return Falso.busqueda

    def get(url, headers=None, timeout=None):
        Falso.pedidos.append({"metodo": "GET", "url": url, "headers": headers})
        return Falso.tags

    Falso.pedidos = []
    monkeypatch.setattr(viator.httpx, "post", post)
    monkeypatch.setattr(viator.httpx, "get", get)
    return Falso


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.headers.update(login_headers(c))
        yield c


# ---- parseo -------------------------------------------------------------------------------------------------------
def test_parsea_un_producto_completo():
    r = viator.leer_busqueda(BUSQUEDA)
    grand = r["productos"][0]
    assert r["total"] == 137
    assert grand == {
        "codigo": "5502GRAND", "titulo": "Grand Canyon West con Skywalk desde Las Vegas",
        "foto": "https://media.example.com/skywalk-540.jpg",  # portada, la más chica que llega a 480 de ancho
        "precio_desde": 189.99, "moneda": "USD", "rating": 4.53, "resenas": 1234,
        "minutos_desde": 720, "minutos_hasta": 720,
        "url": BUSQUEDA["products"][0]["productUrl"], "tags": [21911, 12026]}


def test_duracion_variable_foto_chica_y_campos_faltantes():
    _, high_roller, red_rock = viator.leer_busqueda(BUSQUEDA)["productos"]
    assert (high_roller["minutos_desde"], high_roller["minutos_hasta"]) == (30, 60)
    assert high_roller["foto"] == "https://media.example.com/hr-150.jpg"  # ninguna llega a 480: la más grande
    assert red_rock["foto"] is None and red_rock["rating"] is None and red_rock["resenas"] == 0
    assert (red_rock["minutos_desde"], red_rock["minutos_hasta"]) == (None, None)


def test_descarta_productos_sin_link_o_con_link_fuera_de_viator():
    codigos = [p["codigo"] for p in viator.leer_busqueda(BUSQUEDA)["productos"]]
    assert "SINLINK" not in codigos and "OTROHOST" not in codigos
    assert viator.leer_producto({"productCode": "X", "title": "T", "productUrl": "http://www.viator.com/x"}) is None


def test_agrupa_por_categoria_con_el_arbol_de_tags():
    productos = viator.leer_busqueda(BUSQUEDA)["productos"]
    grupos = viator.agrupar(productos, viator.leer_tags(TAGS))
    assert [(g["clave"], [p["codigo"] for p in g["productos"]]) for g in grupos] == [
        ("excursiones", ["5502GRAND"]), ("aire_libre", ["777RED"]), ("atracciones", ["12345P1"])]
    assert grupos[0]["titulo"] == "Excursiones de un día"


def test_sin_tags_no_agrupa():
    productos = viator.leer_busqueda(BUSQUEDA)["productos"]
    assert viator.agrupar(productos, {}) is None
    assert viator.agrupar([{**p, "tags": []} for p in productos], viator.leer_tags(TAGS)) is None


def test_tag_desconocido_va_a_otras():
    assert viator.categoria([424242], viator.leer_tags(TAGS)) == viator.OTRAS


def test_cuerpo_de_la_busqueda_pagina_de_a_50_en_las_fechas_de_la_estadia():
    cuerpo = viator.cuerpo_busqueda(2, ANTES_DEL_VIAJE)
    assert cuerpo["filtering"] == {"destination": "684", "startDate": "2026-11-29", "endDate": "2026-12-06"}
    assert cuerpo["pagination"] == {"start": 51, "count": 50}
    assert cuerpo["currency"] == "USD"
    # Ya en Las Vegas no se buscan días que pasaron.
    assert viator.cuerpo_busqueda(1, dt.date(2026, 12, 3))["filtering"]["startDate"] == "2026-12-03"


# ---- pedidos y cache ----------------------------------------------------------------------------------------------
def test_pide_con_la_clave_en_el_header_y_la_version_2(api_viator):
    viator.excursiones(1, hoy=ANTES_DEL_VIAJE)
    post = api_viator.pedidos[0]
    assert post["url"] == "https://api.viator.com/partner/products/search"
    assert post["headers"]["exp-api-key"] == CLAVE
    assert post["headers"]["Accept"] == "application/json;version=2.0"
    assert CLAVE not in post["url"]
    assert api_viator.pedidos[1]["url"] == "https://api.viator.com/partner/products/tags"


def test_cache_de_una_hora(api_viator):
    reloj = Reloj()
    primera = viator.excursiones(1, reloj=reloj, hoy=ANTES_DEL_VIAJE)
    reloj.t += viator.TTL_BUSQUEDA_S - 1
    assert viator.excursiones(1, reloj=reloj, hoy=ANTES_DEL_VIAJE) == primera
    assert sum(p["metodo"] == "POST" for p in api_viator.pedidos) == 1
    reloj.t += 2  # pasó la hora: se vuelve a pedir; los tags (una semana) no
    viator.excursiones(1, reloj=reloj, hoy=ANTES_DEL_VIAJE)
    assert sum(p["metodo"] == "POST" for p in api_viator.pedidos) == 2
    assert sum(p["metodo"] == "GET" for p in api_viator.pedidos) == 1


def test_cada_pagina_se_cachea_aparte_y_hay_mas_hasta_el_tope(api_viator):
    assert viator.excursiones(1, hoy=ANTES_DEL_VIAJE)["hay_mas"] is True      # 137 en total
    assert viator.excursiones(3, hoy=ANTES_DEL_VIAJE)["hay_mas"] is False     # 150 >= 137
    assert sum(p["metodo"] == "POST" for p in api_viator.pedidos) == 2
    with pytest.raises(ValueError):
        viator.excursiones(viator.MAX_PAGINAS + 1)


def _posts(api_viator):
    return sum(p["metodo"] == "POST" for p in api_viator.pedidos)


def test_una_respuesta_vacia_se_recuerda_solo_un_minuto(api_viator):
    reloj = Reloj()
    api_viator.busqueda = Resp(200, {"products": [], "totalCount": 0})
    viator.excursiones(1, reloj=reloj, hoy=ANTES_DEL_VIAJE)
    viator.excursiones(1, reloj=reloj, hoy=ANTES_DEL_VIAJE)
    assert _posts(api_viator) == 1
    reloj.t += viator.TTL_FALLO_S + 1
    viator.excursiones(1, reloj=reloj, hoy=ANTES_DEL_VIAJE)
    assert _posts(api_viator) == 2


def test_un_error_se_recuerda_un_minuto_sin_rafagas_contra_viator(api_viator):
    reloj = Reloj()
    api_viator.busqueda = Resp(500, {})
    for _ in range(5):
        with pytest.raises(viator.ViatorNoDisponible):
            viator.excursiones(1, reloj=reloj, hoy=ANTES_DEL_VIAJE)
    assert _posts(api_viator) == 1
    reloj.t += viator.TTL_FALLO_S + 1
    api_viator.busqueda = Resp(200, BUSQUEDA)
    assert len(viator.excursiones(1, reloj=reloj, hoy=ANTES_DEL_VIAJE)["productos"]) == 3
    assert _posts(api_viator) == 2


@pytest.mark.parametrize("data", [
    ["no", "es", "un", "objeto"],
    {"products": "texto", "totalCount": 3},
    {"products": [{"productCode": "X", "title": "T", "productUrl": "https://www.viator.com/x", "pricing": "gratis"}]},
    {"products": [], "totalCount": "muchos"},
])
def test_json_inesperado_es_viator_no_disponible_y_no_un_500(api_viator, data):
    api_viator.busqueda = Resp(200, data)
    with pytest.raises(viator.ViatorNoDisponible):
        viator.excursiones(1, hoy=ANTES_DEL_VIAJE)


def test_elementos_que_no_son_objetos_se_saltean():
    data = {"products": ["texto", None, 3, *BUSQUEDA["products"]], "totalCount": 3}
    assert len(viator.leer_busqueda(data)["productos"]) == 3


@pytest.mark.parametrize("data", [
    "texto", None, {"tags": "x"}, [None, "x", {"tagId": "1"}, {"tagId": 5, "allNamesByLocale": "x", "parentTagIds": "y"}],
])
def test_tags_con_forma_rara_no_rompen(data):
    arbol = viator.leer_tags(data)
    assert arbol in ({}, {5: {"nombre": "", "padres": []}})


def test_si_fallan_los_tags_no_se_reintentan_por_unos_minutos(api_viator):
    reloj = Reloj()
    api_viator.tags = Resp(500, {})
    viator.excursiones(1, reloj=reloj, hoy=ANTES_DEL_VIAJE)
    viator.excursiones(2, reloj=reloj, hoy=ANTES_DEL_VIAJE)
    assert sum(p["metodo"] == "GET" for p in api_viator.pedidos) == 1
    reloj.t += viator.TTL_TAGS_FALLO_S + 1
    viator.excursiones(3, reloj=reloj, hoy=ANTES_DEL_VIAJE)
    assert sum(p["metodo"] == "GET" for p in api_viator.pedidos) == 2


def test_la_clave_nunca_aparece_en_los_logs(client, api_viator, caplog):
    with caplog.at_level(logging.DEBUG):
        api_viator.tags = Resp(401, {"message": f"invalid key {CLAVE}"})
        client.get("/api/actividades/excursiones")
        actividades_api.reiniciar()
        api_viator.busqueda = Resp(403, {"message": f"invalid key {CLAVE}"})
        client.get("/api/actividades/excursiones")
        api_viator.busqueda = httpx.ConnectError(f"fallo con {CLAVE}")
        client.get("/api/actividades/excursiones", params={"pagina": 2})
    assert caplog.records and CLAVE not in caplog.text


def test_sin_clave_no_pide_nada(api_viator, monkeypatch):
    monkeypatch.setattr(config, "VIATOR_API_KEY", None)
    assert viator.habilitado() is False
    with pytest.raises(viator.SinClave):
        viator.excursiones(1)
    assert api_viator.pedidos == []


@pytest.mark.parametrize("status", [401, 429, 500])
def test_error_http_sin_clave_ni_cuerpo_en_el_mensaje(api_viator, status):
    api_viator.busqueda = Resp(status, {"code": "X", "message": f"bad key {CLAVE}"})
    with pytest.raises(viator.ViatorNoDisponible) as e:
        viator.excursiones(1, hoy=ANTES_DEL_VIAJE)
    assert str(status) in str(e.value) and CLAVE not in str(e.value)


def test_sin_conexion(api_viator):
    api_viator.busqueda = httpx.ConnectError("no route")
    with pytest.raises(viator.ViatorNoDisponible):
        viator.excursiones(1, hoy=ANTES_DEL_VIAJE)


def test_si_fallan_los_tags_la_lista_va_sin_agrupar(api_viator):
    api_viator.tags = Resp(500, {})
    r = viator.excursiones(1, hoy=ANTES_DEL_VIAJE)
    assert r["grupos"] is None and len(r["productos"]) == 3


# ---- endpoint -----------------------------------------------------------------------------------------------------
def test_endpoint_devuelve_productos_agrupados(client, api_viator):
    r = client.get("/api/actividades/excursiones")
    assert r.status_code == 200
    body = r.json()
    assert body["habilitado"] is True and body["pagina"] == 1 and body["hay_mas"] is True
    assert [g["clave"] for g in body["grupos"]] == ["excursiones", "aire_libre", "atracciones"]


def test_endpoint_sin_clave_no_se_habilita_y_avisa_una_sola_vez(client, api_viator, monkeypatch, caplog):
    monkeypatch.setattr(config, "VIATOR_API_KEY", None)
    with caplog.at_level(logging.INFO, logger="reinventar.actividades"):
        assert client.get("/api/actividades/excursiones").json() == {"habilitado": False}
        assert client.get("/api/actividades/excursiones").json() == {"habilitado": False}
    avisos = [r for r in caplog.records if r.name == "reinventar.actividades"]
    assert len(avisos) == 1 and avisos[0].levelno == logging.INFO
    assert api_viator.pedidos == []


def test_endpoint_con_viator_caido_da_503_con_mensaje(client, api_viator):
    api_viator.busqueda = Resp(503, None)
    r = client.get("/api/actividades/excursiones")
    assert r.status_code == 503 and "excursiones" in r.json()["detail"]


def test_endpoint_valida_la_pagina(client, api_viator):
    assert client.get("/api/actividades/excursiones", params={"pagina": 0}).status_code == 422
    assert client.get("/api/actividades/excursiones", params={"pagina": viator.MAX_PAGINAS + 1}).status_code == 422


def test_estado_dice_si_hay_excursiones_sin_pedirle_nada_a_viator(client, api_viator, monkeypatch):
    assert client.get("/api/actividades/estado").json() == {"excursiones": True}
    monkeypatch.setattr(config, "VIATOR_API_KEY", None)
    assert client.get("/api/actividades/estado").json() == {"excursiones": False}
    assert api_viator.pedidos == []


def test_endpoint_con_json_inesperado_da_503(client, api_viator):
    api_viator.busqueda = Resp(200, ["no", "es", "un", "objeto"])
    assert client.get("/api/actividades/excursiones").status_code == 503


def test_endpoint_pide_login():
    with TestClient(app) as c:
        assert c.get("/api/actividades/excursiones").status_code == 401


def test_el_dia_de_la_vuelta_no_se_ofrecen_excursiones():
    # La vuelta es el lun 7/12 a las 13:00: el último día que se busca es el domingo 6/12.
    assert viator.cuerpo_busqueda(1, ANTES_DEL_VIAJE)["filtering"]["endDate"] == "2026-12-06"
    # Si ya es el 7/12, el rango queda en ese día y no en uno anterior a «desde».
    assert viator.cuerpo_busqueda(1, dt.date(2026, 12, 7))["filtering"]["startDate"] == "2026-12-07"

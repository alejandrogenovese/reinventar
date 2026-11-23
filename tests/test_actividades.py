"""Actividades › Cerca: atracciones de Google Places ordenadas por distancia, con field mask barata (sin reseñas ni
puntajes), caché por cuadrado, límite por usuario, sin clave y origen desde el itinerario. Places va mockeado."""
import pytest
from fastapi.testclient import TestClient

from app import actividades_api, config, places, today
from app.main import app
from tests.conftest import login_headers

STRIP = (36.1147, -115.1728)


def _lugar(id_, nombre, lat, lng, tipo="Museo"):
    return {"id": id_, "displayName": {"text": nombre}, "formattedAddress": f"{nombre}, Las Vegas",
            "location": {"latitude": lat, "longitude": lng}, "googleMapsUri": f"https://maps.google.com/?cid={id_}",
            "primaryTypeDisplayName": {"text": tipo}}


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    actividades_api.reiniciar()
    monkeypatch.setattr(config, "GOOGLE_PLACES_SERVER_KEY", "clave-de-prueba")
    yield
    actividades_api.reiniciar()


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.headers.update(login_headers(c))
        yield c


@pytest.fixture
def google(monkeypatch):
    class Falso:
        pedidos: list[dict] = []
        respuesta: dict = {"places": []}

    def post(url, json=None, headers=None, timeout=None):
        Falso.pedidos.append({"url": url, "json": json, "headers": headers})
        return type("R", (), {"status_code": 200, "text": "", "json": lambda self: Falso.respuesta})()

    Falso.pedidos = []
    monkeypatch.setattr(places.httpx, "post", post)
    return Falso


def _pedir(client, **params):
    return client.get("/api/actividades/cerca", params={"lat": STRIP[0], "lng": STRIP[1], **params})


def test_pide_tipos_de_atracciones_con_mascara_barata(client, google):
    assert _pedir(client).status_code == 200
    [pedido] = google.pedidos
    assert pedido["url"] == places.NEARBY_URL
    assert set(pedido["json"]["includedTypes"]) >= {"tourist_attraction", "museum", "park", "art_gallery"}
    mascara = pedido["headers"]["X-Goog-FieldMask"]
    assert "places.primaryTypeDisplayName" in mascara
    for caro in ("reviews", "rating", "userRatingCount", "currentOpeningHours", "priceLevel"):
        assert caro not in mascara


def test_ordena_por_distancia_y_trae_minutos(client, google):
    google.respuesta = {"places": [_lugar("lejos", "Hoover Dam Lodge", 36.16, -115.14, "Atracción turística"),
                                   _lugar("cerca", "Museo del Neón", 36.115, -115.173),
                                   {"id": "sin-ubicacion", "displayName": {"text": "X"}}]}
    lugares = _pedir(client).json()["lugares"]
    assert [x["place_id"] for x in lugares] == ["cerca", "lejos"]
    assert lugares[0]["tipo"] == "Museo" and lugares[0]["metros"] < lugares[1]["metros"]
    assert lugares[0]["minutos"] >= 0 and lugares[0]["url"].startswith("https://maps.google.com/")


def test_segunda_llamada_sale_de_cache(client, google):
    google.respuesta = {"places": [_lugar("a", "A", 36.115, -115.173)]}
    _pedir(client)
    _pedir(client)
    assert len(google.pedidos) == 1


def test_cache_vence_con_el_ttl(client, google, monkeypatch):
    google.respuesta = {"places": [_lugar("a", "A", 36.115, -115.173)]}
    t = [1000.0]
    monkeypatch.setattr(actividades_api.time, "monotonic", lambda: t[0])
    _pedir(client)
    t[0] += actividades_api.TTL_CACHE_S + 1
    _pedir(client)
    assert len(google.pedidos) == 2


def test_limite_por_usuario(client, google, monkeypatch):
    google.respuesta = {"places": [_lugar("a", "A", 36.115, -115.173)]}
    monkeypatch.setattr(actividades_api, "_limite", actividades_api.limites.Limite(1, 3600))
    assert _pedir(client).status_code == 200
    assert _pedir(client).status_code == 200  # caché: no gasta cupo
    assert _pedir(client, lat=STRIP[0] + 0.5).status_code == 429


def test_sin_clave_de_places_es_503(client, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_PLACES_SERVER_KEY", "")
    monkeypatch.setattr(config, "GOOGLE_MAPS_API_KEY", "")
    r = _pedir(client)
    assert r.status_code == 503 and "no están disponibles" in r.json()["detail"]


def test_error_de_google_no_filtra_el_detalle(client, monkeypatch):
    monkeypatch.setattr(places.httpx, "post", lambda *a, **k: type("R", (), {"status_code": 403, "text": "secreto"})())
    r = _pedir(client)
    assert r.status_code == 503 and "secreto" not in r.text


def test_origen_desde_la_proxima_sesion(client, google, monkeypatch):
    sesion = {"venue": {"hotel": "Venetian", "lat": 36.1212, "lng": -115.1697}}
    monkeypatch.setattr(today, "for_user", lambda u: {"now": None, "next": sesion, "upcoming": None})
    r = client.get("/api/actividades/cerca")
    assert r.status_code == 200 and r.json()["origen"]["fuente"] == "sesion"


def test_sin_origen_es_404_y_no_llama_a_google(client, google, monkeypatch):
    monkeypatch.setattr(today, "for_user", lambda u: {"now": None, "next": None, "upcoming": None})
    r = client.get("/api/actividades/cerca")
    assert r.status_code == 404 and not google.pedidos


@pytest.mark.parametrize("params", [{"lat": 36.1}, {"lat": 100, "lng": 0}])
def test_valida_parametros(client, google, params):
    assert client.get("/api/actividades/cerca", params=params).status_code == 422


def test_exige_login():
    with TestClient(app) as c:
        assert c.get("/api/actividades/cerca", params={"lat": STRIP[0], "lng": STRIP[1]}).status_code == 401

"""«Dónde comer barato»: parseo de Places (API New), filtros, orden, caché, límite, sin clave y origen desde el
itinerario. Places va mockeado: estos tests nunca le pegan a Google."""
import pytest
from fastapi.testclient import TestClient

from app import comer_api, config, places, today
from app.main import app
from tests.conftest import login_headers

STRIP = (36.1147, -115.1728)


def _lugar(id_, nombre, lat, lng, rating=4.5, n=500, precio="PRICE_LEVEL_INEXPENSIVE", **extra):
    p = {"id": id_, "displayName": {"text": nombre}, "formattedAddress": f"{nombre}, Las Vegas", "rating": rating,
         "userRatingCount": n, "priceLevel": precio, "location": {"latitude": lat, "longitude": lng},
         "currentOpeningHours": {"openNow": True}, "googleMapsUri": f"https://maps.google.com/?cid={id_}"}
    return {**p, **extra}


def _respuesta(*lugares):
    return {"places": list(lugares)}


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    comer_api.reiniciar()
    monkeypatch.setattr(config, "GOOGLE_PLACES_SERVER_KEY", "clave-de-prueba")
    yield
    comer_api.reiniciar()


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.headers.update(login_headers(c))
        yield c


@pytest.fixture
def google(monkeypatch):
    """Reemplaza httpx.post de places.py; guarda cada pedido y devuelve la respuesta cargada en `cargar`."""
    class Falso:
        pedidos: list[dict] = []
        respuesta: dict = _respuesta()

    def post(url, json=None, headers=None, timeout=None):
        Falso.pedidos.append({"url": url, "json": json, "headers": headers})
        return type("R", (), {"status_code": 200, "text": "", "json": lambda self: Falso.respuesta})()

    Falso.pedidos = []
    monkeypatch.setattr(places.httpx, "post", post)
    return Falso


def _pedir(client, **params):
    return client.get("/api/comer", params={"lat": STRIP[0], "lng": STRIP[1], **params})


def test_parsea_campos_de_places():
    data = _respuesta(_lugar("a1", "Taquería", 36.115, -115.173, reviews=[
        {"rating": 5, "text": {"text": "Los mejores tacos " + "x" * 300}},
        {"rating": 4, "text": {"text": "Rápido y rico"}},
        {"rating": 3, "text": {"text": "Tercera"}},
        {"rating": 1}]), {"id": "sin-ubicacion"})
    [lugar] = places.leer_cercanos(data)
    assert (lugar["place_id"], lugar["nombre"], lugar["rating"], lugar["resenas"], lugar["precio"], lugar["abierto"]) == \
        ("a1", "Taquería", 4.5, 500, 1, True)
    assert len(lugar["extracto"]) == 2 and lugar["extracto"][0]["texto"].endswith("…") and lugar["extracto"][1]["texto"] == "Rápido y rico"


def test_niveles_de_precio():
    ls = places.leer_cercanos(_respuesta(
        _lugar("a", "A", 36.1, -115.1, precio="PRICE_LEVEL_FREE"), _lugar("b", "B", 36.1, -115.1, precio="PRICE_LEVEL_MODERATE"),
        _lugar("c", "C", 36.1, -115.1, precio="PRICE_LEVEL_VERY_EXPENSIVE"), _lugar("d", "D", 36.1, -115.1, precio=None)))
    assert [lugar["precio"] for lugar in ls] == [1, 2, 4, None]


def test_pide_a_google_con_mascara_minima_y_circulo(client, google):
    google.respuesta = _respuesta()
    assert _pedir(client).status_code == 200
    [p] = google.pedidos
    assert p["url"] == places.NEARBY_URL and p["headers"]["X-Goog-FieldMask"] == places.NEARBY_FIELDS
    assert "restaurant" in p["json"]["includedTypes"] and p["json"]["maxResultCount"] <= 20
    assert p["json"]["locationRestriction"]["circle"]["radius"] > 0


def test_filtra_por_precio_y_por_minutos_caminando(client, google):
    google.respuesta = _respuesta(
        _lugar("barato", "Barato", 36.1150, -115.1728, precio="PRICE_LEVEL_INEXPENSIVE"),
        _lugar("medio", "Medio", 36.1152, -115.1728, precio="PRICE_LEVEL_MODERATE"),
        _lugar("caro", "Caro", 36.1150, -115.1730, precio="PRICE_LEVEL_EXPENSIVE"),
        _lugar("lejos", "Lejos", 36.1260, -115.1728, precio="PRICE_LEVEL_INEXPENSIVE"),  # ~1,2 km
        _lugar("sindato", "Sin dato", 36.1150, -115.1727, precio=None))
    ids = lambda r: [lugar["place_id"] for lugar in r.json()["lugares"]]  # noqa: E731
    assert set(ids(_pedir(client, precio=1, minutos=15))) == {"barato", "sindato"}
    assert set(ids(_pedir(client, precio=2, minutos=15))) == {"barato", "medio", "sindato"}
    assert "lejos" not in ids(_pedir(client, precio=2, minutos=15))
    assert len(google.pedidos) == 1  # los filtros no repiten la llamada


def test_distancia_y_minutos_usan_travel(client, google):
    google.respuesta = _respuesta(_lugar("a", "A", 36.1160, -115.1728))
    [lugar] = _pedir(client).json()["lugares"]
    from app import travel
    assert lugar["metros"] == round(travel.metros(STRIP, (36.1160, -115.1728)) * travel.FACTOR_RODEO)
    assert lugar["minutos"] == travel.estimar_minutos(STRIP, (36.1160, -115.1728))


def test_orden_pondera_rating_por_cantidad_de_resenas_y_distancia(client, google):
    google.respuesta = _respuesta(
        _lugar("pocas", "Cinco estrellas con 2 reseñas", 36.1150, -115.1728, rating=5.0, n=2),
        _lugar("muchas", "4,6 con mil reseñas", 36.1150, -115.1729, rating=4.6, n=1000),
        _lugar("cerca", "Mismo puntaje, más cerca", 36.1148, -115.1728, rating=4.6, n=1000),
        _lugar("sinrating", "Sin puntaje", 36.1150, -115.1727, rating=None, n=0))
    ids = [lugar["place_id"] for lugar in _pedir(client, minutos=15).json()["lugares"]]
    assert ids == ["cerca", "muchas", "pocas", "sinrating"]


def test_segunda_llamada_sale_de_cache(client, google):
    google.respuesta = _respuesta(_lugar("a", "A", 36.1150, -115.1728))
    _pedir(client)
    r = _pedir(client, lat=STRIP[0] + 0.0003)  # mismo cuadrado de ~200 m
    assert r.status_code == 200 and len(r.json()["lugares"]) == 1
    assert len(google.pedidos) == 1
    _pedir(client, lat=STRIP[0] + 0.02)  # otro cuadrado
    assert len(google.pedidos) == 2


def test_cache_vence_con_el_ttl(client, google, monkeypatch):
    google.respuesta = _respuesta(_lugar("a", "A", 36.1150, -115.1728))
    t = [1000.0]
    monkeypatch.setattr(comer_api.time, "monotonic", lambda: t[0])
    _pedir(client)
    t[0] += comer_api.TTL_CACHE_S + 1
    _pedir(client)
    assert len(google.pedidos) == 2


def test_abierto_ahora_no_sale_de_una_cache_vieja(client, google, monkeypatch):
    google.respuesta = _respuesta(_lugar("a", "A", 36.1150, -115.1728))
    t = [1000.0]
    monkeypatch.setattr(comer_api.time, "monotonic", lambda: t[0])
    assert _pedir(client).json()["lugares"][0]["abierto"] is True
    t[0] += comer_api.TTL_ABIERTO_S - 1
    assert _pedir(client).json()["lugares"][0]["abierto"] is True  # todavía fresco
    t[0] += 2
    r = _pedir(client).json()["lugares"][0]
    assert r["abierto"] is None  # pasada la media hora no se afirma nada
    assert len(google.pedidos) == 1  # y la lista sigue saliendo de la cache


def test_no_cachea_listas_vacias(client, google):
    google.respuesta = _respuesta()
    _pedir(client)
    _pedir(client)
    assert len(google.pedidos) == 2


def test_limite_por_usuario_solo_cuenta_llamadas_a_google(client, google, monkeypatch):
    monkeypatch.setattr(comer_api, "_limite", comer_api.limites.Limite(2, 3600))
    google.respuesta = _respuesta(_lugar("a", "A", 36.1150, -115.1728))
    for i in range(2):
        assert _pedir(client, lat=STRIP[0] + i * 0.05).status_code == 200
    assert _pedir(client, lat=STRIP[0]).status_code == 200  # caché: no gasta cupo
    assert _pedir(client, lat=STRIP[0] + 0.5).status_code == 429


def test_sin_clave_dice_que_no_esta_disponible(client, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_PLACES_SERVER_KEY", "")
    monkeypatch.setattr(config, "GOOGLE_MAPS_API_KEY", "")
    r = _pedir(client)
    assert r.status_code == 503 and "no está disponible" in r.json()["detail"]


def test_error_de_google_es_503_sin_filtrar_el_detalle(client, monkeypatch):
    monkeypatch.setattr(places.httpx, "post", lambda *a, **k: type("R", (), {"status_code": 403, "text": "secreto"})())
    r = _pedir(client)
    assert r.status_code == 503 and "secreto" not in r.text


def test_origen_desde_la_proxima_sesion(client, google, monkeypatch):
    sesion = {"title": "Charla", "venue": {"hotel": "MGM Grand", "lat": STRIP[0], "lng": STRIP[1]}}
    monkeypatch.setattr(today, "for_user", lambda u: {"now": None, "next": sesion, "upcoming": None})
    google.respuesta = _respuesta(_lugar("a", "A", 36.1150, -115.1728))
    r = client.get("/api/comer")
    assert r.status_code == 200
    assert r.json()["origen"] == {"lat": STRIP[0], "lng": STRIP[1], "nombre": "MGM Grand", "fuente": "sesion"}
    assert google.pedidos[0]["json"]["locationRestriction"]["circle"]["center"]["latitude"] == pytest.approx(STRIP[0], abs=0.002)


def test_origen_del_telefono_tiene_prioridad(client, google, monkeypatch):
    monkeypatch.setattr(today, "for_user", lambda u: pytest.fail("no debería mirar el itinerario"))
    google.respuesta = _respuesta()
    assert _pedir(client).json()["origen"]["fuente"] == "telefono"


def test_sin_origen_ni_sesion_con_coordenadas(client, google, monkeypatch):
    monkeypatch.setattr(today, "for_user", lambda u: {"now": None, "next": {"venue": {"hotel": "Various", "lat": None}},
                                                      "upcoming": None})
    r = client.get("/api/comer")
    assert r.status_code == 404 and "ubicación" in r.json()["detail"] and not google.pedidos


@pytest.mark.parametrize("params", [{"lat": 91, "lng": 0}, {"lat": 10}, {"lat": 36, "lng": -115, "precio": 3},
                                    {"lat": 36, "lng": -115, "minutos": 99}])
def test_valida_parametros(client, google, params):
    assert client.get("/api/comer", params=params).status_code == 422


def test_exige_login():
    with TestClient(app) as c:
        assert c.get("/api/comer", params={"lat": 1, "lng": 1}).status_code in (401, 403)


# ---------- por tipo de lugar ----------

def test_sin_tipo_busca_todo_como_antes(client, google):
    _pedir(client)
    [p] = google.pedidos
    assert p["json"]["includedTypes"] == places.TIPOS_COMER
    assert "excludedPrimaryTypes" not in p["json"]


@pytest.mark.parametrize(("tipo", "incluye", "no_incluye"), [
    ("rapida", "fast_food_restaurant", "restaurant"),
    ("dulces", "chocolate_shop", "restaurant"),
    ("cafe", "coffee_shop", "fast_food_restaurant"),
    ("restaurantes", "restaurant", "candy_store")])
def test_cada_tipo_pide_a_google_sus_categorias(client, google, tipo, incluye, no_incluye):
    assert _pedir(client, tipo=tipo).status_code == 200
    [p] = google.pedidos
    assert incluye in p["json"]["includedTypes"]
    assert no_incluye not in p["json"]["includedTypes"]


def test_restaurantes_deja_afuera_la_comida_rapida(client, google):
    _pedir(client, tipo="restaurantes")
    [p] = google.pedidos
    assert "fast_food_restaurant" in p["json"]["excludedPrimaryTypes"]


def test_cada_tipo_tiene_su_propia_cache(client, google):
    google.respuesta = _respuesta(_lugar("a", "A", 36.1150, -115.1728))
    _pedir(client)
    _pedir(client, tipo="dulces")
    _pedir(client)
    _pedir(client, tipo="dulces")
    assert [p["json"]["includedTypes"] == places.TIPOS_COMER for p in google.pedidos] == [True, False]


def test_tipo_desconocido_da_422(client, google):
    assert _pedir(client, tipo="cualquiera").status_code == 422
    assert not google.pedidos


def test_cada_lugar_dice_que_tipo_de_lugar_es(client, google):
    google.respuesta = _respuesta(_lugar("h", "Hershey's Chocolate World", 36.1150, -115.1728,
                                         primaryTypeDisplayName={"text": "Tienda de chocolate"}))
    [lugar] = _pedir(client, tipo="dulces").json()["lugares"]
    assert lugar["tipo"] == "Tienda de chocolate"
    assert "places.primaryTypeDisplayName" in places.NEARBY_FIELDS.split(",")

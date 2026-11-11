"""Mis eventos (los de proveedores que carga cada uno): alta, edición y baja, ubicación (sede o Google Places) y que
entren al itinerario, a Hoy y a los avisos como cualquier ítem fijado. Google se reemplaza por funciones falsas."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import changes, db, itinerary, places, push, sandbox, venues
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_PASSWORD, TEST_USER, login_headers

DIA = "2026-12-01"
SEDES = [{"id_sede": 5, "nombre": "MGM Grand", "lat": 36.102219, "lng": -115.169517, "direccion": "3799 Las Vegas Blvd S"}]
LUGAR = {"place_id": "ChIJtopgolf123", "nombre": "Topgolf Las Vegas", "direccion": "4627 Koval Ln, Las Vegas, NV",
         "lat": 36.1072, "lng": -115.1641}


# ---------- Google Places (lectura pura) ----------

def test_lee_las_sugerencias_del_autocompletar():
    respuesta = {"suggestions": [
        {"placePrediction": {"placeId": "ChIJ1", "text": {"text": "Topgolf, Koval Lane, Las Vegas"},
                             "structuredFormat": {"mainText": {"text": "Topgolf"},
                                                  "secondaryText": {"text": "Koval Lane, Las Vegas"}}}},
        {"queryPrediction": {"text": {"text": "topgolf near me"}}},  # búsquedas sugeridas: no son lugares
    ]}

    assert places.leer_sugerencias(respuesta) == [
        {"place_id": "ChIJ1", "nombre": "Topgolf", "direccion": "Koval Lane, Las Vegas"}]


def test_lee_el_detalle_de_un_lugar():
    respuesta = {"id": "ChIJ1", "displayName": {"text": "Topgolf"}, "formattedAddress": "4627 Koval Ln",
                 "location": {"latitude": 36.1, "longitude": -115.1}}

    assert places.leer_lugar(respuesta) == {"place_id": "ChIJ1", "nombre": "Topgolf", "direccion": "4627 Koval Ln",
                                            "lat": 36.1, "lng": -115.1}


# ---------- API ----------

@pytest.fixture
def client(monkeypatch):
    with TestClient(app) as c:
        venues.load(SEDES)
        llamadas = []
        monkeypatch.setattr(places, "details", lambda pid, sesion=None: llamadas.append(pid) or {**LUGAR, "place_id": pid})
        monkeypatch.setattr(places, "autocomplete", lambda q, sesion=None: [
            {"place_id": "ChIJ1", "nombre": f"{q} Las Vegas", "direccion": "Koval Ln"}])
        c.llamadas_places = llamadas
        yield c


@pytest.fixture
def headers(client):
    h = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    yield h
    for ev in db.list_user_events(TEST_ADMIN):
        db.delete_user_event(TEST_ADMIN, ev["id"])
    for it in db.list_itinerary_items(TEST_ADMIN):
        db.remove_item(TEST_ADMIN, it["code"])


def _alta(client, headers, **kw):
    body = {"nombre": "Cena Datadog", "dia": DIA, "inicio": "19:00", "fin": "22:00", "id_sede": 5, **kw}
    return client.post("/api/my-events", headers=headers, json=body)


def _del_dia(username):
    return next(d["sessions"] for d in itinerary.get_current(username)["days"] if d["day"] == DIA)


def test_un_evento_en_una_sede_queda_fijado_en_el_itinerario(client, headers):
    r = _alta(client, headers, nota="Llevar tarjetas")
    assert r.status_code == 200, r.text
    ev = r.json()

    item = _del_dia(TEST_ADMIN)[0]
    assert (item["kind"], item["code"], item["locked"]) == ("mine", ev["code"], True)
    assert (item["title"], item["start"], item["end"], item["type"]) == ("Cena Datadog", "19:00", "22:00", "Mi evento")
    assert (item["venue"]["hotel"], item["venue"]["lat"]) == ("MGM Grand", 36.102219)
    assert item["note"] == "Llevar tarjetas"


def test_con_un_lugar_de_google_guarda_las_coordenadas_una_sola_vez(client, headers):
    ev = _alta(client, headers, id_sede=None, place_id="ChIJtopgolf123", sesion="3f1c9e7a-1111-4222-8333-444455556666").json()
    client.get("/api/itinerary", headers=headers)
    client.get("/api/itinerary", headers=headers)

    assert client.llamadas_places == ["ChIJtopgolf123"]  # al dar de alta; después sale de la base
    assert (ev["venue"]["hotel"], ev["venue"]["lat"], ev["venue"]["place_id"]) == ("Topgolf Las Vegas", 36.1072, "ChIJtopgolf123")


def test_con_una_direccion_escrita_a_mano_queda_sin_coordenadas(client, headers):
    ev = _alta(client, headers, id_sede=None, direccion="Suite 1203, Wynn").json()

    assert (ev["venue"]["hotel"], ev["venue"]["lat"]) == ("Suite 1203, Wynn", None)


def test_hace_falta_un_lugar_y_datos_validos(client, headers):
    assert _alta(client, headers, id_sede=None).status_code == 422
    assert _alta(client, headers, nombre="").status_code == 422
    assert _alta(client, headers, inicio="25:00").status_code == 422
    assert _alta(client, headers, id_sede=99).status_code == 422
    assert _alta(client, headers, id_sede=None, place_id="../../etc").status_code == 422


def test_editar_mueve_el_item_sin_avisar_un_cambio(client, headers):
    ev = _alta(client, headers).json()

    r = client.put(f"/api/my-events/{ev['id']}", headers=headers,
                   json={"nombre": "Cena Datadog (VIP)", "dia": DIA, "inicio": "20:00", "fin": None, "id_sede": 5})
    item = _del_dia(TEST_ADMIN)[0]

    assert r.status_code == 200
    assert (item["title"], item["start"]) == ("Cena Datadog (VIP)", "20:00")
    assert changes.pending(TEST_ADMIN) == []  # lo cambió la persona: no es una novedad para avisarle


def test_borrar_desde_mis_eventos_o_desde_el_itinerario(client, headers):
    a, b = _alta(client, headers).json(), _alta(client, headers, nombre="Desayuno Snowflake", inicio="07:30", fin="08:30").json()

    assert client.delete(f"/api/my-events/{a['id']}", headers=headers).status_code == 200
    client.delete(f"/api/itinerary/items/{b['code']}", headers=headers)

    assert db.list_user_events(TEST_ADMIN) == []
    assert db.list_itinerary_items(TEST_ADMIN) == []


def test_son_privados(client, headers):
    ev = _alta(client, headers).json()
    otro = login_headers(client, TEST_USER, TEST_PASSWORD)

    assert client.get("/api/my-events", headers=otro).json()["eventos"] == []
    assert client.put(f"/api/my-events/{ev['id']}", headers=otro,
                      json={"nombre": "x", "dia": DIA, "inicio": "10:00", "id_sede": 5}).status_code == 404
    assert client.delete(f"/api/my-events/{ev['id']}", headers=otro).status_code == 404


def test_el_aviso_push_lleva_al_itinerario(client, headers):
    _alta(client, headers)
    card = _del_dia(TEST_ADMIN)[0]
    ahora = dt.datetime(2026, 12, 1, 18, 45, tzinfo=sandbox.EVENT_TZ)

    clave, mensaje = push._notice(card, ahora)

    assert clave.startswith("leave:") and mensaje["url"] == "/#/itinerario"


def test_autocompletar_pide_al_menos_tres_letras(client, headers):
    assert client.get("/api/places/autocomplete", headers=headers, params={"q": "to"}).status_code == 422
    r = client.get("/api/places/autocomplete", headers=headers, params={"q": "topgolf"})

    assert r.json()["lugares"][0]["place_id"] == "ChIJ1"


def test_autocompletar_sin_key_avisa(client, headers, monkeypatch):
    def sin_key(q, sesion=None):
        raise places.PlacesNoDisponible("Falta GOOGLE_MAPS_API_KEY")
    monkeypatch.setattr(places, "autocomplete", sin_key)

    assert client.get("/api/places/autocomplete", headers=headers, params={"q": "topgolf"}).status_code == 503


def test_lista_las_sedes_con_coordenadas_para_el_formulario(client, headers):
    assert client.get("/api/my-events/sedes", headers=headers).json()["sedes"] == [{"id": 5, "nombre": "MGM Grand"}]

"""API de Viajes: alta y baja de vuelos y hoteles, validación y aislamiento por usuario."""
import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers


@pytest.fixture
def cli():
    with TestClient(app) as c:
        c.H = login_headers(c)
        c.H2 = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        _limpiar()
        yield c
        _limpiar()


def _limpiar():
    with db.conn() as c:
        for t in ("viajes_vuelos", "viajes_hoteles"):
            c.execute(f"DELETE FROM {t} WHERE username IN (%s,%s)", (TEST_USER, TEST_ADMIN))
        c.execute("DELETE FROM preferencias_avisos WHERE username IN (%s,%s)", (TEST_USER, TEST_ADMIN))


VUELO = {"numero": "ar 1302", "fecha": "2026-11-28", "hora": "21:05"}
HOTEL = {"nombre": "Venetian", "direccion": "3355 S Las Vegas Blvd", "checkin": "2026-11-29T15:00",
         "checkout": "2026-12-04T11:00"}


def test_agrega_un_vuelo_normaliza_el_numero_y_calcula_cuando_abre_el_check_in(cli):
    r = cli.post("/api/viajes/vuelos", headers=cli.H, json=VUELO)

    assert r.status_code == 201
    v = r.json()
    assert v["numero"] == "AR1302" and v["checkin_abre"] == "2026-11-27T21:05" and v["checkin_horas"] == 24
    assert cli.get("/api/viajes", headers=cli.H).json()["vuelos"][0]["id"] == v["id"]


@pytest.mark.parametrize("cambio", [{"numero": "hola"}, {"hora": "25:00"}, {"zona": "Mars/Base"}, {"fecha": "ayer"}])
def test_rechaza_vuelos_mal_cargados(cli, cambio):
    assert cli.post("/api/viajes/vuelos", headers=cli.H, json={**VUELO, **cambio}).status_code == 422


def test_agrega_y_quita_un_hotel(cli):
    h = cli.post("/api/viajes/hoteles", headers=cli.H, json=HOTEL).json()

    assert h["nombre"] == "Venetian" and h["zona"] == "America/Los_Angeles"
    assert cli.delete(f"/api/viajes/hoteles/{h['id']}", headers=cli.H).status_code == 200
    assert cli.delete(f"/api/viajes/hoteles/{h['id']}", headers=cli.H).status_code == 404


def test_el_check_out_va_despues_del_check_in(cli):
    r = cli.post("/api/viajes/hoteles", headers=cli.H, json={**HOTEL, "checkout": "2026-11-29T10:00"})

    assert r.status_code == 422


def test_cada_persona_ve_y_borra_solo_lo_suyo(cli):
    v = cli.post("/api/viajes/vuelos", headers=cli.H, json=VUELO).json()

    assert cli.get("/api/viajes", headers=cli.H2).json()["vuelos"] == []
    assert cli.delete(f"/api/viajes/vuelos/{v['id']}", headers=cli.H2).status_code == 404
    assert cli.delete(f"/api/viajes/vuelos/{v['id']}", headers=cli.H).status_code == 200


def test_las_preferencias_arrancan_prendidas_y_se_guardan_sin_pisar_las_de_grabar(cli):
    assert cli.get("/api/viajes/preferencias", headers=cli.H).json() == {
        "viajes_checkin": True, "viajes_hoteles": True, "viajes_estado": True}
    cli.put("/api/push/preferencias", headers=cli.H, json={"grabar": False, "ubicacion": False})

    r = cli.put("/api/viajes/preferencias", headers=cli.H, json={
        "viajes_checkin": False, "viajes_hoteles": True, "viajes_estado": False})

    assert r.json() == {"viajes_checkin": False, "viajes_hoteles": True, "viajes_estado": False}
    assert cli.get("/api/push/preferencias", headers=cli.H).json()["grabar"] is False


def test_el_guardado_de_push_no_apaga_los_avisos_de_viajes(cli):
    cli.put("/api/viajes/preferencias", headers=cli.H, json={
        "viajes_checkin": False, "viajes_hoteles": False, "viajes_estado": False})

    cli.put("/api/push/preferencias", headers=cli.H, json={"grabar": True, "ubicacion": False})

    assert cli.get("/api/viajes/preferencias", headers=cli.H).json()["viajes_checkin"] is False


def test_sin_sesion_no_entra(cli):
    assert cli.get("/api/viajes").status_code == 401


def test_sale_de_cualquier_ciudad_y_muestra_la_que_eligio(cli):
    houston = {**VUELO, "numero": "UA1799", "zona": "America/Chicago", "ciudad": "Houston"}

    v = cli.post("/api/viajes/vuelos", headers=cli.H, json=houston).json()

    assert v["zona_nombre"] == "Houston"
    assert v["salida"] == "2026-11-28T21:05"  # la hora cargada, en la zona de Houston


def test_un_vuelo_sin_ciudad_muestra_el_nombre_de_la_zona(cli):
    v = cli.post("/api/viajes/vuelos", headers=cli.H, json={**VUELO, "zona": "Europe/Rome"}).json()

    assert v["zona_nombre"] == "Rome"


def test_busca_la_ciudad_de_salida_mientras_se_escribe(cli):
    r = cli.get("/api/viajes/ciudades", headers=cli.H, params={"q": "hou"})

    assert r.status_code == 200
    assert r.json()["ciudades"][0] == {"nombre": "Houston", "pais": "US", "zona": "America/Chicago"}


def test_buscar_ciudades_pide_sesion_y_una_consulta(cli):
    assert cli.get("/api/viajes/ciudades", params={"q": "hou"}).status_code == 401
    assert cli.get("/api/viajes/ciudades", headers=cli.H, params={"q": ""}).status_code == 422

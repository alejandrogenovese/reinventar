"""API de Viajes: alta, edición y baja de vuelos y hoteles, validación, aislamiento por usuario y reseteo de avisos."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import db, viajes_avisos, vuelos
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
        c.execute("DELETE FROM push_sent WHERE username IN (%s,%s) AND key ~ '^(vcheckin|vcancel|vdemora|vpuerta|vcinta|hin|hout):'",
                  (TEST_USER, TEST_ADMIN))


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


# ---------- editar ----------

def _marcas(username: str, id_: str) -> set[str]:
    with db.conn() as c:
        return {r["key"] for r in c.execute("SELECT key FROM push_sent WHERE username=%s AND key LIKE %s",
                                            (username, f"%:{id_}%")).fetchall()}


def _marcar(username: str, *claves: str) -> None:
    for clave in claves:
        db.mark_push_sent(username, clave)


def _con_estado(username: str, id_: str) -> None:
    vuelos.guardar_estado(username, id_, {"salida_utc": 1.8e9, "demora_min": 40, "puerta": "B12", "terminal": "A",
                                          "estado": "Delayed", "consultado_en": 1.7e9, "destino_iata": "IAH",
                                          "llegada_utc": 1.8e9 + 3600, "llegada_cinta": "7", "matricula": "N1"})


def test_edita_un_vuelo_y_devuelve_la_ficha_actualizada(cli):
    v = cli.post("/api/viajes/vuelos", headers=cli.H, json=VUELO).json()

    r = cli.put(f"/api/viajes/vuelos/{v['id']}", headers=cli.H, json={
        **VUELO, "numero": "ua 1799", "aerolinea": "United", "hora": "08:30", "zona": "America/Chicago", "ciudad": "Houston"})

    assert r.status_code == 200
    e = r.json()
    assert e["id"] == v["id"] and e["numero"] == "UA1799" and e["aerolinea"] == "United"
    assert e["zona_nombre"] == "Houston" and e["salida"] == "2026-11-28T08:30"
    assert [x["id"] for x in cli.get("/api/viajes", headers=cli.H).json()["vuelos"]] == [v["id"]]


@pytest.mark.parametrize("cambio", [{"numero": "hola"}, {"hora": "25:00"}, {"zona": "Mars/Base"}, {"fecha": "ayer"}])
def test_rechaza_ediciones_de_vuelo_mal_cargadas(cli, cambio):
    v = cli.post("/api/viajes/vuelos", headers=cli.H, json=VUELO).json()

    assert cli.put(f"/api/viajes/vuelos/{v['id']}", headers=cli.H, json={**VUELO, **cambio}).status_code == 422


def test_otra_persona_no_puede_editar_el_vuelo_ni_el_hotel(cli):
    v = cli.post("/api/viajes/vuelos", headers=cli.H, json=VUELO).json()
    h = cli.post("/api/viajes/hoteles", headers=cli.H, json=HOTEL).json()

    assert cli.put(f"/api/viajes/vuelos/{v['id']}", headers=cli.H2, json={**VUELO, "numero": "AA1"}).status_code == 404
    assert cli.put(f"/api/viajes/hoteles/{h['id']}", headers=cli.H2, json={**HOTEL, "nombre": "Otro"}).status_code == 404
    assert cli.put("/api/viajes/vuelos/noexiste", headers=cli.H, json=VUELO).status_code == 404
    assert cli.get("/api/viajes", headers=cli.H).json()["vuelos"][0]["numero"] == "AR1302"
    assert cli.get("/api/viajes", headers=cli.H).json()["hoteles"][0]["nombre"] == "Venetian"


def test_cambiar_la_salida_del_vuelo_resetea_estado_y_avisos(cli):
    v = cli.post("/api/viajes/vuelos", headers=cli.H, json=VUELO).json()
    _con_estado(TEST_USER, v["id"])
    _marcar(TEST_USER, f"vcheckin:{v['id']}", f"vcancel:{v['id']}", f"vdemora:{v['id']}:0>40", f"vpuerta:{v['id']}:B12",
            f"vcinta:{v['id']}:7")
    viajes_avisos._pendientes[(TEST_USER, f"vpuerta:{v['id']}:B12")] = (v["id"], {"puerta": "B12"})

    r = cli.put(f"/api/viajes/vuelos/{v['id']}", headers=cli.H, json={**VUELO, "fecha": "2026-11-29"})

    e = r.json()
    assert e["demora_min"] is None and e["puerta"] is None and e["estado"] is None and e["salida"] == "2026-11-29T21:05"
    assert e["destino_iata"] is None and e["llegada"] is None and e["llegada_cinta"] is None and e["matricula"] is None
    guardado = vuelos.get_vuelo(TEST_USER, v["id"])
    assert guardado["salida_utc"] is None and guardado["consultado_en"] is None and guardado["llegada_utc"] is None
    assert _marcas(TEST_USER, v["id"]) == set()
    assert (TEST_USER, f"vpuerta:{v['id']}:B12") not in viajes_avisos._pendientes


def test_cambiar_solo_la_aerolinea_no_repite_avisos(cli):
    v = cli.post("/api/viajes/vuelos", headers=cli.H, json=VUELO).json()
    _con_estado(TEST_USER, v["id"])
    _marcar(TEST_USER, f"vcheckin:{v['id']}")
    viajes_avisos._pendientes[(TEST_USER, f"vpuerta:{v['id']}:B12")] = (v["id"], {"puerta": "B12"})

    e = cli.put(f"/api/viajes/vuelos/{v['id']}", headers=cli.H, json={**VUELO, "aerolinea": "Aerolíneas"}).json()

    assert e["aerolinea"] == "Aerolíneas" and e["puerta"] == "B12" and e["demora_min"] == 40
    assert _marcas(TEST_USER, v["id"]) == {f"vcheckin:{v['id']}"}
    assert viajes_avisos._pendientes.pop((TEST_USER, f"vpuerta:{v['id']}:B12"))


def test_edita_un_hotel_y_valida_las_fechas(cli):
    h = cli.post("/api/viajes/hoteles", headers=cli.H, json=HOTEL).json()

    r = cli.put(f"/api/viajes/hoteles/{h['id']}", headers=cli.H, json={**HOTEL, "nombre": "Wynn", "direccion": ""})
    malo = cli.put(f"/api/viajes/hoteles/{h['id']}", headers=cli.H, json={**HOTEL, "checkout": "2026-11-29T10:00"})
    sin_nombre = cli.put(f"/api/viajes/hoteles/{h['id']}", headers=cli.H, json={**HOTEL, "nombre": ""})

    assert r.status_code == 200 and r.json()["nombre"] == "Wynn" and r.json()["direccion"] == ""
    assert malo.status_code == 422 and sin_nombre.status_code == 422


@pytest.mark.parametrize(("cambio", "quedan"), [
    ({"nombre": "Wynn"}, {"hin", "hout"}),               # el nombre no repite avisos
    ({"checkout": "2026-12-05T11:00"}, {"hin"}),           # otro check-out: se vuelve a avisar solo ese
    ({"checkin": "2026-11-30T15:00"}, set()),              # otro check-in: los dos (el check-out arranca desde ahí)
    ({"zona": "America/New_York"}, set()),
])
def test_editar_el_hotel_resetea_solo_los_avisos_que_cambian(cli, cambio, quedan):
    h = cli.post("/api/viajes/hoteles", headers=cli.H, json=HOTEL).json()
    _marcar(TEST_USER, f"hin:{h['id']}", f"hout:{h['id']}")

    assert cli.put(f"/api/viajes/hoteles/{h['id']}", headers=cli.H, json={**HOTEL, **cambio}).status_code == 200

    assert _marcas(TEST_USER, h["id"]) == {f"{k}:{h['id']}" for k in quedan}


def test_la_ficha_del_vuelo_trae_destino_llegada_y_avion(cli):
    v = cli.post("/api/viajes/vuelos", headers=cli.H, json=VUELO).json()
    llega = dt.datetime(2026, 11, 30, 3, 33, tzinfo=dt.UTC).timestamp()
    vuelos.guardar_estado(TEST_USER, v["id"], {"destino_iata": "IAH", "destino_nombre": "Houston", "llegada_utc": llega,
                                               "llegada_terminal": "C", "llegada_cinta": "7", "checkin_desk": "E1",
                                               "aeronave": "Boeing 737", "matricula": "N1"})

    e = cli.get("/api/viajes", headers=cli.H).json()["vuelos"][0]

    assert (e["destino_iata"], e["destino_nombre"], e["llegada_terminal"], e["llegada_cinta"]) == ("IAH", "Houston", "C", "7")
    assert (e["checkin_desk"], e["aeronave"], e["matricula"]) == ("E1", "Boeing 737", "N1")
    assert e["llegada"] == "2026-11-30T00:33"   # sin la hora local del destino, en la zona del vuelo (Buenos Aires)

    vuelos.guardar_estado(TEST_USER, v["id"], {"llegada_local": "2026-11-29T21:33"})
    assert cli.get("/api/viajes", headers=cli.H).json()["vuelos"][0]["llegada"] == "2026-11-29T21:33"

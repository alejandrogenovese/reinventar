"""La vuelta desde Las Vegas: hora de salir del hotel (app/vuelta.py), que coincida con web/js/vuelta.js, y el ítem
«Salí al aeropuerto» de «Próximo» (app/proximo.py). Sin red ni base."""
import datetime as dt
import re
from pathlib import Path

from app import proximo, sandbox, vuelta

LV = sandbox.EVENT_TZ
JS = (Path(__file__).resolve().parent.parent / "web" / "js" / "vuelta.js").read_text()


def _lv(texto):
    return dt.datetime.fromisoformat(texto).replace(tzinfo=LV)


def _vuelo(**kw):
    # La vuelta del viaje: lun 7/12 13:00 de Las Vegas.
    return {"id": "v9", "numero": "UA1234", "fecha": "2026-12-07", "hora": "13:00", "zona": "America/Los_Angeles",
            "ciudad": "Las Vegas", "salida_utc": None, "demora_min": None, "puerta": None, "estado": None,
            "destino_nombre": None, "destino_iata": None, **kw}


def _constante_js(nombre):
    return int(re.search(rf"export const {nombre} = (\d+);", JS).group(1))


def test_las_constantes_coinciden_con_el_front():
    for nombre in ("ANTICIPACION_INTERNACIONAL_MIN", "ANTICIPACION_DOMESTICO_MIN", "TRASLADO_STRIP_MIN"):
        assert getattr(vuelta, nombre) == _constante_js(nombre), nombre
    lista = re.search(r"AEROPUERTOS_EEUU = Object\.freeze\(\[(.*?)\]\)", JS, re.S).group(1)
    assert set(re.findall(r'"([A-Z]{3})"', lista)) == vuelta.AEROPUERTOS_EEUU


def test_internacional_o_desconocido_sale_3_h_25_min_antes():
    assert vuelta.salir_al_aeropuerto(_vuelo()) == _lv("2026-12-07T09:35")
    assert vuelta.salir_al_aeropuerto(_vuelo(destino_iata="PTY")) == _lv("2026-12-07T09:35")


def test_domestico_sale_2_h_25_min_antes():
    assert vuelta.salir_al_aeropuerto(_vuelo(destino_iata="iah")) == _lv("2026-12-07T10:35")


def test_solo_vuelos_que_salen_de_las_vegas_y_no_cancelados():
    assert vuelta.salir_al_aeropuerto(_vuelo(ciudad="Los Ángeles")) is None
    assert vuelta.salir_al_aeropuerto(_vuelo(zona="America/Argentina/Buenos_Aires", ciudad="Buenos Aires")) is None
    assert vuelta.salir_al_aeropuerto(_vuelo(estado="Cancelled")) is None
    assert vuelta.salir_al_aeropuerto(_vuelo(hora=None)) is None
    # Un vuelo viejo sin ciudad usa el nombre de la zona («Las Vegas»).
    assert vuelta.salir_al_aeropuerto(_vuelo(ciudad="")) == _lv("2026-12-07T09:35")


def test_proximo_muestra_sali_al_aeropuerto_desde_3_h_antes():
    v = _vuelo(destino_iata="IAH")   # doméstico: salir 10:35
    assert proximo.elegir([v], [], None, _lv("2026-12-07T07:34"))["tipo"] == "vuelo"
    p = proximo.elegir([v], [], None, _lv("2026-12-07T07:35"))
    assert p["tipo"] == "aeropuerto" and p["titulo"] == "Salí al aeropuerto" and p["hora"] == "10:35"
    assert p["detalle"] == "UA1234 sale 13:00" and p["url"] == "#/viajes/vuelo/v9"
    # Pasada la hora de salir, queda el vuelo.
    assert proximo.elegir([v], [], None, _lv("2026-12-07T10:35"))["tipo"] == "vuelo"


def test_proximo_aeropuerto_gana_al_check_out_que_empieza_despues():
    hotel = {"id": "h1", "nombre": "Venetian", "direccion": "", "zona": "America/Los_Angeles",
             "checkin": "2026-11-29T15:00", "checkout": "2026-12-07T11:00"}
    p = proximo.elegir([_vuelo()], [hotel], None, _lv("2026-12-07T08:00"))
    assert p["tipo"] == "aeropuerto" and p["hora"] == "09:35"


def test_proximo_no_muestra_aeropuerto_para_la_ida():
    ida = _vuelo(zona="America/Argentina/Buenos_Aires", ciudad="Buenos Aires", fecha="2026-11-29", hora="10:00")
    p = proximo.elegir([ida], [], None, dt.datetime(2026, 11, 29, 9, tzinfo=dt.UTC))
    assert p["tipo"] == "vuelo"

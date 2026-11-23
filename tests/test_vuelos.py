"""Vuelos: número, ventana de check-in por aerolínea, lectura de AeroDataBox y detección de cambios. Sin red."""
import datetime as dt

import httpx
import pytest

from app import config, vuelos

BUE = "America/Argentina/Buenos_Aires"


def _vuelo(**kw):
    return {"id": "v1", "numero": "AR1302", "aerolinea": "", "fecha": "2026-11-28", "hora": "21:05", "zona": BUE,
            "salida_utc": None, "demora_min": None, "puerta": None, "estado": None, "consultado_en": None, **kw}


def _raw(sched="2026-11-29 00:05Z", revised="2026-11-29 00:50Z", gate="B12", status="Expected"):
    return [{"number": "AR 1302", "status": status,
             "departure": {"scheduledTime": {"utc": sched, "local": "2026-11-28 21:05-03:00"},
                           "revisedTime": {"utc": revised} if revised else None, "gate": gate, "terminal": "A"}}]


@pytest.mark.parametrize("texto, esperado", [("ar1302", "AR1302"), (" AA 123 ", "AA123"), ("UA 1234A", "UA1234A")])
def test_normaliza_el_numero_de_vuelo(texto, esperado):
    assert vuelos.normalizar_numero(texto) == esperado


@pytest.mark.parametrize("texto", ["", "1302", "ARGENTINA1", "AR", "AR12345", "A", "AR 13 02 99"])
def test_rechaza_numeros_que_no_son_de_vuelo(texto):
    with pytest.raises(ValueError):
        vuelos.normalizar_numero(texto)


def test_el_check_in_abre_24_h_antes_por_defecto():
    abre = vuelos.abre_checkin(_vuelo(numero="XX100"))

    assert abre == dt.datetime(2026, 11, 27, 21, 5, tzinfo=vuelos.zona(BUE))


def test_la_ventana_depende_de_la_aerolinea(monkeypatch):
    monkeypatch.setitem(vuelos.CHECKIN_WEB, "ZZ", {"horas": 48, "url": "https://ejemplo.invalid/checkin"})

    abre = vuelos.abre_checkin(_vuelo(numero="ZZ77"))

    assert abre == dt.datetime(2026, 11, 26, 21, 5, tzinfo=vuelos.zona(BUE))
    assert vuelos.url_checkin("ZZ77") == "https://ejemplo.invalid/checkin"
    assert vuelos.url_checkin("XX1") is None


def test_sin_hora_ni_salida_no_hay_ventana():
    assert vuelos.abre_checkin(_vuelo(hora=None)) is None


def test_la_salida_que_informa_aerodatabox_manda_sobre_la_hora_cargada():
    salida = dt.datetime(2026, 11, 29, 0, 5, tzinfo=dt.UTC).timestamp()

    assert vuelos.salida(_vuelo(hora="10:00", salida_utc=salida)) == dt.datetime(2026, 11, 29, 0, 5, tzinfo=dt.UTC)


def test_lee_demora_puerta_y_salida_de_la_respuesta():
    r = vuelos.leer_estado(_raw(), "2026-11-28")

    assert r["demora_min"] == 45
    assert r["puerta"] == "B12" and r["terminal"] == "A" and r["estado"] == "Expected"
    assert r["salida_utc"] == dt.datetime(2026, 11, 29, 0, 5, tzinfo=dt.UTC).timestamp()


def test_sin_hora_revisada_la_demora_es_cero():
    assert vuelos.leer_estado(_raw(revised=None), "2026-11-28")["demora_min"] == 0


def test_respuesta_vacia_o_rara_da_none():
    assert vuelos.leer_estado([], "2026-11-28") is None
    assert vuelos.leer_estado([{"number": "AR1"}], "2026-11-28") is None


def test_elige_el_vuelo_del_dia_pedido():
    otro = _raw(sched="2026-11-30 00:05Z", gate="Z9")[0]
    otro["departure"]["scheduledTime"]["local"] = "2026-11-29 21:05-03:00"

    assert vuelos.leer_estado([otro, *_raw()], "2026-11-28")["puerta"] == "B12"


# ---------- cambios ----------

def test_avisa_si_la_demora_cambia_15_min_o_mas():
    nuevo = {"demora_min": 15, "puerta": None, "estado": "Expected"}

    assert vuelos.cambios(_vuelo(), nuevo) == [("demora", 15)]


def test_no_avisa_con_menos_de_15_min_de_diferencia():
    assert vuelos.cambios(_vuelo(demora_min=10), {"demora_min": 24, "puerta": None, "estado": "Expected"}) == []


def test_la_demora_se_compara_con_la_ultima_avisada_no_con_la_anterior():
    # 10 min no avisó; 20 min sí (contra 0 avisado), aunque desde los 10 sean solo 10
    assert vuelos.cambios(_vuelo(demora_min=None), {"demora_min": 20, "puerta": None, "estado": None}) == [("demora", 20)]


def test_avisa_puerta_nueva_y_puerta_cambiada_pero_no_la_misma():
    assert vuelos.cambios(_vuelo(), {"demora_min": 0, "puerta": "B12", "estado": None}) == [("puerta", "B12")]
    assert vuelos.cambios(_vuelo(puerta="B12"), {"demora_min": 0, "puerta": "C3", "estado": None}) == [("puerta", "C3")]
    assert vuelos.cambios(_vuelo(puerta="B12"), {"demora_min": 0, "puerta": "B12", "estado": None}) == []
    assert vuelos.cambios(_vuelo(puerta="B12"), {"demora_min": 0, "puerta": None, "estado": None}) == []


def test_avisa_la_cancelacion_una_sola_vez():
    assert vuelos.cambios(_vuelo(), {"demora_min": 0, "puerta": None, "estado": "Canceled"}) == [("cancelado", None)]
    assert vuelos.cambios(_vuelo(estado="Canceled"), {"demora_min": 0, "puerta": None, "estado": "Canceled"}) == []


# ---------- consulta a AeroDataBox (httpx mockeado) ----------

@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(config, "AERODATABOX_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(config, "AERODATABOX_TOPE_DIARIO", 3)
    monkeypatch.setattr(vuelos, "_persistir_contador", False)   # sin tocar la base
    vuelos.reiniciar_consultas()


class Http:
    def __init__(self, respuesta):
        self.respuesta, self.pedidos = respuesta, []

    def get(self, url, **kw):
        self.pedidos.append((url, kw))
        return self.respuesta


def _resp(status=200, json=None):
    return httpx.Response(status, json=json, request=httpx.Request("GET", "https://x.invalid"))


def test_consulta_el_endpoint_de_numero_y_fecha_con_la_clave_en_el_header():
    http = Http(_resp(json=_raw()))

    r = vuelos.consultar("AR1302", "2026-11-28", http=http)

    [(url, kw)] = http.pedidos
    assert url == "https://prod.api.market/api/v1/aedbx/aerodatabox/flights/number/AR1302/2026-11-28"
    assert kw["headers"] == {"x-api-market-key": "clave-de-prueba"}
    assert r["puerta"] == "B12"


def test_sin_clave_no_consulta():
    config.AERODATABOX_API_KEY = ""
    http = Http(_resp(json=_raw()))

    assert vuelos.consultar("AR1302", "2026-11-28", http=http) is None
    assert http.pedidos == []
    assert not vuelos.estado_disponible()


def test_repetir_la_consulta_usa_el_cache():
    http = Http(_resp(json=_raw()))

    vuelos.consultar("AR1302", "2026-11-28", http=http)
    vuelos.consultar("AR1302", "2026-11-28", http=http)

    assert len(http.pedidos) == 1


def test_el_tope_diario_corta_las_consultas():
    http = Http(_resp(json=_raw()))

    for n in range(1, 6):
        vuelos.consultar(f"AR{n}", "2026-11-28", http=http)

    assert len(http.pedidos) == 3


def test_un_error_de_la_api_o_de_red_no_tira_nada():
    assert vuelos.consultar("AR1", "2026-11-28", http=Http(_resp(500, {"message": "boom"}))) is None
    assert vuelos.consultar("AR2", "2026-11-28", http=Http(_resp(204))) is None

    class Caido:
        def get(self, *a, **k):
            raise httpx.ConnectError("sin red")

    assert vuelos.consultar("AR3", "2026-11-28", http=Caido()) is None


# ---------- destino, llegada y avión (todo opcional) ----------

def _completa():
    """Una respuesta con todo lo que documenta AeroDataBox para flights/number (forma no verificada contra una real)."""
    return [{"number": "UA 1355", "status": "Departed", "greatCircleDistance": {"km": 2209.6},
             "aircraft": {"model": "Boeing 737 MAX 9", "reg": "N37502"},
             "departure": {"airport": {"iata": "LAS", "name": "Las Vegas Harry Reid", "municipalityName": "Las Vegas"},
                           "scheduledTime": {"utc": "2026-12-04 20:45Z", "local": "2026-12-04 12:45-08:00"},
                           "revisedTime": {"utc": "2026-12-04 21:05Z", "local": "2026-12-04 13:05-08:00"},
                           "terminal": "3", "gate": "D12", "checkInDesk": "E1-E8"},
             "arrival": {"airport": {"iata": "IAH", "name": "Houston George Bush Intercontinental",
                                     "municipalityName": "Houston"},
                         "scheduledTime": {"utc": "2026-12-05 02:20Z", "local": "2026-12-04 20:20-06:00"},
                         "revisedTime": {"utc": "2026-12-05 02:40Z", "local": "2026-12-04 20:40-06:00"},
                         "terminal": "C", "baggageBelt": "7"}}]


def test_lee_destino_llegada_y_avion_de_una_respuesta_completa():
    r = vuelos.leer_estado(_completa(), "2026-12-04")

    assert r["demora_min"] == 20 and r["puerta"] == "D12" and r["terminal"] == "3"
    assert (r["destino_iata"], r["destino_nombre"]) == ("IAH", "Houston")
    assert r["llegada_utc"] == dt.datetime(2026, 12, 5, 2, 40, tzinfo=dt.UTC).timestamp()   # la revisada
    assert r["llegada_local"] == "2026-12-04T20:40"   # hora de Houston, del desfase de la respuesta
    assert (r["llegada_terminal"], r["llegada_cinta"], r["checkin_desk"]) == ("C", "7", "E1-E8")
    assert (r["aeronave"], r["matricula"]) == ("Boeing 737 MAX 9", "N37502")


def test_sin_los_datos_opcionales_lee_igual_la_salida():
    r = vuelos.leer_estado(_raw(), "2026-11-28")

    assert r["salida_utc"] and r["puerta"] == "B12"
    assert all(r[k] is None for k in vuelos.CAMPOS_LLEGADA)


def test_con_datos_a_medias_toma_lo_que_hay():
    raw = _completa()
    raw[0]["aircraft"] = "raro"
    raw[0]["departure"]["checkInDesk"] = 12
    raw[0]["arrival"] = {"airport": {"iata": "IAH", "name": "Houston Intercontinental"},
                         "scheduledTime": {"utc": "2026-12-05 02:20Z"}, "baggageBelt": "  "}

    r = vuelos.leer_estado(raw, "2026-12-04")

    assert r["destino_nombre"] == "Houston Intercontinental"   # sin municipio, el nombre del aeropuerto
    assert r["llegada_utc"] == dt.datetime(2026, 12, 5, 2, 20, tzinfo=dt.UTC).timestamp()
    assert r["llegada_local"] is None   # sin hora local no se sabe el huso del destino
    assert r["llegada_cinta"] is None and r["checkin_desk"] is None and r["aeronave"] is None


def test_la_hora_local_de_llegada_sale_del_desfase_aunque_falte_la_revisada_local():
    raw = _completa()
    raw[0]["arrival"]["revisedTime"] = {"utc": "2026-12-05 03:00Z"}

    assert vuelos.leer_estado(raw, "2026-12-04")["llegada_local"] == "2026-12-04T21:00"


def test_un_texto_largo_de_la_respuesta_se_recorta():
    raw = _completa()
    raw[0]["aircraft"]["model"] = "x" * 500

    assert len(vuelos.leer_estado(raw, "2026-12-04")["aeronave"]) == vuelos.LARGO_MAX_TEXTO

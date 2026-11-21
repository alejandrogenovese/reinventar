"""AeroDataBox sin sorpresas: vuelo de otro día, fechas sin zona, respuestas raras, diagnóstico de 401/429 y cupos. Sin red."""
import logging

import httpx
import pytest

from app import config, vuelos


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    monkeypatch.setattr(config, "AERODATABOX_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(config, "AERODATABOX_TOPE_DIARIO", 150)
    vuelos.reiniciar_consultas()


def _raw(local="2026-11-28 21:05-03:00", sched="2026-11-29 00:05Z", revised="2026-11-29 00:50Z"):
    return [{"status": "Expected", "departure": {"scheduledTime": {"utc": sched, "local": local},
                                                 "revisedTime": {"utc": revised}, "gate": "B12"}}]


class Http:
    def __init__(self, status=200, json=None):
        self.status, self.json, self.pedidos = status, json, 0

    def get(self, url, **kw):
        self.pedidos += 1
        return httpx.Response(self.status, json=self.json, request=httpx.Request("GET", "https://x.invalid"))


def test_si_ningun_vuelo_es_del_dia_pedido_no_se_toma_otro_dia():
    assert vuelos.leer_estado(_raw(local="2026-11-29 21:05-03:00"), "2026-11-28") is None


def test_una_fecha_sin_zona_se_toma_como_utc_y_no_tira():
    r = vuelos.leer_estado(_raw(sched="2026-11-29 00:05", revised="2026-11-29 00:50Z"), "2026-11-28")

    assert r["demora_min"] == 45


@pytest.mark.parametrize("respuesta", [[{"departure": "raro"}], [{"departure": {"scheduledTime": "x"}}], [None, 3],
                                       {"no": "lista"}])
def test_una_respuesta_con_formato_raro_da_none_sin_tirar(respuesta):
    assert vuelos.leer_estado(respuesta, "2026-11-28") is None


def test_una_clave_mala_se_loguea_con_el_status_y_no_gasta_cupo(caplog):
    http = Http(401, {"message": "Invalid key"})

    with caplog.at_level(logging.ERROR, logger="reinventar.vuelos"):
        assert vuelos.consultar("AR1", "2026-11-28", http=http, usuario="ana") is None

    assert "401" in caplog.text and "AERODATABOX_API_KEY" in caplog.text
    assert vuelos._dia["n"] == 0 and vuelos._por_usuario.get("ana", 0) == 0


def test_un_fallo_se_cachea_unos_minutos(monkeypatch):
    http = Http(429)
    ahora = [1_000.0]
    monkeypatch.setattr(vuelos.time, "time", lambda: ahora[0])

    vuelos.consultar("AR1", "2026-11-28", http=http)
    vuelos.consultar("AR1", "2026-11-28", http=http)
    assert http.pedidos == 1

    ahora[0] += vuelos.FALLO_CACHE_S + 1
    vuelos.consultar("AR1", "2026-11-28", http=http)
    assert http.pedidos == 2


def test_una_cuota_agotada_se_loguea_con_el_status(caplog):
    with caplog.at_level(logging.WARNING, logger="reinventar.vuelos"):
        vuelos.consultar("AR1", "2026-11-28", http=Http(429))

    assert "429" in caplog.text


def test_un_servidor_caido_se_loguea_con_el_status(caplog):
    with caplog.at_level(logging.WARNING, logger="reinventar.vuelos"):
        vuelos.consultar("AR1", "2026-11-28", http=Http(503))

    assert "503" in caplog.text


def test_cada_persona_tiene_su_cupo_y_no_agota_el_de_todos(monkeypatch):
    monkeypatch.setattr(vuelos, "TOPE_DIARIO_POR_USUARIO", 2)
    http = Http(200, _raw())

    for n in range(5):
        vuelos.consultar(f"AR{n}", "2026-11-28", http=http, usuario="falso")
    otra = vuelos.consultar("AR99", "2026-11-28", http=http, usuario="ana")

    assert http.pedidos == 3   # 2 de "falso" + 1 de ana
    assert otra is not None

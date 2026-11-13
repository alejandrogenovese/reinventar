"""«Está llena / hay mucha cola»: la pista del catálogo, cuándo se puede avisar, el conteo y la API.

Con un catálogo de prueba en memoria y el reloj del evento fijado: corre en CI."""
import datetime as dt
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import catalog, db, lleno, sandbox
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

MARTES = "2026-12-01"


def _charla(base, walk=False, seats=150, st="14:00", en="15:00"):
    return {"base": base, "title": f"Charla {base}", "type": "Breakout session", "people": [],
            "instances": [{"c": base, "d": MARTES, "st": st, "en": en, "v": "", "seats": seats, "walk": walk}]}


GRANDE, CHICA, POR_COLA = _charla("ARC300"), _charla("DAT301", seats=50), _charla("KEY002", walk=True)


def _hora(hhmm, dia=MARTES):
    return dt.datetime.fromisoformat(f"{dia}T{hhmm}").replace(tzinfo=sandbox.EVENT_TZ)


# --- lógica ------------------------------------------------------------------
def test_pista_dice_si_es_por_cola_o_si_la_sala_es_chica():
    assert lleno.pista({"walk_in": True, "seats": 1800}) == "Sin reserva: se entra por orden de llegada"
    assert lleno.pista({"walk_in": False, "seats": 50}) == "Sala chica (50 lugares): llegá con tiempo"
    assert lleno.pista({"walk_in": False, "seats": 150}) is None
    assert lleno.pista({"walk_in": False, "seats": None}) is None


@pytest.mark.parametrize(("hhmm", "dia", "abierto"), [
    ("13:14", MARTES, False),        # falta más de 45 min
    ("13:15", MARTES, True),         # 45 min antes: ya se arma la cola
    ("14:30", MARTES, True),         # en curso
    ("15:00", MARTES, False),        # terminó
    ("14:30", "2026-12-02", False),  # otro día
])
def test_se_puede_avisar_desde_45_min_antes_hasta_que_termina(hhmm, dia, abierto):
    assert lleno.abierto(GRANDE, GRANDE["instances"][0], _hora(hhmm, dia)) is abierto


def test_sin_hora_de_fin_la_estima_por_tipo():
    sin_fin = _charla("ARC301", en=None)
    assert lleno.abierto(sin_fin, sin_fin["instances"][0], _hora("14:50"))


def test_resumen_cuenta_solo_lo_vigente_y_marca_lo_mio():
    ahora = 10_000.0
    filas = [{"code": "X", "username": "ana", "estado": "lleno", "creado": ahora - 300},
             {"code": "X", "username": "beto", "estado": "lleno", "creado": ahora - 600},
             {"code": "X", "username": "caro", "estado": "cola", "creado": ahora - 120},
             {"code": "X", "username": "dani", "estado": "lleno", "creado": ahora - lleno.VIGENCIA_MIN * 60 - 1}]
    assert lleno.resumen(filas, "ana", ahora) == {"lleno": 2, "cola": 1, "hace_min": 2, "mio": "lleno"}
    assert lleno.resumen([], "ana", ahora) == {"lleno": 0, "cola": 0, "hace_min": None, "mio": None}


# --- API ---------------------------------------------------------------------
@pytest.fixture
def cli(monkeypatch):
    reloj = {"ahora": _hora("14:10")}
    monkeypatch.setattr(sandbox, "ahora", lambda tz=sandbox.EVENT_TZ: reloj["ahora"])
    with TestClient(app) as c:
        monkeypatch.setattr(catalog, "_sessions", [GRANDE, CHICA, POR_COLA])  # después del arranque, que lo recarga
        c.H = login_headers(c)
        c.H2 = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        c.reloj = reloj
        yield c
        with db.conn() as conn:
            conn.execute("DELETE FROM reporte_lleno")


def test_avisar_suma_y_lo_ve_el_resto_sin_saber_quien(cli):
    r = cli.post("/api/lleno/ARC300", headers=cli.H, json={"estado": "lleno"})
    assert r.status_code == 200, r.text
    assert r.json() == {"lleno": 1, "cola": 0, "hace_min": 0, "mio": "lleno", "abierto": True, "pista": None}

    otro = cli.get("/api/lleno?codes=ARC300,DAT301,KEY002", headers=cli.H2).json()
    assert otro["ARC300"]["lleno"] == 1 and otro["ARC300"]["mio"] is None
    assert TEST_USER not in str(otro)  # nunca se muestra quién avisó
    assert otro["DAT301"]["pista"].startswith("Sala chica") and otro["KEY002"]["pista"].startswith("Sin reserva")


def test_cada_persona_tiene_un_solo_aviso_por_horario(cli):
    cli.post("/api/lleno/ARC300", headers=cli.H, json={"estado": "lleno"})
    r = cli.post("/api/lleno/ARC300", headers=cli.H, json={"estado": "cola"})
    assert (r.json()["lleno"], r.json()["cola"], r.json()["mio"]) == (0, 1, "cola")
    r = cli.delete("/api/lleno/ARC300", headers=cli.H)
    assert (r.json()["cola"], r.json()["mio"]) == (0, None)


def test_fuera_de_horario_no_se_puede_avisar(cli):
    cli.reloj["ahora"] = _hora("12:00")
    assert cli.post("/api/lleno/ARC300", headers=cli.H, json={"estado": "lleno"}).status_code == 409
    assert cli.get("/api/lleno?codes=ARC300", headers=cli.H).json()["ARC300"]["abierto"] is False


def test_valida_codigo_estado_y_cantidad(cli):
    assert cli.post("/api/lleno/NOEXISTE", headers=cli.H, json={"estado": "lleno"}).status_code == 404
    assert cli.post("/api/lleno/ARC300", headers=cli.H, json={"estado": "vacio"}).status_code == 422
    assert cli.post("/api/lleno/ARC300", headers=cli.H, json={"estado": "lleno", "usuario": "x"}).status_code == 422
    muchos = ",".join(f"C{n}" for n in range(lleno.CODIGOS_POR_PEDIDO + 1))
    assert cli.get(f"/api/lleno?codes={muchos}", headers=cli.H).status_code == 422
    assert cli.get("/api/lleno?codes=NOEXISTE", headers=cli.H).json() == {}
    assert cli.get("/api/lleno?codes=ARC300").status_code == 401


def test_los_avisos_viejos_se_purgan(cli):
    cli.post("/api/lleno/ARC300", headers=cli.H, json={"estado": "lleno"})
    assert db.purgar_reportes_lleno(time.time() + 1) >= 1
    assert cli.get("/api/lleno?codes=ARC300", headers=cli.H).json()["ARC300"]["lleno"] == 0


def _js(nombre):
    return (Path(__file__).resolve().parent.parent / "web" / "js" / nombre).read_text()


def test_la_ficha_muestra_los_avisos_en_cada_horario():
    js = _js("knowledge.js")
    assert "avisosDe(s.instances.map((i) => i.code))" in js and "LlenoAvisos(i.code, aviso)" in js
    lleno_js = _js("lleno.js")
    assert '"Está llena"' in lleno_js and '"Hay mucha cola"' in lleno_js


def test_las_tarjetas_de_hoy_y_del_itinerario_muestran_los_avisos():
    hoy = _js("today.js")
    assert "avisosDe(codigosDeCharlas([data.now, data.next]))" in hoy
    assert "LlenoAvisos(s.code, aviso, { conPista: false })" in hoy  # Hoy ya dice si es sin reserva
    itinerario = _js("itinerary.js")
    assert "avisosDe([...lugares.keys()])" in itinerario and "extra: lleno" in itinerario


def test_los_eventos_no_piden_avisos_y_el_pedido_respeta_el_tope():
    lleno_js = _js("lleno.js")
    assert 'new Set(["event", "mine"])' in lleno_js
    assert f"TOPE_CODIGOS = {lleno.CODIGOS_POR_PEDIDO};" in lleno_js


def test_el_modulo_nuevo_queda_en_el_cache_offline():
    sw = (Path(__file__).resolve().parent.parent / "web" / "sw.js").read_text()
    assert '"/js/lleno.js"' in sw

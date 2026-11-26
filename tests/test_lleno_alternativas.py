"""«Está llena»: otras charlas cerca, en el tiempo (empiezan ahora o en un rato) y en el espacio (misma sede o a pocos
minutos caminando).

Con un catálogo, sedes y tiempos de prueba en memoria y el reloj del evento fijado: corre en CI."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import catalog, db, lleno_alternativas, sandbox, travel, venues
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

MARTES = "2026-12-01"
SEDES = [
    {"id_sede": 2, "nombre": "Caesars Forum", "lat": 36.1179, "lng": -115.1641, "direccion": None},
    {"id_sede": 5, "nombre": "MGM Grand", "lat": 36.102219, "lng": -115.169517, "direccion": None},
    {"id_sede": 6, "nombre": "Various Locations", "lat": None, "lng": None, "direccion": None},
    {"id_sede": 7, "nombre": "Venetian", "lat": 36.1216, "lng": -115.1691, "direccion": None},
]
TIEMPOS = [{"id_origen": 7, "id_destino": 2, "minutos": 9}, {"id_origen": 7, "id_destino": 5, "minutos": 30}]


def _charla(base, st, sede="Venetian", dia=MARTES, en=None, cancelada=False, walk=False):
    inst = {"c": base, "d": dia, "st": st, "en": en, "v": f"{sede}|Level 2|Sala {base}", "seats": 150, "walk": walk}
    return {"base": base, "title": f"Charla {base}", "type": "Breakout session", "people": [],
            "instances": [{**inst, "cancelada": True} if cancelada else inst]}


LLENA = _charla("ARC300", "14:00", en="15:00")
CATALOGO = [
    LLENA,
    _charla("MISMA", "14:05", en="15:00"),                 # misma sede, empieza enseguida
    _charla("CERCA", "14:30", sede="Caesars Forum"),       # 9 min caminando
    _charla("ENCURSO", "13:55", en="14:55"),               # empezó hace un rato: todavía se puede entrar
    _charla("LEJOS", "14:30", sede="MGM Grand"),           # 30 min caminando: demasiado lejos
    _charla("TARDE", "16:00"),                             # empieza dentro de mucho
    _charla("VIEJA", "13:00", en="14:00"),                 # ya terminó (o casi)
    _charla("EMPEZADA", "13:30", en="14:30"),              # empezó hace demasiado
    _charla("OTRODIA", "14:15", dia="2026-12-02"),
    _charla("BAJA", "14:15", cancelada=True),
    _charla("SINSEDE", "14:15", sede="Various Locations"),
]


def _hora(hhmm, dia=MARTES):
    return dt.datetime.fromisoformat(f"{dia}T{hhmm}").replace(tzinfo=sandbox.EVENT_TZ)


@pytest.fixture
def maestro():
    venues.load(SEDES)
    travel.load(TIEMPOS)
    yield
    travel.load([])


def _cercanas(ahora="14:05"):
    origen = catalog.card(LLENA, LLENA["instances"][0])
    return lleno_alternativas.cercanas(origen, CATALOGO, _hora(ahora))


# --- lógica ------------------------------------------------------------------
def test_sugiere_solo_charlas_de_hoy_por_empezar_y_a_pocos_minutos(maestro):
    cercanas = _cercanas()
    assert [a["base"] for a in cercanas] == ["ENCURSO", "MISMA", "CERCA"]  # la que ya empezó primero, después por hora
    assert {a["day"] for a in cercanas} == {MARTES}   # con su día: el shuttle se decide con el de hoy


def test_cada_sugerencia_dice_cuanto_se_camina_y_si_ya_empezo(maestro):
    por_base = {a["base"]: a for a in _cercanas()}
    assert por_base["MISMA"]["misma_sede"] is True
    assert por_base["MISMA"]["minutos"] == travel.MISMA_SEDE_MIN
    assert por_base["CERCA"]["minutos"] == 9
    assert por_base["CERCA"]["misma_sede"] is False
    assert por_base["ENCURSO"]["en_curso"] is True
    assert por_base["CERCA"]["en_curso"] is False
    assert por_base["CERCA"]["venue"]["hotel"] == "Caesars Forum"
    assert por_base["CERCA"]["code"] == "CERCA"


def test_si_no_llegas_a_tiempo_caminando_no_la_sugiere(maestro):
    # A las 14:25 una charla del Caesars Forum de las 14:30 queda a 9 min: llegás 14:34, todavía se entra.
    assert "CERCA" in [a["base"] for a in _cercanas("14:25")]
    # A las 14:37 llegás 14:46: pasado el tope de atraso (14:30 + ATRASO_MAX_MIN), ya no.
    assert lleno_alternativas.ATRASO_MAX_MIN == 15
    assert "CERCA" not in [a["base"] for a in _cercanas("14:37")]


def test_sin_sede_de_origen_conocida_no_sugiere_nada(maestro):
    sin_sede = _charla("RARA", "14:00", sede="Various Locations")
    origen = catalog.card(sin_sede, sin_sede["instances"][0])
    assert lleno_alternativas.cercanas(origen, CATALOGO, _hora("14:05")) == []


# --- API ---------------------------------------------------------------------
@pytest.fixture
def cli(monkeypatch):
    reloj = {"ahora": _hora("14:05")}
    monkeypatch.setattr(sandbox, "ahora", lambda tz=sandbox.EVENT_TZ: reloj["ahora"])
    with TestClient(app) as c:
        # Después del lifespan (que carga el catálogo real si hay): catálogo, sedes y tiempos de prueba.
        monkeypatch.setattr(catalog, "_sessions", CATALOGO)
        venues.load(SEDES)
        travel.load(TIEMPOS)
        c.H = login_headers(c)
        c.H2 = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        yield c
        with db.conn() as conn:
            conn.execute("DELETE FROM reporte_lleno")
    travel.load([])


def _alternativas(cli, code="ARC300"):
    return cli.get(f"/api/lleno/{code}/alternativas", headers=cli.H)


def test_sin_avisos_de_llena_no_sugiere_nada(cli):
    r = _alternativas(cli)
    assert r.status_code == 200, r.text
    assert r.json() == {"motivo": None, "alternativas": []}


def test_con_un_aviso_vigente_de_llena_sugiere_las_cercanas(cli):
    cli.post("/api/lleno/ARC300", headers=cli.H2, json={"estado": "lleno"})
    r = _alternativas(cli).json()
    assert r["motivo"] == "lleno"
    assert [a["base"] for a in r["alternativas"]] == ["ENCURSO", "MISMA", "CERCA"]


def test_con_mucha_cola_tambien_sugiere_las_cercanas(cli):
    cli.post("/api/lleno/ARC300", headers=cli.H2, json={"estado": "cola"})
    r = _alternativas(cli).json()
    assert r["motivo"] == "cola"
    assert [a["base"] for a in r["alternativas"]] == ["ENCURSO", "MISMA", "CERCA"]


def test_si_alguien_dijo_llena_gana_sobre_la_cola(cli):
    cli.post("/api/lleno/ARC300", headers=cli.H, json={"estado": "cola"})
    cli.post("/api/lleno/ARC300", headers=cli.H2, json={"estado": "lleno"})
    assert _alternativas(cli).json()["motivo"] == "lleno"


def test_una_cercana_con_mucha_cola_se_sigue_sugiriendo(cli):
    cli.post("/api/lleno/ARC300", headers=cli.H2, json={"estado": "lleno"})
    cli.post("/api/lleno/MISMA", headers=cli.H2, json={"estado": "cola"})
    assert "MISMA" in [a["base"] for a in _alternativas(cli).json()["alternativas"]]


def test_no_sugiere_otra_charla_que_tambien_esta_llena(cli):
    cli.post("/api/lleno/ARC300", headers=cli.H2, json={"estado": "lleno"})
    cli.post("/api/lleno/MISMA", headers=cli.H2, json={"estado": "lleno"})
    assert "MISMA" not in [a["base"] for a in _alternativas(cli).json()["alternativas"]]


def test_alternativas_valida_codigo_y_sesion(cli):
    assert _alternativas(cli, "NOEXISTE").status_code == 404
    assert cli.get("/api/lleno/ARC300/alternativas").status_code == 401


def test_el_tope_de_sugerencias(cli, monkeypatch):
    monkeypatch.setattr(lleno_alternativas, "MAX_SUGERENCIAS", 2)
    cli.post("/api/lleno/ARC300", headers=cli.H2, json={"estado": "lleno"})
    assert len(_alternativas(cli).json()["alternativas"]) == 2

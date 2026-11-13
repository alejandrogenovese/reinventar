"""«Tu re:Invent en números»: agregados del catálogo y de la semana, la API y quién grabó cada sesión.
Usa un catálogo chico en memoria (no el schema reinvent) y el LLM fake: corre en CI."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import catalog, config, db, explore, numeros, pg, sandbox, travel, venues
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

LUN, MAR = "2026-11-30", "2026-12-01"
WEB = Path(__file__).resolve().parent.parent / "web"


def _s(base, titulo, tipo, *instancias, nivel="300", topic="", resumen="", lanzamiento=False, people=()):
    return {"base": base, "title": titulo, "type": tipo, "level": nivel, "topic": topic, "aoi": "", "services": "",
            "tech": "", "concepts": "", "concepts_en": "", "focus": "", "speakers": "", "people": list(people),
            "abstract": resumen or f"Resumen de {titulo}.", "abstract_es": None, "newlaunch": lanzamiento,
            "instances": [{"c": c, "d": d, "st": st, "v": v, "seats": 100, "walk": walk}
                          for c, d, st, v, walk in instancias]}


CATALOGO = [
    _s("KEY", "CEO Keynote", "Keynote", ("KEY1", MAR, "08:30", "Venetian|Hall A", False), nivel="",
       people=[{"id": 1, "name": "Matt"}]),
    _s("SEC", "Fine-grained access control for agents", "Chalk talk",
       ("SEC1", LUN, "10:00", "MGM Grand|Level 3", True), ("SEC2", MAR, "13:00", "MGM Grand|Level 1", False),
       topic="Security & Identity;Artificial Intelligence", nivel="400", people=[{"id": 2, "name": "Ana"}]),
    _s("AGT", "Building agents with Bedrock", "Breakout session", ("AGT1", LUN, "10:30", "Wynn|Level 1", True),
       topic="Artificial Intelligence", lanzamiento=True, people=[{"id": 2, "name": "Ana"}, {"id": 3, "name": "Bob"}]),
    _s("LIT", "Lightning on lakehouses", "Lightning talk", ("LIT1", LUN, "11:00", "Wynn|Level 2", False),
       topic="Analytics", nivel="200"),
    _s("GRF", "Knowledge graphs on Neptune", "Chalk talk", ("GRF1", LUN, "13:00", "Venetian|Level 2", True),
       topic="Databases"),
]
SEDES = [
    {"id_sede": 5, "nombre": "MGM Grand", "lat": 36.102219, "lng": -115.169517, "direccion": None},
    {"id_sede": 7, "nombre": "Venetian", "lat": 36.1216, "lng": -115.1691, "direccion": None},
    {"id_sede": 9, "nombre": "Wynn", "lat": 36.1265, "lng": -115.1657, "direccion": None},
]
TIEMPOS = [{"id_origen": 5, "id_destino": 9, "minutos": 48, "metros": 3400},
           {"id_origen": 9, "id_destino": 7, "minutos": 12, "metros": 900}]


@pytest.fixture
def sedes():
    venues.load(SEDES)
    travel.load(TIEMPOS)
    yield
    travel.load([])


def _card(code, start, end, hotel, tipo="Breakout session", kind="talk", base=None, nivel="300", titulo=None):
    return {"code": code, "base": base or code, "title": titulo or code, "type": tipo, "kind": kind, "level": nivel,
            "start": start, "end": end, "venue": {"hotel": hotel, "lat": None, "lng": None}}


# ---------- catálogo ----------

def test_el_catalogo_cuenta_horarios_por_dia_y_por_hora():
    r = numeros.resumen_catalogo(CATALOGO)

    assert (r["charlas"], r["horarios"], r["speakers"]) == (5, 6, 3)
    assert r["por_dia"] == [{"dia": LUN, "n": 4}, {"dia": MAR, "n": 2}]
    lunes = next(f["n"] for f in r["dia_hora"] if f["dia"] == LUN)
    assert lunes[10 - numeros.HORA_DESDE] == 2 and lunes[11 - numeros.HORA_DESDE] == 1
    assert r["horas"][0] == numeros.HORA_DESDE and len(r["horas"]) == len(lunes)


def test_una_charla_con_dos_horarios_cuenta_en_los_dos_dias():
    r = numeros.resumen_catalogo([CATALOGO[1]])

    assert [d["dia"] for d in r["por_dia"]] == [LUN, MAR]
    assert r["por_sede"] == [{"valor": "MGM Grand", "n": 2}]
    assert r["por_tipo"] == [{"valor": "Chalk talk", "n": 1}]     # tipo cuenta charlas, no horarios


def test_tipo_tema_walk_up_y_lanzamientos():
    r = numeros.resumen_catalogo(CATALOGO)

    assert r["por_tipo"][0] == {"valor": "Chalk talk", "n": 2}
    assert r["por_tema"][0] == {"valor": "Artificial Intelligence", "n": 2}
    assert (r["walk_up"], r["lanzamientos"]) == (3, 1)
    assert {"dia": LUN, "n": 1} in r["lanzamientos_por_dia"]
    assert {"valor": "400", "n": 1} in r["por_nivel"]


def test_lo_que_no_entra_en_el_top_se_suma_en_otros():
    sesiones = [_s(f"S{i}", f"Charla {i}", f"Tipo {i}", (f"S{i}1", LUN, "10:00", "MGM Grand", False)) for i in range(9)]

    tipos = numeros.resumen_catalogo(sesiones)["por_tipo"]

    assert len(tipos) == numeros.TOP_TIPOS + 1
    assert tipos[-1] == {"valor": "Otros", "n": 9 - numeros.TOP_TIPOS, "otros": True}


# ---------- agenda ----------

def test_dos_items_que_se_pisan_suman_la_union():
    assert numeros.minutos_ocupados([(600, 660), (630, 720)]) == 120
    assert numeros.minutos_ocupados([(600, 660), (700, 720)]) == 80
    assert numeros.minutos_ocupados([(600, 720), (610, 620)]) == 120


def test_detecta_el_choque_y_no_marca_los_pegados():
    assert numeros.choques([(600, 660), (660, 720)]) == []
    assert numeros.choques([(600, 660), (630, 690), (700, 720)]) == [(0, 1)]


def test_no_llegas_si_el_hueco_es_menor_que_la_caminata(sedes):
    cards = [_card("A", "10:00", "11:00", "MGM Grand"), _card("B", "11:30", "12:30", "Wynn"),
             _card("C", "13:00", "14:00", "Venetian")]

    d = numeros.resumen_dia(LUN, cards)

    assert [i["no_llegas"] for i in d["items"]] == [False, True, False]   # 30 min de hueco, 48 caminando
    assert d["no_llegas"][0]["previa"]["code"] == "A" and d["no_llegas"][0]["minutos"] == 48
    assert (d["caminata_min"], d["caminata_m"]) == (48 + 12, 3400 + 900)
    assert d["tramo_mas_largo"]["desde"] == "MGM Grand"
    assert d["minutos_ocupados"] == 180


def test_en_la_misma_sede_no_se_camina_y_los_choques_van_en_dos_carriles(sedes):
    cards = [_card("A", "10:00", "11:00", "MGM Grand"), _card("B", "10:30", "11:30", "MGM Grand", tipo="Keynote")]

    d = numeros.resumen_dia(LUN, cards)

    assert d["caminata_min"] == 0 and not d["no_llegas"]
    assert [(i["choque"], i["carril"]) for i in d["items"]] == [(True, 0), (True, 1)]
    assert d["items"][1]["keynote"] and d["choques"][0]["a"]["code"] == "A"


def test_el_fin_se_estima_por_tipo_si_la_fuente_no_lo_trae():
    d = numeros.resumen_dia(LUN, [_card("L", "10:00", None, "Wynn", tipo="Lightning talk")])

    assert d["items"][0]["end"] == "10:20"


FICHA = {"prioridades": [{"tema": "Agentes", "peso": 3, "claves": ["agentes"]},
                         {"tema": "Grafos", "peso": 2, "claves": ["Knowledge Graph"]},
                         {"tema": "Seguridad", "peso": 1, "claves": ["access control"]}],
         "nivel": [300, 400]}


def test_la_cobertura_compara_las_claves_sin_tildes_ni_mayusculas_y_marca_los_huecos():
    textos = {"AGT": catalog.fold("Building AGENTES with Bedrock"), "GRF": catalog.fold("Knowledge graphs on Neptune"),
              "SEC": catalog.fold("Fine-grained access control")}
    charlas = [_card("AGT1", "10:00", "11:00", "Wynn", base="AGT"), _card("GRF1", "13:00", "14:00", "Wynn", base="GRF")]

    c = numeros.cobertura_ficha(FICHA, charlas, textos)

    assert [(p["tema"], p["agendadas"], p["en_catalogo"]) for p in c["prioridades"]] == [
        ("Agentes", 1, 1), ("Grafos", 1, 1), ("Seguridad", 0, 1)]
    assert c["sin_cubrir"] == ["Seguridad"]
    assert numeros.cobertura_ficha(None, charlas, textos) is None


def test_la_agenda_vacia_devuelve_una_estructura_vacia():
    r = numeros.resumen_agenda([], None, {})

    assert (r["total"], r["dias"], r["choques"], r["caminata_m"], r["ficha"], r["niveles"]) == (0, [], 0, 0, None, [])


def test_la_agenda_separa_charlas_keynotes_y_eventos(sedes):
    dias = [{"day": MAR, "sessions": [_card("KEY1", "08:30", "10:30", "Venetian", tipo="Keynote", nivel=""),
                                      _card("SEC2", "13:00", "14:00", "MGM Grand", nivel="400"),
                                      _card("ev1", "19:00", "21:00", "Wynn", tipo="Fiesta", kind="event")]}]

    r = numeros.resumen_agenda(dias, None, {})

    assert (r["total"], r["charlas"], r["keynotes"], r["eventos"]) == (3, 1, 1, 1)
    assert r["niveles"] == [{"valor": "400", "n": 1}]
    assert r["minutos_ocupados"] == 120 + 60 + 120


# ---------- API ----------

@pytest.fixture
def client(monkeypatch):
    with TestClient(app) as c:
        monkeypatch.setattr(catalog, "_sessions", CATALOGO)
        venues.load(SEDES)
        travel.load(TIEMPOS)
        yield c
    travel.load([])


@pytest.fixture
def headers(client):
    h = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    yield h
    for it in db.list_itinerary_items(TEST_ADMIN):
        db.remove_item(TEST_ADMIN, it["code"])
    db.delete_interview(TEST_ADMIN)


def test_sin_sesion_da_401(client):
    assert client.get("/api/numeros/mio").status_code == 401
    assert client.get("/api/numeros/catalogo").status_code == 401


def test_con_la_agenda_vacia_devuelve_ceros(client, headers):
    r = client.get("/api/numeros/mio", headers=headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["total"], body["dias"], body["ficha"]) == (0, [], None)
    assert body["grabado"]["grabaciones"] >= 0 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", body["hoy"])


def test_mio_cuenta_la_semana_y_la_ficha(client, headers):
    for code in ("SEC1", "AGT1"):
        assert client.post("/api/itinerary/items", headers=headers, json={"code": code}).status_code == 200
    db.save_ficha(TEST_ADMIN, FICHA, "ficha de prueba")

    body = client.get("/api/numeros/mio", headers=headers).json()

    lunes = body["dias"][0]
    assert (body["total"], body["choques"], body["no_llegas"]) == (2, 1, 0)   # 10:00–11:00 y 10:30 se pisan
    assert lunes["dia"] == LUN and [i["code"] for i in lunes["items"]] == ["SEC1", "AGT1"]
    assert {p["tema"]: p["agendadas"] for p in body["ficha"]["prioridades"]}["Seguridad"] == 1


def test_el_catalogo_por_api_usa_el_catalogo_cargado(client, headers):
    body = client.get("/api/numeros/catalogo", headers=headers).json()

    assert (body["charlas"], body["horarios"]) == (len(CATALOGO), 6)
    assert body["por_dia"][0] == {"dia": LUN, "n": 4}


def test_hoy_respeta_el_reloj_simulado_del_modo_prueba(client, headers):
    import datetime as dt
    import time

    simulado = sandbox.Sandbox(username=TEST_ADMIN, reloj=dt.datetime(2026, 12, 2, 13, 40, tzinfo=sandbox.EVENT_TZ),
                               reloj_fijado=time.time())
    with sandbox.activar(simulado):
        from app import numeros_api
        assert numeros_api._hoy() == "2026-12-02"


# ---------- hora de inicio como faceta de Buscar (el heatmap abre Buscar con día y hora) ----------

def test_la_faceta_hora_filtra_por_la_hora_de_inicio(client):
    r = explore.explore({"dia": {LUN}, "hora": {"10 h"}})

    assert sorted(c["code"] for c in r["results"]) == ["AGT1", "SEC1"]
    assert {"value": "10 h", "count": 2} in r["facets"]["hora"]
    assert explore.hora("08:30") == "08 h" and explore.hora(None) is None


# ---------- quién grabó (created_by) ----------

def test_la_migracion_de_created_by_es_idempotente():
    db.init()
    db.init()

    with pg.pool().connection() as c:
        for schema in (config.DB_SCHEMA, sandbox.schema_prueba()):
            col = c.execute("SELECT is_nullable FROM information_schema.columns WHERE table_schema=%s "
                            "AND table_name='sessions' AND column_name='created_by'", (schema,)).fetchone()
            assert col and col["is_nullable"] == "YES", schema


def test_al_crear_una_grabacion_queda_quien_la_grabo(client, headers):
    antes = db.grabado_por(TEST_ADMIN)["grabaciones"]

    s = client.post("/api/sessions", headers=headers, json={"title": "Charla grabada", "kind": "Breakout"}).json()
    db.update_session(s["id"], duration_s=125.4)

    assert db.get_session(s["id"])["created_by"] == TEST_ADMIN
    assert db.grabado_por(TEST_ADMIN)["grabaciones"] == antes + 1
    assert client.get("/api/numeros/mio", headers=headers).json()["grabado"]["grabaciones"] == antes + 1
    db.delete_session(s["id"])


def test_las_grabaciones_viejas_sin_dueno_no_cuentan_para_nadie():
    s = db.create_session("Grabación vieja", "Breakout")

    assert db.get_session(s["id"])["created_by"] is None
    assert db.grabado_por("nadie_en_particular") == {"grabaciones": 0, "segundos": 0}
    db.delete_session(s["id"])


# ---------- front ----------

def test_la_pantalla_esta_en_el_shell_en_la_ruta_y_en_el_itinerario():
    sw = (WEB / "sw.js").read_text()
    app_js = (WEB / "js" / "app.js").read_text()

    assert '"/js/numeros.js"' in sw
    assert "#\\/itinerario\\/numeros" in app_js and 'from "./numeros.js"' in app_js
    assert "#/itinerario/numeros" in (WEB / "js" / "itinerary.js").read_text()

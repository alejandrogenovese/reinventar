"""Armado guiado: estados del traslado (con cola sin reserva), afinidad con la ficha y "qué sigue".
Usa un catálogo chico en memoria (no el schema reinvent) y el LLM fake: corre en CI."""
import pytest
from fastapi.testclient import TestClient

from app import catalog, db, guided, travel, venues
from app.interview import Ficha
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

DIA, DIA2 = "2026-12-01", "2026-12-02"
FICHA = Ficha(
    resumen="Arquitecto de datos muy técnico.",
    prioridades=[{"tema": "Grafos", "peso": 3, "claves": ["Neptune", "knowledge graph"]},
                 {"tema": "Seguridad", "peso": 2, "claves": ["ABAC", "access control"]}],
    nivel=[300, 400], formatos=["Chalk talk"], evitar=["marketing"], industria="banca",
    ritmo={"charlas_por_dia": "5-6", "almuerzo": True, "eventos_noche": True},
    consulta_busqueda="graph databases with fine-grained access control",
)


# ---------- estado del traslado (puro) ----------

def _t(fin, inicio, viaje, reservada=True):
    return guided.evaluar(guided.minutos(fin), guided.minutos(inicio), viaje, reservada)


def test_con_margen_llega_a_tiempo():
    t = _t("09:00", "10:00", 15)

    assert (t.estado, t.salir_antes_min, t.salir_a) == ("a_tiempo", 0, None)


def test_sin_reserva_suma_la_cola_y_dice_desde_cuando():
    t = _t("09:00", "10:00", 15, reservada=False)

    assert (t.estado, t.llegada) == ("a_tiempo", "09:30")


def test_con_menos_de_cinco_minutos_de_margen_es_justo():
    assert _t("09:00", "09:15", 15).estado == "justo"
    assert _t("09:00", "09:19", 15).estado == "justo"
    assert _t("09:00", "09:20", 15).estado == "a_tiempo"


def test_si_hay_que_irse_hasta_30_min_antes_es_salir_antes():
    t = _t("09:00", "09:00", 25)

    assert (t.estado, t.salir_antes_min, t.salir_a) == ("salir_antes", 25, "08:35")
    assert _t("09:00", "09:00", 30).estado == "salir_antes"


def test_mas_de_30_min_se_superpone_y_dice_cuanto():
    t = _t("09:00", "09:00", 31)

    assert (t.estado, t.salir_antes_min, t.salir_a) == ("se_superpone", 31, "08:29")


def test_la_cola_puede_convertir_una_a_tiempo_en_salir_antes():
    # Misma sede (5 min) a las 09:15: con reserva sobra; sin reserva hay que estar 08:45, o sea salir 08:40.
    assert _t("09:00", "09:15", 5).estado == "a_tiempo"
    t = _t("09:00", "09:15", 5, reservada=False)
    assert (t.estado, t.salir_antes_min) == ("salir_antes", 20)


def test_sin_charla_anterior_siempre_llega():
    t = guided.evaluar(None, guided.minutos("08:00"), None, reservada=False)

    assert (t.estado, t.llegada) == ("a_tiempo", "07:30")


# ---------- afinidad con la ficha (pura) ----------

def _sesion(titulo, tipo="Breakout session", nivel="300", resumen="", servicios=""):
    return {"base": titulo[:6], "title": titulo, "type": tipo, "level": nivel, "abstract": resumen,
            "services": servicios, "tech": "", "concepts": "", "concepts_en": "", "topic": ""}


def test_las_claves_suman_por_el_peso_de_su_prioridad():
    grafos, _ = guided.afinidad(_sesion("Amazon Neptune deep dive"), FICHA)
    seguridad, motivos = guided.afinidad(_sesion("ABAC in practice"), FICHA)
    nada, _ = guided.afinidad(_sesion("Serverless patterns"), FICHA)

    assert grafos > seguridad > nada
    assert motivos == ["Seguridad"]


def test_las_claves_cortas_no_matchean_adentro_de_otra_palabra():
    ficha = Ficha(**{**FICHA.model_dump(), "prioridades": [{"tema": "IA", "peso": 3, "claves": ["AI"]}]})

    con, _ = guided.afinidad(_sesion("Generative AI on AWS"), ficha)
    sin, _ = guided.afinidad(_sesion("Maintain your data lake"), ficha)

    assert con > sin


def test_las_claves_matchean_en_plural():
    assert guided.afinidad(_sesion("Securing knowledge graphs"), FICHA)[1] == ["Grafos"]


def test_formato_y_nivel_preferidos_suman_y_lo_que_evita_resta():
    base, _ = guided.afinidad(_sesion("Lakehouse"), FICHA)

    assert guided.afinidad(_sesion("Lakehouse", tipo="Chalk talk"), FICHA)[0] > base
    assert guided.afinidad(_sesion("Lakehouse", nivel="200"), FICHA)[0] < base
    assert guided.afinidad(_sesion("Lakehouse marketing playbook"), FICHA)[0] < base


def test_la_pendiente_va_primero():
    pendiente, _ = guided.afinidad(_sesion("Serverless patterns"), FICHA, pendiente=True)
    mejor, _ = guided.afinidad(_sesion("Amazon Neptune ABAC access control"), FICHA)

    assert pendiente > mejor


# ---------- "qué sigue" (API, catálogo en memoria) ----------

def _s(base, titulo, tipo, nivel, *instancias):
    return {"base": base, "title": titulo, "type": tipo, "level": nivel, "topic": "", "aoi": "", "services": "",
            "tech": "", "concepts": "", "concepts_en": "", "focus": "", "speakers": "", "people": [],
            "abstract": f"Resumen de {titulo}.", "abstract_es": None, "newlaunch": False,
            "instances": [{"c": c, "d": d, "st": st, "v": v, "seats": 100, "walk": True} for c, d, st, v in instancias]}


CATALOGO = [
    _s("PREV", "Fine-grained access control on Amazon Neptune", "Chalk talk", "400", ("PREV1", DIA, "08:00", "MGM Grand|Level 3")),
    _s("MISMA", "Securing knowledge graphs", "Breakout session", "300", ("MISMA1", DIA, "09:45", "MGM Grand|Level 1")),
    _s("LEJOS", "Graph ABAC in practice with Neptune", "Builders' session", "400", ("LEJOS1", DIA, "09:00", "Venetian|Level 2")),
    _s("FORUM", "Neptune Analytics deep dive", "Chalk talk", "400", ("FORUM1", DIA, "09:30", "Caesars Forum|Room 1")),
    _s("RUIDO", "Serverless marketing patterns", "Breakout session", "200", ("RUIDO1", DIA, "10:00", "MGM Grand|Level 1")),
    _s("TARDE", "Neptune at night", "Chalk talk", "400", ("TARDE1", DIA, "16:00", "MGM Grand|Level 1")),
    _s("REPITE", "Knowledge graph security patterns", "Chalk talk", "400",
       ("REPITE1", DIA, "09:00", "MGM Grand|Level 2"), ("REPITE2", DIA2, "10:00", "MGM Grand|Level 2")),
    _s("OTRO", "Serverless on day two", "Breakout session", "300", ("OTRO1", DIA2, "10:00", "MGM Grand|Level 1")),
]
SEDES = [
    {"id_sede": 2, "nombre": "Caesars Forum", "lat": 36.1179, "lng": -115.1641, "direccion": None},
    {"id_sede": 5, "nombre": "MGM Grand", "lat": 36.102219, "lng": -115.169517, "direccion": None},
    {"id_sede": 7, "nombre": "Venetian", "lat": 36.1216, "lng": -115.1691, "direccion": None},
]


@pytest.fixture
def client(monkeypatch):
    with TestClient(app) as c:
        # Después del lifespan (que carga el catálogo real si hay): catálogo, sedes y tiempos de prueba.
        monkeypatch.setattr(catalog, "_sessions", CATALOGO)
        venues.load(SEDES)
        travel.load([{"id_origen": 5, "id_destino": 7, "minutos": 25}, {"id_origen": 5, "id_destino": 2, "minutos": 15}])
        monkeypatch.setattr(guided, "_busqueda", lambda ficha: {})
        yield c
    travel.load([])


@pytest.fixture
def headers(client):
    h = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    yield h
    for it in db.list_itinerary_items(TEST_ADMIN):
        db.remove_item(TEST_ADMIN, it["code"])
    for p in db.list_pending(TEST_ADMIN):
        db.remove_pending(TEST_ADMIN, p["base"])
    db.delete_interview(TEST_ADMIN)


@pytest.fixture
def con_ficha(headers):
    db.save_ficha(TEST_ADMIN, FICHA.model_dump(), "ficha de prueba")
    return headers


def _next(client, headers, **body):
    r = client.post("/api/itinerary/guided/next", headers=headers, json={"day": DIA, **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_sin_ficha_pide_completar_la_entrevista(client, headers):
    assert client.post("/api/itinerary/guided/next", headers=headers, json={"day": DIA}).status_code == 409


def test_despues_de_una_charla_propone_las_que_siguen_con_su_estado(client, con_ficha):
    client.post("/api/itinerary/items", headers=con_ficha, json={"code": "PREV1"})

    r = _next(client, con_ficha, after="PREV1")
    por_base = {o["card"]["base"]: o for o in r["opciones"]}

    assert r["fin_previa"] == "09:00"
    assert "PREV" not in por_base and "TARDE" not in por_base     # ya agendada / fuera de la ventana
    assert por_base["MISMA"]["viaje_min"] == travel.MISMA_SEDE_MIN
    assert por_base["MISMA"]["estado"] == "a_tiempo"              # 09:45 sin reserva: cola 09:15, sale 09:10
    assert por_base["FORUM"]["estado"] == "salir_antes"           # cola 09:00 - 15 min = salir 08:45
    assert por_base["FORUM"]["salir_a"] == "08:45"
    assert por_base["LEJOS"]["estado"] == "se_superpone"          # cola 08:30 - 25 min = salir 08:05
    assert r["opciones"][-1]["estado"] == "se_superpone"          # las rojas van al final
    assert all(o["razon"] for o in r["opciones"])                 # razones del LLM (fake)


def test_la_mejor_opcion_es_la_de_mas_afinidad_y_cercania(client, con_ficha):
    client.post("/api/itinerary/items", headers=con_ficha, json={"code": "PREV1"})

    r = _next(client, con_ficha, after="PREV1")

    assert r["opciones"][0]["card"]["base"] == "MISMA"  # misma sede, con claves de la ficha y sin salir antes


def test_primera_del_dia_arranca_desde_la_hora_pedida(client, con_ficha):
    r = _next(client, con_ficha, desde="09:30")

    assert r["fin_previa"] is None
    assert {o["card"]["start"] for o in r["opciones"]} <= {"09:30", "09:45", "10:00"}


def test_la_pendiente_vuelve_primera_el_dia_que_se_repite(client, con_ficha):
    assert client.post("/api/itinerary/pending", headers=con_ficha, json={"base": "REPITE", "day": DIA}).status_code == 200

    r = _next(client, con_ficha, day=DIA2)
    pendientes = client.get("/api/itinerary/pending", headers=con_ficha).json()["pendientes"]

    assert r["opciones"][0]["card"]["base"] == "REPITE"
    assert r["opciones"][0]["pendiente"] == DIA
    assert pendientes[0]["horarios"][-1]["code"] == "REPITE2"

    client.post("/api/itinerary/items", headers=con_ficha, json={"code": "REPITE2"})  # al agendarla sale de pendientes
    assert client.get("/api/itinerary/pending", headers=con_ficha).json()["pendientes"] == []


def test_pendiente_de_una_charla_que_no_existe(client, con_ficha):
    assert client.post("/api/itinerary/pending", headers=con_ficha, json={"base": "NADA", "day": DIA}).status_code == 404


def test_salir_antes_y_reservada_quedan_en_el_itinerario(client, con_ficha):
    client.post("/api/itinerary/items", headers=con_ficha, json={"code": "PREV1", "reason": "Justo tu desafío."})

    assert client.put("/api/itinerary/items/PREV1/salir-antes", headers=con_ficha, json={"minutos": 25}).status_code == 200
    assert client.put("/api/itinerary/items/PREV1/reservada", headers=con_ficha, json={"reservada": True}).status_code == 200
    item = client.get("/api/itinerary", headers=con_ficha).json()["days"][0]["sessions"][0]

    assert (item["salir_antes"], item["reservada"], item["reason"]) == (25, True, "Justo tu desafío.")
    assert client.put("/api/itinerary/items/NOEXISTE/reservada", headers=con_ficha,
                      json={"reservada": True}).status_code == 404


def test_las_rojas_que_interesan_menos_que_las_que_se_llega_no_se_muestran():
    def o(estado, af):
        return {"estado": estado, "afinidad": af, "puntaje": af, "misma_sede": False, "card": {"base": f"{estado}{af}"}}

    elegidas = guided._elegir([o("a_tiempo", 4), o("justo", 2), o("se_superpone", 6), o("se_superpone", 1)])

    assert [x["afinidad"] for x in elegidas] == [4, 2, 6]


def test_una_charla_que_choca_con_otra_agendada_no_se_propone(client, con_ficha):
    client.post("/api/itinerary/items", headers=con_ficha, json={"code": "PREV1"})
    client.post("/api/itinerary/items", headers=con_ficha, json={"code": "RUIDO1"})  # 10:00-11:00

    r = _next(client, con_ficha, after="PREV1")

    assert "MISMA" not in {o["card"]["base"] for o in r["opciones"]}  # 09:45-10:45 pisa la de las 10


def test_un_evento_propio_ocupa_su_horario(client, con_ficha):
    client.post("/api/itinerary/items", headers=con_ficha, json={"code": "PREV1"})
    r = client.post("/api/my-events", headers=con_ficha, json={
        "nombre": "Reunión con Datadog", "dia": DIA, "inicio": "09:30", "fin": "10:15", "id_sede": 5})
    assert r.status_code == 200, r.text

    bases = {o["card"]["base"] for o in _next(client, con_ficha, after="PREV1")["opciones"]}

    assert {"MISMA", "FORUM"}.isdisjoint(bases)  # 09:45 y 09:30 caen encima de la reunión
    for ev in db.list_user_events(TEST_ADMIN):
        db.delete_user_event(TEST_ADMIN, ev["id"])

"""«Charlas nuevas» para el usuario (app/charlas_nuevas.py): la lista (sin las pasadas, las canceladas, las agregadas ni
las descartadas, separada por usuario), agregar con choques, y el push agrupado (a quién le llega, que no se repita, la
preferencia, el horario de silencio y los intereses). Catálogo en memoria armado a mano: en CI no está el schema
reinvent. Las altas de la base del catálogo se prueban contra un schema efímero con las migraciones."""
import datetime as dt
import os
import uuid
from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import catalog, db, sandbox
from app import charlas_nuevas as cn
from app import push as push_mod
from app.main import app
from scripts.actualizar_catalogo import aplicar_migraciones
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

LV = sandbox.EVENT_TZ
AHORA = dt.datetime(2026, 11, 30, 10, tzinfo=LV)          # reloj del evento, de día
NOCHE = dt.datetime(2026, 11, 30, 23, tzinfo=LV)          # horario de silencio
REAL = dt.datetime(2026, 11, 23, 18, tzinfo=dt.UTC)       # reloj real (contra el que se mide el alta)


def _sesion(base, titulo, instancias, topic="", tipo="Breakout session"):
    return {"base": base, "title": titulo, "type": tipo, "level": "300", "topic": topic, "aoi": "", "services": "",
            "tech": "", "concepts": "", "concepts_en": "", "focus": "", "speakers": "", "people": [], "abstract": "",
            "abstract_es": None, "newlaunch": False, "instances": instancias}


def _inst(code, dia, hora, cancelada=False):
    return {"c": code, "d": dia, "st": hora, "en": None, "v": "MGM Grand|Level 3", "seats": 100, "walk": False,
            "cancelada": cancelada}


CATALOGO = [
    _sesion("AIM401", "Agentes con Bedrock", [_inst("AIM401", "2026-12-01", "10:00"), _inst("AIM401-R", "2026-12-02", "14:00")],
            topic="Generative AI"),
    _sesion("DEV302", "Pipelines de CI", [_inst("DEV302", "2026-12-01", "10:30")], topic="Developer Productivity"),
    _sesion("PAS101", "Ya pasó", [_inst("PAS101", "2026-11-30", "08:00")]),
    _sesion("CAN201", "Cancelada", [_inst("CAN201", "2026-12-01", "11:00", cancelada=True)]),
    _sesion("OLD100", "Vieja pero visible", [_inst("OLD100", "2026-12-03", "09:00")]),
    _sesion("VIE200", "Ya estaba", [_inst("VIE200", "2026-12-01", "10:15")]),
]
ALTAS = {"AIM401": REAL - dt.timedelta(hours=1), "DEV302": REAL - dt.timedelta(hours=2),
         "PAS101": REAL - dt.timedelta(hours=1), "CAN201": REAL - dt.timedelta(hours=1),
         "OLD100": REAL - dt.timedelta(days=3)}


def _limpiar():
    with db.conn() as c:
        for t in ("charlas_nuevas_decision", "push_sent", "preferencias_avisos", "itinerary_items", "itinerary_profile"):
            c.execute(f"DELETE FROM {t} WHERE username IN (%s,%s)", (TEST_USER, TEST_ADMIN))


@pytest.fixture
def cli(monkeypatch):
    with TestClient(app) as c:
        monkeypatch.setattr(catalog, "_sessions", CATALOGO)
        monkeypatch.setattr(cn, "altas", lambda desde, **_: {b: a for b, a in ALTAS.items() if a >= desde})
        monkeypatch.setattr(sandbox, "ahora", lambda tz=LV: AHORA.astimezone(tz))
        monkeypatch.setattr(cn, "ahora_real", lambda: REAL)
        c.H = login_headers(c)
        c.H2 = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        _limpiar()
        yield c
        _limpiar()


def _bases(cli, headers=None):
    return [c["base"] for c in cli.get("/api/charlas-nuevas", headers=headers or cli.H).json()["charlas"]]


class Push:
    def __init__(self, llega=1):
        self.llega = llega
        self.enviados = []

    def __call__(self, username, mensaje):
        self.enviados.append((username, mensaje))
        return self.llega


# ---------- lista ----------

def test_la_lista_trae_las_nuevas_con_horario_por_delante_y_no_las_pasadas_ni_canceladas(cli):
    charlas = cli.get("/api/charlas-nuevas", headers=cli.H).json()

    assert [c["base"] for c in charlas["charlas"]] == ["AIM401", "DEV302", "OLD100"]   # de la más reciente a la más vieja
    assert charlas["total"] == 3
    aim = charlas["charlas"][0]
    assert [h["code"] for h in aim["horarios"]] == ["AIM401", "AIM401-R"]
    assert aim["code"] == "AIM401" and aim["day"] == "2026-12-01"


def test_un_horario_que_ya_paso_no_cuenta_aunque_la_charla_tenga_otro(cli, monkeypatch):
    monkeypatch.setattr(sandbox, "ahora", lambda tz=LV: dt.datetime(2026, 12, 1, 12, tzinfo=LV).astimezone(tz))

    charlas = cli.get("/api/charlas-nuevas", headers=cli.H).json()["charlas"]

    assert [c["base"] for c in charlas] == ["AIM401", "OLD100"]
    assert [h["code"] for h in charlas[0]["horarios"]] == ["AIM401-R"]


def test_agregar_la_saca_de_la_lista_y_avisa_el_choque(cli):
    cli.post("/api/itinerary/items", headers=cli.H, json={"code": "VIE200"})

    r = cli.post("/api/charlas-nuevas/agregar", headers=cli.H, json={"code": "DEV302"})

    assert r.status_code == 200
    assert r.json()["choques"] == ["Ya estaba"]
    assert "DEV302" in {i["code"] for i in db.list_itinerary_items(TEST_USER)}
    assert "DEV302" not in _bases(cli)


def test_la_lista_marca_con_que_choca_cada_horario(cli):
    cli.post("/api/itinerary/items", headers=cli.H, json={"code": "VIE200"})

    aim = next(c for c in cli.get("/api/charlas-nuevas", headers=cli.H).json()["charlas"] if c["base"] == "AIM401")

    assert aim["horarios"][0]["choques"] == ["Ya estaba"]
    assert aim["horarios"][1]["choques"] == []


def test_agregada_y_quitada_del_itinerario_no_vuelve(cli):
    cli.post("/api/charlas-nuevas/agregar", headers=cli.H, json={"code": "AIM401-R"})
    cli.delete("/api/itinerary/items/AIM401-R", headers=cli.H)

    assert "AIM401" not in _bases(cli)


def test_descartar_persiste_y_no_se_mezcla_entre_usuarios(cli):
    assert cli.post("/api/charlas-nuevas/AIM401/descartar", headers=cli.H).status_code == 200
    cli.post("/api/charlas-nuevas/agregar", headers=cli.H2, json={"code": "DEV302"})

    assert _bases(cli) == ["DEV302", "OLD100"]
    assert _bases(cli, cli.H2) == ["AIM401", "OLD100"]
    assert "DEV302" not in {i["code"] for i in db.list_itinerary_items(TEST_USER)}


def test_la_que_ya_tenia_en_el_itinerario_no_aparece(cli):
    cli.post("/api/itinerary/items", headers=cli.H, json={"code": "AIM401-R"})

    assert "AIM401" not in _bases(cli)


def test_codigos_que_no_existen_dan_404(cli):
    assert cli.post("/api/charlas-nuevas/agregar", headers=cli.H, json={"code": "NOPE999"}).status_code == 404
    assert cli.post("/api/charlas-nuevas/NOPE999/descartar", headers=cli.H).status_code == 404
    assert cli.post("/api/charlas-nuevas/agregar", headers=cli.H, json={"code": "x'; drop"}).status_code == 422


def test_sin_login_no_se_ve():
    with TestClient(app) as c:
        assert c.get("/api/charlas-nuevas").status_code == 401


def test_lo_de_sus_intereses_va_primero(cli):
    db.save_profile(TEST_USER, "dev", "5", ["Developer Productivity"], "")

    assert _bases(cli) == ["DEV302", "AIM401", "OLD100"]
    assert _bases(cli, cli.H2) == ["AIM401", "DEV302", "OLD100"]


# ---------- push ----------

def test_un_solo_push_agrupado_con_las_de_las_ultimas_24_horas(cli):
    push = Push()

    assert cn.enviar(TEST_USER, AHORA, push) == 1

    [(usuario, mensaje)] = push.enviados
    assert usuario == TEST_USER
    assert mensaje["title"] == "2 charlas nuevas"   # OLD100 entró hace 3 días: está en la lista, pero no se avisa
    assert mensaje["body"] == "AIM401 Agentes con Bedrock y DEV302 Pipelines de CI"
    assert mensaje["url"] == "/#/itinerario/nuevas"


def test_no_se_repite_y_avisa_solo_las_que_aparecen_despues(cli):
    push = Push()
    cn.enviar(TEST_USER, AHORA, push)
    assert cn.enviar(TEST_USER, AHORA, push) == 0

    ALTAS["NUE500"] = REAL
    CATALOGO.append(_sesion("NUE500", "Recién salida", [_inst("NUE500", "2026-12-02", "09:00")]))
    try:
        assert cn.enviar(TEST_USER, AHORA, push) == 1
    finally:
        del ALTAS["NUE500"]
        CATALOGO.pop()

    assert len(push.enviados) == 2
    assert push.enviados[1][1]["title"] == "Charla nueva: NUE500"


def test_mas_de_dos_se_resumen_con_y_n_mas(cli):
    lista = [{"base": f"X{i}", "title": f"T{i}", "interes": False} for i in range(4)]

    assert cn.mensaje(lista)["body"] == "X0 T0, X1 T1 y 2 más"


def test_con_la_preferencia_apagada_no_le_llega_y_al_otro_si(cli):
    assert cli.put("/api/charlas-nuevas/preferencia", headers=cli.H, json={"avisar": False}).json() == {"avisar": False}
    push = Push()

    assert cn.enviar(TEST_USER, AHORA, push) == 0
    assert cn.enviar(TEST_ADMIN, AHORA, push) == 1
    assert [u for u, _ in push.enviados] == [TEST_ADMIN]
    assert cli.get("/api/charlas-nuevas/preferencia", headers=cli.H).json() == {"avisar": False}
    assert cli.get("/api/charlas-nuevas/preferencia", headers=cli.H2).json() == {"avisar": True}


def test_la_preferencia_no_pisa_las_demas(cli):
    db.set_preferencias_avisos(TEST_USER, False, False, eventos_nuevos=False)

    cli.put("/api/charlas-nuevas/preferencia", headers=cli.H, json={"avisar": False})

    assert db.get_preferencias_avisos(TEST_USER) == {"grabar": False, "ubicacion": False, "eventos_nuevos": False}


def test_en_horario_de_silencio_espera_a_la_manana(cli):
    push = Push()

    assert cn.enviar(TEST_USER, NOCHE, push) == 0
    assert cn.enviar(TEST_USER, AHORA, push) == 1
    assert push.enviados[0][1]["title"] == "2 charlas nuevas"


def test_las_descartadas_y_las_pasadas_no_se_avisan(cli):
    cli.post("/api/charlas-nuevas/AIM401/descartar", headers=cli.H)
    push = Push()

    cn.enviar(TEST_USER, AHORA, push)

    assert push.enviados[0][1]["title"] == "Charla nueva: DEV302"


def test_si_no_llega_a_ningun_dispositivo_se_reintenta(cli):
    assert cn.enviar(TEST_USER, AHORA, Push(llega=0)) == 0
    assert cn.enviar(TEST_USER, AHORA, Push()) == 1


def test_si_el_push_falla_no_quedan_marcadas(cli):
    def roto(_u, _m):
        raise TimeoutError

    with pytest.raises(TimeoutError):
        cn.enviar(TEST_USER, AHORA, roto)
    assert cn.enviar(TEST_USER, AHORA, Push()) == 1


def test_las_de_sus_intereses_encabezan_el_aviso(cli):
    db.save_profile(TEST_USER, "dev", "5", ["developer productivity"], "")
    push = Push()

    cn.enviar(TEST_USER, AHORA, push)

    assert push.enviados[0][1]["body"] == "Para vos: DEV302 Pipelines de CI y AIM401 Agentes con Bedrock"


def test_las_claves_de_la_ficha_cuentan_como_intereses(cli, monkeypatch):
    monkeypatch.setattr(cn.db, "get_interview", lambda u: {"ficha": {"prioridades": [{"claves": ["generative AI"]}]}})

    assert cn.claves_de_interes(TEST_USER) == ["generative AI"]
    assert cn.coincide(CATALOGO[0], ["generative AI"]) and not cn.coincide(CATALOGO[1], ["generative AI"])


# ---------- altas en la base del catálogo ----------

@pytest.fixture
def base():
    schema = f"ch_nuevas_{uuid.uuid4().hex[:8]}"
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    with conn.transaction():
        aplicar_migraciones(conn, schema)

    @contextmanager
    def conectar():
        yield conn

    yield conectar, schema, conn
    conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    conn.close()


def test_altas_lee_solo_las_marcadas_desde_la_fecha(base):
    conectar, schema, conn = base
    for id_speech, alta in (("AIM401", REAL), ("DEV302", REAL - dt.timedelta(days=10)), ("MAN100", None)):
        conn.execute(f"INSERT INTO {schema}.speech (id_speech, titulo, tipo, alta) VALUES (%s, %s, %s, %s)",
                     (id_speech, id_speech, "Breakout session", alta))

    assert cn.altas(REAL - dt.timedelta(days=7), conectar=conectar, schema=schema) == {"AIM401": REAL}


def test_altas_sin_el_schema_del_catalogo_no_rompe():
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    schema = f"ch_vacio_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE SCHEMA {schema}")

    @contextmanager
    def conectar():
        yield conn

    try:
        assert cn.altas(REAL, conectar=conectar, schema=schema) == {}
    finally:
        conn.execute(f"DROP SCHEMA {schema} CASCADE")
        conn.close()


# ---------- push: camino liviano y candado ----------

def test_el_push_va_por_el_camino_liviano_sin_armar_el_itinerario(cli, monkeypatch):
    cli.post("/api/itinerary/items", headers=cli.H, json={"code": "AIM401-R"})
    monkeypatch.setattr(cn.itinerary, "get_current", lambda u: pytest.fail("el push no arma el itinerario"))
    push = Push()

    cn.enviar(TEST_USER, AHORA, push)

    assert push.enviados[0][1]["title"] == "Charla nueva: DEV302"   # AIM401 ya está en su itinerario


def test_sin_altas_para_avisar_sale_sin_tocar_la_base(cli, monkeypatch):
    monkeypatch.setattr(cn, "quiere_aviso", lambda u: pytest.fail("no hacía falta leer la preferencia"))

    assert cn.enviar(TEST_USER, AHORA, Push(), {}) == 0


def test_si_otro_worker_tiene_la_tanda_de_la_persona_no_la_parte(cli):
    otro = psycopg.connect(os.environ["DATABASE_URL"])
    try:
        otro.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (cn.CANDADO, TEST_USER))
        push = Push()
        assert cn.enviar(TEST_USER, AHORA, push) == 0
        assert cn.enviar(TEST_ADMIN, AHORA, push) == 1   # el candado es por persona
    finally:
        otro.rollback()
        otro.close()
    assert cn.enviar(TEST_USER, AHORA, Push()) == 1


# ---------- dentro de push.tick ----------

class Servicio:
    """Los servicios de push: el endpoint «malo» se cuelga; el resto recibe."""

    def __init__(self):
        self.recibidos = []

    def __call__(self, sub, payload, http=None, ttl=0):
        if "malo" in sub["endpoint"]:
            raise TimeoutError
        self.recibidos.append((sub["endpoint"], payload["title"]))
        return 201


@pytest.fixture
def tick(cli, monkeypatch):
    """push.tick con lo demás apagado: solo TEST_USER suscripto, con dos dispositivos (uno se cuelga)."""
    monkeypatch.setattr(push_mod.db, "push_usernames", lambda: [TEST_USER])
    monkeypatch.setattr(push_mod.db, "push_subscriptions",
                        lambda u: [{"endpoint": f"https://fcm.googleapis.com/{u}/{n}"} for n in ("bueno", "malo")])
    monkeypatch.setattr(push_mod.documentos, "purgar_si_toca", lambda ahora: None)
    monkeypatch.setattr(push_mod.ofertas, "correr_si_toca", lambda ahora: None)
    monkeypatch.setattr(push_mod, "_avisos_de", lambda u: 0)
    monkeypatch.setattr(push_mod.ofertas_avisos, "enviar", lambda u, ahora, notificar: 0)
    servicio = Servicio()
    monkeypatch.setattr(push_mod, "send", servicio)
    return servicio


def test_un_dispositivo_que_falla_no_hace_que_los_demas_lo_reciban_de_nuevo(tick):
    assert push_mod.tick() == 1
    assert push_mod.tick() == 0

    assert tick.recibidos == [(f"https://fcm.googleapis.com/{TEST_USER}/bueno", "2 charlas nuevas")]


def test_si_no_llega_a_ningun_dispositivo_el_tick_siguiente_reintenta(tick, monkeypatch):
    monkeypatch.setattr(push_mod.db, "push_subscriptions", lambda u: [{"endpoint": "https://fcm.googleapis.com/malo"}])
    assert push_mod.tick() == 0

    monkeypatch.setattr(push_mod.db, "push_subscriptions", lambda u: [{"endpoint": "https://fcm.googleapis.com/bueno"}])
    assert push_mod.tick() == 1


def test_si_las_charlas_nuevas_fallan_no_frenan_ni_ofertas_ni_itinerario(tick, monkeypatch):
    llamados = []
    monkeypatch.setattr(push_mod.db, "push_usernames", lambda: [TEST_USER, TEST_ADMIN])
    monkeypatch.setattr(push_mod, "_avisos_de", lambda u: llamados.append(("itinerario", u)) or 0)
    monkeypatch.setattr(push_mod.ofertas_avisos, "enviar", lambda u, ahora, n: llamados.append(("ofertas", u)) or 0)

    def roto(*_a, **_k):
        raise RuntimeError("catálogo raro")

    monkeypatch.setattr(cn, "enviar", roto)
    push_mod.tick()
    monkeypatch.setattr(cn, "altas", roto)   # tampoco si falla la lectura de las altas
    push_mod.tick()

    assert llamados == [(k, u) for _ in range(2) for u in (TEST_USER, TEST_ADMIN) for k in ("itinerario", "ofertas")]


def test_el_silencio_va_en_hora_de_las_vegas_aunque_el_reloj_venga_en_utc(tick, monkeypatch):
    # 05:00 UTC son las 21:00 del día anterior en Las Vegas: allá todavía no es de noche.
    monkeypatch.setattr(sandbox, "ahora", lambda tz=LV: dt.datetime(2026, 12, 1, 5, tzinfo=dt.UTC))

    assert push_mod.tick() == 1


# ---------- datos del usuario ----------

def test_la_tabla_es_de_datos_del_usuario_y_se_borra_con_ellos(cli):
    assert "charlas_nuevas_decision" in db.tablas_datos_usuario()
    tabla = f"{sandbox.schema_prueba()}.charlas_nuevas_decision"
    with db.conn() as c:
        c.execute(f"INSERT INTO {tabla} (username, base, decision, creado) VALUES (%s, 'AIM401', 'descartada', 0)",
                  (TEST_USER,))

    db.borrar_datos_prueba()

    with db.conn() as c:
        assert c.execute(f"SELECT count(*) AS n FROM {tabla}").fetchone()["n"] == 0

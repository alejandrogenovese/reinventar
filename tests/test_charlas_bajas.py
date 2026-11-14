"""Charlas que se bajan o cambian (app/charlas_auto.py): el buscador público del catálogo oficial, falso
(httpx.MockTransport con la forma real de catalog.awsevents.com/api/search), contra un schema efímero."""
import datetime as dt
import os
import uuid
from contextlib import contextmanager
from urllib.parse import parse_qs

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from app import catalog, changes, charlas_auto, db, eventos_avisos
from app.catalogo_oficial import PERFIL_BUSCADOR, POR_PAGINA_BUSCADOR, BuscadorRoto, bajar_buscador, leer_buscador
from app.eventos_fuentes import TZ_VEGAS
from app.main import app
from scripts.actualizar_catalogo import aplicar_migraciones
from tests.catalogo_fixture import catalogo_v1, catalogo_v2, item
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

AHORA = dt.datetime(2026, 11, 14, 12, tzinfo=dt.UTC)


def _items(crudo: dict) -> list[dict]:
    return [it for sec in crudo["sectionList"] for it in sec["items"]]


class Buscador:
    """El buscador público, falso: pagina de a 50 como el real (la primera en sectionList, el resto en items)."""

    def __init__(self, items: list[dict]):
        self.items = items
        self.caido = False
        self.pedidos = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        assert req.method == "POST" and req.url.host == "catalog.awsevents.com"
        assert req.headers["rfApiProfileId"] == PERFIL_BUSCADOR
        self.pedidos += 1
        if self.caido:
            return httpx.Response(503)
        form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        desde = int(form["from"])
        pagina = self.items[desde:desde + POR_PAGINA_BUSCADOR]
        total = len(self.items)
        if desde == 0:
            return httpx.Response(200, json={"responseCode": "0", "totalSearchItems": total, "sections": True,
                                             "sectionList": [{"sectionId": "1", "total": total, "items": pagina}]})
        return httpx.Response(200, json={"responseCode": "0", "total": total, "from": desde, "items": pagina})


@pytest.fixture
def base():
    schema = f"ch_auto_{uuid.uuid4().hex[:8]}"
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    with conn.transaction():
        aplicar_migraciones(conn, schema)

    @contextmanager
    def conectar():
        yield conn

    yield conectar, schema, conn
    conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    conn.close()


def _revisar(base, buscador, ahora=AHORA):
    conectar, schema, _conn = base
    http = httpx.Client(transport=httpx.MockTransport(buscador))
    return charlas_auto.revisar(conectar=conectar, schema=schema, http=http, ahora=ahora, pausa=lambda: None)


def _carga_manual(base, items):
    """Lo que hoy deja scripts/actualizar_catalogo.py: el catálogo cargado, sin «charlas nuevas»."""
    buscador = Buscador(items)
    _revisar(base, buscador)
    _c, schema, conn = base
    conn.execute(f"UPDATE {schema}.speech SET alta = NULL")
    return buscador


def _horarios(base):
    _c, schema, conn = base
    filas = conn.execute(f"SELECT codigo, id_speech, fecha, hora_inicio, id_sede, sala, falta_desde, cancelado_desde "
                         f"FROM {schema}.speech_horario").fetchall()
    campos = ("codigo", "base", "fecha", "hora", "sede", "sala", "falta", "cancelado")
    return {f[0]: dict(zip(campos, f, strict=True)) for f in filas}


def _sin(items, codigo):
    return [i for i in items if i["code"] != codigo]


# ---------- bajas ----------

def test_la_primera_falta_avisa_y_la_segunda_cancela(base):
    items = _items(catalogo_v1())
    buscador = _carga_manual(base, items)
    buscador.items = _sin(items, "DEV300")

    _revisar(base, buscador, AHORA + dt.timedelta(hours=3))
    dev = _horarios(base)["DEV300"]
    assert dev["falta"] == AHORA + dt.timedelta(hours=3) and dev["cancelado"] is None

    r = _revisar(base, buscador, AHORA + dt.timedelta(hours=6))
    assert _horarios(base)["DEV300"]["cancelado"] == AHORA + dt.timedelta(hours=6)
    assert r["cancelados"] == ["DEV300"] and r["conteo"]["cancelados"] == 1
    assert all(h["falta"] is None for c, h in _horarios(base).items() if c != "DEV300")


def test_si_reaparece_se_limpia(base):
    items = _items(catalogo_v1())
    buscador = _carga_manual(base, items)
    buscador.items = _sin(items, "DEV300")
    for horas in (3, 6):
        _revisar(base, buscador, AHORA + dt.timedelta(hours=horas))

    buscador.items = items
    _revisar(base, buscador, AHORA + dt.timedelta(hours=9))

    assert (_horarios(base)["DEV300"]["falta"], _horarios(base)["DEV300"]["cancelado"]) == (None, None)


def test_dos_revisiones_muy_seguidas_no_alcanzan_para_cancelar(base):
    items = _items(catalogo_v1())
    buscador = _carga_manual(base, items)
    buscador.items = _sin(items, "DEV300")

    for minutos in (10, 20):
        _revisar(base, buscador, AHORA + dt.timedelta(minutes=minutos))

    assert _horarios(base)["DEV300"]["cancelado"] is None


def test_lo_que_ya_paso_no_se_cancela(base):
    items = _items(catalogo_v1())
    buscador = _carga_manual(base, items)
    buscador.items = _sin(items, "DEV300")
    despues = dt.datetime(2026, 12, 3, tzinfo=dt.UTC)

    for horas in (0, 3):
        _revisar(base, buscador, despues + dt.timedelta(hours=horas))

    assert _horarios(base)["DEV300"]["falta"] is None


def test_si_el_catalogo_falla_no_se_cancela_nada_y_queda_registrado(base):
    conectar, schema, conn = base
    buscador = _carga_manual(base, _items(catalogo_v1()))
    buscador.caido = True

    for horas in (3, 6):
        r = _revisar(base, buscador, AHORA + dt.timedelta(hours=horas))

    assert r["error"].startswith("HTTPStatusError")
    assert all(h["falta"] is None and h["cancelado"] is None for h in _horarios(base).values())
    ok, total = conn.execute(f"SELECT ok, total FROM {schema}.evento_revision WHERE fuente = 'catalogo'").fetchone()
    assert (ok, total) == (False, 6)  # se conserva el total de la última revisión que anduvo


def test_si_el_catalogo_trae_menos_de_la_mitad_no_se_cancela_nada_ni_se_vuelve_referencia(base):
    items = _items(catalogo_v1())
    buscador = _carga_manual(base, items)
    buscador.items = items[:2]

    for horas in (3, 6, 9):
        r = _revisar(base, buscador, AHORA + dt.timedelta(hours=horas))

    assert all(h["falta"] is None and h["cancelado"] is None for h in _horarios(base).values())
    assert r["conteo"]["total"] == 6
    buscador.caido = True  # y después de una caída, la referencia sigue siendo la de la última revisión entera
    _revisar(base, buscador, AHORA + dt.timedelta(hours=12))
    buscador.caido = False
    _revisar(base, buscador, AHORA + dt.timedelta(hours=15))
    assert all(h["falta"] is None for h in _horarios(base).values())


def test_un_catalogo_incompleto_es_un_error():
    def respuesta(req):
        return httpx.Response(200, json={"responseCode": "0", "totalSearchItems": 80,
                                         "sectionList": [{"total": 80, "items": [{"code": "X"}] * 50}]}) \
            if b"from=0" in req.content else httpx.Response(200, json={"responseCode": "0", "total": 80, "items": []})

    with pytest.raises(BuscadorRoto, match="incompleto"):
        bajar_buscador(httpx.Client(transport=httpx.MockTransport(respuesta)), lambda: None)


# ---------- cambios ----------

def test_cambio_de_sala_y_horario_actualiza_solo_eso(base):
    _c, schema, conn = base
    items = _items(catalogo_v1())
    buscador = _carga_manual(base, items)
    conn.execute(f"UPDATE {schema}.speech SET titulo = 'Título curado', resumen_es = 'Resumen traducido' "
                 f"WHERE id_speech = 'ARC100'")
    movida = item("ARC100", "s-arc100", "t-arc100", titulo="Otro título de AWS", inicio="11:30", fin="12:30",
                  room="Wynn/Encore | Level 1 | Chopin 4")
    buscador.items = [movida if i["code"] == "ARC100" else i for i in items]

    r = _revisar(base, buscador, AHORA + dt.timedelta(hours=3))

    arc = _horarios(base)["ARC100"]
    assert (arc["hora"], arc["sede"], arc["sala"]) == (dt.time(11, 30), 3, "Level 1 · Chopin 4")
    assert conn.execute(f"SELECT titulo, resumen_es FROM {schema}.speech WHERE id_speech = 'ARC100'").fetchone() == \
        ("Título curado", "Resumen traducido")
    assert r["conteo"]["cambiados"] == 1


def test_renombre_mantiene_el_horario_con_el_codigo_nuevo(base):
    _c, schema, conn = base
    buscador = _carga_manual(base, _items(catalogo_v1()))
    buscador.items = _items(catalogo_v2())  # PEX321 → PEX218 (mismo sessionTimeID) y SEC200-S se da de baja

    r = _revisar(base, buscador, AHORA + dt.timedelta(hours=3))

    horarios = _horarios(base)
    assert "PEX321" not in horarios and horarios["PEX218"]["base"] == "PEX218"
    assert horarios["PEX218"]["falta"] is None and horarios["SEC200-S"]["falta"] is not None
    assert r["renombres"] == [("PEX321", "PEX218")]
    assert conn.execute(f"SELECT codigo_viejo, codigo_nuevo, aws_time_id FROM {schema}.codigo_renombrado").fetchall() \
        == [("PEX321", "PEX218", "t-pex")]
    # la charla nueva por renombre no es una «charla nueva» para el admin
    assert charlas_auto.nuevas(base[0], schema) == []


def test_charla_nueva_entra_con_lo_del_oficial_y_aparece_para_el_admin(base):
    conectar, schema, conn = base
    items = _items(catalogo_v1())
    buscador = _carga_manual(base, items)
    buscador.items = [*items, item("NEW500", "s-new", "t-new", titulo="Agentes nuevos", fecha="2026-12-03",
                                   room="Venetian | Level 2 | Lando 4201")]

    r = _revisar(base, buscador, AHORA + dt.timedelta(hours=3))

    assert r["conteo"]["nuevos"] == 1 and _horarios(base)["NEW500"]["sede"] == 7
    assert conn.execute(f"SELECT resumen, resumen_es FROM {schema}.speech WHERE id_speech = 'NEW500'").fetchone() == \
        ("Resumen de Agentes nuevos.", None)
    nuevas = charlas_auto.nuevas(conectar, schema)
    assert [(n["base"], n["titulo"], n["horarios"]) for n in nuevas] == [("NEW500", "Agentes nuevos", 1)]


def test_una_repeticion_nueva_de_una_charla_que_ya_esta_no_es_charla_nueva(base):
    conectar, schema, _conn = base
    items = _items(catalogo_v1())
    buscador = _carga_manual(base, items)
    buscador.items = [*items, item("ARC100-R1", "s-arc100r1", "t-arc100r1", fecha="2026-12-04")]

    _revisar(base, buscador, AHORA + dt.timedelta(hours=3))

    assert _horarios(base)["ARC100-R1"]["base"] == "ARC100" and charlas_auto.nuevas(conectar, schema) == []


def test_sede_sin_mapear_no_rompe_la_revision(base):
    conectar, schema, conn = base
    items = _items(catalogo_v1())
    buscador = _carga_manual(base, items)
    buscador.items = [*items, item("ZZZ900", "s-zzz", "t-zzz", room="Hotel Nuevo | Salón 1")]

    _revisar(base, buscador, AHORA + dt.timedelta(hours=3))

    assert "ZZZ900" not in _horarios(base)
    detalle = conn.execute(f"SELECT detalle FROM {schema}.evento_revision WHERE fuente = 'catalogo'").fetchone()[0]
    assert "Hotel Nuevo" in detalle


def test_un_item_con_dos_horarios_no_rompe_la_lectura():
    doble = item("COP370", "s-cop", "t-cop-1")
    doble["times"].append({**doble["times"][0], "sessionTimeID": "t-cop-2"})

    horarios, charlas = leer_buscador([doble, item("ARC100", "s-arc100", "t-arc100")])

    assert sorted(h.aws_time_id for h in horarios) == ["t-arc100", "t-cop-1", "t-cop-2"]
    assert set(charlas) == {"COP370", "ARC100"}


def test_pagina_de_a_50_con_pausa_entre_pedidos():
    items = [item(f"T{i:03d}", f"s{i}", f"t{i}") for i in range(120)]
    buscador, pausas = Buscador(items), []

    bajados = bajar_buscador(httpx.Client(transport=httpx.MockTransport(buscador)), lambda: pausas.append(1))

    assert len(bajados) == 120 and buscador.pedidos == 3 and len(pausas) == 2


def test_frecuencia_cada_3_horas_en_noviembre_y_cada_30_min_en_el_evento():
    assert charlas_auto.intervalo(AHORA) == dt.timedelta(hours=3)
    assert charlas_auto.intervalo(dt.datetime(2026, 11, 29, 9, tzinfo=TZ_VEGAS)) == dt.timedelta(minutes=30)
    assert charlas_auto.intervalo(dt.datetime(2026, 12, 4, 23, tzinfo=TZ_VEGAS)) == dt.timedelta(minutes=30)
    assert charlas_auto.intervalo(dt.datetime(2026, 11, 29, 7, tzinfo=dt.UTC)) == dt.timedelta(hours=3)  # 28/11 en Vegas


def test_sin_la_migracion_la_revision_avisa_y_nuevas_es_vacia(base):
    conectar, schema, conn = base
    conn.execute(f"ALTER TABLE {schema}.speech_horario DROP COLUMN falta_desde")

    with pytest.raises(charlas_auto.MigracionPendiente):
        _revisar(base, Buscador([]))
    conn.execute(f"ALTER TABLE {schema}.speech DROP COLUMN alta")
    assert charlas_auto.nuevas(conectar, schema) == []


# ---------- la app ----------

def test_la_tarjeta_trae_la_duda_y_la_cancelacion():
    sesion = {"base": "AIM301", "title": "Agentes"}

    en_duda = catalog.card(sesion, {"c": "AIM301", "d": "2026-12-02", "st": "10:00", "falta": "2026-11-30T22:30:00+00:00",
                                    "cancelada": False})
    cancelada = catalog.card(sesion, {"c": "AIM301", "falta": "2026-11-30T22:30:00+00:00", "cancelada": True})
    sin_migracion = catalog.card(sesion, {"c": "AIM301"})

    assert (en_duda["missing_since"], en_duda["cancelled"]) == ("14:30", False)
    assert (cancelada["missing_since"], cancelada["cancelled"]) == (None, True)
    assert (sin_migracion["missing_since"], sin_migracion["cancelled"]) == (None, False)


def _dia_con(**charla):
    card = {"kind": "talk", "code": "AIM301", "title": "Agentes", "day": "2026-12-02", "start": "10:00", **charla}
    return [{"day": card["day"], "sessions": [card]}]


def test_push_de_charla_cancelada_solo_si_no_empezo_y_no_de_noche():
    de_dia = dt.datetime(2026, 11, 30, 10, tzinfo=TZ_VEGAS)

    avisos = eventos_avisos.avisos(_dia_con(cancelled=True), de_dia, quiere_nuevos=False, ultimo_nuevos=None)

    assert [(k, m["title"]) for k, m in avisos] == [("chcancel:AIM301", "Se canceló AIM301 (mié 2/12 10:00)")]
    assert eventos_avisos.charlas_canceladas(_dia_con(cancelled=False), de_dia) == []
    assert eventos_avisos.charlas_canceladas(_dia_con(cancelled=True, day="2026-11-30", start="09:00"), de_dia) == []
    de_noche = dt.datetime(2026, 11, 30, 23, tzinfo=TZ_VEGAS)
    assert eventos_avisos.avisos(_dia_con(cancelled=True), de_noche, quiere_nuevos=False, ultimo_nuevos=None) == []


def test_titulo_del_push_de_cambio_de_sala_u_horario():
    antes = {"title": "Agentes", "day": "2026-12-02", "start": "10:00", "venue": "MGM Grand · Level 3 · Premier 311"}

    sala = changes.push_title("AIM301", "talk", antes, {**antes, "venue": "Wynn/Encore · Level 1 · Chopin 4"})
    hora = changes.push_title("AIM301", "talk", antes, {**antes, "start": "11:30"})

    assert sala == "AIM301 cambió de sala: ahora Wynn/Encore · Level 1 · Chopin 4"
    assert hora == "AIM301 cambió de horario: ahora mié 2/12 11:30"
    assert changes.push_title("evt-1", "event", antes, {**antes, "start": "11:30"}) == "Cambió algo de tu itinerario"


@pytest.fixture
def cli():
    with TestClient(app) as c:
        c.H = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        yield c


def test_renombre_pasa_los_itinerarios_al_codigo_nuevo(cli):
    db.add_item("tester", "PEX321", "PEX321", "2026-12-01", "10:00", locked=True)
    db.add_item(TEST_ADMIN, "PEX321", "PEX321", "2026-12-01", "10:00")
    db.add_item(TEST_ADMIN, "PEX218", "PEX218", "2026-12-01", "10:00")  # ya tenía el nuevo: el viejo sobra
    try:
        assert db.renombrar_codigos([("PEX321", "PEX218", "PEX218")]) == 1

        tester = {i["code"]: i for i in db.list_itinerary_items("tester")}
        assert "PEX321" not in tester and tester["PEX218"]["base"] == "PEX218" and tester["PEX218"]["locked"]
        assert [i["code"] for i in db.list_itinerary_items(TEST_ADMIN) if i["code"].startswith("PEX")] == ["PEX218"]
    finally:
        for usuario in ("tester", TEST_ADMIN):
            db.remove_item(usuario, "PEX218")


def test_revisar_ahora_renombra_itinerarios_y_recarga_el_catalogo(monkeypatch):
    llamadas = []
    monkeypatch.setattr(charlas_auto, "revisar", lambda **kw: {"estado": "ok", "error": None,
                                                               "renombres_base": [("A", "B", "B")]})
    monkeypatch.setattr(charlas_auto.db, "renombrar_codigos", lambda r: llamadas.append(("renombrar", r)))
    monkeypatch.setattr(charlas_auto.catalog, "load", lambda: llamadas.append("load"))

    with charlas_auto._en_curso:
        assert charlas_auto.revisar_ahora() == {"estado": "ocupado"}
    charlas_auto.revisar_ahora()

    assert llamadas == [("renombrar", [("A", "B", "B")]), "load"]


def test_apagado_sin_la_variable(monkeypatch):
    arrancados = []
    monkeypatch.setattr(charlas_auto.config, "EVENTOS_AUTO", False)
    monkeypatch.setattr(charlas_auto.threading, "Thread", lambda **kw: arrancados.append(kw))

    charlas_auto.start_worker()

    assert arrancados == []


def test_el_admin_ve_las_charlas_nuevas(cli, monkeypatch):
    monkeypatch.setattr(charlas_auto, "nuevas", lambda: [{"base": "NEW500", "titulo": "Agentes nuevos"}])

    r = cli.get("/api/admin/eventos", headers=cli.H)

    assert r.status_code == 200 and r.json()["charlas_nuevas"][0]["base"] == "NEW500"


def test_revisar_ahora_desde_el_admin_arranca_tambien_las_charlas(cli, monkeypatch):
    arrancadas = []
    monkeypatch.setattr(charlas_auto.config, "EVENTOS_AUTO", True)
    monkeypatch.setattr("app.eventos_auto.en_segundo_plano", lambda: arrancadas.append("eventos") or False)
    monkeypatch.setattr(charlas_auto, "en_segundo_plano", lambda: arrancadas.append("charlas") or True)

    assert cli.post("/api/admin/eventos/revisar", headers=cli.H).status_code == 202
    assert arrancadas == ["eventos", "charlas"]

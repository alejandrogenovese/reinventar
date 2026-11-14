"""Shows de Ticketmaster: limpieza, agrupado, estados, la revisión en un schema efímero (Ticketmaster falso con
httpx.MockTransport, respuestas armadas según la doc pública de la Discovery API v2), la key fuera de los logs y la API."""
import datetime as dt
import logging
import os
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from app import eventos_auto, eventos_avisos, shows, ticketmaster
from app.main import app
from scripts.actualizar_catalogo import aplicar_migraciones
from tests.conftest import login_headers

KEY = "clave-secreta-de-prueba-123"
AHORA = dt.datetime(2026, 11, 14, 12, tzinfo=dt.UTC)
SALA_BELLAGIO = {"id": "KovZpZAEdntA", "name": "O Theatre at Bellagio", "address": {"line1": "3600 S Las Vegas Blvd"},
                 "city": {"name": "Las Vegas"}, "location": {"latitude": "36.1126", "longitude": "-115.1767"}}
SALA_SPHERE = {"id": "KovZ917ACc0", "name": "Sphere", "location": {"latitude": "36.1208", "longitude": "-115.1622"}}


def _ev(id_, nombre="O - Cirque du Soleil", inicio="2026-12-01T03:00:00Z", *, sala=SALA_BELLAGIO,
        atraccion=("K8vZ917Kew0", "Cirque du Soleil - O"), segmento="Arts & Theatre", genero="Theatre",
        estado="onsale", precio=99.5, **extra):
    """Un evento como lo devuelve /discovery/v2/events.json."""
    ev = {
        "id": id_, "name": nombre, "type": "event", "url": f"https://www.ticketmaster.com/event/{id_}",
        "images": [{"ratio": "16_9", "url": f"https://s1.ticketm.net/dam/a/{id_}_640.jpg", "width": 640, "height": 360},
                   {"ratio": "16_9", "url": f"https://s1.ticketm.net/dam/a/{id_}_2048.jpg", "width": 2048},
                   {"ratio": "3_2", "url": f"https://s1.ticketm.net/dam/a/{id_}_305.jpg", "width": 305}],
        "dates": {"start": {"localDate": "2026-11-30", "localTime": "19:00:00", "dateTime": inicio,
                            "dateTBD": False, "dateTBA": False, "timeTBA": False, "noSpecificTime": False},
                  "timezone": "America/Los_Angeles", "status": {"code": estado}, "spanMultipleDays": False},
        "classifications": [{"primary": True, "segment": {"id": "x", "name": segmento}, "genre": {"name": genero},
                             "subGenre": {"name": "Undefined"}, "type": {"name": "Undefined"},
                             "subType": {"name": "Undefined"}}],
        "_embedded": {"venues": [sala] if sala else [],
                      "attractions": [{"id": atraccion[0], "name": atraccion[1]}] if atraccion else []},
    }
    if precio is not None:
        ev["priceRanges"] = [{"type": "standard", "currency": "USD", "min": precio, "max": 250.0}]
    return {**ev, **extra}


def _pagina(eventos, total=None, numero=0, paginas=1):
    total = len(eventos) if total is None else total
    return {"_embedded": {"events": eventos}, "page": {"size": 200, "totalElements": total,
                                                      "totalPages": paginas, "number": numero}}


# ---------- limpieza ----------

def _clases(**cambios):
    ev = _ev("A1")
    ev["classifications"][0].update(cambios)
    return ev


@pytest.mark.parametrize(("ev", "motivo"), [
    (_clases(type={"name": "Upsell"}), "clasificación"),
    (_clases(subType={"name": "Parking"}), "clasificación"),
    (_clases(genre={"name": "Add-On"}), "clasificación"),
    (_clases(segment={"name": "Undefined"}), "clasificación"),
    (_ev("A1", "O - Cirque du Soleil - Parking Pass"), "nombre"),
    (_ev("A1", "Seat Upgrade"), "nombre"),
    (_ev("A1", "U2 VIP Package"), "nombre"),
    (_ev("A1", "Gift Card $50"), "nombre"),
    (_ev("A1", "Souvenir Program"), "nombre"),
    (_ev("A1", "Show Voucher"), "nombre"),
    (_ev("A1", sala=None), "sin sala"),
    (_ev("A1", dates={"start": {"localDate": "2026-12-01", "noSpecificTime": True}, "status": {"code": "onsale"}}),
     "sin hora"),
    (_ev("A1", dates={"start": {"dateTime": "2026-12-01T03:00:00Z"}, "spanMultipleDays": True}), "varios días"),
    (_ev("A1", source={"name": "tmr"}), "reventa"),
])
def test_descarta_el_ruido(ev, motivo):
    assert ticketmaster.descarte(ev) == motivo
    assert ticketmaster.funcion(ev) is None


def test_undefined_en_tipo_y_genero_no_descarta_un_show_normal():
    ev = _clases(genre={"name": "Undefined"})

    assert ticketmaster.descarte(ev) is None


def test_una_funcion_limpia():
    f = ticketmaster.funcion(_ev("A1"))

    assert (f.id_funcion, f.nombre, f.artista, f.tipo, f.sala) == (
        "A1", "O - Cirque du Soleil", "Cirque du Soleil - O", "teatro", "O Theatre at Bellagio")
    assert f.direccion == "3600 S Las Vegas Blvd, Las Vegas" and (f.lat, f.lng) == (36.1126, -115.1767)
    assert f.inicio == dt.datetime(2026, 12, 1, 3, tzinfo=dt.UTC) and f.estado == "onsale"
    assert f.precio_desde == Decimal("99.50")
    assert f.imagen_url == "https://s1.ticketm.net/dam/a/A1_640.jpg"  # la 16:9 más chica que llena la tarjeta
    assert f.url == "https://www.ticketmaster.com/event/A1"


def test_precio_solo_si_viene_y_en_dolares():
    assert ticketmaster.funcion(_ev("A1", precio=None)).precio_desde is None
    assert ticketmaster.funcion(_ev("A1", priceRanges=[{"currency": "EUR", "min": 10}])).precio_desde is None


@pytest.mark.parametrize(("segmento", "genero", "tipo"), [
    ("Music", "Rock", "musica"), ("Sports", "Hockey", "deportes"), ("Arts & Theatre", "Comedy", "comedia"),
    ("Arts & Theatre", "Magic & Illusion", "teatro"), ("Miscellaneous", "Fairs & Festivals", "actividades"),
    ("Miscellaneous", "Comedy", "comedia"),
])
def test_tipo_por_segmento_y_genero(segmento, genero, tipo):
    assert ticketmaster.funcion(_ev("A1", segmento=segmento, genero=genero)).tipo == tipo


@pytest.mark.parametrize(("codigo", "estado"), [
    ("onsale", "onsale"), ("offsale", "offsale"), ("canceled", "canceled"), ("cancelled", "canceled"),
    ("postponed", "postponed"), ("rescheduled", "rescheduled"), ("raro", "onsale"),
])
def test_estados(codigo, estado):
    assert ticketmaster.funcion(_ev("A1", estado=codigo)).estado == estado


def test_link_e_imagen_solo_https():
    f = ticketmaster.funcion(_ev("A1", url="javascript:alert(1)", images=[{"url": "http://x/a.jpg", "width": 900}]))

    assert f.url is None and f.imagen_url is None


def test_agrupa_las_funciones_por_artista_y_sala():
    noche1, noche2 = _ev("A1"), _ev("A2", inicio="2026-12-02T03:00:00Z")
    otra_sala = _ev("A3", sala=SALA_SPHERE)
    sin_artista = [_ev("B1", "Área 15 · Omega Mart", atraccion=None),
                   _ev("B2", "AREA 15 - omega mart!", inicio="2026-12-02T03:00:00Z", atraccion=None)]

    f = {x.id_funcion: x for x in ticketmaster.limpiar([noche1, noche2, otra_sala, *sin_artista])}

    assert f["A1"].id_show == f["A2"].id_show != f["A3"].id_show
    assert f["B1"].id_show == f["B2"].id_show  # sin artista: por el nombre normalizado


def test_sin_repetidos_ni_la_misma_funcion_de_reventa():
    original = _ev("A1")
    copia = _ev("Z9")  # mismo show, misma hora, otro id

    assert [f.id_funcion for f in ticketmaster.limpiar([original, original, copia])] == ["A1"]


def test_dias_de_la_semana_en_hora_de_las_vegas():
    rangos = ticketmaster.dias()

    assert len(rangos) == 6
    assert rangos[0] == (ticketmaster.DESDE, dt.datetime(2026, 11, 30, 7, 59, 59, tzinfo=dt.UTC))
    assert rangos[-1][1] == ticketmaster.HASTA


# ---------- revisión completa ----------

@pytest.fixture
def base():
    schema = f"tm_{uuid.uuid4().hex[:8]}"
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    with conn.transaction():
        aplicar_migraciones(conn, schema)

    @contextmanager
    def conectar():
        yield conn

    yield conectar, schema, conn
    conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    conn.close()


class Ticketmaster:
    """La Discovery API falsa (y Luma y conferenceparties vacíos). Se cambia entre revisiones."""

    def __init__(self, eventos):
        self.eventos = list(eventos)
        self.sueltas: dict[str, httpx.Response] = {}
        self.total: int | None = None
        self.status = 200
        self.pedidos: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.host == "api.lu.ma":
            return httpx.Response(200, json={"entries": [], "has_more": False})
        if req.url.host != "app.ticketmaster.com":
            return httpx.Response(503)
        self.pedidos.append(req)
        assert req.url.params["apikey"] == KEY
        if self.status != 200:  # Ticketmaster repite la key en el cuerpo del error
            return httpx.Response(self.status, json={"fault": {"faultstring": f"Rate limit for apikey={KEY}"}})
        if req.url.path.endswith("/events.json"):
            return httpx.Response(200, json=_pagina(self.eventos, self.total))
        id_ = req.url.path.rsplit("/", 1)[-1].removesuffix(".json")
        return self.sueltas.get(id_, httpx.Response(404, json={"errors": [{"code": "DIS1004"}]}))


@pytest.fixture
def con_key(monkeypatch):
    monkeypatch.setattr(eventos_auto.config, "TICKETMASTER_API_KEY", KEY)


def _revisar(base, tm, ahora=AHORA):
    conectar, schema, _conn = base
    http = httpx.Client(transport=httpx.MockTransport(tm))
    return eventos_auto.revisar(conectar=conectar, schema=schema, http=http, resumir=lambda _: ({}, ()), ahora=ahora,
                                pausa=lambda: None)


def _funciones(base):
    _c, schema, conn = base
    filas = conn.execute(f"SELECT id_funcion, estado, inicio, precio_desde FROM {schema}.show_funcion").fetchall()
    return {f[0]: {"estado": f[1], "inicio": f[2], "precio": f[3]} for f in filas}


def _revision(base):
    _c, schema, conn = base
    return conn.execute(f"SELECT ok, total, nuevos, cambiados, cancelados, detalle FROM {schema}.evento_revision "
                        "WHERE fuente = 'ticketmaster'").fetchone()


def test_la_revision_guarda_las_funciones_limpias(base, con_key):
    tm = Ticketmaster([_ev("A1"), _ev("A2", inicio="2026-12-02T03:00:00Z"), _ev("P1", "Parking Pass")])

    r = _revisar(base, tm)

    assert set(_funciones(base)) == {"A1", "A2"}
    assert r["fuentes"]["ticketmaster"]["nuevos"] == 2
    assert _revision(base)[:3] == (True, 2, 2)
    params = tm.pedidos[0].url.params
    assert (params["dmaId"], params["size"], params["sort"]) == ("319", "200", "date,asc")
    assert (params["startDateTime"], params["endDateTime"]) == ("2026-11-29T08:00:00Z", "2026-12-05T07:59:59Z")
    assert set(params["segmentId"].split(",")) == set(ticketmaster.SEGMENTOS)


def test_estados_cambios_y_lo_igual_no_se_reescribe(base, con_key):
    tm = Ticketmaster([_ev(i, inicio=f"2026-12-0{n}T03:00:00Z") for n, i in enumerate(("A1", "A2", "A3", "A4", "A5"), 1)])
    _revisar(base, tm)
    tm.eventos = [_ev("A1", inicio="2026-12-01T03:00:00Z", estado="canceled"),
                  _ev("A2", inicio="2026-12-02T03:00:00Z", estado="postponed"),
                  _ev("A3", inicio="2026-12-03T05:30:00Z", estado="rescheduled"),
                  _ev("A4", inicio="2026-12-04T03:00:00Z", estado="offsale"),
                  _ev("A5", inicio="2026-12-05T03:00:00Z")]

    r = _revisar(base, tm, AHORA + dt.timedelta(hours=3))

    f = _funciones(base)
    assert [f[i]["estado"] for i in ("A1", "A2", "A3", "A4", "A5")] == [
        "canceled", "postponed", "rescheduled", "offsale", "onsale"]
    assert f["A3"]["inicio"] == dt.datetime(2026, 12, 3, 5, 30, tzinfo=dt.UTC)
    assert r["fuentes"]["ticketmaster"] == {"total": 5, "nuevos": 0, "cambiados": 4, "cancelados": 1, "pendientes": 0}


def test_una_funcion_que_desaparece_se_consulta_antes_de_cancelarla(base, con_key):
    siguen = [_ev("A1"), _ev("A5", inicio="2026-11-30T03:00:00Z"), _ev("A6", inicio="2026-12-05T03:00:00Z")]
    tm = Ticketmaster([*siguen, _ev("A2", inicio="2026-12-02T03:00:00Z"), _ev("A3", inicio="2026-12-03T03:00:00Z"),
                       _ev("A4", inicio="2026-12-04T03:00:00Z")])
    _revisar(base, tm)
    tm.eventos = siguen
    tm.sueltas = {"A2": httpx.Response(200, json=_ev("A2", inicio="2026-12-09T03:00:00Z")),  # se mudó de semana
                  "A3": httpx.Response(500)}                                                 # no se pudo consultar
    tm.pedidos.clear()  # A4: 404 → ya no existe

    _revisar(base, tm, AHORA + dt.timedelta(hours=3))

    f = _funciones(base)
    consultadas = sorted(p.url.path for p in tm.pedidos if not p.url.path.endswith("/events.json"))
    assert consultadas == [f"/discovery/v2/events/{i}.json" for i in ("A2", "A3", "A4")]
    assert (f["A2"]["estado"], f["A2"]["inicio"].day) == ("onsale", 9)
    assert f["A3"]["estado"] == "onsale"     # error al consultar: queda como estaba
    assert f["A4"]["estado"] == "canceled"


def test_si_viene_menos_de_la_mitad_no_se_consulta_ninguna_faltante(base, con_key):
    tm = Ticketmaster([_ev(f"A{n}", inicio=f"2026-12-0{n}T03:00:00Z") for n in range(1, 5)])
    _revisar(base, tm)
    tm.eventos = [_ev("A1")]
    tm.pedidos.clear()

    _revisar(base, tm, AHORA + dt.timedelta(hours=3))

    assert all(p.url.path.endswith("/events.json") for p in tm.pedidos)
    assert {e["estado"] for e in _funciones(base).values()} == {"onsale"}


def test_con_mil_o_mas_se_pide_un_dia_por_vez(base, con_key):
    tm = Ticketmaster([_ev("A1")])
    tm.total = 1000

    _revisar(base, tm)

    rangos = [(p.url.params["startDateTime"], p.url.params["endDateTime"]) for p in tm.pedidos]
    assert rangos[0] == ("2026-11-29T08:00:00Z", "2026-12-05T07:59:59Z")
    assert rangos[1:] == [(ticketmaster._iso(d), ticketmaster._iso(h)) for d, h in ticketmaster.dias()]
    assert _revision(base)[5] == "pedido un día por vez"


def test_pagina_hasta_el_tope(base, con_key):
    paginas = []

    def handler(req):
        if req.url.host != "app.ticketmaster.com":
            return httpx.Response(200, json={"entries": [], "has_more": False})
        n = int(req.url.params["page"])
        paginas.append(n)
        return httpx.Response(200, json=_pagina([_ev(f"P{n}", inicio=f"2026-12-0{n + 1}T03:00:00Z")], 500, n, 3))

    _revisar(base, handler)

    assert paginas == [0, 1, 2] and set(_funciones(base)) == {"P0", "P1", "P2"}


def test_lo_que_paso_hace_mas_de_un_dia_se_borra(base, con_key):
    tm = Ticketmaster([_ev("A1", inicio="2026-11-29T20:00:00Z"), _ev("A2", inicio="2026-12-03T03:00:00Z")])
    _revisar(base, tm)

    _revisar(base, tm, dt.datetime(2026, 12, 1, 12, tzinfo=dt.UTC))

    assert set(_funciones(base)) == {"A2"}


def test_la_key_no_sale_en_los_logs_ni_en_la_base(base, con_key, caplog):
    caplog.set_level(logging.DEBUG)
    tm = Ticketmaster([_ev("A1")])
    tm.status = 429

    r = _revisar(base, tm)

    assert r["errores"]["ticketmaster"] == "HTTP 429"
    revision = _revision(base)
    assert revision[0] is False and revision[5] == "HTTP 429"
    assert KEY not in caplog.text and "apikey" not in caplog.text
    assert tm.pedidos  # sí se pidió (con la key en la URL)


def test_logger_de_httpx_no_loguea_urls():
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


def test_sin_respuesta_tampoco_filtra_la_url(base, con_key, caplog):
    caplog.set_level(logging.DEBUG)

    def handler(req):
        if req.url.host == "app.ticketmaster.com":
            raise httpx.ConnectError(f"no pude con {req.url}")
        return httpx.Response(200, json={"entries": [], "has_more": False})

    r = _revisar(base, handler)

    assert r["errores"]["ticketmaster"] == "sin respuesta (ConnectError)" and KEY not in caplog.text


def test_sin_key_no_se_pide_nada(base, monkeypatch):
    monkeypatch.setattr(eventos_auto.config, "TICKETMASTER_API_KEY", "")
    tm = Ticketmaster([_ev("A1")])

    r = _revisar(base, tm)

    assert tm.pedidos == [] and "ticketmaster" not in r["fuentes"] and _revision(base) is None


def test_sin_la_migracion_la_revision_de_eventos_sigue(base, con_key):
    _c, schema, conn = base
    conn.execute(f"DROP TABLE {schema}.show_funcion")
    tm = Ticketmaster([_ev("A1")])

    r = _revisar(base, tm)

    assert r["estado"] == "ok" and tm.pedidos == []


def test_sin_key_el_admin_lo_dice(base, monkeypatch):
    conectar, schema, _conn = base
    monkeypatch.setattr(eventos_auto.config, "TICKETMASTER_API_KEY", "")

    assert eventos_auto.estado(conectar, schema)["ticketmaster"] is False


# ---------- en memoria, avisos y API ----------

def _fila(id_, inicio, estado="onsale", id_show="s1", tipo="teatro"):
    return {"id_funcion": id_, "id_show": id_show, "nombre": "O - Cirque du Soleil", "artista": "Cirque du Soleil",
            "tipo": tipo, "sala": "O Theatre", "direccion": "3600 S Las Vegas Blvd", "lat": Decimal("36.1126"),
            "lng": Decimal("-115.1767"), "inicio": inicio, "estado": estado, "precio_desde": Decimal("99.00"),
            "imagen_url": "https://s1.ticketm.net/a.jpg", "url": "https://www.ticketmaster.com/event/x"}


SEDES = [("Bellagio", 36.1129, -115.1765)]


def test_tarjeta_de_una_funcion():
    c = shows._card(_fila("A1", dt.datetime(2026, 12, 1, 3, tzinfo=dt.UTC), "canceled"), SEDES)

    assert (c["kind"], c["code"], c["day"], c["start"], c["end"]) == ("show", "tm-A1", "2026-11-30", "19:00", "20:30")
    assert c["cancelled"] and c["type"] == "Teatro y shows" and c["price_from"] == 99.0
    assert c["near"]["name"] == "Bellagio" and c["near"]["meters"] < 100


@pytest.fixture
def en_memoria(monkeypatch):
    filas = [_fila("A1", dt.datetime(2026, 12, 1, 3, tzinfo=dt.UTC)),
             _fila("A2", dt.datetime(2026, 12, 1, 5, 30, tzinfo=dt.UTC)),
             _fila("A3", dt.datetime(2026, 12, 2, 3, tzinfo=dt.UTC), "canceled"),
             _fila("B1", dt.datetime(2026, 12, 1, 4, tzinfo=dt.UTC), id_show="s2", tipo="musica"),
             _fila("X1", dt.datetime(2026, 12, 20, 4, tzinfo=dt.UTC), id_show="s3")]  # fuera de la semana
    funciones = {f"tm-{r['id_funcion']}": shows._card(r, SEDES) for r in filas}
    monkeypatch.setattr(shows, "_funciones", funciones)
    monkeypatch.setattr(shows.config, "TICKETMASTER_API_KEY", KEY)
    return funciones


def test_por_dia_agrupa_por_show(en_memoria):
    dias = {d["day"]: d["shows"] for d in shows.by_day()}

    assert list(dias) == ["2026-11-30", "2026-12-01"]
    o = next(s for s in dias["2026-11-30"] if s["id"] == "s1")
    assert [f["start"] for f in o["functions"]] == ["19:00", "21:30"] and o["price_from"] == 99.0
    assert dias["2026-12-01"][0]["cancelled"] is True
    assert [f["code"] for f in shows.show("s1")["functions"]] == ["tm-A1", "tm-A2", "tm-A3"]


def test_avisa_cancelado_y_postergado_de_un_show_del_itinerario():
    ahora = dt.datetime(2026, 11, 30, 10, tzinfo=eventos_avisos.sandbox.EVENT_TZ)
    base = {"kind": "show", "title": "O", "show": "s1", "day": "2026-12-01", "start": "19:00"}
    dia = [{"day": "2026-12-01", "sessions": [{**base, "code": "tm-A1", "cancelled": True},
                                              {**base, "code": "tm-A2", "postponed": True},
                                              {**base, "code": "tm-A3"}]}]

    avisos = eventos_avisos.cancelados(dia, ahora)

    assert [k for k, _ in avisos] == ["showcancel:tm-A1", "showpost:tm-A2"]
    assert avisos[0][1]["url"] == "/#/show/s1"


@pytest.fixture
def cli():
    with TestClient(app) as c:
        c.H = login_headers(c)
        yield c


def test_api_shows_y_agregar_una_funcion_al_itinerario(cli, en_memoria):
    r = cli.get("/api/shows", headers=cli.H)
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert [d["day"] for d in r.json()["days"]] == ["2026-11-30", "2026-12-01"]

    agregado = cli.post("/api/itinerary/items", headers=cli.H, json={"code": "tm-A2"})
    assert agregado.status_code == 200
    item = next(s for d in agregado.json()["days"] for s in d["sessions"] if s["code"] == "tm-A2")
    assert (item["kind"], item["locked"], item["start"]) == ("show", True, "21:30")

    ficha = cli.get("/api/shows/s1", headers=cli.H).json()
    assert [f["in_itinerary"] for f in ficha["functions"]] == [False, True, False] and ficha["in_itinerary"]
    assert cli.get("/api/shows/nada", headers=cli.H).status_code == 404
    cli.delete("/api/itinerary/items/tm-A2", headers=cli.H)


def test_api_sin_key_apagada_y_sin_login(cli, en_memoria, monkeypatch):
    monkeypatch.setattr(shows.config, "TICKETMASTER_API_KEY", "")

    assert cli.get("/api/shows", headers=cli.H).json() == {"enabled": False, "days": []}
    assert cli.get("/api/shows/s1", headers=cli.H).status_code == 404
    assert cli.get("/api/shows").status_code == 401


def test_el_sync_conserva_los_shows_de_railway():
    script = (Path(__file__).parent.parent / "scripts" / "sync_to_railway.sh").read_text(encoding="utf-8")

    guardar = script.index("CREATE TEMP TABLE guardado_show_funcion ")
    borrar = script.index('echo "DROP SCHEMA IF EXISTS reinvent CASCADE;"')
    reponer = script.index("INSERT INTO reinvent.show_funcion SELECT")
    assert guardar < borrar < reponer

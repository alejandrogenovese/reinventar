"""Eventos automáticos: fuentes (Luma, conferenceparties, links) y la revisión completa en un schema efímero, con las
fuentes y el LLM falsos (httpx.MockTransport y un resumidor que no llama a nada)."""
import datetime as dt
import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from app import eventos_auto, eventos_avisos, eventos_link
from app.eventos_fuentes import (
    TZ_VEGAS,
    Evento,
    datos_de_pagina,
    desde_conferenceparties,
    desde_item_calendario,
    desde_pagina_luma,
    horario,
    sede_por_texto,
    slug_luma,
)
from app.main import app
from scripts.actualizar_catalogo import aplicar_migraciones
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

DIA = dt.date(2026, 12, 1)
AHORA = dt.datetime(2026, 11, 14, 12, tzinfo=dt.UTC)
PAGINA_CP = "https://conferenceparties.com/reinvent2026/"


# ---------- fuentes (puras) ----------

@pytest.mark.parametrize(("texto", "inicio", "fin"), [
    ("6–9PM", (18, 0), (21, 0)),
    ("11–1PM", (11, 0), (13, 0)),           # sin AM/PM al principio: empieza a la mañana
    ("12–1:30 PM", (12, 0), (13, 30)),
    ("7:30–9:30AM", (7, 30), (9, 30)),
    ("6PM–", (18, 0), None),
    ("Evening–", (18, 0), None),
])
def test_horario_de_conferenceparties(texto, inicio, fin):
    ini, f = horario(texto, DIA)

    assert (ini.hour, ini.minute) == inicio and ini.tzinfo == TZ_VEGAS
    assert ((f.hour, f.minute) if f else None) == fin


def test_horario_que_pasa_la_medianoche_termina_al_otro_dia():
    ini, fin = horario("7PM–1AM", DIA)

    assert fin - ini == dt.timedelta(hours=6) and fin.date() == DIA + dt.timedelta(days=1)


def test_horario_ilegible_es_none():
    assert horario("", DIA) is None and horario("TBD", DIA) is None


def _fila(hora, sponsor, nombre, url, lugar):
    link = f'<a href="{url}" target="_blank">{nombre}<br><span class=\'tooltipsall\'>Request an Invite</span></a>' if url else nombre
    return (f'<tr><td class="column-1">{hora}</td><td class="column-2">{sponsor}</td><td class="column-3">{link}</td>'
            f'<td class="column-4">{lugar}</td><td class="column-5">11/1</td></tr>')


def _html_cp(*filas, dia="Tuesday - December 1, 2026"):
    encabezado = ('<tr><td class="column-1"><b>Time</b></td><td class="column-2"><b>Sponsor</b></td>'
                  '<td class="column-3"><b>Event</b></td><td class="column-4"><b>Location</b></td>'
                  '<td class="column-5"><b>Added</b></td></tr>')
    return f'<table><tr><td colspan="5" class="column-1"><h2>{dia}</h2></td></tr>{encabezado}{"".join(filas)}</table>'


FILA_ACME = _fila("6–9PM", "Acme &amp; Co", "Acme Party -", "https://acme.example/party", "Delmonico<br>The Venetian")
FILA_LUMA = _fila("7–10PM", "Beta", "Beta Night", "https://luma.com/beta123?utm_source=cp", "Register to See Address")


def test_conferenceparties_lee_la_tabla():
    eventos = {e.nombre: e for e in desde_conferenceparties(_html_cp(FILA_ACME, FILA_LUMA, FILA_ACME), PAGINA_CP)}

    acme, beta = eventos["Acme Party"], eventos["Beta Night"]
    assert len(eventos) == 2  # la fila repetida entra una vez
    assert (acme.plataforma, acme.url, acme.lugar, acme.direccion) == (
        "conferenceparties", "https://acme.example/party", "Delmonico", "The Venetian")
    assert acme.descripcion == "Sponsor: Acme & Co" and acme.id_evento.startswith("cp-")
    assert acme.inicio == dt.datetime(2026, 12, 1, 18, tzinfo=TZ_VEGAS)
    assert (beta.plataforma, beta.id_evento, beta.url, beta.lugar) == ("luma", "luma-beta123", "https://luma.com/beta123", None)


def test_conferenceparties_sin_link_usa_la_pagina_y_rechaza_links_no_https():
    html = _html_cp(_fila("5–7PM", "X", "Sin link", None, ""), _fila("5–7PM", "Y", "Raro", "javascript:alert(1)", ""))

    assert {e.url for e in desde_conferenceparties(html, PAGINA_CP)} == {PAGINA_CP}


def test_slug_luma():
    assert slug_luma("https://luma.com/AbC?utm=x") == "abc"
    assert slug_luma("https://lu.ma/abc") == "abc"
    assert slug_luma("https://luma.com/user/abc") is None
    assert slug_luma("https://acme.example/abc") is None


def _item_luma(api_id="evt-1", slug="uno", nombre="Uno", inicio="2026-12-02T02:00:00.000Z"):
    return {"event": {"api_id": api_id, "name": nombre, "start_at": inicio, "end_at": "2026-12-02T05:00:00.000Z",
                      "cover_url": f"https://images.lumacdn.com/{slug}.png", "url": slug,
                      "coordinate": {"latitude": 36.12, "longitude": -115.17}}}


def test_item_del_calendario_de_luma():
    ev = desde_item_calendario(_item_luma())

    assert (ev.id_evento, ev.url, ev.nombre, ev.lat) == ("evt-1", "https://luma.com/uno", "Uno", 36.12)
    assert ev.fin == dt.datetime(2026, 12, 2, 5, tzinfo=dt.UTC)


def _pagina_luma(item):
    data = {"event": item["event"], "description_mirror": None, "guest_count": 10, "ticket_types": []}
    nd = json.dumps({"props": {"pageProps": {"initialData": {"data": data}}}})
    return f'<script id="__NEXT_DATA__" type="application/json">{nd}</script>'


def test_evento_entero_desde_la_pagina_de_luma():
    ev = desde_pagina_luma(_pagina_luma(_item_luma("evt-9", "beta123", "Beta Night")))

    assert (ev.id_evento, ev.url, ev.anotados) == ("evt-9", "https://luma.com/beta123", 10)
    assert desde_pagina_luma("<html></html>") is None


def test_sede_por_texto_ubica_el_hotel():
    sedes = [(7, "Venetian", 36.1216, -115.1691), (3, "Wynn/Encore", 36.127, -115.165)]
    base = Evento("x", "conferenceparties", "https://x", "X", AHORA)

    assert sede_por_texto(replace(base, direccion="The Venetian"), sedes).lat == 36.1216
    assert sede_por_texto(replace(base, lugar="Encore Beach Club"), sedes).lat == 36.127
    assert sede_por_texto(replace(base, lugar="Canal Shoppes"), sedes).lat == 36.1216
    assert sede_por_texto(replace(base, lugar="Topgolf"), sedes).lat is None


def test_datos_de_una_pagina_suelta():
    html = ('<html><head><title>Fallback</title><meta property="og:title" content="Red Hat Reception &amp; Co">'
            '<meta content="Join us" name="description"><meta property="og:image" content="https://img/rh.png">'
            '<script type="application/ld+json">{"@graph": [{"@type": "WebPage"}, {"@type": "SocialEvent", '
            '"startDate": "2026-12-01T19:00"}]}</script><script>var x = 1;</script></head>'
            '<body><p>December 1 at SUSHISAMBA</p></body></html>')

    d = datos_de_pagina(html)

    assert (d["titulo"], d["descripcion"], d["imagen"]) == ("Red Hat Reception & Co", "Join us", "https://img/rh.png")
    assert d["jsonld"]["startDate"] == "2026-12-01T19:00"
    assert "SUSHISAMBA" in d["texto"] and "var x" not in d["texto"]


# ---------- links sueltos ----------

def _resolver(ips):
    return lambda _host: ips


@pytest.mark.parametrize(("url", "ips"), [
    ("http://redhat.com/x", ["23.1.1.1"]),
    ("https://user:pw@redhat.com/x", ["23.1.1.1"]),
    ("https://redhat.com:8443/x", ["23.1.1.1"]),
    ("https://interno.example/x", ["10.0.0.5"]),
    ("https://metadata.example/x", ["169.254.169.254"]),
    ("https://localhost/x", ["127.0.0.1"]),
    ("https://railway.example/x", ["fd12:3456::1"]),
])
def test_link_rechaza_lo_que_no_es_https_publico(url, ips):
    with pytest.raises(eventos_link.LinkInvalido):
        eventos_link.validar_url(url, _resolver(ips))


def test_link_valida_cada_redireccion():
    def handler(req):
        if req.headers["host"] == "publico.example":
            return httpx.Response(302, headers={"location": "https://interno.example/"})
        return httpx.Response(200, text="secreto")

    def resolver(host):
        return ["10.0.0.1"] if host == "interno.example" else ["23.1.1.1"]

    with pytest.raises(eventos_link.LinkInvalido):
        eventos_link.bajar("https://publico.example/", httpx.Client(transport=httpx.MockTransport(handler)), resolver)


def test_link_se_conecta_a_la_ip_validada_sin_volver_a_resolver():
    pedidos = []

    def handler(req):
        pedidos.append((req.url.host, req.headers["host"], req.extensions.get("sni_hostname")))
        return httpx.Response(200, text="ok")

    p = eventos_link.bajar("https://rh.example/ev", httpx.Client(transport=httpx.MockTransport(handler)),
                           _resolver(["23.1.1.1"]))

    assert pedidos == [("23.1.1.1", "rh.example", "rh.example")] and p.url == "https://rh.example/ev"


def test_link_con_alguna_ip_interna_entre_varias_se_rechaza():
    with pytest.raises(eventos_link.LinkInvalido):
        eventos_link.validar_url("https://mixto.example/", _resolver(["23.1.1.1", "10.0.0.1"]))


@pytest.mark.parametrize("url", ["https://rh.example:abc/", "https://[::1/", ""])
def test_link_mal_formado_es_link_invalido(url):
    with pytest.raises(eventos_link.LinkInvalido):
        eventos_link.validar_url(url, _resolver(["23.1.1.1"]))


def test_vista_previa_de_un_link():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<title>Red Hat</title>")))
    respuesta = json.dumps({"nombre": "Red Hat Reception", "fecha": "2026-12-01", "inicio": "19:00", "fin": "22:00",
                            "lugar": "SUSHISAMBA", "direccion": "The Venetian", "resumen_es": "Cóctel.",
                            "tipo": "inventado", "temas": ["ia"], "organizadores": ["Red Hat", "AWS"]})

    p = eventos_link.vista_previa("https://rh.example/ev", http, _resolver(["23.1.1.1"]), extraer=lambda u, d: respuesta)

    assert (p["nombre"], p["fecha"], p["inicio"], p["url"], p["tipo"]) == (
        "Red Hat Reception", "2026-12-01", "19:00", "https://rh.example/ev", None)


def test_evento_de_link_que_termina_pasada_la_medianoche():
    ev = eventos_link.evento({"url": "https://rh.example/ev", "nombre": "After", "fecha": "2026-12-01",
                              "inicio": "21:00", "fin": "01:00", "imagen": "javascript:x"})

    assert ev.fin - ev.inicio == dt.timedelta(hours=4) and ev.imagen_url is None
    assert ev.id_evento == eventos_link.id_de_link("https://rh.example/ev") and ev.plataforma == "link"


def test_evento_de_link_sin_hora_no_se_guarda():
    with pytest.raises(eventos_link.LinkInvalido):
        eventos_link.evento({"url": "https://rh.example/ev", "nombre": "X", "fecha": "2026-12-01", "inicio": None})


# ---------- revisión completa ----------

@pytest.fixture
def base():
    schema = f"ev_auto_{uuid.uuid4().hex[:8]}"
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    with conn.transaction():
        aplicar_migraciones(conn, schema)

    @contextmanager
    def conectar():
        yield conn

    yield conectar, schema, conn
    conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    conn.close()


class Fuentes:
    """Luma, conferenceparties y las páginas, falsos. Se cambian entre revisiones."""

    def __init__(self):
        self.luma = [_item_luma("evt-1", "uno", "Uno"), _item_luma("evt-2", "dos", "Dos")]
        self.cp = _html_cp(FILA_ACME, FILA_LUMA)
        self.luma_rota = False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.host == "api.lu.ma":
            if self.luma_rota:
                return httpx.Response(503)
            return httpx.Response(200, json={"entries": self.luma, "has_more": False})
        if req.url.host == "conferenceparties.com":
            return httpx.Response(200, text=self.cp)
        if req.url.host == "luma.com":
            slug = req.url.path.strip("/")
            item = next((i for i in self.luma if i["event"]["url"] == slug), None) \
                or _item_luma("evt-beta", "beta123", "Beta Night (Luma)")
            return httpx.Response(200, text=_pagina_luma(item))
        return httpx.Response(404)


class ResumidorFalso:
    def __init__(self):
        self.pedidos = []

    def __call__(self, eventos):
        self.pedidos.append(sorted(e.id_evento for e in eventos))
        return {e.id_evento: {"resumen_es": f"Resumen de {e.nombre}.", "tipo": "fiesta", "temas": [],
                              "organizadores": ["Acme"]} for e in eventos}, ()


def _revisar(base, fuentes, resumir, ahora=AHORA, tope=50):
    conectar, schema, _conn = base
    http = httpx.Client(transport=httpx.MockTransport(fuentes))
    return eventos_auto.revisar(conectar=conectar, schema=schema, http=http, resumir=resumir, tope=tope, ahora=ahora,
                                pausa=lambda: None, resolver=_resolver(["23.1.1.1"]))


def _eventos(base):
    _c, schema, conn = base
    filas = conn.execute(f"SELECT id_evento, plataforma, nombre, resumen_es, alta, falta_desde, cancelado_desde, "
                         f"lat FROM {schema}.evento").fetchall()
    campos = ("id", "plataforma", "nombre", "resumen", "alta", "falta", "cancelado", "lat")
    return {f[0]: dict(zip(campos, f, strict=True)) for f in filas}


def test_la_primera_revision_carga_todo_sin_disparar_avisos(base):
    r = _revisar(base, Fuentes(), ResumidorFalso())

    evs = _eventos(base)
    acme = next(e for e in evs.values() if e["nombre"] == "Acme Party")
    assert set(evs) == {"evt-1", "evt-2", "evt-beta", acme["id"]}  # Beta vino por conferenceparties con su id de Luma
    assert all(e["resumen"] and e["alta"] is None for e in evs.values())
    assert float(acme["lat"]) == 36.1216  # "The Venetian" → la sede
    assert r["fuentes"]["luma"]["nuevos"] == 2 and r["fuentes"]["conferenceparties"]["nuevos"] == 2


def test_lo_nuevo_despues_de_la_carga_inicial_lleva_alta_y_lo_igual_no_se_vuelve_a_resumir(base):
    fuentes, resumir = Fuentes(), ResumidorFalso()
    _revisar(base, fuentes, resumir)
    fuentes.luma.append(_item_luma("evt-3", "tres", "Tres"))

    _revisar(base, fuentes, resumir, AHORA + dt.timedelta(hours=3))

    evs = _eventos(base)
    assert evs["evt-3"]["alta"] is not None and evs["evt-1"]["alta"] is None
    assert resumir.pedidos[-1] == ["evt-3"]


def test_un_cambio_de_nombre_se_guarda_y_se_vuelve_a_resumir(base):
    fuentes, resumir = Fuentes(), ResumidorFalso()
    _revisar(base, fuentes, resumir)
    fuentes.luma[0] = _item_luma("evt-1", "uno", "Uno renombrado")

    r = _revisar(base, fuentes, resumir, AHORA + dt.timedelta(hours=3))

    assert _eventos(base)["evt-1"]["resumen"] == "Resumen de Uno renombrado."
    assert r["fuentes"]["luma"]["cambiados"] == 1


def test_un_evento_que_falta_dos_revisiones_seguidas_se_cancela_y_si_vuelve_se_descancela(base):
    fuentes, resumir = Fuentes(), ResumidorFalso()
    _revisar(base, fuentes, resumir)
    dos = fuentes.luma.pop()

    _revisar(base, fuentes, resumir, AHORA + dt.timedelta(hours=3))
    assert _eventos(base)["evt-2"]["falta"] is not None and _eventos(base)["evt-2"]["cancelado"] is None

    r = _revisar(base, fuentes, resumir, AHORA + dt.timedelta(hours=6))
    assert _eventos(base)["evt-2"]["cancelado"] is not None
    assert r["fuentes"]["luma"]["cancelados"] == 1

    fuentes.luma.append(dos)
    _revisar(base, fuentes, resumir, AHORA + dt.timedelta(hours=9))
    assert (_eventos(base)["evt-2"]["falta"], _eventos(base)["evt-2"]["cancelado"]) == (None, None)


def test_dos_revisiones_muy_seguidas_no_alcanzan_para_cancelar(base):
    fuentes, resumir = Fuentes(), ResumidorFalso()
    _revisar(base, fuentes, resumir)
    fuentes.luma.pop()

    _revisar(base, fuentes, resumir, AHORA + dt.timedelta(minutes=10))
    _revisar(base, fuentes, resumir, AHORA + dt.timedelta(minutes=20))

    assert _eventos(base)["evt-2"]["cancelado"] is None


def test_si_una_fuente_falla_no_se_cancela_nada(base):
    fuentes, resumir = Fuentes(), ResumidorFalso()
    _revisar(base, fuentes, resumir)
    fuentes.luma_rota = True

    for horas in (3, 6):
        r = _revisar(base, fuentes, resumir, AHORA + dt.timedelta(hours=horas))

    assert all(e["falta"] is None and e["cancelado"] is None for e in _eventos(base).values())
    assert r["errores"]["luma"].startswith("HTTPStatusError")


def test_si_una_fuente_trae_menos_de_la_mitad_no_se_cancela_nada(base):
    fuentes, resumir = Fuentes(), ResumidorFalso()
    fuentes.luma = [_item_luma(f"evt-{i}", f"s{i}", f"Ev {i}") for i in range(10)]
    _revisar(base, fuentes, resumir)
    fuentes.luma = fuentes.luma[:3]

    for horas in (3, 6):
        _revisar(base, fuentes, resumir, AHORA + dt.timedelta(hours=horas))

    assert all(e["cancelado"] is None for e in _eventos(base).values())


def test_una_fuente_a_la_mitad_no_se_vuelve_la_nueva_referencia(base):
    fuentes, resumir = Fuentes(), ResumidorFalso()
    fuentes.luma = [_item_luma(f"evt-{i}", f"s{i}", f"Ev {i}") for i in range(10)]
    _revisar(base, fuentes, resumir)
    fuentes.luma = fuentes.luma[:3]

    for horas in (3, 6, 9, 12):  # sigue trayendo 3: nunca pasa a ser "lo normal"
        r = _revisar(base, fuentes, resumir, AHORA + dt.timedelta(hours=horas))

    assert r["fuentes"]["luma"]["total"] == 10
    assert all(e["falta"] is None and e["cancelado"] is None for e in _eventos(base).values())


def test_un_link_que_falla_raro_no_frena_la_revision(base, monkeypatch):
    conectar, schema, _conn = base
    fuentes, resumir = Fuentes(), ResumidorFalso()
    _revisar(base, fuentes, resumir)
    eventos_auto.guardar_link({"url": "https://rh.example/ev", "nombre": "RH", "fecha": "2026-12-01", "inicio": "19:00"},
                              resumen={}, conectar=conectar, schema=schema, ahora=AHORA)
    monkeypatch.setattr(eventos_link, "bajar", lambda *a: (_ for _ in ()).throw(RuntimeError("raro")))
    fuentes.luma.append(_item_luma("evt-3", "tres", "Tres"))

    _revisar(base, fuentes, resumir, AHORA + dt.timedelta(hours=3))

    assert "evt-3" in _eventos(base)


def test_lo_que_ya_paso_no_se_cancela(base):
    fuentes, resumir = Fuentes(), ResumidorFalso()
    _revisar(base, fuentes, resumir)
    fuentes.luma.pop()
    despues_del_evento = dt.datetime(2026, 12, 3, tzinfo=dt.UTC)

    for horas in (0, 3):
        _revisar(base, fuentes, resumir, despues_del_evento + dt.timedelta(hours=horas))

    assert _eventos(base)["evt-2"]["falta"] is None


def test_el_tope_del_llm_deja_el_resto_para_la_proxima(base):
    fuentes, resumir = Fuentes(), ResumidorFalso()

    r = _revisar(base, fuentes, resumir, tope=1)
    assert sum(1 for e in _eventos(base).values() if e["resumen"]) == 1
    assert r["fuentes"]["luma"]["pendientes"] + r["fuentes"]["conferenceparties"]["pendientes"] == 3

    _revisar(base, fuentes, resumir, AHORA + dt.timedelta(hours=3), tope=50)
    assert all(e["resumen"] for e in _eventos(base).values())


def test_link_cargado_a_mano_se_guarda_con_alta_y_si_da_404_se_cancela(base):
    conectar, schema, _conn = base
    fuentes, resumir = Fuentes(), ResumidorFalso()
    _revisar(base, fuentes, resumir)
    datos = {"url": "https://rh.example/ev", "nombre": "Red Hat Reception", "fecha": "2026-12-01", "inicio": "19:00",
             "direccion": "The Venetian"}

    id_link = eventos_auto.guardar_link(datos, resumen={"resumen_es": "Cóctel."}, conectar=conectar, schema=schema,
                                        ahora=AHORA)
    with pytest.raises(eventos_auto.LinkRepetido):
        eventos_auto.guardar_link(datos, resumen={}, conectar=conectar, schema=schema)

    assert _eventos(base)[id_link]["alta"] is not None and float(_eventos(base)[id_link]["lat"]) == 36.1216
    for horas in (3, 6):  # rh.example responde 404 en las Fuentes falsas
        _revisar(base, fuentes, resumir, AHORA + dt.timedelta(hours=horas))
    assert _eventos(base)[id_link]["cancelado"] is not None


def test_estado_para_el_admin(base):
    conectar, schema, _conn = base
    _revisar(base, Fuentes(), ResumidorFalso())

    e = eventos_auto.estado(conectar, schema)

    assert {r["fuente"] for r in e["revisiones"]} == {"luma", "conferenceparties", "links"}
    assert e["migracion_pendiente"] is False and e["links"] == []


def test_apagado_sin_la_variable(monkeypatch):
    arrancados = []
    monkeypatch.setattr(eventos_auto.config, "EVENTOS_AUTO", False)
    monkeypatch.setattr(eventos_auto.threading, "Thread", lambda **kw: arrancados.append(kw))

    eventos_auto.start_worker()

    assert arrancados == []


def test_una_revision_a_la_vez(monkeypatch):
    llamadas = []
    monkeypatch.setattr(eventos_auto, "revisar", lambda **kw: llamadas.append(kw) or {"estado": "ok"})
    monkeypatch.setattr(eventos_auto.events, "load", lambda: 0)

    with eventos_auto._en_curso:
        assert eventos_auto.revisar_ahora() == {"estado": "ocupado"}
    assert eventos_auto.revisar_ahora() == {"estado": "ok"} and len(llamadas) == 1


# ---------- push ----------

def _ahora_vegas(hora):
    return dt.datetime(2026, 11, 30, hora, tzinfo=TZ_VEGAS)


def _dia_con(**evento):
    card = {"kind": "event", "code": "evt-x", "title": "Fiesta X", "day": "2026-12-01", "start": "19:00", **evento}
    return [{"day": card["day"], "sessions": [card]}]


def test_texto_del_aviso_de_eventos_nuevos():
    assert eventos_avisos.texto_nuevos(["A"]) == ("1 evento nuevo", "A")
    assert eventos_avisos.texto_nuevos(["A", "B"]) == ("2 eventos nuevos", "A y B")
    assert eventos_avisos.texto_nuevos(["A", "B", "C", "D"]) == ("4 eventos nuevos", "A, B y 2 más")


def test_avisa_el_cancelado_de_su_itinerario_solo_si_no_empezo():
    assert [k for k, _ in eventos_avisos.cancelados(_dia_con(cancelled=True), _ahora_vegas(10))] == ["evcancel:evt-x"]
    assert eventos_avisos.cancelados(_dia_con(cancelled=False), _ahora_vegas(10)) == []
    assert eventos_avisos.cancelados(_dia_con(cancelled=True, day="2026-11-30", start="09:00"), _ahora_vegas(10)) == []


def test_eventos_nuevos_desde_el_ultimo_aviso(monkeypatch):
    monkeypatch.setattr(eventos_avisos.events, "_events", {
        "a": {"title": "Viejo", "added": 100.0, "cancelled": False},
        "b": {"title": "Nuevo", "added": 200.0, "cancelled": False},
        "c": {"title": "Cancelado", "added": 300.0, "cancelled": True},
        "d": {"title": "De la carga inicial", "added": None, "cancelled": False}})

    clave, msg = eventos_avisos.nuevos(ultimo=150.0, ahora=1000.0)

    assert (clave, msg["title"], msg["body"], msg["url"]) == ("evnuevos:200", "1 evento nuevo", "Nuevo", "/#/eventos")
    assert eventos_avisos.nuevos(ultimo=250.0, ahora=1000.0) is None


def test_de_noche_no_sale_ningun_aviso_de_eventos(monkeypatch):
    monkeypatch.setattr(eventos_avisos, "nuevos", lambda *_: ("evnuevos:1", {"title": "x"}))

    assert eventos_avisos.avisos(_dia_con(cancelled=True), _ahora_vegas(23), quiere_nuevos=True, ultimo_nuevos=None) == []
    de_dia = eventos_avisos.avisos(_dia_con(cancelled=True), _ahora_vegas(10), quiere_nuevos=False, ultimo_nuevos=None)
    assert [k for k, _ in de_dia] == ["evcancel:evt-x"]  # apagó los nuevos: el cancelado de lo suyo llega igual


# ---------- admin ----------

@pytest.fixture
def admin_cli():
    with TestClient(app) as c:
        c.H = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        yield c


def test_solo_admin_y_apagado_responde_409(admin_cli, monkeypatch):
    monkeypatch.setattr(eventos_auto.config, "EVENTOS_AUTO", False)

    assert admin_cli.post("/api/admin/eventos/revisar", headers=admin_cli.H).status_code == 409
    assert admin_cli.post("/api/admin/eventos/link/vista-previa", headers=admin_cli.H,
                          json={"url": "https://rh.example/ev"}).status_code == 409
    with TestClient(app) as c:
        assert c.get("/api/admin/eventos", headers=login_headers(c)).status_code == 403


def test_guardar_link_valida_los_datos(admin_cli, monkeypatch):
    monkeypatch.setattr(eventos_auto.config, "EVENTOS_AUTO", True)
    malo = {"url": "http://rh.example/ev", "nombre": "X", "fecha": "2026-12-01", "inicio": "25:00"}

    assert admin_cli.post("/api/admin/eventos/link", headers=admin_cli.H, json=malo).status_code == 422
    assert admin_cli.post("/api/admin/eventos/link", headers=admin_cli.H,
                          json={**malo, "url": "https://rh.example/ev", "inicio": "19:00", "extra": 1}).status_code == 422


# ---------- sync ----------

def test_el_sync_conserva_los_eventos_de_railway():
    script = (Path(__file__).parent.parent / "scripts" / "sync_to_railway.sh").read_text(encoding="utf-8")

    guardar = script.index("CREATE TEMP TABLE guardado_evento ")
    borrar = script.index('echo "DROP SCHEMA IF EXISTS reinvent CASCADE;"')
    reponer = script.index("INSERT INTO reinvent.evento\n      SELECT (jsonb_populate_record")
    assert guardar < borrar < reponer
    assert 'REEMPLAZAR_EVENTOS" != "1"' in script
    assert "no tiene la migración 007" in script  # no reponer perdiendo los cancelados
    assert '"id_sede_cercana": null' in script     # una sede que ya no existe no rompe la FK

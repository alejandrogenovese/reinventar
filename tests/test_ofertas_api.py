"""Ofertas con base: la carga manual (solo admin), las preferencias, el envío (dedupe, tope diario, silencio) y el job
de precios de shows dentro del hilo de avisos. Sin catálogo ni push reales."""
import datetime as dt
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import config, db, ofertas, ofertas_avisos, push, sandbox
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

AHORA = dt.datetime(2026, 12, 1, 10, 0, tzinfo=sandbox.EVENT_TZ)
SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/ofe", "keys": {"p256dh": "x" * 87, "auth": "y" * 22}}


def _limpiar():
    with sandbox.real(), db.conn() as c:
        c.execute("DELETE FROM oferta")
        c.execute("DELETE FROM precio_snapshot")
        c.execute("DELETE FROM oferta_job")
        c.execute("DELETE FROM push_sent WHERE username=%s", (TEST_USER,))
        c.execute("DELETE FROM preferencias_avisos WHERE username=%s", (TEST_USER,))


@pytest.fixture
def cli(monkeypatch):
    pub, priv = push.generate_vapid_keys()
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", pub)
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", priv)
    with TestClient(app) as c:
        c.H = login_headers(c)
        c.HA = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        _limpiar()
        yield c
        _limpiar()
        c.post("/api/push/unsubscribe", headers=c.H, json={"endpoint": SUB["endpoint"]})


def _manual(**cambios):
    base = {"titulo": "2x1 en tragos", "categoria": "comida", "lugar": "Bar del lobby, Venetian",
            "desde": "2026-12-01T09:00:00", "hasta": "2026-12-01T18:00:00", "link": "https://ejemplo.com/oferta",
            "nota": "Con la credencial"}
    return {**base, **cambios}


def _prender(categorias=None):
    ofertas.guardar_preferencias(TEST_USER, True, categorias or list(ofertas.CATEGORIAS))


class Buzon:
    """El `notificar` que se le inyecta a ofertas_avisos.enviar: guarda lo que se mandaría al celular."""
    def __init__(self, llega=True):
        self.mensajes, self.llega = [], llega

    def __call__(self, username, mensaje):
        self.mensajes.append(mensaje)
        return int(self.llega)


# ---------- carga manual: solo admin ----------

def test_cargar_una_oferta_exige_ser_admin(cli):
    assert cli.post("/api/ofertas/admin", headers=cli.H, json=_manual()).status_code == 403
    assert cli.get("/api/ofertas/admin/lista", headers=cli.H).status_code == 403
    assert cli.delete("/api/ofertas/admin/m-x", headers=cli.H).status_code == 403
    assert cli.post("/api/ofertas/admin", json=_manual()).status_code in (401, 403)


def test_el_admin_carga_y_la_oferta_aparece_vigente(cli, monkeypatch):
    monkeypatch.setattr(ofertas.sandbox, "ahora", lambda tz=None: AHORA)

    r = cli.post("/api/ofertas/admin", headers=cli.HA, json=_manual())

    assert r.status_code == 201, r.text
    lista = cli.get("/api/ofertas", headers=cli.H).json()
    assert [o["titulo"] for o in lista["ofertas"]] == ["2x1 en tragos"]
    assert lista["es_admin"] is False
    assert cli.get(f"/api/ofertas/{r.json()['id']}", headers=cli.H).json()["lugar"] == "Bar del lobby, Venetian"


def test_las_ofertas_se_filtran_por_categoria(cli, monkeypatch):
    monkeypatch.setattr(ofertas.sandbox, "ahora", lambda tz=None: AHORA)
    cli.post("/api/ofertas/admin", headers=cli.HA, json=_manual())
    cli.post("/api/ofertas/admin", headers=cli.HA, json=_manual(titulo="Outlet 25 %", categoria="compras"))

    solo = cli.get("/api/ofertas?categoria=compras", headers=cli.H).json()["ofertas"]

    assert [o["titulo"] for o in solo] == ["Outlet 25 %"]
    assert cli.get("/api/ofertas?categoria=inventada", headers=cli.H).status_code == 422


def test_una_oferta_vencida_no_sale_en_la_lista_pero_el_admin_la_ve(cli, monkeypatch):
    monkeypatch.setattr(ofertas.sandbox, "ahora", lambda tz=None: AHORA)
    cli.post("/api/ofertas/admin", headers=cli.HA, json=_manual(desde="2026-11-30T09:00:00", hasta="2026-11-30T18:00:00"))

    assert cli.get("/api/ofertas", headers=cli.H).json()["ofertas"] == []
    assert len(cli.get("/api/ofertas/admin/lista", headers=cli.HA).json()["ofertas"]) == 1


def test_el_admin_la_da_de_baja(cli, monkeypatch):
    monkeypatch.setattr(ofertas.sandbox, "ahora", lambda tz=None: AHORA)
    oid = cli.post("/api/ofertas/admin", headers=cli.HA, json=_manual()).json()["id"]

    assert cli.delete(f"/api/ofertas/admin/{oid}", headers=cli.HA).status_code == 200
    assert cli.get(f"/api/ofertas/{oid}", headers=cli.H).status_code == 404


@pytest.mark.parametrize("cambios", [
    {"categoria": "inventada"}, {"titulo": "x"}, {"link": "http://inseguro.com"}, {"link": "javascript:alert(1)"},
    {"hasta": "2026-12-01T08:00:00"}, {"desde": "no es una fecha"}])
def test_la_carga_valida_lo_que_llega(cli, cambios):
    assert cli.post("/api/ofertas/admin", headers=cli.HA, json=_manual(**cambios)).status_code == 422


# ---------- preferencias ----------

def test_las_alertas_vienen_apagadas_y_con_todas_las_categorias(cli):
    p = cli.get("/api/ofertas/preferencias", headers=cli.H).json()

    assert p["activas"] is False
    assert set(p["categorias"]) == {"shows", "comida", "compras", "otros"}


def test_se_guardan_las_preferencias_sin_pisar_las_de_los_otros_avisos(cli):
    cli.put("/api/push/preferencias", headers=cli.H, json={"grabar": False, "ubicacion": False, "eventos_nuevos": False})

    r = cli.put("/api/ofertas/preferencias", headers=cli.H, json={"activas": True, "categorias": ["shows"]})
    cli.put("/api/push/preferencias", headers=cli.H, json={"grabar": False, "ubicacion": False, "eventos_nuevos": False})

    assert r.json() == {"activas": True, "categorias": ["shows"]}
    assert cli.get("/api/ofertas/preferencias", headers=cli.H).json()["activas"] is True
    assert cli.get("/api/push/preferencias", headers=cli.H).json() == {"grabar": False, "ubicacion": False, "eventos_nuevos": False}


def test_categorias_invalidas_se_rechazan(cli):
    assert cli.put("/api/ofertas/preferencias", headers=cli.H, json={"activas": True, "categorias": ["x"]}).status_code == 422


# ---------- envío ----------

def _cargar(cli, **cambios):
    r = cli.post("/api/ofertas/admin", headers=cli.HA, json=_manual(**cambios))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_una_oferta_vigente_se_avisa_una_sola_vez(cli):
    _prender()
    oid = _cargar(cli)
    buzon = Buzon()

    assert ofertas_avisos.enviar(TEST_USER, AHORA, buzon) == 1
    assert ofertas_avisos.enviar(TEST_USER, AHORA, buzon) == 0

    assert [m["url"] for m in buzon.mensajes] == [f"/#/ofertas/{oid}"]


def test_con_las_alertas_apagadas_no_sale_nada(cli):
    _cargar(cli)
    buzon = Buzon()

    assert ofertas_avisos.enviar(TEST_USER, AHORA, buzon) == 0
    assert buzon.mensajes == []


def test_una_categoria_no_suscripta_no_recibe(cli):
    _prender(["shows"])
    _cargar(cli, categoria="comida")
    buzon = Buzon()

    assert ofertas_avisos.enviar(TEST_USER, AHORA, buzon) == 0


def test_de_noche_no_se_avisa_y_a_la_manana_si(cli):
    _prender()
    _cargar(cli, desde="2026-12-01T21:00:00", hasta="2026-12-02T20:00:00")
    buzon = Buzon()

    assert ofertas_avisos.enviar(TEST_USER, AHORA.replace(hour=23), buzon) == 0
    assert ofertas_avisos.enviar(TEST_USER, AHORA.replace(hour=22, minute=30) + dt.timedelta(hours=8, minutes=30), buzon) == 1


def test_el_tope_diario_agrupa_lo_que_sobra(cli, monkeypatch):
    monkeypatch.setattr(config, "OFERTAS_MAX_POR_DIA", 2)
    _prender()
    for i in range(3):
        _cargar(cli, titulo=f"Oferta número {i}")
    buzon = Buzon()

    assert ofertas_avisos.enviar(TEST_USER, AHORA, buzon) == 1

    assert [(m["title"], m["url"]) for m in buzon.mensajes] == [("3 ofertas nuevas", "/#/ofertas")]
    assert ofertas_avisos.enviar(TEST_USER, AHORA, buzon) == 0   # ya salieron las tres: no se repiten


def test_pasado_el_tope_del_dia_lo_nuevo_espera_a_manana(cli, monkeypatch):
    monkeypatch.setattr(config, "OFERTAS_MAX_POR_DIA", 1)
    _prender()
    _cargar(cli, titulo="Primera oferta")
    buzon = Buzon()
    assert ofertas_avisos.enviar(TEST_USER, AHORA, buzon) == 1
    _cargar(cli, titulo="Segunda oferta")

    assert ofertas_avisos.enviar(TEST_USER, AHORA + dt.timedelta(hours=1), buzon) == 0
    assert len(buzon.mensajes) == 1


def test_si_el_push_no_llega_a_ningun_dispositivo_se_reintenta(cli):
    _prender()
    _cargar(cli)

    assert ofertas_avisos.enviar(TEST_USER, AHORA, Buzon(llega=False)) == 0
    assert ofertas_avisos.enviar(TEST_USER, AHORA, Buzon()) == 1


def test_el_envio_forma_parte_del_hilo_de_avisos(cli, monkeypatch):
    enviados = []
    monkeypatch.setattr(push, "send", lambda sub, msg, http=None, ttl=push.TTL_SECONDS: enviados.append(msg) or 201)
    monkeypatch.setattr(push, "due", lambda username, now: [])
    monkeypatch.setattr(push.sandbox, "ahora", lambda tz=None: AHORA)
    cli.post("/api/push/subscribe", headers=cli.H, json=SUB)
    _prender()
    oid = _cargar(cli)

    push.tick()
    push.tick()

    assert [m["url"] for m in enviados] == [f"/#/ofertas/{oid}"]


# ---------- job de precios de shows ----------

class FuncionesFalsas:
    def __init__(self, precio):
        self.precio = precio

    def __call__(self):
        return [{"id_funcion": "F1", "id_show": "S1", "nombre": "Absinthe", "sala": "Caesars Palace", "url": "https://tm.example/f1",
                 "estado": "onsale", "inicio": AHORA + dt.timedelta(days=1), "precio_desde": self.precio}]


def _correr(precio, ahora):
    return ofertas.correr_si_toca(ahora, [ofertas.FuenteTicketmaster(FuncionesFalsas(precio))])


def test_el_job_guarda_snapshots_y_detecta_la_baja(cli):
    assert _correr(Decimal("89"), AHORA) == 0
    assert _correr(Decimal("62"), AHORA + dt.timedelta(hours=6)) == 1

    [o] = ofertas.vigentes(AHORA + dt.timedelta(hours=6))
    assert (o.categoria, o.precio_antes, o.precio_ahora) == ("shows", Decimal("89"), Decimal("62"))


def test_el_job_no_corre_antes_de_las_6_horas(cli):
    _correr(Decimal("89"), AHORA)

    assert _correr(Decimal("40"), AHORA + dt.timedelta(hours=5)) == 0
    assert ofertas.vigentes(AHORA + dt.timedelta(hours=5)) == []


def test_la_misma_baja_no_se_guarda_dos_veces(cli):
    _correr(Decimal("89"), AHORA)
    _correr(Decimal("62"), AHORA + dt.timedelta(hours=6))

    assert _correr(Decimal("62"), AHORA + dt.timedelta(hours=12)) == 0
    assert len(ofertas.vigentes(AHORA + dt.timedelta(hours=12))) == 1


def test_sin_precio_en_ticketmaster_el_job_no_inventa_ofertas(cli):
    assert _correr(None, AHORA) == 0
    assert _correr(None, AHORA + dt.timedelta(hours=6)) == 0
    assert ofertas.vigentes(AHORA + dt.timedelta(hours=6)) == []

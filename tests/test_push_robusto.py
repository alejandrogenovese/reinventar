"""Los avisos push no se caen ni se pierden: un usuario o un job que explota no frena al resto, y un push que no llega
no se da por avisado. Sin red ni catálogo."""
import datetime as dt
import logging

import pytest
from fastapi.testclient import TestClient

from app import config, db, ofertas, ofertas_avisos, push, sandbox, vuelos
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_USER, login_headers

BUE = "America/Argentina/Buenos_Aires"
LV = sandbox.EVENT_TZ
AHORA = dt.datetime(2026, 12, 1, 10, 0, tzinfo=LV)
SALIDA = dt.datetime(2026, 11, 29, 0, 5, tzinfo=dt.UTC).timestamp()   # 21:05 de Buenos Aires del 28/11


def _ahora(texto):
    return dt.datetime.fromisoformat(texto).replace(tzinfo=LV)


def _limpiar():
    with sandbox.real(), db.conn() as c:
        for t in ("viajes_vuelos", "viajes_hoteles", "push_sent"):
            c.execute(f"DELETE FROM {t} WHERE username IN (%s,%s)", (TEST_USER, TEST_ADMIN))
        c.execute("DELETE FROM preferencias_avisos WHERE username IN (%s,%s)", (TEST_USER, TEST_ADMIN))
        c.execute("DELETE FROM oferta")
        c.execute("DELETE FROM precio_snapshot")
        c.execute("DELETE FROM oferta_job")


@pytest.fixture
def cli(monkeypatch):
    pub, priv = push.generate_vapid_keys()
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", pub)
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", priv)
    monkeypatch.setattr(push.itinerary, "get_current", lambda u: {"days": []})
    monkeypatch.setattr(push.changes, "pending", lambda u: [])
    monkeypatch.setattr(db, "push_usernames", lambda: [TEST_USER, TEST_ADMIN])
    monkeypatch.setattr(ofertas, "correr_si_toca", lambda ahora, fuentes=None: 0)
    monkeypatch.setattr(push, "start_worker", lambda: None)   # el hilo real de avisos competiría con el tick() del test
    with TestClient(app) as c:
        c.H = login_headers(c)
        _limpiar()
        yield c
        _limpiar()


# ---------- tick: lo que falla no frena a los demás ----------

def test_un_usuario_con_datos_raros_no_frena_los_avisos_de_los_demas(cli, monkeypatch):
    enviados = []
    monkeypatch.setattr(sandbox, "ahora", lambda tz=LV: _ahora("2026-12-01T10:00"))
    monkeypatch.setattr(push, "notify", lambda u, m: enviados.append(u) or 1)

    def due(username, now):
        if username == TEST_USER:
            raise TypeError("can't subtract offset-naive and offset-aware datetimes")
        return [("k:1", {"title": "Hola", "body": "", "url": "/"})]

    monkeypatch.setattr(push, "due", due)

    assert push.tick() == 1
    assert enviados == [TEST_ADMIN]


def test_el_error_de_un_usuario_queda_en_el_log(cli, monkeypatch, caplog):
    monkeypatch.setattr(push, "due", lambda u, n: (_ for _ in ()).throw(KeyError("x")))

    with caplog.at_level(logging.ERROR, logger="reinventar.push"):
        push.tick()

    assert TEST_USER in caplog.text and "KeyError" in caplog.text


def test_si_el_job_de_ofertas_explota_igual_salen_los_avisos(cli, monkeypatch):
    enviados = []
    monkeypatch.setattr(sandbox, "ahora", lambda tz=LV: _ahora("2026-12-01T10:00"))
    monkeypatch.setattr(ofertas, "correr_si_toca", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("tm caído")))
    monkeypatch.setattr(push, "due", lambda u, n: [("k:2", {"title": "Hola", "body": "", "url": "/"})])
    monkeypatch.setattr(push, "notify", lambda u, m: enviados.append(u) or 1)

    assert push.tick() == 2


def test_un_notify_que_tira_excepcion_no_deja_el_aviso_como_enviado(cli, monkeypatch):
    llamadas = []

    def notify(u, m):
        llamadas.append(u)
        if len(llamadas) == 1:
            raise TimeoutError("push service")
        return 1

    monkeypatch.setattr(sandbox, "ahora", lambda tz=LV: _ahora("2026-12-01T10:00"))
    monkeypatch.setattr(push, "due", lambda u, n: [("k:3", {"title": "Hola", "body": "", "url": "/"})] if u == TEST_USER else [])
    monkeypatch.setattr(push, "notify", notify)

    assert push.tick() == 0
    assert push.tick() == 1   # se reintenta: no quedó marcado


# ---------- ofertas: el job ----------

class _Fuente:
    nombre = "falsa"

    def __init__(self, falla=True):
        self.falla, self.corridas = falla, 0

    def ofertas(self, ahora):
        self.corridas += 1
        if self.falla:
            raise RuntimeError("fuente caída")
        return []


def test_si_la_fuente_falla_se_reintenta_a_los_20_min_no_cada_vuelta(cli, monkeypatch):
    purgas = []
    monkeypatch.setattr(ofertas, "_purgar", lambda ts: purgas.append(ts))
    monkeypatch.undo()   # vuelve el correr_si_toca real (el fixture lo había reemplazado)
    f = _Fuente()

    ofertas.correr_si_toca(AHORA, [f])
    ofertas.correr_si_toca(AHORA + dt.timedelta(minutes=1), [f])
    ofertas.correr_si_toca(AHORA + dt.timedelta(minutes=10), [f])
    assert f.corridas == 1

    ofertas.correr_si_toca(AHORA + dt.timedelta(minutes=21), [f])
    assert f.corridas == 2


def test_la_purga_corre_solo_cuando_alguna_fuente_corre(cli, monkeypatch):
    monkeypatch.undo()
    purgas = []
    monkeypatch.setattr(ofertas, "_purgar", lambda ts: purgas.append(ts))
    f = _Fuente(falla=False)

    ofertas.correr_si_toca(AHORA, [f])
    ofertas.correr_si_toca(AHORA + dt.timedelta(minutes=1), [f])
    ofertas.correr_si_toca(AHORA + dt.timedelta(minutes=2), [f])

    assert len(purgas) == 1


def test_sin_key_de_ticketmaster_se_avisa_en_el_log(monkeypatch, caplog):
    monkeypatch.setattr(config, "TICKETMASTER_API_KEY", "")

    with caplog.at_level(logging.WARNING, logger="reinventar.ofertas"):
        assert ofertas.funciones_de_ticketmaster() == []

    assert "TICKETMASTER_API_KEY" in caplog.text


# ---------- ofertas: el envío ----------

def test_si_el_envio_de_una_oferta_tira_excepcion_se_desmarca_y_no_cuenta_para_el_tope(cli):
    ofertas.guardar_preferencias(TEST_USER, True, list(ofertas.CATEGORIAS))
    ofertas.crear_manual({"categoria": "comida", "titulo": "2x1", "desde": AHORA - dt.timedelta(hours=1)}, AHORA)

    def explota(u, m):
        raise TimeoutError("push service")

    with pytest.raises(TimeoutError):
        ofertas_avisos.enviar(TEST_USER, AHORA, explota)

    assert ofertas_avisos._push_de_hoy(TEST_USER, AHORA) == 0
    assert ofertas_avisos.enviar(TEST_USER, AHORA, lambda u, m: 1) == 1


# ---------- vuelos: el estado se guarda solo si el aviso llegó ----------

class Estado:
    """El `consultar` falso de AeroDataBox: devuelve lo que se le ponga en `ahora`."""
    def __init__(self, demora=0, puerta=None):
        self.demora, self.puerta, self.llamadas = demora, puerta, 0

    def __call__(self, numero, fecha, http=None, usuario=None):
        self.llamadas += 1
        return {"salida_utc": SALIDA, "demora_min": self.demora, "puerta": self.puerta, "terminal": None,
                "estado": "Expected"}


@pytest.fixture
def vuelo(cli, monkeypatch):
    monkeypatch.setattr(config, "AERODATABOX_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(db, "push_usernames", lambda: [TEST_USER])
    monkeypatch.setattr(sandbox, "ahora", lambda tz=LV: _ahora("2026-11-28T08:00"))
    api = Estado()
    monkeypatch.setattr(vuelos, "consultar", api)
    v = vuelos.agregar_vuelo(TEST_USER, "AR1302", "", "2026-11-28", "21:05", BUE)
    # el check-in ya avisado: estos tests miran solo el estado
    db.mark_push_sent(TEST_USER, f"vcheckin:{v['id']}")
    return v, api


def _recien_consultado(id_):
    vuelos.guardar_estado(TEST_USER, id_, {"consultado_en": 0})   # pasaron los 20 min entre consultas


def _titulos(monkeypatch, llega):
    enviados = []
    monkeypatch.setattr(push, "notify", lambda u, m: enviados.append(m["title"]) or int(llega()))
    return enviados


def test_si_el_push_de_la_demora_no_llega_se_reintenta_y_no_se_pierde(vuelo, monkeypatch):
    v, api = vuelo
    api.demora = 45
    llega = [False]
    enviados = _titulos(monkeypatch, lambda: llega[0])

    assert push.tick() == 0
    assert vuelos.get_vuelo(TEST_USER, v["id"])["demora_min"] is None   # no se guardó: la diferencia sigue a la vista

    llega[0] = True
    assert push.tick() == 1   # sin esperar 20 min
    assert enviados == ["AR1302 sale 45 min más tarde", "AR1302 sale 45 min más tarde"]
    assert vuelos.get_vuelo(TEST_USER, v["id"])["demora_min"] == 45


def test_una_demora_que_vuelve_a_un_valor_anterior_se_vuelve_a_avisar(vuelo, monkeypatch):
    v, api = vuelo
    enviados = _titulos(monkeypatch, lambda: True)

    for demora in (30, 0, 30):
        api.demora = demora
        _recien_consultado(v["id"])
        assert push.tick() == 1

    assert enviados == ["AR1302 sale 30 min más tarde", "AR1302 ya no tiene demora", "AR1302 sale 30 min más tarde"]


def test_una_puerta_que_vuelve_a_la_anterior_se_vuelve_a_avisar(vuelo, monkeypatch):
    v, api = vuelo
    enviados = _titulos(monkeypatch, lambda: True)

    for puerta in ("A1", "B2", "A1"):
        api.puerta = puerta
        _recien_consultado(v["id"])
        assert push.tick() == 1

    assert len(enviados) == 3 and enviados[2].endswith("ahora A1")


def test_el_mismo_cambio_no_se_avisa_dos_veces_si_llego(vuelo, monkeypatch):
    v, api = vuelo
    api.demora = 45
    enviados = _titulos(monkeypatch, lambda: True)

    assert push.tick() == 1
    _recien_consultado(v["id"])
    assert push.tick() == 0
    assert len(enviados) == 1


def test_la_cancelacion_no_se_pierde_si_el_push_no_llega(vuelo, monkeypatch):
    v, api = vuelo
    llega = [False]
    _titulos(monkeypatch, lambda: llega[0])
    monkeypatch.setattr(vuelos, "consultar", lambda *a, **k: {**Estado()(*a, **k), "estado": "Canceled"})

    assert push.tick() == 0
    llega[0] = True
    assert push.tick() == 1
    assert (vuelos.get_vuelo(TEST_USER, v["id"])["estado"] or "").lower().startswith("cancel")

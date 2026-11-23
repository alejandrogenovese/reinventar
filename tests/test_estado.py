"""Banner de estado: reglas puras (app/estado.py), contador de fallas del LLM y GET /api/estado (sesión y caché)."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import __version__, db, estado, estado_api, llm, sandbox
from app.llm_router import Tarea
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

AHORA = dt.datetime(2026, 12, 1, 18, 0, tzinfo=dt.UTC).timestamp()
MIN = 60
HORA = 3600


def _revision(fuente: str, horas_atras: float, ok: bool = True) -> dict:
    return {"fuente": fuente, "ok": ok, "revisado": dt.datetime.fromtimestamp(AHORA - horas_atras * HORA, dt.UTC)}


def _eventos(*revisiones, activo=True, horas=6) -> dict:
    return {"activo": activo, "horas": horas, "revisiones": list(revisiones)}


@pytest.fixture(autouse=True)
def _limpio():
    estado.reiniciar_fallas_llm()
    estado_api.reiniciar_cache()
    yield
    estado.reiniciar_fallas_llm()
    estado_api.reiniciar_cache()


# --- reglas puras ------------------------------------------------------------------------------------------------------

def test_sin_problemas_no_hay_avisos():
    senales = estado.Senales(ahora=AHORA, procesando=(AHORA - 5 * MIN,), errores_ultima_hora=2,
                             fallas_llm=(AHORA - MIN, AHORA - 2 * MIN),
                             eventos=_eventos(_revision("luma", 2), _revision("catalogo", 1)))

    assert estado.servicio(senales) == []


def test_grabacion_procesando_hace_30_min_es_transcripcion_demorada():
    senales = estado.Senales(ahora=AHORA, procesando=(AHORA - 30 * MIN, AHORA - 2 * MIN))

    assert estado.servicio(senales) == [{"id": "transcripcion", "nivel": "demorado",
                                         "desde": "2026-12-01T17:30:00+00:00", "detalle_horas": None}]


def test_tres_errores_en_la_ultima_hora_es_transcripcion_caida():
    senales = estado.Senales(ahora=AHORA, procesando=(AHORA - 30 * MIN,), errores_ultima_hora=3)

    assert estado.servicio(senales) == [{"id": "transcripcion", "nivel": "caido", "desde": None, "detalle_horas": None}]


def test_pipeline_parado_es_transcripcion_caida():
    assert estado.transcripcion(estado.Senales(ahora=AHORA, pipeline_vivo=False))["nivel"] == "caido"


def test_senal_que_no_se_pudo_leer_no_avisa():
    senales = estado.Senales(ahora=AHORA, pipeline_vivo=None, procesando=None, errores_ultima_hora=None)

    assert estado.servicio(senales) == []


def test_tres_fallas_del_llm_en_15_min_son_resumenes_caidos():
    fallas = (AHORA - 20 * MIN, AHORA - 10 * MIN, AHORA - 5 * MIN, AHORA - MIN)

    aviso = estado.resumenes(estado.Senales(ahora=AHORA, fallas_llm=fallas))

    assert aviso == {"id": "resumenes", "nivel": "caido", "desde": "2026-12-01T17:50:00+00:00", "detalle_horas": None}


def test_dos_fallas_del_llm_no_alcanzan():
    assert estado.resumenes(estado.Senales(ahora=AHORA, fallas_llm=(AHORA - MIN, AHORA - 2 * MIN))) is None


def test_fuente_de_eventos_atrasada_avisa_con_las_horas_desde_la_ultima_revision():
    # Intervalo de 6 h: atrasada pasadas las 18 h sin revisarse. Toma la más vieja de las atrasadas.
    senales = estado.Senales(ahora=AHORA, eventos=_eventos(_revision("luma", 20.5), _revision("conferenceparties", 25),
                                                           _revision("ticketmaster", 3)))

    assert estado.servicio(senales) == [{"id": "eventos", "nivel": "atrasado", "desde": "2026-11-30T17:00:00+00:00",
                                         "detalle_horas": 25}]


def test_catalogo_atrasado_usa_su_propio_intervalo_de_3_h():
    al_dia = estado.Senales(ahora=AHORA, eventos=_eventos(_revision("catalogo", 8)))
    atrasado = estado.Senales(ahora=AHORA, eventos=_eventos(_revision("catalogo", 10)))

    assert estado.fuentes(al_dia) == []
    assert estado.fuentes(atrasado) == [{"id": "catalogo", "nivel": "atrasado", "desde": "2026-12-01T08:00:00+00:00",
                                         "detalle_horas": 10}]


def test_fuente_que_fallo_o_revision_apagada_no_es_atraso():
    fallida = estado.Senales(ahora=AHORA, eventos=_eventos(_revision("luma", 40, ok=False)))
    apagada = estado.Senales(ahora=AHORA, eventos=_eventos(_revision("luma", 40), activo=False))
    sin_fecha = estado.Senales(ahora=AHORA, eventos=_eventos({"fuente": "luma", "ok": True, "revisado": None}))

    assert estado.fuentes(fallida) == estado.fuentes(apagada) == estado.fuentes(sin_fecha) == []


def test_los_caidos_van_primero():
    senales = estado.Senales(ahora=AHORA, procesando=(AHORA - HORA,), fallas_llm=(AHORA - 1, AHORA - 2, AHORA - 3),
                             eventos=_eventos(_revision("luma", 30)))

    assert [(a["id"], a["nivel"]) for a in estado.servicio(senales)] == [
        ("resumenes", "caido"), ("transcripcion", "demorado"), ("eventos", "atrasado")]


# --- contador de fallas del LLM -------------------------------------------------------------------------------------

def test_el_contador_separa_real_y_prueba_y_olvida_lo_viejo():
    estado.registrar_falla_llm("real", ahora=AHORA - 20 * MIN)
    estado.registrar_falla_llm("real", ahora=AHORA - MIN)
    estado.registrar_falla_llm("prueba", ahora=AHORA - MIN)

    assert estado.fallas_llm("real", ahora=AHORA) == (AHORA - MIN,)
    assert estado.fallas_llm("prueba", ahora=AHORA) == (AHORA - MIN,)


def test_llm_complete_registra_la_falla_y_la_relanza(monkeypatch):
    def falla(*_args, **_kwargs):
        raise RuntimeError("LLM 500: detalle interno")

    monkeypatch.setattr(sandbox, "proveedor_llm", lambda: "openai")
    monkeypatch.setattr(llm, "_openai", falla)

    with pytest.raises(RuntimeError):
        llm.complete(Tarea.CHAT, "sys", "user")

    assert len(estado.fallas_llm("real")) == 1


def test_llm_complete_no_cuenta_los_exitos(monkeypatch):
    monkeypatch.setattr(sandbox, "proveedor_llm", lambda: "openai")
    monkeypatch.setattr(llm, "_openai", lambda *_a, **_k: "ok")

    assert llm.complete(Tarea.CHAT, "sys", "user") == "ok"
    assert estado.fallas_llm("real") == ()


# --- señales de la base ---------------------------------------------------------------------------------------------

def test_consultas_de_grabaciones_en_proceso_y_con_error(client):  # client: el lifespan crea las tablas
    s = db.create_session("Estado banner", "Breakout")
    try:
        antes = db.errores_desde(AHORA - HORA)
        with db.conn() as c:
            c.execute("UPDATE sessions SET status='transcribing', updated_at=%s WHERE id=%s", (AHORA - 30 * MIN, s["id"]))
        assert AHORA - 30 * MIN in db.updated_at_en_proceso()

        with db.conn() as c:
            c.execute("UPDATE sessions SET status='error', updated_at=%s WHERE id=%s", (AHORA, s["id"]))
        assert db.errores_desde(AHORA - HORA) == antes + 1
        assert AHORA - 30 * MIN not in db.updated_at_en_proceso()
    finally:
        db.delete_session(s["id"])


# --- endpoint --------------------------------------------------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_sin_sesion_da_401(client):
    assert client.get("/api/estado").status_code == 401


def test_endpoint_devuelve_el_contrato(client, monkeypatch):
    monkeypatch.setattr(estado_api.pipeline, "vivo", lambda: True)
    monkeypatch.setattr(estado_api.db, "updated_at_en_proceso", lambda: [])
    monkeypatch.setattr(estado_api.db, "errores_desde", lambda _desde: 0)
    monkeypatch.setattr(estado_api.eventos_auto, "estado", lambda: _eventos(_revision("luma", 1)))

    r = client.get("/api/estado", headers=login_headers(client))

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["version"] == __version__
    assert cuerpo["servicio"] == []
    assert dt.datetime.fromisoformat(cuerpo["generado"]).tzinfo is not None


def test_senal_que_explota_no_rompe_el_endpoint(client, monkeypatch):
    def explota():
        raise RuntimeError("relation evento_revision does not exist")

    monkeypatch.setattr(estado_api.pipeline, "vivo", lambda: True)
    monkeypatch.setattr(estado_api.eventos_auto, "estado", explota)

    r = client.get("/api/estado", headers=login_headers(client))

    assert r.status_code == 200
    assert "evento_revision" not in r.text


def test_la_respuesta_se_cachea_60_s(client, monkeypatch):
    llamadas = []

    def calcular(contexto, ahora=None):
        llamadas.append(contexto)
        return {"version": __version__, "servicio": [], "generado": estado.iso(ahora)}

    monkeypatch.setattr(estado_api, "calcular", calcular)
    headers = login_headers(client)

    primera = client.get("/api/estado", headers=headers).json()
    segunda = client.get("/api/estado", headers=headers).json()

    assert llamadas == ["real"]
    assert primera == segunda

    # Se envejece la entrada del caché más allá de CACHE_S: el pedido siguiente recalcula.
    guardado_en, respuesta = estado_api._cache["real"]
    estado_api._cache["real"] = (guardado_en - estado_api.CACHE_S - 1, respuesta)
    client.get("/api/estado", headers=headers)

    assert llamadas == ["real", "real"]


def test_en_modo_prueba_usa_su_propio_contexto(client, monkeypatch):
    llamadas = []
    monkeypatch.setattr(estado_api, "calcular", lambda contexto, ahora=None: llamadas.append(contexto) or {})
    headers = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    db.set_user_sandbox(TEST_ADMIN, True, sandbox.config_json(stt="fake", llm="fake", reloj=None, id_sede=None))
    try:
        client.get("/api/estado", headers=headers)
    finally:
        db.set_user_sandbox(TEST_ADMIN, False, None)

    assert llamadas == ["prueba"]

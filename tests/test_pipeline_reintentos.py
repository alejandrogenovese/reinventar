"""Reintentos de grabaciones: la transcripción se guarda pedazo por pedazo (un 429 en el pedazo N no obliga a volver a
transcribir del 1 al N-1) y las que fallan por un error transitorio se reintentan solas, con tope y espera creciente.
STT y LLM fake: no llama a ninguna API."""
import threading

import pytest

from app import audio, borrar_usuario, config, db, limites, pipeline, stt

PEDAZOS = 4
SEGS_POR_PEDAZO = 3
SEG = config.STT_SEGMENT_SECONDS
AHORA = 1_000_000.0


class CupoAgotado(RuntimeError):
    """Lo que tira el STT con un 429 del cupo diario de Groq."""


@pytest.fixture
def grabacion(monkeypatch, tmp_path):
    """Una grabación de PEDAZOS pedazos con audio y STT simulados. `llamadas` anota qué pedazos se mandaron al STT
    y `fallar` dice en qué pedazo tira un 429 (una sola vez)."""
    db.init()
    llamadas, fallar, encoladas = [], {"en": None}, []

    def split(full, secs):
        out = []
        for i in range(PEDAZOS):
            p = tmp_path / f"seg-{i:03d}.ogg"
            p.write_bytes(b"audio")
            out.append((float(i * secs), p))
        return out

    def fake(path):
        n = int(path.stem.split("-")[1]) + 1
        if fallar["en"] == n:
            fallar["en"] = None
            raise CupoAgotado("429 Too Many Requests")
        llamadas.append(n)
        return [{"start": j * 5.0, "end": (j + 1) * 5.0, "text": f"Piece {n} sentence {j}."} for j in range(SEGS_POR_PEDAZO)]

    monkeypatch.setattr(db, "chunk_index", lambda sid: {0: {0}})
    monkeypatch.setattr(audio, "assemble", lambda sid, parts: tmp_path / "full.ogg")
    monkeypatch.setattr(audio, "duration", lambda path: PEDAZOS * SEG)
    monkeypatch.setattr(audio, "split", split)
    monkeypatch.setattr(stt, "_fake", fake)
    # El worker real puede estar corriendo (otro test abrió la app): lo encolado se anota acá y se procesa a mano.
    monkeypatch.setattr(pipeline, "_encolar", lambda trabajo: encoladas.append(trabajo))

    def nueva(titulo="Charla"):
        return db.create_session(titulo, "Breakout", created_by="tester")["id"]

    return {"nueva": nueva, "llamadas": llamadas, "fallar": fallar, "encoladas": encoladas}


# La base es compartida entre tests: el barrido puede ver grabaciones en error de otros, por eso se mira solo la propia.
def _transcripcion(sid):
    return [(b["start_s"], b["end_s"], b["en"]) for b in db.get_blocks(sid)]


def _procesar_falla(sid, monkeypatch, excepcion):
    def falla(_sid):
        raise excepcion
    with monkeypatch.context() as m:
        m.setattr(pipeline, "process", falla)
        pipeline._procesar(sid, None, None)


# ---------- transcripción guardada por pedazo ----------

def test_un_429_en_el_pedazo_n_no_vuelve_a_transcribir_los_anteriores(grabacion, monkeypatch):
    limpia = grabacion["nueva"]("Sin fallas")
    pipeline._procesar(limpia, None, None)
    assert db.get_session(limpia)["status"] == "ready"
    grabacion["llamadas"].clear()

    sid = grabacion["nueva"]("Con un 429")
    grabacion["fallar"]["en"] = 3
    monkeypatch.setattr(pipeline.time, "time", lambda: AHORA)
    pipeline._procesar(sid, None, None)

    s = db.get_session(sid)
    assert s["status"] == "error" and s["error"] == pipeline.ERROR_REINTENTO_AUTO
    assert grabacion["llamadas"] == [1, 2]
    assert set(db.stt_pedazos(sid, pipeline.firma_audio(s))) == {1, 2}  # quedaron guardados aunque falló el 3

    grabacion["llamadas"].clear()
    assert sid in pipeline.barrer_reintentos(AHORA + 15 * 60)
    pipeline._procesar(*next(t for t in grabacion["encoladas"] if t[0] == sid))

    assert grabacion["llamadas"] == [3, 4]  # solo los que faltaban
    assert db.get_session(sid)["status"] == "ready"
    assert _transcripcion(sid) == _transcripcion(limpia)  # mismos offsets, sin segmentos duplicados
    assert db.stt_pedazos(sid, pipeline.firma_audio(db.get_session(sid))) == {}  # ya están en los bloques


def test_si_cambia_el_audio_no_se_reusa_lo_transcripto(grabacion):
    sid = grabacion["nueva"]()
    db.guardar_stt_pedazo(sid, 1, "otra-firma", [{"start": 0, "end": 1, "text": "Viejo."}])

    pipeline._procesar(sid, None, None)

    assert grabacion["llamadas"] == [1, 2, 3, 4]
    assert "Viejo." not in " ".join(b["en"] for b in db.get_blocks(sid))


def test_reintentar_desde_cero_borra_lo_transcripto_por_pedazo(grabacion):
    sid = grabacion["nueva"]()
    db.guardar_stt_pedazo(sid, 1, "f", [{"start": 0, "end": 1, "text": "Algo."}])

    db.replace_blocks(sid, [])  # lo que hace POST /retry?from_scratch=true

    assert db.stt_pedazos(sid, "f") == {}


def test_borrar_la_grabacion_borra_lo_transcripto_por_pedazo(grabacion):
    sid = grabacion["nueva"]()
    db.guardar_stt_pedazo(sid, 1, "f", [{"start": 0, "end": 1, "text": "Algo."}])

    db.delete_session(sid)

    assert db.stt_pedazos(sid, "f") == {}
    assert "stt_pedazos" in db.tablas_datos_usuario()
    assert "stt_pedazos" not in borrar_usuario._tablas_con_username()  # cuelga de la grabación, no tiene username


# ---------- transitorio vs. definitivo ----------

def test_un_error_para_mostrar_es_definitivo_y_no_se_reintenta_solo(grabacion, monkeypatch):
    sid = grabacion["nueva"]()
    monkeypatch.setattr(pipeline.time, "time", lambda: AHORA)

    _procesar_falla(sid, monkeypatch, pipeline.ErrorParaMostrar(pipeline.SIN_VOZ))

    s = db.get_session(sid)
    assert s["error"] == pipeline.SIN_VOZ and s["reintento_auto_at"] is None
    assert sid not in pipeline.barrer_reintentos(AHORA + 10 * 3600)


def test_los_reintentos_automaticos_esperan_cada_vez_mas_y_tienen_tope(grabacion, monkeypatch):
    sid = grabacion["nueva"]()
    monkeypatch.setattr(pipeline.time, "time", lambda: AHORA)
    esperas = []
    for _ in range(pipeline.MAX_REINTENTOS_AUTO):
        _procesar_falla(sid, monkeypatch, CupoAgotado("429"))
        s = db.get_session(sid)
        assert s["error"] == pipeline.ERROR_REINTENTO_AUTO
        esperas.append(round((s["reintento_auto_at"] - AHORA) / 60))
        assert sid not in pipeline.barrer_reintentos(s["reintento_auto_at"] - 1)  # todavía no toca
        assert sid in pipeline.barrer_reintentos(s["reintento_auto_at"])
        assert db.get_session(sid)["status"] == "queued"

    _procesar_falla(sid, monkeypatch, CupoAgotado("429"))

    s = db.get_session(sid)
    assert esperas == [15, 30, 60]
    assert s["reintentos_auto"] == 3 and s["reintento_auto_at"] is None
    assert s["error"] == pipeline.ERROR_GENERICO  # agotados: queda el «Reintentar» a mano
    assert sid not in pipeline.barrer_reintentos(AHORA + 10 * 3600)


# ---------- sin superponerse ----------

def test_no_reencola_una_que_el_worker_ya_tiene(grabacion, monkeypatch):
    sid = grabacion["nueva"]()
    monkeypatch.setattr(pipeline.time, "time", lambda: AHORA)
    _procesar_falla(sid, monkeypatch, CupoAgotado("429"))
    monkeypatch.setitem(pipeline._en_el_worker, sid, 1)

    assert sid not in pipeline.barrer_reintentos(AHORA + 3600)
    assert db.get_session(sid)["status"] == "error"


def test_un_reintento_a_mano_se_lleva_el_automatico(grabacion, monkeypatch):
    sid = grabacion["nueva"]()
    monkeypatch.setattr(pipeline.time, "time", lambda: AHORA)
    _procesar_falla(sid, monkeypatch, CupoAgotado("429"))

    pipeline.enqueue(sid)  # «Reintentar»

    assert db.get_session(sid)["reintento_auto_at"] is None
    assert sid not in pipeline.barrer_reintentos(AHORA + 3600)
    assert [t for t in grabacion["encoladas"] if t[0] == sid] == [(sid, None, None)]  # solo la del botón


def test_tomar_el_reintento_falla_si_ya_no_esta_en_error(grabacion, monkeypatch):
    sid = grabacion["nueva"]()
    monkeypatch.setattr(pipeline.time, "time", lambda: AHORA)
    _procesar_falla(sid, monkeypatch, CupoAgotado("429"))
    db.update_session(sid, status="queued")  # alguien la reintentó entre la consulta y el UPDATE

    assert not db.tomar_reintento_auto(sid)


def test_el_reintento_automatico_no_gasta_el_cupo_de_reintentar(grabacion, monkeypatch):
    monkeypatch.setattr(limites, "reintentos_grabacion", limites.Limite(1, limites.VENTANA_LARGA))
    monkeypatch.setattr(pipeline.time, "time", lambda: AHORA)
    sid = grabacion["nueva"]()
    _procesar_falla(sid, monkeypatch, CupoAgotado("429"))

    assert sid in pipeline.barrer_reintentos(AHORA + 3600)
    assert not limites.reintentos_grabacion.excedido("tester")


# ---------- el hilo ----------

def test_el_barrido_sobrevive_a_un_error_y_sigue(monkeypatch):
    parar, vueltas = threading.Event(), []

    def barrer():
        vueltas.append(1)
        if len(vueltas) == 1:
            raise RuntimeError("base caída")
        parar.set()

    monkeypatch.setattr(pipeline, "BARRIDO_REINTENTOS_MIN", 0)
    monkeypatch.setattr(pipeline, "barrer_reintentos", barrer)

    pipeline._loop_reintentos(parar)

    assert len(vueltas) == 2


def test_en_los_tests_el_barrido_esta_apagado():
    assert not config.PIPELINE_REINTENTOS_AUTO

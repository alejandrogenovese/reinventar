"""Grabaciones: quién puede subir audio y cerrar, topes por grabación y por usuario, un worker que no se muere y la
limpieza del disco. Corre en CI: Postgres local, STT y LLM fake, sin catálogo."""
import queue
import subprocess
import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from app import audio, config, db, limites, pipeline
from app.main import GRABACION_DEMASIADO_GRANDE, GRABACIONES_DEL_DIA, SOLO_QUIEN_GRABA, YA_SE_PROCESA, app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

PASSWORD = "otrapass1234"


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(pipeline, "enqueue", lambda sid: db.update_session(sid, status="queued"))
    with TestClient(app) as c:
        c.admin = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        c.user = login_headers(c)
        otro = f"otro_{uuid.uuid4().hex[:6]}"
        assert c.post("/api/admin/users", headers=c.admin, json={"username": otro, "password": PASSWORD}).status_code == 200
        c.otro = login_headers(c, otro, PASSWORD)
        c.creadas = []
        yield c
        for sid in c.creadas:
            db.delete_session(sid)


def _grabacion(c, created_by=TEST_USER, status="recording"):
    sid = db.create_session("Prueba", "Breakout", created_by=created_by)["id"]
    if status != "recording":
        db.update_session(sid, status=status)
    c.creadas.append(sid)
    return sid


def _subir(c, sid, quien="user", part=0, seq=0, data=b"audio"):
    return c.put(f"/api/sessions/{sid}/chunks/{part}/{seq}", headers=getattr(c, quien), content=data)


# --- dueño: subir pedazos y terminar ----------------------------------------------------------------

@pytest.mark.parametrize("quien,esperado", [("user", 200), ("otro", 403), ("admin", 403)])
def test_subir_audio_solo_quien_grabo(cli, quien, esperado):
    sid = _grabacion(cli)

    r = _subir(cli, sid, quien)

    assert r.status_code == esperado, r.text
    if esperado == 403:
        assert r.json()["detail"] == SOLO_QUIEN_GRABA
        assert db.chunk_index(sid) == {}


def test_nadie_reabre_ni_pisa_una_ajena_en_error(cli):
    sid = _grabacion(cli, status="error")

    assert _subir(cli, sid, "otro").status_code == 403
    assert db.get_session(sid)["status"] == "error"


@pytest.mark.parametrize("quien", ["user", "admin"])
def test_a_las_viejas_sin_duenio_nadie_les_sube_audio(cli, quien):
    sid = _grabacion(cli, created_by=None)

    assert _subir(cli, sid, quien).status_code == 403


@pytest.mark.parametrize("quien,esperado", [("user", 200), ("otro", 403), ("admin", 200)])
def test_terminar_solo_quien_grabo_o_un_admin(cli, quien, esperado):
    sid = _grabacion(cli)
    assert _subir(cli, sid).status_code == 200

    r = cli.post(f"/api/sessions/{sid}/finish", headers=getattr(cli, quien), json={"parts": {"0": 1}})

    assert r.status_code == esperado, r.text
    assert db.get_session(sid)["status"] == ("queued" if esperado == 200 else "recording")


def test_otro_no_corta_una_grabacion_ajena_con_partes_vacias(cli):
    sid = _grabacion(cli)

    assert cli.post(f"/api/sessions/{sid}/finish", headers=cli.otro, json={"parts": {}}).status_code == 403
    assert db.get_session(sid)["status"] == "recording"


@pytest.mark.parametrize("quien,esperado", [("user", 403), ("admin", 200)])
def test_las_viejas_sin_duenio_solo_las_cierra_un_admin(cli, quien, esperado):
    sid = _grabacion(cli, created_by=None, status="uploading")

    assert cli.post(f"/api/sessions/{sid}/finish", headers=getattr(cli, quien), json={"parts": {}}).status_code == esperado


# --- topes por grabación -----------------------------------------------------------------------------

def test_tope_de_pedazos_por_grabacion(cli, monkeypatch):
    monkeypatch.setattr(config, "MAX_GRABACION_PEDAZOS", 2)
    sid = _grabacion(cli)
    assert _subir(cli, sid, seq=0).status_code == 200
    assert _subir(cli, sid, seq=1).status_code == 200

    r = _subir(cli, sid, seq=2)

    assert r.status_code == 413 and r.json()["detail"] == GRABACION_DEMASIADO_GRANDE
    assert _subir(cli, sid, seq=1).status_code == 200  # volver a subir uno que ya estaba no suma


def test_tope_de_bytes_por_grabacion(cli, monkeypatch):
    monkeypatch.setattr(config, "MAX_GRABACION_BYTES", 10)
    sid = _grabacion(cli)
    assert _subir(cli, sid, seq=0, data=b"x" * 6).status_code == 200

    assert _subir(cli, sid, seq=1, data=b"x" * 5).status_code == 413
    assert _subir(cli, sid, seq=1, data=b"x" * 4).status_code == 200


def test_cuota_diaria_de_grabaciones_nuevas(cli, monkeypatch):
    monkeypatch.setattr(limites, "grabaciones_nuevas", limites.Limite(2, limites.VENTANA_DIA))

    def crear(headers, client_id):
        r = cli.post("/api/sessions", headers=headers, json={"title": "Charla", "kind": "Breakout", "client_id": client_id})
        if r.status_code == 200:
            cli.creadas.append(r.json()["id"])
        return r

    primera = f"loc_{uuid.uuid4().hex[:8]}"
    assert crear(cli.user, primera).status_code == 200
    assert crear(cli.user, f"loc_{uuid.uuid4().hex[:8]}").status_code == 200

    assert crear(cli.user, primera).status_code == 200  # el mismo client_id es un reintento: no gasta cuota
    r = crear(cli.user, f"loc_{uuid.uuid4().hex[:8]}")
    assert r.status_code == 429 and r.json()["detail"] == GRABACIONES_DEL_DIA
    assert crear(cli.otro, f"loc_{uuid.uuid4().hex[:8]}").status_code == 200  # la cuota es por usuario


@pytest.mark.parametrize("status", sorted(db.PROCESSING))
def test_reintentar_mientras_se_procesa_da_409(cli, status):
    sid = _grabacion(cli, status=status)

    r = cli.post(f"/api/sessions/{sid}/retry", headers=cli.user)

    assert r.status_code == 409 and r.json()["detail"] == YA_SE_PROCESA


def test_los_reintentos_tienen_tope(cli, monkeypatch):
    monkeypatch.setattr(limites, "reintentos_grabacion", limites.Limite(2, limites.VENTANA_LARGA))
    sid = _grabacion(cli, status="error")
    for _ in range(2):
        assert cli.post(f"/api/sessions/{sid}/retry", headers=cli.user).status_code == 200
        db.update_session(sid, status="error")

    assert cli.post(f"/api/sessions/{sid}/retry", headers=cli.user).status_code == 429


# --- el worker del pipeline -------------------------------------------------------------------------

def _falla(_sid):
    raise RuntimeError("ffmpeg falló: ffmpeg -y -v…\n/data/sessions/abc/work/part-000.webm: Invalid data")


def test_un_error_de_base_al_marcar_el_error_no_mata_al_worker(monkeypatch):
    procesadas, cola = [], queue.Queue()
    monkeypatch.setattr(pipeline, "process", lambda sid: _falla(sid) if sid == "rota" else procesadas.append(sid))

    def base_caida(*_a, **_k):
        raise TimeoutError("PoolTimeout")

    monkeypatch.setattr(db, "update_session", base_caida)
    threading.Thread(target=pipeline._loop, args=(cola,), name="pipeline-test", daemon=True).start()
    cola.put(("rota", None, None))
    cola.put(("sana", None, None))

    cola.join()

    assert procesadas == ["sana"]


def test_el_worker_sobrevive_a_un_error_fuera_de_procesar(monkeypatch):
    procesadas, cola = [], queue.Queue()
    monkeypatch.setattr(pipeline, "_procesar", lambda sid, *_: _falla(sid) if sid == "rota" else procesadas.append(sid))
    threading.Thread(target=pipeline._loop, args=(cola,), name="pipeline-test", daemon=True).start()
    cola.put(("rota", None, None))
    cola.put(("sana", None, None))

    cola.join()

    assert procesadas == ["sana"]


def test_el_error_crudo_va_al_log_y_se_muestra_uno_generico(cli, monkeypatch, caplog):
    sid = _grabacion(cli)
    monkeypatch.setattr(pipeline, "process", _falla)

    pipeline._procesar(sid, None, None)

    s = db.get_session(sid)
    assert s["status"] == "error" and s["error"] == pipeline.ERROR_GENERICO
    assert "Invalid data" in caplog.text


def test_los_errores_pensados_para_mostrar_se_muestran_tal_cual(cli, monkeypatch):
    sid = _grabacion(cli)

    def sin_voz(_sid):
        raise pipeline.ErrorParaMostrar(pipeline.SIN_VOZ)

    monkeypatch.setattr(pipeline, "process", sin_voz)

    pipeline._procesar(sid, None, None)

    assert db.get_session(sid)["error"] == pipeline.SIN_VOZ


def test_health_dice_si_el_pipeline_esta_vivo():
    with TestClient(app) as c:
        cuerpo = c.get("/health").json()

    assert cuerpo["pipeline"] is True


# --- disco: lo intermedio se borra, los pedazos quedan ------------------------------------------------

def _tono(destino, segundos=3):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}",
                    "-c:a", "libopus", "-b:a", "32k", str(destino)], check=True)
    return destino.read_bytes()


def _con_audio(c):
    sid = _grabacion(c, status="queued")
    path = audio.chunk_path(sid, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _tono(path)
    db.record_chunk(sid, 0, 0, len(data))
    return sid


def test_armar_el_audio_no_deja_la_copia_webm_de_cada_parte(cli):
    sid = _con_audio(cli)

    full = audio.assemble(sid, db.chunk_index(sid))

    work = audio.session_dir(sid) / "work"
    assert full.exists() and not list(work.glob("part-*"))
    assert audio.chunk_path(sid, 0, 0).exists()


def test_al_quedar_lista_se_borra_work_y_quedan_los_pedazos(cli):
    sid = _con_audio(cli)

    pipeline.process(sid)

    assert db.get_session(sid)["status"] == "ready"
    assert not (audio.session_dir(sid) / "work").exists()
    assert audio.chunk_path(sid, 0, 0).exists()  # «Reintentar desde cero» los vuelve a usar


def test_una_grabacion_mas_larga_que_el_tope_no_llega_al_stt(cli, monkeypatch):
    sid = _con_audio(cli)
    monkeypatch.setattr(config, "MAX_GRABACION_SEGUNDOS", 1)
    monkeypatch.setattr(pipeline.stt, "transcribe", lambda *_: pytest.fail("no tenía que transcribir"))

    pipeline._procesar(sid, None, None)

    s = db.get_session(sid)
    assert s["status"] == "error" and "demasiado larga" in s["error"]

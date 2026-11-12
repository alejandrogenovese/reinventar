"""Buscar en lo grabado: fragmentos de las transcripciones, indexados con pgvector y tsvector (embeddings falsos)."""
import pytest
from fastapi.testclient import TestClient

from app import db, fragmentos
from app.main import app
from tests.conftest import login_headers


def _bloques(textos, segundos=15):
    return [{"start_s": i * segundos, "end_s": (i + 1) * segundos, "en": en, "es": es}
            for i, (en, es) in enumerate(textos)]


def _grabacion(titulo, textos, status="ready"):
    s = db.create_session(titulo, "Breakout", "DAT301")
    db.replace_blocks(s["id"], [{"start": b["start_s"], "end": b["end_s"], "en": b["en"], "es": b["es"]}
                                for b in _bloques(textos)])
    db.update_session(s["id"], status=status)
    return s["id"]


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:  # corre el lifespan: crea las tablas y habilita pgvector
        yield c


# --- ventanas ----------------------------------------------------------------
def test_las_ventanas_juntan_bloques_hasta_el_largo_y_se_solapan_en_un_bloque():
    bloques = _bloques([(f"b{i}", f"b{i}") for i in range(8)])  # 8 bloques de 15 s = 2 min

    ventanas = fragmentos.armar_ventanas(bloques, ventana=40)

    assert [(v["start_s"], v["end_s"]) for v in ventanas] == [(0, 45), (30, 75), (60, 105), (90, 120)]
    assert ventanas[0]["en"] == "b0 b1 b2"


def test_sin_traduccion_completa_la_ventana_queda_sin_castellano():
    ventanas = fragmentos.armar_ventanas(_bloques([("one", "uno"), ("two", None)]), ventana=40)

    assert ventanas == [{"start_s": 0, "end_s": 30, "en": "one two", "es": None}]


def test_un_solo_bloque_largo_es_una_ventana_y_sin_bloques_no_hay_ninguna():
    assert len(fragmentos.armar_ventanas([{"start_s": 0, "end_s": 90, "en": "x", "es": "x"}])) == 1
    assert fragmentos.armar_ventanas([]) == []


# --- indexar y buscar --------------------------------------------------------
def test_pgvector_queda_habilitado_al_arrancar(cliente):
    assert db.vector_disponible


def test_encuentra_el_fragmento_por_un_nombre_propio_y_devuelve_el_segundo(cliente):
    sid = _grabacion("Grafos en AWS", [
        ("Welcome everyone to this session.", "Bienvenidos a esta sesión."),
        ("Today we talk about pricing.", "Hoy hablamos de precios."),
        ("Let me show the agenda.", "Les muestro la agenda."),
        ("Neptune lets business analysts explore the graph.", "Neptune permite a los analistas explorar el grafo."),
        ("Thanks for coming.", "Gracias por venir."),
    ])
    assert fragmentos.indexar(sid) > 0

    resultados = fragmentos.buscar("¿qué dijeron de Neptune?")

    primero = resultados[0]
    assert primero["session_id"] == sid and primero["title"] == "Grafos en AWS"
    assert "Neptune" in primero["en"] and primero["start_s"] >= 30


def test_busca_en_castellano_aunque_la_palabra_tenga_tilde(cliente):
    sid = _grabacion("Migraciones", [("We migrated from Teradata.", "Migramos desde Teradata con éxito.")])
    fragmentos.indexar(sid)

    assert any(r["session_id"] == sid for r in fragmentos.buscar("migración exito teradata"))


def test_no_repite_fragmentos_vecinos_de_la_misma_grabacion(cliente):
    sid = _grabacion("Iceberg", [(f"Iceberg tables part {i}.", f"Tablas Iceberg parte {i}.") for i in range(10)])
    fragmentos.indexar(sid)

    idxs = sorted(r["idx"] for r in fragmentos.buscar("iceberg") if r["session_id"] == sid)

    assert idxs and all(b - a > 1 for a, b in zip(idxs, idxs[1:]))


def test_reemplazar_o_borrar_la_grabacion_borra_sus_fragmentos(cliente):
    sid = _grabacion("Efímera", [("Kinesis streams everywhere.", "Kinesis por todos lados.")])
    fragmentos.indexar(sid)
    assert fragmentos.buscar("kinesis")

    db.replace_blocks(sid, [{"start": 0, "end": 15, "en": "Other topic.", "es": "Otro tema."}])
    assert not [r for r in fragmentos.buscar("kinesis") if r["session_id"] == sid]

    fragmentos.indexar(sid)
    db.delete_session(sid)
    assert not [r for r in fragmentos.buscar("otro tema") if r["session_id"] == sid]


def test_indexar_pendientes_toma_las_listas_sin_fragmentos_y_no_las_que_estan_en_proceso(cliente):
    lista = _grabacion("Lista", [("Glue crawlers.", "Crawlers de Glue.")])
    en_proceso = _grabacion("En proceso", [("Athena queries.", "Consultas de Athena.")], status="translating")

    assert lista in fragmentos.pendientes() and en_proceso not in fragmentos.pendientes()
    fragmentos.indexar_pendientes()

    assert lista not in fragmentos.pendientes()


def test_un_error_al_indexar_no_rompe_la_grabacion(cliente, monkeypatch):
    def falla(_sid):
        raise RuntimeError("sin embeddings")

    monkeypatch.setattr(fragmentos, "indexar", falla)

    fragmentos.indexar_sin_fallar("cualquiera")  # no levanta: solo deja el error en el log


def test_consulta_vacia_o_sin_pgvector_no_devuelve_nada(cliente, monkeypatch):
    assert fragmentos.buscar("   ") == []
    monkeypatch.setattr(db, "vector_disponible", False)
    assert fragmentos.buscar("neptune") == []


# --- API ---------------------------------------------------------------------
def test_api_busca_en_lo_grabado_y_pide_login(cliente):
    sid = _grabacion("Lake Formation", [("Lake Formation permissions.", "Permisos de Lake Formation.")])
    fragmentos.indexar(sid)

    assert cliente.get("/api/grabaciones/buscar?q=lake").status_code == 401
    H = login_headers(cliente)
    r = cliente.get("/api/grabaciones/buscar", params={"q": "permisos de lake formation"}, headers=H)

    assert r.status_code == 200 and r.json()["disponible"]
    assert r.json()["resultados"][0]["session_id"] == sid
    assert cliente.get("/api/grabaciones/buscar?q=x", headers=H).status_code == 422


def test_por_significado_descarta_lo_que_no_se_parece(cliente, monkeypatch):
    sid = _grabacion("Ruido", [("Amazon Aurora serverless scaling.", "Escalado serverless de Amazon Aurora.")])
    fragmentos.indexar(sid)
    monkeypatch.setattr(fragmentos, "_por_palabras", lambda c, q: [])  # solo la parte por significado

    assert not [r for r in fragmentos.buscar("receta de empanadas tucumanas") if r["session_id"] == sid]
    assert [r for r in fragmentos.buscar("escalado serverless de aurora") if r["session_id"] == sid]


def test_en_lo_grabado_el_plural_encuentra_el_singular(cliente, monkeypatch):
    sid = _grabacion("Mainframe", [("We moved the mainframe to AWS.", "Movimos el mainframe a AWS.")])
    fragmentos.indexar(sid)
    monkeypatch.setattr(fragmentos, "_por_significado", lambda c, q: [])  # solo la parte por palabras

    assert [r for r in fragmentos.buscar("migrar mainframes") if r["session_id"] == sid]

"""Pestaña "Todas las fechas" de Eventos: lógica pura (node) y cableado en events.js (estático)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
MODULO = RAIZ / "web" / "js" / "eventosTodas.js"
EVENTS = (RAIZ / "web" / "js" / "events.js").read_text(encoding="utf-8")

necesita_node = pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")

DIAS = [
    {"day": "2026-12-01", "events": [
        {"code": "a", "type": "party", "start": "18:00", "venue": {"lat": 0, "lng": 2}},
        {"code": "b", "type": "breakfast", "start": "08:00", "venue": {"lat": 0, "lng": 1}},
    ]},
    {"day": "2026-12-02", "events": [
        {"code": "c", "type": "party", "start": "17:00", "venue": {"lat": 0, "lng": 1}},
        {"code": "d", "type": "party", "start": "16:59", "venue": {"lat": 0, "lng": 3}},
        {"code": "e", "type": "party", "venue": {"lat": 0, "lng": 4}},
        {"code": "f", "type": "party", "start": "19:00", "cancelled": True, "venue": {"lat": 0, "lng": 0}},
    ]},
]


def correr(expresion: str):
    """Evalúa una expresión JS sobre eventosTodas.js y devuelve el JSON resultante."""
    guion = (
        f"import * as m from {json.dumps(MODULO.as_uri())};\n"
        f"const dias = {json.dumps(DIAS)};\n"
        "const dist = (a, b) => Math.abs(a.lng - b.lng);\n"
        f"console.log(JSON.stringify({expresion}));\n"
    )
    r = subprocess.run(["node", "--input-type=module", "-e", guion], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def codigos(grupos):
    return [[e["code"] for e in g["events"]] for g in grupos]


@necesita_node
def test_todas_las_fechas_agrupa_por_dia():
    grupos = correr('m.filtrarEventos(dias, { day: m.TODAS, type: "todos" })')
    assert [g["day"] for g in grupos] == ["2026-12-01", "2026-12-02"]
    assert codigos(grupos) == [["a", "b"], ["c", "d", "e", "f"]]


@necesita_node
def test_un_dia_devuelve_solo_ese_grupo():
    grupos = correr('m.filtrarEventos(dias, { day: "2026-12-02", type: "todos" })')
    assert codigos(grupos) == [["c", "d", "e", "f"]]


@necesita_node
def test_los_cancelados_van_al_final_del_dia():
    grupos = correr('m.filtrarEventos(dias, { day: "2026-12-02", type: "todos", near: true, here: { lat: 0, lng: 0 }, distance: dist })')
    assert codigos(grupos) == [["c", "d", "e", "f"]]


@necesita_node
def test_combina_tipo_party_con_todas_las_fechas():
    grupos = correr('m.filtrarEventos(dias, { day: m.TODAS, type: "party" })')
    assert codigos(grupos) == [["a"], ["c", "d", "e", "f"]]


@necesita_node
def test_desde_las_17_deja_los_que_empiezan_a_partir_de_esa_hora():
    grupos = correr('m.filtrarEventos(dias, { day: m.TODAS, type: "todos", desde: 17 })')
    assert codigos(grupos) == [["a"], ["c", "f"]]


@necesita_node
def test_mas_cerca_ordena_dentro_de_cada_dia():
    grupos = correr('m.filtrarEventos(dias, { day: m.TODAS, type: "todos", near: true, here: { lat: 0, lng: 0 }, distance: dist })')
    assert codigos(grupos) == [["b", "a"], ["c", "d", "e", "f"]]


@necesita_node
def test_mas_cerca_sin_ubicacion_no_reordena():
    grupos = correr('m.filtrarEventos(dias, { day: m.TODAS, type: "todos", near: true, here: null, distance: dist })')
    assert codigos(grupos)[0] == ["a", "b"]


@necesita_node
def test_sin_resultados_devuelve_lista_vacia():
    assert correr('m.filtrarEventos(dias, { day: m.TODAS, type: "inexistente" })') == []


@necesita_node
def test_no_muta_los_dias_de_entrada():
    assert correr('(() => { const antes = JSON.stringify(dias); m.filtrarEventos(dias, { day: m.TODAS, type: "todos", desde: 17 }); return antes === JSON.stringify(dias); })()') is True


@necesita_node
def test_guardar_y_leer_filtros_tolera_storage_roto_y_datos_basura():
    resultado = correr(
        '(() => {'
        ' globalThis.sessionStorage = { getItem: () => { throw new Error("bloqueado"); }, setItem: () => { throw new Error("bloqueado"); } };'
        ' m.guardarFiltros({ day: "x" });'
        ' const roto = m.leerFiltros();'
        ' const datos = new Map();'
        ' globalThis.sessionStorage = { getItem: (k) => datos.get(k) ?? null, setItem: (k, v) => datos.set(k, v) };'
        ' m.guardarFiltros({ day: m.TODAS, type: "party", near: true, desde: 17 });'
        ' const ok = m.leerFiltros();'
        ' datos.set(m.CLAVE_FILTROS, "{no es json");'
        ' return { roto, ok, basura: m.leerFiltros() };'
        '})()'
    )
    assert resultado["roto"] is None
    assert resultado["ok"] == {"day": "todas", "type": "party", "near": True, "desde": 17}
    assert resultado["basura"] is None


def test_events_js_usa_el_modulo_y_muestra_la_pestana():
    assert 'from "./eventosTodas.js"' in EVENTS
    assert "Todas las fechas" in EVENTS
    assert "`Desde las ${HORA_DE_FIESTAS}`" in EVENTS
    assert "HORA_DE_FIESTAS = 17" in MODULO.read_text(encoding="utf-8")
    assert "filtrarEventos(" in EVENTS and "guardarFiltros(" in EVENTS


def test_el_modulo_nuevo_esta_en_el_precache_del_service_worker():
    sw = (RAIZ / "web" / "sw.js").read_text(encoding="utf-8")
    assert '"/js/eventosTodas.js"' in sw

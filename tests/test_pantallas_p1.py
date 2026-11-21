"""Tests estáticos de las pantallas Viajes, Ofertas y Dónde comer: respuestas tardías, filtros, labels y links.
Se verifica el JS/CSS como texto, igual que test_diseno y test_replace_children."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
VIAJES = (WEB / "js" / "viajes.js").read_text()
OFERTAS = (WEB / "js" / "ofertas.js").read_text()
COMER = (WEB / "js" / "comer.js").read_text()
CSS = (WEB / "styles.css").read_text()


@pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")
@pytest.mark.parametrize("archivo", ["viajes.js", "ofertas.js", "comer.js"])
def test_el_js_es_sintaxis_valida(archivo):
    r = subprocess.run(["node", "--check", str(WEB / "js" / archivo)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_viajes_pinta_en_un_contenedor_propio_y_no_pisa_otra_pantalla():
    assert "view.replaceChildren" not in VIAJES
    assert "raiz.isConnected" in VIAJES


def test_quitar_desde_el_detalle_apaga_el_foco_antes_de_repintar():
    assert re.search(r"foco = null;.*\n.*location\.hash = \"#/viajes\";\n\s*await paint\(\)", VIAJES)


def test_los_campos_de_vuelo_y_hotel_tienen_label_asociado():
    assert 'h("label", { class: "label", for: control.id }' in VIAJES


def test_el_link_de_checkin_solo_se_acepta_https():
    assert "href: v.checkin_url" not in VIAJES
    assert 'url.startsWith("https://")' in VIAJES


def test_el_alta_espera_el_refresco_y_maneja_su_rechazo():
    assert "await onGuardado()" in VIAJES
    assert not re.search(r"^\s*onGuardado\(\);", VIAJES, re.M)


def test_ofertas_descarta_respuestas_viejas_y_marca_el_filtro():
    assert "mio !== pedido" in OFERTAS
    assert "setAttribute(\"aria-pressed\"" in OFERTAS
    assert ".ra-segtab[aria-pressed=\"true\"]" in CSS


def test_el_filtro_no_se_reconstruye_al_elegir_para_no_perder_el_foco():
    assert "if (!filtros.firstChild)" in OFERTAS


def test_la_ficha_de_una_oferta_pinta_en_un_contenedor_propio():
    ficha = OFERTAS[OFERTAS.index("async function viewOferta(view, id)"):OFERTAS.index("// --- Ajustes")]
    assert "view.append" in ficha and ficha.count("view.append") == 1  # solo el contenedor
    assert ficha.count("raiz.isConnected") == 2


def test_comer_vuelve_a_viaje():
    assert 'class: "ra-btn ra-btn-ghost ra-back", href: "#/viaje"' in COMER

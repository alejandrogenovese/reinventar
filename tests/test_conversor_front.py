"""Tests estáticos del front del conversor (el JS como texto, igual que test_gastos_front y test_diseno).

Las conversiones se prueban con node en tests/js/unidades.test.mjs y el estado sin señal en tests/js/conversorSinSenal.test.mjs."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
JS = WEB / "js"
APP = (JS / "app.js").read_text()
VIAJE = (JS / "viaje.js").read_text()
PANTALLA = (JS / "conversor.js").read_text()
FOTO = (JS / "conversorFoto.js").read_text()
SW = (WEB / "sw.js").read_text()
ARCHIVOS = ("conversor.js", "conversorFoto.js", "unidades.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")
@pytest.mark.parametrize("archivo", ARCHIVOS)
def test_el_js_es_sintaxis_valida(archivo):
    r = subprocess.run(["node", "--check", str(JS / archivo)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_la_tarjeta_esta_en_viaje_y_la_ruta_existe():
    assert re.search(r'\{ href: "#/viaje/conversor", icono: \(\) => icon\("invertir", 20\), titulo: "Conversor"', VIAJE)
    assert re.search(r"\^#\\/viaje\\/conversor\$.*viewConversor", APP)


def test_anda_sin_senal_porque_el_service_worker_precachea_los_modulos():
    for archivo in ARCHIVOS:
        assert f'"/js/{archivo}"' in SW, f"{archivo} falta en el precache"


def test_tiene_las_siete_pestanas_y_recuerda_la_ultima():
    pestanas = re.findall(r'\["(\w+)", "[^"]+"\]', PANTALLA[PANTALLA.index("PESTANAS = ["):PANTALLA.index("];", PANTALLA.index("PESTANAS = ["))])
    assert pestanas == ["clima", "comida", "gym", "distancia", "talles", "propina", "dolar"]
    assert "localStorage.setItem(CLAVE_PESTANA" in PANTALLA and "localStorage.getItem(CLAVE_PESTANA" in PANTALLA
    assert 'inputmode: "decimal"' in PANTALLA and "oninput" in PANTALLA


def test_la_cotizacion_reusa_la_de_gastos_y_muestra_su_antiguedad():
    assert 'leerMeta("cotizacion")' in PANTALLA and 'api("/api/gastos/cotizacion")' in PANTALLA
    assert "textoEdad(edadCotizacion(" in PANTALLA


def test_la_camara_usa_el_mismo_input_y_achicado_que_gastos():
    assert 'type: "file", accept: "image/*", capture: "environment"' in FOTO
    assert "achicarFoto(elegido)" in FOTO and 'import { achicarFoto } from "./gastos.js"' in FOTO
    assert '"/api/conversor/foto", { method: "POST", body: cuerpo }' in FOTO
    assert "convertirDetectada(" in FOTO  # las unidades las convierte el celular, no el LLM


def test_los_estados_de_la_camara_tienen_su_texto():
    assert "No encontré números ni texto legible. Acercate y evitá reflejos." in FOTO
    assert "No pude leer la foto. Probá de nuevo." in FOTO
    assert "MSG_FOTO_SIN_SENAL" in FOTO and "estadoLecturaFoto(" in FOTO
    assert '"/api/conversor/estado"' in FOTO  # con el kill switch apagado, el botón no se muestra

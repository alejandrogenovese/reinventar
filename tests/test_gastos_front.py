"""Tests estáticos del front de gastos (se verifica el JS/CSS como texto, igual que test_diseno y test_replace_children).

La lógica pura se prueba con node en tests/js/gastos.test.mjs; la carga sin señal de punta a punta, en tests_e2e."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app import __version__

RAIZ = Path(__file__).resolve().parent.parent
WEB = RAIZ / "web"
PANTALLA = (WEB / "js" / "gastos.js").read_text()
COLA = (WEB / "js" / "gastosCola.js").read_text()
CSS = (WEB / "css" / "gastos.css").read_text()
APP = (WEB / "js" / "app.js").read_text()
SW = (WEB / "sw.js").read_text()
INDEX = (WEB / "index.html").read_text()


@pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")
@pytest.mark.parametrize("archivo", ["gastos.js", "gastosCola.js"])
def test_el_js_es_sintaxis_valida(archivo):
    r = subprocess.run(["node", "--check", str(WEB / "js" / archivo)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_la_ruta_existe_y_el_acceso_no_va_en_ajustes():
    assert re.search(r"\^#\\/gastos\$.*viewGastos", APP)
    assert 'location.hash = "#/gastos"' not in APP  # el acceso es el hub Viaje (viaje.js), no Ajustes


def test_la_foto_guardada_se_pide_con_token_y_se_muestra_desde_un_blob():
    assert "src: gasto.foto_url" not in PANTALLA and "href: gasto.foto_url" not in PANTALLA
    assert "mostrarFotoGuardada(gasto.foto_url)" in PANTALLA
    assert "createObjectURL" in PANTALLA and "revokeObjectURL" in PANTALLA


def test_el_sync_parte_en_lotes_de_200_y_usa_el_ahora_del_servidor_como_cursor():
    assert re.search(r"LOTE_SYNC\s*=\s*200", PANTALLA)
    assert "desde = r.ahora" in PANTALLA
    assert "resolverRespuesta" in PANTALLA and "reemplazarPerdido" in COLA


def test_el_export_baja_con_token_como_blob():
    assert '"/api/gastos/export.csv", { raw: true }' in PANTALLA
    assert 'download: "gastos-reintegrables.csv"' in PANTALLA


def test_el_service_worker_y_el_index_cargan_los_archivos_nuevos():
    for ruta in ("/js/gastos.js", "/js/gastosCola.js", "/css/gastos.css"):
        assert f'"{ruta}"' in SW, f"{ruta} falta en el precache"
    assert '<link rel="stylesheet" href="/css/gastos.css">' in INDEX


def test_no_se_toca_la_version_del_service_worker():
    # La versión del service worker sigue a la de la app (app/__init__.py): este cambio no la sube por su cuenta.
    assert f'const VERSION = "reinventar-v{__version__}";' in SW


def test_usa_el_contrato_de_la_api():
    for ruta in ("/api/gastos/cotizacion", "/api/gastos/sync", "/api/gastos/presupuesto", "/api/gastos/export.csv", "/foto"):
        assert ruta in PANTALLA, ruta


def test_el_gasto_nace_con_uuid_en_el_celular():
    assert "crypto.randomUUID()" in PANTALLA + COLA


def test_sincroniza_al_volver_la_red_al_primer_plano_y_cada_60_segundos():
    assert '"online"' in PANTALLA
    assert '"visibilitychange"' in PANTALLA
    assert re.search(r"SYNC_CADA_MS\s*=\s*60_?000", PANTALLA)


def test_la_foto_se_achica_en_el_celular():
    assert "toBlob" in PANTALLA + COLA
    assert "image/jpeg" in PANTALLA + COLA
    assert re.search(r"LADO_MAYOR_PX\s*=\s*1600", COLA)
    assert re.search(r"CALIDAD_JPEG\s*=\s*0\.7", COLA)
    assert 'capture: "environment"' in PANTALLA


def test_la_foto_se_sube_despues_del_gasto():
    # Un gasto todavía pendiente no tiene su foto subida, y las fotos se suben recién al final del sync.
    assert "gasto.pendiente) continue" in PANTALLA
    sync = PANTALLA[PANTALLA.index("async function hacerSync"):]
    assert sync.index('guardarMeta("ultimoSync"') < sync.index("await subirFotos()")


def test_los_toggles_dicen_su_estado_y_tocan_44_px():
    assert PANTALLA.count("aria-pressed") >= 3
    assert "min-height: var(--touch)" in CSS


def test_la_hoja_es_un_dialog_con_titulo_y_los_campos_tienen_label():
    # La hoja es la compartida de ui.js (la usan también las hojas del banner de estado).
    ui = (WEB / "js" / "ui.js").read_text()
    hoja = ui[ui.index("export function Hoja("):]
    assert '"dialog"' in hoja and "aria-labelledby" in hoja
    assert "Hoja(" in PANTALLA and "Hoja," in PANTALLA
    assert PANTALLA.count('"label"') >= 3


def test_los_errores_van_en_castellano_por_mensajeError():
    assert "mensajeError" in PANTALLA


def test_el_dom_se_arma_con_h_y_sin_innerhtml():
    assert "innerHTML" not in PANTALLA + COLA
    assert re.search(r'import \{[^}]*\bh\b[^}]*\} from "\./ui\.js"', PANTALLA)


def test_el_css_usa_tokens_y_no_colores_a_mano():
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", CSS)
    assert not re.search(r"font:\s*\d{3}\s+\d+px", CSS)


def test_la_cola_no_toca_el_dom_para_poder_probarse_con_node():
    assert "document." not in COLA


def test_el_logout_borra_la_base_local_de_gastos():
    logout = APP[APP.index("async function logout()"):]
    logout = logout[:logout.index("location.hash")]
    assert "borrarGastosLocales()" in logout
    assert logout.index('setToken("")') < logout.index("borrarGastosLocales()")
    assert 'import { borrarBaseLocal as borrarGastosLocales } from "./gastosCola.js"' in APP


def test_la_cola_tiene_dueno_y_no_manda_a_la_cuenta_de_otro():
    assert "asegurarDueno()" in PANTALLA
    sync = PANTALLA[PANTALLA.index("async function hacerSync"):]
    assert sync.index("asegurarDueno()") < sync.index("gastosPendientes()")
    assert 'leerMeta("dueno")' in PANTALLA and "decidirDueno" in PANTALLA


def test_el_sync_sigue_mientras_hay_mas_y_tiene_timeout():
    assert "r.hay_mas" in PANTALLA
    assert re.search(r"TIMEOUT_PEDIDO_MS\s*=\s*20_?000", PANTALLA)
    assert "AbortController" in PANTALLA
    assert 'apiConTimeout("/api/gastos/sync"' in PANTALLA
    assert 'api("/api/gastos/sync"' not in PANTALLA


def test_los_rechazados_no_se_reintentan_solos():
    assert "g.pendiente && !g.rechazado" in COLA
    assert "rechazados" in PANTALLA and "is-rechazado" in PANTALLA and ".is-rechazado" in CSS


def test_guardar_dos_veces_no_duplica():
    assert "nuevoId()" in PANTALLA and "id: clientId" in PANTALLA
    assert "botonGuardar.disabled = true" in PANTALLA


def test_no_usa_map_groupby_que_no_existe_en_ios_16():
    assert "groupBy" not in PANTALLA + COLA


def test_la_base_local_se_reabre_si_ios_la_cierra():
    assert "db.onclose" in COLA and "InvalidStateError" in COLA


def test_la_edicion_y_el_sync_van_en_una_transaccion():
    assert "transaccionarGastos" in COLA and "transaccionarGastos" in PANTALLA


def test_el_csv_se_comparte_con_la_hoja_del_sistema_si_se_puede():
    assert "navigator.share" in PANTALLA and "canShare" in PANTALLA
    assert 'download: "gastos-reintegrables.csv"' in PANTALLA  # y si no se puede, la descarga de siempre


def test_con_sesion_vencida_avisa_y_lleva_al_login():
    assert "esSesionVencida" in PANTALLA and 'href: "#/login"' in PANTALLA


def test_la_foto_se_elige_con_botones_y_tambien_de_la_galeria():
    assert 'tabindex: "-1"' not in PANTALLA and '"aria-hidden": "true"' not in PANTALLA
    assert "Elegir de la galería" in PANTALLA
    assert PANTALLA.count('type: "file"') == 2 and PANTALLA.count('capture: "environment"') == 1


def test_muestra_cotizacion_estimada_y_la_antiguedad_de_la_cotizacion():
    assert "cotizacion_estimada" in PANTALLA and "es_respaldo" in PANTALLA and "edadCotizacion" in PANTALLA

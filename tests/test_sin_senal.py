"""Inicio e Itinerario sin señal: el cableado de la última copia buena (la lógica está en tests/js/ultimaCopia.test.mjs)."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def _js(nombre):
    return (WEB / "js" / nombre).read_text()


def test_hoy_itinerario_y_grabaciones_usan_la_ultima_copia():
    api = _js("api.js")
    assert 'list: () => apiConUltimaCopia("/api/sessions")' in api
    assert 'get: () => apiConUltimaCopia("/api/today")' in api
    assert 'get: () => apiConUltimaCopia("/api/itinerary")' in api
    assert 'get: () => apiConUltimaCopia("/api/anuncios")' in api  # «Anuncios sin reserva» de Inicio sin señal
    assert '"/api/anuncios"' in _js("lastgood.js")  # y está en la lista cerrada de rutas que se guardan


def test_sin_senal_lo_avisa_el_banner_global_y_no_cada_pantalla():
    # La franja «Sin señal · datos de las HH:MM» se repetía en Inicio, Hoy e Itinerario: ahora la muestra el banner de
    # estado (estadoBanner.js), que se entera cuando una pantalla cae a la última copia.
    for modulo in ("app.js", "today.js", "itinerary.js", "sinSenal.js", "lastgood.js"):
        codigo = _js(modulo)
        assert not re.search(r"\bSinSenal\(", codigo), modulo  # pintarSinSenal (grabar sin sesión en el servidor) es otra cosa
        assert "hoyNecesitaFranja" not in codigo, modulo
    assert "avisarServicio(EVENTO_SIN_SERVICIO" in _js("api.js")
    assert "addEventListener(EVENTO_SIN_SERVICIO" in _js("estadoBanner.js")


def test_ajustes_no_dice_sesion_no_valida_por_falta_de_red():
    app = _js("app.js")
    assert "cuentaConCopia()" in app
    assert "textoDeCuenta(cuenta)" in app
    assert "try { me = await Auth.me(); } catch {}" not in app  # el catch vacío dejaba {} y salía «Sesión no válida.» sin red
    assert "cuenta.is_admin" in app  # el botón Administración sale también con la copia


def test_tus_grabaciones_sin_datos_sin_senal_no_dice_que_no_grabaste():
    app = _js("app.js")
    assert "textosSinGrabaciones(sessions)" in app
    assert '"Todavía no grabaste ninguna sesión."' not in app  # el texto vive en sinSenal.js


def test_los_modulos_nuevos_estan_en_el_cache_offline():
    sw = (WEB / "sw.js").read_text()
    for modulo in ("lastgood", "sinSenal", "locales", "estado", "estadoBanner", "version", "dia"):
        assert f'"/js/{modulo}.js"' in sw, modulo


def test_inicio_muestra_las_grabaciones_locales_arriba_de_tus_grabaciones():
    app = _js("app.js")
    assert "cargarLocales(store)" in app
    assert "LocalesPendientes(fichas)" in app
    assert app.index("localesSlot,") < app.index('id: "grabaciones-title"')  # arriba de «Tus grabaciones»
    # se cargan antes de pedir la lista al servidor: sin señal ni copia esa falla y las locales igual se ven
    assert app.index("void refreshLocales();") < app.index("const sessions = await Sessions.list();")


def test_el_login_le_deja_el_token_al_service_worker():
    assert 'new Event("reinventar:token")' in _js("api.js")
    assert 'addEventListener("reinventar:token", sync)' in _js("notifications.js")


def test_la_api_nunca_se_cachea_en_el_service_worker():
    sw = (WEB / "sw.js").read_text()
    assert 'url.pathname.startsWith("/api/")' in sw  # el SW la deja pasar: la copia vive en la página

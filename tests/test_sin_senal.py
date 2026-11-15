"""Inicio e Itinerario sin señal: el cableado de la última copia buena (la lógica está en tests/js/ultimaCopia.test.mjs)."""
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def _js(nombre):
    return (WEB / "js" / nombre).read_text()


def test_hoy_itinerario_y_grabaciones_usan_la_ultima_copia():
    api = _js("api.js")
    assert 'list: () => apiConUltimaCopia("/api/sessions")' in api
    assert 'get: () => apiConUltimaCopia("/api/today")' in api
    assert 'get: () => apiConUltimaCopia("/api/itinerary")' in api


def test_las_pantallas_muestran_la_franja_sin_senal():
    assert "SinSenal(sessions)" in _js("app.js")
    assert _js("itinerary.js").count("SinSenal(data)") == 2  # con y sin días armados


def test_los_modulos_nuevos_estan_en_el_cache_offline():
    sw = (WEB / "sw.js").read_text()
    assert '"/js/lastgood.js"' in sw and '"/js/sinSenal.js"' in sw


def test_el_login_le_deja_el_token_al_service_worker():
    assert 'new Event("reinventar:token")' in _js("api.js")
    assert 'addEventListener("reinventar:token", sync)' in _js("notifications.js")


def test_la_api_nunca_se_cachea_en_el_service_worker():
    sw = (WEB / "sw.js").read_text()
    assert 'url.pathname.startsWith("/api/")' in sw  # el SW la deja pasar: la copia vive en la página

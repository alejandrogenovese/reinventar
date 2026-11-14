"""PWA: service worker, notificaciones, fuentes locales y robots (auditoría pre re:Invent)."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
SW = (WEB / "sw.js").read_text()


def test_el_shell_cae_a_la_cache_si_la_red_no_contesta_en_3_segundos():
    assert "const SHELL_TIMEOUT_MS = 3000;" in SW
    assert "Promise.race([sinRed, lenta])" in SW
    assert "e.waitUntil(red.catch" in SW  # la red sigue y actualiza la caché después del timeout


def _shell():
    return set(re.findall(r'"(/[^"]*)"', re.search(r"const SHELL = \[(.*?)\];", SW, re.S).group(1)))


def test_los_iconos_con_version_de_index_y_manifest_estan_precacheados():
    import json

    index = (WEB / "index.html").read_text()
    manifest = json.loads((WEB / "manifest.webmanifest").read_text())
    pedidos = set(re.findall(r'<link rel="(?:icon|apple-touch-icon)" href="(/icons/[^"]+)"', index))
    pedidos |= {i["src"] for i in manifest["icons"]}

    assert pedidos and pedidos <= _shell()


def test_el_sw_re_suscribe_y_manda_la_suscripcion_al_mismo_endpoint_que_la_pagina():
    api = (WEB / "js" / "api.js").read_text()
    assert 'subscribe: (sub) => api("/api/push/subscribe"' in api
    assert 'addEventListener("pushsubscriptionchange"' in SW
    assert '"/api/push/subscribe"' in SW and "applicationServerKey" in SW
    assert "e.oldSubscription" in SW  # da de baja la vieja


def test_el_sw_no_borra_la_cache_de_datos_con_el_token_al_activarse():
    assert 'const DATOS = "sw-datos"' in SW and 'k !== DATOS' in SW
    assert 'const SW_DATOS = "sw-datos"' in (WEB / "js" / "notifications.js").read_text()


def test_notificationclick_solo_navega_ventanas_controladas():
    assert "includeUncontrolled: false" in SW and "includeUncontrolled: true" not in SW
    assert "openWindow(url)" in SW

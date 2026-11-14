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


def test_enable_pide_el_permiso_antes_de_cualquier_await():
    js = (WEB / "js" / "notifications.js").read_text()
    cuerpo = js[js.index("async function enable()"):]
    assert cuerpo.index("Notification.requestPermission()") < cuerpo.index("await Push.key()")
    antes = cuerpo[: cuerpo.index("Notification.requestPermission()")]
    codigo = "\n".join(linea for linea in antes.splitlines() if not linea.strip().startswith("//"))
    previo = codigo.split("{", 1)[1].replace("if (await ", "")  # el await propio de requestPermission no cuenta
    assert "await" not in previo  # nada asíncrono entre el toque y el permiso


FUENTES = {
    "inter": (400, 500, 600, 700, 800),
    "jetbrains-mono": (500, 600),
}
ARCHIVOS_DE_FUENTES = [f"{familia}-latin-{peso}-normal.woff2" for familia, pesos in FUENTES.items() for peso in pesos]


def test_las_fuentes_son_locales_sin_google_fonts():
    index = (WEB / "index.html").read_text()
    tokens = (WEB / "css" / "tokens.css").read_text()
    for texto in (index, SW, tokens, (WEB / "styles.css").read_text()):
        assert "fonts.googleapis.com" not in texto and "fonts.gstatic.com" not in texto
    assert "precacheFonts" not in SW and "FONTS_CSS" not in SW


def test_cada_fuente_tiene_su_font_face_con_swap_y_su_archivo_precacheado():
    tokens = (WEB / "css" / "tokens.css").read_text()
    bloques = re.findall(r"@font-face\s*\{[^}]*\}", tokens)
    locales = [b for b in bloques if "/fonts/" in b]

    assert len(locales) == len(ARCHIVOS_DE_FUENTES)
    assert all("font-display: swap" in b and 'format("woff2")' in b and "unicode-range" in b for b in locales)
    for archivo in ARCHIVOS_DE_FUENTES:
        assert f'url("/fonts/{archivo}")' in tokens
        assert (WEB / "fonts" / archivo).stat().st_size > 10_000
        assert f'"/fonts/{archivo}"' in SW


def test_las_licencias_ofl_viajan_con_las_fuentes():
    for licencia in ("OFL-Inter.txt", "OFL-JetBrainsMono.txt"):
        texto = (WEB / "fonts" / licencia).read_text()
        assert "SIL Open Font License, Version 1.1" in texto


def test_el_backend_sirve_los_woff2_con_su_content_type():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        for archivo in ARCHIVOS_DE_FUENTES:
            r = c.get(f"/fonts/{archivo}")
            assert r.status_code == 200, archivo
            assert r.headers["content-type"] == "font/woff2", archivo
            assert r.content[:4] == b"wOF2"


def test_robots_txt_prohibe_todo_y_el_index_es_noindex():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = c.get("/robots.txt")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert r.text.splitlines()[:2] == ["User-agent: *", "Disallow: /"]
    assert '<meta name="robots" content="noindex">' in (WEB / "index.html").read_text()

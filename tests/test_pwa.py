"""PWA: service worker, notificaciones, fuentes locales y robots (auditoría pre re:Invent)."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
SW = (WEB / "sw.js").read_text()


def test_el_shell_cae_a_la_cache_si_la_red_no_contesta_en_3_segundos():
    assert "const SHELL_TIMEOUT_MS = 3000;" in SW
    assert "Promise.race([sinRed, lenta])" in SW
    assert "e.waitUntil(red.catch" in SW  # la red sigue y actualiza la caché después del timeout

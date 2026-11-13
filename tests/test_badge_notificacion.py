"""El ícono chico de la barra de estado (badge) de Android usa solo la transparencia de la imagen: tiene que ser un
PNG con fondo transparente y el dibujo en blanco, si no se ve como un cuadrado blanco."""
from pathlib import Path

from PIL import Image

WEB = Path(__file__).resolve().parent.parent / "web"


def test_el_service_worker_usa_el_badge_transparente():
    sw = (WEB / "sw.js").read_text()
    assert 'badge: "/icons/badge-96.png"' in sw
    assert '"/icons/badge-96.png",' in sw  # precacheado


def test_el_badge_es_monocromo_con_fondo_transparente():
    img = Image.open(WEB / "icons" / "badge-96.png").convert("RGBA")
    assert img.size == (96, 96)
    assert img.getpixel((0, 0))[3] == 0  # la esquina es transparente
    opacos = [p for p in img.getdata() if p[3] > 0]
    assert opacos and all(p[:3] == (255, 255, 255) for p in opacos if p[3] == 255)

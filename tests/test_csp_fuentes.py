"""La CSP ya no deja cargar tipografías ni estilos de Google Fonts: las fuentes se sirven desde el propio dominio."""
from app import cabeceras


def _directiva(nombre: str) -> str:
    return next(d for d in cabeceras.politica().split("; ") if d.startswith(nombre + " "))


def test_style_src_no_permite_google_fonts():
    assert _directiva("style-src") == "style-src 'self' 'unsafe-inline'"


def test_font_src_solo_permite_el_propio_dominio():
    assert _directiva("font-src") == "font-src 'self'"


def test_la_politica_no_nombra_a_google_fonts():
    politica = cabeceras.politica()

    assert "fonts.googleapis.com" not in politica
    assert "fonts.gstatic.com" not in politica

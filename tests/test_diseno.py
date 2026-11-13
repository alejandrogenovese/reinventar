"""Propuesta visual: tokens, contraste AA, íconos SVG en vez de emojis y los bugs visuales de la auditoría.

No hay navegador en los tests: se verifica el CSS y el JS como texto (lo mismo que sirve la app)."""
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
TOKENS = (WEB / "css" / "tokens.css").read_text()
STYLES = (WEB / "styles.css").read_text()
JS = {p.name: p.read_text() for p in (WEB / "js").glob("*.js")}

AA = 4.5
EMOJIS_DE_UI = ["🟠", "🕒", "📍", "🎉", "📌", "⚠", "🟢", "🟡", "🔴"]


def _bloque(selector: str) -> dict[str, str]:
    """Variables CSS (--nombre: valor) del bloque `selector { ... }` de tokens.css."""
    inicio = TOKENS.index(selector + " {")
    cuerpo = TOKENS[inicio:TOKENS.index("\n  }", inicio)]
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", cuerpo))


CLARO = _bloque(":root")
OSCURO = {**CLARO, **_bloque(':root[data-theme="dark"]')}


def _color(tema: dict[str, str], nombre: str) -> str:
    valor = tema[nombre].strip()
    while valor.startswith("var("):
        valor = tema[valor[4:-1]].strip()
    assert re.fullmatch(r"#[0-9a-f]{6}", valor), f"{nombre} = {valor}"
    return valor


def _luminancia(hex_: str) -> float:
    canales = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contraste(a: str, b: str) -> float:
    la, lb = sorted([_luminancia(a), _luminancia(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _regla(selector: str) -> str:
    """Cuerpo de la primera regla de styles.css que empieza exactamente con `selector {`."""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", STYLES)
    assert m, f"falta la regla {selector}"
    return m.group(1)


# --- tokens -------------------------------------------------------------------------------------------

def test_escala_tipografica_de_seis_pasos():
    esperado = {
        "--t-display": "700 28px/34px", "--t-title": "700 20px/26px", "--t-heading": "600 17px/23px",
        "--t-body": "400 16px/24px", "--t-small": "400 14px/20px", "--t-micro": "600 12px/16px",
    }
    for nombre, valor in esperado.items():
        assert CLARO[nombre].startswith(valor), nombre


def test_radios_y_tamano_de_toque():
    assert (CLARO["--radius-s"], CLARO["--radius-m"], CLARO["--radius-l"]) == ("6px", "12px", "16px")
    assert CLARO["--touch"] == "44px"


def test_en_oscuro_no_hay_sombras():
    assert OSCURO["--shadow-1"] == "none"
    assert OSCURO["--shadow-2"] == "none"


def test_el_evento_usa_info_y_no_el_violeta():
    assert CLARO["--event"] == "var(--info)"
    assert "#8a50f7" not in STYLES + TOKENS


# --- contraste ----------------------------------------------------------------------------------------

PARES = [
    ("--ink-muted", "--surface-1"), ("--ink-muted", "--bg"), ("--ink", "--surface-3"),
    ("--brand-ink", "--brand-soft"), ("--brand-ink", "--surface-1"),
    ("--on-success-soft", "--success-soft"), ("--on-warning-soft", "--warning-soft"),
    ("--on-error-soft", "--error-soft"), ("--on-info-soft", "--info-soft"),
    ("--accent-on-ink", "--ink"),  # acción del toast (Deshacer): el toast tiene fondo --ink
]


@pytest.mark.parametrize("tema", [CLARO, OSCURO], ids=["claro", "oscuro"])
@pytest.mark.parametrize("texto,fondo", PARES)
def test_texto_sobre_fondo_pasa_aa(tema, texto, fondo):
    assert contraste(_color(tema, texto), _color(tema, fondo)) >= AA


def test_ink_muted_tiene_mas_contraste_que_antes():
    assert contraste(_color(CLARO, "--ink-muted"), "#ffffff") > contraste("#6a6a6a", "#ffffff")
    assert contraste(_color(OSCURO, "--ink-muted"), _color(OSCURO, "--surface-1")) > contraste("#a3a3a3", "#1c1c1c")


def test_accion_del_toast_y_pill_listo_usan_los_tokens_aa():
    assert "var(--accent-on-ink)" in _regla(".toast-action")
    listo = _regla(".ra-pill-ready")
    assert "var(--on-success-soft)" in listo and "var(--success-soft)" in listo


# --- bugs visuales de la auditoría --------------------------------------------------------------------

def test_las_pestanas_se_pegan_debajo_del_encabezado_real():
    tabs = _regla(".tabs")
    assert "68px" not in tabs
    assert "var(--masthead-h" in tabs
    assert "--masthead-h" in JS["app.js"]


def test_un_solo_bloque_pegado_arriba():
    index = (WEB / "index.html").read_text()
    assert 'id="masthead"' in index
    assert "sticky" in _regla(".masthead")
    assert "sticky" not in _regla(".topbar")
    assert ".top-banners { position: sticky" not in STYLES


def test_ra_mono_tiene_regla():
    assert "var(--font-data)" in _regla(".ra-mono")


def test_barra_inferior_solida_sin_blur():
    assert "backdrop-filter:" not in STYLES


def test_momentos_del_chat_en_naranja_y_no_en_rojo_de_error():
    assert "var(--rec)" not in _regla(".ra-hit-time")
    assert "var(--brand-ink)" in _regla(".ra-cite.ra-moment-ref")


def test_pildora_de_filtro_de_44px():
    assert "var(--touch)" in _regla("button.ra-chip, .chipgroup label")


# --- íconos -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("nombre,codigo", sorted(JS.items()))
def test_sin_emojis_como_iconos(nombre, codigo):
    usados = [e for e in EMOJIS_DE_UI if e in codigo]
    assert not usados, f"{nombre} usa {usados}"


def test_cada_icono_usado_esta_definido():
    definidos = set(re.findall(r"^  (\w+): \"", JS["icons.js"], re.M))
    usados = set()
    for codigo in JS.values():
        usados |= set(re.findall(r"\bicon\(\"(\w+)\"", codigo))
        usados |= set(re.findall(r"\bIconText\(\"(\w+)\"", codigo))
    hint = re.search(r"const HINT_ICON = \{([^}]*)\}", JS["ui.js"]).group(1)
    usados |= set(re.findall(r"\"(\w+)\"", hint))
    assert usados - definidos == set()
    assert {"ubicacion", "reloj", "caminar", "alerta", "fijar", "llevar", "reproducir", "agregar", "cerrar"} <= definidos


def test_el_service_worker_precachea_los_archivos_del_diseno():
    sw = (WEB / "sw.js").read_text()
    for archivo in ("/css/tokens.css", "/css/base.css", "/styles.css", "/js/icons.js", "/js/ui.js"):
        assert f'"{archivo}"' in sw

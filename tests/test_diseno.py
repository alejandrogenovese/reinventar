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


CSS = re.sub(r"/\*.*?\*/", "", STYLES, flags=re.S)  # sin comentarios: pueden traer llaves o selectores de ejemplo


def _reglas() -> list[tuple[str, str]]:
    """(selector, cuerpo) de cada regla de styles.css, incluidas las que están dentro de @media."""
    return [(sel.strip(), cuerpo) for sel, cuerpo in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS)]


def _regla(selector: str) -> str:
    """Cuerpos (unidos, en orden) de las reglas cuyo selector es exactamente `selector`, no `.x selector` ni `selector.y`."""
    cuerpos = [cuerpo for sel, cuerpo in _reglas() if sel == selector]
    assert cuerpos, f"falta la regla {selector}"
    return "\n".join(cuerpos)


def _token(selector: str, propiedad: str) -> str:
    """Token de `propiedad` (color o background) en las reglas de `selector`; gana la última declaración, como en la cascada."""
    valores = re.findall(rf"(?<![-\w]){propiedad}:\s*var\((--[\w-]+)\)", _regla(selector))
    assert valores, f"{selector} no toma {propiedad} de un token"
    return valores[-1]


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

# Pares texto/fondo tal como los declara styles.css: (regla del texto, regla del fondo o token del fondo).
# Si una regla cambia de token, el test mide el par nuevo y no uno supuesto.
PARES_USADOS = [
    (".label", "--bg"), (".label", "--surface-1"),
    (".toast", ".toast"), (".toast-action", ".toast"),  # Deshacer sobre el fondo del toast
    (".ra-tag", ".ra-tag"), (".ra-tag.is-new", ".ra-tag.is-new"),
    (".countdown-banner", ".countdown-banner.is-soon"),  # el texto lo hereda de la franja base
    (".countdown-banner.is-urgent", ".countdown-banner.is-urgent"),
    (".countdown-banner.is-event", ".countdown-banner.is-event"),
    (".countdown-banner.is-live", ".countdown-banner.is-live"),
    (".ra-chip-on, .chipgroup input:checked + label", ".ra-chip-on, .chipgroup input:checked + label"),
    (".ra-pill-recording", ".ra-pill-recording"),
    (".ra-pill-uploading, .ra-pill-queued", ".ra-pill-uploading, .ra-pill-queued"),
    (".ra-pill-transcribing, .ra-pill-translating, .ra-pill-summarizing",
     ".ra-pill-transcribing, .ra-pill-translating, .ra-pill-summarizing"),
    (".ra-pill-ready", ".ra-pill-ready"), (".ra-pill-error", ".ra-pill-error"),
    (".ra-hint", ".ra-hint"), (".ra-hint.is-warn", ".ra-hint.is-warn"),
    (".ra-hint.is-error", ".ra-hint.is-error"), (".ra-hint.is-info", ".ra-hint.is-info"),
    (".ra-cite", ".ra-cite"), (".ra-cite.ra-moment-ref", ".ra-cite.ra-moment-ref"), (".ra-hit-time", ".ra-hit-time"),
    (".ra-check-list .is-ok strong", "--surface-1"), (".ra-check-list .is-fail strong", "--surface-1"),
]


@pytest.mark.parametrize("tema", [CLARO, OSCURO], ids=["claro", "oscuro"])
@pytest.mark.parametrize("texto,fondo", PARES_USADOS, ids=[f"{t} sobre {f}" for t, f in PARES_USADOS])
def test_texto_sobre_fondo_pasa_aa(tema, texto, fondo):
    color = _token(texto, "color")
    fondo_token = fondo if fondo.startswith("--") else _token(fondo, "background")
    ratio = contraste(_color(tema, color), _color(tema, fondo_token))
    assert ratio >= AA, f"{color} sobre {fondo_token}: {ratio:.2f}:1"


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
    pegadas = {sel for sel, cuerpo in _reglas() if re.search(r"position:\s*sticky", cuerpo)}
    # el encabezado (franjas + barra) y las pestañas, que se pegan debajo de él
    assert pegadas == {".masthead", ".tabs"}


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


def _primer_argumento(codigo: str, abre: int) -> str:
    """Texto del primer argumento de la llamada cuyo paréntesis abre en `abre` (respeta paréntesis y comillas)."""
    nivel, comilla = 0, None
    for i in range(abre + 1, len(codigo)):
        c = codigo[i]
        if comilla:
            comilla = None if c == comilla and codigo[i - 1] != "\\" else comilla
        elif c in "\"'`":
            comilla = c
        elif c in "([{":
            nivel += 1
        elif c in ")]}" and nivel:
            nivel -= 1
        elif c in ",)" and not nivel:
            return codigo[abre + 1:i].strip()
    raise AssertionError("llamada sin cerrar")


def _literales_de_icono(expr: str) -> set[str]:
    """Strings de la expresión que pueden ser el nombre: las ramas de un ternario, no lo que se compara (=== "event")."""
    return {nombre for op, nombre in re.findall(r"([!=]==?\s*)?\"(\w+)\"", expr) if not op}


def _primeros_de(objeto: str, codigo: str) -> set[str]:
    """Primer elemento de cada arreglo de `const OBJETO = { clave: ["nombre", ...] }`."""
    cuerpo = re.search(rf"const {objeto} = \{{(.*?)\}};", codigo).group(1)
    return set(re.findall(r"\[\s*\"(\w+)\"", cuerpo))


def _iconos_dinamicos() -> dict[str, set[str]]:
    """Para cada argumento no literal de icon()/IconText(), los nombres que puede tomar."""
    todo = "\n".join(JS.values())
    hint = set(re.findall(r"\"(\w+)\"", re.search(r"const HINT_ICON = \{([^}]*)\}", JS["ui.js"]).group(1)))
    tema = re.search(r"const next = ([^;]+);", JS["app.js"]).group(1)
    kind = _primeros_de("KIND_ICON", JS["today.js"])
    return {
        "slot.dataset.icon": set(re.findall(r'data-icon="(\w+)"', (WEB / "index.html").read_text())),
        "next": _literales_de_icono(tema),
        "iconName": hint | set(re.findall(r"\biconName:\s*\"(\w+)\"", todo)),  # Hint: por tono o explícito
        "name": set(),  # dentro de IconText: sus llamadas se revisan una por una
        "...KIND_ICON[s.kind]": kind, "KIND_ICON[s.kind][0]": kind,
    }


def test_cada_icono_usado_esta_definido():
    definidos = set(re.findall(r"^  (\w+): \"", JS["icons.js"], re.M))
    dinamicos = _iconos_dinamicos()
    usados, sin_resolver = set(), []
    for archivo, codigo in JS.items():
        for m in re.finditer(r"(?<!function )\b(?:icon|IconText)\(", codigo):
            expr = _primer_argumento(codigo, m.end() - 1)
            literales = _literales_de_icono(expr)
            if literales:
                usados |= literales
            elif expr in dinamicos:
                usados |= dinamicos[expr]
            else:
                sin_resolver.append(f"{archivo}: {expr}")
    assert not sin_resolver, f"ícono con nombre dinámico que el test no sabe resolver: {sin_resolver}"
    assert {"reloj", "eventos", "fijar", "claro", "oscuro", "caminar", "alerta"} <= usados  # countdown, tema y Hint
    assert usados - definidos == set()
    assert {"ubicacion", "reloj", "caminar", "alerta", "fijar", "llevar", "reproducir", "agregar", "cerrar",
            "listo", "externo"} <= definidos


GLIFOS_DE_UI = ["✕", "✓", "✗", "＋", "↗"]


@pytest.mark.parametrize("nombre,codigo", sorted(JS.items()))
def test_sin_glifos_como_iconos(nombre, codigo):
    # ✕ ✓ ＋ ↗ como texto de botón se ven distintos en cada sistema y el lector los lee raro: van con icon().
    sin_comentarios = re.sub(r"/\*.*?\*/|//[^\n]*", "", codigo, flags=re.S)
    usados = [g for g in GLIFOS_DE_UI if g in sin_comentarios]
    assert not usados, f"{nombre} usa {usados}"


def _modulos_del_arranque() -> set[str]:
    """Módulos que carga app.js, recorriendo sus imports estáticos."""
    vistos, pendientes = set(), ["app.js"]
    while pendientes:
        archivo = pendientes.pop()
        if archivo in vistos:
            continue
        vistos.add(archivo)
        pendientes += re.findall(r"""^(?:import|export)\b[^;]*?\bfrom\s*["']\./([\w.]+)["']""", JS[archivo], re.M)
    return vistos


def test_el_service_worker_precachea_todo_el_shell():
    sw = (WEB / "sw.js").read_text()
    shell = set(re.findall(r'"(/[^"]*)"', re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1)))
    index = (WEB / "index.html").read_text()
    estilos = set(re.findall(r'<link rel="stylesheet" href="(/[^"?]+)"', index))
    modulos = {f"/js/{m}" for m in _modulos_del_arranque()}
    assert {"/css/tokens.css", "/css/base.css", "/styles.css"} <= estilos
    assert {"/js/countdown.js", "/js/notifications.js", "/js/adminLlm.js"} <= modulos  # el recorrido llega lejos
    assert (estilos | modulos) - shell == set()


def test_sin_tamanos_ni_radios_fuera_de_la_escala():
    # La letra sale de los 6 pasos (y --t-time / --t-data); los radios, de 6/12/16/pill. Solo quedan
    # los detalles de 2-3 px de barritas y del glifo de stop.
    assert re.findall(r"font:\s*\d{3}\s+\d+px", CSS) == []
    radios = [int(px) for valor in re.findall(r"border-radius:\s*([^;}]+)", CSS) for px in re.findall(r"(\d+)px", valor)]
    assert all(px <= 3 for px in radios), radios


def test_hint_de_info_con_su_tinte():
    regla = _regla(".ra-hint.is-info")
    assert "var(--info-soft)" in regla and "var(--on-info-soft)" in regla
    assert 'class: `ra-hint is-${tone}`' in JS["ui.js"]


def test_la_seccion_hoy_se_nombra_con_la_fecha():
    assert '"aria-labelledby": "hoy-title hoy-fecha"' in JS["today.js"]
    assert 'id: "hoy-fecha"' in JS["today.js"]


def test_tarjeta_compacta_dice_nivel():
    compacta = JS["itinerary.js"][JS["itinerary.js"].index("function CompactCard"):]
    assert "`Nivel ${s.level}`" in compacta[:compacta.index("\n}\n")]

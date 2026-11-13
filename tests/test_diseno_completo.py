"""Lo que faltaba del mock aprobado: barra y menú ⋯ del detalle, campo fijo del chat, "Nueva" y "Llevame" en Inicio y
Filtros dentro del campo de Buscar. Como en test_diseno.py, se verifica el CSS y el JS como texto; `clock` se corre
con node si está instalado."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
STYLES = re.sub(r"/\*.*?\*/", "", (WEB / "styles.css").read_text(), flags=re.S)
INDEX = (WEB / "index.html").read_text()
JS = {p.name: p.read_text() for p in (WEB / "js").glob("*.js")}


def _regla(selector: str) -> str:
    cuerpos = [c for s, c in re.findall(r"([^{}]+)\{([^{}]*)\}", STYLES) if s.strip() == selector]
    assert cuerpos, f"falta la regla {selector}"
    return "\n".join(cuerpos)


def _funcion(archivo: str, nombre: str) -> str:
    """Cuerpo aproximado de una función: desde su firma hasta la próxima función de primer nivel."""
    codigo = JS[archivo]
    inicio = re.search(rf"^(?:export )?(?:async )?function {nombre}\(", codigo, re.M).start()
    fin = re.search(r"^(?:export )?(?:async )?function ", codigo[inicio + 1:], re.M)
    return codigo[inicio:inicio + 1 + fin.start()] if fin else codigo[inicio:]


# --- detalle: barra de arriba y menú ⋯ --------------------------------------------------------------------

def test_el_detalle_tiene_barra_con_volver():
    assert 'id="pagebar"' in INDEX
    detalle = JS["detail.js"]
    assert '"aria-label": "Volver"' in detalle and 'icon("volver", 24)' in detalle
    assert "history.back()" in detalle
    # el router la vacía en cada navegación y el detalle salió de app.js
    assert "clearPageBar()" in JS["app.js"]
    assert "async function viewDetail" not in JS["app.js"]


def test_la_barra_reemplaza_logo_tema_y_ajustes():
    assert "display: none" in _regla(".has-pagebar .topbar > .brand, .has-pagebar .topbar > .toolbar")


def test_exportar_y_eliminar_van_en_el_menu_y_eliminar_confirma():
    detalle = JS["detail.js"]
    assert 'MenuButton({ label: "Más acciones", items })' in detalle
    assert 'label: "Exportar .md"' in detalle and 'label: "Eliminar"' in detalle and "danger: true" in detalle
    assert 'Button("Exportar .md"' not in detalle and 'Button("Eliminar"' not in detalle
    assert 'confirmDialog("¿Eliminar la sesión?"' in _funcion("detail.js", "viewDetail")


def test_compartir_solo_si_el_navegador_comparte_archivos():
    detalle = JS["detail.js"]
    assert "navigator.canShare?.({ files:" in detalle
    assert "ready && canShareFiles()" in detalle
    # si compartir falla (y no es que el usuario canceló), se descarga
    assert 'e?.name !== "AbortError"' in detalle


def test_menu_accesible():
    menu = JS["menu.js"]
    for atributo in ('"aria-haspopup": "menu"', '"aria-expanded": "false"', 'role: "menu"', 'role: "menuitem"', '"aria-controls"'):
        assert atributo in menu, atributo
    assert 'e.key === "Escape"' in menu and "close({ refocus: true })" in menu and "trigger.focus()" in menu
    assert 'addEventListener("pointerdown", onOutside, true)' in menu  # tocar afuera cierra
    assert 'removeEventListener("pointerdown", onOutside, true)' in menu
    assert "ArrowDown" in menu and "ArrowUp" in menu
    assert "display: none" in _regla(".ra-menu[hidden]")
    assert "var(--touch)" in _regla(".ra-menu-item")


def test_ficha_de_la_charla_como_link_con_chevron_y_fila_de_estado():
    detalle = JS["detail.js"]
    assert '"Ver la ficha de la charla"' in detalle and 'icon("seguir", 16)' in detalle
    meta = _funcion("detail.js", "MetaRow")
    assert "StatusPill(s.status" in meta and "clock(s.duration_s)" in meta
    assert "flex-wrap: wrap" in _regla(".ra-detail-meta")


def test_desde_la_busqueda_con_la_consulta_y_franja_de_borde_a_borde():
    assert '?q=${encodeURIComponent(q)}' in JS["grabado.js"]
    assert r"(?:\?q=([^&#]*))?" in JS["app.js"]
    assert "Desde la búsqueda «${q}»" in JS["detail.js"]
    hit = _regla(".ra-tb.is-hit")
    assert "var(--brand-soft)" in hit and "calc(-1 * var(--space-4))" in hit and "animation" not in hit


# --- chat: campo fijo abajo -----------------------------------------------------------------------------

def test_el_campo_del_chat_queda_fijo_sobre_la_navegacion():
    composer = _regla(".ra-composer")
    assert "position: fixed" in composer
    assert "bottom: max(var(--kb, 0px), var(--nav-h))" in composer
    assert "--nav-h: calc(65px + env(safe-area-inset-bottom))" in STYLES  # la barra inferior con el safe-area
    assert "var(--composer-h" in _regla(".app:has(.ra-composer)")  # no tapa la última respuesta


def test_boton_de_enviar_de_44px_con_nombre():
    envio = _regla(".ra-send")
    assert "width: var(--touch)" in envio and "height: var(--touch)" in envio
    assert '"aria-label": "Enviar pregunta"' in JS["ask.js"] and 'icon("enviar", 20)' in JS["ask.js"]


def test_el_campo_sigue_al_teclado_y_se_suelta_al_salir():
    ask, buscar = JS["ask.js"], JS["search.js"]
    assert "window.visualViewport" in ask and '"--kb"' in ask and '"--composer-h"' in ask
    assert "ask.attach()" in buscar and "ask?.detach()" in buscar


def test_la_conversacion_va_de_la_mas_vieja_a_la_mas_nueva():
    assert "history = [...history, { q, result }].slice(-HISTORY_LIMIT)" in JS["ask.js"]


# --- inicio --------------------------------------------------------------------------------------------

def test_nueva_es_la_accion_del_encabezado_de_grabaciones():
    app = JS["app.js"]
    assert '"Nueva sesión"' not in _funcion("app.js", "viewList")
    assert 'icon("agregar", 16), h("span", {}, "Nueva")' in app
    assert '"Tus grabaciones"), newBtn)' in app


def test_llevame_es_un_boton_de_solo_icono_de_48px():
    assert "iconOnly: true" in JS["today.js"]
    assert '"aria-label": label' in JS["location.js"] and "iconOnly ? null : \"Llevame\"" in JS["location.js"]
    icono = _regla(".ra-btn-icon")
    assert "width: 48px" in icono and "padding: 0" in icono
    assert "ra-today-actions" in JS["today.js"]


# --- buscar › filtrar ------------------------------------------------------------------------------------

def test_filtros_dentro_del_campo_con_contador():
    explora = JS["explore.js"]
    assert 'h("div", { class: "ra-searchfield" }, icon("buscar", 20), qInput, filterBtn)' in explora
    assert "`Filtros, ${plural(n, \"activo\", \"activos\")}`" in explora
    assert 'class: "ra-badge", "aria-hidden": "true"' in explora
    assert "position: absolute" in _regla(".ra-badge")


def test_convertir_en_filtros_aparece_solo_con_texto():
    explora = JS["explore.js"]
    assert 'class: "ra-suggest", hidden: !state.q' in explora
    assert "nlButton.hidden = !text;" in explora
    assert "display: none" in _regla(".ra-suggest[hidden]")


def test_buscar_sigue_con_la_tarjeta_completa():
    # Excepción del usuario al mock: la tarjeta de charla en Filtrar no se compacta.
    assert "Cards = (rows) => rows.map((s) => SessionMiniCard(s, { onAdd: addToItinerary(s.code) }))" in JS["explore.js"]


# --- minutos cortos como en el mock (58:12, 1:52:10) ----------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="sin node")
def test_clock_corta_los_ceros_de_la_hora():
    script = (
        f"const {{ clock }} = await import({json.dumps((WEB / 'js' / 'ui.js').as_uri())});"
        "console.log(JSON.stringify([0, 59, 3492, 6730, 36000].map(clock)));"
    )
    salida = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(salida) == ["00:00", "00:59", "58:12", "1:52:10", "10:00:00"]

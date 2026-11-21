"""Textos de la UI: ningún mensaje técnico en inglés del navegador (TypeError «Load failed», DOMException
«NotAllowedError», etc.) le llega al usuario. Todo error que se muestra pasa por mensajeError() (web/js/ui.js), que deja
pasar los mensajes de ApiError y los propios de la app y cambia el resto por un texto en castellano."""
import re
from pathlib import Path

WEB_JS = Path(__file__).resolve().parent.parent / "web" / "js"

# Archivos que se excluyen del barrido: ninguno. La grabación ya pasa por mensajeError y api.js lanza ApiError en castellano.
DE_OTROS = set()
# Funciones de app.js que se excluyen del barrido (ninguna: la grabación ya pasa por mensajeError).
FUNCIONES_DE_GRABACION = ()
# Detalle técnico a propósito: el diagnóstico del admin muestra el error crudo para poder arreglarlo.
TECNICO_A_PROPOSITO = {("adminEstado.js", "detail:"), ("ui.js", "esPropio")}  # ui.js: la definición de mensajeError

MENSAJE_CRUDO = re.compile(r"\b(?:err|e|error)\??\.message\b|\breason\??\.message\b")


def _sin_funciones(codigo: str, inicios: tuple[str, ...]) -> str:
    for inicio in inicios:
        desde = codigo.index(inicio)
        hasta = codigo.index("\n}\n", desde) + 3
        codigo = codigo[:desde] + codigo[hasta:]
    return codigo


def _lineas_con_mensaje_crudo(nombre: str) -> list[str]:
    codigo = (WEB_JS / nombre).read_text(encoding="utf-8")
    if nombre == "app.js":
        codigo = _sin_funciones(codigo, FUNCIONES_DE_GRABACION)
    crudas = []
    for numero, linea in enumerate(codigo.splitlines(), 1):
        if not MENSAJE_CRUDO.search(linea) or "mensajeError(" in linea:
            continue
        if any(nombre == archivo and marca in linea for archivo, marca in TECNICO_A_PROPOSITO):
            continue
        crudas.append(f"{nombre}:{numero}: {linea.strip()[:140]}")
    return crudas


def test_ninguna_pantalla_muestra_err_message_crudo():
    archivos = sorted(p.name for p in WEB_JS.glob("*.js") if p.name not in DE_OTROS)
    crudas = [linea for nombre in archivos for linea in _lineas_con_mensaje_crudo(nombre)]

    assert not crudas, "Estos mensajes pueden llegar en inglés al usuario; usá mensajeError(err):\n" + "\n".join(crudas)


# El DOM nativo (a diferencia de h() de ui.js, que descarta null) pinta «null» o «undefined» como texto.
SUMIDERO_NATIVO_CON_NULL = re.compile(
    r"\.(?:append|prepend|replaceChildren|before|after)\([^;\n]*(?:\?[^;\n]*:\s*(?:null|undefined)\b|\b(?:null|undefined)\s*[,)])")


def test_el_dom_nativo_no_recibe_null_ni_undefined():
    sospechosas = []
    for archivo in sorted(WEB_JS.glob("*.js")):
        if archivo.name in DE_OTROS:
            continue
        for numero, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), 1):
            if SUMIDERO_NATIVO_CON_NULL.search(linea) and 'h("' not in linea:
                sospechosas.append(f"{archivo.name}:{numero}: {linea.strip()[:140]}")

    assert not sospechosas, "replaceChildren/append con null pintan «null» en pantalla:\n" + "\n".join(sospechosas)


def test_mensajeerror_existe_y_toastonerror_lo_usa():
    ui = (WEB_JS / "ui.js").read_text(encoding="utf-8")

    assert "export function mensajeError(" in ui
    assert "toast(mensajeError(err))" in ui


def test_el_microfono_tiene_textos_propios_en_castellano_por_tipo_de_error():
    # getUserMedia falla con DOMException en inglés: la pantalla de grabar los traduce por e.name.
    app = (WEB_JS / "app.js").read_text(encoding="utf-8")

    assert 'NotAllowedError: "Necesito permiso para usar el micrófono."' in app
    assert 'NotFoundError: "No encuentro ningún micrófono."' in app
    assert "MSG_MICROFONO[e.name]" in app

"""La pantalla de grabar no puede usar un `const` antes de declararlo (ReferenceError al abrirla)."""
from pathlib import Path

APP_JS = Path(__file__).resolve().parent.parent / "web" / "js" / "app.js"


def _cuerpo_de_view_record() -> str:
    codigo = APP_JS.read_text(encoding="utf-8")
    inicio = codigo.index("async function viewRecord(")
    return codigo[inicio:codigo.index("\n}\n", inicio)]


def test_silence_se_declara_una_vez_y_antes_de_usarse_en_la_pantalla_de_grabar():
    cuerpo = _cuerpo_de_view_record()
    assert cuerpo.count("const silence =") == 1
    declaracion = cuerpo.index("const silence =") + len("const ")  # posición del nombre en su declaración
    assert declaracion == cuerpo.index("silence"), "silence se usa antes de su const (TDZ)"
    assert cuerpo.index("const silence =") < cuerpo.index("view.append(")


def test_el_estado_de_subida_no_le_pasa_null_al_dom():
    # replaceChildren(null) escribe el texto «null» en pantalla (se veía al lado de «Todo subido»).
    cuerpo = _cuerpo_de_view_record()
    inicio = cuerpo.index("upl.replaceChildren(")
    llamada = cuerpo[inicio:cuerpo.index(";", inicio)]
    assert "null" not in llamada

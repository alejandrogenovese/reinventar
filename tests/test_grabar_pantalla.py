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


def test_el_boton_de_grabar_espera_al_microfono():
    # «Listo para grabar» y el botón no pueden aparecer antes de que termine openMic: tocar en esa ventana
    # daba «Primero abrí el micrófono». Mientras no haya rec.stream queda deshabilitado.
    cuerpo = _cuerpo_de_view_record()
    assert "Abriendo el micrófono…" in cuerpo
    assert "!rec.stream" in cuerpo
    assert "disabled" in cuerpo[cuerpo.index("const paint ="):cuerpo.index("rec.addEventListener(\"state\"")]
    assert cuerpo.index("const paint =") < cuerpo.index("await openMic(pref")


def test_si_falla_el_microfono_el_boton_queda_deshabilitado_con_el_error():
    cuerpo = _cuerpo_de_view_record()
    inicio = cuerpo.index("async function openMic(")
    openmic = cuerpo[inicio:cuerpo.index("micSelect.addEventListener", inicio)]
    assert "micError" in openmic and "paint()" in openmic


def test_toggle_no_arranca_sin_microfono():
    cuerpo = _cuerpo_de_view_record()
    inicio = cuerpo.index("function toggle(")
    assert "rec.stream" in cuerpo[inicio:cuerpo.index("rec.start()", inicio)]


def test_al_terminar_el_estado_no_vuelve_a_decir_listo_para_grabar_ni_abriendo_el_microfono():
    # Tras «Terminar» se cierra el micrófono (rec.stream = null): sin una marca propia, paint() diría «Abriendo el micrófono…».
    cuerpo = _cuerpo_de_view_record()
    paint = cuerpo[cuerpo.index("const paint ="):cuerpo.index("rec.addEventListener(\"state\"")]
    assert "terminando" in paint
    assert "textosTerminar(" in cuerpo


def test_terminar_sin_red_se_vuelve_a_pintar_mientras_espera():
    cuerpo = _cuerpo_de_view_record()
    inicio = cuerpo.index("async function finish(")
    finish = cuerpo[inicio:cuerpo.index("async function discard(", inicio)]
    assert "navigator.onLine" in cuerpo and "pintarTerminando" in finish
    assert "Esperando que termine de subir…" in cuerpo  # con señal, el texto de siempre


def test_record_button_acepta_deshabilitado_y_etiqueta():
    ui = (APP_JS.parent / "ui.js").read_text(encoding="utf-8")
    inicio = ui.index("export function RecordButton(")
    firma = ui[inicio:ui.index("\n", inicio)]
    assert "disabled" in firma and "label" in firma

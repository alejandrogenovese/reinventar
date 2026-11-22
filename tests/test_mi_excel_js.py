"""«Mis códigos de Excel» (web/js/miExcel.js): se verifica el JS como texto, igual que test_replace_children.py."""
from pathlib import Path

JS = (Path(__file__).resolve().parent.parent / "web" / "js" / "miExcel.js").read_text(encoding="utf-8")


def test_pide_confirmacion_antes_de_borrar_la_lista():
    assert "confirmDialog" in JS
    antes_de_borrar = JS.split("Codigos.borrar()")[0]
    assert "await confirmDialog(" in antes_de_borrar.rsplit("const borrar", 1)[1]


def test_una_respuesta_tardia_no_pisa_otra_pantalla():
    assert "view.isConnected" in JS
    assert JS.count("view.isConnected") >= 3  # carga inicial, subida y borrado


def test_avisa_de_los_codigos_descartados():
    assert "codigos_descartados" in JS


def test_ofrece_bajar_el_excel_de_ejemplo_con_el_token():
    assert "Bajar un Excel de ejemplo" in JS
    # Con api() (lleva el header Authorization) y como blob: un <a href> directo a la ruta daría 401.
    assert 'api("/api/codigos/ejemplo.xlsx", { raw: true })' in JS
    assert "URL.createObjectURL" in JS and "download: EJEMPLO" in JS
    assert "completá la columna Código" in JS

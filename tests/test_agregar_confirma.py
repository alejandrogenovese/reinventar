"""El botón Agregar confirma: queda en naranja como «Agregada», no vuelve a agregar y otro toque la quita. En la ficha
de la charla, un horario que ya está en tu itinerario se puede quitar. Como test_diseno.py, se verifica el JS como texto."""
import re
from pathlib import Path

JS = {p.name: p.read_text() for p in (Path(__file__).resolve().parent.parent / "web" / "js").glob("*.js")}


def _funcion(archivo: str, nombre: str) -> str:
    texto = JS[archivo]
    inicio = texto.index(f"function {nombre}(")
    fin = re.search(r"\n(export )?(async )?function |\nconst |\nlet ", texto[inicio + 1:])
    return texto[inicio:inicio + 1 + fin.start()] if fin else texto[inicio:]


def test_la_tarjeta_usa_el_boton_que_confirma():
    tarjeta = _funcion("itinerary.js", "SessionMiniCard")
    assert "AddButton(s.code, onAdd)" in tarjeta
    assert 'Button("Agregar"' not in tarjeta


def test_agregada_queda_en_naranja_y_el_segundo_toque_la_quita():
    boton = _funcion("itinerary.js", "AddButton")
    assert '"Agregada"' in boton and '"ra-btn-primary", added' in boton  # naranja = variante primaria (marca)
    assert "aria-pressed" in boton
    assert "Itinerary.remove(code)" in boton and "Quitada del itinerario." in boton
    assert "btn.disabled = true" in boton  # sin doble agregado mientras viaja el pedido
    assert "itineraryCodes()" in boton  # arranca como «Agregada» si ya estaba


def test_si_falla_el_agregado_no_queda_marcada():
    assert "await onAdd() !== false" in _funcion("itinerary.js", "AddButton")
    for archivo in ("explore.js", "ask.js", "knowledge.js"):
        assert "toast(e.message); return false;" in JS[archivo], archivo


def test_en_la_ficha_un_horario_agregado_se_puede_quitar():
    horario = _funcion("knowledge.js", "Slot")
    assert '"En tu itinerario"' in horario and 'Button("Quitar"' in horario
    assert "Itinerary.remove(i.code)" in horario

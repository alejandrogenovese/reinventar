"""Navegación del hub Viaje: Documentos de viaje en la lista y la pestaña Viaje marcada también en Actividades."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
VIAJE = (WEB / "js" / "viaje.js").read_text()
INDEX = (WEB / "index.html").read_text()


def test_documentos_de_viaje_esta_en_el_hub():
    assert '{ href: "#/viajes/documentos"' in VIAJE
    assert 'titulo: "Documentos de viaje", bajada: "Pasaporte, ESTA, seguro y reservas, también sin señal"' in VIAJE


def test_la_pestana_viaje_queda_marcada_en_actividades():
    patron = re.search(r'href="#/viaje" data-match="([^"]+)"', INDEX).group(1)
    for ruta in ("#/viaje", "#/viajes/documentos", "#/comer", "#/gastos", "#/ofertas", "#/actividades"):
        assert re.search(patron, ruta), ruta
    assert not re.search(patron, "#/itinerario")

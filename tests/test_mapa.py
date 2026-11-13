"""Mapa del itinerario: con un solo lugar no tiene que quedar con el zoom al máximo (adentro del edificio, sin calles)."""
import re
from pathlib import Path

MAP_JS = (Path(__file__).parents[1] / "web" / "js" / "map.js").read_text(encoding="utf-8")


def test_despues_de_encuadrar_se_topa_el_zoom():
    tope = int(re.search(r"const ZOOM_MAXIMO = (\d+);", MAP_JS).group(1))

    assert 14 <= tope <= 17  # se ven las calles y los hoteles vecinos
    assert re.search(r"fitBounds\(bounds.*?addListenerOnce\(map, \"idle\".*?setZoom\(ZOOM_MAXIMO\)", MAP_JS, re.S)

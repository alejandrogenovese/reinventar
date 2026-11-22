"""Búsqueda de ciudades de salida (app/ciudades.py, datos de GeoNames)."""
import pytest

from app import ciudades


def primera(q: str) -> tuple[str, str, str]:
    c = ciudades.buscar(q)[0]
    return c["nombre"], c["pais"], c["zona"]


@pytest.mark.parametrize(("consulta", "esperada"), [
    ("hou", ("Houston", "US", "America/Chicago")),
    ("Houston", ("Houston", "US", "America/Chicago")),
    ("nueva york", ("New York City", "US", "America/New_York")),
    ("san pablo", ("São Paulo", "BR", "America/Sao_Paulo")),
    ("sao paulo", ("São Paulo", "BR", "America/Sao_Paulo")),
    ("SÃO PAULO", ("São Paulo", "BR", "America/Sao_Paulo")),
    ("londres", ("London", "GB", "Europe/London")),
    ("buenos", ("Buenos Aires", "AR", "America/Argentina/Buenos_Aires")),
    ("las veg", ("Las Vegas", "US", "America/Los_Angeles")),
])
def test_encuentra_la_ciudad_que_se_esta_escribiendo(consulta, esperada):
    assert primera(consulta) == esperada


def test_sin_texto_no_devuelve_nada():
    assert ciudades.buscar("   ") == []


def test_devuelve_como_maximo_el_limite():
    assert len(ciudades.buscar("san")) == ciudades.LIMITE


def test_las_zonas_son_validas_para_los_vuelos():
    from app import vuelos

    assert all(vuelos.zona_valida(c["zona"]) for c in ciudades.buscar("san"))


def test_nombre_de_zona_para_vuelos_viejos():
    assert ciudades.nombre_de_zona("America/Argentina/Buenos_Aires") == "Buenos Aires"

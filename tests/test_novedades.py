"""Novedades: parseo del CHANGELOG.md real del repo (app/novedades.py) y GET /api/novedades."""
import pytest
from fastapi.testclient import TestClient

from app import __version__, novedades
from app.main import app
from tests.conftest import login_headers

CHANGELOG_ARMADO = """# Changelog

## [Sin publicar]

### Agregado
- **No publicado.** No tiene que aparecer.

## [2.0.0] - 2026-12-01

Párrafo de presentación que no es un ítem.

### Agregado
- **Uno.** Con un [link](https://example.com) y `código`,
  en dos líneas.
- Sin título en negrita.
- **Tres.** a
- **Cuatro.** b
- **Cinco.** c
- **Seis.** d

### Arreglado
- **Viejo nombre.** Cuenta como Corregido.

### Seguridad
- **No se muestra.** La PWA solo muestra tres secciones.

## [1.9.0] - 2026-11-30

### Cambiado
- **Algo.** Cambió.
"""


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_parsea_items_secciones_y_limites():
    versiones = novedades.parsear(CHANGELOG_ARMADO)

    assert [v["version"] for v in versiones] == ["2.0.0", "1.9.0"]
    v = versiones[0]
    assert v["fecha"] == "2026-12-01"
    assert set(v["secciones"]) == {"Agregado", "Corregido"}
    assert len(v["secciones"]["Agregado"]) == novedades.MAX_ITEMS_POR_SECCION
    assert v["secciones"]["Agregado"][0] == {"titulo": "Uno.", "texto": "Con un link y código, en dos líneas."}
    assert v["secciones"]["Agregado"][1] == {"titulo": "", "texto": "Sin título en negrita."}
    assert v["secciones"]["Corregido"] == [{"titulo": "Viejo nombre.", "texto": "Cuenta como Corregido."}]


def test_changelog_real_desde_1_1_0_trae_1_1_1_y_1_1_2():
    versiones = novedades.posteriores((1, 1, 0))

    assert [v["version"] for v in versiones][-2:] == ["1.1.2", "1.1.1"]
    assert all(novedades.semver(v["version"]) > (1, 1, 0) for v in versiones)
    v112 = next(v for v in versiones if v["version"] == "1.1.2")
    assert v112["fecha"] == "2026-11-22"
    assert v112["secciones"]["Agregado"][0]["titulo"] == "Editar vuelos y hoteles."
    assert v112["secciones"]["Agregado"][0]["texto"].startswith("En Viajes, cada vuelo y cada hotel")


def test_titulos_y_textos_sin_markdown():
    for v in novedades.todas():
        for items in v["secciones"].values():
            assert len(items) <= novedades.MAX_ITEMS_POR_SECCION
            for item in items:
                assert "*" not in item["titulo"] and "**" not in item["texto"]
                assert "\n" not in item["texto"]


def test_el_parseo_se_cachea():
    assert novedades.todas() is novedades.todas()


def test_endpoint_desde_1_1_0(client):
    r = client.get("/api/novedades", params={"desde": "1.1.0"}, headers=login_headers(client))

    assert r.status_code == 200
    versiones = [v["version"] for v in r.json()]
    assert "1.1.1" in versiones and "1.1.2" in versiones and "1.1.0" not in versiones
    assert set(r.json()[0]) == {"version", "fecha", "secciones"}


def test_endpoint_desde_la_ultima_version_no_trae_nada(client):
    r = client.get("/api/novedades", params={"desde": __version__}, headers=login_headers(client))

    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.parametrize("desde", ["1.1", "v1.1.0", "1.1.0-beta", "abc", "", "1.1.0.0"])
def test_desde_invalido_da_422(client, desde):
    r = client.get("/api/novedades", params={"desde": desde}, headers=login_headers(client))

    assert r.status_code == 422


def test_sin_sesion_da_401(client):
    assert client.get("/api/novedades", params={"desde": "1.0.0"}).status_code == 401

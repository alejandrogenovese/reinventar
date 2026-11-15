"""Staging se instala con otro ícono y otro nombre que producción, así no se confunden las dos apps en el celular."""
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import config
from app.main import app, icono

ICONOS = Path(__file__).resolve().parent.parent / "web" / "icons"


def test_produccion_sirve_el_manifest_y_los_iconos_de_siempre(monkeypatch):
    monkeypatch.setattr(config, "ENTORNO", None)
    with TestClient(app) as c:
        m = c.get("/manifest.webmanifest").json()
        icono = c.get("/icons/icon-192.png?v=2")

    assert m["name"] == "ReinventAR"
    assert all(i["src"].startswith("/icons/icon") for i in m["icons"])
    assert icono.content == (ICONOS / "icon-192.png").read_bytes()


def test_staging_cambia_nombre_e_iconos(monkeypatch):
    monkeypatch.setattr(config, "ENTORNO", "staging")
    with TestClient(app) as c:
        r = c.get("/manifest.webmanifest")
        m = r.json()
        apple = c.get("/icons/apple-touch-icon.png?v=2")
        badge = c.get("/icons/badge-96.png")

    assert r.headers["content-type"].startswith("application/manifest+json")
    assert m["name"] == m["short_name"] == "ReinventAR STG"
    assert all(i["src"].startswith("/icons/stg/") for i in m["icons"])
    assert apple.content == (ICONOS / "stg" / "apple-touch-icon.png").read_bytes()
    # Lo que no tiene versión de staging (el badge de las notificaciones) sale igual que en producción.
    assert badge.content == (ICONOS / "badge-96.png").read_bytes()


def test_cada_icono_del_manifest_de_staging_existe(monkeypatch):
    monkeypatch.setattr(config, "ENTORNO", "staging")
    with TestClient(app) as c:
        m = c.get("/manifest.webmanifest").json()
        respuestas = [c.get(i["src"]) for i in m["icons"]]

    assert all(r.status_code == 200 for r in respuestas)


def test_icono_inexistente_o_con_ruta_da_404(monkeypatch):
    monkeypatch.setattr(config, "ENTORNO", "staging")
    with TestClient(app) as c:
        assert c.get("/icons/no-existe.png").status_code == 404
    # Solo nombres de archivo de la carpeta: una ruta relativa no sale de icons/.
    with pytest.raises(HTTPException) as e:
        icono("../manifest.webmanifest")
    assert e.value.status_code == 404

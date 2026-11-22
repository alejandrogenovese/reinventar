"""Galería pública de demos: links firmados del bucket, índice, carga de archivos (solo admin), CSP y la página."""
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import cabeceras, config, demos
from app.main import app
from app.tickets_almacen import url_firmada
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

INDICE = [
    {"feature": "gastos", "titulo": "Gastos del viaje en segundos", "beneficio": "Cargás y ves el total",
     "duracion_s": 51, "video": "gastos.mp4", "poster": "gastos.jpg"},
]


class AlmacenFalso:
    """Bucket en memoria: guarda lo que se sube y firma links predecibles."""

    host = "demos-x.t3.storageapi.dev"

    def __init__(self, archivos: dict[str, bytes] | None = None):
        self.archivos = dict(archivos or {})
        self.tipos: dict[str, str] = {}

    def guardar(self, clave, datos, tipo):
        self.archivos[clave] = datos
        self.tipos[clave] = tipo

    def leer(self, clave):
        return self.archivos.get(clave)

    def url_firmada(self, clave, segundos, ahora=None):
        return f"https://{self.host}/{clave}?firma=ok&expira={segundos}"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def almacen(monkeypatch):
    falso = AlmacenFalso({demos.CLAVE_INDICE: json.dumps(INDICE).encode()})
    monkeypatch.setattr(demos, "obtener", lambda: falso)
    demos.olvidar_indice()
    yield falso
    demos.olvidar_indice()


def test_el_link_firmado_coincide_con_el_ejemplo_de_aws():
    # Ejemplo de la documentación de S3 (Authenticating Requests: Using Query Parameters, AWS SigV4).
    url = url_firmada("examplebucket.s3.amazonaws.com", "/test.txt", "AKIAIOSFODNN7EXAMPLE",
                      "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1", datetime(2013, 5, 24, tzinfo=UTC), 86400)
    assert url.startswith("https://examplebucket.s3.amazonaws.com/test.txt?X-Amz-Algorithm=AWS4-HMAC-SHA256")
    assert url.endswith("X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404")


def test_sin_bucket_la_galeria_dice_que_no_hay_demos(client, monkeypatch):
    monkeypatch.setattr(demos, "obtener", lambda: None)
    r = client.get("/api/demos")
    assert r.status_code == 200
    assert r.json() == {"disponible": False, "demos": []}


def test_la_galeria_es_publica_y_devuelve_links_firmados(client, almacen):
    r = client.get("/api/demos")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["disponible"] is True
    demo = cuerpo["demos"][0]
    assert demo["titulo"] == "Gastos del viaje en segundos"
    assert demo["video"].startswith("https://demos-x.t3.storageapi.dev/gastos.mp4?firma=ok")
    assert demo["poster"].startswith("https://demos-x.t3.storageapi.dev/gastos.jpg?firma=ok")


def test_un_indice_roto_responde_502_con_mensaje_claro(client, almacen):
    almacen.archivos[demos.CLAVE_INDICE] = b"{no es json"
    demos.olvidar_indice()
    r = client.get("/api/demos")
    assert r.status_code == 502
    assert "demos" in r.json()["detail"]


def test_subir_archivos_es_solo_para_admin(client, almacen):
    r = client.put("/api/admin/demos/archivos/gastos.mp4", content=b"video", headers=login_headers(client))
    assert r.status_code == 403


def test_el_admin_sube_un_video_con_su_tipo(client, almacen):
    admin = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    r = client.put("/api/admin/demos/archivos/gastos.mp4", content=b"video", headers=admin)
    assert r.status_code == 200, r.text
    assert almacen.archivos["gastos.mp4"] == b"video"
    assert almacen.tipos["gastos.mp4"] == "video/mp4"


@pytest.mark.parametrize("nombre", ["../index.json", "gastos.exe", "Gastos.mp4", "index.json"])
def test_no_se_aceptan_nombres_fuera_del_patron(client, almacen, nombre):
    admin = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    r = client.put(f"/api/admin/demos/archivos/{nombre}", content=b"x", headers=admin)
    assert r.status_code in (404, 405, 422)  # «../» lo normaliza el cliente a otra ruta, que no acepta PUT
    assert almacen.archivos.get(nombre) != b"x"  # no se guardó (ni pisó el índice)


def test_sin_bucket_subir_responde_503(client, monkeypatch):
    monkeypatch.setattr(demos, "obtener", lambda: None)
    admin = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    r = client.put("/api/admin/demos/archivos/gastos.mp4", content=b"video", headers=admin)
    assert r.status_code == 503


def test_el_indice_nuevo_se_ve_enseguida_en_la_galeria(client, almacen):
    admin = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    nuevo = [{**INDICE[0], "feature": "shows", "titulo": "Shows", "video": "shows.mp4", "poster": "shows.jpg"}]
    r = client.put("/api/admin/demos/indice", json=nuevo, headers=admin)
    assert r.status_code == 200, r.text
    assert [d["feature"] for d in client.get("/api/demos").json()["demos"]] == ["shows"]


def test_el_indice_rechaza_claves_que_no_son_de_demos(client, almacen):
    admin = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    malo = [{**INDICE[0], "video": "../tickets/ale/foto.jpg"}]
    r = client.put("/api/admin/demos/indice", json=malo, headers=admin)
    assert r.status_code == 422


def test_la_csp_deja_reproducir_videos_solo_del_bucket_de_demos(monkeypatch):
    monkeypatch.setattr(demos, "origen_publico", lambda: "https://demos-x.t3.storageapi.dev")
    assert "media-src 'self' https://demos-x.t3.storageapi.dev" in cabeceras.politica()
    monkeypatch.setattr(demos, "origen_publico", lambda: None)
    assert "media-src 'self'" in cabeceras.politica()


def test_la_pagina_de_demos_se_sirve_sin_login(client):
    r = client.get("/demos/")
    assert r.status_code == 200
    assert "Cómo se usa ReinventAR" in r.text


def test_el_bucket_se_arma_con_las_variables_de_demos(monkeypatch):
    for nombre, valor in {"DEMOS_S3_ENDPOINT": "https://t3.storageapi.dev", "DEMOS_S3_BUCKET": "demos-x",
                          "DEMOS_S3_KEY_ID": "k", "DEMOS_S3_SECRET": "s", "DEMOS_S3_REGION": "auto"}.items():
        monkeypatch.setattr(config, nombre, valor)
    monkeypatch.setattr(demos, "_s3", None)
    assert demos.origen_publico() == "https://demos-x.t3.storageapi.dev"
    monkeypatch.setattr(config, "DEMOS_S3_SECRET", "")
    monkeypatch.setattr(demos, "_s3", None)
    assert demos.obtener() is None
    assert demos.origen_publico() is None

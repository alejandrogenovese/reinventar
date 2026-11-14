"""Límite por usuario en los endpoints que gastan LLM/STT: corta con 429 y un mensaje claro, sin tocar el proveedor."""
import pytest
from fastapi.testclient import TestClient

from app import limites, nl_filters
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

PERFIL = {"profile": {"role": "dev", "experience": "", "interests": []}, "prompt": ""}

# (nombre, límite, método, ruta, cuerpo, quién llama)
ENDPOINTS = [
    ("parse", limites.busquedas_nl, "post", "/api/k/explore/parse", {"json": {"text": "charlas de datos"}}, TEST_USER),
    ("ask", limites.preguntas, "post", "/api/k/ask", {"json": {"q": "¿qué hay de IA?"}}, TEST_USER),
    ("briefing", limites.briefings, "post", "/api/k/briefing", {"json": {"kind": "speaker", "id": 1}}, TEST_USER),
    ("repreguntas", limites.entrevista, "post", "/api/itinerary/interview/repreguntas", {}, TEST_USER),
    ("ficha", limites.entrevista, "post", "/api/itinerary/ficha", {}, TEST_USER),
    ("voz", limites.entrevista, "post", "/api/itinerary/interview/voz",
     {"content": b"x", "headers": {"content-type": "audio/webm"}}, TEST_USER),
    ("generate", limites.itinerarios, "post", "/api/itinerary/generate", {"json": PERFIL}, TEST_USER),
    ("vista-previa", limites.admin_links, "post", "/api/admin/eventos/link/vista-previa",
     {"json": {"url": "https://example.com/evento"}}, TEST_ADMIN),
    ("link", limites.admin_links, "post", "/api/admin/eventos/link",
     {"json": {"url": "https://example.com/evento", "nombre": "Cena", "fecha": "2026-12-01", "inicio": "19:00"}},
     TEST_ADMIN),
]


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as cliente:
        yield cliente


def _headers(c, quien):
    clave = TEST_ADMIN_PASSWORD if quien == TEST_ADMIN else "testpass123"
    return login_headers(c, quien, clave)


@pytest.mark.parametrize("nombre,limite,metodo,ruta,pedido,quien", ENDPOINTS, ids=[e[0] for e in ENDPOINTS])
def test_corta_con_429_cuando_el_usuario_agota_su_cupo(c, monkeypatch, nombre, limite, metodo, ruta, pedido, quien):
    monkeypatch.setattr(limite, "maximo", 1)
    headers = _headers(c, quien)
    assert limite.consumir(quien)  # el cupo ya está gastado

    r = getattr(c, metodo)(ruta, headers={**headers, **pedido.get("headers", {})},
                           **{k: v for k, v in pedido.items() if k != "headers"})

    assert r.status_code == 429, r.text
    assert "Esperá" in r.json()["detail"]


def test_un_usuario_que_agota_su_cupo_no_corta_a_otro(c, monkeypatch):
    monkeypatch.setattr(limites.busquedas_nl, "maximo", 1)
    monkeypatch.setattr(nl_filters, "parse", lambda texto: {"filtros": {}})
    admin = _headers(c, TEST_ADMIN)
    usuario = _headers(c, TEST_USER)
    cuerpo = {"text": "charlas de datos"}

    assert c.post("/api/k/explore/parse", headers=usuario, json=cuerpo).status_code == 200
    assert c.post("/api/k/explore/parse", headers=usuario, json=cuerpo).status_code == 429
    assert c.post("/api/k/explore/parse", headers=admin, json=cuerpo).status_code == 200


def test_el_cupo_vuelve_al_pasar_la_ventana():
    limite = limites.Limite(1, ventana=60)
    assert limite.consumir("ana")
    assert not limite.consumir("ana")
    limite.reiniciar()
    assert limite.consumir("ana")


def test_los_limites_alcanzan_para_uso_real_del_evento(c, monkeypatch):
    """Un usuario normal hace varias búsquedas seguidas sin tocar el tope."""
    monkeypatch.setattr(nl_filters, "parse", lambda texto: {"filtros": {}})
    headers = _headers(c, TEST_USER)
    for _ in range(10):
        assert c.post("/api/k/explore/parse", headers=headers, json={"text": "charlas de datos"}).status_code == 200

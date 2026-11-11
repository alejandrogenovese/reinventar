"""Entrevista del itinerario guiado: respuestas obligatorias, progreso parcial, repreguntas, ficha y respuesta por voz.
LLM y STT en modo fake; no usa el catálogo (corre en CI)."""
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import interview
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

COMPLETAS = {
    "rol": {"texto": "Líder de Arquitectura de Datos", "industria": "banca"},
    "dia_a_dia": "Lidero un equipo de arquitectos de datos: definimos estándares, revisamos diseños y "
                 "acompañamos la migración del data warehouse a un lakehouse en AWS.",
    "equipo": {"lidera": True, "personas": 8, "perfiles": "arquitectos de datos"},
    "desafio": "Tener una herramienta de explotación de grafos con segregación de seguridad por usuario.",
    "trayectoria": {"anios": "+10", "origen": ["desarrollo", "datos"]},
    "nivel": {"niveles": [300, 400], "formatos": ["Chalk talk", "Builders' session"]},
    "tecnologias": ["Amazon Neptune", "AWS Lake Formation"],
    "objetivos": ["aprender algo puntual", "casos de clientes"],
}


# ---------- validación (pura) ----------

def test_sin_respuestas_faltan_las_ocho_obligatorias():
    assert interview.faltantes(interview.Respuestas()) == list(interview.OBLIGATORIAS)


def test_completas_no_falta_nada_y_las_opcionales_no_son_obligatorias():
    assert interview.faltantes(interview.Respuestas(**COMPLETAS)) == []


def test_textos_cortos_cuentan_como_faltantes():
    r = interview.Respuestas(**{**COMPLETAS, "dia_a_dia": "Datos.", "desafio": "Grafos."})

    assert interview.faltantes(r) == ["dia_a_dia", "desafio"]


def test_si_lidera_tiene_que_decir_cuantas_personas():
    r = interview.Respuestas(**{**COMPLETAS, "equipo": {"lidera": True}})

    assert interview.faltantes(r) == ["equipo"]


def test_tecnologias_y_objetivos_piden_al_menos_uno():
    r = interview.Respuestas(**{**COMPLETAS, "tecnologias": [], "objetivos": []})

    assert interview.faltantes(r) == ["tecnologias", "objetivos"]


def test_la_ficha_toma_nivel_formatos_industria_y_ritmo_de_lo_que_respondio():
    llm = {"resumen": "Arquitecto muy técnico.", "prioridades": [{"tema": "Grafos", "peso": 3, "claves": ["Neptune"]}],
           "evitar": ["intro a IA"], "consulta_busqueda": "graph databases fine-grained access control",
           "nivel": [100], "industria": "retail"}  # lo que el LLM no debería decidir se pisa con las respuestas

    ficha = interview.armar_ficha(llm, interview.Respuestas(**COMPLETAS))

    assert (ficha.nivel, ficha.formatos, ficha.industria) == ([300, 400], ["Chalk talk", "Builders' session"], "banca")
    assert ficha.ritmo == interview.Ritmo()  # sin la pregunta 10, el ritmo por defecto
    assert "●●● Grafos (Neptune)" in interview.ficha_a_texto(ficha)


# ---------- API ----------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def headers(client):
    # Cada test arranca sin entrevista: el admin se usa como usuario limpio y se borra lo que deja.
    h = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    yield h
    from app import db
    db.delete_interview(TEST_ADMIN)


def test_guarda_el_progreso_de_a_una_pregunta(client, headers):
    r = client.put("/api/itinerary/interview", headers=headers, json={"rol": COMPLETAS["rol"]})
    assert r.status_code == 200
    assert "rol" not in r.json()["faltan"]

    r = client.put("/api/itinerary/interview", headers=headers, json={"desafio": COMPLETAS["desafio"]})
    estado = client.get("/api/itinerary/interview", headers=headers).json()

    assert estado["respuestas"]["rol"]["industria"] == "banca"  # la segunda no pisó la primera
    assert estado["respuestas"]["desafio"] == COMPLETAS["desafio"]
    assert estado["faltan"] == ["dia_a_dia", "equipo", "trayectoria", "nivel", "tecnologias", "objetivos"]


def test_rechaza_valores_fuera_de_las_opciones(client, headers):
    r = client.put("/api/itinerary/interview", headers=headers, json={"rol": {"texto": "Dev", "industria": "minería"}})

    assert r.status_code == 422


def test_sin_completar_no_hay_repreguntas_ni_ficha(client, headers):
    client.put("/api/itinerary/interview", headers=headers, json={"rol": COMPLETAS["rol"]})

    assert client.post("/api/itinerary/interview/repreguntas", headers=headers).status_code == 422
    assert client.post("/api/itinerary/ficha", headers=headers).status_code == 422


def test_repreguntas_ficha_y_edicion(client, headers):
    client.put("/api/itinerary/interview", headers=headers, json=COMPLETAS)

    rep = client.post("/api/itinerary/interview/repreguntas", headers=headers).json()["repreguntas"]
    assert 1 <= len(rep) <= interview.MAX_REPREGUNTAS
    respondidas = [{**rep[0], "respuesta": "Los consultan analistas y también agentes."}]
    client.put("/api/itinerary/interview", headers=headers, json={"repreguntas": respondidas})

    ficha = client.post("/api/itinerary/ficha", headers=headers).json()
    assert ficha["ficha"]["industria"] == "banca"
    assert ficha["ficha"]["prioridades"]
    assert "Prioridades" in ficha["ficha_texto"]

    editada = {**ficha["ficha"], "evitar": ["marketing"]}
    r = client.put("/api/itinerary/ficha", headers=headers, json=editada)
    estado = client.get("/api/itinerary/interview", headers=headers).json()

    assert r.status_code == 200
    assert estado["ficha"]["evitar"] == ["marketing"]
    assert "marketing" in estado["ficha_texto"]


def test_editar_la_ficha_valida_los_pesos(client, headers):
    client.put("/api/itinerary/interview", headers=headers, json=COMPLETAS)
    ficha = client.post("/api/itinerary/ficha", headers=headers).json()["ficha"]
    mala = {**ficha, "prioridades": [{"tema": "Grafos", "peso": 7, "claves": []}]}

    assert client.put("/api/itinerary/ficha", headers=headers, json=mala).status_code == 422


def _audio(tmp_path: Path) -> bytes:
    out = tmp_path / "voz.webm"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-c:a", "libopus", "-b:a", "32k", str(out)], check=True)
    return out.read_bytes()


def test_responder_con_la_voz_devuelve_el_texto(client, headers, tmp_path):
    r = client.post("/api/itinerary/interview/voz", headers={**headers, "Content-Type": "audio/webm"},
                    content=_audio(tmp_path))

    assert r.status_code == 200
    assert r.json()["texto"]  # el STT fake devuelve una frase por cada 5 s


def test_voz_vacia_o_demasiado_grande(client, headers):
    h = {**headers, "Content-Type": "audio/webm"}

    assert client.post("/api/itinerary/interview/voz", headers=h, content=b"").status_code == 422
    grande = b"0" * (interview.MAX_VOZ_BYTES + 1)
    assert client.post("/api/itinerary/interview/voz", headers=h, content=grande).status_code == 413

"""Perfil profesional del speaker: el descartado (homónimo) no se muestra; el que está a revisar va con aviso."""
import datetime as dt

from app import knowledge


def _fila(calidad: str | None) -> dict:
    return {"encontrado": True, "cargo_actual": "Principal SA", "empresa_actual": "AWS", "seniority": "Senior",
            "cargo_desde": dt.date(2024, 1, 1), "industria_empresa": None, "headline": "SA", "ubicacion": "Seattle",
            "linkedin_url": "https://www.linkedin.com/in/x", "github_url": None, "x_handle": None, "skills": ["aws"],
            "otros_roles_actuales": None, "trayectoria": [{"cargo": "SA"}], "educacion": [], "fuente": "crustdata",
            "fecha_consulta": dt.date(2026, 11, 10), "calidad_match": calidad}


def test_descartado_no_muestra_datos_de_otra_persona():
    p = knowledge._profile(_fila("descartado"))
    assert p["found"] is False
    assert p["match"] == "descartado"
    assert "title" not in p
    assert "linkedin" not in p
    assert p["experience"] == []


def test_revisar_se_muestra_con_aviso():
    p = knowledge._profile(_fila("revisar"))
    assert p["found"] is True
    assert p["unverified"] is True
    assert p["title"] == "Principal SA"


def test_confiable_sin_aviso():
    assert knowledge._profile(_fila("confiable"))["unverified"] is False

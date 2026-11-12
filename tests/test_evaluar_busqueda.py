"""Métricas del script que mide la búsqueda del catálogo (scripts/evaluar_busqueda.py) y forma del set de preguntas."""
import json

from scripts import evaluar_busqueda as ev


def test_acierto_recall_y_mrr_de_un_ranking():
    m = ev.metricas(["X", "A", "Y", "B"], {"A", "B", "C"}, k=3)

    assert m == {"acierto": 1.0, "recall": 1 / 3, "mrr": 0.5}


def test_sin_relevantes_entre_los_primeros_todo_da_cero():
    assert ev.metricas(["X", "Y"], {"A"}, k=2) == {"acierto": 0.0, "recall": 0.0, "mrr": 0.0}


def test_el_recall_no_castiga_cuando_hay_mas_relevantes_que_k():
    relevantes = {f"R{i}" for i in range(20)}

    assert ev.metricas([f"R{i}" for i in range(10)], relevantes, k=10)["recall"] == 1.0


def test_el_set_tiene_preguntas_con_criterio_y_relevantes():
    preguntas = json.loads(ev.SET.read_text(encoding="utf-8"))

    assert len(preguntas) >= 30
    assert all(p["pregunta"] and p["criterio"] and p["relevantes"] for p in preguntas)

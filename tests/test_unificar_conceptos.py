"""Unificación de sinónimos de conceptos (funciones puras, sin base)."""
from scripts.unificar_conceptos import plan


def test_formas_con_el_mismo_ingles_pasan_a_la_mas_usada_y_no_se_repiten():
    filas = [
        ("A", ["cumplimiento normativo", "latencia"], ["regulatory compliance", "latency"]),
        ("B", ["cumplimiento normativo"], ["Regulatory compliance"]),
        ("C", ["cumplimiento regulatorio", "cumplimiento normativo"], ["regulatory compliance", "regulatory compliance"]),
    ]

    cambios = plan(filas)

    assert cambios == {"B": (["cumplimiento normativo"], ["regulatory compliance"]),
                       "C": (["cumplimiento normativo"], ["regulatory compliance"])}


def test_es_idempotente_y_respeta_las_filas_sin_pares_alineados():
    filas = [("A", ["x", "y"], ["x"]), ("B", ["agentes de IA"], ["AI agents"])]

    assert plan(filas) == {}

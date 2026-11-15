"""El catálogo oficial de AWS trae algunos textos con mojibake (UTF-8 leído como cp1252/latin-1 y vuelto a codificar):
«fleetÂ » por «fleet », «â€”» por «—». app/catalogo_oficial._limpio los repara y normaliza el espacio duro."""
import pytest

from app import catalogo_oficial as co


@pytest.mark.parametrize("crudo, esperado", [
    ("Find the waste hiding in your accelerator fleetÂ ", "Find the waste hiding in your accelerator fleet"),
    ("resources your teams run â€” and the hardest", "resources your teams run — and the hardest"),
    ("Benchmarkâ€”our agent", "Benchmark—our agent"),
    ("itâ€™s", "it’s"),
    ("cafÃ©", "café"),
    ("dosÂ Â espacios", "dos espacios"),
])
def test_limpio_repara_el_mojibake_de_la_fuente(crudo, esperado):
    assert co._limpio(crudo) == esperado


@pytest.mark.parametrize("texto", [
    "Café y ñandú: ¿qué tal?",           # texto bien codificado
    "Ångström and Ñuñoa",                 # letras que arrancan igual que un mojibake pero no lo son
    "Tom & Jerry — 100% real ’ok’",
    "Â",                             # un resto suelto no se puede reparar: queda como está
])
def test_limpio_no_toca_el_texto_bien_codificado(texto):
    assert co._limpio(texto) == texto


def test_el_espacio_duro_se_normaliza_a_un_espacio():
    assert co._limpio("a b  c ") == "a b c"


def test_las_charlas_salen_sin_mojibake():
    item = {"code": "COP361", "title": "Find the waste hiding in your accelerator fleetÂ ",
            "abstract": "run â€” and"}
    charla = co._charla(item, {}, [])

    assert charla.titulo == "Find the waste hiding in your accelerator fleet"
    assert charla.resumen == "run — and"

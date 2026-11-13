"""Prefijos de consulta y documento por modelo de embeddings, y plurales en los tokens de la búsqueda por palabras."""
import pytest

from app import config, embeddings, search


def test_embeddinggemma_lleva_prefijos_distintos_para_consulta_y_documento(monkeypatch):
    monkeypatch.setattr(config, "EMBED_MODEL", "google/embeddinggemma-300m")

    assert embeddings.con_prefijo(["data mesh"], embeddings.CONSULTA) == ["task: search result | query: data mesh"]
    assert embeddings.con_prefijo(["Data mesh at scale"], embeddings.DOCUMENTO) == ["title: none | text: Data mesh at scale"]


def test_un_modelo_sin_prefijos_deja_el_texto_igual(monkeypatch):
    monkeypatch.setattr(config, "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

    assert embeddings.con_prefijo(["hola"], embeddings.CONSULTA) == ["hola"]


def test_el_modelo_por_defecto_es_embeddinggemma_cuantizado():
    assert config.EMBED_MODEL == "google/embeddinggemma-300m-q4" or config.EMBED_PROVIDER == "fake"


def test_la_version_cuantizada_usa_los_mismos_prefijos_que_el_original(monkeypatch):
    monkeypatch.setattr(config, "EMBED_MODEL", "google/embeddinggemma-300m-q4")

    assert embeddings.con_prefijo(["data mesh"], embeddings.CONSULTA) == ["task: search result | query: data mesh"]


def test_la_version_cuantizada_se_registra_una_vez_con_su_archivo_de_4_bits():
    from fastembed import TextEmbedding

    embeddings._registrar_variante("google/embeddinggemma-300m-q4")
    embeddings._registrar_variante("google/embeddinggemma-300m-q4")  # la segunda no hace nada

    registrados = [m for m in TextEmbedding._list_supported_models() if m.model == "google/embeddinggemma-300m-q4"]
    assert len(registrados) == 1
    assert registrados[0].model_file == "onnx/model_q4.onnx" and registrados[0].dim == 768


@pytest.mark.parametrize("plural,singular", [
    ("mainframes", "mainframe"), ("agents", "agent"), ("migraciones", "migracion"), ("servidores", "servidor"),
    ("tablas", "tabla"), ("costs", "cost"),
])
def test_los_plurales_simples_pasan_a_singular(plural, singular):
    assert search.singular(plural) == singular


@pytest.mark.parametrize("palabra", ["aws", "glass", "ios", "bus"])
def test_no_toca_palabras_cortas_ni_las_terminadas_en_doble_s(palabra):
    assert search.singular(palabra) == palabra


def test_consulta_e_indice_quedan_con_los_mismos_tokens():
    assert search._tokens("Migraciones de mainframes") == search._tokens("migración del mainframe") == ["migracion", "mainframe"]

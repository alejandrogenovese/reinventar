"""Armado de bloques de lectura a partir de los segmentos de Whisper (estilo subtítulos)."""
from app import config, pipeline


def _segs(n, seconds=5, text="Hola."):
    return [{"start": i * seconds, "end": (i + 1) * seconds, "text": text} for i in range(n)]


def test_el_largo_por_defecto_es_de_subtitulo():
    assert config.BLOCK_SECONDS == 15


def test_corta_cerca_del_largo_objetivo_y_en_fin_de_oracion():
    blocks = pipeline.group_blocks(_segs(12), 15)

    assert [(b["start"], b["end"]) for b in blocks] == [(0, 15), (15, 30), (30, 45), (45, 60)]
    assert all(b["en"].endswith(".") for b in blocks)


def test_no_corta_a_mitad_de_oracion_si_no_hace_falta():
    segs = _segs(4, text="sigue la idea") + [{"start": 20, "end": 25, "text": "y termina."}]

    blocks = pipeline.group_blocks(segs, 15)

    assert len(blocks) == 1 and blocks[0]["en"].endswith("termina.")


def test_sin_puntuacion_corta_igual_al_doble_del_objetivo():
    blocks = pipeline.group_blocks(_segs(20, text="music"), 15)

    assert all(b["end"] - b["start"] <= 30 for b in blocks)
    assert len(blocks) > 1


def test_el_ultimo_pedazo_no_se_pierde():
    blocks = pipeline.group_blocks(_segs(4), 15)

    assert blocks[-1]["end"] == 20

"""Parámetros de thinking por modelo: cada modelo acepta una configuración distinta (si no, la API devuelve 400)."""
from app import llm


def test_sonnet_5_5_apaga_el_thinking_con_between_tools():
    assert llm.thinking_params("claude-sonnet-5-5") == {"thinking": {"type": "between_tools"}}


def test_opus_5_5_no_manda_thinking_y_fija_el_effort():
    params = llm.thinking_params("claude-opus-5-5")

    assert "thinking" not in params
    assert params == {"output_config": {"effort": llm.DEFAULT_EFFORT}}


def test_haiku_5_5_apaga_el_thinking_con_disabled_como_en_el_gateway():
    assert llm.thinking_params("claude-haiku-5-5") == {"thinking": {"type": "disabled"}}


def test_otros_modelos_no_mandan_thinking():
    assert "thinking" not in llm.thinking_params("claude-fable-5-1")

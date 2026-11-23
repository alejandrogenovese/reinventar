"""Conversor › «Leer con la cámara» (app/conversor.py, app/conversor_api.py) y el mensaje con imagen de app/llm.py.
LLM en modo fake: no consume APIs. Sin catálogo (corre en CI)."""
import base64
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, conversor, limites, llm, trazas
from app.llm_router import Tarea
from app.main import app
from tests.conftest import login_headers

JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"\r\n\n\x00\xff" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
URL = "/api/conversor/foto"


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(config, "CONVERSOR_FOTO", True)
    with TestClient(app) as c:
        c.H = login_headers(c)
        limites.reiniciar_todo()
        yield c


def subir(cli, datos=JPEG, tipo="image/jpeg", campo="foto", headers=None):
    return cli.post(URL, headers=cli.H if headers is None else headers, files={campo: ("carta.jpg", datos, tipo)})


# ---------- endpoint ----------

def test_en_modo_fake_devuelve_el_json_bien_formado(cli):
    r = subir(cli)

    assert r.status_code == 200, r.text
    textos = r.json()["textos"]
    assert textos and all(set(t) == {"original", "traduccion", "unidades"} for t in textos)
    assert textos[0]["unidades"] == [{"valor": 16, "unidad": "oz"}]
    assert all(isinstance(u["valor"], int | float) and u["unidad"] for t in textos for u in t["unidades"])


def test_acepta_png(cli):
    assert subir(cli, PNG, "image/png").status_code == 200


@pytest.mark.parametrize("datos,tipo", [(b"%PDF-1.7 no es una imagen", "application/pdf"),
                                        (b"%PDF-1.7 disfrazado", "image/jpeg"),   # la firma manda, no lo declarado
                                        (JPEG, "text/plain")])
def test_rechaza_lo_que_no_es_imagen(cli, datos, tipo):
    assert subir(cli, datos, tipo).status_code == 415


def test_rechaza_lo_que_se_pasa_de_tamano(cli):
    grande = JPEG + b"\x00" * (2 * 1024 * 1024)

    assert subir(cli, grande).status_code == 413


def test_sin_el_campo_foto_da_422(cli):
    assert subir(cli, campo="archivo").status_code == 422


def test_con_el_kill_switch_apagado_da_503_y_el_estado_lo_dice(cli, monkeypatch):
    monkeypatch.setattr(config, "CONVERSOR_FOTO", False)

    assert subir(cli).status_code == 503
    assert cli.get("/api/conversor/estado", headers=cli.H).json() == {"foto": False}


def test_el_estado_dice_si_esta_prendido(cli):
    assert cli.get("/api/conversor/estado", headers=cli.H).json() == {"foto": True}


def test_pide_sesion(cli):
    assert subir(cli, headers={}).status_code == 401
    assert cli.get("/api/conversor/estado").status_code == 401


def test_tiene_cupo_por_usuario(cli):
    for _ in range(limites.FOTOS_CONVERSOR_POR_USUARIO):
        assert subir(cli).status_code == 200

    assert subir(cli).status_code == 429


def test_si_el_llm_falla_da_502_sin_loguear_el_contenido(cli, monkeypatch, caplog):
    def falla(*_a, **_k):
        raise RuntimeError("LLM 500: respuesta con datos de la foto")

    monkeypatch.setattr(conversor.llm, "complete", falla)
    with caplog.at_level(logging.WARNING):
        r = subir(cli)

    assert r.status_code == 502 and r.json()["detail"] == "No pude leer la foto. Probá de nuevo."
    assert "datos de la foto" not in caplog.text and base64.b64encode(JPEG).decode() not in caplog.text


def test_la_foto_no_se_guarda_en_disco(cli, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    antes = set(config.DATA_DIR.rglob("*"))

    assert subir(cli).status_code == 200
    assert set(config.DATA_DIR.rglob("*")) == antes and list(tmp_path.iterdir()) == []


# ---------- parseo ----------

def test_el_parseo_tolera_json_incompleto():
    cortado = ('{"textos": [{"original": "Ribeye 16 oz", "traduccion": "Ojo de bife", "unidades": [{"valor": 16, "unidad": "oz"}]},'
               ' {"original": "Draft beer", "tradu')

    assert conversor.parsear(cortado) == {"textos": [
        {"original": "Ribeye 16 oz", "traduccion": "Ojo de bife", "unidades": [{"valor": 16, "unidad": "oz"}]}]}


@pytest.mark.parametrize("respuesta", ["", "no veo nada", '{"textos": []}', '{"textos": "nada"}', '{"otra": 1}', "[1, 2]",
                                       '```json\n{"textos": [{"original": "", "traduccion": ""}]}\n```'])
def test_el_parseo_sin_nada_legible_devuelve_lista_vacia(respuesta):
    assert conversor.parsear(respuesta) == {"textos": []}


def test_el_parseo_limpia_unidades_y_textos_raros():
    crudo = json.dumps({"textos": [
        {"original": "  Coffee $3,50 ", "traduccion": "Café", "unidades": [
            {"valor": "3,50", "unidad": "$"}, {"valor": True, "unidad": "oz"}, {"valor": 1, "unidad": ""}, "16 oz"]},
        "suelto", {"original": "x" * 1000, "unidades": "no es lista"}]})

    textos = conversor.parsear(crudo)["textos"]

    assert textos[0] == {"original": "Coffee $3,50", "traduccion": "Café", "unidades": [{"valor": 3.5, "unidad": "$"}]}
    assert len(textos) == 2 and len(textos[1]["original"]) == conversor.LARGO_TEXTO and textos[1]["unidades"] == []


# ---------- mensaje con imagen (app/llm.py) ----------

def _capturar_post(monkeypatch, pedidos):
    def post(url, headers, json, timeout):
        pedidos.append(json)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"textos": []}'}}]})

    monkeypatch.setattr(llm.httpx, "post", post)


def test_por_litellm_la_imagen_va_como_image_url_en_base64_y_sin_guardar_en_langfuse(monkeypatch):
    pedidos = []
    monkeypatch.setattr(config, "LLM_PROVIDER", "litellm")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://litellm:4000")
    _capturar_post(monkeypatch, pedidos)

    conversor.leer(llm.Imagen("image/jpeg", JPEG))

    body = pedidos[0]
    assert body["model"] == "rx-foto"
    texto, imagen = body["messages"][1]["content"]
    assert texto["type"] == "text"
    assert imagen == {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(JPEG).decode()}"}}
    assert body["metadata"]["mask_input"] is True and body["metadata"]["mask_output"] is True


def test_sin_imagen_el_pedido_queda_como_antes(monkeypatch):
    pedidos = []
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://llm:4000")
    _capturar_post(monkeypatch, pedidos)

    llm.complete(Tarea.CHAT, "sistema", "pregunta", 10)

    assert pedidos[0]["messages"][1] == {"role": "user", "content": "pregunta"}


def test_directo_a_claude_la_imagen_va_como_bloque_base64():
    contenido = llm.contenido_claude("leé", llm.Imagen("image/png", PNG))

    assert contenido[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": base64.b64encode(PNG).decode()}}
    assert contenido[1] == {"type": "text", "text": "leé"}
    assert llm.contenido_claude("solo texto") == "solo texto"


def test_la_imagen_no_se_vuelca_en_un_repr():
    assert repr(llm.Imagen("image/jpeg", JPEG)) == f"Imagen(image/jpeg, {len(JPEG)} bytes)"


def test_la_tarea_foto_es_privada_en_langfuse():
    assert trazas.metadata("foto", "s")["mask_input"] is True

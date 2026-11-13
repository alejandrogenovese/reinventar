"""Scores automáticos en Langfuse: el cliente (contra un httpx falso) y el cálculo de cada score.
No llama a ninguna API; el LLM es fake o una respuesta fija."""
import json
import logging

import httpx
import pytest

from app import ask, briefing, catalog, config, db, guided, langfuse_scores, llm, pipeline, prompts, sandbox, trazas

PUBLICA, SECRETA = "pk-lf-prueba", "sk-lf-secreta-de-prueba"


@pytest.fixture
def claves(monkeypatch):
    monkeypatch.setattr(config, "LANGFUSE_PUBLIC_KEY", PUBLICA)
    monkeypatch.setattr(config, "LANGFUSE_SECRET_KEY", SECRETA)
    monkeypatch.setattr(config, "LANGFUSE_HOST", "https://langfuse.prueba/")


@pytest.fixture
def scores(monkeypatch):
    """Captura los scores que se mandarían, como si hubiera claves: (nombre, valor, trace_id de la traza abierta)."""
    vistos = []
    monkeypatch.setattr(langfuse_scores, "activo", lambda: True)
    monkeypatch.setattr(catalog, "get_instance", lambda c: None)
    monkeypatch.setattr(langfuse_scores, "puntuar",
                        lambda nombre, valor: vistos.append((nombre, valor, trazas.actual().trace_id)))
    return vistos


# ---------- cliente ----------

def test_sin_claves_no_manda_nada(monkeypatch):
    monkeypatch.setattr(config, "LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr(langfuse_scores.httpx, "post", lambda *a, **k: pytest.fail("no debería llamar"))

    assert langfuse_scores.enviar("t1", "json_valido", 1) is None


def test_con_claves_manda_el_score_con_basic_auth(claves, monkeypatch):
    pedidos = []

    def post(url, json, auth, timeout):
        pedidos.append((url, json, auth, timeout))
        return httpx.Response(200, json={"id": "s1"})

    monkeypatch.setattr(langfuse_scores.httpx, "post", post)

    langfuse_scores.enviar("t1", "lineas_faltantes", 3).join()

    url, cuerpo, auth, timeout = pedidos[0]
    assert url == "https://langfuse.prueba/api/public/scores"
    assert cuerpo == [{"id": "t1-lineas_faltantes", "traceId": "t1", "name": "lineas_faltantes", "value": 3,
                       "dataType": "NUMERIC", "environment": "dev"}]
    assert auth == (PUBLICA, SECRETA)
    assert timeout == langfuse_scores.TIMEOUT_SEGUNDOS


@pytest.mark.parametrize("respuesta", [httpx.ConnectError("caído"), httpx.Response(500, text=f"error {SECRETA}")])
def test_un_error_de_langfuse_no_rompe_nada_y_no_loguea_secretos(claves, monkeypatch, caplog, respuesta):
    def post(*a, **k):
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    monkeypatch.setattr(langfuse_scores.httpx, "post", post)

    with caplog.at_level(logging.WARNING, logger="reinventar.langfuse"):
        langfuse_scores.enviar("t1", "json_valido", 0).join()

    assert "json_valido" in caplog.text
    assert SECRETA not in caplog.text
    assert PUBLICA not in caplog.text


def _cuerpos(monkeypatch) -> list[dict]:
    """Reemplaza httpx.post y devuelve la lista donde quedan los scores mandados."""
    cuerpos = []

    def post(url, json, auth, timeout):
        cuerpos.extend(json)
        return httpx.Response(202)

    monkeypatch.setattr(langfuse_scores.httpx, "post", post)
    return cuerpos


def test_el_id_del_score_es_deterministico_para_no_duplicar_al_reprocesar(claves, monkeypatch):
    cuerpos = _cuerpos(monkeypatch)

    langfuse_scores.enviar("t1", "lineas_faltantes", 3).join()
    langfuse_scores.enviar("t1", "lineas_faltantes", 0).join()  # la grabación se reprocesó
    langfuse_scores.enviar("t1", "json_valido", 1).join()

    ids = [c["id"] for c in cuerpos]
    assert ids == ["t1-lineas_faltantes", "t1-lineas_faltantes", "t1-json_valido"]


def test_el_score_lleva_el_entorno_y_marca_el_modo_prueba(claves, monkeypatch):
    cuerpos = _cuerpos(monkeypatch)
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "production")

    langfuse_scores.enviar("t1", "json_valido", 1).join()
    with sandbox.activar(sandbox.Sandbox(username="ale", llm="real")):
        langfuse_scores.enviar("t2", "json_valido", 1).join()

    real, prueba = cuerpos
    assert real["environment"] == "prod"
    assert "metadata" not in real
    assert prueba["environment"] == "prod"
    assert prueba["metadata"] == {"prueba": True}


def test_puntuar_va_sobre_la_traza_abierta_solo_por_el_gateway(claves, monkeypatch):
    enviados = []
    monkeypatch.setattr(langfuse_scores, "enviar", lambda *a: enviados.append(a))

    langfuse_scores.puntuar("json_valido", 1)  # sin traza
    with trazas.abrir():
        langfuse_scores.puntuar("json_valido", 1)  # LLM fake: no hay traza en Langfuse
    monkeypatch.setattr(config, "LLM_PROVIDER", "litellm")
    with trazas.abrir() as traza:
        langfuse_scores.puntuar("json_valido", 1)

    assert enviados == [(traza.trace_id, "json_valido", 1)]


# ---------- json_valido ----------

def test_json_valido_uno_si_parsea_y_cero_si_no(scores):
    with trazas.abrir() as traza:
        assert llm.parse_json_puntuado('```json {"a": 1} ```') == {"a": 1}
        with pytest.raises(ValueError):
            llm.parse_json_puntuado("no hay JSON acá")

    assert scores == [("json_valido", 1, traza.trace_id), ("json_valido", 0, traza.trace_id)]


def test_las_razones_del_armado_mandan_json_valido(scores, monkeypatch):
    elegidas = [{"card": {"code": "ARC407", "title": "t", "type": "Breakout", "level": 400}}]
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "sin json")

    assert guided._razones("ficha", elegidas) == {}
    assert [(n, v) for n, v, _ in scores] == [("json_valido", 0)]


# ---------- traducción: lineas_faltantes ----------

def test_la_traduccion_cuenta_las_lineas_que_hubo_que_reintentar(scores, monkeypatch):
    db.init()
    s = db.create_session("Charla", "Breakout")
    db.replace_blocks(s["id"], [{"start": i * 5, "end": i * 5 + 5, "en": f"Line {i}."} for i in range(3)])
    real = llm.complete

    def comilona(tarea, system, user, *a):
        if system == prompts.TRANSLATE_SYSTEM and user.count("[[") > 1:  # el lote: se come la última línea
            return real(tarea, system, user, *a).rsplit("\n", 1)[0]
        return real(tarea, system, user, *a)

    monkeypatch.setattr(llm, "complete", comilona)

    pipeline.process(s["id"])

    assert db.get_session(s["id"])["status"] == "ready"
    traza = trazas.id_grabacion(s["id"])
    assert ("lineas_faltantes", 1, traza) in scores
    assert ("json_valido", 1, traza) in scores  # el resumen


# ---------- chat: codigos_inventados y momentos_citados ----------

def test_el_chat_cuenta_codigos_inventados_y_momentos_citados(scores, monkeypatch):
    momentos = [{"session_id": "s1", "title": "Charla", "start_s": 0, "en": "x"},
                {"session_id": "s1", "title": "Charla", "start_s": 40, "en": "y"}]
    monkeypatch.setattr(ask.search, "hybrid", lambda q, n: [])
    monkeypatch.setattr(ask.fragmentos, "buscar", lambda q, n: momentos)
    monkeypatch.setattr(catalog, "get_session", lambda c: {"base": c, "instances": [{}]} if c == "ARC407" else None)
    monkeypatch.setattr(catalog, "first_card", lambda s: {"code": s["base"]})
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "Mirá [ARC407], [FAKE999] y [NOPE123]; lo dijeron en [G2] y [G2].")

    r = ask.answer("¿qué hay de data mesh?")

    assert r["cited"] == ["ARC407"]
    assert {(n, v) for n, v, _ in scores} == {("codigos_inventados", 2), ("momentos_citados", 1)}
    assert len({t for *_, t in scores}) == 1  # los dos sobre la misma traza


def test_los_momentos_no_cuentan_como_codigos_inventados(monkeypatch):
    monkeypatch.setattr(catalog, "get_session", lambda c: None)
    monkeypatch.setattr(catalog, "get_instance", lambda c: None)

    assert ask.codigos_inventados("[G1] [G12] [ARC999] [ARC999]") == ["ARC999"]


def test_los_codigos_de_instancia_no_cuentan_como_inventados(monkeypatch):
    """Las grabaciones citan el código de la instancia ([ARC407-R1]): existe aunque no sea el de la sesión."""
    monkeypatch.setattr(catalog, "get_session", lambda c: {"base": c} if c == "ARC407" else None)
    monkeypatch.setattr(catalog, "get_instance", lambda c: ({}, {"c": c}) if c == "ARC407-R1" else None)

    assert ask.codigos_inventados("[ARC407] [ARC407-R1] [ARC407-R9]") == ["ARC407-R9"]


def test_las_siglas_sueltas_no_cuentan_como_codigos(monkeypatch):
    monkeypatch.setattr(catalog, "get_session", lambda c: None)
    monkeypatch.setattr(catalog, "get_instance", lambda c: None)

    assert ask.codigos_inventados("[AWS] [API] [IAM-ROLE] [ZZZ000]") == ["ZZZ000"]


def test_sin_claves_el_chat_no_calcula_los_scores(monkeypatch):
    monkeypatch.setattr(ask.search, "hybrid", lambda q, n: [])
    monkeypatch.setattr(ask.fragmentos, "buscar", lambda q, n: [])
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "Mirá [ARC407].")
    monkeypatch.setattr(catalog, "get_session", lambda c: None)
    monkeypatch.setattr(ask, "codigos_inventados", lambda t: pytest.fail("no debería contar códigos sin claves"))

    assert ask.answer("¿qué hay?")["cited"] == []


def test_sin_claves_el_briefing_no_calcula_codigos_inventados(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps({"quien": "x"}))
    monkeypatch.setattr(ask, "codigos_inventados", lambda t: pytest.fail("no debería contar códigos sin claves"))

    with pytest.raises(briefing.BriefingUnavailable):  # la forma no es válida, pero no contó códigos antes
        briefing._ask("Entidad a preparar: x")


# ---------- briefing ----------

def test_el_briefing_manda_json_valido_y_codigos_inventados(scores, monkeypatch):
    ficha = {"quien": "Alguien", "temas": [{"tema": "Mesh", "por_que": "Dio [ARC407] y [ZZZ000]"}], "preguntas": []}
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps(ficha))
    monkeypatch.setattr(catalog, "get_session", lambda c: {"base": c} if c == "ARC407" else None)

    assert briefing._ask("Entidad a preparar: x") == ficha
    assert [(n, v) for n, v, _ in scores] == [("json_valido", 1), ("codigos_inventados", 1)]

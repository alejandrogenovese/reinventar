"""Buscar por el código de un horario («IND347-R1») trae la tarjeta de ese horario, no la del primero de la charla.
Catálogo chico en memoria (corre en CI)."""
import pytest

from app import catalog, explore


def _i(code, dia, hora):
    return {"c": code, "d": dia, "st": hora, "v": "Wynn/Encore|Latour 7", "seats": 50, "walk": False}


CHARLA = {"base": "IND347", "title": "Build a governed semantic layer", "type": "Builders' session", "level": "300",
          "topic": "", "aoi": "", "services": "", "tech": "", "concepts": "", "concepts_en": "", "focus": "",
          "speakers": "", "people": [], "abstract": "", "abstract_es": None, "newlaunch": False,
          "instances": [_i("IND347-R", "2026-12-01", "15:00"), _i("IND347-R1", "2026-12-04", "10:00")]}


@pytest.fixture(autouse=True)
def catalogo(monkeypatch):
    monkeypatch.setattr(catalog, "_sessions", [CHARLA])


def _codigos(q, filtros=None, **kw):
    return [t["code"] for t in explore.explore(filtros or {}, q, **kw)["results"]]


@pytest.mark.parametrize("q", ["IND347-R1", "ind347-r1", " IND347-R1 "])
def test_el_codigo_de_un_horario_trae_solo_ese_horario(q):
    assert _codigos(q) == ["IND347-R1"]


@pytest.mark.parametrize("q", ["IND347", "ind347"])
def test_el_codigo_de_la_charla_trae_todos_sus_horarios(q):
    r = explore.explore({}, q)

    assert [t["code"] for t in r["results"]] == ["IND347-R", "IND347-R1"]
    assert r["total"] == 2


def test_un_texto_que_no_es_codigo_trae_una_tarjeta_por_charla():
    assert _codigos("semantic") == ["IND347-R"]


def test_el_codigo_se_combina_con_los_filtros_de_horario():
    # El filtro de día manda: con el martes elegido, la charla de la base trae solo el martes.
    assert _codigos("IND347", {"dia": {"2026-12-01"}}) == ["IND347-R"]
    # Si el filtro deja afuera el horario del código, queda el que sí cumple (la charla calza por texto).
    assert _codigos("IND347-R1", {"dia": {"2026-12-01"}}) == ["IND347-R"]


def test_paginado_sobre_los_horarios():
    assert _codigos("IND347", limit=1, offset=1) == ["IND347-R1"]


def test_agrupado_por_dia_cada_grupo_muestra_su_horario():
    grupos = explore.explore({}, "IND347", group_by="dia")["groups"]

    assert {g["value"]: [t["code"] for t in g["results"]] for g in grupos} == {
        "2026-12-01": ["IND347-R"], "2026-12-04": ["IND347-R1"]}


def test_agrupado_por_tipo_respeta_el_codigo_buscado():
    [base] = explore.explore({}, "IND347", group_by="tipo")["groups"]
    [horario] = explore.explore({}, "IND347-R1", group_by="tipo")["groups"]

    assert [t["code"] for t in base["results"]] == ["IND347-R", "IND347-R1"]
    assert [t["code"] for t in horario["results"]] == ["IND347-R1"]

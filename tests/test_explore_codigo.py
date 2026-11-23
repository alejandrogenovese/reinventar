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


@pytest.mark.parametrize(("q", "codigo"), [("IND347-R1", "IND347-R1"), ("ind347-r1", "IND347-R1"),
                                          (" IND347-R ", "IND347-R")])
def test_el_codigo_de_un_horario_trae_ese_horario(q, codigo):
    [tarjeta] = explore.explore({}, q)["results"]

    assert tarjeta["code"] == codigo


def test_el_codigo_base_o_un_texto_traen_el_primer_horario():
    assert explore.explore({}, "IND347")["results"][0]["code"] == "IND347-R"
    assert explore.explore({}, "semantic")["results"][0]["code"] == "IND347-R"


def test_el_codigo_se_combina_con_los_filtros_de_horario():
    # Con un filtro de día que deja afuera el horario del código, la tarjeta es la del horario que sí cumple.
    [tarjeta] = explore.explore({"dia": {"2026-12-01"}}, "IND347-R1")["results"]

    assert tarjeta["code"] == "IND347-R"


def test_agrupado_cada_grupo_muestra_su_horario_y_si_no_el_del_codigo():
    por_dia = {g["value"]: g["results"][0]["code"] for g in explore.explore({}, "IND347-R", group_by="dia")["groups"]}
    [por_tipo] = explore.explore({}, "IND347-R1", group_by="tipo")["groups"]

    assert por_dia == {"2026-12-01": "IND347-R", "2026-12-04": "IND347-R1"}
    assert por_tipo["results"][0]["code"] == "IND347-R1"

"""Auditoría de perfiles con LLM: qué se considera sospechoso, validación de la respuesta y comparación con lo manual."""
import json

import pytest

from scripts import auditar_perfiles as ap


def _caso(id_=1, cargo_catalogo="Sr. Technical Account Manager", es_amazon=True, cargo="OB Operations Flow Lead"):
    return ap.Caso(id_, "Mohamed Othman", cargo_catalogo, "AWS", es_amazon, ("Charla",), cargo, "Amazon", None, None,
                   ({"cargo": "Process Assistant", "empresa": "Amazon"},), (), None)


def test_sospechoso_amazon_con_cargo_distinto():
    assert ap.sospechoso(_caso())


def test_no_sospechoso_amazon_con_cargo_parecido():
    assert not ap.sospechoso(_caso(cargo="Senior Technical Account Manager"))


def test_no_sospechoso_fuera_de_amazon():
    assert not ap.sospechoso(_caso(es_amazon=False))


def test_sospechoso_sin_cargo_en_catalogo():
    assert ap.sospechoso(_caso(cargo_catalogo=None, es_amazon=False))


def test_leer_veredictos_exige_todos_los_ids_y_valores_validos():
    ok = json.dumps({"casos": [{"id": 1, "veredicto": "Otra", "motivo": "depósito"}]})
    assert ap.leer_veredictos(ok, [1])[1] == ap.Veredicto("otra", "depósito")
    with pytest.raises(ValueError):
        ap.leer_veredictos(ok, [1, 2])
    with pytest.raises(ValueError):
        ap.leer_veredictos(json.dumps({"casos": [{"id": 1, "veredicto": "quizás"}]}), [1])


def test_auditar_por_lotes_con_llm_falso():
    casos = [_caso(i) for i in range(1, 5)]

    def completar(_modelo, _system, user, _max):
        ids = [c["id"] for c in json.loads(user.split("\n", 1)[1])["casos"]]
        return json.dumps({"casos": [{"id": i, "veredicto": "misma", "motivo": "ok"} for i in ids]})

    veredictos, fallidos = ap.auditar(casos, completar=completar, lote=3, hilos=2)

    assert set(veredictos) == {1, 2, 3, 4} and not fallidos


def test_auditar_vuelve_a_pedir_los_casos_salteados():
    casos = [_caso(i) for i in range(1, 4)]
    pedidos = []

    def completar(_modelo, _system, user, _max):
        ids = [c["id"] for c in json.loads(user.split("\n", 1)[1])["casos"]]
        pedidos.append(ids)
        devuelve = ids if len(pedidos) > 1 else ids[:-1]  # la primera vez se saltea el último
        return json.dumps({"casos": [{"id": i, "veredicto": "otra", "motivo": ""} for i in devuelve]})

    veredictos, fallidos = ap.auditar(casos, completar=completar, lote=3, hilos=1)

    assert set(veredictos) == {1, 2, 3} and not fallidos
    assert pedidos == [[1, 2, 3], [3]]


def test_aplicar_validacion_manual_gana_y_dudosos_en_bloque_quedan_a_revisar():
    from scripts import aplicar_validacion_perfiles as av

    manual = av.desde_manual({"1": {"decision": "valido"}, "2": {"decision": "saltear"},
                              "3": {"decision": "valido", "cargo": "Founder and CEO", "empresa": "Zenie AI"}})
    auditoria = av.desde_auditoria(
        [{"id_speaker": "1", "veredicto": "otra"}, {"id_speaker": "4", "veredicto": "otra"},
         {"id_speaker": "5", "veredicto": "dudosa"}, {"id_speaker": "6", "veredicto": "dudosa"},
         {"id_speaker": "7", "veredicto": "dudosa"}, {"id_speaker": "8", "veredicto": "misma"}],
        {"5": {"decision": "valido"}, "6": {"decision": "valido", "nota": av.NOTA_EN_BLOQUE}})

    c = av.combinar(manual, auditoria)

    assert {i: x.calidad for i, x in c.items()} == {1: "confiable", 2: "revisar", 3: "confiable", 4: "descartado",
                                                     5: "confiable", 6: "revisar"}
    assert (c[3].cargo, c[3].empresa) == ("Founder and CEO", "Zenie AI")


def test_comparar_marca_solo_contradicciones():
    veredictos = {1: ap.Veredicto("misma", ""), 2: ap.Veredicto("otra", ""), 3: ap.Veredicto("dudosa", "")}
    matriz, errores = ap.comparar(veredictos, {1: "misma", 2: "misma", 3: "otra"})
    assert errores == [2]
    assert matriz[("misma", "otra")] == 1 and matriz[("otra", "dudosa")] == 1

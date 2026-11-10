"""Parser del catálogo oficial de AWS y asignación de speakers: funciones puras, sin base."""
import datetime as dt

import pytest

from scripts.catalogo_oficial import (
    SpeakerExistente, SpeakerOficial, clave, codigo_base, parsear, planear_speakers,
)
from tests.catalogo_fixture import catalogo_v1


def test_codigo_base_saca_solo_el_sufijo_de_repeticion():
    assert codigo_base("ANT319-R1") == "ANT319"
    assert codigo_base("AIM402-R") == "AIM402"
    assert codigo_base("SEC212-S-R") == "SEC212-S"
    assert codigo_base("ARC407") == "ARC407"


def test_clave_ignora_tildes_mayusculas_y_agregados_entre_parentesis():
    assert clave("Alex Torres (AWS)") == clave("alex torres") == "alextorres"
    assert clave("José Núñez-Pérez") == "josenunezperez"
    assert clave("ヘレナ・イン Yin Koeppl") == "yinkoeppl"


def test_agrupa_repeticiones_en_una_charla_con_sus_horarios():
    cat = parsear(catalogo_v1())

    arc = [h for h in cat.horarios if h.id_speech == "ARC100"]
    assert {c.id_speech for c in cat.charlas} == {"ARC100", "SEC200-S", "DEV300", "COM400", "PEX321"}
    assert [(h.codigo, h.aws_time_id, h.aws_session_id) for h in arc] == [
        ("ARC100", "t-arc100", "s-arc100"), ("ARC100-R", "t-arc100r", "s-arc100r")]


def test_horario_trae_fin_sede_y_sala_separadas():
    cat = parsear(catalogo_v1())

    h = next(h for h in cat.horarios if h.codigo == "ARC100")
    assert (h.fecha, h.hora_inicio, h.hora_fin) == (dt.date(2026, 12, 1), dt.time(10), dt.time(11))
    assert (h.sede, h.sala, h.cupo, h.walk_up) == ("MGM Grand", "Level 3 · Premier 311", 78, True)


def test_charla_trae_los_campos_nuevos_del_oficial():
    cat = parsear(catalogo_v1())
    charlas = {c.id_speech: c for c in cat.charlas}

    arc, sec = charlas["ARC100"], charlas["SEC200-S"]
    assert (arc.nivel, arc.topicos, arc.area_interes) == (300, ("Architecture", "Serverless"), "Generative AI;Cost")
    assert (arc.roles, arc.industria, arc.duracion_min) == (("Developer",), ("Financial Services",), 60)
    assert (arc.es_sponsoreada, arc.speakers_ocultos) == (False, False)
    assert (sec.es_sponsoreada, sec.speakers_ocultos) == (True, True)
    assert arc.modificado == dt.datetime(2026, 11, 6, 20, 31, 24, tzinfo=dt.timezone.utc)


def test_participaciones_con_id_de_aws_rol_cargo_y_orden():
    cat = parsear(catalogo_v1())

    arc = sorted((p for p in cat.participaciones if p.id_speech == "ARC100"), key=lambda p: p.orden)
    assert [(p.aws_speaker_id, p.orden, p.rol, p.cargo) for p in arc] == [
        ("u-ana", 0, "Internal Speaker", "Solutions Architect"), ("u-bob", 1, "External Speaker", "CTO")]


def _oficial(ref, nombre, empresas=("AWS",), charlas=1):
    return SpeakerOficial(ref, nombre, frozenset(empresas), charlas)


def test_asigna_primero_por_id_de_aws_y_despues_por_nombre():
    existentes = [SpeakerExistente(1, "Ana Perez", "anaperez", "u-ana", None),
                  SpeakerExistente(2, "Bob Smith", "bobsmith", None, None)]
    oficiales = [_oficial("u-ana", "Ana Pérez (AWS)"), _oficial("u-bob", "Bob Smith (Acme)")]

    plan = planear_speakers(existentes, oficiales)

    assert plan.asignados == {"u-ana": 1, "u-bob": 2}
    assert plan.ids_completados == {2: "u-bob"}
    assert plan.nuevos == ()


def test_homonimos_el_existente_queda_con_quien_coincide_con_su_perfil():
    existentes = [SpeakerExistente(7, "David Victoria", "davidvictoria", None, "Caylent Inc.")]
    oficiales = [_oficial("u-david-1", "David Victoria", ["Amazon"], charlas=3),
                 _oficial("u-david-2", "David Victoria", ["Caylent"], charlas=1)]

    plan = planear_speakers(existentes, oficiales)

    assert plan.asignados == {"u-david-2": 7}
    assert [n.aws_speaker_id for n in plan.nuevos] == ["u-david-1"]
    assert plan.homonimos[0].id_speaker == 7 and plan.homonimos[0].criterio == "empresa del perfil"


def test_homonimos_sin_perfil_el_existente_queda_con_el_de_mas_charlas():
    existentes = [SpeakerExistente(7, "David Victoria", "davidvictoria", None, None)]
    oficiales = [_oficial("u-david-1", "David Victoria", ["Amazon"], charlas=1),
                 _oficial("u-david-2", "David Victoria", ["Caylent"], charlas=2)]

    plan = planear_speakers(existentes, oficiales)

    assert plan.asignados == {"u-david-2": 7}
    assert plan.homonimos[0].criterio == "más charlas (sin perfil)"


def test_speaker_desconocido_es_nuevo():
    plan = planear_speakers([], [_oficial("u-eva", "Eva Ruiz")])

    assert [(n.aws_speaker_id, n.nombre, n.nombre_clave) for n in plan.nuevos] == [("u-eva", "Eva Ruiz", "evaruiz")]
    assert plan.asignados == {}


def test_codigo_repetido_en_el_json_gana_el_mas_reciente():
    crudo = catalogo_v1()
    viejo = {**crudo["sectionList"][0]["items"][0], "modified": "2026-01-01T00:00:00Z", "title": "Título viejo"}
    crudo["sectionList"][0]["items"].insert(0, viejo)

    cat = parsear(crudo)

    assert [h.codigo for h in cat.horarios].count("ARC100") == 1


def test_sessiontimeid_repetido_entre_codigos_distintos_es_un_error():
    crudo = catalogo_v1()
    otro = {**crudo["sectionList"][0]["items"][0], "code": "ZZZ999"}
    crudo["sectionList"][0]["items"].append(otro)

    with pytest.raises(ValueError, match="sessionTimeID repetido"):
        parsear(crudo)


def test_homonimo_cuyo_perfil_no_coincide_queda_marcado_para_revisar():
    existentes = [SpeakerExistente(7, "Rohit Sharma", "rohitsharma", None, "Property Finder")]
    oficiales = [_oficial("u-r1", "Rohit Sharma", ["AWS"], charlas=1), _oficial("u-r2", "Rohit Sharma", ["AWS India"])]

    plan = planear_speakers(existentes, oficiales)

    assert "revisar" in plan.homonimos[0].criterio


def test_renombre_de_speaker_actualiza_tambien_su_clave():
    assert clave("Eric Johnson") == "ericjohnson"

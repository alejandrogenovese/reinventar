"""Carga del catálogo oficial en un schema efímero (no toca reinvent): idempotencia, homónimos, renombres y bajas."""
import os
import uuid

import psycopg
import pytest

from scripts.actualizar_catalogo import actualizar, aplicar_migraciones, migrar_codigos_app
from scripts.catalogo_oficial import parsear
from tests.catalogo_fixture import catalogo_v1, catalogo_v2

V1, V2 = parsear(catalogo_v1()), parsear(catalogo_v2())


@pytest.fixture
def conn():
    schema, schema_app = f"cat_test_{uuid.uuid4().hex[:8]}", f"cat_app_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        aplicar_migraciones(c, schema)
        c.execute(f"""
          CREATE SCHEMA {schema_app};
          CREATE TABLE {schema_app}.itinerary_items (username text, code text, base text, PRIMARY KEY (username, code));
          CREATE TABLE {schema_app}.sessions (id text PRIMARY KEY, code text);""")
        c.commit()
        c.schema, c.schema_app = schema, schema_app
        yield c
        c.rollback()
        c.execute(f"DROP SCHEMA {schema} CASCADE; DROP SCHEMA {schema_app} CASCADE")
        c.commit()


def _uno(c, sql: str, *params):
    return c.execute(sql.format(s=c.schema, a=c.schema_app), params).fetchone()


def _todos(c, sql: str, *params):
    return c.execute(sql.format(s=c.schema, a=c.schema_app), params).fetchall()


def _cargar(c, cat, **kw):
    return actualizar(c, cat, schema=c.schema, **kw)


def test_primera_carga_crea_charlas_horarios_speakers_y_vinculos(conn):
    reporte = _cargar(conn, V1)

    assert _uno(conn, "SELECT count(*) FROM {s}.speech")[0] == 5
    assert _uno(conn, "SELECT count(*) FROM {s}.speech_horario WHERE aws_time_id IS NOT NULL AND hora_fin IS NOT NULL")[0] == 6
    assert _uno(conn, "SELECT count(*) FROM {s}.speaker WHERE aws_speaker_id IS NOT NULL")[0] == 6
    assert _todos(conn, "SELECT k.aws_speaker_id, ss.orden, ss.rol, ss.cargo_en_charla FROM {s}.speech_speaker ss "
                        "JOIN {s}.speaker k USING (id_speaker) WHERE id_speech = 'ARC100' ORDER BY orden") == [
        ("u-ana", 0, "Internal Speaker", "Solutions Architect"), ("u-bob", 1, "External Speaker", "CTO")]
    assert reporte.total_cambios > 0


def test_segunda_carga_no_cambia_nada(conn):
    _cargar(conn, V1)

    reporte = _cargar(conn, V1)

    assert reporte.total_cambios == 0, reporte.cambios


def test_speaker_existente_recibe_su_id_de_aws_y_conserva_el_perfil(conn):
    conn.execute(f"""
      INSERT INTO {conn.schema}.speaker (id_speaker, nombre, nombre_clave) VALUES (50, 'Bob Smith', 'bobsmith');
      INSERT INTO {conn.schema}.speaker_perfil (id_speaker, encontrado, fuente, fecha_consulta, empresa_actual)
      VALUES (50, true, 'crustdata', '2026-11-01', 'Acme Bank');""")

    _cargar(conn, V1)

    assert _uno(conn, "SELECT nombre, aws_speaker_id FROM {s}.speaker WHERE id_speaker = 50") == ("Bob Smith (Acme)", "u-bob")
    assert _uno(conn, "SELECT count(*) FROM {s}.speaker_perfil WHERE id_speaker = 50")[0] == 1


def test_homonimos_fusionados_se_separan_y_el_perfil_queda_con_su_dueno(conn):
    conn.execute(f"""
      INSERT INTO {conn.schema}.speaker (id_speaker, nombre, nombre_clave) VALUES (70, 'David Victoria', 'davidvictoria');
      INSERT INTO {conn.schema}.speaker_perfil (id_speaker, encontrado, fuente, fecha_consulta, empresa_actual)
      VALUES (70, true, 'crustdata', '2026-11-01', 'Caylent');""")

    reporte = _cargar(conn, V1)

    charlas = dict(_todos(conn, "SELECT ss.id_speech, k.id_speaker FROM {s}.speech_speaker ss JOIN {s}.speaker k "
                                "USING (id_speaker) WHERE k.nombre = 'David Victoria'"))
    assert charlas["COM400"] == 70 and charlas["DEV300"] != 70
    assert [(h.id_speaker, h.aws_speaker_id) for h in reporte.homonimos] == [(70, "u-david-2")]
    assert _uno(conn, "SELECT count(*) FROM {s}.speaker_perfil")[0] == 1


def test_renombre_de_codigo_se_detecta_por_el_id_del_horario(conn):
    _cargar(conn, V1)

    reporte = _cargar(conn, V2)

    assert reporte.renombres == [("PEX321", "PEX218")]
    assert _uno(conn, "SELECT codigo, id_speech FROM {s}.speech_horario WHERE aws_time_id = 't-pex'") == ("PEX218", "PEX218")
    assert _todos(conn, "SELECT codigo_viejo, codigo_nuevo FROM {s}.codigo_renombrado") == [("PEX321", "PEX218")]


def test_bajas_se_reportan_y_solo_se_borran_si_se_pide(conn):
    _cargar(conn, V1)

    reporte = _cargar(conn, V2)
    assert "SEC200-S" in reporte.bajas_horarios
    assert _uno(conn, "SELECT count(*) FROM {s}.speech_horario WHERE codigo = 'SEC200-S'")[0] == 1

    _cargar(conn, V2, borrar_bajas=True)
    assert _uno(conn, "SELECT count(*) FROM {s}.speech WHERE id_speech IN ('SEC200-S', 'PEX321')")[0] == 0


def test_migrar_codigos_app_mueve_itinerarios_y_grabaciones_al_codigo_nuevo(conn):
    _cargar(conn, V1)
    conn.execute(f"""
      INSERT INTO {conn.schema_app}.itinerary_items VALUES ('ale', 'PEX321', 'PEX321'), ('ale', 'ARC100', 'ARC100');
      INSERT INTO {conn.schema_app}.sessions VALUES ('g1', 'PEX321'), ('g2', NULL);""")
    _cargar(conn, V2)

    huerfanos = migrar_codigos_app(conn, conn.schema, conn.schema_app)

    assert _todos(conn, "SELECT code, base FROM {a}.itinerary_items ORDER BY code") == [
        ("ARC100", "ARC100"), ("PEX218", "PEX218")]
    assert _uno(conn, "SELECT code FROM {a}.sessions WHERE id = 'g1'") == ("PEX218",)
    assert huerfanos == 0


def _con_codigos(cat_crudo: dict, renombres: dict[str, str]) -> dict:
    """Copia del catálogo con códigos cambiados (mismo sessionTimeID): simula renombres de AWS."""
    items = [{**i, "code": renombres.get(i["code"], i["code"])} for i in cat_crudo["sectionList"][0]["items"]]
    return {"sectionList": [{"items": items}]}


def test_intercambio_de_codigos_entre_dos_horarios_no_rompe_la_carga(conn):
    _cargar(conn, V1)

    reporte = _cargar(conn, parsear(_con_codigos(catalogo_v1(), {"DEV300": "COM400", "COM400": "DEV300"})))

    assert sorted(reporte.renombres) == [("COM400", "DEV300"), ("DEV300", "COM400")]
    assert _uno(conn, "SELECT codigo FROM {s}.speech_horario WHERE aws_time_id = 't-dev300'") == ("COM400",)


def test_cadena_de_renombres_sobre_un_codigo_existente(conn):
    _cargar(conn, V1)

    reporte = _cargar(conn, parsear(_con_codigos(catalogo_v1(), {"PEX321": "COM400", "COM400": "COM401"})))

    assert sorted(reporte.renombres) == [("COM400", "COM401"), ("PEX321", "COM400")]
    assert _uno(conn, "SELECT codigo FROM {s}.speech_horario WHERE aws_time_id = 't-pex'") == ("COM400",)


def test_renombre_a_un_codigo_ocupado_se_reporta_sin_romper(conn):
    _cargar(conn, V1)
    conn.execute(f"INSERT INTO {conn.schema}.speech_horario (codigo, id_speech, fecha, hora_inicio, sede) "
                 f"VALUES ('PEX218', 'PEX321', '2026-12-01', '09:00', 'X')")

    reporte = _cargar(conn, V2)

    assert reporte.renombres_en_conflicto == [("PEX321", "PEX218")]
    assert _uno(conn, "SELECT aws_time_id FROM {s}.speech_horario WHERE codigo = 'PEX218'") == ("t-pex",)


def test_charla_sin_participantes_conserva_sus_speakers(conn):
    _cargar(conn, V1)
    sin_speakers = catalogo_v1()
    for i in sin_speakers["sectionList"][0]["items"]:
        if i["code"] == "COM400":
            i["participants"] = []

    reporte = _cargar(conn, parsear(sin_speakers))

    assert _uno(conn, "SELECT count(*) FROM {s}.speech_speaker WHERE id_speech = 'COM400'")[0] == 1
    assert reporte.cambios["Vínculos charla-speaker quitados"] == 0


def test_borrar_bajas_se_niega_con_un_catalogo_sospechosamente_chico(conn):
    _cargar(conn, V1)
    casi_vacio = catalogo_v1()
    casi_vacio["sectionList"][0]["items"] = casi_vacio["sectionList"][0]["items"][:1]

    with pytest.raises(ValueError, match="sospechosamente chico"):
        _cargar(conn, parsear(casi_vacio), borrar_bajas=True)


def test_un_codigo_viejo_que_vuelve_al_catalogo_no_se_migra(conn):
    _cargar(conn, V1)
    _cargar(conn, V2)  # PEX321 → PEX218 queda en codigo_renombrado
    vuelve = catalogo_v2()
    vuelve["sectionList"][0]["items"].append(
        {**catalogo_v1()["sectionList"][0]["items"][-1], "sessionID": "s-otro", "title": "Otra charla",
         "times": [{**catalogo_v1()["sectionList"][0]["items"][-1]["times"][0], "sessionTimeID": "t-otro"}]})
    _cargar(conn, parsear(vuelve))
    conn.execute(f"INSERT INTO {conn.schema_app}.itinerary_items VALUES ('ale', 'PEX321', 'PEX321')")

    migrar_codigos_app(conn, conn.schema, conn.schema_app)

    assert _uno(conn, "SELECT code FROM {a}.itinerary_items") == ("PEX321",)
    assert _uno(conn, "SELECT count(*) FROM {s}.codigo_renombrado WHERE codigo_viejo = 'PEX321'")[0] == 0


def test_dos_codigos_viejos_que_terminan_en_el_mismo_nuevo_no_chocan(conn):
    _cargar(conn, V1)
    conn.execute(f"""
      INSERT INTO {conn.schema}.codigo_renombrado (codigo_viejo, codigo_nuevo, aws_time_id)
      VALUES ('VIEJO1', 'VIEJO2', 'x'), ('VIEJO2', 'ARC100', 't-arc100');
      INSERT INTO {conn.schema_app}.itinerary_items VALUES ('ale', 'VIEJO1', 'VIEJO1'), ('ale', 'VIEJO2', 'VIEJO2');""")

    migrar_codigos_app(conn, conn.schema, conn.schema_app)

    assert _todos(conn, "SELECT code FROM {a}.itinerary_items") == [("ARC100",)]


def test_si_aws_cambia_el_resumen_se_vacian_su_traduccion_y_sus_claves(conn):
    _cargar(conn, V1)
    conn.execute(f"UPDATE {conn.schema}.speech SET resumen_es = 'traducido', conceptos = '{{agentes}}'")
    cambiado = catalogo_v1()
    for i in cambiado["sectionList"][0]["items"]:
        if i["code"] == "COM400":
            i["abstract"] = "A brand new abstract."

    reporte = _cargar(conn, parsear(cambiado))

    assert reporte.cambios["Resúmenes a reprocesar (traducción y claves)"] == 1
    assert _todos(conn, "SELECT id_speech FROM {s}.speech WHERE resumen_es IS NULL AND conceptos IS NULL") == [
        ("COM400",)]

"""Enriquecimiento de speakers con Crustdata: decisión del match (pura) y escritura en un schema efímero, sin la API."""
import datetime as dt
import os
import uuid

import psycopg
import pytest

from scripts.actualizar_catalogo import aplicar_migraciones
from scripts.enriquecer_speakers import Decision, Speaker, a_fila, consultar, decidir, enriquecer, nombre_limpio

HOY = dt.date(2026, 11, 10)


def _sp(nombre="Ana Pérez", empresa="Nubank", es_amazon=False, cargo="Staff Data Engineer", grupo="sin_perfil",
        calidad=None):
    return Speaker(1, nombre, empresa, es_amazon, cargo, grupo, calidad)


def _perfil(pid, nombre, empresa, cargo="Staff Data Engineer", pasados=()):
    return {"crustdata_person_id": pid, "basic_profile": {"name": nombre, "headline": f"{cargo} at {empresa}",
                                                          "location": {"raw": "São Paulo, Brazil"}},
            "social_handles": {"professional_network_identifier": {"profile_url": f"https://www.linkedin.com/in/p{pid}"}},
            "experience": {"employment_details": {
                "current": [{"title": cargo, "company_name": empresa, "start_date": "2024-03-01",
                             "seniority_level": "Senior", "company_industries": ["Financial Services"]}],
                "past": [{"title": "Data Engineer", "company_name": e, "start_date": "2020-01-01",
                          "end_date": "2024-02-01"} for e in pasados]}},
            "education": {"schools": [{"school": "USP", "degree": "BSc", "field_of_study": "Computer Science"}]}}


def test_nombre_limpio_saca_los_agregados_entre_parentesis():
    assert nombre_limpio("Alex Torres (AWS)") == "Alex Torres"


def test_nombre_y_empresa_actual_es_confiable():
    d = decidir(_sp(), [_perfil(1, "Ana Pérez", "Nubank"), _perfil(2, "Ana Perez", "Itaú")])

    assert (d.calidad, d.perfil["crustdata_person_id"]) == ("confiable", 1)


def test_amazon_acepta_cualquier_variante_de_amazon_o_aws():
    d = decidir(_sp(empresa="AWS", es_amazon=True), [_perfil(1, "Ana Pérez", "Amazon Web Services (AWS)")])

    assert d.calidad == "confiable"


def test_dos_en_la_empresa_desempata_el_cargo():
    dos = [_perfil(1, "Ana Pérez", "Nubank", "Product Manager"), _perfil(2, "Ana Pérez", "Nubank")]

    assert decidir(_sp(), dos).perfil["crustdata_person_id"] == 2


def test_dos_en_la_empresa_con_el_mismo_cargo_queda_para_revisar():
    empatados = [_perfil(1, "Ana Pérez", "Nubank"), _perfil(2, "Ana Pérez", "Nubank")]

    assert decidir(_sp(), empatados).calidad == "revisar"


def test_empresa_en_un_trabajo_anterior_queda_para_revisar():
    d = decidir(_sp(), [_perfil(1, "Ana Pérez", "Mercado Libre", pasados=["Nubank"])])

    assert d.motivo == "la empresa aparece en un trabajo anterior"


def test_si_nadie_tiene_ese_nombre_no_se_encontro():
    assert decidir(_sp(), [_perfil(1, "Ana María López", "Nubank")]).calidad is None


def test_si_nadie_con_ese_nombre_encaja_se_descarta():
    assert decidir(_sp(), [_perfil(1, "Ana Pérez", "Globant", "Chef")]).calidad == "descartado"


def test_si_el_match_con_empresa_es_confiable_no_gasta_la_busqueda_solo_por_nombre():
    pedidos = []

    def buscar(filtros, limite):
        pedidos.append(filtros)
        return [_perfil(1, "Ana Pérez", "Nubank")]

    consultar(_sp(), buscar)

    assert len(pedidos) == 1


def test_la_fila_respeta_el_formato_de_los_perfiles_existentes():
    fila = a_fila(_sp(), decidir(_sp(), [_perfil(7, "Ana Pérez", "Nubank", pasados=["Itaú"])]), HOY)

    assert (fila["cargo_actual"], fila["empresa_actual"], fila["cargo_desde"]) == (
        "Staff Data Engineer", "Nubank", dt.date(2024, 3, 1))
    assert fila["trayectoria"].obj == [{"cargo": "Data Engineer", "desde": "2020-01", "hasta": "2024-02", "empresa": "Itaú"}]
    assert fila["educacion"].obj == [{"area": "Computer Science", "titulo": "BSc", "institucion": "USP"}]


def test_la_fila_de_un_no_encontrado():
    assert a_fila(_sp(), Decision(None, None, "nadie"), HOY)["encontrado"] is False


@pytest.fixture
def conn():
    schema = f"en_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        aplicar_migraciones(c, schema)
        c.execute(f"""
          INSERT INTO {schema}.empresa (id_empresa, nombre, es_amazon) VALUES (1, 'Nubank', false);
          INSERT INTO {schema}.speech (id_speech, titulo, tipo) VALUES ('FSI301', 'Pagos', 'Breakout session');
          INSERT INTO {schema}.speaker (id_speaker, nombre, nombre_clave) VALUES
            (10, 'Ana Pérez', 'anaperez'), (11, 'Bruno Dias', 'brunodias'), (12, 'Carla Souza', 'carlasouza');
          INSERT INTO {schema}.speech_speaker (id_speech, id_speaker, id_empresa, orden, cargo_en_charla) VALUES
            ('FSI301', 10, 1, 0, 'Staff Data Engineer'), ('FSI301', 11, 1, 1, 'CTO'), ('FSI301', 12, 1, 2, 'CFO');
          INSERT INTO {schema}.speaker_perfil (id_speaker, encontrado, fuente, fecha_consulta, calidad_match, cargo_actual)
          VALUES (11, true, 'crustdata', '2026-11-01', 'descartado', 'Chef'),
                 (12, true, 'crustdata', '2026-11-01', 'confiable', 'CFO');""")
        c.commit()
        c.schema = schema
        yield c
        c.rollback()
        c.execute(f"DROP SCHEMA {schema} CASCADE")
        c.commit()


def _buscar_falso(filtros, limite):
    nombre = filtros.get("value") or filtros["conditions"][0]["value"]
    return {"Ana Pérez": [_perfil(1, "Ana Pérez", "Nubank")], "Bruno Dias": []}.get(nombre, [])


def test_aplicar_guarda_lo_que_mejora_y_no_pisa_un_descartado_con_un_no_encontrado(conn):
    r = enriquecer(conn, _buscar_falso, schema=conn.schema, aplicar=True, hoy=HOY)

    perfiles = {i: tuple(resto) for i, *resto in conn.execute(
        f"SELECT id_speaker, calidad_match, cargo_actual, fecha_consulta FROM {conn.schema}.speaker_perfil").fetchall()}
    assert (r.guardados, r.sin_mejora) == (1, 1)  # el 12 ya tenía un perfil confiable: no es pendiente
    assert perfiles[10] == ("confiable", "Staff Data Engineer", HOY)
    assert perfiles[11] == ("descartado", "Chef", HOY)  # sigue como estaba, con la fecha de la consulta nueva


def test_lo_consultado_hoy_no_se_vuelve_a_consultar(conn):
    enriquecer(conn, _buscar_falso, schema=conn.schema, aplicar=True, hoy=HOY)

    r = enriquecer(conn, _buscar_falso, schema=conn.schema, aplicar=True, hoy=HOY)

    assert r.decisiones == ()


def test_modo_prueba_no_escribe(conn):
    r = enriquecer(conn, _buscar_falso, schema=conn.schema, hoy=HOY)

    assert len(r.decisiones) == 2
    assert conn.execute(f"SELECT count(*) FROM {conn.schema}.speaker_perfil").fetchone()[0] == 2


def test_el_nombre_exige_nombre_de_pila_y_apellido():
    from scripts.enriquecer_speakers import nombre_coincide

    assert nombre_coincide("ADAM B", "Adam Brown")
    assert not nombre_coincide("ADAM B", "Stephanie B. Adam")
    assert nombre_coincide("José Núñez (AWS)", "Jose Antonio Nunez")
    assert not nombre_coincide("Ana Pérez", "Pérez Ana Gómez")


def test_en_amazon_sin_cargo_parecido_queda_para_revisar():
    sp = _sp(empresa="AWS", es_amazon=True, cargo="Sr. Manager, Product Management")

    d = decidir(sp, [_perfil(1, "Ana Pérez", "Amazon Web Services (AWS)", "Software Dev Engineer")])

    assert d.calidad == "revisar"


def test_varios_en_la_empresa_sin_cargo_parecido_se_descarta():
    sp = _sp(empresa="AWS", es_amazon=True, cargo="WW Tech Leader, Connect")
    perfiles = [_perfil(i, "Ana Pérez", "Amazon", cargo) for i, cargo in ((1, "Assistant"), (2, "Driver"), (3, "Recruiter"))]

    assert decidir(sp, perfiles).calidad == "descartado"

"""Extracción de claves del resumen (servicios, tecnologías, conceptos, enfoque) en un schema efímero, con el LLM fake."""
import json
import os
import uuid

import psycopg
import pytest

from scripts.actualizar_catalogo import aplicar_migraciones
from scripts.extraer_claves import Claves, extraer, leer_claves, pendientes


@pytest.fixture
def conn():
    schema = f"kx_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        aplicar_migraciones(c, schema)
        c.execute(f"""INSERT INTO {schema}.speech (id_speech, titulo, tipo, resumen, servicios) VALUES
          ('ARC100', 'Arquitectura', 'Breakout session', 'Build a lakehouse on Amazon S3.', '{{"Amazon S3"}}'),
          ('DEV200', 'Dev', 'Chalk talk', 'Agents with Amazon Bedrock.', '{{}}'),
          ('KEY001', 'Keynote', 'Keynote', '', '{{}}')""")
        c.commit()
        c.schema = schema
        yield c
        c.rollback()
        c.execute(f"DROP SCHEMA {schema} CASCADE")
        c.commit()


def _respuesta(**charlas) -> str:
    return json.dumps({"charlas": [{"id": i, **campos} for i, campos in charlas.items()]})


def test_normaliza_servicios_y_descarta_enfoques_inventados_y_repetidos():
    respuesta = _respuesta(A={"servicios": ["amazon bedrock", "Amazon Bedrock", " "], "tecnologias": ["MCP"],
                              "conceptos": ["agentes de IA"], "conceptos_en": ["AI agents"],
                              "enfoque": ["Arquitectura", "chamuyo"]})

    claves = leer_claves(respuesta, ["A"], servicios_oficiales=["Amazon Bedrock"])

    assert claves["A"] == Claves(("Amazon Bedrock",), ("MCP",), ("agentes de IA",), ("AI agents",), ("arquitectura",))


def test_respuesta_incompleta_o_con_tipos_raros_es_un_error():
    with pytest.raises(ValueError, match="faltan"):
        leer_claves(_respuesta(A={}), ["A", "B"])
    with pytest.raises(ValueError, match="ilegible"):
        leer_claves(_respuesta(A={"conceptos": "no es lista"}), ["A"])


def test_aplicar_guarda_las_claves_y_no_toca_las_charlas_sin_resumen(conn):
    r = extraer(conn, schema=conn.schema, aplicar=True, lote=1)

    assert (r.procesadas, r.lotes_fallidos) == (2, ())
    filas = conn.execute(f"SELECT id_speech, servicios_mencionados, tecnologias, conceptos, conceptos_en, enfoque "
                         f"FROM {conn.schema}.speech ORDER BY id_speech").fetchall()
    assert filas == [
        ("ARC100", ["Amazon S3"], ["Apache Iceberg"], ["gobierno de datos"], ["data governance"], ["arquitectura"]),
        ("DEV200", ["Amazon S3"], ["Apache Iceberg"], ["gobierno de datos"], ["data governance"], ["arquitectura"]),
        ("KEY001", None, None, None, None, None)]
    assert pendientes(conn, conn.schema) == []


def test_modo_prueba_muestra_sin_escribir(conn):
    r = extraer(conn, schema=conn.schema, codigos=["DEV200"])

    assert [i for i, _ in r.muestra] == ["DEV200"] and r.procesadas == 0
    assert len(pendientes(conn, conn.schema)) == 2

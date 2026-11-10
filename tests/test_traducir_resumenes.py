"""Traducción de los resúmenes del catálogo (speech.resumen_es) en un schema efímero, con el LLM fake."""
import json
import os
import uuid

import psycopg
import pytest

from app import llm
from scripts.actualizar_catalogo import aplicar_migraciones
from scripts.traducir_resumenes import leer_traducciones, pendientes, traducir


@pytest.fixture
def conn():
    schema = f"tr_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        aplicar_migraciones(c, schema)
        c.execute(f"""INSERT INTO {schema}.speech (id_speech, titulo, tipo, resumen) VALUES
          ('ARC100', 'Arquitectura', 'Breakout session', 'Learn how to build serverless apps.'),
          ('DEV200', 'Dev', 'Chalk talk', 'You will learn about Amazon Bedrock.'),
          ('KEY001', 'Keynote', 'Keynote', ''),
          ('SEC300', 'Sec', 'Workshop', 'Secure your workloads.')""")
        c.commit()
        c.schema = schema
        yield c
        c.rollback()
        c.execute(f"DROP SCHEMA {schema} CASCADE")
        c.commit()


def test_leer_traducciones_exige_todos_los_ids():
    ok = json.dumps({"traducciones": [{"id": "A", "texto": "Hola"}, {"id": "B", "texto": "Chau"}]})
    assert leer_traducciones(ok, ["A", "B"]) == {"A": "Hola", "B": "Chau"}

    with pytest.raises(ValueError, match="faltan"):
        leer_traducciones(json.dumps({"traducciones": [{"id": "A", "texto": "Hola"}]}), ["A", "B"])
    with pytest.raises(ValueError, match="faltan"):
        leer_traducciones(json.dumps({"traducciones": [{"id": "A", "texto": " "}]}), ["A"])
    with pytest.raises(ValueError, match="ilegible"):
        leer_traducciones("no es json", ["A"])


def test_aplicar_traduce_lo_pendiente_y_no_toca_los_vacios(conn):
    r = traducir(conn, schema=conn.schema, aplicar=True, lote=2, hilos=2)

    assert (r.traducidas, r.lotes_fallidos) == (3, ())
    filas = dict(conn.execute(f"SELECT id_speech, resumen_es FROM {conn.schema}.speech").fetchall())
    assert filas == {"ARC100": "Traducción de ARC100.", "DEV200": "Traducción de DEV200.",
                     "SEC300": "Traducción de SEC300.", "KEY001": None}
    assert pendientes(conn, conn.schema) == []


def test_modo_prueba_muestra_sin_escribir(conn):
    r = traducir(conn, schema=conn.schema, limite=2)

    assert [m[0] for m in r.muestra] == ["ARC100", "DEV200"]
    assert r.traducidas == 0
    assert len(pendientes(conn, conn.schema)) == 3


def test_un_lote_fallido_no_frena_al_resto(conn):
    def completar(model, system, user, max_tokens):
        if "ARC100" in user:
            return "respuesta cortada"
        return llm.complete(model, system, user, max_tokens)

    r = traducir(conn, schema=conn.schema, aplicar=True, lote=1, completar=completar)

    assert r.traducidas == 2
    assert len(r.lotes_fallidos) == 1
    assert "ARC100" in r.lotes_fallidos[0]
    assert [p[0] for p in pendientes(conn, conn.schema)] == ["ARC100"]


def test_muestra_con_codigos_elegidos(conn):
    r = traducir(conn, schema=conn.schema, codigos=["SEC300", "KEY001"])

    assert [m[0] for m in r.muestra] == ["SEC300"]  # KEY001 no tiene resumen

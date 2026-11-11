"""Tiempos entre sedes con la Routes API: pedido, lectura de la matriz (pura) y carga en un schema efímero.
La API se reemplaza por una función falsa: no consume Google."""
import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from scripts.calcular_tiempos_sedes import Sede, Tiempo, armar_pedido, guardar, leer_matriz, leer_sedes

SEDES = [Sede(2, "Caesars Forum", 36.1179, -115.1641), Sede(7, "Venetian", 36.1216, -115.1691)]


def test_el_pedido_es_a_pie_con_todas_las_sedes_como_origen_y_destino():
    pedido = armar_pedido(SEDES)

    assert pedido["travelMode"] == "WALK"
    assert len(pedido["origins"]) == len(pedido["destinations"]) == 2
    assert pedido["origins"][1]["waypoint"]["location"]["latLng"] == {"latitude": 36.1216, "longitude": -115.1691}


def test_lee_la_matriz_con_indices_omitidos_y_redondea_minutos_para_arriba():
    # La API omite los campos en cero (originIndex 0) y manda la duración como "541s".
    elementos = [
        {"destinationIndex": 1, "duration": "541s", "distanceMeters": 690, "condition": "ROUTE_EXISTS"},
        {"originIndex": 1, "duration": "480s", "distanceMeters": 655, "condition": "ROUTE_EXISTS"},
        {"duration": "0s", "condition": "ROUTE_EXISTS"},                            # 0 → 0: misma sede, se ignora
        {"originIndex": 1, "destinationIndex": 1, "condition": "ROUTE_EXISTS"},
    ]

    assert leer_matriz(elementos, SEDES) == [Tiempo(2, 7, 10, 690), Tiempo(7, 2, 8, 655)]


def test_los_pares_sin_ruta_quedan_afuera():
    elementos = [{"destinationIndex": 1, "condition": "ROUTE_NOT_FOUND"},
                 {"originIndex": 1, "destinationIndex": 0, "duration": "60s", "distanceMeters": 80,
                  "condition": "ROUTE_EXISTS"}]

    assert leer_matriz(elementos, SEDES) == [Tiempo(7, 2, 1, 80)]


@pytest.fixture
def conn():
    schema = f"st_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as c:
        c.schema = schema
        yield c
        c.rollback()
        c.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        c.commit()


def test_guardar_crea_la_tabla_y_reemplaza_lo_medido(conn):
    sedes = leer_sedes(conn, schema=conn.schema)
    assert [s.nombre for s in sedes][:2] == ["Allegiant Stadium", "Caesars Forum"]
    assert all(s.lat is not None for s in sedes)  # Various Locations no tiene coordenadas: queda afuera

    guardar(conn, [Tiempo(2, 7, 10, 690)], schema=conn.schema)
    guardar(conn, [Tiempo(2, 7, 12, 700), Tiempo(7, 2, 8, 655)], schema=conn.schema)

    filas = conn.execute(f"SELECT id_origen, id_destino, minutos, metros FROM {conn.schema}.sede_tiempo "
                         "ORDER BY 1, 2").fetchall()
    assert [tuple(f.values()) for f in filas] == [(2, 7, 12, 700), (7, 2, 8, 655)]

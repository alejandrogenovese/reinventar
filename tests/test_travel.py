"""Minutos caminando entre sedes: dato medido (Routes API), misma sede y respaldo por línea recta. No usa el catálogo."""
import pytest

from app import travel, venues

SEDES = [
    {"id_sede": 2, "nombre": "Caesars Forum", "lat": 36.1179, "lng": -115.1641, "direccion": "3911 Koval Ln"},
    {"id_sede": 5, "nombre": "MGM Grand", "lat": 36.102219, "lng": -115.169517, "direccion": "3799 Las Vegas Blvd S"},
    {"id_sede": 6, "nombre": "Various Locations", "lat": None, "lng": None, "direccion": None},
    {"id_sede": 7, "nombre": "Venetian", "lat": 36.1216, "lng": -115.1691, "direccion": "3355 Las Vegas Blvd S"},
]


@pytest.fixture(autouse=True)
def _maestro():
    venues.load(SEDES)
    travel.load([{"id_origen": 7, "id_destino": 2, "minutos": 9}])
    yield
    travel.load([])


def test_usa_el_tiempo_medido_con_la_routes_api():
    assert travel.viaje(7, 2) == travel.Viaje(minutos=9, estimado=False)


def test_la_misma_sede_cuenta_el_cambio_de_sala():
    assert travel.viaje(5, 5) == travel.Viaje(minutos=travel.MISMA_SEDE_MIN, estimado=False)


def test_un_par_sin_medir_se_estima_por_linea_recta_con_rodeo():
    # Venetian → MGM Grand: ~2,2 km en línea recta × 1,4 a 75 m/min ≈ 41 min.
    v = travel.viaje(7, 5)

    assert v.estimado is True
    assert 38 <= v.minutos <= 44


def test_el_par_medido_no_se_usa_al_reves_sin_medir():
    # Los sentidos pueden diferir (puentes peatonales, escaleras): si falta el inverso, se estima.
    assert travel.viaje(2, 7).estimado is True


def test_sin_coordenadas_o_sin_sede_no_hay_viaje():
    assert travel.viaje(6, 7) is None
    assert travel.viaje(7, None) is None
    assert travel.viaje(99, 7) is None


def test_estimar_minutos_nunca_da_cero():
    assert travel.estimar_minutos((36.1, -115.1), (36.1, -115.1)) == 1


def test_load_reemplaza_los_tiempos_anteriores():
    travel.load([{"id_origen": 2, "id_destino": 7, "minutos": 11}])

    assert travel.viaje(2, 7) == travel.Viaje(minutos=11, estimado=False)
    assert travel.viaje(7, 2).estimado is True

"""«También van»: quién más del grupo tiene un horario en el itinerario. Privacidad: solo nombres de usuario, nunca el
propio, nunca de quien apagó «mostrar mi agenda al grupo» ni de cuentas desactivadas, y solo de los horarios pedidos."""
import time

import pytest
from fastapi.testclient import TestClient

from app import db, passwords
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

URL = "/api/grupo/tambien-van"
PREF = "/api/grupo/preferencia"
CARLA = "carla_grupo"
TODOS = (TEST_USER, TEST_ADMIN, CARLA)


def _limpiar():
    with db.conn() as c:
        c.execute("DELETE FROM itinerary_items WHERE username = ANY(%s)", (list(TODOS),))
        c.execute("DELETE FROM preferencias_avisos WHERE username = ANY(%s)", (list(TODOS),))
        c.execute("UPDATE users SET is_active = TRUE WHERE username = %s", (CARLA,))


def _agregar(username, code, kind="talk"):
    with db.conn() as c:
        c.execute("INSERT INTO itinerary_items (username, code, base, day, start, added_at, kind) "
                  "VALUES (%s,%s,%s,'2026-12-01','10:00',%s,%s)", (username, code, code.split("-")[0], time.time(), kind))


@pytest.fixture
def cli():
    with TestClient(app) as c:
        if not db.get_user(CARLA):
            db.create_user(CARLA, *passwords.hash_password("carlapass123"), must_change_password=False)
        c.H = login_headers(c)
        c.H2 = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        _limpiar()
        yield c
        _limpiar()


def _van(cli, codes, headers=None):
    r = cli.get(URL, params={"codes": ",".join(codes)}, headers=headers or cli.H)
    assert r.status_code == 200, r.text
    return r.json()


def test_sin_sesion_da_401(cli):
    assert cli.get(URL, params={"codes": "AIM301"}).status_code == 401
    assert cli.get(PREF).status_code == 401
    assert cli.put(PREF, json={"agenda_visible": False}).status_code == 401


def test_muestra_a_los_otros_del_grupo_y_no_a_uno_mismo(cli):
    for u in TODOS:
        _agregar(u, "AIM301-R1")

    assert _van(cli, ["AIM301-R1"]) == {"AIM301-R1": [TEST_ADMIN, CARLA]}


def test_solo_el_horario_pedido_y_solo_nombres(cli):
    _agregar(CARLA, "AIM301-R1")
    _agregar(CARLA, "AIM301-R2")
    _agregar(CARLA, "SEC201")

    assert _van(cli, ["AIM301-R1"]) == {"AIM301-R1": [CARLA]}
    assert _van(cli, ["AIM301-R1", "AIM301-R2"]) == {"AIM301-R1": [CARLA], "AIM301-R2": [CARLA]}


def test_horario_sin_nadie_no_aparece(cli):
    _agregar(TEST_USER, "AIM301-R1")
    assert _van(cli, ["AIM301-R1", "XYZ999"]) == {}


def test_eventos_propios_no_cuentan(cli):
    _agregar(CARLA, "AIM301-R1", kind="mine")
    assert _van(cli, ["AIM301-R1"]) == {}


def test_quien_apaga_su_agenda_no_aparece(cli):
    _agregar(TEST_ADMIN, "AIM301-R1")
    _agregar(CARLA, "AIM301-R1")

    r = cli.put(PREF, headers=cli.H2, json={"agenda_visible": False})

    assert r.json() == {"agenda_visible": False}
    assert _van(cli, ["AIM301-R1"]) == {"AIM301-R1": [CARLA]}
    cli.put(PREF, headers=cli.H2, json={"agenda_visible": True})
    assert _van(cli, ["AIM301-R1"]) == {"AIM301-R1": [TEST_ADMIN, CARLA]}


def test_la_preferencia_es_visible_por_defecto_y_de_cada_uno(cli):
    assert cli.get(PREF, headers=cli.H).json() == {"agenda_visible": True}
    cli.put(PREF, headers=cli.H, json={"agenda_visible": False})

    assert cli.get(PREF, headers=cli.H).json() == {"agenda_visible": False}
    assert cli.get(PREF, headers=cli.H2).json() == {"agenda_visible": True}


def test_apagar_la_agenda_no_toca_las_otras_preferencias(cli):
    db.set_preferencias_avisos(TEST_USER, False, True, False)
    cli.put(PREF, headers=cli.H, json={"agenda_visible": False})

    assert db.get_preferencias_avisos(TEST_USER) == {"grabar": False, "ubicacion": True, "eventos_nuevos": False}


def test_cuenta_desactivada_no_aparece(cli):
    _agregar(CARLA, "AIM301-R1")
    db.set_user_active(CARLA, False)

    assert _van(cli, ["AIM301-R1"]) == {}


@pytest.mark.parametrize("codes", ["", ",,", ",".join(f"C{i}" for i in range(21)), "AIM301;DROP", "a" * 41])
def test_codigos_invalidos_dan_422(cli, codes):
    assert cli.get(URL, params={"codes": codes}, headers=cli.H).status_code == 422


def test_la_preferencia_solo_acepta_el_campo_esperado(cli):
    assert cli.put(PREF, headers=cli.H, json={"agenda_visible": False, "username": CARLA}).status_code == 422
    assert cli.put(PREF, headers=cli.H, json={"agenda_visible": "quizás"}).status_code == 422

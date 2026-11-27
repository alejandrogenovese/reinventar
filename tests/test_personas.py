"""«Personas que conocí»: alta idempotente por id del teléfono, edición, borrado, validación (largos y LinkedIn solo
https://www.linkedin.com/), aislamiento entre usuarios (un id ajeno da 404 y no se pisa), cuota de altas y tope total."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app import db, limites
from app import personas as pc
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

URL = "/api/personas"


def _limpiar():
    with db.conn() as c:
        c.execute("DELETE FROM personas_conocidas WHERE username IN (%s,%s)", (TEST_USER, TEST_ADMIN))


@pytest.fixture
def cli():
    with TestClient(app) as c:
        c.H = login_headers(c)
        c.H2 = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        _limpiar()
        yield c
        _limpiar()


def _persona(**extra):
    return {"nombre": "Ana Gómez", "empresa": "Globant", "cargo": "Cloud Architect",
            "linkedin": "https://www.linkedin.com/in/ana-gomez", "donde": "Almuerzo del martes", "nota": "Habla de Bedrock", **extra}


def _guardar(cli, datos=None, id_=None, headers=None):
    id_ = id_ or str(uuid.uuid4())
    return id_, cli.put(f"{URL}/{id_}", headers=headers or cli.H, json=datos or _persona())


def _lista(cli, headers=None):
    r = cli.get(URL, headers=headers or cli.H)
    assert r.status_code == 200
    return r.json()["personas"]


# ---------- alta, edición y borrado ----------

def test_sin_sesion_no_hay_nada(cli):
    assert cli.get(URL).status_code == 401
    assert cli.put(f"{URL}/{uuid.uuid4()}", json=_persona()).status_code == 401
    assert cli.delete(f"{URL}/{uuid.uuid4()}").status_code == 401


def test_alta_y_lista(cli):
    id_, r = _guardar(cli, _persona(charla_code="AIM301-R1", charla_titulo="Agentes en producción"))

    assert r.status_code == 200, r.text
    assert r.json()["id"] == id_
    [p] = _lista(cli)
    assert p["nombre"] == "Ana Gómez"
    assert p["linkedin"] == "https://www.linkedin.com/in/ana-gomez"
    assert p["charla_code"] == "AIM301-R1"
    assert p["charla_titulo"] == "Agentes en producción"


def test_reenviar_el_mismo_alta_no_duplica(cli):
    id_, _ = _guardar(cli)
    _, r = _guardar(cli, id_=id_)

    assert r.status_code == 200
    assert len(_lista(cli)) == 1


def test_editar_cambia_los_datos(cli):
    id_, _ = _guardar(cli)
    _, r = _guardar(cli, _persona(nombre="Ana G.", empresa="", linkedin=""), id_=id_)

    assert r.status_code == 200
    [p] = _lista(cli)
    assert (p["nombre"], p["empresa"], p["linkedin"]) == ("Ana G.", "", "")


def test_borrar(cli):
    id_, _ = _guardar(cli)

    assert cli.delete(f"{URL}/{id_}", headers=cli.H).status_code == 200
    assert _lista(cli) == []
    assert cli.delete(f"{URL}/{id_}", headers=cli.H).status_code == 404


def test_lista_la_ultima_tocada_primero(cli):
    primera, _ = _guardar(cli, _persona(nombre="Primera"))
    _guardar(cli, _persona(nombre="Segunda"))
    _guardar(cli, _persona(nombre="Primera editada"), id_=primera)

    assert [p["nombre"] for p in _lista(cli)] == ["Primera editada", "Segunda"]


# ---------- validación ----------

@pytest.mark.parametrize("linkedin", [
    "http://www.linkedin.com/in/ana",               # sin https
    "https://linkedin.com/in/ana",                  # sin www
    "https://www.linkedin.com.malo.com/in/ana",     # dominio que solo empieza igual
    "https://evil.com/https://www.linkedin.com/",
    "javascript:alert(1)",
    "https://www.linkedin.com/in/ana con espacio",
    "https://www.linkedin.com/" + "a" * pc.LINKEDIN_MAX,
])
def test_linkedin_invalido_da_422(cli, linkedin):
    _, r = _guardar(cli, _persona(linkedin=linkedin))
    assert r.status_code == 422


@pytest.mark.parametrize("campo,largo", [("nombre", pc.NOMBRE_MAX), ("empresa", pc.EMPRESA_MAX), ("cargo", pc.CARGO_MAX),
                                         ("donde", pc.DONDE_MAX), ("nota", pc.NOTA_MAX),
                                         ("charla_titulo", pc.CHARLA_TITULO_MAX)])
def test_cada_campo_tiene_tope_de_largo(cli, campo, largo):
    _, justo = _guardar(cli, _persona(**{campo: "x" * largo}))
    _, pasado = _guardar(cli, _persona(**{campo: "x" * (largo + 1)}))

    assert justo.status_code == 200, justo.text
    assert pasado.status_code == 422


def test_nombre_vacio_o_en_blanco_da_422(cli):
    assert _guardar(cli, _persona(nombre=""))[1].status_code == 422
    assert _guardar(cli, _persona(nombre="   \n "))[1].status_code == 422


def test_codigo_de_charla_raro_da_422(cli):
    assert _guardar(cli, _persona(charla_code="AIM301; DROP"))[1].status_code == 422


def test_id_que_no_es_uuid_da_422(cli):
    assert cli.put(f"{URL}/no-es-uuid", headers=cli.H, json=_persona()).status_code == 422


def test_limpia_espacios_y_saltos_en_campos_de_una_linea(cli):
    _guardar(cli, _persona(nombre="  Ana \n Gómez ", empresa=" AWS  ", nota="  línea 1\nlínea 2  "))
    [p] = _lista(cli)
    assert (p["nombre"], p["empresa"], p["nota"]) == ("Ana Gómez", "AWS", "línea 1\nlínea 2")


# ---------- aislamiento entre usuarios ----------

def test_cada_usuario_ve_solo_lo_suyo(cli):
    _guardar(cli, _persona(nombre="De tester"))
    _guardar(cli, _persona(nombre="De admin"), headers=cli.H2)

    assert [p["nombre"] for p in _lista(cli)] == ["De tester"]
    assert [p["nombre"] for p in _lista(cli, cli.H2)] == ["De admin"]


def test_no_se_puede_borrar_lo_de_otro(cli):
    id_, _ = _guardar(cli)

    assert cli.delete(f"{URL}/{id_}", headers=cli.H2).status_code == 404
    assert len(_lista(cli)) == 1


def test_el_mismo_id_desde_otra_cuenta_no_pisa_al_dueno(cli):
    id_, _ = _guardar(cli, _persona(nombre="Original"))
    _, r = _guardar(cli, _persona(nombre="Intruso"), id_=id_, headers=cli.H2)

    assert r.status_code == 200  # para el otro es una persona nueva suya
    assert [p["nombre"] for p in _lista(cli)] == ["Original"]
    assert [p["nombre"] for p in _lista(cli, cli.H2)] == ["Intruso"]


# ---------- cuota y tope ----------

def test_cuota_de_altas_por_hora(cli, monkeypatch):
    monkeypatch.setattr(limites.personas_nuevas, "maximo", 2)
    assert _guardar(cli)[1].status_code == 200
    id_, r = _guardar(cli)
    assert r.status_code == 200

    assert _guardar(cli)[1].status_code == 429
    assert _guardar(cli, id_=id_)[1].status_code == 200  # editar no gasta cuota


def test_tope_total_por_persona(cli, monkeypatch):
    monkeypatch.setattr(pc, "TOPE_POR_PERSONA", 1)
    id_, _ = _guardar(cli)

    assert _guardar(cli)[1].status_code == 409
    assert _guardar(cli, id_=id_)[1].status_code == 200

"""Huecos sin audio de una grabación (Android le saca el micrófono a la app durante una llamada): POST
/api/sessions/{sid}/huecos reemplaza la lista, GET de la sesión la devuelve ordenada y el export markdown los marca."""
import pytest
from fastapi.testclient import TestClient

from app import db, huecos, pipeline
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

NUEVA = {"title": "Charla con llamada", "kind": "Breakout"}


@pytest.fixture
def cli():
    with TestClient(app) as c:
        c.user = login_headers(c)
        c.otro = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        c.sid = c.post("/api/sessions", headers=c.user, json=NUEVA).json()["id"]
        yield c


def _poner(c, lista, headers=None, sid=None):
    return c.post(f"/api/sessions/{sid or c.sid}/huecos", headers=headers or c.user, json={"huecos": lista})


def _ver(c):
    return c.get(f"/api/sessions/{c.sid}", headers=c.user).json()


# ---------- guardar y leer ----------

def test_una_sesion_nueva_no_tiene_huecos(cli):
    assert _ver(cli)["huecos"] == []


def test_los_huecos_se_guardan_y_el_get_los_devuelve_ordenados(cli):
    r = _poner(cli, [{"desde": 300, "hasta": 310.5}, {"desde": 126.0, "hasta": 160.5}])

    assert r.status_code == 200
    esperados = [{"desde": 126.0, "hasta": 160.5}, {"desde": 300.0, "hasta": 310.5}]
    assert r.json() == {"huecos": esperados}
    assert _ver(cli)["huecos"] == esperados


def test_mandar_la_lista_otra_vez_la_reemplaza_y_es_idempotente(cli):
    _poner(cli, [{"desde": 1, "hasta": 2}, {"desde": 3, "hasta": 4}])
    _poner(cli, [{"desde": 10, "hasta": 20}])
    _poner(cli, [{"desde": 10, "hasta": 20}])

    assert _ver(cli)["huecos"] == [{"desde": 10.0, "hasta": 20.0}]


def test_una_lista_vacia_borra_los_huecos(cli):
    _poner(cli, [{"desde": 1, "hasta": 2}])

    assert _poner(cli, []).status_code == 200
    assert _ver(cli)["huecos"] == []


def test_el_limite_de_200_huecos_se_acepta(cli):
    lista = [{"desde": i * 10, "hasta": i * 10 + 5} for i in range(huecos.MAX_HUECOS)]

    assert _poner(cli, lista).status_code == 200
    assert len(_ver(cli)["huecos"]) == huecos.MAX_HUECOS


# ---------- validación ----------

@pytest.mark.parametrize("lista", [
    [{"desde": i * 10, "hasta": i * 10 + 5} for i in range(huecos.MAX_HUECOS + 1)],  # más de 200
    [{"desde": -1, "hasta": 5}],                                                       # desde negativo
    [{"desde": 5, "hasta": 5}],                                                        # vacío
    [{"desde": 9, "hasta": 5}],                                                        # al revés
    [{"desde": 0, "hasta": huecos.MAX_SEGUNDOS + 1}],                                  # más de 6 h
    [{"desde": 1}],                                                                    # falta hasta
    [{"desde": "uno", "hasta": 5}],                                                    # no es número
])
def test_un_hueco_invalido_da_422_y_no_cambia_lo_guardado(cli, lista):
    _poner(cli, [{"desde": 1, "hasta": 2}])

    assert _poner(cli, lista).status_code == 422
    assert _ver(cli)["huecos"] == [{"desde": 1.0, "hasta": 2.0}]


def test_hasta_exactamente_6_horas_se_acepta(cli):
    assert _poner(cli, [{"desde": 0, "hasta": huecos.MAX_SEGUNDOS}]).status_code == 200


@pytest.mark.parametrize("numero", ["NaN", "Infinity", "-Infinity"])
def test_los_numeros_no_finitos_dan_422(cli, numero):
    r = cli.post(f"/api/sessions/{cli.sid}/huecos", headers={**cli.user, "Content-Type": "application/json"},
                 content=f'{{"huecos": [{{"desde": 1, "hasta": {numero}}}]}}')

    assert r.status_code == 422


def test_sin_el_campo_huecos_da_422(cli):
    assert cli.post(f"/api/sessions/{cli.sid}/huecos", headers=cli.user, json={}).status_code == 422


# ---------- dueño y autenticación ----------

def test_otro_usuario_no_puede_cambiar_los_huecos_de_una_grabacion_ajena(cli):
    r = _poner(cli, [{"desde": 1, "hasta": 2}], headers=cli.otro)

    assert r.status_code == 403
    assert _ver(cli)["huecos"] == []


def test_sin_token_da_401(cli):
    assert cli.post(f"/api/sessions/{cli.sid}/huecos", json={"huecos": []}).status_code == 401


def test_una_sesion_inexistente_da_404(cli):
    assert _poner(cli, [], sid="noexiste0000").status_code == 404


# ---------- export markdown ----------

def _bloques(cli):
    db.replace_blocks(cli.sid, [{"start": 0, "end": 60, "en": "first", "es": "primero"},
                                {"start": 200, "end": 260, "en": "second", "es": "segundo"}])


def test_el_export_marca_cada_hueco_en_su_lugar(cli):
    _bloques(cli)
    _poner(cli, [{"desde": 126.0, "hasta": 160.5}])

    md = cli.get(f"/api/sessions/{cli.sid}/export.md", headers=cli.user).text

    assert "— sin audio 02:06–02:40 —" in md
    assert md.index("primero") < md.index("— sin audio") < md.index("segundo")


def test_el_export_sin_huecos_no_marca_nada(cli):
    _bloques(cli)

    assert "sin audio" not in cli.get(f"/api/sessions/{cli.sid}/export.md", headers=cli.user).text


def test_el_hueco_antes_del_primer_bloque_y_el_del_final_tambien_se_marcan():
    s = {"title": "T", "kind": "Breakout", "huecos": [{"desde": 0.0, "hasta": 5.0}, {"desde": 900.0, "hasta": 3700.0}]}
    blocks = [{"start_s": 10, "en": "uno", "es": "uno"}, {"start_s": 100, "en": "dos", "es": "dos"}]

    md = pipeline.to_markdown(s, blocks)

    assert md.index("— sin audio 00:00–00:05 —") < md.index("uno")
    assert md.index("dos") < md.index("— sin audio 15:00–61:40 —")


def test_mmss_pasa_a_minutos_sin_horas():
    assert huecos.mmss(0) == "00:00"
    assert huecos.mmss(126.0) == "02:06"
    assert huecos.mmss(160.5) == "02:40"
    assert huecos.mmss(3700) == "61:40"

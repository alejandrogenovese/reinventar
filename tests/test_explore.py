"""Explorador por facetas: filtros en cualquier orden, conteos por faceta y agrupar por."""
from fastapi.testclient import TestClient

from app import catalog
from app.main import app
from tests.conftest import login_headers

FACETS = {"tema", "sector", "industria", "empresa", "seniority", "topico", "area", "servicio", "tecnologia", "concepto",
          "enfoque", "tipo", "nivel", "dia", "sede", "hora", "lanzamiento"}


def _explore(c, H, **body):
    r = c.post("/api/k/explore", headers=H, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _values(facet_list):
    return {f["value"]: f["count"] for f in facet_list}


def test_explore_requiere_sesion():
    with TestClient(app) as c:
        assert c.post("/api/k/explore", json={}).status_code == 401


def test_sin_filtros_devuelve_todo_y_todas_las_facetas():
    with TestClient(app) as c:
        body = _explore(c, login_headers(c))

        assert body["total"] == len(catalog.all_sessions())
        assert set(body["facets"]) == FACETS
        assert sum(_values(body["facets"]["tipo"]).values()) == body["total"]


def test_filtro_por_sector_y_conteos_disyuntivos():
    with TestClient(app) as c:
        H = login_headers(c)

        body = _explore(c, H, filters={"sector": ["Finanzas"]})

        assert 0 < body["total"] < len(catalog.all_sessions())
        assert all(any(p.get("sector") == "Finanzas" for p in r["people"]) for r in body["results"])
        # la faceta del propio filtro sigue mostrando las otras opciones (para sumar con O)
        assert _values(body["facets"]["sector"]).get("Tecnología", 0) > 0
        # las demás facetas cuentan dentro del resultado: Nubank está, y ninguna empresa supera el total
        empresas = _values(body["facets"]["empresa"])
        assert "Nubank" in empresas and max(empresas.values()) <= body["total"]


def test_varios_valores_de_una_faceta_suman_con_o():
    with TestClient(app) as c:
        H = login_headers(c)

        finanzas = _explore(c, H, filters={"sector": ["Finanzas"]})["total"]
        salud = _explore(c, H, filters={"sector": ["Salud"]})["total"]
        ambos = _explore(c, H, filters={"sector": ["Finanzas", "Salud"]})["total"]

        assert max(finanzas, salud) < ambos <= finanzas + salud


def test_el_orden_de_los_filtros_no_cambia_el_resultado():
    with TestClient(app) as c:
        H = login_headers(c)

        a = _explore(c, H, filters={"sector": ["Finanzas"], "topico": ["Artificial Intelligence"]}, limit=500)
        b = _explore(c, H, filters={"topico": ["Artificial Intelligence"], "sector": ["Finanzas"]}, limit=500)

        assert [r["base"] for r in a["results"]] == [r["base"] for r in b["results"]]
        assert a["total"] == b["total"] > 0


def test_dia_y_sede_se_cumplen_en_el_mismo_horario():
    with TestClient(app) as c:
        H = login_headers(c)

        body = _explore(c, H, filters={"dia": ["2026-12-02"], "sede": ["Caesars Palace"]}, limit=500)

        assert body["total"] > 0
        for r in body["results"]:
            session = catalog.get_session(r["base"])
            assert any(i["d"] == "2026-12-02" and i["v"].startswith("Caesars Palace|") for i in session["instances"])
            # la card muestra justamente ese horario
            assert (r["day"], r["venue"]["hotel"]) == ("2026-12-02", "Caesars Palace")


def test_texto_libre_se_combina_con_filtros():
    with TestClient(app) as c:
        H = login_headers(c)

        body = _explore(c, H, q="itau", filters={"sector": ["Finanzas"]})

        assert "MAM207" in {r["base"] for r in body["results"]}


def test_agrupar_por_empresa():
    with TestClient(app) as c:
        H = login_headers(c)

        body = _explore(c, H, filters={"sector": ["Finanzas"]}, group_by="empresa")

        groups = body["groups"]
        assert groups and [g["count"] for g in groups] == sorted((g["count"] for g in groups), reverse=True)
        for g in groups:
            assert all(any(p.get("company") == g["value"] for p in r["people"]) for r in g["results"])


def test_facetas_y_agrupacion_invalidas_dan_422():
    with TestClient(app) as c:
        H = login_headers(c)

        assert c.post("/api/k/explore", headers=H, json={"filters": {"precio": ["x"]}}).status_code == 422
        assert c.post("/api/k/explore", headers=H, json={"group_by": "precio"}).status_code == 422

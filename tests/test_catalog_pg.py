"""Catálogo leído de Postgres (schema reinvent) con speakers, empresas y sector."""
from fastapi.testclient import TestClient

from app import catalog, db, pg, search, sectors
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers


def _count(sql: str) -> int:
    with pg.pool().connection() as c:
        return c.execute(sql).fetchone()["n"]


def setup_module(_module):
    db.init()
    catalog.load()


def test_carga_todas_las_sesiones_y_horarios_de_la_base():
    sessions = catalog.search(limit=10_000)

    assert len({s["base"] for s in sessions}) == _count("SELECT count(*) n FROM reinvent.speech")
    assert len(sessions) == _count("SELECT count(*) n FROM reinvent.speech_horario")


def test_instancia_conserva_el_formato_del_json():
    session, instance = catalog.get_instance("ARC407")

    assert instance == {"c": "ARC407", "d": "2026-12-03", "st": "14:30",
                        "v": "MGM Grand|Level 3|Chairman's 363|Content Hub|Red Theater", "seats": 116, "walk": True}
    assert session["level"] == "400" and session["topic"] == "Architecture"


def test_card_trae_speakers_con_cargo_empresa_y_sector_en_orden():
    session, instance = catalog.get_instance("ARC407")

    people = catalog.card(session, instance)["people"]

    assert [p["name"] for p in people] == ["Romi Patel", "Mohammed Ali Syed", "Rohit Kumar Singh"]
    experian = people[1]
    assert (experian["company"], experian["title"], experian["sector"]) == ("Experian", "Data Engineering Director", "Tecnología")
    assert people[0]["is_amazon"] is True


def test_todas_las_industrias_de_la_base_tienen_sector():
    with pg.pool().connection() as c:
        industrias = {r["industria"] for r in c.execute("SELECT DISTINCT industria FROM reinvent.empresa").fetchall()}

    assert industrias <= set(sectors.SECTOR_BY_INDUSTRY)


def test_prefilter_encuentra_charlas_por_empresa_e_industria():
    por_empresa = search.prefilter({"role": "", "experience": "", "interests": []}, "Nubank", limit=5)
    por_industria = search.prefilter({"role": "", "experience": "", "interests": []}, "banca", limit=20)

    assert any(p["company"] == "Nubank" for p in por_empresa[0]["people"])
    assert any(p["industry"] == "Banca" for c in por_industria for p in c["people"])


def test_facets_incluye_sectores():
    sectores = {f["value"] for f in catalog.facets()["sectors"]}

    assert {"Finanzas", "Tecnología"} <= sectores


def test_admin_recarga_el_catalogo():
    with TestClient(app) as c:
        admin = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)

        r = c.post("/api/admin/catalog/reload", headers=admin)
        no_admin = c.post("/api/admin/catalog/reload", headers=login_headers(c))

        assert r.status_code == 200, r.text
        assert r.json()["sessions"] == _count("SELECT count(*) n FROM reinvent.speech")
        assert no_admin.status_code == 403


def test_busqueda_por_texto_encuentra_speakers_y_empresas():
    por_empresa = catalog.search(q="nubank", limit=10)
    por_speaker = catalog.search(q="mohammed ali syed", limit=10)

    assert por_empresa and all(any(p["company"] == "Nubank" for p in r["people"]) for r in por_empresa)
    assert [r["base"] for r in por_speaker] == ["ARC407"]


def test_busqueda_ignora_tildes_y_mayusculas():
    sin_tilde = {r["base"] for r in catalog.search(q="itau", limit=20)}
    con_tilde = {r["base"] for r in catalog.search(q="ITAÚ", limit=20)}

    assert "MAM207" in sin_tilde and sin_tilde == con_tilde


def test_busqueda_por_texto_usa_las_claves_del_resumen():
    s = {"title": "Charla", "abstract": "Build agents.", "tech": "Apache Iceberg;MCP",
         "concepts": "costo de inferencia;agentes de IA", "concepts_en": "inference cost;AI agents"}

    assert catalog._matches(catalog.fold("costo de inferencia"), s)
    assert catalog._matches(catalog.fold("iceberg"), s)
    assert catalog._matches(catalog.fold("inference cost"), s)
    assert not catalog._matches(catalog.fold("ia costo"), s)  # no pega el final de una clave con otra


def test_las_coordenadas_de_la_sede_vienen_del_maestro():
    mgm = next(i for s in catalog.all_sessions() for i in s["instances"] if i["v"].startswith("MGM Grand|"))
    varios = next(i for s in catalog.all_sessions() for i in s["instances"] if i["v"] == "Various Locations")

    venue = catalog.card({"base": "X", "title": "X"}, mgm)["venue"]
    assert (venue["hotel"], venue["lat"], venue["lng"]) == ("MGM Grand", 36.102219, -115.169517)
    assert catalog.card({"base": "X", "title": "X"}, varios)["venue"]["lat"] is None

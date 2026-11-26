"""«Nueva · agregada el …»: el catálogo marca las charlas que la revisión del catálogo oficial sumó hace poco
(app/catalog.agregada) y la tarjeta lo muestra. Sin catálogo cargado: card() se arma con datos de prueba."""
import datetime as dt

from app import catalog, charlas_nuevas

AHORA = dt.datetime(2026, 11, 26, 18, 0, tzinfo=dt.UTC)


def test_la_etiqueta_dura_lo_mismo_que_la_lista_de_charlas_nuevas():
    assert catalog.DIAS_NUEVA == charlas_nuevas.DIAS_VISIBLES


def test_marca_el_dia_de_las_vegas_en_que_se_sumo():
    # 24/11 a las 03:00 UTC es todavía el 23/11 en Las Vegas
    assert catalog.agregada(dt.datetime(2026, 11, 24, 3, 0, tzinfo=dt.UTC), AHORA) == "2026-11-23"
    assert catalog.agregada("2026-11-24T20:00:00+00:00", AHORA) == "2026-11-24"


def test_pasados_los_dias_o_sin_alta_ya_no_es_nueva():
    assert catalog.agregada(AHORA - dt.timedelta(days=catalog.DIAS_NUEVA, minutes=1), AHORA) is None
    assert catalog.agregada(AHORA - dt.timedelta(days=catalog.DIAS_NUEVA - 1), AHORA) is not None
    assert catalog.agregada(None, AHORA) is None


def test_la_card_trae_added():
    alta = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    sesion = {"base": "SVS342", "title": "Charla", "alta": alta}
    instancia = {"c": "SVS342", "d": "2026-12-02", "st": "15:30", "v": ""}
    assert catalog.card(sesion, instancia)["added"] == alta.astimezone(catalog.sandbox.EVENT_TZ).date().isoformat()
    assert catalog.card({"base": "X", "title": "Vieja"}, {"c": "X", "v": ""})["added"] is None


def test_si_la_base_no_tiene_la_columna_alta_carga_igual():
    assert "/*ALTA*/" in catalog._LOAD_SQL and "s.alta" in catalog._ALTA

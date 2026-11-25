"""Ofertas: detección de bajas de precio, qué ofertas corresponden avisar y cómo se agrupan. Funciones puras: no usan
base, catálogo ni red (corren en CI)."""
import datetime as dt
from decimal import Decimal

from app import ofertas, ofertas_avisos, sandbox

AHORA = dt.datetime(2026, 12, 1, 10, 0, tzinfo=sandbox.EVENT_TZ)
HORA = 3600
TODAS = frozenset(ofertas.CATEGORIAS)


def _historial(*precios, hace_horas=(18, 12, 6, 0)):
    """[(ts, precio)] con un snapshot cada 6 h terminando ahora."""
    return [(AHORA.timestamp() - h * HORA, Decimal(str(p))) for p, h in zip(precios, hace_horas, strict=False)]


# ---------- bajas de precio ----------

def test_una_baja_de_15_por_ciento_es_oferta():
    assert ofertas.baja_de_precio(_historial(100, 100, 100, 85), AHORA.timestamp()) == (Decimal("100"), Decimal("85"))


def test_una_baja_de_20_dolares_es_oferta_aunque_sea_menos_del_15_por_ciento():
    # 200 -> 178: 11 %, pero US$ 22
    assert ofertas.baja_de_precio(_historial(200, 200, 200, 178), AHORA.timestamp()) == (Decimal("200"), Decimal("178"))


def test_una_baja_chica_no_es_oferta():
    # 100 -> 90: 10 % y US$ 10
    assert ofertas.baja_de_precio(_historial(100, 100, 100, 90), AHORA.timestamp()) is None


def test_justo_en_los_umbrales_cuenta():
    assert ofertas.baja_de_precio(_historial(100, 100, 100, 85), AHORA.timestamp()) is not None  # 15 % exacto
    assert ofertas.baja_de_precio(_historial(500, 500, 500, 480), AHORA.timestamp()) is not None  # US$ 20 exactos


def test_sin_un_precio_anterior_no_hay_oferta():
    assert ofertas.baja_de_precio(_historial(60, hace_horas=(0,)), AHORA.timestamp()) is None
    assert ofertas.baja_de_precio([], AHORA.timestamp()) is None


def test_la_referencia_es_el_maximo_de_los_ultimos_7_dias():
    # subió y bajó: el máximo de la semana (120) es lo que se compara, no el precio de ayer (100)
    assert ofertas.baja_de_precio(_historial(100, 120, 100, 95), AHORA.timestamp()) == (Decimal("120"), Decimal("95"))


def test_un_precio_de_hace_mas_de_7_dias_no_cuenta_como_referencia():
    viejo = [(AHORA.timestamp() - 8 * 24 * HORA, Decimal("300"))]

    assert ofertas.baja_de_precio(viejo + _historial(100, 100, 100, 95), AHORA.timestamp()) is None


def test_si_el_precio_subio_no_es_oferta():
    assert ofertas.baja_de_precio(_historial(100, 100, 100, 140), AHORA.timestamp()) is None


def _funcion(**cambios):
    base = {"id_funcion": "F1", "id_show": "S1", "nombre": "Absinthe", "sala": "Caesars Palace", "url": "https://tm.example/f1",
            "estado": "onsale", "inicio": AHORA + dt.timedelta(days=1), "precio_desde": Decimal("62")}
    return {**base, **cambios}


def test_las_bajas_se_vuelven_ofertas_de_la_categoria_shows():
    historial = {"F1": _historial(89, 89, 89, 62)}

    [o] = ofertas.ofertas_de_bajas([_funcion()], historial, AHORA)

    assert (o.categoria, o.fuente, o.titulo, o.lugar) == ("shows", "ticketmaster", "Absinthe", "Caesars Palace")
    assert (o.precio_antes, o.precio_ahora, o.id_show, o.link) == (Decimal("89"), Decimal("62"), "S1", "https://tm.example/f1")
    assert o.hasta == AHORA + dt.timedelta(days=1)   # vale hasta que empieza la función
    assert o.id == "tm-F1-6200"                       # la misma baja no se repite; una más profunda es otra oferta


def test_sin_precio_en_ticketmaster_no_se_inventa_una_oferta():
    historial = {"F1": _historial(89, 89, 89, 62)}

    assert ofertas.ofertas_de_bajas([_funcion(precio_desde=None)], historial, AHORA) == []


def test_una_funcion_cancelada_o_que_ya_empezo_no_es_oferta():
    historial = {"F1": _historial(89, 89, 89, 62)}

    assert ofertas.ofertas_de_bajas([_funcion(estado="canceled")], historial, AHORA) == []
    assert ofertas.ofertas_de_bajas([_funcion(inicio=AHORA - dt.timedelta(hours=1))], historial, AHORA) == []


# ---------- la fuente Ticketmaster: con y sin precios ----------

def _fuente_sin_base(monkeypatch, funciones):
    """FuenteTicketmaster con las funciones dadas y sin tocar la base: devuelve los snapshots que intentó guardar."""
    guardados = []
    monkeypatch.setattr(ofertas, "guardar_snapshots", lambda fs, _ts: guardados.extend(f["id_funcion"] for f in fs))
    monkeypatch.setattr(ofertas, "historial", lambda ids, _desde: {i: _historial(89, 89, 89, 62) for i in ids})
    return ofertas.FuenteTicketmaster(lambda: funciones), guardados


def test_si_ninguna_funcion_trae_precio_se_avisa_en_el_log_en_vez_de_quedar_en_silencio(monkeypatch, caplog):
    fuente, guardados = _fuente_sin_base(monkeypatch, [_funcion(id_funcion=f"F{i}", precio_desde=None) for i in range(3)])

    with caplog.at_level("WARNING", logger="reinventar.ofertas"):
        assert fuente.ofertas(AHORA) == []

    assert guardados == []
    assert "3 funciones de la semana y ninguna con precio" in caplog.text


def test_solo_las_funciones_con_precio_se_miran_y_sin_aviso_en_el_log(monkeypatch, caplog):
    fuente, guardados = _fuente_sin_base(monkeypatch, [_funcion(), _funcion(id_funcion="F2", precio_desde=None)])

    with caplog.at_level("WARNING", logger="reinventar.ofertas"):
        [o] = fuente.ofertas(AHORA)

    assert (guardados, o.id) == (["F1"], "tm-F1-6200")
    assert "ninguna con precio" not in caplog.text


def test_sin_funciones_en_la_semana_no_se_avisa_que_faltan_precios(monkeypatch, caplog):
    fuente, _ = _fuente_sin_base(monkeypatch, [])

    with caplog.at_level("WARNING", logger="reinventar.ofertas"):
        assert fuente.ofertas(AHORA) == []

    assert "ninguna con precio" not in caplog.text


# ---------- qué ofertas corresponden avisar ----------

def _oferta(id="m-1", categoria="comida", desde=AHORA, hasta=None, creado=None, **cambios):
    return ofertas.Oferta(id=id, fuente="manual", categoria=categoria, titulo=f"Oferta {id}", lugar="Venetian", desde=desde,
                          hasta=hasta, link=None, nota="", id_show=None, precio_antes=None, precio_ahora=None,
                          creado=(creado if creado is not None else desde.timestamp() - HORA), **cambios)


def _ids(lista):
    return [o.id for o in lista]


def test_una_oferta_manual_se_avisa_cuando_arranca_su_vigencia():
    futura = _oferta(desde=AHORA + dt.timedelta(minutes=30))

    assert ofertas_avisos.elegibles([futura], AHORA, TODAS, set()) == []
    assert _ids(ofertas_avisos.elegibles([futura], AHORA + dt.timedelta(minutes=31), TODAS, set())) == ["m-1"]


def test_una_oferta_vencida_no_se_avisa():
    vencida = _oferta(desde=AHORA - dt.timedelta(hours=3), hasta=AHORA - dt.timedelta(minutes=1))

    assert ofertas_avisos.elegibles([vencida], AHORA, TODAS, set()) == []


def test_una_oferta_que_arranco_hace_mucho_no_se_avisa():
    vieja = _oferta(desde=AHORA - dt.timedelta(hours=13))

    assert ofertas_avisos.elegibles([vieja], AHORA, TODAS, set()) == []


def test_una_oferta_cargada_con_la_vigencia_ya_empezada_se_avisa_al_cargarla():
    cargada_ahora = _oferta(desde=AHORA - dt.timedelta(hours=20), creado=AHORA.timestamp() - 60)

    assert _ids(ofertas_avisos.elegibles([cargada_ahora], AHORA, TODAS, set())) == ["m-1"]


def test_las_ya_avisadas_no_se_repiten():
    assert ofertas_avisos.elegibles([_oferta()], AHORA, TODAS, {ofertas_avisos.clave("m-1")}) == []


def test_solo_las_categorias_suscriptas():
    lista = [_oferta("m-1", "comida"), _oferta("m-2", "shows"), _oferta("m-3", "compras")]

    assert _ids(ofertas_avisos.elegibles(lista, AHORA, frozenset({"shows", "compras"}), set())) == ["m-2", "m-3"]
    assert ofertas_avisos.elegibles(lista, AHORA, frozenset(), set()) == []


# ---------- tope diario y agrupado ----------

def _tres():
    return [_oferta(f"m-{i}", desde=AHORA - dt.timedelta(minutes=10 - i)) for i in range(3)]


def test_si_entran_en_el_tope_salen_de_a_una_con_su_link():
    avisos = ofertas_avisos.armar(_tres(), quedan=3)

    assert len(avisos) == 3
    assert avisos[0].mensaje["url"] == "/#/ofertas/m-0"
    assert avisos[0].claves == [ofertas_avisos.clave("m-0")]


def test_si_hay_mas_que_el_tope_van_en_un_solo_push_que_abre_la_lista():
    [aviso] = ofertas_avisos.armar(_tres(), quedan=2)

    assert aviso.mensaje["title"] == "3 ofertas nuevas"
    assert aviso.mensaje["url"] == "/#/ofertas"
    assert aviso.claves == [ofertas_avisos.clave(f"m-{i}") for i in range(3)]


def test_sin_cupo_no_sale_nada():
    assert ofertas_avisos.armar(_tres(), quedan=0) == []


def test_el_texto_del_push_individual_lleva_precio_y_lugar():
    o = ofertas.Oferta(id="tm-F1-6200", fuente="ticketmaster", categoria="shows", titulo="Absinthe", lugar="Caesars Palace",
                       desde=AHORA, hasta=None, link=None, nota="", id_show="S1", precio_antes=Decimal("89"),
                       precio_ahora=Decimal("62"), creado=AHORA.timestamp())

    msg = ofertas_avisos.mensaje(o)

    assert msg["title"] == "Absinthe bajó a US$ 62"
    assert "89" in msg["body"] and "Caesars Palace" in msg["body"]

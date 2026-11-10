"""Eventos de networking: lectura de Luma (pura) y carga en un schema efímero con un resumidor falso."""
import datetime as dt
import json
import os
import uuid

import psycopg
import pytest

from scripts.cargar_eventos import cargar, leer_export, leer_resumenes
from scripts.eventos_fuentes import Evento, _precio, completar_con_pagina_luma, sede_mas_cercana, texto_de_mirror


def _entrada(i="evt-1", nombre="Happy Hour at Topgolf", inicio="2026-12-02T03:00:00.000Z"):
    return {"name": nombre, "start_at": inicio, "timezone": "America/Los_Angeles", "cover_url": f"https://img/{i}.png",
            "coordinate": {"latitude": 36.171563, "longitude": -115.1391009}, "href": f"https://luma.com/{i}",
            "api_id": f"calev-{i}", "platform": "luma", "event_api_id": i}


def _pagina(direccion="Topgolf Las Vegas", ciudad="Las Vegas", tickets=None, descripcion="Join us for drinks."):
    data = {"event": {"end_at": "2026-12-02T06:00:00.000Z", "geo_address_info": {
                "address": direccion, "city": ciudad, "full_address": "4627 Koval Ln, Las Vegas, NV",
                "place_id": "ChIJtopgolf", "place_coordinate": {"latitude": 36.1072, "longitude": -115.1641}}},
            "description_mirror": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": descripcion}]}]},
            "guest_count": 312, "sold_out": False,
            "ticket_types": tickets if tickets is not None else [{"type": "free", "require_approval": True}]}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": {"pageProps": {"initialData": {"data": data}}}})}</script>'


def _evento(**kw):
    return completar_con_pagina_luma(leer_export({"entries": [_entrada()]})[0], _pagina(**kw))


def test_la_pagina_suma_fin_direccion_precio_y_anotados():
    ev = _evento()

    assert (ev.lugar, ev.direccion_exacta, ev.google_place_id) == ("Topgolf Las Vegas", True, "ChIJtopgolf")
    assert (ev.lat, ev.lng) == (36.1072, -115.1641)
    assert ev.fin == dt.datetime(2026, 12, 2, 6, tzinfo=dt.timezone.utc)
    assert (ev.precio, ev.requiere_aprobacion, ev.anotados, ev.descripcion) == ("Gratis", True, 312, "Join us for drinks.")


def test_si_solo_dice_la_ciudad_la_direccion_no_es_exacta():
    ev = _evento(direccion="Las Vegas")

    assert (ev.direccion_exacta, ev.lugar, ev.lat) == (False, None, 36.171563)


def test_pagina_sin_datos_deja_el_evento_como_estaba():
    ev = leer_export({"entries": [_entrada()]})[0]

    assert completar_con_pagina_luma(ev, "<html>sin datos</html>") == ev


def test_precio_toma_la_entrada_paga_mas_barata():
    tickets = [{"type": "free"}, {"type": "paid", "cents": 5000, "currency": "usd"}, {"type": "paid", "cents": 2500, "currency": "usd"}]

    assert _precio(tickets) == ("USD 25", False)


def test_texto_de_mirror_respeta_parrafos_y_listas():
    doc = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Hola"}]},
        {"type": "bullet_list", "content": [{"type": "list_item", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Uno"}]}]}]}]}

    assert texto_de_mirror(doc).strip() == "Hola\n\n- Uno"


def test_sede_mas_cercana():
    ev = Evento("x", "luma", "u", "n", dt.datetime(2026, 12, 1, tzinfo=dt.timezone.utc), lat=36.1216, lng=-115.1691)

    assert sede_mas_cercana(ev, [(5, 36.102219, -115.169517), (7, 36.1216, -115.1691)]) == (7, 0)


def test_resumen_con_tipo_inventado_queda_sin_tipo():
    respuesta = json.dumps({"eventos": [{"id": "a", "resumen_es": "Fiesta.", "tipo": "rave", "temas": ["IA"]}]})

    assert leer_resumenes(respuesta, ["a"])["a"]["tipo"] is None


def test_resumen_faltante_es_un_error():
    with pytest.raises(ValueError, match="faltan"):
        leer_resumenes(json.dumps({"eventos": []}), ["a"])


# ---------- carga ----------

@pytest.fixture
def conn():
    schema = f"ev_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.schema = schema
        yield c
        c.rollback()
        c.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        c.commit()


class ResumidorFalso:
    def __init__(self):
        self.pedidos = []

    def __call__(self, eventos):
        self.pedidos.append([e.id_evento for e in eventos])
        return {e.id_evento: {"resumen_es": f"Resumen de {e.nombre}.", "tipo": "happy hour", "temas": ["datos"],
                              "organizadores": ["Acme"]} for e in eventos}, ()


def test_la_carga_es_idempotente_y_solo_resume_lo_que_cambio(conn):
    resumir = ResumidorFalso()
    eventos = [_evento(), completar_con_pagina_luma(leer_export({"entries": [_entrada("evt-2", "Breakfast")]})[0], _pagina())]

    primera = cargar(conn, eventos, schema=conn.schema, resumir=resumir)
    segunda = cargar(conn, eventos, schema=conn.schema, resumir=resumir)
    cambiado = [eventos[0], completar_con_pagina_luma(eventos[1], _pagina(descripcion="New agenda."))]
    tercera = cargar(conn, cambiado, schema=conn.schema, resumir=resumir)

    assert (primera.nuevos, segunda.actualizados, segunda.sin_cambios) == (2, 0, 2)
    assert resumir.pedidos == [["evt-1", "evt-2"], ["evt-2"]]
    assert tercera.actualizados == 1


def test_la_carga_guarda_la_sede_mas_cercana_y_el_resumen(conn):
    cargar(conn, [_evento()], schema=conn.schema, resumir=ResumidorFalso())

    fila = conn.execute(f"SELECT e.tipo, s.nombre, e.metros_a_sede, e.organizadores FROM {conn.schema}.evento e "
                        f"JOIN {conn.schema}.sede s ON s.id_sede = e.id_sede_cercana").fetchone()
    assert fila[0] == "happy hour" and fila[3] == ["Acme"]
    assert fila[1] == "MGM Grand" and fila[2] < 1000


def test_lo_que_sale_del_export_se_reporta_y_solo_se_borra_si_se_pide(conn):
    cargar(conn, [_evento()], schema=conn.schema)
    otro = completar_con_pagina_luma(leer_export({"entries": [_entrada("evt-9")]})[0], _pagina())

    reporte = cargar(conn, [otro], schema=conn.schema)
    assert reporte.bajas == ("evt-1",)
    cargar(conn, [otro], schema=conn.schema, borrar_bajas=True)

    assert conn.execute(f"SELECT array_agg(id_evento) FROM {conn.schema}.evento").fetchone()[0] == ["evt-9"]

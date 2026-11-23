"""Cargar eventos propios desde un Excel (app/eventos_excel.py, app/eventos_ejemplo.py y POST /api/my-events/excel):
lectura de cada columna, vista previa sin guardar, confirmar sin duplicar y la ida y vuelta con el Excel de ejemplo."""
import datetime as dt
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import db, eventos_ejemplo, eventos_excel, eventos_excel_api, venues
from app.eventos_excel import ArchivoInvalido, leer_dia, leer_eventos, leer_hora
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

SEDES = [{"id": 5, "name": "MGM Grand"}, {"id": 3, "name": "Wynn/Encore"}, {"id": 7, "name": "Venetian"},
         {"id": 2, "name": "Caesars Forum"}]
CABECERA = ("Nombre *", "Día *", "Inicio *", "Fin", "Tipo", "Lugar *", "Dirección", "Link", "Precio", "Notas")


def _xlsx(*filas, cabecera=CABECERA, hoja="Eventos"):
    libro = openpyxl.Workbook()
    libro.active.title = hoja
    libro.active.append(list(cabecera))
    for fila in filas:
        libro.active.append(list(fila))
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def _fila(nombre="Cena", dia="01/12/2026", inicio="19:30", fin=None, tipo=None, lugar="MGM Grand", direccion=None,
          link=None, precio=None, notas=None):
    return (nombre, dia, inicio, fin, tipo, lugar, direccion, link, precio, notas)


def _una(*valores, **kw):
    [fila] = leer_eventos(_xlsx(_fila(*valores, **kw)), "e.xlsx", SEDES)
    return fila


# ---------- día y hora ----------

@pytest.mark.parametrize("valor", [dt.datetime(2026, 12, 1), dt.date(2026, 12, 1), "01/12/2026", "1/12/2026",
                                   "2026-12-01", "01-12-2026", 46357])
def test_lee_el_dia_en_todas_sus_formas(valor):
    assert leer_dia(valor) == "2026-12-01"


@pytest.mark.parametrize("valor", ["28/11/2026", "08/12/2026", "2025-12-01"])
def test_un_dia_fuera_de_la_estadia_es_error(valor):
    with pytest.raises(ValueError, match="entre el 29/11/2026 y el 07/12/2026"):
        leer_dia(valor)


@pytest.mark.parametrize("valor", ["mañana", "31/02/2026", "12/01", 1e20, float("inf"), float("nan"), -1e10, 0])
def test_un_dia_que_no_se_entiende_es_error(valor):
    with pytest.raises(ValueError, match="día"):
        leer_dia(valor)


@pytest.mark.parametrize(("valor", "esperado"), [
    (dt.time(19, 30), "19:30"), (dt.datetime(1899, 12, 30, 7, 5), "07:05"), (0.8125, "19:30"),
    (dt.timedelta(hours=9), "09:00"), ("19:30", "19:30"), ("7:30", "07:30"), ("19:30:00", "19:30"),
    ("7:30 PM", "19:30"), ("7:30pm", "19:30"), ("7 pm", "19:00"), ("12:15 AM", "00:15"), ("12 PM", "12:00"),
    ("7:30 a.m.", "07:30"), ("19.30", "19:30")])
def test_lee_la_hora_en_todas_sus_formas(valor, esperado):
    assert leer_hora(valor) == esperado


@pytest.mark.parametrize("valor", ["25:00", "19:75", "13 PM", "a la tarde", "", "7m", "7:30 m", float("inf")])
def test_una_hora_que_no_se_entiende_es_error(valor):
    with pytest.raises(ValueError, match="hora"):
        leer_hora(valor)


# ---------- filas ----------

def test_una_fila_completa_en_una_sede_toma_la_sede_y_arma_la_nota():
    fila = _una(tipo="Meetup tecnico", lugar="mgm grand", link="https://example.com/x", precio="Gratis",
                notas="Llevar tarjetas", fin="22:00")

    assert fila.error is None
    ev = fila.evento
    assert (ev.nombre, ev.dia, ev.inicio, ev.fin, ev.id_sede) == ("Cena", "2026-12-01", "19:30", "22:00", 5)
    assert (fila.lugar, fila.sede) == ("MGM Grand", True)
    assert ev.nota == "Tipo: meetup técnico\nPrecio: Gratis\nLink: https://example.com/x\nLlevar tarjetas"


def test_una_parte_del_nombre_de_la_sede_tambien_la_reconoce():
    assert _una(lugar="Encore").evento.id_sede == 3


def test_un_lugar_que_no_es_sede_queda_como_texto_y_la_direccion_va_a_la_nota():
    fila = _una(lugar="Rooftop sobre el Strip", direccion="255 Sands Ave")

    assert (fila.evento.id_sede, fila.evento.direccion, fila.lugar, fila.sede) == (None, "Rooftop sobre el Strip",
                                                                                   "Rooftop sobre el Strip", False)
    assert fila.evento.nota == "Dirección: 255 Sands Ave"


def test_un_fin_menor_que_el_inicio_termina_al_dia_siguiente():
    fila = _una(inicio="22:00", fin="1:00 AM")

    assert fila.evento.fin == eventos_excel.FIN_DEL_DIA
    assert fila.evento.nota == "Termina al día siguiente, a las 01:00."


@pytest.mark.parametrize(("kw", "motivo"), [
    ({"nombre": None, "lugar": ""}, "Falta Nombre, Lugar"),
    ({"dia": None}, "Falta Día"),
    ({"inicio": None}, "Falta Inicio"),
    ({"dia": "10/12/2026"}, "entre el 29/11/2026"),
    ({"inicio": "tarde"}, "No entiendo la hora"),
    ({"link": "http://example.com"}, "https://"),
    ({"link": "javascript:alert(1)"}, "https://"),
    ({"tipo": "boliche"}, "Tipo «boliche» desconocido"),
    ({"nombre": "x" * 121}, "120"),
    ({"fin": "19:30"}, "igual al inicio"),
    ({"notas": "x" * 490, "precio": "USD 40"}, "500"),
])
def test_las_filas_que_no_sirven_dicen_por_que(kw, motivo):
    fila = _una(**kw)
    assert fila.evento is None
    assert motivo in fila.error


def test_detecta_la_cabecera_por_nombre_en_cualquier_orden_y_sin_tildes():
    cabecera = ("NOTAS", "lugar", "INICIO*", "dia (dd/mm/aaaa)", "nombre")
    datos = _xlsx(("Ojo", "Venetian", "8:00", "02/12/2026", "Desayuno"), cabecera=cabecera)

    [fila] = leer_eventos(datos, "e.xlsx", SEDES)

    assert (fila.evento.nombre, fila.evento.dia, fila.evento.inicio, fila.evento.nota) == (
        "Desayuno", "2026-12-02", "08:00", "Ojo")


def test_la_cabecera_puede_estar_debajo_de_un_titulo_y_se_saltean_las_filas_vacias():
    libro = openpyxl.Workbook()
    for fila in (["Mis eventos de re:Invent"], [], list(CABECERA), _fila(), [], _fila(nombre="Otra")):
        libro.active.append(list(fila))
    salida = io.BytesIO()
    libro.save(salida)

    filas = leer_eventos(salida.getvalue(), "e.xlsx", SEDES)

    assert [(f.numero, f.evento.nombre) for f in filas] == [(4, "Cena"), (6, "Otra")]


def test_lee_un_csv_con_punto_y_coma():
    datos = "Nombre;Día;Inicio;Lugar\nCena;01/12/2026;7:30 PM;Venetian\n".encode()
    [fila] = leer_eventos(datos, "eventos.csv", SEDES)
    assert (fila.evento.inicio, fila.evento.id_sede) == ("19:30", 7)


def test_una_fila_repetida_en_el_mismo_archivo_es_error():
    filas = leer_eventos(_xlsx(_fila(), _fila(nombre="  CENA ")), "e.xlsx", SEDES)
    assert filas[0].error is None
    assert "fila 2" in filas[1].error


def test_una_hora_sin_minutos_ni_am_pm_es_ambigua():
    with pytest.raises(ValueError, match="ambigua: escribí 07:00, 19:00 o 7 PM"):
        leer_hora("7")
    assert (leer_hora("19"), leer_hora("0"), leer_hora("7 PM")) == ("19:00", "00:00", "19:00")


def test_un_dia_numerico_enorme_es_un_error_de_la_fila_y_no_rompe():
    fila = _una(dia=1e20)
    assert fila.evento is None
    assert "No entiendo el día" in fila.error


def test_el_id_no_depende_de_mayusculas_ni_espacios():
    assert eventos_excel.id_de("Cena  Bienvenida", "2026-12-01", "19:30") == eventos_excel.id_de(
        " cena bienvenida", "2026-12-01", "19:30")
    assert eventos_excel.id_de("Cena", "2026-12-01", "19:30") != eventos_excel.id_de("Cena", "2026-12-01", "20:00")


def test_el_id_distingue_nombres_que_no_son_ascii():
    assert eventos_excel.id_de("会議", "2026-12-01", "19:30") != eventos_excel.id_de("夕食", "2026-12-01", "19:30")
    assert eventos_excel.id_de("Cena", "2026-12-01", "19:30") != eventos_excel.id_de("Céna", "2026-12-01", "19:30")
    assert eventos_excel.id_de("ＣＥＮＡ", "2026-12-01", "19:30") == eventos_excel.id_de("cena", "2026-12-01", "19:30")


def test_dos_filas_con_nombres_en_otro_alfabeto_no_chocan():
    filas = leer_eventos(_xlsx(_fila(nombre="会議"), _fila(nombre="夕食")), "e.xlsx", SEDES)
    assert [f.error for f in filas] == [None, None]


@pytest.mark.parametrize(("datos", "nombre", "motivo"), [
    (b"", "e.xlsx", "vacío"),
    (b"x", "e.txt", ".xlsx o .csv"),
    (b"no es un zip", "e.xlsx", "Excel"),
    (b"Nombre,Lugar\nCena,Venetian\n", "e.csv", "cabecera"),
    (b"Nombre,Dia,Inicio,Lugar\n", "e.csv", "no tiene eventos"),
])
def test_los_archivos_que_no_sirven_dan_un_error_claro(datos, nombre, motivo):
    with pytest.raises(ArchivoInvalido, match=motivo):
        leer_eventos(datos, nombre, SEDES)


def test_tope_de_cien_eventos():
    filas = [_fila(nombre=f"Evento {i}") for i in range(eventos_excel.MAX_EVENTOS)]
    assert len(leer_eventos(_xlsx(*filas), "e.xlsx", SEDES)) == eventos_excel.MAX_EVENTOS
    with pytest.raises(ArchivoInvalido, match="más de 100"):
        leer_eventos(_xlsx(*filas, _fila(nombre="Uno más")), "e.xlsx", SEDES)


# ---------- estado contra lo guardado ----------

def test_estado_nueva_sin_cambios_y_actualiza():
    fila = _una(notas="Hola")
    guardado = {"nombre": "Cena", "dia": "2026-12-01", "inicio": "19:30", "fin": None, "nota": "Hola", "id_sede": 5,
                "lugar": "MGM Grand"}

    assert eventos_excel.estado(fila, None) == "nueva"
    assert eventos_excel.estado(fila, guardado) == "sin_cambios"
    assert eventos_excel.estado(fila, {**guardado, "nota": "Otra"}) == "actualiza"
    assert eventos_excel.estado(fila, guardado, en_itinerario=False) == "vuelve"
    assert eventos_excel.estado(_una(lugar="tarde", inicio="x"), None) == "error"


# ---------- el Excel de ejemplo ----------

def test_el_ejemplo_tiene_la_hoja_de_eventos_primero_y_las_instrucciones_aparte():
    libro = openpyxl.load_workbook(io.BytesIO(eventos_ejemplo.generar()))
    assert libro.sheetnames == [eventos_ejemplo.HOJA_EVENTOS, eventos_ejemplo.HOJA_INSTRUCCIONES]
    assert [c.value for c in libro[eventos_ejemplo.HOJA_EVENTOS][1]] == list(CABECERA)


def test_el_ejemplo_subido_tal_cual_da_seis_eventos_sin_errores():
    filas = leer_eventos(eventos_ejemplo.generar(), eventos_ejemplo.NOMBRE, SEDES)

    assert len(filas) == len(eventos_ejemplo.FILAS) == 6
    assert [f.error for f in filas] == [None] * 6
    assert [f.sede for f in filas] == [True, True, True, False, True, False]


def test_los_tipos_del_ejemplo_son_los_que_lee_la_app():
    assert eventos_ejemplo.TIPOS == eventos_excel.TIPOS
    assert {fila[4] for fila in eventos_ejemplo.FILAS} <= set(eventos_excel.TIPOS)


# ---------- API ----------

@pytest.fixture
def client(monkeypatch):
    with TestClient(app) as c:
        monkeypatch.setattr(venues, "_by_id", venues._by_id)  # se restaura al terminar: load los reemplaza
        monkeypatch.setattr(venues, "_venues", venues._venues)
        venues.load([{"id_sede": s["id"], "nombre": s["name"], "lat": 36.1, "lng": -115.1, "direccion": "Strip"}
                     for s in SEDES])
        eventos_excel_api._subidas.reiniciar()
        _limpiar()
        yield c
        _limpiar()


def _limpiar():
    for usuario in (TEST_USER, TEST_ADMIN):
        for ev in db.list_user_events(usuario):
            db.delete_user_event(usuario, ev["id"])
        for it in db.list_itinerary_items(usuario):
            db.remove_item(usuario, it["code"])


@pytest.fixture
def H(client):
    return login_headers(client)


def _subir(client, H, datos, confirmar=False, nombre="eventos.xlsx"):
    params = {"nombre": nombre, **({"confirmar": "1"} if confirmar else {})}
    return client.post("/api/my-events/excel", params=params, headers=H, content=datos)


def test_la_api_pide_sesion(client):
    assert client.post("/api/my-events/excel", content=b"x").status_code == 401
    assert client.get("/api/my-events/excel/ejemplo.xlsx").status_code == 401


def test_la_vista_previa_no_guarda_y_confirmar_si(client, H):
    datos = eventos_ejemplo.generar()

    previa = _subir(client, H, datos)
    assert previa.status_code == 200, previa.text
    assert previa.json()["guardado"] is False
    assert previa.json()["resumen"] == {"nueva": 6, "actualiza": 0, "vuelve": 0, "sin_cambios": 0, "error": 0}
    assert db.list_user_events(TEST_USER) == []

    confirmado = _subir(client, H, datos, confirmar=True)
    assert confirmado.json()["guardado"] is True
    eventos = client.get("/api/my-events", headers=H).json()["eventos"]
    assert len(eventos) == 6
    mgm = next(e for e in eventos if e["venue"]["hotel"] == "MGM Grand")
    assert (mgm["venue"]["lat"], mgm["venue"]["id_sede"]) == (36.1, 5)
    codigos = {it["code"] for it in db.list_itinerary_items(TEST_USER)}
    assert {e["code"] for e in eventos} <= codigos  # quedan fijados en el itinerario


def test_el_mismo_archivo_dos_veces_no_duplica_y_una_fila_editada_actualiza(client, H):
    _subir(client, H, _xlsx(_fila(), _fila(nombre="Desayuno", inicio="8:00")), confirmar=True)

    otra_vez = _subir(client, H, _xlsx(_fila(), _fila(nombre="Desayuno", inicio="8:00", notas="Cambió")),
                      confirmar=True).json()

    assert [f["estado"] for f in otra_vez["filas"]] == ["sin_cambios", "actualiza"]
    eventos = db.list_user_events(TEST_USER)
    assert len(eventos) == 2
    assert next(e for e in eventos if e["nombre"] == "Desayuno")["nota"] == "Cambió"


def test_si_lo_sacaron_del_itinerario_se_vuelve_a_fijar_al_confirmar(client, H):
    datos = _xlsx(_fila())
    _subir(client, H, datos, confirmar=True)
    [ev] = db.list_user_events(TEST_USER)
    db.remove_item(TEST_USER, "mine-" + ev["id"])

    previa = _subir(client, H, datos).json()
    assert previa["filas"][0]["estado"] == "vuelve"
    assert previa["resumen"]["vuelve"] == 1
    assert db.list_itinerary_items(TEST_USER) == []

    _subir(client, H, datos, confirmar=True)
    assert [it["code"] for it in db.list_itinerary_items(TEST_USER)] == ["mine-" + ev["id"]]
    assert _subir(client, H, datos).json()["filas"][0]["estado"] == "sin_cambios"


def test_lo_que_ya_no_esta_en_un_archivo_posterior_se_conserva_y_las_filas_con_error_no_se_guardan(client, H):
    _subir(client, H, _xlsx(_fila(), _fila(nombre="Desayuno", inicio="8:00")), confirmar=True)

    r = _subir(client, H, _xlsx(_fila(nombre="Almuerzo", inicio="13:00"), _fila(nombre="Roto", dia="1/1/2027")),
               confirmar=True).json()

    assert [(f["fila"], f["estado"]) for f in r["filas"]] == [(2, "nueva"), (3, "error")]
    assert sorted(e["nombre"] for e in db.list_user_events(TEST_USER)) == ["Almuerzo", "Cena", "Desayuno"]


def test_los_eventos_de_cada_usuario_quedan_aislados(client, H):
    otro = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    _subir(client, H, _xlsx(_fila()), confirmar=True)

    previa_del_otro = _subir(client, otro, _xlsx(_fila())).json()

    assert previa_del_otro["filas"][0]["estado"] == "nueva"  # el mismo id, pero de otra persona
    assert client.get("/api/my-events", headers=otro).json()["eventos"] == []
    _subir(client, otro, _xlsx(_fila(notas="Mía")), confirmar=True)
    assert db.list_user_events(TEST_USER)[0]["nota"] == ""
    assert db.list_user_events(TEST_ADMIN)[0]["nota"] == "Mía"


@pytest.mark.parametrize(("datos", "nombre"), [(b"", "e.xlsx"), (b"x", "e.pdf"), (b"Nombre\nCena\n", "e.csv")])
def test_un_archivo_que_no_sirve_da_422(client, H, datos, nombre):
    r = _subir(client, H, datos, nombre=nombre)
    assert r.status_code == 422
    assert r.json()["detail"]


def test_mas_de_un_mega_da_413_o_422(client, H):
    r = _subir(client, H, b"x" * (eventos_excel.MAX_BYTES + 1), nombre="e.csv")
    assert r.status_code in (413, 422)


def test_el_cupo_de_subidas_da_429(client, H):
    datos = _xlsx(_fila())
    for _ in range(eventos_excel_api.SUBIDAS_POR_HORA):
        assert _subir(client, H, datos).status_code == 200
    r = _subir(client, H, datos)
    assert r.status_code == 429
    assert "muchos pedidos" in r.json()["detail"]


def test_baja_el_excel_de_ejemplo(client, H):
    r = client.get("/api/my-events/excel/ejemplo.xlsx", headers=H)
    assert r.status_code == 200
    assert r.headers["content-type"] == eventos_ejemplo.MEDIA_TYPE
    assert eventos_ejemplo.NOMBRE in r.headers["content-disposition"]
    assert len(leer_eventos(r.content, eventos_ejemplo.NOMBRE, SEDES)) == 6

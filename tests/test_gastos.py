"""Control de gastos (app/gastos.py, app/gastos_api.py): sync idempotente, conflictos, borrado lógico, aislamiento entre
personas, conversión ARS→USD con cotización congelada, totales, export CSV, fotos y validaciones. Sin red ni catálogo."""
import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import db, gastos, gastos_api, limites
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

# Relativo a hoy: el servidor recorta los updated_at adelantados (reloj mal puesto), así que no puede ser una fecha futura.
T0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=3)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"\r\n\n\x00\xff" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 20


def entrada(**kw):
    base = {"client_id": str(uuid.uuid4()), "fecha": "2026-12-01", "monto": 10, "moneda": "USD",
            "categoria": "comida", "nota": "", "reintegrable": False, "compartido": False,
            "updated_at": T0.isoformat(), "deleted_at": None}
    return {**base, **kw}


def _limpiar():
    with db.conn() as c:
        c.execute("DELETE FROM gastos")
        c.execute("DELETE FROM gastos_presupuesto")
        c.execute("DELETE FROM cotizaciones")


def poner_cotizacion(oficial=1000, blue=1200, tarjeta=1300):
    with db.conn() as c:
        c.execute("INSERT INTO cotizaciones (oficial, blue, tarjeta) VALUES (%s, %s, %s)", (oficial, blue, tarjeta))


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.TICKETS_DIR", tmp_path)
    with TestClient(app) as c:
        c.A = login_headers(c)
        c.B = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        limites.reiniciar_todo()
        gastos_api._syncs.reiniciar()
        gastos_api._fotos.reiniciar()
        _limpiar()
        poner_cotizacion()
        yield c
        _limpiar()


def sync(cli, headers, *cambios, desde=None):
    r = cli.post("/api/gastos/sync", headers=headers, json={"cambios": list(cambios), "desde": desde})
    assert r.status_code == 200, r.text
    return r.json()


def foto(cli, headers, client_id, datos=JPEG, tipo="image/jpeg", campo="foto"):
    return cli.post(f"/api/gastos/{client_id}/foto", headers=headers, files={campo: ("lo-que-sea.exe", datos, tipo)})


def borrar(cli, g, headers=None):
    marca = (T0 + timedelta(hours=1)).isoformat()
    return sync(cli, headers or cli.A, {**g, "updated_at": marca, "deleted_at": marca})


# ---------- sync ----------

def test_sync_crea_el_gasto_y_congela_las_tres_cotizaciones(cli):
    g = entrada(monto=13000, moneda="ARS")
    r = sync(cli, cli.A, g)
    assert r["aplicados"] == [g["client_id"]]
    creado = r["cambios"][0]
    assert (creado["cotizacion_oficial"], creado["cotizacion_blue"], creado["cotizacion_tarjeta"]) == (1000, 1200, 1300)
    assert creado["monto_usd"] == 10.0  # 13000 ARS / 1300 de tarjeta


def test_un_gasto_en_dolares_no_se_convierte(cli):
    r = sync(cli, cli.A, entrada(monto=25.5, moneda="USD"))
    assert r["cambios"][0]["monto_usd"] == 25.5


def test_la_cotizacion_congelada_no_cambia_cuando_el_dolar_se_mueve(cli):
    viejo = entrada(monto=13000, moneda="ARS")
    sync(cli, cli.A, viejo)
    poner_cotizacion(oficial=2000, blue=2400, tarjeta=2600)
    nuevo = entrada(monto=13000, moneda="ARS")
    sync(cli, cli.A, nuevo)
    por_id = {g["client_id"]: g for g in cli.get("/api/gastos", headers=cli.A).json()["gastos"]}
    assert por_id[viejo["client_id"]]["monto_usd"] == 10.0 and por_id[viejo["client_id"]]["cotizacion_tarjeta"] == 1300
    assert por_id[nuevo["client_id"]]["monto_usd"] == 5.0 and por_id[nuevo["client_id"]]["cotizacion_tarjeta"] == 2600


def test_editar_el_monto_usa_la_cotizacion_congelada_del_gasto(cli):
    g = entrada(monto=13000, moneda="ARS")
    sync(cli, cli.A, g)
    poner_cotizacion(tarjeta=2600)
    r = sync(cli, cli.A, {**g, "monto": 26000, "updated_at": (T0 + timedelta(hours=1)).isoformat()})
    assert r["cambios"][0]["monto_usd"] == 20.0 and r["cambios"][0]["cotizacion_tarjeta"] == 1300


def test_reenviar_lo_mismo_no_duplica(cli):
    g = entrada()
    sync(cli, cli.A, g)
    r = sync(cli, cli.A, g)
    assert r["aplicados"] == [g["client_id"]]
    assert len(cli.get("/api/gastos", headers=cli.A).json()["gastos"]) == 1


def test_gana_el_updated_at_mas_nuevo_y_el_perdedor_vuelve_con_la_version_del_servidor(cli):
    g = entrada(monto=10)
    sync(cli, cli.A, g)
    viejo = sync(cli, cli.A, {**g, "monto": 99, "updated_at": (T0 - timedelta(hours=1)).isoformat()},
                 desde=datetime.now(UTC).isoformat())
    assert viejo["aplicados"] == []
    assert [c["monto"] for c in viejo["cambios"]] == [10.0]  # llega aunque sea anterior a 'desde'
    nuevo = sync(cli, cli.A, {**g, "monto": 30, "updated_at": (T0 + timedelta(hours=1)).isoformat()})
    assert nuevo["aplicados"] == [g["client_id"]]
    assert cli.get("/api/gastos", headers=cli.A).json()["gastos"][0]["monto"] == 30.0


def test_un_reloj_adelantado_no_gana_para_siempre(cli):
    g = entrada()
    r = sync(cli, cli.A, {**g, "updated_at": "2099-01-01T00:00:00Z"})
    assert datetime.fromisoformat(r["cambios"][0]["updated_at"]) < datetime.now(UTC) + timedelta(hours=1)


def test_borrado_logico_sale_de_la_lista_y_de_los_totales_pero_viaja_en_el_sync(cli):
    g = entrada(monto=10)
    primero = sync(cli, cli.A, g)
    marca = (T0 + timedelta(hours=1)).isoformat()
    r = sync(cli, cli.A, {**g, "updated_at": marca, "deleted_at": marca}, desde=primero["ahora"])
    assert r["cambios"][0]["deleted_at"] is not None
    listado = cli.get("/api/gastos", headers=cli.A).json()
    assert listado["gastos"] == [] and listado["totales"]["usd"] == 0
    with db.conn() as c:  # sigue en la base
        assert c.execute("SELECT count(*) AS n FROM gastos").fetchone()["n"] == 1


def test_sync_devuelve_solo_lo_modificado_desde(cli):
    primero = sync(cli, cli.A, entrada())
    assert len(primero["cambios"]) == 1
    assert sync(cli, cli.A, desde=primero["ahora"])["cambios"] == []
    otro = entrada()
    assert [c["client_id"] for c in sync(cli, cli.A, otro, desde=primero["ahora"])["cambios"]] == [otro["client_id"]]


def test_un_gasto_de_otro_dispositivo_llega_con_desde_nulo(cli):
    sync(cli, cli.A, entrada(), entrada())
    assert len(sync(cli, cli.A, desde=None)["cambios"]) == 2


def test_sync_acepta_a_lo_sumo_200_cambios(cli):
    r = cli.post("/api/gastos/sync", headers=cli.A, json={"cambios": [entrada() for _ in range(201)], "desde": None})
    assert r.status_code == 422


def test_sync_tiene_limite_de_pedidos(cli, monkeypatch):
    monkeypatch.setattr(gastos_api, "_syncs", limites.Limite(2, 60))
    sync(cli, cli.A)
    sync(cli, cli.A)
    assert cli.post("/api/gastos/sync", headers=cli.A, json={"cambios": [], "desde": None}).status_code == 429


# ---------- aislamiento ----------

def test_cada_persona_ve_solo_sus_gastos_y_su_foto(cli):
    g = entrada(reintegrable=True, compartido=True)
    sync(cli, cli.A, g)
    assert foto(cli, cli.A, g["client_id"]).status_code == 200
    assert cli.get("/api/gastos", headers=cli.B).json()["gastos"] == []
    assert cli.get("/api/gastos/compartidos", headers=cli.B).json()["gastos"] == []
    assert cli.get(f"/api/gastos/{g['client_id']}/foto", headers=cli.B).status_code == 404
    assert foto(cli, cli.B, g["client_id"]).status_code == 404
    assert "comida" not in cli.get("/api/gastos/export.csv", headers=cli.B).text
    assert cli.get(f"/api/gastos/{g['client_id']}/foto", headers=cli.A).status_code == 200


def test_el_mismo_client_id_en_dos_cuentas_son_dos_gastos_y_B_no_pisa_a_A(cli):
    g = entrada(monto=10)
    sync(cli, cli.A, g)
    sync(cli, cli.B, {**g, "monto": 77, "updated_at": (T0 + timedelta(days=1)).isoformat()})
    assert cli.get("/api/gastos", headers=cli.A).json()["gastos"][0]["monto"] == 10.0
    assert cli.get("/api/gastos", headers=cli.B).json()["gastos"][0]["monto"] == 77.0


@pytest.mark.parametrize(("metodo", "ruta"), [("get", "/api/gastos"), ("get", "/api/gastos/cotizacion"),
                                              ("post", "/api/gastos/sync"), ("get", "/api/gastos/export.csv"),
                                              ("get", "/api/gastos/compartidos"), ("put", "/api/gastos/presupuesto"),
                                              ("get", f"/api/gastos/{uuid.uuid4()}/foto")])
def test_todo_exige_sesion(cli, metodo, ruta):
    assert getattr(cli, metodo)(ruta).status_code == 401


# ---------- lectura y totales ----------

def test_totales_por_dia_y_por_categoria_en_usd(cli):
    sync(cli, cli.A,
         entrada(monto=10, fecha="2026-12-01", categoria="comida"),
         entrada(monto=13000, moneda="ARS", fecha="2026-12-01", categoria="comida"),
         entrada(monto=5, fecha="2026-12-02", categoria="shows"))
    t = cli.get("/api/gastos", headers=cli.A).json()["totales"]
    assert t == {"usd": 25.0, "por_categoria": {"comida": 20.0, "shows": 5.0},
                 "por_dia": {"2026-12-01": 20.0, "2026-12-02": 5.0}}


def test_el_listado_se_filtra_por_rango_de_fechas(cli):
    sync(cli, cli.A, entrada(fecha="2026-12-01"), entrada(fecha="2026-12-03"), entrada(fecha="2026-12-05"))
    r = cli.get("/api/gastos", headers=cli.A, params={"desde": "2026-12-02", "hasta": "2026-12-04"}).json()
    assert [g["fecha"] for g in r["gastos"]] == ["2026-12-03"] and r["totales"]["usd"] == 10.0


def test_cotizacion_actual(cli):
    r = cli.get("/api/gastos/cotizacion", headers=cli.A).json()
    assert (r["oficial"], r["blue"], r["tarjeta"]) == (1000, 1200, 1300) and r["at"]


def test_presupuesto_se_guarda_y_viaja_en_el_listado(cli):
    assert cli.get("/api/gastos", headers=cli.A).json()["presupuesto"] == {"total_usd": None, "diario_usd": None,
                                                                          "por_categoria": {}}
    cuerpo = {"total_usd": 1500, "diario_usd": 200, "por_categoria": {"comida": 400.5}}
    assert cli.put("/api/gastos/presupuesto", headers=cli.A, json=cuerpo).status_code == 200
    assert cli.get("/api/gastos", headers=cli.A).json()["presupuesto"] == cuerpo
    assert cli.get("/api/gastos", headers=cli.B).json()["presupuesto"]["total_usd"] is None


@pytest.mark.parametrize("cuerpo", [{"total_usd": -1, "diario_usd": 1, "por_categoria": {}},
                                    {"total_usd": 1, "diario_usd": 1, "por_categoria": {"joyas": 5}},
                                    {"total_usd": 1, "diario_usd": 1, "por_categoria": {"comida": -5}}])
def test_presupuesto_invalido(cli, cuerpo):
    assert cli.put("/api/gastos/presupuesto", headers=cli.A, json=cuerpo).status_code == 422


def test_compartidos_lista_solo_los_marcados_y_no_borrados_con_su_total(cli):
    quitado = entrada(compartido=True)
    sync(cli, cli.A, entrada(monto=10, compartido=True), entrada(monto=5, compartido=False), quitado)
    borrar(cli, quitado)
    r = cli.get("/api/gastos/compartidos", headers=cli.A).json()
    assert len(r["gastos"]) == 1 and r["total_usd"] == 10.0


# ---------- export ----------

def test_el_csv_trae_solo_reintegrables_no_borrados_con_bom_y_link_absoluto(cli):
    con_foto = entrada(monto=13000, moneda="ARS", categoria="transporte", nota="Uber al Venetian", reintegrable=True)
    quitado = entrada(reintegrable=True, nota="borrado")
    sync(cli, cli.A, con_foto, quitado, entrada(nota="personal", reintegrable=False))
    borrar(cli, quitado)
    foto(cli, cli.A, con_foto["client_id"])
    r = cli.get("/api/gastos/export.csv", headers=cli.A)
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    assert r.content.startswith(b"\xef\xbb\xbf")
    filas = r.content.decode("utf-8-sig").splitlines()
    assert len(filas) == 2  # encabezado + el único reintegrable vigente
    assert filas[1] == (f"2026-12-01;transporte - Uber al Venetian;ARS;13000,00;10,00;1300,0000;"
                        f"http://testserver/api/gastos/{con_foto['client_id']}/foto")


def test_el_csv_neutraliza_celdas_que_excel_leeria_como_formula(cli):
    sync(cli, cli.A, entrada(nota='=HYPERLINK("http://x")', reintegrable=True))
    texto = cli.get("/api/gastos/export.csv", headers=cli.A).content.decode("utf-8-sig")
    concepto = list(csv.reader(io.StringIO(texto), delimiter=";"))[1][1]
    assert concepto == 'comida - =HYPERLINK("http://x")'  # arranca con la categoría: nunca con = + - @
    assert gastos._celda("=1+1") == "'=1+1" and gastos._celda("-5") == "'-5" and gastos._celda("comida") == "comida"


# ---------- validaciones ----------

@pytest.mark.parametrize("cambio", [{"monto": -5}, {"monto": 0}, {"monto": "abc"}, {"monto": 0.004}, {"monto": 1e12},
                                    {"moneda": "EUR"}, {"categoria": "joyas"}, {"fecha": "2026-13-45"},
                                    {"nota": "x" * 501}, {"client_id": "no-es-uuid"},
                                    {"updated_at": "2026-12-01T10:00:00"}],  # sin zona horaria
                         ids=["negativo", "cero", "texto", "menos-de-un-centavo", "enorme", "moneda", "categoria",
                              "fecha", "nota-larga", "client_id", "sin-zona"])
def test_sync_rechaza_gastos_invalidos(cli, cambio):
    r = cli.post("/api/gastos/sync", headers=cli.A, json={"cambios": [entrada(**cambio)], "desde": None})
    assert r.status_code == 422
    assert cli.get("/api/gastos", headers=cli.A).json()["gastos"] == []


def test_el_monto_se_redondea_a_centavos(cli):
    assert sync(cli, cli.A, entrada(monto=12.345))["cambios"][0]["monto"] == 12.35


def test_los_campos_que_decide_el_servidor_se_ignoran(cli):
    r = sync(cli, cli.A, entrada(monto_usd=999, cotizacion_tarjeta=1, foto_url="/x"))["cambios"][0]
    assert r["monto_usd"] == 10.0 and r["cotizacion_tarjeta"] == 1300 and r["foto_url"] is None


# ---------- fotos ----------

@pytest.mark.parametrize(("datos", "tipo"), [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")])
def test_la_foto_se_guarda_y_vuelve_igual(cli, datos, tipo):
    g = entrada()
    sync(cli, cli.A, g)
    r = foto(cli, cli.A, g["client_id"], datos, tipo)
    assert r.status_code == 200 and r.json() == {"foto_url": f"/api/gastos/{g['client_id']}/foto"}
    vuelta = cli.get(r.json()["foto_url"], headers=cli.A)
    assert vuelta.content == datos and vuelta.headers["content-type"] == tipo
    assert vuelta.headers["x-content-type-options"] == "nosniff"
    assert cli.get("/api/gastos", headers=cli.A).json()["gastos"][0]["foto_url"] == r.json()["foto_url"]


def test_la_clave_del_objeto_sale_del_usuario_y_el_client_id_no_del_nombre_del_cliente(cli, tmp_path):
    g = entrada()
    sync(cli, cli.A, g)
    foto(cli, cli.A, g["client_id"])
    assert [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()] == [
        f"tickets/{TEST_USER}/{g['client_id']}.jpg"]


def test_cambiar_la_foto_por_otro_formato_borra_la_anterior(cli, tmp_path):
    g = entrada()
    sync(cli, cli.A, g)
    foto(cli, cli.A, g["client_id"], JPEG, "image/jpeg")
    foto(cli, cli.A, g["client_id"], PNG, "image/png")
    assert [p.suffix for p in tmp_path.rglob("*") if p.is_file()] == [".png"]


def test_sincronizar_despues_no_pisa_la_foto(cli):
    g = entrada()
    sync(cli, cli.A, g)
    foto(cli, cli.A, g["client_id"])
    r = sync(cli, cli.A, {**g, "monto": 11, "updated_at": (T0 + timedelta(hours=1)).isoformat()})
    assert r["cambios"][0]["foto_url"] == f"/api/gastos/{g['client_id']}/foto"


@pytest.mark.parametrize(("datos", "tipo"), [(b"esto es texto, no una imagen", "image/jpeg"),
                                             (b"GIF89a" + b"\x00" * 20, "image/gif"),
                                             (PNG, "image/jpeg"),                       # declara una cosa y es otra
                                             (b"<html><script>1</script>", "image/png")],
                         ids=["texto", "gif", "tipo-no-coincide", "html"])
def test_la_foto_que_no_es_imagen_se_rechaza_por_sus_bytes(cli, datos, tipo):
    g = entrada()
    sync(cli, cli.A, g)
    assert foto(cli, cli.A, g["client_id"], datos, tipo).status_code == 415
    assert cli.get(f"/api/gastos/{g['client_id']}/foto", headers=cli.A).status_code == 404


def test_la_foto_de_mas_de_2_mb_se_rechaza(cli):
    g = entrada()
    sync(cli, cli.A, g)
    grande = JPEG + b"\x00" * (2 * 1024 * 1024)
    assert foto(cli, cli.A, g["client_id"], grande).status_code == 413
    justo = JPEG + b"\x00" * (2 * 1024 * 1024 - len(JPEG))
    assert foto(cli, cli.A, g["client_id"], justo).status_code == 200


def test_la_foto_sin_el_campo_foto_es_un_error_claro(cli):
    g = entrada()
    sync(cli, cli.A, g)
    assert foto(cli, cli.A, g["client_id"], campo="archivo").status_code == 422
    assert cli.post(f"/api/gastos/{g['client_id']}/foto", headers=cli.A, content=JPEG).status_code == 422


def test_foto_de_un_gasto_que_no_existe_o_esta_borrado(cli):
    assert foto(cli, cli.A, uuid.uuid4()).status_code == 404
    g = entrada()
    sync(cli, cli.A, g)
    borrar(cli, g)
    assert foto(cli, cli.A, g["client_id"]).status_code == 404


def test_si_el_almacen_falla_responde_502_y_no_guarda_la_clave(cli, monkeypatch):
    class Roto:
        def guardar(self, *args):
            raise OSError("disco lleno")

    monkeypatch.setattr("app.tickets_almacen.obtener", lambda: Roto())
    g = entrada()
    sync(cli, cli.A, g)
    assert foto(cli, cli.A, g["client_id"]).status_code == 502
    assert cli.get("/api/gastos", headers=cli.A).json()["gastos"][0]["foto_url"] is None

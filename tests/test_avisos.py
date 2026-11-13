"""Avisos del armado guiado: "hacé la cola desde" (charla sin reserva), "salí antes" (para llegar a la siguiente),
en Hoy, en los avisos push y en el calendario .ics. Funciones puras: no usan el catálogo (corren en CI)."""
import datetime as dt

from app import ics, leave, push, sandbox, today

DIA = "2026-12-01"


def _card(code, start, end, *, kind="talk", reservada=False, salir_antes=0, title=None):
    return {"kind": kind, "code": code, "base": code, "title": title or f"Charla {code}", "type": "Breakout session",
            "day": DIA, "start": start, "end": end, "locked": True, "reservada": reservada, "salir_antes": salir_antes,
            "venue": {"hotel": "MGM Grand", "detail": "Level 3", "lat": 36.1, "lng": -115.17}}


def _ahora(hhmm):
    return dt.datetime.fromisoformat(f"{DIA}T{hhmm}").replace(tzinfo=sandbox.EVENT_TZ)


# ---------- horas ----------

def test_sin_reserva_hay_que_estar_30_min_antes():
    assert leave.arrive_by(_card("A", "10:00", "11:00")) == "09:30"
    assert leave.arrive_by(_card("A", "10:00", "11:00", reservada=True)) == "10:00"
    assert leave.arrive_by(_card("E", "18:00", "21:00", kind="event")) == "18:00"  # los eventos no tienen cola


def test_salir_antes_resta_del_fin():
    assert leave.leave_early_at(_card("A", "08:30", "09:30", salir_antes=4)) == "09:26"
    assert leave.leave_early_at(_card("A", "08:30", "09:30")) is None


# ---------- Hoy ----------

def test_hoy_dice_desde_cuando_hacer_la_cola_y_a_que_hora_salir():
    days = [{"day": DIA, "sessions": [_card("A", "08:30", "09:30", salir_antes=4), _card("B", "10:00", "11:00")]}]

    r = today.plan(days, _ahora("09:00"))

    assert (r["now"]["salis_a"], r["now"].get("cola_desde")) == ("09:26", "08:00")
    assert (r["next"]["cola_desde"], r["next"]["salis_a"]) == ("09:30", None)


# ---------- avisos push ----------

def _titulos(cards, hhmm):
    return [m["title"] for _, m in push.day_notices(cards, _ahora(hhmm))]


def test_sin_reserva_el_aviso_de_salir_cuenta_la_cola():
    cards = [_card("B", "10:00", "11:00")]

    assert _titulos(cards, "09:05") == []                                    # faltan 25 min para la cola
    clave, msg = push.day_notices(cards, _ahora("09:15"))[0]
    assert msg["title"] == "Salí para Charla B" and "cola desde las 09:30" in msg["body"]
    assert clave.startswith("leave:B:")


def test_con_reserva_el_aviso_es_contra_el_inicio():
    cards = [_card("B", "10:00", "11:00", reservada=True)]

    assert _titulos(cards, "09:15") == []
    assert _titulos(cards, "09:45") == ["Salí para Charla B"]


def test_avisa_salir_antes_para_llegar_a_la_siguiente():
    cards = [_card("A", "08:30", "09:30", salir_antes=4), _card("B", "09:30", "10:30", reservada=True, title="GraphRAG")]

    assert not [k for k, _ in push.day_notices(cards, _ahora("09:15")) if k.startswith("early:")]
    clave, msg = next((k, m) for k, m in push.day_notices(cards, _ahora("09:22")) if k.startswith("early:"))
    assert msg["title"] == "Salí a las 09:26 para llegar a GraphRAG"
    assert clave == f"early:A:{DIA}"


# ---------- calendario .ics ----------

def test_el_calendario_tiene_cada_item_con_alarma_de_cola():
    cards = [_card("A", "08:30", "09:30", salir_antes=4, title="Grafos, seguridad; y más"),
             _card("B", "10:00", "11:00", reservada=True), _card("E", "19:00", None, kind="mine")]

    texto = ics.calendario(cards, ahora=dt.datetime(2026, 11, 20, tzinfo=dt.UTC))
    lineas = texto.split("\r\n")

    assert lineas[0] == "BEGIN:VCALENDAR" and texto.endswith("END:VCALENDAR\r\n")
    assert texto.count("BEGIN:VEVENT") == 3
    assert "DTSTART:20261201T163000Z" in lineas                 # 08:30 en Las Vegas = 16:30 UTC
    assert "DTEND:20261201T172600Z" in lineas                   # sale 09:26
    assert "SUMMARY:Grafos\\, seguridad\\; y más" in lineas
    assert "TRIGGER:-PT45M" in lineas                           # sin reserva: 30 de cola + 15
    assert "TRIGGER:-PT15M" in lineas                           # reservada
    assert "DTEND:20261202T040000Z" in lineas                   # sin fin: 1 h (19:00 → 20:00 = 04:00 UTC del 2)
    assert all(len(linea.encode()) <= 75 for linea in lineas)   # líneas plegadas como pide el RFC 5545

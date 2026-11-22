"""Fin de la estadía (lun 7/12 13:00 en Las Vegas): eventos, shows y la carga a mano llegan hasta ahí."""
import re
from pathlib import Path

from app import estadia, events, prompts, ticketmaster

RAIZ = Path(__file__).resolve().parent.parent
ADMIN_EVENTOS = (RAIZ / "web" / "js" / "adminEventos.js").read_text(encoding="utf-8")


def _evento(code: str, day: str, start: str) -> dict:
    return {"kind": "event", "code": code, "day": day, "start": start, "end": None, "title": code}


def test_la_estadia_va_del_domingo_29_al_lunes_7_a_las_13():
    assert estadia.INICIO_DE_LA_ESTADIA.isoformat() == "2026-11-29T00:00:00-08:00"
    assert estadia.FIN_DE_LA_ESTADIA.isoformat() == "2026-12-07T13:00:00-08:00"


def test_ticketmaster_pide_hasta_el_fin_de_la_estadia():
    assert (ticketmaster._iso(ticketmaster.DESDE), ticketmaster._iso(ticketmaster.HASTA)) == \
        ("2026-11-29T08:00:00Z", "2026-12-07T21:00:00Z")
    dias = [desde.astimezone(estadia.TZ_VEGAS).date().isoformat() for desde, _ in ticketmaster.dias()]
    assert dias[-3:] == ["2026-12-05", "2026-12-06", "2026-12-07"]


def test_eventos_del_5_6_y_7_aparecen_cada_uno_en_su_dia(monkeypatch):
    monkeypatch.setattr(events, "_events", {
        "sab": _evento("sab", "2026-12-05", "20:00"),
        "dom": _evento("dom", "2026-12-06", "21:00"),
        "lun": _evento("lun", "2026-12-07", "09:00"),
        "mie": _evento("mie", "2026-12-02", "18:00")})

    dias = {d["day"]: [e["code"] for e in d["events"]] for d in events.by_day()}

    assert dias == {"2026-12-02": ["mie"], "2026-12-05": ["sab"], "2026-12-06": ["dom"], "2026-12-07": ["lun"]}


def test_el_admin_acepta_eventos_hasta_el_ultimo_dia_de_la_estadia():
    fecha_max = re.search(r'const FECHA_MAX = "([\d-]+)"', ADMIN_EVENTOS).group(1)

    assert fecha_max == estadia.FIN_DE_LA_ESTADIA.date().isoformat()
    assert "max: FECHA_MAX" in ADMIN_EVENTOS


def test_el_llm_sabe_que_hay_eventos_hasta_el_7_de_diciembre():
    assert "7 de diciembre" in prompts.EVENT_LINK_SYSTEM

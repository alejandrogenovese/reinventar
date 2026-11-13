"""Recordatorio "¿la grabás?" (reglas B y C): función pura, con reloj, sede y grabaciones simuladas. Corre en CI."""
import datetime as dt

import pytest

from app import recordatorio as r
from app.sandbox import EVENT_TZ

VENETIAN, CAESARS_FORUM, MGM = 1, 2, 5
VIAJES = {(CAESARS_FORUM, VENETIAN): 8, (MGM, VENETIAN): 25}


def _charla(code="ARC401", start="14:00", locked=True, id_sede=VENETIAN, kind="talk"):
    return {"kind": kind, "code": code, "base": code, "title": "Arquitecturas serverless", "day": "2026-12-01",
            "start": start, "locked": locked, "id_sede": id_sede,
            "venue": {"hotel": "Venetian", "detail": "Level 4 · Room 401"}}


def _ahora(hhmm):
    return dt.datetime.fromisoformat(f"2026-12-01T{hhmm}").replace(tzinfo=EVENT_TZ)


PREFS_POR_DEFECTO = r.Preferencias()


def _avisos(cards, hhmm, *, sede=None, prefs=PREFS_POR_DEFECTO, grabando=(), ultimo=None):
    return r.recordatorios(cards, _ahora(hhmm), sede=sede, prefs=prefs, grabando=lambda code: code in grabando,
                           viaje_min=lambda a, b: VIAJES.get((a, b)), minutos_desde_ultimo=ultimo)


@pytest.mark.parametrize("hhmm, avisa", [("14:01", False), ("14:02", True), ("14:04", True), ("14:06", True),
                                         ("14:07", False), ("13:58", False)])
def test_avisa_entre_2_y_6_min_despues_del_inicio(hhmm, avisa):
    assert bool(_avisos([_charla()], hhmm)) is avisa


def test_el_aviso_abre_la_grabacion_de_esa_charla_y_vence_rapido():
    [(key, msg)] = _avisos([_charla()], "14:03")

    assert key == "rec:ARC401:2026-12-01"
    assert msg["url"] == msg["recordUrl"] == "/#/grabar-charla/ARC401"
    assert msg["actions"] == [{"action": "grabar", "title": "Grabar"}]
    assert msg["tag"] == key
    assert msg["ttl"] == r.TTL_SEGUNDOS == 600
    assert msg["title"] == "Empezó Arquitecturas serverless en Venetian"
    assert "Tocá para grabar" in msg["body"]


def test_no_avisa_si_alguien_ya_la_esta_grabando():
    assert _avisos([_charla()], "14:03", grabando={"ARC401"}) == []


def test_en_la_misma_sede_dice_donde_esta():
    [(_, msg)] = _avisos([_charla()], "14:03", sede=r.Sede(VENETIAN, "Venetian"))

    assert msg["title"] == "Estás en Venetian: ¿grabás Arquitecturas serverless?"


def test_en_una_sede_cercana_avisa_y_dice_donde_esta():
    [(_, msg)] = _avisos([_charla()], "14:03", sede=r.Sede(CAESARS_FORUM, "Caesars Forum"))

    assert msg["title"] == "Arquitecturas serverless ya empezó en Venetian (estás en Caesars Forum)"
    assert "8 min caminando" in msg["body"]


def test_en_una_sede_lejana_no_avisa():
    assert _avisos([_charla()], "14:03", sede=r.Sede(MGM, "MGM Grand")) == []


def test_sin_sede_solo_avisa_lo_fijado():
    assert _avisos([_charla(locked=False)], "14:03") == []
    assert len(_avisos([_charla(locked=True)], "14:03")) == 1


def test_lo_no_fijado_avisa_solo_si_esta_en_esa_sede():
    no_fijada = _charla(locked=False)

    assert len(_avisos([no_fijada], "14:03", sede=r.Sede(VENETIAN, "Venetian"))) == 1
    assert _avisos([no_fijada], "14:03", sede=r.Sede(CAESARS_FORUM, "Caesars Forum")) == []


def test_charla_en_sede_sin_coordenadas_cuenta_como_sin_dato():
    sin_sede = _charla(id_sede=None)

    assert len(_avisos([sin_sede], "14:03", sede=r.Sede(MGM, "MGM Grand"))) == 1


def test_no_avisa_en_horario_de_silencio():
    assert _avisos([_charla(start="22:00")], "22:03") == []
    assert _avisos([_charla(start="06:30")], "06:33") == []
    assert r.en_silencio(_ahora("21:59")) is False
    assert r.en_silencio(_ahora("07:00")) is False


def test_respeta_el_enfriamiento_de_30_min():
    assert _avisos([_charla()], "14:03", ultimo=10) == []
    assert len(_avisos([_charla()], "14:03", ultimo=31)) == 1


def test_con_la_preferencia_apagada_no_avisa():
    assert _avisos([_charla()], "14:03", prefs=r.Preferencias(grabar=False)) == []


def test_como_mucho_un_aviso_por_vuelta_y_solo_charlas():
    cards = [_charla(kind="event", code="evt-1"), _charla("ARC401"), _charla("DEV302")]

    assert [k for k, _ in _avisos(cards, "14:03")] == ["rec:ARC401:2026-12-01"]


def test_no_avisa_charlas_de_otro_dia():
    otra = {**_charla(), "day": "2026-12-02"}

    assert _avisos([otra], "14:03") == []

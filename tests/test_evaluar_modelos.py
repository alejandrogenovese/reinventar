"""Vara de modelos por tarea: chequeos de formato, juez a ciegas y resumen (sin llamar a la API)."""
import random
from types import SimpleNamespace

from scripts import evaluar_modelos as ev


def _msg(texto, entrada=1000, salida=100):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=texto)],
                           usage=SimpleNamespace(input_tokens=entrada, output_tokens=salida,
                                                 cache_read_input_tokens=0, cache_creation_input_tokens=0))


def test_traduccion_ok_exige_todas_las_lineas():
    user = "[[1]] Hello\n[[2]] World"

    assert ev.traduccion_ok(user, "[[1]] Hola\n[[2]] Mundo")
    assert not ev.traduccion_ok(user, "[[1]] Hola")


def test_chat_ok_rechaza_codigos_inventados_y_no_cuenta_lo_grabado():
    assert ev.chat_ok("Mirá [DAT401] y lo que dijeron en [G1].", {"DAT401", "ARC302"})
    assert not ev.chat_ok("Mirá [XYZ999].", {"DAT401"})
    assert not ev.chat_ok("Sin citas.", {"DAT401"})


def test_razones_ok_pide_una_razon_corta_por_opcion():
    bien = '{"razones": [{"code": "A1", "razon": "Te sirve para migrar Teradata."}]}'
    larga = '{"razones": [{"code": "A1", "razon": "' + "palabra " * 30 + '"}]}'

    assert ev.razones_ok(bien, {"A1"})
    assert not ev.razones_ok(larga, {"A1"})
    assert not ev.razones_ok(bien, {"A1", "B2"})
    assert not ev.razones_ok("no es json", {"A1"})


def test_resumen_ok_pide_tldr_y_puntos():
    assert ev.resumen_ok('{"tldr": "Habló de Iceberg.", "key_points": []}')
    assert not ev.resumen_ok('{"key_points": []}')


def test_trozos_corta_en_bloques_de_palabras():
    assert ev.trozos("a b c d e", palabras=2) == ["a b", "c d", "e"]


def test_costo_usa_el_precio_de_cada_modelo():
    uso = _msg("x", entrada=1_000_000, salida=1_000_000).usage

    assert ev.costo("claude-haiku-5-5", uso) == 0.10 + 0.50
    assert ev.costo("claude-sonnet-5-5", uso) == 2.0 + 10.0


def _caso():
    return ev.Caso("chat", "chat-1", "sys", "Pregunta: algo", 100, lambda s: True)


def test_el_juez_no_sabe_cual_es_el_candidato_y_se_traduce_bien_su_veredicto(monkeypatch):
    vistos = []

    def juez(modelo, system, user, max_tokens):
        vistos.append(user)
        ganador = "A" if user.index("SALIDA-CANDIDATO") < user.index("SALIDA-BASE") else "B"
        return _msg(f'{{"ganador": "{ganador}", "motivo": "más concreta"}}')

    monkeypatch.setattr(ev.llm, "claude_mensaje", juez)
    base, cand = {"salida": "SALIDA-BASE"}, {"salida": "SALIDA-CANDIDATO"}
    rnd = random.Random(1)

    resultados = [ev.juzgar(_caso(), base, cand, rnd)["resultado"] for _ in range(6)]

    assert resultados == ["candidato"] * 6  # el juez siempre eligió al candidato, en cualquier orden
    assert all("claude" not in u for u in vistos)  # no ve qué modelo es cuál


def test_si_el_juez_no_devuelve_json_cuenta_como_empate(monkeypatch):
    monkeypatch.setattr(ev.llm, "claude_mensaje", lambda *a: _msg("no sé"))

    assert ev.juzgar(_caso(), {"salida": "a"}, {"salida": "b"}, random.Random(1))["resultado"] == "empate"


def _fila(resultado, formato_ok=True):
    lado = {"formato_ok": formato_ok, "segundos": 1.0, "usd": 0.01}
    return {"base": {**lado, "formato_ok": True}, "candidato": lado, "juez": {"resultado": resultado}}


def test_recomienda_cambiar_si_gana_o_empata_casi_siempre_y_no_rompe_el_formato():
    assert ev.resumir([_fila("candidato"), _fila("empate"), _fila("empate"), _fila("empate"), _fila("base")])["cambiar"]
    assert not ev.resumir([_fila("base"), _fila("base"), _fila("empate")])["cambiar"]
    assert not ev.resumir([_fila("empate"), _fila("empate", formato_ok=False)])["cambiar"]

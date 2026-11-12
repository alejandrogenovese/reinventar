"""Chat de búsqueda con lo grabado: los momentos de las grabaciones van al LLM como [G1], [G2]… y vuelven los citados.
No usa el catálogo (la búsqueda del catálogo se reemplaza), así que corre también en CI."""
from app import ask, fragmentos, prompts, search

MOMENTOS = [
    {"session_id": "s1", "idx": 3, "start_s": 95.0, "end_s": 135.0, "title": "Grafos para analistas", "kind": "Chalk talk",
     "code": "DAT402", "es": "Neptune permite a los analistas explorar el grafo.", "en": "Neptune lets analysts explore."},
    {"session_id": "s2", "idx": 0, "start_s": 0.0, "end_s": 40.0, "title": "Keynote", "kind": "Keynote", "code": None,
     "es": None, "en": "This year is all about agents."},
]


def test_el_prompt_lleva_los_momentos_con_referencia_charla_y_minuto():
    texto = prompts.ask_user("¿qué dijeron de Neptune?", [], None, MOMENTOS)

    assert "Momentos de charlas que grabó:" in texto
    assert "[G1] Grafos para analistas (DAT402), minuto 1: Neptune permite" in texto
    assert "[G2] Keynote, minuto 0: This year is all about agents." in texto  # sin traducción, va el inglés


def test_sin_momentos_el_prompt_queda_como_antes():
    assert "Momentos de charlas" not in prompts.ask_user("data mesh", [], None, [])
    assert "[G1]" in prompts.ASK_SYSTEM  # el sistema explica cómo citarlos


def test_los_momentos_citados_existen_no_se_repiten_y_respetan_el_orden():
    citados = ask._momentos_citados("Primero [G2], después [G1], otra vez [G2] y uno inventado [G7].", MOMENTOS)

    assert [m["ref"] for m in citados] == ["G2", "G1"]
    assert citados[1]["session_id"] == "s1" and citados[1]["start_s"] == 95.0


def test_el_chat_busca_en_lo_grabado_y_devuelve_los_momentos_citados(monkeypatch):
    monkeypatch.setattr(search, "hybrid", lambda q, n: [])
    pedidos = []
    monkeypatch.setattr(fragmentos, "buscar", lambda q, n: pedidos.append((q, n)) or MOMENTOS)

    r = ask.answer("¿qué dijeron de Neptune?")

    assert pedidos == [("¿qué dijeron de Neptune?", ask.ASK_FRAGMENTOS)]
    assert "[G1]" in r["answer"]  # el LLM falso cita el primer momento
    assert [m["ref"] for m in r["momentos"]] == ["G1"] and r["momentos"][0]["title"] == "Grafos para analistas"


def test_si_falla_la_busqueda_en_lo_grabado_el_chat_responde_igual(monkeypatch):
    def falla(q, n):
        raise RuntimeError("sin base")

    monkeypatch.setattr(search, "hybrid", lambda q, n: [])
    monkeypatch.setattr(fragmentos, "buscar", falla)

    r = ask.answer("agentes")

    assert r["answer"] and r["momentos"] == []

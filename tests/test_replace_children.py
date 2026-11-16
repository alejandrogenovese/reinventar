"""`el.replaceChildren(a, null)` del DOM convierte el null en el texto «null» (no lo saltea como `h()` de ui.js).

Pasó en el voto del resumen: sin votos se veía «👍 Sí 👎 No null». Toda llamada que pueda recibir un null tiene que
filtrarlo (`.filter(Boolean)`) o usar "" en su lugar. Se verifica el JS como texto, igual que test_diseno."""
from pathlib import Path

import pytest

WEB_JS = Path(__file__).resolve().parent.parent / "web" / "js"
LLAMADA = "replaceChildren("


def _argumentos(texto: str, desde: int) -> str:
    """Texto entre los paréntesis de la llamada que abre en `desde` (cuenta paréntesis anidados)."""
    nivel = 0
    for i in range(desde, len(texto)):
        if texto[i] == "(":
            nivel += 1
        elif texto[i] == ")":
            nivel -= 1
            if nivel == 0:
                return texto[desde + 1:i]
    return texto[desde + 1:]


def _llamadas(texto: str) -> list[str]:
    salida, i = [], texto.find(LLAMADA)
    while i != -1:
        salida.append(_argumentos(texto, i + len(LLAMADA) - 1))
        i = texto.find(LLAMADA, i + 1)
    return salida


def _de_primer_nivel(args: str) -> list[str]:
    """Separa los argumentos por las comas de primer nivel (fuera de (), [], {} y strings)."""
    partes, actual, nivel, comilla = [], [], 0, None
    for c in args:
        if comilla:
            comilla = None if c == comilla else comilla
        elif c in "\"'`":
            comilla = c
        elif c in "([{":
            nivel += 1
        elif c in ")]}":
            nivel -= 1
        elif c == "," and nivel == 0:
            partes.append("".join(actual).strip())
            actual = []
            continue
        actual.append(c)
    return [p for p in [*partes, "".join(actual).strip()] if p]


def _con_null(args: str) -> list[str]:
    """Argumentos directos que pueden valer null (un `?:` que termina en null, o `?? null`); dentro de h() no cuenta."""
    return [a for a in _de_primer_nivel(args)
            if a == "null" or a.endswith(": null") or a.endswith("?? null")]


def test_detecta_el_null_suelto_y_no_el_que_va_dentro_de_h():
    assert _con_null(_llamadas('box.replaceChildren(h("p"), n ? h("span") : null);')[0])
    assert not _con_null(_llamadas('box.replaceChildren(...[h("p"), n ? h("span") : null].filter(Boolean));')[0])
    assert not _con_null(_llamadas('box.replaceChildren(h("div", {}, n ? h("span") : null, "a, b"));')[0])


@pytest.mark.parametrize("archivo", sorted(WEB_JS.glob("*.js")), ids=lambda p: p.name)
def test_replace_children_no_recibe_null(archivo):
    malas = [n for a in _llamadas(archivo.read_text()) for n in _con_null(a)]
    assert not malas, f"{archivo.name}: replaceChildren con un null posible (se vería «null»): {malas}"

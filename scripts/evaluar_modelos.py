"""Compara modelos por tarea con pedidos reales de la app y un juez: la vara para elegir el modelo de cada tarea.

Por tarea, el modelo de hoy (base) contra uno más barato (candidato), con los mismos prompts (app/prompts.py) y los
mismos parámetros (app/llm.py: claude_mensaje) que la app. Un juez (Opus) compara cada par a ciegas, en orden al azar,
y dice cuál es mejor o si empatan. Además se chequea el formato como lo usa la app y se mide costo y demora.

  traduccion  Sonnet → Haiku. Bloques de grabaciones reales si hay; si no, abstracts del catálogo cortados en bloques
              (inglés escrito: mide terminología y formato, no el ruido del STT).
  resumen     Opus → Sonnet. Solo grabaciones reales de al menos 10 minutos.
  chat        Sonnet → Haiku. Preguntas de scripts/eval/busqueda_catalogo.json.
  razones     Sonnet → Haiku. Fichas inventadas de scripts/eval/modelos.json.

Cuesta plata: llama a la API de Anthropic (ANTHROPIC_API_KEY). Con --estimar muestra los casos y una estimación del
costo sin llamar a nadie. Las salidas quedan en data/eval_modelos.json, para leerlas a mano.

Uso (desde la raíz del repo, con el catálogo cargado en el Postgres local):
  DATABASE_URL=... EMBED_PROVIDER=local python -m scripts.evaluar_modelos --estimar
  DATABASE_URL=... EMBED_PROVIDER=local ANTHROPIC_API_KEY=... python -m scripts.evaluar_modelos [--tareas chat,razones] [--n 6]
"""
import argparse
import json
import random
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app import ask, catalog, config, db, llm, prompts, search, talks
from app.pipeline import SUMMARY_MAX_TOKENS, hms

SET = Path(__file__).parent / "eval" / "modelos.json"
PREGUNTAS = Path(__file__).parent / "eval" / "busqueda_catalogo.json"
SALIDA = config.DATA_DIR / "eval_modelos.json"
JUEZ = "claude-opus-5-5"
SEMILLA = 7
BLOQUE_PALABRAS = 40       # ~15 s de charla
BLOQUES_POR_CASO = 20
MIN_BLOQUES_RESUMEN = 40   # ~10 minutos de charla
OPCIONES_POR_CASO = 4      # el armado guiado muestra pocas opciones por vez
MAX_PALABRAS_RAZON = 25    # el prompt pide 20; un margen chico
UMBRAL_CAMBIO = 0.8        # el candidato tiene que ganar o empatar en al menos el 80 % de los casos

# USD por millón de tokens (entrada, salida). Cache: lectura 10 % y escritura 125 % de la entrada.
PRECIOS = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}
SALIDA_ESTIMADA = {"traduccion": 1.3, "resumen": 0.15, "chat": 0.15, "razones": 0.15}  # tokens de salida / entrada

PARES = {  # tarea: (modelo de hoy, candidato)
    "traduccion": ("claude-sonnet-5-5", "claude-haiku-5-5"),
    "resumen": ("claude-opus-5-5", "claude-sonnet-5-5"),
    "chat": ("claude-sonnet-5-5", "claude-haiku-5-5"),
    "razones": ("claude-sonnet-5-5", "claude-haiku-5-5"),
}

CRITERIOS = {
    "traduccion": "fidelidad al inglés sin agregar ni quitar, terminología (nombres de servicios y términos técnicos "
                  "en inglés como pide el glosario), castellano rioplatense natural, y cada línea con su marcador [[n]]",
    "resumen": "fidelidad a la transcripción (sin inventar anuncios ni datos), utilidad para un arquitecto de datos de "
               "un banco, concreción, y citas textuales reales",
    "chat": "que responda la pregunta, que recomiende las charlas candidatas más pertinentes citándolas por código sin "
            "inventar códigos, y claridad",
    "razones": "que cada razón conecte la charla con el desafío o las prioridades concretas de la ficha, sin frases "
               "genéricas ni contenido inventado, en una oración corta",
}

JUEZ_SYSTEM = """Comparás dos respuestas (A y B) al mismo pedido de una app para AWS re:Invent y decidís cuál es mejor según el criterio que te pasan. Si la diferencia no le cambiaría nada a quien usa la app, es empate.
Devolvé SOLO un objeto JSON: {"ganador": "A" | "B" | "empate", "motivo": "una oración"}"""


@dataclass(frozen=True)
class Caso:
    tarea: str
    id: str
    system: str
    user: str
    max_tokens: int
    formato_ok: Callable[[str], bool]


# --- formato: lo mismo que necesita la app para usar la respuesta -------------
def traduccion_ok(user: str, salida: str) -> bool:
    """Están todas las líneas: la app reintenta una por una las que faltan (más llamadas y más demora)."""
    pedidas = set(re.findall(r"^\[\[(\d+)\]\]", user, re.M))
    return bool(pedidas) and pedidas <= set(re.findall(r"\[\[(\d+)\]\]", salida))


def resumen_ok(salida: str) -> bool:
    try:
        r = llm.parse_json(salida)
    except ValueError:
        return False
    return isinstance(r.get("tldr"), str) and bool(r["tldr"]) and isinstance(r.get("key_points"), list)


def chat_ok(salida: str, codigos: set[str]) -> bool:
    """Cita al menos una charla y ninguna inventada (los [G1] de lo grabado no cuentan: tienen 2 caracteres)."""
    citados = set(ask._CODE.findall(salida))
    return bool(citados) and citados <= codigos


def razones_ok(salida: str, codigos: set[str]) -> bool:
    try:
        razones = llm.parse_json(salida).get("razones", [])
    except ValueError:
        return False
    return ({str(r.get("code")) for r in razones} == codigos
            and all(0 < len(str(r.get("razon", "")).split()) <= MAX_PALABRAS_RAZON for r in razones))


# --- casos ----------------------------------------------------------------------
def trozos(texto: str, palabras: int = BLOQUE_PALABRAS) -> list[str]:
    w = texto.split()
    return [" ".join(w[i:i + palabras]) for i in range(0, len(w), palabras)]


def _grabaciones(min_bloques: int) -> list[tuple[dict, list[dict]]]:
    con_bloques = ((db.get_session(sid), db.get_blocks(sid)) for sid in db.sessions_in(["ready"]))
    return [(s, b) for s, b in con_bloques if len(b) >= min_bloques]


def casos_traduccion(n: int, rnd: random.Random) -> list[Caso]:
    def caso(i: int, textos: list[str], nombres: list[str]) -> Caso:
        user = prompts.translate_user(list(enumerate(textos, 1)), nombres)
        return Caso("traduccion", f"traduccion-{i}", prompts.TRANSLATE_SYSTEM, user, 8000,
                    lambda salida: traduccion_ok(user, salida))

    casos = []
    for s, bloques in _grabaciones(BLOQUES_POR_CASO)[:n]:
        desde = rnd.randrange(len(bloques) - BLOQUES_POR_CASO + 1)
        textos = [b["en"] for b in bloques[desde:desde + BLOQUES_POR_CASO]]
        casos.append(caso(len(casos) + 1, textos, talks.proper_names(s.get("code"))))
    largas = [s for s in catalog.all_sessions() if len((s.get("abstract") or "").split()) >= 3 * BLOQUE_PALABRAS]
    rnd.shuffle(largas)
    while len(casos) < n and largas:
        textos, nombres = [], []
        while len(textos) < BLOQUES_POR_CASO and largas:
            s = largas.pop()
            textos += trozos(s["abstract"])
            nombres += talks.proper_names(s["base"])
        casos.append(caso(len(casos) + 1, textos[:BLOQUES_POR_CASO], list(dict.fromkeys(nombres))))
    return casos


def casos_resumen(n: int, _rnd: random.Random) -> list[Caso]:
    casos = []
    for s, bloques in _grabaciones(MIN_BLOQUES_RESUMEN)[:n]:
        transcript = "\n".join(f"[{hms(b['start_s'])}] {b['en']}" for b in bloques)
        user = prompts.summary_user(s["kind"], s["title"], transcript, talks.context(s.get("code")))
        casos.append(Caso("resumen", f"resumen-{s['id']}", prompts.SUMMARY_SYSTEM, user, SUMMARY_MAX_TOKENS, resumen_ok))
    return casos


def casos_chat(n: int, _rnd: random.Random) -> list[Caso]:
    preguntas = [p["pregunta"] for p in json.loads(PREGUNTAS.read_text(encoding="utf-8"))][:n]
    casos = []
    for i, q in enumerate(preguntas, 1):
        hits = search.hybrid(q, ask.ASK_CANDIDATES)
        codigos = {h["base"] for h in hits}
        user = prompts.ask_user(q, hits, None, ask._momentos(q))
        casos.append(Caso("chat", f"chat-{i}", prompts.ASK_SYSTEM, user, ask.ASK_MAX_TOKENS,
                          lambda salida, c=codigos: chat_ok(salida, c)))
    return casos


def casos_razones(n: int, _rnd: random.Random) -> list[Caso]:
    fichas = json.loads(SET.read_text(encoding="utf-8"))["fichas"]
    casos = []
    for i in range(n):
        ficha = fichas[i % len(fichas)]
        desde = (i // len(fichas)) * OPCIONES_POR_CASO
        hits = search.hybrid(ficha["consulta"], desde + OPCIONES_POR_CASO)[desde:]
        items = [{"code": s["base"], "title": s["title"], "type": s.get("type"), "level": s.get("level"),
                  "resumen": (s.get("abstract") or "")[:500]} for s in hits]
        codigos = {s["base"] for s in hits}
        user = prompts.guided_reasons_user(ficha["texto"], items)
        casos.append(Caso("razones", f"razones-{i + 1}", prompts.GUIDED_REASONS_SYSTEM, user, 2000,
                          lambda salida, c=codigos: razones_ok(salida, c)))
    return casos


ARMAR = {"traduccion": casos_traduccion, "resumen": casos_resumen, "chat": casos_chat, "razones": casos_razones}


# --- correr y juzgar --------------------------------------------------------------
def costo(modelo: str, uso) -> float:
    entrada, salida = PRECIOS[modelo]
    lee = getattr(uso, "cache_read_input_tokens", 0) or 0
    escribe = getattr(uso, "cache_creation_input_tokens", 0) or 0
    return (uso.input_tokens * entrada + lee * entrada * 0.1 + escribe * entrada * 1.25 + uso.output_tokens * salida) / 1e6


def correr(modelo: str, caso: Caso) -> dict:
    t = time.monotonic()
    msg = llm.claude_mensaje(modelo, caso.system, caso.user, caso.max_tokens)
    salida = llm.texto(msg)
    return {"modelo": modelo, "salida": salida, "segundos": round(time.monotonic() - t, 1),
            "usd": costo(modelo, msg.usage), "formato_ok": caso.formato_ok(salida)}


def juzgar(caso: Caso, base: dict, candidato: dict, rnd: random.Random) -> dict:
    """A ciegas: el juez no sabe qué modelo es cuál, y el orden se sortea en cada caso."""
    a_es_candidato = rnd.random() < 0.5
    a, b = (candidato, base) if a_es_candidato else (base, candidato)
    user = (f"Criterio: {CRITERIOS[caso.tarea]}\n\nPedido:\n{caso.user}\n\n"
            f"=== Respuesta A ===\n{a['salida']}\n\n=== Respuesta B ===\n{b['salida']}")
    msg = llm.claude_mensaje(JUEZ, JUEZ_SYSTEM, user, 4000)
    try:
        veredicto = llm.parse_json(llm.texto(msg))
    except ValueError:
        veredicto = {"ganador": "empate", "motivo": "el juez no devolvió JSON"}
    ganador = veredicto.get("ganador")
    resultado = "empate" if ganador not in ("A", "B") else ("candidato" if (ganador == "A") == a_es_candidato else "base")
    return {"resultado": resultado, "motivo": veredicto.get("motivo", ""), "usd": costo(JUEZ, msg.usage)}


def resumir(filas: list[dict]) -> dict:
    n = len(filas)
    resultados = [f["juez"]["resultado"] for f in filas]
    gana, empata, pierde = (resultados.count(r) for r in ("candidato", "empate", "base"))

    def lado(quien: str) -> dict:
        return {"formato_ok": sum(f[quien]["formato_ok"] for f in filas),
                "segundos": round(sum(f[quien]["segundos"] for f in filas) / n, 1),
                "usd_por_llamada": sum(f[quien]["usd"] for f in filas) / n}

    candidato = lado("candidato")
    cambiar = candidato["formato_ok"] == n and (gana + empata) / n >= UMBRAL_CAMBIO
    return {"casos": n, "base": lado("base"), "candidato": candidato, "candidato_gana": gana, "empates": empata,
            "candidato_pierde": pierde, "cambiar": cambiar}


def estimar(casos: list[Caso]) -> float:
    """USD aproximados de correr los casos: base + candidato + juez, contando ~4 caracteres por token."""
    total = 0.0
    for c in casos:
        entrada = (len(c.system) + len(c.user)) / 4
        salida = entrada * SALIDA_ESTIMADA[c.tarea]
        base, candidato = PARES[c.tarea]
        for modelo in (base, candidato):
            total += (entrada * PRECIOS[modelo][0] + salida * PRECIOS[modelo][1]) / 1e6
        total += ((entrada + 2 * salida) * PRECIOS[JUEZ][0] + 200 * PRECIOS[JUEZ][1]) / 1e6
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tareas", default=",".join(PARES), help=f"separadas por coma, de: {', '.join(PARES)}")
    ap.add_argument("--n", type=int, default=6, help="casos por tarea")
    ap.add_argument("--estimar", action="store_true", help="solo muestra los casos y el costo estimado")
    args = ap.parse_args()
    tareas = [t for t in args.tareas.split(",") if t]
    if desconocidas := [t for t in tareas if t not in PARES]:
        sys.exit(f"Tareas desconocidas: {', '.join(desconocidas)}")

    catalog.load()
    search.ensure_index()
    rnd = random.Random(SEMILLA)
    casos = {t: ARMAR[t](args.n, rnd) for t in tareas}
    for t, cs in casos.items():
        aviso = " (sin grabaciones de 10 minutos o más: se saltea)" if t == "resumen" and not cs else ""
        print(f"{t:<11} {len(cs)} casos · {PARES[t][0]} contra {PARES[t][1]}{aviso}")
    print(f"Costo estimado: USD {estimar([c for cs in casos.values() for c in cs]):.2f}")
    if args.estimar:
        return
    if not config.ANTHROPIC_API_KEY:
        sys.exit("Falta ANTHROPIC_API_KEY (el juez y los modelos se llaman directo a Anthropic).")

    salida = {}
    for tarea, cs in casos.items():
        base, candidato = PARES[tarea]
        filas = []
        for c in cs:
            fila = {"id": c.id, "base": correr(base, c), "candidato": correr(candidato, c)}
            fila["juez"] = juzgar(c, fila["base"], fila["candidato"], rnd)
            filas.append(fila)
            print(f"  {c.id}: {fila['juez']['resultado']} — {fila['juez']['motivo']}", flush=True)
        if filas:
            salida[tarea] = {"resumen": resumir(filas), "filas": filas}
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'tarea':<11} {'gana':>4} {'empata':>6} {'pierde':>6} {'formato':>8} {'USD/llamada':>18} {'seg':>11}  ¿cambiar?")
    for tarea, d in salida.items():
        r, b, c = d["resumen"], d["resumen"]["base"], d["resumen"]["candidato"]
        print(f"{tarea:<11} {r['candidato_gana']:>4} {r['empates']:>6} {r['candidato_pierde']:>6} "
              f"{c['formato_ok']:>3}/{r['casos']:<4} {b['usd_por_llamada']:>8.4f} → {c['usd_por_llamada']:<7.4f} "
              f"{b['segundos']:>4} → {c['segundos']:<4}  {'sí' if r['cambiar'] else 'no'}")
    print(f"\nSalidas completas en {SALIDA}")


if __name__ == "__main__":
    main()

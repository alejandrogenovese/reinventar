"""Mide la búsqueda del catálogo (app/search.py) contra un set fijo de preguntas: la vara para comparar cambios.

Cada pregunta de scripts/eval/busqueda_catalogo.json trae las charlas relevantes según un criterio fijo sobre el
título (ver "criterio"), así el set se puede regenerar si cambia el catálogo. Por pregunta se mide:
  acierto@k  → hay al menos una relevante entre las primeras k
  recall@k   → relevantes entre las primeras k / min(relevantes, k)
  MRR        → 1 / puesto de la primera relevante (0 si no aparece en las primeras k)
Y se compara la búsqueda híbrida contra cada mitad sola (por palabras, por significado).

No consume APIs: los embeddings son locales (EMBED_PROVIDER=local). La primera vez baja el modelo.

Uso (desde la raíz del repo, con el catálogo cargado en el Postgres local):
  DATABASE_URL=postgresql://reinvent:<clave>@localhost:5433/reinvent EMBED_PROVIDER=local \\
    python -m scripts.evaluar_busqueda              # resumen
  ... python -m scripts.evaluar_busqueda --detalle  # además, pregunta por pregunta
"""
import argparse
import json
from collections.abc import Callable
from pathlib import Path

from app import catalog, search

SET = Path(__file__).parent / "eval" / "busqueda_catalogo.json"
K = 10


def metricas(ranking: list[str], relevantes: set[str], k: int = K) -> dict:
    primeros = ranking[:k]
    puestos = [i for i, base in enumerate(primeros, 1) if base in relevantes]
    return {
        "acierto": 1.0 if puestos else 0.0,
        "recall": len(puestos) / min(len(relevantes), k) if relevantes else 0.0,
        "mrr": 1 / puestos[0] if puestos else 0.0,
    }


def promedio(filas: list[dict]) -> dict:
    return {m: sum(f[m] for f in filas) / len(filas) for m in ("acierto", "recall", "mrr")} if filas else {}


def _bases(indices: list[int]) -> list[str]:
    sesiones = catalog.all_sessions()
    return [sesiones[i]["base"] for i in indices]


def buscadores() -> dict[str, Callable[[str], list[str]]]:
    return {
        "híbrida": lambda q: [s["base"] for s in search.hybrid(q, K)],
        "palabras": lambda q: _bases(search._lexical_ranking(q, K)),
        "significado": lambda q: _bases(search._semantic_ranking(q, K)),
    }


def evaluar(preguntas: list[dict], buscar: Callable[[str], list[str]]) -> list[dict]:
    return [{"pregunta": p["pregunta"], **metricas(buscar(p["pregunta"]), set(p["relevantes"]))} for p in preguntas]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--detalle", action="store_true", help="muestra las métricas de cada pregunta")
    args = ap.parse_args()

    preguntas = [p for p in json.loads(SET.read_text(encoding="utf-8")) if p["relevantes"]]
    catalog.load()
    search.ensure_index()  # embeddings del catálogo (calcula solo lo que falte)

    print(f"{len(preguntas)} preguntas · k={K}\n")
    print(f"{'búsqueda':<12} {'acierto@k':>10} {'recall@k':>9} {'MRR':>6}")
    resultados = {}
    for nombre, buscar in buscadores().items():
        filas = resultados[nombre] = evaluar(preguntas, buscar)
        m = promedio(filas)
        print(f"{nombre:<12} {m['acierto']:>10.2f} {m['recall']:>9.2f} {m['mrr']:>6.2f}")

    if args.detalle:
        print(f"\n{'pregunta (híbrida)':<52} {'acierto':>7} {'recall':>7} {'MRR':>5}")
        for f in sorted(resultados["híbrida"], key=lambda f: f["recall"]):
            print(f"{f['pregunta'][:52]:<52} {f['acierto']:>7.0f} {f['recall']:>7.2f} {f['mrr']:>5.2f}")


if __name__ == "__main__":
    main()

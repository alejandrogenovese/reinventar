"""Procesa ítems (charlas, eventos) en lotes paralelos contra el LLM (lo comparten traducir_resumenes y extraer_claves).

Cada lote se guarda apenas vuelve; un lote fallido no frena al resto y queda pendiente para la próxima corrida.
"""
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed


def en_lotes[T](items: Sequence[T], tamano: int) -> list[list[T]]:
    return [list(items[i:i + tamano]) for i in range(0, len(items), tamano)]


def procesar[T, R](lotes: list[list[T]], llamar: Callable[[list[T]], R], al_volver: Callable[[list[T], R], None], *,
                   hilos: int, describir: Callable[[list[T]], str], avisar: Callable[[str], None]) -> tuple[str, ...]:
    """Llama al LLM por lote en paralelo; al_volver corre en este hilo (acá se escribe en la base).
    Devuelve los errores de los lotes que fallaron."""
    fallidos = []
    with ThreadPoolExecutor(max_workers=hilos) as pool:
        futuros = {pool.submit(llamar, lote): lote for lote in lotes}
        for futuro in as_completed(futuros):
            lote = futuros[futuro]
            try:
                resultado = futuro.result()
            except Exception as e:  # el error queda en el reporte y el lote se reintenta en la próxima corrida
                fallidos.append(f"{describir(lote)}: {e}")
                avisar(f"  lote fallido ({len(lote)} charlas): {e}")
                continue
            al_volver(lote, resultado)
    return tuple(fallidos)

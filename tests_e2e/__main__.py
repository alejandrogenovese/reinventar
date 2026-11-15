"""python -m tests_e2e: corre los escenarios sin señal en Chromium contra un servidor local. A mano, antes de publicar
(no corre en CI). Si algo falla deja capturas, el log de la consola y el del servidor en e2e-fallas/<fecha>/."""
import asyncio
import shutil
import sys
import time
import traceback
from pathlib import Path

from tests_e2e.escenarios import ESCENARIOS, Contexto, preparar
from tests_e2e.navegador import SinNavegador, buscar_navegador, navegador
from tests_e2e.servidor import RAIZ, servidor_local


async def correr(carpeta_fallas: Path) -> int:
    resultados: list[tuple[str, str, str]] = []
    with servidor_local(carpeta_fallas) as servidor:
        print(f"Servidor de prueba en {servidor.url} (schema {servidor.schema})")
        async with navegador(servidor.url, carpeta_fallas) as pagina:
            contexto = Contexto(pagina, servidor)
            try:
                await preparar(contexto)
            except Exception as e:  # noqa: BLE001 — sin sesión no hay nada que probar
                await pagina.captura(carpeta_fallas / "preparar.png")
                print(f"No pude preparar la sesión de prueba: {e}\n" + "\n".join(pagina.consola[-10:]))
                return 1
            fallo_el_2 = False
            for nombre, escenario in ESCENARIOS:
                if fallo_el_2 and nombre.startswith("3"):
                    resultados.append((nombre, "SALTEADO", "depende del escenario 2"))
                    continue
                inicio = time.monotonic()
                try:
                    await escenario(contexto)
                    resultados.append((nombre, "OK", f"{time.monotonic() - inicio:.0f} s"))
                except Exception as e:  # noqa: BLE001 — se informa y se sigue con el próximo
                    fallo_el_2 = fallo_el_2 or nombre.startswith("2")
                    resultados.append((nombre, "FALLÓ", f"{type(e).__name__}: {e}"))
                    await pagina.captura(carpeta_fallas / f"escenario-{nombre[0]}.png")
                    (carpeta_fallas / f"escenario-{nombre[0]}.txt").write_text(
                        traceback.format_exc() + "\n--- consola ---\n" + "\n".join(pagina.consola))
    for nombre, estado, detalle in resultados:
        print(f"[{estado:8}] {nombre} — {detalle}")
    return 0 if all(estado == "OK" for _, estado, _ in resultados) else 1


def main() -> int:
    try:
        print(f"Navegador: {buscar_navegador()}")
    except SinNavegador as e:
        print(f"SALTEADA: {e}")
        return 0
    carpeta = RAIZ / "e2e-fallas" / time.strftime("%Y%m%d-%H%M%S")
    codigo = asyncio.run(correr(carpeta))
    if codigo:
        print(f"Capturas y logs en {carpeta}")
    else:
        shutil.rmtree(carpeta, ignore_errors=True)  # todo bien: no queda nada para mirar
    return codigo


if __name__ == "__main__":
    sys.exit(main())

"""Aplica a speaker_perfil la validación de perfiles de Crustdata: la manual (link por link) y la auditoría con LLM.

Solo cambia calidad_match (y el cargo y la empresa donde la validación manual los corrigió). No borra datos: la app
oculta los perfiles descartados y muestra los que están a revisar con un aviso de que puede no ser esa persona.

Fuentes (en ~/Documents/Proyectos/Scripts/reinventar/out/):
  validar_speakers_respuestas.json   validación manual: valido → confiable, descartado → descartado, saltear → revisar
  auditoria_perfiles.csv             auditoría con LLM: otra → descartado; misma no cambia
  dudosos_opus_respuestas.json       dudosos de la auditoría: valido (abierto a mano) → confiable; el resto → revisar
Lo validado a mano gana sobre la auditoría.

Sin --aplicar corre en una transacción, muestra qué cambiaría y hace ROLLBACK.
Con --aplicar hace backup (pg_dump del docker local) y confirma.
"""
import argparse
import collections
import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

from scripts.actualizar_catalogo import _HOSTS_LOCALES, _backup

OUT = Path(os.environ.get("AUDIT_OUT_DIR", "~/Documents/Proyectos/Scripts/reinventar/out")).expanduser()
MANUAL = {"valido": "confiable", "cambio_empresa": "confiable", "descartado": "descartado", "saltear": "revisar"}
NOTA_EN_BLOQUE = "dado por válido en bloque"


@dataclass(frozen=True)
class Cambio:
    id_speaker: int
    calidad: str
    origen: str
    cargo: str | None = None
    empresa: str | None = None


def desde_manual(respuestas: dict) -> dict[int, Cambio]:
    return {int(i): Cambio(int(i), MANUAL[r["decision"]], "manual", r.get("cargo"), r.get("empresa") if r.get("cargo") else None)
            for i, r in respuestas.items() if r.get("decision") in MANUAL}


def desde_auditoria(filas: list[dict], dudosos: dict) -> dict[int, Cambio]:
    cambios = {}
    for f in filas:
        i = int(f["id_speaker"])
        if f["veredicto"] == "otra":
            cambios[i] = Cambio(i, "descartado", "auditoría")
        elif f["veredicto"] == "dudosa" and str(i) in dudosos:
            r = dudosos[str(i)]
            abierto = r.get("decision") == "valido" and r.get("nota") != NOTA_EN_BLOQUE
            cambios[i] = Cambio(i, "confiable" if abierto else "revisar", "auditoría (dudoso)")
    return cambios


def combinar(manual: dict[int, Cambio], auditoria: dict[int, Cambio]) -> dict[int, Cambio]:
    return {**auditoria, **manual}  # lo validado a mano gana


def aplicar(conn: psycopg.Connection, cambios: dict[int, Cambio], schema: str = "reinvent") -> collections.Counter:
    """Actualiza y devuelve un conteo (origen, antes → después). Solo cuenta lo que realmente cambia."""
    s = sql.Identifier(schema)
    antes = dict(conn.execute(sql.SQL("SELECT id_speaker, calidad_match FROM {}.speaker_perfil WHERE id_speaker = ANY(%s)")
                              .format(s), (list(cambios),)).fetchall())
    conteo = collections.Counter()
    for c in cambios.values():
        if c.id_speaker not in antes:
            conteo[(c.origen, "sin perfil en la base")] += 1
            continue
        if antes[c.id_speaker] == c.calidad and not c.cargo:
            continue
        conn.execute(sql.SQL("""UPDATE {}.speaker_perfil SET calidad_match = %s,
                                cargo_actual = coalesce(%s, cargo_actual), empresa_actual = coalesce(%s, empresa_actual)
                                WHERE id_speaker = %s""").format(s), (c.calidad, c.cargo, c.empresa, c.id_speaker))
        conteo[(c.origen, f"{antes[c.id_speaker] or '—'} → {c.calidad}")] += 1
    return conteo


def leer_fuentes(out: Path) -> dict[int, Cambio]:
    manual = json.loads((out / "validar_speakers_respuestas.json").read_text())
    with (out / "auditoria_perfiles.csv").open(encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))
    dudosos = json.loads((out / "dudosos_opus_respuestas.json").read_text())
    return combinar(desde_manual(manual), desde_auditoria(filas, dudosos))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true", help="backup y commit (sin esto: ROLLBACK)")
    ap.add_argument("--schema", default="reinvent")
    args = ap.parse_args()

    url = os.environ.get("REINVENT_DATABASE_URL")
    if not url:
        sys.exit("Falta REINVENT_DATABASE_URL (Postgres del docker local).")
    if args.aplicar and not any(h in url for h in _HOSTS_LOCALES):
        sys.exit("--aplicar solo contra el docker local (localhost). A Railway se sube con scripts/sync_to_railway.sh.")
    try:
        cambios = leer_fuentes(OUT)
    except (OSError, ValueError, KeyError) as e:
        sys.exit(f"No pude leer las validaciones en {OUT}: {e}")

    backup = _backup(args.schema) if args.aplicar else None
    with psycopg.connect(url) as conn:
        conteo = aplicar(conn, cambios, args.schema)
        estado = conn.execute(sql.SQL("SELECT coalesce(calidad_match, '(no encontrado)'), count(*) FROM {}.speaker_perfil "
                                      "GROUP BY 1 ORDER BY 2 DESC").format(sql.Identifier(args.schema))).fetchall()
        if args.aplicar:
            conn.commit()
        else:
            conn.rollback()

    print(f"> {len(cambios)} perfiles con decisión" + ("" if args.aplicar else " · MODO PRUEBA: ROLLBACK, no se guardó nada"))
    for (origen, cambio), n in sorted(conteo.items()):
        print(f"  {origen:<20} {cambio:<28} {n}")
    print("\nCómo queda speaker_perfil:")
    for calidad, n in estado:
        print(f"  {calidad:<16} {n}")
    if backup:
        print(f"\nBackup previo: {backup}")


if __name__ == "__main__":
    main()

"""Audita con un LLM los perfiles de Crustdata marcados como confiables con reglas viejas: ¿es el speaker o un homónimo?

Usa solo lo que ya está guardado en speaker_perfil (cargo, empresa, trayectoria): no gasta créditos de Crustdata.
No escribe en la base: deja los veredictos en un CSV para revisar los dudosos a mano y aplicarlos después.

Qué audita (por defecto): los confiables de speakers de Amazon cuyo cargo en LinkedIn no se parece al del catálogo,
y los confiables cuyo speaker no tiene cargo en el catálogo.

Uso (desde la raíz del repo):
  export REINVENT_DATABASE_URL='postgresql://reinvent:<clave>@localhost:5433/reinvent'
  export ANTHROPIC_API_KEY=...
  python -m scripts.auditar_perfiles --validados respuestas.json   # mide contra lo validado a mano, no audita
  python -m scripts.auditar_perfiles --limite 20                   # muestra
  python -m scripts.auditar_perfiles                               # todos los sospechosos → CSV
  python -m scripts.auditar_perfiles --modelo claude-opus-5-5      # otro modelo (default: AUDIT_MODEL)
"""
import argparse
import collections
import csv
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

from app import config, llm, prompts
from scripts import lotes_llm
from scripts.enriquecer_speakers import MIN_CARGO_EMPRESA_GRANDE, _similitud

MODELO = os.environ.get("AUDIT_MODEL", "claude-fable-5-1")
LOTE = 15
HILOS = 4
MAX_TOKENS = 32000
MAX_EMPLEOS = 8
MAX_SKILLS = 12
MAX_CHARLAS = 2
SALIDA = Path(os.environ.get("AUDIT_OUT", "~/Documents/Proyectos/Scripts/reinventar/out/auditoria_perfiles.csv")).expanduser()
# Decisiones de la validación manual → veredicto esperado (saltear no cuenta).
ESPERADO = {"valido": "misma", "cambio_empresa": "misma", "descartado": "otra"}

Completar = Callable[[str, str, str, int], str]


@dataclass(frozen=True)
class Caso:
    id_speaker: int
    nombre: str
    cargo_catalogo: str | None
    empresa_catalogo: str | None
    es_amazon: bool
    charlas: tuple[str, ...]
    cargo: str | None
    empresa: str | None
    headline: str | None
    ubicacion: str | None
    trayectoria: tuple[dict, ...]
    skills: tuple[str, ...]
    linkedin: str | None

    def para_llm(self) -> dict:
        return {"id": self.id_speaker,
                "catalogo": {"nombre": self.nombre, "cargo": self.cargo_catalogo, "empresa": self.empresa_catalogo,
                             "charlas": list(self.charlas)},
                "perfil": {"cargo_actual": self.cargo, "empresa_actual": self.empresa, "headline": self.headline,
                           "ubicacion": self.ubicacion, "trayectoria": list(self.trayectoria[:MAX_EMPLEOS]),
                           "skills": list(self.skills[:MAX_SKILLS])}}


@dataclass(frozen=True)
class Veredicto:
    veredicto: str
    motivo: str


_CASOS = """
SELECT p.id_speaker, sk.nombre,
       (SELECT ss.cargo_en_charla FROM {s}.speech_speaker ss
        WHERE ss.id_speaker = sk.id_speaker AND coalesce(ss.cargo_en_charla, '') <> ''
        GROUP BY ss.cargo_en_charla ORDER BY count(*) DESC, ss.cargo_en_charla LIMIT 1),
       pr.empresa, coalesce(pr.es_amazon, false),
       (SELECT array_agg(DISTINCT sp.titulo) FROM {s}.speech_speaker ss JOIN {s}.speech sp USING (id_speech)
        WHERE ss.id_speaker = sk.id_speaker),
       p.cargo_actual, p.empresa_actual, p.headline, p.ubicacion, coalesce(p.trayectoria, '[]'::jsonb),
       coalesce(p.skills, '{{}}'), p.linkedin_url
FROM {s}.speaker_perfil p
JOIN {s}.speaker sk USING (id_speaker)
LEFT JOIN {s}.v_speaker_empresa_principal pr USING (id_speaker)
WHERE (%(ids)s::int[] IS NULL AND p.calidad_match = 'confiable') OR p.id_speaker = ANY(%(ids)s::int[])
ORDER BY p.id_speaker
"""


def leer_casos(conn: psycopg.Connection, schema: str = "reinvent", ids: list[int] | None = None) -> list[Caso]:
    filas = conn.execute(sql.SQL(_CASOS).format(s=sql.Identifier(schema)), {"ids": ids}).fetchall()
    return [Caso(f[0], f[1], f[2], f[3], f[4], tuple(sorted(f[5] or ()))[:MAX_CHARLAS], f[6], f[7], f[8], f[9],
                 tuple(f[10]), tuple(f[11]), f[12]) for f in filas]


def sospechoso(c: Caso) -> bool:
    """Lo que la regla nueva no daría por confiable: Amazon con cargo distinto, o sin cargo en el catálogo."""
    if not c.cargo_catalogo:
        return True
    return c.es_amazon and _similitud(c.cargo_catalogo, c.cargo) < MIN_CARGO_EMPRESA_GRANDE


def leer_veredictos(respuesta: str, ids: list[int], *, parcial: bool = False) -> dict[int, Veredicto]:
    """Valida la respuesta. Con parcial, los ids que faltan no son error (se vuelven a pedir aparte)."""
    try:
        casos = {int(c["id"]): c for c in llm.parse_json(respuesta)["casos"]}
        salida = {i: Veredicto(str(c["veredicto"]).strip().lower(), str(c.get("motivo", "")).strip())
                  for i, c in casos.items()}
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"respuesta ilegible: {e}") from e
    malos = [i for i, v in salida.items() if v.veredicto not in prompts.PROFILE_VERDICTS]
    faltan, sobran = [i for i in ids if i not in salida], set(salida) - set(ids)
    if malos or sobran or (faltan and not parcial):
        raise ValueError(f"veredictos inválidos {malos} / faltan {faltan} / sobran {sorted(sobran)}")
    return salida


def auditar(casos: list[Caso], *, modelo: str = MODELO, completar: Completar = llm.complete, lote: int = LOTE,
            hilos: int = HILOS, avisar: Callable[[str], None] = lambda _: None) -> tuple[dict[int, Veredicto], tuple[str, ...]]:
    resultados: dict[int, Veredicto] = {}

    def pedir(lt: list[Caso], parcial: bool) -> dict[int, Veredicto]:
        respuesta = completar(modelo, prompts.PROFILE_AUDIT_SYSTEM,
                              prompts.profile_audit_user([c.para_llm() for c in lt]), MAX_TOKENS)
        return leer_veredictos(respuesta, [c.id_speaker for c in lt], parcial=parcial)

    def llamar(lt: list[Caso]) -> dict[int, Veredicto]:
        """Si el modelo se saltea algún caso, se le vuelven a pedir solo esos (una vez)."""
        vs = pedir(lt, parcial=True)
        faltan = [c for c in lt if c.id_speaker not in vs]
        return {**vs, **pedir(faltan, parcial=False)} if faltan else vs

    def al_volver(_lt: list[Caso], vs: dict[int, Veredicto]) -> None:
        resultados.update(vs)
        avisar(f"  {len(resultados)}/{len(casos)} auditados")

    fallidos = lotes_llm.procesar(lotes_llm.en_lotes(casos, lote), llamar, al_volver, hilos=hilos,
                                  describir=lambda lt: str([c.id_speaker for c in lt]), avisar=avisar)
    return resultados, fallidos


def comparar(veredictos: dict[int, Veredicto], esperado: dict[int, str]) -> tuple[collections.Counter, list[int]]:
    """Matriz (esperado, veredicto) y los ids donde el LLM contradice lo validado a mano (misma ↔ otra)."""
    matriz = collections.Counter((esperado[i], v.veredicto) for i, v in veredictos.items() if i in esperado)
    errores = [i for i, v in veredictos.items() if i in esperado and {esperado[i], v.veredicto} == {"misma", "otra"}]
    return matriz, sorted(errores)


def esperado_de(path: Path) -> dict[int, str]:
    respuestas = json.loads(path.read_text())
    return {int(i): ESPERADO[r["decision"]] for i, r in respuestas.items() if r.get("decision") in ESPERADO}


def guardar_csv(path: Path, casos: list[Caso], veredictos: dict[int, Veredicto]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    orden = {"otra": 0, "dudosa": 1, "misma": 2}
    filas = sorted((c for c in casos if c.id_speaker in veredictos),
                   key=lambda c: (orden[veredictos[c.id_speaker].veredicto], c.nombre.casefold()))
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel/Numbers lo abren con acentos bien
        w = csv.writer(f, delimiter=";")
        w.writerow(["veredicto", "motivo", "id_speaker", "nombre", "cargo_catalogo", "empresa_catalogo",
                    "cargo_linkedin", "empresa_linkedin", "ubicacion", "linkedin_url"])
        for c in filas:
            v = veredictos[c.id_speaker]
            w.writerow([v.veredicto, v.motivo, c.id_speaker, c.nombre, c.cargo_catalogo, c.empresa_catalogo,
                        c.cargo, c.empresa, c.ubicacion, c.linkedin])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelo", default=MODELO)
    ap.add_argument("--validados", type=Path, help="JSON de la validación manual: mide el acierto y no audita nada más")
    ap.add_argument("--ids", type=lambda v: [int(x) for x in v.split(",") if x.strip()])
    ap.add_argument("--limite", type=int)
    ap.add_argument("--schema", default="reinvent")
    args = ap.parse_args()

    url = os.environ.get("REINVENT_DATABASE_URL")
    if not url:
        sys.exit("Falta REINVENT_DATABASE_URL (Postgres del docker local).")
    if config.LLM_PROVIDER == "anthropic" and not config.ANTHROPIC_API_KEY:
        sys.exit("Falta ANTHROPIC_API_KEY.")

    esperado = esperado_de(args.validados.expanduser()) if args.validados else {}
    ids = sorted(esperado) if esperado else args.ids
    with psycopg.connect(url) as conn:
        casos = leer_casos(conn, args.schema, ids)
    if not ids:
        casos = [c for c in casos if sospechoso(c)]
    casos = casos[:args.limite] if args.limite else casos
    print(f"> {len(casos)} perfiles a auditar · modelo {args.modelo}")

    veredictos, fallidos = auditar(casos, modelo=args.modelo, avisar=print)
    print("\nVeredictos:", dict(collections.Counter(v.veredicto for v in veredictos.values())))
    if esperado:
        matriz, errores = comparar(veredictos, esperado)
        print("\nValidado a mano → LLM:")
        for (e, v), n in sorted(matriz.items()):
            print(f"  {e:>6} → {v:<7} {n}")
        por_id = {c.id_speaker: c for c in casos}
        for i in errores:
            c = por_id[i]
            print(f"\n  ✗ [{i}] {c.nombre}: a mano {esperado[i]}, LLM {veredictos[i].veredicto}"
                  f"\n    catálogo: {c.cargo_catalogo} @ {c.empresa_catalogo} · LinkedIn: {c.cargo} @ {c.empresa}"
                  f"\n    {veredictos[i].motivo}")
    salida = SALIDA.with_name(SALIDA.stem + ("_validacion" if esperado else "") + SALIDA.suffix)
    guardar_csv(salida, casos, veredictos)
    print(f"\nCSV: {salida}")
    if fallidos:
        print(f"Lotes fallidos: {len(fallidos)} (volvé a correr el script)")
        sys.exit(1)


if __name__ == "__main__":
    main()

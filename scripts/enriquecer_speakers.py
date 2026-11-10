"""Busca en Crustdata los datos profesionales de los speakers con charla que no los tienen (speaker_perfil).

Grupos (se eligen con --grupos; por defecto todos):
  sin_perfil     nunca se buscaron (se sumaron al catálogo después de la primera corrida)
  no_encontrado  se buscaron y no aparecieron
  descartado     apareció alguien con ese nombre que no era la persona
  vacio          perfil encontrado pero sin cargo ni empresa

Búsqueda: primero nombre + empresa actual del catálogo; si no hay un match claro, solo por nombre, y decide con el
cargo que AWS muestra en la charla. Calidad: confiable (nombre y empresa actual), revisar (nombre y empresa en un
trabajo anterior, o cargo parecido, o varios candidatos) o descartado. Nunca empeora un perfil que ya existe.

Se puede cortar y volver a correr: no reconsulta en el día lo que ya consultó, y las respuestas quedan en un caché
local (CRUSTDATA_CACHE_DIR), así que --aplicar después del modo prueba no vuelve a pagar esas consultas.

Uso (desde la raíz del repo):
  export REINVENT_DATABASE_URL='postgresql://reinvent:<clave>@localhost:5433/reinvent'
  export CRUSTDATA_API_KEY=...
  python -m scripts.enriquecer_speakers                      # prueba con 10 speakers, no escribe
  python -m scripts.enriquecer_speakers --ids 60,694         # prueba con esos speakers
  python -m scripts.enriquecer_speakers --aplicar            # todos los pendientes, con backup previo
"""
import argparse
import datetime as dt
import os
import re
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from scripts.actualizar_catalogo import _HOSTS_LOCALES, _backup
from scripts.crustdata import Cliente, CrustdataError

GRUPOS = ("sin_perfil", "no_encontrado", "descartado", "vacio")
RANGO = {"confiable": 3, "revisar": 2, "descartado": 1}  # None (no encontrado) = 0
MIN_SIMILITUD_CARGO = 0.5
# En Amazon (enorme, con muchos homónimos) coincidir en la empresa no alcanza: el cargo también se tiene que parecer.
MIN_CARGO_EMPRESA_GRANDE = 0.2
LIMITE_CON_EMPRESA, LIMITE_SOLO_NOMBRE = 3, 5
MUESTRA = 10
COMMIT_CADA = 20
CACHE_DIR = Path(os.environ.get("CRUSTDATA_CACHE_DIR", "~/Documents/Proyectos/Scripts/reinventar/out/crustdata")).expanduser()
_SIN_PESO = {"inc", "llc", "ltd", "corp", "co", "the", "sa", "gmbh", "plc", "group", "company"}

Buscar = Callable[[dict, int], list[dict]]


@dataclass(frozen=True)
class Speaker:
    id_speaker: int
    nombre: str
    empresa: str | None      # empresa principal en el catálogo
    es_amazon: bool
    cargo: str | None        # el cargo que AWS muestra en sus charlas
    grupo: str
    calidad_actual: str | None


@dataclass(frozen=True)
class Decision:
    calidad: str | None      # None = no apareció nadie con ese nombre
    perfil: dict | None
    motivo: str


@dataclass(frozen=True)
class Resultado:
    decisiones: tuple[tuple[Speaker, Decision], ...]
    guardados: int
    sin_mejora: int


# ---------- Comparaciones ----------

def _tokens(texto: str | None) -> set[str]:
    plano = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z0-9]+", plano))


def _palabras(texto: str | None) -> list[str]:
    plano = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", plano)


def nombre_coincide(buscado: str, candidato: str | None) -> bool:
    """Mismo nombre de pila y mismo apellido (el último del catálogo, en cualquier lugar después del nombre del
    candidato). Si el catálogo solo tiene la inicial ("Adam B"), el apellido del candidato tiene que empezar con esa letra."""
    b, c = _palabras(nombre_limpio(buscado)), _palabras(candidato)
    if len(b) < 2 or len(c) < 2 or b[0] != c[0]:
        return bool(b) and b == c
    apellido = b[-1]
    if len(apellido) == 1:
        return c[-1].startswith(apellido)
    return apellido in c[1:]


def nombre_limpio(nombre: str) -> str:
    """Sin agregados entre paréntesis: 'Alex Torres (AWS)' → 'Alex Torres'."""
    return re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", nombre)).strip()


def _empresa_coincide(sp: Speaker, empresa: str | None) -> bool:
    t = _tokens(empresa) - _SIN_PESO
    if not t or not sp.empresa:
        return False
    if sp.es_amazon:
        return bool(t & {"amazon", "aws"})
    e = _tokens(sp.empresa) - _SIN_PESO
    return bool(e) and (e <= t or t <= e)


def _similitud(a: str | None, b: str | None) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _empleos(perfil: dict, cuales: str) -> list[dict]:
    return ((perfil.get("experience") or {}).get("employment_details") or {}).get(cuales) or []


def _empresa_de(empleo: dict) -> str | None:
    return empleo.get("company_name") or empleo.get("name")


# ---------- Decisión ----------

def filtros(sp: Speaker, con_empresa: bool) -> dict:
    nombre = {"field": "basic_profile.name", "type": "(.)", "value": nombre_limpio(sp.nombre)}
    if not con_empresa:
        return nombre
    empresa = {"field": "experience.employment_details.current.company_name", "type": "(.)",
               "value": "Amazon" if sp.es_amazon else sp.empresa}
    return {"op": "and", "conditions": [nombre, empresa]}


def decidir(sp: Speaker, perfiles: list[dict]) -> Decision:
    mismos = [p for p in perfiles if nombre_coincide(sp.nombre, (p.get("basic_profile") or {}).get("name"))]
    if not mismos:
        return Decision(None, None, "nadie con ese nombre")

    def cargo(p: dict) -> float:
        return max((_similitud(sp.cargo, e.get("title")) for e in _empleos(p, "current")), default=0.0)

    def trabaja_en(p: dict, cuales: str) -> bool:
        return any(_empresa_coincide(sp, _empresa_de(e)) for e in _empleos(p, cuales))

    actual = sorted((p for p in mismos if trabaja_en(p, "current")), key=cargo, reverse=True)
    if actual:
        return _decidir_actual(sp, actual, [cargo(p) for p in actual[:2]])
    antes = [p for p in mismos if trabaja_en(p, "past")]
    if len(antes) == 1:
        return Decision("revisar", antes[0], "la empresa aparece en un trabajo anterior")
    por_cargo = [p for p in mismos if cargo(p) >= MIN_SIMILITUD_CARGO]
    if len(por_cargo) == 1:
        return Decision("revisar", por_cargo[0], "el cargo coincide con el de la charla, la empresa no")
    return Decision("descartado", max(mismos, key=cargo), "hay personas con ese nombre pero ninguna encaja")


def _decidir_actual(sp: Speaker, actual: list[dict], cargos: list[float]) -> Decision:
    """Candidatos que hoy trabajan en la empresa del catálogo, ordenados por parecido del cargo (cargos: los 2 mejores)."""
    mejor, n = cargos[0], len(actual)
    if n > 1 and mejor == 0:
        return Decision("descartado", actual[0], f"{n} personas con ese nombre en la empresa y ninguna con un cargo parecido")
    if n > 1 and mejor <= cargos[1]:
        return Decision("revisar", actual[0], f"{n} personas con ese nombre en la empresa")
    if sp.es_amazon and mejor < MIN_CARGO_EMPRESA_GRANDE:
        return Decision("revisar", actual[0], "nombre y empresa coinciden pero el cargo no (en Amazon hay muchos homónimos)")
    return Decision("confiable", actual[0], "nombre, empresa actual y cargo" if mejor else "nombre y empresa actual")


def consultar(sp: Speaker, buscar: Buscar) -> Decision:
    """Nombre + empresa; si no alcanza para un match confiable, también solo por nombre."""
    primeros = buscar(filtros(sp, True), LIMITE_CON_EMPRESA) if sp.empresa else []
    decision = decidir(sp, primeros)
    if decision.calidad == "confiable":
        return decision
    vistos = {p.get("crustdata_person_id") for p in primeros}
    todos = primeros + [p for p in buscar(filtros(sp, False), LIMITE_SOLO_NOMBRE)
                        if p.get("crustdata_person_id") not in vistos]
    return decidir(sp, todos)


# ---------- Fila de speaker_perfil ----------

def _fecha(valor: str | None) -> dt.date | None:
    m = re.match(r"(\d{4})-(\d{2})(?:-(\d{2}))?", valor or "")
    return dt.date(int(m[1]), int(m[2]), int(m[3] or 1)) if m else None


def _mes(valor: str | None) -> str | None:
    return (valor or "")[:7] or None


def a_fila(sp: Speaker, d: Decision, hoy: dt.date) -> dict:
    """La decisión con el mismo formato que los perfiles que ya están en speaker_perfil."""
    base = {"fuente": "crustdata", "fecha_consulta": hoy, "calidad_match": d.calidad}
    if d.perfil is None:
        return {**base, "encontrado": False}
    p = d.perfil
    actuales = _empleos(p, "current")
    principal = next((e for e in actuales if _empresa_coincide(sp, _empresa_de(e))), actuales[0] if actuales else {})
    perfil_basico, redes = p.get("basic_profile") or {}, p.get("social_handles") or {}
    lugar = perfil_basico.get("location") or {}
    otros = [f"{e.get('title')} @ {_empresa_de(e)}" for e in actuales if e is not principal and e.get("title")]
    return {
        **base, "encontrado": True, "verificar": d.calidad == "revisar",
        "crustdata_person_id": p.get("crustdata_person_id"),
        "cargo_actual": principal.get("title"), "empresa_actual": _empresa_de(principal),
        "seniority": principal.get("seniority_level"), "cargo_desde": _fecha(principal.get("start_date")),
        "industria_empresa": (principal.get("company_industries") or [None])[0],
        "headline": perfil_basico.get("headline"),
        "ubicacion": lugar.get("raw") or ", ".join(filter(None, (lugar.get("city"), lugar.get("state"),
                                                                lugar.get("country")))) or None,
        "linkedin_url": (redes.get("professional_network_identifier") or {}).get("profile_url"),
        "github_url": (redes.get("dev_platform_identifier") or {}).get("profile_url"),
        "x_handle": (redes.get("twitter_identifier") or {}).get("slug"),
        "otros_roles_actuales": " | ".join(otros) or None,
        "trayectoria": Jsonb([{"cargo": e.get("title"), "desde": _mes(e.get("start_date")),
                               "hasta": _mes(e.get("end_date")), "empresa": _empresa_de(e)}
                              for e in _empleos(p, "past")]),
        "educacion": Jsonb([{"area": s.get("field_of_study"), "titulo": s.get("degree"), "institucion": s.get("school")}
                            for s in (p.get("education") or {}).get("schools") or []]),
    }


def mejora(sp: Speaker, fila: dict) -> bool:
    """Solo se escribe si el resultado es mejor que lo que había (un perfil vacío mejora con cargo o empresa)."""
    nuevo, actual = RANGO.get(fila["calidad_match"], 0), RANGO.get(sp.calidad_actual, 0)
    if sp.grupo == "sin_perfil" or nuevo > actual:
        return True
    return sp.grupo == "vacio" and nuevo >= actual > 0 and bool(fila.get("cargo_actual") or fila.get("empresa_actual"))


# ---------- Base ----------

_PENDIENTES = """
SELECT sk.id_speaker, sk.nombre, pr.empresa, coalesce(pr.es_amazon, false),
       (SELECT ss.cargo_en_charla FROM {s}.speech_speaker ss
        WHERE ss.id_speaker = sk.id_speaker AND coalesce(ss.cargo_en_charla, '') <> ''
        GROUP BY ss.cargo_en_charla ORDER BY count(*) DESC, ss.cargo_en_charla LIMIT 1),
       CASE WHEN p.id_speaker IS NULL THEN 'sin_perfil'
            WHEN NOT p.encontrado THEN 'no_encontrado'
            WHEN p.calidad_match = 'descartado' THEN 'descartado'
            WHEN coalesce(p.cargo_actual, '') = '' AND coalesce(p.empresa_actual, '') = '' THEN 'vacio' END,
       p.calidad_match
FROM {s}.speaker sk
LEFT JOIN {s}.speaker_perfil p ON p.id_speaker = sk.id_speaker
LEFT JOIN {s}.v_speaker_empresa_principal pr ON pr.id_speaker = sk.id_speaker
WHERE EXISTS (SELECT 1 FROM {s}.speech_speaker ss WHERE ss.id_speaker = sk.id_speaker)
  AND (p.id_speaker IS NULL OR p.fecha_consulta < %(hoy)s)
  AND (%(ids)s::int[] IS NULL OR sk.id_speaker = ANY(%(ids)s::int[]))
ORDER BY sk.id_speaker
"""

_COLUMNAS = ("encontrado", "verificar", "crustdata_person_id", "cargo_actual", "empresa_actual", "seniority",
             "cargo_desde", "industria_empresa", "headline", "ubicacion", "linkedin_url", "github_url", "x_handle",
             "otros_roles_actuales", "trayectoria", "educacion", "fuente", "fecha_consulta", "calidad_match")


def pendientes(conn, schema: str, hoy: dt.date, grupos=GRUPOS, ids: list[int] | None = None) -> list[Speaker]:
    filas = conn.execute(sql.SQL(_PENDIENTES).format(s=sql.Identifier(schema)), {"hoy": hoy, "ids": ids}).fetchall()
    return [Speaker(*f) for f in filas if f[5] in grupos]


def guardar(conn, schema: str, sp: Speaker, fila: dict) -> bool:
    """Escribe el perfil si mejora; si no, solo anota que se consultó hoy. Devuelve si escribió el perfil."""
    s = sql.Identifier(schema)
    if not mejora(sp, fila):
        conn.execute(sql.SQL("UPDATE {}.speaker_perfil SET fecha_consulta = %s WHERE id_speaker = %s").format(s),
                     (fila["fecha_consulta"], sp.id_speaker))
        return False
    valores = {c: fila.get(c) for c in _COLUMNAS}
    columnas = sql.SQL(", ").join(map(sql.Identifier, ("id_speaker", *_COLUMNAS)))
    marcas = sql.SQL(", ").join(sql.Placeholder(c) for c in ("id_speaker", *_COLUMNAS))
    asignar = sql.SQL(", ").join(sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in _COLUMNAS)
    conn.execute(sql.SQL("INSERT INTO {}.speaker_perfil ({}) VALUES ({}) ON CONFLICT (id_speaker) DO UPDATE SET {}")
                 .format(s, columnas, marcas, asignar), {"id_speaker": sp.id_speaker, **valores})
    return True


def enriquecer(conn, buscar: Buscar, *, schema: str = "reinvent", aplicar: bool = False, grupos=GRUPOS,
               ids: list[int] | None = None, limite: int | None = None, hoy: dt.date | None = None,
               avisar: Callable[[str], None] = lambda _: None) -> Resultado:
    hoy = hoy or dt.date.today()
    todos = pendientes(conn, schema, hoy, grupos, ids)
    if not limite and not aplicar and not ids:
        limite = MUESTRA  # el modo prueba consulta una muestra: cada consulta gasta créditos
    todos = todos[:limite] if limite else todos
    decisiones, guardados, sin_mejora = [], 0, 0
    for n, sp in enumerate(todos, 1):
        d = consultar(sp, buscar)  # CrustdataError (credenciales, request inválido) corta todo: fallaría igual con los demás
        decisiones.append((sp, d))
        if aplicar:
            if guardar(conn, schema, sp, a_fila(sp, d, hoy)):
                guardados += 1
            else:
                sin_mejora += 1
            if n % COMMIT_CADA == 0:
                conn.commit()
                avisar(f"  {n}/{len(todos)} consultados · {guardados} perfiles guardados")
    if aplicar:
        conn.commit()
    return Resultado(tuple(decisiones), guardados, sin_mejora)


# ---------- CLI ----------

def _imprimir(r: Resultado) -> None:
    for sp, d in r.decisiones:
        fila = a_fila(sp, d, dt.date.today())
        hallado = f"{(d.perfil or {}).get('basic_profile', {}).get('name')} · {fila.get('cargo_actual') or 'sin cargo'} @ " \
                  f"{fila.get('empresa_actual') or 'sin empresa'}" if d.perfil else "—"
        print(f"\n[{sp.id_speaker}] {sp.nombre} · {sp.grupo} · catálogo: {sp.cargo or '—'} @ {sp.empresa or '—'}")
        print(f"   → {d.calidad or 'no encontrado'} ({d.motivo}): {hallado}"
              + ("" if mejora(sp, fila) else "   [no mejora lo que hay: no se escribe]"))
    calidades = [d.calidad or "no encontrado" for _, d in r.decisiones]
    print("\nResumen: " + ", ".join(f"{c} {calidades.count(c)}" for c in
                                    ("confiable", "revisar", "descartado", "no encontrado") if calidades.count(c)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true", help="consulta todos los pendientes y guarda (con backup)")
    ap.add_argument("--grupos", type=lambda v: tuple(g.strip() for g in v.split(",")), default=GRUPOS,
                    help=f"cuáles buscar, separados por coma ({', '.join(GRUPOS)})")
    ap.add_argument("--ids", type=lambda v: [int(i) for i in v.split(",") if i.strip()], help="solo estos id_speaker")
    ap.add_argument("--limite", type=int, help="como mucho esta cantidad de speakers")
    ap.add_argument("--schema", default="reinvent")
    args = ap.parse_args()
    if set(args.grupos) - set(GRUPOS):
        sys.exit(f"Grupos válidos: {', '.join(GRUPOS)}")
    url = os.environ.get("REINVENT_DATABASE_URL")
    if not url:
        sys.exit("Falta REINVENT_DATABASE_URL (Postgres del docker local).")
    if args.aplicar and not any(h in url for h in _HOSTS_LOCALES):
        sys.exit("--aplicar solo contra el docker local (localhost). A Railway se sube con scripts/sync_to_railway.sh.")
    try:
        cliente = Cliente(os.environ.get("CRUSTDATA_API_KEY", ""), CACHE_DIR)
    except CrustdataError as e:
        sys.exit(str(e))

    backup = _backup(args.schema) if args.aplicar else None
    with psycopg.connect(url) as conn:
        total = len(pendientes(conn, args.schema, dt.date.today(), args.grupos, args.ids))
        print(f"> {total} speakers pendientes ({', '.join(args.grupos)})"
              + ("" if args.aplicar else " · MODO PRUEBA: consulta Crustdata pero no escribe en la base"))
        try:
            r = enriquecer(conn, cliente.buscar, schema=args.schema, aplicar=args.aplicar, grupos=args.grupos,
                           ids=args.ids, limite=args.limite, avisar=print)
        except CrustdataError as e:
            conn.commit() if args.aplicar else conn.rollback()  # lo ya consultado queda guardado
            sys.exit(f"Crustdata cortó: {e}")
    _imprimir(r)
    print(f"\nConsultas a Crustdata: {cliente.consultas} (el resto salió del caché) · créditos: {cliente.creditos:.2f}")
    if args.aplicar:
        print(f"Perfiles guardados: {r.guardados} · consultados sin mejora: {r.sin_mejora} · backup previo: {backup}")


if __name__ == "__main__":
    main()

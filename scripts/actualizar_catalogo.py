"""Actualiza el schema reinvent con el catálogo oficial de AWS (sessions_full.json de bajar_catalogo_reinvent.py).

No es un reemplazo total: conserva ids de speaker, perfiles (speaker_perfil), empresas y alias curados.
  speech          upsert por código base
  speech_horario  upsert por código; los renombres se detectan por sessionTimeID y quedan en codigo_renombrado
  speaker         match por id de AWS (userRef); si no lo tiene, por nombre normalizado (salvo homónimos)
  speech_speaker  se sincroniza por charla, con rol y cargo
Las bajas (lo que AWS sacó) se reportan y solo se borran con --borrar-bajas.
Si AWS cambia un resumen, su traducción y sus claves se vacían para que traducir_resumenes.py y extraer_claves.py
las rehagan.

Por defecto corre en modo prueba: hace todo en una transacción, muestra el reporte y hace ROLLBACK.
Con --aplicar hace backup del schema (pg_dump en el docker local) y confirma.

Uso:
  export REINVENT_DATABASE_URL='postgresql://reinvent:<clave>@localhost:5433/reinvent'
  python -m scripts.actualizar_catalogo ~/Downloads/catalogo_reinvent/sessions_full.json            # prueba
  python -m scripts.actualizar_catalogo ~/Downloads/catalogo_reinvent/sessions_full.json --aplicar  # de verdad
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from psycopg import sql

from scripts.catalogo_oficial import (
    Catalogo,
    Homonimo,
    SpeakerExistente,
    clave,
    parsear,
    planear_speakers,
    speakers_oficiales,
)

MIGRACIONES = Path(__file__).parent / "migraciones"
MIGRAR_CODIGOS_APP = Path(__file__).parent / "migrar_codigos_app.sql"
_NOMBRE_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
MINIMO_PARA_BORRAR = 0.5  # con --borrar-bajas, el catálogo nuevo tiene que traer al menos la mitad de los horarios
_HOSTS_LOCALES = ("@localhost:", "@127.0.0.1:")
LOCAL_CONTAINER = os.environ.get("LOCAL_CONTAINER", "reinvent-pg")
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "~/Documents/Proyectos/Scripts/reinventar/backups_reinvent")).expanduser()


@dataclass(frozen=True)
class Reporte:
    cambios: dict[str, int]
    estado: dict[str, int]
    homonimos: tuple[Homonimo, ...] = ()
    renombres: list[tuple[str, str]] = field(default_factory=list)
    renombres_en_conflicto: list[tuple[str, str]] = field(default_factory=list)
    bajas_horarios: list[str] = field(default_factory=list)
    bajas_charlas: list[str] = field(default_factory=list)

    @property
    def total_cambios(self) -> int:
        return sum(self.cambios.values())


def _schema(nombre: str) -> sql.Identifier:
    if not _NOMBRE_SCHEMA.match(nombre):
        raise ValueError(f"Nombre de schema inválido: {nombre!r}")
    return sql.Identifier(nombre)


def aplicar_migraciones(conn: psycopg.Connection, schema: str = "reinvent") -> None:
    """Crea el schema si falta y corre las migraciones (todas idempotentes). Deja el search_path en ese schema."""
    ident = _schema(schema)
    conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(ident))
    conn.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(ident))
    for archivo in sorted(MIGRACIONES.glob("*.sql")):
        conn.execute(archivo.read_text(encoding="utf-8"))


# ---------- Temporales con el catálogo nuevo ----------

_TEMPORALES = """
DROP TABLE IF EXISTS pg_temp.n_speech, pg_temp.n_horario, pg_temp.n_part, pg_temp.sk_map, pg_temp.n_link;
CREATE TEMP TABLE n_speech (id_speech text, titulo text, tipo text, nivel smallint, topicos text[], servicios text[],
  area_interes text, formato text, roles text[], industria text[], es_lanzamiento boolean, es_sponsoreada boolean,
  speakers_ocultos boolean, duracion_min smallint, resumen text, speakers_original text, modificado timestamptz);
CREATE TEMP TABLE n_horario (codigo text, id_speech text, fecha date, hora_inicio time, hora_fin time, sede text,
  sala text, cupo integer, walk_up boolean, aws_session_id text, aws_time_id text, id_sede smallint);
CREATE TEMP TABLE n_part (id_speech text, aws_speaker_id text, nombre text, orden smallint, rol text, cargo text,
  empresa_original text);
CREATE TEMP TABLE sk_map (aws_speaker_id text, id_speaker integer, nombre text, nombre_clave text);
"""


def _copiar(conn, tabla: str, filas, columnas: str = "") -> None:
    with conn.cursor().copy(f"COPY {tabla} {columnas} FROM STDIN") as cp:
        for fila in filas:
            cp.write_row([list(v) if isinstance(v, tuple) else v for v in fila])


def _cargar_temporales(conn, cat: Catalogo) -> None:
    conn.execute(_TEMPORALES)
    _copiar(conn, "n_speech", ((c.id_speech, c.titulo, c.tipo, c.nivel, c.topicos, c.servicios, c.area_interes,
                                c.formato, c.roles, c.industria, c.es_lanzamiento, c.es_sponsoreada,
                                c.speakers_ocultos, c.duracion_min, c.resumen, c.speakers_original, c.modificado)
                               for c in cat.charlas))
    _copiar(conn, "n_horario", ((h.codigo, h.id_speech, h.fecha, h.hora_inicio, h.hora_fin, h.sede, h.sala, h.cupo,
                                 h.walk_up, h.aws_session_id, h.aws_time_id) for h in cat.horarios),
            "(codigo, id_speech, fecha, hora_inicio, hora_fin, sede, sala, cupo, walk_up, aws_session_id, aws_time_id)")
    _copiar(conn, "n_part", ((p.id_speech, p.aws_speaker_id, p.nombre, p.orden, p.rol, p.cargo, p.empresa_original)
                             for p in cat.participaciones))


# ---------- Charlas y horarios ----------

def _resolver_sedes(conn) -> None:
    """Texto de AWS → id_sede por sede_alias; un lugar dentro de la sede (bar, restaurante) queda como sala.
    Una sede que AWS agregue corta la carga antes de tocar nada: hay que sumarla a sede y sede_alias."""
    sin_mapear = [r[0] for r in conn.execute(
        "SELECT DISTINCT sede FROM n_horario n WHERE NOT EXISTS (SELECT 1 FROM sede_alias a WHERE a.alias = n.sede) "
        "ORDER BY 1").fetchall()]
    if sin_mapear:
        raise ValueError(f"Sedes nuevas sin mapear en sede_alias: {', '.join(sin_mapear)}. Agregalas con una "
                         "migración en scripts/migraciones (sede con sus coordenadas y sede_alias) y volvé a correr.")
    conn.execute("UPDATE n_horario n SET id_sede = a.id_sede, sala = coalesce(n.sala, a.lugar) "
                 "FROM sede_alias a WHERE a.alias = n.sede")


_COLS_SPEECH = ("titulo", "tipo", "nivel", "topicos", "servicios", "area_interes", "formato", "roles", "industria",
                "es_lanzamiento", "es_sponsoreada", "speakers_ocultos", "duracion_min", "resumen", "speakers_original",
                "modificado")
_COLS_HORARIO = ("id_speech", "fecha", "hora_inicio", "hora_fin", "id_sede", "sala", "cupo", "walk_up",
                 "aws_session_id", "aws_time_id")


def _upsert(conn, tabla: str, temporal: str, clave: str, cols: tuple[str, ...]) -> tuple[int, int]:
    """INSERT ... ON CONFLICT que solo toca las filas que cambian. Devuelve (nuevas, actualizadas)."""
    todas = ", ".join((clave, *cols))
    fila = ", ".join(f"t.{c}" for c in cols)
    nueva = ", ".join(f"EXCLUDED.{c}" for c in cols)
    asignar = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
    nuevas, actualizadas = conn.execute(f"""
      WITH up AS (
        INSERT INTO {tabla} AS t ({todas}) SELECT {todas} FROM {temporal}
        ON CONFLICT ({clave}) DO UPDATE SET {asignar} WHERE ({fila}) IS DISTINCT FROM ({nueva})
        RETURNING (xmax = 0) AS es_nueva)
      SELECT count(*) FILTER (WHERE es_nueva), count(*) FILTER (WHERE NOT es_nueva) FROM up""").fetchone()
    return nuevas, actualizadas


def _aplicables(pares: list[tuple], ocupados: set[str]) -> list[tuple]:
    """Un renombre se puede aplicar si el código nuevo está libre o lo deja libre otro renombre aplicable
    (cadenas A→B→C e intercambios A↔B). Se itera hasta que no cambia."""
    aplicables = list(pares)
    while True:
        salen = {viejo for viejo, _, _ in aplicables}
        siguen = [p for p in aplicables if p[1] not in ocupados or p[1] in salen]
        if len(siguen) == len(aplicables):
            return aplicables
        aplicables = siguen


def _renombres(conn) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Mismo sessionTimeID con otro código: AWS renombró el horario. Si el código nuevo está ocupado por otro horario
    que sigue existiendo, no se mueve: se reporta y al viejo se le quitan los ids de AWS (pasa a ser una baja)."""
    pares = conn.execute("""
      SELECT h.codigo, n.codigo, n.id_speech FROM speech_horario h JOIN n_horario n ON n.aws_time_id = h.aws_time_id
      WHERE h.codigo <> n.codigo ORDER BY h.codigo""").fetchall()
    ocupados = {r[0] for r in conn.execute("SELECT codigo FROM speech_horario WHERE codigo = ANY(%s)",
                                           ([nuevo for _, nuevo, _ in pares],)).fetchall()}
    aplicables = _aplicables(pares, ocupados)
    conflictos = [(viejo, nuevo) for viejo, nuevo, base in pares if (viejo, nuevo, base) not in aplicables]

    with conn.cursor() as cur:
        # Dos pasos (pasando por un código temporal) para que cadenas e intercambios no choquen con la PK.
        cur.executemany("UPDATE speech_horario SET codigo = '~' || codigo WHERE codigo = %s",
                        [(viejo,) for viejo, _, _ in aplicables])
        cur.executemany("UPDATE speech_horario SET codigo = %s, id_speech = %s WHERE codigo = '~' || %s",
                        [(nuevo, base, viejo) for viejo, nuevo, base in aplicables])
        cur.executemany("""
          INSERT INTO codigo_renombrado (codigo_viejo, codigo_nuevo, aws_time_id)
          SELECT %s, %s, aws_time_id FROM speech_horario WHERE codigo = %s
          ON CONFLICT (codigo_viejo) DO UPDATE SET codigo_nuevo = EXCLUDED.codigo_nuevo, detectado = now()""",
                        [(viejo, nuevo, nuevo) for viejo, nuevo, _ in aplicables])
        cur.executemany("UPDATE speech_horario SET aws_time_id = NULL, aws_session_id = NULL WHERE codigo = %s",
                        [(viejo,) for viejo, _ in conflictos])
    return [(viejo, nuevo) for viejo, nuevo, _ in aplicables], conflictos


def _horarios(conn) -> tuple[dict[str, int], list, list]:
    completados = conn.execute("""
      UPDATE speech_horario h SET aws_time_id = n.aws_time_id, aws_session_id = n.aws_session_id
      FROM n_horario n
      WHERE h.codigo = n.codigo AND h.aws_time_id IS NULL
        AND NOT EXISTS (SELECT 1 FROM speech_horario x WHERE x.aws_time_id = n.aws_time_id)""").rowcount
    renombres, conflictos = _renombres(conn)
    nuevos, actualizados = _upsert(conn, "speech_horario", "n_horario", "codigo", _COLS_HORARIO)
    # Si AWS vuelve a usar un código viejo, ya no es un renombre: no hay que migrar nada que apunte a él.
    conn.execute("DELETE FROM codigo_renombrado r WHERE EXISTS (SELECT 1 FROM speech_horario h WHERE h.codigo = r.codigo_viejo)")
    return ({"Horarios con id de AWS completado": completados, "Horarios renombrados": len(renombres),
             "Horarios nuevos": nuevos, "Horarios actualizados": actualizados}, renombres, conflictos)


def _verificar_tamano(conn) -> None:
    """Antes de borrar bajas: un JSON truncado o vacío no puede vaciar el catálogo."""
    nuevos, actuales = conn.execute("SELECT (SELECT count(*) FROM n_horario), (SELECT count(*) FROM speech_horario)").fetchone()
    if actuales and nuevos < actuales * MINIMO_PARA_BORRAR:
        raise ValueError(f"El catálogo nuevo es sospechosamente chico ({nuevos} horarios contra {actuales} en la base): "
                         "no se borra nada. Revisá la descarga.")


def _bajas(conn, borrar: bool, conflictos: list[tuple[str, str]]) -> tuple[dict[str, int], list[str], list[str]]:
    if borrar:
        _verificar_tamano(conn)
    horarios = [r[0] for r in conn.execute(
        "SELECT codigo FROM speech_horario h WHERE NOT EXISTS (SELECT 1 FROM n_horario n WHERE n.codigo = h.codigo) "
        "ORDER BY codigo").fetchall()]
    charlas = [r[0] for r in conn.execute(
        "SELECT id_speech FROM speech s WHERE NOT EXISTS (SELECT 1 FROM n_speech n WHERE n.id_speech = s.id_speech) "
        "ORDER BY id_speech").fetchall()]
    if not borrar:
        return {}, horarios, charlas
    # Los renombres que no se pudieron aplicar no se borran: los itinerarios que los usan quedarían sin destino.
    en_conflicto = {viejo for viejo, _ in conflictos}
    horarios = [h for h in horarios if h not in en_conflicto]
    conn.execute("DELETE FROM speech_horario WHERE codigo = ANY(%s)", (horarios,))
    conn.execute("DELETE FROM speech WHERE id_speech = ANY(%s)", (charlas,))
    return {"Horarios borrados (bajas)": len(horarios), "Charlas borradas (bajas)": len(charlas)}, [], []


# ---------- Speakers y vínculos ----------

def _speakers(conn, cat: Catalogo) -> tuple[dict[str, int], tuple[Homonimo, ...]]:
    existentes = [SpeakerExistente(*r) for r in conn.execute("""
      SELECT k.id_speaker, k.nombre, k.nombre_clave, k.aws_speaker_id, p.empresa_actual
      FROM speaker k LEFT JOIN speaker_perfil p USING (id_speaker)""").fetchall()]
    oficiales = speakers_oficiales(cat)
    plan = planear_speakers(existentes, oficiales)

    with conn.cursor() as cur:
        cur.executemany("UPDATE speaker SET aws_speaker_id = %s WHERE id_speaker = %s",
                        [(ref, id_speaker) for id_speaker, ref in plan.ids_completados.items()])
    ids = dict(plan.asignados)
    for n in plan.nuevos:
        ids[n.aws_speaker_id] = conn.execute(
            "INSERT INTO speaker (nombre, nombre_clave, aws_speaker_id) VALUES (%s, %s, %s) RETURNING id_speaker",
            (n.nombre, n.nombre_clave, n.aws_speaker_id)).fetchone()[0]

    _copiar(conn, "sk_map", ((o.aws_speaker_id, ids[o.aws_speaker_id], o.nombre, clave(o.nombre)) for o in oficiales))
    renombrados = conn.execute("""
      UPDATE speaker k SET nombre = m.nombre, nombre_clave = m.nombre_clave FROM sk_map m
      WHERE k.id_speaker = m.id_speaker AND (k.nombre, k.nombre_clave) IS DISTINCT FROM (m.nombre, m.nombre_clave)""").rowcount
    return ({"Speakers con id de AWS completado": len(plan.ids_completados), "Speakers nuevos": len(plan.nuevos),
             "Nombres de speaker actualizados": renombrados}, plan.homonimos)


_VINCULOS = """
CREATE TEMP TABLE n_link AS
SELECT p.id_speech, m.id_speaker, p.orden, p.rol, p.cargo, p.empresa_original,
       coalesce((SELECT a.id_empresa FROM empresa_alias a
                 WHERE lower(a.alias) = lower(p.empresa_original) AND a.id_empresa IS NOT NULL ORDER BY a.alias LIMIT 1),
                (SELECT e.id_empresa FROM empresa e WHERE lower(e.nombre) = lower(p.empresa_original) LIMIT 1)) AS id_empresa
FROM n_part p JOIN sk_map m USING (aws_speaker_id);
"""


def _vinculos(conn) -> dict[str, int]:
    conn.execute(_VINCULOS)
    quitados = conn.execute("""
      DELETE FROM speech_speaker ss
      -- Solo charlas que en el oficial traen speakers: si AWS los oculta o vienen vacíos, se conservan los curados.
      WHERE ss.id_speech IN (SELECT id_speech FROM n_part)
        AND NOT EXISTS (SELECT 1 FROM n_link l WHERE l.id_speech = ss.id_speech AND l.id_speaker = ss.id_speaker)""").rowcount
    actualizados = conn.execute("""
      UPDATE speech_speaker ss
      SET orden = l.orden, rol = l.rol, cargo_en_charla = l.cargo,
          empresa_original = coalesce(l.empresa_original, ss.empresa_original),
          id_empresa = coalesce(ss.id_empresa, l.id_empresa)
      FROM n_link l
      WHERE l.id_speech = ss.id_speech AND l.id_speaker = ss.id_speaker
        AND (ss.orden, ss.rol, ss.cargo_en_charla, ss.empresa_original, ss.id_empresa) IS DISTINCT FROM
            (l.orden, l.rol, l.cargo, coalesce(l.empresa_original, ss.empresa_original), coalesce(ss.id_empresa, l.id_empresa))
      """).rowcount
    nuevos = conn.execute("""
      INSERT INTO speech_speaker (id_speech, id_speaker, id_empresa, orden, empresa_original, rol, cargo_en_charla)
      SELECT l.id_speech, l.id_speaker, l.id_empresa, l.orden, l.empresa_original, l.rol, l.cargo FROM n_link l
      WHERE NOT EXISTS (SELECT 1 FROM speech_speaker ss WHERE ss.id_speech = l.id_speech AND ss.id_speaker = l.id_speaker)
      """).rowcount
    return {"Vínculos charla-speaker quitados": quitados, "Vínculos charla-speaker actualizados": actualizados,
            "Vínculos charla-speaker nuevos": nuevos}


_ESTADO = """
SELECT (SELECT count(*) FROM speech), (SELECT count(*) FROM speech_horario),
       (SELECT count(*) FROM speech_horario WHERE aws_time_id IS NULL),
       (SELECT count(*) FROM speaker), (SELECT count(*) FROM speaker WHERE aws_speaker_id IS NULL),
       (SELECT count(*) FROM speaker k WHERE NOT EXISTS (SELECT 1 FROM speech_speaker ss WHERE ss.id_speaker = k.id_speaker)),
       (SELECT count(*) FROM speaker_perfil), (SELECT count(*) FROM speech_speaker), (SELECT count(*) FROM codigo_renombrado),
       (SELECT count(*) FROM speech WHERE resumen_es IS NULL AND coalesce(resumen, '') <> ''),
       (SELECT count(*) FROM speech WHERE conceptos IS NULL AND coalesce(resumen, '') <> '')
"""
_CONCEPTOS_ESTADO = ("Charlas", "Horarios", "Horarios sin id de AWS", "Speakers", "Speakers sin id de AWS",
                     "Speakers sin charla (fuera del catálogo)", "Perfiles de speaker", "Vínculos charla-speaker",
                     "Códigos renombrados (histórico)", "Resúmenes sin traducir (traducir_resumenes.py)",
                     "Resúmenes sin claves (extraer_claves.py)")


def _invalidar_derivados(conn) -> int:
    """Si AWS cambió el resumen, su traducción y sus claves quedaron viejas: se vacían y los scripts las rehacen."""
    return conn.execute("""
      UPDATE speech s SET resumen_es = NULL, servicios_mencionados = NULL, tecnologias = NULL, conceptos = NULL,
                          conceptos_en = NULL, enfoque = NULL
      FROM n_speech n
      WHERE n.id_speech = s.id_speech AND (s.resumen_es IS NOT NULL OR s.conceptos IS NOT NULL)
        AND n.resumen IS DISTINCT FROM s.resumen""").rowcount


def actualizar(conn: psycopg.Connection, cat: Catalogo, *, schema: str = "reinvent",
               borrar_bajas: bool = False) -> Reporte:
    """Aplica el catálogo dentro de la transacción de conn; quien llama decide COMMIT o ROLLBACK."""
    aplicar_migraciones(conn, schema)
    _cargar_temporales(conn, cat)
    _resolver_sedes(conn)
    cambios: dict[str, int] = {"Resúmenes a reprocesar (traducción y claves)": _invalidar_derivados(conn)}
    cambios["Charlas nuevas"], cambios["Charlas actualizadas"] = _upsert(conn, "speech", "n_speech", "id_speech",
                                                                         _COLS_SPEECH)
    horarios, renombres, conflictos = _horarios(conn)
    bajas, bajas_horarios, bajas_charlas = _bajas(conn, borrar_bajas, conflictos)
    speakers, homonimos = _speakers(conn, cat)
    cambios |= horarios | bajas | speakers | _vinculos(conn)
    estado = dict(zip(_CONCEPTOS_ESTADO, conn.execute(_ESTADO).fetchone(), strict=False))
    return Reporte(cambios, estado, homonimos, renombres, conflictos, bajas_horarios, bajas_charlas)


def migrar_codigos_app(conn: psycopg.Connection, schema: str = "reinvent", schema_app: str = "app") -> int:
    """Corre migrar_codigos_app.sql y devuelve cuántos itinerarios y grabaciones siguen apuntando a códigos inexistentes."""
    texto = (MIGRAR_CODIGOS_APP.read_text(encoding="utf-8")
             .replace(':"catalogo"', _schema(schema).as_string(conn))
             .replace(':"app"', _schema(schema_app).as_string(conn)))
    conn.execute(texto)
    return huerfanos_app(conn, schema, schema_app)


def huerfanos_app(conn: psycopg.Connection, schema: str = "reinvent", schema_app: str = "app") -> int:
    query = sql.SQL("""
      SELECT (SELECT count(*) FROM {a}.itinerary_items i
              WHERE NOT EXISTS (SELECT 1 FROM {s}.speech_horario h WHERE h.codigo = i.code))
           + (SELECT count(*) FROM {a}.sessions g WHERE coalesce(g.code, '') <> ''
              AND NOT EXISTS (SELECT 1 FROM {s}.speech_horario h WHERE h.codigo = upper(g.code))
              AND NOT EXISTS (SELECT 1 FROM {s}.speech p WHERE p.id_speech = upper(g.code)))""")
    return conn.execute(query.format(s=_schema(schema), a=_schema(schema_app))).fetchone()[0]


# ---------- CLI ----------

_IDENTIFICADOR = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def _backup(schema: str) -> Path:
    # El schema y el contenedor van como argumentos de pg_dump/docker: solo identificadores simples (nada que empiece
    # con "-" ni con espacios), y el schema en la forma --schema=valor para que no se pueda leer como otra opción.
    if not _IDENTIFICADOR.fullmatch(schema) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", LOCAL_CONTAINER):
        sys.exit(f"Schema o contenedor inválido ({schema!r}, {LOCAL_CONTAINER!r}); no se aplicó nada.")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destino = BACKUP_DIR / f"{schema}_antes_actualizar_{dt.datetime.now():%Y%m%d-%H%M%S}.dump"
    with destino.open("wb") as f:
        r = subprocess.run(["docker", "exec", LOCAL_CONTAINER, "pg_dump", "-U", "reinvent", "-d", "reinvent",
                            f"--schema={schema}", "-Fc", "--no-owner", "--no-privileges"], stdout=f, check=False)
    if r.returncode != 0:
        destino.unlink(missing_ok=True)
        sys.exit("Falló el backup; no se aplicó nada.")
    return destino


def _imprimir(reporte: Reporte, huerfanos: int | None) -> None:
    ancho = max(map(len, [*reporte.cambios, *reporte.estado])) + 2
    print("Cambios")
    for concepto, n in reporte.cambios.items():
        print(f"  {concepto:<{ancho}}{n:>7}")
    print(f"  {'TOTAL':<{ancho}}{reporte.total_cambios:>7}\n\nEstado después")
    for concepto, n in reporte.estado.items():
        print(f"  {concepto:<{ancho}}{n:>7}")
    if reporte.homonimos:
        print("\nHomónimos separados (revisá que el perfil haya quedado con la persona correcta)")
        for h in reporte.homonimos:
            print(f"  {h.nombre}: id {h.id_speaker} → {h.aws_speaker_id} ({h.criterio}); nuevos: {', '.join(h.otros)}")
    for titulo, filas in (("Renombres", reporte.renombres), ("Renombres NO aplicados (el código nuevo ya existía)",
                                                              reporte.renombres_en_conflicto)):
        if filas:
            print(f"\n{titulo}: " + ", ".join(f"{v} → {n}" for v, n in filas))
    if reporte.bajas_horarios or reporte.bajas_charlas:
        print(f"\nBajas pendientes (se borran con --borrar-bajas): {len(reporte.bajas_horarios)} horarios, "
              f"{len(reporte.bajas_charlas)} charlas")
        print("  horarios: " + ", ".join(reporte.bajas_horarios[:40]) + (" …" if len(reporte.bajas_horarios) > 40 else ""))
        print("  charlas:  " + ", ".join(reporte.bajas_charlas[:40]) + (" …" if len(reporte.bajas_charlas) > 40 else ""))
    if huerfanos is not None:
        print(f"\nItinerarios y grabaciones de este Postgres que apuntan a códigos inexistentes: {huerfanos}")


def _tiene_app(conn, schema_app: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL", (f"{schema_app}.itinerary_items",)).fetchone()[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json", type=Path, help="sessions_full.json crudo del catálogo oficial")
    ap.add_argument("--aplicar", action="store_true", help="confirma los cambios (sin esto: reporte y ROLLBACK)")
    ap.add_argument("--borrar-bajas", action="store_true", help="borra horarios y charlas que AWS sacó")
    ap.add_argument("--schema", default="reinvent")
    ap.add_argument("--schema-app", default="app", help="schema de la app, para contar huérfanos")
    args = ap.parse_args()

    url = os.environ.get("REINVENT_DATABASE_URL")
    if not url:
        sys.exit("Falta REINVENT_DATABASE_URL (Postgres del docker local).")
    if args.aplicar and not any(h in url for h in _HOSTS_LOCALES):
        # El backup se hace con pg_dump dentro del docker local: no cubriría otra base.
        sys.exit("--aplicar solo contra el docker local (localhost). A Railway se sube con scripts/sync_to_railway.sh.")
    try:
        cat = parsear(json.loads(args.json.expanduser().read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError) as e:
        sys.exit(f"No pude leer el catálogo {args.json}: {e}")

    backup = _backup(args.schema) if args.aplicar else None
    print("> " + ("APLICANDO cambios" if args.aplicar else "MODO PRUEBA (todo se deshace al final)") + "\n")
    with psycopg.connect(url) as conn:
        try:
            reporte = actualizar(conn, cat, schema=args.schema, borrar_bajas=args.borrar_bajas)
        except ValueError as e:  # sedes sin mapear, catálogo sospechosamente chico: no se aplicó nada
            conn.rollback()
            sys.exit(f"No se aplicó nada: {e}")
        huerfanos = huerfanos_app(conn, args.schema, args.schema_app) if _tiene_app(conn, args.schema_app) else None
        _imprimir(reporte, huerfanos)
        if args.aplicar:
            conn.commit()
            print(f"\nListo. Backup previo: {backup}\nVolver atrás: docker exec -i {LOCAL_CONTAINER} pg_restore "
                  f"-U reinvent -d reinvent --clean --if-exists --no-owner < {backup}")
        else:
            conn.rollback()
            print("\nNo se cambió nada. Si el reporte está bien, corré lo mismo con --aplicar.")


if __name__ == "__main__":
    main()

"""Estado de la app en Postgres (schema DB_SCHEMA): grabaciones, usuarios, tokens e itinerarios.

Las tablas de datos del usuario (DATOS_USUARIO) existen también en el schema de prueba (app/sandbox.py); las de cuentas
(CUENTAS) y las globales (GLOBALES: ofertas, cotizaciones) solo en el real, así que un usuario en modo prueba se loguea igual pero escribe en el schema de prueba.
"""
import hashlib
import json
import logging
import time
import uuid
from contextlib import contextmanager

import psycopg
from psycopg.types.json import Jsonb

from . import config, legacy_import, passwords, pg, sandbox, sectors

log = logging.getLogger("reinventar.db")

DATOS_USUARIO = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  kind TEXT NOT NULL,
  code TEXT, venue TEXT, speaker TEXT,
  status TEXT NOT NULL,
  error TEXT,
  progress TEXT,
  duration_s DOUBLE PRECISION,
  expected_parts TEXT,
  summary TEXT,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  session_id TEXT NOT NULL,
  part INTEGER NOT NULL,
  seq INTEGER NOT NULL,
  bytes INTEGER NOT NULL,
  received_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (session_id, part, seq)
);
CREATE TABLE IF NOT EXISTS blocks (
  session_id TEXT NOT NULL,
  idx INTEGER NOT NULL,
  start_s DOUBLE PRECISION NOT NULL,
  end_s DOUBLE PRECISION NOT NULL,
  en TEXT NOT NULL,
  es TEXT,
  PRIMARY KEY (session_id, idx)
);
CREATE TABLE IF NOT EXISTS itinerary_profile (
  username TEXT PRIMARY KEY,
  role TEXT, experience TEXT, interests TEXT, prompt TEXT,
  notes TEXT, skipped TEXT,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS itinerary_items (
  username TEXT NOT NULL,
  code TEXT NOT NULL,
  base TEXT NOT NULL,
  day TEXT NOT NULL,
  start TEXT NOT NULL,
  locked INTEGER NOT NULL DEFAULT 0,
  reason TEXT,
  added_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (username, code)
);
-- "☆ Me interesa, para otro día": charlas que quedaron afuera por choque y vuelven cuando se repiten.
CREATE TABLE IF NOT EXISTS itinerary_pending (
  username TEXT NOT NULL,
  base TEXT NOT NULL,
  dia_marcada TEXT NOT NULL,
  added_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (username, base)
);
-- Mis eventos (app/my_events.py): los de proveedores que carga cada uno. Entran al itinerario como kind = 'mine'.
CREATE TABLE IF NOT EXISTS user_events (
  username TEXT NOT NULL,
  id TEXT NOT NULL,
  nombre TEXT NOT NULL,
  dia TEXT NOT NULL,
  inicio TEXT NOT NULL,
  fin TEXT,
  id_sede SMALLINT,
  place_id TEXT,
  lugar TEXT NOT NULL,
  direccion TEXT,
  lat DOUBLE PRECISION,
  lng DOUBLE PRECISION,
  nota TEXT NOT NULL DEFAULT '',
  created_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (username, id)
);
-- Avisos de Web Push ya mandados (app/push.py): cada uno sale una sola vez.
CREATE TABLE IF NOT EXISTS push_sent (
  username TEXT NOT NULL,
  key TEXT NOT NULL,
  sent_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (username, key)
);
-- Recordatorio "¿la grabás?" (app/recordatorio.py): la última sede en la que estuvo cada persona, si lo permitió.
-- Una fila por persona que se sobreescribe (sin historial), nunca coordenadas; se ignora a los 45 min y se borra a las 2 h.
CREATE TABLE IF NOT EXISTS ubicacion_reciente (
  username TEXT PRIMARY KEY,
  id_sede INTEGER,                     -- NULL = no está en ninguna sede
  visto_en DOUBLE PRECISION NOT NULL
);
-- «Está llena / hay mucha cola» (app/lleno.py): avisos de la gente en la puerta de la charla. Una fila por persona y
-- horario que se sobreescribe; valen 1 h y se borran a las 6 h.
CREATE TABLE IF NOT EXISTS reporte_lleno (
  code TEXT NOT NULL,
  username TEXT NOT NULL,
  estado TEXT NOT NULL CHECK (estado IN ('lleno', 'cola')),
  creado DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (code, username)
);
-- 👍/👎 de cada persona sobre el resumen de una grabación (app/voto_resumen_api.py): uno por persona, se pisa si cambia.
CREATE TABLE IF NOT EXISTS voto_resumen (
  session_id TEXT NOT NULL,
  username TEXT NOT NULL,
  util BOOLEAN NOT NULL,
  creado DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (session_id, username)
);
CREATE TABLE IF NOT EXISTS preferencias_avisos (
  username TEXT PRIMARY KEY,
  grabar BOOLEAN NOT NULL DEFAULT TRUE,
  ubicacion BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at DOUBLE PRECISION NOT NULL
);
-- Vuelos y hoteles cargados a mano (app/vuelos.py, app/viajes_avisos.py). Fechas y horas locales como texto ISO; la zona
-- (IANA) dice de qué lugar son. En el vuelo, demora_min/puerta/estado son lo último que se avisó (base del próximo cambio).
CREATE TABLE IF NOT EXISTS viajes_vuelos (
  username TEXT NOT NULL,
  id TEXT NOT NULL,
  numero TEXT NOT NULL,
  aerolinea TEXT NOT NULL DEFAULT '',
  fecha TEXT NOT NULL,
  hora TEXT,
  zona TEXT NOT NULL,
  salida_utc DOUBLE PRECISION,
  demora_min INTEGER,
  puerta TEXT,
  terminal TEXT,
  estado TEXT,
  consultado_en DOUBLE PRECISION,
  creado DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (username, id)
);
CREATE TABLE IF NOT EXISTS viajes_hoteles (
  username TEXT NOT NULL,
  id TEXT NOT NULL,
  nombre TEXT NOT NULL,
  direccion TEXT NOT NULL DEFAULT '',
  checkin TEXT NOT NULL,
  checkout TEXT NOT NULL,
  zona TEXT NOT NULL,
  creado DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (username, id)
);
-- Control de gastos del viaje (app/gastos.py). client_id lo genera el teléfono: reenviar un gasto no lo duplica.
-- updated_at es el reloj del teléfono (decide quién gana en un conflicto); sincronizado_at es el del servidor (es el
-- cursor de /sync: un teléfono con el reloj atrasado no puede hacer que otro se pierda el cambio). Las tres cotizaciones
-- (ARS por USD) se congelan al crear el gasto; foto_clave la maneja solo el servidor.
CREATE TABLE IF NOT EXISTS gastos (
  id BIGSERIAL PRIMARY KEY,
  username TEXT NOT NULL,
  client_id UUID NOT NULL,
  fecha DATE NOT NULL,
  monto NUMERIC(12,2) NOT NULL CHECK (monto > 0),
  moneda TEXT NOT NULL CHECK (moneda IN ('USD', 'ARS')),
  categoria TEXT NOT NULL CHECK (categoria IN ('comida', 'transporte', 'shows', 'compras', 'otros')),
  nota TEXT NOT NULL DEFAULT '',
  reintegrable BOOLEAN NOT NULL DEFAULT FALSE,
  compartido BOOLEAN NOT NULL DEFAULT FALSE,
  cotizacion_oficial NUMERIC(14,4) NOT NULL,
  cotizacion_blue NUMERIC(14,4) NOT NULL,
  cotizacion_tarjeta NUMERIC(14,4) NOT NULL,
  monto_usd NUMERIC(12,2) NOT NULL,
  foto_clave TEXT,
  updated_at TIMESTAMPTZ NOT NULL,
  sincronizado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  UNIQUE (username, client_id)
);
CREATE INDEX IF NOT EXISTS gastos_usuario_fecha ON gastos (username, fecha);
CREATE INDEX IF NOT EXISTS gastos_usuario_sync ON gastos (username, sincronizado_at);
CREATE TABLE IF NOT EXISTS gastos_presupuesto (
  username TEXT PRIMARY KEY,
  total_usd NUMERIC(12,2),
  diario_usd NUMERIC(12,2),
  por_categoria JSONB NOT NULL DEFAULT '{}'::jsonb
);
-- Los códigos de sesión que la persona quiere, de su Excel o CSV (app/codigos_api.py). Subir otra lista reemplaza la anterior.
CREATE TABLE IF NOT EXISTS codigos_deseados (
  username TEXT NOT NULL,
  codigo TEXT NOT NULL,                -- como lo escribió (AIM301-R1)
  base TEXT NOT NULL,                  -- AIM301
  orden INTEGER NOT NULL,
  archivo TEXT,
  subido_en DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (username, codigo)
);
"""
INDICES_DATOS_USUARIO = """
-- Va después de agregar las columnas: usa client_id.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_client_id_unico ON sessions (created_by, client_id) WHERE client_id IS NOT NULL;
"""
# Columnas agregadas después de crear la tabla (solo se hace el ALTER si faltan: ver _agregar_columnas).
# created_by: quién grabó (para «Tu re:Invent en números»; las de antes quedan en NULL). huecos: tramos sin audio, JSON
# [{"desde": s, "hasta": s}] (app/huecos.py). client_id: id que genera el cliente al grabar sin señal, para que reintentar
# el alta no duplique la sesión. kind: talk o event. snapshot: cómo era el ítem al agregarlo (app/changes.py).
# respuestas/ficha/ficha_texto: itinerario guiado (app/interview.py). salir_antes/reservada: armado guiado (app/guided.py).
# ofertas*: alertas de ofertas (app/ofertas_avisos.py), apagadas hasta que la persona las prende.
# cotizacion_estimada: la congelada era la de respaldo o tenía más de 48 h. foto_at: va como ?v= para no ver la foto vieja.
COLUMNAS_DATOS_USUARIO = (
    ("sessions", "created_by", "TEXT"),
    ("sessions", "huecos", "TEXT"),
    ("sessions", "client_id", "TEXT"),
    ("itinerary_items", "kind", "TEXT NOT NULL DEFAULT 'talk'"),
    ("itinerary_items", "snapshot", "JSONB"),
    ("itinerary_profile", "respuestas", "JSONB"),
    ("itinerary_profile", "ficha", "JSONB"),
    ("itinerary_profile", "ficha_texto", "TEXT"),
    ("itinerary_items", "salir_antes", "INTEGER NOT NULL DEFAULT 0"),
    ("itinerary_items", "reservada", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("preferencias_avisos", "eventos_nuevos", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("preferencias_avisos", "ofertas", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("preferencias_avisos", "ofertas_categorias", "TEXT[] NOT NULL DEFAULT ARRAY['shows','comida','compras','otros']"),
    ("preferencias_avisos", "viajes_checkin", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("preferencias_avisos", "viajes_hoteles", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("preferencias_avisos", "viajes_estado", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("gastos", "cotizacion_estimada", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("gastos", "foto_at", "TIMESTAMPTZ"),
)

TABLAS_DATOS_USUARIO = ("sessions", "chunks", "blocks", "itinerary_profile", "itinerary_items", "itinerary_pending",
                        "user_events", "push_sent", "ubicacion_reciente", "preferencias_avisos",
                        "reporte_lleno", "voto_resumen", "viajes_vuelos", "viajes_hoteles", "gastos", "gastos_presupuesto", "codigos_deseados")

# Fragmentos de las grabaciones para buscar en lo grabado (app/fragmentos.py). Necesita la extensión pgvector: si la
# base no la tiene, la tabla no se crea y esa búsqueda queda apagada (el resto de la app anda igual).
FRAGMENTOS = """
CREATE TABLE IF NOT EXISTS fragmentos (
  session_id TEXT NOT NULL,
  idx INTEGER NOT NULL,
  start_s DOUBLE PRECISION NOT NULL,
  end_s DOUBLE PRECISION NOT NULL,
  es TEXT,
  en TEXT NOT NULL,
  modelo TEXT,                         -- modelo de embeddings del vector (NULL si los embeddings están apagados)
  vector vector,                       -- sin dimensión fija: depende del modelo
  tsv tsvector NOT NULL,               -- para la parte por palabras (texto ya sin tildes, configuración simple)
  PRIMARY KEY (session_id, idx)
);
"""
vector_disponible = False
INIT_LOCK_TIMEOUT = "5s"
INIT_ADVISORY_LOCK = 7_265_001  # clave arbitraria del lock de arranque (solo tiene que ser siempre la misma)

CUENTAS = """
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY,
  salt TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_tokens (
  token TEXT PRIMARY KEY,              -- sha256 del token (el token en claro solo lo tiene el celular)
  username TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS passkeys (
  id TEXT PRIMARY KEY,                 -- credential id en base64url
  username TEXT NOT NULL,
  public_key BYTEA NOT NULL,
  sign_count BIGINT NOT NULL DEFAULT 0,
  device TEXT,
  created_at DOUBLE PRECISION NOT NULL,
  last_used_at DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS push_subscriptions (    -- Web Push: un registro por dispositivo (app/push.py)
  endpoint TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  p256dh TEXT NOT NULL,
  auth TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS webauthn_challenges (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,                  -- register | login
  username TEXT,                       -- solo en register
  challenge BYTEA NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
"""
# Los usuarios que ya existían quedan obligados a cambiar la contraseña. prueba: modo prueba (app/sandbox.py).
COLUMNAS_CUENTAS = (
    ("users", "must_change_password", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("users", "is_active", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("users", "modo_prueba", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("users", "prueba", "JSONB"),
    ("auth_tokens", "usado_at", "DOUBLE PRECISION"),
    ("auth_tokens", "hasheado", "BOOLEAN NOT NULL DEFAULT FALSE"),
)

GLOBALES = """
-- Ofertas (app/ofertas.py): las cargadas a mano por un admin y las bajas de precio de shows. Son de todos: solo existen
-- en el schema real (y se leen siempre de ahí, también en modo prueba).
CREATE TABLE IF NOT EXISTS oferta (
  id TEXT PRIMARY KEY,
  fuente TEXT NOT NULL,
  categoria TEXT NOT NULL CHECK (categoria IN ('shows', 'comida', 'compras', 'otros')),
  titulo TEXT NOT NULL,
  lugar TEXT NOT NULL DEFAULT '',
  desde TIMESTAMPTZ NOT NULL,
  hasta TIMESTAMPTZ,
  link TEXT,
  nota TEXT NOT NULL DEFAULT '',
  id_show TEXT,
  precio_antes NUMERIC(10,2),
  precio_ahora NUMERIC(10,2),
  creado DOUBLE PRECISION NOT NULL
);
-- Precio mínimo (USD) de cada función de Ticketmaster cada 6 h, para detectar bajas (se purga a los 14 días).
CREATE TABLE IF NOT EXISTS precio_snapshot (
  id_funcion TEXT NOT NULL,
  tomado DOUBLE PRECISION NOT NULL,
  precio NUMERIC(10,2) NOT NULL,
  PRIMARY KEY (id_funcion, tomado)
);
-- Cuándo corrió por última vez cada fuente de ofertas (para no pedirla más seguido que cada 6 h).
CREATE TABLE IF NOT EXISTS oferta_job (
  fuente TEXT PRIMARY KEY,
  ultimo DOUBLE PRECISION NOT NULL
);
-- Historial de cotizaciones (app/cotizacion.py): solo se agrega una fila cuando alguna se movió más de 0,1 %.
-- Es global (no de una persona): solo existe en el schema real.
CREATE TABLE IF NOT EXISTS cotizaciones (
  id BIGSERIAL PRIMARY KEY,
  at TIMESTAMPTZ NOT NULL DEFAULT now(),
  oficial NUMERIC(14,4) NOT NULL,
  blue NUMERIC(14,4) NOT NULL,
  tarjeta NUMERIC(14,4) NOT NULL
);
CREATE INDEX IF NOT EXISTS cotizaciones_at ON cotizaciones (at DESC);
"""


KINDS = ("Keynote", "Chalk talk", "Workshop", "Breakout")
PROCESSING = ("queued", "transcribing", "translating", "summarizing")


@contextmanager
def conn():
    """Conexión del pool; commit al salir sin error, rollback si hubo excepción."""
    with pg.pool().connection() as c:
        yield c


def init():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with sandbox.real():
        with conn() as c:
            _preparar_init(c)
            c.execute(f"CREATE SCHEMA IF NOT EXISTS {config.DB_SCHEMA}")
            _crear_datos_usuario(c)
            c.execute(GLOBALES)
            c.execute(CUENTAS)
            _agregar_columnas(c, COLUMNAS_CUENTAS)
            _crear_fragmentos(c)
            _hashear_tokens_viejos(c)
            sectors.ensure(c)
            _crear_schema_prueba(c)
        with conn() as c:
            legacy_import.run_once(c, config.LEGACY_SQLITE_PATH)
        bootstrap_users()


def _preparar_init(c) -> None:
    """Dos arranques a la vez (un deploy con réplicas) no se pisan: el segundo espera al primero. Y si algún DDL no
    consigue su lock en INIT_LOCK_TIMEOUT, el arranque falla en vez de dejar colgados los pedidos que esperan detrás."""
    c.execute(f"SET LOCAL lock_timeout = '{INIT_LOCK_TIMEOUT}'")
    c.execute("SELECT pg_advisory_xact_lock(%s)", (INIT_ADVISORY_LOCK,))


def _agregar_columnas(c, columnas) -> None:
    """ALTER TABLE ... ADD COLUMN solo de las que faltan en el schema actual (search_path): aunque la columna exista,
    el ADD COLUMN IF NOT EXISTS pide ACCESS EXCLUSIVE sobre la tabla en cada arranque."""
    existentes = {(r["table_name"], r["column_name"]) for r in c.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = current_schema()").fetchall()}
    for tabla, columna, definicion in columnas:
        if (tabla, columna) not in existentes:
            c.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {columna} {definicion}")


def _crear_datos_usuario(c) -> None:
    c.execute(DATOS_USUARIO)
    _agregar_columnas(c, COLUMNAS_DATOS_USUARIO)
    c.execute(INDICES_DATOS_USUARIO)


def _hashear_tokens_viejos(c) -> None:
    """Los tokens se guardaban en claro: se reemplazan por su sha256 (una sola vez; las sesiones siguen valiendo)."""
    c.execute("UPDATE auth_tokens SET token = encode(sha256(convert_to(token, 'UTF8')), 'hex'), hasheado = TRUE "
              "WHERE NOT hasheado")


def _crear_schema_prueba(c) -> None:
    """Solo las tablas de datos del usuario: lo demás (cuentas, tablas globales, cachés compartidos) se lee del schema real."""
    c.execute(f"CREATE SCHEMA IF NOT EXISTS {sandbox.schema_prueba()}")
    c.execute(f"SET LOCAL search_path TO {sandbox.schema_prueba()}, public")  # public: el tipo vector de pgvector
    _crear_datos_usuario(c)
    if vector_disponible:
        c.execute(FRAGMENTOS)


def _crear_fragmentos(c) -> None:
    """Habilita pgvector (en public, así lo ven el schema real y el de prueba) y crea la tabla de fragmentos.
    Si falta la extensión o el permiso para crearla, deja la búsqueda en lo grabado apagada sin tumbar el arranque."""
    global vector_disponible
    try:
        with c.transaction():  # savepoint: si falla, la transacción del init sigue viva
            c.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
            c.execute(FRAGMENTOS)
        vector_disponible = True
    except psycopg.Error as e:
        vector_disponible = False
        log.warning("Sin pgvector (%s): la búsqueda en lo grabado queda apagada", e)


def tablas_datos_usuario() -> tuple[str, ...]:
    return TABLAS_DATOS_USUARIO + (("fragmentos",) if vector_disponible else ())


def borrar_datos_prueba() -> int:
    """Vacía las tablas del schema de prueba (de todos los usuarios en modo prueba). Devuelve las filas borradas."""
    total = 0
    with sandbox.real(), conn() as c:
        for tabla in tablas_datos_usuario():
            total += c.execute(f"DELETE FROM {sandbox.schema_prueba()}.{tabla}").rowcount
    return total


def _row(r):
    if r is None:
        return None
    d = dict(r)
    d["summary"] = json.loads(d["summary"]) if d.get("summary") else None
    d["expected_parts"] = json.loads(d["expected_parts"]) if d.get("expected_parts") else None
    d["huecos"] = json.loads(d["huecos"]) if d.get("huecos") else []
    return d


def create_session(title, kind, code=None, venue=None, speaker=None, created_by=None, client_id=None, recorded_at=None):
    """Crea la sesión. Con client_id es idempotente por usuario: si ya existe una con ese client_id, devuelve esa
    (y no toca nada). recorded_at (epoch) es la hora real de la grabación: es el created_at, con el que se ordena la lista."""
    sid = uuid.uuid4().hex[:12]
    now = time.time()
    with conn() as c:
        creada = c.execute(
            "INSERT INTO sessions (id,title,kind,code,venue,speaker,status,created_by,client_id,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (created_by, client_id) WHERE client_id IS NOT NULL DO NOTHING RETURNING id",
            (sid, title, kind, code, venue, speaker, "recording", created_by, client_id,
             recorded_at if recorded_at is not None else now, now),
        ).fetchone()
        if creada is None:  # el client_id ya estaba: es un reintento
            sid = c.execute("SELECT id FROM sessions WHERE created_by=%s AND client_id=%s", (created_by, client_id)).fetchone()["id"]
    return get_session(sid)


def get_session(sid):
    with conn() as c:
        r = c.execute("SELECT * FROM sessions WHERE id=%s", (sid,)).fetchone()
        s = _row(r)
        if s:
            agg = c.execute("SELECT COUNT(*) n, COALESCE(SUM(bytes),0) b FROM chunks WHERE session_id=%s", (sid,)).fetchone()
            s["chunks_received"] = agg["n"]
            s["bytes_received"] = int(agg["b"])
        return s


def list_sessions():
    with conn() as c:
        rows = c.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
    return [_row(r) for r in rows]


def update_session(sid, **fields):
    if not fields:
        return
    fields["updated_at"] = time.time()
    for k in ("summary", "expected_parts", "huecos"):
        if k in fields and fields[k] is not None and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
    cols = ", ".join(f"{k}=%s" for k in fields)  # las claves vienen del código, nunca del request
    with conn() as c:
        c.execute(f"UPDATE sessions SET {cols} WHERE id=%s", (*fields.values(), sid))


def delete_session(sid):
    with conn() as c:
        if vector_disponible:
            c.execute("DELETE FROM fragmentos WHERE session_id=%s", (sid,))
        c.execute("DELETE FROM blocks WHERE session_id=%s", (sid,))
        c.execute("DELETE FROM chunks WHERE session_id=%s", (sid,))
        c.execute("DELETE FROM voto_resumen WHERE session_id=%s", (sid,))
        c.execute("DELETE FROM sessions WHERE id=%s", (sid,))


def record_chunk(sid, part, seq, nbytes):
    with conn() as c:
        c.execute(
            "INSERT INTO chunks (session_id,part,seq,bytes,received_at) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (session_id,part,seq) DO UPDATE SET bytes=EXCLUDED.bytes, received_at=EXCLUDED.received_at",
            (sid, part, seq, nbytes, time.time()),
        )


def chunk_index(sid):
    """{part: set(seq)} de lo recibido."""
    with conn() as c:
        rows = c.execute("SELECT part, seq FROM chunks WHERE session_id=%s", (sid,)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["part"], set()).add(r["seq"])
    return out


def replace_blocks(sid, blocks):
    with conn() as c:
        c.execute("DELETE FROM blocks WHERE session_id=%s", (sid,))
        if vector_disponible:  # los fragmentos se arman de los bloques: si cambian, se vuelven a indexar
            c.execute("DELETE FROM fragmentos WHERE session_id=%s", (sid,))
        c.cursor().executemany(
            "INSERT INTO blocks (session_id,idx,start_s,end_s,en,es) VALUES (%s,%s,%s,%s,%s,%s)",
            [(sid, i, b["start"], b["end"], b["en"], b.get("es")) for i, b in enumerate(blocks)],
        )


def set_translations(sid, pairs):
    with conn() as c:
        c.cursor().executemany(
            "UPDATE blocks SET es=%s WHERE session_id=%s AND idx=%s", [(es, sid, i) for i, es in pairs]
        )


def get_blocks(sid):
    with conn() as c:
        rows = c.execute("SELECT idx,start_s,end_s,en,es FROM blocks WHERE session_id=%s ORDER BY idx", (sid,)).fetchall()
    return [dict(r) for r in rows]


def recordings_for(codes):
    """Grabaciones cuyo código es alguno de estos (los horarios de una charla), de la más nueva a la más vieja."""
    with conn() as c:
        rows = c.execute(
            "SELECT id, title, status, created_at FROM sessions WHERE code = ANY(%s) ORDER BY created_at DESC",
            (list(codes),),
        ).fetchall()
    return [dict(r) for r in rows]


def ready_summaries_for(codes):
    """Grabaciones procesadas de estos códigos, con su resumen (para el briefing)."""
    with conn() as c:
        rows = c.execute(
            "SELECT code, title, summary FROM sessions WHERE code = ANY(%s) AND status = 'ready' AND summary IS NOT NULL "
            "ORDER BY created_at DESC",
            (list(codes),),
        ).fetchall()
    return [{**dict(r), "summary": json.loads(r["summary"])} for r in rows]


def grabado_por(username) -> dict:
    """Cuántas grabaciones hizo la persona y cuántos segundos suman (las que todavía no se procesaron, sin duración)."""
    with conn() as c:
        r = c.execute("SELECT COUNT(*) AS n, COALESCE(SUM(duration_s), 0) AS s FROM sessions WHERE created_by=%s",
                      (username,)).fetchone()
    return {"grabaciones": r["n"], "segundos": round(float(r["s"]))}


def sessions_in(statuses):
    with conn() as c:
        rows = c.execute(
            "SELECT id FROM sessions WHERE status = ANY(%s) ORDER BY updated_at", (list(statuses),)
        ).fetchall()
    return [r["id"] for r in rows]


# --- usuarios / login ------------------------------------------------------------------------

def get_user(username):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE username=%s", (username,)).fetchone()
    return dict(r) if r else None


def create_user(username, salt, password_hash, must_change_password=True):
    with conn() as c:
        c.execute(
            "INSERT INTO users (username,salt,password_hash,created_at,must_change_password) VALUES (%s,%s,%s,%s,%s)",
            (username, salt, password_hash, time.time(), must_change_password),
        )


def set_password(username, salt, password_hash, must_change_password):
    with conn() as c:
        c.execute(
            "UPDATE users SET salt=%s, password_hash=%s, must_change_password=%s WHERE username=%s",
            (salt, password_hash, must_change_password, username),
        )


def set_user_active(username, active):
    with conn() as c:
        c.execute("UPDATE users SET is_active=%s WHERE username=%s", (active, username))


# --- Web Push -------------------------------------------------------------------------------
# Las suscripciones son del dispositivo: siempre en el schema real (no existen en el de prueba).

def save_push_subscription(username, endpoint, p256dh, auth):
    with conn() as c:
        c.execute("INSERT INTO push_subscriptions (endpoint,username,p256dh,auth,created_at) VALUES (%s,%s,%s,%s,%s) "
                  "ON CONFLICT (endpoint) DO UPDATE SET username=EXCLUDED.username, p256dh=EXCLUDED.p256dh, auth=EXCLUDED.auth",
                  (endpoint, username, p256dh, auth, time.time()))


def delete_push_subscription(endpoint, username=None):
    with conn() as c:
        if username:
            c.execute("DELETE FROM push_subscriptions WHERE endpoint=%s AND username=%s", (endpoint, username))
        else:
            c.execute("DELETE FROM push_subscriptions WHERE endpoint=%s", (endpoint,))


def push_subscriptions(username):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM push_subscriptions WHERE username=%s", (username,)).fetchall()]


def push_usernames():
    """Usuarios activos con algún dispositivo suscripto (a los desactivados no se les manda nada)."""
    with conn() as c:
        return [r["username"] for r in c.execute(
            "SELECT DISTINCT p.username FROM push_subscriptions p JOIN users u ON u.username = p.username "
            "WHERE u.is_active").fetchall()]


def delete_push_subscriptions(username):
    """Baja de todos los dispositivos del usuario (al desactivarlo o resetear su contraseña)."""
    with conn() as c:
        c.execute("DELETE FROM push_subscriptions WHERE username=%s", (username,))


def mark_push_sent(username, key) -> bool:
    """True si es la primera vez (hay que mandarlo); False si ya se había mandado."""
    with conn() as c:
        return c.execute("INSERT INTO push_sent (username,key,sent_at) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                         (username, key, time.time())).rowcount == 1


def unmark_push_sent(username, key):
    with conn() as c:
        c.execute("DELETE FROM push_sent WHERE username=%s AND key=%s", (username, key))


def ultimo_push(username, prefijo) -> float | None:
    """time.time() del último aviso con claves que empiezan con `prefijo` (para el enfriamiento), o None."""
    with conn() as c:
        r = c.execute("SELECT MAX(sent_at) AS t FROM push_sent WHERE username=%s AND key LIKE %s",
                      (username, prefijo.replace("%", r"\%").replace("_", r"\_") + "%")).fetchone()
    return r["t"] if r else None


# ---------- recordatorio "¿la grabás?" ----------

def grabacion_activa(code, creada_desde, chunk_desde) -> bool:
    """Si hay una grabación de esa charla creada desde `creada_desde`, o en curso con audio desde `chunk_desde`."""
    with conn() as c:
        return c.execute(
            "SELECT 1 FROM sessions s WHERE upper(s.code) = upper(%s) AND (s.created_at >= %s OR (s.status = 'recording' "
            "AND EXISTS (SELECT 1 FROM chunks k WHERE k.session_id = s.id AND k.received_at >= %s))) LIMIT 1",
            (code, creada_desde, chunk_desde)).fetchone() is not None


def set_ubicacion(username, id_sede) -> None:
    with conn() as c:
        c.execute("INSERT INTO ubicacion_reciente (username,id_sede,visto_en) VALUES (%s,%s,%s) "
                  "ON CONFLICT (username) DO UPDATE SET id_sede=EXCLUDED.id_sede, visto_en=EXCLUDED.visto_en",
                  (username, id_sede, time.time()))


def get_ubicacion(username, desde) -> dict | None:
    """{id_sede, visto_en} si se reportó desde `desde` (time.time()); None si no hay o venció."""
    with conn() as c:
        r = c.execute("SELECT id_sede, visto_en FROM ubicacion_reciente WHERE username=%s AND visto_en >= %s",
                      (username, desde)).fetchone()
    return dict(r) if r else None


def delete_ubicacion(username) -> None:
    with conn() as c:
        c.execute("DELETE FROM ubicacion_reciente WHERE username=%s", (username,))


def purgar_ubicaciones(antes_de) -> int:
    """Borra las sedes reportadas antes de `antes_de`, en el schema real y en el de prueba. Devuelve cuántas."""
    total = 0
    with sandbox.real(), conn() as c:
        for schema in (config.DB_SCHEMA, sandbox.schema_prueba()):
            total += c.execute(f"DELETE FROM {schema}.ubicacion_reciente WHERE visto_en < %s", (antes_de,)).rowcount
    return total


def set_reporte_lleno(code, username, estado) -> None:
    with conn() as c:
        c.execute("INSERT INTO reporte_lleno (code,username,estado,creado) VALUES (%s,%s,%s,%s) "
                  "ON CONFLICT (code, username) DO UPDATE SET estado=EXCLUDED.estado, creado=EXCLUDED.creado",
                  (code, username, estado, time.time()))


def delete_reporte_lleno(code, username) -> None:
    with conn() as c:
        c.execute("DELETE FROM reporte_lleno WHERE code=%s AND username=%s", (code, username))


def reportes_lleno(codes, desde) -> list[dict]:
    """[{code, username, estado, creado}] de esos horarios reportados desde `desde` (time.time())."""
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT code, username, estado, creado FROM reporte_lleno WHERE code = ANY(%s) AND creado >= %s",
            (list(codes), desde)).fetchall()]


def purgar_reportes_lleno(antes_de) -> int:
    """Borra los avisos de lleno anteriores a `antes_de`, en el schema real y en el de prueba. Devuelve cuántos."""
    total = 0
    with sandbox.real(), conn() as c:
        for schema in (config.DB_SCHEMA, sandbox.schema_prueba()):
            total += c.execute(f"DELETE FROM {schema}.reporte_lleno WHERE creado < %s", (antes_de,)).rowcount
    return total


def renombrar_codigos(renombres) -> int:
    """AWS renombró horarios [(viejo, nuevo, base nueva)] (app/charlas_auto.py): los itinerarios y las grabaciones
    pasan al código nuevo, en el schema real y en el de prueba. Si alguien ya tenía el nuevo, el viejo sobra.
    Lo mismo que scripts/migrar_codigos_app.sql, para lo que detecta la revisión automática. Devuelve los ítems movidos."""
    movidos = 0
    with sandbox.real(), conn() as c:
        for schema in (config.DB_SCHEMA, sandbox.schema_prueba()):
            for viejo, nuevo, base in renombres:
                c.execute(f"DELETE FROM {schema}.itinerary_items i WHERE i.code = %s AND EXISTS "
                          f"(SELECT 1 FROM {schema}.itinerary_items x WHERE x.username = i.username AND x.code = %s)",
                          (viejo, nuevo))
                movidos += c.execute(f"UPDATE {schema}.itinerary_items SET code = %s, base = %s WHERE code = %s",
                                     (nuevo, base, viejo)).rowcount
                c.execute(f"UPDATE {schema}.sessions SET code = %s WHERE upper(code) = %s", (nuevo, viejo))
    return movidos


def set_voto_resumen(sid, username, util: bool) -> None:
    with conn() as c:
        c.execute("INSERT INTO voto_resumen (session_id,username,util,creado) VALUES (%s,%s,%s,%s) "
                  "ON CONFLICT (session_id, username) DO UPDATE SET util=EXCLUDED.util, creado=EXCLUDED.creado",
                  (sid, username, util, time.time()))


def delete_voto_resumen(sid, username) -> None:
    with conn() as c:
        c.execute("DELETE FROM voto_resumen WHERE session_id=%s AND username=%s", (sid, username))


def votos_resumen(sid, username) -> dict:
    """{si, no, mio}: cuántos dijeron que el resumen les sirvió, cuántos que no, y qué votó esta persona (o None)."""
    with conn() as c:
        filas = c.execute("SELECT username, util FROM voto_resumen WHERE session_id=%s", (sid,)).fetchall()
    return {"si": sum(f["util"] for f in filas), "no": sum(not f["util"] for f in filas),
            "mio": next((f["util"] for f in filas if f["username"] == username), None)}


def get_preferencias_avisos(username) -> dict:
    with conn() as c:
        r = c.execute("SELECT grabar, ubicacion, eventos_nuevos FROM preferencias_avisos WHERE username=%s",
                      (username,)).fetchone()
    return dict(r) if r else {"grabar": True, "ubicacion": False, "eventos_nuevos": True}


def set_preferencias_avisos(username, grabar, ubicacion, eventos_nuevos=True) -> None:
    with conn() as c:
        c.execute("INSERT INTO preferencias_avisos (username,grabar,ubicacion,eventos_nuevos,updated_at) "
                  "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (username) DO UPDATE SET grabar=EXCLUDED.grabar, "
                  "ubicacion=EXCLUDED.ubicacion, eventos_nuevos=EXCLUDED.eventos_nuevos, updated_at=EXCLUDED.updated_at",
                  (username, grabar, ubicacion, eventos_nuevos, time.time()))
        if not ubicacion:
            c.execute("DELETE FROM ubicacion_reciente WHERE username=%s", (username,))


def set_user_sandbox(username, active, cfg):
    """Prende o apaga el modo prueba de un usuario y guarda su configuración (proveedores, reloj, ubicación)."""
    with sandbox.real(), conn() as c:
        c.execute("UPDATE users SET modo_prueba=%s, prueba=%s WHERE username=%s",
                  (active, Jsonb(cfg) if cfg is not None else None, username))


def list_users():
    """Usuarios con su última sesión iniciada y cuántas sesiones abiertas tienen (para el admin)."""
    with conn() as c:
        rows = c.execute(
            "SELECT u.username, u.created_at, u.must_change_password, u.is_active, u.modo_prueba, u.prueba, "
            "       MAX(t.created_at) AS last_login, COUNT(t.token) AS open_sessions, "
            "       (SELECT COUNT(*) FROM itinerary_items i WHERE i.username = u.username) AS itinerary_items "
            "FROM users u LEFT JOIN auth_tokens t ON t.username = u.username "
            "GROUP BY u.username ORDER BY u.username"
        ).fetchall()
    return [dict(r) for r in rows]


def bootstrap_users():
    """Crea los usuarios listados en BOOTSTRAP_USERS ('user:pass,user:pass') si todavía no existen."""
    for pair in config.BOOTSTRAP_USERS.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        username, password = pair.split(":", 1)
        username = username.strip()
        if not username or not password or get_user(username):
            continue
        salt, password_hash = passwords.hash_password(password)
        create_user(username, salt, password_hash)


# Sesiones: en la base se guarda el sha256 del token (quien lea un backup no puede entrar como nadie) y vencen
# tras SESION_INACTIVA_DIAS sin usarse (ventana deslizante: quien usa la app todos los días no se tiene que volver
# a loguear en plena conferencia).
SESION_INACTIVA_SEGUNDOS = 30 * 24 * 3600
_REFRESCO_USO_SEGUNDOS = 24 * 3600  # usado_at se actualiza como mucho una vez por día (no una escritura por pedido)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_auth_token(token, username):
    ahora = time.time()
    with conn() as c:
        c.execute("DELETE FROM auth_tokens WHERE COALESCE(usado_at, created_at) < %s", (ahora - SESION_INACTIVA_SEGUNDOS,))
        c.execute("INSERT INTO auth_tokens (token,username,created_at,usado_at,hasheado) VALUES (%s,%s,%s,%s,TRUE)",
                  (hash_token(token), username, ahora, ahora))


def resolve_session(token, ahora=None):
    """{username, must_change_password, created_at} del dueño del token: solo si el usuario sigue activo y la sesión
    no venció. None si no vale."""
    ahora = ahora or time.time()
    th = hash_token(token)
    with conn() as c:
        r = c.execute(
            "SELECT t.username, u.must_change_password, t.created_at, COALESCE(t.usado_at, t.created_at) AS usado "
            "FROM auth_tokens t JOIN users u ON u.username = t.username "
            "WHERE t.token=%s AND u.is_active AND COALESCE(t.usado_at, t.created_at) >= %s",
            (th, ahora - SESION_INACTIVA_SEGUNDOS),
        ).fetchone()
        if r and r["usado"] < ahora - _REFRESCO_USO_SEGUNDOS:
            c.execute("UPDATE auth_tokens SET usado_at=%s WHERE token=%s", (ahora, th))
    return dict(r) if r else None


def resolve_auth_token(token):
    """Username dueño del token, solo si el usuario sigue activo y la sesión no venció."""
    r = resolve_session(token)
    return r["username"] if r else None


def delete_auth_token(token):
    with conn() as c:
        c.execute("DELETE FROM auth_tokens WHERE token=%s", (hash_token(token),))


def revoke_tokens(username, except_token=None):
    with conn() as c:
        c.execute("DELETE FROM auth_tokens WHERE username=%s AND token IS DISTINCT FROM %s",
                  (username, hash_token(except_token) if except_token else None))


# --- uso (admin) -----------------------------------------------------------------------------

_RECENT_ERRORS = 10


def recordings_by_status():
    with conn() as c:
        rows = c.execute("SELECT status, COUNT(*) AS n FROM sessions GROUP BY status ORDER BY n DESC").fetchall()
    return {r["status"]: r["n"] for r in rows}


def recent_errors():
    with conn() as c:
        rows = c.execute(
            "SELECT id, title, error, updated_at FROM sessions WHERE status='error' ORDER BY updated_at DESC LIMIT %s",
            (_RECENT_ERRORS,),
        ).fetchall()
    return [dict(r) for r in rows]


# --- itinerario (por usuario) ----------------------------------------------------------------

def get_profile(username):
    with conn() as c:
        r = c.execute("SELECT * FROM itinerary_profile WHERE username=%s", (username,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["interests"] = json.loads(d["interests"]) if d.get("interests") else []
    d["skipped"] = json.loads(d["skipped"]) if d.get("skipped") else []
    return d


def save_profile(username, role, experience, interests, prompt):
    """Reemplaza el perfil entero: notes/skipped vuelven a NULL hasta que save_run_meta los complete."""
    with conn() as c:
        c.execute(
            "INSERT INTO itinerary_profile (username,role,experience,interests,prompt,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (username) DO UPDATE SET role=EXCLUDED.role, experience=EXCLUDED.experience, "
            "interests=EXCLUDED.interests, prompt=EXCLUDED.prompt, notes=NULL, skipped=NULL, "
            "updated_at=EXCLUDED.updated_at",
            (username, role, experience, json.dumps(interests, ensure_ascii=False), prompt, time.time()),
        )


def save_run_meta(username, notes, skipped):
    """Se corre después de save_profile (que resetea notes/skipped)."""
    with conn() as c:
        c.execute(
            "UPDATE itinerary_profile SET notes=%s, skipped=%s WHERE username=%s",
            (notes, json.dumps(skipped, ensure_ascii=False), username),
        )


def get_interview(username) -> dict:
    """{respuestas, ficha, ficha_texto} de la entrevista guiada (vacío si nunca empezó)."""
    with conn() as c:
        r = c.execute("SELECT respuestas, ficha, ficha_texto FROM itinerary_profile WHERE username=%s",
                      (username,)).fetchone()
    return dict(r) if r else {"respuestas": None, "ficha": None, "ficha_texto": None}


def save_answers(username, respuestas: dict):
    """Guarda las respuestas (ya combinadas y validadas). No toca el perfil del armado rápido ni la ficha."""
    with conn() as c:
        c.execute(
            "INSERT INTO itinerary_profile (username, respuestas, updated_at) VALUES (%s,%s,%s) "
            "ON CONFLICT (username) DO UPDATE SET respuestas=EXCLUDED.respuestas, updated_at=EXCLUDED.updated_at",
            (username, Jsonb(respuestas), time.time()),
        )


def save_ficha(username, ficha: dict, texto: str):
    with conn() as c:
        c.execute(
            "INSERT INTO itinerary_profile (username, ficha, ficha_texto, updated_at) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (username) DO UPDATE SET ficha=EXCLUDED.ficha, ficha_texto=EXCLUDED.ficha_texto, "
            "updated_at=EXCLUDED.updated_at",
            (username, Jsonb(ficha), texto, time.time()),
        )


def delete_interview(username):
    with conn() as c:
        c.execute("UPDATE itinerary_profile SET respuestas=NULL, ficha=NULL, ficha_texto=NULL WHERE username=%s",
                  (username,))


def list_itinerary_items(username):
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM itinerary_items WHERE username=%s ORDER BY day, start", (username,)
        ).fetchall()
    return [dict(r) for r in rows]


def replace_itinerary_items(username, items):
    """Reemplaza las sesiones no bloqueadas de este usuario; las bloqueadas (locked=1) se conservan tal cual."""
    with conn() as c:
        c.execute("DELETE FROM itinerary_items WHERE username=%s AND locked=0", (username,))
        c.cursor().executemany(
            "INSERT INTO itinerary_items (username,code,base,day,start,locked,reason,added_at,snapshot) "
            "VALUES (%s,%s,%s,%s,%s,0,%s,%s,%s) ON CONFLICT (username,code) DO NOTHING",
            [(username, i["code"], i["base"], i["day"], i["start"], i.get("reason"), time.time(),
              Jsonb(i["snapshot"]) if i.get("snapshot") else None) for i in items],
        )


def add_item(username, code, base, day, start, locked=False, reason=None, kind="talk", snapshot=None):
    with conn() as c:
        c.execute(
            "INSERT INTO itinerary_items (username,code,base,day,start,locked,reason,added_at,kind,snapshot) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (username,code) DO UPDATE SET base=EXCLUDED.base, day=EXCLUDED.day, start=EXCLUDED.start, "
            "locked=EXCLUDED.locked, reason=EXCLUDED.reason, added_at=EXCLUDED.added_at, kind=EXCLUDED.kind, "
            "snapshot=EXCLUDED.snapshot",
            (username, code, base, day, start, int(locked), reason, time.time(), kind,
             Jsonb(snapshot) if snapshot is not None else None),
        )


def set_item_snapshot(username, code, snapshot):
    with conn() as c:
        c.execute("UPDATE itinerary_items SET snapshot=%s WHERE username=%s AND code=%s", (Jsonb(snapshot), username, code))


def set_item_locked(username, code, locked):
    with conn() as c:
        c.execute(
            "UPDATE itinerary_items SET locked=%s WHERE username=%s AND code=%s", (int(locked), username, code)
        )


def set_item_leave_early(username, code, minutos: int) -> bool:
    with conn() as c:
        return c.execute("UPDATE itinerary_items SET salir_antes=%s WHERE username=%s AND code=%s",
                         (minutos, username, code)).rowcount > 0


def set_item_booked(username, code, reservada: bool) -> bool:
    with conn() as c:
        return c.execute("UPDATE itinerary_items SET reservada=%s WHERE username=%s AND code=%s",
                         (reservada, username, code)).rowcount > 0


def list_pending(username) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT base, dia_marcada, added_at FROM itinerary_pending WHERE username=%s ORDER BY added_at",
                         (username,)).fetchall()
    return [dict(r) for r in rows]


def add_pending(username, base, dia_marcada):
    with conn() as c:
        c.execute("INSERT INTO itinerary_pending (username, base, dia_marcada, added_at) VALUES (%s,%s,%s,%s) "
                  "ON CONFLICT (username, base) DO NOTHING", (username, base, dia_marcada, time.time()))


def remove_pending(username, base):
    with conn() as c:
        c.execute("DELETE FROM itinerary_pending WHERE username=%s AND base=%s", (username, base))


_USER_EVENT_COLS = ("nombre", "dia", "inicio", "fin", "id_sede", "place_id", "lugar", "direccion", "lat", "lng", "nota")


def save_user_event(username, id_, data: dict):
    """Alta o edición de un evento propio (data con las columnas de _USER_EVENT_COLS)."""
    valores = [data.get(k) for k in _USER_EVENT_COLS]
    with conn() as c:
        c.execute(
            f"INSERT INTO user_events (username, id, {', '.join(_USER_EVENT_COLS)}, created_at) "
            f"VALUES (%s, %s, {', '.join(['%s'] * len(_USER_EVENT_COLS))}, %s) "
            "ON CONFLICT (username, id) DO UPDATE SET "
            + ", ".join(f"{k}=EXCLUDED.{k}" for k in _USER_EVENT_COLS),
            (username, id_, *valores, time.time()),
        )


def get_user_event(username, id_) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM user_events WHERE username=%s AND id=%s", (username, id_)).fetchone()
    return dict(r) if r else None


def list_user_events(username) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM user_events WHERE username=%s ORDER BY dia, inicio", (username,)).fetchall()
    return [dict(r) for r in rows]


def delete_user_event(username, id_) -> bool:
    with conn() as c:
        return c.execute("DELETE FROM user_events WHERE username=%s AND id=%s", (username, id_)).rowcount > 0


def remove_item(username, code):
    with conn() as c:
        c.execute("DELETE FROM itinerary_items WHERE username=%s AND code=%s", (username, code))

"""Estado de la app en Postgres (schema DB_SCHEMA): grabaciones, usuarios, tokens e itinerarios.

Las tablas de datos del usuario (DATOS_USUARIO) existen también en el schema de prueba (app/sandbox.py); las de cuentas
(CUENTAS) solo en el real, así que un usuario en modo prueba se loguea igual pero escribe en el schema de prueba.
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
-- Quién grabó (username): para «Tu re:Invent en números». Las grabaciones de antes quedan en NULL (no son de nadie).
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS created_by TEXT;
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
-- talk (charla del catálogo) o event (evento de networking, reinvent.evento): todo se maneja desde el itinerario.
ALTER TABLE itinerary_items ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'talk';
-- Cómo era al agregarlo (título, día, hora, sala, lleno): si AWS lo cambia, la app avisa (app/changes.py).
ALTER TABLE itinerary_items ADD COLUMN IF NOT EXISTS snapshot JSONB;
-- Itinerario guiado (app/interview.py): respuestas de la entrevista y la ficha que arma el LLM.
ALTER TABLE itinerary_profile ADD COLUMN IF NOT EXISTS respuestas JSONB;
ALTER TABLE itinerary_profile ADD COLUMN IF NOT EXISTS ficha JSONB;
ALTER TABLE itinerary_profile ADD COLUMN IF NOT EXISTS ficha_texto TEXT;
-- Armado guiado (app/guided.py): salir N min antes de que termine (para llegar a la siguiente) y si la persona
-- tiene la charla reservada en el portal de AWS (si no, hay que hacer la cola de walk-up).
ALTER TABLE itinerary_items ADD COLUMN IF NOT EXISTS salir_antes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE itinerary_items ADD COLUMN IF NOT EXISTS reservada BOOLEAN NOT NULL DEFAULT FALSE;
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
CREATE TABLE IF NOT EXISTS preferencias_avisos (
  username TEXT PRIMARY KEY,
  grabar BOOLEAN NOT NULL DEFAULT TRUE,
  ubicacion BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at DOUBLE PRECISION NOT NULL
);
"""
TABLAS_DATOS_USUARIO = ("sessions", "chunks", "blocks", "itinerary_profile", "itinerary_items", "itinerary_pending",
                        "user_events", "push_sent", "ubicacion_reciente", "preferencias_avisos")

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

CUENTAS = """
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY,
  salt TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
-- Altas de columnas sobre tablas con datos reales: los usuarios existentes quedan obligados a cambiar la contraseña.
ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
-- Modo prueba (app/sandbox.py): lo prende un admin; "prueba" guarda proveedores, reloj y ubicación simulados.
ALTER TABLE users ADD COLUMN IF NOT EXISTS modo_prueba BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS prueba JSONB;
CREATE TABLE IF NOT EXISTS auth_tokens (
  token TEXT PRIMARY KEY,              -- sha256 del token (el token en claro solo lo tiene el celular)
  username TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
ALTER TABLE auth_tokens ADD COLUMN IF NOT EXISTS usado_at DOUBLE PRECISION;
ALTER TABLE auth_tokens ADD COLUMN IF NOT EXISTS hasheado BOOLEAN NOT NULL DEFAULT FALSE;
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
SCHEMA = DATOS_USUARIO + CUENTAS

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
            c.execute(f"CREATE SCHEMA IF NOT EXISTS {config.DB_SCHEMA}")
            c.execute(SCHEMA)
            _crear_fragmentos(c)
            _hashear_tokens_viejos(c)
            sectors.ensure(c)
            _crear_schema_prueba(c)
        with conn() as c:
            legacy_import.run_once(c, config.LEGACY_SQLITE_PATH)
        bootstrap_users()


def _hashear_tokens_viejos(c) -> None:
    """Los tokens se guardaban en claro: se reemplazan por su sha256 (una sola vez; las sesiones siguen valiendo)."""
    c.execute("UPDATE auth_tokens SET token = encode(sha256(convert_to(token, 'UTF8')), 'hex'), hasheado = TRUE "
              "WHERE NOT hasheado")


def _crear_schema_prueba(c) -> None:
    """Solo las tablas de datos del usuario: lo demás (cuentas, cachés compartidos) se lee del schema real."""
    c.execute(f"CREATE SCHEMA IF NOT EXISTS {sandbox.schema_prueba()}")
    c.execute(f"SET LOCAL search_path TO {sandbox.schema_prueba()}, public")  # public: el tipo vector de pgvector
    c.execute(DATOS_USUARIO)
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
    return d


def create_session(title, kind, code=None, venue=None, speaker=None, created_by=None):
    sid = uuid.uuid4().hex[:12]
    now = time.time()
    with conn() as c:
        c.execute(
            "INSERT INTO sessions (id,title,kind,code,venue,speaker,status,created_by,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (sid, title, kind, code, venue, speaker, "recording", created_by, now, now),
        )
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
    for k in ("summary", "expected_parts"):
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


def get_preferencias_avisos(username) -> dict:
    with conn() as c:
        r = c.execute("SELECT grabar, ubicacion FROM preferencias_avisos WHERE username=%s", (username,)).fetchone()
    return dict(r) if r else {"grabar": True, "ubicacion": False}


def set_preferencias_avisos(username, grabar, ubicacion) -> None:
    with conn() as c:
        c.execute("INSERT INTO preferencias_avisos (username,grabar,ubicacion,updated_at) VALUES (%s,%s,%s,%s) "
                  "ON CONFLICT (username) DO UPDATE SET grabar=EXCLUDED.grabar, ubicacion=EXCLUDED.ubicacion, "
                  "updated_at=EXCLUDED.updated_at", (username, grabar, ubicacion, time.time()))
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

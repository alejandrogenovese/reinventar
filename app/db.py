"""Estado de la app en Postgres (schema DB_SCHEMA): grabaciones, usuarios, tokens e itinerarios.

Las tablas de datos del usuario (DATOS_USUARIO) existen también en el schema de prueba (app/sandbox.py); las de cuentas
(CUENTAS) solo en el real, así que un usuario en modo prueba se loguea igual pero escribe en el schema de prueba.
"""
import json
import time
import uuid
from contextlib import contextmanager

from psycopg.types.json import Jsonb

from . import config, legacy_import, passwords, pg, sandbox, sectors

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
-- talk (charla del catálogo) o event (evento de networking, reinvent.evento): todo se maneja desde el itinerario.
ALTER TABLE itinerary_items ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'talk';
-- Cómo era al agregarlo (título, día, hora, sala, lleno): si AWS lo cambia, la app avisa (app/changes.py).
ALTER TABLE itinerary_items ADD COLUMN IF NOT EXISTS snapshot JSONB;
-- Avisos de Web Push ya mandados (app/push.py): cada uno sale una sola vez.
CREATE TABLE IF NOT EXISTS push_sent (
  username TEXT NOT NULL,
  key TEXT NOT NULL,
  sent_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (username, key)
);
"""
TABLAS_DATOS_USUARIO = ("sessions", "chunks", "blocks", "itinerary_profile", "itinerary_items", "push_sent")

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
  token TEXT PRIMARY KEY,
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
            sectors.ensure(c)
            _crear_schema_prueba(c)
        with conn() as c:
            legacy_import.run_once(c, config.LEGACY_SQLITE_PATH)
        bootstrap_users()


def _crear_schema_prueba(c) -> None:
    """Solo las tablas de datos del usuario: lo demás (cuentas, cachés compartidos) se lee del schema real."""
    c.execute(f"CREATE SCHEMA IF NOT EXISTS {sandbox.schema_prueba()}")
    c.execute(f"SET LOCAL search_path TO {sandbox.schema_prueba()}")
    c.execute(DATOS_USUARIO)


def borrar_datos_prueba() -> int:
    """Vacía las tablas del schema de prueba (de todos los usuarios en modo prueba). Devuelve las filas borradas."""
    total = 0
    with sandbox.real(), conn() as c:
        for tabla in TABLAS_DATOS_USUARIO:
            total += c.execute(f"DELETE FROM {sandbox.schema_prueba()}.{tabla}").rowcount
    return total


def _row(r):
    if r is None:
        return None
    d = dict(r)
    d["summary"] = json.loads(d["summary"]) if d.get("summary") else None
    d["expected_parts"] = json.loads(d["expected_parts"]) if d.get("expected_parts") else None
    return d


def create_session(title, kind, code=None, venue=None, speaker=None):
    sid = uuid.uuid4().hex[:12]
    now = time.time()
    with conn() as c:
        c.execute(
            "INSERT INTO sessions (id,title,kind,code,venue,speaker,status,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (sid, title, kind, code, venue, speaker, "recording", now, now),
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
    with conn() as c:
        return [r["username"] for r in c.execute("SELECT DISTINCT username FROM push_subscriptions").fetchall()]


def mark_push_sent(username, key) -> bool:
    """True si es la primera vez (hay que mandarlo); False si ya se había mandado."""
    with conn() as c:
        return c.execute("INSERT INTO push_sent (username,key,sent_at) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                         (username, key, time.time())).rowcount == 1


def unmark_push_sent(username, key):
    with conn() as c:
        c.execute("DELETE FROM push_sent WHERE username=%s AND key=%s", (username, key))


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


def create_auth_token(token, username):
    with conn() as c:
        c.execute(
            "INSERT INTO auth_tokens (token,username,created_at) VALUES (%s,%s,%s)", (token, username, time.time())
        )


def resolve_auth_token(token):
    """Username dueño del token, solo si el usuario sigue activo."""
    with conn() as c:
        r = c.execute(
            "SELECT t.username FROM auth_tokens t JOIN users u ON u.username = t.username "
            "WHERE t.token=%s AND u.is_active",
            (token,),
        ).fetchone()
    return r["username"] if r else None


def delete_auth_token(token):
    with conn() as c:
        c.execute("DELETE FROM auth_tokens WHERE token=%s", (token,))


def revoke_tokens(username, except_token=None):
    with conn() as c:
        c.execute(
            "DELETE FROM auth_tokens WHERE username=%s AND token IS DISTINCT FROM %s", (username, except_token)
        )


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


def remove_item(username, code):
    with conn() as c:
        c.execute("DELETE FROM itinerary_items WHERE username=%s AND code=%s", (username, code))

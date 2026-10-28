"""SQLite sobre el volumen. Una conexión por operación; WAL para lecturas concurrentes."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from . import config, passwords

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  kind TEXT NOT NULL,
  code TEXT, venue TEXT, speaker TEXT,
  status TEXT NOT NULL,
  error TEXT,
  progress TEXT,
  duration_s REAL,
  expected_parts TEXT,
  summary TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  session_id TEXT NOT NULL,
  part INTEGER NOT NULL,
  seq INTEGER NOT NULL,
  bytes INTEGER NOT NULL,
  received_at REAL NOT NULL,
  PRIMARY KEY (session_id, part, seq)
);
CREATE TABLE IF NOT EXISTS blocks (
  session_id TEXT NOT NULL,
  idx INTEGER NOT NULL,
  start_s REAL NOT NULL,
  end_s REAL NOT NULL,
  en TEXT NOT NULL,
  es TEXT,
  PRIMARY KEY (session_id, idx)
);
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY,
  salt TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_tokens (
  token TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS itinerary_profile (
  username TEXT PRIMARY KEY,
  role TEXT, experience TEXT, interests TEXT, prompt TEXT,
  notes TEXT, skipped TEXT,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS itinerary_items (
  username TEXT NOT NULL,
  code TEXT NOT NULL,
  base TEXT NOT NULL,
  day TEXT NOT NULL,
  start TEXT NOT NULL,
  locked INTEGER NOT NULL DEFAULT 0,
  reason TEXT,
  added_at REAL NOT NULL,
  PRIMARY KEY (username, code)
);
"""

KINDS = ("Keynote", "Chalk talk", "Workshop", "Breakout")
PROCESSING = ("queued", "transcribing", "translating", "summarizing")


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _needs_itinerary_migration(c) -> bool:
    """True si itinerary_profile existe con el esquema viejo (singleton, sin username)."""
    cols = {r["name"] for r in c.execute("PRAGMA table_info(itinerary_profile)").fetchall()}
    return bool(cols) and "username" not in cols


def _add_missing_columns(c, table: str, columns: dict[str, str]):
    """Alta no destructiva de columnas nuevas en una tabla que ya existe con datos reales."""
    existing = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, decl in columns.items():
        if name not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        if _needs_itinerary_migration(c):
            c.executescript("DROP TABLE IF EXISTS itinerary_profile; DROP TABLE IF EXISTS itinerary_items;")
        c.executescript(SCHEMA)
        _add_missing_columns(c, "itinerary_profile", {"notes": "TEXT", "skipped": "TEXT"})
    bootstrap_users()


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
            "INSERT INTO sessions (id,title,kind,code,venue,speaker,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, title, kind, code, venue, speaker, "recording", now, now),
        )
    return get_session(sid)


def get_session(sid):
    with conn() as c:
        r = c.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        s = _row(r)
        if s:
            agg = c.execute("SELECT COUNT(*) n, COALESCE(SUM(bytes),0) b FROM chunks WHERE session_id=?", (sid,)).fetchone()
            s["chunks_received"] = agg["n"]
            s["bytes_received"] = agg["b"]
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
    cols = ", ".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE sessions SET {cols} WHERE id=?", (*fields.values(), sid))


def delete_session(sid):
    with conn() as c:
        c.execute("DELETE FROM blocks WHERE session_id=?", (sid,))
        c.execute("DELETE FROM chunks WHERE session_id=?", (sid,))
        c.execute("DELETE FROM sessions WHERE id=?", (sid,))


def record_chunk(sid, part, seq, nbytes):
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO chunks (session_id,part,seq,bytes,received_at) VALUES (?,?,?,?,?)",
            (sid, part, seq, nbytes, time.time()),
        )


def chunk_index(sid):
    """{part: set(seq)} de lo recibido."""
    with conn() as c:
        rows = c.execute("SELECT part, seq FROM chunks WHERE session_id=?", (sid,)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["part"], set()).add(r["seq"])
    return out


def replace_blocks(sid, blocks):
    with conn() as c:
        c.execute("DELETE FROM blocks WHERE session_id=?", (sid,))
        c.executemany(
            "INSERT INTO blocks (session_id,idx,start_s,end_s,en,es) VALUES (?,?,?,?,?,?)",
            [(sid, i, b["start"], b["end"], b["en"], b.get("es")) for i, b in enumerate(blocks)],
        )


def set_translations(sid, pairs):
    with conn() as c:
        c.executemany("UPDATE blocks SET es=? WHERE session_id=? AND idx=?", [(es, sid, i) for i, es in pairs])


def get_blocks(sid):
    with conn() as c:
        rows = c.execute("SELECT idx,start_s,end_s,en,es FROM blocks WHERE session_id=? ORDER BY idx", (sid,)).fetchall()
    return [dict(r) for r in rows]


def sessions_in(statuses):
    q = ",".join("?" * len(statuses))
    with conn() as c:
        rows = c.execute(f"SELECT id FROM sessions WHERE status IN ({q}) ORDER BY updated_at", tuple(statuses)).fetchall()
    return [r["id"] for r in rows]


# --- usuarios / login ------------------------------------------------------------------------

def get_user(username):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return dict(r) if r else None


def create_user(username, salt, password_hash):
    with conn() as c:
        c.execute(
            "INSERT INTO users (username,salt,password_hash,created_at) VALUES (?,?,?,?)",
            (username, salt, password_hash, time.time()),
        )


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
        c.execute("INSERT INTO auth_tokens (token,username,created_at) VALUES (?,?,?)", (token, username, time.time()))


def resolve_auth_token(token):
    with conn() as c:
        r = c.execute("SELECT username FROM auth_tokens WHERE token=?", (token,)).fetchone()
    return r["username"] if r else None


def delete_auth_token(token):
    with conn() as c:
        c.execute("DELETE FROM auth_tokens WHERE token=?", (token,))


# --- itinerario (por usuario) ----------------------------------------------------------------

def get_profile(username):
    with conn() as c:
        r = c.execute("SELECT * FROM itinerary_profile WHERE username=?", (username,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["interests"] = json.loads(d["interests"]) if d.get("interests") else []
    d["skipped"] = json.loads(d["skipped"]) if d.get("skipped") else []
    return d


def save_profile(username, role, experience, interests, prompt):
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO itinerary_profile (username,role,experience,interests,prompt,updated_at) VALUES (?,?,?,?,?,?)",
            (username, role, experience, json.dumps(interests, ensure_ascii=False), prompt, time.time()),
        )


def save_run_meta(username, notes, skipped):
    """Se corre después de save_profile (que resetea notes/skipped al reemplazar la fila)."""
    with conn() as c:
        c.execute(
            "UPDATE itinerary_profile SET notes=?, skipped=? WHERE username=?",
            (notes, json.dumps(skipped, ensure_ascii=False), username),
        )


def list_itinerary_items(username):
    with conn() as c:
        rows = c.execute("SELECT * FROM itinerary_items WHERE username=? ORDER BY day, start", (username,)).fetchall()
    return [dict(r) for r in rows]


def replace_itinerary_items(username, items):
    """Reemplaza las sesiones no bloqueadas de este usuario; las bloqueadas (locked=1) se conservan tal cual."""
    with conn() as c:
        c.execute("DELETE FROM itinerary_items WHERE username=? AND locked=0", (username,))
        c.executemany(
            "INSERT INTO itinerary_items (username,code,base,day,start,locked,reason,added_at) VALUES (?,?,?,?,?,0,?,?)",
            [(username, i["code"], i["base"], i["day"], i["start"], i.get("reason"), time.time()) for i in items],
        )


def add_item(username, code, base, day, start, locked=False, reason=None):
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO itinerary_items (username,code,base,day,start,locked,reason,added_at) VALUES (?,?,?,?,?,?,?,?)",
            (username, code, base, day, start, int(locked), reason, time.time()),
        )


def set_item_locked(username, code, locked):
    with conn() as c:
        c.execute("UPDATE itinerary_items SET locked=? WHERE username=? AND code=?", (int(locked), username, code))


def remove_item(username, code):
    with conn() as c:
        c.execute("DELETE FROM itinerary_items WHERE username=? AND code=?", (username, code))

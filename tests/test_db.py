"""Capa de datos sobre Postgres: upserts que antes eran INSERT OR REPLACE e importación del SQLite viejo."""
import sqlite3
import uuid

from app import db, legacy_import, pg


def _user():
    return f"u_{uuid.uuid4().hex[:8]}"


def setup_module(_module):
    db.init()


def test_save_profile_resets_run_meta_on_replace():
    username = _user()
    db.save_profile(username, "arquitecto", "senior", ["AI"], "agentes")
    db.save_run_meta(username, "notas", ["X1"])

    db.save_profile(username, "data", "mid", ["Data"], "lakehouse")

    p = db.get_profile(username)
    assert (p["role"], p["interests"], p["notes"], p["skipped"]) == ("data", ["Data"], None, [])


def test_add_item_twice_updates_instead_of_failing():
    username = _user()
    db.add_item(username, "AIM301-1", "AIM301", "2026-12-01", "09:00")

    db.add_item(username, "AIM301-1", "AIM301", "2026-12-01", "10:00", locked=True, reason="me interesa")

    items = db.list_itinerary_items(username)
    assert [(i["start"], i["locked"], i["reason"]) for i in items] == [("10:00", 1, "me interesa")]


def test_replace_items_keeps_locked_even_if_regenerated():
    username = _user()
    db.add_item(username, "A-1", "A", "2026-12-01", "09:00", locked=True)
    db.add_item(username, "B-1", "B", "2026-12-01", "11:00")

    db.replace_itinerary_items(username, [
        {"code": "A-1", "base": "A", "day": "2026-12-01", "start": "09:00"},
        {"code": "C-1", "base": "C", "day": "2026-12-02", "start": "09:00"},
    ])

    assert {(i["code"], i["locked"]) for i in db.list_itinerary_items(username)} == {("A-1", 1), ("C-1", 0)}


def test_record_chunk_is_idempotent():
    s = db.create_session("Charla", "Breakout")

    db.record_chunk(s["id"], 0, 0, 100)
    db.record_chunk(s["id"], 0, 0, 120)

    assert db.get_session(s["id"])["bytes_received"] == 120


def _legacy_sqlite(path, username):
    src = sqlite3.connect(path)
    src.executescript(
        "CREATE TABLE users (username TEXT, salt TEXT, password_hash TEXT, created_at REAL);"
        "CREATE TABLE itinerary_items (username TEXT, code TEXT, base TEXT, day TEXT, start TEXT,"
        " locked INTEGER, reason TEXT, added_at REAL);"
    )
    src.execute("INSERT INTO users VALUES (?, 's', 'h', 1.5)", (username,))
    src.execute("INSERT INTO itinerary_items VALUES (?, 'X-1', 'X', '2026-12-01', '09:00', 1, NULL, 2.5)", (username,))
    src.commit()
    src.close()


def test_legacy_import_copies_rows_and_renames_file(tmp_path):
    username = _user()
    path = tmp_path / "reinventar.db"
    _legacy_sqlite(path, username)

    with pg.pool().connection() as c:
        c.execute("DELETE FROM users")  # la importación solo corre sobre una base sin usuarios
        legacy_import.run_once(c, path)

    assert db.get_user(username)["salt"] == "s"
    assert [i["code"] for i in db.list_itinerary_items(username)] == ["X-1"]
    assert not path.exists() and (tmp_path / "reinventar.db.migrated").exists()


def test_legacy_import_skips_when_postgres_has_users(tmp_path):
    db.bootstrap_users()
    path = tmp_path / "reinventar.db"
    _legacy_sqlite(path, "otro")

    with pg.pool().connection() as c:
        legacy_import.run_once(c, path)

    assert path.exists()
    assert db.get_user("otro") is None

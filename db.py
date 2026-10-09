"""SQLite storage for DepShield. Zero-config local database."""
from __future__ import annotations

import os
import sqlite3
import time

DB_PATH = os.environ.get("DEPSHIELD_DB", os.path.join(os.path.dirname(__file__), "depshield.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    status_api TEXT,
    status_page TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    added_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    checked_at INTEGER NOT NULL,
    ok INTEGER NOT NULL,
    latency_ms INTEGER,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS domain_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at INTEGER NOT NULL,
    ok INTEGER NOT NULL,
    latency_ms INTEGER
);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    impact TEXT,
    started_at INTEGER,
    resolved INTEGER NOT NULL DEFAULT 0,
    url TEXT,
    seen_at INTEGER NOT NULL,
    UNIQUE(vendor_id, external_id)
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    page TEXT NOT NULL,
    url TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at INTEGER NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    read INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    con = connect()
    con.executescript(SCHEMA)
    con.commit()
    con.close()


def now() -> int:
    return int(time.time())


# ---- vendors ----
def upsert_vendor(key, name, category, status_api=None, status_page=None):
    con = connect()
    con.execute(
        """INSERT INTO vendors (key, name, category, status_api, status_page, added_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET name=excluded.name, category=excluded.category,
               status_api=excluded.status_api, status_page=excluded.status_page""",
        (key, name, category, status_api, status_page, now()),
    )
    con.commit()
    con.close()


def list_vendors(enabled_only=False):
    con = connect()
    q = "SELECT * FROM vendors ORDER BY name"
    if enabled_only:
        q = "SELECT * FROM vendors WHERE enabled=1 ORDER BY name"
    rows = con.execute(q).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_vendor_row(vendor_id):
    con = connect()
    row = con.execute("SELECT * FROM vendors WHERE id=?", (vendor_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def set_vendor_enabled(vendor_id, enabled: bool):
    con = connect()
    con.execute("UPDATE vendors SET enabled=? WHERE id=?", (1 if enabled else 0, vendor_id))
    con.commit()
    con.close()


def delete_vendor(vendor_id):
    con = connect()
    con.execute("DELETE FROM checks WHERE vendor_id=?", (vendor_id,))
    con.execute("DELETE FROM incidents WHERE vendor_id=?", (vendor_id,))
    con.execute("DELETE FROM snapshots WHERE vendor_id=?", (vendor_id,))
    con.execute("DELETE FROM vendors WHERE id=?", (vendor_id,))
    con.commit()
    con.close()


# ---- checks ----
def record_check(vendor_id, ok: bool, latency_ms=None, detail=None):
    con = connect()
    con.execute(
        "INSERT INTO checks (vendor_id, checked_at, ok, latency_ms, detail) VALUES (?, ?, ?, ?, ?)",
        (vendor_id, now(), 1 if ok else 0, latency_ms, detail),
    )
    con.commit()
    con.close()


def record_domain_check(ok: bool, latency_ms=None):
    con = connect()
    con.execute(
        "INSERT INTO domain_checks (checked_at, ok, latency_ms) VALUES (?, ?, ?)",
        (now(), 1 if ok else 0, latency_ms),
    )
    con.commit()
    con.close()


def uptime_pct(vendor_id, since_ts) -> float | None:
    con = connect()
    row = con.execute(
        "SELECT COUNT(*) c, SUM(ok) s FROM checks WHERE vendor_id=? AND checked_at>=?",
        (vendor_id, since_ts),
    ).fetchone()
    con.close()
    if not row or not row["c"]:
        return None
    return round(100.0 * (row["s"] or 0) / row["c"], 1)


def recent_checks(vendor_id, limit=20):
    con = connect()
    rows = con.execute(
        "SELECT * FROM checks WHERE vendor_id=? ORDER BY checked_at DESC LIMIT ?",
        (vendor_id, limit),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def domain_uptime_pct(since_ts) -> float | None:
    con = connect()
    row = con.execute(
        "SELECT COUNT(*) c, SUM(ok) s FROM domain_checks WHERE checked_at>=?", (since_ts,)
    ).fetchone()
    con.close()
    if not row or not row["c"]:
        return None
    return round(100.0 * (row["s"] or 0) / row["c"], 1)


# ---- incidents ----
def record_incident(vendor_id, external_id, title, impact=None, started_at=None, url=None):
    """Returns True if this is a NEW incident (not seen before)."""
    con = connect()
    try:
        con.execute(
            """INSERT INTO incidents (vendor_id, external_id, title, impact, started_at, url, seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (vendor_id, external_id, title, impact, started_at, url, now()),
        )
        con.commit()
        is_new = True
    except sqlite3.IntegrityError:
        is_new = False
    con.close()
    return is_new


def mark_incident_resolved(vendor_id, external_id):
    con = connect()
    con.execute(
        "UPDATE incidents SET resolved=1 WHERE vendor_id=? AND external_id=?",
        (vendor_id, external_id),
    )
    con.commit()
    con.close()


def list_incidents(vendor_id=None, limit=30, unresolved_only=False):
    con = connect()
    q = """SELECT i.*, v.name AS vendor_name FROM incidents i
           JOIN vendors v ON v.id=i.vendor_id"""
    clauses, params = [], []
    if vendor_id:
        clauses.append("i.vendor_id=?")
        params.append(vendor_id)
    if unresolved_only:
        clauses.append("i.resolved=0")
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY i.seen_at DESC LIMIT ?"
    params.append(limit)
    rows = con.execute(q, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


def incidents_since(vendor_id, since_ts):
    con = connect()
    rows = con.execute(
        "SELECT * FROM incidents WHERE vendor_id=? AND seen_at>=? ORDER BY seen_at DESC",
        (vendor_id, since_ts),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


# ---- snapshots (ToS diff watcher) ----
def last_snapshot(vendor_id, page):
    con = connect()
    row = con.execute(
        "SELECT * FROM snapshots WHERE vendor_id=? AND page=? ORDER BY fetched_at DESC LIMIT 1",
        (vendor_id, page),
    ).fetchone()
    con.close()
    return dict(row) if row else None


def save_snapshot(vendor_id, page, url, content_hash):
    con = connect()
    con.execute(
        "INSERT INTO snapshots (vendor_id, page, url, content_hash, fetched_at) VALUES (?, ?, ?, ?, ?)",
        (vendor_id, page, url, content_hash, now()),
    )
    con.commit()
    con.close()


# ---- alerts ----
def add_alert(kind, title, body=None):
    con = connect()
    con.execute(
        "INSERT INTO alerts (created_at, kind, title, body) VALUES (?, ?, ?, ?)",
        (now(), kind, title, body),
    )
    con.commit()
    con.close()


def list_alerts(limit=50, unread_only=False):
    con = connect()
    q = "SELECT * FROM alerts"
    if unread_only:
        q += " WHERE read=0"
    q += " ORDER BY created_at DESC LIMIT ?"
    rows = con.execute(q, (limit,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def mark_alerts_read():
    con = connect()
    con.execute("UPDATE alerts SET read=1")
    con.commit()
    con.close()


def unread_count():
    con = connect()
    row = con.execute("SELECT COUNT(*) c FROM alerts WHERE read=0").fetchone()
    con.close()
    return row["c"]


# ---- settings ----
def get_setting(key, default=None):
    con = connect()
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    con.close()
    return row["value"] if row else default


def set_setting(key, value):
    con = connect()
    con.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    con.commit()
    con.close()

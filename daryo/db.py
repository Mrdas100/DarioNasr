"""سجل الأخبار والحالة (SQLite)"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id        INTEGER NOT NULL UNIQUE,
    posted_at     TEXT NOT NULL,
    seen_at       TEXT NOT NULL,
    raw_text      TEXT,
    norm_text     TEXT,
    text_hash     TEXT,
    photos        TEXT,
    status        TEXT NOT NULL,      -- new | sent | skipped | duplicate | failed | baseline
    reason        TEXT,
    template      TEXT,
    headline      TEXT,
    body          TEXT,
    dup_of        INTEGER,
    update_of     INTEGER,
    png_path      TEXT,
    sent_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_seen ON posts(seen_at);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, level TEXT, message TEXT
);
"""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # ---------- kv ----------
    def get(self, k: str, default=None):
        row = self.conn.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(row["v"]) if row else default

    def set(self, k: str, v) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                              (k, json.dumps(v, ensure_ascii=False)))
            self.conn.commit()

    # ---------- posts ----------
    def known(self, msg_id: int):
        return self.conn.execute("SELECT * FROM posts WHERE msg_id=?", (msg_id,)).fetchone()

    def upsert_post(self, msg_id: int, **fields) -> int:
        with self.lock:
            row = self.conn.execute("SELECT id FROM posts WHERE msg_id=?", (msg_id,)).fetchone()
            if row:
                if fields:
                    cols = ", ".join(f"{k}=?" for k in fields)
                    self.conn.execute(f"UPDATE posts SET {cols} WHERE msg_id=?", (*fields.values(), msg_id))
                pid = row["id"]
            else:
                fields.setdefault("seen_at", now_utc().isoformat())
                fields.setdefault("status", "new")
                fields.setdefault("posted_at", now_utc().isoformat())
                cols = ", ".join(["msg_id", *fields.keys()])
                qs = ", ".join("?" * (len(fields) + 1))
                cur = self.conn.execute(f"INSERT INTO posts({cols}) VALUES({qs})", (msg_id, *fields.values()))
                pid = cur.lastrowid
            self.conn.commit()
            return pid

    def recent_published(self, hours: int):
        since = (now_utc() - timedelta(hours=hours)).isoformat()
        return self.conn.execute(
            "SELECT * FROM posts WHERE status IN ('sent') AND seen_at>=? ORDER BY id DESC LIMIT 300",
            (since,)).fetchall()

    def last_posts(self, n: int = 10):
        return self.conn.execute("SELECT * FROM posts ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    def stats_today(self):
        since = (now_utc() - timedelta(hours=24)).isoformat()
        rows = self.conn.execute("SELECT status, COUNT(*) c FROM posts WHERE seen_at>=? GROUP BY status",
                                 (since,)).fetchall()
        return {r["status"]: r["c"] for r in rows}

    def max_msg_id(self) -> int:
        row = self.conn.execute("SELECT MAX(msg_id) m FROM posts").fetchone()
        return row["m"] or 0

    def log(self, level: str, message: str) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO events(at, level, message) VALUES(?,?,?)",
                              (now_utc().isoformat(), level, message))
            self.conn.commit()

"""
Storage
-------
Persists raw per-process snapshots to SQLite.
This is the truth layer — Prometheus is NOT a database.

Retention: rows older than RETENTION_DAYS are pruned on each write cycle.
"""

import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

RETENTION_DAYS = 7
DB_PATH = Path("/data/metrics.db")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")  # allows concurrent reads
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS process_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT    NOT NULL,
            pid         INTEGER NOT NULL,
            username    TEXT,
            name        TEXT,
            cmd_short   TEXT,
            cpu_percent REAL,
            mem_percent REAL,
            gpu_mem_mb  REAL,
            uid         INTEGER,
            session_id  INTEGER,
            cmd_hash    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ps_ts       ON process_snapshots(ts);
        CREATE INDEX IF NOT EXISTS idx_ps_username ON process_snapshots(username);

        CREATE TABLE IF NOT EXISTS gpu_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ts           TEXT NOT NULL,
            gpu_id       INTEGER,
            util_pct     REAL,
            mem_used_mb  REAL,
            mem_total_mb REAL
        );

        CREATE INDEX IF NOT EXISTS idx_gs_ts ON gpu_snapshots(ts);

        CREATE TABLE IF NOT EXISTS hike_events (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        TEXT NOT NULL,
            username  TEXT,
            type      TEXT,
            value     REAL,
            threshold REAL
        );
        """
    )
    conn.commit()


def save_snapshot(
    conn: sqlite3.Connection,
    processes: list[dict],
    gpu_summary: list[dict],
    hike_events: list[dict],
) -> None:
    ts = datetime.now(timezone.utc).isoformat()

    conn.executemany(
        """
        INSERT INTO process_snapshots
            (ts, pid, username, name, cmd_short, cpu_percent, mem_percent, gpu_mem_mb,
             uid, session_id, cmd_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                ts,
                p.get("pid"),
                p.get("username"),
                p.get("name"),
                p.get("cmd_short"),
                p.get("cpu_percent"),
                p.get("memory_percent"),
                p.get("gpu_mem_mb", 0.0),
                p.get("uid"),
                p.get("session_id"),
                p.get("cmd_hash"),
            )
            for p in processes
        ],
    )

    conn.executemany(
        """
        INSERT INTO gpu_snapshots (ts, gpu_id, util_pct, mem_used_mb, mem_total_mb)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                ts,
                g["gpu_id"],
                g["util_pct"],
                g["mem_used_mb"],
                g["mem_total_mb"],
            )
            for g in gpu_summary
        ],
    )

    if hike_events:
        conn.executemany(
            """
            INSERT INTO hike_events (ts, username, type, value, threshold)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (ts, e["user"], e["type"], e["value"], e["threshold"])
                for e in hike_events
            ],
        )

    conn.commit()
    _prune(conn)


def _prune(conn: sqlite3.Connection) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    for table in ("process_snapshots", "gpu_snapshots", "hike_events"):
        conn.execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))  # noqa: S608
    conn.commit()


# ---------------------------------------------------------------------------
# Query helpers (used by FastAPI)
# ---------------------------------------------------------------------------


def query_top_users(
    conn: sqlite3.Connection, minutes: int = 60, limit: int = 20
) -> list[dict]:
    """Top users by GPU memory over the last N minutes."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    rows = conn.execute(
        """
        SELECT username,
               AVG(cpu_percent)  AS avg_cpu,
               AVG(mem_percent)  AS avg_mem,
               SUM(gpu_mem_mb)   AS total_gpu_mb,
               COUNT(DISTINCT pid) AS distinct_procs
        FROM process_snapshots
        WHERE ts >= ?
        GROUP BY username
        ORDER BY total_gpu_mb DESC
        LIMIT ?
        """,
        (since, limit),
    ).fetchall()
    cols = ["username", "avg_cpu", "avg_mem", "total_gpu_mb", "distinct_procs"]
    return [dict(zip(cols, r)) for r in rows]


def query_hike_events(conn: sqlite3.Connection, hours: int = 24) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        "SELECT ts, username, type, value, threshold FROM hike_events WHERE ts >= ? ORDER BY ts DESC",
        (since,),
    ).fetchall()
    cols = ["ts", "username", "type", "value", "threshold"]
    return [dict(zip(cols, r)) for r in rows]


def query_gpu_history(conn: sqlite3.Connection, hours: int = 24) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        """
        SELECT ts, gpu_id, util_pct, mem_used_mb, mem_total_mb
        FROM gpu_snapshots
        WHERE ts >= ?
        ORDER BY ts ASC
        """,
        (since,),
    ).fetchall()
    cols = ["ts", "gpu_id", "util_pct", "mem_used_mb", "mem_total_mb"]
    return [dict(zip(cols, r)) for r in rows]

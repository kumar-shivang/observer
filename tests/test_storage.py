"""
Tests for monitor.storage — uses in-memory SQLite to avoid touching /data.
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from monitor import storage


@pytest.fixture()
def mem_db():
    """Fresh in-memory SQLite connection, schema initialised."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    storage.init_db(conn)
    yield conn
    conn.close()


PROCS = [
    {
        "pid": 1, "username": "alice", "name": "python3", "cmd_short": "python3 train.py",
        "cpu_percent": 50.0, "memory_percent": 5.0, "gpu_mem_mb": 4096.0,
    },
    {
        "pid": 2, "username": "bob", "name": "bash", "cmd_short": "bash",
        "cpu_percent": 5.0, "memory_percent": 0.5, "gpu_mem_mb": 0.0,
    },
]

GPUS = [
    {"gpu_id": 0, "util_pct": 72.0, "mem_used_mb": 8192.0, "mem_total_mb": 24576.0},
]

ABUSE = [
    {"user": "alice", "type": "gpu_mem", "value": 4096.0, "threshold": 3000.0},
]


class TestInitDb:
    def test_creates_expected_tables(self, mem_db):
        tables = {
            row[0]
            for row in mem_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"process_snapshots", "gpu_snapshots", "abuse_events"} <= tables


class TestSaveSnapshot:
    def test_saves_process_rows(self, mem_db):
        storage.save_snapshot(mem_db, PROCS, [], [])
        count = mem_db.execute("SELECT COUNT(*) FROM process_snapshots").fetchone()[0]
        assert count == 2

    def test_saves_gpu_rows(self, mem_db):
        storage.save_snapshot(mem_db, [], GPUS, [])
        count = mem_db.execute("SELECT COUNT(*) FROM gpu_snapshots").fetchone()[0]
        assert count == 1

    def test_saves_abuse_rows(self, mem_db):
        storage.save_snapshot(mem_db, [], [], ABUSE)
        count = mem_db.execute("SELECT COUNT(*) FROM abuse_events").fetchone()[0]
        assert count == 1

    def test_no_error_on_empty_inputs(self, mem_db):
        storage.save_snapshot(mem_db, [], [], [])  # should not raise

    def test_prune_removes_old_rows(self, mem_db):
        # Insert a row with a timestamp 8 days ago
        old_ts = (
            datetime.now(timezone.utc) - timedelta(days=8)
        ).isoformat()
        mem_db.execute(
            "INSERT INTO process_snapshots "
            "(ts, pid, username, name, cmd_short, cpu_percent, mem_percent, gpu_mem_mb) "
            "VALUES (?, 1, 'gone', 'bash', 'bash', 1.0, 0.1, 0.0)",
            (old_ts,),
        )
        mem_db.commit()

        # Trigger prune via a new save
        storage.save_snapshot(mem_db, [], [], [])

        count = mem_db.execute(
            "SELECT COUNT(*) FROM process_snapshots WHERE username='gone'"
        ).fetchone()[0]
        assert count == 0


class TestQueryTopUsers:
    def test_returns_top_users(self, mem_db):
        storage.save_snapshot(mem_db, PROCS, [], [])
        results = storage.query_top_users(mem_db, minutes=60, limit=10)
        usernames = [r["username"] for r in results]
        assert "alice" in usernames
        assert "bob" in usernames

    def test_ordered_by_total_gpu_desc(self, mem_db):
        storage.save_snapshot(mem_db, PROCS, [], [])
        results = storage.query_top_users(mem_db, minutes=60, limit=10)
        assert results[0]["username"] == "alice"  # alice has higher GPU

    def test_returns_empty_outside_window(self, mem_db):
        storage.save_snapshot(mem_db, PROCS, [], [])
        results = storage.query_top_users(mem_db, minutes=0, limit=10)
        assert results == []


class TestQueryAbuseEvents:
    def test_returns_abuse_events(self, mem_db):
        storage.save_snapshot(mem_db, [], [], ABUSE)
        events = storage.query_abuse_events(mem_db, hours=24)
        assert len(events) == 1
        assert events[0]["username"] == "alice"

    def test_empty_when_no_events(self, mem_db):
        assert storage.query_abuse_events(mem_db, hours=24) == []


class TestQueryGpuHistory:
    def test_returns_gpu_rows(self, mem_db):
        storage.save_snapshot(mem_db, [], GPUS, [])
        rows = storage.query_gpu_history(mem_db, hours=24)
        assert len(rows) == 1
        assert rows[0]["gpu_id"] == 0
        assert rows[0]["util_pct"] == 72.0

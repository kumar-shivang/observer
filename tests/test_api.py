"""
Tests for monitor.api — all endpoints via FastAPI TestClient.
Uses an in-memory SQLite DB injected into app.state.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from monitor import storage
from monitor.api import app


@pytest.fixture(autouse=True)
def inject_db():
    """
    Each test gets a fresh in-memory DB.
    The get_db dependency is overridden so the API uses it instead of /data.
    autouse=True so every test in this module gets isolation automatically.
    """
    from monitor.api import get_db

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    storage.init_db(conn)

    def _override():
        try:
            yield conn
        finally:
            pass  # keep open; closed in finally below

    app.dependency_overrides[get_db] = _override
    yield conn
    app.dependency_overrides.pop(get_db, None)
    conn.close()


@pytest.fixture()
def client():
    return TestClient(app)


PROCS = [
    {
        "pid": 1, "username": "alice", "name": "python3", "cmd_short": "python3 train.py",
        "cpu_percent": 50.0, "memory_percent": 5.0, "gpu_mem_mb": 4096.0,
    }
]
GPUS = [{"gpu_id": 0, "util_pct": 72.0, "mem_used_mb": 8192.0, "mem_total_mb": 24576.0}]
ABUSE = [{"user": "alice", "type": "gpu_mem", "value": 4096.0, "threshold": 3000.0}]


class TestHealth:
    def test_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestMetricsEndpoint:
    def test_returns_prometheus_text(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]


class TestTopEndpoint:
    def test_returns_list(self, client, inject_db):
        storage.save_snapshot(inject_db, PROCS, [], [])
        r = client.get("/top?minutes=60")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert data[0]["username"] == "alice"

    def test_rejects_invalid_minutes(self, client):
        r = client.get("/top?minutes=0")
        assert r.status_code == 422

    def test_empty_db_returns_empty_list(self, client):
        r = client.get("/top")
        assert r.status_code == 200
        assert r.json() == []


class TestAbuseEndpoint:
    def test_returns_abuse_events(self, client, inject_db):
        storage.save_snapshot(inject_db, [], [], ABUSE)
        r = client.get("/abuse?hours=24")
        assert r.status_code == 200
        events = r.json()
        assert len(events) == 1
        assert events[0]["username"] == "alice"

    def test_empty_when_no_events(self, client):
        r = client.get("/abuse")
        assert r.status_code == 200
        assert r.json() == []


class TestGpuHistoryEndpoint:
    def test_returns_gpu_rows(self, client, inject_db):
        storage.save_snapshot(inject_db, [], GPUS, [])
        r = client.get("/gpu/history?hours=24")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["gpu_id"] == 0

    def test_empty_when_no_data(self, client):
        r = client.get("/gpu/history")
        assert r.status_code == 200
        assert r.json() == []


class TestProcessesLatestEndpoint:
    def test_returns_rows_for_user(self, client, inject_db):
        storage.save_snapshot(inject_db, PROCS, [], [])
        r = client.get("/processes/latest?user=alice")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["pid"] == 1

    def test_empty_for_unknown_user(self, client):
        r = client.get("/processes/latest?user=nobody")
        assert r.status_code == 200
        assert r.json() == []

    def test_missing_user_param_returns_422(self, client):
        r = client.get("/processes/latest")
        assert r.status_code == 422

"""
API
---
FastAPI application exposing:
  GET /metrics          — Prometheus scrape endpoint
  GET /health           — liveness probe
  GET /top              — top users by GPU/CPU over last N minutes
  GET /abuse            — abuse events from the last 24 h
  GET /gpu/history      — per-GPU utilisation history
  GET /processes/latest — latest raw process snapshot for a user

All JSON endpoints query SQLite (the truth layer), not Prometheus.
"""

import sqlite3
from fastapi import FastAPI, Query, Depends
from fastapi.responses import Response, JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from monitor import storage

app = FastAPI(title="Observer", version="1.0.0")


# ---------------------------------------------------------------------------
# Shared DB dependency
# ---------------------------------------------------------------------------


def get_db():
    """Yield a SQLite connection per-request (thread-safe with WAL mode)."""
    conn = storage._connect()
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def prometheus_metrics():
    """Prometheus scrape endpoint."""
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/top")
def top_users(
    minutes: int = Query(default=60, ge=1, le=10080, description="Look-back window in minutes"),
    limit: int = Query(default=20, ge=1, le=100),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Top users by GPU + CPU usage over the last `minutes` minutes."""
    return storage.query_top_users(conn, minutes=minutes, limit=limit)


@app.get("/abuse")
def abuse_events(
    hours: int = Query(default=24, ge=1, le=168),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Recent abuse threshold breaches."""
    return storage.query_abuse_events(conn, hours=hours)


@app.get("/gpu/history")
def gpu_history(
    hours: int = Query(default=24, ge=1, le=168),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Per-GPU utilisation history."""
    return storage.query_gpu_history(conn, hours=hours)


@app.get("/processes/latest")
def latest_processes(
    user: str = Query(description="Username to filter by"),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Latest raw process snapshot rows for a specific user (most recent 100)."""
    rows = conn.execute(
        """
        SELECT ts, pid, name, cmd_short, cpu_percent, mem_percent, gpu_mem_mb
        FROM process_snapshots
        WHERE username = ?
        ORDER BY ts DESC
        LIMIT 100
        """,
        (user,),
    ).fetchall()
    cols = ["ts", "pid", "name", "cmd_short", "cpu_percent", "mem_percent", "gpu_mem_mb"]
    return [dict(zip(cols, r)) for r in rows]

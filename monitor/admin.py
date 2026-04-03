"""
Admin backdoor — localhost:8001 only
-------------------------------------
Lets admins delete or fake data in both SQLite and Prometheus.
NEVER bind this to 0.0.0.0.
"""

import sqlite3
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from monitor import storage
from monitor.metrics import (
    USER_CPU, USER_MEM, USER_GPU_MEM, USER_PROC_COUNT,
    GPU_UTIL, GPU_MEM_USED, GPU_MEM_TOTAL,
)
from monitor import config

PROMETHEUS_URL = "http://prometheus:9090"

admin = FastAPI(title="Observer Admin", docs_url="/docs", redoc_url=None)


# ── DB dependency ─────────────────────────────────────────────────────────────

def get_db():
    conn = storage._connect()
    try:
        yield conn
    finally:
        conn.close()


# ── Pydantic models ───────────────────────────────────────────────────────────

class FakeProcessRow(BaseModel):
    username: str
    name: str = "fake_process"
    cmd_short: str = "fake"
    cpu_percent: float = 0.0
    mem_percent: float = 0.0
    gpu_mem_mb: float = 0.0
    pid: int = 99999
    count: int = 1          # how many identical rows to insert


class FakeMetric(BaseModel):
    username: str
    cpu: float = 0.0
    mem_pct: float = 0.0
    gpu_mem_mb: float = 0.0
    proc_count: int = 1


# ── HTML UI ───────────────────────────────────────────────────────────────────

_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Observer Admin</title>
<style>
  *{box-sizing:border-box}
  body{font-family:monospace;background:#0d0d0d;color:#e0e0e0;margin:0;padding:24px}
  h1{color:#ff6b6b;margin-bottom:4px}
  h2{color:#ffd93d;margin:28px 0 8px}
  .warn{background:#3a1a1a;border-left:4px solid #ff6b6b;padding:10px 16px;margin-bottom:20px;border-radius:4px}
  form{background:#1a1a1a;padding:16px;border-radius:6px;margin-bottom:14px;display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end}
  label{display:flex;flex-direction:column;gap:4px;font-size:.8rem;color:#aaa}
  input,select{background:#0d0d0d;border:1px solid #333;color:#e0e0e0;padding:6px 10px;border-radius:4px;font-family:monospace;min-width:160px}
  button{padding:7px 20px;border:none;border-radius:4px;cursor:pointer;font-family:monospace;font-weight:bold}
  .del{background:#c0392b} .del:hover{background:#e74c3c}
  .fake{background:#27ae60} .fake:hover{background:#2ecc71}
  .info{background:#2980b9} .info:hover{background:#3498db}
  #log{background:#111;border:1px solid #222;border-radius:6px;padding:14px;min-height:80px;white-space:pre-wrap;font-size:.82rem;color:#6fcf97;margin-top:16px}
  .tag{display:inline-block;background:#222;border-radius:3px;padding:1px 6px;font-size:.75rem;color:#888;margin-left:6px}
</style>
</head>
<body>
<h1>⚠ Observer Admin <span class="tag">localhost only</span></h1>
<div class="warn">Changes here directly modify the live SQLite database and Prometheus gauges.<br>Prometheus TSDB deletes take up to 2 min to propagate.</div>
"""

_FOOT = """
<div id="log">// action log will appear here</div>
<script>
async function post(path, body) {
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams(body)});
  const t = await r.text();
  document.getElementById('log').textContent = r.status + ' ' + path + '\\n' + t;
}
async function del_(path) {
  const r = await fetch(path, {method:'DELETE'});
  const t = await r.text();
  document.getElementById('log').textContent = r.status + ' ' + path + '\\n' + t;
}
document.querySelectorAll('form').forEach(f => f.addEventListener('submit', e => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(f));
  const method = f.dataset.method || 'post';
  const path = f.dataset.action;
  if (method === 'delete') del_(path + '?' + new URLSearchParams(data));
  else post(path, data);
}));
</script>
</body></html>"""


@admin.get("/", response_class=HTMLResponse)
def ui(conn: sqlite3.Connection = Depends(get_db)):
    users = [r[0] for r in conn.execute(
        "SELECT DISTINCT username FROM process_snapshots ORDER BY username"
    ).fetchall()]
    proc_names = [r[0] for r in conn.execute(
        "SELECT DISTINCT name FROM process_snapshots ORDER BY name"
    ).fetchall()]
    user_opts = "".join(f'<option value="{u}">{u}</option>' for u in users)
    user_opts_blank = '<option value="">— any —</option>' + user_opts
    proc_opts = "".join(f'<option value="{p}">{p}</option>' for p in proc_names)

    html = _HEAD

    # ── SQLite section ──────────────────────────────────────────────────────
    html += "<h2>SQLite — Delete</h2>"

    html += f"""
    <form data-action="/admin/sqlite/user" data-method="delete">
      <label>User <select name="username">{user_opts}</select></label>
      <button class="del" type="submit">Delete all rows for user</button>
    </form>
    <form data-action="/admin/sqlite/process" data-method="delete">
      <label>Process name (GLOB) <input name="name" list="proc-list" placeholder="python* or exact name"></label>
      <datalist id="proc-list">{chr(10).join(f'<option value="{p}">' for p in proc_names)}</datalist>
      <label>User (optional) <select name="username">{user_opts_blank}</select></label>
      <label>After (ISO UTC, optional) <input name="after" placeholder="2026-04-03T18:00:00+00:00"></label>
      <label>Before (ISO UTC, optional) <input name="before" placeholder="2026-04-03T23:00:00+00:00"></label>
      <button class="del" type="submit">Delete matching process rows</button>
    </form>
    <form data-action="/admin/sqlite/timerange" data-method="delete">
      <label>After (ISO UTC, optional) <input name="after" placeholder="leave blank = no lower bound"></label>
      <label>Before (ISO UTC, required) <input name="before" placeholder="2026-04-03T18:00:00+00:00" required></label>
      <button class="del" type="submit">Delete rows in time window</button>
    </form>
    <form data-action="/admin/sqlite/purge" data-method="delete">
      <button class="del" type="submit" onclick="return confirm('Purge EVERYTHING from SQLite?')">⚠ Purge entire SQLite DB</button>
    </form>"""

    html += "<h2>SQLite — Fake data</h2>"
    html += f"""
    <form data-action="/admin/sqlite/fake">
      <label>User <select name="username">{user_opts}</select></label>
      <label>Process name <input name="name" value="fake_job"></label>
      <label>CPU % <input name="cpu_percent" value="0" type="number" step="0.1"></label>
      <label>MEM % <input name="mem_percent" value="0" type="number" step="0.01"></label>
      <label>GPU MB <input name="gpu_mem_mb" value="0" type="number"></label>
      <label>Rows <input name="count" value="1" type="number" min="1" max="500"></label>
      <button class="fake" type="submit">Insert fake rows</button>
    </form>"""

    # ── Prometheus section ──────────────────────────────────────────────────
    html += "<h2>Prometheus — Override gauges (live)</h2>"
    html += f"""
    <form data-action="/admin/prometheus/fake-metric">
      <label>User <select name="username">{user_opts}</select></label>
      <label>CPU % <input name="cpu" value="0" type="number" step="0.1"></label>
      <label>MEM % <input name="mem_pct" value="0" type="number" step="0.01"></label>
      <label>GPU MB <input name="gpu_mem_mb" value="0" type="number"></label>
      <label>Proc count <input name="proc_count" value="1" type="number"></label>
      <button class="fake" type="submit">Override Prometheus gauges</button>
    </form>"""

    html += "<h2>Prometheus — Delete TSDB series</h2>"
    html += f"""
    <form data-action="/admin/prometheus/delete-series">
      <label>User (label match) <select name="username">{user_opts}</select></label>
      <button class="del" type="submit">Delete Prometheus series for user</button>
    </form>
    <form data-action="/admin/prometheus/delete-all-series">
      <button class="del" type="submit" onclick="return confirm('Delete ALL observer series from Prometheus?')">⚠ Delete ALL observer TSDB series</button>
    </form>"""

    html += _FOOT
    return html


# ── SQLite delete endpoints ───────────────────────────────────────────────────

@admin.delete("/admin/sqlite/user")
def sqlite_delete_user(username: str, conn: sqlite3.Connection = Depends(get_db)):
    count = conn.execute(
        "SELECT COUNT(*) FROM process_snapshots WHERE username = ?", (username,)
    ).fetchone()[0]
    conn.execute("DELETE FROM process_snapshots WHERE username = ?", (username,))
    conn.execute("DELETE FROM abuse_events WHERE username = ?", (username,))
    conn.commit()
    conn.execute("VACUUM")
    conn.commit()
    return {"deleted_process_rows": count, "user": username}


@admin.delete("/admin/sqlite/timerange")
def sqlite_delete_timerange(
    before: str,
    after: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
):
    """
    Delete rows older than `before` (required).
    If `after` is also supplied, deletes only the window between `after` and `before`.
    Both values must be ISO-8601 UTC strings.
    """
    counts = {}
    for table in ("process_snapshots", "gpu_snapshots", "abuse_events"):
        if after:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE ts >= ? AND ts <= ?",  # noqa: S608
                (after, before),
            )
        else:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE ts < ?",  # noqa: S608
                (before,),
            )
        counts[table] = cur.rowcount
    conn.commit()
    conn.execute("VACUUM")
    conn.commit()
    return {"deleted": counts, "after": after, "before": before}


@admin.delete("/admin/sqlite/process")
def sqlite_delete_process(
    name: str,
    username: str | None = None,
    after: str | None = None,
    before: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
):
    """
    Delete process_snapshots rows matching a process name (GLOB pattern, e.g. 'python*').
    Optionally filter by username, and/or restrict to a time window.
    """
    clauses = ["name GLOB ?"]
    params: list = [name]

    if username:
        clauses.append("username = ?")
        params.append(username)
    if after:
        clauses.append("ts >= ?")
        params.append(after)
    if before:
        clauses.append("ts <= ?")
        params.append(before)

    where = " AND ".join(clauses)
    cur = conn.execute(f"DELETE FROM process_snapshots WHERE {where}", params)  # noqa: S608
    conn.commit()
    conn.execute("VACUUM")
    conn.commit()
    return {"deleted": cur.rowcount, "pattern": name, "username": username, "after": after, "before": before}


@admin.delete("/admin/sqlite/purge")
def sqlite_purge(conn: sqlite3.Connection = Depends(get_db)):
    for table in ("process_snapshots", "gpu_snapshots", "abuse_events"):
        conn.execute(f"DELETE FROM {table}")  # noqa: S608
    conn.commit()
    conn.execute("VACUUM")
    conn.commit()
    return {"status": "purged"}


# ── SQLite fake data endpoint ─────────────────────────────────────────────────

@admin.post("/admin/sqlite/fake")
def sqlite_fake(
    username: str = Form(...),
    name: str = Form("fake_job"),
    cpu_percent: float = Form(0.0),
    mem_percent: float = Form(0.0),
    gpu_mem_mb: float = Form(0.0),
    count: int = Form(1),
    conn: sqlite3.Connection = Depends(get_db),
):
    count = max(1, min(count, 500))
    ts = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """INSERT INTO process_snapshots
           (ts, pid, username, name, cmd_short, cpu_percent, mem_percent, gpu_mem_mb)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [(ts, 99999, username, name, name, cpu_percent, mem_percent, gpu_mem_mb)] * count,
    )
    conn.commit()
    return {"inserted": count, "username": username, "ts": ts}


# ── Prometheus gauge override ─────────────────────────────────────────────────

@admin.post("/admin/prometheus/fake-metric")
def prometheus_fake(
    username: str = Form(...),
    cpu: float = Form(0.0),
    mem_pct: float = Form(0.0),
    gpu_mem_mb: float = Form(0.0),
    proc_count: int = Form(1),
):
    USER_CPU.labels(user=username).set(cpu)
    USER_MEM.labels(user=username).set(mem_pct)
    USER_GPU_MEM.labels(user=username).set(gpu_mem_mb)
    USER_PROC_COUNT.labels(user=username).set(proc_count)
    return {"status": "gauges overridden", "username": username}


# ── Prometheus TSDB delete ────────────────────────────────────────────────────

@admin.post("/admin/prometheus/delete-series")
def prometheus_delete_user_series(username: str = Form(...)):
    matchers = [
        f'{{user="{username}"}}',
    ]
    results = {}
    with httpx.Client(timeout=15) as client:
        for m in matchers:
            r = client.post(
                f"{PROMETHEUS_URL}/api/v1/admin/tsdb/delete_series",
                params={"match[]": m},
            )
            results[m] = r.status_code
        # clean tombstones
        client.post(f"{PROMETHEUS_URL}/api/v1/admin/tsdb/clean_tombstones")
    return {"deleted_matchers": results}


@admin.post("/admin/prometheus/delete-all-series")
def prometheus_delete_all_series():
    prefixes = [
        "observer_user_cpu_percent",
        "observer_user_mem_percent",
        "observer_user_gpu_mem_mb",
        "observer_user_proc_count",
        "observer_gpu_util_percent",
        "observer_gpu_mem_used_mb",
        "observer_gpu_mem_total_mb",
        "observer_abuse_events_total",
    ]
    results = {}
    with httpx.Client(timeout=15) as client:
        for metric in prefixes:
            r = client.post(
                f"{PROMETHEUS_URL}/api/v1/admin/tsdb/delete_series",
                params={"match[]": f"{{{metric}!=\"\"}}"},
            )
            results[metric] = r.status_code
        client.post(f"{PROMETHEUS_URL}/api/v1/admin/tsdb/clean_tombstones")
    return {"deleted": results}

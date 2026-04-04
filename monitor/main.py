"""
Main entrypoint
---------------
Starts two concurrent tasks:
  1. Collector loop   — collect → aggregate → store → update Prometheus metrics
  2. FastAPI server   — serves /metrics and JSON query endpoints

Both run in the same process using asyncio + uvicorn.
"""

import asyncio
import logging
import sqlite3
from pathlib import Path

import uvicorn

from monitor import config, storage
from monitor.api import app
from monitor.admin import admin
from monitor.collector import collect
from monitor.aggregator import aggregate_by_user, aggregate_by_session, detect_abuse
from monitor.metrics import update_user_metrics, update_session_metrics, update_gpu_metrics, record_abuse_events

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
log = logging.getLogger("observer.main")


# Override storage DB path from config
storage.DB_PATH = Path(config.DB_PATH)
storage.RETENTION_DAYS = config.RETENTION_DAYS


async def collector_loop(conn: sqlite3.Connection) -> None:
    """Collect → aggregate → persist → expose. Runs forever."""
    log.info(
        "Collector loop started (interval=%ds, abuse_gpu=%.0fMB, abuse_cpu=%.0f%%)",
        config.COLLECT_INTERVAL,
        config.ABUSE_GPU_MEM_MB,
        config.ABUSE_CPU_PERCENT,
    )
    while True:
        try:
            processes, gpu_summary = collect()

            user_agg = aggregate_by_user(processes)
            abuse_events = detect_abuse(
                user_agg,
                gpu_threshold_mb=config.ABUSE_GPU_MEM_MB,
                cpu_threshold=config.ABUSE_CPU_PERCENT,
            )

            # Persist raw snapshot + abuse events
            storage.save_snapshot(conn, processes, gpu_summary, abuse_events)

            # Push aggregated data to Prometheus gauges
            update_user_metrics(user_agg)
            update_session_metrics(aggregate_by_session(processes))
            update_gpu_metrics(gpu_summary)
            record_abuse_events(abuse_events)

            log.info(
                "Snapshot saved: %d processes, %d GPUs, %d abuse events",
                len(processes),
                len(gpu_summary),
                len(abuse_events),
            )
        except Exception:
            log.exception("Collector loop error (will retry next cycle)")

        await asyncio.sleep(config.COLLECT_INTERVAL)


async def main() -> None:
    # Initialise DB
    conn = storage._connect()
    storage.init_db(conn)

    # Attach DB connection to FastAPI app state so endpoints can reach it
    app.state.db_conn = conn

    # Public API server
    server_config = uvicorn.Config(
        app,
        host=config.API_HOST,
        port=config.API_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(server_config)

    # Admin backdoor — host-side port binding restricts to localhost only
    admin_config = uvicorn.Config(
        admin,
        host="0.0.0.0",
        port=config.ADMIN_PORT,
        log_level="warning",
    )
    admin_server = uvicorn.Server(admin_config)

    await asyncio.gather(
        server.serve(),
        admin_server.serve(),
        collector_loop(conn),
    )


def run() -> None:
    """Sync entry point for `observer` CLI script."""
    asyncio.run(main())


if __name__ == "__main__":
    run()

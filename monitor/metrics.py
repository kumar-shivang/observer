"""
Metrics (Prometheus)
--------------------
Defines all Gauges and provides an update function.
Cardinality is strictly controlled: only `user` and `gpu_id` labels here.
Raw per-process data lives in SQLite.
"""

from prometheus_client import Gauge, Counter, Info, REGISTRY
import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-user gauges
# ---------------------------------------------------------------------------
USER_CPU = Gauge(
    "observer_user_cpu_percent",
    "Aggregated CPU % consumed by all processes of this user",
    ["user"],
)
USER_MEM = Gauge(
    "observer_user_mem_percent",
    "Aggregated RAM % consumed by all processes of this user",
    ["user"],
)
USER_GPU_MEM = Gauge(
    "observer_user_gpu_mem_mb",
    "Aggregated GPU memory (MB) consumed by all processes of this user",
    ["user"],
)
USER_PROC_COUNT = Gauge(
    "observer_user_proc_count",
    "Number of running processes owned by this user",
    ["user"],
)

# ---------------------------------------------------------------------------
# Per-GPU gauges
# ---------------------------------------------------------------------------
GPU_UTIL = Gauge(
    "observer_gpu_util_percent",
    "GPU compute utilisation %",
    ["gpu_id"],
)
GPU_MEM_USED = Gauge(
    "observer_gpu_mem_used_mb",
    "GPU memory used (MB)",
    ["gpu_id"],
)
GPU_MEM_TOTAL = Gauge(
    "observer_gpu_mem_total_mb",
    "GPU memory total (MB)",
    ["gpu_id"],
)

# ---------------------------------------------------------------------------
# Abuse counter
# ---------------------------------------------------------------------------
ABUSE_EVENTS = Counter(
    "observer_abuse_events_total",
    "Total abuse threshold breaches detected",
    ["user", "type"],
)

# ---------------------------------------------------------------------------
# Update helpers
# ---------------------------------------------------------------------------


def update_user_metrics(user_agg: dict[str, dict]) -> None:
    for user, vals in user_agg.items():
        USER_CPU.labels(user=user).set(vals["cpu"])
        USER_MEM.labels(user=user).set(vals["mem_pct"])
        USER_GPU_MEM.labels(user=user).set(vals["gpu_mem_mb"])
        USER_PROC_COUNT.labels(user=user).set(vals["proc_count"])


def update_gpu_metrics(gpu_summary: list[dict]) -> None:
    for g in gpu_summary:
        gid = str(g["gpu_id"])
        GPU_UTIL.labels(gpu_id=gid).set(g["util_pct"])
        GPU_MEM_USED.labels(gpu_id=gid).set(g["mem_used_mb"])
        GPU_MEM_TOTAL.labels(gpu_id=gid).set(g["mem_total_mb"])


def record_abuse_events(events: list[dict]) -> None:
    for e in events:
        ABUSE_EVENTS.labels(user=e["user"], type=e["type"]).inc()
        log.warning(
            "ABUSE: user=%s type=%s value=%.1f threshold=%.1f",
            e["user"], e["type"], e["value"], e["threshold"],
        )

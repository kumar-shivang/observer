"""
Aggregator
----------
Collapses raw per-process records into per-user, per-process-name, and
per-session summaries suitable for Prometheus (controlled cardinality).

Prometheus receives AGGREGATED data only.
Raw per-process detail goes to SQLite (see storage.py).
"""

from collections import defaultdict


def aggregate_by_user(processes: list[dict]) -> dict[str, dict]:
    """
    Returns:
        {
          "alice": {"cpu": 42.3, "mem_pct": 5.1, "gpu_mem_mb": 1024, "proc_count": 7},
          ...
        }
    """
    agg: dict[str, dict] = defaultdict(
        lambda: {"cpu": 0.0, "mem_pct": 0.0, "gpu_mem_mb": 0.0, "proc_count": 0}
    )

    for p in processes:
        user = p.get("username") or "unknown"
        agg[user]["cpu"] += p.get("cpu_percent") or 0.0
        agg[user]["mem_pct"] += p.get("memory_percent") or 0.0
        agg[user]["gpu_mem_mb"] += p.get("gpu_mem_mb", 0.0)
        agg[user]["proc_count"] += 1

    return dict(agg)


def aggregate_by_proc_name(processes: list[dict]) -> dict[str, dict]:
    """
    Returns per-process-name aggregates (for "which workload type is costly").
        {
          "python3 train.py": {"cpu": 310.0, "mem_pct": 12.0, "gpu_mem_mb": 8192},
          ...
        }
    """
    agg: dict[str, dict] = defaultdict(
        lambda: {"cpu": 0.0, "mem_pct": 0.0, "gpu_mem_mb": 0.0}
    )

    for p in processes:
        name = p.get("cmd_short") or p.get("name") or "unknown"
        agg[name]["cpu"] += p.get("cpu_percent") or 0.0
        agg[name]["mem_pct"] += p.get("memory_percent") or 0.0
        agg[name]["gpu_mem_mb"] += p.get("gpu_mem_mb", 0.0)

    return dict(agg)


def detect_abuse(
    user_agg: dict[str, dict],
    gpu_threshold_mb: float = 10_000,
    cpu_threshold: float = 200.0,
) -> list[dict]:
    """
    Returns a list of abuse events (dicts) for users exceeding thresholds.
    Callers can log these, alert, or take action.
    """
    events = []
    for user, vals in user_agg.items():
        if vals["gpu_mem_mb"] >= gpu_threshold_mb:
            events.append(
                {
                    "user": user,
                    "type": "gpu_mem",
                    "value": vals["gpu_mem_mb"],
                    "threshold": gpu_threshold_mb,
                }
            )
        if vals["cpu"] >= cpu_threshold:
            events.append(
                {
                    "user": user,
                    "type": "cpu",
                    "value": vals["cpu"],
                    "threshold": cpu_threshold,
                }
            )
    return events


def group_by_session(processes: list[dict]) -> dict[int, list[dict]]:
    """
    Group processes by their OS session ID.

    Session IDs naturally cluster related processes (e.g. a shell and the
    jobs it spawned) without requiring knowledge of container or job IDs.

    Returns:
        {
          1234: [proc_dict, proc_dict, ...],
          5678: [proc_dict],
          ...
        }
    """
    groups: dict[int, list[dict]] = defaultdict(list)
    for p in processes:
        groups[p.get("session_id", -1)].append(p)
    return dict(groups)


def aggregate_by_session(processes: list[dict]) -> dict[int, dict]:
    """
    Aggregate resource usage per OS session.

    Useful for attributing GPU/CPU cost to a "job" rather than a single PID.
    The username is taken from the first process seen in each session.

    Returns:
        {
          1234: {"username": "alice", "cpu": 80.0, "mem_pct": 8.0,
                 "gpu_mem_mb": 6144.0, "proc_count": 2},
          ...
        }
    """
    agg: dict[int, dict] = defaultdict(
        lambda: {
            "username": "unknown",
            "cpu": 0.0,
            "mem_pct": 0.0,
            "gpu_mem_mb": 0.0,
            "proc_count": 0,
        }
    )

    for p in processes:
        session = p.get("session_id", -1)
        agg[session]["cpu"] += p.get("cpu_percent") or 0.0
        agg[session]["mem_pct"] += p.get("memory_percent") or 0.0
        agg[session]["gpu_mem_mb"] += p.get("gpu_mem_mb", 0.0)
        agg[session]["proc_count"] += 1
        if agg[session]["username"] == "unknown":
            agg[session]["username"] = p.get("username") or "unknown"

    return dict(agg)

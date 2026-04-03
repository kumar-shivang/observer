"""
Process Collector
-----------------
Collects per-process CPU, memory, and metadata from the host via psutil.
Runs inside Docker with --pid=host so /proc is the real host /proc.
"""

import psutil


def get_processes() -> list[dict]:
    """
    Return a list of dicts with live process stats.
    Silently skips processes that vanish or deny access mid-iteration.
    """
    data = []
    for p in psutil.process_iter(
        ["pid", "username", "name", "cmdline", "cpu_percent", "memory_percent"]
    ):
        try:
            info = p.info
            # cpu_percent returns 0.0 on first call per process; that's fine —
            # the scheduler loop calls this every cycle so it warms up quickly.
            info["cmd_short"] = _short_cmd(info)
            data.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return data


def _short_cmd(info: dict) -> str:
    """
    Derive a human-readable short command name (<=40 chars).
    Falls back to the process 'name' field when cmdline is empty.
    """
    cmdline = info.get("cmdline") or []
    if cmdline:
        # strip interpreter paths like /usr/bin/python3 → python3
        base = cmdline[0].split("/")[-1]
        # include first meaningful arg if it looks like a script
        if len(cmdline) > 1 and not cmdline[1].startswith("-"):
            arg = cmdline[1].split("/")[-1]
            return f"{base} {arg}"[:40]
        return base[:40]
    return (info.get("name") or "unknown")[:40]

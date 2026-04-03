"""
Process Collector
-----------------
Collects per-process CPU, memory, and metadata from the host via psutil.
Runs inside Docker with --pid=host so /proc is the real host /proc.
"""

import hashlib
import os

import psutil
import pwd


def get_identity(p: psutil.Process) -> dict:
    """
    Build a hybrid identity dict for a process.

    Returns a dict with:
      uid        — real UID of the process owner
      session_id — OS session ID (groups related processes automatically)
      cmd_hash   — 8-char MD5 prefix of the full command line (stable job fingerprint)

    All fields degrade gracefully on permission errors or vanished processes.
    """
    try:
        uid: int = p.uids().real
    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
        uid = -1

    try:
        session_id: int = os.getsid(p.pid)
    except (ProcessLookupError, PermissionError, OSError):
        session_id = -1

    try:
        cmd = " ".join(p.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        cmd = ""

    cmd_hash = hashlib.md5(cmd.encode()).hexdigest()[:8]  # noqa: S324

    return {
        "uid": uid,
        "session_id": session_id,
        "cmd_hash": cmd_hash,
    }


def get_processes() -> list[dict]:
    """
    Return a list of dicts with live process stats.
    Each record includes hybrid identity fields (uid, session_id, cmd_hash)
    so callers can group by session or fingerprint by command.
    Silently skips processes that vanish or deny access mid-iteration.
    """
    data = []
    for p in psutil.process_iter(
        ["pid", "username", "name", "cmdline", "cpu_percent", "memory_percent"]
    ):
        try:
            info = p.info
            info["username"] = _resolve_username(info.get("username"))
            info["cmd_short"] = _short_cmd(info)
            info.update(get_identity(p))
            data.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return data


def _resolve_username(raw: str | None) -> str:
    """
    psutil may return a numeric UID string when the container's passwd doesn't
    map the host UID. Fall back to pwd.getpwuid() which reads the mounted
    /etc/passwd directly.
    """
    if raw is None:
        return "unknown"
    if raw.isdigit():
        try:
            return pwd.getpwuid(int(raw)).pw_name
        except KeyError:
            return raw
    return raw


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

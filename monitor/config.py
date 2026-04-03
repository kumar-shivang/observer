"""
Config
------
All tunables in one place. Override via environment variables.
"""

import os

# How often to collect metrics (seconds)
COLLECT_INTERVAL: int = int(os.getenv("COLLECT_INTERVAL", "60"))

# Abuse detection thresholds
ABUSE_GPU_MEM_MB: float = float(os.getenv("ABUSE_GPU_MEM_MB", "10000"))
ABUSE_CPU_PERCENT: float = float(os.getenv("ABUSE_CPU_PERCENT", "200"))

# API server bind
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8000"))

# SQLite path (override via env for custom volume mounts)
DB_PATH: str = os.getenv("DB_PATH", "/data/metrics.db")

# Retention for SQLite (days)
RETENTION_DAYS: int = int(os.getenv("RETENTION_DAYS", "7"))

# ── Stage 1: install deps with uv ────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Install uv (official installer; no pip needed)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy only the files uv needs to resolve the lock file first (better cache reuse)
COPY pyproject.toml uv.lock .python-version ./

# Install production deps only into /app/.venv using the frozen lock file
RUN uv sync --frozen --no-dev --no-install-project

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim

# Copy uv binary (used to run the entry point cleanly)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install procps for psutil to read /proc correctly inside the container
RUN apt-get update && apt-get install -y --no-install-recommends \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy project metadata (needed so the venv entry point resolves correctly)
COPY pyproject.toml uv.lock .python-version ./

# Copy application source
COPY monitor/ monitor/

# Install the project itself (editable-free, no deps re-downloaded — venv already built)
RUN uv sync --frozen --no-dev

# Data volume mount point for SQLite
RUN mkdir -p /data

EXPOSE 8000

# Run the module directly via the venv Python
CMD ["/app/.venv/bin/python", "-m", "monitor.main"]

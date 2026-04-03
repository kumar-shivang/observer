# Observer

System resource monitor: per-user CPU / RAM / GPU attribution → Prometheus → Grafana.

## Architecture

```
Host processes
    │
    ▼
observer (Python)
    ├── collects via psutil + nvidia-smi
    ├── aggregates by user (controlled cardinality)
    ├── stores raw snapshots in SQLite   ← truth layer
    └── exposes /metrics + JSON API
            │
      ┌─────┴─────┐
  Prometheus    FastAPI
  (7d TSDB)    /top /abuse /gpu/history
      │
   Grafana
```

## Quick start

```bash
# 1. (Optional) set Grafana admin password
echo "GRAFANA_PASSWORD=supersecret" > .env

# 2. Build and start everything
docker compose up -d --build

# 3. Open Grafana
#    http://localhost:3000  (admin / changeme)
#    Dashboard: "Observer"

# 4. Raw API examples
curl http://localhost:8000/health
curl "http://localhost:8000/top?minutes=60"
curl "http://localhost:8000/abuse?hours=24"
curl "http://localhost:8000/gpu/history?hours=6"
curl "http://localhost:8000/processes/latest?user=alice"
```

## Configuration (environment variables)

| Variable           | Default   | Description                             |
|--------------------|-----------|-----------------------------------------|
| `COLLECT_INTERVAL` | `60`      | Seconds between collection cycles       |
| `ABUSE_GPU_MEM_MB` | `10000`   | Alert threshold: GPU memory MB per user |
| `ABUSE_CPU_PERCENT`| `200`     | Alert threshold: CPU % per user         |
| `RETENTION_DAYS`   | `7`       | SQLite row retention                    |
| `GRAFANA_PASSWORD` | `changeme`| Grafana admin password (`.env` file)    |

## Project layout

```
observer/
├── monitor/
│   ├── __init__.py
│   ├── main.py        ← entrypoint: asyncio loop + uvicorn
│   ├── collector.py   ← orchestrates process + GPU collection
│   ├── process.py     ← psutil wrapper
│   ├── gpu.py         ← nvidia-smi wrapper (graceful no-GPU fallback)
│   ├── aggregator.py  ← per-user aggregation + abuse detection
│   ├── storage.py     ← SQLite (raw history + query helpers)
│   ├── metrics.py     ← Prometheus gauges/counters
│   ├── api.py         ← FastAPI app
│   └── config.py      ← env-var config
├── prometheus/
│   └── prometheus.yml
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/prometheus.yml
│   │   └── dashboards/observer.yml
│   └── dashboards/observer.json
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Why this design

- **Aggregation in Python, not Prometheus.** Raw per-PID metrics would create unbounded cardinality and kill Prometheus. Python aggregates first; only `user` and `gpu_id` labels reach Prometheus.
- **SQLite is the truth layer.** Prometheus holds 7 days of aggregated time series. The full per-process detail (PID, full command, timestamps) is in SQLite and queryable via the FastAPI endpoints.
- **Graceful GPU fallback.** If `nvidia-smi` is unavailable the service runs normally; GPU metrics are simply zero.

## Extending

### Abuse alerting (Alertmanager)
Add to `prometheus.yml`:
```yaml
rule_files:
  - /etc/prometheus/alerts.yml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]
```

Example rule:
```yaml
groups:
  - name: observer
    rules:
      - alert: HighGPUUser
        expr: observer_user_gpu_mem_mb > 10000
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "{{ $labels.user }} has held >10 GB GPU for 30 min"
```

### Cost estimation
In `aggregator.py`, add a cost function after `aggregate_by_user`:
```python
GPU_HOUR_COST_INR = 12.0  # ₹ per GPU-hour

def estimate_cost(user_agg, interval_seconds):
    for user, vals in user_agg.items():
        gpu_hours = (vals["gpu_mem_mb"] / 1000) * (interval_seconds / 3600)
        vals["cost_inr"] = gpu_hours * GPU_HOUR_COST_INR
```

### Kill switch
```python
import psutil, os, signal

def kill_runaway(processes, user, max_gpu_mb=20000):
    for p in processes:
        if p["username"] == user and p["gpu_mem_mb"] > max_gpu_mb:
            os.kill(p["pid"], signal.SIGTERM)
```

"""
GPU Collector
-------------
Queries nvidia-smi for per-process GPU memory usage and per-GPU utilisation.

Falls back gracefully when:
  - nvidia-smi is not available
  - No GPUs are present
  - Individual GPU query errors
"""

import subprocess
import logging

log = logging.getLogger(__name__)


def get_gpu_process_map() -> dict[int, float]:
    """
    Returns {pid: gpu_mem_MB} for all processes currently using a GPU.
    Returns {} when nvidia-smi is unavailable or no compute apps are running.
    """
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_memory",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).decode()
    except FileNotFoundError:
        log.debug("nvidia-smi not found — GPU metrics disabled")
        return {}
    except subprocess.TimeoutExpired:
        log.warning("nvidia-smi timed out querying compute apps")
        return {}
    except subprocess.CalledProcessError as e:
        log.warning("nvidia-smi exited with code %d", e.returncode)
        return {}

    gpu_map: dict[int, float] = {}
    for line in out.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0].strip())
            mem = float(parts[1].strip())
            # A single process can appear per-GPU; sum across GPUs.
            gpu_map[pid] = gpu_map.get(pid, 0.0) + mem
        except ValueError:
            continue

    return gpu_map


def get_gpu_summary() -> list[dict]:
    """
    Returns per-GPU utilisation stats:
      [{"gpu_id": 0, "util_pct": 72.0, "mem_used_mb": 4096, "mem_total_mb": 24576}, ...]

    Returns [] when nvidia-smi is unavailable.
    """
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).decode()
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return []

    gpus = []
    for line in out.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            continue
        try:
            gpus.append(
                {
                    "gpu_id": int(parts[0]),
                    "util_pct": float(parts[1]),
                    "mem_used_mb": float(parts[2]),
                    "mem_total_mb": float(parts[3]),
                }
            )
        except ValueError:
            continue

    return gpus

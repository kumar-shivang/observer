"""
Collector
---------
Orchestrates process + GPU collection and merges them into a unified record.
"""

from monitor.process import get_processes
from monitor.gpu import get_gpu_process_map, get_gpu_summary


def collect() -> tuple[list[dict], list[dict]]:
    """
    Returns:
        processes   — list of per-process dicts with gpu_mem_mb injected
        gpu_summary — list of per-GPU utilisation dicts
    """
    processes = get_processes()
    gpu_map = get_gpu_process_map()
    gpu_summary = get_gpu_summary()

    for p in processes:
        p["gpu_mem_mb"] = gpu_map.get(p["pid"], 0.0)

    return processes, gpu_summary

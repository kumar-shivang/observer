"""
Tests for monitor.collector — integration of process + gpu + merge.
"""
from unittest.mock import patch
from monitor.collector import collect


FAKE_PROCS = [
    {
        "pid": 100, "username": "alice", "name": "python3",
        "cmdline": ["python3", "train.py"], "cpu_percent": 60.0,
        "memory_percent": 4.0, "cmd_short": "python3 train.py",
    }
]

FAKE_GPU_MAP = {100: 8192.0}
FAKE_GPU_SUMMARY = [
    {"gpu_id": 0, "util_pct": 90.0, "mem_used_mb": 8192.0, "mem_total_mb": 24576.0}
]


class TestCollect:
    def test_injects_gpu_mem_into_procs(self):
        with (
            patch("monitor.collector.get_processes", return_value=FAKE_PROCS),
            patch("monitor.collector.get_gpu_process_map", return_value=FAKE_GPU_MAP),
            patch("monitor.collector.get_gpu_summary", return_value=FAKE_GPU_SUMMARY),
        ):
            procs, gpus = collect()

        assert procs[0]["gpu_mem_mb"] == 8192.0
        assert gpus[0]["util_pct"] == 90.0

    def test_zero_gpu_for_cpu_only_process(self):
        with (
            patch("monitor.collector.get_processes", return_value=FAKE_PROCS),
            patch("monitor.collector.get_gpu_process_map", return_value={}),
            patch("monitor.collector.get_gpu_summary", return_value=[]),
        ):
            procs, gpus = collect()

        assert procs[0]["gpu_mem_mb"] == 0.0
        assert gpus == []

    def test_returns_correct_types(self):
        with (
            patch("monitor.collector.get_processes", return_value=FAKE_PROCS),
            patch("monitor.collector.get_gpu_process_map", return_value={}),
            patch("monitor.collector.get_gpu_summary", return_value=[]),
        ):
            procs, gpus = collect()

        assert isinstance(procs, list)
        assert isinstance(gpus, list)

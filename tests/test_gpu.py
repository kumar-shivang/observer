"""
Tests for monitor.gpu
"""
from unittest.mock import patch
from monitor.gpu import get_gpu_process_map, get_gpu_summary
import subprocess


GPU_PROCESS_OUTPUT = b"1234, 2048\n5678, 4096\n"
GPU_SUMMARY_OUTPUT = b"0, 72, 8192, 24576\n1, 45, 4096, 24576\n"


class TestGetGpuProcessMap:
    def test_parses_output_correctly(self):
        with patch("monitor.gpu.subprocess.check_output", return_value=GPU_PROCESS_OUTPUT):
            result = get_gpu_process_map()
        assert result == {1234: 2048.0, 5678: 4096.0}

    def test_sums_across_gpus_for_same_pid(self):
        output = b"1234, 2048\n1234, 1024\n"
        with patch("monitor.gpu.subprocess.check_output", return_value=output):
            result = get_gpu_process_map()
        assert result[1234] == 3072.0

    def test_returns_empty_when_no_nvidia_smi(self):
        with patch("monitor.gpu.subprocess.check_output",
                   side_effect=FileNotFoundError):
            result = get_gpu_process_map()
        assert result == {}

    def test_returns_empty_on_timeout(self):
        with patch("monitor.gpu.subprocess.check_output",
                   side_effect=subprocess.TimeoutExpired("nvidia-smi", 10)):
            result = get_gpu_process_map()
        assert result == {}

    def test_returns_empty_on_nonzero_exit(self):
        with patch("monitor.gpu.subprocess.check_output",
                   side_effect=subprocess.CalledProcessError(1, "nvidia-smi")):
            result = get_gpu_process_map()
        assert result == {}

    def test_skips_malformed_lines(self):
        output = b"1234, 2048\nbad line\n5678, 4096\n"
        with patch("monitor.gpu.subprocess.check_output", return_value=output):
            result = get_gpu_process_map()
        assert 1234 in result
        assert 5678 in result

    def test_empty_output_returns_empty_dict(self):
        with patch("monitor.gpu.subprocess.check_output", return_value=b""):
            result = get_gpu_process_map()
        assert result == {}


class TestGetGpuSummary:
    def test_parses_output_correctly(self):
        with patch("monitor.gpu.subprocess.check_output", return_value=GPU_SUMMARY_OUTPUT):
            result = get_gpu_summary()
        assert len(result) == 2
        assert result[0] == {
            "gpu_id": 0,
            "util_pct": 72.0,
            "mem_used_mb": 8192.0,
            "mem_total_mb": 24576.0,
        }
        assert result[1]["gpu_id"] == 1

    def test_returns_empty_when_no_nvidia_smi(self):
        with patch("monitor.gpu.subprocess.check_output",
                   side_effect=FileNotFoundError):
            result = get_gpu_summary()
        assert result == []

"""
Tests for monitor.aggregator
"""
from monitor.aggregator import aggregate_by_user, aggregate_by_proc_name, detect_abuse

PROCESSES = [
    {"pid": 1, "username": "alice", "name": "python3", "cmd_short": "python3 train.py",
     "cpu_percent": 50.0, "memory_percent": 5.0, "gpu_mem_mb": 4096.0},
    {"pid": 2, "username": "alice", "name": "python3", "cmd_short": "python3 infer.py",
     "cpu_percent": 30.0, "memory_percent": 3.0, "gpu_mem_mb": 2048.0},
    {"pid": 3, "username": "bob",   "name": "bash",    "cmd_short": "bash",
     "cpu_percent": 10.0, "memory_percent": 0.5, "gpu_mem_mb": 0.0},
]


class TestAggregateByUser:
    def test_sums_cpu_per_user(self):
        agg = aggregate_by_user(PROCESSES)
        assert agg["alice"]["cpu"] == 80.0
        assert agg["bob"]["cpu"] == 10.0

    def test_sums_mem_per_user(self):
        agg = aggregate_by_user(PROCESSES)
        assert agg["alice"]["mem_pct"] == 8.0

    def test_sums_gpu_per_user(self):
        agg = aggregate_by_user(PROCESSES)
        assert agg["alice"]["gpu_mem_mb"] == 6144.0
        assert agg["bob"]["gpu_mem_mb"] == 0.0

    def test_counts_processes_per_user(self):
        agg = aggregate_by_user(PROCESSES)
        assert agg["alice"]["proc_count"] == 2
        assert agg["bob"]["proc_count"] == 1

    def test_handles_none_username(self):
        procs = [{"pid": 99, "username": None, "cpu_percent": 5.0,
                  "memory_percent": 1.0, "gpu_mem_mb": 0.0}]
        agg = aggregate_by_user(procs)
        assert "unknown" in agg

    def test_handles_none_cpu(self):
        procs = [{"pid": 99, "username": "alice", "cpu_percent": None,
                  "memory_percent": 1.0, "gpu_mem_mb": 0.0}]
        agg = aggregate_by_user(procs)
        assert agg["alice"]["cpu"] == 0.0

    def test_empty_returns_empty(self):
        assert aggregate_by_user([]) == {}


class TestAggregateByProcName:
    def test_sums_by_cmd_short(self):
        agg = aggregate_by_proc_name(PROCESSES)
        assert "python3 train.py" in agg
        assert "python3 infer.py" in agg
        assert agg["python3 train.py"]["cpu"] == 50.0

    def test_empty_returns_empty(self):
        assert aggregate_by_proc_name([]) == {}


class TestDetectAbuse:
    def test_flags_high_gpu(self):
        user_agg = {"alice": {"cpu": 10.0, "mem_pct": 1.0, "gpu_mem_mb": 15000.0, "proc_count": 1}}
        events = detect_abuse(user_agg, gpu_threshold_mb=10000, cpu_threshold=500)
        assert any(e["type"] == "gpu_mem" and e["user"] == "alice" for e in events)

    def test_flags_high_cpu(self):
        user_agg = {"alice": {"cpu": 300.0, "mem_pct": 1.0, "gpu_mem_mb": 0.0, "proc_count": 5}}
        events = detect_abuse(user_agg, gpu_threshold_mb=10000, cpu_threshold=200)
        assert any(e["type"] == "cpu" and e["user"] == "alice" for e in events)

    def test_no_abuse_below_thresholds(self):
        user_agg = {"alice": {"cpu": 10.0, "mem_pct": 1.0, "gpu_mem_mb": 100.0, "proc_count": 1}}
        events = detect_abuse(user_agg)
        assert events == []

    def test_returns_all_breaches_for_user(self):
        user_agg = {"alice": {"cpu": 999.0, "mem_pct": 1.0, "gpu_mem_mb": 99999.0, "proc_count": 1}}
        events = detect_abuse(user_agg, gpu_threshold_mb=1000, cpu_threshold=100)
        types = {e["type"] for e in events}
        assert "gpu_mem" in types
        assert "cpu" in types

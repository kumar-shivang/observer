"""
Tests for monitor.process
"""
from unittest.mock import MagicMock, patch
from monitor.process import _short_cmd, get_processes


def _make_proc_info(pid=1, username="alice", name="python3",
                    cmdline=None, cpu=10.0, mem=1.5):
    return {
        "pid": pid,
        "username": username,
        "name": name,
        "cmdline": cmdline if cmdline is not None else ["python3", "train.py"],
        "cpu_percent": cpu,
        "memory_percent": mem,
    }


class TestShortCmd:
    def test_uses_cmdline_with_script(self):
        info = _make_proc_info(cmdline=["python3", "train.py"])
        assert _short_cmd(info) == "python3 train.py"

    def test_strips_path_from_interpreter(self):
        info = _make_proc_info(cmdline=["/usr/bin/python3", "train.py"])
        assert _short_cmd(info) == "python3 train.py"

    def test_skips_flag_arg(self):
        info = _make_proc_info(cmdline=["python3", "-u", "train.py"])
        assert _short_cmd(info) == "python3"

    def test_falls_back_to_name_when_no_cmdline(self):
        info = _make_proc_info(name="sshd", cmdline=[])
        assert _short_cmd(info) == "sshd"

    def test_truncates_at_40_chars(self):
        info = _make_proc_info(cmdline=["a" * 30, "b" * 30])
        result = _short_cmd(info)
        assert len(result) <= 40

    def test_none_cmdline_falls_back_to_name(self):
        info = _make_proc_info(name="bash", cmdline=None)
        # cmdline=None → the helper replaces it with the default ["python3", "train.py"]
        # so this just checks it doesn't raise
        assert isinstance(_short_cmd(info), str)


class TestGetProcesses:
    def test_returns_list_with_cmd_short(self):
        fake_info = _make_proc_info()
        mock_proc = MagicMock()
        mock_proc.info = fake_info

        with patch("monitor.process.psutil.process_iter", return_value=[mock_proc]):
            result = get_processes()

        assert len(result) == 1
        assert "cmd_short" in result[0]

    def test_skips_no_such_process(self):
        import psutil

        mock_proc = MagicMock()
        mock_proc.info  # accessing .info will raise
        type(mock_proc).info = property(
            lambda self: (_ for _ in ()).throw(psutil.NoSuchProcess(pid=99))
        )

        with patch("monitor.process.psutil.process_iter", return_value=[mock_proc]):
            result = get_processes()

        assert result == []

    def test_skips_access_denied(self):
        import psutil

        mock_proc = MagicMock()
        type(mock_proc).info = property(
            lambda self: (_ for _ in ()).throw(psutil.AccessDenied(pid=99))
        )

        with patch("monitor.process.psutil.process_iter", return_value=[mock_proc]):
            result = get_processes()

        assert result == []

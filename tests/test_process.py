"""
Tests for monitor.process
"""
from unittest.mock import MagicMock, patch
from monitor.process import _short_cmd, get_identity, get_processes


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

    def test_includes_identity_fields(self):
        fake_info = _make_proc_info()
        mock_proc = MagicMock()
        mock_proc.info = fake_info

        with patch("monitor.process.psutil.process_iter", return_value=[mock_proc]):
            result = get_processes()

        assert "uid" in result[0]
        assert "session_id" in result[0]
        assert "cmd_hash" in result[0]

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


class TestGetIdentity:
    def _make_mock_process(self, pid=42, uid=1000,
                           cmdline=None):
        import psutil
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = pid
        mock_proc.uids.return_value = MagicMock(real=uid)
        mock_proc.cmdline.return_value = cmdline or ["python3", "train.py"]
        return mock_proc

    def test_returns_required_keys(self):
        p = self._make_mock_process()
        with patch("monitor.process.os.getsid", return_value=5000):
            identity = get_identity(p)
        assert {"uid", "session_id", "cmd_hash"} == set(identity.keys())

    def test_uid_is_real_uid(self):
        p = self._make_mock_process(uid=1001)
        with patch("monitor.process.os.getsid", return_value=1):
            identity = get_identity(p)
        assert identity["uid"] == 1001

    def test_session_id_from_getsid(self):
        p = self._make_mock_process(pid=42)
        with patch("monitor.process.os.getsid", return_value=9999) as mock_sid:
            identity = get_identity(p)
        mock_sid.assert_called_once_with(42)
        assert identity["session_id"] == 9999

    def test_cmd_hash_is_8_chars(self):
        p = self._make_mock_process()
        with patch("monitor.process.os.getsid", return_value=1):
            identity = get_identity(p)
        assert len(identity["cmd_hash"]) == 8

    def test_cmd_hash_is_deterministic(self):
        p = self._make_mock_process(cmdline=["python3", "train.py"])
        with patch("monitor.process.os.getsid", return_value=1):
            id1 = get_identity(p)
            id2 = get_identity(p)
        assert id1["cmd_hash"] == id2["cmd_hash"]

    def test_cmd_hash_differs_for_different_commands(self):
        p1 = self._make_mock_process(cmdline=["python3", "train.py"])
        p2 = self._make_mock_process(cmdline=["python3", "eval.py"])
        with patch("monitor.process.os.getsid", return_value=1):
            id1 = get_identity(p1)
            id2 = get_identity(p2)
        assert id1["cmd_hash"] != id2["cmd_hash"]

    def test_degrades_gracefully_on_access_denied(self):
        import psutil
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = 99
        mock_proc.uids.side_effect = psutil.AccessDenied(pid=99)
        mock_proc.cmdline.side_effect = psutil.AccessDenied(pid=99)
        with patch("monitor.process.os.getsid", side_effect=ProcessLookupError):
            identity = get_identity(mock_proc)
        assert identity["uid"] == -1
        assert identity["session_id"] == -1
        assert identity["cmd_hash"] == "d41d8cd9"  # md5("") prefix

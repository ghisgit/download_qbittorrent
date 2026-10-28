from __future__ import annotations

import sys
from datetime import datetime

import pytest

from crawler.log import capture_logs, new_log_path


class TestNewLogPath:
    def test_timestamped_name(self, tmp_path):
        path = new_log_path(tmp_path, now=datetime(2026, 10, 28, 19, 25, 27))
        assert path.name == "crawler_20261028_192527.log"
        assert path.parent == tmp_path
        assert tmp_path.is_dir()

    def test_same_second_collision_adds_suffix(self, tmp_path):
        now = datetime(2026, 10, 28, 19, 25, 27)
        first = new_log_path(tmp_path, now=now)
        first.write_text("first", encoding="utf-8")
        second = new_log_path(tmp_path, now=now)
        assert second.name == "crawler_20261028_192527_1.log"

    def test_creates_nested_directory(self, tmp_path):
        directory = tmp_path / "a" / "b"
        path = new_log_path(directory, now=datetime(2026, 10, 28, 19, 25, 27))
        assert directory.is_dir()
        assert path.parent == directory


class TestCaptureLogs:
    def test_tees_stdout_and_stderr(self, tmp_path, capsys):
        with capture_logs(True, tmp_path) as path:
            assert path is not None
            print("hello stdout")
            print("hello stderr", file=sys.stderr)

        text = path.read_text(encoding="utf-8")
        assert "hello stdout" in text
        assert "hello stderr" in text

        captured = capsys.readouterr()
        assert "hello stdout" in captured.out
        assert "hello stderr" in captured.err

    def test_restores_streams_after_context(self, tmp_path):
        stdout = sys.stdout
        stderr = sys.stderr
        with capture_logs(True, tmp_path):
            assert sys.stdout is not stdout
            assert sys.stderr is not stderr
        assert sys.stdout is stdout
        assert sys.stderr is stderr

    def test_restores_streams_after_exception(self, tmp_path):
        stdout = sys.stdout
        with pytest.raises(RuntimeError, match="boom"), capture_logs(True, tmp_path):
            raise RuntimeError("boom")
        assert sys.stdout is stdout

    def test_disabled_does_not_create_directory(self, tmp_path):
        directory = tmp_path / "logs"
        with capture_logs(False, directory) as path:
            assert path is None
            print("still works")
        assert not directory.exists()

    def test_invalid_directory_warns_and_continues(self, tmp_path, capsys):
        not_a_dir = tmp_path / "not-a-dir"
        not_a_dir.write_text("x", encoding="utf-8")

        with capture_logs(True, not_a_dir) as path:
            assert path is None
            print("run continues")

        captured = capsys.readouterr()
        assert "无法创建日志文件" in captured.err
        assert "run continues" in captured.out

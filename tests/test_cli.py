from __future__ import annotations

import sys

import pytest

import crawler.cli as cli
from crawler.config import CrawlerConfig


def _clear_log_env(monkeypatch) -> None:
    monkeypatch.delenv("CRAWLER_LOG_SAVE", raising=False)
    monkeypatch.delenv("CRAWLER_LOG_DIR", raising=False)


def _fake_config() -> CrawlerConfig:
    return CrawlerConfig(name="test")


async def _fake_pipeline(config) -> list[str]:
    return []


class TestResolveLogOptions:
    def test_defaults(self, monkeypatch):
        _clear_log_env(monkeypatch)
        assert cli._resolve_log_options(False, None) == (False, "logs")

    def test_env_flag_enables(self, monkeypatch):
        _clear_log_env(monkeypatch)
        monkeypatch.setenv("CRAWLER_LOG_SAVE", "yes")
        assert cli._resolve_log_options(False, None) == (True, "logs")

    def test_env_dir_enables(self, monkeypatch):
        _clear_log_env(monkeypatch)
        monkeypatch.setenv("CRAWLER_LOG_DIR", "/tmp/crawler-logs")
        assert cli._resolve_log_options(False, None) == (True, "/tmp/crawler-logs")

    def test_cli_dir_overrides_env_dir(self, monkeypatch):
        _clear_log_env(monkeypatch)
        monkeypatch.setenv("CRAWLER_LOG_DIR", "/tmp/from-env")
        assert cli._resolve_log_options(False, "/tmp/from-cli") == (True, "/tmp/from-cli")

    def test_cli_flag_with_env_dir(self, monkeypatch):
        _clear_log_env(monkeypatch)
        monkeypatch.setenv("CRAWLER_LOG_DIR", "/tmp/from-env")
        assert cli._resolve_log_options(True, None) == (True, "/tmp/from-env")


class TestMainLogging:
    def test_writes_timestamped_log(self, monkeypatch, tmp_path, capsys):
        _clear_log_env(monkeypatch)
        monkeypatch.setattr(cli, "load_config", lambda path: _fake_config())
        monkeypatch.setattr(cli, "run_pipeline", _fake_pipeline)
        monkeypatch.setattr(
            sys,
            "argv",
            ["crawler", "--log-save", "--log-dir", str(tmp_path), "dummy.yaml"],
        )

        cli.main()

        files = list(tmp_path.glob("crawler_*.log"))
        assert len(files) == 1
        text = files[0].read_text(encoding="utf-8")
        assert "[log] 保存到:" in text
        assert "爬虫: test" in text
        assert "爬虫: test" in capsys.readouterr().out

    def test_without_logging_creates_no_file(self, monkeypatch, tmp_path):
        _clear_log_env(monkeypatch)
        monkeypatch.setattr(cli, "load_config", lambda path: _fake_config())
        monkeypatch.setattr(cli, "run_pipeline", _fake_pipeline)
        monkeypatch.setattr(sys, "argv", ["crawler", "dummy.yaml"])
        monkeypatch.chdir(tmp_path)

        cli.main()

        assert not list(tmp_path.glob("crawler_*.log"))
        assert not (tmp_path / "logs").exists()

    def test_traceback_is_written_to_log(self, monkeypatch, tmp_path):
        _clear_log_env(monkeypatch)

        def fail_load(path):
            raise RuntimeError("boom")

        monkeypatch.setattr(cli, "load_config", fail_load)
        monkeypatch.setattr(
            sys,
            "argv",
            ["crawler", "--log-dir", str(tmp_path), "dummy.yaml"],
        )

        with pytest.raises(SystemExit) as exc_info:
            cli.main()

        assert exc_info.value.code == 1
        files = list(tmp_path.glob("crawler_*.log"))
        assert len(files) == 1
        text = files[0].read_text(encoding="utf-8")
        assert "Traceback" in text
        assert "RuntimeError: boom" in text

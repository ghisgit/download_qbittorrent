from __future__ import annotations

import argparse
import asyncio
import os
import traceback

from .config import load_config
from .log import capture_logs
from .pipeline import run_pipeline


def _env_flag(name: str) -> bool:
    v = os.environ.get(name, "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _resolve_log_options(log_save: bool, log_dir: str | None) -> tuple[bool, str]:
    env_dir = os.environ.get("CRAWLER_LOG_DIR", "").strip()
    directory = log_dir or env_dir or "logs"
    enabled = log_save or _env_flag("CRAWLER_LOG_SAVE") or bool(log_dir) or bool(env_dir)
    return enabled, directory


def _run(config_path: str) -> None:
    config = load_config(config_path)
    print(f"爬虫: {config.name}  (分类: {config.qb.category})")
    asyncio.run(run_pipeline(config))


def main() -> None:
    parser = argparse.ArgumentParser(description="通用爬虫引擎")
    parser.add_argument("config", help="YAML 配置文件路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    parser.add_argument("--debug-save", action="store_true", help="保存下载的 HTML 到文件用于调试")
    parser.add_argument("--log-save", action="store_true", help="保存运行日志到带时间戳的文件")
    parser.add_argument(
        "--log-dir",
        metavar="DIR",
        help="日志目录 (默认 logs; 设置后自动开启日志)",
    )
    args = parser.parse_args()

    import crawler

    crawler.settings.verbose = args.verbose or _env_flag("CRAWLER_VERBOSE")
    crawler.settings.debug_save = args.debug_save or _env_flag("CRAWLER_DEBUG_SAVE")

    log_enabled, log_dir = _resolve_log_options(args.log_save, args.log_dir)
    with capture_logs(log_enabled, log_dir) as log_path:
        if log_path is not None:
            print(f"[log] 保存到: {log_path.resolve()}")
        try:
            _run(args.config)
        except Exception:
            traceback.print_exc()
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()

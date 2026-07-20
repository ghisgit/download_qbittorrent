from __future__ import annotations

import argparse
import asyncio

from .config import load_config
from .pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="通用爬虫引擎")
    parser.add_argument("config", help="YAML 配置文件路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    parser.add_argument("--debug-save", action="store_true", help="保存下载的 HTML 到文件用于调试")
    args = parser.parse_args()

    import crawler

    crawler.settings.verbose = args.verbose
    crawler.settings.debug_save = args.debug_save

    config = load_config(args.config)
    print(f"爬虫: {config.name}  (分类: {config.qb.category})")
    asyncio.run(run_pipeline(config))


if __name__ == "__main__":
    main()

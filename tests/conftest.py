from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crawler.config import CrawlerConfig, load_config

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
FIXTURES.mkdir(exist_ok=True)


def _write_yaml(name: str, data: dict) -> Path:
    path = FIXTURES / name
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


@pytest.fixture
def minimal_config() -> CrawlerConfig:
    path = _write_yaml(
        "minimal.yaml",
        {
            "name": "test",
            "stages": [
                {
                    "id": "seed",
                    "urls": ["https://example.com"],
                    "fetcher": "httpx",
                }
            ],
        },
    )
    return load_config(path)

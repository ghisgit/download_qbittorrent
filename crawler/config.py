from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any, Literal

import yaml


@dataclass
class QBConfig:
    url: str = ""
    user: str = ""
    password: str = ""
    category: str = ""
    timeout: int = 30
    sequential_download: bool = True
    first_last_piece_prio: bool = True
    add_to_top_of_queue: bool = True


@dataclass
class BrowserConfig:
    headless: bool = True
    args: list[str] = dc_field(default_factory=lambda: ["--blink-settings=imagesEnabled=false"])


@dataclass
class RetryConfig:
    max_retries: int = 10
    retryable_codes: set[int] = dc_field(default_factory=lambda: {429, 502, 503, 504})


@dataclass
class FieldExtract:
    selector: str = ""
    attribute: str = ""
    multiple: bool = False  # True ⇒ returns a list of values
    type: str = ""  # "int" to cast


@dataclass
class ExtractConfig:
    type: Literal["regex", "css", "xpath"]
    selector: str = ""  # top-level selector (parent element for css multi-field)
    pattern: str = ""  # regex pattern
    flags: list[str] = dc_field(default_factory=list)
    attribute: str = ""  # simple-mode: attribute to extract
    multiple: bool = True
    fields: dict[str, FieldExtract] = dc_field(default_factory=dict)  # multi-field mode


# sentinel for unset numeric filter fields
_UNSET = float("-inf")


@dataclass
class FilterCondition:
    """A primitive condition: check one field."""

    field: str = "text"
    contains: str = ""
    not_contains: str = ""
    eq: str = ""
    not_in: list[str] = dc_field(default_factory=list)
    gt: float = _UNSET
    gte: float = _UNSET
    lt: float = _UNSET
    lte: float = _UNSET


@dataclass
class FilterRule:
    """A filter rule — either a primitive condition, or a logical group."""

    condition: FilterCondition | None = None
    any_of: list[FilterRule] = dc_field(default_factory=list)
    all_of: list[FilterRule] = dc_field(default_factory=list)


@dataclass
class StageConfig:
    id: str
    input: str | list[str] | None = None
    urls: list[str] = dc_field(default_factory=list)
    url_pattern: str = ""
    url_range: dict[str, Any] | None = None
    fetcher: Literal["playwright", "httpx"] = "httpx"
    headers: dict[str, str] = dc_field(default_factory=dict)
    extracts: list[ExtractConfig] = dc_field(default_factory=list)
    retry: RetryConfig | None = None
    filter: list[FilterRule] = dc_field(default_factory=list)
    security: bool = False
    security_selector: str = ""
    resources: list[str] = dc_field(default_factory=list)
    qb_send: bool = False
    category: str = ""
    concurrency: int = 0
    delay: float = 0.0
    dedup_by: str | None = None


@dataclass
class CrawlerConfig:
    name: str
    browser: BrowserConfig = dc_field(default_factory=BrowserConfig)
    qb: QBConfig = dc_field(default_factory=QBConfig)
    stages: list[StageConfig] = dc_field(default_factory=list)


# ── helpers ─────────────────────────────────────────────────────────


def _parse_fields(raw: dict[str, Any] | None) -> dict[str, FieldExtract]:
    fields = {}
    for name, f_raw in (raw or {}).items():
        fields[name] = FieldExtract(
            selector=f_raw.get("selector", ""),
            attribute=f_raw.get("attribute", ""),
            multiple=f_raw.get("multiple", False),
            type=f_raw.get("type", ""),
        )
    return fields


def _parse_condition(raw: Any) -> FilterCondition | None:
    if not isinstance(raw, dict):
        print(f"  [config] 警告: filter 条件应为字典, 收到 {type(raw).__name__}: {raw}")
        return None

    def _get(v: Any) -> float:
        return _UNSET if v is None else v

    cond = FilterCondition(
        field=raw.get("field", "text"),
        contains=raw.get("contains", ""),
        not_contains=raw.get("not_contains", ""),
        eq=raw.get("eq", ""),
        not_in=raw.get("not_in", []),
        gt=_get(raw.get("gt")),
        gte=_get(raw.get("gte")),
        lt=_get(raw.get("lt")),
        lte=_get(raw.get("lte")),
    )
    if not any(
        [
            cond.contains,
            cond.not_contains,
            cond.eq,
            cond.not_in,
            cond.gt is not _UNSET,
            cond.gte is not _UNSET,
            cond.lt is not _UNSET,
            cond.lte is not _UNSET,
        ]
    ):
        print(f"  [config] 警告: filter 条件 '{cond.field}' 未设置任何操作符, 将被忽略")
        return None
    return cond


def _parse_filter_rules(raw: list[Any]) -> list[FilterRule]:
    rules = []
    for r in raw or []:
        if "any_of" in r:
            rules.append(FilterRule(any_of=_parse_filter_rules(r["any_of"])))
        elif "all_of" in r:
            rules.append(FilterRule(all_of=_parse_filter_rules(r["all_of"])))
        else:
            cond = _parse_condition(r)
            if cond is not None:
                rules.append(FilterRule(condition=cond))
    return rules


def load_config(path: str | Path) -> CrawlerConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    qb_raw = raw.get("qb", {})
    if not qb_raw:
        print("[config] 警告: qb 配置未设置, 请配置 qb.url / qb.user / qb.password")
    qb = QBConfig(
        url=qb_raw.get("url", ""),
        user=qb_raw.get("user", ""),
        password=qb_raw.get("password", ""),
        category=qb_raw.get("category", ""),
        timeout=qb_raw.get("timeout", 30),
        sequential_download=qb_raw.get("sequential_download", True),
        first_last_piece_prio=qb_raw.get("first_last_piece_prio", True),
        add_to_top_of_queue=qb_raw.get("add_to_top_of_queue", True),
    )

    browser_raw = raw.get("browser", {})
    browser = BrowserConfig(
        headless=browser_raw.get("headless", True),
        args=browser_raw.get("args", ["--blink-settings=imagesEnabled=false"]),
    )

    stages = []
    for s in raw.get("stages", []):
        extract_raw = s.get("extract", [])
        if isinstance(extract_raw, dict):
            extract_raw = [extract_raw]
        extracts = []
        for ex in extract_raw:
            extracts.append(
                ExtractConfig(
                    type=ex["type"],
                    selector=ex.get("selector", ""),
                    pattern=ex.get("pattern", ""),
                    flags=ex.get("flags", []),
                    attribute=ex.get("attribute", ""),
                    multiple=ex.get("multiple", True),
                    fields=_parse_fields(ex.get("fields")),
                )
            )

        retry_raw = s.get("retry")
        retry = None
        if retry_raw:
            if isinstance(retry_raw, int):
                retry = RetryConfig(max_retries=retry_raw)
            else:
                retry = RetryConfig(
                    max_retries=retry_raw.get("max_retries", 10),
                    retryable_codes=set(retry_raw.get("retryable_codes", [429, 502, 503, 504])),
                )

        stages.append(
            StageConfig(
                id=s["id"],
                input=s.get("input"),
                urls=s.get("urls", []),
                url_pattern=s.get("url_pattern", ""),
                url_range=s.get("url_range"),
                fetcher=s.get("fetcher", "httpx"),
                headers=s.get("headers", {}),
                extracts=extracts,
                retry=retry,
                filter=_parse_filter_rules(s.get("filter")),
                security=s.get("security", False),
                security_selector=s.get("security_selector", ""),
                resources=s.get("resources", []),
                qb_send=s.get("qb_send", False),
                category=s.get("category", ""),
                concurrency=s.get("concurrency", 0),
                delay=s.get("delay", 0.0),
                dedup_by=s.get("dedup_by"),
            )
        )

    return CrawlerConfig(
        name=raw.get("name", "unnamed"),
        browser=browser,
        qb=qb,
        stages=stages,
    )


def expand_urls(stage: StageConfig) -> list[str]:
    if stage.urls:
        return stage.urls
    if stage.url_pattern and stage.url_range:
        name = stage.url_range["name"]
        start = stage.url_range.get("start", 0)
        end = stage.url_range["end"]
        step = stage.url_range.get("step", 1)
        if step == 0:
            print("  [config] 警告: url_range.step 不能为 0, 使用默认值 1")
            step = 1
        return [stage.url_pattern.replace(f"{{{name}}}", str(i)) for i in range(start, end, step)]
    return []

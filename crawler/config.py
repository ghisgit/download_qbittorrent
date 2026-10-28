from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from itertools import product
from pathlib import Path
from typing import Any, Literal, cast

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
class CacheConfig:
    enabled: bool = False  # 全局默认关闭, 通过配置开启
    dir: str = "cache"  # 缓存目录 (相对工作目录)
    ttl: int = 0  # 过期秒数, 0 = 永不过期


@dataclass
class RetryConfig:
    max_retries: int = 10
    retryable_codes: set[int] = dc_field(default_factory=lambda: {429, 502, 503, 504})


@dataclass
class FieldExtract:
    selector: str = ""
    attribute: str = ""  # ""/text 取文本, 否则取属性值
    multiple: bool = False  # True ⇒ returns a list of values
    type: str = ""  # "int" to cast
    pattern: str = ""  # regex applied to the raw value (group 1 preferred)
    replace: dict[str, str] = dc_field(default_factory=dict)  # regex → replacement, via re.sub
    flags: list[str] = dc_field(default_factory=list)  # [I, S, M]


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


CompareKeep = Literal["first", "last", "max", "min"]


@dataclass
class CompareConfig:
    """Post-filter comparison: group results by ``by`` and keep one per group.

    ``by`` entries are literal top-level item fields: fields extracted in the
    current stage, non-underscore fields inherited from upstream stages, or
    internal fields such as ``_source_url`` / ``_source``.  Nested paths,
    indexes, and ``{field}`` templates are not supported.
    """

    by: list[str] = dc_field(default_factory=list)
    keep: CompareKeep = "first"
    metric: list[str] = dc_field(default_factory=list)


@dataclass
class StageConfig:
    id: str
    input: str | list[str] | None = None
    urls: list[str] = dc_field(default_factory=list)
    url_pattern: str = ""
    url_range: dict[str, Any] | list[dict[str, Any]] | None = None
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
    compare: CompareConfig | None = None
    debug_save: bool | None = None
    cache: bool | None = None  # 覆盖全局 cache.enabled (None = 跟随全局)


@dataclass
class CrawlerConfig:
    name: str
    browser: BrowserConfig = dc_field(default_factory=BrowserConfig)
    qb: QBConfig = dc_field(default_factory=QBConfig)
    cache: CacheConfig = dc_field(default_factory=CacheConfig)
    stages: list[StageConfig] = dc_field(default_factory=list)


# ── helpers ─────────────────────────────────────────────────────────


def _parse_fields(raw: dict[str, Any] | None) -> dict[str, FieldExtract]:
    fields = {}
    for name, f_raw in (raw or {}).items():
        replace: dict[str, str] = {}
        replace_raw = f_raw.get("replace") or {}
        if not isinstance(replace_raw, dict):
            print(
                f"  [config] 警告: 字段 '{name}' 的 replace 应为字典, 收到 {type(replace_raw).__name__}: {replace_raw}"
            )
        else:
            for pattern, replacement in replace_raw.items():
                pattern = str(pattern)
                try:
                    re.compile(pattern)
                except re.error as exc:
                    print(f"  [config] 警告: 字段 '{name}' 的 replace 正则无效: {pattern!r} ({exc}), 已忽略")
                    continue
                replace[pattern] = "" if replacement is None else str(replacement)

        fields[name] = FieldExtract(
            selector=f_raw.get("selector", ""),
            attribute=f_raw.get("attribute", ""),
            multiple=f_raw.get("multiple", False),
            type=f_raw.get("type", ""),
            pattern=f_raw.get("pattern", ""),
            replace=replace,
            flags=f_raw.get("flags", []),
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


_COMPARE_KEEP_MODES: tuple[str, ...] = ("first", "last", "max", "min")


def _parse_compare(raw: Any) -> CompareConfig | None:
    """Parse the optional per-stage ``compare`` block.

    ``by`` is required and names literal top-level item fields (nested paths and
    templates are not supported).  Accepted forms::

        compare: group_0
        compare: [title, season]
        compare: {by: [title], keep: max, metric: [seeders, leechers]}
    """
    if raw is None or raw is False:
        return None
    if raw is True:
        print("  [config] 警告: compare: true 缺少 by, 已忽略; 请写 compare: <字段名> 或 compare: {by: ...}")
        return None
    if isinstance(raw, str):
        raw = {"by": [raw]}
    elif isinstance(raw, list):
        raw = {"by": raw}
    if not isinstance(raw, dict):
        print(f"  [config] 警告: compare 配置应为字段名、字段列表或字典, 收到 {type(raw).__name__}: {raw}")
        return None

    by_raw = raw.get("by")
    if isinstance(by_raw, str):
        by = [by_raw]
    elif isinstance(by_raw, list):
        by = [str(item) for item in by_raw]
    else:
        by = []
    by = [field.strip() for field in by if field.strip()]
    if not by:
        print("  [config] 警告: compare 缺少 by, 已忽略")
        return None

    keep_raw = raw.get("keep", "first")
    keep = str(keep_raw).strip().lower()
    if keep not in _COMPARE_KEEP_MODES:
        print(f"  [config] 警告: compare.keep 无效 '{keep_raw}', 使用 first")
        keep = "first"
    keep_mode = cast(CompareKeep, keep)

    metric_raw = raw.get("metric")
    if isinstance(metric_raw, str):
        metric = [metric_raw]
    elif isinstance(metric_raw, list):
        metric = [str(item) for item in metric_raw]
    else:
        metric = []
    metric = [field.strip() for field in metric if field.strip()]
    if keep_mode in ("max", "min") and not metric:
        print(f"  [config] 警告: compare.keep={keep_mode} 需要 metric, 回退 first")
        keep_mode = "first"

    return CompareConfig(by=by, keep=keep_mode, metric=metric)


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

    cache_raw = raw.get("cache", {})
    cache = CacheConfig(
        enabled=cache_raw.get("enabled", False),
        dir=cache_raw.get("dir", "cache"),
        ttl=cache_raw.get("ttl", 0),
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
                compare=_parse_compare(s.get("compare")),
                debug_save=s.get("debug_save"),
                cache=s.get("cache"),
            )
        )

    return CrawlerConfig(
        name=raw.get("name", "unnamed"),
        browser=browser,
        qb=qb,
        cache=cache,
        stages=stages,
    )


def _url_range_values(raw_range: Any) -> tuple[str, list[str]] | None:
    """Build the value list for one ``url_range`` entry."""
    if not isinstance(raw_range, dict):
        print(f"  [config] 警告: url_range 项应为字典, 收到 {type(raw_range).__name__}: {raw_range}")
        return None

    name = raw_range.get("name")
    if not name:
        print(f"  [config] 警告: url_range 缺少 name: {raw_range}")
        return None

    end = raw_range.get("end")
    if end is None:
        print(f"  [config] 警告: url_range '{name}' 缺少 end")
        return None

    start = raw_range.get("start", 0)
    step = raw_range.get("step", 1)
    if step == 0:
        print("  [config] 警告: url_range.step 不能为 0, 使用默认值 1")
        step = 1

    try:
        start_int = int(start)
        end_int = int(end)
        step_int = int(step)
    except TypeError, ValueError:
        print(f"  [config] 警告: url_range '{name}' 的 start/end/step 必须是整数")
        return None

    if step_int == 0:
        print("  [config] 警告: url_range.step 不能为 0, 使用默认值 1")
        step_int = 1

    values = [str(value) for value in range(start_int, end_int, step_int)]
    if not values:
        print(f"  [config] 警告: url_range '{name}' 未生成任何值")
    return str(name), values


def expand_urls(stage: StageConfig) -> list[str]:
    if stage.urls:
        return stage.urls
    if not stage.url_pattern or not stage.url_range:
        return []

    raw_ranges = stage.url_range if isinstance(stage.url_range, list) else [stage.url_range]
    ranges: list[tuple[str, list[str]]] = []
    seen_names: set[str] = set()
    for raw_range in raw_ranges:
        range_item = _url_range_values(raw_range)
        if range_item is None:
            continue
        name, values = range_item
        if name in seen_names:
            print(f"  [config] 警告: url_range.name 重复, 已忽略: {name}")
            continue
        seen_names.add(name)
        ranges.append((name, values))

    if not ranges or any(not values for _, values in ranges):
        return []

    configured_names = {name for name, _ in ranges}
    placeholders = set(re.findall(r"\{([^{}]+)\}", stage.url_pattern))
    missing = sorted(placeholders - configured_names)
    if missing:
        print(f"  [config] 警告: url_pattern 存在未配置的占位符: {', '.join(missing)}")

    urls: list[str] = []
    for combination in product(*(values for _, values in ranges)):
        url = stage.url_pattern
        for (name, _), value in zip(ranges, combination, strict=True):
            url = url.replace(f"{{{name}}}", value)
        urls.append(url)

    return list(dict.fromkeys(urls))

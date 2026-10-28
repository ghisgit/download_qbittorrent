from __future__ import annotations

import math
import re
from typing import Any

from bs4 import BeautifulSoup

import crawler

from .config import _UNSET, CompareConfig, CompareKeep, ExtractConfig, FieldExtract, FilterCondition, FilterRule


def extract(html: str, cfg: ExtractConfig, source_url: str = "") -> list[dict[str, Any]]:
    if cfg.type == "regex":
        return _extract_regex(html, cfg, source_url)
    elif cfg.type == "css":
        return _extract_css(html, cfg, source_url)
    elif cfg.type == "xpath":
        return _extract_xpath(html, cfg, source_url)
    return []


def _compile_flags(flags: list[str]) -> int:
    result = 0
    for f in flags:
        if f.upper() == "I":
            result |= re.I
        elif f.upper() == "S":
            result |= re.S
        elif f.upper() == "M":
            result |= re.M
    return result


def _extract_regex(html: str, cfg: ExtractConfig, source_url: str) -> list[dict[str, Any]]:
    flag = _compile_flags(cfg.flags)
    matches = re.findall(cfg.pattern, html, flag)
    if not cfg.multiple:
        matches = matches[:1]
    if crawler.settings.verbose:
        pattern_short = cfg.pattern[:60]
        print(f"  [extract] regex '{pattern_short}' \u2192 {len(matches)} matches")
    results = []
    for m in matches:
        if isinstance(m, tuple):
            keys = [f"group_{i}" for i in range(len(m))]
            item = dict(zip(keys, m))
        else:
            item = {"group_0": m}
        item["_source"] = source_url
        if crawler.settings.verbose:
            display = {k: v for k, v in item.items() if not k.startswith("_")}
            print(f"  [extract] item: {display}")
        results.append(item)
    return results


def _single_value(el: Any, attr: str) -> str | None:
    val = el.get(attr) if attr and attr != "text" else el.get_text(strip=True)
    return str(val).strip() if val else None


def _finalize_value(raw: str | None, fe: FieldExtract) -> Any:
    """Value pipeline: pattern → re.sub replacements → int cast.

    Returns ``None`` when extraction or replace fails.
    """
    if raw is None:
        return None
    val: str = raw
    flags = _compile_flags(fe.flags)
    if fe.pattern:
        m = re.search(fe.pattern, val, flags)
        if not m:
            return None
        val = m.group(0)
        if m.lastindex:
            for gi in range(1, m.lastindex + 1):
                g = m.group(gi)
                if g is not None:
                    val = g
                    break
    if fe.replace:
        try:
            for pattern, replacement in fe.replace.items():
                val = re.sub(pattern, replacement, val, flags=flags)
        except re.error:
            return None
    if fe.type == "int":
        try:
            return int(val)
        except ValueError:
            return None
    return val


def _extract_value(el: Any, attr: str, multiple: bool) -> str | list[str] | None:
    if not multiple:
        return _single_value(el, attr)
    # multiple: el may contain several sub-elements with values
    if attr:
        # if attr is set, get that attribute from all matching sub-elements
        items = el.select(attr) if attr else []
        vals = []
        for item in items:
            v = _single_value(item, attr)
            if v is not None:
                vals.append(v)
        return vals if vals else None
    else:
        # no attr: get text from all direct child elements
        texts = el.stripped_strings
        vals = [t for t in texts]
        return vals if vals else None


def _extract_css(html: str, cfg: ExtractConfig, source_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    elements = soup.select(cfg.selector)
    if not cfg.multiple:
        elements = elements[:1]
    if crawler.settings.verbose:
        print(f"  [extract] css selector '{cfg.selector}' \u2192 {len(elements)} elements")

    results = []

    for i, el in enumerate(elements):
        if cfg.fields:
            item: dict[str, Any] = {"_source": source_url}
            for name, fe in cfg.fields.items():
                if fe.multiple:
                    sub_els = el.select(fe.selector) if fe.selector else []
                    vals = []
                    for sub in sub_els:
                        v = _finalize_value(_single_value(sub, fe.attribute), fe)
                        if v is not None:
                            vals.append(v)
                    if vals:
                        item[name] = vals
                else:
                    sub_el = el.select_one(fe.selector) if fe.selector else el
                    if sub_el:
                        v = _finalize_value(_single_value(sub_el, fe.attribute), fe)
                        if v is not None:
                            item[name] = v
            if len(item) > 1:
                if crawler.settings.verbose:
                    display = {k: v for k, v in item.items() if not k.startswith("_")}
                    print(f"  [extract] item#{i}: {display}")
                results.append(item)
            elif crawler.settings.verbose:
                print(f"  [extract] item#{i}: \u2716 no fields extracted (all sub-selectors missed)")
        else:
            val = _single_value(el, cfg.attribute)
            if val is not None:
                results.append({"text": val, "_source": source_url})
                if crawler.settings.verbose:
                    print(f"  [extract] item: {val[:60]}")

    return results


def _xpath_value(el: Any, attr: str) -> str | None:
    if attr and attr != "text":
        val = el.get(attr)
    elif hasattr(el, "text"):
        val = (el.text or "").strip()
    else:
        val = str(el).strip()
    return val or None


def _extract_xpath(html: str, cfg: ExtractConfig, source_url: str) -> list[dict[str, Any]]:
    from lxml import html as lh

    tree = lh.fromstring(html)

    if cfg.fields:
        root_elements = tree.xpath(cfg.selector) if cfg.selector else [tree]
        if not cfg.multiple:
            root_elements = root_elements[:1]
        if crawler.settings.verbose:
            print(f"  [extract] xpath '{cfg.selector}' \u2192 {len(root_elements)} root elements")
        results = []
        for el in root_elements:
            item: dict[str, Any] = {"_source": source_url}
            for name, fe in cfg.fields.items():
                if fe.selector:
                    sub_els = el.xpath(fe.selector)
                    vals = []
                    for sub in sub_els:
                        v = _finalize_value(_xpath_value(sub, fe.attribute), fe)
                        if v is not None:
                            vals.append(v)
                    if vals:
                        item[name] = vals if fe.multiple else vals[0]
            if len(item) > 1:
                if crawler.settings.verbose:
                    display = {k: v for k, v in item.items() if not k.startswith("_")}
                    print(f"  [extract] item: {display}")
                results.append(item)
        return results

    elements = tree.xpath(cfg.selector)
    if not cfg.multiple:
        elements = elements[:1]
    if crawler.settings.verbose:
        print(f"  [extract] xpath '{cfg.selector}' \u2192 {len(elements)} elements")
    results = []
    for el in elements:
        val = _xpath_value(el, cfg.attribute)
        if val:
            results.append({"text": val, "_source": source_url})
    if crawler.settings.verbose and results:
        for r in results:
            print(f"  [extract] item: {r.get('text', '')[:60]}")
    return results


# ── filter engine ───────────────────────────────────────────────────


def _get_field(item: dict[str, Any], field: str) -> str:
    val = item.get(field, "")
    if isinstance(val, list):
        return "\n".join(str(v) for v in val)
    return str(val)


def _check_condition(item: dict[str, Any], cond: FilterCondition) -> bool:
    val = _get_field(item, cond.field)

    if cond.contains and cond.contains not in val:
        return False
    if cond.not_contains and cond.not_contains in val:
        return False
    if cond.eq and val != cond.eq:
        return False
    if cond.not_in:
        raw_val = item.get(cond.field)
        if isinstance(raw_val, list):
            if any(str(v) in cond.not_in for v in raw_val):
                return False
        elif val in cond.not_in:
            return False
    if cond.gt is not _UNSET:
        try:
            if float(val) <= cond.gt:
                return False
        except ValueError:
            return False
    if cond.gte is not _UNSET:
        try:
            if float(val) < cond.gte:
                return False
        except ValueError:
            return False
    if cond.lt is not _UNSET:
        try:
            if float(val) >= cond.lt:
                return False
        except ValueError:
            return False
    if cond.lte is not _UNSET:
        try:
            if float(val) > cond.lte:
                return False
        except ValueError:
            return False
    return True


def _check_rule(item: dict[str, Any], rule: FilterRule) -> bool:
    if rule.condition:
        return _check_condition(item, rule.condition)
    if rule.any_of:
        return any(_check_rule(item, r) for r in rule.any_of)
    if rule.all_of:
        return all(_check_rule(item, r) for r in rule.all_of)
    return True


def apply_filter(items: list[dict[str, Any]], rules: list[FilterRule]) -> list[dict[str, Any]]:
    if not rules:
        return items
    filtered = []
    for item in items:
        ok = all(_check_rule(item, r) for r in rules)
        if crawler.settings.verbose:
            title = item.get("title") or item.get("text", "")[:40]
            status = "+pass" if ok else "-drop"
            print(f"  [filter] {status}: {title}")
        if ok:
            filtered.append(item)
    return filtered


# ── compare engine ───────────────────────────────────────────────────


def _normalize_compare_value(value: Any) -> tuple[str, ...] | None:
    """Normalize one comparison-key field to a hashable, order-preserving tuple."""
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value if item is not None]
        parts = [part for part in parts if part]
        return tuple(parts) or None
    text = str(value).strip()
    return (text,) if text else None


def _compare_key(item: dict[str, Any], by: list[str]) -> tuple[tuple[str, ...], ...] | None:
    """Build the comparison key; ``None`` means the item cannot be compared."""
    parts: list[tuple[str, ...]] = []
    for field in by:
        part = _normalize_compare_value(item.get(field))
        if part is None:
            return None
        parts.append(part)
    return tuple(parts)


def _metric_value(item: dict[str, Any], field: str) -> float | None:
    """Return a finite numeric metric value, or ``None`` when unusable."""
    value = item.get(field)
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _metric_values(item: dict[str, Any], fields: list[str]) -> tuple[float | None, ...]:
    return tuple(_metric_value(item, field) for field in fields)


def _metric_better(
    candidate: tuple[float | None, ...],
    current: tuple[float | None, ...],
    keep: CompareKeep,
) -> bool:
    """Lexicographic comparison; a missing metric only loses at its own position."""
    for candidate_value, current_value in zip(candidate, current, strict=True):
        if candidate_value is None and current_value is None:
            continue
        if candidate_value is None:
            return False
        if current_value is None:
            return True
        if candidate_value == current_value:
            continue
        return candidate_value > current_value if keep == "max" else candidate_value < current_value
    return False


def _compare_winner(
    indices: list[int],
    items: list[dict[str, Any]],
    cfg: CompareConfig,
) -> int:
    if cfg.keep == "last":
        return indices[-1]
    if cfg.keep in ("max", "min") and cfg.metric:
        winner = indices[0]
        winner_values = _metric_values(items[winner], cfg.metric)
        for index in indices[1:]:
            values = _metric_values(items[index], cfg.metric)
            if _metric_better(values, winner_values, cfg.keep):
                winner = index
                winner_values = values
        return winner
    return indices[0]


def _display_compare_item(item: dict[str, Any]) -> str:
    for field in ("title", "text", "group_0"):
        value = item.get(field)
        if value:
            return str(value)[:60]
    for field in ("_url", "_source_url", "_source"):
        value = item.get(field)
        if value:
            return str(value)[:60]
    return "<item>"


def _format_compare_key(key: tuple[tuple[str, ...], ...]) -> str:
    return " | ".join("+".join(part) for part in key)


def apply_compare(items: list[dict[str, Any]], cfg: CompareConfig) -> list[dict[str, Any]]:
    """Group items by ``cfg.by`` and keep one item per group.

    With ``keep: max/min`` multiple metric fields are compared lexicographically.
    The returned list preserves the original relative order of the kept items.
    Items whose comparison key is missing/empty are always kept.
    """
    if len(items) < 2 or not cfg.by:
        return items

    groups: dict[tuple[tuple[str, ...], ...], list[int]] = {}
    for index, item in enumerate(items):
        key = _compare_key(item, cfg.by)
        if key is None:
            continue
        groups.setdefault(key, []).append(index)

    if not groups:
        if crawler.settings.verbose:
            print(f"  [compare] 无可比较项 (缺少字段: {', '.join(cfg.by)})")
        return items

    grouped: set[int] = set()
    kept: set[int] = set()
    for key, indices in groups.items():
        grouped.update(indices)
        winner = _compare_winner(indices, items, cfg)
        kept.add(winner)
        if crawler.settings.verbose:
            label = _format_compare_key(key)
            for index in indices:
                if index != winner:
                    print(f"  [compare] -drop: {_display_compare_item(items[index])} (key={label})")

    return [item for index, item in enumerate(items) if index not in grouped or index in kept]

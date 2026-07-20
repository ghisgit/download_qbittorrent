from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

import crawler

from .config import _UNSET, ExtractConfig, FilterCondition, FilterRule


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
    val = el.get(attr) if attr else el.get_text(strip=True)
    return str(val).strip() if val else None


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
                        v = _single_value(sub, fe.attribute)
                        if v is not None:
                            vals.append(int(v) if fe.type == "int" else v)
                    if vals:
                        item[name] = vals if fe.multiple else vals[0]
                else:
                    sub_el = el.select_one(fe.selector) if fe.selector else el
                    if sub_el:
                        v = _single_value(sub_el, fe.attribute)
                        if v is not None:
                            item[name] = int(v) if fe.type == "int" else v
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
    if attr:
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
                        v = _xpath_value(sub, fe.attribute)
                        if v is not None:
                            vals.append(int(v) if fe.type == "int" else v)
                    if vals:
                        item[name] = vals if fe.multiple else vals[0]
            if len(item) > 1:
                if crawler.settings.verbose:
                    display = {k: v for k, v in item.items() if not k.startswith("_")}
                    print(f"  [extract] item: {display}")
                results.append(item)
        return results

    elements = tree.xpath(cfg.selector)
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
    if cond.not_in and val in cond.not_in:
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

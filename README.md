# download-qbittorrent

A config-driven async crawler engine that scrapes websites, extracts magnet links, and sends them to qBittorrent.

## Features

- **Multi-stage pipelines** — chain fetch → extract → filter → qBittorrent across as many stages as needed
- **Three extraction methods** — regex, CSS selectors, XPath
- **Two fetcher backends** — Playwright (JS-rendered pages) and httpx (lightweight)
- **Security check bypass** — auto-click age-gate/security buttons (Playwright mode)
- **Config-driven** — all pipeline logic expressed in YAML, zero code changes to add a new crawler
- **Per-stage control** — concurrency, delay, retry policy, category override per stage
- **Rich filtering** — field matching (`contains`, `not_contains`, `eq`, numeric `gt`/`gte`/`lt`/`lte`) with `any_of` / `all_of` logical groups
- **Upstream data merge** — downstream stages carry forward all non-`_` fields from upstream items
- **Verbose logging** — `-v` per-item fetch, extract, and filter decision logging

## Quick start

```bash
# Install dependencies
uv sync

# Install Chromium for Playwright
playwright install chromium

# Run a crawler
uv run python -m crawler.cli configs/template.yaml
```

## CLI

```
uv run python -m crawler.cli [-v] [--debug-save] <config.yaml>
```

| Flag               | Description                                                   |
| ------------------ | ------------------------------------------------------------- |
| `-v` / `--verbose` | Per-item fetch, extract, and filter decision logging          |
| `--debug-save`     | Save downloaded HTML to `debug_*.html` for offline inspection |

## Configuration

Create a YAML file and pass it to the CLI. See `configs/template.yaml` for a complete reference.

### Global settings

```yaml
name: my-crawler # Crawler name (displayed at startup)

qb: # qBittorrent connection
  url: "http://localhost:8080"
  user: "admin"
  password: "adminadmin"
  category: my-category
  sequential_download: true
  first_last_piece_prio: true
  add_to_top_of_queue: true

browser: # Playwright browser config
  headless: true
  args: ["--blink-settings=imagesEnabled=false"]
```

### Pipeline stages

Each stage defines:

| Field         | Description                                              |
| ------------- | -------------------------------------------------------- |
| `id`          | Unique stage identifier                                  |
| `input`       | Upstream stage ID (omit for seed stages)                 |
| `fetcher`     | `playwright` or `httpx`                                  |
| `url_pattern` | URL template with `{field}` placeholders                 |
| `url_range`   | Auto-generate URLs for seed stages                       |
| `extract`     | Extraction rule(s) — single object or list               |
| `resources`   | Fields this stage produces (for logging)                 |
| `filter`      | Filter rules to drop unwanted items                      |
| `qb_send`     | Send extracted magnets to qBittorrent                    |
| `concurrency` | Max concurrent fetches (default: playwright=3, httpx=10) |
| `delay`       | Seconds to wait after each fetch                         |
| `retry`       | Retry policy (httpx only)                                |
| `security`    | Auto-click security check buttons (playwright only)      |

### Data flow

```
[Seed URLs] → Stage A → Stage B → Stage C → ... → qBittorrent
                    ↓           ↓
              Field A_1     Field B_1
              Field A_2     Field B_2
                              ...
```

Each stage receives items from its `input` stage, fetches each item's URL, extracts new fields, merges upstream fields (non-`_` keys) into extracted results, and passes them downstream.

## Project structure

```
├── crawler/
│   ├── __init__.py    # Global flags (VERBOSE, DEBUG_SAVE)
│   ├── cli.py         # CLI entry point
│   ├── config.py      # Dataclasses + YAML loader
│   ├── extract.py     # Regex/CSS/XPath extraction + filter engine
│   ├── fetch.py       # Playwright + httpx fetchers
│   ├── pipeline.py    # Pipeline orchestrator
│   └── qb.py          # qBittorrent API client
├── configs/
│   └── template.yaml  # Configuration template
├── pyproject.toml
└── uv.lock
```

## Adding a new crawler

1. Create a YAML config in `configs/`
2. Run `uv run python -m crawler.cli configs/your-crawler.yaml`
3. Optionally pass `-v` to debug extraction and filtering

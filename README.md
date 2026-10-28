# download-qbittorrent

A config-driven async crawler engine that scrapes websites, extracts magnet links, and sends them to qBittorrent.

## Features

- **Multi-stage pipelines** — chain fetch → extract → filter → compare → qBittorrent across as many stages as needed
- **Three extraction methods** — regex, CSS selectors, XPath
- **Two fetcher backends** — Playwright (JS-rendered pages) and httpx (lightweight)
- **Security check bypass** — auto-click age-gate/security buttons (Playwright mode)
- **Multi-input merge** — a stage can consume several upstream stages (`input: [a, b]`), concatenating items and deduplicating by `_url`; `dedup_by` also dedups by any field
- **Config-driven** — all pipeline logic expressed in YAML, zero code changes to add a new crawler
- **Per-stage control** — concurrency, delay, retry policy, category override per stage
- **Rich filtering** — field matching (`contains`, `not_contains`, `eq`, `not_in`, numeric `gt`/`gte`/`lt`/`lte`) with `any_of` / `all_of` logical groups
- **Post-filter comparison** — optionally group filtered results by one or more fields and keep one per group (first, last, or the max/min of one or more numeric metrics); only runs when more than one result remains
- **Filtered qB sends** — when both `filter` and `qb_send: true` are set, only items that pass the filter are sent to qBittorrent
- **Per-item category** — `category` supports `{field}` templates resolved from current-stage resources or fields inherited from upstream stages
- **Upstream data merge** — downstream stages carry forward all non-`_` fields from upstream items
- **Verbose logging** — `-v` per-item fetch, extract, filter, and compare decision logging
- **Timestamped run logs** — optionally tee stdout/stderr to `logs/crawler_YYYYMMDD_HHMMSS.log` via `--log-save` or environment variables, with an optional custom directory

## Quick start

```bash
# Install dependencies
uv sync

# Install Chromium for Playwright
playwright install chromium

# Run a crawler
uv run python -m crawler.cli configs/template.yaml
```

## Docker

Package the crawler as a container so it can run on any Docker host without rebuilding the environment — just mount your config file.

### Build

```bash
docker build -t download-qbittorrent .
```

### Run (docker compose)

```bash
export UID=$(id -u) GID=$(id -g)   # so files written by the container are owned by you
docker compose run --rm crawler                # runs /app/user.yaml by default
docker compose run --rm crawler -v             # add -v for verbose logging
docker compose run --rm crawler /app/user.yaml # specify a config explicitly
CRAWLER_VERBOSE=1 docker compose run --rm crawler  # or via environment variable
docker compose run --rm -e CRAWLER_LOG_SAVE=1 crawler  # save logs under ./work/logs/
```

Enter your options through the root `.env` (env vars above), or `required: false` means compose still works without it. Compose sets `network_mode: host`, so `qb.url`'s `http://localhost:8080` reaches the host's qBittorrent directly — no YAML changes needed (Linux only).

### Mount contract

| Host path      | Container path  | Description                                          |
| -------------- | --------------- | ---------------------------------------------------- |
| `./user.yaml`  | `/app/user.yaml`| Read-only personal config (contains qB credentials)  |
| `./work/`      | `/app/work`     | Working directory; `--debug-save` HTML and run logs (`./work/logs/`) land on the host |

For daily runs only the personal `user.yaml` needs mounting; the `configs/` template is for syntax reference and is not required.

### Run (docker run)

```bash
mkdir -p work
docker run --rm --network host --user $(id -u):$(id -g) \
  -v $PWD/user.yaml:/app/user.yaml:ro \
  -v $PWD/work:/app/work \
  -w /app/work \
  download-qbittorrent /app/user.yaml
```

### Notes

- **Headless only**: Chromium in the container runs with `headless: true` only; do visual debugging on the host
- **UID matching**: without `--user $(id -u):$(id -g)`, files written by the container are owned by root
- **Image size ~1GB**: includes Chromium and its system libraries
- **Migration**: `docker save download-qbittorrent | gzip > img.tgz`, then `gunzip -c img.tgz | docker load` on the target host
- **No secrets in the image**: `user.yaml` is in `.dockerignore` and injected at runtime via mount

## CLI

```
uv run python -m crawler.cli [-v] [--debug-save] [--log-save] [--log-dir DIR] <config.yaml>
```

| Flag               | Description                                                   |
| ------------------ | ------------------------------------------------------------- |
| `-v` / `--verbose` | Per-item fetch, extract, and filter decision logging          |
| `--debug-save`     | Save downloaded HTML to `debug_{stage.id}_*.html` for offline inspection |
| `--log-save`       | Save run output to a timestamped log file                     |
| `--log-dir DIR`    | Log directory (default `logs`; setting it also enables log saving) |

These options can also be controlled via environment variables (CLI flags win):

```bash
CRAWLER_VERBOSE=1 uv run python -m crawler.cli configs/template.yaml
CRAWLER_DEBUG_SAVE=1 uv run python -m crawler.cli configs/template.yaml
CRAWLER_LOG_SAVE=1 uv run python -m crawler.cli configs/template.yaml
CRAWLER_LOG_DIR=/tmp/crawler-logs uv run python -m crawler.cli configs/template.yaml
```

Acceptable values for boolean variables (`CRAWLER_VERBOSE`, `CRAWLER_DEBUG_SAVE`, `CRAWLER_LOG_SAVE`): `1`, `true`, `yes`, `on`.

`--debug-save` is a global switch, but each stage can override it with `debug_save`:

```yaml
- id: posts
  fetcher: playwright
  debug_save: true  # save HTML even without --debug-save
  ...

- id: details
  fetcher: httpx
  debug_save: false # don't save even with --debug-save
  ...
```

Unset stages follow the global CLI flag. Retry (`retry: {max_retries, retryable_codes}`) works for both fetchers — it retries on load failures/timeouts and on the listed HTTP status codes, with exponential backoff.

### Run logs

Enable with `--log-save` (or `CRAWLER_LOG_SAVE=1`). Each run creates a new file named from the local start time:

```text
logs/crawler_20261028_192527.log
```

- Default directory is `logs`; use `--log-dir DIR` or `CRAWLER_LOG_DIR=DIR` to change it. Setting either directory option also enables logging.
- stdout and stderr are still printed to the console and are tee'd into the file; config warnings and unhandled tracebacks are included.
- Existing log files are never overwritten; runs starting in the same second get `_1`, `_2`, ... suffixes.
- If the directory/file cannot be created or written, the crawler logs a warning and continues without file logging.
- In Docker the working directory is `/app/work`, so default logs land in `./work/logs/` on the host.
- Timestamps use the process local time; Docker defaults to UTC unless `TZ` is set (for example `TZ=Asia/Shanghai`).
- CLI options take precedence over environment variables.

```bash
uv run python -m crawler.cli --log-save configs/template.yaml
uv run python -m crawler.cli --log-dir /tmp/crawler-logs configs/template.yaml
CRAWLER_LOG_SAVE=1 uv run python -m crawler.cli configs/template.yaml
```

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
  timeout: 30
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
| `input`       | Upstream stage ID(s) — string or list; list concatenates sources and dedups by `_url` |
| `urls`        | Static seed URL list (alternative to `url_pattern` + `url_range` for seed stages) |
| `fetcher`     | `playwright` or `httpx`                                  |
| `url_pattern` | URL template with `{field}` placeholders                 |
| `url_range`   | Auto-generate URLs for seed stages; single range or list of ranges |
| `headers`     | Extra HTTP headers (httpx only)                          |
| `extract`     | Extraction rule(s) — single object or list               |
| `resources`   | Fields this stage produces (for logging)                 |
| `filter`      | Filter rules to drop unwanted items; `qb_send` only sends survivors |
| `compare`     | Optional post-filter comparison (`by`, `keep`, `metric`); skipped when ≤1 result |
| `dedup_by`    | Dedup input by this field before fetching                |
| `cache`       | Override global `cache.enabled` for this stage (`true`/`false`) |
| `debug_save`  | Override global `--debug-save` for this stage (`true`/`false`) |
| `qb_send`     | Send magnets from filtered results to qBittorrent        |
| `category`    | Override the global `qb.category`; supports `{field}` templates |
| `concurrency` | Max concurrent fetches (default: playwright=3, httpx=10) |
| `delay`       | Seconds to wait after each fetch                         |
| `retry`       | Retry policy (both playwright and httpx)                 |
| `security`    | Auto-click security check buttons (playwright only)      |
| `security_selector` | CSS selector of the security button to click        |

### URL generation

Seed stages can generate URLs from `url_pattern` and one or more `url_range` entries.  The original single-range form is still supported:

```yaml
url_pattern: "https://example.com/list?page={page}"
url_range:
  name: page
  start: 1
  end: 4   # end is exclusive
  step: 1  # optional, defaults to 1
```

For multiple placeholders, use a list.  URLs are generated as the Cartesian product of all ranges, preserving configuration order:

```yaml
url_pattern: "https://example.com/list?page={page}&category={category}"
url_range:
  - name: page
    start: 1
    end: 3
  - name: category
    start: 1
    end: 3
```

This generates:

```text
https://example.com/list?page=1&category=1
https://example.com/list?page=1&category=2
https://example.com/list?page=2&category=1
https://example.com/list?page=2&category=2
```

`urls` takes precedence over `url_pattern` + `url_range`.  Placeholders without a matching range are left unchanged and produce a configuration warning.

### qBittorrent output

`qb_send: true` sends magnets collected from the stage's results.  `filter` is applied first, so dropped items are never sent:

```yaml
- id: magnets
  input: details
  fetcher: httpx
  url_pattern: "https://example.com/links/{text}"
  extract:
    type: regex
    pattern: "(magnet:\\?xt=urn:btih:[a-fA-F0-9]{32})"
    flags: [I]
    multiple: true
  resources: ["group_0"]
  filter:
    - field: group_0
      contains: "magnet:"
  category: "movie/{id}"   # current resource or upstream field
  qb_send: true
```

`category` can be a literal string or a template containing `{field}` placeholders.  Placeholders are resolved per result from the merged item, so fields extracted in the current stage and fields inherited from the previous stage are both available.  Examples:

```yaml
category: "movie"            # fixed category
category: "movie/{text}"     # current-stage resource or inherited field
category: "movie/{id}"
```

If a placeholder is missing or resolves to an empty value, the global `qb.category` is used.  Results that resolve to different categories are grouped and added with separate qBittorrent requests.

If qBittorrent reports that a torrent already exists (HTTP 409), the crawler ensures the resolved category exists (creating it with `/api/v2/torrents/createCategory` when necessary) and then moves the torrent through `/api/v2/torrents/setCategory`.  When `category` is empty, the existing torrent is only logged and left unchanged.

### Comparison

`compare` runs after `filter` and only when more than one result remains.  It groups results by one or more fields and keeps one item per group.  Comparison is off by default; omit `compare` (or set it to `false`) to disable it.

```yaml
- id: magnets
  # ...
  compare:
    by: [title]                  # one field or a list of fields
    keep: max                    # first (default) | last | max | min
    metric: [seeders, leechers]  # one field or a list; required for max/min
```

`metric` can be a single field (`metric: size`) or a list.  With a list, comparison is lexicographic: the first metric has priority, and later metrics break ties:

```yaml
compare:
  by: [title]
  keep: max
  metric: [seeders, leechers]   # highest seeders, then highest leechers
```

Shorthand forms:

```yaml
compare: group_0          # single field, keep first
compare: [title, season]  # multiple fields, keep first
```

#### What `by` accepts

`by` is required.  It is a literal top-level field name or a list of field names, resolved against each item at comparison time.  Common sources:

| Source | Examples | Notes |
| --- | --- | --- |
| Fields extracted in the current stage | `title`, `magnet`, `seeders`, `group_0`, `text` | regex fields are `group_0`, `group_1`, ...; CSS/XPath fields use the configured names; simple extraction without `fields` produces `text` |
| Fields inherited from upstream stages | `id`, `category`, `post_url` | only non-`_` fields are merged downstream |
| Internal item fields | `_source_url`, `_source` | `_source_url` is the URL of the page the item was extracted from; useful for grouping all rows from one page |

Not supported: nested paths (`a.b`), list indexes (`tags[0]`), `{field}` templates, expressions, or special keywords.  Such names are treated as literal keys and will normally be missing.  `_url` is only present on seed/pass-through items (stages without `extract`); use `_source_url` for extracted items.

A list creates a composite key; every listed field must be present and non-empty, otherwise the item is unkeyed and kept as-is.  To compare all results as one group, use a key that is constant for those results, for example `by: [_source_url]` for rows extracted from the same page.

Key values are normalized to trimmed strings; list/tuple values become ordered string tuples.  Comparison is exact (case-sensitive) after trimming.  There is no default key: a missing/empty `by` disables comparison with a config warning.

Semantics:

- `first` / `last` keep the first/last occurrence of each comparison key.
- `max` / `min` keep the item with the largest/smallest numeric `metric`.  With multiple metrics, the fields are compared in the configured order, so `[seeders, leechers]` means “highest seeders, then highest leechers among ties”.
- A missing or non-numeric metric only loses that field's comparison; the item can still win on an earlier metric.  If every item in the group lacks valid metrics, the first item is kept.  Ties keep the earliest item.
- Items with a missing or empty `by` field cannot be compared and are always kept.
- Kept items retain their original relative order.  The compared list is stored for downstream stages and is what `qb_send` uses.
- Comparison does not query qBittorrent.

Use a numeric extraction for each `metric` field (for example `type: int` or a regex-captured number), since `max`/`min` do numeric comparison only.

### Extraction rules

`extract` accepts a single object or a list. Three types: `regex`, `css`, `xpath`.

```yaml
extract:
  - type: css                      # extract several fields per matched element
    selector: "div.post-item"
    multiple: true                 # keep all matches (set false to keep only the first)
    fields:
      title:
        selector: "h2.post-title"  # default: inner text
      href:
        selector: "a.post-link"
        attribute: href            # or "text" (alias for inner text)
      id:
        selector: "a.post-link"
        attribute: href
        pattern: "post-(\\d+)"     # regex on the raw value; group 1 preferred
        flags: [I]
        type: int                  # cast after pattern
      tags:
        selector: "span.tag"
        multiple: true             # returns a list (pipeline applied per element)
  - type: regex
    pattern: 'data-id="(\d+)"'
    multiple: true                 # false keeps only the first match
```

Field-level options (`css`/`xpath` multi-field mode): `selector`, `attribute`, `pattern`, `flags`, `type` (`"int"`), `multiple`. Value pipeline: **attribute/text → regex (`pattern`) → cast (`type`)**; a field is omitted when its pattern misses.

### Caching

Fetched HTML is cached on disk by URL, so re-runs skip fetching entirely and replay extraction/filtering from cache. Off by default; enable globally:

```yaml
cache:
  enabled: true    # enable globally
  dir: "cache"     # cache directory (relative to workdir)
  ttl: 86400       # expire after N seconds; 0 = never
```

Each stage can override the global setting (unset = follow global):

```yaml
- id: details
  fetcher: httpx
  cache: false     # always fetch, don't cache
```

Notes:

- Cache hits skip the fetcher entirely — no network request, no retry, no security-click, no `--debug-save` dump
- `qb_send` still runs on cached data; duplicate magnets are ignored by qBittorrent (dedup by hash)
- When the site markup changes, delete the cache directory to avoid stale extractions
- With Docker, `workdir` is `/app/work` so the cache lands in the mounted `./work/cache` on the host

### Data flow

```
[Seed URLs] → Stage A → Stage B → Stage C → ... → qBittorrent
                    ↓           ↓
              Field A_1     Field B_1
              Field A_2     Field B_2
                              ...
```

Each stage receives items from its `input` stage (or seed URLs when `input` is omitted), fetches each item's URL, extracts new fields, merges upstream fields (non-`_` keys) into extracted results, applies `filter` and optional `compare`, and passes the result downstream.

`input` accepts a string or a list of stage IDs:

```yaml
input: posts          # single upstream stage
input: [posts, posts2] # merge two sources (dedup by _url)
```

Use `dedup_by` to dedup incoming items by a custom field (e.g. an extracted id) before fetching:

```yaml
- id: details
  input: [posts, posts2]
  dedup_by: group_0
  ...
```

## Project structure

```
├── crawler/
│   ├── __init__.py    # Global flags (VERBOSE, DEBUG_SAVE)
│   ├── cli.py         # CLI entry point
│   ├── config.py      # Dataclasses + YAML loader
│   ├── extract.py     # Regex/CSS/XPath extraction + filter/compare engines
│   ├── fetch.py       # Playwright + httpx fetchers
│   ├── log.py         # Timestamped run log capture
│   ├── pipeline.py    # Pipeline orchestrator
│   └── qb.py          # qBittorrent API client
├── configs/
│   └── template.yaml  # Configuration template
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── pyproject.toml
└── uv.lock
```

## Adding a new crawler

1. Create a YAML config in `configs/`
2. Run `uv run python -m crawler.cli configs/your-crawler.yaml`
3. Optionally pass `-v` to debug extraction, filtering, and comparison

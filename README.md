# download-qbittorrent

A config-driven async crawler engine that scrapes websites, extracts magnet links, and sends them to qBittorrent.

## Features

- **Multi-stage pipelines** — chain fetch → extract → filter → qBittorrent across as many stages as needed
- **Three extraction methods** — regex, CSS selectors, XPath
- **Two fetcher backends** — Playwright (JS-rendered pages) and httpx (lightweight)
- **Security check bypass** — auto-click age-gate/security buttons (Playwright mode)
- **Multi-input merge** — a stage can consume several upstream stages (`input: [a, b]`), concatenating items and deduplicating by `_url`; `dedup_by` also dedups by any field
- **Config-driven** — all pipeline logic expressed in YAML, zero code changes to add a new crawler
- **Per-stage control** — concurrency, delay, retry policy, category override per stage
- **Rich filtering** — field matching (`contains`, `not_contains`, `eq`, `not_in`, numeric `gt`/`gte`/`lt`/`lte`) with `any_of` / `all_of` logical groups
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
```

Enter your options through the root `.env` (env vars above), or `required: false` means compose still works without it. Compose sets `network_mode: host`, so `qb.url`'s `http://localhost:8080` reaches the host's qBittorrent directly — no YAML changes needed (Linux only).

### Mount contract

| Host path      | Container path  | Description                                          |
| -------------- | --------------- | ---------------------------------------------------- |
| `./user.yaml`  | `/app/user.yaml`| Read-only personal config (contains qB credentials)  |
| `./work/`      | `/app/work`     | Working directory; `--debug-save` HTML lands in `./work/` on the host |

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
uv run python -m crawler.cli [-v] [--debug-save] <config.yaml>
```

| Flag               | Description                                                   |
| ------------------ | ------------------------------------------------------------- |
| `-v` / `--verbose` | Per-item fetch, extract, and filter decision logging          |
| `--debug-save`     | Save downloaded HTML to `debug_{stage.id}_*.html` for offline inspection |

Both options can also be controlled via environment variables (CLI flag wins):

```bash
CRAWLER_VERBOSE=1 uv run python -m crawler.cli configs/template.yaml
CRAWLER_DEBUG_SAVE=1 uv run python -m crawler.cli configs/template.yaml
```

Acceptable values: `1`, `true`, `yes`, `on`.

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
| `url_range`   | Auto-generate URLs for seed stages                       |
| `headers`     | Extra HTTP headers (httpx only)                          |
| `extract`     | Extraction rule(s) — single object or list               |
| `resources`   | Fields this stage produces (for logging)                 |
| `filter`      | Filter rules to drop unwanted items                      |
| `dedup_by`    | Dedup input by this field before fetching                |
| `debug_save`  | Override global `--debug-save` for this stage (`true`/`false`) |
| `qb_send`     | Send extracted magnets to qBittorrent                    |
| `category`    | Override the global `qb.category` for this stage         |
| `concurrency` | Max concurrent fetches (default: playwright=3, httpx=10) |
| `delay`       | Seconds to wait after each fetch                         |
| `retry`       | Retry policy (both playwright and httpx)                 |
| `security`    | Auto-click security check buttons (playwright only)      |
| `security_selector` | CSS selector of the security button to click        |

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

### Data flow

```
[Seed URLs] → Stage A → Stage B → Stage C → ... → qBittorrent
                    ↓           ↓
              Field A_1     Field B_1
              Field A_2     Field B_2
                              ...
```

Each stage receives items from its `input` stage (or seed URLs when `input` is omitted), fetches each item's URL, extracts new fields, merges upstream fields (non-`_` keys) into extracted results, and passes them downstream.

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
│   ├── extract.py     # Regex/CSS/XPath extraction + filter engine
│   ├── fetch.py       # Playwright + httpx fetchers
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
3. Optionally pass `-v` to debug extraction and filtering

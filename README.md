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
```

Compose sets `network_mode: host`, so `qb.url`'s `http://localhost:8080` reaches the host's qBittorrent directly — no YAML changes needed (Linux only).

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

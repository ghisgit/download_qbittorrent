# AGENTS.md

## Stack

- Python 3.12+, managed with **uv** (lockfile: `uv.lock`)
- Dependencies: `httpx`, `bs4` (beautifulsoup4), `lxml`, `playwright`, `playwright-stealth`, `pyyaml`
- Async throughout (asyncio)
- Linting: `ruff` (check + format)
- Type checking: `pyright`

## Setup

```bash
uv sync                            # install dependencies
playwright install chromium        # required for Playwright fetcher
```

## Entrypoint

The CLI entrypoint is `crawler.cli`:

```bash
uv run python -m crawler.cli configs/template.yaml
```

The standalone scripts `main.py` and `dmn.py` described in earlier versions were replaced by the generic crawler engine. To replicate their behavior, use the corresponding YAML configs (create them under `configs/`).

## Config-driven crawler engine

The `crawler/` package provides a config-driven crawler framework. Pipeline stages are defined in YAML.

Each YAML config defines:

- global `qb` / `browser` settings
- a sequence of `stages`, each with: fetcher (`playwright` or `httpx`), URL pattern, extraction rule (`regex`, `css`, `xpath`), retry policy, optional security-check handler, filter rules, and qBittorrent output flag.
- Stage output feeds into the next stage via `input`; upstream fields (non-`_` keys) are automatically merged into downstream items.
- Any stage with `qb_send: true` sends its collected magnet links to qBittorrent.

To add a new crawler: create a YAML file under `configs/` and run it with the CLI. See `configs/template.yaml` for the complete schema reference.

## CLI flags

```bash
uv run python -m crawler.cli -v configs/template.yaml     # detailed logging
uv run python -m crawler.cli --debug-save configs/template.yaml  # save HTML for debugging
```

- `-v` / `--verbose` — per-item fetch, extract, and filter decision logging
- `--debug-save` — writes downloaded HTML to `debug_*.html` files for offline inspection

## Lint, type check & test

```bash
uv run ruff check .                  # lint
uv run ruff format --check .         # formatting
uv run pyright .                     # type check
uv run pytest                        # tests
```

All commands must pass before committing.

## Important notes

- qBittorrent credentials/host are configured in YAML (`qb.url`, `qb.user`, `qb.password`). Edit the config file before running.
- The template config `configs/template.yaml` is for reference only — create your own config for actual crawling.
- Personal/user-specific configs should be placed in `user.yaml` (gitignored) at the project root.
- Playwright fetcher uses `headless: true` by default in production configs; set `browser.headless: false` for debugging.
- `.venv/`, `__pycache__/`, and `user.yaml` are gitignored.

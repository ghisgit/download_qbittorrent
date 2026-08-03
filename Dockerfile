FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY crawler ./crawler

RUN uv pip install --system .

RUN playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/work \
    && chown -R app:app /app

WORKDIR /app/work

ENTRYPOINT ["python", "-m", "crawler.cli"]

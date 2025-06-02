FROM python:3.12.2-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.6.7 /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src

COPY pyproject.toml .
RUN uv sync

COPY app ./app

CMD ["./.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0" , "--port", "8090"]
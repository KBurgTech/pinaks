FROM debian:trixie-slim AS validator

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/install-mustang-validator.sh /usr/local/bin/install-mustang-validator
RUN /usr/local/bin/install-mustang-validator /opt/pinaks/mustang

FROM ghcr.io/astral-sh/uv:0.11.12 AS uv

FROM python:3.14-slim-trixie

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        default-jre-headless \
        libharfbuzz-subset0 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --home-dir /app --shell /usr/sbin/nologin pinaks

COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=validator /opt/pinaks/mustang /opt/pinaks/mustang

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/README.md backend/manage.py backend/
COPY backend/src backend/src
RUN uv sync --frozen --no-dev --package pinaks-backend

ENV DJANGO_SETTINGS_MODULE=pinaks.settings.production \
    MUSTANG_CLI_JAR=/opt/pinaks/mustang/Mustang-CLI-2.23.0.jar \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

USER pinaks
EXPOSE 8000
CMD ["gunicorn", "--chdir", "backend", "--bind", "0.0.0.0:8000", "pinaks.wsgi:application"]

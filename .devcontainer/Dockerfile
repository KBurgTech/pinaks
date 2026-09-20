FROM mcr.microsoft.com/devcontainers/python:1-3.14-trixie

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        gettext \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

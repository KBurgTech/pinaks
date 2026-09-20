FROM ghcr.io/astral-sh/uv:0.11.12 AS uv

FROM mcr.microsoft.com/devcontainers/python:2-3.14-trixie

USER root

# The base image's optional Yarn APT source currently has no valid signing key.
# We install Node and pnpm through the official Dev Container Feature instead.
# The remaining packages are the only Debian runtime libraries WeasyPrint's wheels need.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install --yes --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

USER vscode

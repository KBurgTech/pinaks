FROM ghcr.io/astral-sh/uv:0.11.12 AS uv

FROM mcr.microsoft.com/devcontainers/python:2-3.14-trixie

USER root

# The base image's optional Yarn APT source currently has no valid signing key.
# We install Node and pnpm through the official Dev Container Feature instead.
# Install the WeasyPrint libraries plus the offline validator runtime and installer.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install --yes --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz-subset0 \
        default-jre-headless \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

COPY scripts/install-mustang-validator.sh /usr/local/bin/install-mustang-validator
RUN /usr/local/bin/install-mustang-validator /opt/pinaks/mustang

ENV MUSTANG_CLI_JAR=/opt/pinaks/mustang/Mustang-CLI-2.23.0.jar

USER vscode

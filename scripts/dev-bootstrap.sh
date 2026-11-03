#!/usr/bin/env bash
# Explicitly seed the configured development database; never run during startup.
set -euo pipefail

cd "$(dirname "$0")/.."
export PINAKS_BOOTSTRAP_ADMIN_USERNAME="${PINAKS_BOOTSTRAP_ADMIN_USERNAME:-devadmin}"
export PINAKS_BOOTSTRAP_ADMIN_EMAIL="${PINAKS_BOOTSTRAP_ADMIN_EMAIL:-devadmin@example.test}"
if [[ -z "${PINAKS_BOOTSTRAP_ADMIN_PASSWORD:-}" ]]; then
    read -r -s -p 'Development admin password: ' PINAKS_BOOTSTRAP_ADMIN_PASSWORD
    printf '\n' >&2
fi
export PINAKS_BOOTSTRAP_ADMIN_PASSWORD

uv run python backend/manage.py migrate
uv run python backend/manage.py bootstrap_admin

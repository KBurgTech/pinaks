#!/usr/bin/env bash
# Run inside the dev container, or with a configured PostgreSQL connection.
set -euo pipefail
set -m

cd "$(dirname "$0")/.."
uv run python backend/manage.py migrate

server_pids=()
cleanup() {
    trap '' INT TERM
    for pid in "${server_pids[@]}"; do
        kill -TERM -- "-$pid" 2>/dev/null || true
    done
    wait || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

uv run python backend/manage.py runserver 0.0.0.0:8000 &
server_pids+=("$!")
corepack pnpm --filter @pinaks/web dev --host 0.0.0.0 &
server_pids+=("$!")

echo 'Development UI: http://localhost:5173 — press Ctrl+C to stop.'
wait -n "${server_pids[@]}"

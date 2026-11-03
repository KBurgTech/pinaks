# Pinaks

Pinaks is the planned web-based successor to Numus. This repository currently contains only the development scaffold: framework configuration, quality tooling, CI, and the agreed module boundaries. Product functionality has intentionally not been implemented.

See [`docs/TARGET_ARCHITECTURE.md`](docs/TARGET_ARCHITECTURE.md) for the accepted architecture.

## Stack

- Python 3.15, Django 6.1, Django REST Framework, PostgreSQL 18
- React 19, TypeScript, Vite, shadcn/ui, Base UI, Tailwind CSS
- `uv` for Python; `pnpm` for TypeScript
- pytest, Ruff, mypy, Vitest, Testing Library, ESLint, Prettier

## Layout

```text
backend/          Django configuration and domain-boundary packages
frontend/         React application shell
docs/             Architecture
.devcontainer/    Reproducible development environment
.github/          CI and repository automation
```

The backend domain packages are deliberately empty placeholders until behavior is introduced test-first.

## Setup

The recommended path is to open the repository in a dev-container capable editor. The container installs locked dependencies and starts PostgreSQL automatically.

For a local setup, install Python 3.15, uv 0.13.6, Node.js 24 LTS, pnpm 12.5.1, and PostgreSQL 18:

```bash
uv sync --all-packages --all-groups
corepack pnpm install --frozen-lockfile
make check
```

The project requires uv 0.13.x. If an existing dev container reports a uv version
mismatch, rebuild the container to pick up the pinned version. Restarting it alone
does not update installed tools.

Useful commands:

- `make install` — install locked dependencies
- `make test` — run backend and frontend tests
- `make lint` — run Ruff and ESLint
- `make typecheck` — run mypy and TypeScript checks
- `make build` — validate Django and build the frontend
- `make check` — run all local quality gates

Copy `.env.example` to `.env` only when local overrides are needed. Never commit credentials, personal data, invoice artifacts, database dumps, or legacy migration exports.

## Status

Scaffolding only. There are no customer, catalog, billing, authentication, document, migration, or other product workflows yet.

Account administration and optional OIDC setup: [docs/ACCOUNTS.md](docs/ACCOUNTS.md).

## Development server

After installing dependencies, run:

```bash
make dev
```

This applies database migrations and starts Django and Vite together. Open
<http://localhost:5173>; Vite proxies API and account requests to Django. Press
Ctrl+C to stop both servers. If either server exits, the other stops too.

Run this inside the dev container, where PostgreSQL is already running. For a
local setup, start PostgreSQL first and export `DATABASE_URL` with your local
connection URL (the example's `db` hostname is for the dev container). The launcher
uses environment variables; it does not load `.env` into your local shell.
The launcher requires Bash 4.3 or newer.

To seed a local development administrator, run this once before signing in:

```bash
make dev-bootstrap
```

This applies migrations and prompts for a password without echoing it. Sign in as
`devadmin` (email `devadmin@example.test`). Django's password validation applies.
The command uses the same database environment as `make dev`; run it inside the
dev container or configure `DATABASE_URL` first. It does not load `.env`.

Override the defaults with `PINAKS_BOOTSTRAP_ADMIN_USERNAME` and
`PINAKS_BOOTSTRAP_ADMIN_EMAIL`. For noninteractive use, supply
`PINAKS_BOOTSTRAP_ADMIN_PASSWORD` through the environment. Do not commit passwords.
Repeating the command preserves an existing protected administrator and its
password; it does not reset credentials or promote an existing ordinary user.

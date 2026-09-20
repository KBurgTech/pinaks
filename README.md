# Pinaks

Pinaks is the planned web-based successor to Numus. This repository currently contains only the development scaffold: framework configuration, quality tooling, CI, and the agreed module boundaries. Product functionality has intentionally not been implemented.

See [`docs/TARGET_ARCHITECTURE.md`](docs/TARGET_ARCHITECTURE.md) for the accepted architecture.

## Stack

- Python 3.14, Django 6.1, Django REST Framework, PostgreSQL 18
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

For a local setup, install Python 3.14, uv, Node.js 24 LTS, pnpm 12.5.1, and PostgreSQL 18:

```bash
uv sync --all-packages --all-groups
corepack pnpm install --frozen-lockfile
make check
```

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

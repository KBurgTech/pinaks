.PHONY: install lint format-check typecheck test build check backend-dev frontend-dev

install:
	uv sync --all-packages --all-groups
	corepack pnpm install --frozen-lockfile

lint:
	uv run ruff check backend
	corepack pnpm --filter @pinaks/web lint

format-check:
	uv run ruff format --check backend
	corepack pnpm --filter @pinaks/web format:check

typecheck:
	uv run mypy backend/src backend/tests
	corepack pnpm --filter @pinaks/web typecheck

test:
	uv run pytest backend
	corepack pnpm --filter @pinaks/web test

build:
	uv run python backend/manage.py check --settings=pinaks.settings.test
	corepack pnpm --filter @pinaks/web build

check: lint format-check typecheck test build

backend-dev:
	uv run python backend/manage.py runserver 0.0.0.0:8000

frontend-dev:
	corepack pnpm --filter @pinaks/web dev --host 0.0.0.0

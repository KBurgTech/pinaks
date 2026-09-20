.PHONY: install api-client api-client-check lint format-check typecheck test build check backend-dev frontend-dev

install:
	uv sync --all-packages --all-groups
	corepack pnpm install --frozen-lockfile

api-client:
	uv run python backend/manage.py spectacular --settings=pinaks.settings.test --file backend/schema/openapi.json --format openapi-json --validate
	corepack pnpm --filter @pinaks/web api:generate

api-client-check:
	@schema_check=$$(mktemp); \
	trap 'rm -f "$$schema_check"' EXIT; \
	uv run python backend/manage.py spectacular --settings=pinaks.settings.test --file "$$schema_check" --format openapi-json --validate; \
	diff -u backend/schema/openapi.json "$$schema_check"
	corepack pnpm --filter @pinaks/web api:check

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

check: api-client-check lint format-check typecheck test build

backend-dev:
	uv run python backend/manage.py runserver 0.0.0.0:8000

frontend-dev:
	corepack pnpm --filter @pinaks/web dev --host 0.0.0.0

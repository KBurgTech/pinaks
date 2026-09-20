# Contributing

Read `AGENTS.md` and the target architecture first. For behavior changes: write and observe a failing test, implement the minimum, refactor green, then run `make check`.

Use `uv add --package pinaks-backend` for backend dependencies and `pnpm --filter @pinaks/web add` for frontend dependencies. Commit lockfile changes and justify new production dependencies.

Generate and commit Django migrations. Test important constraints and transactions against PostgreSQL. Never use production or customer-derived data in tests.

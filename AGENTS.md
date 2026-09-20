# Pinaks agent instructions

## Architecture

- Treat `docs/TARGET_ARCHITECTURE.md` as the accepted baseline. Surface conflicts before changing it.
- Keep a Django modular monolith, same-origin React client, and PostgreSQL. Do not introduce microservices, browser JWT storage, a runtime plugin system, or a second application API.
- Keep business rules in backend application/domain services. Views and serializers translate transport concerns; React never owns authoritative billing calculations.
- Respect module ownership and use public service boundaries instead of mutating another module's models.
- Issued billing records and artifacts are immutable. Use `Decimal` for money and database constraints for critical invariants.
- Keep English and German complete together, using stable language-neutral codes.
- Justify every new production dependency.

## Mandatory test-driven development

Use red-green-refactor for every behavior change:

1. Write the smallest test expressing the next behavior or reproducing the defect.
2. Run it and confirm it fails for the expected reason.
3. Add only enough product code to make it pass.
4. Run the focused test, then the affected suite.
5. Refactor while tests stay green.

Never add product implementation first and tests afterward. Every bug fix starts with a failing regression test. Documentation, formatting, dependency metadata, and non-behavioral configuration are exempt, but their validation must still run.

Prefer public behavior over private implementation details. Use integration tests for database constraints, transactions, permissions, API contracts, issuance, and adapter boundaries. Mock only external systems or time/randomness boundaries.

## Tooling

- Run Python commands through `uv run`; use `uv add`/`uv remove` and commit `uv.lock`.
- Use `pnpm` exclusively for TypeScript; commit `pnpm-lock.yaml`.
- Use focused tests during TDD and `make check` before handoff.
- Do not hand-edit generated clients or lockfiles.
- Create migrations for model changes; never rewrite an applied migration without explicit approval.

## Quality and safety

- Keep Python typed and TypeScript strict; avoid `Any` and unsafe casts without documented boundaries.
- Keep secrets, personal data, invoices, databases, and migration exports out of Git and logs.
- Preserve CSRF, backend authorization, safe template rendering, and same-origin session authentication.
- Use stable API error codes; localized messages are presentation text.

## Verification

For cross-cutting work run:

```bash
make lint
make typecheck
make test
make build
```

Report checks that could not run. In review, flag behavior without prior failing tests, invoice mutation after issuance, float money, client-authoritative totals, UI-only permissions, sensitive logging, and unjustified architecture expansion.

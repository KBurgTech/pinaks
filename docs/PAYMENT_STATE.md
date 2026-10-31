# Payment state

Admin and Company Member users can mark an issued invoice paid or unpaid from the invoice list or detail view. Read-Only users can inspect its state. The same session-authenticated, CSRF-protected API commands are available at:

- `POST /api/v1/invoices/{id}/mark-paid/`
- `POST /api/v1/invoices/{id}/mark-unpaid/`

Commands serialize on the invoice lock. Repeating the current state returns the invoice without changing its timestamp or adding an audit event. A real transition records `payment_changed_at`, `payment_changed_by_id`, and an immutable `billing.invoice_payment_changed` event. Draft and issuing invoices return `409 invalid_payment_transition`.

Payment updates leave invoice content, totals, version, snapshot, lines, and original artifact bytes and hashes unchanged. Payment status is separate from the frozen legal document. No document is regenerated.

Overdue is derived: the invoice must be issued, unpaid, and have a due date strictly before the current application-local date. Due today, missing due date, draft, and issuing invoices are not overdue. The domain predicate accepts an explicit date for deterministic tests. A future cancelled lifecycle will also be excluded; creating cancellation documents belongs to issue #35.

The invoice list supports `payment_status=PAID|UNPAID` and `overdue=true|false`, including combined filters. Both UI languages use the same stable API values. Provider integrations remain outside this manual payment workflow.

Validation: `uv run pytest backend/tests/test_payments.py backend/tests/test_billing.py`, `corepack pnpm --filter @pinaks/web exec vitest run src/invoices/payment-status.test.tsx src/invoices/invoice-page.test.tsx`, and `make check`.

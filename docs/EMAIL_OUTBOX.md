# Invoice email snapshots

Admins manage plain-text email templates at `/app/email-templates/`. Each save
creates a new numbered language version. Publication requires complete English
and German subject/body variants. Published versions cannot be updated or deleted,
including through bulk SQL. Only `{{ invoice_number }}` is substituted; arbitrary
template expressions and multiline subjects are rejected. Template content is
rendered as text in the administration UI.

Admin and Company Member users can open the invoice email dialog for issued
invoices, including original documents retained after cancellation. The current
customer email and correspondence language supply editable defaults; neither the
UI language nor the invoice's frozen document language changes those defaults.
A separate payer address can be entered explicitly. Read-Only users cannot queue
emails or read these defaults. Template administration is Admin-only.

`POST /api/v1/invoices/{id}/send/` accepts `template_id`, `language`, `recipients`
(one to twenty distinct addresses), `idempotency_key`, and optional `scheduled_at`
(an ISO timestamp). Billing locks the invoice, checks its lifecycle, verifies all
three original stored artifacts, then calls the public notification service.
The outbox freezes the selected published template version, rendered subject/body,
recipients, language, invoice and PDF identities, attachment SHA-256, sender key,
creation time, creator, and schedule. Existing customer or template edits cannot
change a queued snapshot. No generated PDF replaces the original artifact.

The UUID primary key is the stable logical message identity for future delivery.
The invoice plus idempotency key is unique. An identical command returns its
original receipt, even after source edits or subsequent artifact degradation;
a changed command with the same key returns `email_conflict` (HTTP 409).
Concurrent requests serialize on the invoice. The dialog retains its command
through failed requests and close/reopen within the mounted invoice screen.
After a page reload, callers must retain their command identity to retry safely.
An explicit new identity represents a separate message, rather than a retry.

The database protects all outbox columns except `delivery_state` from updates and
prohibits deletion. Insert triggers require an issued invoice, matching PDF
identity/hash, and a published template version in the selected language.
File integrity remains checked by application services because files and database
rows do not share a transaction. Delivery must recheck the stored attachment
before handing it to a provider. The send response exposes a receipt and queue
state; correspondence bodies, recipients, storage paths, and sender configuration
are omitted. Responses with defaults/receipts use `Cache-Control: no-store`.
Audit events contain identifiers and language/version metadata, never recipients,
subjects, bodies, or secrets.

`EMAIL_SENDER_KEY` selects a deployment-defined sender configuration (default:
`default`). It is a non-secret key, not an SMTP address or credential. This task
creates durable `queued` outbox records only. SMTP delivery, provider configuration,
attempt history, worker claiming, and delivery retries belong to issue #37; no
worker job is enqueued until that delivery handler exists. Sending is always an
explicit user command, never an implicit consequence of issuance.

Validation: `uv run pytest backend/tests/test_email_outbox.py` and
`corepack pnpm --filter @pinaks/web exec vitest run src/notifications/email.test.tsx`.

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
`default`). It is a non-secret key, not an SMTP address or credential. The outbox and delivery handler are implemented by issues #36 and #37.
A matching worker job is enqueued atomically with each snapshot. Sending is always an
explicit user command, never an implicit consequence of issuance.

Validation: `uv run pytest backend/tests/test_email_outbox.py` and
`corepack pnpm --filter @pinaks/web exec vitest run src/notifications/email.test.tsx`.

## SMTP delivery

Issue #37 adds the `notifications.deliver` worker handler. Queuing a snapshot now
creates its work item in the same transaction, at the frozen schedule. An upgrade
migration also schedules existing queued snapshots without duplicating work.
Run the existing `run_worker` command; no separate broker or process is required.

`EmailSender` accepts a provider-neutral immutable message. The SMTP adapter uses
only deployment settings: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
`SMTP_PASSWORD`, `SMTP_FROM_EMAIL` (a bare mailbox address), `SMTP_USE_TLS`
(STARTTLS, default true), `SMTP_USE_SSL` (implicit TLS, default false), and
`SMTP_TIMEOUT` (seconds, greater than zero and at most 30; default 10).
TLS modes are mutually exclusive. Certificates use the system trust store;
STARTTLS failure never falls back to plaintext. Credentials are neither persisted
nor returned in the API. `EMAIL_SENDER_KEY` remains the frozen non-secret sender
selection; changing that key makes older unmatched snapshots fail closed.
No new production dependency is needed: SMTP, MIME and TLS use the standard library.

Each transmission verifies the original stored attachment bytes and frozen hash.
It sends a plain-text UTF-8 body and the original PDF with the snapshot's subject,
recipients and language. `Content-Language` follows the snapshot language;
`Date` follows snapshot creation and `Message-ID` is always
`<outbox-uuid@pinaks.invalid>`, including retries. The reserved domain makes the
identity independent of mutable deployment settings. SMTP acceptance is reported
as `sent`; it does not prove inbox delivery.

Attempts preserve start/end timestamps, an outcome, a stable failure code and
numeric SMTP response code where available. Raw SMTP response text is discarded.
Completed attempts cannot be changed or deleted at the database boundary. Audit
records contain only message/attempt identifiers, outcome and safe failure code.

Explicit temporary rejection and connection failures before handoff use the
worker's bounded exponential retry schedule. Permanent rejection, invalid
configuration, damaged artifacts and partial recipient acceptance stop delivery.
Exhaustion stops the logical message. A partial acceptance never retries the
whole recipient list automatically.

A PostgreSQL session advisory lock serializes workers for each logical message,
even when a worker lease expires. This requires direct PostgreSQL connections or
session pooling; transaction pooling is incompatible. A committed `sending`
marker precedes every external handoff. A crash with that marker or connection
loss during SMTP handoff produces `delivery_unknown` and stops automatic retries.
The worker reconciles expired final leases as well as ordinary retries. These
rules favor avoiding silent duplicate delivery; they cannot provide exactly-once
SMTP delivery. After an unknown/partial outcome, an operator must check the mail
server and recipients before explicitly queuing a new message identity. A stable
Message-ID alone cannot make SMTP idempotent.

Admin and Company Member users can inspect state and attempts at
`GET /api/v1/invoices/{id}/emails/` and in the invoice's English/German delivery
history. The response includes the next scheduled attempt but excludes recipients,
body, subject, storage keys and provider configuration, and uses `no-store`.
Read-Only and inactive users are denied. The UI refreshes history every ten seconds
and explains unknown outcomes before a user sends again.

Validation uses a local fake SMTP server for acceptance, temporary/permanent
rejection, timeout, connection loss and acknowledgement loss, plus PostgreSQL
concurrency, crash, immutability, upgrade and API permission tests:
`uv run pytest backend/tests/test_email_delivery.py backend/tests/test_email_outbox.py backend/tests/test_worker.py`.

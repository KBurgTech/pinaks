# Partial credit notes

`POST /api/v1/invoices/{id}/credit-notes/` creates a separate `CREDIT_NOTE`
review draft for an issued `STANDARD` invoice. Admin and Company Member roles
may invoke it through the same session/CSRF boundary as issuance.

The command requires a reason, an idempotency key, and distinct original line
positions with explicit positive quantities and nonnegative unit prices. The
original discount, service dates, description, tax treatment, and custom data
are copied. Unit prices cannot exceed the original. Totals are calculated by
the existing backend Decimal policy. Zero-value documents are rejected.

## Reservations and concurrency

Creation reserves quantities and net, tax, and gross amounts per original
line. All credit drafts, issuing credits, and issued credits count toward the
limits. A reduced price still reserves its selected quantity. This conservative
policy can leave an uncredited monetary remainder when all quantities have
been reserved; it never permits cumulative quantities or amounts to exceed
the original. Cent rounding can also limit further splits.

Commands lock the original invoice. PostgreSQL also locks the original when
validating a reservation, enforces command uniqueness, checks cumulative line
limits, and protects reserved content and lines against mutation or deletion.
A full cancellation reservation and partial credit reservations are mutually
exclusive. Draft reservations have no automatic expiry or release operation.
Review quantities and prices carefully before creating a draft.

An identical key and normalized allocation returns the existing credit even
after issuance; changing the reason or selection with that key returns
`invalid_credit_note`. Conflicting reservations also return this stable code.
Invalid input returns the standard validation envelope. After an uncertain
network outcome, retry the same command rather than allocating a new key.

## Issuance and evidence

The invoice UI opens the linked draft with the exact backend total, reason,
and original navigation. Its content cannot be edited. Authorized users issue
it with optimistic version checking and the ordinary idempotent issuance
command. It uses a published template in the original document language.

Issuance copies the original frozen seller, customer, recipient, tax profile,
and custom-field labels, then projects the selected lines and recalculated
tax groups. EN 16931 mapping emits type 381 with positive amounts, the original
invoice number/date, and the reason. PDF output identifies the document as a
credit note / Gutschrift and includes the same reference and reason.

The original invoice remains issued. Its content, payment history, snapshots,
and stored artifact bytes are unchanged. Credit issuance does not mark the
original paid or cancelled. Both documents keep authorized original-byte
downloads and bidirectional relationship navigation. Full cancellation is
covered separately; corrected replacements remain tracked by issue #98.

No production dependencies are added. Tests cover reservation races,
permission/CSRF checks, database bypasses, immutable content, retries, frozen
issuance, bilingual UI, and real taxable/exempt EN/DE XML and PDF/A validation.

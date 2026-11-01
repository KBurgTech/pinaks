# Corrected replacement invoices

Issue #98 completes the focused correction slices of #35. A replacement is a new
invoice following a completed full cancellation, using positive quantities and
amounts and EN 16931 type **380**. It is not a type 384 document revising an active
receivable. This follows the credit-then-new-invoice process described by
[e-Rechnung](https://www.erechnung.gv.at/erb/en_GB/content_correctiveinvoice) and the
[OpenPeppol document type mapping](https://docs.peppol.eu/poacc/billing/3.0/bis/).

## Command and preconditions

An active Admin or Company Member calls `POST /api/v1/invoices/{id}/correct/` with a
nonblank `reason` (maximum 500 characters) and `idempotency_key` (maximum 100).
The source must be a cancelled standard invoice with an issued full cancellation.
Both documents must have healthy stored artifacts. Pending cancellations and
partial credits, including fully allocated partial credits, do not qualify.
This avoids introducing a second receivable while the original remains active.

The command creates one `REPLACEMENT` draft linked directly to the original. It
copies the original recipient, custom values, language and lines as starting
content, resets payment state to unpaid, uses today's issue date and leaves the
due date unset. The existing draft editor and backend Decimal calculations allow
correction of recipient, lines, dates, language and custom values. Current seller,
customer, tax configuration and published templates are checked again at issuance.
This differs from reversal documents, which freeze the original parties and tax.

The original invoice and cancellation, payment metadata, snapshots, artifact rows
and bytes are preserved. Replacement creation does not perform refunds, transfer
payments or assert that a paid original has been refunded. Financial settlement of
a previously paid invoice remains a separate administrative responsibility.

## Identity and evidence

An identical command returns the existing draft or issued replacement, including
after edits. Another identity or reason conflicts with `invalid_replacement`.
An aggregate lock and PostgreSQL uniqueness serialize competing commands.
Replacement identity, original link and reason cannot be changed or deleted,
including while content is still editable. There is no reservation release or
second replacement for the same source. This initial flow accepts standard source
invoices; it does not offer replacement chains or cancellation of replacements.

Issuance rechecks original/cancellation artifact health and requires an issue date
on or after the original date. Ordinary optimistic version and issuance identity
checks apply. A new number and snapshot freeze corrected content, original invoice
number/date and the reason. XML maps the original to BG-3 (BT-25/BT-26) and the
reason to BT-22. The PDF adds an escaped bilingual replacement heading, reference
and reason independently of the selected template. The normal durable artifact
worker validates and finalizes the replacement idempotently.

The UI requires a reason, explains the new receivable, opens the linked draft for
review, and provides original/related navigation for readers. Failed submissions
retry the same command identity. Backend permissions and CSRF remain authoritative.
The audit event records document identifiers without copying the reason.

## Verification

`test_replacements.py` covers public API and service behavior, edits, issuance,
original preservation, permissions, CSRF, evidence health, duplicate commands,
concurrent creation and database bypasses. `test_cancellation_artifacts.py` checks
real taxable/exempt EN/DE replacement XML/PDF-A conformance and embedded bytes.
Frontend tests cover bilingual reason/confirmation, retries, navigation and edit
capabilities. No production dependency is added.

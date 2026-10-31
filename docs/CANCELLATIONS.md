# Full invoice cancellations

Full cancellation is the first focused slice of #35, tracked by #96. Partial credit
notes (#97) and corrected replacements (#98) remain separate work because their
amount limits and receivable semantics differ. No new production dependency is needed.

## Commands and evidence

An active Admin or Company Member calls `POST /api/v1/invoices/{id}/cancel/` with a
nonblank `reason` (up to 500 characters) and `idempotency_key` (up to 100 characters).
Only an issued standard invoice with healthy stored evidence can be cancelled.
The command creates one linked, noneditable full cancellation draft. The original
invoice, its lines, snapshot, payment history and artifact bytes remain unchanged.
Repeated identical commands return the same draft; a different reason or identity
conflicts. The aggregate lock and database uniqueness prevent concurrent duplicates.

The draft is a review step: creating it does not cancel the original. The UI shows
the full credit amount and reason, links both documents, and offers issuance using
the original logical template. Issuance uses the currently published bilingual
version of that template. Missing publication prevents issuance. Full cancellation
drafts cannot be edited, deleted or changed into partial credits.

Issuance freezes seller, customer, recipient, lines, tax treatment and custom-field
metadata from the original snapshot, even if current master data has changed. It
assigns a new invoice number and freezes the cancellation reason and original
invoice number/date. Full cancellation uses EN 16931 type **381**, with positive
quantities and amounts: the document type supplies the credit direction. Original
references map to BG-3 (BT-25/BT-26), and the reason maps to the invoice note BT-22.
The renderer adds the cancellation heading, reference/date and escaped reason to
the visible document without depending on template authors to include them.

References: [OpenPeppol billing and credit-note semantics](https://docs.peppol.eu/poacc/billing/3.0/bis/)
and [GS1 Germany document types](https://www.ecr.de/weiterbildung-events/media-hub/dokumententypen-rechnungen-en-16931/).

Only after the worker validates and durably stores all cancellation artifacts does
one transaction mark the cancellation `ISSUED` and the original `CANCELLED`.
Generation failures leave the original `ISSUED` and the cancellation recoverable in
`ISSUING`. The database requires an issued related cancellation for this transition
and prevents reverting a cancelled original. Its original PDF, XML and report remain
downloadable under the same authorization/hash checks and remain included in
integrity verification. Cancelled invoices are not overdue and reject payment changes.
Existing payment records are preserved; cancellation does not perform a refund.

Audit events record actor and document identifiers without copying the reason or
recipient details. API invoice representations expose only the relationship IDs,
reason and original template ID, never the private snapshot or command key.

## Verification

`backend/tests/test_cancellations.py` exercises commands, permissions, CSRF,
idempotency, concurrency, database immutability, source-data changes, finalization
and original downloads. `backend/tests/test_cancellation_artifacts.py` runs real
Mustang XML/PDF-A validation for taxable/exempt English and German documents,
checks visible references/reasons and verifies the exact embedded XML.
`frontend/src/invoices/cancellation.test.tsx` covers bilingual confirmation, required
reason, retries, reader navigation and the explicit issuance action.

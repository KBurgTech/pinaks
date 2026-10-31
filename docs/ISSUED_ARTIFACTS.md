# Issuance persistence

`documents.generate` is registered with the database worker. It locks the invoice,
uses only its frozen snapshot to generate and validate the hybrid PDF/XML, and
publishes PDF, XML, validation evidence, and a manifest as one private bundle.
Only after publication and hash verification does one database transaction insert
all three artifact records and call Billing's finalization service. Billing emits
one `billing.invoice_issued` audit event and transitions `ISSUING` to `ISSUED`.
No additional production dependency is needed.

## Storage configuration

Set `ISSUED_DOCUMENT_ROOT` to a dedicated local persistent volume shared by web and
worker processes (default: `backend/issued-documents`). Do not expose it through a
web server or include it in container images. Artifact keys are opaque SHA-256
snapshot identities plus fixed artifact kinds. Direct download authorization and
ongoing integrity checks are delivered by issue #33.

Directories are private (`0700`); files are private (`0600`). The local filesystem
must support atomic directory rename and file/directory `fsync`. Generation writes
and syncs a temporary sibling directory before renaming and syncing its parent.
Published bundles are never overwritten by the application. Database constraints
and triggers protect artifact uniqueness, metadata immutability, completeness at
finalization, and the one-way issued lifecycle.

## Failure and recovery

- Before publication: no artifact records or lifecycle transition commit. A normal
  exception removes the temporary directory; a process kill can leave an unused
  `.issuance-*` directory. Such directories are never treated as issued evidence.
- After publication but before database commit: the complete published bundle
  remains. Retry verifies and reuses its original bytes and generation metadata;
  it does not regenerate the PDF or allocate another invoice number.
- After database commit but before worker completion: retry sees `ISSUED` and does
  no further work. Concurrent handlers serialize on the invoice row, including
  handlers with expired worker leases.
- Missing/corrupt published bundles stop finalization. Never overwrite or silently
  repair them. Preserve evidence and investigate storage before retrying.
- The existing worker records only `handler_error`, never exception text, raw
  validator output, or document data. Its bounded retry/backoff and terminal state
  apply; the invoice remains `ISSUING` when generation does not complete. Validation
  reports for successful issuance remain in the protected report artifact.

PostgreSQL and this volume form one recoverable dataset. Coordinated encrypted
backup/restore, cleanup policy, and deployment manifests belong to issue #41.
Do not remove published bundles merely because a database row is absent: this is
an expected recoverable intermediate state.

## Verification

The issuance integration suite uses PostgreSQL and the pinned Mustang/veraPDF
validator. It covers exact hashes/sizes, replay, simultaneous handlers, private
bundle publication, interruptions on either side of rename, database failure after
publication, storage failure, and direct database immutability violations.

# Validated hybrid invoice generation

`pinaks.apps.e_invoicing.generation.HybridInvoiceGenerator.generate(snapshot)`
projects one frozen schema-v1 billing snapshot into final Factur-X EN 16931 bytes.
It validates XML with Mustang, renders the frozen template through WeasyPrint,
packages the exact XML through factur-x, then validates the hybrid PDF with
Mustang's embedded business-rule and veraPDF validators. No successful result is
returned unless both validations pass.

The immutable result contains the final PDF, separately retrievable exact XML,
both complete machine-readable validator reports (including validator versions),
standard/profile/specification identifiers and visual renderer/template provenance.
It does not persist files or change billing lifecycle state; issue #32 owns that
recoverable file/database transition.

A supplemental package integrity check requires one `factur-x.xml` attachment,
the packager's `/Data` relationship and matching filename metadata, and exact
identity with the separately returned XML. This closes a gap demonstrated by
negative tests: Mustang 2.23.0 accepts a changed attachment relationship and can
accept a different, independently valid embedded invoice. pypdf is now an explicit
production dependency for this inspection; it was already installed transitively
by factur-x. No new library is introduced into the runtime environment.

`GenerationError` exposes a stable code and retry flag. Invalid snapshots,
rendering input, packaging and conformance failures are non-retryable. Validator
execution/timeout failures and renderer storage I/O failures are retryable.
Validation failures retain their report as restricted evidence. Error messages
contain only codes; callers must not log exception chains or validation reports,
which can contain invoice data. Correcting a non-retryable issuance must follow
billing's immutable snapshot rules rather than editing frozen evidence.

The conformance tests cover taxable/exempt snapshots in English and German,
byte-identical attachment extraction, corrupt PDFs, altered XML totals, changed
attachment metadata and substituted XML. Run them with the pinned local toolchain:

```bash
MUSTANG_CLI_JAR=/opt/pinaks/mustang/Mustang-CLI-2.23.0.jar \
  uv run pytest backend/tests/test_hybrid_generation.py
```

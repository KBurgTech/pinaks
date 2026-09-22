# EN 16931 and ZUGFeRD toolchain

## Decision

Pinaks targets the ZUGFeRD/Factur-X EN 16931 profile using three narrow internal
interfaces in `pinaks.apps.e_invoicing.contracts`:

- `EInvoiceSerializer` maps a canonical, immutable Pinaks snapshot to CII XML.
- `HybridPdfPackager` embeds that XML in an existing PDF/A-3 document.
- `EInvoiceValidator` returns a library-neutral, machine-readable validation result.

The selected serializer and packager are `factur-x` 6.x (BSD-3-Clause). Version 6.8
is locked by `uv.lock`. It is maintained, ships the current Factur-X schemas, supports
EN 16931 CII generation, and packages an XML attachment without exposing its data
model to billing. Pinaks disables its optional HTTP Schematron integration: XSD checks
and packaging are local, while final conformance is decided by Mustang.

The authoritative validation boundary is Mustang CLI 2.23.0 (Apache-2.0). Its shaded
JAR includes the EN 16931/ZUGFeRD Schematron rules and veraPDF. The installer pins the
release and verifies SHA-256 before placing it in the image. The adapter starts Java in
headless mode, captures Mustang's XML report, and treats any reported error as invalid
even if an outer summary is permissive.

WeasyPrint 67.x, already part of the architecture baseline, renders the visual source
with its `pdf/a-3u` variant. `factur-x` preserves the PDF/A data while adding the CII
attachment and Factur-X XMP extension metadata.

All invoice-generation and validation steps run without network access. Network access
is used only while dependencies and the checksum-pinned validator are installed during
an image or CI build.

## Reproducible proof

`backend/tests/test_e_invoicing.py` generates XML and a hybrid PDF from the non-personal
fixture in `backend/tests/fixtures/e_invoicing/canonical_invoice.json`. It proves:

- current-profile XML generation and XSD validation;
- embedding the exact XML payload into a PDF/A-3 source;
- passing Mustang Schematron and veraPDF validation for XML and hybrid PDF;
- expected failures for inconsistent totals (`BR-CO-16`), inconsistent tax data
  (`BR-S-08`), and broken PDF/A identification metadata.

The directory also retains generated representative XML, the two invalid XML fixtures,
and Mustang's machine-readable passing report. CI installs the same pinned JAR, runs the
proof tests, builds the production image, and validates the representative XML inside
that image with networking disabled.

For local runs outside the development container, install Java 11 or newer and run:

```bash
scripts/install-mustang-validator.sh /tmp/pinaks-mustang
MUSTANG_CLI_JAR=/tmp/pinaks-mustang/Mustang-CLI-2.23.0.jar make check
```

## Alternatives considered

- KoSIT Validator is an authoritative, well-maintained Apache-2.0 validation engine,
  but it needs a separately curated scenario bundle and does not validate PDF/A or
  ZUGFeRD container metadata. It remains suitable for a future XRechnung CIUS check.
- Direct use of veraPDF validates PDF/A but not CII business rules or the hybrid
  relationship. Mustang embeds veraPDF and produces one combined XML report.
- `factur-x` Schematron validation was rejected as the final gate because current
  releases call a Saxon HTTP server. That would violate offline invoice generation and
  add an unnecessary runtime service.
- Hand-written CII XML and PDF attachment logic was rejected because it would duplicate
  mature standards mappings and metadata behavior with a much larger maintenance risk.

## Upgrade strategy

Upgrade one component at a time. Regenerate the representative and negative fixtures,
inspect rule/version changes in the retained report, run the proof suite and `make check`,
then build and validate the production image with `--network none`. A Mustang upgrade
requires updating both version and checksum in the installer and default adapter path.
A Factur-X upgrade goes through `uv add` so its transitive dependencies remain locked.
Never accept a changed validation result without reviewing the corresponding standard
or validator release notes.

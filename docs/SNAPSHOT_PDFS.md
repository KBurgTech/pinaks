# Frozen snapshot visual PDFs

`documents.snapshot_renderer.VisualDocumentRenderer` is the visual rendering boundary.
`WeasyPrintRenderer.render(snapshot)` returns PDF bytes, renderer identity/version,
and the frozen template version ID. It does not finalize issuance or claim PDF/A
conformance; packaging, validation and artifact persistence are subsequent tasks.

The input is billing's schema-version-1 issuance snapshot. HTML, CSS, language,
page settings and declared asset keys come from its exact published template copy,
never the latest template or current customer/company records. The billing issuance
service is responsible for selecting a published template before freezing it.

Templates receive `invoice`, `seller`, `customer`, `recipient` and bilingual
`labels.invoice`. `invoice.lines` contains the frozen lines; `invoice.exemption_wording`
selects only the document language's frozen wording. The existing `money` and `date`
filters format display values without recalculating authoritative totals. The
`invoice.tax_column_policy` value is also available. Mark optional tax columns with
`data-tax-column`; the frozen `hide` policy suppresses these elements. The grand
total and structured tax amounts stay unchanged. Only the supported A4 page setting
is accepted and enforced. Final documents contain no preview watermark.

The same constrained template syntax, output limits, resource allowlist, isolated
PDF process and timeout used for previews apply. Images must be declared controlled
assets belonging to the frozen template. Missing, resized, unsupported or corrupt
images cause final rendering to fail. WeasyPrint errors are captured inside the
worker so a partially rendered document is rejected. Failures expose the stable
`visual_render_failed` code, without embedding template data or storage paths.

No production dependency was added. PDF integration tests inspect text, page size,
page counts and metadata using the existing PDF toolchain dependencies; they avoid
pixel-perfect golden files.

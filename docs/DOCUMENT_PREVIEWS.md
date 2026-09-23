# Document previews

An Admin can preview the latest saved English or German template version from the document template editor. The optional draft invoice ID selects existing draft data; leaving it empty uses safe sample data. Save source changes before previewing. Preview output is marked as non-authoritative and is never used for issuance.

The template context contains only these fields:

| Name | Fields |
| --- | --- |
| `labels` | `invoice` |
| `seller` | `name` |
| `customer`, `recipient` | `name` |
| `invoice` | `number`, `issue_date`, `currency`, `subtotal`, `tax_total`, `grand_total`, `lines` |
| `line` within a line loop | `description`, `quantity`, `net_total`, `tax_total`, `gross_total` |

Use `{{ invoice.grand_total | money }}` for a localized amount, `{{ invoice.issue_date | date }}` for a localized date, and `{% for line in invoice.lines %}...{% endfor %}` for lines. One line loop is allowed. Missing variables fail preview creation. Values are escaped. The template cannot call functions, include other files, or access application objects.

Stored PNG and JPEG assets may be referenced as `<img src="asset:document-assets/...">` after adding their keys to the template version. The renderer embeds only declared stored assets. Remote URLs, arbitrary file paths, and other resource references fail. PDF rendering runs in a separate process with a 10 second limit. Template source, output, assets, and draft line counts have size limits.

Preview files use the `document-previews/` storage prefix and expire after 30 minutes. The authorized retrieval endpoint returns `Cache-Control: no-store` and a sandboxed content policy. Schedule `uv run python backend/manage.py cleanup_document_previews` at least hourly to remove expired files and metadata. Expired links stop working even before cleanup runs.

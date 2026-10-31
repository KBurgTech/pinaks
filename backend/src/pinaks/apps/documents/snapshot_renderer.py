"""Visual projection of frozen issuance evidence; no live invoice/configuration reads."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from importlib.metadata import version
from typing import Protocol

from django.core.files.storage import default_storage

from pinaks.apps.documents.models import DocumentAsset
from pinaks.apps.documents.renderer import (
    PreviewRenderError,
    render_preview_html,
    render_preview_pdf,
)


class SnapshotRenderError(ValueError):
    code = "visual_render_failed"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class VisualDocument:
    pdf: bytes
    renderer: str
    renderer_version: str
    template_version_id: int


class VisualDocumentRenderer(Protocol):
    def render(self, snapshot: Mapping[str, object]) -> VisualDocument: ...


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise SnapshotRenderError()
    return deepcopy(value)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise SnapshotRenderError()
    return value


def _assets(template: dict[str, object]) -> dict[str, tuple[str, bytes]]:
    keys = template.get("asset_keys")
    if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
        raise SnapshotRenderError()
    assets: dict[str, tuple[str, bytes]] = {}
    for asset in DocumentAsset.objects.filter(template_id=template.get("id"), key__in=keys):
        if asset.size > 2 * 1024 * 1024 or asset.content_type not in {"image/png", "image/jpeg"}:
            raise SnapshotRenderError()
        with default_storage.open(asset.key, "rb") as stored:
            payload = stored.read(2 * 1024 * 1024 + 1)
        if len(payload) != asset.size:
            raise SnapshotRenderError()
        assets[asset.key] = (asset.content_type, payload)
    if set(assets) != set(keys):
        raise SnapshotRenderError()
    return assets


class WeasyPrintRenderer:
    def render(self, snapshot: Mapping[str, object]) -> VisualDocument:
        try:
            return self._render(snapshot)
        except (PreviewRenderError, OSError, ValueError, TypeError, KeyError) as error:
            raise SnapshotRenderError() from error

    def _render(self, snapshot: Mapping[str, object]) -> VisualDocument:
        if snapshot.get("schema_version") != 1:
            raise SnapshotRenderError()
        invoice = _object(snapshot.get("invoice"))
        template = _object(snapshot.get("template"))
        profile = _object(snapshot.get("tax_profile"))
        language = _text(invoice.get("language"))
        if language not in {"en", "de"} or template.get("language") != language:
            raise SnapshotRenderError()
        if template.get("page_settings") != {"size": "A4"}:
            raise SnapshotRenderError()
        version_id = template.get("version_id")
        if not isinstance(version_id, int) or isinstance(version_id, bool) or version_id <= 0:
            raise SnapshotRenderError()
        lines = snapshot.get("lines")
        if not isinstance(lines, list) or not 1 <= len(lines) <= 200:
            raise SnapshotRenderError()
        invoice["lines"] = [_object(line) for line in lines]
        invoice["exemption_wording"] = profile.get(f"exemption_wording_{language}", "")
        invoice["tax_column_policy"] = profile.get("tax_column_policy")
        labels = {"invoice": "Rechnung" if language == "de" else "Invoice"}
        context: dict[str, object] = {"invoice": invoice, "labels": labels}
        for party in ("seller", "customer", "recipient"):
            context[party] = _object(snapshot.get(party))
        policy = profile.get("tax_column_policy")
        if policy not in {"show", "hide"}:
            raise SnapshotRenderError()
        page_css = "\n@page { size: A4 !important; }"
        if policy == "hide":
            page_css += "\n[data-tax-column] { display: none !important; }"
        source = _text(template.get("html"))
        if invoice.get("type") in ("CANCELLATION", "CREDIT_NOTE"):
            labels["invoice"] = "Stornorechnung" if language == "de" else "Cancellation invoice"
            if invoice.get("type") == "CREDIT_NOTE":
                labels["invoice"] = "Gutschrift" if language == "de" else "Credit note"
            labels["original"] = (
                "Ursprüngliche Rechnung" if language == "de" else "Original invoice"
            )
            labels["reason"] = "Grund" if language == "de" else "Reason"
            source = (
                "<h1>{{ labels.invoice }} {{ invoice.number }}</h1>"
                "<p>{{ labels.original }}: {{ invoice.original_reference.number }} "
                "({{ invoice.original_reference.issue_date | date }})</p>"
                "<p>{{ labels.reason }}: {{ invoice.correction_reason }}</p>" + source
            )
        html = render_preview_html(
            source,
            _text(template.get("css")) + page_css,
            language=language,
            context=context,
            assets=_assets(template),
            preview=False,
        )
        return VisualDocument(
            pdf=render_preview_pdf(html, strict=True),
            renderer="WeasyPrint",
            renderer_version=version("weasyprint"),
            template_version_id=version_id,
        )

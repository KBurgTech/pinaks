"""Preview application operations and allowlisted projection of draft data."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from pinaks.apps.accounts.models import User
from pinaks.apps.billing.models import Invoice, InvoiceLine
from pinaks.apps.configuration.models import CompanyProfile
from pinaks.apps.documents.models import DocumentAsset, DocumentTemplateVersion, PreviewArtifact
from pinaks.apps.documents.renderer import (
    PreviewRenderError,
    render_preview_html,
    render_preview_pdf,
)

PREVIEW_LIFETIME = timedelta(minutes=30)


def _context(*, language: str, invoice: Invoice | None) -> dict[str, object]:
    labels = {"en": {"invoice": "Invoice"}, "de": {"invoice": "Rechnung"}}[language]
    company = CompanyProfile.objects.first()
    seller = {"name": company.legal_name if company else "Sample Seller"}
    if invoice is None:
        return {
            "labels": labels,
            "seller": seller,
            "customer": {"name": "Sample Customer"},
            "recipient": {"name": "Sample Recipient"},
            "invoice": {
                "number": "PREVIEW",
                "issue_date": timezone.localdate(),
                "currency": "EUR",
                "subtotal": Decimal("100.00"),
                "tax_total": Decimal("19.00"),
                "grand_total": Decimal("119.00"),
                "lines": [
                    {
                        "description": "Sample service",
                        "quantity": Decimal("1"),
                        "net_total": Decimal("100.00"),
                        "tax_total": Decimal("19.00"),
                        "gross_total": Decimal("119.00"),
                    }
                ],
            },
        }
    customer = invoice.customer
    name = (
        customer.organization_name
        if customer.party_type == "organization"
        else f"{customer.given_name} {customer.family_name}".strip()
    )
    lines = list(InvoiceLine.objects.filter(invoice=invoice).order_by("position", "pk")[:201])
    if len(lines) > 200:
        raise PreviewRenderError("Draft has too many lines for a preview.")
    return {
        "labels": labels,
        "seller": seller,
        "customer": {"name": name},
        "recipient": {
            "name": invoice.recipient.get("organization_name")
            or invoice.recipient.get("family_name")
            or name
        },
        "invoice": {
            "number": "PREVIEW",
            "issue_date": invoice.issue_date,
            "currency": invoice.currency,
            "subtotal": invoice.subtotal,
            "tax_total": invoice.tax_total,
            "grand_total": invoice.grand_total,
            "lines": [
                {
                    "description": line.description,
                    "quantity": line.quantity,
                    "net_total": line.net_total,
                    "tax_total": line.tax_total,
                    "gross_total": line.gross_total,
                }
                for line in lines
            ],
        },
    }


def create_preview(
    *, version: DocumentTemplateVersion, actor: User, invoice: Invoice | None, output_format: str
) -> PreviewArtifact:
    if invoice is not None and invoice.document_language != version.language:
        raise PreviewRenderError("Draft language does not match template version.")
    assets: dict[str, tuple[str, bytes]] = {}
    for asset in DocumentAsset.objects.filter(
        template=version.template, key__in=version.asset_keys
    ):
        if asset.size > 2 * 1024 * 1024:
            raise PreviewRenderError("Image asset is too large.")
        try:
            with default_storage.open(asset.key, "rb") as stored:
                payload = stored.read(2 * 1024 * 1024 + 1)
        except OSError as error:
            raise PreviewRenderError("Image asset is missing.") from error
        if len(payload) != asset.size:
            raise PreviewRenderError("Image asset is missing or changed.")
        assets[asset.key] = (asset.content_type, payload)
    html = render_preview_html(
        version.html,
        version.css,
        language=version.language,
        context=_context(language=version.language, invoice=invoice),
        assets=assets,
    )
    payload = html.encode("utf-8") if output_format == "html" else render_preview_pdf(html)
    suffix = "html" if output_format == "html" else "pdf"
    key = f"document-previews/{uuid4().hex}.{suffix}"
    key = default_storage.save(key, ContentFile(payload))
    try:
        return PreviewArtifact.objects.create(
            created_by=actor,
            storage_key=key,
            content_type="text/html" if suffix == "html" else "application/pdf",
            expires_at=timezone.now() + PREVIEW_LIFETIME,
        )
    except Exception:
        default_storage.delete(key)
        raise


def cleanup_expired_previews() -> int:
    expired = list(PreviewArtifact.objects.filter(expires_at__lte=timezone.now()))
    for artifact in expired:
        default_storage.delete(artifact.storage_key)
        artifact.delete()
    return len(expired)

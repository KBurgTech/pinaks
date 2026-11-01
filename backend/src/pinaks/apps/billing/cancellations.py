"""Full reversals are separate documents; original evidence is never edited."""

from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.services import record_event
from pinaks.apps.billing.models import Invoice, InvoiceLine


class InvalidCancellationError(ValueError):
    pass


@transaction.atomic
def create_cancellation(
    *, invoice_id: int, reason: str, idempotency_key: str, actor: User, correlation_id: str
) -> tuple[Invoice, bool]:
    from pinaks.apps.documents.access import artifacts_healthy
    from pinaks.apps.documents.models import IssuedArtifact

    if not actor.is_active or actor.role not in (UserRole.ADMIN, UserRole.COMPANY_MEMBER):
        raise PermissionDenied
    reason = reason.strip()
    if not reason or len(reason) > 500 or not idempotency_key.strip() or len(idempotency_key) > 100:
        raise ValidationError({"reason": "A reason and command identity are required."})
    original = Invoice.objects.select_for_update().get(pk=invoice_id)
    existing = Invoice.objects.filter(
        original_invoice=original, invoice_type="CANCELLATION"
    ).first()
    if existing is not None:
        if existing.correction_key != idempotency_key or existing.correction_reason != reason:
            raise InvalidCancellationError("A different cancellation command already exists.")
        return existing, False
    if Invoice.objects.filter(original_invoice=original, invoice_type="CREDIT_NOTE").exists():
        raise InvalidCancellationError("Partial credits already reserve this invoice.")
    if original.invoice_type != "STANDARD" or original.lifecycle_status != "ISSUED":
        raise InvalidCancellationError("Only issued standard invoices can be cancelled.")
    if not artifacts_healthy(list(IssuedArtifact.objects.filter(invoice=original))):
        raise InvalidCancellationError("Original evidence is unhealthy.")
    draft = Invoice.objects.create(
        customer_id=original.customer_id,
        currency=original.currency,
        document_language=original.document_language,
        issue_date=timezone.localdate(),
        recipient=deepcopy(original.recipient),
        custom_data=deepcopy(original.custom_data),
        subtotal=original.subtotal,
        tax_total=original.tax_total,
        grand_total=original.grand_total,
    )
    for line in InvoiceLine.objects.filter(invoice=original).order_by("position"):
        line.pk = None
        line.invoice = draft
        line.save(force_insert=True)
    draft.original_invoice = original
    draft.invoice_type = "CANCELLATION"
    draft.correction_reason = reason
    draft.correction_key = idempotency_key
    draft.save()
    record_event(
        actor=actor,
        action_code="billing.cancellation_created",
        target_type="billing.invoice",
        target_identifier=str(draft.pk),
        correlation_id=correlation_id,
        metadata={"original_invoice_id": original.pk},
    )
    return draft, True


def freeze_correction(
    *, invoice: Invoice, template_id: int, idempotency_key: str, actor: User, correlation_id: str
) -> Invoice:
    """Called under the issuance transaction and aggregate lock."""
    from pinaks.apps.billing.issuance import _number
    from pinaks.apps.configuration.models import CompanyProfile
    from pinaks.apps.documents.services import get_published_version
    from pinaks.apps.workers.services import enqueue_work

    original = Invoice.objects.select_for_update().get(pk=invoice.original_invoice_id)
    if original.lifecycle_status != "ISSUED" or original.snapshot is None:
        raise ValidationError({"original_invoice": "Original invoice must still be issued."})
    if invoice.issue_date < original.issue_date:
        raise ValidationError({"issue_date": "Correction cannot precede the original invoice."})
    template = get_published_version(template_id=template_id, language=invoice.document_language)
    if template is None:
        raise ValidationError({"template": "A published bilingual template is required."})
    company = CompanyProfile.objects.select_for_update().first()
    if company is None:
        raise ValidationError({"company": "Company profile is missing."})
    number = _number(company, invoice.issue_date.year)
    snapshot = deepcopy(original.snapshot)
    document = snapshot["invoice"]
    assert isinstance(document, dict)
    document.update(
        id=invoice.pk,
        number=number,
        type=invoice.invoice_type,
        issue_date=invoice.issue_date.isoformat(),
        due_date=None,
        correction_reason=invoice.correction_reason,
        original_reference={
            "number": original.invoice_number,
            "issue_date": original.issue_date.isoformat(),
        },
    )
    if invoice.invoice_type == "CREDIT_NOTE":
        from pinaks.apps.billing.credit_notes import credit_snapshot

        credit_snapshot(invoice, snapshot)
    snapshot["template"] = {
        "id": template.template.pk,
        "version_id": template.pk,
        "version": template.version,
        "language": template.language,
        "html": template.html,
        "css": template.css,
        "page_settings": template.page_settings,
        "asset_keys": template.asset_keys,
    }
    Invoice.objects.filter(pk=invoice.pk).update(
        snapshot=snapshot,
        invoice_number=number,
        issuance_key=idempotency_key,
        lifecycle_status="ISSUING",
        version=invoice.version + 1,
        modified_at=timezone.now(),
    )
    record_event(
        actor=actor,
        action_code="billing.invoice_issuing",
        target_type="billing.invoice",
        target_identifier=str(invoice.pk),
        correlation_id=correlation_id,
        metadata={"invoice_number": number},
    )
    enqueue_work(job_type="documents.generate", identity=str(invoice.pk))
    invoice.refresh_from_db()
    return invoice

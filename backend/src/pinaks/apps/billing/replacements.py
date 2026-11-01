"""A new receivable is allowed only after a validated full reversal."""

from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.services import record_event
from pinaks.apps.billing.models import Invoice, InvoiceLine


class InvalidReplacementError(ValueError):
    pass


def validate_replacement_original(original: Invoice) -> None:
    from pinaks.apps.documents.access import artifacts_healthy
    from pinaks.apps.documents.models import IssuedArtifact

    cancellation = Invoice.objects.filter(
        original_invoice=original, invoice_type="CANCELLATION", lifecycle_status="ISSUED"
    ).first()
    if (
        original.invoice_type != "STANDARD"
        or original.lifecycle_status != "CANCELLED"
        or cancellation is None
        or not artifacts_healthy(list(IssuedArtifact.objects.filter(invoice=original)))
        or not artifacts_healthy(list(IssuedArtifact.objects.filter(invoice=cancellation)))
    ):
        raise InvalidReplacementError("A healthy issued full cancellation is required.")


@transaction.atomic
def create_replacement(
    *, invoice_id: int, reason: str, idempotency_key: str, actor: User, correlation_id: str
) -> tuple[Invoice, bool]:
    if not actor.is_active or actor.role not in (UserRole.ADMIN, UserRole.COMPANY_MEMBER):
        raise PermissionDenied
    reason = reason.strip()
    if not reason or len(reason) > 500 or not idempotency_key.strip() or len(idempotency_key) > 100:
        raise ValidationError({"reason": "A reason and command identity are required."})
    original = Invoice.objects.select_for_update().get(pk=invoice_id)
    existing = Invoice.objects.filter(original_invoice=original, invoice_type="REPLACEMENT").first()
    if existing is not None:
        if existing.correction_key != idempotency_key or existing.correction_reason != reason:
            raise InvalidReplacementError("A different replacement command already exists.")
        return existing, False
    if Invoice.objects.filter(original_invoice=original, correction_key=idempotency_key).exists():
        raise InvalidReplacementError("Command identity is already used by another correction.")
    validate_replacement_original(original)
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
    draft.invoice_type = "REPLACEMENT"
    draft.correction_reason = reason
    draft.correction_key = idempotency_key
    draft.save()
    record_event(
        actor=actor,
        action_code="billing.replacement_created",
        target_type="billing.invoice",
        target_identifier=str(draft.pk),
        correlation_id=correlation_id,
        metadata={"original_invoice_id": original.pk},
    )
    return draft, True

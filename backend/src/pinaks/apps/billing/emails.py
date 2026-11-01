"""Billing commands orchestrate document checks and the public notification service."""

from datetime import datetime

from django.db import transaction

from pinaks.apps.accounts.models import User
from pinaks.apps.billing.models import Invoice, LifecycleStatus
from pinaks.apps.documents.services import email_attachment
from pinaks.apps.notifications.models import OutgoingEmail
from pinaks.apps.notifications.services import (
    EmailConflictError,
    authorize,
    existing_email,
    queue_invoice_email,
    request_fingerprint,
)


@transaction.atomic
def send_invoice(
    *,
    invoice_id: int,
    template_id: int,
    language: str,
    recipients: list[str],
    idempotency_key: str,
    actor: User,
    correlation_id: str,
    scheduled_at: datetime | None = None,
) -> OutgoingEmail:
    authorize(actor)
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    fingerprint = request_fingerprint(
        template_id=template_id, language=language, recipients=recipients, scheduled_at=scheduled_at
    )
    existing = existing_email(
        invoice_id=invoice_id, idempotency_key=idempotency_key, fingerprint=fingerprint
    )
    if existing:
        return existing
    if invoice.lifecycle_status not in (LifecycleStatus.ISSUED, LifecycleStatus.CANCELLED):
        raise EmailConflictError("Only issued documents can be queued.")
    assert invoice.invoice_number is not None
    attachment_id, attachment_sha256 = email_attachment(invoice_id=invoice_id)
    return queue_invoice_email(
        invoice_id=invoice_id,
        invoice_number=invoice.invoice_number,
        template_id=template_id,
        language=language,
        recipients=recipients,
        idempotency_key=idempotency_key,
        attachment_id=attachment_id,
        attachment_sha256=attachment_sha256,
        scheduled_at=scheduled_at,
        actor=actor,
        correlation_id=correlation_id,
    )

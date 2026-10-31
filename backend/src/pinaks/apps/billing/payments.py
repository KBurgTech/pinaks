"""Provider-neutral payment commands; issued content remains frozen."""

from datetime import date

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.services import record_event
from pinaks.apps.billing.models import Invoice, PaymentStatus


class InvalidPaymentTransitionError(ValueError):
    pass


def is_overdue(invoice: Invoice, *, today: date) -> bool:
    return bool(
        invoice.lifecycle_status == "ISSUED"
        and invoice.payment_status == "UNPAID"
        and invoice.due_date is not None
        and invoice.due_date < today
    )


@transaction.atomic
def change_payment_status(
    *, invoice_id: int, payment_status: PaymentStatus, actor: User, correlation_id: str
) -> Invoice:
    if not actor.is_active or actor.role not in (UserRole.ADMIN, UserRole.COMPANY_MEMBER):
        raise PermissionDenied
    if payment_status not in PaymentStatus.values:
        raise InvalidPaymentTransitionError("Unsupported payment status.")
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    if invoice.lifecycle_status != "ISSUED":
        raise InvalidPaymentTransitionError("Only issued invoices accept payment changes.")
    if invoice.payment_status == payment_status:
        return invoice
    previous = invoice.payment_status
    changed_at = timezone.now()
    Invoice.objects.filter(pk=invoice.pk).update(
        payment_status=payment_status, payment_changed_at=changed_at, payment_changed_by=actor
    )
    record_event(
        actor=actor,
        action_code="billing.invoice_payment_changed",
        target_type="billing.invoice",
        target_identifier=str(invoice.pk),
        correlation_id=correlation_id,
        metadata={"previous_status": previous, "payment_status": payment_status},
    )
    invoice.refresh_from_db()
    return invoice

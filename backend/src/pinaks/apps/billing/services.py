from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.services import record_event
from pinaks.apps.billing.calculations import LineAmounts
from pinaks.apps.billing.models import Invoice
from pinaks.apps.configuration.models import CompanyProfile, DocumentLanguage
from pinaks.apps.customers.models import Customer


class CompanyConfigurationMissingError(ValueError):
    pass


@transaction.atomic
def create_draft(
    *,
    customer: Customer,
    actor: User,
    correlation_id: str,
    document_language: str | None = None,
    issue_date: date | str | None = None,
    due_date: date | str | None = None,
) -> Invoice:
    company = CompanyProfile.objects.first()
    if company is None:
        raise CompanyConfigurationMissingError("The company profile is missing.")
    if customer.is_archived:
        raise ValidationError({"customer_id": "Archived customers cannot receive new drafts."})
    if isinstance(issue_date, str):
        issue_date = date.fromisoformat(issue_date)
    if isinstance(due_date, str):
        due_date = date.fromisoformat(due_date)
    invoice = Invoice(
        customer=customer,
        currency=company.default_currency,
        document_language=document_language
        or customer.preferred_language
        or company.default_document_language,
        issue_date=issue_date or timezone.localdate(),
        due_date=due_date,
    )
    if invoice.document_language not in DocumentLanguage.values:
        raise ValidationError({"document_language": "Unsupported document language."})
    invoice.full_clean()
    invoice.save()
    record_event(
        actor=actor,
        action_code="billing.invoice_draft_created",
        target_type="billing.invoice",
        target_identifier=str(invoice.pk),
        correlation_id=correlation_id,
        metadata={"customer_id": customer.pk},
    )
    return invoice


@transaction.atomic
def recalculate_draft(*, invoice_id: int) -> Invoice:
    """Recalculate persisted draft lines and totals under the aggregate lock."""
    from pinaks.apps.billing.calculations import calculate_line, calculate_totals
    from pinaks.apps.billing.models import InvoiceLine

    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    rows: list[tuple[str, Decimal, LineAmounts]] = []
    for line in InvoiceLine.objects.filter(invoice=invoice).order_by("position", "pk"):
        amounts = calculate_line(
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount_percent=line.discount_percent,
            tax_rate=line.tax_rate,
            price_entry_policy=line.price_entry_policy,
        )
        line.net_total, line.tax_total, line.gross_total = amounts.net, amounts.tax, amounts.gross
        line.full_clean()
        line.save(update_fields=("net_total", "tax_total", "gross_total"))
        rows.append((line.tax_category, line.tax_rate, amounts))
    totals = calculate_totals(rows)
    invoice.subtotal = totals.subtotal
    invoice.tax_total = totals.tax_total
    invoice.grand_total = totals.grand_total
    invoice.version += 1
    invoice.full_clean()
    invoice.save(update_fields=("subtotal", "tax_total", "grand_total", "version", "modified_at"))
    return invoice

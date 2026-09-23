from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.services import record_event
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

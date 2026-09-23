"""Freeze a draft as canonical versioned evidence before document generation."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.services import record_event
from pinaks.apps.billing.calculations import LineAmounts, calculate_line, calculate_totals
from pinaks.apps.billing.models import Invoice, InvoiceLine, LifecycleStatus
from pinaks.apps.configuration.models import CompanyProfile, InvoiceNumberReset, TaxProfile
from pinaks.apps.custom_fields.models import CustomFieldDefinition
from pinaks.apps.documents.services import get_published_version
from pinaks.apps.workers.services import enqueue_work


class StaleIssueVersionError(ValueError):
    pass


class IssueIdentityConflictError(ValueError):
    pass


def _custom_fields(target: str, values: dict[str, object]) -> list[dict[str, object]]:
    definitions = {
        field.key: field
        for field in CustomFieldDefinition.objects.filter(target=target, key__in=values)
    }
    if len(definitions) != len(values):
        raise ValidationError({"custom_data": "A custom-field definition is missing."})
    result: list[dict[str, object]] = []
    for key in sorted(values):
        field = definitions[key]
        result.append(
            {
                "key": key,
                "value": values[key],
                "data_type": field.data_type,
                "label_en": field.label_en,
                "label_de": field.label_de,
                "visibility": field.visibility,
                "is_sensitive": field.is_sensitive,
                "choices": field.choices,
            }
        )
    return result


def _number(company: CompanyProfile, year: int) -> str:
    if company.invoice_number_reset == InvoiceNumberReset.ANNUAL:
        if company.invoice_number_year is not None and year < company.invoice_number_year:
            raise ValidationError({"issue_date": "Invoice year cannot move backwards."})
        if company.invoice_number_year != year:
            company.invoice_number_next = 1
            company.invoice_number_year = year
        suffix = f"{year}-{company.invoice_number_next:0{company.invoice_number_padding}d}"
    else:
        suffix = f"{company.invoice_number_next:0{company.invoice_number_padding}d}"
    number = f"{company.invoice_number_prefix}{suffix}"
    if len(number) > 80:
        raise ValidationError({"invoice_number": "Invoice number exceeds the allowed length."})
    company.invoice_number_next += 1
    company.save(update_fields=("invoice_number_next", "invoice_number_year", "modified_at"))
    return number


@transaction.atomic
def issue_invoice(
    *,
    invoice_id: int,
    expected_version: int,
    template_id: int,
    idempotency_key: str,
    actor: User,
    correlation_id: str,
) -> Invoice:
    if not idempotency_key or len(idempotency_key) > 100:
        raise ValidationError({"idempotency_key": "Provide an identity of at most 100 characters."})
    invoice = Invoice.objects.select_for_update().select_related("customer").get(pk=invoice_id)
    if invoice.lifecycle_status == LifecycleStatus.ISSUING:
        frozen_template = invoice.snapshot.get("template") if invoice.snapshot else None
        if (
            invoice.issuance_key != idempotency_key
            or not isinstance(frozen_template, dict)
            or frozen_template.get("id") != template_id
        ):
            raise IssueIdentityConflictError("Invoice already has a different issuance command.")
        return invoice
    if invoice.lifecycle_status != LifecycleStatus.DRAFT:
        raise ValidationError({"invoice": "Only drafts can be issued."})
    if invoice.version != expected_version:
        raise StaleIssueVersionError("The invoice changed since it was loaded.")
    company = CompanyProfile.objects.select_for_update().first()
    if company is None:
        raise ValidationError({"company": "Company profile is missing."})
    if not all(
        (
            company.legal_name.strip(),
            company.address_line_1.strip(),
            company.city.strip(),
            company.postal_code.strip(),
            company.country_code.strip(),
        )
    ):
        raise ValidationError({"seller": "Seller identity and address are incomplete."})
    if not (company.tax_number.strip() or company.vat_identifier.strip()):
        raise ValidationError({"seller": "Seller tax identifier is missing."})
    if not (company.iban.strip() or company.payment_instructions.strip()):
        raise ValidationError({"payment": "Payment instructions are missing."})
    if invoice.currency != "EUR" or invoice.document_language not in ("en", "de"):
        raise ValidationError({"invoice": "Currency or document language is unsupported."})
    if invoice.due_date is not None and invoice.due_date < invoice.issue_date:
        raise ValidationError({"due_date": "Due date must follow issue date."})
    if (
        not invoice.recipient.get("address_line_1")
        or not invoice.recipient.get("city")
        or not (invoice.recipient.get("organization_name") or invoice.recipient.get("family_name"))
    ):
        raise ValidationError({"recipient": "Recipient identity and address are incomplete."})
    customer = invoice.customer
    address = customer.addresses.filter(is_primary=True).first()
    if address is None or not address.address_line_1 or not address.city:
        raise ValidationError({"customer": "Customer address is incomplete."})
    template = get_published_version(template_id=template_id, language=invoice.document_language)
    if template is None:
        raise ValidationError({"template": "A published bilingual template is required."})
    profile = TaxProfile.objects.filter(is_default=True, is_current=True).first()
    if profile is None:
        raise ValidationError({"tax_profile": "A current default tax profile is required."})
    for identifier in profile.required_seller_identifiers:
        if not str(getattr(company, identifier)).strip():
            raise ValidationError(
                {"seller": "The tax profile requires a missing seller identifier."}
            )
    lines = list(InvoiceLine.objects.filter(invoice=invoice).order_by("position", "pk"))
    if not lines or len(lines) > 200:
        raise ValidationError({"lines": "An invoice needs between one and 200 lines."})
    line_snapshots: list[dict[str, object]] = []
    rows: list[tuple[str, Decimal, LineAmounts]] = []
    for position, line in enumerate(lines, start=1):
        if line.position != position or not line.description.strip() or not line.unit:
            raise ValidationError({"lines": "Line order or content is incomplete."})
        if line.service_date is None or (
            line.service_period_end and line.service_period_end < line.service_date
        ):
            raise ValidationError({"lines": "A valid service date is required."})
        if (line.tax_category, line.tax_rate, line.price_entry_policy) != (
            profile.tax_category,
            profile.rate,
            profile.price_entry_policy,
        ):
            raise ValidationError(
                {"tax_profile": "Line tax treatment differs from the active profile."}
            )
        if line.tax_category == "E" and (
            line.exemption_reason_code != profile.exemption_reason_code
            or line.exemption_wording
            != getattr(profile, f"exemption_wording_{invoice.document_language}")
        ):
            raise ValidationError(
                {"tax_profile": "Exemption details differ from the active profile."}
            )
        try:
            amounts = calculate_line(
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_percent=line.discount_percent,
                tax_rate=line.tax_rate,
                price_entry_policy=line.price_entry_policy,
            )
        except ValueError as error:
            raise ValidationError({"lines": "Invalid line calculation."}) from error
        if (amounts.net, amounts.tax, amounts.gross) != (
            line.net_total,
            line.tax_total,
            line.gross_total,
        ):
            raise ValidationError({"totals": "Draft line totals are stale."})
        rows.append((line.tax_category, line.tax_rate, amounts))
        line_snapshots.append(
            {
                "position": position,
                "item_code": line.item_code,
                "description": line.description,
                "unit": line.unit,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "discount_percent": str(line.discount_percent),
                "service_date": line.service_date.isoformat(),
                "service_period_end": line.service_period_end.isoformat()
                if line.service_period_end
                else None,
                "tax_category": line.tax_category,
                "tax_rate": str(line.tax_rate),
                "price_entry_policy": line.price_entry_policy,
                "exemption_reason_code": line.exemption_reason_code,
                "exemption_wording": line.exemption_wording,
                "net_total": str(amounts.net),
                "tax_total": str(amounts.tax),
                "gross_total": str(amounts.gross),
                "custom_data": line.custom_data,
                "custom_fields": _custom_fields("invoice_line", line.custom_data),
            }
        )
    totals = calculate_totals(rows)
    if (totals.subtotal, totals.tax_total, totals.grand_total) != (
        invoice.subtotal,
        invoice.tax_total,
        invoice.grand_total,
    ) or totals.grand_total <= 0:
        raise ValidationError({"totals": "Draft totals are stale or empty."})
    number = _number(company, invoice.issue_date.year)
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "invoice": {
            "id": invoice.pk,
            "number": number,
            "type": invoice.invoice_type,
            "issue_date": invoice.issue_date.isoformat(),
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "currency": invoice.currency,
            "language": invoice.document_language,
            "subtotal": str(totals.subtotal),
            "tax_total": str(totals.tax_total),
            "grand_total": str(totals.grand_total),
            "custom_data": invoice.custom_data,
            "custom_fields": _custom_fields("invoice", invoice.custom_data),
        },
        "seller": {
            key: getattr(company, key)
            for key in (
                "legal_name",
                "address_line_1",
                "address_line_2",
                "postal_code",
                "city",
                "country_code",
                "email",
                "phone",
                "tax_number",
                "vat_identifier",
                "company_identifier",
                "bank_account_holder",
                "iban",
                "bic",
                "payment_instructions",
            )
        },
        "customer": {
            "number": customer.customer_number,
            "party_type": customer.party_type,
            "given_name": customer.given_name,
            "family_name": customer.family_name,
            "organization_name": customer.organization_name,
            "email": customer.email,
            "phone": customer.phone,
            "address_line_1": address.address_line_1,
            "address_line_2": address.address_line_2,
            "postal_code": address.postal_code,
            "city": address.city,
            "country_code": address.country_code,
        },
        "recipient": dict(invoice.recipient),
        "tax_profile": {
            "code": profile.code,
            "version": profile.version,
            "category": profile.tax_category,
            "rate": str(profile.rate),
            "price_entry_policy": profile.price_entry_policy,
            "tax_column_policy": profile.tax_column_policy,
            "exemption_reason_code": profile.exemption_reason_code,
            "exemption_wording_en": profile.exemption_wording_en,
            "exemption_wording_de": profile.exemption_wording_de,
        },
        "template": {
            "id": template.template.pk,
            "version_id": template.pk,
            "version": template.version,
            "language": template.language,
            "html": template.html,
            "css": template.css,
            "page_settings": template.page_settings,
            "asset_keys": template.asset_keys,
        },
        "lines": line_snapshots,
        "tax_breakdowns": [
            {
                "category": group.category,
                "rate": str(group.rate),
                "net": str(group.net),
                "tax": str(group.tax),
            }
            for group in totals.groups
        ],
    }
    invoice.invoice_number = number
    invoice.issuance_key = idempotency_key
    invoice.snapshot = snapshot
    invoice.lifecycle_status = LifecycleStatus.ISSUING
    invoice.version += 1
    invoice.full_clean()
    invoice.save(
        update_fields=(
            "invoice_number",
            "issuance_key",
            "snapshot",
            "lifecycle_status",
            "version",
            "modified_at",
        )
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
    return invoice

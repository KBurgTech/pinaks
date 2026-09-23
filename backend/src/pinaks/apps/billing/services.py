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
from pinaks.apps.custom_fields.services import validate_custom_data
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
    custom_data: object = None,
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
        custom_data=validate_custom_data(target="invoice", values=custom_data or {}),
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


class StaleInvoiceVersionError(ValueError):
    pass


@transaction.atomic
def update_draft(
    *,
    invoice_id: int,
    expected_version: int,
    values: dict[str, object],
    actor: User,
    correlation_id: str,
) -> Invoice:
    """Apply one ordered draft command under the invoice aggregate lock."""
    from pinaks.apps.billing.calculations import calculate_line, calculate_totals
    from pinaks.apps.billing.models import InvoiceLine
    from pinaks.apps.catalog.services import draft_line_defaults
    from pinaks.apps.customers.services import recipient_snapshot

    invoice = Invoice.objects.select_for_update().select_related("customer").get(pk=invoice_id)
    if invoice.version != expected_version:
        raise StaleInvoiceVersionError("The invoice changed since it was loaded.")
    if invoice.lifecycle_status != "DRAFT":
        raise ValidationError({"invoice": "Only drafts can be edited."})
    if "custom_data" in values:
        invoice.custom_data = validate_custom_data(
            target="invoice", values=values["custom_data"], existing=invoice.custom_data
        )
    for field in ("document_language", "issue_date", "due_date"):
        if field in values:
            setattr(invoice, field, values[field])
    if invoice.due_date is not None and invoice.due_date < invoice.issue_date:
        raise ValidationError({"due_date": "Due date must be on or after issue date."})
    raw_recipient = values.get("recipient")
    if isinstance(raw_recipient, dict):
        source = str(raw_recipient["source"])
        invoice.recipient = recipient_snapshot(
            source=source,
            customer=invoice.customer,
            recipient_id=raw_recipient.get("recipient_id"),
            source_customer_id=raw_recipient.get("customer_id"),
            values=raw_recipient.get("values"),
        )
    lines = list(InvoiceLine.objects.filter(invoice=invoice).order_by("position", "pk"))
    operations = values.get("line_operations", [])
    if isinstance(operations, list):
        for operation in operations:
            if not isinstance(operation, dict):
                raise ValidationError({"line_operations": "Each operation must be an object."})
            action = operation["action"]
            if action == "add":
                catalog_item_id = operation.get("catalog_item_id")
                if catalog_item_id is not None:
                    defaults = draft_line_defaults(
                        item_id=catalog_item_id, language=invoice.document_language
                    )
                else:
                    required = (
                        "description",
                        "unit",
                        "unit_price",
                        "tax_category",
                        "tax_rate",
                        "price_entry_policy",
                    )
                    if any(field not in operation for field in required):
                        raise ValidationError(
                            {
                                "line_operations": "Manual lines require description, unit, price, "
                                "and tax details."
                            }
                        )
                    defaults = {field: operation[field] for field in required}
                    defaults.update(
                        {
                            "item_code": operation.get("item_code", ""),
                            "exemption_reason_code": operation.get("exemption_reason_code", ""),
                            "exemption_wording": operation.get("exemption_wording", ""),
                        }
                    )
                line = InvoiceLine(invoice=invoice, **defaults)
                line.quantity = operation.get("quantity", Decimal("1"))
                line.discount_percent = operation.get("discount_percent", Decimal("0"))
                line.service_date = operation.get("service_date")
                line.service_period_end = operation.get("service_period_end")
                line.custom_data = validate_custom_data(
                    target="invoice_line", values=operation.get("custom_data", {})
                )
                position = operation.get("position", len(lines) + 1)
                if not isinstance(position, int) or not 1 <= position <= len(lines) + 1:
                    raise ValidationError({"position": "Invalid line position."})
                lines.insert(position - 1, line)
            else:
                line_id = operation.get("line_id")
                target = next((line for line in lines if line.pk == line_id), None)
                if target is None:
                    raise ValidationError({"line_id": "Line does not belong to this draft."})
                if action == "remove":
                    lines.remove(target)
                elif action == "update":
                    if "custom_data" in operation:
                        target.custom_data = validate_custom_data(
                            target="invoice_line",
                            values=operation["custom_data"],
                            existing=target.custom_data,
                        )
                    for field in (
                        "quantity",
                        "unit_price",
                        "discount_percent",
                        "description",
                        "unit",
                        "item_code",
                        "tax_category",
                        "tax_rate",
                        "price_entry_policy",
                        "exemption_reason_code",
                        "exemption_wording",
                        "service_date",
                        "service_period_end",
                    ):
                        if field in operation:
                            setattr(target, field, operation[field])
                    if "position" in operation:
                        position = operation["position"]
                        if not isinstance(position, int) or not 1 <= position <= len(lines):
                            raise ValidationError({"position": "Invalid line position."})
                        lines.remove(target)
                        lines.insert(position - 1, target)
                else:
                    raise ValidationError({"action": "Unsupported line operation."})
    rows: list[tuple[str, Decimal, LineAmounts]] = []
    for position, line in enumerate(lines, start=1):
        line.position = position
        if line.service_period_end is not None and (
            line.service_date is None or line.service_period_end < line.service_date
        ):
            raise ValidationError({"service_period_end": "Invalid service period."})
        try:
            amounts = calculate_line(
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_percent=line.discount_percent,
                tax_rate=line.tax_rate,
                price_entry_policy=line.price_entry_policy,
            )
        except ValueError as error:
            raise ValidationError({"line_operations": str(error)}) from error
        line.net_total, line.tax_total, line.gross_total = amounts.net, amounts.tax, amounts.gross
        if (
            line.tax_category == "S"
            and (line.tax_rate <= 0 or line.exemption_reason_code or line.exemption_wording)
        ) or (
            line.tax_category == "E"
            and (line.tax_rate != 0 or not line.exemption_reason_code or not line.exemption_wording)
        ):
            raise ValidationError(
                {"line_operations": "Tax category, rate and exemption details do not match."}
            )
        if line.tax_category not in ("S", "E"):
            raise ValidationError({"tax_category": "Unsupported tax category."})
        line.full_clean(validate_unique=False, validate_constraints=False)
        rows.append((line.tax_category, line.tax_rate, amounts))
    totals = calculate_totals(rows)
    invoice.subtotal, invoice.tax_total, invoice.grand_total = (
        totals.subtotal,
        totals.tax_total,
        totals.grand_total,
    )
    invoice.version += 1
    invoice.full_clean()
    if "line_operations" in values:
        InvoiceLine.objects.filter(invoice=invoice).delete()
        InvoiceLine.objects.bulk_create(lines)
    invoice.save()
    record_event(
        actor=actor,
        action_code="billing.invoice_draft_updated",
        target_type="billing.invoice",
        target_identifier=str(invoice.pk),
        correlation_id=correlation_id,
        metadata={"changed_fields": sorted(values)},
    )
    return invoice

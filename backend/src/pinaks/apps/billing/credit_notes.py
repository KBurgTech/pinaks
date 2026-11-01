"""Immutable partial credits reserve original quantities and amounts at creation."""

from copy import deepcopy
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.services import record_event
from pinaks.apps.billing.calculations import LineAmounts, calculate_line, calculate_totals
from pinaks.apps.billing.models import Invoice, InvoiceLine


class InvalidCreditNoteError(ValueError):
    pass


@transaction.atomic
def create_credit_note(
    *,
    invoice_id: int,
    reason: str,
    idempotency_key: str,
    lines: list[dict[str, object]],
    actor: User,
    correlation_id: str,
) -> tuple[Invoice, bool]:
    from pinaks.apps.documents.access import artifacts_healthy
    from pinaks.apps.documents.models import IssuedArtifact

    if not actor.is_active or actor.role not in (UserRole.ADMIN, UserRole.COMPANY_MEMBER):
        raise PermissionDenied
    reason = reason.strip()
    if not reason or len(reason) > 500 or not idempotency_key.strip() or len(idempotency_key) > 100:
        raise ValidationError({"reason": "A reason and command identity are required."})
    original = Invoice.objects.select_for_update().get(pk=invoice_id)
    allocations: list[dict[str, str | int]] = []
    for row in lines:
        position, quantity, price = row.get("position"), row.get("quantity"), row.get("unit_price")
        if (
            not isinstance(position, int)
            or isinstance(position, bool)
            or not isinstance(quantity, Decimal)
            or not isinstance(price, Decimal)
        ):
            raise ValidationError(
                {"lines": "Provide an original position, quantity and unit price."}
            )
        allocations.append(
            {
                "position": position,
                "quantity": str(quantity.normalize()),
                "unit_price": str(price.normalize()),
            }
        )
    allocations.sort(key=lambda row: int(row["position"]))
    if not 1 <= len(allocations) <= 200 or len({row["position"] for row in allocations}) != len(
        allocations
    ):
        raise ValidationError({"lines": "Select between one and 200 distinct original lines."})
    existing = Invoice.objects.filter(
        original_invoice=original, correction_key=idempotency_key
    ).first()
    if existing is not None:
        if (
            existing.invoice_type != "CREDIT_NOTE"
            or existing.correction_reason != reason
            or existing.credit_allocations != allocations
        ):
            raise InvalidCreditNoteError("Command identity has different content.")
        return existing, False
    if original.invoice_type != "STANDARD" or original.lifecycle_status != "ISSUED":
        raise InvalidCreditNoteError("Only issued standard invoices can be credited.")
    if Invoice.objects.filter(original_invoice=original, invoice_type="CANCELLATION").exists():
        raise InvalidCreditNoteError("A full cancellation already reserves this invoice.")
    if not artifacts_healthy(list(IssuedArtifact.objects.filter(invoice=original))):
        raise InvalidCreditNoteError("Original evidence is unhealthy.")
    sources = {line.position: line for line in InvoiceLine.objects.filter(invoice=original)}
    used: dict[int, tuple[Decimal, Decimal, Decimal, Decimal]] = {}
    for credit in Invoice.objects.filter(original_invoice=original, invoice_type="CREDIT_NOTE"):
        for allocation, line in zip(
            credit.credit_allocations,
            InvoiceLine.objects.filter(invoice=credit).order_by("position"),
            strict=True,
        ):
            position = int(allocation["position"])
            prior = used.get(position, (Decimal(0),) * 4)
            used[position] = (
                prior[0] + line.quantity,
                prior[1] + line.net_total,
                prior[2] + line.tax_total,
                prior[3] + line.gross_total,
            )
    selected: list[InvoiceLine] = []
    rows: list[tuple[str, Decimal, LineAmounts]] = []
    for allocation in allocations:
        source = sources.get(int(allocation["position"]))
        quantity, price = Decimal(allocation["quantity"]), Decimal(allocation["unit_price"])
        if source is None or price > source.unit_price:
            raise ValidationError(
                {"lines": "Select original lines and prices no greater than the original."}
            )
        try:
            amounts = calculate_line(
                quantity=quantity,
                unit_price=price,
                discount_percent=source.discount_percent,
                tax_rate=source.tax_rate,
                price_entry_policy=source.price_entry_policy,
            )
        except ValueError as error:
            raise ValidationError({"lines": "Invalid credit quantity or price."}) from error
        prior = used.get(source.position, (Decimal(0),) * 4)
        if any(
            a + b > limit
            for a, b, limit in zip(
                prior,
                (quantity, amounts.net, amounts.tax, amounts.gross),
                (source.quantity, source.net_total, source.tax_total, source.gross_total),
                strict=True,
            )
        ):
            raise InvalidCreditNoteError("Cumulative credit exceeds original quantity or amounts.")
        line = deepcopy(source)
        line.pk = None
        line.position = len(selected) + 1
        line.quantity, line.unit_price = quantity, price
        line.net_total, line.tax_total, line.gross_total = amounts.net, amounts.tax, amounts.gross
        selected.append(line)
        rows.append((line.tax_category, line.tax_rate, amounts))
    totals = calculate_totals(rows)
    if totals.grand_total <= 0:
        raise ValidationError({"lines": "A credit must have a positive amount."})
    draft = Invoice.objects.create(
        customer_id=original.customer_id,
        currency=original.currency,
        document_language=original.document_language,
        issue_date=timezone.localdate(),
        recipient=deepcopy(original.recipient),
        custom_data=deepcopy(original.custom_data),
        subtotal=totals.subtotal,
        tax_total=totals.tax_total,
        grand_total=totals.grand_total,
    )
    for line in selected:
        line.invoice = draft
        line.save(force_insert=True)
    draft.original_invoice = original
    draft.invoice_type = "CREDIT_NOTE"
    draft.correction_reason, draft.correction_key = reason, idempotency_key
    draft.credit_allocations = allocations
    draft.save()
    record_event(
        actor=actor,
        action_code="billing.credit_note_created",
        target_type="billing.invoice",
        target_identifier=str(draft.pk),
        correlation_id=correlation_id,
        metadata={"original_invoice_id": original.pk},
    )
    return draft, True


def credit_snapshot(invoice: Invoice, snapshot: dict[str, object]) -> None:
    """Replace only credited lines/totals; retain frozen parties, tax and custom labels."""
    original_lines = snapshot["lines"]
    assert isinstance(original_lines, list)
    lines: list[dict[str, object]] = []
    rows: list[tuple[str, Decimal, LineAmounts]] = []
    for allocation, line in zip(
        invoice.credit_allocations,
        InvoiceLine.objects.filter(invoice=invoice).order_by("position"),
        strict=True,
    ):
        original_line = original_lines[int(allocation["position"]) - 1]
        assert isinstance(original_line, dict)
        row = deepcopy(original_line)
        row.update(
            position=line.position,
            quantity=str(line.quantity),
            unit_price=str(line.unit_price),
            net_total=str(line.net_total),
            tax_total=str(line.tax_total),
            gross_total=str(line.gross_total),
        )
        lines.append(row)
        rows.append(
            (
                line.tax_category,
                line.tax_rate,
                LineAmounts(line.net_total, line.tax_total, line.gross_total),
            )
        )
    totals = calculate_totals(rows)
    document = snapshot["invoice"]
    assert isinstance(document, dict)
    document.update(
        subtotal=str(totals.subtotal),
        tax_total=str(totals.tax_total),
        grand_total=str(totals.grand_total),
    )
    snapshot["lines"] = lines
    snapshot["tax_breakdowns"] = [
        {
            "category": group.category,
            "rate": str(group.rate),
            "net": str(group.net),
            "tax": str(group.tax),
        }
        for group in totals.groups
    ]

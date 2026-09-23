"""Application operations for reusable invoice draft presets."""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.services import record_event
from pinaks.apps.billing.calculations import calculate_line
from pinaks.apps.billing.models import Invoice, InvoiceLine, InvoicePreset
from pinaks.apps.billing.services import update_draft


class ArchivedPresetError(ValueError):
    pass


_LINE_FIELDS = (
    "item_code",
    "description",
    "unit",
    "quantity",
    "unit_price",
    "discount_percent",
    "tax_category",
    "tax_rate",
    "price_entry_policy",
    "exemption_reason_code",
    "exemption_wording",
    "service_date",
    "service_period_end",
)


def _snapshot_lines(raw_lines: object) -> list[dict[str, str]]:
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValidationError({"lines": "A preset needs at least one line."})
    snapshots: list[dict[str, str]] = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            raise ValidationError({"lines": "Each line must be an object."})
        line = InvoiceLine(**raw)
        if line.service_period_end is not None and (
            line.service_date is None or line.service_period_end < line.service_date
        ):
            raise ValidationError({"lines": "Invalid service period."})
        if (
            line.tax_category == "S"
            and (line.tax_rate <= 0 or line.exemption_reason_code or line.exemption_wording)
        ) or (
            line.tax_category == "E"
            and (line.tax_rate != 0 or not line.exemption_reason_code or not line.exemption_wording)
        ):
            raise ValidationError({"lines": "Tax category and exemption details do not match."})
        try:
            calculate_line(
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_percent=line.discount_percent,
                tax_rate=line.tax_rate,
                price_entry_policy=line.price_entry_policy,
            )
        except ValueError as error:
            raise ValidationError({"lines": str(error)}) from error
        snapshots.append(
            {
                key: value.isoformat() if isinstance(value, date) else str(value)
                for key in _LINE_FIELDS
                if (value := getattr(line, key)) is not None
            }
        )
    return snapshots


@transaction.atomic
def create_preset(
    *, values: Mapping[str, object], actor: User, correlation_id: str
) -> InvoicePreset:
    preset = InvoicePreset(name=str(values["name"]), lines=_snapshot_lines(values["lines"]))
    preset.full_clean()
    preset.save()
    record_event(
        actor=actor,
        action_code="billing.preset_created",
        target_type="billing.invoice_preset",
        target_identifier=str(preset.pk),
        correlation_id=correlation_id,
        metadata={},
    )
    return preset


@transaction.atomic
def update_preset(
    *, preset_id: int, values: Mapping[str, object], actor: User, correlation_id: str
) -> InvoicePreset:
    preset = InvoicePreset.objects.select_for_update().get(pk=preset_id)
    if preset.is_archived:
        raise ArchivedPresetError("Archived presets cannot be edited.")
    if "name" in values:
        preset.name = str(values["name"])
    if "lines" in values:
        preset.lines = _snapshot_lines(values["lines"])
    preset.full_clean()
    preset.save()
    record_event(
        actor=actor,
        action_code="billing.preset_updated",
        target_type="billing.invoice_preset",
        target_identifier=str(preset.pk),
        correlation_id=correlation_id,
        metadata={"changed_fields": sorted(values)},
    )
    return preset


@transaction.atomic
def archive_preset(*, preset_id: int, actor: User, correlation_id: str) -> InvoicePreset:
    preset = InvoicePreset.objects.select_for_update().get(pk=preset_id)
    if not preset.is_archived:
        preset.is_archived = True
        preset.save(update_fields=("is_archived", "modified_at"))
        record_event(
            actor=actor,
            action_code="billing.preset_archived",
            target_type="billing.invoice_preset",
            target_identifier=str(preset.pk),
            correlation_id=correlation_id,
            metadata={},
        )
    return preset


@transaction.atomic
def apply_preset(
    *,
    preset_id: int,
    invoice_id: int,
    expected_version: int,
    mode: str,
    actor: User,
    correlation_id: str,
) -> Invoice:
    preset = InvoicePreset.objects.get(pk=preset_id)
    if preset.is_archived:
        raise ArchivedPresetError("Archived presets cannot be applied.")
    if mode not in ("append", "replace"):
        raise ValidationError({"mode": "Unsupported apply mode."})
    operations: list[dict[str, object]] = []
    if mode == "replace":
        operations.extend(
            {"action": "remove", "line_id": line_id}
            for line_id in InvoiceLine.objects.filter(invoice_id=invoice_id).values_list(
                "pk", flat=True
            )
        )
    for row in preset.lines:
        values: dict[str, object] = dict(row)
        for field in ("quantity", "unit_price", "discount_percent", "tax_rate"):
            values[field] = Decimal(row[field])
        for field in ("service_date", "service_period_end"):
            if field in row and row[field] is not None:
                values[field] = date.fromisoformat(row[field])
        operations.append({"action": "add", **values})
    invoice = update_draft(
        invoice_id=invoice_id,
        expected_version=expected_version,
        values={"line_operations": operations},
        actor=actor,
        correlation_id=correlation_id,
    )
    record_event(
        actor=actor,
        action_code="billing.preset_applied",
        target_type="billing.invoice",
        target_identifier=str(invoice.pk),
        correlation_id=correlation_id,
        metadata={"preset_id": preset.pk, "mode": mode},
    )
    return invoice

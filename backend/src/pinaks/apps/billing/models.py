from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q
from django.utils import timezone

from pinaks.apps.accounts.models import User
from pinaks.apps.configuration.models import DocumentLanguage
from pinaks.apps.customers.models import Customer


class InvoiceType(models.TextChoices):
    STANDARD = "STANDARD", "Standard"
    CANCELLATION = "CANCELLATION", "Cancellation"
    REPLACEMENT = "REPLACEMENT", "Replacement"
    CREDIT_NOTE = "CREDIT_NOTE", "Credit note"


class LifecycleStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ISSUING = "ISSUING", "Issuing"
    ISSUED = "ISSUED", "Issued"
    CANCELLED = "CANCELLED", "Cancelled"


class PaymentStatus(models.TextChoices):
    UNPAID = "UNPAID", "Unpaid"
    PAID = "PAID", "Paid"


class Invoice(models.Model):
    original_invoice_id: int | None
    original_invoice: models.ForeignKey[Invoice | None, Invoice | None] = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="related_invoices"
    )
    correction_reason: models.CharField[str, str] = models.CharField(max_length=500, blank=True)
    correction_key: models.CharField[str, str] = models.CharField(max_length=100, blank=True)
    credit_allocations: models.JSONField[list[dict[str, str | int]], list[dict[str, str | int]]] = (
        models.JSONField(default=list, blank=True)
    )
    customer_id: int
    customer: models.ForeignKey[Customer, Customer] = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="invoices"
    )
    invoice_type: models.CharField[str, str] = models.CharField(
        max_length=20, choices=InvoiceType, default=InvoiceType.STANDARD
    )
    lifecycle_status: models.CharField[str, str] = models.CharField(
        max_length=20, choices=LifecycleStatus, default=LifecycleStatus.DRAFT
    )
    payment_status: models.CharField[str, str] = models.CharField(
        max_length=20, choices=PaymentStatus, default=PaymentStatus.UNPAID
    )
    payment_changed_at: models.DateTimeField[datetime | None, datetime | None] = (
        models.DateTimeField(null=True, blank=True)
    )
    payment_changed_by_id: int | None
    payment_changed_by: models.ForeignKey[User | None, User | None] = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payment_changes",
    )
    invoice_number: models.CharField[str | None, str | None] = models.CharField(
        max_length=80, null=True, blank=True, unique=True
    )
    issuance_key: models.CharField[str, str] = models.CharField(max_length=100, blank=True)
    snapshot: models.JSONField[dict[str, object] | None, dict[str, object] | None] = (
        models.JSONField(null=True, blank=True)
    )
    currency: models.CharField[str, str] = models.CharField(max_length=3, default="EUR")
    document_language: models.CharField[str, str] = models.CharField(
        max_length=2, choices=DocumentLanguage
    )
    issue_date: models.DateField[date, date] = models.DateField()
    due_date: models.DateField[date | None, date | None] = models.DateField(null=True, blank=True)
    recipient: models.JSONField[dict[str, str], dict[str, str]] = models.JSONField(
        default=dict, blank=True
    )
    custom_data: models.JSONField[dict[str, object], dict[str, object]] = models.JSONField(
        default=dict, blank=True
    )
    subtotal: models.DecimalField[Decimal, Decimal] = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    tax_total: models.DecimalField[Decimal, Decimal] = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    grand_total: models.DecimalField[Decimal, Decimal] = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    version: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=1)
    created_at: models.DateTimeField[object, object] = models.DateTimeField(auto_now_add=True)
    modified_at: models.DateTimeField[object, object] = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes: ClassVar[list[models.Index]] = [
            GinIndex(fields=("custom_data",), name="invoice_custom_data_gin")
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(lifecycle_status__in=("DRAFT", "ISSUING", "ISSUED", "CANCELLED")),
                name="invoice_supported_lifecycle",
            ),
            models.CheckConstraint(
                condition=Q(
                    invoice_type__in=("STANDARD", "CANCELLATION", "CREDIT_NOTE", "REPLACEMENT")
                ),
                name="invoice_supported_type",
            ),
            models.UniqueConstraint(
                fields=("original_invoice",),
                condition=Q(invoice_type="CANCELLATION"),
                name="one_full_cancellation_per_invoice",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        invoice_type="STANDARD",
                        original_invoice__isnull=True,
                        correction_reason="",
                        correction_key="",
                    )
                    | (
                        Q(
                            invoice_type__in=("CANCELLATION", "CREDIT_NOTE", "REPLACEMENT"),
                            original_invoice__isnull=False,
                        )
                        & ~Q(correction_reason="")
                        & ~Q(correction_key="")
                    )
                ),
                name="invoice_correction_identity",
            ),
            models.UniqueConstraint(
                fields=("original_invoice", "correction_key"),
                condition=~Q(invoice_type="STANDARD"),
                name="unique_correction_command",
            ),
            models.UniqueConstraint(
                fields=("original_invoice",),
                condition=Q(invoice_type="REPLACEMENT"),
                name="one_replacement_per_invoice",
            ),
            models.CheckConstraint(
                condition=~Q(original_invoice=models.F("pk")),
                name="invoice_no_self_correction",
            ),
            models.CheckConstraint(
                condition=Q(payment_status__in=("UNPAID", "PAID")), name="invoice_payment_state"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        lifecycle_status="DRAFT",
                        invoice_number__isnull=True,
                        snapshot__isnull=True,
                        issuance_key="",
                    )
                    | (
                        Q(
                            lifecycle_status__in=("ISSUING", "ISSUED", "CANCELLED"),
                            invoice_number__isnull=False,
                            snapshot__isnull=False,
                        )
                        & ~Q(issuance_key="")
                    )
                ),
                name="invoice_number_matches_lifecycle",
            ),
            models.CheckConstraint(
                condition=Q(subtotal__gte=0, tax_total__gte=0, grand_total__gte=0),
                name="invoice_nonnegative_totals",
            ),
            models.CheckConstraint(
                condition=Q(grand_total=models.F("subtotal") + models.F("tax_total")),
                name="invoice_totals_consistent",
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="invoice_positive_version"),
            models.CheckConstraint(
                condition=Q(document_language__in=("en", "de")), name="invoice_supported_language"
            ),
            models.CheckConstraint(condition=Q(currency="EUR"), name="invoice_supported_currency"),
        ]

    def __str__(self) -> str:
        return self.invoice_number or f"Draft {self.pk}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None and not self._state.adding:
            stored = Invoice.objects.get(pk=self.pk)
            if stored.lifecycle_status != LifecycleStatus.DRAFT or stored.invoice_type not in (
                InvoiceType.STANDARD,
                InvoiceType.REPLACEMENT,
            ):
                raise ValueError("Issuing invoices are immutable.")
        super().save(*args, **kwargs)

    @property
    def is_overdue(self) -> bool:
        from pinaks.apps.billing.payments import is_overdue

        return is_overdue(self, today=timezone.localdate())


class InvoiceLine(models.Model):
    """Ordered draft content and copied source values."""

    invoice_id: int
    invoice: models.ForeignKey[Invoice, Invoice] = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="lines"
    )
    position: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    service_date: models.DateField[date | None, date | None] = models.DateField(
        null=True, blank=True
    )
    service_period_end: models.DateField[date | None, date | None] = models.DateField(
        null=True, blank=True
    )
    item_code: models.CharField[str, str] = models.CharField(max_length=50, blank=True)
    description: models.CharField[str, str] = models.CharField(max_length=255)
    unit: models.CharField[str, str] = models.CharField(max_length=3)
    quantity: models.DecimalField[Decimal, Decimal] = models.DecimalField(
        max_digits=12, decimal_places=4
    )
    unit_price: models.DecimalField[Decimal, Decimal] = models.DecimalField(
        max_digits=12, decimal_places=2
    )
    discount_percent: models.DecimalField[Decimal, Decimal] = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    tax_category: models.CharField[str, str] = models.CharField(max_length=1)
    tax_rate: models.DecimalField[Decimal, Decimal] = models.DecimalField(
        max_digits=5, decimal_places=2
    )
    price_entry_policy: models.CharField[str, str] = models.CharField(max_length=5)
    exemption_reason_code: models.CharField[str, str] = models.CharField(max_length=50, blank=True)
    exemption_wording: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    custom_data: models.JSONField[dict[str, object], dict[str, object]] = models.JSONField(
        default=dict, blank=True
    )
    net_total: models.DecimalField[Decimal, Decimal] = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    tax_total: models.DecimalField[Decimal, Decimal] = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    gross_total: models.DecimalField[Decimal, Decimal] = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )

    class Meta:
        ordering = ("position", "pk")
        indexes: ClassVar[list[models.Index]] = [
            GinIndex(fields=("custom_data",), name="invoice_line_custom_gin")
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("invoice", "position"), name="unique_invoice_line_position"
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1), name="invoice_line_positive_position"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="invoice_line_positive_quantity"
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0), name="invoice_line_nonnegative_price"
            ),
            models.CheckConstraint(
                condition=Q(discount_percent__gte=0, discount_percent__lte=100),
                name="invoice_line_discount_range",
            ),
            models.CheckConstraint(
                condition=Q(tax_rate__gte=0, tax_rate__lte=100), name="invoice_line_rate_range"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        tax_category="S",
                        tax_rate__gt=0,
                        exemption_reason_code="",
                        exemption_wording="",
                    )
                    | (
                        Q(tax_category="E", tax_rate=0)
                        & ~Q(exemption_reason_code="")
                        & ~Q(exemption_wording="")
                    )
                ),
                name="invoice_line_tax_semantics",
            ),
            models.CheckConstraint(
                condition=Q(price_entry_policy__in=("net", "gross")),
                name="invoice_line_price_policy",
            ),
            models.CheckConstraint(
                condition=Q(net_total__gte=0, tax_total__gte=0, gross_total__gte=0),
                name="invoice_line_nonnegative_totals",
            ),
            models.CheckConstraint(
                condition=Q(gross_total=models.F("net_total") + models.F("tax_total")),
                name="invoice_line_totals_consistent",
            ),
        ]

    def __str__(self) -> str:
        return f"Invoice {self.invoice_id} line {self.position}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.invoice.lifecycle_status != LifecycleStatus.DRAFT:
            from django.core.exceptions import ValidationError

            raise ValidationError("Issuing invoice lines are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if self.invoice.lifecycle_status != LifecycleStatus.DRAFT:
            from django.core.exceptions import ValidationError

            raise ValidationError("Issuing invoice lines are immutable.")
        return super().delete(*args, **kwargs)


class InvoicePreset(models.Model):
    """Reusable, ordered draft defaults independent of catalog and document templates."""

    name: models.CharField[str, str] = models.CharField(max_length=120, unique=True)
    lines: models.JSONField[list[dict[str, str]], list[dict[str, str]]] = models.JSONField(
        default=list
    )
    is_archived: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    created_at: models.DateTimeField[object, object] = models.DateTimeField(auto_now_add=True)
    modified_at: models.DateTimeField[object, object] = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "pk")

    def __str__(self) -> str:
        return self.name

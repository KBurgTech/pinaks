from datetime import date
from decimal import Decimal
from typing import ClassVar

from django.db import models
from django.db.models import Q
from django.utils import timezone

from pinaks.apps.configuration.models import DocumentLanguage
from pinaks.apps.customers.models import Customer


class InvoiceType(models.TextChoices):
    STANDARD = "STANDARD", "Standard"


class LifecycleStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"


class PaymentStatus(models.TextChoices):
    UNPAID = "UNPAID", "Unpaid"
    PAID = "PAID", "Paid"


class Invoice(models.Model):
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
    invoice_number: models.CharField[str | None, str | None] = models.CharField(
        max_length=80, null=True, blank=True, unique=True
    )
    currency: models.CharField[str, str] = models.CharField(max_length=3, default="EUR")
    document_language: models.CharField[str, str] = models.CharField(
        max_length=2, choices=DocumentLanguage
    )
    issue_date: models.DateField[date, date] = models.DateField()
    due_date: models.DateField[date | None, date | None] = models.DateField(null=True, blank=True)
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
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(lifecycle_status="DRAFT"), name="invoice_supported_lifecycle"
            ),
            models.CheckConstraint(
                condition=Q(invoice_type="STANDARD"), name="invoice_supported_type"
            ),
            models.CheckConstraint(
                condition=Q(payment_status__in=("UNPAID", "PAID")), name="invoice_payment_state"
            ),
            models.CheckConstraint(
                condition=Q(invoice_number__isnull=True), name="draft_has_no_number"
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

    @property
    def is_overdue(self) -> bool:
        return bool(
            self.payment_status == PaymentStatus.UNPAID
            and self.due_date is not None
            and self.due_date < timezone.localdate()
        )


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

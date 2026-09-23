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

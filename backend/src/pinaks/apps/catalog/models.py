from decimal import Decimal
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from pinaks.apps.configuration.models import TaxProfile


class UnitCode(models.TextChoices):
    """Supported UN/CEFACT Recommendation 20 unit codes."""

    PIECE = "C62", "Piece"
    HOUR = "HUR", "Hour"
    DAY = "DAY", "Day"


class CatalogItem(models.Model):
    code: models.CharField[str, str] = models.CharField(
        max_length=50,
        unique=True,
        validators=[
            RegexValidator(
                r"^[A-Z][A-Z0-9_-]*$",
                "Use an uppercase language-neutral code containing letters, numbers, _ or -.",
            )
        ],
    )
    description_en: models.CharField[str, str] = models.CharField(max_length=255)
    description_de: models.CharField[str, str] = models.CharField(max_length=255)
    unit: models.CharField[str, str] = models.CharField(max_length=3, choices=UnitCode)
    default_price: models.DecimalField[Decimal, Decimal] = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    minimum_price: models.DecimalField[Decimal | None, Decimal | None] = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    maximum_price: models.DecimalField[Decimal | None, Decimal | None] = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    default_tax_profile_id: int
    default_tax_profile: models.ForeignKey[TaxProfile, TaxProfile] = models.ForeignKey(
        TaxProfile,
        on_delete=models.PROTECT,
        related_name="catalog_items",
    )
    is_archived: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    created_at: models.DateTimeField[object, object] = models.DateTimeField(auto_now_add=True)
    modified_at: models.DateTimeField[object, object] = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("code",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~Q(description_en=""),
                name="catalog_english_description_required",
            ),
            models.CheckConstraint(
                condition=~Q(description_de=""),
                name="catalog_german_description_required",
            ),
            models.CheckConstraint(
                condition=Q(unit__in=UnitCode.values),
                name="catalog_supported_unit",
            ),
            models.CheckConstraint(
                condition=Q(default_price__gte=0),
                name="catalog_default_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(minimum_price__isnull=True) | Q(minimum_price__gte=0),
                name="catalog_minimum_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(maximum_price__isnull=True) | Q(maximum_price__gte=0),
                name="catalog_maximum_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(minimum_price__isnull=True)
                | Q(default_price__gte=models.F("minimum_price")),
                name="catalog_default_at_or_above_minimum",
            ),
            models.CheckConstraint(
                condition=Q(maximum_price__isnull=True)
                | Q(default_price__lte=models.F("maximum_price")),
                name="catalog_default_at_or_below_maximum",
            ),
            models.CheckConstraint(
                condition=Q(minimum_price__isnull=True)
                | Q(maximum_price__isnull=True)
                | Q(minimum_price__lte=models.F("maximum_price")),
                name="catalog_advisory_price_order",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.description_en}"

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if not self.description_en.strip():
            errors["description_en"] = "An English description is required."
        if not self.description_de.strip():
            errors["description_de"] = "A German description is required."
        if (
            isinstance(self.minimum_price, Decimal)
            and isinstance(self.default_price, Decimal)
            and self.default_price < self.minimum_price
        ):
            errors["minimum_price"] = "The minimum price cannot exceed the default price."
        if (
            isinstance(self.maximum_price, Decimal)
            and isinstance(self.default_price, Decimal)
            and self.default_price > self.maximum_price
        ):
            errors["maximum_price"] = "The maximum price cannot be below the default price."
        if errors:
            raise ValidationError(errors)

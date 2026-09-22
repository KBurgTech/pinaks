from collections.abc import Mapping
from decimal import Decimal
from typing import Any, ClassVar, Final

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q


class DocumentLanguage(models.TextChoices):
    ENGLISH = "en", "English"
    GERMAN = "de", "German"


class InstallationLocale(models.TextChoices):
    ENGLISH_GERMANY = "en-DE", "English (Germany)"
    GERMAN_GERMANY = "de-DE", "German (Germany)"


class InvoiceNumberReset(models.TextChoices):
    NEVER = "never", "Never"
    ANNUAL = "annual", "Annually"


class TaxCategory(models.TextChoices):
    STANDARD = "S", "Standard rated"
    EXEMPT = "E", "Exempt"


class PriceEntryPolicy(models.TextChoices):
    NET = "net", "Net"
    GROSS = "gross", "Gross"


class TaxColumnPolicy(models.TextChoices):
    SHOW = "show", "Show"
    HIDE = "hide", "Hide"


class SellerTaxIdentifier(models.TextChoices):
    TAX_NUMBER = "tax_number", "Tax number"
    VAT_IDENTIFIER = "vat_identifier", "VAT identifier"


FEATURE_FIELDS: Final[dict[str, str]] = {
    "payment_requests": "feature_payment_requests",
    "reminders": "feature_reminders",
    "time_tracking": "feature_time_tracking",
}


class CompanyProfile(models.Model):
    """Current installation configuration; issued documents snapshot its values."""

    SINGLETON_PK: ClassVar[int] = 1

    id: models.PositiveSmallIntegerField[int, int] = models.PositiveSmallIntegerField(
        primary_key=True,
        default=SINGLETON_PK,
        editable=False,
    )
    legal_name: models.CharField[str, str] = models.CharField(max_length=255)
    address_line_1: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    address_line_2: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    postal_code: models.CharField[str, str] = models.CharField(max_length=20, blank=True)
    city: models.CharField[str, str] = models.CharField(max_length=100, blank=True)
    country_code: models.CharField[str, str] = models.CharField(
        max_length=2,
        default="DE",
        validators=[RegexValidator(r"^[A-Z]{2}$", "Use an ISO 3166-1 alpha-2 code.")],
    )
    email: models.EmailField[str, str] = models.EmailField(blank=True)
    phone: models.CharField[str, str] = models.CharField(max_length=50, blank=True)
    tax_number: models.CharField[str, str] = models.CharField(max_length=50, blank=True)
    vat_identifier: models.CharField[str, str] = models.CharField(max_length=50, blank=True)
    company_identifier: models.CharField[str, str] = models.CharField(max_length=100, blank=True)
    bank_account_holder: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    iban: models.CharField[str, str] = models.CharField(max_length=34, blank=True)
    bic: models.CharField[str, str] = models.CharField(max_length=11, blank=True)
    payment_instructions: models.TextField[str, str] = models.TextField(blank=True)
    default_currency: models.CharField[str, str] = models.CharField(
        max_length=3, choices=(("EUR", "Euro"),), default="EUR"
    )
    default_locale: models.CharField[str, str] = models.CharField(
        max_length=5,
        choices=InstallationLocale,
        default=InstallationLocale.GERMAN_GERMANY,
    )
    default_ui_language: models.CharField[str, str] = models.CharField(
        max_length=2,
        choices=DocumentLanguage,
        default=DocumentLanguage.GERMAN,
    )
    default_document_language: models.CharField[str, str] = models.CharField(
        max_length=2,
        choices=DocumentLanguage,
        default=DocumentLanguage.GERMAN,
    )
    invoice_number_prefix: models.CharField[str, str] = models.CharField(
        max_length=30, default="RE-"
    )
    invoice_number_next: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    invoice_number_padding: models.PositiveSmallIntegerField[int, int] = (
        models.PositiveSmallIntegerField(
            default=4,
            validators=[MinValueValidator(1), MaxValueValidator(12)],
        )
    )
    invoice_number_reset: models.CharField[str, str] = models.CharField(
        max_length=10,
        choices=InvoiceNumberReset,
        default=InvoiceNumberReset.ANNUAL,
    )
    feature_payment_requests: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    feature_reminders: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    feature_time_tracking: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    modified_at: models.DateTimeField[object, object] = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "company profile"

    def __str__(self) -> str:
        return self.legal_name


class TaxProfile(models.Model):
    """A constrained, versioned German invoice tax treatment."""

    code: models.SlugField[str, str] = models.SlugField(max_length=80)
    version: models.PositiveSmallIntegerField[int, int] = models.PositiveSmallIntegerField(
        default=1
    )
    name: models.CharField[str, str] = models.CharField(max_length=120)
    tax_category: models.CharField[str, str] = models.CharField(max_length=1, choices=TaxCategory)
    rate: models.DecimalField[Decimal, Decimal] = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )
    exemption_reason_code: models.CharField[str, str] = models.CharField(max_length=50, blank=True)
    exemption_wording_en: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    exemption_wording_de: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    price_entry_policy: models.CharField[str, str] = models.CharField(
        max_length=5, choices=PriceEntryPolicy
    )
    tax_column_policy: models.CharField[str, str] = models.CharField(
        max_length=4, choices=TaxColumnPolicy
    )
    requires_tax_number: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    requires_vat_identifier: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    is_default: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    is_current: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    used_at: models.DateTimeField[object, object | None] = models.DateTimeField(
        null=True, blank=True
    )
    created_at: models.DateTimeField[object, object] = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("code", "-version")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=("code", "version"), name="unique_tax_profile_version"),
            models.UniqueConstraint(
                fields=("code",),
                condition=Q(is_current=True),
                name="unique_current_tax_profile_code",
            ),
            models.UniqueConstraint(
                fields=("is_default",),
                condition=Q(is_default=True, is_current=True),
                name="one_current_default_tax_profile",
            ),
            models.CheckConstraint(
                condition=Q(requires_tax_number=True) | Q(requires_vat_identifier=True),
                name="tax_profile_requires_seller_identifier",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        tax_category=TaxCategory.STANDARD,
                        rate__gt=0,
                        exemption_reason_code="",
                        exemption_wording_en="",
                        exemption_wording_de="",
                    )
                    | (
                        Q(tax_category=TaxCategory.EXEMPT, rate=0)
                        & ~Q(exemption_reason_code="")
                        & ~Q(exemption_wording_en="")
                        & ~Q(exemption_wording_de="")
                    )
                ),
                name="supported_german_tax_profile",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} (v{self.version})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding and self.pk is not None:
            stored = TaxProfile.objects.get(pk=self.pk)
            semantic_fields = (
                "code",
                "version",
                "name",
                "tax_category",
                "rate",
                "exemption_reason_code",
                "exemption_wording_en",
                "exemption_wording_de",
                "price_entry_policy",
                "tax_column_policy",
                "requires_tax_number",
                "requires_vat_identifier",
            )
            if stored.used_at is not None and any(
                getattr(stored, field) != getattr(self, field) for field in semantic_fields
            ):
                raise ValidationError("Used tax profile versions are immutable.")
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.tax_category == TaxCategory.STANDARD:
            if isinstance(self.rate, Decimal) and self.rate <= 0:
                errors["rate"] = "A standard-rated profile requires a positive rate."
            for field in (
                "exemption_reason_code",
                "exemption_wording_en",
                "exemption_wording_de",
            ):
                if getattr(self, field):
                    errors[field] = "A standard-rated profile cannot contain exemption details."
        elif self.tax_category == TaxCategory.EXEMPT:
            if isinstance(self.rate, Decimal) and self.rate != 0:
                errors["rate"] = "An exempt profile requires a zero rate."
            for field in (
                "exemption_reason_code",
                "exemption_wording_en",
                "exemption_wording_de",
            ):
                if not str(getattr(self, field)).strip():
                    errors[field] = "This field is required for an exempt profile."
        if not self.required_seller_identifiers:
            errors["required_seller_identifiers"] = (
                "At least one seller tax identifier must be required."
            )
        if errors:
            raise ValidationError(errors)

    @property
    def required_seller_identifiers(self) -> list[str]:
        identifiers: list[str] = []
        if self.requires_tax_number:
            identifiers.append(SellerTaxIdentifier.TAX_NUMBER)
        if self.requires_vat_identifier:
            identifiers.append(SellerTaxIdentifier.VAT_IDENTIFIER)
        return identifiers

    @property
    def translation_complete(self) -> bool:
        return self.tax_category != TaxCategory.EXEMPT or bool(
            self.exemption_wording_en.strip() and self.exemption_wording_de.strip()
        )

    @classmethod
    def from_values(cls, values: Mapping[str, object]) -> TaxProfile:
        model_values = dict(values)
        identifiers = model_values.pop("required_seller_identifiers", [])
        profile = cls(**model_values)
        if isinstance(identifiers, (list, tuple, set, frozenset)):
            profile.requires_tax_number = SellerTaxIdentifier.TAX_NUMBER in identifiers
            profile.requires_vat_identifier = SellerTaxIdentifier.VAT_IDENTIFIER in identifiers
        return profile

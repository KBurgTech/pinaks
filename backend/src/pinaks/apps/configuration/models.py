from typing import ClassVar, Final

from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models


class DocumentLanguage(models.TextChoices):
    ENGLISH = "en", "English"
    GERMAN = "de", "German"


class InstallationLocale(models.TextChoices):
    ENGLISH_GERMANY = "en-DE", "English (Germany)"
    GERMAN_GERMANY = "de-DE", "German (Germany)"


class InvoiceNumberReset(models.TextChoices):
    NEVER = "never", "Never"
    ANNUAL = "annual", "Annually"


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

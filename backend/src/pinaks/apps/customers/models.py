from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from pinaks.apps.configuration.models import DocumentLanguage

if TYPE_CHECKING:
    from django.db.models.manager import Manager


class PartyType(models.TextChoices):
    PERSON = "person", "Person"
    ORGANIZATION = "organization", "Organization"


class PartyFields(models.Model):
    party_type: models.CharField[str, str] = models.CharField(max_length=20, choices=PartyType)
    given_name: models.CharField[str, str] = models.CharField(max_length=120, blank=True)
    family_name: models.CharField[str, str] = models.CharField(max_length=120, blank=True)
    organization_name: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    email: models.EmailField[str, str] = models.EmailField(blank=True)
    phone: models.CharField[str, str] = models.CharField(max_length=50, blank=True)

    class Meta:
        abstract = True

    @property
    def display_name(self) -> str:
        if self.party_type == PartyType.ORGANIZATION:
            return self.organization_name
        return " ".join(part for part in (self.given_name, self.family_name) if part)

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.party_type == PartyType.PERSON:
            if not self.given_name.strip():
                errors["given_name"] = "A person requires a given name."
            if not self.family_name.strip():
                errors["family_name"] = "A person requires a family name."
            if self.organization_name.strip():
                errors["organization_name"] = "A person cannot have an organization name."
        elif self.party_type == PartyType.ORGANIZATION:
            if not self.organization_name.strip():
                errors["organization_name"] = "An organization requires a name."
            if self.given_name.strip():
                errors["given_name"] = "An organization cannot have a given name."
            if self.family_name.strip():
                errors["family_name"] = "An organization cannot have a family name."
        if errors:
            raise ValidationError(errors)


class Customer(PartyFields):
    addresses: Manager[CustomerAddress]
    billing_recipients: Manager[BillingRecipient]
    customer_number: models.CharField[str, str] = models.CharField(max_length=50, unique=True)
    preferred_language: models.CharField[str, str] = models.CharField(
        max_length=2, choices=DocumentLanguage, default=DocumentLanguage.GERMAN
    )
    is_archived: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    created_at: models.DateTimeField[object, object] = models.DateTimeField(auto_now_add=True)
    modified_at: models.DateTimeField[object, object] = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("customer_number",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(
                    Q(
                        party_type=PartyType.PERSON,
                        given_name__gt="",
                        family_name__gt="",
                        organization_name="",
                    )
                    | (
                        Q(party_type=PartyType.ORGANIZATION, organization_name__gt="")
                        & Q(given_name="", family_name="")
                    )
                ),
                name="customer_party_fields_match_type",
            )
        ]

    def __str__(self) -> str:
        return f"{self.customer_number} — {self.display_name}"


class CustomerAddress(models.Model):
    customer_id: int
    customer: models.ForeignKey[Customer, Customer] = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="addresses"
    )
    label: models.CharField[str, str] = models.CharField(max_length=80)
    address_line_1: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    address_line_2: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    postal_code: models.CharField[str, str] = models.CharField(max_length=20, blank=True)
    city: models.CharField[str, str] = models.CharField(max_length=100, blank=True)
    country_code: models.CharField[str, str] = models.CharField(
        max_length=2,
        default="DE",
        validators=[RegexValidator(r"^[A-Z]{2}$", "Use an ISO 3166-1 alpha-2 code.")],
    )
    is_primary: models.BooleanField[bool, bool] = models.BooleanField(default=False)

    class Meta:
        ordering = ("pk",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("customer", "label"), name="unique_customer_address_label"
            ),
            models.UniqueConstraint(
                fields=("customer",),
                condition=Q(is_primary=True),
                name="one_primary_address_per_customer",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer.customer_number}: {self.label}"


class BillingRecipient(PartyFields):
    customer_id: int
    customer: models.ForeignKey[Customer, Customer] = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="billing_recipients"
    )
    address_line_1: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    address_line_2: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    postal_code: models.CharField[str, str] = models.CharField(max_length=20, blank=True)
    city: models.CharField[str, str] = models.CharField(max_length=100, blank=True)
    country_code: models.CharField[str, str] = models.CharField(
        max_length=2,
        default="DE",
        validators=[RegexValidator(r"^[A-Z]{2}$", "Use an ISO 3166-1 alpha-2 code.")],
    )
    created_at: models.DateTimeField[object, object] = models.DateTimeField(auto_now_add=True)
    modified_at: models.DateTimeField[object, object] = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("pk",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(
                    Q(
                        party_type=PartyType.PERSON,
                        given_name__gt="",
                        family_name__gt="",
                        organization_name="",
                    )
                    | (
                        Q(party_type=PartyType.ORGANIZATION, organization_name__gt="")
                        & Q(given_name="", family_name="")
                    )
                ),
                name="billing_recipient_party_fields_match_type",
            )
        ]

    def __str__(self) -> str:
        return f"{self.customer.customer_number}: {self.display_name}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

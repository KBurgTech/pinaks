from typing import ClassVar

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q


class FieldTarget(models.TextChoices):
    CUSTOMER = "customer", "Customer"
    CATALOG_ITEM = "catalog_item", "Catalog item"


class FieldType(models.TextChoices):
    TEXT = "text", "Text"
    LONG_TEXT = "long_text", "Long text"
    INTEGER = "integer", "Integer"
    DECIMAL = "decimal", "Decimal"
    BOOLEAN = "boolean", "Boolean"
    DATE = "date", "Date"
    CHOICE = "choice", "Choice"


class SearchMode(models.TextChoices):
    NONE = "none", "None"
    EXACT = "exact", "Exact"
    RANGE = "range", "Range"
    TEXT = "text", "Text"


class FieldVisibility(models.TextChoices):
    INTERNAL = "internal", "Internal"
    DOCUMENT = "document", "Document"


class CustomFieldDefinition(models.Model):
    key: models.CharField[str, str] = models.CharField(
        max_length=64,
        validators=[RegexValidator(r"^[a-z][a-z0-9_]*$", "Use a lowercase machine key.")],
    )
    target: models.CharField[str, str] = models.CharField(max_length=20, choices=FieldTarget)
    data_type: models.CharField[str, str] = models.CharField(max_length=20, choices=FieldType)
    label_en: models.CharField[str, str] = models.CharField(max_length=120)
    label_de: models.CharField[str, str] = models.CharField(max_length=120)
    help_en: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    help_de: models.CharField[str, str] = models.CharField(max_length=255, blank=True)
    required: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    default_value: models.JSONField[object, object] = models.JSONField(null=True, blank=True)
    choices: models.JSONField[list[dict[str, str]], list[dict[str, str]]] = models.JSONField(
        default=list, blank=True
    )
    display_order: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    visibility: models.CharField[str, str] = models.CharField(
        max_length=20, choices=FieldVisibility, default=FieldVisibility.INTERNAL
    )
    search_mode: models.CharField[str, str] = models.CharField(
        max_length=10, choices=SearchMode, default=SearchMode.NONE
    )
    is_sensitive: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    is_retired: models.BooleanField[bool, bool] = models.BooleanField(default=False)

    class Meta:
        ordering = ("target", "display_order", "key")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("target", "key"), name="unique_custom_field_target_key"
            ),
            models.CheckConstraint(
                condition=Q(target__in=FieldTarget.values), name="custom_field_target"
            ),
            models.CheckConstraint(
                condition=Q(data_type__in=FieldType.values), name="custom_field_type"
            ),
            models.CheckConstraint(
                condition=Q(search_mode__in=SearchMode.values), name="custom_field_search"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.target}.{self.key}"

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if not self.label_en.strip():
            errors["label_en"] = "An English label is required."
        if not self.label_de.strip():
            errors["label_de"] = "A German label is required."
        if self.search_mode == SearchMode.RANGE and self.data_type not in {
            FieldType.INTEGER,
            FieldType.DECIMAL,
            FieldType.DATE,
        }:
            errors["search_mode"] = "Range search requires integer, decimal or date."
        if self.search_mode == SearchMode.TEXT and self.data_type not in {
            FieldType.TEXT,
            FieldType.LONG_TEXT,
        }:
            errors["search_mode"] = "Text search requires text."
        if self.search_mode == SearchMode.EXACT and self.data_type not in {
            FieldType.TEXT,
            FieldType.INTEGER,
            FieldType.DECIMAL,
            FieldType.BOOLEAN,
            FieldType.CHOICE,
        }:
            errors["search_mode"] = "Exact search is not supported for this type."
        if self.is_sensitive and (
            self.search_mode != SearchMode.NONE or self.visibility != FieldVisibility.INTERNAL
        ):
            errors["is_sensitive"] = "Sensitive fields cannot be searched or placed on documents."
        if self.data_type == FieldType.CHOICE:
            if not self.choices or any(
                not isinstance(choice, dict)
                or set(choice) != {"code", "label_en", "label_de"}
                or not all(isinstance(value, str) and value.strip() for value in choice.values())
                for choice in self.choices
            ):
                errors["choices"] = "Choices need a code and English and German labels."
            elif len({choice["code"] for choice in self.choices}) != len(self.choices):
                errors["choices"] = "Choice codes must be unique."
        elif self.choices:
            errors["choices"] = "Only choice fields may define choices."
        if errors:
            raise ValidationError(errors)

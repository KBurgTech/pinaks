from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import QuerySet

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.services import record_event
from pinaks.apps.custom_fields.models import CustomFieldDefinition, FieldType


class DefinitionKeyImmutableError(ValueError):
    pass


_FIELDS = (
    "key",
    "target",
    "data_type",
    "label_en",
    "label_de",
    "help_en",
    "help_de",
    "required",
    "default_value",
    "choices",
    "display_order",
    "visibility",
    "search_mode",
    "is_sensitive",
)


def _normalize_value(field: CustomFieldDefinition, value: object) -> object:
    kind = field.data_type
    valid = False
    if kind in {FieldType.TEXT, FieldType.LONG_TEXT}:
        valid = isinstance(value, str) and (kind != FieldType.TEXT or len(value) <= 255)
    elif kind == FieldType.INTEGER:
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif kind == FieldType.DECIMAL:
        try:
            number = (
                Decimal(value)
                if isinstance(value, (str, int, Decimal)) and not isinstance(value, bool)
                else Decimal("NaN")
            )
            exponent = number.as_tuple().exponent
            valid = number.is_finite() and isinstance(exponent, int) and exponent >= -2
            if valid:
                value = str(number)
        except InvalidOperation:
            valid = False
    elif kind == FieldType.BOOLEAN:
        valid = isinstance(value, bool)
    elif kind == FieldType.DATE:
        if isinstance(value, str):
            try:
                valid = date.fromisoformat(value).isoformat() == value
            except ValueError:
                pass
    elif kind == FieldType.CHOICE:
        valid = isinstance(value, str) and value in {choice["code"] for choice in field.choices}
    if not valid:
        raise ValidationError({"custom_data": f"Invalid value for {field.key}."})
    return value


def validate_custom_data(
    *, target: str, values: object, existing: Mapping[str, object] | None = None
) -> dict[str, object]:
    definitions = {
        field.key: field for field in CustomFieldDefinition.objects.filter(target=target)
    }
    if not isinstance(values, Mapping) or any(not isinstance(key, str) for key in values):
        raise ValidationError({"custom_data": "Expected an object with string keys."})
    result = dict(existing or {})
    for key, value in values.items():
        field = definitions.get(key)
        if field is None or (field.is_retired and key not in result):
            raise ValidationError({"custom_data": f"Unknown or retired field: {key}."})
        if value is None:
            result.pop(key, None)
        else:
            result[key] = _normalize_value(field, value)
    for field in definitions.values():
        if not field.is_retired and field.key not in result:
            if field.default_value is not None:
                result[field.key] = _normalize_value(field, field.default_value)
            elif field.required:
                raise ValidationError({"custom_data": f"Required field: {field.key}."})
    return result


@transaction.atomic
def publish_definition(
    *, values: Mapping[str, object], actor: User, correlation_id: str
) -> CustomFieldDefinition:
    field = CustomFieldDefinition()
    for key in _FIELDS:
        if key in values:
            setattr(field, key, values[key])
    field.full_clean()
    if field.default_value is not None:
        field.default_value = _normalize_value(field, field.default_value)
    field.save(force_insert=True)
    record_event(
        action_code="custom_fields.definition_published",
        target_type="custom_fields.definition",
        target_identifier=str(field.pk),
        actor=actor,
        correlation_id=correlation_id,
        metadata={"key": field.key, "target": field.target},
    )
    return field


@transaction.atomic
def update_definition(
    *, field: CustomFieldDefinition, values: Mapping[str, object], actor: User, correlation_id: str
) -> CustomFieldDefinition:
    field = CustomFieldDefinition.objects.select_for_update().get(pk=field.pk)
    if any(
        key in values and values[key] != getattr(field, key)
        for key in ("key", "target", "data_type")
    ):
        raise DefinitionKeyImmutableError("The field key, target and type cannot be changed.")
    if field.is_sensitive and values.get("is_sensitive") is False:
        raise ValidationError({"is_sensitive": "A published sensitive field cannot become public."})
    old_choice_codes = {choice["code"] for choice in field.choices}
    for key in _FIELDS:
        if key in values:
            setattr(field, key, values[key])
    field.full_clean()
    if not old_choice_codes.issubset({choice["code"] for choice in field.choices}):
        raise ValidationError({"choices": "Published choice codes cannot be removed."})
    if field.default_value is not None:
        field.default_value = _normalize_value(field, field.default_value)
    field.save()
    record_event(
        action_code="custom_fields.definition_updated",
        target_type="custom_fields.definition",
        target_identifier=str(field.pk),
        actor=actor,
        correlation_id=correlation_id,
        metadata={"key": field.key, "target": field.target},
    )
    return field


@transaction.atomic
def retire_definition(*, field: CustomFieldDefinition, actor: User, correlation_id: str) -> None:
    field = CustomFieldDefinition.objects.select_for_update().get(pk=field.pk)
    if not field.is_retired:
        field.is_retired = True
        field.save(update_fields=("is_retired",))
        record_event(
            action_code="custom_fields.definition_retired",
            target_type="custom_fields.definition",
            target_identifier=str(field.pk),
            actor=actor,
            correlation_id=correlation_id,
            metadata={"key": field.key, "target": field.target},
        )


def definitions_for_target(
    *, target: str, include_retired: bool = False
) -> QuerySet[CustomFieldDefinition]:
    result = CustomFieldDefinition.objects.filter(target=target)
    if not include_retired:
        result = result.filter(is_retired=False)
    return result.order_by("display_order", "key")


def redact_custom_data(*, target: str, values: Mapping[str, object]) -> dict[str, object]:
    sensitive = set(
        CustomFieldDefinition.objects.filter(target=target, is_sensitive=True).values_list(
            "key", flat=True
        )
    )
    return {key: value for key, value in values.items() if key not in sensitive}


def filter_custom_data[ModelT: models.Model](
    queryset: QuerySet[ModelT], *, target: str, key: str, operator: str, value: object
) -> QuerySet[ModelT]:
    from django.db.models import DateField, DecimalField, IntegerField
    from django.db.models.fields.json import KeyTextTransform
    from django.db.models.functions import Cast

    try:
        field = CustomFieldDefinition.objects.get(target=target, key=key, is_retired=False)
    except CustomFieldDefinition.DoesNotExist as error:
        raise ValidationError({"field": "Unknown searchable field."}) from error
    if field.is_sensitive or field.search_mode == "none":
        raise ValidationError({"field": "This field is not searchable."})
    if operator == "exact" and field.search_mode == "exact":
        if field.data_type == FieldType.BOOLEAN and value in {"true", "false"}:
            value = value == "true"
        if field.data_type == FieldType.INTEGER and isinstance(value, str):
            try:
                value = int(value)
            except ValueError:
                raise ValidationError({"value": "Enter an integer."}) from None
        normalized = _normalize_value(field, value)
        return queryset.filter(**{f"custom_data__{key}": normalized})
    if operator == "text" and field.search_mode == "text" and isinstance(value, str):
        return queryset.filter(**{f"custom_data__{key}__icontains": value})
    if operator in {"gte", "lte"} and field.search_mode == "range":
        if field.data_type == FieldType.INTEGER and isinstance(value, str):
            try:
                value = int(value)
            except ValueError:
                raise ValidationError({"value": "Enter an integer."}) from None
        normalized = _normalize_value(field, value)
        output_field: models.Field[object, object]
        if field.data_type == FieldType.INTEGER:
            output_field = IntegerField()
        elif field.data_type == FieldType.DECIMAL:
            output_field = DecimalField(max_digits=18, decimal_places=2)
        else:
            output_field = DateField()
        return queryset.annotate(
            _custom_filter_value=Cast(
                KeyTextTransform(key, "custom_data"), output_field=output_field
            )
        ).filter(**{f"_custom_filter_value__{operator}": normalized})
    raise ValidationError({"operator": "Operator is incompatible with the field search mode."})


def sensitive_custom_data(
    *, target: str, instance: models.Model, actor: User, correlation_id: str
) -> dict[str, object]:
    values = getattr(instance, "custom_data")  # noqa: B009 - model boundary
    keys = set(
        CustomFieldDefinition.objects.filter(target=target, is_sensitive=True).values_list(
            "key", flat=True
        )
    )
    result = {key: value for key, value in values.items() if key in keys}
    record_event(
        action_code="custom_fields.sensitive_accessed",
        target_type=f"{target}.sensitive_fields",
        target_identifier=str(instance.pk),
        actor=actor,
        correlation_id=correlation_id,
        metadata={"keys": sorted(result)},
    )
    return result

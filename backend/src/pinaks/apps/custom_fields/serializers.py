from rest_framework import serializers

from pinaks.apps.custom_fields.models import CustomFieldDefinition


class CustomFieldDefinitionSerializer(serializers.Serializer[CustomFieldDefinition]):
    id = serializers.IntegerField(read_only=True)
    key = serializers.RegexField(r"^[a-z][a-z0-9_]*$", max_length=64)
    target = serializers.ChoiceField(
        choices=("customer", "catalog_item", "invoice", "invoice_line")
    )
    data_type = serializers.ChoiceField(
        choices=("text", "long_text", "integer", "decimal", "boolean", "date", "choice")
    )
    label_en = serializers.CharField(max_length=120)
    label_de = serializers.CharField(max_length=120)
    help_en = serializers.CharField(max_length=255, allow_blank=True, required=False)
    help_de = serializers.CharField(max_length=255, allow_blank=True, required=False)
    required = serializers.BooleanField(required=False)  # type: ignore[assignment]
    default_value = serializers.JSONField(required=False, allow_null=True)
    choices = serializers.JSONField(required=False)
    display_order = serializers.IntegerField(min_value=0, required=False)
    visibility = serializers.ChoiceField(choices=("internal", "document"), required=False)
    search_mode = serializers.ChoiceField(
        choices=("none", "exact", "range", "text"), required=False
    )
    is_sensitive = serializers.BooleanField(required=False)
    is_retired = serializers.BooleanField(read_only=True)

    def to_internal_value(self, data: object) -> dict[str, object]:
        if isinstance(data, dict):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({key: "Unknown field." for key in unknown})
        return super().to_internal_value(data)

    def to_representation(self, instance: CustomFieldDefinition) -> dict[str, object]:
        return {
            "id": instance.pk,
            "key": instance.key,
            "target": instance.target,
            "data_type": instance.data_type,
            "label_en": instance.label_en,
            "label_de": instance.label_de,
            "help_en": instance.help_en,
            "help_de": instance.help_de,
            "required": instance.required,
            "default_value": None if instance.is_sensitive else instance.default_value,
            "choices": instance.choices,
            "display_order": instance.display_order,
            "visibility": instance.visibility,
            "search_mode": instance.search_mode,
            "is_sensitive": instance.is_sensitive,
            "is_retired": instance.is_retired,
        }

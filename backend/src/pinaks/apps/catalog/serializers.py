from rest_framework import serializers

from pinaks.apps.catalog.models import CatalogItem
from pinaks.apps.configuration.models import TaxProfile
from pinaks.apps.custom_fields.services import redact_custom_data


class CatalogTaxProfileSummarySerializer(serializers.Serializer[TaxProfile]):
    id = serializers.IntegerField(read_only=True)
    code = serializers.CharField(read_only=True)
    version = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    rate = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    tax_category = serializers.CharField(read_only=True)


class CatalogItemSerializer(serializers.Serializer[CatalogItem]):
    id = serializers.IntegerField(read_only=True)
    code = serializers.RegexField(r"^[A-Z][A-Z0-9_-]*$", max_length=50)
    description_en = serializers.CharField(max_length=255, allow_blank=False, trim_whitespace=True)
    description_de = serializers.CharField(max_length=255, allow_blank=False, trim_whitespace=True)
    unit = serializers.ChoiceField(choices=("C62", "HUR", "DAY"))
    default_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    minimum_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, allow_null=True, required=False
    )
    maximum_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, allow_null=True, required=False
    )
    default_tax_profile_id = serializers.IntegerField(min_value=1, write_only=True)
    default_tax_profile = CatalogTaxProfileSummarySerializer(read_only=True)
    is_archived = serializers.BooleanField(read_only=True)
    custom_data = serializers.JSONField(required=False)

    def to_internal_value(self, data: object) -> dict[str, object]:
        if isinstance(data, dict):
            unknown_fields = set(data).difference(self.fields)
            if unknown_fields:
                raise serializers.ValidationError(
                    {
                        field: [
                            serializers.ErrorDetail(
                                "This field is not accepted.", code="unknown_field"
                            )
                        ]
                        for field in sorted(unknown_fields)
                    }
                )
        return super().to_internal_value(data)

    def to_representation(self, instance: CatalogItem) -> dict[str, object]:
        return {
            "id": instance.pk,
            "code": instance.code,
            "description_en": instance.description_en,
            "description_de": instance.description_de,
            "unit": instance.unit,
            "default_price": f"{instance.default_price:.2f}",
            "minimum_price": (
                f"{instance.minimum_price:.2f}" if instance.minimum_price is not None else None
            ),
            "maximum_price": (
                f"{instance.maximum_price:.2f}" if instance.maximum_price is not None else None
            ),
            "default_tax_profile": {
                "id": instance.default_tax_profile.pk,
                "code": instance.default_tax_profile.code,
                "version": instance.default_tax_profile.version,
                "name": instance.default_tax_profile.name,
                "rate": f"{instance.default_tax_profile.rate:.2f}",
                "tax_category": instance.default_tax_profile.tax_category,
            },
            "is_archived": instance.is_archived,
            "custom_data": redact_custom_data(target="catalog_item", values=instance.custom_data),
        }

from rest_framework import serializers

from pinaks.apps.configuration.models import FEATURE_FIELDS, CompanyProfile, TaxProfile


class ApiRootSerializer(serializers.Serializer[dict[str, str]]):
    capabilities = serializers.URLField()
    probe = serializers.URLField()
    schema = serializers.URLField()


class ProbeSerializer(serializers.Serializer[dict[str, object]]):
    status = serializers.CharField()
    checks = serializers.ListField(child=serializers.CharField())


class CapabilitiesSerializer(serializers.Serializer[dict[str, object]]):
    role = serializers.ChoiceField(choices=("admin", "company_member", "read_only"))
    capabilities = serializers.DictField(child=serializers.BooleanField())
    features = serializers.DictField(child=serializers.BooleanField())


class FeatureFlagsSerializer(serializers.Serializer[dict[str, bool]]):
    payment_requests = serializers.BooleanField()
    reminders = serializers.BooleanField()
    time_tracking = serializers.BooleanField()

    def to_internal_value(self, data: object) -> dict[str, bool]:
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


class CompanyProfileSerializer(serializers.Serializer[CompanyProfile]):
    legal_name = serializers.CharField(max_length=255)
    address_line_1 = serializers.CharField(max_length=255, allow_blank=True)
    address_line_2 = serializers.CharField(max_length=255, allow_blank=True)
    postal_code = serializers.CharField(max_length=20, allow_blank=True)
    city = serializers.CharField(max_length=100, allow_blank=True)
    country_code = serializers.RegexField(r"^[A-Z]{2}$", max_length=2)
    email = serializers.EmailField(allow_blank=True)
    phone = serializers.CharField(max_length=50, allow_blank=True)
    tax_number = serializers.CharField(max_length=50, allow_blank=True)
    vat_identifier = serializers.CharField(max_length=50, allow_blank=True)
    company_identifier = serializers.CharField(max_length=100, allow_blank=True)
    bank_account_holder = serializers.CharField(max_length=255, allow_blank=True)
    iban = serializers.CharField(max_length=34, allow_blank=True)
    bic = serializers.CharField(max_length=11, allow_blank=True)
    payment_instructions = serializers.CharField(allow_blank=True)
    default_currency = serializers.ChoiceField(choices=("EUR",))
    default_locale = serializers.ChoiceField(choices=("en-DE", "de-DE"))
    default_ui_language = serializers.ChoiceField(choices=("en", "de"))
    default_document_language = serializers.ChoiceField(choices=("en", "de"))
    invoice_number_prefix = serializers.CharField(max_length=30, allow_blank=True)
    invoice_number_next = serializers.IntegerField(min_value=1)
    invoice_number_padding = serializers.IntegerField(min_value=1, max_value=12)
    invoice_number_reset = serializers.ChoiceField(choices=("never", "annual"))
    features = FeatureFlagsSerializer()

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

    def to_representation(self, instance: CompanyProfile) -> dict[str, object]:
        profile_fields = (
            "legal_name",
            "address_line_1",
            "address_line_2",
            "postal_code",
            "city",
            "country_code",
            "email",
            "phone",
            "tax_number",
            "vat_identifier",
            "company_identifier",
            "bank_account_holder",
            "iban",
            "bic",
            "payment_instructions",
            "default_currency",
            "default_locale",
            "default_ui_language",
            "default_document_language",
            "invoice_number_prefix",
            "invoice_number_next",
            "invoice_number_padding",
            "invoice_number_reset",
        )
        representation: dict[str, object] = {
            field: getattr(instance, field) for field in profile_fields
        }
        representation["features"] = {
            code: bool(getattr(instance, model_field))
            for code, model_field in FEATURE_FIELDS.items()
        }
        return representation


class TaxProfileSerializer(serializers.Serializer[TaxProfile]):
    id = serializers.IntegerField(read_only=True)
    code = serializers.SlugField(max_length=80)
    version = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=120)
    tax_category = serializers.ChoiceField(choices=("S", "E"))
    rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    exemption_reason_code = serializers.CharField(max_length=50, allow_blank=True)
    exemption_wording_en = serializers.CharField(max_length=255, allow_blank=True)
    exemption_wording_de = serializers.CharField(max_length=255, allow_blank=True)
    price_entry_policy = serializers.ChoiceField(choices=("net", "gross"))
    tax_column_policy = serializers.ChoiceField(choices=("show", "hide"))
    required_seller_identifiers = serializers.MultipleChoiceField(
        choices=("tax_number", "vat_identifier"), allow_empty=False
    )
    is_default = serializers.BooleanField()
    is_current = serializers.BooleanField(read_only=True)
    translation_complete = serializers.BooleanField(read_only=True)

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

    def to_representation(self, instance: TaxProfile) -> dict[str, object]:
        return {
            "id": instance.pk,
            "code": instance.code,
            "version": instance.version,
            "name": instance.name,
            "tax_category": instance.tax_category,
            "rate": f"{instance.rate:.2f}",
            "exemption_reason_code": instance.exemption_reason_code,
            "exemption_wording_en": instance.exemption_wording_en,
            "exemption_wording_de": instance.exemption_wording_de,
            "price_entry_policy": instance.price_entry_policy,
            "tax_column_policy": instance.tax_column_policy,
            "required_seller_identifiers": instance.required_seller_identifiers,
            "is_default": instance.is_default,
            "is_current": instance.is_current,
            "translation_complete": instance.translation_complete,
        }


class ErrorItemSerializer(serializers.Serializer[dict[str, str]]):
    code = serializers.CharField()
    message = serializers.CharField()


class ErrorBodySerializer(serializers.Serializer[dict[str, object]]):
    code = serializers.CharField()
    message = serializers.CharField()
    # DRF's metaclass removes declared fields before class creation; the stubs
    # instead see the inherited runtime ``fields`` property at analysis time.
    fields = serializers.DictField(
        child=serializers.ListField(child=ErrorItemSerializer()),
    )  # type: ignore[assignment]


class ErrorEnvelopeSerializer(serializers.Serializer[dict[str, object]]):
    error = ErrorBodySerializer()

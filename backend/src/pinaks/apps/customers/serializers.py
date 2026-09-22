from rest_framework import serializers

from pinaks.apps.customers.models import BillingRecipient, Customer, CustomerAddress


class StrictSerializer[SerializerInstance](serializers.Serializer[SerializerInstance]):
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


class CustomerAddressSerializer(StrictSerializer[CustomerAddress]):
    id = serializers.IntegerField(read_only=True)
    label = serializers.CharField(max_length=80)  # type: ignore[assignment]
    address_line_1 = serializers.CharField(max_length=255, allow_blank=True)
    address_line_2 = serializers.CharField(max_length=255, allow_blank=True)
    postal_code = serializers.CharField(max_length=20, allow_blank=True)
    city = serializers.CharField(max_length=100, allow_blank=True)
    country_code = serializers.RegexField(r"^[A-Z]{2}$", max_length=2)
    is_primary = serializers.BooleanField()

    def to_representation(self, instance: CustomerAddress) -> dict[str, object]:
        return {
            "id": instance.pk,
            "label": instance.label,
            "address_line_1": instance.address_line_1,
            "address_line_2": instance.address_line_2,
            "postal_code": instance.postal_code,
            "city": instance.city,
            "country_code": instance.country_code,
            "is_primary": instance.is_primary,
        }


class CustomerSerializer(StrictSerializer[Customer]):
    id = serializers.IntegerField(read_only=True)
    customer_number = serializers.CharField(max_length=50)
    party_type = serializers.ChoiceField(choices=("person", "organization"))
    given_name = serializers.CharField(max_length=120, allow_blank=True)
    family_name = serializers.CharField(max_length=120, allow_blank=True)
    organization_name = serializers.CharField(max_length=255, allow_blank=True)
    display_name = serializers.CharField(read_only=True)
    email = serializers.EmailField(allow_blank=True)
    phone = serializers.CharField(max_length=50, allow_blank=True)
    preferred_language = serializers.ChoiceField(choices=("en", "de"))
    is_archived = serializers.BooleanField(read_only=True)
    addresses = CustomerAddressSerializer(many=True, allow_empty=False)

    def to_representation(self, instance: Customer) -> dict[str, object]:
        return {
            "id": instance.pk,
            "customer_number": instance.customer_number,
            "party_type": instance.party_type,
            "given_name": instance.given_name,
            "family_name": instance.family_name,
            "organization_name": instance.organization_name,
            "display_name": instance.display_name,
            "email": instance.email,
            "phone": instance.phone,
            "preferred_language": instance.preferred_language,
            "is_archived": instance.is_archived,
            "addresses": CustomerAddressSerializer(instance.addresses.all(), many=True).data,  # type: ignore[arg-type]
        }


class BillingRecipientSerializer(StrictSerializer[BillingRecipient]):
    id = serializers.IntegerField(read_only=True)
    customer_id = serializers.IntegerField(read_only=True)
    party_type = serializers.ChoiceField(choices=("person", "organization"))
    given_name = serializers.CharField(max_length=120, allow_blank=True)
    family_name = serializers.CharField(max_length=120, allow_blank=True)
    organization_name = serializers.CharField(max_length=255, allow_blank=True)
    display_name = serializers.CharField(read_only=True)
    email = serializers.EmailField(allow_blank=True)
    phone = serializers.CharField(max_length=50, allow_blank=True)
    address_line_1 = serializers.CharField(max_length=255, allow_blank=True)
    address_line_2 = serializers.CharField(max_length=255, allow_blank=True)
    postal_code = serializers.CharField(max_length=20, allow_blank=True)
    city = serializers.CharField(max_length=100, allow_blank=True)
    country_code = serializers.RegexField(r"^[A-Z]{2}$", max_length=2)

    def to_representation(self, instance: BillingRecipient) -> dict[str, object]:
        return {
            "id": instance.pk,
            "customer_id": instance.customer_id,
            "party_type": instance.party_type,
            "given_name": instance.given_name,
            "family_name": instance.family_name,
            "organization_name": instance.organization_name,
            "display_name": instance.display_name,
            "email": instance.email,
            "phone": instance.phone,
            "address_line_1": instance.address_line_1,
            "address_line_2": instance.address_line_2,
            "postal_code": instance.postal_code,
            "city": instance.city,
            "country_code": instance.country_code,
        }

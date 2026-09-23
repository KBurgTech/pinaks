from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from pinaks.apps.billing.models import Invoice, InvoiceLine
from pinaks.apps.customers.serializers import StrictSerializer


class DraftCreateSerializer(StrictSerializer[Invoice]):
    customer_id = serializers.IntegerField(min_value=1)
    document_language = serializers.ChoiceField(choices=("en", "de"), required=False)
    issue_date = serializers.DateField(required=False)
    due_date = serializers.DateField(required=False, allow_null=True)


class InvoiceLineSerializer(serializers.Serializer[object]):
    id = serializers.IntegerField(read_only=True)
    position = serializers.IntegerField(read_only=True)
    service_date = serializers.DateField(read_only=True, allow_null=True)
    service_period_end = serializers.DateField(read_only=True, allow_null=True)
    item_code = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    unit = serializers.CharField(read_only=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    discount_percent = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    tax_category = serializers.CharField(read_only=True)
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    price_entry_policy = serializers.CharField(read_only=True)
    exemption_reason_code = serializers.CharField(read_only=True)
    exemption_wording = serializers.CharField(read_only=True)
    net_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    tax_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    gross_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)


class InvoiceSerializer(serializers.Serializer[Invoice]):
    id = serializers.IntegerField(read_only=True)
    customer_id = serializers.IntegerField(read_only=True)
    invoice_type = serializers.CharField(read_only=True)
    lifecycle_status = serializers.CharField(read_only=True)
    payment_status = serializers.CharField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    invoice_number = serializers.CharField(read_only=True, allow_null=True)
    currency = serializers.CharField(read_only=True)
    document_language = serializers.CharField(read_only=True)
    issue_date = serializers.DateField(read_only=True)
    due_date = serializers.DateField(read_only=True, allow_null=True)
    recipient = serializers.DictField(read_only=True)
    lines = serializers.SerializerMethodField()
    subtotal = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    tax_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    grand_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    version = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    modified_at = serializers.DateTimeField(read_only=True)

    @extend_schema_field(InvoiceLineSerializer(many=True))
    def get_lines(self, obj: Invoice) -> list[dict[str, object]]:
        return list(
            InvoiceLineSerializer(
                InvoiceLine.objects.filter(invoice=obj).order_by("position", "pk"), many=True
            ).data
        )


class RecipientInputSerializer(StrictSerializer[dict[str, object]]):
    source = serializers.ChoiceField(choices=("customer", "saved", "known_customer", "manual"))  # type: ignore[assignment]
    recipient_id = serializers.IntegerField(min_value=1, required=False)
    customer_id = serializers.IntegerField(min_value=1, required=False)
    values = serializers.DictField(required=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        required = {"saved": "recipient_id", "known_customer": "customer_id", "manual": "values"}
        field = required.get(str(attrs["source"]))
        if field and field not in attrs:
            raise serializers.ValidationError({field: "This field is required for the source."})
        if set(attrs) - {"source", field}:
            raise serializers.ValidationError("Fields do not match the recipient source.")
        return attrs


class LineOperationSerializer(StrictSerializer[dict[str, object]]):
    action = serializers.ChoiceField(choices=("add", "update", "remove"))
    line_id = serializers.IntegerField(min_value=1, required=False)
    catalog_item_id = serializers.IntegerField(min_value=1, required=False)
    position = serializers.IntegerField(min_value=1, required=False)
    item_code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    description = serializers.CharField(max_length=255, required=False)
    unit = serializers.ChoiceField(choices=("C62", "HUR", "DAY"), required=False)
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=4, required=False, min_value=0
    )
    unit_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, min_value=0
    )
    discount_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, min_value=0, max_value=100
    )
    tax_category = serializers.ChoiceField(choices=("S", "E"), required=False)
    tax_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, min_value=0, max_value=100
    )
    price_entry_policy = serializers.ChoiceField(choices=("net", "gross"), required=False)
    exemption_reason_code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    exemption_wording = serializers.CharField(max_length=255, required=False, allow_blank=True)
    service_date = serializers.DateField(required=False, allow_null=True)
    service_period_end = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        action = attrs["action"]
        if action in ("update", "remove") and "line_id" not in attrs:
            raise serializers.ValidationError({"line_id": "A line ID is required."})
        if action == "add" and "line_id" in attrs:
            raise serializers.ValidationError({"line_id": "A new line has no ID."})
        if action == "remove" and set(attrs) != {"action", "line_id"}:
            raise serializers.ValidationError("Remove accepts only a line ID.")
        if action == "update" and "catalog_item_id" in attrs:
            raise serializers.ValidationError(
                {"catalog_item_id": "Catalog selection creates a new line."}
            )
        if (
            action == "add"
            and "catalog_item_id" in attrs
            and set(attrs)
            & {
                "description",
                "unit",
                "unit_price",
                "tax_category",
                "tax_rate",
                "price_entry_policy",
                "exemption_reason_code",
                "exemption_wording",
                "item_code",
            }
        ):
            raise serializers.ValidationError("Catalog values cannot be overridden on selection.")
        return attrs


class DraftUpdateSerializer(StrictSerializer[dict[str, object]]):
    expected_version = serializers.IntegerField(min_value=1)
    document_language = serializers.ChoiceField(choices=("en", "de"), required=False)
    issue_date = serializers.DateField(required=False)
    due_date = serializers.DateField(required=False, allow_null=True)
    recipient = RecipientInputSerializer(required=False)
    line_operations = LineOperationSerializer(many=True, required=False, allow_empty=False)

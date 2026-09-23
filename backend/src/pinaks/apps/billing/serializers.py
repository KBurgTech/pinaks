from rest_framework import serializers

from pinaks.apps.billing.models import Invoice
from pinaks.apps.customers.serializers import StrictSerializer


class DraftCreateSerializer(StrictSerializer[Invoice]):
    customer_id = serializers.IntegerField(min_value=1)
    document_language = serializers.ChoiceField(choices=("en", "de"), required=False)
    issue_date = serializers.DateField(required=False)
    due_date = serializers.DateField(required=False, allow_null=True)


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
    subtotal = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    tax_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    grand_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    version = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    modified_at = serializers.DateTimeField(read_only=True)

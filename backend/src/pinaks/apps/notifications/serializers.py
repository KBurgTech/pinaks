from rest_framework import serializers

from pinaks.apps.notifications.models import EmailTemplate, EmailTemplateVersion, OutgoingEmail


class EmailVersionSerializer(serializers.ModelSerializer[EmailTemplateVersion]):
    class Meta:
        model = EmailTemplateVersion
        fields = (
            "id",
            "language",
            "version",
            "status",
            "subject",
            "body",
            "created_at",
            "published_at",
        )
        read_only_fields = ("id", "version", "status", "created_at", "published_at")


class EmailTemplateSerializer(serializers.ModelSerializer[EmailTemplate]):
    versions = EmailVersionSerializer(many=True, read_only=True)

    class Meta:
        model = EmailTemplate
        fields = ("id", "code", "name", "versions")
        read_only_fields = ("id",)


class EmailSendSerializer(serializers.Serializer):
    template_id = serializers.IntegerField(min_value=1)
    language = serializers.ChoiceField(choices=("en", "de"))
    recipients = serializers.ListField(child=serializers.EmailField(), min_length=1, max_length=20)
    idempotency_key = serializers.CharField(max_length=100)
    scheduled_at = serializers.DateTimeField(required=False)


class OutgoingEmailSerializer(serializers.ModelSerializer[OutgoingEmail]):
    """Command receipt intentionally omits correspondence content and internal keys."""

    class Meta:
        model = OutgoingEmail
        fields = ("id", "invoice_id", "language", "delivery_state", "scheduled_at", "created_at")
        read_only_fields = fields


class SendTemplateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class EmailDefaultsSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=("en", "de"))
    recipients = serializers.ListField(child=serializers.EmailField())
    templates = SendTemplateSerializer(many=True)

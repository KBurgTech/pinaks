from datetime import datetime

from rest_framework import serializers

from pinaks.apps.notifications.models import (
    DeliveryAttempt,
    EmailTemplate,
    EmailTemplateVersion,
    OutgoingEmail,
)
from pinaks.apps.workers.services import next_attempt_at


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
        fields: tuple[str, ...] = (
            "id",
            "invoice_id",
            "language",
            "delivery_state",
            "scheduled_at",
            "created_at",
        )
        read_only_fields: tuple[str, ...] = fields


class SendTemplateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class EmailDefaultsSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=("en", "de"))
    recipients = serializers.ListField(child=serializers.EmailField())
    templates = SendTemplateSerializer(many=True)


class DeliveryAttemptSerializer(serializers.ModelSerializer[DeliveryAttempt]):
    class Meta:
        model = DeliveryAttempt
        fields = ("id", "started_at", "finished_at", "outcome", "failure_code", "response_code")
        read_only_fields: tuple[str, ...] = fields


class EmailDeliverySerializer(OutgoingEmailSerializer):
    attempts = DeliveryAttemptSerializer(many=True, read_only=True)
    next_attempt_at = serializers.SerializerMethodField()

    def get_next_attempt_at(self, outgoing: OutgoingEmail) -> datetime | None:
        return next_attempt_at(job_type="notifications.deliver", identity=str(outgoing.pk))

    class Meta(OutgoingEmailSerializer.Meta):
        fields = (*OutgoingEmailSerializer.Meta.fields, "attempts", "next_attempt_at")
        read_only_fields: tuple[str, ...] = fields

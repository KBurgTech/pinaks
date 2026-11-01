"""Versioned plain-text templates and durable, write-once email content."""

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID, uuid4

from django.db import models
from django.db.models import Q

from pinaks.apps.accounts.models import User

if TYPE_CHECKING:
    from django.db.models.fields.related_descriptors import RelatedManager

    from pinaks.apps.billing.models import Invoice
    from pinaks.apps.documents.models import IssuedArtifact


class EmailTemplate(models.Model):
    code: models.SlugField[str, str] = models.SlugField(max_length=80, unique=True)
    name: models.CharField[str, str] = models.CharField(max_length=120)

    class Meta:
        ordering = ("pk",)

    def __str__(self) -> str:
        return self.name


class EmailTemplateVersion(models.Model):
    template: models.ForeignKey[EmailTemplate, EmailTemplate] = models.ForeignKey(
        EmailTemplate, on_delete=models.PROTECT, related_name="versions"
    )
    language: models.CharField[str, str] = models.CharField(
        max_length=2, choices=(("en", "English"), ("de", "German"))
    )
    version: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    subject: models.CharField[str, str] = models.CharField(max_length=255)
    body: models.TextField[str, str] = models.TextField()
    status: models.CharField[str, str] = models.CharField(
        max_length=10, default="draft", choices=(("draft", "Draft"), ("published", "Published"))
    )
    created_by: models.ForeignKey[User, User] = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(auto_now_add=True)
    published_at: models.DateTimeField[datetime | None, datetime | None] = models.DateTimeField(
        null=True, blank=True
    )

    class Meta:
        ordering = ("pk",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("template", "language", "version"), name="email_template_version_unique"
            ),
            models.CheckConstraint(
                condition=Q(language__in=("en", "de")), name="email_template_language"
            ),
            models.CheckConstraint(
                condition=Q(status__in=("draft", "published")), name="email_template_status"
            ),
            models.CheckConstraint(
                condition=Q(version__gt=0), name="email_template_version_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.template.pk} {self.language} v{self.version}"


class OutgoingEmail(models.Model):
    invoice_id: int
    if TYPE_CHECKING:
        attempts: RelatedManager[DeliveryAttempt]

    id: models.UUIDField[UUID, UUID] = models.UUIDField(
        primary_key=True, default=uuid4, editable=False
    )
    invoice: models.ForeignKey[Invoice, Invoice] = models.ForeignKey(
        "billing.Invoice", on_delete=models.PROTECT
    )
    attachment: models.ForeignKey[IssuedArtifact, IssuedArtifact] = models.ForeignKey(
        "documents.IssuedArtifact", on_delete=models.PROTECT
    )
    attachment_sha256: models.CharField[str, str] = models.CharField(max_length=64)
    template_version: models.ForeignKey[EmailTemplateVersion, EmailTemplateVersion] = (
        models.ForeignKey(EmailTemplateVersion, on_delete=models.PROTECT)
    )
    recipients: models.JSONField[list[str], list[str]] = models.JSONField()
    subject: models.CharField[str, str] = models.CharField(max_length=255)
    body: models.TextField[str, str] = models.TextField()
    language: models.CharField[str, str] = models.CharField(
        max_length=2, choices=(("en", "English"), ("de", "German"))
    )
    sender_key: models.SlugField[str, str] = models.SlugField(max_length=80)
    idempotency_key: models.CharField[str, str] = models.CharField(max_length=100)
    request_sha256: models.CharField[str, str] = models.CharField(max_length=64)
    scheduled_at: models.DateTimeField[datetime, datetime] = models.DateTimeField()
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(auto_now_add=True)
    created_by: models.ForeignKey[User, User] = models.ForeignKey(User, on_delete=models.PROTECT)
    delivery_state: models.CharField[str, str] = models.CharField(
        max_length=12,
        default="queued",
        choices=(
            ("queued", "Queued"),
            ("sending", "Sending"),
            ("sent", "Sent"),
            ("failed", "Failed"),
        ),
    )

    class Meta:
        ordering = ("created_at", "pk")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("invoice", "idempotency_key"), name="email_command_unique"
            ),
            models.CheckConstraint(
                condition=Q(language__in=("en", "de")), name="outgoing_email_language"
            ),
            models.CheckConstraint(
                condition=Q(delivery_state__in=("queued", "sending", "sent", "failed")),
                name="outgoing_email_state",
            ),
        ]

    def __str__(self) -> str:
        return str(self.pk)


class DeliveryAttempt(models.Model):
    email_id: UUID

    email: models.ForeignKey[OutgoingEmail, OutgoingEmail] = models.ForeignKey(
        OutgoingEmail, on_delete=models.PROTECT, related_name="attempts"
    )
    started_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(auto_now_add=True)
    finished_at: models.DateTimeField[datetime | None, datetime | None] = models.DateTimeField(
        null=True
    )
    outcome: models.CharField[str, str] = models.CharField(max_length=12, default="sending")
    failure_code: models.CharField[str, str] = models.CharField(max_length=32, blank=True)
    response_code: models.PositiveSmallIntegerField[int | None, int | None] = (
        models.PositiveSmallIntegerField(null=True)
    )

    class Meta:
        ordering = ("pk",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(outcome__in=("sending", "sent", "failed", "unknown")),
                name="delivery_attempt_outcome",
            ),
            models.CheckConstraint(
                condition=Q(outcome="sending", finished_at__isnull=True)
                | Q(outcome__in=("sent", "failed", "unknown"), finished_at__isnull=False),
                name="delivery_attempt_finished",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.email_id}: {self.pk}"

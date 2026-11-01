"""Public notification boundary. This module never opens a delivery connection."""

import json
import re
from datetime import datetime
from hashlib import sha256

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.services import record_event
from pinaks.apps.notifications.models import EmailTemplate, EmailTemplateVersion, OutgoingEmail


class EmailConflictError(ValueError):
    pass


def authorize(actor: User, *, admin: bool = False) -> None:
    roles = (UserRole.ADMIN,) if admin else (UserRole.ADMIN, UserRole.COMPANY_MEMBER)
    if not actor.is_active or actor.role not in roles:
        raise PermissionDenied


def _validate_content(subject: str, body: str) -> None:
    if not subject.strip() or not body.strip() or "\r" in subject or "\n" in subject:
        raise ValidationError({"subject": "A single-line subject and a body are required."})
    for value in (subject, body):
        remaining = re.sub(r"{{\s*invoice_number\s*}}", "", value)
        if "{{" in remaining or "}}" in remaining or "{%" in remaining or "{#" in remaining:
            raise ValidationError({"body": "Only the invoice_number placeholder is supported."})


@transaction.atomic
def create_template(*, code: str, name: str, actor: User, correlation_id: str) -> EmailTemplate:
    authorize(actor, admin=True)
    template = EmailTemplate(code=code, name=name)
    template.full_clean()
    template.save()
    record_event(
        actor=actor,
        action_code="notifications.template_created",
        target_type="notifications.template",
        target_identifier=str(template.pk),
        correlation_id=correlation_id,
    )
    return template


@transaction.atomic
def create_version(
    *, template_id: int, language: str, subject: str, body: str, actor: User, correlation_id: str
) -> EmailTemplateVersion:
    authorize(actor, admin=True)
    template = EmailTemplate.objects.select_for_update().get(pk=template_id)
    _validate_content(subject, body)
    last = (
        EmailTemplateVersion.objects.filter(template=template, language=language)
        .order_by("-version")
        .first()
    )
    version = EmailTemplateVersion(
        template=template,
        language=language,
        version=last.version + 1 if last else 1,
        subject=subject,
        body=body,
        created_by=actor,
    )
    version.full_clean()
    version.save()
    record_event(
        actor=actor,
        action_code="notifications.template_version_created",
        target_type="notifications.template_version",
        target_identifier=str(version.pk),
        correlation_id=correlation_id,
        metadata={"language": language, "version": version.version},
    )
    return version


@transaction.atomic
def publish_template(*, template_id: int, actor: User, correlation_id: str) -> EmailTemplate:
    authorize(actor, admin=True)
    template = EmailTemplate.objects.select_for_update().get(pk=template_id)
    selected = [
        EmailTemplateVersion.objects.filter(template=template, language=language)
        .order_by("-version")
        .first()
        for language in ("en", "de")
    ]
    if any(version is None for version in selected):
        raise EmailConflictError("Complete English and German versions are required.")
    drafts = [version for version in selected if version and version.status == "draft"]
    if not drafts:
        raise EmailConflictError("No new versions to publish.")
    for version in drafts:
        _validate_content(version.subject, version.body)
        version.status = "published"
        version.published_at = timezone.now()
        version.save(update_fields=("status", "published_at"))
    record_event(
        actor=actor,
        action_code="notifications.template_published",
        target_type="notifications.template",
        target_identifier=str(template.pk),
        correlation_id=correlation_id,
    )
    return template


def published_templates() -> list[EmailTemplate]:
    return [
        template
        for template in EmailTemplate.objects.prefetch_related("versions")
        if all(
            any(
                v.language == language and v.status == "published"
                for v in EmailTemplateVersion.objects.filter(template=template)
            )
            for language in ("en", "de")
        )
    ]


def request_fingerprint(
    *, template_id: int, language: str, recipients: list[str], scheduled_at: datetime | None
) -> str:
    if language not in ("en", "de"):
        raise ValidationError({"language": "Unsupported language."})
    if not 1 <= len(recipients) <= 20 or len(set(recipients)) != len(recipients):
        raise ValidationError({"recipients": "Provide between one and twenty distinct recipients."})
    for recipient in recipients:
        if "\n" in recipient or "\r" in recipient:
            raise ValidationError({"recipients": "Invalid email address."})
        validate_email(recipient)
    if scheduled_at is not None and timezone.is_naive(scheduled_at):
        raise ValidationError({"scheduled_at": "An aware timestamp is required."})
    return sha256(
        json.dumps(
            {
                "template": template_id,
                "language": language,
                "recipients": recipients,
                "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def existing_email(
    *, invoice_id: int, idempotency_key: str, fingerprint: str
) -> OutgoingEmail | None:
    if not idempotency_key.strip() or len(idempotency_key) > 100:
        raise ValidationError(
            {"idempotency_key": "A command identity up to 100 characters is required."}
        )
    existing = OutgoingEmail.objects.filter(
        invoice_id=invoice_id, idempotency_key=idempotency_key
    ).first()
    if existing is not None and existing.request_sha256 != fingerprint:
        raise EmailConflictError("The command identity was already used with different inputs.")
    return existing


@transaction.atomic
def queue_invoice_email(
    *,
    invoice_id: int,
    invoice_number: str,
    template_id: int,
    language: str,
    recipients: list[str],
    idempotency_key: str,
    attachment_id: int,
    attachment_sha256: str,
    scheduled_at: datetime | None,
    actor: User,
    correlation_id: str,
) -> OutgoingEmail:
    """Called by billing with a locked invoice and verified document descriptor."""
    authorize(actor)
    fingerprint = request_fingerprint(
        template_id=template_id, language=language, recipients=recipients, scheduled_at=scheduled_at
    )
    existing = existing_email(
        invoice_id=invoice_id, idempotency_key=idempotency_key, fingerprint=fingerprint
    )
    if existing:
        return existing
    template = EmailTemplate.objects.select_for_update().get(pk=template_id)
    if not all(
        EmailTemplateVersion.objects.filter(
            template=template, language=required, status="published"
        ).exists()
        for required in ("en", "de")
    ):
        raise EmailConflictError("A bilingual published template is required.")
    version = (
        EmailTemplateVersion.objects.filter(
            template=template, language=language, status="published"
        )
        .order_by("-version")
        .first()
    )
    assert version is not None

    def render(value: str) -> str:
        return re.sub(r"{{\s*invoice_number\s*}}", lambda _: invoice_number, value)

    outgoing = OutgoingEmail(
        invoice_id=invoice_id,
        attachment_id=attachment_id,
        attachment_sha256=attachment_sha256,
        template_version=version,
        recipients=recipients,
        subject=render(version.subject),
        body=render(version.body),
        language=language,
        sender_key=settings.EMAIL_SENDER_KEY,
        idempotency_key=idempotency_key,
        request_sha256=fingerprint,
        scheduled_at=scheduled_at or timezone.now(),
        created_by=actor,
    )
    if "\r" in outgoing.subject or "\n" in outgoing.subject:
        raise ValidationError({"subject": "The rendered subject must be a single line."})
    outgoing.full_clean()
    outgoing.save(force_insert=True)
    record_event(
        actor=actor,
        action_code="notifications.email_queued",
        target_type="notifications.outgoing_email",
        target_identifier=str(outgoing.pk),
        correlation_id=correlation_id,
        metadata={
            "invoice_id": invoice_id,
            "language": language,
            "template_version_id": version.pk,
        },
    )
    return outgoing

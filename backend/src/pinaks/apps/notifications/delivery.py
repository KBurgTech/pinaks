"""Durable handoff markers prevent automatic resend after an ambiguous SMTP handoff."""

from hashlib import sha256

from django.core.exceptions import ImproperlyConfigured
from django.db import connection, transaction
from django.utils import timezone

from pinaks.apps.audit.services import record_event
from pinaks.apps.documents.access import read_artifact
from pinaks.apps.documents.issuance import ArtifactIntegrityError
from pinaks.apps.notifications.models import DeliveryAttempt, OutgoingEmail
from pinaks.apps.notifications.senders import DeliveryResult, Message, get_sender
from pinaks.apps.workers.models import WorkItem
from pinaks.apps.workers.services import owns_claim


class RetryDelivery(Exception):
    pass


def handle_delivery(item: WorkItem) -> None:
    # Session advisory lock survives the marker commit and serializes lease overlaps.
    # A process crash releases the lock but leaves the durable 'sending' marker.
    key = int.from_bytes(sha256(item.identity.encode()).digest()[:8], signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
        locked = cursor.fetchone()
    if not locked or not locked[0]:
        raise RetryDelivery
    try:
        if not owns_claim(item):
            return
        with transaction.atomic():
            outgoing = (
                OutgoingEmail.objects.select_for_update()
                .select_related("attachment")
                .get(pk=item.identity)
            )
            if outgoing.delivery_state in ("sent", "failed"):
                return
            if outgoing.delivery_state == "sending":
                attempt = outgoing.attempts.get(outcome="sending")
                _complete(
                    outgoing, attempt, DeliveryResult("unknown", "delivery_unknown"), terminal=True
                )
                return
            attempt = DeliveryAttempt.objects.create(email=outgoing)
            outgoing.delivery_state = "sending"
            outgoing.save(update_fields=("delivery_state",))
        # The marker is committed before touching the external system.
        try:
            data = read_artifact(outgoing.attachment)
            if sha256(data).hexdigest() != outgoing.attachment_sha256:
                raise ArtifactIntegrityError
            result = get_sender(outgoing.sender_key).send(
                Message(
                    identity=str(outgoing.pk),
                    recipients=tuple(outgoing.recipients),
                    subject=outgoing.subject,
                    body=outgoing.body,
                    language=outgoing.language,
                    created_at=outgoing.created_at,
                    attachment=data,
                )
            )
        except ArtifactIntegrityError:
            result = DeliveryResult("failed", "artifact_integrity_failed")
        except ImproperlyConfigured:
            result = DeliveryResult("failed", "smtp_configuration")
        terminal = not result.retryable or item.attempt_count >= item.max_attempts
        with transaction.atomic():
            _complete(outgoing, attempt, result, terminal=terminal)
        if not terminal:
            raise RetryDelivery
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [key])


def _complete(
    outgoing: OutgoingEmail, attempt: DeliveryAttempt, result: DeliveryResult, *, terminal: bool
) -> None:
    attempt.outcome = result.outcome
    attempt.failure_code = result.failure_code
    attempt.response_code = result.response_code
    attempt.finished_at = timezone.now()
    attempt.save(update_fields=("outcome", "failure_code", "response_code", "finished_at"))
    outgoing.delivery_state = (
        "sent" if result.outcome == "sent" else "failed" if terminal else "queued"
    )
    outgoing.save(update_fields=("delivery_state",))
    record_event(
        action_code="notifications.delivery_completed",
        target_type="notifications.outgoing_email",
        target_identifier=str(outgoing.pk),
        metadata={
            "attempt_id": attempt.pk,
            "outcome": result.outcome,
            "failure_code": result.failure_code,
        },
    )


def reconcile_deliveries() -> None:
    """Resolve exhausted leases without ever repeating an uncertain handoff."""
    from pinaks.apps.workers.services import terminal_work

    for item in terminal_work(job_type="notifications.deliver"):
        if not OutgoingEmail.objects.filter(
            pk=item.identity, delivery_state__in=("queued", "sending")
        ).exists():
            continue
        key = int.from_bytes(sha256(item.identity.encode()).digest()[:8], signed=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
            locked = cursor.fetchone()
        if not locked or not locked[0]:
            continue
        try:
            with transaction.atomic():
                outgoing = OutgoingEmail.objects.select_for_update().get(pk=item.identity)
                if outgoing.delivery_state not in ("queued", "sending"):
                    continue
                attempt = outgoing.attempts.filter(outcome="sending").first()
                if attempt:
                    result = DeliveryResult("unknown", "delivery_unknown")
                else:
                    attempt = DeliveryAttempt.objects.create(email=outgoing)
                    result = DeliveryResult("failed", "worker_exhausted")
                _complete(outgoing, attempt, result, terminal=True)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [key])

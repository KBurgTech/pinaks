import socketserver
from collections.abc import Iterator
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path
from threading import Thread

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User
from pinaks.apps.billing.models import Invoice
from pinaks.apps.notifications.models import OutgoingEmail
from pinaks.apps.workers.models import WorkItem
from pinaks.apps.workers.registry import HANDLERS
from pinaks.apps.workers.services import run_one
from test_artifact_access import stored_invoice  # noqa: F401
from test_email_outbox import published
from test_issuance import ready_invoice as issuance_ready  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


class SMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), SMTPHandler)
        self.messages: list[bytes] = []
        self.mode = "success"


class SMTPHandler(socketserver.StreamRequestHandler):
    server: SMTPServer  # type: ignore[assignment]

    def handle(self) -> None:
        def reply(value: bytes) -> None:
            self.wfile.write(value + b"\r\n")
            self.wfile.flush()

        if self.server.mode == "disconnect":
            return
        if self.server.mode == "timeout":
            try:
                self.connection.settimeout(1)
                self.rfile.read(1)
            except TimeoutError:
                pass
            return
        reply(b"220 localhost")
        while line := self.rfile.readline():
            command = line.upper()
            if command.startswith((b"EHLO", b"HELO")):
                reply(b"250 localhost")
            elif command.startswith(b"RCPT") and self.server.mode in ("transient", "permanent"):
                reply(
                    b"451 private@example.test secret"
                    if self.server.mode == "transient"
                    else b"550 private@example.test secret"
                )
            elif command.startswith(b"DATA"):
                reply(b"354 Go ahead")
                data = b""
                while (part := self.rfile.readline()) != b".\r\n":
                    if not part:
                        return
                    data += part[1:] if part.startswith(b"..") else part
                self.server.messages.append(data)
                if self.server.mode == "lost_ack":
                    return
                reply(b"250 private acceptance text")
            elif command.startswith(b"QUIT"):
                reply(b"221 Bye")
                return
            else:
                reply(b"250 OK")


@pytest.fixture
def smtp() -> Iterator[SMTPServer]:
    with SMTPServer() as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with override_settings(
            SMTP_HOST="127.0.0.1",
            SMTP_PORT=server.server_address[1],
            SMTP_USE_TLS=False,
            SMTP_USE_SSL=False,
            SMTP_TIMEOUT=0.1,
            SMTP_USERNAME="",
            SMTP_PASSWORD="",
            SMTP_FROM_EMAIL="sender@example.test",
        ):
            yield server
        server.shutdown()
        thread.join()


@pytest.fixture
def queued(stored_invoice: tuple[Invoice, User]) -> OutgoingEmail:  # noqa: F811
    invoice, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    template_id = published(client)
    response = client.post(
        f"/api/v1/invoices/{invoice.pk}/send/",
        {
            "template_id": template_id,
            "language": "de",
            "recipients": ["recipient@example.test"],
            "idempotency_key": "delivery",
        },
        format="json",
    )
    assert response.status_code == 201
    # Ignore the already completed fixture's document generation job.
    WorkItem.objects.filter(job_type="documents.generate").delete()
    return OutgoingEmail.objects.get()


def deliver() -> bool:
    return run_one(handlers=HANDLERS)


def test_queue_enqueues_one_scheduled_delivery(queued: OutgoingEmail) -> None:
    item = WorkItem.objects.get(job_type="notifications.deliver")
    assert item.identity == str(queued.pk)
    assert item.scheduled_at == queued.scheduled_at


def test_smtp_delivers_original_bytes_and_stable_identity(
    queued: OutgoingEmail, smtp: SMTPServer
) -> None:
    assert deliver()
    queued.refresh_from_db()
    assert queued.delivery_state == "sent"
    assert len(smtp.messages) == 1
    message = BytesParser(policy=policy.default).parsebytes(smtp.messages[0])
    assert message["Message-ID"] == f"<{queued.pk}@pinaks.invalid>"
    assert message["Content-Language"] == "de"
    assert message["Subject"] == queued.subject
    body = message.get_body(preferencelist=("plain",))
    assert body is not None
    assert body.get_content().strip() == queued.body
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_payload(decode=True) == b"original pdf"
    assert attachments[0]["Content-Type"] == "application/pdf"
    from pinaks.apps.notifications.delivery import handle_delivery

    handle_delivery(WorkItem.objects.get(job_type="notifications.deliver"))
    assert len(smtp.messages) == 1
    attempt = queued.attempts.get()
    assert attempt.outcome == "sent"
    assert attempt.finished_at is not None
    assert attempt.finished_at >= attempt.started_at
    assert attempt.response_code == 250


@pytest.mark.parametrize(
    "mode,code",
    [
        ("transient", "smtp_transient"),
        ("permanent", "smtp_permanent"),
        ("timeout", "smtp_unavailable"),
        ("disconnect", "smtp_unavailable"),
        ("lost_ack", "delivery_unknown"),
    ],
)
def test_failure_policy_and_sanitized_evidence(
    queued: OutgoingEmail, smtp: SMTPServer, mode: str, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    smtp.mode = mode
    deliver()
    queued.refresh_from_db()
    attempt = queued.attempts.get()
    assert attempt.failure_code == code
    terminal = mode in ("permanent", "lost_ack")
    assert queued.delivery_state == ("failed" if terminal else "queued")
    assert attempt.outcome == ("unknown" if mode == "lost_ack" else "failed")
    assert "secret" not in caplog.text
    assert "private@example.test" not in caplog.text
    smtp.mode = "success"
    WorkItem.objects.filter(job_type="notifications.deliver").update(
        scheduled_at=timezone.now() - timedelta(seconds=1)
    )
    deliver()
    queued.refresh_from_db()
    assert queued.delivery_state == ("failed" if terminal else "sent")
    assert len(smtp.messages) == (1 if mode == "lost_ack" or not terminal else 0)


def test_attachment_damage_prevents_smtp(
    queued: OutgoingEmail, smtp: SMTPServer, tmp_path: Path
) -> None:
    (tmp_path / ("a" * 64) / "pdf").write_bytes(b"corrupt")
    deliver()
    queued.refresh_from_db()
    assert queued.delivery_state == "failed"
    assert queued.attempts.get().failure_code == "artifact_integrity_failed"
    assert smtp.messages == []


def test_retry_exhaustion_is_terminal(queued: OutgoingEmail, smtp: SMTPServer) -> None:
    smtp.mode = "transient"
    WorkItem.objects.filter(job_type="notifications.deliver").update(max_attempts=1)
    deliver()
    queued.refresh_from_db()
    assert queued.delivery_state == "failed"
    assert queued.attempts.get().failure_code == "smtp_transient"


@pytest.mark.parametrize("role", ["admin", "company_member", "read_only"])
def test_delivery_history_is_authorized_and_sanitized(
    queued: OutgoingEmail, smtp: SMTPServer, role: str
) -> None:
    deliver()
    actor = User.objects.create_user(username=role, role=role)
    client = APIClient()
    client.force_authenticate(actor)
    response = client.get(f"/api/v1/invoices/{queued.invoice_id}/emails/")
    assert response.status_code == (403 if role == "read_only" else 200)
    if role != "read_only":
        assert response["Cache-Control"] == "no-store"
        assert response.data[0]["delivery_state"] == "sent"
        assert response.data[0]["attempts"][0]["outcome"] == "sent"
        assert response.data[0]["attempts"][0]["response_code"] == 250
        text = str(response.data)
        assert "recipient@example.test" not in text
        assert queued.body not in text
        assert "storage_key" not in text
        assert "sender_key" not in text


def test_expired_last_lease_reconciles_unknown_delivery(
    queued: OutgoingEmail, smtp: SMTPServer
) -> None:
    from django.core.management import call_command

    from pinaks.apps.notifications.models import DeliveryAttempt
    from pinaks.apps.workers.services import claim_work

    WorkItem.objects.filter(job_type="notifications.deliver").update(max_attempts=1)
    item = claim_work()
    assert item is not None
    OutgoingEmail.objects.filter(pk=queued.pk).update(delivery_state="sending")
    DeliveryAttempt.objects.create(email=queued)
    WorkItem.objects.filter(pk=item.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    call_command("run_worker", once=True)
    queued.refresh_from_db()
    assert queued.delivery_state == "failed"
    assert queued.attempts.get().outcome == "unknown"
    assert smtp.messages == []


def test_delivery_history_includes_retry_schedule(queued: OutgoingEmail, smtp: SMTPServer) -> None:
    smtp.mode = "transient"
    deliver()
    client = APIClient()
    client.force_authenticate(queued.created_by)
    response = client.get(f"/api/v1/invoices/{queued.invoice_id}/emails/")
    assert response.status_code == 200
    assert response.data[0]["next_attempt_at"] is not None
    assert response.data[0]["attempts"][0]["failure_code"] == "smtp_transient"


def test_attempt_evidence_is_database_immutable(queued: OutgoingEmail, smtp: SMTPServer) -> None:
    from django.db import DatabaseError, transaction

    from pinaks.apps.notifications.models import DeliveryAttempt

    deliver()
    with pytest.raises(DatabaseError), transaction.atomic():
        DeliveryAttempt.objects.update(failure_code="rewritten")
    with pytest.raises(DatabaseError), transaction.atomic():
        DeliveryAttempt.objects.all().delete()


def test_invalid_sender_is_a_configuration_failure(queued: OutgoingEmail, smtp: SMTPServer) -> None:
    with override_settings(SMTP_FROM_EMAIL="invalid"):
        deliver()
    queued.refresh_from_db()
    assert queued.delivery_state == "failed"
    assert queued.attempts.get().failure_code == "smtp_configuration"
    assert smtp.messages == []


def test_existing_queued_outbox_is_enqueued_by_upgrade(queued: OutgoingEmail) -> None:
    from importlib import import_module

    from django.apps import apps
    from django.db import connection

    WorkItem.objects.filter(job_type="notifications.deliver").delete()
    migration = import_module("pinaks.apps.notifications.migrations.0006_delivery_evidence")
    with connection.schema_editor() as editor:
        migration.enqueue_existing(apps, editor)
        migration.enqueue_existing(apps, editor)
    assert WorkItem.objects.get(job_type="notifications.deliver").identity == str(queued.pk)


def test_concurrent_and_delayed_delivery_sends_once(
    queued: OutgoingEmail, smtp: SMTPServer
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections, connection

    from pinaks.apps.notifications.delivery import RetryDelivery, handle_delivery
    from pinaks.apps.workers.services import claim_work

    item = claim_work()
    assert item is not None

    def send(_: int) -> None:
        close_old_connections()
        try:
            try:
                handle_delivery(item)
            except RetryDelivery:
                pass
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(send, range(2)))
    # An expired/stale claimant cannot resend the completed message.
    WorkItem.objects.filter(pk=item.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    handle_delivery(item)
    queued.refresh_from_db()
    assert queued.delivery_state == "sent"
    assert queued.attempts.count() == 1
    assert len(smtp.messages) == 1

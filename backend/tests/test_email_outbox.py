from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from django.db import DatabaseError, close_old_connections, connection, transaction
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.models import AuditEvent
from pinaks.apps.billing.models import Invoice
from pinaks.apps.documents.models import IssuedArtifact
from test_artifact_access import stored_invoice  # noqa: F401
from test_issuance import ready_invoice as issuance_ready  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def client(stored_invoice: tuple[Invoice, User]) -> APIClient:  # noqa: F811
    _, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    return client


def template(client: APIClient) -> int:
    response = client.post(
        "/api/v1/email-templates/", {"code": "invoice", "name": "Invoice"}, format="json"
    )
    assert response.status_code == 201, response.data
    return int(response.data["id"])


def version(client: APIClient, template_id: int, language: str, **changes: str) -> int:
    response = client.post(
        f"/api/v1/email-templates/{template_id}/versions/",
        {
            "language": language,
            "subject": "Invoice {{ invoice_number }}",
            "body": "Please find invoice {{ invoice_number }} attached.",
            **changes,
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    return int(response.data["id"])


def published(client: APIClient) -> int:
    pk = template(client)
    for language in ("en", "de"):
        version(client, pk, language)
    assert client.post(f"/api/v1/email-templates/{pk}/publish/").status_code == 200
    return pk


def test_publication_requires_both_languages_and_retains_versions(client: APIClient) -> None:
    pk = template(client)
    first = version(client, pk, "en")
    assert client.post(f"/api/v1/email-templates/{pk}/publish/").status_code == 409
    version(client, pk, "de")
    assert client.post(f"/api/v1/email-templates/{pk}/publish/").status_code == 200
    second = version(client, pk, "en", subject="Updated {{ invoice_number }}")
    assert second != first
    assert client.post(f"/api/v1/email-templates/{pk}/publish/").status_code == 200
    versions = client.get("/api/v1/email-templates/").data[0]["versions"]
    assert len(versions) == 3
    assert all(v["status"] == "published" for v in versions)
    assert versions[0]["subject"] == "Invoice {{ invoice_number }}"


@pytest.mark.parametrize(
    "changes",
    [
        {"subject": "bad\r\nBcc: hidden@example.test"},
        {"subject": ""},
        {"body": ""},
        {"body": "{{ customer.custom_data }}"},
        {"language": "fr"},
    ],
)
def test_template_validation(client: APIClient, changes: dict[str, str]) -> None:
    pk = template(client)
    response = client.post(
        f"/api/v1/email-templates/{pk}/versions/",
        {
            "language": "en",
            "subject": "Invoice",
            "body": "Attached",
            **changes,
        },
        format="json",
    )
    assert response.status_code == 400


def test_queue_snapshots_and_replay_survive_source_changes(
    client: APIClient,
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from pinaks.apps.notifications.models import OutgoingEmail

    invoice, _ = stored_invoice
    pk = published(client)
    invoice.customer.email = "billing@example.test"
    invoice.customer.preferred_language = "de"
    invoice.customer.save()
    url = f"/api/v1/invoices/{invoice.pk}/send/"
    defaults = client.get(url)
    assert defaults.status_code == 200
    assert defaults.data["language"] == "de"
    assert defaults.data["recipients"] == ["billing@example.test"]
    payload = {
        "template_id": pk,
        "language": "de",
        "recipients": ["payer@example.test"],
        "idempotency_key": "send-1",
    }
    response = client.post(url, payload, format="json")
    assert response.status_code == 201
    queued = OutgoingEmail.objects.get()
    assert queued.recipients == ["payer@example.test"]
    assert queued.language == "de"
    assert queued.subject == f"Invoice {invoice.invoice_number}"
    assert invoice.invoice_number is not None
    assert invoice.invoice_number in queued.body
    assert (
        queued.attachment_sha256 == IssuedArtifact.objects.get(invoice=invoice, kind="pdf").sha256
    )
    assert queued.delivery_state == "queued"
    assert queued.sender_key == "default"
    assert queued.scheduled_at is not None
    before = (queued.subject, queued.body, queued.recipients, queued.attachment_sha256)
    invoice.customer.email = "changed@example.test"
    invoice.customer.preferred_language = "en"
    invoice.customer.save()
    version(client, pk, "de", subject="New subject")
    assert client.post(f"/api/v1/email-templates/{pk}/publish/").status_code == 200
    retry = client.post(url, payload, format="json")
    assert retry.status_code == 201
    assert retry.data["id"] == response.data["id"]
    assert OutgoingEmail.objects.count() == 1
    queued.refresh_from_db()
    assert before == (queued.subject, queued.body, queued.recipients, queued.attachment_sha256)
    assert (
        client.post(
            url, {**payload, "recipients": ["other@example.test"]}, format="json"
        ).status_code
        == 409
    )
    audit = AuditEvent.objects.get(action_code="notifications.email_queued")
    assert "example.test" not in str(audit.metadata)
    assert queued.body not in str(audit.metadata)
    assert "storage_key" not in str(response.data)
    assert "body" not in response.data
    assert "sender_key" not in response.data


@pytest.mark.parametrize(
    "changes",
    [
        {"recipients": []},
        {"recipients": ["bad"]},
        {"recipients": ["a@example.test\nBcc: b@example.test"]},
        {"language": "fr"},
        {"idempotency_key": ""},
        {"scheduled_at": "not-a-date"},
    ],
)
def test_send_validation(
    client: APIClient,
    stored_invoice: tuple[Invoice, User],  # noqa: F811
    changes: dict[str, object],
) -> None:
    invoice, _ = stored_invoice
    pk = published(client)
    response = client.post(
        f"/api/v1/invoices/{invoice.pk}/send/",
        {
            "template_id": pk,
            "language": "en",
            "recipients": ["a@example.test"],
            "idempotency_key": "send",
            **changes,
        },
        format="json",
    )
    assert response.status_code == 400


def test_unpublished_and_damaged_artifacts_cannot_queue(
    client: APIClient,
    stored_invoice: tuple[Invoice, User],  # noqa: F811
    tmp_path: Path,
) -> None:
    from pinaks.apps.notifications.models import OutgoingEmail

    invoice, _ = stored_invoice
    pk = template(client)
    payload = {
        "template_id": pk,
        "language": "en",
        "recipients": ["a@example.test"],
        "idempotency_key": "send",
    }
    url = f"/api/v1/invoices/{invoice.pk}/send/"
    assert client.post(url, payload, format="json").status_code == 409
    for language in ("en", "de"):
        version(client, pk, language)
    client.post(f"/api/v1/email-templates/{pk}/publish/")
    (tmp_path / ("a" * 64) / "xml").write_bytes(b"corrupt")
    response = client.post(url, payload, format="json")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "artifact_integrity_failed"
    assert not OutgoingEmail.objects.exists()


@pytest.mark.parametrize("role", ["read_only", "company_member", "admin"])
def test_permissions(client: APIClient, stored_invoice: tuple[Invoice, User], role: str) -> None:  # noqa: F811
    invoice, _ = stored_invoice
    pk = published(client)
    actor = User.objects.create_user(username=role, role=role)
    client.force_authenticate(actor)
    assert client.post(
        "/api/v1/email-templates/", {"code": "other", "name": "Other"}, format="json"
    ).status_code == (201 if role == "admin" else 403)
    assert client.get("/api/v1/email-templates/").status_code == (200 if role == "admin" else 403)
    assert client.post(f"/api/v1/email-templates/{pk}/publish/").status_code == (
        409 if role == "admin" else 403
    )
    assert client.post(
        f"/api/v1/email-templates/{pk}/versions/",
        {"language": "en", "subject": "New", "body": "Body"},
        format="json",
    ).status_code == (201 if role == "admin" else 403)
    url = f"/api/v1/invoices/{invoice.pk}/send/"
    assert client.get(url).status_code == (403 if role == "read_only" else 200)
    assert client.post(
        url,
        {
            "template_id": pk,
            "language": "en",
            "recipients": ["a@example.test"],
            "idempotency_key": "send",
        },
        format="json",
    ).status_code == (403 if role == "read_only" else 201)
    actor.is_active = False
    actor.save()
    assert client.get(url).status_code == 403
    client.force_authenticate(None)
    assert client.post(url, {}, format="json").status_code == 403


def test_published_versions_and_snapshots_are_database_immutable(
    client: APIClient,
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from pinaks.apps.notifications.models import EmailTemplateVersion, OutgoingEmail

    invoice, _ = stored_invoice
    pk = published(client)
    client.post(
        f"/api/v1/invoices/{invoice.pk}/send/",
        {
            "template_id": pk,
            "language": "en",
            "recipients": ["a@example.test"],
            "idempotency_key": "send",
        },
        format="json",
    )
    for model, field in ((EmailTemplateVersion, "subject"), (OutgoingEmail, "body")):
        with pytest.raises(DatabaseError), transaction.atomic():
            model.objects.update(**{field: "tampered"})
        with pytest.raises(DatabaseError), transaction.atomic():
            model.objects.all().delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        OutgoingEmail.objects.update(attachment_sha256="0" * 64)


def test_simultaneous_retries_queue_one_snapshot(
    client: APIClient,
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from pinaks.apps.billing.emails import send_invoice
    from pinaks.apps.notifications.models import OutgoingEmail

    invoice, actor = stored_invoice
    pk = published(client)

    def send(_: int) -> str:
        close_old_connections()
        try:
            return str(
                send_invoice(
                    invoice_id=invoice.pk,
                    template_id=pk,
                    language="en",
                    recipients=["a@example.test"],
                    idempotency_key="concurrent",
                    actor=actor,
                    correlation_id="test",
                ).pk
            )
        finally:
            connection.close()

    assert connection.vendor == "postgresql"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, range(2)))
    assert results[0] == results[1]
    assert OutgoingEmail.objects.count() == 1


def test_outbox_rejects_mismatched_attachment_hash_at_database_boundary(
    client: APIClient,
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from pinaks.apps.notifications.models import OutgoingEmail

    invoice, _ = stored_invoice
    pk = published(client)
    response = client.post(
        f"/api/v1/invoices/{invoice.pk}/send/",
        {
            "template_id": pk,
            "language": "en",
            "recipients": ["a@example.test"],
            "idempotency_key": "original",
        },
        format="json",
    )
    assert response.status_code == 201
    outgoing = OutgoingEmail.objects.get()
    outgoing.pk = None
    outgoing.idempotency_key = "forged"
    outgoing.attachment_sha256 = "0" * 64
    with pytest.raises(DatabaseError), transaction.atomic():
        outgoing.save(force_insert=True)


def test_draft_cannot_queue_and_session_command_requires_csrf(
    client: APIClient,
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from pinaks.apps.billing.services import create_draft
    from pinaks.apps.notifications.models import OutgoingEmail

    invoice, actor = stored_invoice
    pk = published(client)
    draft = create_draft(customer=invoice.customer, actor=actor, correlation_id="test")
    payload = {
        "template_id": pk,
        "language": "en",
        "recipients": ["a@example.test"],
        "idempotency_key": "send",
    }
    assert (
        client.post(f"/api/v1/invoices/{draft.pk}/send/", payload, format="json").status_code == 409
    )
    session = APIClient(enforce_csrf_checks=True)
    session.force_login(actor)
    assert (
        session.post(f"/api/v1/invoices/{invoice.pk}/send/", payload, format="json").status_code
        == 403
    )
    assert not OutgoingEmail.objects.exists()


def test_schedule_and_direct_service_authorization(
    client: APIClient,
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from datetime import UTC, datetime

    from django.core.exceptions import PermissionDenied

    from pinaks.apps.billing.emails import send_invoice
    from pinaks.apps.notifications.models import OutgoingEmail
    from pinaks.apps.notifications.services import create_template

    invoice, _ = stored_invoice
    pk = published(client)
    response = client.post(
        f"/api/v1/invoices/{invoice.pk}/send/",
        {
            "template_id": pk,
            "language": "en",
            "recipients": ["a@example.test"],
            "idempotency_key": "scheduled",
            "scheduled_at": "2027-01-10T10:00:00Z",
        },
        format="json",
    )
    assert response.status_code == 201
    assert OutgoingEmail.objects.get().scheduled_at == datetime(2027, 1, 10, 10, tzinfo=UTC)
    reader = User.objects.create_user(username="reader", role="read_only")
    with pytest.raises(PermissionDenied):
        send_invoice(
            invoice_id=invoice.pk,
            template_id=pk,
            language="en",
            recipients=["a@example.test"],
            idempotency_key="forbidden",
            actor=reader,
            correlation_id="test",
        )
    with pytest.raises(PermissionDenied):
        create_template(code="forbidden", name="Forbidden", actor=reader, correlation_id="test")
    assert OutgoingEmail.objects.count() == 1


def test_rendered_subject_cannot_introduce_header_lines(
    client: APIClient,
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from django.core.exceptions import ValidationError

    from pinaks.apps.notifications.services import queue_invoice_email

    invoice, actor = stored_invoice
    pk = published(client)
    artifact = IssuedArtifact.objects.get(invoice=invoice, kind="pdf")
    with pytest.raises(ValidationError):
        queue_invoice_email(
            invoice_id=invoice.pk,
            invoice_number="bad\r\nBcc: hidden@example.test",
            template_id=pk,
            language="en",
            recipients=["a@example.test"],
            idempotency_key="headers",
            attachment_id=artifact.pk,
            attachment_sha256=artifact.sha256,
            scheduled_at=None,
            actor=actor,
            correlation_id="test",
        )

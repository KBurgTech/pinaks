import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.models import AuditEvent
from pinaks.apps.billing.models import Invoice, InvoiceLine
from pinaks.apps.billing.services import update_draft
from pinaks.apps.documents.models import IssuedArtifact
from test_artifact_access import stored_invoice  # noqa: F401
from test_issuance import ready_invoice as issuance_ready  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


def test_cancel_creates_one_frozen_full_credit_draft_without_changing_original(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    original, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    before = Invoice.objects.values().get(pk=original.pk)
    artifacts = list(IssuedArtifact.objects.values())
    url = f"/api/v1/invoices/{original.pk}/cancel/"
    body = {"reason": "Duplicate invoice", "idempotency_key": "cancel-1"}
    response = client.post(url, body, format="json")
    assert response.status_code == 201
    draft = Invoice.objects.get(pk=response.data["id"])
    assert draft.invoice_type == "CANCELLATION"
    assert draft.lifecycle_status == "DRAFT"
    assert draft.original_invoice_id == original.pk
    assert draft.correction_reason == body["reason"]
    assert draft.grand_total == original.grand_total
    assert draft.issue_date == timezone.localdate()
    fields = [
        field.name for field in InvoiceLine._meta.fields if field.name not in {"id", "invoice"}
    ]
    assert list(InvoiceLine.objects.filter(invoice=draft).values(*fields)) == list(
        InvoiceLine.objects.filter(invoice=original).values(*fields)
    )
    repeated = client.post(url, body, format="json")
    assert repeated.status_code == 200
    assert repeated.data == response.data
    assert client.get(f"/api/v1/invoices/{original.pk}/").data["related_invoice_ids"] == [draft.pk]
    assert response.data["original_invoice_id"] == original.pk
    assert Invoice.objects.values().get(pk=original.pk) == before
    assert list(IssuedArtifact.objects.values()) == artifacts
    assert AuditEvent.objects.filter(action_code="billing.cancellation_created").count() == 1
    assert client.post(url, {**body, "reason": "Changed"}, format="json").status_code == 409
    assert client.post(url, {**body, "idempotency_key": "other"}, format="json").status_code == 409
    with pytest.raises(ValidationError):
        update_draft(
            invoice_id=draft.pk,
            expected_version=draft.version,
            values={
                "line_operations": [
                    {"action": "remove", "line_id": InvoiceLine.objects.get(invoice=draft).pk}
                ]
            },
            actor=actor,
            correlation_id="test",
        )
    with pytest.raises(DatabaseError), transaction.atomic():
        Invoice.objects.filter(pk=draft.pk).update(correction_reason="Changed")
    with pytest.raises(DatabaseError), transaction.atomic():
        InvoiceLine.objects.filter(invoice=draft).update(unit_price="1.00")


@pytest.mark.parametrize(
    "role,active,expected",
    [
        ("admin", True, 201),
        ("company_member", True, 201),
        ("read_only", True, 403),
        ("admin", False, 403),
    ],
)
def test_cancellation_permissions(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
    role: str,
    active: bool,
    expected: int,
) -> None:
    original, _ = stored_invoice
    actor = User.objects.create_user(username="cancel-actor", role=role, is_active=active)
    client = APIClient()
    url = f"/api/v1/invoices/{original.pk}/cancel/"
    body = {"reason": "Duplicate", "idempotency_key": "cancel"}
    assert client.post(url, body, format="json").status_code == 403
    client.force_authenticate(actor)
    assert client.post(url, body, format="json").status_code == expected


def test_cancel_validates_input_and_csrf(stored_invoice: tuple[Invoice, User]) -> None:  # noqa: F811
    original, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    url = f"/api/v1/invoices/{original.pk}/cancel/"
    for body in (
        {},
        {"reason": " ", "idempotency_key": "x"},
        {"reason": "x", "idempotency_key": ""},
    ):
        assert client.post(url, body, format="json").status_code == 400
    body = {"reason": "Duplicate", "idempotency_key": "cancel"}
    session = APIClient(enforce_csrf_checks=True)
    session.force_login(actor)
    assert session.post(url, body, format="json").status_code == 403
    assert client.post("/api/v1/invoices/999999/cancel/", body, format="json").status_code == 404
    artifact = IssuedArtifact.objects.get(invoice=original, kind="pdf")
    from django.conf import settings

    (settings.ISSUED_DOCUMENT_ROOT / artifact.storage_key).write_bytes(b"broken")
    assert client.post(url, body, format="json").status_code == 409


def test_only_issued_standard_invoices_can_be_cancelled(
    issuance_ready: tuple[Invoice, User, object],  # noqa: F811
) -> None:
    original, actor, _ = issuance_ready
    client = APIClient()
    client.force_authenticate(actor)
    for state in ("DRAFT", "ISSUING"):
        if state == "ISSUING":
            Invoice.objects.filter(pk=original.pk).update(
                lifecycle_status=state, invoice_number="x", snapshot={}, issuance_key="x"
            )
        response = client.post(
            f"/api/v1/invoices/{original.pk}/cancel/",
            {"reason": "Duplicate", "idempotency_key": "cancel"},
            format="json",
        )
        assert response.status_code == 409
        assert response.data["error"]["code"] == "invalid_cancellation"


def test_cancellation_issuance_freezes_original_parties_and_tax_then_cancels_after_storage(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from pinaks.apps.billing.issuance import issue_invoice
    from pinaks.apps.configuration.models import CompanyProfile, TaxProfile
    from pinaks.apps.documents.issuance import generate_invoice

    original, actor = stored_invoice
    assert original.snapshot is not None
    original_before = Invoice.objects.values().get(pk=original.pk)
    artifacts = list(IssuedArtifact.objects.filter(invoice=original).values())
    client = APIClient()
    client.force_authenticate(actor)
    response = client.post(
        f"/api/v1/invoices/{original.pk}/cancel/",
        {"reason": "Duplicate", "idempotency_key": "cancel"},
        format="json",
    )
    assert response.status_code == 201
    draft = Invoice.objects.get(pk=response.data["id"])
    template = original.snapshot["template"]
    assert isinstance(template, dict)
    CompanyProfile.objects.update(legal_name="Changed seller")
    TaxProfile.objects.update(rate="7.00")
    original.customer.given_name = "Changed customer"
    original.customer.save()
    issued = issue_invoice(
        invoice_id=draft.pk,
        expected_version=draft.version,
        template_id=template["id"],
        idempotency_key="issue-cancel",
        actor=actor,
        correlation_id="test",
    )
    assert issued.lifecycle_status == "ISSUING"
    assert issued.snapshot is not None
    for key in ("seller", "customer", "recipient", "lines", "tax_profile", "tax_breakdowns"):
        assert issued.snapshot[key] == original.snapshot[key]
    original.refresh_from_db()
    assert original.lifecycle_status == "ISSUED"
    generate_invoice(invoice_id=issued.pk)
    original.refresh_from_db()
    issued.refresh_from_db()
    assert issued.lifecycle_status == "ISSUED"
    assert original.lifecycle_status == "CANCELLED"
    after = Invoice.objects.values().get(pk=original.pk)
    for field in ("lifecycle_status", "modified_at"):
        original_before.pop(field)
        after.pop(field)
    assert after == original_before
    assert list(IssuedArtifact.objects.filter(invoice=original).values()) == artifacts
    assert client.get(f"/api/v1/invoices/{original.pk}/documents/pdf/").content == b"original pdf"
    assert client.get(f"/api/v1/invoices/{original.pk}/documents/").data["healthy"] is True
    assert (
        client.post(f"/api/v1/invoices/{original.pk}/mark-paid/", {}, format="json").status_code
        == 409
    )
    generate_invoice(invoice_id=issued.pk)
    assert IssuedArtifact.objects.filter(invoice=issued).count() == 3
    assert AuditEvent.objects.filter(action_code="billing.invoice_cancelled").count() == 1


def test_cancellation_exposes_original_template_identity_without_snapshot_contents(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    original, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    response = client.post(
        f"/api/v1/invoices/{original.pk}/cancel/",
        {"reason": "Duplicate", "idempotency_key": "cancel"},
        format="json",
    )
    assert response.status_code == 201
    assert original.snapshot is not None
    template = original.snapshot["template"]
    assert isinstance(template, dict)
    assert response.data["cancellation_template_id"] == template["id"]
    assert "snapshot" not in response.data
    assert "correction_key" not in response.data


def test_concurrent_cancel_commands_create_one_draft(stored_invoice: tuple[Invoice, User]) -> None:  # noqa: F811
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connections

    from pinaks.apps.billing.cancellations import create_cancellation

    original, actor = stored_invoice
    barrier = Barrier(2)

    def cancel() -> tuple[int, bool]:
        try:
            thread_actor = User.objects.get(pk=actor.pk)
            barrier.wait(timeout=10)
            invoice, created = create_cancellation(
                invoice_id=original.pk,
                reason="Duplicate",
                idempotency_key="concurrent",
                actor=thread_actor,
                correlation_id="test",
            )
            return invoice.pk, created
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: cancel(), range(2)))
    assert len({result[0] for result in results}) == 1
    assert sum(result[1] for result in results) == 1
    assert Invoice.objects.filter(original_invoice=original).count() == 1


@pytest.mark.parametrize("command", ["generate", "issue"])
def test_cancelled_original_generation_retry_is_idempotent(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
    command: str,
) -> None:
    from pinaks.apps.billing.cancellations import create_cancellation
    from pinaks.apps.billing.issuance import issue_invoice
    from pinaks.apps.documents.issuance import generate_invoice

    original, actor = stored_invoice
    draft, _ = create_cancellation(
        invoice_id=original.pk,
        reason="Duplicate",
        idempotency_key="cancel",
        actor=actor,
        correlation_id="test",
    )
    assert original.snapshot is not None
    template = original.snapshot["template"]
    assert isinstance(template, dict)
    issue_invoice(
        invoice_id=draft.pk,
        expected_version=draft.version,
        template_id=template["id"],
        idempotency_key="issue",
        actor=actor,
        correlation_id="test",
    )
    generate_invoice(invoice_id=draft.pk)
    if command == "generate":
        generate_invoice(invoice_id=original.pk)
    else:
        result = issue_invoice(
            invoice_id=original.pk,
            expected_version=original.version,
            template_id=template["id"],
            idempotency_key="download",
            actor=actor,
            correlation_id="test",
        )
        assert result.lifecycle_status == "CANCELLED"
    original.refresh_from_db()
    assert original.lifecycle_status == "CANCELLED"

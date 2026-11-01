from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User
from pinaks.apps.billing.models import Invoice, InvoiceLine
from pinaks.apps.documents.models import IssuedArtifact
from test_artifact_access import stored_invoice  # noqa: F401
from test_issuance import ready_invoice as issuance_ready  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


def cancel_original(original: Invoice, actor: User) -> Invoice:
    from pinaks.apps.billing.cancellations import create_cancellation
    from pinaks.apps.billing.issuance import issue_invoice
    from pinaks.apps.documents.issuance import generate_invoice

    cancellation, _ = create_cancellation(
        invoice_id=original.pk,
        reason="Wrong details",
        idempotency_key="cancel",
        actor=actor,
        correlation_id="test",
    )
    assert original.snapshot is not None
    template = original.snapshot["template"]
    assert isinstance(template, dict)
    issue_invoice(
        invoice_id=cancellation.pk,
        expected_version=cancellation.version,
        template_id=template["id"],
        idempotency_key="issue-cancel",
        actor=actor,
        correlation_id="test",
    )
    generate_invoice(invoice_id=cancellation.pk)
    original.refresh_from_db()
    return cancellation


def test_replacement_requires_completed_full_cancellation_then_creates_editable_draft(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    original, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    url = f"/api/v1/invoices/{original.pk}/correct/"
    body = {"reason": "Correct service price", "idempotency_key": "replace"}
    response = client.post(url, body, format="json")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "invalid_replacement"
    cancellation = cancel_original(original, actor)
    before = Invoice.objects.values().get(pk=original.pk)
    artifacts = list(IssuedArtifact.objects.values())
    response = client.post(url, body, format="json")
    assert response.status_code == 201
    draft = Invoice.objects.get(pk=response.data["id"])
    assert response.data["cancellation_template_id"] is not None
    assert draft.invoice_type == "REPLACEMENT"
    assert draft.original_invoice_id == original.pk
    assert draft.correction_reason == body["reason"]
    assert draft.payment_status == "UNPAID"
    assert draft.invoice_number is None
    assert draft.grand_total == original.grand_total
    line = InvoiceLine.objects.get(invoice=draft)
    changed = client.patch(
        f"/api/v1/invoices/{draft.pk}/",
        {
            "expected_version": draft.version,
            "line_operations": [{"action": "update", "line_id": line.pk, "unit_price": "50.00"}],
        },
        format="json",
    )
    assert changed.status_code == 200
    assert changed.data["grand_total"] == "59.50"
    retry = client.post(url, body, format="json")
    assert retry.status_code == 200 and retry.data["id"] == draft.pk
    assert client.post(url, {**body, "reason": "Other"}, format="json").status_code == 409
    assert client.post(url, {**body, "idempotency_key": "other"}, format="json").status_code == 409
    assert set(client.get(f"/api/v1/invoices/{original.pk}/").data["related_invoice_ids"]) == {
        cancellation.pk,
        draft.pk,
    }
    assert Invoice.objects.values().get(pk=original.pk) == before
    assert list(IssuedArtifact.objects.values()) == artifacts


def test_replacement_issuance_freezes_corrected_content_and_traceability(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from pinaks.apps.billing.issuance import issue_invoice
    from pinaks.apps.billing.replacements import create_replacement
    from pinaks.apps.billing.services import update_draft
    from pinaks.apps.documents.issuance import generate_invoice

    original, actor = stored_invoice
    cancel_original(original, actor)
    before = Invoice.objects.values().get(pk=original.pk)
    evidence = list(IssuedArtifact.objects.values())
    replacement, _ = create_replacement(
        invoice_id=original.pk,
        reason="Wrong price",
        idempotency_key="replace",
        actor=actor,
        correlation_id="test",
    )
    line = InvoiceLine.objects.get(invoice=replacement)
    replacement = update_draft(
        invoice_id=replacement.pk,
        expected_version=replacement.version,
        values={
            "line_operations": [
                {"action": "update", "line_id": line.pk, "unit_price": Decimal("50.00")}
            ]
        },
        actor=actor,
        correlation_id="test",
    )
    assert original.snapshot is not None
    template = original.snapshot["template"]
    assert isinstance(template, dict)
    issued = issue_invoice(
        invoice_id=replacement.pk,
        expected_version=replacement.version,
        template_id=template["id"],
        idempotency_key="issue-replacement",
        actor=actor,
        correlation_id="test",
    )
    assert issued.snapshot is not None
    invoice = issued.snapshot["invoice"]
    assert isinstance(invoice, dict)
    assert invoice["type"] == "REPLACEMENT"
    assert invoice["correction_reason"] == "Wrong price"
    assert invoice["original_reference"] == {
        "number": original.invoice_number,
        "issue_date": original.issue_date.isoformat(),
    }
    assert invoice["grand_total"] == "59.50"
    assert issued.invoice_number != original.invoice_number
    generate_invoice(invoice_id=issued.pk)
    issued.refresh_from_db()
    assert issued.lifecycle_status == "ISSUED"
    assert issued.payment_status == "UNPAID"
    generate_invoice(invoice_id=issued.pk)
    assert IssuedArtifact.objects.filter(invoice=issued).count() == 3
    assert Invoice.objects.values().get(pk=original.pk) == before
    assert list(IssuedArtifact.objects.exclude(invoice=issued).values()) == evidence


@pytest.mark.parametrize(
    "role,active,expected",
    [
        ("admin", True, 201),
        ("company_member", True, 201),
        ("read_only", True, 403),
        ("admin", False, 403),
    ],
)
def test_replacement_permissions(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
    role: str,
    active: bool,
    expected: int,
) -> None:
    original, owner = stored_invoice
    cancel_original(original, owner)
    actor = User.objects.create_user(username="replacement-actor", role=role, is_active=active)
    client = APIClient()
    url = f"/api/v1/invoices/{original.pk}/correct/"
    body = {"reason": "Fix", "idempotency_key": "replace"}
    assert client.post(url, body, format="json").status_code == 403
    client.force_authenticate(actor)
    assert client.post(url, body, format="json").status_code == expected


def test_replacement_validation_csrf_and_unhealthy_cancellation(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from django.conf import settings

    original, actor = stored_invoice
    cancellation = cancel_original(original, actor)
    client = APIClient()
    client.force_authenticate(actor)
    url = f"/api/v1/invoices/{original.pk}/correct/"
    body = {"reason": "Fix", "idempotency_key": "replace"}
    for invalid in (
        {},
        {**body, "reason": " "},
        {**body, "idempotency_key": ""},
        {**body, "reason": "x" * 501},
        {**body, "invoice_type": "STANDARD"},
    ):
        assert client.post(url, invalid, format="json").status_code == 400
    session = APIClient(enforce_csrf_checks=True)
    session.force_login(actor)
    assert session.post(url, body, format="json").status_code == 403
    assert client.post("/api/v1/invoices/999999/correct/", body, format="json").status_code == 404
    artifact = IssuedArtifact.objects.get(invoice=cancellation, kind="pdf")
    (settings.ISSUED_DOCUMENT_ROOT / artifact.storage_key).write_bytes(b"damaged")
    response = client.post(url, body, format="json")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "invalid_replacement"


def test_concurrent_replacement_commands_create_one_identity(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connections

    from pinaks.apps.billing.replacements import create_replacement

    original, actor = stored_invoice
    cancel_original(original, actor)
    barrier = Barrier(2)

    def create() -> tuple[int, bool]:
        try:
            thread_actor = User.objects.get(pk=actor.pk)
            barrier.wait(timeout=10)
            invoice, created = create_replacement(
                invoice_id=original.pk,
                reason="Fix",
                idempotency_key="same",
                actor=thread_actor,
                correlation_id="test",
            )
            return invoice.pk, created
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    assert len({result[0] for result in results}) == 1
    assert sum(result[1] for result in results) == 1


def test_database_prevents_replacement_without_reversal_and_identity_mutation(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from django.db import DatabaseError, transaction

    from pinaks.apps.billing.replacements import create_replacement

    original, actor = stored_invoice
    with pytest.raises(DatabaseError), transaction.atomic():
        Invoice.objects.create(
            customer=original.customer,
            issue_date=original.issue_date,
            document_language="en",
            invoice_type="REPLACEMENT",
            original_invoice=original,
            correction_reason="Fix",
            correction_key="direct",
        )
    cancel_original(original, actor)
    draft, _ = create_replacement(
        invoice_id=original.pk,
        reason="Fix",
        idempotency_key="replace",
        actor=actor,
        correlation_id="test",
    )
    for values in (
        {"correction_reason": "Other"},
        {"correction_key": "other"},
        {
            "invoice_type": "STANDARD",
            "original_invoice": None,
            "correction_key": "",
            "correction_reason": "",
        },
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            Invoice.objects.filter(pk=draft.pk).update(**values)
    with pytest.raises(DatabaseError), transaction.atomic():
        Invoice.objects.filter(pk=draft.pk).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        Invoice.objects.create(
            customer=original.customer,
            issue_date=draft.issue_date,
            document_language="en",
            invoice_type="REPLACEMENT",
            original_invoice=original,
            correction_reason="Another",
            correction_key="another",
        )


@pytest.mark.parametrize("reservation", ["pending_cancellation", "partial_credit"])
def test_replacement_does_not_accept_unissued_or_partial_reversals(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
    reservation: str,
) -> None:
    original, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    body = {"reason": "Fix", "idempotency_key": "reserve"}
    if reservation == "pending_cancellation":
        response = client.post(f"/api/v1/invoices/{original.pk}/cancel/", body, format="json")
    else:
        response = client.post(
            f"/api/v1/invoices/{original.pk}/credit-notes/",
            {
                **body,
                "lines": [{"position": 1, "quantity": "0.5", "unit_price": "100.00"}],
            },
            format="json",
        )
    assert response.status_code == 201
    assert (
        client.post(
            f"/api/v1/invoices/{original.pk}/correct/",
            {
                "reason": "Fix",
                "idempotency_key": "replace",
            },
            format="json",
        ).status_code
        == 409
    )


def test_replacement_returns_business_errors_for_key_collision_and_earlier_date(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from datetime import timedelta

    original, actor = stored_invoice
    cancel_original(original, actor)
    client = APIClient()
    client.force_authenticate(actor)
    url = f"/api/v1/invoices/{original.pk}/correct/"
    collision = client.post(url, {"reason": "Fix", "idempotency_key": "cancel"}, format="json")
    assert collision.status_code == 409
    assert collision.data["error"]["code"] == "invalid_replacement"
    response = client.post(url, {"reason": "Fix", "idempotency_key": "replace"}, format="json")
    assert response.status_code == 201
    draft = response.data
    response = client.patch(
        f"/api/v1/invoices/{draft['id']}/",
        {
            "expected_version": draft["version"],
            "issue_date": (original.issue_date - timedelta(days=1)).isoformat(),
        },
        format="json",
    )
    assert response.status_code == 400
    assert Invoice.objects.get(pk=draft["id"]).version == draft["version"]

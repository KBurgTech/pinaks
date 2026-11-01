from datetime import date, timedelta
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.models import AuditEvent
from pinaks.apps.billing.models import Invoice
from pinaks.apps.documents.models import IssuedArtifact
from test_artifact_access import stored_invoice  # noqa: F401
from test_issuance import ready_invoice as issuance_ready  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


def test_payment_commands_preserve_evidence_and_record_only_real_transitions(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    invoice, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    before = Invoice.objects.values().get(pk=invoice.pk)
    artifacts = list(IssuedArtifact.objects.filter(invoice=invoice).values())
    for state, command in (("PAID", "mark-paid"), ("UNPAID", "mark-unpaid")):
        url = f"/api/v1/invoices/{invoice.pk}/{command}/"
        response = client.post(url, {}, format="json")
        assert response.status_code == 200
        assert response.data["payment_status"] == state
        assert response.data["payment_changed_by_id"] == actor.pk
        assert response.data["payment_changed_at"]
        repeated = client.post(url, {}, format="json")
        assert repeated.data == response.data
    after = Invoice.objects.values().get(pk=invoice.pk)
    for field in ("payment_status", "payment_changed_at", "payment_changed_by_id"):
        before.pop(field, None)
        after.pop(field)
    assert after == before
    assert list(IssuedArtifact.objects.filter(invoice=invoice).values()) == artifacts
    events = AuditEvent.objects.filter(action_code="billing.invoice_payment_changed")
    assert events.count() == 2
    event = events.last()
    assert event is not None
    assert event.metadata == {"previous_status": "PAID", "payment_status": "UNPAID"}


@pytest.mark.parametrize(
    "role,active,allowed",
    [
        ("admin", True, True),
        ("company_member", True, True),
        ("read_only", True, False),
        ("admin", False, False),
    ],
)
def test_payment_permissions(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
    role: str,
    active: bool,
    allowed: bool,
) -> None:
    invoice, _ = stored_invoice
    actor = User.objects.create_user(username="payment-actor", role=role, is_active=active)
    client = APIClient()
    url = f"/api/v1/invoices/{invoice.pk}/mark-paid/"
    assert client.post(url, {}, format="json").status_code == 403
    client.force_authenticate(actor)
    assert client.post(url, {}, format="json").status_code == (200 if allowed else 403)


def test_payment_rejects_drafts_and_issuing_and_honors_csrf(
    issuance_ready: tuple[Invoice, User, object],  # noqa: F811
) -> None:
    invoice, actor, _ = issuance_ready
    client = APIClient()
    client.force_authenticate(actor)
    for state in ("DRAFT", "ISSUING"):
        if state == "ISSUING":
            Invoice.objects.filter(pk=invoice.pk).update(
                lifecycle_status=state, invoice_number="test", snapshot={}, issuance_key="test"
            )
        response = client.post(f"/api/v1/invoices/{invoice.pk}/mark-paid/", {}, format="json")
        assert response.status_code == 409
        assert response.data["error"]["code"] == "invalid_payment_transition"
    assert client.post("/api/v1/invoices/999999/mark-paid/", {}, format="json").status_code == 404
    session = APIClient(enforce_csrf_checks=True)
    session.force_login(actor)
    assert (
        session.post(f"/api/v1/invoices/{invoice.pk}/mark-paid/", {}, format="json").status_code
        == 403
    )


@pytest.mark.parametrize("lifecycle", ["DRAFT", "ISSUING", "ISSUED", "CANCELLED"])
@pytest.mark.parametrize("payment", ["UNPAID", "PAID"])
@pytest.mark.parametrize("offset", [-1, 0, 1, None])
def test_overdue_uses_lifecycle_payment_and_injected_date(
    lifecycle: str, payment: str, offset: int | None
) -> None:
    from pinaks.apps.billing.payments import is_overdue

    today = date(2026, 10, 31)
    invoice = Invoice(
        lifecycle_status=lifecycle,
        payment_status=payment,
        due_date=None if offset is None else today + timedelta(days=offset),
    )
    expected = lifecycle == "ISSUED" and payment == "UNPAID" and offset == -1
    assert is_overdue(invoice, today=today) is expected
    with patch("django.utils.timezone.localdate", return_value=today):
        assert invoice.is_overdue is expected


def test_filters_match_overdue_representation(stored_invoice: tuple[Invoice, User]) -> None:  # noqa: F811
    invoice, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    today = invoice.due_date + timedelta(days=1) if invoice.due_date else date(2099, 1, 1)
    with patch("django.utils.timezone.localdate", return_value=today):
        result = client.get("/api/v1/invoices/?lifecycle_status=ISSUED&overdue=true")
        assert result.status_code == 200
        assert result.data["count"] == int(invoice.due_date is not None)
        client.post(f"/api/v1/invoices/{invoice.pk}/mark-paid/", {}, format="json")
        assert client.get("/api/v1/invoices/?overdue=true").data["count"] == 0
        assert client.get("/api/v1/invoices/?payment_status=PAID&overdue=false").data["count"] == 1

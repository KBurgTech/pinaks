from decimal import Decimal

import pytest
from django.db import DatabaseError, transaction
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User
from pinaks.apps.audit.models import AuditEvent
from pinaks.apps.billing.models import Invoice, InvoiceLine
from pinaks.apps.documents.models import IssuedArtifact
from test_artifact_access import stored_invoice  # noqa: F401
from test_issuance import ready_invoice as issuance_ready  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


def command(key: str = "credit-1", quantity: str = "0.5") -> dict[str, object]:
    return {
        "reason": "Service partly refunded",
        "idempotency_key": key,
        "lines": [{"position": 1, "quantity": quantity, "unit_price": "100.00"}],
    }


def test_partial_credit_reserves_limits_is_idempotent_and_preserves_evidence(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    original, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    before = Invoice.objects.values().get(pk=original.pk)
    artifacts = list(IssuedArtifact.objects.values())
    url = f"/api/v1/invoices/{original.pk}/credit-notes/"
    response = client.post(url, command(), format="json")
    assert response.status_code == 201
    draft = Invoice.objects.get(pk=response.data["id"])
    assert draft.invoice_type == "CREDIT_NOTE"
    assert draft.original_invoice_id == original.pk
    assert draft.grand_total == Decimal("59.50")
    assert InvoiceLine.objects.get(invoice=draft).quantity == Decimal("0.5")
    assert client.post(url, command(), format="json").status_code == 200
    assert client.post(url, command(quantity="0.4"), format="json").status_code == 409
    assert client.post(url, command("credit-2", "0.6"), format="json").status_code == 409
    assert client.post(url, command("credit-2", "0.5"), format="json").status_code == 201
    assert client.post(url, command("credit-3", "0.1"), format="json").status_code == 409
    assert (
        client.post(
            f"/api/v1/invoices/{original.pk}/cancel/",
            {"reason": "Cancel", "idempotency_key": "cancel"},
            format="json",
        ).status_code
        == 409
    )
    assert Invoice.objects.values().get(pk=original.pk) == before
    assert list(IssuedArtifact.objects.values()) == artifacts
    assert AuditEvent.objects.filter(action_code="billing.credit_note_created").count() == 2
    assert client.get(f"/api/v1/invoices/{original.pk}/").data["related_invoice_ids"] == list(
        Invoice.objects.filter(original_invoice=original)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    for mutate in (
        lambda: Invoice.objects.filter(pk=draft.pk).update(correction_reason="Changed"),
        lambda: InvoiceLine.objects.filter(invoice=draft).update(quantity="0.9"),
        lambda: Invoice.objects.filter(pk=draft.pk).delete(),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            mutate()


@pytest.mark.parametrize(
    "role,active,expected",
    [
        ("admin", True, 201),
        ("company_member", True, 201),
        ("read_only", True, 403),
        ("admin", False, 403),
    ],
)
def test_credit_permissions_and_csrf(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
    role: str,
    active: bool,
    expected: int,
) -> None:
    original, _ = stored_invoice
    actor = User.objects.create_user(username="credit-actor", role=role, is_active=active)
    client = APIClient()
    url = f"/api/v1/invoices/{original.pk}/credit-notes/"
    assert client.post(url, command(), format="json").status_code == 403
    client.force_authenticate(actor)
    assert client.post(url, command(), format="json").status_code == expected
    session = APIClient(enforce_csrf_checks=True)
    session.force_login(actor)
    assert session.post(url, command(), format="json").status_code == 403


@pytest.mark.parametrize(
    "lines",
    [
        [],
        [{"position": 1, "quantity": "0", "unit_price": "100.00"}],
        [{"position": 1, "quantity": "0.5", "unit_price": "101.00"}],
        [{"position": 999, "quantity": "0.5", "unit_price": "100.00"}],
        [{"position": 1, "quantity": "0.5", "unit_price": "100.00"}] * 2,
    ],
)
def test_credit_rejects_invalid_allocations(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
    lines: list[dict[str, str | int]],
) -> None:
    original, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    response = client.post(
        f"/api/v1/invoices/{original.pk}/credit-notes/",
        {**command(), "lines": lines},
        format="json",
    )
    assert response.status_code == 400
    assert not Invoice.objects.filter(original_invoice=original).exists()


def test_cancellation_reservation_prevents_partial_credit(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    original, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    assert (
        client.post(
            f"/api/v1/invoices/{original.pk}/cancel/",
            {"reason": "Cancel", "idempotency_key": "cancel"},
            format="json",
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/v1/invoices/{original.pk}/credit-notes/", command(), format="json"
        ).status_code
        == 409
    )


def test_credit_issuance_uses_frozen_tax_and_does_not_cancel_original(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from pinaks.apps.billing.issuance import issue_invoice
    from pinaks.apps.configuration.models import TaxProfile
    from pinaks.apps.documents.issuance import generate_invoice

    original, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    response = client.post(
        f"/api/v1/invoices/{original.pk}/credit-notes/", command(), format="json"
    )
    assert response.status_code == 201
    draft = Invoice.objects.get(pk=response.data["id"])
    assert original.snapshot is not None
    template = original.snapshot["template"]
    assert isinstance(template, dict)
    TaxProfile.objects.update(rate="7.00")
    frozen = issue_invoice(
        invoice_id=draft.pk,
        expected_version=draft.version,
        template_id=template["id"],
        idempotency_key="issue-credit",
        actor=actor,
        correlation_id="test",
    )
    assert frozen.snapshot is not None
    for key in ("seller", "customer", "recipient", "tax_profile"):
        assert frozen.snapshot[key] == original.snapshot[key]
    document = frozen.snapshot["invoice"]
    assert isinstance(document, dict)
    assert document["type"] == "CREDIT_NOTE"
    assert Decimal(str(document["grand_total"])) == Decimal("59.50")
    generate_invoice(invoice_id=draft.pk)
    generate_invoice(invoice_id=draft.pk)
    original.refresh_from_db()
    draft.refresh_from_db()
    assert original.lifecycle_status == "ISSUED"
    assert draft.lifecycle_status == "ISSUED"
    assert IssuedArtifact.objects.filter(invoice=draft).count() == 3
    replay = client.post(f"/api/v1/invoices/{original.pk}/credit-notes/", command(), format="json")
    assert replay.status_code == 200
    assert replay.data["id"] == draft.pk


def test_concurrent_credits_cannot_overreserve(stored_invoice: tuple[Invoice, User]) -> None:  # noqa: F811
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connections

    from pinaks.apps.billing.credit_notes import InvalidCreditNoteError, create_credit_note

    original, actor = stored_invoice
    barrier = Barrier(2)

    def credit(key: str) -> str:
        try:
            thread_actor = User.objects.get(pk=actor.pk)
            barrier.wait(timeout=10)
            try:
                create_credit_note(
                    invoice_id=original.pk,
                    reason="Partial",
                    idempotency_key=key,
                    lines=[
                        {"position": 1, "quantity": Decimal("0.6"), "unit_price": Decimal("100")}
                    ],
                    actor=thread_actor,
                    correlation_id="test",
                )
                return "created"
            except InvalidCreditNoteError:
                return "conflict"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(credit, ["a", "b"])) == ["conflict", "created"]


def test_database_prevents_cancellation_after_credit_reservation(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    original, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    assert (
        client.post(
            f"/api/v1/invoices/{original.pk}/credit-notes/", command(), format="json"
        ).status_code
        == 201
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        Invoice.objects.create(
            customer=original.customer,
            document_language="en",
            issue_date=original.issue_date,
            invoice_type="CANCELLATION",
            original_invoice=original,
            correction_reason="Bypass",
            correction_key="bypass",
        )


def test_price_reduction_and_validation(stored_invoice: tuple[Invoice, User]) -> None:  # noqa: F811
    original, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    body = {**command(), "lines": [{"position": 1, "quantity": "0.5", "unit_price": "40.00"}]}
    url = f"/api/v1/invoices/{original.pk}/credit-notes/"
    response = client.post(url, body, format="json")
    assert response.status_code == 201
    assert response.data["grand_total"] == "23.80"
    assert response.data["cancellation_template_id"] is not None
    assert "credit_allocations" not in response.data
    assert "snapshot" not in response.data
    assert client.post(url, {**body, "reason": "changed"}, format="json").status_code == 409
    assert client.post(url, {**body, "reason": " "}, format="json").status_code == 400
    assert (
        client.post("/api/v1/invoices/999999/credit-notes/", body, format="json").status_code == 404
    )


def test_database_rejects_overcredit_even_without_service(
    stored_invoice: tuple[Invoice, User],  # noqa: F811
) -> None:
    from copy import deepcopy

    original, actor = stored_invoice
    client = APIClient()
    client.force_authenticate(actor)
    assert (
        client.post(
            f"/api/v1/invoices/{original.pk}/credit-notes/", command(), format="json"
        ).status_code
        == 201
    )
    candidate = Invoice.objects.create(
        customer=original.customer,
        document_language="en",
        issue_date=original.issue_date,
        subtotal="60.00",
        tax_total="11.40",
        grand_total="71.40",
    )
    line = deepcopy(InvoiceLine.objects.get(invoice=original))
    line.pk = None
    line.invoice = candidate
    line.quantity = Decimal("0.6")
    line.net_total, line.tax_total, line.gross_total = (
        Decimal("60"),
        Decimal("11.4"),
        Decimal("71.4"),
    )
    line.save(force_insert=True)
    with pytest.raises(DatabaseError), transaction.atomic():
        Invoice.objects.filter(pk=candidate.pk).update(
            invoice_type="CREDIT_NOTE",
            original_invoice=original,
            correction_reason="Bypass",
            correction_key="bypass",
            credit_allocations=[{"position": 1, "quantity": "0.6", "unit_price": "100"}],
        )

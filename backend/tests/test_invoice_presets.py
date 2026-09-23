from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.billing.models import Invoice, InvoiceLine
from pinaks.apps.billing.services import create_draft
from pinaks.apps.configuration.models import CompanyProfile
from pinaks.apps.customers.models import Customer

pytestmark = pytest.mark.django_db


@pytest.fixture
def context() -> tuple[APIClient, Invoice, User]:
    CompanyProfile.objects.create(legal_name="Seller")
    user = User.objects.create_user(username="editor", password="test", role=UserRole.ADMIN)
    customer = Customer.objects.create(
        customer_number="P1", party_type="person", given_name="Ada", family_name="Lovelace"
    )
    invoice = create_draft(customer=customer, actor=user, correlation_id="preset-test")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, invoice, user


def line(description: str, price: str = "10.00") -> dict[str, str]:
    return {
        "description": description,
        "item_code": "WORK",
        "unit": "HUR",
        "quantity": "2.0000",
        "unit_price": price,
        "discount_percent": "0.00",
        "tax_category": "S",
        "tax_rate": "19.00",
        "price_entry_policy": "net",
        "exemption_reason_code": "",
        "exemption_wording": "",
    }


def test_preset_create_update_apply_append_replace_and_archive(
    context: tuple[APIClient, Invoice, User],
) -> None:
    client, invoice, _ = context
    created = client.post(
        "/api/v1/invoice-presets/",
        {"name": "Routine", "lines": [line("First"), line("Second", "5.00")]},
        format="json",
    )
    assert created.status_code == 201, created.json()
    preset_id = created.json()["id"]
    assert [row["description"] for row in created.json()["lines"]] == ["First", "Second"]
    appended = client.post(
        f"/api/v1/invoices/{invoice.pk}/apply-preset/",
        {"preset_id": preset_id, "expected_version": 1, "mode": "append"},
        format="json",
    )
    assert appended.status_code == 200, appended.json()
    assert [row["description"] for row in appended.json()["lines"]] == ["First", "Second"]
    assert appended.json()["grand_total"] == "35.70"
    assert appended.json()["version"] == 2

    edited = client.patch(
        f"/api/v1/invoice-presets/{preset_id}/",
        {"name": "Updated", "lines": [line("Changed", "7.00")]},
        format="json",
    )
    assert edited.status_code == 200, edited.json()
    replaced = client.post(
        f"/api/v1/invoices/{invoice.pk}/apply-preset/",
        {"preset_id": preset_id, "expected_version": 2, "mode": "replace"},
        format="json",
    )
    assert replaced.status_code == 200, replaced.json()
    assert [row["description"] for row in replaced.json()["lines"]] == ["Changed"]
    assert replaced.json()["grand_total"] == "16.66"
    assert list(InvoiceLine.objects.filter(invoice=invoice).values_list("position", flat=True)) == [
        1
    ]

    archived = client.post(f"/api/v1/invoice-presets/{preset_id}/archive/")
    assert archived.status_code == 200, archived.json()
    assert archived.json()["is_archived"] is True
    assert client.get("/api/v1/invoice-presets/").json() == []
    forbidden = client.post(
        f"/api/v1/invoices/{invoice.pk}/apply-preset/",
        {"preset_id": preset_id, "expected_version": 3, "mode": "append"},
        format="json",
    )
    assert forbidden.status_code == 409
    assert forbidden.json()["error"]["code"] == "preset_archived"


def test_preset_is_snapshot_and_stale_apply_is_atomic(
    context: tuple[APIClient, Invoice, User],
) -> None:
    client, invoice, _ = context
    created = client.post(
        "/api/v1/invoice-presets/", {"name": "Snapshot", "lines": [line("Stored")]}, format="json"
    )
    preset_id = created.json()["id"]
    stale = client.post(
        f"/api/v1/invoices/{invoice.pk}/apply-preset/",
        {"preset_id": preset_id, "expected_version": 99, "mode": "append"},
        format="json",
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_invoice_version"
    assert not InvoiceLine.objects.filter(invoice=invoice).exists()
    assert Invoice.objects.get(pk=invoice.pk).version == 1
    assert Decimal(created.json()["lines"][0]["unit_price"]) == Decimal("10.00")


def test_preset_permissions_and_invalid_lines(context: tuple[APIClient, Invoice, User]) -> None:
    client, invoice, _ = context
    invalid = client.post(
        "/api/v1/invoice-presets/",
        {"name": "Bad", "lines": [{**line("Bad"), "tax_category": "E"}]},
        format="json",
    )
    assert invalid.status_code == 400
    reader = User.objects.create_user(username="reader", password="test", role=UserRole.READ_ONLY)
    client.force_authenticate(user=reader)
    assert client.post("/api/v1/invoice-presets/", {"name": "No"}, format="json").status_code == 403
    assert (
        client.post(
            f"/api/v1/invoices/{invoice.pk}/apply-preset/",
            {"preset_id": 1, "expected_version": 1, "mode": "append"},
            format="json",
        ).status_code
        == 403
    )

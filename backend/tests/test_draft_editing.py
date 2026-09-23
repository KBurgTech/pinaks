from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.billing.models import Invoice, InvoiceLine
from pinaks.apps.billing.services import create_draft
from pinaks.apps.catalog.models import CatalogItem
from pinaks.apps.configuration.models import CompanyProfile, TaxProfile
from pinaks.apps.customers.models import BillingRecipient, Customer, CustomerAddress

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup() -> tuple[APIClient, Invoice, Customer, Customer]:
    CompanyProfile.objects.create(legal_name="Seller")
    actor = User.objects.create_user(username="editor", password="test", role=UserRole.ADMIN)
    buyer = Customer.objects.create(
        customer_number="C1",
        party_type="person",
        given_name="Ada",
        family_name="Lovelace",
        preferred_language="en",
    )
    other = Customer.objects.create(
        customer_number="C2",
        party_type="organization",
        organization_name="Other Ltd",
        preferred_language="de",
    )
    CustomerAddress.objects.create(
        customer=buyer, label="Main", address_line_1="Buyer St", city="Berlin", is_primary=True
    )
    CustomerAddress.objects.create(
        customer=other, label="Main", address_line_1="Other St", city="Bonn", is_primary=True
    )
    invoice = create_draft(customer=buyer, actor=actor, correlation_id="test")
    client = APIClient()
    client.force_authenticate(user=actor)
    return client, invoice, buyer, other


@pytest.mark.parametrize("source", ["customer", "saved", "known_customer", "manual"])
def test_recipient_sources_are_copied_and_separate(
    setup: tuple[APIClient, Invoice, Customer, Customer], source: str
) -> None:
    client, invoice, buyer, other = setup
    saved = BillingRecipient.objects.create(
        customer=buyer,
        party_type="organization",
        organization_name="Payer GmbH",
        address_line_1="Payer St",
        city="Leipzig",
    )
    recipient = {
        "customer": {"source": "customer"},
        "saved": {"source": "saved", "recipient_id": saved.pk},
        "known_customer": {"source": "known_customer", "customer_id": other.pk},
        "manual": {
            "source": "manual",
            "values": {
                "party_type": "organization",
                "organization_name": "Manual AG",
                "address_line_1": "Manual St",
                "city": "Hamburg",
                "country_code": "DE",
            },
        },
    }[source]
    response = client.patch(
        f"/api/v1/invoices/{invoice.pk}/",
        {"expected_version": 1, "recipient": recipient},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["customer_id"] == buyer.pk
    assert (
        response.json()["recipient"]["address_line_1"]
        == {
            "customer": "Buyer St",
            "saved": "Payer St",
            "known_customer": "Other St",
            "manual": "Manual St",
        }[source]
    )
    if source == "saved":
        saved.address_line_1 = "Changed"
        saved.save()
    elif source == "known_customer":
        other.organization_name = "Changed"
        other.save()
    else:
        buyer.given_name = "Changed"
        buyer.save()
    assert (
        client.get(f"/api/v1/invoices/{invoice.pk}/").json()["recipient"]
        == response.json()["recipient"]
    )


def test_header_validation_and_stale_version(
    setup: tuple[APIClient, Invoice, Customer, Customer],
) -> None:
    client, invoice, _, _ = setup
    url = f"/api/v1/invoices/{invoice.pk}/"
    invalid = client.patch(url, {"expected_version": 1, "document_language": "fr"}, format="json")
    assert invalid.status_code == 400
    invalid = client.patch(
        url,
        {"expected_version": 1, "issue_date": "2026-10-01", "due_date": "2026-09-01"},
        format="json",
    )
    assert invalid.status_code == 400
    first = client.patch(
        url,
        {"expected_version": 1, "document_language": "de", "issue_date": "2026-09-22"},
        format="json",
    )
    assert first.status_code == 200, first.json()
    stale = client.patch(url, {"expected_version": 1, "document_language": "en"}, format="json")
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_invoice_version"
    assert client.get(url).json()["document_language"] == "de"


def test_line_operations_reorder_recalculate_and_copy_catalog_tax(
    setup: tuple[APIClient, Invoice, Customer, Customer],
) -> None:
    client, invoice, _, _ = setup
    tax = TaxProfile.objects.create(
        code="standard",
        name="Standard",
        tax_category="S",
        rate=Decimal("19.00"),
        price_entry_policy="net",
        tax_column_policy="show",
        requires_tax_number=True,
    )
    item = CatalogItem.objects.create(
        code="WORK",
        description_en="Work",
        description_de="Arbeit",
        unit="HUR",
        default_price=Decimal("10.00"),
        default_tax_profile=tax,
    )
    url = f"/api/v1/invoices/{invoice.pk}/"
    first = client.patch(
        url,
        {
            "expected_version": 1,
            "line_operations": [
                {"action": "add", "catalog_item_id": item.pk, "quantity": "2.0000"}
            ],
        },
        format="json",
    )
    assert first.status_code == 200, first.json()
    assert first.json()["grand_total"] == "23.80"
    line_id = first.json()["lines"][0]["id"]
    assert first.json()["lines"][0]["description"] == "Work"
    item.description_en = "Changed"
    item.default_price = Decimal("20.00")
    item.save()
    tax.rate = Decimal("7.00")
    tax.save()
    assert client.get(url).json()["lines"][0]["description"] == "Work"
    assert client.get(url).json()["lines"][0]["tax_rate"] == "19.00"
    second = client.patch(
        url,
        {
            "expected_version": 2,
            "line_operations": [
                {"action": "add", "catalog_item_id": item.pk, "quantity": "1.0000", "position": 1},
                {"action": "update", "line_id": line_id, "quantity": "3.0000"},
            ],
        },
        format="json",
    )
    assert second.status_code == 200, second.json()
    assert [(line["position"], line["description"]) for line in second.json()["lines"]] == [
        (1, "Changed"),
        (2, "Work"),
    ]
    assert second.json()["grand_total"] == "57.10"
    removed = client.patch(
        url,
        {"expected_version": 3, "line_operations": [{"action": "remove", "line_id": line_id}]},
        format="json",
    )
    assert removed.status_code == 200, removed.json()
    assert removed.json()["grand_total"] == "21.40"
    assert list(InvoiceLine.objects.filter(invoice=invoice).values_list("position", flat=True)) == [
        1
    ]


def test_draft_mutation_requires_role_and_rejects_totals(
    setup: tuple[APIClient, Invoice, Customer, Customer],
) -> None:
    client, invoice, _, _ = setup
    url = f"/api/v1/invoices/{invoice.pk}/"
    assert (
        client.patch(url, {"expected_version": 1, "grand_total": "1.00"}, format="json").status_code
        == 400
    )
    reader = User.objects.create_user(username="reader", password="test", role=UserRole.READ_ONLY)
    client.force_authenticate(user=reader)
    assert (
        client.patch(
            url, {"expected_version": 1, "document_language": "de"}, format="json"
        ).status_code
        == 403
    )


def test_manual_line_and_invalid_tax_are_atomic(
    setup: tuple[APIClient, Invoice, Customer, Customer],
) -> None:
    client, invoice, _, _ = setup
    url = f"/api/v1/invoices/{invoice.pk}/"
    base = {
        "action": "add",
        "description": "Consulting",
        "unit": "HUR",
        "quantity": "2.0000",
        "unit_price": "5.00",
        "tax_category": "S",
        "tax_rate": "19.00",
        "price_entry_policy": "net",
    }
    invalid = client.patch(
        url,
        {"expected_version": 1, "line_operations": [{**base, "tax_category": "E"}]},
        format="json",
    )
    assert invalid.status_code == 400, invalid.json()
    assert Invoice.objects.get(pk=invoice.pk).version == 1
    assert not InvoiceLine.objects.filter(invoice=invoice).exists()
    valid = client.patch(url, {"expected_version": 1, "line_operations": [base]}, format="json")
    assert valid.status_code == 200, valid.json()
    assert valid.json()["grand_total"] == "11.90"


def test_saved_recipient_must_belong_to_invoice_customer(
    setup: tuple[APIClient, Invoice, Customer, Customer],
) -> None:
    client, invoice, _, other = setup
    saved = BillingRecipient.objects.create(
        customer=other, party_type="organization", organization_name="Private"
    )
    response = client.patch(
        f"/api/v1/invoices/{invoice.pk}/",
        {"expected_version": 1, "recipient": {"source": "saved", "recipient_id": saved.pk}},
        format="json",
    )
    assert response.status_code == 404
    assert Invoice.objects.get(pk=invoice.pk).version == 1


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_writes_allow_one_version_winner(
    setup: tuple[APIClient, Invoice, Customer, Customer],
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from pinaks.apps.billing.services import StaleInvoiceVersionError, update_draft

    _, invoice, _, _ = setup
    actor = User.objects.get(username="editor")
    barrier = Barrier(2)

    def write(language: str) -> str:
        barrier.wait()
        try:
            update_draft(
                invoice_id=invoice.pk,
                expected_version=1,
                values={"document_language": language},
                actor=actor,
                correlation_id="concurrent",
            )
            return "saved"
        except StaleInvoiceVersionError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ("en", "de")))
    assert sorted(results) == ["saved", "stale"]
    assert Invoice.objects.get(pk=invoice.pk).version == 2

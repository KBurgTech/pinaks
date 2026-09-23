from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.billing.models import Invoice
from pinaks.apps.billing.services import create_draft
from pinaks.apps.configuration.models import CompanyProfile
from pinaks.apps.customers.models import Customer

pytestmark = pytest.mark.django_db


def user(role: UserRole) -> User:
    return User.objects.create_user(username=role.value, password="long test password", role=role)


def customer(number: str = "C-1", language: str = "en") -> Customer:
    return Customer.objects.create(
        customer_number=number,
        party_type="person",
        given_name="Ada",
        family_name="Lovelace",
        preferred_language=language,
    )


def test_create_draft_uses_customer_and_company_defaults_without_a_number() -> None:
    CompanyProfile.objects.create(legal_name="Seller", default_document_language="de")
    actor = user(UserRole.COMPANY_MEMBER)
    buyer = customer()

    invoice = create_draft(customer=buyer, actor=actor, correlation_id="draft-1")

    assert invoice.customer == buyer
    assert invoice.lifecycle_status == "DRAFT"
    assert invoice.payment_status == "UNPAID"
    assert invoice.invoice_number is None
    assert invoice.currency == "EUR"
    assert invoice.document_language == "en"
    assert invoice.subtotal == invoice.tax_total == invoice.grand_total == Decimal("0.00")
    assert invoice.version == 1


def test_create_draft_accepts_explicit_language_and_dates() -> None:
    CompanyProfile.objects.create(legal_name="Seller")
    invoice = create_draft(
        customer=customer(),
        actor=user(UserRole.ADMIN),
        correlation_id="draft-2",
        document_language="de",
        issue_date="2026-09-20",
        due_date="2026-10-20",
    )
    assert invoice.document_language == "de"
    assert invoice.issue_date.isoformat() == "2026-09-20"
    assert invoice.due_date is not None
    assert invoice.due_date.isoformat() == "2026-10-20"


def test_create_draft_requires_company_configuration() -> None:
    with pytest.raises(ValueError, match="company"):
        create_draft(customer=customer(), actor=user(UserRole.ADMIN), correlation_id="missing")
    assert not Invoice.objects.exists()


def test_invoice_database_rejects_invalid_draft_state_and_negative_totals() -> None:
    CompanyProfile.objects.create(legal_name="Seller")
    invoice = create_draft(customer=customer(), actor=user(UserRole.ADMIN), correlation_id="draft")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Invoice.objects.filter(pk=invoice.pk).update(invoice_number="RE-1")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Invoice.objects.filter(pk=invoice.pk).update(grand_total=Decimal("-0.01"))


def test_invoice_api_permissions_and_missing_configuration() -> None:
    buyer = customer()
    client = APIClient()
    reader = user(UserRole.READ_ONLY)
    client.force_authenticate(user=reader)
    assert (
        client.post("/api/v1/invoices/", {"customer_id": buyer.pk}, format="json").status_code
        == 403
    )
    client.force_authenticate(user=user(UserRole.COMPANY_MEMBER))
    missing = client.post("/api/v1/invoices/", {"customer_id": buyer.pk}, format="json")
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "company_configuration_missing"

    CompanyProfile.objects.create(legal_name="Seller")
    created = client.post("/api/v1/invoices/", {"customer_id": buyer.pk}, format="json")
    assert created.status_code == 201
    assert created.json()["invoice_number"] is None
    invoice_id = created.json()["id"]
    client.force_authenticate(user=reader)
    assert client.get(f"/api/v1/invoices/{invoice_id}/").status_code == 200
    assert client.get("/api/v1/invoices/").json()["count"] == 1


def test_invoice_list_paginates_and_filters_customer_status_dates_and_overdue() -> None:
    CompanyProfile.objects.create(legal_name="Seller")
    actor = user(UserRole.ADMIN)
    first = create_draft(
        customer=customer("C-1"), actor=actor, correlation_id="first", due_date="2020-01-01"
    )
    create_draft(
        customer=customer("C-2"), actor=actor, correlation_id="second", due_date="2099-01-01"
    )
    client = APIClient()
    client.force_authenticate(user=actor)
    assert client.get("/api/v1/invoices/?page_size=1").json()["count"] == 2
    for query in (
        f"customer={first.customer_id}",
        "lifecycle_status=DRAFT",
        "payment_status=UNPAID",
        "due_date_before=2020-12-31",
        "overdue=true",
    ):
        result = client.get(f"/api/v1/invoices/?{query}")
        assert result.status_code == 200
        assert first.pk in [row["id"] for row in result.json()["results"]]
    overdue_results = client.get("/api/v1/invoices/?overdue=true").json()
    assert overdue_results["count"] == 1
    assert overdue_results["results"][0]["is_overdue"] is True
    assert client.get("/api/v1/invoices/?overdue=false").json()["results"][0]["is_overdue"] is False

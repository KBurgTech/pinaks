import logging

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.models import AuditEvent
from pinaks.apps.customers.models import (
    BillingRecipient,
    Customer,
    CustomerAddress,
    PartyType,
)
from pinaks.apps.customers.services import create_customer, update_customer

pytestmark = pytest.mark.django_db


def create_user(*, username: str, role: UserRole) -> User:
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="correct horse battery staple",
        role=role,
    )


def person_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "customer_number": "C-0001",
        "party_type": "person",
        "given_name": "Ada",
        "family_name": "Lovelace",
        "organization_name": "",
        "email": "ada@example.test",
        "phone": "+49 30 123456",
        "preferred_language": "en",
        "addresses": [
            {
                "label": "home",
                "address_line_1": "Musterstrasse 1",
                "address_line_2": "",
                "postal_code": "10115",
                "city": "Berlin",
                "country_code": "DE",
                "is_primary": True,
            }
        ],
    }
    data.update(overrides)
    return data


def organization_data(**overrides: object) -> dict[str, object]:
    data = person_data(
        customer_number="C-0002",
        party_type="organization",
        given_name="",
        family_name="",
        organization_name="Analytical Engines GmbH",
        email="billing@example.test",
        preferred_language="de",
    )
    data.update(overrides)
    return data


def recipient_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "party_type": "organization",
        "given_name": "",
        "family_name": "",
        "organization_name": "Alternate Payer GmbH",
        "email": "payer@example.test",
        "phone": "",
        "address_line_1": "Andere Strasse 2",
        "address_line_2": "",
        "postal_code": "20095",
        "city": "Hamburg",
        "country_code": "DE",
    }
    data.update(overrides)
    return data


def test_person_and_organization_customers_have_stable_codes_and_addresses() -> None:
    actor = create_user(username="member", role=UserRole.COMPANY_MEMBER)

    person = create_customer(values=person_data(), actor=actor, correlation_id="person-create")
    organization = create_customer(
        values=organization_data(), actor=actor, correlation_id="organization-create"
    )

    assert [(choice.value, choice.label) for choice in PartyType] == [
        ("person", "Person"),
        ("organization", "Organization"),
    ]
    assert person.display_name == "Ada Lovelace"
    assert organization.display_name == "Analytical Engines GmbH"
    assert person.addresses.get().country_code == "DE"
    assert person.addresses.get().is_primary is True


def test_customer_number_and_address_label_are_database_unique() -> None:
    customer = Customer.objects.create(
        customer_number="C-0001",
        party_type=PartyType.PERSON,
        given_name="Ada",
        family_name="Lovelace",
    )
    CustomerAddress.objects.create(customer=customer, label="home")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Customer.objects.create(
                customer_number="C-0001",
                party_type=PartyType.PERSON,
                given_name="Grace",
                family_name="Hopper",
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CustomerAddress.objects.create(customer=customer, label="home")


def test_billing_recipient_is_owned_by_exactly_one_customer() -> None:
    actor = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    first = create_customer(values=person_data(), actor=actor, correlation_id="first")
    second = create_customer(values=organization_data(), actor=actor, correlation_id="second")
    recipient = BillingRecipient.objects.create(customer=first, **recipient_data())

    assert recipient.customer == first
    assert first.billing_recipients.get() == recipient
    assert not second.billing_recipients.exists()


def test_customer_number_cannot_change_and_archive_preserves_records() -> None:
    actor = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    customer = create_customer(values=person_data(), actor=actor, correlation_id="create")
    recipient = BillingRecipient.objects.create(customer=customer, **recipient_data())

    with pytest.raises(ValueError, match="customer number"):
        update_customer(
            customer=customer,
            values={"customer_number": "C-9999"},
            actor=actor,
            correlation_id="renumber",
        )

    client = APIClient()
    client.force_authenticate(user=actor)
    response = client.delete(f"/api/v1/customers/{customer.pk}/", HTTP_X_REQUEST_ID="archive")

    assert response.status_code == 204
    customer.refresh_from_db()
    assert customer.is_archived is True
    assert CustomerAddress.objects.filter(customer=customer).exists()
    assert BillingRecipient.objects.filter(pk=recipient.pk, customer=customer).exists()
    event = AuditEvent.objects.get(action_code="customers.customer_archived")
    assert event.target_identifier == str(customer.pk)
    assert event.correlation_id == "archive"
    assert event.metadata == {}


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.COMPANY_MEMBER])
def test_authorized_roles_can_create_and_update_customers(role: UserRole) -> None:
    actor = create_user(username=role.value, role=role)
    client = APIClient()
    client.force_authenticate(user=actor)

    created = client.post(
        "/api/v1/customers/",
        person_data(),
        format="json",
        HTTP_X_REQUEST_ID="customer-create",
    )
    updated = client.patch(
        f"/api/v1/customers/{created.json()['id']}/",
        {"phone": "+49 30 654321"},
        format="json",
        HTTP_X_REQUEST_ID="customer-update",
    )

    assert created.status_code == 201
    assert created.json()["display_name"] == "Ada Lovelace"
    assert created.json()["addresses"][0]["label"] == "home"
    assert updated.status_code == 200
    assert updated.json()["phone"] == "+49 30 654321"
    events = list(
        AuditEvent.objects.filter(action_code__startswith="customers.customer_").order_by("pk")
    )
    assert [event.action_code for event in events] == [
        "customers.customer_created",
        "customers.customer_updated",
    ]
    assert events[0].metadata == {
        "changed_fields": sorted(person_data()),
        "party_type": "person",
    }
    assert "ada@example.test" not in str(events[0].metadata)


def test_read_only_can_view_but_cannot_mutate_customers() -> None:
    member = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    reader = create_user(username="reader", role=UserRole.READ_ONLY)
    customer = create_customer(values=person_data(), actor=member, correlation_id="create")
    client = APIClient()
    client.force_authenticate(user=reader)

    assert client.get("/api/v1/customers/").status_code == 200
    assert client.get(f"/api/v1/customers/{customer.pk}/").status_code == 200
    assert client.post("/api/v1/customers/", person_data(), format="json").status_code == 403
    assert (
        client.patch(
            f"/api/v1/customers/{customer.pk}/", {"phone": "new"}, format="json"
        ).status_code
        == 403
    )
    assert client.delete(f"/api/v1/customers/{customer.pk}/").status_code == 403


def test_customer_list_is_paginated_filterable_and_excludes_archived_by_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    actor = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    client = APIClient()
    client.force_authenticate(user=actor)
    first = create_customer(values=person_data(), actor=actor, correlation_id="first")
    create_customer(values=organization_data(), actor=actor, correlation_id="second")
    Customer.objects.filter(pk=first.pk).update(is_archived=True)

    caplog.set_level(logging.DEBUG)
    response = client.get("/api/v1/customers/?search=Analytical&page_size=1")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert [item["customer_number"] for item in response.json()["results"]] == ["C-0002"]
    assert "Analytical" not in caplog.text
    assert client.get("/api/v1/customers/?archived=true").json()["count"] == 1


def test_billing_recipient_crud_enforces_customer_ownership_and_permissions() -> None:
    member = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    reader = create_user(username="reader", role=UserRole.READ_ONLY)
    first = create_customer(values=person_data(), actor=member, correlation_id="first")
    second = create_customer(values=organization_data(), actor=member, correlation_id="second")
    client = APIClient()
    client.force_authenticate(user=member)

    created = client.post(
        f"/api/v1/customers/{first.pk}/billing-recipients/",
        recipient_data(),
        format="json",
    )
    recipient_id = created.json()["id"]
    updated = client.patch(
        f"/api/v1/customers/{first.pk}/billing-recipients/{recipient_id}/",
        {"organization_name": "Updated Payer GmbH"},
        format="json",
    )

    assert created.status_code == 201
    assert created.json()["customer_id"] == first.pk
    assert updated.status_code == 200
    assert updated.json()["organization_name"] == "Updated Payer GmbH"
    assert (
        client.get(f"/api/v1/customers/{second.pk}/billing-recipients/{recipient_id}/").status_code
        == 404
    )

    client.force_authenticate(user=reader)
    assert client.get(f"/api/v1/customers/{first.pk}/billing-recipients/").status_code == 200
    assert (
        client.post(
            f"/api/v1/customers/{first.pk}/billing-recipients/",
            recipient_data(),
            format="json",
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "payload",
    [
        person_data(given_name=""),
        organization_data(organization_name=""),
        person_data(preferred_language="fr"),
        person_data(addresses=[]),
    ],
)
def test_customer_api_rejects_invalid_party_language_and_address_data(
    payload: dict[str, object],
) -> None:
    actor = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    client = APIClient()
    client.force_authenticate(user=actor)

    response = client.post("/api/v1/customers/", payload, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert not Customer.objects.exists()

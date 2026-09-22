from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.models import AuditEvent
from pinaks.apps.catalog.models import CatalogItem, UnitCode
from pinaks.apps.catalog.services import create_catalog_item, update_catalog_item
from pinaks.apps.configuration.models import (
    PriceEntryPolicy,
    TaxCategory,
    TaxColumnPolicy,
    TaxProfile,
)

pytestmark = pytest.mark.django_db


def create_user(*, username: str, role: UserRole) -> User:
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="correct horse battery staple",
        role=role,
    )


def create_tax_profile(*, code: str = "standard-19", current: bool = True) -> TaxProfile:
    return TaxProfile.objects.create(
        code=code,
        name="Standard 19%",
        tax_category=TaxCategory.STANDARD,
        rate=Decimal("19.00"),
        price_entry_policy=PriceEntryPolicy.NET,
        tax_column_policy=TaxColumnPolicy.SHOW,
        requires_tax_number=True,
        is_current=current,
    )


def item_data(tax_profile: TaxProfile, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "code": "CONSULTING",
        "description_en": "Consulting hour",
        "description_de": "Beratungsstunde",
        "unit": "HUR",
        "default_price": "120.00",
        "minimum_price": "90.00",
        "maximum_price": "180.00",
        "default_tax_profile_id": tax_profile.pk,
    }
    data.update(overrides)
    return data


def test_catalog_code_is_unique_and_database_price_constraints_hold() -> None:
    tax_profile = create_tax_profile()
    CatalogItem.objects.create(
        code="CONSULTING",
        description_en="Consulting hour",
        description_de="Beratungsstunde",
        unit=UnitCode.HOUR,
        default_price=Decimal("120.00"),
        minimum_price=Decimal("90.00"),
        maximum_price=Decimal("180.00"),
        default_tax_profile=tax_profile,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CatalogItem.objects.create(
                code="CONSULTING",
                description_en="Other",
                description_de="Andere",
                unit=UnitCode.PIECE,
                default_price=Decimal("1.00"),
                default_tax_profile=tax_profile,
            )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CatalogItem.objects.create(
                code="INVALID-PRICE",
                description_en="Invalid",
                description_de="Ungültig",
                unit=UnitCode.PIECE,
                default_price=Decimal("80.00"),
                minimum_price=Decimal("90.00"),
                maximum_price=Decimal("180.00"),
                default_tax_profile=tax_profile,
            )


def test_database_rejects_incomplete_localization_and_unsupported_units() -> None:
    tax_profile = create_tax_profile()
    values = {
        "code": "INVALID",
        "description_en": "Description",
        "description_de": "Beschreibung",
        "unit": UnitCode.PIECE,
        "default_price": Decimal("10.00"),
        "default_tax_profile": tax_profile,
    }

    for invalid_values in (
        {**values, "description_en": ""},
        {**values, "description_de": ""},
        {**values, "unit": "BAD"},
    ):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CatalogItem.objects.create(**invalid_values)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"description_en": ""}, "description_en"),
        ({"description_de": ""}, "description_de"),
        ({"unit": "INVALID"}, "unit"),
        ({"default_price": "12.345"}, "default_price"),
        ({"minimum_price": "130.00"}, "minimum_price"),
        ({"maximum_price": "100.00"}, "maximum_price"),
    ],
)
def test_catalog_service_validates_localization_units_precision_and_advisory_prices(
    overrides: dict[str, object], field: str
) -> None:
    actor = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    tax_profile = create_tax_profile()

    with pytest.raises(ValidationError) as exc_info:
        create_catalog_item(
            values=item_data(tax_profile, **overrides),
            actor=actor,
            correlation_id="invalid-create",
        )

    assert field in exc_info.value.message_dict
    assert not CatalogItem.objects.exists()


def test_catalog_service_requires_a_current_supported_tax_profile() -> None:
    actor = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    old_profile = create_tax_profile(current=False)

    with pytest.raises(ValidationError) as exc_info:
        create_catalog_item(
            values=item_data(old_profile), actor=actor, correlation_id="old-tax-profile"
        )

    assert "default_tax_profile_id" in exc_info.value.message_dict


def test_catalog_code_is_immutable_and_mutations_are_audited_without_descriptions() -> None:
    actor = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    tax_profile = create_tax_profile()
    item = create_catalog_item(
        values=item_data(tax_profile), actor=actor, correlation_id="catalog-create"
    )

    with pytest.raises(ValueError, match="catalog code"):
        update_catalog_item(
            item=item,
            values={"code": "RENAMED"},
            actor=actor,
            correlation_id="catalog-update",
        )

    event = AuditEvent.objects.get(action_code="catalog.item_created")
    assert event.correlation_id == "catalog-create"
    assert event.metadata == {
        "changed_fields": sorted(item_data(tax_profile)),
        "code": "CONSULTING",
    }
    assert "Consulting hour" not in str(event.metadata)


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.COMPANY_MEMBER])
def test_authorized_roles_can_create_and_update_catalog_items(role: UserRole) -> None:
    actor = create_user(username=role.value, role=role)
    tax_profile = create_tax_profile()
    client = APIClient()
    client.force_authenticate(user=actor)

    created = client.post("/api/v1/catalog/", item_data(tax_profile), format="json")
    updated = client.patch(
        f"/api/v1/catalog/{created.json()['id']}/",
        {"default_price": "125.50"},
        format="json",
    )

    assert created.status_code == 201
    assert created.json()["default_price"] == "120.00"
    assert created.json()["default_tax_profile"]["code"] == "standard-19"
    assert updated.status_code == 200
    assert updated.json()["default_price"] == "125.50"


def test_read_only_can_view_but_cannot_mutate_catalog_items() -> None:
    member = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    reader = create_user(username="reader", role=UserRole.READ_ONLY)
    tax_profile = create_tax_profile()
    item = create_catalog_item(values=item_data(tax_profile), actor=member, correlation_id="create")
    client = APIClient()
    client.force_authenticate(user=reader)

    assert client.get("/api/v1/catalog/").status_code == 200
    assert client.get(f"/api/v1/catalog/{item.pk}/").status_code == 200
    assert client.post("/api/v1/catalog/", item_data(tax_profile), format="json").status_code == 403
    assert (
        client.patch(
            f"/api/v1/catalog/{item.pk}/", {"default_price": "10.00"}, format="json"
        ).status_code
        == 403
    )
    assert client.delete(f"/api/v1/catalog/{item.pk}/").status_code == 403


def test_catalog_list_is_paginated_searchable_and_excludes_archived_items() -> None:
    actor = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    tax_profile = create_tax_profile()
    archived = create_catalog_item(
        values=item_data(tax_profile), actor=actor, correlation_id="first"
    )
    create_catalog_item(
        values=item_data(
            tax_profile,
            code="BOOKKEEPING",
            description_en="Bookkeeping package",
            description_de="Buchhaltungspaket",
        ),
        actor=actor,
        correlation_id="second",
    )
    CatalogItem.objects.filter(pk=archived.pk).update(is_archived=True)
    client = APIClient()
    client.force_authenticate(user=actor)

    response = client.get("/api/v1/catalog/?search=Buchhaltung&page_size=1")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert [item["code"] for item in response.json()["results"]] == ["BOOKKEEPING"]
    assert client.get("/api/v1/catalog/").json()["count"] == 1
    assert client.get("/api/v1/catalog/?archived=true").json()["count"] == 1


def test_archiving_preserves_direct_retrieval_but_removes_item_from_new_selection() -> None:
    actor = create_user(username="member", role=UserRole.COMPANY_MEMBER)
    tax_profile = create_tax_profile()
    item = create_catalog_item(values=item_data(tax_profile), actor=actor, correlation_id="create")
    client = APIClient()
    client.force_authenticate(user=actor)

    response = client.delete(f"/api/v1/catalog/{item.pk}/", HTTP_X_REQUEST_ID="catalog-archive")

    assert response.status_code == 204
    assert client.get(f"/api/v1/catalog/{item.pk}/").json()["is_archived"] is True
    assert client.get("/api/v1/catalog/").json()["count"] == 0
    assert CatalogItem.objects.filter(pk=item.pk).exists()
    event = AuditEvent.objects.get(action_code="catalog.item_archived")
    assert event.correlation_id == "catalog-archive"

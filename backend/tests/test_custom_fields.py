from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.models import AuditEvent
from pinaks.apps.custom_fields.models import CustomFieldDefinition
from pinaks.apps.custom_fields.services import publish_definition, validate_custom_data

pytestmark = pytest.mark.django_db


def actor(role: UserRole = UserRole.ADMIN) -> User:
    return User.objects.create_user(username=role.value, password="test", role=role)


def definition(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "key": "reference",
        "target": "customer",
        "data_type": "text",
        "label_en": "Reference",
        "label_de": "Referenz",
        "help_en": "Customer reference",
        "help_de": "Kundenreferenz",
        "required": False,
        "search_mode": "exact",
        "visibility": "internal",
        "is_sensitive": False,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("data_type", "valid", "invalid"),
    [
        ("text", "short", 2),
        ("long_text", "long", 2),
        ("integer", 2, True),
        ("decimal", "2.75", "NaN"),
        ("boolean", True, "true"),
        ("date", "2026-09-22", "2026-02-30"),
        ("choice", "one", "other"),
    ],
)
def test_validate_each_type(data_type: str, valid: object, invalid: object) -> None:
    values = definition(data_type=data_type, search_mode="none")
    if data_type == "choice":
        values["choices"] = [{"code": "one", "label_en": "One", "label_de": "Eins"}]
    publish_definition(values=values, actor=actor(), correlation_id="create")

    assert validate_custom_data(target="customer", values={"reference": valid})
    with pytest.raises(ValidationError):
        validate_custom_data(target="customer", values={"reference": invalid})


def test_required_defaults_immutable_key_and_retirement() -> None:
    admin = actor()
    field = publish_definition(
        values=definition(required=True, default_value="auto"), actor=admin, correlation_id="add"
    )
    assert validate_custom_data(target="customer", values={}) == {"reference": "auto"}
    assert AuditEvent.objects.get(action_code="custom_fields.definition_published").metadata == {
        "key": "reference",
        "target": "customer",
    }

    client = APIClient()
    client.force_authenticate(user=admin)
    assert (
        client.patch(
            f"/api/v1/custom-fields/{field.pk}/", {"key": "changed"}, format="json"
        ).status_code
        == 409
    )
    assert client.delete(f"/api/v1/custom-fields/{field.pk}/").status_code == 204
    assert CustomFieldDefinition.objects.get(pk=field.pk).is_retired
    assert validate_custom_data(
        target="customer", values={}, existing={"reference": "retained"}
    ) == {"reference": "retained"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"target": "unknown"},
        {"data_type": "script"},
        {"label_de": ""},
        {"search_mode": "range", "data_type": "text"},
        {"search_mode": "exact", "is_sensitive": True},
        {"data_type": "choice", "choices": [{"code": "one", "label_en": "One"}]},
        {"default_value": "bad", "data_type": "integer"},
    ],
)
def test_reject_invalid_definitions(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        publish_definition(values=definition(**overrides), actor=actor(), correlation_id="bad")


def test_definition_permissions_and_sensitive_redaction() -> None:
    admin = actor()
    reader = actor(UserRole.READ_ONLY)
    publish_definition(
        values=definition(key="diagnosis", is_sensitive=True, search_mode="none"),
        actor=admin,
        correlation_id="sensitive",
    )
    client = APIClient()
    client.force_authenticate(user=reader)
    assert client.get("/api/v1/custom-fields/?target=customer").status_code == 200
    assert client.post("/api/v1/custom-fields/", definition(), format="json").status_code == 403
    assert validate_custom_data(target="customer", values={"diagnosis": "private"}) == {
        "diagnosis": "private"
    }


def test_decimal_value_is_json_safe_and_exact() -> None:
    publish_definition(
        values=definition(data_type="decimal", search_mode="range"),
        actor=actor(),
        correlation_id="decimal",
    )
    assert validate_custom_data(target="customer", values={"reference": "2.75"}) == {
        "reference": "2.75"
    }
    assert validate_custom_data(target="customer", values={"reference": "2.75"})[
        "reference"
    ] == str(Decimal("2.75"))


def test_customer_and_catalog_api_validate_custom_data_and_redact_sensitive_values() -> None:
    from pinaks.apps.catalog.models import CatalogItem
    from pinaks.apps.configuration.models import (
        PriceEntryPolicy,
        TaxCategory,
        TaxColumnPolicy,
        TaxProfile,
    )
    from pinaks.apps.customers.models import Customer

    admin = actor()
    publish_definition(values=definition(), actor=admin, correlation_id="customer-field")
    publish_definition(
        values=definition(key="private_note", is_sensitive=True, search_mode="none"),
        actor=admin,
        correlation_id="private-field",
    )
    publish_definition(
        values=definition(
            key="category",
            target="catalog_item",
            data_type="choice",
            choices=[{"code": "service", "label_en": "Service", "label_de": "Dienstleistung"}],
        ),
        actor=admin,
        correlation_id="catalog-field",
    )
    tax = TaxProfile.objects.create(
        code="standard-19",
        name="Standard 19%",
        tax_category=TaxCategory.STANDARD,
        rate=Decimal("19.00"),
        price_entry_policy=PriceEntryPolicy.NET,
        tax_column_policy=TaxColumnPolicy.SHOW,
        requires_tax_number=True,
        is_current=True,
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    customer = client.post(
        "/api/v1/customers/",
        {
            "customer_number": "C-1",
            "party_type": "person",
            "given_name": "Ada",
            "family_name": "Lovelace",
            "organization_name": "",
            "email": "",
            "phone": "",
            "preferred_language": "en",
            "addresses": [
                {
                    "label": "primary",
                    "address_line_1": "",
                    "address_line_2": "",
                    "postal_code": "",
                    "city": "",
                    "country_code": "DE",
                    "is_primary": True,
                }
            ],
            "custom_data": {"reference": "A-1", "private_note": "secret-diagnosis"},
        },
        format="json",
    )
    assert customer.status_code == 201, customer.json()
    assert customer.json()["custom_data"] == {"reference": "A-1"}
    assert "secret-diagnosis" not in str(client.get("/api/v1/customers/").json())
    assert (
        Customer.objects.get(pk=customer.json()["id"]).custom_data["private_note"]
        == "secret-diagnosis"
    )
    assert "secret-diagnosis" not in str(AuditEvent.objects.values_list("metadata", flat=True))
    invalid = client.patch(
        f"/api/v1/customers/{customer.json()['id']}/",
        {"custom_data": {"unknown": "x"}},
        format="json",
    )
    assert invalid.status_code == 400
    catalog = client.post(
        "/api/v1/catalog/",
        {
            "code": "CONSULTING",
            "description_en": "Consulting",
            "description_de": "Beratung",
            "unit": "HUR",
            "default_price": "100.00",
            "default_tax_profile_id": tax.pk,
            "custom_data": {"category": "service"},
        },
        format="json",
    )
    assert catalog.status_code == 201, catalog.json()
    assert catalog.json()["custom_data"] == {"category": "service"}
    assert CatalogItem.objects.get(pk=catalog.json()["id"]).custom_data == {"category": "service"}


def test_typed_filters_find_values_without_exposing_sensitive_fields() -> None:
    from pinaks.apps.custom_fields.services import filter_custom_data
    from pinaks.apps.customers.models import Customer

    admin = actor()
    publish_definition(values=definition(), actor=admin, correlation_id="exact")
    publish_definition(
        values=definition(key="visits", data_type="integer", search_mode="range"),
        actor=admin,
        correlation_id="range",
    )
    for number, visits in (("C-1", 2), ("C-2", 5)):
        Customer.objects.create(
            customer_number=number,
            party_type="person",
            given_name="Ada",
            family_name="Lovelace",
            custom_data={"reference": number, "visits": visits},
        )
    assert list(
        filter_custom_data(
            Customer.objects.all(),
            target="customer",
            key="reference",
            operator="exact",
            value="C-1",
        ).values_list("customer_number", flat=True)
    ) == ["C-1"]
    assert list(
        filter_custom_data(
            Customer.objects.all(), target="customer", key="visits", operator="gte", value="3"
        ).values_list("customer_number", flat=True)
    ) == ["C-2"]
    with pytest.raises(ValidationError):
        filter_custom_data(
            Customer.objects.all(), target="customer", key="visits", operator="text", value="3"
        )


def test_customer_api_filter_and_sensitive_reveal_are_authorized_and_audited() -> None:
    from pinaks.apps.customers.models import Customer

    admin = actor()
    reader = actor(UserRole.READ_ONLY)
    publish_definition(values=definition(), actor=admin, correlation_id="exact")
    publish_definition(
        values=definition(key="private_note", is_sensitive=True, search_mode="none"),
        actor=admin,
        correlation_id="secret",
    )
    customer = Customer.objects.create(
        customer_number="C-1",
        party_type="person",
        given_name="Ada",
        family_name="Lovelace",
        custom_data={"reference": "R-1", "private_note": "private-value"},
    )
    client = APIClient()
    client.force_authenticate(user=reader)
    found = client.get(
        "/api/v1/customers/?custom_field=reference&custom_operator=exact&custom_value=R-1"
    )
    assert found.status_code == 200
    assert found.json()["count"] == 1
    assert (
        client.get(
            "/api/v1/customers/?custom_field=private_note&custom_operator=exact&custom_value=private-value"
        ).status_code
        == 400
    )
    assert client.get(f"/api/v1/customers/{customer.pk}/sensitive-fields/").status_code == 403
    client.force_authenticate(user=admin)
    reveal = client.get(f"/api/v1/customers/{customer.pk}/sensitive-fields/")
    assert reveal.status_code == 200
    assert reveal.json() == {"private_note": "private-value"}
    assert AuditEvent.objects.filter(action_code="custom_fields.sensitive_accessed").count() == 1
    assert "private-value" not in str(
        AuditEvent.objects.filter(action_code="custom_fields.sensitive_accessed").values_list(
            "metadata", flat=True
        )
    )


def test_published_choice_codes_cannot_be_removed() -> None:
    from pinaks.apps.custom_fields.services import update_definition

    admin = actor()
    field = publish_definition(
        values=definition(
            data_type="choice",
            search_mode="exact",
            choices=[{"code": "one", "label_en": "One", "label_de": "Eins"}],
        ),
        actor=admin,
        correlation_id="choice",
    )
    with pytest.raises(ValidationError):
        update_definition(
            field=field,
            values={"choices": [{"code": "two", "label_en": "Two", "label_de": "Zwei"}]},
            actor=admin,
            correlation_id="change",
        )


def test_exact_boolean_filter_accepts_query_parameter_strings() -> None:
    from pinaks.apps.custom_fields.services import filter_custom_data
    from pinaks.apps.customers.models import Customer

    publish_definition(
        values=definition(key="insured", data_type="boolean", search_mode="exact"),
        actor=actor(),
        correlation_id="boolean",
    )
    Customer.objects.create(
        customer_number="C-1",
        party_type="person",
        given_name="Ada",
        family_name="Lovelace",
        custom_data={"insured": True},
    )
    result = filter_custom_data(
        Customer.objects.all(), target="customer", key="insured", operator="exact", value="true"
    )
    assert list(result.values_list("customer_number", flat=True)) == ["C-1"]


def test_published_sensitive_field_cannot_be_made_public() -> None:
    from pinaks.apps.custom_fields.services import update_definition

    admin = actor()
    field = publish_definition(
        values=definition(key="private_note", is_sensitive=True, search_mode="none"),
        actor=admin,
        correlation_id="private",
    )
    with pytest.raises(ValidationError):
        update_definition(
            field=field, values={"is_sensitive": False}, actor=admin, correlation_id="expose"
        )

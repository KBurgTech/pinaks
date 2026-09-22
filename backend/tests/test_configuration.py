from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.models import AuditEvent
from pinaks.apps.configuration.models import (
    CompanyProfile,
    DocumentLanguage,
    InvoiceNumberReset,
    PriceEntryPolicy,
    SellerTaxIdentifier,
    TaxCategory,
    TaxColumnPolicy,
    TaxProfile,
)
from pinaks.apps.configuration.services import mark_tax_profile_used, save_tax_profile

pytestmark = pytest.mark.django_db


def create_user(*, username: str, role: UserRole) -> User:
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="correct horse battery staple",
        role=role,
    )


def valid_profile_data() -> dict[str, object]:
    return {
        "legal_name": "Beispiel GmbH",
        "address_line_1": "Musterstrasse 1",
        "address_line_2": "",
        "postal_code": "10115",
        "city": "Berlin",
        "country_code": "DE",
        "email": "rechnung@example.test",
        "phone": "+49 30 123456",
        "tax_number": "12/345/67890",
        "vat_identifier": "DE123456789",
        "company_identifier": "HRB 12345",
        "bank_account_holder": "Beispiel GmbH",
        "iban": "DE89370400440532013000",
        "bic": "COBADEFFXXX",
        "payment_instructions": "Bitte innerhalb von 14 Tagen zahlen.",
        "default_currency": "EUR",
        "default_locale": "de-DE",
        "default_ui_language": "de",
        "default_document_language": "de",
        "invoice_number_prefix": "RE-",
        "invoice_number_next": 1000,
        "invoice_number_padding": 6,
        "invoice_number_reset": "annual",
        "features": {
            "payment_requests": True,
            "reminders": False,
            "time_tracking": True,
        },
    }


def valid_tax_profile_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "code": "standard-19",
        "name": "Standard VAT 19%",
        "tax_category": "S",
        "rate": "19.00",
        "exemption_reason_code": "",
        "exemption_wording_en": "",
        "exemption_wording_de": "",
        "price_entry_policy": "net",
        "tax_column_policy": "show",
        "required_seller_identifiers": ["tax_number"],
        "is_default": True,
    }
    data.update(overrides)
    return data


def test_company_profile_is_a_database_enforced_singleton() -> None:
    first = CompanyProfile.objects.create(legal_name="First company")

    assert first.pk == CompanyProfile.SINGLETON_PK
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CompanyProfile.objects.create(legal_name="Second company")


def test_numbering_and_language_policy_uses_stable_codes_and_validates_bounds() -> None:
    assert [value for value, _label in InvoiceNumberReset.choices] == ["never", "annual"]
    assert [value for value, _label in DocumentLanguage.choices] == ["en", "de"]

    profile = CompanyProfile(
        legal_name="Example",
        invoice_number_next=0,
        invoice_number_padding=13,
        invoice_number_reset="monthly",
    )

    with pytest.raises(ValidationError) as error:
        profile.full_clean()

    assert set(error.value.message_dict) >= {
        "invoice_number_next",
        "invoice_number_padding",
        "invoice_number_reset",
    }


@pytest.mark.parametrize("role", [UserRole.COMPANY_MEMBER, UserRole.READ_ONLY])
def test_company_configuration_is_admin_only(role: UserRole) -> None:
    user = create_user(username=role.value, role=role)
    client = APIClient()
    client.force_authenticate(user=user)

    assert client.get("/api/v1/configuration/company/").status_code == 403
    assert (
        client.patch(
            "/api/v1/configuration/company/", valid_profile_data(), format="json"
        ).status_code
        == 403
    )


def test_admin_can_create_read_and_update_company_configuration() -> None:
    administrator = create_user(username="administrator", role=UserRole.ADMIN)
    client = APIClient()
    client.force_authenticate(user=administrator)

    missing = client.get("/api/v1/configuration/company/")
    created = client.put(
        "/api/v1/configuration/company/",
        valid_profile_data(),
        format="json",
        HTTP_X_REQUEST_ID="configuration-create",
    )
    fetched = client.get("/api/v1/configuration/company/")
    updated = client.patch(
        "/api/v1/configuration/company/",
        {"invoice_number_padding": 8, "features": {"reminders": True}},
        format="json",
        HTTP_X_REQUEST_ID="configuration-update",
    )

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert created.status_code == 201
    assert created.json() == valid_profile_data()
    assert fetched.json() == valid_profile_data()
    assert updated.status_code == 200
    assert updated.json()["invoice_number_padding"] == 8
    assert updated.json()["features"] == {
        "payment_requests": True,
        "reminders": True,
        "time_tracking": True,
    }

    events = list(AuditEvent.objects.filter(action_code="configuration.company_changed"))
    assert len(events) == 2
    assert events[0].actor == administrator
    assert events[0].correlation_id == "configuration-create"
    assert events[0].metadata == {"changed_fields": sorted(valid_profile_data())}
    assert events[1].metadata == {"changed_fields": ["features", "invoice_number_padding"]}


@pytest.mark.parametrize(
    "secret_field",
    ["smtp_password", "oidc_client_secret", "api_token"],
)
def test_secret_shaped_configuration_is_rejected_and_not_audited(secret_field: str) -> None:
    administrator = create_user(username="administrator", role=UserRole.ADMIN)
    client = APIClient()
    client.force_authenticate(user=administrator)
    payload = valid_profile_data()
    payload[secret_field] = "must-not-be-stored-or-logged"

    response = client.put("/api/v1/configuration/company/", payload, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["fields"][secret_field][0]["code"] == "unknown_field"
    assert not CompanyProfile.objects.exists()
    assert not AuditEvent.objects.filter(action_code="configuration.company_changed").exists()
    assert "must-not-be-stored-or-logged" not in str(AuditEvent.objects.all().values())


def test_secret_shaped_feature_configuration_is_rejected() -> None:
    administrator = create_user(username="administrator", role=UserRole.ADMIN)
    client = APIClient()
    client.force_authenticate(user=administrator)
    payload = valid_profile_data()
    features = payload["features"]
    assert isinstance(features, dict)
    features["provider_secret"] = "must-not-be-stored-or-logged"

    response = client.put("/api/v1/configuration/company/", payload, format="json")

    assert response.status_code == 400
    assert (
        response.json()["error"]["fields"]["features"]["provider_secret"][0]["code"]
        == "unknown_field"
    )
    assert not CompanyProfile.objects.exists()
    assert not AuditEvent.objects.filter(action_code="configuration.company_changed").exists()


def test_capabilities_return_persisted_installation_feature_flags() -> None:
    CompanyProfile.objects.create(
        legal_name="Example",
        feature_payment_requests=True,
        feature_reminders=False,
        feature_time_tracking=True,
    )
    user = create_user(username="reader", role=UserRole.READ_ONLY)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/capabilities/")

    assert response.status_code == 200
    assert response.json()["features"] == {
        "payment_requests": True,
        "reminders": False,
        "time_tracking": True,
    }


@pytest.mark.parametrize(
    ("values", "expected_category", "expected_rate"),
    [
        (valid_tax_profile_data(), TaxCategory.STANDARD, "19.00"),
        (
            valid_tax_profile_data(
                code="medical-exempt",
                tax_category="E",
                rate="0.00",
                exemption_reason_code="VATEX-EU-132",
                exemption_wording_en="Tax exempt medical care",
                exemption_wording_de="Steuerfreie Heilbehandlung",
                tax_column_policy="hide",
            ),
            TaxCategory.EXEMPT,
            "0.00",
        ),
    ],
)
def test_supported_german_tax_profiles_preserve_decimal_rates(
    values: dict[str, object], expected_category: TaxCategory, expected_rate: str
) -> None:
    profile = TaxProfile.from_values(values)

    profile.full_clean()
    profile.save()
    profile.refresh_from_db()

    assert profile.tax_category == expected_category
    assert str(profile.rate) == expected_rate


@pytest.mark.parametrize(
    ("overrides", "invalid_fields"),
    [
        ({"tax_category": "S", "rate": "0.00"}, {"rate"}),
        (
            {"tax_category": "S", "exemption_reason_code": "VATEX-EU-132"},
            {"exemption_reason_code"},
        ),
        (
            {
                "tax_category": "E",
                "rate": "7.00",
                "exemption_reason_code": "VATEX-EU-132",
                "exemption_wording_en": "Exempt",
                "exemption_wording_de": "Steuerfrei",
            },
            {"rate"},
        ),
        (
            {
                "tax_category": "E",
                "rate": "0.00",
                "exemption_reason_code": "",
                "exemption_wording_en": "",
                "exemption_wording_de": "",
            },
            {"exemption_reason_code", "exemption_wording_en", "exemption_wording_de"},
        ),
    ],
)
def test_inconsistent_tax_combinations_are_rejected(
    overrides: dict[str, object], invalid_fields: set[str]
) -> None:
    profile = TaxProfile.from_values(valid_tax_profile_data(**overrides))

    with pytest.raises(ValidationError) as error:
        profile.full_clean()

    assert set(error.value.message_dict) >= invalid_fields


def test_tax_profile_uses_stable_policy_codes_and_rate_precision() -> None:
    assert [value for value, _label in TaxCategory.choices] == ["S", "E"]
    assert [value for value, _label in PriceEntryPolicy.choices] == ["net", "gross"]
    assert [value for value, _label in TaxColumnPolicy.choices] == ["show", "hide"]
    assert [value for value, _label in SellerTaxIdentifier.choices] == [
        "tax_number",
        "vat_identifier",
    ]

    too_precise = TaxProfile.from_values(valid_tax_profile_data(rate="19.001"))
    with pytest.raises(ValidationError) as error:
        too_precise.full_clean()
    assert "rate" in error.value.message_dict


def test_database_allows_only_one_current_default_tax_profile() -> None:
    first = TaxProfile.from_values(valid_tax_profile_data(code="first"))
    first.full_clean()
    first.save()
    second = TaxProfile.from_values(valid_tax_profile_data(code="second"))

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            second.save()


def test_editing_used_tax_profile_creates_new_version_and_preserves_old_semantics() -> None:
    CompanyProfile.objects.create(legal_name="Example", tax_number="12/345/67890")
    administrator = create_user(username="administrator", role=UserRole.ADMIN)
    original, created = save_tax_profile(
        values=valid_tax_profile_data(),
        actor=administrator,
        correlation_id="tax-create",
    )
    mark_tax_profile_used(original)

    replacement, replacement_created = save_tax_profile(
        profile=original,
        values={"rate": "7.00", "name": "Reduced VAT 7%"},
        actor=administrator,
        correlation_id="tax-update",
    )

    original.refresh_from_db()
    assert created is True
    assert replacement_created is True
    assert replacement.pk != original.pk
    assert replacement.code == original.code
    assert replacement.version == 2
    assert str(original.rate) == "19.00"
    assert original.is_current is False
    assert replacement.is_current is True
    assert replacement.is_default is True


def test_default_tax_profile_requires_configured_seller_identifiers() -> None:
    CompanyProfile.objects.create(legal_name="Example", tax_number="")
    administrator = create_user(username="administrator", role=UserRole.ADMIN)

    with pytest.raises(ValidationError) as error:
        save_tax_profile(
            values=valid_tax_profile_data(required_seller_identifiers=["tax_number"]),
            actor=administrator,
            correlation_id="tax-create",
        )

    assert "required_seller_identifiers" in error.value.message_dict


def test_used_tax_profile_semantics_cannot_be_mutated_in_place() -> None:
    profile = TaxProfile.from_values(valid_tax_profile_data(is_default=False))
    profile.full_clean()
    profile.save()
    mark_tax_profile_used(profile)

    profile.rate = Decimal("7.00")
    with pytest.raises(ValidationError):
        profile.save()


@pytest.mark.parametrize("role", [UserRole.COMPANY_MEMBER, UserRole.READ_ONLY])
def test_tax_profile_configuration_is_admin_only(role: UserRole) -> None:
    user = create_user(username=f"tax-{role.value}", role=role)
    client = APIClient()
    client.force_authenticate(user=user)

    assert client.get("/api/v1/configuration/tax-profiles/").status_code == 403
    assert (
        client.post(
            "/api/v1/configuration/tax-profiles/", valid_tax_profile_data(), format="json"
        ).status_code
        == 403
    )


def test_admin_can_create_list_and_version_tax_profiles() -> None:
    CompanyProfile.objects.create(legal_name="Example", tax_number="12/345/67890")
    administrator = create_user(username="administrator", role=UserRole.ADMIN)
    client = APIClient()
    client.force_authenticate(user=administrator)

    created = client.post(
        "/api/v1/configuration/tax-profiles/",
        valid_tax_profile_data(),
        format="json",
        HTTP_X_REQUEST_ID="tax-create",
    )
    profile_id = created.json()["id"]
    profile = TaxProfile.objects.get(pk=profile_id)
    mark_tax_profile_used(profile)
    updated = client.patch(
        f"/api/v1/configuration/tax-profiles/{profile_id}/",
        {"rate": "7.00", "name": "Reduced VAT 7%"},
        format="json",
        HTTP_X_REQUEST_ID="tax-update",
    )
    listed = client.get("/api/v1/configuration/tax-profiles/")

    assert created.status_code == 201
    assert created.json()["version"] == 1
    assert created.json()["rate"] == "19.00"
    assert created.json()["translation_complete"] is True
    assert updated.status_code == 201
    assert updated.json()["id"] != profile_id
    assert updated.json()["version"] == 2
    assert listed.status_code == 200
    assert [item["version"] for item in listed.json()] == [2]
    assert AuditEvent.objects.filter(action_code="configuration.tax_profile_changed").count() == 2

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
)

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

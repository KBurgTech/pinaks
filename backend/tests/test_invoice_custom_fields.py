import pytest
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.audit.models import AuditEvent
from pinaks.apps.billing.models import Invoice, InvoiceLine
from pinaks.apps.billing.services import create_draft
from pinaks.apps.configuration.models import CompanyProfile
from pinaks.apps.custom_fields.models import CustomFieldDefinition
from pinaks.apps.custom_fields.services import publish_definition, retire_definition
from pinaks.apps.customers.models import Customer

pytestmark = pytest.mark.django_db


def setup_invoice() -> tuple[APIClient, Invoice, User]:
    admin = User.objects.create_user(username="admin", password="test", role=UserRole.ADMIN)
    CompanyProfile.objects.create(legal_name="Seller")
    customer = Customer.objects.create(
        customer_number="C-1", party_type="person", given_name="Ada", family_name="Lovelace"
    )
    invoice = create_draft(customer=customer, actor=admin, correlation_id="test")
    client = APIClient()
    client.force_authenticate(user=admin)
    return client, invoice, admin


def field(admin: User, *, target: str, key: str, **changes: object) -> CustomFieldDefinition:
    values: dict[str, object] = {
        "target": target,
        "key": key,
        "data_type": "text",
        "label_en": key,
        "label_de": key,
        "search_mode": "exact",
    }
    values.update(changes)
    return publish_definition(values=values, actor=admin, correlation_id="test")


def test_invoice_values_are_validated_and_retired_values_remain_editable() -> None:
    client, invoice, admin = setup_invoice()
    definition = field(admin, target="invoice", key="reference", required=True)
    url = f"/api/v1/invoices/{invoice.pk}/"
    bad = client.patch(url, {"expected_version": 1, "custom_data": {"other": "x"}}, format="json")
    assert bad.status_code == 400
    assert Invoice.objects.get(pk=invoice.pk).version == 1
    saved = client.patch(
        url, {"expected_version": 1, "custom_data": {"reference": "A-1"}}, format="json"
    )
    assert saved.status_code == 200, saved.json()
    assert saved.json()["custom_data"] == {"reference": "A-1"}
    retire_definition(field=definition, actor=admin, correlation_id="test")
    kept = client.patch(url, {"expected_version": 2, "document_language": "de"}, format="json")
    assert kept.status_code == 200, kept.json()
    assert kept.json()["custom_data"] == {"reference": "A-1"}


def test_line_choice_codes_are_validated_and_survive_definition_relabeling() -> None:
    client, invoice, admin = setup_invoice()
    definition = field(
        admin,
        target="invoice_line",
        key="kind",
        data_type="choice",
        choices=[{"code": "work", "label_en": "Work", "label_de": "Arbeit"}],
    )
    url = f"/api/v1/invoices/{invoice.pk}/"
    operation = {
        "action": "add",
        "description": "Consulting",
        "unit": "HUR",
        "quantity": "1.0000",
        "unit_price": "5.00",
        "tax_category": "S",
        "tax_rate": "19.00",
        "price_entry_policy": "net",
        "custom_data": {"kind": "work"},
    }
    invalid = client.patch(
        url,
        {
            "expected_version": 1,
            "line_operations": [{**operation, "custom_data": {"kind": "other"}}],
        },
        format="json",
    )
    assert invalid.status_code == 400
    assert not InvoiceLine.objects.exists()
    saved = client.patch(
        url, {"expected_version": 1, "line_operations": [operation]}, format="json"
    )
    assert saved.status_code == 200, saved.json()
    assert saved.json()["lines"][0]["custom_data"] == {"kind": "work"}
    definition.choices = [{"code": "work", "label_en": "Service", "label_de": "Dienstleistung"}]
    definition.save(update_fields=("choices",))
    assert client.get(url).json()["lines"][0]["custom_data"] == {"kind": "work"}


def test_invoice_exact_filter_and_sensitive_reveal_are_authorized_and_audited() -> None:
    client, invoice, admin = setup_invoice()
    field(admin, target="invoice", key="reference")
    field(admin, target="invoice", key="secret", search_mode="none", is_sensitive=True)
    url = f"/api/v1/invoices/{invoice.pk}/"
    saved = client.patch(
        url,
        {"expected_version": 1, "custom_data": {"reference": "A-1", "secret": "private-value"}},
        format="json",
    )
    assert saved.status_code == 200, saved.json()
    assert saved.json()["custom_data"] == {"reference": "A-1"}
    assert "private-value" not in str(client.get("/api/v1/invoices/").json())
    found = client.get("/api/v1/invoices/?custom_field=reference&custom_value=A-1")
    assert found.status_code == 200 and found.json()["count"] == 1
    assert (
        client.get("/api/v1/invoices/?custom_field=secret&custom_value=private-value").status_code
        == 400
    )
    reader = User.objects.create_user(username="reader", password="test", role=UserRole.READ_ONLY)
    client.force_authenticate(user=reader)
    assert client.get(f"{url}sensitive-fields/").status_code == 403
    client.force_authenticate(user=admin)
    revealed = client.get(f"{url}sensitive-fields/")
    assert revealed.status_code == 200 and revealed.json() == {"secret": "private-value"}
    assert AuditEvent.objects.filter(action_code="custom_fields.sensitive_accessed").count() == 1
    assert "private-value" not in str(AuditEvent.objects.values_list("metadata", flat=True))


def test_typed_range_and_text_filters_on_invoices() -> None:
    client, invoice, admin = setup_invoice()
    field(admin, target="invoice", key="visits", data_type="integer", search_mode="range")
    field(admin, target="invoice", key="memo", search_mode="text")
    updated = client.patch(
        f"/api/v1/invoices/{invoice.pk}/",
        {"expected_version": 1, "custom_data": {"visits": 4, "memo": "Consultation"}},
        format="json",
    )
    assert updated.status_code == 200, updated.json()
    assert (
        client.get(
            "/api/v1/invoices/?custom_field=visits&custom_operator=gte&custom_value=3"
        ).json()["count"]
        == 1
    )
    assert (
        client.get(
            "/api/v1/invoices/?custom_field=visits&custom_operator=lte&custom_value=3"
        ).json()["count"]
        == 0
    )
    assert (
        client.get(
            "/api/v1/invoices/?custom_field=memo&custom_operator=text&custom_value=consult"
        ).json()["count"]
        == 1
    )


def test_sensitive_line_reveal_is_admin_only_and_audited() -> None:
    client, invoice, admin = setup_invoice()
    field(admin, target="invoice_line", key="secret", search_mode="none", is_sensitive=True)
    saved = client.patch(
        f"/api/v1/invoices/{invoice.pk}/",
        {
            "expected_version": 1,
            "line_operations": [
                {
                    "action": "add",
                    "description": "Consulting",
                    "unit": "HUR",
                    "unit_price": "5.00",
                    "tax_category": "S",
                    "tax_rate": "19.00",
                    "price_entry_policy": "net",
                    "custom_data": {"secret": "private-line"},
                }
            ],
        },
        format="json",
    )
    assert saved.status_code == 200, saved.json()
    line_id = saved.json()["lines"][0]["id"]
    assert "private-line" not in str(saved.json())
    reader = User.objects.create_user(username="reader", password="test", role=UserRole.READ_ONLY)
    client.force_authenticate(user=reader)
    url = f"/api/v1/invoices/{invoice.pk}/lines/{line_id}/sensitive-fields/"
    assert client.get(url).status_code == 403
    client.force_authenticate(user=admin)
    revealed = client.get(url)
    assert revealed.status_code == 200 and revealed.json() == {"secret": "private-line"}
    assert AuditEvent.objects.filter(action_code="custom_fields.sensitive_accessed").count() == 1
    assert "private-line" not in str(AuditEvent.objects.values_list("metadata", flat=True))


def test_creation_requires_published_invoice_field_and_accepts_value() -> None:
    client, invoice, admin = setup_invoice()
    field(admin, target="invoice", key="reference", required=True)
    failed = client.post("/api/v1/invoices/", {"customer_id": invoice.customer_id}, format="json")
    assert failed.status_code == 400
    created = client.post(
        "/api/v1/invoices/",
        {"customer_id": invoice.customer_id, "custom_data": {"reference": "B-2"}},
        format="json",
    )
    assert created.status_code == 201, created.json()
    assert created.json()["custom_data"] == {"reference": "B-2"}


def test_invoice_list_can_filter_on_line_custom_fields() -> None:
    client, invoice, admin = setup_invoice()
    field(
        admin,
        target="invoice_line",
        key="kind",
        data_type="choice",
        choices=[
            {"code": "work", "label_en": "Work", "label_de": "Arbeit"},
        ],
    )
    saved = client.patch(
        f"/api/v1/invoices/{invoice.pk}/",
        {
            "expected_version": 1,
            "line_operations": [
                {
                    "action": "add",
                    "description": "Consulting",
                    "unit": "HUR",
                    "unit_price": "5.00",
                    "tax_category": "S",
                    "tax_rate": "19.00",
                    "price_entry_policy": "net",
                    "custom_data": {"kind": "work"},
                }
            ],
        },
        format="json",
    )
    assert saved.status_code == 200, saved.json()
    found = client.get("/api/v1/invoices/?line_custom_field=kind&line_custom_value=work")
    assert found.status_code == 200 and found.json()["count"] == 1
    missing = client.get("/api/v1/invoices/?line_custom_field=kind&line_custom_value=other")
    assert missing.status_code == 400  # Unknown choice codes are rejected.


def test_rejected_sensitive_value_is_absent_from_response_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, invoice, admin = setup_invoice()
    field(
        admin,
        target="invoice",
        key="secret_number",
        data_type="integer",
        search_mode="none",
        is_sensitive=True,
    )
    response = client.patch(
        f"/api/v1/invoices/{invoice.pk}/",
        {"expected_version": 1, "custom_data": {"secret_number": "private-value"}},
        format="json",
    )
    assert response.status_code == 400
    assert "private-value" not in str(response.json())
    assert "private-value" not in caplog.text

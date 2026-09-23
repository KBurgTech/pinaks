from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.billing.issuance import issue_invoice
from pinaks.apps.billing.models import Invoice, InvoiceLine, LifecycleStatus
from pinaks.apps.billing.services import create_draft, update_draft
from pinaks.apps.configuration.models import CompanyProfile, TaxProfile
from pinaks.apps.customers.models import Customer, CustomerAddress
from pinaks.apps.documents.models import DocumentTemplate, DocumentTemplateVersion, VersionStatus
from pinaks.apps.workers.models import WorkItem

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def ready_invoice() -> tuple[Invoice, User, DocumentTemplate]:
    CompanyProfile.objects.create(
        legal_name="Seller GmbH",
        address_line_1="Seller St",
        postal_code="10115",
        city="Berlin",
        tax_number="12/345/67890",
        iban="DE89370400440532013000",
    )
    TaxProfile.objects.create(
        code="standard",
        name="Standard",
        tax_category="S",
        rate=Decimal("19.00"),
        price_entry_policy="net",
        tax_column_policy="show",
        requires_tax_number=True,
        is_default=True,
    )
    actor = User.objects.create_user(username="issuer", password="test", role=UserRole.ADMIN)
    customer = Customer.objects.create(
        customer_number="C1",
        party_type="person",
        given_name="Ada",
        family_name="Lovelace",
        preferred_language="en",
    )
    CustomerAddress.objects.create(
        customer=customer,
        label="Main",
        address_line_1="Buyer St",
        postal_code="10115",
        city="Berlin",
        is_primary=True,
    )
    invoice = create_draft(customer=customer, actor=actor, correlation_id="test")
    invoice = update_draft(
        invoice_id=invoice.pk,
        expected_version=invoice.version,
        actor=actor,
        correlation_id="test",
        values={
            "recipient": {"source": "customer"},
            "line_operations": [
                {
                    "action": "add",
                    "description": "Service",
                    "unit": "HUR",
                    "quantity": Decimal("1"),
                    "unit_price": Decimal("100"),
                    "tax_category": "S",
                    "tax_rate": Decimal("19"),
                    "price_entry_policy": "net",
                    "service_date": "2026-09-23",
                }
            ],
        },
    )
    template = DocumentTemplate.objects.create(code="invoice", name="Invoice")
    for language in ("en", "de"):
        DocumentTemplateVersion.objects.create(
            template=template,
            language=language,
            version=1,
            status=VersionStatus.PUBLISHED,
            html="<p>{{ invoice.number }}</p>",
            page_settings={"size": "A4"},
            created_by=actor,
            published_by=actor,
        )
    return invoice, actor, template


def test_issuance_freezes_values_and_enqueues_once(
    ready_invoice: tuple[Invoice, User, DocumentTemplate],
) -> None:
    invoice, actor, template = ready_invoice
    issued = issue_invoice(
        invoice_id=invoice.pk,
        expected_version=invoice.version,
        template_id=template.pk,
        idempotency_key="issue-1",
        actor=actor,
        correlation_id="test",
    )
    assert issued.lifecycle_status == LifecycleStatus.ISSUING
    assert issued.invoice_number
    assert isinstance(issued.snapshot, dict)
    assert issued.snapshot["schema_version"] == 1
    frozen_invoice = issued.snapshot["invoice"]
    assert isinstance(frozen_invoice, dict)
    assert frozen_invoice["grand_total"] == "119.00"
    assert WorkItem.objects.get(job_type="documents.generate", identity=str(invoice.pk))
    snapshot = issued.snapshot.copy()
    invoice.customer.given_name = "Changed"
    invoice.customer.save()
    CompanyProfile.objects.update(legal_name="Changed Seller")
    TaxProfile.objects.update(rate=Decimal("7.00"))
    assert (
        issue_invoice(
            invoice_id=invoice.pk,
            expected_version=invoice.version,
            template_id=template.pk,
            idempotency_key="issue-1",
            actor=actor,
            correlation_id="test",
        ).snapshot
        == snapshot
    )
    assert WorkItem.objects.count() == 1
    with pytest.raises(ValidationError):
        update_draft(
            invoice_id=invoice.pk,
            expected_version=issued.version,
            values={"due_date": None},
            actor=actor,
            correlation_id="test",
        )
    line = InvoiceLine.objects.get(invoice=issued)
    line.description = "Changed"
    with pytest.raises(ValidationError):
        line.save()


def test_invalid_draft_receives_no_number_or_work(
    ready_invoice: tuple[Invoice, User, DocumentTemplate],
) -> None:
    invoice, actor, template = ready_invoice
    InvoiceLine.objects.filter(invoice=invoice).delete()
    with pytest.raises(ValidationError):
        issue_invoice(
            invoice_id=invoice.pk,
            expected_version=invoice.version,
            template_id=template.pk,
            idempotency_key="issue-1",
            actor=actor,
            correlation_id="test",
        )
    invoice.refresh_from_db()
    assert invoice.invoice_number is None
    assert WorkItem.objects.count() == 0
    assert CompanyProfile.objects.get().invoice_number_next == 1


def test_issue_api_enforces_role_and_idempotency(
    ready_invoice: tuple[Invoice, User, DocumentTemplate],
) -> None:
    from rest_framework.test import APIClient

    invoice, actor, template = ready_invoice
    client = APIClient()
    url = f"/api/v1/invoices/{invoice.pk}/issue/"
    body = {
        "expected_version": invoice.version,
        "template_id": template.pk,
        "idempotency_key": "one",
    }
    assert client.post(url, body, format="json").status_code == 403
    reader = User.objects.create_user(username="reader", password="test", role=UserRole.READ_ONLY)
    client.force_authenticate(user=reader)
    assert client.post(url, body, format="json").status_code == 403
    client.force_authenticate(user=actor)
    response = client.post(url, body, format="json")
    assert response.status_code == 202, response.json()
    assert response.json()["lifecycle_status"] == "ISSUING"
    assert client.post(url, body, format="json").status_code == 202
    conflict = client.post(url, {**body, "idempotency_key": "other"}, format="json")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "issue_identity_conflict"


def test_issuing_rows_reject_direct_content_mutation(
    ready_invoice: tuple[Invoice, User, DocumentTemplate],
) -> None:
    from django.db import DatabaseError, transaction

    invoice, actor, template = ready_invoice
    issue_invoice(
        invoice_id=invoice.pk,
        expected_version=invoice.version,
        template_id=template.pk,
        idempotency_key="one",
        actor=actor,
        correlation_id="test",
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        Invoice.objects.filter(pk=invoice.pk).update(recipient={"city": "Changed"})
    with pytest.raises(DatabaseError), transaction.atomic():
        InvoiceLine.objects.filter(invoice=invoice).update(description="Changed")
    with pytest.raises(DatabaseError), transaction.atomic():
        InvoiceLine.objects.filter(invoice=invoice).delete()


def test_two_invoices_share_monotonic_series(
    ready_invoice: tuple[Invoice, User, DocumentTemplate],
) -> None:
    invoice, actor, template = ready_invoice
    second = create_draft(customer=invoice.customer, actor=actor, correlation_id="test")
    second = update_draft(
        invoice_id=second.pk,
        expected_version=second.version,
        actor=actor,
        correlation_id="test",
        values={
            "recipient": {"source": "customer"},
            "line_operations": [
                {
                    "action": "add",
                    "description": "Service",
                    "unit": "HUR",
                    "quantity": Decimal("1"),
                    "unit_price": Decimal("100"),
                    "tax_category": "S",
                    "tax_rate": Decimal("19"),
                    "price_entry_policy": "net",
                    "service_date": "2026-09-23",
                }
            ],
        },
    )
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connections

    barrier = Barrier(2)

    def issue(target: Invoice, key: str) -> str:
        barrier.wait()
        try:
            result = issue_invoice(
                invoice_id=target.pk,
                expected_version=target.version,
                template_id=template.pk,
                idempotency_key=key,
                actor=actor,
                correlation_id="test",
            )
            assert result.invoice_number is not None
            return result.invoice_number
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(issue, invoice, "one"), pool.submit(issue, second, "two")]
        numbers = [future.result() for future in futures]
    assert len(set(numbers)) == 2
    assert sorted(number[-4:] for number in numbers) == ["0001", "0002"]
    assert CompanyProfile.objects.get().invoice_number_next == 3


def test_concurrent_replay_allocates_one_number(
    ready_invoice: tuple[Invoice, User, DocumentTemplate],
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connections

    invoice, actor, template = ready_invoice
    barrier = Barrier(2)

    def issue() -> str | None:
        barrier.wait()
        try:
            return issue_invoice(
                invoice_id=invoice.pk,
                expected_version=invoice.version,
                template_id=template.pk,
                idempotency_key="same-command",
                actor=actor,
                correlation_id="test",
            ).invoice_number
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        numbers = list(pool.map(lambda _: issue(), range(2)))
    assert numbers[0] == numbers[1]
    assert CompanyProfile.objects.get().invoice_number_next == 2
    assert WorkItem.objects.count() == 1


def test_issuing_invoice_cannot_be_deleted(
    ready_invoice: tuple[Invoice, User, DocumentTemplate],
) -> None:
    from django.db import DatabaseError, transaction

    invoice, actor, template = ready_invoice
    issue_invoice(
        invoice_id=invoice.pk,
        expected_version=invoice.version,
        template_id=template.pk,
        idempotency_key="delete-check",
        actor=actor,
        correlation_id="test",
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        Invoice.objects.filter(pk=invoice.pk).delete()


@pytest.mark.parametrize(
    "invalid",
    [
        "seller",
        "payment",
        "recipient",
        "template",
        "tax",
        "totals",
        "service_date",
        "bilingual_template",
    ],
)
def test_issuance_preconditions_are_atomic(
    ready_invoice: tuple[Invoice, User, DocumentTemplate],
    invalid: str,
) -> None:
    invoice, actor, template = ready_invoice
    template_id = template.pk
    if invalid == "seller":
        CompanyProfile.objects.update(tax_number="", vat_identifier="")
    elif invalid == "payment":
        CompanyProfile.objects.update(iban="", payment_instructions="")
    elif invalid == "recipient":
        Invoice.objects.filter(pk=invoice.pk).update(recipient={})
    elif invalid == "template":
        template_id += 100
    elif invalid == "tax":
        InvoiceLine.objects.filter(invoice=invoice).update(tax_rate=Decimal("7.00"))
    elif invalid == "totals":
        Invoice.objects.filter(pk=invoice.pk).update(
            subtotal=Decimal("90.00"), grand_total=Decimal("109.00")
        )
    elif invalid == "service_date":
        InvoiceLine.objects.filter(invoice=invoice).update(service_date=None)
    elif invalid == "bilingual_template":
        incomplete = DocumentTemplate.objects.create(code="incomplete", name="Incomplete")
        DocumentTemplateVersion.objects.create(
            template=incomplete,
            language="en",
            version=1,
            status=VersionStatus.PUBLISHED,
            html="<p>Invoice</p>",
            page_settings={"size": "A4"},
            created_by=actor,
            published_by=actor,
        )
        template_id = incomplete.pk
    with pytest.raises(ValidationError):
        issue_invoice(
            invoice_id=invoice.pk,
            expected_version=invoice.version,
            template_id=template_id,
            idempotency_key="invalid",
            actor=actor,
            correlation_id="test",
        )
    invoice.refresh_from_db()
    assert invoice.lifecycle_status == LifecycleStatus.DRAFT
    assert invoice.invoice_number is None
    assert invoice.snapshot is None
    assert WorkItem.objects.count() == 0
    assert CompanyProfile.objects.get().invoice_number_next == 1


def test_custom_field_metadata_is_frozen_with_values(
    ready_invoice: tuple[Invoice, User, DocumentTemplate],
) -> None:
    import json

    from pinaks.apps.custom_fields.models import CustomFieldDefinition

    invoice, actor, template = ready_invoice
    definition = CustomFieldDefinition.objects.create(
        target="invoice",
        key="reference",
        data_type="text",
        label_en="Reference",
        label_de="Referenz",
        visibility="document",
    )
    line_definition = CustomFieldDefinition.objects.create(
        target="invoice_line",
        key="detail",
        data_type="text",
        label_en="Detail",
        label_de="Detail",
        visibility="document",
    )
    line = InvoiceLine.objects.get(invoice=invoice)
    invoice = update_draft(
        invoice_id=invoice.pk,
        expected_version=invoice.version,
        actor=actor,
        correlation_id="test",
        values={
            "custom_data": {"reference": "A-1"},
            "line_operations": [
                {"action": "update", "line_id": line.pk, "custom_data": {"detail": "Travel"}}
            ],
        },
    )
    issued = issue_invoice(
        invoice_id=invoice.pk,
        expected_version=invoice.version,
        template_id=template.pk,
        idempotency_key="custom",
        actor=actor,
        correlation_id="test",
    )
    before = json.dumps(issued.snapshot, sort_keys=True, ensure_ascii=False).encode()
    CustomFieldDefinition.objects.filter(pk__in=[definition.pk, line_definition.pk]).update(
        label_en="Changed", label_de="Geändert"
    )
    issued.refresh_from_db()
    assert json.dumps(issued.snapshot, sort_keys=True, ensure_ascii=False).encode() == before
    assert isinstance(issued.snapshot, dict)
    frozen_invoice = issued.snapshot["invoice"]
    assert isinstance(frozen_invoice, dict)
    assert frozen_invoice["custom_fields"][0]["label_en"] == "Reference"


def test_frozen_issuance_snapshot_serializes_without_live_models(
    ready_invoice: tuple[Invoice, User, DocumentTemplate],
) -> None:
    from pathlib import Path

    from pinaks.apps.e_invoicing.facturx import FacturXSerializer
    from pinaks.apps.e_invoicing.mustang import MustangValidator

    invoice, actor, template = ready_invoice
    issued = issue_invoice(
        invoice_id=invoice.pk,
        expected_version=invoice.version,
        template_id=template.pk,
        idempotency_key="xml-snapshot",
        actor=actor,
        correlation_id="test",
    )
    assert issued.snapshot is not None
    first = FacturXSerializer().serialize(issued.snapshot)
    invoice.customer.given_name = "Changed"
    invoice.customer.save()
    CompanyProfile.objects.update(legal_name="Changed Seller")
    assert FacturXSerializer().serialize(issued.snapshot) == first
    validator = MustangValidator(
        jar_path=Path("/tmp/pinaks-einvoice-tools/mustang/Mustang-CLI-2.23.0.jar")
    )
    report = validator.validate(first, filename="issued.xml")
    assert report.valid, report.findings

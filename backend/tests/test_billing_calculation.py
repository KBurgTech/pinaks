from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from pinaks.apps.accounts.models import User, UserRole
from pinaks.apps.billing.calculations import calculate_line, calculate_totals
from pinaks.apps.billing.models import InvoiceLine
from pinaks.apps.billing.services import create_draft, recalculate_draft
from pinaks.apps.configuration.models import CompanyProfile
from pinaks.apps.customers.models import Customer


@pytest.mark.parametrize(
    ("policy", "quantity", "price", "discount", "rate", "expected"),
    [
        ("net", "2", "10.00", "0", "19.00", ("20.00", "3.80", "23.80")),
        ("gross", "2", "11.90", "0", "19.00", ("20.00", "3.80", "23.80")),
        ("net", "1", "10.00", "10.00", "7.00", ("9.00", "0.63", "9.63")),
        ("gross", "1", "10.70", "0", "7.00", ("10.00", "0.70", "10.70")),
        ("net", "1", "10.00", "0", "0.00", ("10.00", "0.00", "10.00")),
        ("gross", "1", "0.03", "0", "19.00", ("0.03", "0.00", "0.03")),
        ("net", "3", "0.01", "0", "19.00", ("0.03", "0.01", "0.04")),
        ("net", "1", "0.01", "100.00", "19.00", ("0.00", "0.00", "0.00")),
    ],
)
def test_calculate_line(
    policy: str, quantity: str, price: str, discount: str, rate: str, expected: tuple[str, str, str]
) -> None:
    result = calculate_line(
        quantity=Decimal(quantity),
        unit_price=Decimal(price),
        discount_percent=Decimal(discount),
        tax_rate=Decimal(rate),
        price_entry_policy=policy,
    )
    assert (result.net, result.tax, result.gross) == tuple(map(Decimal, expected))


@pytest.mark.parametrize(
    "quantity,price,discount,rate,policy",
    [
        ("0", "1.00", "0", "19.00", "net"),
        ("-1", "1.00", "0", "19.00", "net"),
        ("1", "-1.00", "0", "19.00", "net"),
        ("1", "1.00", "100.01", "19.00", "net"),
        ("1", "1.00", "0", "101.00", "net"),
        ("1", "1.001", "0", "19.00", "net"),
        ("1", "1.00", "0", "19.00", "other"),
    ],
)
def test_calculate_line_rejects_invalid_values(
    quantity: str, price: str, discount: str, rate: str, policy: str
) -> None:
    with pytest.raises(ValueError):
        calculate_line(
            quantity=Decimal(quantity),
            unit_price=Decimal(price),
            discount_percent=Decimal(discount),
            tax_rate=Decimal(rate),
            price_entry_policy=policy,
        )


def test_grouped_totals_sum_rounded_lines_without_losing_remainders() -> None:
    lines = [
        (
            "S",
            Decimal("19.00"),
            calculate_line(
                quantity=Decimal("1"),
                unit_price=Decimal("0.03"),
                discount_percent=Decimal("0"),
                tax_rate=Decimal("19.00"),
                price_entry_policy="net",
            ),
        ),
        (
            "S",
            Decimal("19.00"),
            calculate_line(
                quantity=Decimal("1"),
                unit_price=Decimal("0.03"),
                discount_percent=Decimal("0"),
                tax_rate=Decimal("19.00"),
                price_entry_policy="net",
            ),
        ),
        (
            "E",
            Decimal("0.00"),
            calculate_line(
                quantity=Decimal("1"),
                unit_price=Decimal("2.00"),
                discount_percent=Decimal("0"),
                tax_rate=Decimal("0.00"),
                price_entry_policy="net",
            ),
        ),
    ]
    result = calculate_totals(lines)
    assert (result.subtotal, result.tax_total, result.grand_total) == (
        Decimal("2.06"),
        Decimal("0.02"),
        Decimal("2.08"),
    )
    assert [(group.category, group.rate, group.net, group.tax) for group in result.groups] == [
        ("E", Decimal("0.00"), Decimal("2.00"), Decimal("0.00")),
        ("S", Decimal("19.00"), Decimal("0.06"), Decimal("0.02")),
    ]


@pytest.mark.django_db
def test_recalculate_persists_ordered_line_snapshots_and_invoice_totals() -> None:
    CompanyProfile.objects.create(legal_name="Seller")
    buyer = Customer.objects.create(
        customer_number="C-1", party_type="person", given_name="Ada", family_name="Lovelace"
    )
    actor = User.objects.create_user(
        username="editor", password="long test password", role=UserRole.COMPANY_MEMBER
    )
    invoice = create_draft(customer=buyer, actor=actor, correlation_id="calc")
    for position, policy, price, rate, category in [
        (2, "gross", "11.90", "19.00", "S"),
        (1, "net", "2.00", "0.00", "E"),
    ]:
        InvoiceLine.objects.create(
            invoice=invoice,
            position=position,
            item_code="CODE",
            description="Work",
            unit="C62",
            quantity=Decimal("1"),
            unit_price=Decimal(price),
            discount_percent=Decimal("0"),
            tax_category=category,
            tax_rate=Decimal(rate),
            price_entry_policy=policy,
            exemption_reason_code="VATEX-EU-132" if category == "E" else "",
            exemption_wording="Exempt" if category == "E" else "",
        )
    result = recalculate_draft(invoice_id=invoice.pk)
    assert (result.subtotal, result.tax_total, result.grand_total) == (
        Decimal("12.00"),
        Decimal("1.90"),
        Decimal("13.90"),
    )
    assert [
        (line.position, line.net_total, line.tax_total, line.gross_total)
        for line in InvoiceLine.objects.filter(invoice=invoice)
    ] == [
        (1, Decimal("2.00"), Decimal("0.00"), Decimal("2.00")),
        (2, Decimal("10.00"), Decimal("1.90"), Decimal("11.90")),
    ]
    assert result.version == 2


@pytest.mark.django_db
def test_database_rejects_invalid_line_and_inconsistent_invoice_totals() -> None:
    CompanyProfile.objects.create(legal_name="Seller")
    buyer = Customer.objects.create(
        customer_number="C-1", party_type="person", given_name="Ada", family_name="Lovelace"
    )
    actor = User.objects.create_user(
        username="editor", password="long test password", role=UserRole.COMPANY_MEMBER
    )
    invoice = create_draft(customer=buyer, actor=actor, correlation_id="constraint")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            InvoiceLine.objects.create(
                invoice=invoice,
                position=1,
                item_code="CODE",
                description="Work",
                unit="C62",
                quantity=Decimal("0"),
                unit_price=Decimal("1.00"),
                discount_percent=Decimal("0"),
                tax_category="S",
                tax_rate=Decimal("19.00"),
                price_entry_policy="net",
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            type(invoice).objects.filter(pk=invoice.pk).update(grand_total=Decimal("1.00"))


@pytest.mark.django_db
def test_create_api_rejects_authoritative_totals() -> None:
    CompanyProfile.objects.create(legal_name="Seller")
    buyer = Customer.objects.create(
        customer_number="C-1", party_type="person", given_name="Ada", family_name="Lovelace"
    )
    actor = User.objects.create_user(
        username="editor", password="long test password", role=UserRole.COMPANY_MEMBER
    )
    client = APIClient()
    client.force_authenticate(user=actor)
    response = client.post(
        "/api/v1/invoices/", {"customer_id": buyer.pk, "grand_total": "0.01"}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["error"]["fields"]["grand_total"][0]["code"] == "unknown_field"


def test_line_and_invoice_balances_across_small_rounding_grid() -> None:
    for policy in ("net", "gross"):
        for cents in range(1, 21):
            for quantity in (Decimal("0.5"), Decimal("1"), Decimal("3")):
                for discount in (Decimal("0"), Decimal("12.50"), Decimal("100")):
                    for category, rate in (
                        ("E", Decimal("0")),
                        ("S", Decimal("7")),
                        ("S", Decimal("19")),
                    ):
                        line = calculate_line(
                            quantity=quantity,
                            unit_price=Decimal(cents) / Decimal("100"),
                            discount_percent=discount,
                            tax_rate=rate,
                            price_entry_policy=policy,
                        )
                        assert line.net + line.tax == line.gross
                        totals = calculate_totals([(category, rate, line)])
                        assert totals.subtotal + totals.tax_total == totals.grand_total
                        assert totals.grand_total == line.gross

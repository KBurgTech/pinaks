"""The issued snapshot is the sole input to structured invoice generation."""

from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree

import pytest

from pinaks.apps.e_invoicing.facturx import FacturXSerializer, InvoiceMappingError
from pinaks.apps.e_invoicing.mustang import MustangValidator

MUSTANG_JAR = Path("/tmp/pinaks-einvoice-tools/mustang/Mustang-CLI-2.23.0.jar")


def snapshot(*, language: str = "de", exempt: bool = False) -> dict[str, object]:
    category = "E" if exempt else "S"
    tax = "0.00" if exempt else "19.00"
    tax_amount = "0.00" if exempt else "38.00"
    grand_total = "200.00" if exempt else "238.00"
    return {
        "schema_version": 1,
        "invoice": {
            "number": "INV-2026-0001",
            "type": "STANDARD",
            "issue_date": "2026-09-15",
            "due_date": "2026-09-29",
            "currency": "EUR",
            "language": language,
            "subtotal": "200.00",
            "tax_total": tax_amount,
            "grand_total": grand_total,
        },
        "seller": {
            "legal_name": "Beispiel Dienstleistungen GmbH",
            "address_line_1": "Musterweg 12",
            "postal_code": "10115",
            "city": "Berlin",
            "country_code": "DE",
            "vat_identifier": "DE123456789",
            "tax_number": "",
            "iban": "DE89370400440532013000",
            "bic": "COBADEFFXXX",
            "bank_account_holder": "Beispiel Dienstleistungen GmbH",
            "payment_instructions": "Banküberweisung" if language == "de" else "Bank transfer",
        },
        "customer": {"number": "C-1", "organization_name": "Other Company GmbH"},
        "recipient": {
            "organization_name": "Beispiel Kunde GmbH",
            "address_line_1": "Testallee 7",
            "postal_code": "20095",
            "city": "Hamburg",
            "country_code": "DE",
        },
        "tax_profile": {
            "category": category,
            "rate": tax,
            "exemption_reason_code": "VATEX-EU-132" if exempt else "",
            "exemption_wording_de": "Steuerbefreit" if exempt else "",
            "exemption_wording_en": "Exempt from VAT" if exempt else "",
        },
        "lines": [
            {
                "position": 1,
                "item_code": "CONSULT",
                "description": "Beratung" if language == "de" else "Consulting",
                "unit": "HUR",
                "quantity": "2.0000",
                "unit_price": "100.00",
                "discount_percent": "0.00",
                "price_entry_policy": "net",
                "service_date": "2026-09-15",
                "service_period_end": None,
                "tax_category": category,
                "tax_rate": tax,
                "exemption_reason_code": "VATEX-EU-132" if exempt else "",
                "exemption_wording": "Steuerbefreit" if language == "de" else "Exempt from VAT",
                "net_total": "200.00",
                "tax_total": tax_amount,
                "gross_total": grand_total,
            }
        ],
        "tax_breakdowns": [{"category": category, "rate": tax, "net": "200.00", "tax": tax_amount}],
    }


@pytest.mark.parametrize(
    "language,exempt", [("de", False), ("en", False), ("de", True), ("en", True)]
)
def test_frozen_snapshot_generates_valid_en16931(language: str, exempt: bool) -> None:
    issued = snapshot(language=language, exempt=exempt)
    xml = FacturXSerializer().serialize(issued)
    assert xml == FacturXSerializer().serialize(deepcopy(issued))
    root = ElementTree.fromstring(xml)
    content = " ".join(root.itertext())
    assert "Beispiel Kunde GmbH" in content
    assert "Other Company GmbH" not in content
    assert ("Beratung" if language == "de" else "Consulting") in content
    if exempt:
        assert ("Steuerbefreit" if language == "de" else "Exempt from VAT") in content
    report = MustangValidator(jar_path=MUSTANG_JAR).validate(xml, filename="issued.xml")
    assert report.valid, report.findings


def test_discount_and_rounding_use_frozen_line_amounts() -> None:
    issued = snapshot()
    lines = issued["lines"]
    assert isinstance(lines, list)
    lines[0]["quantity"] = "3.0000"
    lines[0]["unit_price"] = "100.00"
    lines[0]["discount_percent"] = "10.00"
    lines[0]["net_total"] = "270.00"
    lines[0]["tax_total"] = "51.30"
    lines[0]["gross_total"] = "321.30"
    invoice = issued["invoice"]
    assert isinstance(invoice, dict)
    invoice.update(subtotal="270.00", tax_total="51.30", grand_total="321.30")
    breakdowns = issued["tax_breakdowns"]
    assert isinstance(breakdowns, list)
    breakdowns[0].update(net="270.00", tax="51.30")
    xml = FacturXSerializer().serialize(issued)
    assert b"270.00" in xml
    assert MustangValidator(jar_path=MUSTANG_JAR).validate(xml, filename="discount.xml").valid


@pytest.mark.parametrize("change", ["schema", "total", "tax", "missing_recipient", "float"])
def test_invalid_snapshot_returns_stable_mapping_error(change: str) -> None:
    issued = snapshot()
    if change == "schema":
        issued["schema_version"] = 2
    elif change == "total":
        invoice = issued["invoice"]
        assert isinstance(invoice, dict)
        invoice["grand_total"] = "999.00"
    elif change == "tax":
        breakdowns = issued["tax_breakdowns"]
        assert isinstance(breakdowns, list)
        breakdowns[0]["tax"] = "0.00"
    elif change == "missing_recipient":
        issued["recipient"] = {}
    else:
        lines = issued["lines"]
        assert isinstance(lines, list)
        lines[0]["unit_price"] = 100.0
    with pytest.raises(InvoiceMappingError) as error:
        FacturXSerializer().serialize(issued)
    assert error.value.code in {"unsupported_snapshot", "invalid_snapshot", "inconsistent_totals"}


def test_serializer_identifies_its_standard_and_specification() -> None:
    serializer = FacturXSerializer()
    assert serializer.standard == "Factur-X"
    assert serializer.profile == "EN 16931"
    assert serializer.specification_version == "1.09"
    assert serializer.generator_version == "6.8"

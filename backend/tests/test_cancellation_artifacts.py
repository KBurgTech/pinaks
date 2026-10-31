from copy import deepcopy
from io import BytesIO

import pytest
from lxml import etree  # type: ignore[import-untyped]
from pypdf import PdfReader

from pinaks.apps.e_invoicing.generation import HybridInvoiceGenerator
from pinaks.apps.e_invoicing.snapshot import InvoiceMappingError, serialize_snapshot
from test_snapshot_pdf import visual_snapshot


def cancellation_snapshot(language: str = "en", exempt: bool = False) -> dict[str, object]:
    snapshot = visual_snapshot(language, exempt)
    invoice = snapshot["invoice"]
    assert isinstance(invoice, dict)
    invoice.update(
        type="CANCELLATION",
        correction_reason="Duplicate <invoice>",
        original_reference={"number": "ORIGINAL-2026-01", "issue_date": "2026-09-01"},
    )
    return snapshot


@pytest.mark.parametrize("language", ["en", "de"])
@pytest.mark.parametrize("exempt", [False, True])
def test_cancellation_is_valid_hybrid_credit_with_visible_original_reference(
    language: str, exempt: bool
) -> None:
    snapshot = cancellation_snapshot(language, exempt)
    before = deepcopy(snapshot)
    generated = HybridInvoiceGenerator().generate(snapshot)
    xml = etree.fromstring(generated.xml)
    ns = {
        "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    }
    assert xml.xpath("string(//ram:TypeCode)", namespaces=ns) == "381"
    assert (
        xml.xpath("string(//ram:InvoiceReferencedDocument/ram:IssuerAssignedID)", namespaces=ns)
        == "ORIGINAL-2026-01"
    )
    assert b"Duplicate &lt;invoice&gt;" in generated.xml
    reader = PdfReader(BytesIO(generated.pdf))
    text = " ".join(page.extract_text() for page in reader.pages)
    assert "ORIGINAL-2026-01" in text
    assert "Duplicate <invoice>" in text
    assert ("Stornorechnung" if language == "de" else "Cancellation invoice") in text
    assert generated.xml_report.valid and generated.pdf_report.valid
    assert reader.attachments["factur-x.xml"] == [generated.xml]
    assert snapshot == before


@pytest.mark.parametrize("field", ["correction_reason", "original_reference"])
def test_cancellation_mapping_requires_traceability(field: str) -> None:
    snapshot = cancellation_snapshot()
    invoice = snapshot["invoice"]
    assert isinstance(invoice, dict)
    invoice.pop(field)
    with pytest.raises(InvoiceMappingError):
        serialize_snapshot(snapshot)


@pytest.mark.parametrize("language", ["en", "de"])
@pytest.mark.parametrize("exempt", [False, True])
def test_partial_credit_is_valid_hybrid_with_original_reference(
    language: str, exempt: bool
) -> None:
    snapshot = cancellation_snapshot(language, exempt)
    invoice = snapshot["invoice"]
    assert isinstance(invoice, dict)
    invoice["type"] = "CREDIT_NOTE"
    invoice.update(
        subtotal="100.00",
        tax_total="0.00" if exempt else "19.00",
        grand_total="100.00" if exempt else "119.00",
    )
    lines = snapshot["lines"]
    assert isinstance(lines, list)
    line = lines[0]
    assert isinstance(line, dict)
    line.update(
        quantity="1",
        net_total="100.00",
        tax_total="0.00" if exempt else "19.00",
        gross_total="100.00" if exempt else "119.00",
    )
    groups = snapshot["tax_breakdowns"]
    assert isinstance(groups, list)
    group = groups[0]
    assert isinstance(group, dict)
    group.update(net="100.00", tax="0.00" if exempt else "19.00")
    generated = HybridInvoiceGenerator().generate(snapshot)
    xml = etree.fromstring(generated.xml)
    ns = {
        "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    }
    assert xml.xpath("string(//ram:TypeCode)", namespaces=ns) == "381"
    assert (
        xml.xpath("string(//ram:InvoiceReferencedDocument/ram:IssuerAssignedID)", namespaces=ns)
        == "ORIGINAL-2026-01"
    )
    text = " ".join(page.extract_text() for page in PdfReader(BytesIO(generated.pdf)).pages)
    assert ("Gutschrift" if language == "de" else "Credit note") in text
    assert "ORIGINAL-2026-01" in text
    assert generated.xml_report.valid and generated.pdf_report.valid


def test_fractional_credit_with_reduced_price_preserves_cent_rounding() -> None:
    snapshot = cancellation_snapshot()
    invoice = snapshot["invoice"]
    assert isinstance(invoice, dict)
    invoice.update(type="CREDIT_NOTE", subtotal="13.34", tax_total="2.53", grand_total="15.87")
    lines = snapshot["lines"]
    assert isinstance(lines, list)
    line = lines[0]
    assert isinstance(line, dict)
    line.update(
        quantity="0.3334",
        unit_price="40.00",
        net_total="13.34",
        tax_total="2.53",
        gross_total="15.87",
    )
    groups = snapshot["tax_breakdowns"]
    assert isinstance(groups, list)
    group = groups[0]
    group.update(net="13.34", tax="2.53")
    generated = HybridInvoiceGenerator().generate(snapshot)
    assert generated.xml_report.valid and generated.pdf_report.valid

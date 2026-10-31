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

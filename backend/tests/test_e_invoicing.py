import io
import json
import os
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import StreamObject
from weasyprint import HTML  # type: ignore[import-untyped]

from pinaks.apps.e_invoicing.contracts import (
    CanonicalInvoice,
    InvoiceLine,
    PostalAddress,
    TaxBreakdown,
    TradeParty,
)
from pinaks.apps.e_invoicing.facturx import FacturXHybridPdfPackager, FacturXSerializer
from pinaks.apps.e_invoicing.mustang import MustangValidator

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "e_invoicing"
MUSTANG_CLI_JAR = Path(
    os.environ.get("MUSTANG_CLI_JAR", "/tmp/pinaks-einvoice-tools/mustang/Mustang-CLI-2.23.0.jar")
)
JAVA_EXECUTABLE = Path(os.environ.get("JAVA_EXECUTABLE", "java"))


def canonical_invoice() -> CanonicalInvoice:
    fixture = json.loads((FIXTURE_DIRECTORY / "canonical_invoice.json").read_text())
    seller = fixture.pop("seller")
    buyer = fixture.pop("buyer")
    lines = fixture.pop("lines")
    tax_breakdowns = fixture.pop("tax_breakdowns")
    issue_date = date.fromisoformat(fixture.pop("issue_date"))
    due_date = date.fromisoformat(fixture.pop("due_date"))
    delivery_date = date.fromisoformat(fixture.pop("delivery_date"))
    decimal_fields = (
        "line_total",
        "tax_basis_total",
        "tax_total",
        "grand_total",
        "due_payable",
    )
    decimal_values = {field: Decimal(fixture.pop(field)) for field in decimal_fields}
    return CanonicalInvoice(
        invoice_number=fixture["invoice_number"],
        currency=fixture["currency"],
        language=fixture["language"],
        payment_terms=fixture["payment_terms"],
        issue_date=issue_date,
        due_date=due_date,
        delivery_date=delivery_date,
        seller=TradeParty(
            name=seller["name"],
            vat_identifier=seller["vat_identifier"],
            address=PostalAddress(
                address_line=seller["address_line"],
                city=seller["city"],
                postal_code=seller["postal_code"],
                country_code=seller["country_code"],
            ),
        ),
        buyer=TradeParty(
            name=buyer["name"],
            vat_identifier=buyer["vat_identifier"],
            address=PostalAddress(
                address_line=buyer["address_line"],
                city=buyer["city"],
                postal_code=buyer["postal_code"],
                country_code=buyer["country_code"],
            ),
        ),
        lines=tuple(
            InvoiceLine(
                **(
                    line
                    | {
                        "quantity": Decimal(line["quantity"]),
                        "unit_price": Decimal(line["unit_price"]),
                        "net_amount": Decimal(line["net_amount"]),
                        "tax_rate": Decimal(line["tax_rate"]),
                    }
                )
            )
            for line in lines
        ),
        tax_breakdowns=tuple(
            TaxBreakdown(
                **(
                    tax
                    | {
                        "tax_rate": Decimal(tax["tax_rate"]),
                        "tax_basis": Decimal(tax["tax_basis"]),
                        "tax_amount": Decimal(tax["tax_amount"]),
                    }
                )
            )
            for tax in tax_breakdowns
        ),
        line_total=decimal_values["line_total"],
        tax_basis_total=decimal_values["tax_basis_total"],
        tax_total=decimal_values["tax_total"],
        grand_total=decimal_values["grand_total"],
        due_payable=decimal_values["due_payable"],
    )


def test_serializer_produces_zugferd_en16931_xml() -> None:
    xml = FacturXSerializer().serialize(canonical_invoice())

    assert b"urn:cen.eu:en16931:2017" in xml
    assert b"INV-2026-0001" in xml
    assert b"238.00" in xml
    assert xml == (FIXTURE_DIRECTORY / "representative-invoice.xml").read_bytes()


def test_packager_embeds_xml_in_pdf_a_3() -> None:
    invoice = canonical_invoice()
    xml = FacturXSerializer().serialize(invoice)
    source_pdf = HTML(string="<h1>Invoice INV-2026-0001</h1>").write_pdf(pdf_variant="pdf/a-3u")

    packaged_pdf = FacturXHybridPdfPackager().package(source_pdf, xml, language=invoice.language)

    reader = PdfReader(BytesIO(packaged_pdf))
    assert reader.attachments["factur-x.xml"][0] == xml


def test_mustang_validator_returns_machine_readable_success() -> None:
    report = MustangValidator(jar_path=MUSTANG_CLI_JAR, java_executable=JAVA_EXECUTABLE).validate(
        FacturXSerializer().serialize(canonical_invoice()), filename="invoice.xml"
    )

    assert report.valid is True
    assert report.validator == "Mustang 2.23.0"
    assert b'<summary status="valid"/>' in report.raw_report
    assert report.findings == ()


def test_validator_rejects_invalid_totals() -> None:
    invalid_xml = (FIXTURE_DIRECTORY / "invalid-total.xml").read_bytes()

    report = MustangValidator(jar_path=MUSTANG_CLI_JAR, java_executable=JAVA_EXECUTABLE).validate(
        invalid_xml, filename="invalid-total.xml"
    )

    assert report.valid is False
    assert any("[BR-CO-16]" in finding.message for finding in report.findings)


def test_validator_rejects_invalid_tax_data() -> None:
    invalid_xml = (FIXTURE_DIRECTORY / "invalid-tax.xml").read_bytes()

    report = MustangValidator(jar_path=MUSTANG_CLI_JAR, java_executable=JAVA_EXECUTABLE).validate(
        invalid_xml, filename="invalid-tax.xml"
    )

    assert report.valid is False
    assert any("[BR-S-08]" in finding.message for finding in report.findings)


def test_validator_rejects_broken_pdf_a_metadata() -> None:
    invoice = canonical_invoice()
    xml = FacturXSerializer().serialize(invoice)
    source_pdf = HTML(string="<h1>Invoice</h1>").write_pdf(pdf_variant="pdf/a-3u")
    hybrid_pdf = FacturXHybridPdfPackager().package(source_pdf, xml, language=invoice.language)
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(BytesIO(hybrid_pdf)))
    metadata = writer.root_object["/Metadata"].get_object()
    assert isinstance(metadata, StreamObject)
    metadata.set_data(
        metadata.get_data().replace(
            b"<pdfaid:conformance>B</pdfaid:conformance>",
            b"<pdfaid:conformance>Z</pdfaid:conformance>",
        )
    )
    broken_pdf = io.BytesIO()
    writer.write(broken_pdf)

    report = MustangValidator(jar_path=MUSTANG_CLI_JAR, java_executable=JAVA_EXECUTABLE).validate(
        broken_pdf.getvalue(), filename="invalid-metadata.pdf"
    )

    assert report.valid is False
    assert any("Not a PDF/A-3" in finding.message for finding in report.findings)


def test_authoritative_validator_accepts_hybrid_pdf() -> None:
    invoice = canonical_invoice()
    xml = FacturXSerializer().serialize(invoice)
    source_pdf = HTML(string="<h1>Invoice INV-2026-0001</h1>").write_pdf(pdf_variant="pdf/a-3u")
    hybrid_pdf = FacturXHybridPdfPackager().package(source_pdf, xml, language=invoice.language)

    report = MustangValidator(jar_path=MUSTANG_CLI_JAR, java_executable=JAVA_EXECUTABLE).validate(
        hybrid_pdf, filename="invoice.pdf"
    )

    assert report.valid is True
    assert b"<pdf>ValidationResult [flavour=3b" in report.raw_report
    assert b"<profile>urn:cen.eu:en16931:2017</profile>" in report.raw_report

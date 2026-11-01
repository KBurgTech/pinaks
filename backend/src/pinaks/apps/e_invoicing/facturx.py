from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal
from importlib.metadata import version
from io import BytesIO

from facturx import generate_from_binary, generate_xml  # type: ignore[import-untyped]
from lxml import etree  # type: ignore[import-untyped]
from pypdf import PdfReader, PdfWriter
from pypdf.generic import StreamObject

from pinaks.apps.e_invoicing.contracts import CanonicalInvoice
from pinaks.apps.e_invoicing.snapshot import InvoiceMappingError as InvoiceMappingError
from pinaks.apps.e_invoicing.snapshot import serialize_snapshot


def _amount(value: Decimal) -> str:
    return format(value, "f")


def _normalise_pdfa_xmp(pdf: bytes) -> bytes:
    reader = PdfReader(BytesIO(pdf), strict=True)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    metadata_reference = writer.root_object.get("/Metadata")
    if metadata_reference is None:
        raise ValueError("Factur-X package has no XMP metadata")
    metadata = metadata_reference.get_object()
    if not isinstance(metadata, StreamObject):
        raise ValueError("Factur-X package has invalid XMP metadata")

    packet = metadata.get_data()
    root_start = packet.find(b"<x:xmpmeta")
    root_end = packet.find(b"</x:xmpmeta>", root_start)
    if root_start < 0 or root_end < 0:
        raise ValueError("Factur-X package has malformed XMP metadata")
    root_end += len(b"</x:xmpmeta>")
    source_root = etree.fromstring(packet[root_start:root_end])
    rdf_namespace = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmp_namespace = "adobe:ns:meta/"
    source_rdf = source_root.find(f"{{{rdf_namespace}}}RDF")
    if source_rdf is None:
        raise ValueError("Factur-X package XMP has no RDF data")

    normalized_root = etree.Element(f"{{{xmp_namespace}}}xmpmeta", nsmap={"x": xmp_namespace})
    normalized_rdf = etree.SubElement(
        normalized_root, f"{{{rdf_namespace}}}RDF", nsmap={"rdf": rdf_namespace}
    )
    namespace_map = {
        prefix: namespace
        for prefix, namespace in source_root.nsmap.items()
        if prefix not in (None, "x")
    }
    about_attribute = f"{{{rdf_namespace}}}about"
    for description in source_rdf.findall(f"{{{rdf_namespace}}}Description"):
        attributes = dict(description.attrib)
        attributes[about_attribute] = ""
        normalized_description = etree.SubElement(
            normalized_rdf,
            description.tag,
            attributes,
            nsmap=namespace_map,
        )
        for child in description:
            normalized_description.append(deepcopy(child))

    normalized_packet = (
        packet[:root_start]
        + etree.tostring(normalized_root, encoding="utf-8", pretty_print=True)
        + packet[root_end:]
    )
    metadata.set_data(normalized_packet)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


class FacturXSerializer:
    """Map Pinaks' canonical snapshot to ZUGFeRD/Factur-X EN 16931 CII."""

    standard = "Factur-X"
    profile = "EN 16931"
    specification_version = "1.09"
    generator_version = version("factur-x")

    def serialize_snapshot(self, snapshot: Mapping[str, object]) -> bytes:
        return serialize_snapshot(snapshot)

    def serialize(self, invoice: CanonicalInvoice | Mapping[str, object]) -> bytes:
        if isinstance(invoice, Mapping):
            return self.serialize_snapshot(invoice)
        data: dict[str, object] = {
            "BT-1": invoice.invoice_number,
            "BT-2": invoice.issue_date,
            "BT-3": "380",
            "BT-5": invoice.currency,
            "BT-9": invoice.due_date,
            "BT-20": invoice.payment_terms,
            "BT-72": invoice.delivery_date,
            "BG-4": {
                "name": invoice.seller.name,
                "addr_l1": invoice.seller.address.address_line,
                "city": invoice.seller.address.city,
                "postcode": invoice.seller.address.postal_code,
                "country_code": invoice.seller.address.country_code,
                "vat_identifier": invoice.seller.vat_identifier,
            },
            "BG-7": {
                "name": invoice.buyer.name,
                "addr_l1": invoice.buyer.address.address_line,
                "city": invoice.buyer.address.city,
                "postcode": invoice.buyer.address.postal_code,
                "country_code": invoice.buyer.address.country_code,
                "vat_identifier": invoice.buyer.vat_identifier,
            },
            "BG-23": [
                {
                    "BT-116": _amount(tax.tax_basis),
                    "BT-117": _amount(tax.tax_amount),
                    "BT-118": tax.tax_category,
                    "BT-119": _amount(tax.tax_rate),
                }
                for tax in invoice.tax_breakdowns
            ],
            "BT-106": _amount(invoice.line_total),
            "BT-109": _amount(invoice.tax_basis_total),
            "BT-110": _amount(invoice.tax_total),
            "BT-110-1": invoice.currency,
            "BT-112": _amount(invoice.grand_total),
            "BT-115": _amount(invoice.due_payable),
            "BG-25": [
                {
                    "BT-126": line.identifier,
                    "BT-127-00": [{"BT-127": line.description}],
                    "BT-129": _amount(line.quantity),
                    "BT-130": line.unit_code,
                    "BT-131": _amount(line.net_amount),
                    "BT-146": _amount(line.unit_price),
                    "BT-151": line.tax_category,
                    "BT-152": _amount(line.tax_rate),
                    "BT-153": line.name,
                }
                for line in invoice.lines
            ],
        }
        return generate_xml(
            data,
            flavor="factur-x",
            level="en16931",
            check_xsd=True,
            check_schematron=False,
            prefixed_namespaces=True,
        )


class FacturXHybridPdfPackager:
    """Embed CII XML in an existing PDF/A document without library leakage."""

    def package(self, source_pdf: bytes, invoice_xml: bytes, *, language: str) -> bytes:
        return _normalise_pdfa_xmp(
            generate_from_binary(
                source_pdf,
                invoice_xml,
                flavor="factur-x",
                level="en16931",
                check_xsd=True,
                check_schematron=False,
                lang=language,
            )
        )

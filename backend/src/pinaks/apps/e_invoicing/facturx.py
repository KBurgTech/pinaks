from collections.abc import Mapping
from decimal import Decimal
from importlib.metadata import version

from facturx import generate_from_binary, generate_xml  # type: ignore[import-untyped]

from pinaks.apps.e_invoicing.contracts import CanonicalInvoice
from pinaks.apps.e_invoicing.snapshot import InvoiceMappingError as InvoiceMappingError
from pinaks.apps.e_invoicing.snapshot import serialize_snapshot


def _amount(value: Decimal) -> str:
    return format(value, "f")


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
            "BT-27": invoice.seller.name,
            "BT-31": invoice.seller.vat_identifier,
            "BT-35": invoice.seller.address.address_line,
            "BT-37": invoice.seller.address.city,
            "BT-38": invoice.seller.address.postal_code,
            "BT-40": invoice.seller.address.country_code,
            "BT-44": invoice.buyer.name,
            "BT-48": invoice.buyer.vat_identifier,
            "BT-50": invoice.buyer.address.address_line,
            "BT-52": invoice.buyer.address.city,
            "BT-53": invoice.buyer.address.postal_code,
            "BT-55": invoice.buyer.address.country_code,
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
                    "BT-127": line.description,
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
        return generate_from_binary(
            source_pdf,
            invoice_xml,
            flavor="factur-x",
            level="en16931",
            check_xsd=True,
            check_schematron=False,
            lang=language,
        )

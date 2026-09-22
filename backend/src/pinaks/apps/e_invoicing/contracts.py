from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PostalAddress:
    address_line: str
    city: str
    postal_code: str
    country_code: str


@dataclass(frozen=True, slots=True)
class TradeParty:
    name: str
    address: PostalAddress
    vat_identifier: str


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    identifier: str
    name: str
    description: str
    quantity: Decimal
    unit_code: str
    unit_price: Decimal
    net_amount: Decimal
    tax_category: str
    tax_rate: Decimal


@dataclass(frozen=True, slots=True)
class TaxBreakdown:
    tax_category: str
    tax_rate: Decimal
    tax_basis: Decimal
    tax_amount: Decimal


@dataclass(frozen=True, slots=True)
class CanonicalInvoice:
    invoice_number: str
    issue_date: date
    due_date: date
    delivery_date: date
    currency: str
    language: str
    seller: TradeParty
    buyer: TradeParty
    payment_terms: str
    lines: tuple[InvoiceLine, ...]
    tax_breakdowns: tuple[TaxBreakdown, ...]
    line_total: Decimal
    tax_basis_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    due_payable: Decimal


class EInvoiceSerializer(Protocol):
    def serialize(self, invoice: CanonicalInvoice) -> bytes: ...


class HybridPdfPackager(Protocol):
    def package(self, source_pdf: bytes, invoice_xml: bytes, *, language: str) -> bytes: ...


class EInvoiceValidator(Protocol):
    def validate(self, document: bytes, *, filename: str) -> ValidationReport: ...


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    level: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    valid: bool
    validator: str
    raw_report: bytes
    findings: tuple[ValidationFinding, ...]

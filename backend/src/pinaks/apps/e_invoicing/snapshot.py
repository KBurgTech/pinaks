"""Map versioned billing snapshots into EN 16931 input without live model reads."""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

from facturx import generate_xml  # type: ignore[import-untyped]


class InvoiceMappingError(ValueError):
    """A frozen invoice cannot be represented by the supported profile."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def obj(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise InvoiceMappingError("invalid_snapshot")
    return value


def string(value: object, *, required: bool = True) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        raise InvoiceMappingError("invalid_snapshot")
    return value


def number(value: object) -> Decimal:
    if not isinstance(value, str):
        raise InvoiceMappingError("invalid_snapshot")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise InvoiceMappingError("invalid_snapshot") from error
    if not result.is_finite() or result < 0:
        raise InvoiceMappingError("invalid_snapshot")
    return result


def date_value(value: object) -> date:
    try:
        return date.fromisoformat(string(value))
    except ValueError as error:
        raise InvoiceMappingError("invalid_snapshot") from error


def rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not value:
        raise InvoiceMappingError("invalid_snapshot")
    return [obj(row) for row in value]


def amount(value: Decimal) -> str:
    return format(value, "f")


def serialize_snapshot(snapshot: Mapping[str, object]) -> bytes:
    if snapshot.get("schema_version") != 1:
        raise InvoiceMappingError("unsupported_snapshot")
    invoice = obj(snapshot.get("invoice"))
    seller = obj(snapshot.get("seller"))
    recipient = obj(snapshot.get("recipient"))
    profile = obj(snapshot.get("tax_profile"))
    lines = rows(snapshot.get("lines"))
    groups = rows(snapshot.get("tax_breakdowns"))
    if invoice.get("type") != "STANDARD" or invoice.get("language") not in {"en", "de"}:
        raise InvoiceMappingError("unsupported_snapshot")
    if invoice.get("currency") != "EUR":
        raise InvoiceMappingError("unsupported_snapshot")
    issue_date = date_value(invoice.get("issue_date"))
    due_date = date_value(invoice.get("due_date")) if invoice.get("due_date") else None
    if due_date and due_date < issue_date:
        raise InvoiceMappingError("invalid_snapshot")
    organization = string(recipient.get("organization_name", ""), required=False)
    first = string(recipient.get("given_name", ""), required=False)
    last = string(recipient.get("family_name", ""), required=False)
    recipient_name = string(organization or f"{first} {last}".strip())
    data: dict[str, object] = {
        "BT-1": string(invoice.get("number")),
        "BT-2": issue_date,
        "BT-3": "380",
        "BT-5": "EUR",
        "BT-27": string(seller.get("legal_name")),
        "BT-35": string(seller.get("address_line_1")),
        "BT-37": string(seller.get("city")),
        "BT-38": string(seller.get("postal_code")),
        "BT-40": string(seller.get("country_code")),
        "BT-44": recipient_name,
        "BT-50": string(recipient.get("address_line_1")),
        "BT-52": string(recipient.get("city")),
        "BT-53": string(recipient.get("postal_code")),
        "BT-55": string(recipient.get("country_code")),
    }
    vat = string(seller.get("vat_identifier", ""), required=False)
    tax_number = string(seller.get("tax_number", ""), required=False)
    if not (vat or tax_number):
        raise InvoiceMappingError("invalid_snapshot")
    if vat:
        data["BT-31"] = vat
    if tax_number:
        data["BT-32"] = tax_number
        if not vat:
            data["BT-29"] = {"": tax_number}
    if due_date:
        data["BT-9"] = due_date
    payment = string(seller.get("payment_instructions", ""), required=False)
    if payment:
        data["BT-20"] = payment
    elif due_date is None:
        data["BT-20"] = (
            "Zahlbar nach Erhalt." if invoice["language"] == "de" else "Payable upon receipt."
        )
    iban = string(seller.get("iban", ""), required=False)
    if iban:
        data.update({"BT-81": "58", "BT-84": iban})
        holder = string(seller.get("bank_account_holder", ""), required=False)
        bic = string(seller.get("bic", ""), required=False)
        if holder:
            data["BT-85"] = holder
        if bic:
            data["BT-86"] = bic

    xml_lines: list[dict[str, object]] = []
    net_total = Decimal("0.00")
    for position, line in enumerate(lines, 1):
        if line.get("position") != position or line.get("price_entry_policy") not in {
            "net",
            "gross",
        }:
            raise InvoiceMappingError("invalid_snapshot")
        quantity = number(line.get("quantity"))
        rate = number(line.get("tax_rate"))
        net = number(line.get("net_total"))
        price = number(line.get("unit_price"))
        discount = number(line.get("discount_percent"))
        category = string(line.get("tax_category"))
        if quantity <= 0 or discount > 100 or category not in {"S", "E"}:
            raise InvoiceMappingError("invalid_snapshot")
        if number(line.get("tax_total")) + net != number(line.get("gross_total")):
            raise InvoiceMappingError("inconsistent_totals")
        if line.get("price_entry_policy") == "gross":
            price = price / (1 + rate / 100)
        net_price = net / quantity
        if net_price > price:
            raise InvoiceMappingError("inconsistent_totals")
        service_date = date_value(line.get("service_date"))
        end = (
            date_value(line.get("service_period_end"))
            if line.get("service_period_end")
            else service_date
        )
        if end < service_date:
            raise InvoiceMappingError("invalid_snapshot")
        xml_line: dict[str, object] = {
            "BT-126": str(position),
            "BT-129": amount(quantity),
            "BT-130": string(line.get("unit")),
            "BT-131": amount(net),
            "BT-146": amount(net_price),
            "BT-151": category,
            "BT-152": amount(rate),
            "BT-153": string(line.get("description")),
            "BT-134": service_date,
            "BT-135": end,
        }
        item_code = string(line.get("item_code", ""), required=False)
        if item_code:
            xml_line["BT-155"] = item_code
        if discount:
            xml_line["BT-148"] = amount(price)
            xml_line["BT-147"] = amount(price - net_price)
        xml_lines.append(xml_line)
        net_total += net
    data["BG-25"] = xml_lines
    data["BT-72"] = min(date_value(line.get("service_date")) for line in lines)

    xml_groups: list[dict[str, object]] = []
    group_net = Decimal("0.00")
    group_tax = Decimal("0.00")
    for group in groups:
        category = string(group.get("category"))
        rate = number(group.get("rate"))
        basis = number(group.get("net"))
        tax = number(group.get("tax"))
        if category not in {"S", "E"} or (category == "E" and (rate or tax)):
            raise InvoiceMappingError("invalid_snapshot")
        matching = sum(
            (
                number(line.get("net_total"))
                for line in lines
                if line.get("tax_category") == category and number(line.get("tax_rate")) == rate
            ),
            Decimal("0.00"),
        )
        if matching != basis:
            raise InvoiceMappingError("inconsistent_totals")
        xml_group: dict[str, object] = {
            "BT-116": amount(basis),
            "BT-117": amount(tax),
            "BT-118": category,
            "BT-119": amount(rate),
        }
        if category == "E":
            language = string(invoice.get("language"))
            xml_group["BT-120"] = string(profile.get(f"exemption_wording_{language}"))
            xml_group["BT-121"] = string(profile.get("exemption_reason_code"))
        xml_groups.append(xml_group)
        group_net += basis
        group_tax += tax
    if (
        net_total != group_net
        or group_net != number(invoice.get("subtotal"))
        or group_tax != number(invoice.get("tax_total"))
        or group_net + group_tax != number(invoice.get("grand_total"))
    ):
        raise InvoiceMappingError("inconsistent_totals")
    data.update(
        {
            "BG-23": xml_groups,
            "BT-106": amount(net_total),
            "BT-109": amount(group_net),
            "BT-110": amount(group_tax),
            "BT-110-1": "EUR",
            "BT-112": amount(group_net + group_tax),
            "BT-115": amount(group_net + group_tax),
        }
    )
    try:
        return generate_xml(
            data,
            flavor="factur-x",
            level="en16931",
            check_xsd=True,
            check_schematron=False,
            prefixed_namespaces=True,
        )
    except (ValueError, KeyError) as error:
        raise InvoiceMappingError("invalid_snapshot") from error

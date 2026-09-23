"""Authoritative EUR calculation policy for draft and issued invoice snapshots.

Each line is rounded to cents with ROUND_HALF_UP. For net entry, round the
discounted net, then its tax. For gross entry, round the discounted gross,
derive and round net, then use gross minus net as tax. Invoice tax groups sum
already rounded line values; they do not round a second time.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class LineAmounts:
    net: Decimal
    tax: Decimal
    gross: Decimal


@dataclass(frozen=True)
class TaxGroup:
    category: str
    rate: Decimal
    net: Decimal
    tax: Decimal


@dataclass(frozen=True)
class InvoiceAmounts:
    subtotal: Decimal
    tax_total: Decimal
    grand_total: Decimal
    groups: tuple[TaxGroup, ...]


def _has_scale(value: Decimal, places: int) -> bool:
    return value == value.quantize(Decimal(1).scaleb(-places))


def calculate_line(
    *,
    quantity: Decimal,
    unit_price: Decimal,
    discount_percent: Decimal,
    tax_rate: Decimal,
    price_entry_policy: str,
) -> LineAmounts:
    if (
        any(not value.is_finite() for value in (quantity, unit_price, discount_percent, tax_rate))
        or quantity <= 0
        or not _has_scale(quantity, 4)
        or unit_price < 0
        or not _has_scale(unit_price, 2)
        or discount_percent < 0
        or discount_percent > HUNDRED
        or not _has_scale(discount_percent, 2)
        or tax_rate < 0
        or tax_rate > HUNDRED
        or not _has_scale(tax_rate, 2)
        or price_entry_policy not in ("net", "gross")
    ):
        raise ValueError("Invalid invoice line calculation input.")
    discounted = quantity * unit_price * (HUNDRED - discount_percent) / HUNDRED
    if price_entry_policy == "net":
        net = discounted.quantize(CENT, rounding=ROUND_HALF_UP)
        tax = (net * tax_rate / HUNDRED).quantize(CENT, rounding=ROUND_HALF_UP)
        gross = net + tax
    else:
        gross = discounted.quantize(CENT, rounding=ROUND_HALF_UP)
        net = (gross / (Decimal("1") + tax_rate / HUNDRED)).quantize(CENT, rounding=ROUND_HALF_UP)
        tax = gross - net
    return LineAmounts(net=net, tax=tax, gross=gross)


def calculate_totals(lines: list[tuple[str, Decimal, LineAmounts]]) -> InvoiceAmounts:
    grouped: dict[tuple[str, Decimal], tuple[Decimal, Decimal]] = {}
    for category, rate, amounts in lines:
        key = (category, rate)
        net, tax = grouped.get(key, (Decimal("0.00"), Decimal("0.00")))
        grouped[key] = (net + amounts.net, tax + amounts.tax)
    groups = tuple(
        TaxGroup(category, rate, *grouped[(category, rate)]) for category, rate in sorted(grouped)
    )
    subtotal = sum((group.net for group in groups), Decimal("0.00"))
    tax_total = sum((group.tax for group in groups), Decimal("0.00"))
    return InvoiceAmounts(subtotal, tax_total, subtotal + tax_total, groups)

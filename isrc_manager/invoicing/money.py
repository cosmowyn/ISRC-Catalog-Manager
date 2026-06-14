"""Integer-minor-unit money, VAT, and quantity helpers."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .currencies import is_iso_4217_currency_code
from .models import (
    DEFAULT_CURRENCY,
    VAT_TREATMENT_STANDARD,
    VAT_TREATMENTS,
    ZERO_VAT_TREATMENTS,
    Quantity,
)

_MONEY_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
_QUANTITY_RE = re.compile(r"^[+]?\d+(?:[.,]\d+)?$")


def normalize_currency(value: object | None, *, default: str = DEFAULT_CURRENCY) -> str:
    currency = str(value or default).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Currency must be a three-letter ISO code.")
    if not is_iso_4217_currency_code(currency):
        raise ValueError(f"Unsupported ISO 4217 currency code: {currency}.")
    return currency


def _reject_float(value: object | None) -> None:
    if isinstance(value, float):
        raise TypeError("Financial values must not use floating point numbers.")


def _decimal_from_text(value: object | None, *, pattern: re.Pattern[str], label: str) -> Decimal:
    _reject_float(value)
    text = str(value or "").strip().replace(",", ".")
    if not text or pattern.fullmatch(text) is None:
        raise ValueError(f"{label} must be a decimal string or integer.")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{label} is not a valid decimal value.") from exc


def parse_money_minor(value: object | None, *, scale: int = 2) -> int:
    """Parse a user-facing amount into integer minor units."""

    decimal_value = _decimal_from_text(value, pattern=_MONEY_RE, label="Money amount")
    quantizer = Decimal(1).scaleb(-int(scale))
    rounded = decimal_value.quantize(quantizer, rounding=ROUND_HALF_UP)
    return int(rounded.scaleb(int(scale)).to_integral_exact())


def format_money(minor_units: int, *, currency: str = DEFAULT_CURRENCY, scale: int = 2) -> str:
    currency = normalize_currency(currency)
    amount = Decimal(int(minor_units)).scaleb(-int(scale))
    return f"{currency} {amount:.{int(scale)}f}"


def parse_quantity(value: object | None) -> Quantity:
    """Parse decimal-safe quantities into integer value plus scale."""

    _reject_float(value)
    text = str(value or "").strip().replace(",", ".")
    if not text or _QUANTITY_RE.fullmatch(text) is None:
        raise ValueError("Quantity must be a positive decimal string or integer.")
    whole, _separator, fraction = text.partition(".")
    scale = len(fraction)
    digits = f"{whole}{fraction}"
    parsed = int(digits or "0")
    if parsed <= 0:
        raise ValueError("Quantity must be greater than zero.")
    return Quantity(value=parsed, scale=scale)


def format_quantity(quantity: Quantity) -> str:
    value = int(quantity.value)
    scale = max(0, int(quantity.scale))
    if scale == 0:
        return str(value)
    sign = "-" if value < 0 else ""
    digits = str(abs(value)).rjust(scale + 1, "0")
    return f"{sign}{digits[:-scale]}.{digits[-scale:]}".rstrip("0").rstrip(".")


def divide_minor_half_up(numerator: int, denominator: int) -> int:
    if int(denominator) <= 0:
        raise ValueError("Denominator must be greater than zero.")
    value = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def line_net_amount_minor(unit_price_minor: int, quantity: Quantity) -> int:
    if int(unit_price_minor) < 0:
        raise ValueError("Unit price must be non-negative.")
    denominator = 10 ** max(0, int(quantity.scale))
    return divide_minor_half_up(int(unit_price_minor) * int(quantity.value), denominator)


def normalize_vat_treatment(value: object | None) -> str:
    clean = str(value or VAT_TREATMENT_STANDARD).strip().lower().replace("-", "_")
    if clean not in VAT_TREATMENTS:
        raise ValueError(f"Unsupported VAT treatment: {value}")
    return clean


def calculate_vat_minor(
    net_minor: int,
    vat_rate_basis_points: int,
    *,
    vat_treatment: object | None = VAT_TREATMENT_STANDARD,
) -> int:
    treatment = normalize_vat_treatment(vat_treatment)
    if int(net_minor) < 0:
        raise ValueError("Net amount must be non-negative.")
    if int(vat_rate_basis_points) < 0:
        raise ValueError("VAT rate must be non-negative.")
    if treatment in ZERO_VAT_TREATMENTS:
        return 0
    return divide_minor_half_up(int(net_minor) * int(vat_rate_basis_points), 10_000)

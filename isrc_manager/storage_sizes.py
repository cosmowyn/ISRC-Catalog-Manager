"""Centralized storage-size parsing, conversion, and display helpers."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from isrc_manager.constants import (
    DEFAULT_HISTORY_STORAGE_BUDGET_MB,
    MAX_HISTORY_STORAGE_BUDGET_MB,
    MIN_HISTORY_STORAGE_BUDGET_MB,
)

KIB_IN_BYTES = 1024
MIB_IN_BYTES = KIB_IN_BYTES * 1024
GIB_IN_BYTES = MIB_IN_BYTES * 1024
TIB_IN_BYTES = GIB_IN_BYTES * 1024
GIB_IN_MB = 1024
TIB_IN_MB = GIB_IN_MB * 1024

_STORAGE_TEXT_RE = re.compile(
    r"^\s*(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>mb?|gb?|tb?)?\s*$",
    re.IGNORECASE,
)


def clamp_history_storage_budget_mb(value: int) -> int:
    parsed = int(value)
    return max(MIN_HISTORY_STORAGE_BUDGET_MB, min(MAX_HISTORY_STORAGE_BUDGET_MB, parsed))


def parse_history_storage_budget_mb(raw_value: object | None) -> int:
    try:
        parsed = int(raw_value)
    except Exception:
        return DEFAULT_HISTORY_STORAGE_BUDGET_MB
    return clamp_history_storage_budget_mb(parsed)


def megabytes_to_bytes(megabytes: int) -> int:
    return max(0, int(megabytes or 0)) * MIB_IN_BYTES


def bytes_to_megabytes_floor(size_bytes: int) -> int:
    return max(0, int(size_bytes or 0)) // MIB_IN_BYTES


def format_storage_bytes(size_bytes: int, *, max_decimals: int = 1) -> str:
    total = max(0, int(size_bytes or 0))
    units = (
        ("B", 1),
        ("KB", KIB_IN_BYTES),
        ("MB", MIB_IN_BYTES),
        ("GB", GIB_IN_BYTES),
        ("TB", TIB_IN_BYTES),
    )
    unit_label = "B"
    divisor = 1
    for label, candidate_divisor in units:
        unit_label = label
        divisor = candidate_divisor
        if total < candidate_divisor * 1024 or label == "TB":
            break
    if unit_label == "B":
        return f"{total} B"
    value = Decimal(total) / Decimal(divisor)
    return f"{_format_decimal(value, max_decimals=max_decimals)} {unit_label}"


def format_budget_megabytes(megabytes: int) -> str:
    total_mb = clamp_history_storage_budget_mb(int(megabytes or 0))
    if total_mb < GIB_IN_MB:
        return f"{total_mb} MB"
    if total_mb < TIB_IN_MB:
        value = Decimal(total_mb) / Decimal(GIB_IN_MB)
        return f"{_format_decimal(value, max_decimals=2)} GB"
    value = Decimal(total_mb) / Decimal(TIB_IN_MB)
    return f"{_format_decimal(value, max_decimals=2)} TB"


def parse_storage_text_to_megabytes(text: str) -> int:
    raw = str(text or "").strip()
    match = _STORAGE_TEXT_RE.fullmatch(raw)
    if match is None:
        raise ValueError(f"Unsupported storage size: {text!r}")
    number_text = str(match.group("number") or "").replace(",", ".")
    unit = str(match.group("unit") or "mb").strip().lower()
    unit = {"m": "mb", "g": "gb", "t": "tb"}.get(unit, unit)
    multiplier = {
        "mb": Decimal(1),
        "gb": Decimal(GIB_IN_MB),
        "tb": Decimal(TIB_IN_MB),
    }.get(unit)
    if multiplier is None:
        raise ValueError(f"Unsupported storage unit: {unit!r}")
    try:
        value = Decimal(number_text)
    except InvalidOperation as exc:
        raise ValueError(f"Unsupported storage size: {text!r}") from exc
    megabytes = (value * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return clamp_history_storage_budget_mb(int(megabytes))


def storage_text_is_valid(text: str) -> bool:
    try:
        parse_storage_text_to_megabytes(text)
    except ValueError:
        return False
    return True


def _format_decimal(value: Decimal, *, max_decimals: int) -> str:
    quantizer = Decimal("1") if max_decimals <= 0 else Decimal(f"1.{'0' * max_decimals}")
    normalized = value.quantize(quantizer, rounding=ROUND_HALF_UP)
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text

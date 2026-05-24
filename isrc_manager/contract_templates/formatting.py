"""Formatting helpers for contract template runtime values."""

from __future__ import annotations

from datetime import date, datetime

DEFAULT_MANUAL_DATE_FORMAT = "dd.mmm.yyyy"
MANUAL_DATE_FORMAT_PRESETS = (
    DEFAULT_MANUAL_DATE_FORMAT,
    "d.mmm.yyyy",
    "d.m.yy",
    "yyyy-mm-dd",
    "dd/mm/yyyy",
)

_MONTH_ABBR = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_MONTH_FULL = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def normalize_manual_date_format(value: object | None) -> str:
    clean = str(value or "").strip()
    return clean or DEFAULT_MANUAL_DATE_FORMAT


def parse_manual_date_value(value: object | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def format_manual_date_value(
    value: object | None,
    format_code: object | None = None,
) -> str:
    parsed = parse_manual_date_value(value)
    if parsed is None:
        return str(value or "")
    code = normalize_manual_date_format(format_code)
    rendered: list[str] = []
    index = 0
    while index < len(code):
        remaining = code[index:]
        lower_remaining = remaining.lower()
        if lower_remaining.startswith("yyyy"):
            rendered.append(f"{parsed.year:04d}")
            index += 4
        elif lower_remaining.startswith("mmmm"):
            rendered.append(_MONTH_FULL[parsed.month])
            index += 4
        elif lower_remaining.startswith("mmm"):
            rendered.append(_MONTH_ABBR[parsed.month])
            index += 3
        elif lower_remaining.startswith("yy"):
            rendered.append(f"{parsed.year % 100:02d}")
            index += 2
        elif lower_remaining.startswith("dd"):
            rendered.append(f"{parsed.day:02d}")
            index += 2
        elif lower_remaining.startswith("mm"):
            rendered.append(f"{parsed.month:02d}")
            index += 2
        elif lower_remaining.startswith("d"):
            rendered.append(str(parsed.day))
            index += 1
        elif lower_remaining.startswith("m"):
            rendered.append(str(parsed.month))
            index += 1
        else:
            rendered.append(code[index])
            index += 1
    return "".join(rendered)

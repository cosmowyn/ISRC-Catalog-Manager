"""Validation and normalization helpers for music catalog codes."""

import re

_ISRC_COMPACT_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{2}\d{5}$", re.IGNORECASE)
_ISRC_ISO_RE = re.compile(r"^[A-Z]{2}-[A-Z0-9]{3}-\d{2}-\d{5}$", re.IGNORECASE)

_ISWC_ANY_RE = re.compile(r"^(?:T\d{9}[\dX]|T-\d{3}\.\d{3}\.\d{3}-[\dX])$", re.IGNORECASE)
_ISWC_ISO_RE = re.compile(r"^T-\d{3}\.\d{3}\.\d{3}-[\dX]$", re.IGNORECASE)

_UPC_EAN_RE = re.compile(r"^\d{12,13}$")


def is_blank(s: str) -> bool:
    return s is None or str(s).strip() == ""


def normalize_isrc(s: str) -> str:
    """Compact uppercase (e.g., XXX0X2512345)."""
    if is_blank(s):
        return ""
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def to_iso_isrc(s: str) -> str:
    """From any to ISO CC-XXX-YY-NNNNN. '' if cannot format."""
    sc = normalize_isrc(s)
    if not _ISRC_COMPACT_RE.match(sc):
        return ""
    return f"{sc[0:2]}-{sc[2:5]}-{sc[5:7]}-{sc[7:12]}"


def is_valid_isrc_compact_or_iso(s: str) -> bool:
    if is_blank(s):
        return False
    s = s.strip().upper()
    return bool(_ISRC_COMPACT_RE.match(normalize_isrc(s)) or _ISRC_ISO_RE.match(s))


def to_compact_isrc(s: str) -> str:
    """Return strict compact 12-char ISRC or ''."""
    sc = normalize_isrc(s)
    return sc if _ISRC_COMPACT_RE.match(sc) else ""


def normalize_iswc(s: str) -> str:
    """Compact uppercase (e.g., T1234567890)."""
    if is_blank(s):
        return ""
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def to_iso_iswc(s: str) -> str:
    """From any to ISO T-###.###.###-C. '' if cannot format."""
    sc = normalize_iswc(s)
    if not sc.startswith("T") or len(sc) != 11:
        return ""
    body = sc[1:10]
    chk = sc[10]
    if not (body.isdigit() and (chk.isdigit() or chk == "X")):
        return ""
    return f"T-{body[0:3]}.{body[3:6]}.{body[6:9]}-{chk}"


def is_valid_iswc_any(s: str) -> bool:
    if is_blank(s):
        return True
    return bool(_ISWC_ANY_RE.match(s.strip()))


def valid_upc_ean(s: str) -> bool:
    if is_blank(s):
        return True
    return bool(_UPC_EAN_RE.match(s.strip()))


def upc_ean_checksum_valid(s: str) -> bool:
    text = str(s or "").strip()
    if not _UPC_EAN_RE.match(text):
        return False
    digits = [int(char) for char in text]
    check_digit = digits.pop()
    total = 0
    reverse_digits = list(reversed(digits))
    for index, digit in enumerate(reverse_digits):
        total += digit * (3 if index % 2 == 0 else 1)
    return ((10 - (total % 10)) % 10) == check_digit


def barcode_validation_status(s: str) -> str:
    if is_blank(s):
        return "missing"
    if not valid_upc_ean(s):
        return "invalid_format"
    if not upc_ean_checksum_valid(s):
        return "invalid_checksum"
    return "valid"

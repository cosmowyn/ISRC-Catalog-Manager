"""Header alias and value-localization helpers for GS1 workbook variants."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from .gs1_models import CANONICAL_GS1_EXPORT_FIELDS, CORE_GS1_TEMPLATE_FIELDS


GS1_FIELD_LABELS = {
    "contract_number": "Contract Number",
    "gtin_request_number": "GS1 Article Code / GTIN",
    "status": "Status",
    "product_classification": "Product Classification",
    "consumer_unit_flag": "Consumer Unit",
    "packaging_type": "Packaging Type",
    "target_market": "Target Market",
    "product_description": "Product Description",
    "language": "Language",
    "brand": "Brand",
    "subbrand": "Subbrand",
    "quantity": "Quantity",
    "unit": "Unit",
    "image_url": "Image URL",
    "notes": "Notes",
    "export_enabled": "Export Enabled",
}

GS1_HEADER_ALIASES = {
    "gtin_request_number": (
        "gs1 artikelcode",
        "gs1 article code",
        "gs1 articlecode",
        "gs1 product code",
        "gs1 item code",
        "article code",
        "article code gtin",
        "gtin",
        "gtin13",
        "gtin 13",
        "code",
    ),
    "status": (
        "status",
    ),
    "product_classification": (
        "productclassificatie",
        "productclassificatie gpc",
        "product classification",
        "product classification gpc",
        "gpc",
    ),
    "consumer_unit_flag": (
        "gaat naar de consument",
        "consumenteneenheid",
        "consumer unit",
        "consumer unit flag",
        "is consumer unit",
        "consumer facing unit",
        "sold to consumer",
    ),
    "packaging_type": (
        "verpakkingstype",
        "verpakkings type",
        "packaging type",
        "package type",
        "pack type",
    ),
    "target_market": (
        "landen of regios",
        "landen of regios",
        "landen of regio",
        "countries or regions",
        "countries and regions",
        "country or region",
        "target market",
        "target markets",
        "market",
        "countries",
        "regions",
    ),
    "product_description": (
        "productomschrijving",
        "product description",
        "trade item description",
        "description",
    ),
    "language": (
        "taal",
        "language",
        "description language",
        "product language",
    ),
    "brand": (
        "merknaam",
        "merk",
        "brand name",
        "brand",
    ),
    "subbrand": (
        "submerk",
        "subbrand",
        "sub brand",
        "sub-brand",
    ),
    "quantity": (
        "aantal",
        "quantity",
        "net content",
        "content amount",
    ),
    "unit": (
        "eenheid",
        "unit",
        "uom",
        "measurement unit",
    ),
    "image_url": (
        "afbeelding",
        "image url",
        "image",
        "picture url",
        "image link",
    ),
}

COMMON_STATUS_CHOICES = ("Concept", "Active", "Inactive")
COMMON_PACKAGING_CHOICES = ("Digital file", "Digital", "Download", "Other")
COMMON_MARKET_CHOICES = (
    "Worldwide",
    "Global Market",
    "European Union",
    "Non-EU",
    "Developing Countries Support",
    "Wereldwijd",
    "Europese Unie",
    "Niet EU",
    "Ontwikkelingslanden ondersteuning",
    "Global",
    "Netherlands",
    "United States",
)
COMMON_LANGUAGE_CHOICES = ("English", "Dutch", "German", "French", "Spanish")
COMMON_CLASSIFICATION_CHOICES = ("Audio", "Music", "Digital audio release", "Digital goods")
COMMON_UNIT_CHOICES = ("Each", "EA", "Count")

_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")

_DUTCH_HEADER_HINTS = {
    "gs1 artikelcode",
    "productclassificatie",
    "gaat naar de consument",
    "verpakkingstype",
    "verpakkings type",
    "landen of regios",
    "productomschrijving",
    "taal",
    "merk",
    "submerk",
    "aantal",
    "eenheid",
    "afbeelding",
}

_BOOLEAN_EXPORT_VALUES = {
    "default": {True: "Yes", False: "No"},
    "nl": {True: "Ja", False: "Nee"},
}

_STATUS_EXPORT_VALUES = {
    "concept": {"default": "Concept", "nl": "Concept"},
    "draft": {"default": "Concept", "nl": "Concept"},
    "active": {"default": "Active", "nl": "Actief"},
    "inactive": {"default": "Inactive", "nl": "Inactief"},
}

_SIMPLE_LOCALIZED_VALUES = {
    "language": {
        "english": {"default": "English", "nl": "Engels"},
        "dutch": {"default": "Dutch", "nl": "Nederlands"},
        "nederlands": {"default": "Dutch", "nl": "Nederlands"},
        "engels": {"default": "English", "nl": "Engels"},
    },
    "target_market": {
        "global": {"default": "Worldwide", "nl": "Wereldwijd"},
        "global market": {"default": "Global Market", "nl": "Global Market"},
        "worldwide": {"default": "Worldwide", "nl": "Wereldwijd"},
        "werelwijd": {"default": "Worldwide", "nl": "Wereldwijd"},
        "wereldwijd": {"default": "Worldwide", "nl": "Wereldwijd"},
        "european union": {"default": "European Union", "nl": "Europese Unie"},
        "europese unie": {"default": "European Union", "nl": "Europese Unie"},
        "non eu": {"default": "Non-EU", "nl": "Niet EU"},
        "niet eu": {"default": "Non-EU", "nl": "Niet EU"},
        "developing countries support": {"default": "Developing Countries Support", "nl": "Ontwikkelingslanden ondersteuning"},
        "ontwikkelingslanden ondersteuning": {"default": "Developing Countries Support", "nl": "Ontwikkelingslanden ondersteuning"},
    },
    "unit": {
        "ea": {"default": "Each", "nl": "Aantal"},
        "each": {"default": "Each", "nl": "Aantal"},
        "count": {"default": "Count", "nl": "Aantal"},
        "aantal": {"default": "Count", "nl": "Aantal"},
    },
    "packaging_type": {
        "digital": {"default": "Digital file", "nl": "Digitaal bestand"},
        "digital file": {"default": "Digital file", "nl": "Digitaal bestand"},
        "download": {"default": "Digital file", "nl": "Digitaal bestand"},
    },
}


def normalize_gs1_text(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("&", " and ")
    text = text.replace("-", " ")
    text = text.replace("/", " ")
    text = text.replace("(", " ")
    text = text.replace(")", " ")
    text = text.replace("'", "")
    text = text.replace("\xad", "")
    text = " ".join(text.split())
    return text


def gs1_tokens(value: object) -> tuple[str, ...]:
    normalized = normalize_gs1_text(value)
    if not normalized:
        return ()
    return tuple(token for token in _TOKEN_SPLIT_RE.split(normalized) if token)


def score_header_match(header_text: object, alias_text: object) -> float:
    header_norm = normalize_gs1_text(header_text)
    alias_norm = normalize_gs1_text(alias_text)
    if not header_norm or not alias_norm:
        return 0.0
    if header_norm == alias_norm:
        return 4.0
    if header_norm.startswith(alias_norm) or alias_norm.startswith(header_norm):
        return 3.5
    if alias_norm in header_norm or header_norm in alias_norm:
        return 3.0
    header_tokens = set(gs1_tokens(header_norm))
    alias_tokens = set(gs1_tokens(alias_norm))
    if not header_tokens or not alias_tokens:
        return 0.0
    overlap = header_tokens & alias_tokens
    if not overlap:
        return 0.0
    coverage = len(overlap) / max(len(alias_tokens), len(header_tokens))
    if alias_tokens <= header_tokens:
        return 2.5 + coverage
    if coverage >= 0.75:
        return 2.25 + coverage
    if coverage >= 0.5:
        return 1.25 + coverage
    return 0.0


def match_canonical_field(header_text: object) -> tuple[str | None, float]:
    best_field = None
    best_score = 0.0
    for field_name, aliases in GS1_HEADER_ALIASES.items():
        for alias in aliases:
            score = score_header_match(header_text, alias)
            if score > best_score:
                best_field = field_name
                best_score = score
    return best_field, best_score


def resolve_header_row(header_values: Sequence[object]) -> tuple[dict[str, int], dict[str, str], float]:
    best_by_field: dict[str, tuple[int, str, float]] = {}
    for column_index, header_value in enumerate(header_values, start=1):
        if header_value is None or str(header_value).strip() == "":
            continue
        field_name, score = match_canonical_field(header_value)
        if field_name is None or score <= 0.0:
            continue
        current = best_by_field.get(field_name)
        if current is None or score > current[2]:
            best_by_field[field_name] = (column_index, str(header_value), score)

    column_map = {field_name: match[0] for field_name, match in best_by_field.items()}
    matched_headers = {field_name: match[1] for field_name, match in best_by_field.items()}
    total_score = sum(match[2] for match in best_by_field.values())
    return column_map, matched_headers, total_score


def missing_core_template_fields(column_map: dict[str, int]) -> tuple[str, ...]:
    return tuple(field for field in CORE_GS1_TEMPLATE_FIELDS if field not in column_map)


def optional_template_fields(column_map: dict[str, int]) -> tuple[str, ...]:
    return tuple(field for field in CANONICAL_GS1_EXPORT_FIELDS if field not in column_map and field not in CORE_GS1_TEMPLATE_FIELDS)


def detect_template_locale(matched_headers: dict[str, str], workbook_markers: Sequence[str] | None = None) -> str:
    normalized_headers = {normalize_gs1_text(text) for text in matched_headers.values() if text}
    if normalized_headers & _DUTCH_HEADER_HINTS:
        return "nl"
    markers = {normalize_gs1_text(marker) for marker in (workbook_markers or ()) if marker}
    if any("instruct" in marker or "codelijst" in marker or "artikelcode" in marker for marker in markers):
        return "nl"
    return "default"


def field_label(field_name: str) -> str:
    return GS1_FIELD_LABELS.get(field_name, field_name.replace("_", " ").title())


def localize_export_value(field_name: str, value, locale_hint: str) -> str:
    locale_key = "nl" if locale_hint == "nl" else "default"
    if field_name == "consumer_unit_flag":
        return _BOOLEAN_EXPORT_VALUES[locale_key][bool(value)]

    clean_value = str(value or "").strip()
    if not clean_value:
        return ""

    if field_name == "status":
        normalized = normalize_gs1_text(clean_value)
        localized = _STATUS_EXPORT_VALUES.get(normalized)
        if localized is not None:
            return localized.get(locale_key, localized["default"])
        return clean_value

    localized_lookup = _SIMPLE_LOCALIZED_VALUES.get(field_name)
    if localized_lookup is not None:
        normalized = normalize_gs1_text(clean_value)
        localized = localized_lookup.get(normalized)
        if localized is not None:
            return localized.get(locale_key, localized["default"])
    return clean_value

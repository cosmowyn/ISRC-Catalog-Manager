"""Centralized field normalization, mapping, and transform helpers."""

from __future__ import annotations

import re
from dataclasses import replace

from isrc_manager.domain.timecode import seconds_to_hms

from .models import (
    MAPPING_KIND_CONSTANT,
    MAPPING_KIND_SKIP,
    MAPPING_KIND_SOURCE,
    MAPPING_KIND_UNMAPPED,
    TRANSFORM_BOOL_TO_YES_NO,
    TRANSFORM_COMMA_JOIN,
    TRANSFORM_DATE_TO_YEAR,
    TRANSFORM_DURATION_SECONDS_TO_HMS,
    TRANSFORM_IDENTITY,
    ConversionMappingEntry,
    ConversionSession,
    ConversionTargetField,
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_YEAR_RE = re.compile(r"(?P<year>\d{4})")

TRANSFORM_LABELS: dict[str, str] = {
    TRANSFORM_IDENTITY: "Identity",
    TRANSFORM_DURATION_SECONDS_TO_HMS: "Duration Seconds -> HH:MM:SS",
    TRANSFORM_DATE_TO_YEAR: "Date -> Year",
    TRANSFORM_BOOL_TO_YES_NO: "Boolean -> Yes/No",
    TRANSFORM_COMMA_JOIN: "Comma Join",
}

_FIELD_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "track_title": ("track_title", "title", "song_title", "recording_title"),
    "artist_name": ("artist_name", "artist", "main_artist", "primary_artist", "performer"),
    "additional_artists": (
        "additional_artists",
        "featured_artists",
        "feature_artists",
        "featuring",
    ),
    "album_title": ("album_title", "album", "album_name", "release_title"),
    "genre": ("genre", "style"),
    "isrc": ("isrc", "isrc_code"),
    "duration": ("duration", "track_length_hms", "track_length_sec", "length"),
    "composer": ("composer", "songwriter", "writer"),
    "publisher": ("publisher", "publisher_name", "publishing"),
    "pro_number": ("pro_number", "pro number", "sena_number", "sena number"),
    "upc": ("upc", "ean", "upc_ean", "barcode"),
    "catalog_number": ("catalog_number", "catalog"),
    "track_id": ("track_id", "id", "trackid"),
}
_ALIAS_CANONICALS = {
    alias: canonical for canonical, aliases in _FIELD_ALIAS_GROUPS.items() for alias in aliases
}
_DATE_FIELD_NAMES = {
    "release_date",
    "release_date_release",
    "release_original_release_date",
    "date",
    "date_start",
    "entry_date",
}


def normalize_field_name(name: str | None) -> str:
    text = str(name or "").strip()
    while text.endswith("*"):
        text = text[:-1].rstrip()
    clean = _NON_ALNUM_RE.sub("_", text.casefold()).strip("_")
    return clean


def canonical_field_name(name: str | None) -> str:
    normalized = normalize_field_name(name)
    for prefix in ("owner_", "db_owner_"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return _ALIAS_CANONICALS.get(normalized, normalized)


def available_transforms() -> tuple[str, ...]:
    return tuple(TRANSFORM_LABELS)


def transform_label(name: str) -> str:
    return TRANSFORM_LABELS.get(str(name or "").strip(), str(name or "").strip() or "Identity")


def stringify_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(part for part in (stringify_value(item) for item in value) if part)
    if isinstance(value, dict):
        return ", ".join(
            f"{key}: {stringify_value(item)}"
            for key, item in value.items()
            if stringify_value(item)
        )
    return str(value)


def apply_transform(value: object, transform_name: str) -> str:
    transform = str(transform_name or TRANSFORM_IDENTITY).strip() or TRANSFORM_IDENTITY
    if transform == TRANSFORM_DURATION_SECONDS_TO_HMS:
        if value in (None, ""):
            return ""
        try:
            return seconds_to_hms(int(float(str(value).strip())))
        except (TypeError, ValueError):
            return stringify_value(value)
    if transform == TRANSFORM_DATE_TO_YEAR:
        text = stringify_value(value)
        match = _YEAR_RE.search(text)
        return match.group("year") if match else ""
    if transform == TRANSFORM_BOOL_TO_YES_NO:
        if isinstance(value, str):
            truthy = value.strip().casefold() in {"1", "true", "yes", "y"}
        else:
            truthy = bool(value)
        return "Yes" if truthy else "No"
    if transform == TRANSFORM_COMMA_JOIN:
        if isinstance(value, (list, tuple)):
            return ", ".join(part for part in (stringify_value(item) for item in value) if part)
        return stringify_value(value)
    return stringify_value(value)


def resolve_mapping_value(entry: ConversionMappingEntry, source_row: dict[str, object]) -> str:
    if entry.mapping_kind == MAPPING_KIND_CONSTANT:
        raw_value: object = entry.constant_value
    elif entry.mapping_kind == MAPPING_KIND_SOURCE:
        raw_value = source_row.get(entry.source_field)
    elif entry.mapping_kind == MAPPING_KIND_SKIP:
        raw_value = ""
    else:
        raw_value = ""
    return apply_transform(raw_value, entry.transform_name)


def suggest_mapping_entries(session: ConversionSession) -> dict[str, ConversionMappingEntry]:
    source_headers = tuple(session.source_profile.headers)
    suggestions: dict[str, ConversionMappingEntry] = {}
    for field in session.template_profile.target_fields:
        suggestion = _best_mapping_for_target(field, source_headers)
        if suggestion is None:
            suggestions[field.field_key] = ConversionMappingEntry(
                target_field_key=field.field_key,
                target_display_name=field.display_name,
                mapping_kind=MAPPING_KIND_UNMAPPED,
                transform_name=TRANSFORM_IDENTITY,
                status="unmapped",
                origin="suggested",
                message="No confident source match was found.",
            )
            continue
        source_field, transform_name, message = suggestion
        suggestions[field.field_key] = ConversionMappingEntry(
            target_field_key=field.field_key,
            target_display_name=field.display_name,
            mapping_kind=MAPPING_KIND_SOURCE,
            source_field=source_field,
            transform_name=transform_name,
            status="suggested",
            origin="suggested",
            message=message,
        )
    return suggestions


def update_entry_sample(
    entry: ConversionMappingEntry,
    source_rows: tuple[dict[str, object], ...],
) -> ConversionMappingEntry:
    sample_value = ""
    message = entry.message
    if entry.mapping_kind == MAPPING_KIND_UNMAPPED:
        status = "unmapped"
    elif entry.mapping_kind == MAPPING_KIND_SKIP:
        status = "skipped"
        message = "Field is intentionally skipped."
    elif entry.mapping_kind == MAPPING_KIND_CONSTANT:
        sample_value = apply_transform(entry.constant_value, entry.transform_name)
        status = "constant" if sample_value else "constant_empty"
        if not sample_value:
            message = "Constant value is empty."
    else:
        for row in source_rows:
            sample_value = resolve_mapping_value(entry, row)
            if sample_value:
                break
        status = "mapped" if sample_value else "mapped_empty"
        if not sample_value and not message:
            message = "Mapped source rows currently resolve to an empty value."
    return replace(entry, sample_value=sample_value, status=status, message=message)


def _best_mapping_for_target(
    field: ConversionTargetField,
    source_headers: tuple[str, ...],
) -> tuple[str, str, str] | None:
    target_normalized = normalize_field_name(field.display_name)
    target_canonical = canonical_field_name(field.display_name)
    best: tuple[int, str, str, str] | None = None
    for source_field in source_headers:
        source_normalized = normalize_field_name(source_field)
        source_canonical = canonical_field_name(source_field)
        candidate: tuple[int, str, str, str] | None = None
        if source_normalized == target_normalized:
            candidate = (100, source_field, TRANSFORM_IDENTITY, "Exact field-name match.")
        elif source_canonical == target_canonical and source_canonical:
            candidate = (92, source_field, TRANSFORM_IDENTITY, "Alias-based field match.")
        elif target_canonical == "duration" and source_normalized == "track_length_hms":
            candidate = (90, source_field, TRANSFORM_IDENTITY, "Duration alias match.")
        elif target_canonical == "duration" and source_normalized == "track_length_sec":
            candidate = (
                88,
                source_field,
                TRANSFORM_DURATION_SECONDS_TO_HMS,
                "Duration sourced from seconds.",
            )
        elif target_normalized.endswith("year") and source_normalized in _DATE_FIELD_NAMES:
            candidate = (
                82,
                source_field,
                TRANSFORM_DATE_TO_YEAR,
                "Year inferred from a date field.",
            )
        elif target_normalized.startswith("is_") and source_normalized == target_normalized:
            candidate = (80, source_field, TRANSFORM_BOOL_TO_YES_NO, "Boolean field match.")
        if candidate is None:
            continue
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        return None
    _score, source_field, transform_name, message = best
    return source_field, transform_name, message

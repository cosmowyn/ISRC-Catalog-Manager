"""Standard track field specifications shared across the app."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StandardFieldSpec:
    key: str
    label: str
    field_type: str
    default_visible: bool = True
    promoted_from_custom: bool = False
    value_column: str | None = None
    path_column: str | None = None
    mime_column: str | None = None
    size_column: str | None = None
    media_key: str | None = None


STANDARD_FIELD_SPECS = (
    StandardFieldSpec("id", "ID", "int"),
    StandardFieldSpec(
        "audio_file",
        "Audio File",
        "blob_audio",
        promoted_from_custom=True,
        path_column="audio_file_path",
        mime_column="audio_file_mime_type",
        size_column="audio_file_size_bytes",
        media_key="audio_file",
    ),
    StandardFieldSpec("track_title", "Track Title", "text"),
    StandardFieldSpec("track_length_sec", "Track Length (hh:mm:ss)", "int"),
    StandardFieldSpec("album_title", "Album Title", "text"),
    StandardFieldSpec(
        "album_art",
        "Album Art",
        "blob_image",
        promoted_from_custom=True,
        path_column="album_art_path",
        mime_column="album_art_mime_type",
        size_column="album_art_size_bytes",
        media_key="album_art",
    ),
    StandardFieldSpec("artist_name", "Artist Name", "text"),
    StandardFieldSpec("additional_artists", "Additional Artists", "text"),
    StandardFieldSpec("isrc", "ISRC", "text"),
    StandardFieldSpec(
        "buma_work_number",
        "BUMA Wnr.",
        "text",
        promoted_from_custom=True,
        value_column="buma_work_number",
    ),
    StandardFieldSpec("iswc", "ISWC", "text"),
    StandardFieldSpec("upc", "UPC", "text"),
    StandardFieldSpec(
        "catalog_number",
        "Catalog#",
        "text",
        promoted_from_custom=True,
        value_column="catalog_number",
    ),
    StandardFieldSpec("db_entry_date", "Entry Date", "date"),
    StandardFieldSpec("release_date", "Release Date", "date"),
    StandardFieldSpec("genre", "Genre", "text"),
)

STANDARD_FIELD_BY_LABEL = {spec.label: spec for spec in STANDARD_FIELD_SPECS}
STANDARD_FIELD_BY_KEY = {spec.key: spec for spec in STANDARD_FIELD_SPECS}


def default_base_headers() -> list[str]:
    return [spec.label for spec in STANDARD_FIELD_SPECS]


def promoted_custom_fields() -> tuple[dict[str, str], ...]:
    promoted = []
    for spec in STANDARD_FIELD_SPECS:
        if not spec.promoted_from_custom:
            continue
        field = {
            "name": spec.label,
            "field_type": spec.field_type,
        }
        if spec.value_column:
            field["value_column"] = spec.value_column
        if spec.path_column:
            field["path_column"] = spec.path_column
        if spec.mime_column:
            field["mime_column"] = spec.mime_column
        if spec.size_column:
            field["size_column"] = spec.size_column
        promoted.append(field)
    return tuple(promoted)


def promoted_text_value_columns_by_label_lower() -> dict[str, str]:
    return {
        spec.label.strip().lower(): str(spec.value_column)
        for spec in STANDARD_FIELD_SPECS
        if spec.promoted_from_custom and spec.value_column
    }


def promoted_field_spec_by_label_lower() -> dict[str, StandardFieldSpec]:
    return {
        spec.label.strip().lower(): spec
        for spec in STANDARD_FIELD_SPECS
        if spec.promoted_from_custom
    }


def standard_field_spec_for_label(label: str) -> StandardFieldSpec | None:
    return STANDARD_FIELD_BY_LABEL.get(label)


def standard_media_specs_by_label() -> dict[str, StandardFieldSpec]:
    return {spec.label: spec for spec in STANDARD_FIELD_SPECS if spec.media_key is not None}


def standard_media_specs_by_key() -> dict[str, StandardFieldSpec]:
    return {spec.media_key: spec for spec in STANDARD_FIELD_SPECS if spec.media_key is not None}

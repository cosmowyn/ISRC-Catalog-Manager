from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from isrc_manager import app_sounds
from isrc_manager.conversion import mapping
from isrc_manager.conversion.models import (
    MAPPING_KIND_CONSTANT,
    MAPPING_KIND_SKIP,
    MAPPING_KIND_SOURCE,
    MAPPING_KIND_UNMAPPED,
    REQUIRED_STATUS_OPTIONAL,
    TRANSFORM_BOOL_TO_YES_NO,
    TRANSFORM_COMMA_JOIN,
    TRANSFORM_DATE_TO_YEAR,
    TRANSFORM_DURATION_SECONDS_TO_HMS,
    TRANSFORM_IDENTITY,
    ConversionMappingEntry,
    ConversionSession,
    ConversionSourceProfile,
    ConversionTargetField,
    ConversionTemplateProfile,
)
from isrc_manager.parties import authority


def _target(field_key: str, display_name: str) -> ConversionTargetField:
    return ConversionTargetField(
        field_key=field_key,
        display_name=display_name,
        location="Sheet!A1",
        required_status=REQUIRED_STATUS_OPTIONAL,
    )


def _session(
    targets: tuple[ConversionTargetField, ...],
    headers: tuple[str, ...],
) -> ConversionSession:
    return ConversionSession(
        template_profile=ConversionTemplateProfile(
            template_path=Path("template.csv"),
            format_name="csv",
            output_suffix=".csv",
            structure_label="CSV",
            target_fields=targets,
            template_signature="test",
        ),
        source_profile=ConversionSourceProfile(
            source_mode="file",
            format_name="csv",
            source_label="source.csv",
            headers=headers,
            rows=(),
            preview_rows=(),
        ),
        mapping_entries=(),
        included_row_indices=(),
    )


def test_conversion_mapping_transforms_stringify_and_samples() -> None:
    assert mapping.normalize_field_name("Release Year***") == "release_year"
    assert TRANSFORM_COMMA_JOIN in mapping.available_transforms()
    assert mapping.stringify_value(None) == ""
    assert mapping.stringify_value(True) == "true"
    assert mapping.stringify_value(False) == "false"
    assert mapping.stringify_value(["A", None, "B"]) == "A, B"
    assert mapping.stringify_value({"title": "Song", "empty": ""}) == "title: Song"
    assert mapping.apply_transform(None, TRANSFORM_DURATION_SECONDS_TO_HMS) == ""
    assert mapping.apply_transform("bad", TRANSFORM_DURATION_SECONDS_TO_HMS) == "bad"
    assert mapping.apply_transform("2026-04-05", TRANSFORM_DATE_TO_YEAR) == "2026"
    assert mapping.apply_transform("no date", TRANSFORM_DATE_TO_YEAR) == ""
    assert mapping.apply_transform(" yes ", TRANSFORM_BOOL_TO_YES_NO) == "Yes"
    assert mapping.apply_transform(0, TRANSFORM_BOOL_TO_YES_NO) == "No"
    assert mapping.apply_transform(["Lead", "Guest"], TRANSFORM_COMMA_JOIN) == "Lead, Guest"
    assert mapping.apply_transform("plain", TRANSFORM_COMMA_JOIN) == "plain"

    unmapped = mapping.update_entry_sample(
        ConversionMappingEntry("title", "Title", mapping_kind=MAPPING_KIND_UNMAPPED),
        (),
    )
    skipped = mapping.update_entry_sample(
        ConversionMappingEntry("title", "Title", mapping_kind=MAPPING_KIND_SKIP),
        (),
    )
    empty_constant = mapping.update_entry_sample(
        ConversionMappingEntry("title", "Title", mapping_kind=MAPPING_KIND_CONSTANT),
        (),
    )
    mapped_empty = mapping.update_entry_sample(
        ConversionMappingEntry(
            "title",
            "Title",
            mapping_kind=MAPPING_KIND_SOURCE,
            source_field="missing",
            message="",
        ),
        ({"missing": ""},),
    )
    filled_constant = mapping.update_entry_sample(
        ConversionMappingEntry(
            "label",
            "Label",
            mapping_kind=MAPPING_KIND_CONSTANT,
            constant_value="Fixed Label",
        ),
        (),
    )
    late_source = mapping.update_entry_sample(
        ConversionMappingEntry(
            "title",
            "Title",
            mapping_kind=MAPPING_KIND_SOURCE,
            source_field="title",
            transform_name=TRANSFORM_IDENTITY,
        ),
        ({"title": ""}, {"title": "Late Song"}),
    )
    constant_entry = ConversionMappingEntry(
        "title",
        "Title",
        mapping_kind=MAPPING_KIND_CONSTANT,
        constant_value="Constant Song",
    )
    skip_entry = ConversionMappingEntry(
        "title",
        "Title",
        mapping_kind=MAPPING_KIND_SKIP,
    )
    unmapped_entry = ConversionMappingEntry(
        "title",
        "Title",
        mapping_kind=MAPPING_KIND_UNMAPPED,
    )

    assert unmapped.status == "unmapped"
    assert skipped.status == "skipped"
    assert skipped.message == "Field is intentionally skipped."
    assert empty_constant.status == "constant_empty"
    assert empty_constant.message == "Constant value is empty."
    assert mapped_empty.status == "mapped_empty"
    assert mapped_empty.message == "Mapped source rows currently resolve to an empty value."
    assert filled_constant.status == "constant"
    assert filled_constant.sample_value == "Fixed Label"
    assert late_source.status == "mapped"
    assert late_source.sample_value == "Late Song"
    assert mapping.resolve_mapping_value(constant_entry, {"title": "Ignored"}) == "Constant Song"
    assert mapping.resolve_mapping_value(skip_entry, {"title": "Ignored"}) == ""
    assert mapping.resolve_mapping_value(unmapped_entry, {"title": "Ignored"}) == ""


def test_conversion_mapping_suggestions_cover_alias_duration_and_year_edges() -> None:
    session = _session(
        (
            _target("display_name", "Display Name"),
            _target("title", "Track Title"),
            _target("duration", "Duration"),
            _target("year", "Release Year"),
            _target("unknown", "Unmatched Field"),
        ),
        (
            "Display Name",
            "song title",
            "track_length_sec",
            "release_date",
            "completely unrelated",
        ),
    )

    suggestions = mapping.suggest_mapping_entries(session)

    assert suggestions["display_name"].source_field == "Display Name"
    assert suggestions["display_name"].message == "Exact field-name match."
    assert suggestions["title"].source_field == "song title"
    assert suggestions["title"].message == "Alias-based field match."
    assert suggestions["duration"].source_field == "track_length_sec"
    assert suggestions["duration"].transform_name == "identity"
    assert suggestions["year"].source_field == "release_date"
    assert suggestions["year"].transform_name == TRANSFORM_DATE_TO_YEAR
    assert suggestions["unknown"].mapping_kind == MAPPING_KIND_UNMAPPED
    assert mapping.transform_label("") == "Identity"
    assert mapping.transform_label("custom") == "custom"
    assert mapping.canonical_field_name("Owner Artist") == "artist_name"


def test_app_sound_normalization_and_party_authority_labels() -> None:
    assert app_sounds.coerce_sound_bool(None, default=True) is True
    assert app_sounds.coerce_sound_bool(0) is False
    assert app_sounds.coerce_sound_bool("off") is False
    assert app_sounds.coerce_sound_bool("yes") is True

    normalized = app_sounds.normalize_app_sound_settings(
        {
            "startup_sound_enabled": "0",
            "notice_sound_enabled": "no",
            app_sounds.APP_SOUND_WARNING: 1,
        },
        startup_sound_enabled=True,
    )
    assert normalized == {
        app_sounds.APP_SOUND_STARTUP: True,
        app_sounds.APP_SOUND_NOTICE: False,
        app_sounds.APP_SOUND_WARNING: True,
    }
    assert app_sounds.normalize_app_sound_settings(
        {"startup_sound_enabled": "0", "notice_sound_enabled": "no"}
    ) == {
        app_sounds.APP_SOUND_STARTUP: False,
        app_sounds.APP_SOUND_NOTICE: False,
        app_sounds.APP_SOUND_WARNING: True,
    }
    assert (
        app_sounds.normalize_app_sound_settings(startup_sound_enabled=False)[
            app_sounds.APP_SOUND_STARTUP
        ]
        is False
    )

    assert (
        authority.artist_display_name_from_values(None, None, None, None, fallback_id=7)
        == "Party #7"
    )
    assert authority.artist_display_name_from_values(None, None, None, None) == ""
    record = SimpleNamespace(
        id=3,
        artist_name="Stage Name",
        display_name="Display",
        company_name="Company",
        legal_name="Legal Name",
    )
    assert authority.artist_primary_label(record) == "Stage Name"
    assert authority.artist_choice_label(record) == "Stage Name (Legal Name)"
    assert (
        authority.artist_choice_label(
            SimpleNamespace(
                id=4,
                artist_name="Legal Name",
                display_name="",
                company_name="",
                legal_name="legal name",
            )
        )
        == "Legal Name"
    )


def test_party_authority_notifier_reuses_singleton_and_emits(monkeypatch) -> None:
    monkeypatch.setattr(authority, "_NOTIFIER", None)
    seen: list[str] = []

    notifier = authority.party_authority_notifier()
    notifier.changed.connect(lambda: seen.append("changed"))

    assert authority.party_authority_notifier() is notifier

    authority.emit_party_authority_changed()

    assert seen == ["changed"]

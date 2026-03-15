"""Policy-aware mapping between catalog metadata and canonical audio tags."""

from __future__ import annotations

from dataclasses import dataclass

from .models import AudioTagData, TagFieldConflict

TAG_FIELD_NAMES = (
    "title",
    "artist",
    "album",
    "album_artist",
    "track_number",
    "disc_number",
    "genre",
    "composer",
    "publisher",
    "release_date",
    "isrc",
    "upc",
    "comments",
    "lyrics",
    "artwork",
)


def _is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


@dataclass(slots=True)
class TagImportPatch:
    values: dict[str, object]


@dataclass(slots=True)
class TagConflictPreview:
    patch: TagImportPatch
    conflicts: list[TagFieldConflict]


def catalog_metadata_to_tags(
    *,
    track_values: dict[str, object],
    release_values: dict[str, object] | None = None,
    placement_values: dict[str, object] | None = None,
    artwork=None,
) -> AudioTagData:
    release = release_values or {}
    placement = placement_values or {}
    return AudioTagData(
        title=str(track_values.get("track_title") or "").strip() or None,
        artist=str(track_values.get("artist_name") or "").strip() or None,
        album=str(release.get("title") or track_values.get("album_title") or "").strip() or None,
        album_artist=(
            str(release.get("album_artist") or release.get("primary_artist") or "").strip()
            or str(track_values.get("artist_name") or "").strip()
            or None
        ),
        track_number=int(placement.get("track_number") or 0) or None,
        disc_number=int(placement.get("disc_number") or 0) or None,
        genre=str(track_values.get("genre") or "").strip() or None,
        composer=str(track_values.get("composer") or "").strip() or None,
        publisher=(
            str(release.get("label") or track_values.get("publisher") or "").strip()
            or None
        ),
        release_date=(
            str(release.get("release_date") or track_values.get("release_date") or "").strip()
            or None
        ),
        isrc=str(track_values.get("isrc") or "").strip() or None,
        upc=str(release.get("upc") or track_values.get("upc") or "").strip() or None,
        comments=str(track_values.get("comments") or "").strip() or None,
        lyrics=str(track_values.get("lyrics") or "").strip() or None,
        artwork=artwork,
    )


def merge_imported_tags(
    *,
    database_values: dict[str, object],
    file_tags: AudioTagData,
    policy: str,
) -> TagConflictPreview:
    normalized_policy = str(policy or "merge_blanks").strip().lower()
    values: dict[str, object] = {}
    conflicts: list[TagFieldConflict] = []

    for field_name in TAG_FIELD_NAMES:
        file_value = getattr(file_tags, field_name)
        db_value = database_values.get(field_name)
        if field_name == "artwork":
            if file_value is None:
                chosen = db_value
            elif normalized_policy == "prefer_database" and db_value is not None:
                chosen = db_value
            elif normalized_policy == "merge_blanks" and db_value is not None:
                chosen = db_value
            else:
                chosen = file_value
        elif normalized_policy == "prefer_database":
            chosen = db_value if not _is_blank(db_value) else file_value
        elif normalized_policy == "prefer_file_tags":
            chosen = file_value if not _is_blank(file_value) else db_value
        else:
            chosen = db_value if not _is_blank(db_value) else file_value

        values[field_name] = chosen
        if file_value != db_value and not (_is_blank(file_value) and _is_blank(db_value)):
            conflicts.append(
                TagFieldConflict(
                    field_name=field_name,
                    database_value=db_value,
                    file_value=file_value,
                    chosen_value=chosen,
                )
            )

    return TagConflictPreview(patch=TagImportPatch(values=values), conflicts=conflicts)

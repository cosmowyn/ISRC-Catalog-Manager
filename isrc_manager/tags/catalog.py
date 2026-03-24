"""Service-layer helpers for building catalog-owned tag payloads."""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import TYPE_CHECKING

from .mapping import catalog_metadata_to_tags
from .models import ArtworkPayload, AudioTagData

if TYPE_CHECKING:
    from isrc_manager.releases import ReleaseService
    from isrc_manager.services.tracks import TrackService, TrackSnapshot
    from .service import AudioTagService


CATALOG_EXPORT_RELEASE_POLICY = "unambiguous"


def _effective_artwork_payload_for_track(
    track_id: int,
    *,
    snapshot: TrackSnapshot,
    track_service: TrackService,
) -> ArtworkPayload | None:
    has_album_art = bool(
        snapshot.album_art_path
        or snapshot.album_art_blob_b64
        or snapshot.album_art_filename
        or int(snapshot.album_art_size_bytes or 0) > 0
    )
    if not has_album_art:
        return None
    fallback_mime_type = str(snapshot.album_art_mime_type or "").strip() or "image/jpeg"
    try:
        data, mime_type = track_service.fetch_media_bytes(track_id, "album_art")
    except Exception:
        return None
    return ArtworkPayload(data=data, mime_type=mime_type or fallback_mime_type)


def _select_release_context(
    track_id: int,
    *,
    track_snapshot: TrackSnapshot,
    release_service: ReleaseService | None,
    release_policy: str,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    if release_service is None:
        return None, None
    clean_policy = str(release_policy or "unambiguous").strip().lower()
    if clean_policy == "primary":
        release = release_service.find_primary_release_for_track(track_id)
        if release is None:
            return None, None
        summary = release_service.fetch_release_summary(release.id)
        if summary is None:
            return release.to_dict(), None
        placement_values = None
        for placement in summary.tracks:
            if int(placement.track_id) != int(track_id):
                continue
            placement_values = {
                "track_number": int(placement.track_number),
                "disc_number": int(placement.disc_number),
            }
            break
        return summary.release.to_dict(), placement_values

    release_ids = release_service.find_release_ids_for_track(track_id)
    if not release_ids:
        return None, None
    chosen_release_id: int | None = None
    if len(release_ids) == 1:
        chosen_release_id = release_ids[0]
    else:
        clean_album_title = str(track_snapshot.album_title or "").strip().casefold()
        if clean_album_title:
            matching_release_ids = [
                release_id
                for release_id in release_ids
                if (
                    (release := release_service.fetch_release(int(release_id))) is not None
                    and str(release.title or "").strip().casefold() == clean_album_title
                )
            ]
            if len(matching_release_ids) == 1:
                chosen_release_id = int(matching_release_ids[0])
    if chosen_release_id is None:
        return None, None
    summary = release_service.fetch_release_summary(chosen_release_id)
    if summary is None:
        return None, None
    placement_values = None
    for placement in summary.tracks:
        if int(placement.track_id) != int(track_id):
            continue
        placement_values = {
            "track_number": int(placement.track_number),
            "disc_number": int(placement.disc_number),
        }
        break
    return summary.release.to_dict(), placement_values


def build_catalog_tag_data(
    track_id: int,
    *,
    track_service: TrackService,
    release_service: ReleaseService | None = None,
    release_policy: str = "unambiguous",
    include_artwork_bytes: bool = True,
) -> AudioTagData:
    snapshot = track_service.fetch_track_snapshot(track_id)
    if snapshot is None:
        raise ValueError(f"Track {track_id} not found")
    release_values, placement_values = _select_release_context(
        track_id,
        track_snapshot=snapshot,
        release_service=release_service,
        release_policy=release_policy,
    )
    artwork = (
        _effective_artwork_payload_for_track(
            track_id,
            snapshot=snapshot,
            track_service=track_service,
        )
        if include_artwork_bytes
        else None
    )
    return catalog_metadata_to_tags(
        track_values=asdict(snapshot),
        release_values=release_values,
        placement_values=placement_values,
        artwork=artwork,
    )


def build_catalog_export_tag_data(
    track_id: int,
    *,
    track_service: TrackService,
    release_service: ReleaseService | None = None,
    include_artwork_bytes: bool = True,
) -> AudioTagData:
    """Build tag data for user-facing catalog-backed audio exports.

    Export workflows should only add release context when it is unambiguous enough
    to keep the catalog as the trustworthy source of truth.
    """

    return build_catalog_tag_data(
        track_id,
        track_service=track_service,
        release_service=release_service,
        release_policy=CATALOG_EXPORT_RELEASE_POLICY,
        include_artwork_bytes=include_artwork_bytes,
    )


def has_exportable_catalog_tag_data(tag_data: AudioTagData) -> bool:
    for field in dataclass_fields(AudioTagData):
        if field.name in {"raw_fields", "warnings"}:
            continue
        value = getattr(tag_data, field.name)
        if value not in (None, "", [], {}, ()):
            return True
    return False


def write_catalog_export_tags(
    destination_path: str | Path,
    *,
    track_id: int,
    track_service: TrackService,
    release_service: ReleaseService | None = None,
    tag_service: AudioTagService,
    include_artwork_bytes: bool = True,
) -> tuple[bool, str | None]:
    """Best-effort metadata embedding for catalog-backed audio exports.

    Exports should succeed even when trustworthy catalog metadata cannot be
    resolved or a target container cannot accept the tag payload.
    """

    try:
        tag_data = build_catalog_export_tag_data(
            track_id,
            track_service=track_service,
            release_service=release_service,
            include_artwork_bytes=include_artwork_bytes,
        )
    except Exception as exc:
        return False, f"catalog metadata was unavailable ({exc})"
    if not has_exportable_catalog_tag_data(tag_data):
        return False, "catalog metadata was empty, so no embedded tags were written"
    try:
        tag_service.write_tags(Path(destination_path), tag_data)
    except Exception as exc:
        return False, f"embedded metadata could not be written ({exc})"
    return True, None

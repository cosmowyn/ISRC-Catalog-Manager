"""Dry-run SoundCloud publication planning without network calls."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol

from isrc_manager.domain.codes import is_valid_isrc_compact_or_iso, to_iso_isrc

from .client import (
    SC_TRACK_FIELD_BPM,
    SC_TRACK_FIELD_PURCHASE_TITLE,
    SUPPORTED_LICENSES,
)
from .models import (
    SoundCloudPlanAction,
    SoundCloudPlanItemStatus,
    SoundCloudPreflightIssue,
    SoundCloudPreflightIssueCode,
    SoundCloudPreflightSeverity,
    SoundCloudPublishOptions,
    SoundCloudPublishPlanItem,
    SoundCloudPublishPlanResult,
    SoundCloudQuotaSnapshot,
    SoundCloudTrackMetadataPayload,
)

SUPPORTED_TRACK_SHARING = {"public", "private"}
AUDIO_BYTES_LIMIT = 4 * 1024 * 1024 * 1024
AUDIO_DURATION_LIMIT_SECONDS = 24 * 60 * 60
SUPPORTED_ARTWORK_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif"}
SUPPORTED_ARTWORK_MIME = {"image/jpeg", "image/png", "image/gif"}
SUPPORTED_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOW_REMAINING_RATE_LIMIT = 5


class SoundCloudTrackSnapshotProvider(Protocol):
    def get_track_snapshot(self, track_id: int) -> Mapping[str, Any] | None: ...


class SoundCloudReleaseSummaryProvider(Protocol):
    def get_release_summary(self, track_id: int) -> Mapping[str, Any] | None: ...


class SoundCloudMediaHandle(Protocol):
    filename: str
    mime_type: str | None
    size_bytes: int
    source_path: str | Path | None


class SoundCloudMediaProvider(Protocol):
    def get_audio_handle(self, track_id: int) -> SoundCloudMediaHandle | None: ...

    def get_effective_artwork_handle(
        self, track_id: int
    ) -> tuple[SoundCloudMediaHandle | None, bool]: ...


class SoundCloudPublicationLookup(Protocol):
    def find_publication(self, track_id: int) -> Mapping[str, Any] | None: ...


class SoundCloudAccountState(Protocol):
    def is_connected(self) -> bool: ...

    def get_quota_snapshot(self) -> SoundCloudQuotaSnapshot | None: ...


def _coalesce(*values: object) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _coerce_int(value: object | None) -> int | None:
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value)
        if value is None:
            return None
        return int(str(value))
    except Exception:
        return None


def _is_valid_release_date(value: str | None) -> bool:
    if not value:
        return False
    if not SUPPORTED_DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _is_artwork_handle_supported(handle: object) -> bool:
    if handle is None:
        return False
    filename = str(getattr(handle, "filename", "") or "")
    mime_type = str(getattr(handle, "mime_type", "") or "").lower()
    source = str(getattr(handle, "source_path", "") or "")
    extension = Path(filename).suffix.lower() or Path(source).suffix.lower()
    return extension in SUPPORTED_ARTWORK_EXTENSIONS or (mime_type in SUPPORTED_ARTWORK_MIME)


def _media_path(handle: object) -> str | None:
    if handle is None:
        return None
    source = str(getattr(handle, "source_path", "") or "").strip()
    if source:
        return source
    return None


def _status_from_issues(issues: list[SoundCloudPreflightIssue]) -> SoundCloudPlanItemStatus:
    if any(issue.is_blocking for issue in issues):
        return SoundCloudPlanItemStatus.BLOCKED
    if any(issue.severity == SoundCloudPreflightSeverity.WARNING for issue in issues):
        return SoundCloudPlanItemStatus.WARN
    return SoundCloudPlanItemStatus.READY


@dataclass(slots=True)
class _PlanInput:
    track_id: int
    track_snapshot: Mapping[str, Any]
    release_summary: Mapping[str, Any] | None
    audio_handle: SoundCloudMediaHandle | None
    artwork_handle: SoundCloudMediaHandle | None
    artwork_is_ambiguous: bool
    publication: Mapping[str, Any] | None
    connected: bool
    quota_snapshot: SoundCloudQuotaSnapshot | None
    options: SoundCloudPublishOptions


class SoundCloudPublishPlanner:
    """Builds deterministic, no-network publish plans."""

    def __init__(
        self,
        track_snapshot_provider: SoundCloudTrackSnapshotProvider,
        release_summary_provider: SoundCloudReleaseSummaryProvider,
        media_provider: SoundCloudMediaProvider,
        publication_lookup: SoundCloudPublicationLookup,
        account_state: SoundCloudAccountState,
    ) -> None:
        self.track_snapshot_provider = track_snapshot_provider
        self.release_summary_provider = release_summary_provider
        self.media_provider = media_provider
        self.publication_lookup = publication_lookup
        self.account_state = account_state

    def _track_lookup(self, track_id: int) -> Mapping[str, Any] | None:
        return self.track_snapshot_provider.get_track_snapshot(track_id)

    def _release_lookup(self, track_id: int) -> Mapping[str, Any] | None:
        return self.release_summary_provider.get_release_summary(track_id)

    def _media_lookup(
        self, track_id: int
    ) -> tuple[SoundCloudMediaHandle | None, SoundCloudMediaHandle | None, bool]:
        audio_handle = self.media_provider.get_audio_handle(track_id)
        artwork_handle, ambiguous = self.media_provider.get_effective_artwork_handle(track_id)
        return audio_handle, artwork_handle, ambiguous

    def _publication_lookup(self, track_id: int) -> Mapping[str, Any] | None:
        return self.publication_lookup.find_publication(track_id)

    def _add_issue(
        self,
        issues: list[SoundCloudPreflightIssue],
        code: SoundCloudPreflightIssueCode,
        severity: SoundCloudPreflightSeverity,
        message: str,
        detail: str | None = None,
    ) -> None:
        issues.append(
            SoundCloudPreflightIssue(
                code=code,
                severity=severity,
                message=message,
                detail=detail,
            )
        )

    def _issue_missing(self, track_id: int, detail: str | None = None) -> SoundCloudPublishPlanItem:
        issues: list[SoundCloudPreflightIssue] = [
            SoundCloudPreflightIssue(
                code=SoundCloudPreflightIssueCode.TRACK_NOT_FOUND,
                severity=SoundCloudPreflightSeverity.BLOCK,
                message=f"Track {track_id} could not be resolved from snapshot provider.",
                detail=detail,
            )
        ]
        return SoundCloudPublishPlanItem(
            track_id=track_id,
            status=SoundCloudPlanItemStatus.BLOCKED,
            action=SoundCloudPlanAction.SKIP,
            title="",
            remote_urn=None,
            remote_numeric_id=None,
            metadata=None,
            issues=issues,
            would_upload_audio=False,
        )

    def _validate_license(
        self,
        license_value: str | None,
        issues: list[SoundCloudPreflightIssue],
    ) -> str | None:
        normalized = _coalesce(license_value)
        if not normalized:
            return None
        normalized_lower = normalized.strip().lower()
        if normalized_lower not in SUPPORTED_LICENSES:
            self._add_issue(
                issues,
                SoundCloudPreflightIssueCode.LICENSE_INVALID,
                SoundCloudPreflightSeverity.BLOCK,
                "License value is not in the SoundCloud documented enum.",
                detail=normalized,
            )
            return None
        return normalized_lower

    def _validate_title(
        self, track_snapshot: Mapping[str, Any], issues: list[SoundCloudPreflightIssue]
    ) -> str:
        title = _coalesce(track_snapshot.get("track_title"), track_snapshot.get("title"))
        if not title:
            self._add_issue(
                issues,
                SoundCloudPreflightIssueCode.BLANK_TITLE,
                SoundCloudPreflightSeverity.BLOCK,
                "Track title is blank.",
            )
            return ""
        return title

    def _validate_release_date(
        self,
        track_snapshot: Mapping[str, Any],
        release_summary: Mapping[str, Any] | None,
        issues: list[SoundCloudPreflightIssue],
    ) -> str | None:
        track_date = _coalesce(
            track_snapshot.get("release_date"), track_snapshot.get("track_release_date")
        )
        if not track_date:
            return None
        if not _is_valid_release_date(track_date):
            self._add_issue(
                issues,
                SoundCloudPreflightIssueCode.INVALID_RELEASE_DATE,
                SoundCloudPreflightSeverity.WARNING,
                "Release date is not in YYYY-MM-DD format.",
                detail=track_date,
            )
            return None

        if not release_summary:
            return track_date

        candidate_dates: set[str] = set()
        for key in ("release_date", "effective_release_date"):
            if (candidate := _coalesce(release_summary.get(key))) is not None:
                if _is_valid_release_date(candidate):
                    candidate_dates.add(candidate)

        collection = release_summary.get("release_dates")
        if isinstance(collection, (list, tuple, set, frozenset)):
            for item in collection:
                if isinstance(item, str):
                    item_value = item.strip()
                else:
                    item_value = str(item or "").strip()
                if item_value and _is_valid_release_date(item_value):
                    candidate_dates.add(item_value)

        if not candidate_dates:
            return track_date
        if len(candidate_dates) > 1:
            self._add_issue(
                issues,
                SoundCloudPreflightIssueCode.RELEASE_DATE_CONFLICT,
                SoundCloudPreflightSeverity.WARNING,
                "Release date is ambiguous across release metadata.",
                detail=", ".join(sorted(candidate_dates)),
            )
            return None
        (candidate,) = tuple(candidate_dates)
        if candidate != track_date:
            self._add_issue(
                issues,
                SoundCloudPreflightIssueCode.RELEASE_DATE_CONFLICT,
                SoundCloudPreflightSeverity.WARNING,
                "Track and release dates do not match.",
                detail=f"{track_date} vs {candidate}",
            )
            return None
        return track_date

    def _resolve_release_text(
        self,
        release_summary: Mapping[str, Any] | None,
        singular: str,
        plural: str,
        issues: list[SoundCloudPreflightIssue],
    ) -> str | None:
        if not release_summary:
            return None
        direct = _coalesce(release_summary.get(singular))
        if direct:
            return direct
        values: list[str] = []
        for item in release_summary.get(plural, ()) or ():
            if isinstance(item, str):
                candidate = item.strip()
            else:
                candidate = str(item or "").strip()
            if candidate:
                values.append(candidate)
        unique = sorted(set(values))
        if not unique:
            return None
        if len(unique) == 1:
            return unique[0]
        self._add_issue(
            issues,
            SoundCloudPreflightIssueCode.METADATA_CONFLICT,
            SoundCloudPreflightSeverity.WARNING,
            f"Release {singular.replace('_', ' ')} is ambiguous.",
            detail=", ".join(unique),
        )
        return None

    def _resolve_artwork(
        self,
        handle: SoundCloudMediaHandle | None,
        ambiguous: bool,
        issues: list[SoundCloudPreflightIssue],
    ) -> str | None:
        if ambiguous:
            self._add_issue(
                issues,
                SoundCloudPreflightIssueCode.ARTWORK_AMBIGUOUS,
                SoundCloudPreflightSeverity.WARNING,
                "Track/album/release artwork source is ambiguous.",
            )
            return None
        if handle is None:
            return None
        if not _is_artwork_handle_supported(handle):
            self._add_issue(
                issues,
                SoundCloudPreflightIssueCode.ARTWORK_UNSUPPORTED,
                SoundCloudPreflightSeverity.WARNING,
                "Artwork format is unsupported for upload.",
                detail=str(getattr(handle, "filename", "")),
            )
            return None
        return _media_path(handle)

    def _validate_metadata_conflicts(
        self,
        track_snapshot: Mapping[str, Any],
        issues: list[SoundCloudPreflightIssue],
    ) -> None:
        unsupported = [
            (SC_TRACK_FIELD_BPM, "BPM"),
            (SC_TRACK_FIELD_PURCHASE_TITLE, "purchase_title"),
        ]
        for field, field_label in unsupported:
            value = track_snapshot.get(field, track_snapshot.get(field_label))
            if _coalesce(value) is not None:
                self._add_issue(
                    issues,
                    SoundCloudPreflightIssueCode.UNSUPPORTED_TRACK_FIELD,
                    SoundCloudPreflightSeverity.WARNING,
                    f"{field_label} is not supported by SoundCloud upload/update schema.",
                )

    def _validate_internal_notes(
        self, track_snapshot: Mapping[str, Any], issues: list[SoundCloudPreflightIssue]
    ) -> None:
        if _coalesce(
            track_snapshot.get("comments"),
            track_snapshot.get("internal_notes"),
            track_snapshot.get("notes"),
        ):
            self._add_issue(
                issues,
                SoundCloudPreflightIssueCode.INTERNAL_NOTES_OMITTED,
                SoundCloudPreflightSeverity.WARNING,
                "Internal notes are intentionally omitted from SoundCloud payloads.",
            )

    def _build_remote_identifier(
        self, publication: Mapping[str, Any] | None, issues: list[SoundCloudPreflightIssue]
    ) -> tuple[SoundCloudPlanAction, str | None, int | None]:
        if not publication:
            return SoundCloudPlanAction.CREATE, None, None

        remote_urn = _coalesce(publication.get("remote_urn"), publication.get("urn"))
        remote_numeric_id = _coerce_int(publication.get("remote_numeric_id"))
        if remote_numeric_id is None and remote_urn:
            remote_numeric_id = _coerce_int(str(remote_urn).rsplit(":", 1)[-1])
        if not remote_urn:
            self._add_issue(
                issues,
                SoundCloudPreflightIssueCode.UNCLEAR_UPDATE_ELIGIBILITY,
                SoundCloudPreflightSeverity.WARNING,
                "Existing publication has no canonical remote_urn.",
                detail=f"candidate_id={remote_numeric_id}",
            )
            return SoundCloudPlanAction.CREATE, None, remote_numeric_id
        return SoundCloudPlanAction.UPDATE, remote_urn, remote_numeric_id

    def _build_metadata(
        self,
        track_id: int,
        title: str,
        *,
        action: SoundCloudPlanAction,
        audio_handle: SoundCloudMediaHandle | None,
        track_snapshot: Mapping[str, Any],
        track_release_date: str | None,
        artwork_data: str | None,
        label_name: str | None,
        release: str | None,
        license_value: str | None,
        options: SoundCloudPublishOptions,
        issues: list[SoundCloudPreflightIssue],
    ) -> tuple[SoundCloudTrackMetadataPayload, bool]:
        asset_data: str | None = None
        would_upload_audio = False

        if action == SoundCloudPlanAction.CREATE:
            would_upload_audio = True
            if audio_handle is None:
                self._add_issue(
                    issues,
                    SoundCloudPreflightIssueCode.MISSING_AUDIO,
                    SoundCloudPreflightSeverity.BLOCK,
                    "Primary audio source is missing.",
                )
                would_upload_audio = False
            else:
                if audio_handle.size_bytes > AUDIO_BYTES_LIMIT:
                    self._add_issue(
                        issues,
                        SoundCloudPreflightIssueCode.TOO_LARGE_AUDIO,
                        SoundCloudPreflightSeverity.BLOCK,
                        "Audio file exceeds 4 GB.",
                        detail=str(audio_handle.size_bytes),
                    )
                asset_data = _media_path(audio_handle)
                if not asset_data:
                    self._add_issue(
                        issues,
                        SoundCloudPreflightIssueCode.MISSING_AUDIO,
                        SoundCloudPreflightSeverity.BLOCK,
                        "Primary audio source is not resolved to a readable file path.",
                        detail=str(getattr(audio_handle, "filename", "") or ""),
                    )
                    would_upload_audio = False
        else:
            would_upload_audio = False

        genre = _coalesce(track_snapshot.get("genre"))
        isrc_raw = _coalesce(track_snapshot.get("isrc"))
        isrc_value: str | None = None
        if isrc_raw:
            if not is_valid_isrc_compact_or_iso(isrc_raw):
                self._add_issue(
                    issues,
                    SoundCloudPreflightIssueCode.METADATA_CONFLICT,
                    SoundCloudPreflightSeverity.WARNING,
                    "ISRC is not in a valid format.",
                    detail=isrc_raw,
                )
            else:
                isrc_value = to_iso_isrc(isrc_raw)

        artist = _coalesce(
            track_snapshot.get("artist_name"),
            track_snapshot.get("artist"),
            track_snapshot.get("metadata_artist"),
        )
        publisher = _coalesce(track_snapshot.get("publisher"), track_snapshot.get("publisher_name"))
        composer = _coalesce(track_snapshot.get("composer"), track_snapshot.get("writer_composer"))
        album_title = _coalesce(track_snapshot.get("album_title"), track_snapshot.get("album"))
        upc_or_ean = _coalesce(
            track_snapshot.get("upc"),
            track_snapshot.get("ean"),
            track_snapshot.get("barcode"),
        )
        iswc = _coalesce(track_snapshot.get("iswc"))
        effective_label = _coalesce(options.record_label, label_name, publisher)
        effective_release = _coalesce(release, track_snapshot.get("release_title"), album_title)

        return (
            SoundCloudTrackMetadataPayload(
                track_id=track_id,
                title=title,
                asset_data=asset_data,
                description=_coalesce(options.description),
                genre=genre,
                isrc=isrc_value,
                release_date=track_release_date,
                artwork_data=artwork_data,
                label_name=effective_label,
                release=effective_release,
                metadata_artist=artist,
                publisher=publisher,
                composer=composer,
                album_title=album_title,
                upc_or_ean=upc_or_ean,
                iswc=iswc,
                p_line=_coalesce(
                    track_snapshot.get("soundcloud_p_line"), track_snapshot.get("p_line")
                ),
                contains_music=options.contains_music,
                contains_explicit=options.contains_explicit,
                license=license_value,
            ),
            would_upload_audio,
        )

    def _plan_single(self, plan_input: _PlanInput) -> SoundCloudPublishPlanItem:
        track_snapshot = plan_input.track_snapshot
        issues: list[SoundCloudPreflightIssue] = []
        if not plan_input.connected:
            self._add_issue(
                issues,
                SoundCloudPreflightIssueCode.DISCONNECTED_ACCOUNT,
                SoundCloudPreflightSeverity.BLOCK,
                "SoundCloud account is not connected.",
            )

        title = self._validate_title(track_snapshot, issues)
        track_id = plan_input.track_id

        action, remote_urn, remote_numeric_id = self._build_remote_identifier(
            plan_input.publication, issues
        )

        duration_seconds = _coerce_int(
            _coalesce(track_snapshot.get("audio_duration_seconds"), track_snapshot.get("duration"))
        )
        if duration_seconds is not None and duration_seconds > AUDIO_DURATION_LIMIT_SECONDS:
            self._add_issue(
                issues,
                SoundCloudPreflightIssueCode.LONG_DURATION,
                SoundCloudPreflightSeverity.BLOCK,
                "Track duration exceeds 24 hours.",
                detail=f"{duration_seconds} sec",
            )

        release_date = self._validate_release_date(
            track_snapshot, plan_input.release_summary, issues
        )
        release = self._resolve_release_text(
            plan_input.release_summary,
            singular="release_title",
            plural="release_titles",
            issues=issues,
        )
        label_name = self._resolve_release_text(
            plan_input.release_summary, singular="label_name", plural="label_names", issues=issues
        )
        artwork_data = self._resolve_artwork(
            plan_input.artwork_handle, plan_input.artwork_is_ambiguous, issues
        )

        license_raw = _coalesce(plan_input.options.license, track_snapshot.get("license"))
        license_value = self._validate_license(license_raw, issues)

        self._validate_metadata_conflicts(track_snapshot, issues)
        self._validate_internal_notes(track_snapshot, issues)

        if plan_input.quota_snapshot is None:
            self._add_issue(
                issues,
                SoundCloudPreflightIssueCode.MISSING_QUOTA_SNAPSHOT,
                SoundCloudPreflightSeverity.WARNING,
                "Quota snapshot unavailable.",
            )
        else:
            if plan_input.quota_snapshot.quota_exhausted:
                self._add_issue(
                    issues,
                    SoundCloudPreflightIssueCode.EXPLICIT_QUOTA_EXHAUSTION,
                    SoundCloudPreflightSeverity.BLOCK,
                    "Quota snapshot reports no remaining uploads.",
                    detail=f"daily={plan_input.quota_snapshot.daily_remaining_uploads}, hourly={plan_input.quota_snapshot.hourly_remaining_uploads}",
                )
            if (
                plan_input.quota_snapshot.rate_limit_remaining is not None
                and 0 < plan_input.quota_snapshot.rate_limit_remaining <= LOW_REMAINING_RATE_LIMIT
            ):
                self._add_issue(
                    issues,
                    SoundCloudPreflightIssueCode.RATE_LIMIT_POTENTIAL,
                    SoundCloudPreflightSeverity.WARNING,
                    "Upload rate-limit remaining is low.",
                    detail=str(plan_input.quota_snapshot.rate_limit_remaining),
                )
            if plan_input.quota_snapshot.rate_limit_remaining == 0:
                self._add_issue(
                    issues,
                    SoundCloudPreflightIssueCode.RATE_LIMIT_POTENTIAL,
                    SoundCloudPreflightSeverity.WARNING,
                    "API rate-limit remaining is zero; SoundCloud may throttle this run.",
                    detail=plan_input.quota_snapshot.rate_limit_reset,
                )

        metadata, would_upload_audio = self._build_metadata(
            track_id=track_id,
            title=title,
            action=action,
            audio_handle=plan_input.audio_handle,
            track_snapshot=track_snapshot,
            track_release_date=release_date,
            artwork_data=artwork_data,
            label_name=label_name,
            release=release,
            license_value=license_value,
            options=plan_input.options,
            issues=issues,
        )

        return SoundCloudPublishPlanItem(
            track_id=track_id,
            status=_status_from_issues(issues),
            action=action,
            title=title,
            remote_urn=remote_urn,
            remote_numeric_id=remote_numeric_id,
            metadata=metadata,
            issues=issues,
            would_upload_audio=would_upload_audio,
        )

    def plan_tracks(
        self, track_ids: list[int], options: SoundCloudPublishOptions | None = None
    ) -> SoundCloudPublishPlanResult:
        plan_options = options or SoundCloudPublishOptions()
        quota_snapshot = self.account_state.get_quota_snapshot() if self.account_state else None
        connected = bool(self.account_state.is_connected()) if self.account_state else False
        items: list[SoundCloudPublishPlanItem] = []

        for track_id in track_ids:
            snapshot = self._track_lookup(track_id)
            if snapshot is None:
                items.append(self._issue_missing(track_id))
                continue

            audio_handle, artwork_handle, artwork_ambiguous = self._media_lookup(track_id)
            publication = self._publication_lookup(track_id)
            release_summary = self._release_lookup(track_id)
            item = self._plan_single(
                _PlanInput(
                    track_id=track_id,
                    track_snapshot=snapshot,
                    release_summary=release_summary,
                    audio_handle=audio_handle,
                    artwork_handle=artwork_handle,
                    artwork_is_ambiguous=artwork_ambiguous,
                    publication=publication,
                    connected=connected,
                    quota_snapshot=quota_snapshot,
                    options=plan_options,
                )
            )
            items.append(item)

        return SoundCloudPublishPlanResult(
            track_ids=tuple(track_ids),
            items=tuple(items),
            options=plan_options,
            quota_snapshot=quota_snapshot,
        )


__all__ = [
    "SoundCloudPublishPlanner",
    "SUPPORTED_TRACK_SHARING",
    "AUDIO_BYTES_LIMIT",
    "AUDIO_DURATION_LIMIT_SECONDS",
]

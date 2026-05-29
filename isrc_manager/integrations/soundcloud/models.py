from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any


def _optional_int(value: object | None) -> int | None:
    if value is None:
        return None
    return int(str(value))


class SoundCloudPreflightSeverity(str, Enum):
    """Issue severity used during dry-run preflight."""

    BLOCK = "block"
    WARNING = "warning"


class SoundCloudPreflightIssueCode(str, Enum):
    """Machine-readable issue types for preflight planning."""

    DISCONNECTED_ACCOUNT = "disconnected_account"
    BLANK_TITLE = "blank_title"
    MISSING_AUDIO = "missing_audio"
    MISSING_QUOTA_SNAPSHOT = "missing_quota_snapshot"
    EXPLICIT_QUOTA_EXHAUSTION = "explicit_quota_exhaustion"
    RATE_LIMIT_POTENTIAL = "rate_limit_potential"
    TRACK_NOT_FOUND = "track_not_found"
    QUOTA_WARNING = "quota_warning"
    TOO_LARGE_AUDIO = "too_large_audio"
    LONG_DURATION = "long_duration"
    INVALID_RELEASE_DATE = "invalid_release_date"
    RELEASE_DATE_CONFLICT = "release_date_conflict"
    RELEASE_LABEL_CONFLICT = "release_label_conflict"
    ARTWORK_UNSUPPORTED = "artwork_unsupported"
    ARTWORK_AMBIGUOUS = "artwork_ambiguous"
    METADATA_CONFLICT = "metadata_conflict"
    UNSUPPORTED_TRACK_FIELD = "unsupported_track_field"
    LICENSE_INVALID = "license_invalid"
    INTERNAL_NOTES_OMITTED = "internal_notes_omitted"
    UNCLEAR_UPDATE_ELIGIBILITY = "unclear_update_eligibility"


class SoundCloudPlanAction(str, Enum):
    """Planned publication action."""

    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"


class SoundCloudPlanItemStatus(str, Enum):
    """Plan state returned from the preflight planner."""

    READY = "ready"
    WARN = "warn"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class SoundCloudTokenKind(str, Enum):
    """Execution token persistence status."""

    SESSION = "session"
    PERSISTENT = "persistent"


class SoundCloudExecutionStatus(str, Enum):
    """Execution run status values."""

    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SoundCloudExecutionItemStatus(str, Enum):
    """Publish run item status values."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SKIPPED = "skipped"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class SoundCloudPublishOptions:
    """Per-run defaults and optional SoundCloud upload options."""

    sharing: str = "private"
    tag_list: str | None = None
    description: str | None = None
    downloadable: bool = False
    streamable: bool = True
    commentable: bool = True
    reveal_stats: bool = True
    reveal_comments: bool = True
    purchase_url: str | None = None
    record_label: str | None = None
    contains_music: bool = True
    contains_explicit: bool = False
    license: str | None = None


@dataclass(frozen=True, slots=True)
class SoundCloudTrackMetadataPayload:
    """Computed request payload for a planned SoundCloud track publish."""

    track_id: int
    title: str
    asset_data: str | None
    description: str | None = None
    genre: str | None = None
    isrc: str | None = None
    release_date: str | None = None
    artwork_data: str | None = None
    label_name: str | None = None
    release: str | None = None
    metadata_artist: str | None = None
    publisher: str | None = None
    composer: str | None = None
    album_title: str | None = None
    upc_or_ean: str | None = None
    iswc: str | None = None
    p_line: str | None = None
    contains_music: bool | None = None
    contains_explicit: bool | None = None
    license: str | None = None


@dataclass(frozen=True, slots=True)
class SoundCloudQuotaSnapshot:
    """Snapshot of account/upload quota and rate-limit metadata."""

    daily_remaining_uploads: int | None = None
    daily_upload_limit: int | None = None
    hourly_remaining_uploads: int | None = None
    hourly_upload_limit: int | None = None
    rate_limit_remaining: int | None = None
    rate_limit_reset: str | None = None
    rate_limit_reset_seconds: int | None = None

    @property
    def quota_exhausted(self) -> bool:
        if self.daily_remaining_uploads is not None and self.daily_remaining_uploads <= 0:
            return True
        if self.hourly_remaining_uploads is not None and self.hourly_remaining_uploads <= 0:
            return True
        return False

    @property
    def rate_limited(self) -> bool:
        return (
            self.rate_limit_remaining is not None
            and self.rate_limit_remaining <= 5
            and self.rate_limit_remaining > 0
        )


@dataclass(frozen=True, slots=True)
class SoundCloudPreflightIssue:
    """One issue from the dry-run preflight."""

    code: SoundCloudPreflightIssueCode
    severity: SoundCloudPreflightSeverity
    message: str
    detail: str | None = None

    @property
    def is_blocking(self) -> bool:
        return self.severity == SoundCloudPreflightSeverity.BLOCK


@dataclass(frozen=True, slots=True)
class SoundCloudPublishPlanItem:
    """Result row for one track selected for publishing."""

    track_id: int
    status: SoundCloudPlanItemStatus
    action: SoundCloudPlanAction
    title: str
    remote_urn: str | None = None
    remote_numeric_id: int | None = None
    metadata: SoundCloudTrackMetadataPayload | None = None
    issues: list[SoundCloudPreflightIssue] = field(default_factory=list)
    would_upload_audio: bool = False


@dataclass(frozen=True, slots=True)
class SoundCloudPublishPlanResult:
    """Final preflight plan for a set of tracks."""

    track_ids: tuple[int, ...]
    items: tuple[SoundCloudPublishPlanItem, ...]
    options: SoundCloudPublishOptions
    quota_snapshot: SoundCloudQuotaSnapshot | None = None

    @property
    def has_blocking_items(self) -> bool:
        return any(item.status == SoundCloudPlanItemStatus.BLOCKED for item in self.items)

    @property
    def has_warning_items(self) -> bool:
        return any(item.status == SoundCloudPlanItemStatus.WARN for item in self.items)

    @property
    def ready_items(self) -> tuple[SoundCloudPublishPlanItem, ...]:
        return tuple(item for item in self.items if item.status == SoundCloudPlanItemStatus.READY)


@dataclass(frozen=True, slots=True)
class SoundCloudOAuthTokenBundle:
    """Token bundle returned by SoundCloud OAuth endpoints."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    scope: str | None = None
    expires_in: int | None = None
    issued_at: str | None = None
    expires_at: str | None = None

    def __repr__(self) -> str:
        return (
            "SoundCloudOAuthTokenBundle("
            "access_token='***', refresh_token='***', "
            f"token_type={self.token_type!r}, scope={self.scope!r}, "
            f"expires_in={self.expires_in!r}, issued_at={self.issued_at!r}, "
            f"expires_at={self.expires_at!r})"
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        if now is None:
            now = datetime.now(timezone.utc)
        try:
            if self.expires_at.endswith("Z"):
                expiry = datetime.fromisoformat(self.expires_at[:-1] + "+00:00")
            else:
                expiry = datetime.fromisoformat(self.expires_at)
        except Exception:
            return False
        return expiry <= now

    def to_record(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "scope": self.scope,
            "expires_in": self.expires_in,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_record(cls, payload: dict[str, Any]) -> "SoundCloudOAuthTokenBundle":
        return cls(
            access_token=str(payload.get("access_token")),
            refresh_token=str(payload.get("refresh_token")),
            token_type=str(payload.get("token_type") or "Bearer"),
            scope=(str(payload.get("scope")) if payload.get("scope") is not None else None),
            expires_in=_optional_int(payload.get("expires_in")),
            issued_at=(
                str(payload.get("issued_at")) if payload.get("issued_at") is not None else None
            ),
            expires_at=(
                str(payload.get("expires_at")) if payload.get("expires_at") is not None else None
            ),
        )


if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True)
class SoundCloudPublishExecutionItemResult:
    """Execution result for one run item."""

    track_id: int
    status: SoundCloudExecutionItemStatus
    action: SoundCloudPlanAction
    operation_message: str | None = None
    remote_urn: str | None = None
    remote_numeric_id: int | None = None
    remote_url: str | None = None
    metadata_hash: str | None = None
    audio_hash: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SoundCloudPublishExecutionResult:
    """Outcome summary for a whole run."""

    run_id: int
    status: SoundCloudExecutionStatus
    items_total: int
    items_succeeded: int
    items_failed: int
    items_skipped: int
    item_results: tuple[SoundCloudPublishExecutionItemResult, ...]


__all__ = [
    "SoundCloudPlanAction",
    "SoundCloudPlanItemStatus",
    "SoundCloudExecutionItemStatus",
    "SoundCloudExecutionStatus",
    "SoundCloudPlanItemStatus",
    "SoundCloudPreflightIssue",
    "SoundCloudPreflightIssueCode",
    "SoundCloudPreflightSeverity",
    "SoundCloudPublishOptions",
    "SoundCloudPublishPlanItem",
    "SoundCloudPublishPlanResult",
    "SoundCloudQuotaSnapshot",
    "SoundCloudTrackMetadataPayload",
    "SoundCloudOAuthTokenBundle",
    "SoundCloudPublishExecutionItemResult",
    "SoundCloudPublishExecutionResult",
    "SoundCloudTokenKind",
]

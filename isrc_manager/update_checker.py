"""Safe update-manifest fetching and comparison."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Callable
from urllib.parse import urlparse

from .versioning import SemVer, SemVerError

RELEASE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/cosmowyn/ISRC-Catalog-Manager/main/"
    "docs/releases/latest.json"
)
DEFAULT_UPDATE_TIMEOUT_SECONDS = 4.0
MAX_MANIFEST_BYTES = 64 * 1024


class UpdateCheckStatus:
    UPDATE_AVAILABLE = "update_available"
    CURRENT = "current"
    IGNORED = "ignored"
    FAILED = "failed"


class UpdateCheckError(RuntimeError):
    """Raised for recoverable update-check failures."""


FetchManifest = Callable[[str, float], bytes]


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    version: str
    released_at: str
    summary: str
    release_notes_url: str
    minimum_supported_version: str | None = None

    @classmethod
    def from_json_bytes(cls, data: bytes) -> "ReleaseManifest":
        try:
            payload = json.loads(data.decode("utf-8"))
        except Exception as exc:
            raise UpdateCheckError("Update information could not be decoded.") from exc
        if not isinstance(payload, dict):
            raise UpdateCheckError("Update information has an invalid format.")
        return cls.from_mapping(payload)

    @classmethod
    def from_mapping(cls, payload: dict[str, object]) -> "ReleaseManifest":
        version = _required_text(payload, "version")
        SemVer.parse(version)
        released_at = _required_text(payload, "released_at")
        _parse_iso_date(released_at)
        summary = _required_text(payload, "summary")
        release_notes_url = _required_text(payload, "release_notes_url")
        _validate_https_url(release_notes_url, field_name="release_notes_url")
        minimum_supported = payload.get("minimum_supported_version")
        if minimum_supported in (None, ""):
            clean_minimum = None
        else:
            clean_minimum = str(minimum_supported).strip()
            SemVer.parse(clean_minimum)
        return cls(
            version=version,
            released_at=released_at,
            summary=summary,
            release_notes_url=release_notes_url,
            minimum_supported_version=clean_minimum,
        )


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    status: str
    current_version: str
    latest_version: str | None = None
    manifest: ReleaseManifest | None = None
    message: str = ""

    @property
    def update_available(self) -> bool:
        return self.status == UpdateCheckStatus.UPDATE_AVAILABLE and self.manifest is not None


class UpdateChecker:
    """Fetch and evaluate the repo-backed release manifest."""

    def __init__(
        self,
        *,
        manifest_url: str = RELEASE_MANIFEST_URL,
        timeout_seconds: float = DEFAULT_UPDATE_TIMEOUT_SECONDS,
        fetcher: FetchManifest | None = None,
    ) -> None:
        _validate_https_url(manifest_url, field_name="manifest_url")
        self.manifest_url = manifest_url
        self.timeout_seconds = float(timeout_seconds)
        self.fetcher = fetcher or fetch_manifest_bytes

    def check(
        self, current_version: object, *, ignored_version: object | None = None
    ) -> UpdateCheckResult:
        current_text = str(current_version or "").strip()
        try:
            current = SemVer.parse(current_text)
        except SemVerError:
            return UpdateCheckResult(
                status=UpdateCheckStatus.FAILED,
                current_version=current_text,
                message="The installed app version is not valid.",
            )
        try:
            manifest = ReleaseManifest.from_json_bytes(
                self.fetcher(self.manifest_url, self.timeout_seconds)
            )
            latest = SemVer.parse(manifest.version)
        except Exception:
            return UpdateCheckResult(
                status=UpdateCheckStatus.FAILED,
                current_version=current_text,
                message="Update information is unavailable right now.",
            )
        if latest <= current:
            return UpdateCheckResult(
                status=UpdateCheckStatus.CURRENT,
                current_version=current.without_build,
                latest_version=latest.without_build,
                manifest=manifest,
                message="You are running the latest available version.",
            )
        ignored_text = str(ignored_version or "").strip()
        if ignored_text:
            try:
                ignored = SemVer.parse(ignored_text)
            except SemVerError:
                ignored = None
            if ignored is not None and ignored == latest:
                return UpdateCheckResult(
                    status=UpdateCheckStatus.IGNORED,
                    current_version=current.without_build,
                    latest_version=latest.without_build,
                    manifest=manifest,
                    message="This update has been ignored.",
                )
        return UpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            current_version=current.without_build,
            latest_version=latest.without_build,
            manifest=manifest,
            message="A newer version is available.",
        )


def fetch_manifest_bytes(url: str, timeout_seconds: float) -> bytes:
    _validate_https_url(url, field_name="manifest_url")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ISRC-Catalog-Manager-Update-Check",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=float(timeout_seconds)) as response:
            data = bytes(response.read(MAX_MANIFEST_BYTES + 1))
    except (OSError, TimeoutError, socket.timeout, urllib.error.URLError) as exc:
        raise UpdateCheckError("Update information is unavailable right now.") from exc
    if len(data) > MAX_MANIFEST_BYTES:
        raise UpdateCheckError("Update information is too large.")
    return data


def _required_text(payload: dict[str, object], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise UpdateCheckError(f"Update information is missing {key}.")
    return value


def _parse_iso_date(value: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise UpdateCheckError("Update release date is invalid.") from exc


def _validate_https_url(url: str, *, field_name: str) -> None:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise UpdateCheckError(f"{field_name} must be an HTTPS URL.")

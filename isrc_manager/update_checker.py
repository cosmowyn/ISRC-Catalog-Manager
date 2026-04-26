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
    "https://github.com/cosmowyn/ISRC-Catalog-Manager/releases/latest/download/latest.json"
)
DEFAULT_UPDATE_TIMEOUT_SECONDS = 4.0
DEFAULT_RELEASE_NOTES_TIMEOUT_SECONDS = 6.0
MAX_MANIFEST_BYTES = 64 * 1024
MAX_RELEASE_NOTES_BYTES = 512 * 1024
SUPPORTED_RELEASE_ASSET_PLATFORMS = ("windows", "macos", "linux")


class UpdateCheckStatus:
    UPDATE_AVAILABLE = "update_available"
    CURRENT = "current"
    IGNORED = "ignored"
    FAILED = "failed"


class UpdateCheckError(RuntimeError):
    """Raised for recoverable update-check failures."""


FetchManifest = Callable[[str, float], bytes]


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    url: str
    sha256: str

    @classmethod
    def from_mapping(cls, platform_key: str, payload: object) -> "ReleaseAsset":
        if not isinstance(payload, dict):
            raise UpdateCheckError(f"Update asset for {platform_key} has an invalid format.")
        name = _required_text(payload, "name")
        if "/" in name or "\\" in name:
            raise UpdateCheckError(f"Update asset for {platform_key} has an invalid name.")
        url = _required_text(payload, "url")
        _validate_https_url(url, field_name=f"assets.{platform_key}.url")
        sha256 = _required_text(payload, "sha256").lower()
        _validate_sha256(sha256, field_name=f"assets.{platform_key}.sha256")
        return cls(name=name, url=url, sha256=sha256)


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    version: str
    released_at: str
    summary: str
    release_notes_url: str
    assets: dict[str, ReleaseAsset]
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
        assets = _release_assets_from_mapping(payload.get("assets"))
        _validate_asset_version_binding(assets, version)
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
            assets=assets,
            minimum_supported_version=clean_minimum,
        )

    def asset_for_platform(self, platform_key: str) -> ReleaseAsset:
        clean_key = str(platform_key or "").strip().lower()
        try:
            return self.assets[clean_key]
        except KeyError as exc:
            raise UpdateCheckError(
                f"No update package is available for {clean_key or 'this platform'}."
            ) from exc


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
    """Fetch and evaluate the GitHub Release update manifest."""

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
    return _fetch_https_bytes(
        url,
        float(timeout_seconds),
        field_name="manifest_url",
        accept="application/json",
        max_bytes=MAX_MANIFEST_BYTES,
        too_large_message="Update information is too large.",
    )


def fetch_release_notes_text(
    url: str,
    timeout_seconds: float = DEFAULT_RELEASE_NOTES_TIMEOUT_SECONDS,
    *,
    fetcher: FetchManifest | None = None,
) -> str:
    notes_url = resolve_release_notes_fetch_url(url)
    _validate_https_url(notes_url, field_name="release_notes_url")
    fetch_notes = fetcher or _fetch_release_notes_bytes
    data = fetch_notes(notes_url, float(timeout_seconds))
    if len(data) > MAX_RELEASE_NOTES_BYTES:
        raise UpdateCheckError("Release notes are too large.")
    try:
        return data.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise UpdateCheckError("Release notes could not be decoded.") from exc


def resolve_release_notes_fetch_url(url: str) -> str:
    """Return the direct content URL used by the in-app release notes viewer."""

    candidate = str(url or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme == "https" and parsed.netloc.lower() == "github.com":
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 5 and path_parts[2] == "blob":
            owner, repo, _blob, ref = path_parts[:4]
            release_path = "/".join(path_parts[4:])
            if owner and repo and ref and release_path:
                return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/" f"{release_path}"
    return candidate


def _fetch_release_notes_bytes(url: str, timeout_seconds: float) -> bytes:
    return _fetch_https_bytes(
        url,
        float(timeout_seconds),
        field_name="release_notes_url",
        accept="text/markdown, text/plain, */*",
        max_bytes=MAX_RELEASE_NOTES_BYTES,
        too_large_message="Release notes are too large.",
    )


def _fetch_https_bytes(
    url: str,
    timeout_seconds: float,
    *,
    field_name: str,
    accept: str,
    max_bytes: int,
    too_large_message: str,
) -> bytes:
    _validate_https_url(url, field_name=field_name)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "ISRC-Catalog-Manager-Update-Check",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = bytes(response.read(max_bytes + 1))
    except (OSError, TimeoutError, socket.timeout, urllib.error.URLError) as exc:
        raise UpdateCheckError("Update information is unavailable right now.") from exc
    if len(data) > max_bytes:
        raise UpdateCheckError(too_large_message)
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


def _validate_sha256(value: str, *, field_name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise UpdateCheckError(f"{field_name} must be a lowercase SHA256 hex digest.")


def _release_assets_from_mapping(payload: object) -> dict[str, ReleaseAsset]:
    if not isinstance(payload, dict):
        raise UpdateCheckError("Update information is missing platform assets.")
    assets: dict[str, ReleaseAsset] = {}
    for platform_key in SUPPORTED_RELEASE_ASSET_PLATFORMS:
        if platform_key not in payload:
            raise UpdateCheckError(f"Update information is missing the {platform_key} asset.")
        assets[platform_key] = ReleaseAsset.from_mapping(platform_key, payload[platform_key])
    extra_keys = sorted(set(str(key) for key in payload) - set(SUPPORTED_RELEASE_ASSET_PLATFORMS))
    if extra_keys:
        raise UpdateCheckError("Update information contains unsupported platform assets.")
    return assets


def _validate_asset_version_binding(assets: dict[str, ReleaseAsset], version: str) -> None:
    release_tag = f"v{version}"
    release_path = f"/releases/download/{release_tag}/"
    for platform_key, asset in assets.items():
        if release_tag not in asset.name or release_path not in asset.url:
            raise UpdateCheckError(
                f"Update asset for {platform_key} does not match release {release_tag}."
            )

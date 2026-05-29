"""SoundCloud request construction, transport safety, and API client helpers."""

from __future__ import annotations

import base64
import json as jsonlib
import logging
import mimetypes
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from .models import SoundCloudOAuthTokenBundle, SoundCloudPublishOptions, SoundCloudQuotaSnapshot

LOGGER = logging.getLogger("ISRCManager.soundcloud")
RICH_METADATA_SYNC_WARNING = "rich_metadata_sync_rejected"
RICH_METADATA_SYNC_WARNING_MESSAGE = (
    "SoundCloud accepted the public track update, but rejected web-editor rich metadata."
)

SC_TRACK_FIELD_TITLE = "track[title]"
SC_TRACK_FIELD_ASSET_DATA = "track[asset_data]"
SC_TRACK_FIELD_GENRE = "track[genre]"
SC_TRACK_FIELD_ISRC = "track[isrc]"
SC_TRACK_FIELD_RELEASE_DATE = "track[release_date]"
SC_TRACK_FIELD_ARTWORK_DATA = "track[artwork_data]"
SC_TRACK_FIELD_LABEL_NAME = "track[label_name]"
SC_TRACK_FIELD_RELEASE = "track[release]"
SC_TRACK_FIELD_LICENSE = "track[license]"
SC_TRACK_FIELD_DESCRIPTION = "track[description]"
SC_TRACK_FIELD_SHARING = "track[sharing]"
SC_TRACK_FIELD_TAG_LIST = "track[tag_list]"
SC_TRACK_FIELD_DOWNLOADABLE = "track[downloadable]"
SC_TRACK_FIELD_STREAMABLE = "track[streamable]"
SC_TRACK_FIELD_COMMENTABLE = "track[commentable]"
SC_TRACK_FIELD_REVEAL_STATS = "track[reveal_stats]"
SC_TRACK_FIELD_REVEAL_COMMENTS = "track[reveal_comments]"
SC_TRACK_FIELD_PURCHASE_URL = "track[purchase_url]"
SC_TRACK_FIELD_PURCHASE_TITLE = "track[purchase_title]"
SC_TRACK_FIELD_METADATA_ARTIST = "track[metadata_artist]"
SC_TRACK_FIELD_BPM = "track[bpm]"
SC_TRACK_FIELD_PUBLISHER_METADATA_ARTIST = "track[publisher_metadata][artist]"
SC_TRACK_FIELD_PUBLISHER_METADATA_PUBLISHER = "track[publisher_metadata][publisher]"
SC_TRACK_FIELD_PUBLISHER_METADATA_COMPOSER = "track[publisher_metadata][writer_composer]"
SC_TRACK_FIELD_PUBLISHER_METADATA_RELEASE_TITLE = "track[publisher_metadata][release_title]"
SC_TRACK_FIELD_PUBLISHER_METADATA_ALBUM_TITLE = "track[publisher_metadata][album_title]"
SC_TRACK_FIELD_PUBLISHER_METADATA_UPC_OR_EAN = "track[publisher_metadata][upc_or_ean]"
SC_TRACK_FIELD_PUBLISHER_METADATA_ISRC = "track[publisher_metadata][isrc]"
SC_TRACK_FIELD_PUBLISHER_METADATA_ISWC = "track[publisher_metadata][iswc]"
SC_TRACK_FIELD_PUBLISHER_METADATA_P_LINE = "track[publisher_metadata][p_line]"
SC_TRACK_FIELD_PUBLISHER_METADATA_CONTAINS_MUSIC = "track[publisher_metadata][contains_music]"
SC_TRACK_FIELD_PUBLISHER_METADATA_EXPLICIT = "track[publisher_metadata][explicit]"

SUPPORTED_TRACK_WRITE_FIELDS = frozenset(
    {
        SC_TRACK_FIELD_TITLE,
        SC_TRACK_FIELD_ASSET_DATA,
        SC_TRACK_FIELD_GENRE,
        SC_TRACK_FIELD_ISRC,
        SC_TRACK_FIELD_RELEASE_DATE,
        SC_TRACK_FIELD_ARTWORK_DATA,
        SC_TRACK_FIELD_LABEL_NAME,
        SC_TRACK_FIELD_RELEASE,
        SC_TRACK_FIELD_LICENSE,
        SC_TRACK_FIELD_DESCRIPTION,
        SC_TRACK_FIELD_SHARING,
        SC_TRACK_FIELD_TAG_LIST,
        SC_TRACK_FIELD_DOWNLOADABLE,
        SC_TRACK_FIELD_STREAMABLE,
        SC_TRACK_FIELD_COMMENTABLE,
        SC_TRACK_FIELD_REVEAL_STATS,
        SC_TRACK_FIELD_REVEAL_COMMENTS,
        SC_TRACK_FIELD_PURCHASE_URL,
        SC_TRACK_FIELD_METADATA_ARTIST,
        SC_TRACK_FIELD_PUBLISHER_METADATA_ARTIST,
        SC_TRACK_FIELD_PUBLISHER_METADATA_PUBLISHER,
        SC_TRACK_FIELD_PUBLISHER_METADATA_COMPOSER,
        SC_TRACK_FIELD_PUBLISHER_METADATA_RELEASE_TITLE,
        SC_TRACK_FIELD_PUBLISHER_METADATA_ALBUM_TITLE,
        SC_TRACK_FIELD_PUBLISHER_METADATA_UPC_OR_EAN,
        SC_TRACK_FIELD_PUBLISHER_METADATA_ISRC,
        SC_TRACK_FIELD_PUBLISHER_METADATA_ISWC,
        SC_TRACK_FIELD_PUBLISHER_METADATA_P_LINE,
        SC_TRACK_FIELD_PUBLISHER_METADATA_CONTAINS_MUSIC,
        SC_TRACK_FIELD_PUBLISHER_METADATA_EXPLICIT,
    }
)

UNSUPPORTED_WRITABLE_TRACK_FIELDS = frozenset({SC_TRACK_FIELD_BPM, SC_TRACK_FIELD_PURCHASE_TITLE})


class SoundCloudLicense(str, Enum):
    """Known SoundCloud upload license values."""

    ALL_RIGHTS_RESERVED = "all-rights-reserved"
    CC_BY = "cc-by"
    CC_BY_NC = "cc-by-nc"
    CC_BY_ND = "cc-by-nd"
    CC_BY_SA = "cc-by-sa"
    CC_BY_NC_SA = "cc-by-nc-sa"
    CC_BY_NC_ND = "cc-by-nc-nd"
    CC0 = "cc0"
    PUBLIC_DOMAIN = "public-domain"


SUPPORTED_LICENSES = frozenset(item.value for item in SoundCloudLicense)


SoundCloudFileValue = str | Path | tuple[str, bytes, str]


@dataclass(frozen=True, slots=True)
class SoundCloudTransportResponse:
    """Normalized HTTP response returned by fake or live transports."""

    status_code: int
    headers: Mapping[str, str]
    body: Any


class SoundCloudTransport(Protocol):
    """Minimal fakeable transport contract."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, object] | None = None,
        data: Mapping[str, object] | None = None,
        json: Mapping[str, object] | None = None,
        files: Mapping[str, SoundCloudFileValue] | None = None,
        timeout_seconds: float | None = None,
    ) -> SoundCloudTransportResponse: ...


class SoundCloudAPIError(RuntimeError):
    """Redacted SoundCloud API failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        url: str | None = None,
        rate_limit: "SoundCloudRateLimitError | None" = None,
    ) -> None:
        self.status_code = status_code
        self.url = redact_text(url or "")
        self.rate_limit = rate_limit
        super().__init__(redact_text(message))


class SoundCloudMalformedResponseError(SoundCloudAPIError):
    """Raised when SoundCloud returns a response that cannot be used safely."""


class UrllibSoundCloudTransport:
    """Small stdlib HTTP transport for live SoundCloud calls.

    Tests use fake transports; this class is the production boundary for real HTTP.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, object] | None = None,
        data: Mapping[str, object] | None = None,
        json: Mapping[str, object] | None = None,
        files: Mapping[str, SoundCloudFileValue] | None = None,
        timeout_seconds: float | None = None,
    ) -> SoundCloudTransportResponse:
        final_url = _url_with_params(url, params)
        final_headers = dict(headers or {})
        body: bytes | None = None
        if files:
            body, content_type = _encode_multipart(data or {}, files)
            final_headers["Content-Type"] = content_type
        elif json is not None:
            body = jsonlib.dumps(dict(json), separators=(",", ":")).encode("utf-8")
            final_headers["Content-Type"] = "application/json"
        elif data is not None:
            body = urllib.parse.urlencode(
                {str(key): str(value) for key, value in data.items()}
            ).encode("utf-8")
            final_headers["Content-Type"] = "application/x-www-form-urlencoded"

        request = urllib.request.Request(
            final_url,
            data=body,
            headers=final_headers,
            method=str(method or "GET").upper(),
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout_seconds if timeout_seconds is not None else 60,
            ) as response:
                raw_body = response.read()
                return SoundCloudTransportResponse(
                    status_code=int(response.status),
                    headers=dict(response.headers.items()),
                    body=_decode_response_body(raw_body, response.headers.get("Content-Type")),
                )
        except urllib.error.HTTPError as exc:
            raw_body = exc.read()
            return SoundCloudTransportResponse(
                status_code=int(exc.code),
                headers=dict(exc.headers.items()),
                body=_decode_response_body(raw_body, exc.headers.get("Content-Type")),
            )
        except urllib.error.URLError as exc:
            raise SoundCloudAPIError(
                f"SoundCloud network error: {exc.reason}", url=final_url
            ) from exc


def is_supported_track_field(field_name: str) -> bool:
    """Return whether the field is documented as supported by upload request schema."""

    return field_name in SUPPORTED_TRACK_WRITE_FIELDS


def unsupported_track_fields(fields: Iterable[str]) -> list[str]:
    """Return unsupported field names from an input collection."""

    return sorted(field for field in fields if field and not is_supported_track_field(field))


REDACTED = "***"

_AUTHORIZATION_HEADER_RE = re.compile(
    r"(?i)\b(authorization)\s*:\s*(OAuth|Bearer|Basic)\s+([A-Za-z0-9._~+/\-=]+)"
)
_QUERY_SECRET_RE = re.compile(r"(?i)(access_token|refresh_token|client_secret|code)=([^&\s]+)")
_JSON_SECRET_RE = re.compile(
    r'(?i)("?(?:access_token|refresh_token|client_secret|code)"?\s*[:=]\s*")([^"]+)(")'
)
_CALLBACK_QUERY_RE = re.compile(
    r"(?i)([a-z][a-z0-9+.-]*://[^\s'\"<>?]*callback[^\s'\"<>?]*)(\?[^\s'\"<>)]*)"
)


def redact_text(value: str) -> str:
    """Redact known secret-bearing fragments from log-like or user-facing strings."""

    if not value:
        return value
    redacted = _AUTHORIZATION_HEADER_RE.sub(
        lambda match: f"{match.group(1)}: {match.group(2)} {REDACTED}",
        str(value),
    )
    redacted = _CALLBACK_QUERY_RE.sub(lambda match: f"{match.group(1)}?{REDACTED}", redacted)
    redacted = _QUERY_SECRET_RE.sub(
        lambda match: f"{match.group(1)}={REDACTED}",
        redacted,
    )
    redacted = _JSON_SECRET_RE.sub(
        lambda match: f"{match.group(1)}{REDACTED}{match.group(3)}", redacted
    )
    return redacted


def redact_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    """Return a redacted copy of headers suitable for logs and UI output."""

    if not headers:
        return {}
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        lower_key = str(key).strip().lower()
        raw_value = str(value or "")
        if lower_key == "authorization":
            redacted[str(key)] = redact_text(f"Authorization: {raw_value}")
        elif lower_key in {"x-csrf-token", "cookie", "set-cookie"}:
            redacted[str(key)] = REDACTED
        else:
            redacted[str(key)] = _QUERY_SECRET_RE.sub(
                lambda match: f"{match.group(1)}={REDACTED}",
                raw_value,
            )
    return redacted


def _url_for_log(url: str) -> str:
    """Return a URL safe enough for application logs.

    SoundCloud API endpoints are useful for troubleshooting, but query strings and
    fragments can carry OAuth callback data or future auth-bearing parameters. The
    log form keeps only the scheme, host, and path.
    """

    redacted = redact_text(str(url or ""))
    parsed = urllib.parse.urlparse(redacted)
    if parsed.scheme or parsed.netloc:
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return redacted.split("?", 1)[0].split("#", 1)[0]


def _header_value(headers: Mapping[str, str] | None, *names: str) -> str | None:
    normalized = _casefold_headers(headers)
    for name in names:
        value = normalized.get(name.lower())
        if value not in (None, ""):
            return value
    return None


@dataclass(frozen=True, slots=True)
class SoundCloudRateLimitError:
    """Normalized rate-limit response metadata."""

    status_code: int
    message: str
    retry_after_seconds: int | None = None
    limit: int | None = None
    remaining: int | None = None
    reset_utc: str | None = None
    request_id: str | None = None

    @property
    def is_retryable(self) -> bool:
        return self.status_code == 429


def _casefold_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {str(key).lower(): str(value or "") for key, value in headers.items()}


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


def parse_rate_limit_error(
    status_code: int,
    *,
    headers: Mapping[str, str] | None = None,
    body: Mapping[str, Any] | str | None = None,
) -> SoundCloudRateLimitError | None:
    """Parse rate-limit information if the response indicates throttling."""

    if status_code != 429:
        return None

    status_text = "Rate limit exceeded."
    if isinstance(body, Mapping):
        if body.get("message"):
            status_text = str(body.get("message"))
        elif body.get("error"):
            status_text = str(body.get("error"))
    elif isinstance(body, str) and body.strip():
        status_text = body.strip()

    normalized = _casefold_headers(headers)
    return SoundCloudRateLimitError(
        status_code=429,
        message=status_text,
        retry_after_seconds=_coerce_int(normalized.get("retry-after")),
        limit=_coerce_int(normalized.get("x-ratelimit-limit")),
        remaining=_coerce_int(
            normalized.get("x-ratelimit-remaining")
            or normalized.get("ratelimit-remaining")
            or normalized.get("x-limit-remaining")
        ),
        reset_utc=normalized.get("x-ratelimit-reset"),
        request_id=normalized.get("x-request-id"),
    )


def parse_scope_scopes(raw_scope: str | Iterable[str] | None) -> str:
    """Normalize OAuth scope input to a canonical string."""

    if raw_scope is None:
        return ""
    if isinstance(raw_scope, str):
        return raw_scope.strip()
    return " ".join(sorted({str(scope).strip() for scope in raw_scope if str(scope).strip()}))


def _b64url_no_padding(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def build_upload_request_fields(metadata: Mapping[str, object]) -> dict[str, object]:
    """Build the documented SoundCloud upload payload field map."""

    return {
        SC_TRACK_FIELD_TITLE: str(metadata.get("title", "")),
        SC_TRACK_FIELD_ASSET_DATA: metadata.get("asset_data"),
        SC_TRACK_FIELD_DESCRIPTION: metadata.get("description"),
        SC_TRACK_FIELD_GENRE: metadata.get("genre"),
        SC_TRACK_FIELD_ISRC: metadata.get("isrc"),
        SC_TRACK_FIELD_RELEASE_DATE: metadata.get("release_date"),
        SC_TRACK_FIELD_ARTWORK_DATA: metadata.get("artwork_data"),
        SC_TRACK_FIELD_LABEL_NAME: metadata.get("label_name"),
        SC_TRACK_FIELD_RELEASE: metadata.get("release"),
        SC_TRACK_FIELD_METADATA_ARTIST: metadata.get("metadata_artist"),
        SC_TRACK_FIELD_PUBLISHER_METADATA_ARTIST: metadata.get("metadata_artist"),
        SC_TRACK_FIELD_PUBLISHER_METADATA_PUBLISHER: metadata.get("publisher"),
        SC_TRACK_FIELD_PUBLISHER_METADATA_COMPOSER: metadata.get("composer"),
        SC_TRACK_FIELD_PUBLISHER_METADATA_RELEASE_TITLE: metadata.get("release"),
        SC_TRACK_FIELD_PUBLISHER_METADATA_ALBUM_TITLE: metadata.get("album_title"),
        SC_TRACK_FIELD_PUBLISHER_METADATA_UPC_OR_EAN: metadata.get("upc_or_ean"),
        SC_TRACK_FIELD_PUBLISHER_METADATA_ISRC: metadata.get("isrc"),
        SC_TRACK_FIELD_PUBLISHER_METADATA_ISWC: metadata.get("iswc"),
        SC_TRACK_FIELD_PUBLISHER_METADATA_P_LINE: metadata.get("p_line"),
        SC_TRACK_FIELD_PUBLISHER_METADATA_CONTAINS_MUSIC: (
            _bool_field(bool(metadata.get("contains_music")))
            if metadata.get("contains_music") is not None
            else None
        ),
        SC_TRACK_FIELD_PUBLISHER_METADATA_EXPLICIT: (
            _bool_field(bool(metadata.get("contains_explicit")))
            if metadata.get("contains_explicit") is not None
            else None
        ),
        SC_TRACK_FIELD_LICENSE: metadata.get("license"),
    }


def _url_with_params(url: str, params: Mapping[str, object] | None) -> str:
    if not params:
        return url
    parsed = urllib.parse.urlparse(url)
    query_values = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query_values.extend(
        (str(key), str(value)) for key, value in params.items() if value is not None
    )
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query_values)))


def _decode_response_body(raw_body: bytes, content_type: str | None) -> Any:
    if not raw_body:
        return None
    text = raw_body.decode("utf-8", errors="replace")
    if "json" in str(content_type or "").lower():
        try:
            return jsonlib.loads(text)
        except Exception:
            return text
    try:
        return jsonlib.loads(text)
    except Exception:
        return text


def _encode_multipart(
    data: Mapping[str, object],
    files: Mapping[str, SoundCloudFileValue],
) -> tuple[bytes, str]:
    boundary = f"isrc-soundcloud-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in data.items():
        if value is None:
            continue
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for key, value in files.items():
        filename, payload, content_type = _file_payload(value)
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="{key}"; ' f'filename="{filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
                payload,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _file_payload(value: SoundCloudFileValue) -> tuple[str, bytes, str]:
    if isinstance(value, tuple):
        filename, payload, content_type = value
        return filename, payload, content_type
    path = Path(value)
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise SoundCloudAPIError(
            f"SoundCloud upload file could not be read: {path.name} ({exc.strerror or exc})"
        ) from exc
    return path.name, payload, content_type


def _bool_field(value: bool) -> str:
    return "true" if bool(value) else "false"


def _normalize_tag_list(value: object | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    pieces = re.split(r"[,;\n]+", text)
    tags: list[str] = []
    for piece in pieces:
        tag = " ".join(piece.split())
        if not tag:
            continue
        if " " in tag and not (tag.startswith('"') and tag.endswith('"')):
            tag = f'"{tag}"'
        tags.append(tag)
    return " ".join(tags) or None


def build_track_request_fields(
    metadata: Mapping[str, object],
    options: SoundCloudPublishOptions,
    *,
    include_asset: bool,
) -> dict[str, object]:
    fields = build_upload_request_fields(metadata)
    if not include_asset:
        fields.pop(SC_TRACK_FIELD_ASSET_DATA, None)
    fields.update(
        {
            SC_TRACK_FIELD_SHARING: options.sharing,
            SC_TRACK_FIELD_TAG_LIST: _normalize_tag_list(options.tag_list),
            SC_TRACK_FIELD_DOWNLOADABLE: _bool_field(options.downloadable),
            SC_TRACK_FIELD_STREAMABLE: _bool_field(options.streamable),
            SC_TRACK_FIELD_COMMENTABLE: _bool_field(options.commentable),
            SC_TRACK_FIELD_REVEAL_STATS: _bool_field(options.reveal_stats),
            SC_TRACK_FIELD_REVEAL_COMMENTS: _bool_field(options.reveal_comments),
            SC_TRACK_FIELD_PURCHASE_URL: options.purchase_url,
        }
    )
    return {key: value for key, value in fields.items() if value is not None and value != ""}


def _clean_payload_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in values.items() if value is not None and value != ""}


def _publisher_metadata_payload(metadata: Mapping[str, object]) -> dict[str, object]:
    return _clean_payload_mapping(
        {
            "artist": metadata.get("metadata_artist"),
            "publisher": metadata.get("publisher") or metadata.get("label_name"),
            "writer_composer": metadata.get("composer"),
            "release_title": metadata.get("release"),
            "album_title": metadata.get("album_title"),
            "upc_or_ean": metadata.get("upc_or_ean"),
            "isrc": metadata.get("isrc"),
            "iswc": metadata.get("iswc"),
            "p_line": metadata.get("p_line"),
            "contains_music": metadata.get("contains_music"),
            "explicit": metadata.get("contains_explicit"),
        }
    )


def build_track_json_payload(
    metadata: Mapping[str, object],
    options: SoundCloudPublishOptions,
) -> dict[str, object]:
    """Build a JSON update payload including richer SoundCloud publisher metadata.

    SoundCloud's public API documentation uses a ``track`` wrapper for the core
    fields, while the current web editor saves richer metadata as top-level JSON
    attributes. Carry both shapes so documented fields and web-editor metadata
    can be accepted by whichever server-side path handles the request.
    """

    track = _clean_payload_mapping(
        {
            "title": metadata.get("title"),
            "description": metadata.get("description"),
            "genre": metadata.get("genre"),
            "tag_list": _normalize_tag_list(options.tag_list),
            "label_name": metadata.get("label_name"),
            "release": metadata.get("release"),
            "release_date": metadata.get("release_date"),
            "streamable": options.streamable,
            "downloadable": options.downloadable,
            "sharing": options.sharing,
            "commentable": options.commentable,
            "reveal_stats": options.reveal_stats,
            "reveal_comments": options.reveal_comments,
            "purchase_url": options.purchase_url,
            "license": metadata.get("license"),
            "isrc": metadata.get("isrc"),
            "metadata_artist": metadata.get("metadata_artist"),
        }
    )
    publisher_metadata = _publisher_metadata_payload(metadata)
    if publisher_metadata:
        track["publisher_metadata"] = publisher_metadata
    payload = dict(track)
    payload["track"] = track
    return payload


def build_track_web_editor_json_payload(
    metadata: Mapping[str, object],
    options: SoundCloudPublishOptions,
) -> dict[str, object]:
    """Build the top-level JSON shape used by SoundCloud's web metadata editor."""

    payload = dict(build_track_json_payload(metadata, options))
    payload.pop("track", None)
    return payload


def _metadata_has_rich_publisher_fields(metadata: Mapping[str, object]) -> bool:
    return bool(_publisher_metadata_payload(metadata))


def _metadata_without_media(metadata: Mapping[str, object]) -> dict[str, object]:
    clean = dict(metadata)
    clean.pop("asset_data", None)
    clean.pop("artwork_data", None)
    return clean


def _response_status(response: SoundCloudTransportResponse) -> int:
    return int(response.status_code)


def _message_from_body(body: Any, fallback: str) -> str:
    if isinstance(body, Mapping):
        for key in ("message", "error", "status"):
            if body.get(key):
                return str(body.get(key))
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, Mapping) and first.get("error_message"):
                return str(first.get("error_message"))
    if isinstance(body, str) and body.strip():
        return body.strip()
    return fallback


def _require_mapping(body: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(body, Mapping):
        raise SoundCloudMalformedResponseError(
            f"SoundCloud returned a malformed {context} response."
        )
    return body


def _coerce_remote_numeric_id(value: object | None) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(str(value))
    except Exception:
        return None


def _token_bundle_from_body(body: Mapping[str, Any]) -> SoundCloudOAuthTokenBundle:
    access_token = str(body.get("access_token") or "").strip()
    refresh_token = str(body.get("refresh_token") or "").strip()
    if not access_token or not refresh_token:
        raise SoundCloudMalformedResponseError(
            "SoundCloud OAuth response did not include a complete token bundle."
        )
    return SoundCloudOAuthTokenBundle.from_record(dict(body))


@dataclass(frozen=True, slots=True)
class SoundCloudRemoteTrackMetadataSnapshot:
    """Non-secret metadata fetched from an uploaded SoundCloud track."""

    remote_urn: str
    remote_numeric_id: int | None
    remote_url: str | None
    title: str | None = None
    description: str | None = None
    genre: str | None = None
    tag_list: str | None = None
    purchase_url: str | None = None
    label_name: str | None = None
    release: str | None = None
    release_date: str | None = None
    isrc: str | None = None
    metadata_artist: str | None = None
    publisher_metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SoundCloudRemoteTrackSummary:
    """Non-secret track summary used for matching existing SoundCloud uploads."""

    remote_urn: str
    remote_numeric_id: int | None
    remote_url: str | None
    title: str | None = None
    genre: str | None = None
    created_at: str | None = None
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SoundCloudRemoteTrack:
    """Remote track identity returned by upload or update calls."""

    remote_urn: str
    remote_numeric_id: int | None
    remote_url: str | None
    raw: Mapping[str, Any]


class SoundCloudAPIClient:
    """Live SoundCloud API methods behind an injectable transport."""

    def __init__(
        self,
        *,
        transport: SoundCloudTransport,
        api_base_url: str = "https://api.soundcloud.com",
        api_v2_base_url: str = "https://api-v2.soundcloud.com",
        auth_base_url: str = "https://secure.soundcloud.com",
        timeout_seconds: float | None = 60,
    ) -> None:
        self.transport = transport
        self.api_base_url = api_base_url.rstrip("/")
        self.api_v2_base_url = api_v2_base_url.rstrip("/")
        self.auth_base_url = auth_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, object] | None = None,
        data: Mapping[str, object] | None = None,
        json: Mapping[str, object] | None = None,
        files: Mapping[str, SoundCloudFileValue] | None = None,
    ) -> SoundCloudTransportResponse:
        log_method = str(method or "GET").upper()
        log_endpoint = _url_for_log(url)
        payload_kind = (
            "multipart"
            if files
            else "json" if json is not None else "form" if data is not None else "none"
        )
        LOGGER.info(
            "SoundCloud API request started: method=%s endpoint=%s payload=%s",
            log_method,
            log_endpoint,
            payload_kind,
            extra={
                "event": "soundcloud.api.request.started",
                "action": log_method,
                "entity": "soundcloud_api",
                "path": log_endpoint,
                "details": {"payload": payload_kind, "has_files": bool(files)},
            },
        )
        final_headers = {"accept": "application/json; charset=utf-8", **dict(headers or {})}
        try:
            response = self.transport.request(
                method,
                url,
                headers=final_headers,
                params=params,
                data=data,
                json=json,
                files=files,
                timeout_seconds=self.timeout_seconds,
            )
        except SoundCloudAPIError as exc:
            LOGGER.warning(
                "SoundCloud API transport failed: method=%s endpoint=%s error=%s",
                log_method,
                log_endpoint,
                redact_text(str(exc)),
                extra={
                    "event": "soundcloud.api.request.transport_failed",
                    "action": log_method,
                    "entity": "soundcloud_api",
                    "path": log_endpoint,
                    "status": "failed",
                    "details": {"error": redact_text(str(exc))},
                },
            )
            raise
        status_code = _response_status(response)
        request_id = _header_value(response.headers, "x-request-id", "x-amzn-requestid")
        rate_remaining = _header_value(
            response.headers,
            "x-ratelimit-remaining",
            "ratelimit-remaining",
            "x-limit-remaining",
        )
        rate_limit = parse_rate_limit_error(
            status_code,
            headers=response.headers,
            body=response.body,
        )
        if rate_limit is not None:
            LOGGER.warning(
                "SoundCloud API rate limited: method=%s endpoint=%s status=%s retry_after=%s request_id=%s",
                log_method,
                log_endpoint,
                status_code,
                rate_limit.retry_after_seconds,
                request_id,
                extra={
                    "event": "soundcloud.api.request.rate_limited",
                    "action": log_method,
                    "entity": "soundcloud_api",
                    "path": log_endpoint,
                    "status": status_code,
                    "ref_id": request_id,
                    "details": {
                        "retry_after_seconds": rate_limit.retry_after_seconds,
                        "remaining": rate_limit.remaining,
                        "limit": rate_limit.limit,
                    },
                },
            )
            raise SoundCloudAPIError(
                rate_limit.message,
                status_code=status_code,
                url=url,
                rate_limit=rate_limit,
            )
        if status_code >= 400:
            message = _message_from_body(
                response.body,
                f"SoundCloud request failed with HTTP {status_code}.",
            )
            safe_message = redact_text(message)
            LOGGER.warning(
                "SoundCloud API request failed: method=%s endpoint=%s status=%s request_id=%s error=%s",
                log_method,
                log_endpoint,
                status_code,
                request_id,
                safe_message,
                extra={
                    "event": "soundcloud.api.request.failed",
                    "action": log_method,
                    "entity": "soundcloud_api",
                    "path": log_endpoint,
                    "status": status_code,
                    "ref_id": request_id,
                    "details": {"error": safe_message},
                },
            )
            raise SoundCloudAPIError(message, status_code=status_code, url=url)
        LOGGER.info(
            "SoundCloud API request completed: method=%s endpoint=%s status=%s request_id=%s rate_remaining=%s",
            log_method,
            log_endpoint,
            status_code,
            request_id,
            rate_remaining,
            extra={
                "event": "soundcloud.api.request.completed",
                "action": log_method,
                "entity": "soundcloud_api",
                "path": log_endpoint,
                "status": status_code,
                "ref_id": request_id,
                "details": {"rate_limit_remaining": rate_remaining},
            },
        )
        return response

    def exchange_authorization_code(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        code: str,
        code_verifier: str,
    ) -> SoundCloudOAuthTokenBundle:
        response = self._request(
            "POST",
            f"{self.auth_base_url}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "code": code,
            },
        )
        return _token_bundle_from_body(_require_mapping(response.body, "OAuth token"))

    def refresh_token(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> SoundCloudOAuthTokenBundle:
        response = self._request(
            "POST",
            f"{self.auth_base_url}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
        )
        return _token_bundle_from_body(_require_mapping(response.body, "OAuth refresh"))

    def sign_out(self, access_token: str) -> None:
        self._request(
            "POST",
            f"{self.auth_base_url}/sign-out",
            headers={"Content-Type": "application/json"},
            json={"access_token": access_token},
        )

    def get_me(self, access_token: str) -> Mapping[str, Any]:
        response = self._request(
            "GET",
            f"{self.api_base_url}/me",
            headers={"Authorization": f"OAuth {access_token}"},
        )
        return _require_mapping(response.body, "account")

    def get_quota_snapshot(self, access_token: str) -> SoundCloudQuotaSnapshot:
        response = self._request(
            "GET",
            f"{self.api_base_url}/me",
            headers={"Authorization": f"OAuth {access_token}"},
        )
        body = _require_mapping(response.body, "quota")
        headers = _casefold_headers(response.headers)
        daily_remaining = (
            body.get("daily_remaining_uploads")
            if body.get("daily_remaining_uploads") is not None
            else body.get("upload_limit_remaining")
        )
        return SoundCloudQuotaSnapshot(
            daily_remaining_uploads=_coerce_int(daily_remaining),
            daily_upload_limit=_coerce_int(body.get("daily_upload_limit")),
            hourly_remaining_uploads=_coerce_int(body.get("hourly_remaining_uploads")),
            hourly_upload_limit=_coerce_int(body.get("hourly_upload_limit")),
            rate_limit_remaining=_coerce_int(
                headers.get("x-ratelimit-remaining") or headers.get("ratelimit-remaining")
            ),
            rate_limit_reset=headers.get("x-ratelimit-reset"),
            rate_limit_reset_seconds=_coerce_int(headers.get("retry-after")),
        )

    def fetch_track_metadata(
        self,
        *,
        access_token: str,
        remote_track_ref: str | int,
    ) -> SoundCloudRemoteTrackMetadataSnapshot:
        """Fetch non-secret metadata for an uploaded SoundCloud track."""

        clean_ref = str(remote_track_ref or "").strip()
        if not clean_ref:
            raise ValueError("SoundCloud track reference is required.")
        path_ref = urllib.parse.quote(clean_ref, safe=":")
        response = self._request(
            "GET",
            f"{self.api_base_url}/tracks/{path_ref}",
            headers={"Authorization": f"OAuth {access_token}"},
        )
        return self._metadata_snapshot_from_response(response.body)

    def resolve_track_url(
        self,
        *,
        access_token: str,
        track_url: str,
    ) -> SoundCloudRemoteTrackMetadataSnapshot:
        """Resolve an existing public SoundCloud track URL to safe remote metadata."""

        clean_url = str(track_url or "").strip()
        parsed = urllib.parse.urlparse(clean_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("A valid SoundCloud track URL is required.")
        response = self._request(
            "GET",
            f"{self.api_base_url}/resolve",
            headers={"Authorization": f"OAuth {access_token}"},
            params={"url": clean_url},
        )
        return self._metadata_snapshot_from_response(response.body)

    def list_my_tracks(
        self,
        *,
        access_token: str,
        limit: int = 200,
    ) -> tuple[SoundCloudRemoteTrackSummary, ...]:
        """List the authenticated user's uploaded tracks for manual matching."""

        response = self._request(
            "GET",
            f"{self.api_base_url}/me/tracks",
            headers={"Authorization": f"OAuth {access_token}"},
            params={"limit": max(1, min(int(limit), 200))},
        )
        body = response.body
        if isinstance(body, Mapping):
            collection = body.get("collection", ())
        else:
            collection = body
        if not isinstance(collection, list):
            raise SoundCloudMalformedResponseError("SoundCloud track list response was malformed.")
        return tuple(
            self._track_summary_from_payload(item)
            for item in collection
            if isinstance(item, Mapping)
        )

    def upload_track(
        self,
        *,
        access_token: str,
        metadata: Mapping[str, object],
        options: SoundCloudPublishOptions,
    ) -> SoundCloudRemoteTrack:
        fields = build_track_request_fields(metadata, options, include_asset=True)
        asset_data = fields.pop(SC_TRACK_FIELD_ASSET_DATA, None)
        artwork_data = fields.pop(SC_TRACK_FIELD_ARTWORK_DATA, None)
        if not asset_data:
            raise ValueError("SoundCloud upload requires track[asset_data].")
        files: dict[str, SoundCloudFileValue] = {SC_TRACK_FIELD_ASSET_DATA: str(asset_data)}
        if artwork_data:
            files[SC_TRACK_FIELD_ARTWORK_DATA] = str(artwork_data)
        response = self._request(
            "POST",
            f"{self.api_base_url}/tracks",
            headers={"Authorization": f"OAuth {access_token}"},
            data=fields,
            files=files,
        )
        uploaded = self._track_from_response(response.body)
        if uploaded.remote_numeric_id is not None and _metadata_has_rich_publisher_fields(metadata):
            return self._sync_web_editor_metadata(
                access_token=access_token,
                remote_numeric_id=uploaded.remote_numeric_id,
                remote_urn=uploaded.remote_urn,
                metadata=_metadata_without_media(metadata),
                options=options,
                fallback=uploaded,
            )
        return uploaded

    def update_track_metadata(
        self,
        *,
        access_token: str,
        remote_numeric_id: int,
        metadata: Mapping[str, object],
        options: SoundCloudPublishOptions,
    ) -> SoundCloudRemoteTrack:
        fields = build_track_request_fields(metadata, options, include_asset=False)
        artwork_data = fields.pop(SC_TRACK_FIELD_ARTWORK_DATA, None)
        rich_metadata = _metadata_has_rich_publisher_fields(metadata)
        if artwork_data:
            artwork_response = self._request(
                "PUT",
                f"{self.api_base_url}/tracks/{int(remote_numeric_id)}",
                headers={"Authorization": f"OAuth {access_token}"},
                data=fields,
                files={SC_TRACK_FIELD_ARTWORK_DATA: str(artwork_data)},
            )
            if rich_metadata:
                artwork_remote = self._track_from_response(artwork_response.body)
                return self._sync_web_editor_metadata(
                    access_token=access_token,
                    remote_numeric_id=remote_numeric_id,
                    remote_urn=artwork_remote.remote_urn,
                    metadata=_metadata_without_media(metadata),
                    options=options,
                    fallback=artwork_remote,
                )
            response = artwork_response
        else:
            response = self._request(
                "PUT",
                f"{self.api_base_url}/tracks/{int(remote_numeric_id)}",
                headers={"Authorization": f"OAuth {access_token}"},
                json=build_track_json_payload(metadata, options),
            )
            public_remote = self._track_from_response(response.body)
            if rich_metadata:
                return self._sync_web_editor_metadata(
                    access_token=access_token,
                    remote_numeric_id=remote_numeric_id,
                    remote_urn=public_remote.remote_urn,
                    metadata=metadata,
                    options=options,
                    fallback=public_remote,
                )
            return public_remote
        return self._track_from_response(response.body)

    def _sync_web_editor_metadata(
        self,
        *,
        access_token: str,
        remote_numeric_id: int,
        remote_urn: str | None,
        metadata: Mapping[str, object],
        options: SoundCloudPublishOptions,
        fallback: SoundCloudRemoteTrack,
    ) -> SoundCloudRemoteTrack:
        """Best-effort sync for fields exposed by SoundCloud's web metadata editor."""

        web_ref = str(remote_urn or "").strip() or f"soundcloud:tracks:{int(remote_numeric_id)}"
        path_ref = urllib.parse.quote(web_ref, safe=":")
        endpoint = f"{self.api_v2_base_url}/tracks/{path_ref}"
        try:
            response = self._request(
                "PUT",
                endpoint,
                headers={"Authorization": f"OAuth {access_token}"},
                json=build_track_web_editor_json_payload(metadata, options),
            )
            return self._track_from_response(response.body)
        except SoundCloudAPIError as exc:
            safe_error = redact_text(str(exc))
            LOGGER.warning(
                "SoundCloud rich metadata sync failed: remote_numeric_id=%s status=%s error=%s",
                int(remote_numeric_id),
                exc.status_code,
                safe_error,
                extra={
                    "event": "soundcloud.api.rich_metadata_sync.failed",
                    "action": "PUT",
                    "entity": "soundcloud_api",
                    "path": endpoint,
                    "status": exc.status_code or "failed",
                    "details": {"error": safe_error},
                },
            )
            fallback_raw = dict(fallback.raw)
            fallback_raw["rich_metadata_sync_status"] = RICH_METADATA_SYNC_WARNING
            fallback_raw["rich_metadata_sync_error"] = safe_error
            return SoundCloudRemoteTrack(
                remote_urn=fallback.remote_urn,
                remote_numeric_id=fallback.remote_numeric_id,
                remote_url=fallback.remote_url,
                raw=fallback_raw,
            )

    def _track_from_response(self, body: Any) -> SoundCloudRemoteTrack:
        payload = _require_mapping(body, "track")
        remote_numeric_id = _coerce_remote_numeric_id(payload.get("id"))
        raw_urn = str(payload.get("urn") or "").strip()
        remote_urn = raw_urn or (
            f"soundcloud:tracks:{remote_numeric_id}" if remote_numeric_id is not None else ""
        )
        if not remote_urn:
            raise SoundCloudMalformedResponseError(
                "SoundCloud track response did not include a remote identifier."
            )
        remote_url = str(payload.get("permalink_url") or "").strip() or None
        return SoundCloudRemoteTrack(
            remote_urn=remote_urn,
            remote_numeric_id=remote_numeric_id,
            remote_url=remote_url,
            raw=payload,
        )

    def _metadata_snapshot_from_response(self, body: Any) -> SoundCloudRemoteTrackMetadataSnapshot:
        payload = _require_mapping(body, "track")
        return self._metadata_snapshot_from_payload(payload)

    def _metadata_snapshot_from_payload(
        self, payload: Mapping[str, Any]
    ) -> SoundCloudRemoteTrackMetadataSnapshot:
        remote_numeric_id = _coerce_remote_numeric_id(payload.get("id"))
        raw_urn = str(payload.get("urn") or "").strip()
        remote_urn = raw_urn or (
            f"soundcloud:tracks:{remote_numeric_id}" if remote_numeric_id is not None else ""
        )
        if not remote_urn:
            raise SoundCloudMalformedResponseError(
                "SoundCloud track response did not include a remote identifier."
            )
        publisher_metadata_raw = payload.get("publisher_metadata")
        publisher_metadata = (
            dict(publisher_metadata_raw) if isinstance(publisher_metadata_raw, Mapping) else None
        )
        return SoundCloudRemoteTrackMetadataSnapshot(
            remote_urn=remote_urn,
            remote_numeric_id=remote_numeric_id,
            remote_url=str(payload.get("permalink_url") or "").strip() or None,
            title=str(payload.get("title") or "").strip() or None,
            description=str(payload.get("description") or "").strip() or None,
            genre=str(payload.get("genre") or "").strip() or None,
            tag_list=str(payload.get("tag_list") or "").strip() or None,
            purchase_url=str(payload.get("purchase_url") or "").strip() or None,
            label_name=str(payload.get("label_name") or "").strip() or None,
            release=str(payload.get("release") or "").strip() or None,
            release_date=str(payload.get("release_date") or "").strip() or None,
            isrc=str(payload.get("isrc") or "").strip() or None,
            metadata_artist=str(payload.get("metadata_artist") or "").strip() or None,
            publisher_metadata=publisher_metadata,
        )

    def _track_summary_from_payload(
        self, payload: Mapping[str, Any]
    ) -> SoundCloudRemoteTrackSummary:
        snapshot = self._metadata_snapshot_from_payload(payload)
        return SoundCloudRemoteTrackSummary(
            remote_urn=snapshot.remote_urn,
            remote_numeric_id=snapshot.remote_numeric_id,
            remote_url=snapshot.remote_url,
            title=snapshot.title,
            genre=snapshot.genre,
            created_at=str(payload.get("created_at") or "").strip() or None,
            duration_ms=_coerce_int(payload.get("duration")),
        )


__all__ = [
    "SC_TRACK_FIELD_ARTWORK_DATA",
    "SC_TRACK_FIELD_BPM",
    "SC_TRACK_FIELD_COMMENTABLE",
    "SC_TRACK_FIELD_DOWNLOADABLE",
    "SC_TRACK_FIELD_GENRE",
    "SC_TRACK_FIELD_ISRC",
    "SC_TRACK_FIELD_LABEL_NAME",
    "SC_TRACK_FIELD_LICENSE",
    "SC_TRACK_FIELD_METADATA_ARTIST",
    "SC_TRACK_FIELD_PURCHASE_TITLE",
    "SC_TRACK_FIELD_PURCHASE_URL",
    "SC_TRACK_FIELD_PUBLISHER_METADATA_ALBUM_TITLE",
    "SC_TRACK_FIELD_PUBLISHER_METADATA_ARTIST",
    "SC_TRACK_FIELD_PUBLISHER_METADATA_COMPOSER",
    "SC_TRACK_FIELD_PUBLISHER_METADATA_CONTAINS_MUSIC",
    "SC_TRACK_FIELD_PUBLISHER_METADATA_EXPLICIT",
    "SC_TRACK_FIELD_PUBLISHER_METADATA_ISRC",
    "SC_TRACK_FIELD_PUBLISHER_METADATA_ISWC",
    "SC_TRACK_FIELD_PUBLISHER_METADATA_P_LINE",
    "SC_TRACK_FIELD_PUBLISHER_METADATA_PUBLISHER",
    "SC_TRACK_FIELD_PUBLISHER_METADATA_RELEASE_TITLE",
    "SC_TRACK_FIELD_PUBLISHER_METADATA_UPC_OR_EAN",
    "SC_TRACK_FIELD_RELEASE",
    "SC_TRACK_FIELD_RELEASE_DATE",
    "SC_TRACK_FIELD_REVEAL_COMMENTS",
    "SC_TRACK_FIELD_REVEAL_STATS",
    "SC_TRACK_FIELD_SHARING",
    "SC_TRACK_FIELD_STREAMABLE",
    "SC_TRACK_FIELD_TAG_LIST",
    "SC_TRACK_FIELD_TITLE",
    "SC_TRACK_FIELD_ASSET_DATA",
    "SUPPORTED_LICENSES",
    "SUPPORTED_TRACK_WRITE_FIELDS",
    "RICH_METADATA_SYNC_WARNING",
    "RICH_METADATA_SYNC_WARNING_MESSAGE",
    "SoundCloudAPIClient",
    "SoundCloudAPIError",
    "SoundCloudFileValue",
    "SoundCloudLicense",
    "SoundCloudMalformedResponseError",
    "SoundCloudRateLimitError",
    "SoundCloudRemoteTrack",
    "SoundCloudRemoteTrackMetadataSnapshot",
    "SoundCloudRemoteTrackSummary",
    "SoundCloudTransport",
    "SoundCloudTransportResponse",
    "UrllibSoundCloudTransport",
    "UNSUPPORTED_WRITABLE_TRACK_FIELDS",
    "build_track_json_payload",
    "build_track_request_fields",
    "build_track_web_editor_json_payload",
    "build_upload_request_fields",
    "is_supported_track_field",
    "parse_rate_limit_error",
    "parse_scope_scopes",
    "redact_headers",
    "redact_text",
    "unsupported_track_fields",
    "_b64url_no_padding",
]

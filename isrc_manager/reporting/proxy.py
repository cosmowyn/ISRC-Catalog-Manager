"""Reference server-side report proxy.

Deploy this module outside the desktop app, behind HTTPS. It keeps GitHub credentials server-side
and enforces the bug/crash-report-only policy before creating issues.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .models import ALLOWED_LABELS
from .sanitizer import ReportSanitizer

JsonPayload = dict[str, Any]
StartResponse = Callable[[str, list[tuple[str, str]]], None]


@dataclass(frozen=True)
class ReportProxyConfig:
    repository: str
    allowed_versions: tuple[str, ...] = ()
    max_payload_bytes: int = 180_000
    max_body_chars: int = 160_000
    per_ip_hour_limit: int = 20
    allowed_labels: frozenset[str] = ALLOWED_LABELS


class ProxyValidationError(ValueError):
    def __init__(self, message: str, *, status: str = "400 Bad Request"):
        super().__init__(message)
        self.status = status


class InMemoryProxyRateLimiter:
    """Simple process-local rate limiter for small deployments.

    Production deployments should also enforce rate limits at the ingress or API gateway.
    """

    def __init__(self, *, max_per_hour: int):
        self.max_per_hour = int(max_per_hour)
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, now: float | None = None) -> bool:
        now = time.time() if now is None else float(now)
        events = self._events[key]
        cutoff = now - 3600
        while events and events[0] < cutoff:
            events.popleft()
        if len(events) >= self.max_per_hour:
            return False
        events.append(now)
        return True


class GitHubAppIssueClient:
    """Create issues using a GitHub App installation token."""

    def __init__(
        self,
        *,
        app_id: str,
        installation_id: str,
        private_key_pem: str,
        api_base: str = "https://api.github.com",
    ):
        self.app_id = str(app_id)
        self.installation_id = str(installation_id)
        self.private_key_pem = private_key_pem
        self.api_base = api_base.rstrip("/")
        self._installation_token = ""
        self._installation_token_expires_at = 0.0

    def create_issue(self, *, repository: str, issue_payload: JsonPayload) -> JsonPayload:
        owner, repo = repository.split("/", maxsplit=1)
        url = f"{self.api_base}/repos/{owner}/{repo}/issues"
        return _github_json_request("POST", url, token=self._token(), payload=issue_payload)

    def _token(self) -> str:
        if self._installation_token and time.time() < self._installation_token_expires_at - 60:
            return self._installation_token
        jwt_token = github_app_jwt(self.app_id, self.private_key_pem)
        url = f"{self.api_base}/app/installations/{self.installation_id}/access_tokens"
        response = _github_json_request("POST", url, token=jwt_token, payload={})
        token = str(response.get("token") or "")
        expires_at = str(response.get("expires_at") or "")
        if not token:
            raise RuntimeError("GitHub did not return an installation token.")
        self._installation_token = token
        self._installation_token_expires_at = _parse_github_expiration(expires_at)
        return token


class ReportProxyApp:
    """Minimal WSGI app for report submission."""

    def __init__(
        self,
        *,
        config: ReportProxyConfig,
        issue_client: GitHubAppIssueClient,
        sanitizer: ReportSanitizer | None = None,
        rate_limiter: InMemoryProxyRateLimiter | None = None,
    ):
        self.config = config
        self.issue_client = issue_client
        self.sanitizer = sanitizer or ReportSanitizer(max_chars=config.max_body_chars)
        self.rate_limiter = rate_limiter or InMemoryProxyRateLimiter(
            max_per_hour=config.per_ip_hour_limit
        )

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        try:
            response = self._handle(environ)
        except ProxyValidationError as exc:
            return _json_response(start_response, exc.status, {"error": str(exc)})
        except Exception:
            return _json_response(
                start_response,
                "502 Bad Gateway",
                {"error": "Report proxy could not create the GitHub issue."},
            )
        return _json_response(start_response, "201 Created", response)

    def _handle(self, environ: dict[str, Any]) -> JsonPayload:
        if environ.get("REQUEST_METHOD") != "POST":
            raise ProxyValidationError(
                "Use POST for report submission.", status="405 Method Not Allowed"
            )
        remote_addr = str(environ.get("REMOTE_ADDR") or "unknown")
        if not self.rate_limiter.allow(remote_addr):
            raise ProxyValidationError(
                "Report rate limit exceeded.", status="429 Too Many Requests"
            )
        body = _read_limited_body(environ, limit=self.config.max_payload_bytes)
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise ProxyValidationError("Report payload must be valid JSON.") from exc
        issue_payload = validate_proxy_payload(
            payload, config=self.config, sanitizer=self.sanitizer
        )
        created = self.issue_client.create_issue(
            repository=self.config.repository,
            issue_payload=issue_payload,
        )
        return {
            "message": "Report submitted.",
            "issue_url": str(created.get("html_url") or created.get("url") or ""),
        }


def create_wsgi_app_from_environment() -> ReportProxyApp:
    """Build the WSGI app from deployment environment variables."""

    private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY", "")
    private_key_file = os.environ.get("GITHUB_APP_PRIVATE_KEY_FILE", "")
    if not private_key and private_key_file:
        private_key = Path(private_key_file).read_text(encoding="utf-8")
    app_id = os.environ.get("GITHUB_APP_ID", "")
    installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID", "")
    if not app_id or not installation_id or not private_key:
        raise RuntimeError(
            "Set GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, and "
            "GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_FILE."
        )
    config = ReportProxyConfig(
        repository=os.environ.get("ISRC_REPORT_PROXY_REPOSITORY", "cosmowyn/ISRC-Catalog-Manager"),
        allowed_versions=_csv_env("ISRC_REPORT_PROXY_ALLOWED_VERSIONS"),
        max_payload_bytes=_int_env("ISRC_REPORT_PROXY_MAX_BYTES", 180_000),
        max_body_chars=_int_env("ISRC_REPORT_PROXY_MAX_BODY_CHARS", 160_000),
        per_ip_hour_limit=_int_env("ISRC_REPORT_PROXY_PER_IP_HOUR_LIMIT", 20),
    )
    client = GitHubAppIssueClient(
        app_id=app_id,
        installation_id=installation_id,
        private_key_pem=private_key,
        api_base=os.environ.get("GITHUB_API_BASE", "https://api.github.com"),
    )
    return ReportProxyApp(config=config, issue_client=client)


def validate_proxy_payload(
    payload: object,
    *,
    config: ReportProxyConfig,
    sanitizer: ReportSanitizer,
) -> JsonPayload:
    if not isinstance(payload, dict):
        raise ProxyValidationError("Report payload must be an object.")
    if payload.get("schema_version") != "1.0":
        raise ProxyValidationError("Unsupported report schema version.")
    if payload.get("repository") != config.repository:
        raise ProxyValidationError("Report repository is not accepted.")
    kind = str(payload.get("kind") or "")
    if kind not in {"bug", "crash"}:
        raise ProxyValidationError("Report kind must be bug or crash.")
    app_version = str(payload.get("app_version") or "")
    if config.allowed_versions and app_version not in config.allowed_versions:
        raise ProxyValidationError("Application version is not accepted.")

    client_labels = set(payload.get("labels") or [])
    if not client_labels <= config.allowed_labels:
        raise ProxyValidationError("Report requested unsupported labels.")

    title = sanitizer.sanitize_text(str(payload.get("title") or ""), max_chars=140).strip()
    expected_prefix = "[Crash Report]" if kind == "crash" else "[Bug Report]"
    if not title.startswith(expected_prefix):
        raise ProxyValidationError("Report title prefix is not accepted.")

    body = sanitizer.sanitize_text(str(payload.get("body") or ""), max_chars=config.max_body_chars)
    if not body.strip():
        raise ProxyValidationError("Report body is required.")
    if len(body.encode("utf-8")) > config.max_payload_bytes:
        raise ProxyValidationError("Report body exceeds the payload limit.")

    labels = ["bug", "user-report"]
    if kind == "crash":
        labels.append("crash-report")

    return {
        "title": title,
        "body": body,
        "labels": labels,
    }


def github_app_jwt(app_id: str, private_key_pem: str, *, now: int | None = None) -> str:
    now = int(time.time()) if now is None else int(now)
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {"iat": now - 60, "exp": now + 540, "iss": str(app_id)}
    signing_input = (
        _base64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + b"."
        + _base64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    )
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"),
        password=None,
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return (signing_input + b"." + _base64url(signature)).decode("ascii")


def _read_limited_body(environ: dict[str, Any], *, limit: int) -> bytes:
    try:
        content_length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        raise ProxyValidationError("Invalid content length.") from None
    if content_length <= 0:
        raise ProxyValidationError("Report payload is empty.")
    if content_length > limit:
        raise ProxyValidationError(
            "Report payload exceeds the size limit.", status="413 Payload Too Large"
        )
    stream = environ.get("wsgi.input")
    if not hasattr(stream, "read"):
        raise ProxyValidationError("Request body stream is unavailable.")
    return stream.read(content_length)


def _github_json_request(
    method: str,
    url: str,
    *,
    token: str,
    payload: JsonPayload,
) -> JsonPayload:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "ISRC-Catalog-Manager-Report-Proxy",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
    except urllib.error.HTTPError:
        raise
    if not raw:
        return {}
    parsed = json.loads(raw.decode("utf-8", errors="replace"))
    return parsed if isinstance(parsed, dict) else {}


def _json_response(
    start_response: StartResponse,
    status: str,
    payload: JsonPayload,
) -> list[bytes]:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
        ],
    )
    return [body]


def _base64url(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _parse_github_expiration(value: str) -> float:
    if not value:
        return time.time() + 300
    try:
        return time.mktime(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return time.time() + 300


def _csv_env(name: str) -> tuple[str, ...]:
    value = os.environ.get(name, "")
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default

"""GitHub issue submission abstraction.

The desktop app intentionally does not bundle repository-write credentials. The supported
production path is a hardened HTTPS report proxy that owns GitHub credentials server-side.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .models import ReportPayload

MAX_SUBMISSION_BYTES = 180_000


@dataclass(frozen=True)
class ReportSubmissionResult:
    success: bool
    message: str
    issue_url: str = ""
    pending_path: str = ""
    status_code: int | None = None


class BackendProxySubmitter:
    """Submit structured reports to a configured HTTPS report proxy."""

    def __init__(self, endpoint_url: str | None, *, max_payload_bytes: int = MAX_SUBMISSION_BYTES):
        self.endpoint_url = (endpoint_url or "").strip()
        self.max_payload_bytes = int(max_payload_bytes)
        if self.endpoint_url:
            _validate_endpoint(self.endpoint_url)

    def submit(self, report: ReportPayload) -> ReportSubmissionResult:
        if not self.endpoint_url:
            return ReportSubmissionResult(
                False,
                "No report proxy is configured; the report was saved locally for later submission.",
            )

        payload = report.to_issue_payload()
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        if len(payload_bytes) > self.max_payload_bytes:
            return ReportSubmissionResult(False, "The report exceeds the configured payload limit.")

        request = urllib.request.Request(
            self.endpoint_url,
            data=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"ISRC-Catalog-Manager-Reporter/{report.app_version}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response_body = response.read(min(4096, self.max_payload_bytes))
                status_code = int(getattr(response, "status", 200))
        except urllib.error.HTTPError as exc:
            return ReportSubmissionResult(
                False,
                f"Report proxy rejected the submission with HTTP {exc.code}.",
                status_code=exc.code,
            )
        except Exception as exc:
            return ReportSubmissionResult(False, f"Report submission failed: {exc}")

        parsed = _parse_response_body(response_body)
        issue_url = str(parsed.get("issue_url") or parsed.get("url") or "")
        message = str(parsed.get("message") or "Report submitted.")
        return ReportSubmissionResult(True, message, issue_url=issue_url, status_code=status_code)


def _validate_endpoint(endpoint_url: str) -> None:
    parsed = urllib.parse.urlparse(endpoint_url)
    host = parsed.hostname or ""
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}:
        return
    raise ValueError("Report proxy endpoint must use HTTPS unless it targets localhost.")


def _parse_response_body(raw: bytes) -> dict[str, object]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}

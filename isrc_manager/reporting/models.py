"""Structured report payload models."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

MAX_TITLE_CHARS = 120
GITHUB_ISSUE_BODY_SOFT_LIMIT_BYTES = 60_000
ALLOWED_LABELS = frozenset({"bug", "crash-report", "user-report"})
ISSUE_BODY_TRUNCATION_NOTICE = (
    "\n\n---\n\n"
    "_Report body was shortened before online submission because GitHub issues reject "
    "very large bodies._\n"
)


@dataclass(frozen=True)
class ReportSection:
    """One diagnostic or user-authored section in a report preview."""

    title: str
    body: str
    kind: str = "text"
    collapsed: bool = True


@dataclass(frozen=True)
class ManualBugReportFields:
    """User-entered manual bug report content."""

    summary: str
    description: str
    steps_to_reproduce: str
    expected_behavior: str
    actual_behavior: str
    include_logs: bool = True
    include_system_details: bool = True
    include_os_context: bool = False


@dataclass(frozen=True)
class ReportPayload:
    """Sanitised report ready for preview and submission."""

    report_id: str
    kind: str
    created_at: str
    summary: str
    app_version: str
    repository: str
    sections: tuple[ReportSection, ...]
    metadata: dict[str, str] = field(default_factory=dict)
    labels: tuple[str, ...] = ("bug", "user-report")
    schema_version: str = "1.0"
    sanitized: bool = True

    @property
    def issue_title(self) -> str:
        prefix = "[Crash Report]" if self.kind == "crash" else "[Bug Report]"
        title = _single_line(self.summary) or "Untitled report"
        max_summary_chars = max(24, MAX_TITLE_CHARS - len(prefix) - 1)
        if len(title) > max_summary_chars:
            title = f"{title[: max_summary_chars - 3].rstrip()}..."
        return f"{prefix} {title}"

    @property
    def safe_labels(self) -> tuple[str, ...]:
        return tuple(label for label in self.labels if label in ALLOWED_LABELS)

    @property
    def deduplication_key(self) -> str:
        material = "\n".join(
            (
                self.kind,
                _single_line(self.summary).lower(),
                self.metadata.get("session_id", ""),
                self.metadata.get("exception_type", ""),
            )
        )
        return sha256(material.encode("utf-8")).hexdigest()

    def to_issue_payload(self, *, max_body_bytes: int | None = None) -> dict[str, Any]:
        body = self.to_markdown()
        if max_body_bytes is not None:
            body = fit_issue_body_for_github(body, max_bytes=max_body_bytes)
        return {
            "schema_version": self.schema_version,
            "repository": self.repository,
            "title": self.issue_title,
            "body": body,
            "labels": list(self.safe_labels),
            "report_id": self.report_id,
            "kind": self.kind,
            "app_version": self.app_version,
        }

    def to_markdown(self) -> str:
        metadata_rows = {
            "Report ID": self.report_id,
            "Report type": self.kind,
            "Created": self.created_at,
            "Application version": self.app_version,
            "Sanitised": "yes" if self.sanitized else "no",
        }
        metadata_rows.update({key: value for key, value in self.metadata.items() if value})

        parts = [
            "## Summary",
            _safe_markdown_text(self.summary),
            "",
            "## Privacy Notice",
            (
                "This report was generated locally. Logs and diagnostics were sanitised before "
                "preview and before submission. Raw catalog databases, audio files, documents, "
                "credentials, tokens, and private local paths are not intentionally included."
            ),
            "",
            "## Metadata",
            "| Field | Value |",
            "| --- | --- |",
        ]
        for key, value in metadata_rows.items():
            parts.append(f"| {_table_cell(key)} | {_table_cell(value)} |")

        for section in self.sections:
            body = section.body.strip() or "(empty)"
            summary = html.escape(section.title, quote=False)
            parts.extend(
                [
                    "",
                    "<details>",
                    f"<summary>{summary}</summary>",
                    "",
                    _format_section_body(body, kind=section.kind),
                    "",
                    "</details>",
                ]
            )
        return "\n".join(parts).strip() + "\n"


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fit_issue_body_for_github(
    body: str,
    *,
    max_bytes: int = GITHUB_ISSUE_BODY_SOFT_LIMIT_BYTES,
) -> str:
    """Keep an issue body under the conservative GitHub API size budget."""

    body = str(body or "")
    max_bytes = int(max_bytes)
    if max_bytes <= 0:
        return ""
    if len(body.encode("utf-8")) <= max_bytes:
        return body
    notice_bytes = ISSUE_BODY_TRUNCATION_NOTICE.encode("utf-8")
    if len(notice_bytes) >= max_bytes:
        return _truncate_utf8(ISSUE_BODY_TRUNCATION_NOTICE, max_bytes)
    budget = max_bytes - len(notice_bytes)
    return _truncate_utf8(body, budget).rstrip() + ISSUE_BODY_TRUNCATION_NOTICE


def _format_section_body(body: str, *, kind: str) -> str:
    if kind == "markdown":
        return _safe_markdown_text(body)
    return f"```text\n{_safe_code_block(body)}\n```"


def _safe_code_block(value: str) -> str:
    return value.replace("```", "` ` `")


def _safe_markdown_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")


def _truncate_utf8(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    return value.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def _single_line(value: str) -> str:
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())


def _table_cell(value: object) -> str:
    text = _single_line(str(value))
    text = text.replace("|", "\\|")
    return html.escape(text, quote=False)

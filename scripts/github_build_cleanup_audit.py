"""Audit models, durable recording, and summaries for GitHub build cleanup."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, TextIO


@dataclass(frozen=True, order=True, slots=True)
class SemVer:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True, slots=True)
class AuditContext:
    repository: str
    mode: str


@dataclass(frozen=True, slots=True)
class AuditEntry:
    resource: str
    name: str
    version: str | None
    action: str
    reason: str
    repository: str = ""
    mode: str = "dry-run"
    timestamp_utc: str = ""
    resource_id: int | None = None
    size_bytes: int = 0
    expired: bool = False
    url: str = ""
    workflow_run_id: int | None = None


class CleanupApplyError(RuntimeError):
    """An apply failed or was blocked after a complete plan was available."""

    def __init__(self, message: str, entries: list[AuditEntry], keep: set[SemVer]):
        super().__init__(message)
        self.entries = entries
        self.keep = keep


class AuditRecorder:
    """Append and flush JSONL audit events before and after destructive calls."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream: TextIO = path.open("w", encoding="utf-8")

    def __enter__(self) -> AuditRecorder:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.sync()
        self._stream.close()

    def record(self, entry: AuditEntry) -> None:
        self._stream.write(json.dumps(asdict(entry), sort_keys=True) + "\n")

    def record_all(self, entries: Iterable[AuditEntry]) -> None:
        for entry in entries:
            self.record(entry)

    def sync(self) -> None:
        self._stream.flush()
        os.fsync(self._stream.fileno())


def _format_bytes(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    return f"{size_bytes / (1024**3):.3f} GiB"


def _safe_markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_summary(entries: Iterable[AuditEntry], keep: Iterable[SemVer], *, apply: bool) -> str:
    entries = list(entries)
    counts: dict[str, int] = {}
    sizes: dict[str, int] = {}
    for entry in entries:
        counts[entry.action] = counts.get(entry.action, 0) + 1
        sizes[entry.action] = sizes.get(entry.action, 0) + entry.size_bytes
    kept_versions = ", ".join(f"`{version}`" for version in sorted(keep, reverse=True)) or "None"
    lines = [
        "## GitHub build cleanup",
        "",
        f"Mode: **{'apply' if apply else 'dry-run'}**",
        "",
        f"Retained stable versions: {kept_versions}",
        "",
        "| Outcome | Count | Size |",
        "| --- | ---: | ---: |",
    ]
    for outcome in (
        "deleted",
        "already-absent",
        "would-delete",
        "keep",
        "skip",
        "blocked",
        "error",
    ):
        lines.append(
            f"| {outcome} | {counts.get(outcome, 0)} | " f"{_format_bytes(sizes.get(outcome, 0))} |"
        )
    lines.extend(
        [
            "",
            "### Audit",
            "",
            "| Resource | ID | Name | Version | Size | Expired | Run | Decision | Reason | URL |",
            "| --- | ---: | --- | --- | ---: | --- | ---: | --- | --- | --- |",
        ]
    )
    for entry in entries:
        lines.append(
            f"| {entry.resource} | {entry.resource_id or '—'} | {_safe_markdown(entry.name)} | "
            f"{entry.version or '—'} | {_format_bytes(entry.size_bytes)} | "
            f"{'yes' if entry.expired else 'no'} | {entry.workflow_run_id or '—'} | "
            f"{entry.action} | {_safe_markdown(entry.reason)} | "
            f"{_safe_markdown(entry.url) or '—'} |"
        )
    return "\n".join(lines) + "\n"

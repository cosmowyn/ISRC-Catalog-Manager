"""Data models for quality dashboard scans."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class QualityIssue:
    issue_type: str
    severity: str
    title: str
    details: str
    entity_type: str
    entity_id: int | None
    release_id: int | None = None
    track_id: int | None = None
    fix_key: str | None = None


@dataclass(slots=True)
class QualityScanResult:
    issues: list[QualityIssue]
    counts_by_severity: dict[str, int] = field(default_factory=dict)
    counts_by_type: dict[str, int] = field(default_factory=dict)

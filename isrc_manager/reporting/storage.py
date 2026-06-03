"""Local pending-report storage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import GITHUB_ISSUE_BODY_SOFT_LIMIT_BYTES, ReportPayload


@dataclass(frozen=True)
class PendingReportReference:
    report_id: str
    json_path: Path
    markdown_path: Path


class PendingReportStore:
    """Persist reports that cannot be submitted immediately."""

    def __init__(self, pending_dir: Path):
        self.pending_dir = Path(pending_dir)
        self.pending_dir.mkdir(parents=True, exist_ok=True)

    def save(self, report: ReportPayload) -> PendingReportReference:
        json_path = self.pending_dir / f"{report.report_id}.json"
        markdown_path = self.pending_dir / f"{report.report_id}.md"
        payload = report.to_issue_payload(max_body_bytes=GITHUB_ISSUE_BODY_SOFT_LIMIT_BYTES)
        self._write_text(json_path, json.dumps(payload, indent=2, sort_keys=True))
        self._write_text(markdown_path, report.to_markdown())
        return PendingReportReference(
            report_id=report.report_id,
            json_path=json_path,
            markdown_path=markdown_path,
        )

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(text.rstrip() + "\n", encoding="utf-8")
        tmp_path.replace(path)

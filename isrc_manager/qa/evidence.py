"""Evidence artifact writing for UI PQ execution."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class EvidenceEvent:
    test_id: str
    timestamp: str
    status: str
    message: str
    data: dict[str, Any]


class EvidenceRecorder:
    """Writes structured UI PQ evidence under an artifact directory."""

    def __init__(self, artifact_dir: Path):
        self.artifact_dir = Path(artifact_dir)
        self.events: list[EvidenceEvent] = []
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    @property
    def evidence_path(self) -> Path:
        return self.artifact_dir / "evidence.json"

    @property
    def summary_path(self) -> Path:
        return self.artifact_dir / "summary.md"

    def record(
        self,
        test_id: str,
        *,
        status: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> EvidenceEvent:
        event = EvidenceEvent(
            test_id=str(test_id),
            timestamp=datetime.now(UTC).isoformat(),
            status=str(status),
            message=str(message),
            data=dict(data or {}),
        )
        self.events.append(event)
        return event

    def write_json(self) -> Path:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        payload = [asdict(event) for event in self.events]
        self.evidence_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return self.evidence_path

    def write_summary(
        self,
        *,
        inventory_count: int,
        traceability_count: int,
        deviation_count: int,
        automated_count: int,
        pending_count: int,
        database_path: str,
        open_deviation_count: int = 0,
        pending_deviation_count: int = 0,
        object_name_gap_count: int = 0,
    ) -> Path:
        lines = [
            "# UI PQ Execution Summary",
            "",
            "This is an internal engineering UI qualification artifact. It is not a "
            "regulatory certification or external compliance claim.",
            "",
            f"- Generated: {datetime.now(UTC).isoformat()}",
            f"- Inventory items discovered: {inventory_count}",
            f"- Traceability rows written: {traceability_count}",
            f"- Automated traceability rows: {automated_count}",
            f"- Pending/manual/out-of-scope rows: {pending_count}",
            f"- Deviations recorded: {deviation_count}",
            f"- Open actionable deviations: {open_deviation_count}",
            f"- Pending/manual deviations: {pending_deviation_count}",
            f"- Object-name gap deviations: {object_name_gap_count}",
            f"- QA database: {database_path or '-'}",
            "",
            "## Executed Evidence Events",
            "",
        ]
        for event in self.events:
            lines.append(f"- `{event.test_id}` {event.status}: {event.message}")
        self.summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.summary_path

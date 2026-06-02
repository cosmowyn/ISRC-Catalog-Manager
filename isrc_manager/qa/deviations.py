"""Deviation recording for UI PQ execution."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

DEVIATION_COLUMNS = (
    "deviation_id",
    "timestamp",
    "test_id",
    "severity",
    "ui_area",
    "workflow",
    "ui_object",
    "step",
    "expected",
    "actual",
    "exception_type",
    "exception_message",
    "screenshot_path",
    "log_path",
    "database_path",
    "evidence_path",
    "coverage_status",
    "recommended_followup",
    "owner",
    "status",
)


@dataclass(slots=True)
class Deviation:
    deviation_id: str
    timestamp: str
    test_id: str
    severity: str
    ui_area: str
    workflow: str
    ui_object: str
    step: str
    expected: str
    actual: str
    exception_type: str = ""
    exception_message: str = ""
    screenshot_path: str = ""
    log_path: str = ""
    database_path: str = ""
    evidence_path: str = ""
    coverage_status: str = ""
    recommended_followup: str = ""
    owner: str = "engineering"
    status: str = "open"


class DeviationRecorder:
    """Collects machine-readable deviations for follow-up engineering work."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.deviations: list[Deviation] = []

    def add(
        self,
        *,
        test_id: str,
        severity: str,
        ui_area: str,
        workflow: str,
        ui_object: str,
        step: str,
        expected: str,
        actual: str,
        exception_type: str = "",
        exception_message: str = "",
        screenshot_path: str = "",
        log_path: str = "",
        database_path: str = "",
        evidence_path: str = "",
        coverage_status: str = "",
        recommended_followup: str = "",
        owner: str = "engineering",
        status: str = "open",
    ) -> Deviation:
        deviation = Deviation(
            deviation_id=f"UI-PQ-DEV-{len(self.deviations) + 1:04d}",
            timestamp=datetime.now(UTC).isoformat(),
            test_id=str(test_id),
            severity=str(severity),
            ui_area=str(ui_area),
            workflow=str(workflow),
            ui_object=str(ui_object),
            step=str(step),
            expected=str(expected),
            actual=str(actual),
            exception_type=str(exception_type),
            exception_message=str(exception_message),
            screenshot_path=str(screenshot_path),
            log_path=str(log_path),
            database_path=str(database_path),
            evidence_path=str(evidence_path),
            coverage_status=str(coverage_status),
            recommended_followup=str(recommended_followup),
            owner=str(owner),
            status=str(status),
        )
        self.deviations.append(deviation)
        return deviation

    def record_exception(
        self,
        *,
        test_id: str,
        ui_area: str,
        workflow: str,
        ui_object: str,
        step: str,
        expected: str,
        exc: BaseException,
        database_path: str = "",
        evidence_path: str = "",
        screenshot_path: str = "",
    ) -> Deviation:
        return self.add(
            test_id=test_id,
            severity="high",
            ui_area=ui_area,
            workflow=workflow,
            ui_object=ui_object,
            step=step,
            expected=expected,
            actual="Exception raised during UI PQ execution.",
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            database_path=database_path,
            evidence_path=evidence_path,
            screenshot_path=screenshot_path,
            coverage_status="failed",
            recommended_followup="Stabilize the failing UI workflow and rerun the UI PQ suite.",
        )

    def write(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=DEVIATION_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for deviation in self.deviations:
                writer.writerow(asdict(deviation))
        return self.path

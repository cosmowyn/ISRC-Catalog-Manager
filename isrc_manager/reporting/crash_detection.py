"""Startup session markers for post-crash detection."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import utc_timestamp


@dataclass(frozen=True)
class CrashSession:
    """Previous session evidence that did not close cleanly."""

    session_id: str
    started_at: str
    last_seen_at: str
    app_version: str
    pid: int
    last_event: str = ""
    last_message: str = ""
    last_workflow: str = ""


@dataclass
class SessionRecord:
    session_id: str
    started_at: str
    last_seen_at: str
    app_version: str
    pid: int
    clean_shutdown: bool = False
    closed_at: str = ""
    last_event: str = ""
    last_message: str = ""
    last_workflow: str = ""

    @classmethod
    def current(cls, *, app_version: str) -> SessionRecord:
        now = utc_timestamp()
        return cls(
            session_id=uuid.uuid4().hex,
            started_at=now,
            last_seen_at=now,
            app_version=app_version,
            pid=os.getpid(),
        )

    def as_crash_session(self) -> CrashSession:
        return CrashSession(
            session_id=self.session_id,
            started_at=self.started_at,
            last_seen_at=self.last_seen_at,
            app_version=self.app_version,
            pid=self.pid,
            last_event=self.last_event,
            last_message=self.last_message,
            last_workflow=self.last_workflow,
        )


class SessionMarkerStore:
    """Persist and inspect the single active runtime session marker."""

    def __init__(self, marker_path: Path):
        self.marker_path = Path(marker_path)
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)

    def start_session(self, *, app_version: str) -> CrashSession | None:
        previous = self._load_record()
        crash = None
        if previous is not None and not previous.clean_shutdown:
            crash = previous.as_crash_session()
        self._write_record(SessionRecord.current(app_version=app_version))
        return crash

    def mark_clean_shutdown(self) -> None:
        record = self._load_record()
        if record is None:
            return
        record.clean_shutdown = True
        record.closed_at = utc_timestamp()
        record.last_seen_at = record.closed_at
        self._write_record(record)

    def record_event(
        self,
        *,
        event: str,
        message: str = "",
        workflow: str = "",
    ) -> None:
        record = self._load_record()
        if record is None or record.clean_shutdown:
            return
        record.last_seen_at = utc_timestamp()
        record.last_event = str(event)[:180]
        record.last_message = str(message)[:500]
        if workflow:
            record.last_workflow = str(workflow)[:180]
        self._write_record(record)

    def _load_record(self) -> SessionRecord | None:
        try:
            raw = json.loads(self.marker_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        return _record_from_mapping(raw)

    def _write_record(self, record: SessionRecord) -> None:
        payload = json.dumps(asdict(record), indent=2, sort_keys=True)
        tmp_path = self.marker_path.with_suffix(f"{self.marker_path.suffix}.tmp")
        tmp_path.write_text(payload + "\n", encoding="utf-8")
        tmp_path.replace(self.marker_path)


def _record_from_mapping(raw: dict[str, Any]) -> SessionRecord | None:
    try:
        return SessionRecord(
            session_id=str(raw["session_id"]),
            started_at=str(raw["started_at"]),
            last_seen_at=str(raw.get("last_seen_at") or raw["started_at"]),
            app_version=str(raw.get("app_version", "")),
            pid=int(raw.get("pid", 0)),
            clean_shutdown=bool(raw.get("clean_shutdown", False)),
            closed_at=str(raw.get("closed_at", "")),
            last_event=str(raw.get("last_event", "")),
            last_message=str(raw.get("last_message", "")),
            last_workflow=str(raw.get("last_workflow", "")),
        )
    except Exception:
        return None

"""Local abuse protection for user-initiated reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Any

COUNTED_FAILURE_KINDS = frozenset({"submission", "proxy-rate-limit"})
DEFAULT_FAILURE_KIND = "submission"


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    reason: str = ""


class LocalReportRateLimiter:
    """Persistent per-installation report throttling."""

    def __init__(
        self,
        state_path: Path,
        *,
        max_per_hour: int = 3,
        max_per_day: int = 8,
        duplicate_window_seconds: int = 24 * 60 * 60,
        failure_cooldown_seconds: int = 15 * 60,
        failure_threshold: int = 3,
    ):
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_per_hour = int(max_per_hour)
        self.max_per_day = int(max_per_day)
        self.duplicate_window_seconds = int(duplicate_window_seconds)
        self.failure_cooldown_seconds = int(failure_cooldown_seconds)
        self.failure_threshold = int(failure_threshold)

    def check(self, *, deduplication_key: str, now: float | None = None) -> RateLimitDecision:
        now = time() if now is None else float(now)
        state = self._load_state()
        timestamps = self._recent(state.get("submissions", []), now=now, window=24 * 60 * 60)
        failures = self._recent_counted_failures(
            state.get("failures", []),
            now=now,
            window=60 * 60,
        )
        duplicate_seen_at = float(state.get("deduplication", {}).get(deduplication_key, 0) or 0)

        if duplicate_seen_at and now - duplicate_seen_at < self.duplicate_window_seconds:
            return RateLimitDecision(False, "A matching report was already submitted recently.")
        if len(self._recent(timestamps, now=now, window=60 * 60)) >= self.max_per_hour:
            return RateLimitDecision(False, "Report limit reached for this hour.")
        if len(timestamps) >= self.max_per_day:
            return RateLimitDecision(False, "Report limit reached for today.")
        if len(failures) >= self.failure_threshold:
            retry_after = self.failure_cooldown_seconds - (now - failures[-1])
            if retry_after > 0:
                minutes = max(1, int(retry_after // 60))
                return RateLimitDecision(
                    False, f"Submission cooldown active. Try again in {minutes}m."
                )
        return RateLimitDecision(True)

    def record_submission(self, *, deduplication_key: str, now: float | None = None) -> None:
        now = time() if now is None else float(now)
        state = self._load_state()
        state["submissions"] = self._recent(
            [*state.get("submissions", []), now],
            now=now,
            window=24 * 60 * 60,
        )
        deduplication = dict(state.get("deduplication", {}))
        deduplication[deduplication_key] = now
        state["deduplication"] = {
            key: value
            for key, value in deduplication.items()
            if now - float(value or 0) < self.duplicate_window_seconds
        }
        state["failures"] = []
        self._write_state(state)

    def record_failure(
        self,
        *,
        kind: str = DEFAULT_FAILURE_KIND,
        now: float | None = None,
    ) -> None:
        now = time() if now is None else float(now)
        state = self._load_state()
        failure_kind = str(kind or DEFAULT_FAILURE_KIND).strip() or DEFAULT_FAILURE_KIND
        state["failures"] = self._recent_failure_records(
            [*self._failure_records(state.get("failures", [])), {"at": now, "kind": failure_kind}],
            now=now,
            window=60 * 60,
        )
        self._write_state(state)

    def _load_state(self) -> dict[str, object]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"submissions": [], "failures": [], "deduplication": {}}
        except Exception:
            return {"submissions": [], "failures": [], "deduplication": {}}
        if not isinstance(raw, dict):
            return {"submissions": [], "failures": [], "deduplication": {}}
        raw.setdefault("submissions", [])
        raw.setdefault("failures", [])
        raw.setdefault("deduplication", {})
        return raw

    def _write_state(self, state: dict[str, object]) -> None:
        tmp_path = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(self.state_path)

    @staticmethod
    def _recent(values: object, *, now: float, window: float) -> list[float]:
        if not isinstance(values, list):
            return []
        recent = []
        for value in values:
            try:
                timestamp = float(value)
            except Exception:
                continue
            if 0 <= now - timestamp <= window:
                recent.append(timestamp)
        return sorted(recent)

    @staticmethod
    def _failure_records(values: object) -> list[dict[str, Any]]:
        if not isinstance(values, list):
            return []
        records: list[dict[str, Any]] = []
        for value in values:
            if isinstance(value, dict):
                records.append(value)
                continue
            try:
                timestamp = float(value)
            except Exception:
                continue
            records.append({"at": timestamp, "kind": "legacy"})
        return records

    @classmethod
    def _recent_failure_records(
        cls,
        values: object,
        *,
        now: float,
        window: float,
    ) -> list[dict[str, Any]]:
        recent = []
        for record in cls._failure_records(values):
            try:
                timestamp = float(record.get("at", 0) or 0)
            except Exception:
                continue
            if 0 <= now - timestamp <= window:
                recent.append(
                    {
                        "at": timestamp,
                        "kind": str(record.get("kind") or DEFAULT_FAILURE_KIND),
                    }
                )
        return sorted(recent, key=lambda record: float(record["at"]))

    @classmethod
    def _recent_counted_failures(
        cls,
        values: object,
        *,
        now: float,
        window: float,
    ) -> list[float]:
        return [
            float(record["at"])
            for record in cls._recent_failure_records(values, now=now, window=window)
            if str(record.get("kind") or "") in COUNTED_FAILURE_KINDS
        ]

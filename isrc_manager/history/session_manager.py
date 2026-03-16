"""App-level history for profile lifecycle actions."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from .models import HistoryEntry


class SessionHistoryManager:
    """Stores undo/redo history for actions that span multiple profile databases."""

    def __init__(self, history_root: str | Path):
        self.history_root = Path(history_root)
        self.history_root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.history_root / "session_history.json"
        self.snapshot_dir = self.history_root / "session_profile_snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        self._state = self._load_state()

    # ------------------------------------------------------------------
    # Public queries
    # ------------------------------------------------------------------
    def list_entries(self, limit: int = 250) -> list[HistoryEntry]:
        current_id = self.get_current_entry_id()
        rows = sorted(self._state["entries"], key=lambda item: int(item["entry_id"]), reverse=True)[
            : int(limit)
        ]
        return [self._entry_from_dict(row, current_id=current_id) for row in rows]

    def get_current_entry_id(self) -> int | None:
        current_id = self._state.get("current_entry_id")
        return int(current_id) if current_id is not None else None

    def get_current_entry(self) -> HistoryEntry | None:
        current_id = self.get_current_entry_id()
        if current_id is None:
            return None
        for row in self._state["entries"]:
            if int(row["entry_id"]) == current_id:
                return self._entry_from_dict(row, current_id=current_id)
        return None

    def get_default_redo_entry(self) -> HistoryEntry | None:
        current_id = self.get_current_entry_id()
        candidates = []
        for row in self._state["entries"]:
            if not row.get("reversible", True):
                continue
            parent_id = row.get("parent_id")
            if current_id is None:
                if parent_id is None:
                    candidates.append(row)
            elif parent_id == current_id:
                candidates.append(row)
        if not candidates:
            return None
        selected = max(candidates, key=lambda item: int(item["entry_id"]))
        return self._entry_from_dict(selected, current_id=current_id)

    def can_undo(self) -> bool:
        entry = self.get_current_entry()
        return bool(entry and entry.reversible)

    def can_redo(self) -> bool:
        return self.get_default_redo_entry() is not None

    def describe_undo(self) -> str | None:
        entry = self.get_current_entry()
        if entry and entry.reversible:
            return entry.label
        return None

    def describe_redo(self) -> str | None:
        entry = self.get_default_redo_entry()
        return entry.label if entry is not None else None

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def capture_profile_snapshot(self, profile_path: str | Path, *, kind: str) -> str:
        source = Path(profile_path)
        if not source.exists():
            raise FileNotFoundError(source)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target = self.snapshot_dir / f"{timestamp}_{kind}_{source.name}"
        self._copy_profile_bundle(source, target)
        return str(target)

    def record_profile_switch(
        self,
        *,
        from_path: str,
        to_path: str,
        action_type: str = "profile.switch",
        label: str | None = None,
    ) -> HistoryEntry | None:
        from_norm = str(Path(from_path))
        to_norm = str(Path(to_path))
        if from_norm == to_norm:
            return None
        entry_id = self._insert_entry(
            label=label or f"Switch Profile: {Path(to_norm).name}",
            action_type=action_type,
            entity_type="Profile",
            entity_id=to_norm,
            payload={"from_path": from_norm, "to_path": to_norm},
            inverse_payload={"target_path": from_norm},
            redo_payload={"target_path": to_norm},
        )
        return self.fetch_entry(entry_id)

    def record_profile_create(
        self,
        *,
        created_path: str,
        previous_path: str,
    ) -> HistoryEntry:
        created_norm = str(Path(created_path))
        previous_norm = str(Path(previous_path))
        snapshot_path = self.capture_profile_snapshot(created_norm, kind="profile_create")
        entry_id = self._insert_entry(
            label=f"Create Profile: {Path(created_norm).name}",
            action_type="profile.create",
            entity_type="Profile",
            entity_id=created_norm,
            payload={"created_path": created_norm, "previous_path": previous_norm},
            inverse_payload={
                "created_path": created_norm,
                "previous_path": previous_norm,
                "snapshot_path": snapshot_path,
            },
            redo_payload={
                "created_path": created_norm,
                "previous_path": previous_norm,
                "snapshot_path": snapshot_path,
            },
        )
        return self.fetch_entry(entry_id)

    def record_profile_remove(
        self,
        *,
        deleted_path: str,
        current_path: str,
        fallback_path: str | None,
        deleting_current: bool,
        snapshot_path: str,
    ) -> HistoryEntry:
        deleted_norm = str(Path(deleted_path))
        current_norm = str(Path(current_path))
        fallback_norm = str(Path(fallback_path)) if fallback_path else None
        entry_id = self._insert_entry(
            label=f"Remove Profile: {Path(deleted_norm).name}",
            action_type="profile.remove",
            entity_type="Profile",
            entity_id=deleted_norm,
            payload={
                "deleted_path": deleted_norm,
                "deleting_current": deleting_current,
                "fallback_path": fallback_norm,
            },
            inverse_payload={
                "deleted_path": deleted_norm,
                "snapshot_path": snapshot_path,
                "deleting_current": deleting_current,
                "restore_open_path": deleted_norm if deleting_current else current_norm,
            },
            redo_payload={
                "deleted_path": deleted_norm,
                "deleting_current": deleting_current,
                "fallback_path": fallback_norm,
                "current_path": current_norm,
            },
        )
        return self.fetch_entry(entry_id)

    def fetch_entry(self, entry_id: int) -> HistoryEntry | None:
        current_id = self.get_current_entry_id()
        for row in self._state["entries"]:
            if int(row["entry_id"]) == int(entry_id):
                return self._entry_from_dict(row, current_id=current_id)
        return None

    # ------------------------------------------------------------------
    # Undo / redo
    # ------------------------------------------------------------------
    def undo(self, app) -> HistoryEntry | None:
        entry = self.get_current_entry()
        if entry is None or not entry.reversible:
            return None
        self._apply_payload(app, entry.action_type, entry.inverse_payload or {}, direction="undo")
        self._state["current_entry_id"] = entry.parent_id
        self._save_state()
        return entry

    def redo(self, app, entry_id: int | None = None) -> HistoryEntry | None:
        entry = (
            self.fetch_entry(entry_id) if entry_id is not None else self.get_default_redo_entry()
        )
        if entry is None or not entry.reversible:
            return None
        self._apply_payload(app, entry.action_type, entry.redo_payload or {}, direction="redo")
        self._state["current_entry_id"] = entry.entry_id
        self._save_state()
        return entry

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _insert_entry(
        self,
        *,
        label: str,
        action_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict,
        inverse_payload: dict,
        redo_payload: dict,
    ) -> int:
        entry_id = int(self._state["next_entry_id"])
        self._state["next_entry_id"] = entry_id + 1
        row = {
            "entry_id": entry_id,
            "parent_id": self.get_current_entry_id(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "label": label,
            "action_type": action_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "reversible": True,
            "strategy": "session",
            "payload": payload,
            "inverse_payload": inverse_payload,
            "redo_payload": redo_payload,
            "status": "applied",
        }
        self._state["entries"].append(row)
        self._state["current_entry_id"] = entry_id
        self._save_state()
        return entry_id

    def _apply_payload(self, app, action_type: str, payload: dict, *, direction: str) -> None:
        if action_type in {"profile.switch", "profile.browse"}:
            app._session_history_open_profile(payload["target_path"])
            return

        if action_type == "profile.create":
            if direction == "undo":
                app._session_history_delete_profile(payload["created_path"])
                app._session_history_open_profile(payload["previous_path"])
            else:
                self._restore_profile_bundle(payload["snapshot_path"], payload["created_path"])
                app._session_history_open_profile(payload["created_path"])
            return

        if action_type == "profile.remove":
            if direction == "undo":
                self._restore_profile_bundle(payload["snapshot_path"], payload["deleted_path"])
                restore_open_path = payload.get("restore_open_path")
                if restore_open_path:
                    app._session_history_open_profile(restore_open_path)
                else:
                    app._session_history_reload_profiles()
            else:
                app._session_history_delete_profile(payload["deleted_path"])
                if payload.get("deleting_current"):
                    fallback_path = payload.get("fallback_path")
                    if fallback_path:
                        app._session_history_open_profile(fallback_path)
                else:
                    current_path = payload.get("current_path")
                    app._session_history_reload_profiles(select_path=current_path)
            return

        raise ValueError(f"Unknown session history action: {action_type}")

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {"next_entry_id": 1, "current_entry_id": None, "entries": []}
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        raw.setdefault("next_entry_id", 1)
        raw.setdefault("current_entry_id", None)
        raw.setdefault("entries", [])
        return raw

    def _save_state(self) -> None:
        tmp_path = self.state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        tmp_path.replace(self.state_path)

    def _entry_from_dict(self, row: dict, *, current_id: int | None) -> HistoryEntry:
        return HistoryEntry(
            entry_id=int(row["entry_id"]),
            parent_id=int(row["parent_id"]) if row.get("parent_id") is not None else None,
            created_at=row.get("created_at", ""),
            label=row.get("label", ""),
            action_type=row.get("action_type", ""),
            entity_type=row.get("entity_type"),
            entity_id=row.get("entity_id"),
            reversible=bool(row.get("reversible", True)),
            strategy=row.get("strategy", "session"),
            payload=row.get("payload", {}),
            inverse_payload=row.get("inverse_payload"),
            redo_payload=row.get("redo_payload"),
            snapshot_before_id=None,
            snapshot_after_id=None,
            status=row.get("status", "applied"),
            is_current=int(row["entry_id"]) == current_id,
        )

    @staticmethod
    def _copy_profile_bundle(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        for suffix in ("-wal", "-shm"):
            companion = Path(str(source) + suffix)
            if companion.exists():
                shutil.copy2(companion, Path(str(target) + suffix))

    @staticmethod
    def _restore_profile_bundle(snapshot_path: str | Path, target_path: str | Path) -> None:
        snapshot = Path(snapshot_path)
        target = Path(target_path)
        if not snapshot.exists():
            raise FileNotFoundError(snapshot)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot, target)
        for suffix in ("-wal", "-shm"):
            target_companion = Path(str(target) + suffix)
            if target_companion.exists():
                target_companion.unlink()
            snapshot_companion = Path(str(snapshot) + suffix)
            if snapshot_companion.exists():
                shutil.copy2(snapshot_companion, target_companion)

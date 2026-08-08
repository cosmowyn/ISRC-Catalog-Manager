"""App-level history for profile lifecycle actions."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import HistoryEntry
from .session_bundle import (
    SNAPSHOT_INVENTORY_KEY,
    ProfileDeletionRollback,
    SessionProfileBundleStore,
)
from .snapshot_replay import profile_database_states_match


class SessionHistoryManager:
    """Stores undo/redo history for actions that span multiple profile databases."""

    STATUS_APPLIED = "applied"
    STATUS_UNDONE = "undone"
    STATUS_SUPERSEDED = "superseded"

    def __init__(
        self,
        history_root: str | Path,
        *,
        connection_factory: object | None = None,
    ):
        self.history_root = Path(history_root)
        self.connection_factory = connection_factory
        self.history_root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.history_root / "session_history.json"
        self.snapshot_dir = self.history_root / "session_profile_snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._bundle_store = SessionProfileBundleStore(self.snapshot_dir)

        self._state = self._load_state()
        self._ensure_invariants()

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
            if str(row.get("status", self.STATUS_APPLIED)) != self.STATUS_UNDONE:
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
            return str(entry.label)
        return None

    def describe_redo(self) -> str | None:
        entry = self.get_default_redo_entry()
        return str(entry.label) if entry is not None else None

    def snapshot_references(self) -> list[dict]:
        references: list[dict] = []
        for row in self._state["entries"]:
            payload = row.get("payload") or {}
            inverse_payload = row.get("inverse_payload") or {}
            redo_payload = row.get("redo_payload") or {}
            for source_name, source in (
                ("payload", payload),
                ("inverse_payload", inverse_payload),
                ("redo_payload", redo_payload),
            ):
                snapshot_path = str(source.get("snapshot_path") or "").strip()
                if not snapshot_path:
                    continue
                profile_path = (
                    str(source.get("deleted_path") or "").strip()
                    or str(source.get("created_path") or "").strip()
                    or str(payload.get("created_path") or "").strip()
                    or str(payload.get("deleted_path") or "").strip()
                    or str(row.get("entity_id") or "").strip()
                )
                references.append(
                    {
                        "entry_id": int(row["entry_id"]),
                        "label": str(row.get("label") or ""),
                        "action_type": str(row.get("action_type") or ""),
                        "snapshot_path": snapshot_path,
                        "profile_path": profile_path,
                        "source_name": source_name,
                    }
                )
        return references

    def remove_entries(self, entry_ids: list[int] | tuple[int, ...]) -> tuple[int, ...]:
        selected = {int(entry_id) for entry_id in entry_ids}
        if not selected:
            return ()
        before = len(self._state["entries"])
        self._state["entries"] = [
            row for row in self._state["entries"] if int(row["entry_id"]) not in selected
        ]
        if len(self._state["entries"]) == before:
            return ()
        self._ensure_invariants()
        return tuple(sorted(selected))

    def remove_entries_for_snapshot(self, snapshot_path: str | Path) -> tuple[int, ...]:
        target = str(Path(snapshot_path))
        entry_ids = [
            int(reference["entry_id"])
            for reference in self.snapshot_references()
            if str(Path(str(reference.get("snapshot_path") or ""))) == target
        ]
        return self.remove_entries(entry_ids)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def capture_profile_snapshot(self, profile_path: str | Path, *, kind: str) -> str:
        source = Path(profile_path)
        if not source.exists():
            raise FileNotFoundError(source)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target = self.snapshot_dir / f"{timestamp}_{kind}_{source.name}"
        target = self._bundle_store.validate_snapshot_path(target)
        self._bundle_store.capture(source, target)
        return str(target)

    def refresh_snapshot_inventories(
        self,
        snapshot_paths: Iterable[str | Path],
    ) -> int:
        """Refresh integrity metadata after an authorised snapshot-byte rewrite.

        Password rotation is the expected caller. Paths that are not referenced by
        this session history are ignored so callers may pass a mixed history batch.
        """

        requested = {self._bundle_store.cache_key(path) for path in snapshot_paths}
        if not requested:
            return 0

        matched_payloads: dict[str, list[dict]] = {}
        for row in self._state["entries"]:
            for payload_name in ("inverse_payload", "redo_payload"):
                payload = row.get(payload_name)
                if not isinstance(payload, dict):
                    continue
                raw_path = str(payload.get("snapshot_path") or "").strip()
                if not raw_path:
                    continue
                cache_key = self._bundle_store.cache_key(raw_path)
                if cache_key in requested:
                    matched_payloads.setdefault(cache_key, []).append(payload)

        if not matched_payloads:
            return 0

        refreshed: dict[str, dict[str, Any]] = {}
        for cache_key, payloads in matched_payloads.items():
            snapshot = self._bundle_store.validate_snapshot_path(payloads[0]["snapshot_path"])
            refreshed[cache_key] = self._bundle_store.capture_inventory(
                snapshot,
                require_main=True,
            )

        previous_state = copy.deepcopy(self._state)
        try:
            for cache_key, payloads in matched_payloads.items():
                inventory = refreshed[cache_key]
                for payload in payloads:
                    payload[SNAPSHOT_INVENTORY_KEY] = copy.deepcopy(inventory)
            self._save_state()
        except Exception:
            self._state = previous_state
            raise
        return len(refreshed)

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
        snapshot_inventory = self._inventory_for_record(snapshot_path)
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
                SNAPSHOT_INVENTORY_KEY: copy.deepcopy(snapshot_inventory),
            },
            redo_payload={
                "created_path": created_norm,
                "previous_path": previous_norm,
                "snapshot_path": snapshot_path,
                SNAPSHOT_INVENTORY_KEY: copy.deepcopy(snapshot_inventory),
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
        snapshot_inventory = self._inventory_for_record(snapshot_path)
        deleted_profile = Path(deleted_norm)
        try:
            self._bundle_store.finalize_recorded_removal(
                deleted_profile,
                snapshot_inventory,
            )
            entry_id = self._insert_entry(
                label=f"Remove Profile: {deleted_profile.name}",
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
                    SNAPSHOT_INVENTORY_KEY: copy.deepcopy(snapshot_inventory),
                },
                redo_payload={
                    "deleted_path": deleted_norm,
                    "deleting_current": deleting_current,
                    "fallback_path": fallback_norm,
                    "current_path": current_norm,
                    "snapshot_path": str(Path(snapshot_path)),
                    SNAPSHOT_INVENTORY_KEY: copy.deepcopy(snapshot_inventory),
                },
            )
        except Exception:
            try:
                self._bundle_store.restore_after_failed_removal_record(
                    deleted_profile,
                    Path(snapshot_path),
                    snapshot_inventory,
                )
            except Exception as rollback_exc:
                raise RuntimeError(
                    "Profile removal history could not be recorded, and the deleted profile "
                    "could not be restored without risking another file."
                ) from rollback_exc
            raise
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
    def undo(self, app: Any) -> HistoryEntry | None:
        self._ensure_invariants()
        entry = self.get_current_entry()
        if entry is None or not entry.reversible:
            return None
        previous_state = copy.deepcopy(self._state)
        replay_rollback = self._apply_payload(
            app,
            entry.action_type,
            entry.inverse_payload or {},
            direction="undo",
        )
        for row in self._state["entries"]:
            if int(row["entry_id"]) == entry.entry_id:
                row["status"] = self.STATUS_UNDONE
                break
        self._state["current_entry_id"] = entry.parent_id
        try:
            self._save_replay_state_with_compensation(
                app,
                entry,
                previous_state=previous_state,
                compensation_payload=entry.redo_payload or {},
                compensation_direction="redo",
                operation="Undo",
                replay_rollback=replay_rollback,
            )
        finally:
            if replay_rollback is not None:
                replay_rollback.close()
        return entry

    def redo(self, app: Any, entry_id: int | None = None) -> HistoryEntry | None:
        self._ensure_invariants()
        entry = (
            self.fetch_entry(entry_id) if entry_id is not None else self.get_default_redo_entry()
        )
        if entry is None or not entry.reversible:
            return None
        if not self._is_entry_redoable(entry):
            raise ValueError(f"Session history entry {entry.entry_id} is not redoable right now.")
        previous_state = copy.deepcopy(self._state)
        replay_rollback = self._apply_payload(
            app,
            entry.action_type,
            entry.redo_payload or {},
            direction="redo",
        )
        for row in self._state["entries"]:
            if int(row["entry_id"]) == entry.entry_id:
                row["status"] = self.STATUS_APPLIED
                break
        self._state["current_entry_id"] = entry.entry_id
        try:
            self._save_replay_state_with_compensation(
                app,
                entry,
                previous_state=previous_state,
                compensation_payload=entry.inverse_payload or {},
                compensation_direction="undo",
                operation="Redo",
                replay_rollback=replay_rollback,
            )
        finally:
            if replay_rollback is not None:
                replay_rollback.close()
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
        previous_state = copy.deepcopy(self._state)
        entry_id = int(self._state["next_entry_id"])
        try:
            parent_id = self.get_current_entry_id()
            for row in self._state["entries"]:
                row_parent_id = row.get("parent_id")
                if parent_id is None:
                    is_redo_child = row_parent_id is None
                else:
                    is_redo_child = (
                        int(row_parent_id) == int(parent_id) if row_parent_id is not None else False
                    )
                if (
                    is_redo_child
                    and str(row.get("status", self.STATUS_APPLIED)) == self.STATUS_UNDONE
                ):
                    row["status"] = self.STATUS_SUPERSEDED
            self._state["next_entry_id"] = entry_id + 1
            row = {
                "entry_id": entry_id,
                "parent_id": parent_id,
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
                "status": self.STATUS_APPLIED,
                "visible_in_history": True,
            }
            self._state["entries"].append(row)
            self._state["current_entry_id"] = entry_id
            self._save_state()
        except Exception:
            self._state = previous_state
            raise
        return entry_id

    def _apply_payload(
        self,
        app: Any,
        action_type: str,
        payload: dict,
        *,
        direction: str,
    ) -> ProfileDeletionRollback | None:
        if action_type in {"profile.switch", "profile.browse"}:
            app._session_history_open_profile(payload["target_path"])
            return None

        if action_type == "profile.create":
            snapshot, snapshot_inventory = self._bundle_store.verified_payload_snapshot(payload)
            created_path = Path(payload["created_path"])
            if direction == "undo":
                self._bundle_store.assert_live_matches(
                    created_path,
                    snapshot_inventory,
                    action="undo profile creation",
                    logical_matcher=self._logical_profile_matcher(created_path, snapshot),
                )
                return self._bundle_store.delete_profile_bundle(
                    app,
                    created_path,
                    after_delete=lambda: app._session_history_open_profile(
                        payload["previous_path"]
                    ),
                    after_rollback=lambda: app._session_history_open_profile(str(created_path)),
                )
            else:
                self._bundle_store.assert_live_absent(
                    created_path,
                    action="redo profile creation",
                )
                self._bundle_store.restore(
                    snapshot,
                    created_path,
                    snapshot_inventory,
                )
                try:
                    app._session_history_open_profile(str(created_path))
                except Exception:
                    self._bundle_store.remove_restored_if_unchanged(
                        created_path,
                        snapshot_inventory,
                    )
                    raise
            return None

        if action_type == "profile.remove":
            snapshot, snapshot_inventory = self._bundle_store.verified_payload_snapshot(payload)
            deleted_path = Path(payload["deleted_path"])
            if direction == "undo":
                self._bundle_store.assert_live_absent(
                    deleted_path,
                    action="undo profile removal",
                )
                self._bundle_store.restore(
                    snapshot,
                    deleted_path,
                    snapshot_inventory,
                )
                restore_open_path = payload.get("restore_open_path")
                try:
                    if restore_open_path:
                        app._session_history_open_profile(restore_open_path)
                    else:
                        app._session_history_reload_profiles()
                except Exception:
                    self._bundle_store.remove_restored_if_unchanged(
                        deleted_path,
                        snapshot_inventory,
                    )
                    raise
            else:
                self._bundle_store.assert_live_matches(
                    deleted_path,
                    snapshot_inventory,
                    action="redo profile removal",
                    logical_matcher=self._logical_profile_matcher(deleted_path, snapshot),
                )
                return self._bundle_store.delete_profile_bundle(
                    app,
                    deleted_path,
                    after_delete=lambda: self._navigate_after_profile_removal(
                        app,
                        payload,
                    ),
                    after_rollback=lambda: self._navigate_after_profile_removal_rollback(
                        app,
                        payload,
                        deleted_path,
                    ),
                )
            return None

        raise ValueError(f"Unknown session history action: {action_type}")

    @staticmethod
    def _navigate_after_profile_removal(app: Any, payload: dict) -> None:
        if payload.get("deleting_current"):
            fallback_path = payload.get("fallback_path")
            if fallback_path:
                app._session_history_open_profile(fallback_path)
            return
        app._session_history_reload_profiles(select_path=payload.get("current_path"))

    @staticmethod
    def _navigate_after_profile_removal_rollback(
        app: Any,
        payload: dict,
        deleted_path: Path,
    ) -> None:
        if payload.get("deleting_current"):
            app._session_history_open_profile(str(deleted_path))
            return
        app._session_history_reload_profiles(select_path=payload.get("current_path"))

    def _logical_profile_matcher(
        self,
        live_path: Path,
        snapshot_path: Path,
    ) -> Callable[[], bool] | None:
        if self.connection_factory is None:
            return None
        return lambda: profile_database_states_match(
            live_path,
            snapshot_path,
            connection_factory=self.connection_factory,
        )

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"next_entry_id": 1, "current_entry_id": None, "entries": []}
        raw: dict[str, Any] = json.loads(self.state_path.read_text(encoding="utf-8"))
        raw.setdefault("next_entry_id", 1)
        raw.setdefault("current_entry_id", None)
        raw.setdefault("entries", [])
        return raw

    def _ensure_invariants(self) -> None:
        current_id = self.get_current_entry_id()
        if current_id is not None and self.fetch_entry(current_id) is None:
            self._state["current_entry_id"] = self._select_fallback_current_entry_id()
        if all(
            str(row.get("status", self.STATUS_APPLIED)) == self.STATUS_APPLIED
            for row in self._state["entries"]
        ):
            self._bootstrap_statuses()
        self._save_state()

    def _bootstrap_statuses(self) -> None:
        current_id = self.get_current_entry_id()
        applied_ids: set[int] = set()
        parent_map = {
            int(row["entry_id"]): (
                int(row["parent_id"]) if row.get("parent_id") is not None else None
            )
            for row in self._state["entries"]
        }
        while current_id is not None and current_id in parent_map:
            applied_ids.add(int(current_id))
            current_id = parent_map[current_id]
        for row in self._state["entries"]:
            row["status"] = (
                self.STATUS_APPLIED if int(row["entry_id"]) in applied_ids else self.STATUS_UNDONE
            )

    def _select_fallback_current_entry_id(self) -> int | None:
        applied_ids = {
            int(row["entry_id"])
            for row in self._state["entries"]
            if str(row.get("status", self.STATUS_APPLIED)) == self.STATUS_APPLIED
        }
        applied_child_ids = {
            int(row["parent_id"])
            for row in self._state["entries"]
            if row.get("parent_id") is not None
            and str(row.get("status", self.STATUS_APPLIED)) == self.STATUS_APPLIED
        }
        leaf_ids = sorted(applied_ids - applied_child_ids, reverse=True)
        return leaf_ids[0] if leaf_ids else None

    def _is_entry_redoable(self, entry: HistoryEntry) -> bool:
        if entry.status != self.STATUS_UNDONE:
            return False
        current_id = self.get_current_entry_id()
        if current_id is None:
            return entry.parent_id is None
        return bool(entry.parent_id == current_id)

    def _save_state(self) -> None:
        tmp_path = self.state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        tmp_path.replace(self.state_path)

    def _save_replay_state_with_compensation(
        self,
        app: Any,
        entry: HistoryEntry,
        *,
        previous_state: dict[str, Any],
        compensation_payload: dict,
        compensation_direction: str,
        operation: str,
        replay_rollback: ProfileDeletionRollback | None,
    ) -> None:
        try:
            self._save_state()
        except Exception as save_exc:
            self._state = previous_state
            try:
                if replay_rollback is not None:
                    replay_rollback.rollback()
                else:
                    self._apply_payload(
                        app,
                        entry.action_type,
                        compensation_payload,
                        direction=compensation_direction,
                    )
            except Exception as compensation_exc:
                raise RuntimeError(
                    f"{operation} changed the profile but its history state could not be saved, "
                    "and the automatic filesystem rollback also failed."
                ) from compensation_exc
            raise RuntimeError(
                f"{operation} could not save its history state; the profile change was rolled back."
            ) from save_exc

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
            visible_in_history=bool(row.get("visible_in_history", True)),
            is_current=int(row["entry_id"]) == current_id,
        )

    def _inventory_for_record(self, snapshot_path: str | Path) -> dict[str, Any]:
        return self._bundle_store.inventory_for_record(snapshot_path)

    def _restore_profile_bundle(
        self,
        snapshot_path: str | Path,
        target_path: str | Path,
        expected_inventory: dict[str, Any] | None = None,
    ) -> None:
        self._bundle_store.restore(snapshot_path, target_path, expected_inventory)

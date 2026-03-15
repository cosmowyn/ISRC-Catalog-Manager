"""Task-friendly history helpers shared by background workflows."""

from __future__ import annotations

import logging
from pathlib import Path


def run_snapshot_history_action(
    *,
    history_manager,
    action_label: str,
    action_type: str,
    mutation,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    payload: dict | None = None,
    before_kind: str | None = None,
    before_label: str | None = None,
    after_kind: str | None = None,
    after_label: str | None = None,
    logger: logging.Logger | None = None,
):
    if history_manager is None:
        return mutation()

    safe_kind = action_type.replace(".", "_")
    before_snapshot = history_manager.capture_snapshot(
        kind=before_kind or f"pre_{safe_kind}",
        label=before_label or f"Before {action_label}",
    )
    try:
        result = mutation()
    except Exception:
        try:
            history_manager.restore_snapshot(before_snapshot.snapshot_id)
        except Exception as restore_error:
            if logger is not None:
                logger.exception("Snapshot rollback failed for %s: %s", action_type, restore_error)
        try:
            history_manager.delete_snapshot(before_snapshot.snapshot_id)
        except Exception:
            pass
        raise

    after_snapshot = history_manager.capture_snapshot(
        kind=after_kind or f"post_{safe_kind}",
        label=after_label or f"After {action_label}",
    )
    history_manager.record_snapshot_action(
        label=action_label,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        payload=payload or {},
        snapshot_before_id=before_snapshot.snapshot_id,
        snapshot_after_id=after_snapshot.snapshot_id,
    )
    return result


def run_file_history_action(
    *,
    history_manager,
    action_label,
    action_type: str,
    target_path: str | Path,
    mutation,
    companion_suffixes: tuple[str, ...] = (),
    entity_type: str | None = "File",
    entity_id: str | None = None,
    payload=None,
    logger: logging.Logger | None = None,
):
    if history_manager is None:
        return mutation()

    before_state = history_manager.capture_file_state(
        target_path,
        companion_suffixes=companion_suffixes,
    )
    try:
        result = mutation()
    except Exception:
        try:
            history_manager.restore_file_state(target_path, before_state)
        except Exception as restore_error:
            if logger is not None:
                logger.exception("File rollback failed for %s: %s", action_type, restore_error)
        raise

    after_state = history_manager.capture_file_state(
        target_path,
        companion_suffixes=companion_suffixes,
    )
    if before_state != after_state:
        final_label = action_label(result) if callable(action_label) else action_label
        final_payload = payload(result) if callable(payload) else (payload or {})
        history_manager.record_file_write_action(
            label=final_label,
            action_type=action_type,
            target_path=target_path,
            before_state=before_state,
            after_state=after_state,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=final_payload,
        )
    return result

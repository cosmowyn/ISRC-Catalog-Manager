"""Deterministic UI PQ probes for destructive Party and Rights history."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from isrc_manager.history import HistoryEntry, HistoryManager
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.rights import RightPayload, RightsService

DELETE_PARTY_NAME = "UI PQ History Delete Party"
DELETE_PARTY_ALIAS = "UI PQ History Delete Alias"
MERGE_PRIMARY_PARTY_NAME = "UI PQ History Merge Primary"
MERGE_DUPLICATE_PARTY_NAME = "UI PQ History Merge Duplicate"
MERGE_RIGHT_TITLE = "UI PQ History Merge Relationship"
DELETE_RIGHT_TITLE = "UI PQ History Delete Right"


class _HistoryHost(Protocol):
    history_manager: HistoryManager | None
    party_service: PartyService | None
    rights_service: RightsService | None


class _PartyHistoryPanel(Protocol):
    delete_party_handler: Callable[[list[int]], object] | None
    merge_party_handler: Callable[[int, list[int]], object] | None


class _RightsHistoryPanel(Protocol):
    delete_right_handler: Callable[[int], object] | None


def _required_history(host: _HistoryHost) -> HistoryManager:
    history = host.history_manager
    if history is None:
        raise AssertionError("Profile history is unavailable for destructive-action qualification.")
    return history


def _required_services(host: _HistoryHost) -> tuple[PartyService, RightsService]:
    party_service = host.party_service
    rights_service = host.rights_service
    if party_service is None or rights_service is None:
        raise AssertionError("Party or Rights service is unavailable for history qualification.")
    return party_service, rights_service


def _require_current_action(history: HistoryManager, action_type: str) -> HistoryEntry:
    entry = history.get_current_entry()
    if entry is None or entry.action_type != action_type:
        actual = "none" if entry is None else entry.action_type
        raise AssertionError(f"Expected current history action {action_type!r}, found {actual!r}.")
    return entry


def _require_replayed_entry(
    entry: HistoryEntry | None,
    *,
    expected_entry_id: int,
    direction: str,
) -> None:
    if entry is None or entry.entry_id != expected_entry_id:
        raise AssertionError(f"{direction.title()} did not replay the expected history entry.")


def _optional_id(value: int) -> int | None:
    normalized = int(value)
    return normalized if normalized > 0 else None


def qualify_party_delete_merge_history(
    host: _HistoryHost,
    panel: _PartyHistoryPanel,
    *,
    work_id: int,
) -> dict[str, object]:
    """Exercise injected Party delete/merge handlers through complete replay cycles."""

    history = _required_history(host)
    party_service, rights_service = _required_services(host)
    delete_handler = panel.delete_party_handler
    merge_handler = panel.merge_party_handler
    if not callable(delete_handler) or not callable(merge_handler):
        raise AssertionError("Party Manager destructive history handlers were not injected.")

    delete_party_id = party_service.create_party(
        PartyPayload(
            legal_name=f"{DELETE_PARTY_NAME} B.V.",
            display_name=DELETE_PARTY_NAME,
            party_type="publisher",
            artist_aliases=[DELETE_PARTY_ALIAS],
        )
    )
    primary_party_id = party_service.create_party(
        PartyPayload(
            legal_name=f"{MERGE_PRIMARY_PARTY_NAME} B.V.",
            display_name=MERGE_PRIMARY_PARTY_NAME,
            party_type="publisher",
        )
    )
    duplicate_party_id = party_service.create_party(
        PartyPayload(
            legal_name=f"{MERGE_DUPLICATE_PARTY_NAME} B.V.",
            display_name=MERGE_DUPLICATE_PARTY_NAME,
            party_type="publisher",
        )
    )
    merge_right_id = rights_service.create_right(
        RightPayload(
            title=MERGE_RIGHT_TITLE,
            right_type="other",
            work_id=int(work_id),
            granted_to_party_id=duplicate_party_id,
        )
    )
    delete_handler([delete_party_id])
    delete_entry = _require_current_action(history, "party.delete")
    delete_removed = party_service.fetch_party(delete_party_id) is None
    if not delete_removed:
        raise AssertionError("Party delete handler did not remove the transient Party.")

    undone = history.undo()
    _require_replayed_entry(
        undone,
        expected_entry_id=delete_entry.entry_id,
        direction="undo",
    )
    restored_delete_party = party_service.fetch_party(delete_party_id)
    delete_undo_restored = restored_delete_party is not None
    delete_undo_alias_restored = bool(
        restored_delete_party is not None
        and DELETE_PARTY_ALIAS in restored_delete_party.artist_aliases
    )
    if not delete_undo_restored or not delete_undo_alias_restored:
        raise AssertionError("Party delete Undo did not restore the Party and alias relationship.")

    redone = history.redo()
    _require_replayed_entry(
        redone,
        expected_entry_id=delete_entry.entry_id,
        direction="redo",
    )
    delete_redo_removed = party_service.fetch_party(delete_party_id) is None
    if not delete_redo_removed:
        raise AssertionError("Party delete Redo did not remove the transient Party.")

    merge_handler(primary_party_id, [duplicate_party_id])
    merge_entry = _require_current_action(history, "party.merge")
    merged_right = rights_service.fetch_right(merge_right_id)
    merge_applied = (
        party_service.fetch_party(duplicate_party_id) is None
        and merged_right is not None
        and merged_right.granted_to_party_id == primary_party_id
    )
    if not merge_applied:
        raise AssertionError("Party merge did not reassign the transient Rights relationship.")

    undone = history.undo()
    _require_replayed_entry(
        undone,
        expected_entry_id=merge_entry.entry_id,
        direction="undo",
    )
    restored_right = rights_service.fetch_right(merge_right_id)
    merge_undo_restored = (
        party_service.fetch_party(duplicate_party_id) is not None
        and restored_right is not None
        and restored_right.granted_to_party_id == duplicate_party_id
    )
    if not merge_undo_restored:
        raise AssertionError("Party merge Undo did not restore the duplicate and Rights link.")

    redone = history.redo()
    _require_replayed_entry(
        redone,
        expected_entry_id=merge_entry.entry_id,
        direction="redo",
    )
    redone_right = rights_service.fetch_right(merge_right_id)
    merge_redo_applied = (
        party_service.fetch_party(primary_party_id) is not None
        and party_service.fetch_party(duplicate_party_id) is None
        and redone_right is not None
        and redone_right.granted_to_party_id == primary_party_id
    )
    if not merge_redo_applied:
        raise AssertionError("Party merge Redo did not restore the merged state.")

    return {
        "party_delete_handler_injected": True,
        "party_delete_action_type": delete_entry.action_type,
        "party_delete_action_label": delete_entry.label,
        "party_delete_transient_id": delete_party_id,
        "party_delete_removed": delete_removed,
        "party_delete_undo_restored": delete_undo_restored,
        "party_delete_undo_alias_restored": delete_undo_alias_restored,
        "party_delete_redo_removed": delete_redo_removed,
        "party_merge_handler_injected": True,
        "party_merge_action_type": merge_entry.action_type,
        "party_merge_action_label": merge_entry.label,
        "party_merge_primary_transient_id": primary_party_id,
        "party_merge_duplicate_transient_id": duplicate_party_id,
        "party_merge_right_transient_id": merge_right_id,
        "party_merge_applied": merge_applied,
        "party_merge_undo_restored": merge_undo_restored,
        "party_merge_redo_applied": merge_redo_applied,
    }


def qualify_right_delete_history(
    host: _HistoryHost,
    panel: _RightsHistoryPanel,
    *,
    party_id: int,
    work_id: int,
    track_id: int,
    release_id: int,
    contract_id: int,
    primary_right_id: int,
) -> dict[str, object]:
    """Exercise the injected Rights delete handler through Undo and final Redo."""

    history = _required_history(host)
    _, rights_service = _required_services(host)
    delete_handler = panel.delete_right_handler
    if not callable(delete_handler):
        raise AssertionError("Rights Matrix delete history handler was not injected.")

    transient_right_id = rights_service.create_right(
        RightPayload(
            title=DELETE_RIGHT_TITLE,
            right_type="promotional",
            territory="UI PQ Test Territory",
            media_use_type="Qualification",
            granted_by_party_id=int(party_id),
            granted_to_party_id=int(party_id),
            retained_by_party_id=int(party_id),
            source_contract_id=_optional_id(contract_id),
            work_id=int(work_id),
            track_id=_optional_id(track_id),
            release_id=_optional_id(release_id),
        )
    )
    delete_handler(transient_right_id)
    delete_entry = _require_current_action(history, "right.delete")
    right_removed = rights_service.fetch_right(transient_right_id) is None
    if not right_removed:
        raise AssertionError("Rights delete handler did not remove the transient record.")

    undone = history.undo()
    _require_replayed_entry(
        undone,
        expected_entry_id=delete_entry.entry_id,
        direction="undo",
    )
    restored = rights_service.fetch_right(transient_right_id)
    right_undo_restored = restored is not None
    right_undo_relationships_restored = bool(
        restored is not None
        and restored.granted_to_party_id == int(party_id)
        and restored.source_contract_id == _optional_id(contract_id)
        and restored.work_id == int(work_id)
        and restored.track_id == _optional_id(track_id)
        and restored.release_id == _optional_id(release_id)
    )
    if not right_undo_restored or not right_undo_relationships_restored:
        raise AssertionError("Rights delete Undo did not restore the record and relationships.")

    redone = history.redo()
    _require_replayed_entry(
        redone,
        expected_entry_id=delete_entry.entry_id,
        direction="redo",
    )
    right_redo_removed = rights_service.fetch_right(transient_right_id) is None
    primary_right_preserved = rights_service.fetch_right(int(primary_right_id)) is not None
    if not right_redo_removed or not primary_right_preserved:
        raise AssertionError("Rights delete Redo changed the wrong Rights record.")

    return {
        "right_delete_handler_injected": True,
        "right_delete_action_type": delete_entry.action_type,
        "right_delete_action_label": delete_entry.label,
        "right_delete_transient_id": transient_right_id,
        "right_delete_removed": right_removed,
        "right_delete_undo_restored": right_undo_restored,
        "right_delete_undo_relationships_restored": right_undo_relationships_restored,
        "right_delete_redo_removed": right_redo_removed,
        "right_delete_primary_record_preserved": primary_right_preserved,
    }

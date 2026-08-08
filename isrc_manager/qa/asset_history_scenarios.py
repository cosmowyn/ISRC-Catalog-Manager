"""Deterministic UI PQ probe for reversible Asset Registry deletion."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from isrc_manager.assets import AssetService, AssetVersionPayload
from isrc_manager.file_storage import STORAGE_MODE_MANAGED_FILE
from isrc_manager.history import HistoryEntry, HistoryManager

TRANSIENT_ASSET_FILENAME = "ui-pq-asset-history-master.wav"
EXTERNAL_REFERENCE_FILENAME = "ui-pq-asset-history-source.wav"
ASSET_CONTENT = b"UI PQ reversible managed asset fixture\n"


class _AssetHistoryHost(Protocol):
    history_manager: HistoryManager | None
    asset_service: AssetService | None


class _AssetHistoryPanel(Protocol):
    delete_asset_handler: Callable[[int], object] | None


def _required_history(host: _AssetHistoryHost) -> HistoryManager:
    history = host.history_manager
    if history is None:
        raise AssertionError("Profile history is unavailable for Asset deletion qualification.")
    return history


def _required_asset_service(host: _AssetHistoryHost) -> AssetService:
    service = host.asset_service
    if service is None:
        raise AssertionError("Asset service is unavailable for Asset deletion qualification.")
    if service.data_root is None:
        raise AssertionError("Managed Asset storage is unavailable for deletion qualification.")
    return service


def _require_current_asset_delete(history: HistoryManager) -> HistoryEntry:
    entry = history.get_current_entry()
    if entry is None or entry.action_type != "asset.delete":
        actual = "none" if entry is None else entry.action_type
        raise AssertionError(f"Expected current history action 'asset.delete', found {actual!r}.")
    return entry


def _require_replayed_entry(
    entry: HistoryEntry | None,
    *,
    expected_entry_id: int,
    direction: str,
) -> None:
    if entry is None or entry.entry_id != expected_entry_id:
        raise AssertionError(f"Asset delete {direction} did not replay the expected history entry.")


def _require_external_reference(path: Path) -> None:
    if not path.is_file() or path.read_bytes() != ASSET_CONTENT:
        raise AssertionError("Asset deletion changed or removed the external source file.")


def _require_preserved_asset(service: AssetService, asset_id: int) -> None:
    if service.fetch_asset(int(asset_id)) is None:
        raise AssertionError("Asset deletion changed the seeded registry record used by UI PQ.")


def qualify_asset_delete_history(
    host: _AssetHistoryHost,
    panel: _AssetHistoryPanel,
    *,
    track_id: int,
    preserved_asset_id: int,
) -> dict[str, object]:
    """Exercise the injected Asset delete handler through Undo and final Redo."""

    history = _required_history(host)
    service = _required_asset_service(host)
    delete_handler = panel.delete_asset_handler
    if not callable(delete_handler):
        raise AssertionError("Asset Registry delete history handler was not injected.")

    external_root = service.data_root.parent / "ui-pq-external-references"
    external_root.mkdir(parents=True, exist_ok=True)
    external_reference = external_root / EXTERNAL_REFERENCE_FILENAME
    external_reference.write_bytes(ASSET_CONTENT)
    if service.asset_store.is_managed(str(external_reference)):
        raise AssertionError("The external Asset source unexpectedly resolved as managed storage.")

    transient_asset_id = service.create_asset(
        AssetVersionPayload(
            asset_type="alt_master",
            filename=TRANSIENT_ASSET_FILENAME,
            source_path=str(external_reference),
            storage_mode=STORAGE_MODE_MANAGED_FILE,
            track_id=int(track_id),
            version_status="approved",
            notes="Created by the automated UI PQ reversible Asset deletion workflow.",
        )
    )
    transient_asset = service.fetch_asset(transient_asset_id)
    if transient_asset is None:
        raise AssertionError("Transient managed Asset was not created for deletion qualification.")
    managed_path = service.resolve_asset_path(transient_asset.stored_path)
    if managed_path is None or not managed_path.is_file():
        raise AssertionError("Transient Asset did not create an app-managed file.")
    if managed_path.read_bytes() != ASSET_CONTENT:
        raise AssertionError("Transient app-managed Asset content did not match its source.")
    _require_external_reference(external_reference)
    _require_preserved_asset(service, preserved_asset_id)

    delete_handler(transient_asset_id)
    delete_entry = _require_current_asset_delete(history)
    delete_removed = service.fetch_asset(transient_asset_id) is None
    managed_file_removed = not managed_path.exists()
    if not delete_removed or not managed_file_removed:
        raise AssertionError("Asset delete did not remove its database row and managed file.")
    _require_external_reference(external_reference)
    _require_preserved_asset(service, preserved_asset_id)

    undone = history.undo()
    _require_replayed_entry(
        undone,
        expected_entry_id=delete_entry.entry_id,
        direction="Undo",
    )
    restored = service.fetch_asset(transient_asset_id)
    undo_restored = bool(
        restored is not None
        and restored.filename == TRANSIENT_ASSET_FILENAME
        and restored.asset_type == "alt_master"
        and restored.track_id == int(track_id)
        and restored.stored_path == transient_asset.stored_path
        and restored.version_status == "approved"
    )
    undo_managed_file_restored = (
        managed_path.is_file() and managed_path.read_bytes() == ASSET_CONTENT
    )
    if not undo_restored or not undo_managed_file_restored:
        raise AssertionError("Asset delete Undo did not restore the row and app-managed file.")
    _require_external_reference(external_reference)
    _require_preserved_asset(service, preserved_asset_id)

    redone = history.redo()
    _require_replayed_entry(
        redone,
        expected_entry_id=delete_entry.entry_id,
        direction="Redo",
    )
    redo_removed = service.fetch_asset(transient_asset_id) is None
    redo_managed_file_removed = not managed_path.exists()
    if not redo_removed or not redo_managed_file_removed:
        raise AssertionError("Asset delete Redo did not remove the row and app-managed file.")
    _require_external_reference(external_reference)
    _require_preserved_asset(service, preserved_asset_id)

    return {
        "asset_delete_handler_injected": True,
        "asset_delete_action_type": delete_entry.action_type,
        "asset_delete_action_label": delete_entry.label,
        "asset_delete_transient_id": transient_asset_id,
        "asset_delete_removed": delete_removed,
        "asset_delete_managed_file_removed": managed_file_removed,
        "asset_delete_undo_restored": undo_restored,
        "asset_delete_undo_managed_file_restored": undo_managed_file_restored,
        "asset_delete_redo_removed": redo_removed,
        "asset_delete_redo_managed_file_removed": redo_managed_file_removed,
        "asset_delete_external_reference_preserved": True,
        "asset_delete_seeded_asset_preserved": True,
        "asset_delete_managed_path": str(transient_asset.stored_path or ""),
        "asset_delete_external_reference_filename": external_reference.name,
    }

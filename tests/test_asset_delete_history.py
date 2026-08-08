from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from PySide6.QtCore import QSettings

from isrc_manager.assets import AssetService, AssetVersionPayload
from isrc_manager.file_storage import STORAGE_MODE_MANAGED_FILE
from isrc_manager.history import HistoryManager
from isrc_manager.services import (
    DatabaseSchemaService,
    DatabaseSessionService,
    TrackCreatePayload,
    TrackService,
)
from isrc_manager.tasks.history_helpers import run_snapshot_history_action


@pytest.fixture()
def asset_history(tmp_path: Path):
    db_path = tmp_path / "Database" / "library.db"
    data_root = tmp_path / "data"
    backups_root = tmp_path / "backups"
    data_root.mkdir()
    backups_root.mkdir()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    sessions = DatabaseSessionService()
    session = sessions.open(db_path)
    conn = session.conn
    schema = DatabaseSchemaService(conn, data_root=data_root)
    schema.init_db()
    schema.migrate_schema()
    tracks = TrackService(conn, data_root=data_root)
    assets = AssetService(conn, data_root=data_root)
    history = HistoryManager(
        conn,
        settings,
        db_path,
        tmp_path / "history",
        data_root,
        backups_root,
    )
    track_id = tracks.create_track(
        TrackCreatePayload(
            isrc="NL-TST-26-00881",
            track_title="Asset Undo",
            artist_name="History Artist",
            additional_artists=[],
            album_title="History Album",
            release_date="2026-08-08",
            track_length_sec=181,
            iswc=None,
            upc=None,
            genre="Test",
        )
    )
    try:
        yield assets, history, track_id
    finally:
        settings.clear()
        sessions.close(conn)


def _record_asset_delete(
    assets: AssetService,
    history: HistoryManager,
    asset_id: int,
) -> None:
    asset = assets.fetch_asset(asset_id)
    assert asset is not None
    run_snapshot_history_action(
        history_manager=history,
        action_label=f"Delete Asset: {asset.filename}",
        action_type="asset.delete",
        entity_type="AssetVersion",
        entity_id=asset_id,
        payload={"filename": asset.filename, "asset_type": asset.asset_type},
        mutation=lambda: assets.delete_asset(asset_id),
    )


def test_managed_asset_delete_undo_redo_restores_row_and_file(
    asset_history,
    tmp_path: Path,
) -> None:
    assets, history, track_id = asset_history
    source = tmp_path / "external-source.wav"
    source.write_bytes(b"managed asset history")
    asset_id = assets.create_asset(
        AssetVersionPayload(
            asset_type="main_master",
            source_path=str(source),
            storage_mode=STORAGE_MODE_MANAGED_FILE,
            track_id=track_id,
            version_status="approved",
        )
    )
    asset = assets.fetch_asset(asset_id)
    assert asset is not None
    managed_path = assets.resolve_asset_path(asset.stored_path)
    assert managed_path is not None and managed_path.exists()

    _record_asset_delete(assets, history, asset_id)

    assert assets.fetch_asset(asset_id) is None
    assert not managed_path.exists()
    assert source.read_bytes() == b"managed asset history"
    assert history.describe_undo() == f"Delete Asset: {source.name}"

    history.undo()

    restored = assets.fetch_asset(asset_id)
    assert restored is not None
    assert restored.stored_path == asset.stored_path
    assert managed_path.read_bytes() == b"managed asset history"
    assert source.read_bytes() == b"managed asset history"

    history.redo()

    assert assets.fetch_asset(asset_id) is None
    assert not managed_path.exists()
    assert source.read_bytes() == b"managed asset history"


def test_shared_managed_asset_alias_remains_safe_through_delete_undo_redo(
    asset_history,
    tmp_path: Path,
) -> None:
    assets, history, track_id = asset_history
    source = tmp_path / "shared-history-source.wav"
    source.write_bytes(b"shared asset history")
    first_id = assets.create_asset(
        AssetVersionPayload(
            asset_type="main_master",
            source_path=str(source),
            storage_mode=STORAGE_MODE_MANAGED_FILE,
            track_id=track_id,
        )
    )
    first = assets.fetch_asset(first_id)
    assert first is not None and first.stored_path is not None
    managed_path = assets.resolve_asset_path(first.stored_path)
    assert managed_path is not None
    lexical_alias = f"{Path(first.stored_path).parent.as_posix()}/./{Path(first.stored_path).name}"
    second_id = assets.create_asset(
        AssetVersionPayload(
            asset_type="alt_master",
            filename="shared-history-source.wav",
            stored_path=first.stored_path,
            storage_mode=STORAGE_MODE_MANAGED_FILE,
            track_id=track_id,
        )
    )
    with assets.conn:
        assets.conn.execute(
            "UPDATE AssetVersions SET stored_path=? WHERE id=?",
            (lexical_alias, second_id),
        )

    _record_asset_delete(assets, history, first_id)
    assert assets.fetch_asset(first_id) is None
    assert assets.fetch_asset(second_id) is not None
    assert managed_path.read_bytes() == b"shared asset history"

    history.undo()
    assert assets.fetch_asset(first_id) is not None
    assert assets.fetch_asset(second_id) is not None
    assert managed_path.read_bytes() == b"shared asset history"

    history.redo()
    assert assets.fetch_asset(first_id) is None
    assert assets.fetch_asset(second_id) is not None
    assert managed_path.read_bytes() == b"shared asset history"

    _record_asset_delete(assets, history, second_id)
    assert assets.fetch_asset(second_id) is None
    assert not managed_path.exists()

    history.undo()
    assert assets.fetch_asset(second_id) is not None
    assert managed_path.read_bytes() == b"shared asset history"

    history.redo()
    assert assets.fetch_asset(second_id) is None
    assert not managed_path.exists()
    assert source.read_bytes() == b"shared asset history"


def test_reference_asset_file_survives_delete_undo_and_redo(
    asset_history,
    tmp_path: Path,
) -> None:
    assets, history, track_id = asset_history
    reference = tmp_path / "outside-managed-storage.wav"
    reference.write_bytes(b"reference must survive")
    asset_id = assets.create_asset(
        AssetVersionPayload(
            asset_type="alt_master",
            filename=reference.name,
            stored_path=str(reference),
            storage_mode=STORAGE_MODE_MANAGED_FILE,
            track_id=track_id,
        )
    )

    _record_asset_delete(assets, history, asset_id)
    assert assets.fetch_asset(asset_id) is None
    assert reference.read_bytes() == b"reference must survive"

    history.undo()
    assert assets.fetch_asset(asset_id) is not None
    assert reference.read_bytes() == b"reference must survive"

    history.redo()
    assert assets.fetch_asset(asset_id) is None
    assert reference.read_bytes() == b"reference must survive"


def test_asset_delete_history_failure_restores_managed_row_and_file(
    asset_history,
    tmp_path: Path,
) -> None:
    assets, history, track_id = asset_history
    source = tmp_path / "rollback-source.wav"
    source.write_bytes(b"restore on history failure")
    asset_id = assets.create_asset(
        AssetVersionPayload(
            asset_type="main_master",
            source_path=str(source),
            storage_mode=STORAGE_MODE_MANAGED_FILE,
            track_id=track_id,
        )
    )
    asset = assets.fetch_asset(asset_id)
    assert asset is not None
    managed_path = assets.resolve_asset_path(asset.stored_path)
    assert managed_path is not None

    with (
        mock.patch.object(
            history,
            "record_snapshot_action",
            side_effect=RuntimeError("history write failed"),
        ),
        pytest.raises(RuntimeError, match="history write failed"),
    ):
        _record_asset_delete(assets, history, asset_id)

    assert assets.fetch_asset(asset_id) is not None
    assert managed_path.read_bytes() == b"restore on history failure"
    assert source.read_bytes() == b"restore on history failure"
    assert history.list_entries(include_hidden=True) == []

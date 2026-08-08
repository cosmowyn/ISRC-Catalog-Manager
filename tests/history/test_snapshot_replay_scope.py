import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QSettings

from isrc_manager.code_registry import BUILTIN_CATEGORY_CATALOG_NUMBER, CodeRegistryService
from isrc_manager.history import HistoryManager, HistoryRecoveryError
from isrc_manager.history.snapshot_replay import SnapshotConnectionError
from isrc_manager.history.snapshot_scope import (
    capture_managed_file_inventory,
    changed_managed_files,
    changed_setting_keys,
    restore_managed_files,
    validate_managed_files_match,
    validate_setting_values_match,
)
from isrc_manager.invoicing import LedgerEntryDraft, LedgerPostingService
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.services import DatabaseSchemaService, TrackCreatePayload, TrackService
from isrc_manager.services.database_security import (
    SQLITE_HEADER,
    DatabaseSessionPasswordManager,
    is_probably_encrypted_database,
)
from isrc_manager.services.db_access import SQLiteConnectionFactory
from isrc_manager.tasks.history_helpers import run_snapshot_history_action


def _initialize_schema(conn) -> None:
    schema = DatabaseSchemaService(conn)
    schema.init_db()
    schema.migrate_schema()


def _history_manager(
    conn,
    settings: QSettings,
    tmp_path: Path,
    db_path: Path,
    *,
    connection_factory: SQLiteConnectionFactory | None = None,
) -> HistoryManager:
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    return HistoryManager(
        conn,
        settings,
        db_path,
        tmp_path / "history",
        data_root,
        tmp_path / "backups",
        connection_factory=connection_factory,
    )


def _create_track(service: TrackService, *, isrc: str = "NL-ABC-26-00421") -> int:
    return service.create_track(
        TrackCreatePayload(
            isrc=isrc,
            track_title="History Replay Track",
            artist_name="History Replay Artist",
            additional_artists=[],
            album_title=None,
            release_date="2026-08-08",
            track_length_sec=180,
            iswc=None,
            upc=None,
            genre="Pop",
        )
    )


def _post_canary_transaction(conn, command_key: str, amount_minor: int) -> None:
    LedgerPostingService(conn).post_transaction(
        command_key=command_key,
        transaction_type="adjustment",
        entries=(
            LedgerEntryDraft("1000", "EUR", debit_minor=amount_minor),
            LedgerEntryDraft("9000", "EUR", credit_minor=amount_minor),
        ),
    )


def _table_rows(conn, table_name: str) -> list[tuple]:
    return conn.execute(f'SELECT * FROM "{table_name}" ORDER BY rowid').fetchall()


def test_track_delete_undo_redo_preserves_all_immutable_canaries_and_later_ledger_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    tracks = TrackService(conn)

    party_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Immutable Canary BV",
            display_name="Immutable Canary",
            party_type="organization",
        )
    )
    _post_canary_transaction(conn, "history-canary-before", 100)
    conn.execute(
        """
        INSERT INTO Invoices (
            party_id, invoice_type, document_status, invoice_number, currency
        ) VALUES (?, 'sales', 'issued', 'INV-CANARY', 'EUR')
        """,
        (party_id,),
    )
    calculation_id = int(
        conn.execute(
            """
            INSERT INTO RoyaltyCalculations (party_id, status, currency)
            VALUES (?, 'calculated', 'EUR')
            RETURNING id
            """,
            (party_id,),
        ).fetchone()[0]
    )
    conn.execute(
        """
        INSERT INTO RoyaltyStatements (
            calculation_id, party_id, issue_date, currency, total_minor, idempotency_key
        ) VALUES (?, ?, '2026-08-08', 'EUR', 100, 'royalty-canary')
        """,
        (calculation_id, party_id),
    )
    conn.execute("""
        INSERT INTO AuditLog (action, entity, ref_id, details)
        VALUES ('TEST', 'History', 'immutable-canary', 'must survive replay')
        """)
    conn.commit()

    track_id = _create_track(tracks)
    persistent_track_id = _create_track(tracks, isrc="NL-ABC-26-00420")
    run_snapshot_history_action(
        history_manager=history,
        action_label="Delete history replay track",
        action_type="track.delete",
        entity_type="Track",
        entity_id=track_id,
        mutation=lambda: tracks.delete_track(track_id),
    )
    assert tracks.fetch_track_snapshot(track_id) is None

    # This transaction was not part of the delete action and must survive both replay directions.
    _post_canary_transaction(conn, "history-canary-after", 250)
    later_track_id = _create_track(tracks, isrc="NL-ABC-26-00423")
    immutable_tables = (
        "AccountingTransactions",
        "AccountingEntries",
        "FinancialCommandLog",
        "Invoices",
        "RoyaltyStatements",
        "AuditLog",
        "CodeRegistryEntries",
    )
    expected_rows = {table: _table_rows(conn, table) for table in immutable_tables}

    history.undo()
    assert tracks.fetch_track_snapshot(track_id) is not None
    assert tracks.fetch_track_snapshot(persistent_track_id) is not None
    assert tracks.fetch_track_snapshot(later_track_id) is not None
    assert {table: _table_rows(conn, table) for table in immutable_tables} == expected_rows

    history.redo()
    assert tracks.fetch_track_snapshot(track_id) is None
    assert tracks.fetch_track_snapshot(persistent_track_id) is not None
    assert tracks.fetch_track_snapshot(later_track_id) is not None
    assert {table: _table_rows(conn, table) for table in immutable_tables} == expected_rows

    settings.clear()
    conn.close()


def test_snapshot_replay_progress_tracks_completed_phases_and_expected_visible_entry(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    tracks = TrackService(conn)
    track_id = _create_track(tracks, isrc="NL-ABC-26-00444")

    run_snapshot_history_action(
        history_manager=history,
        action_label="Delete progress canary",
        action_type="track.delete",
        entity_type="Track",
        entity_id=track_id,
        mutation=lambda: tracks.delete_track(track_id),
    )
    visible_entry = history.get_current_visible_entry()
    assert visible_entry is not None

    undo_progress: list[tuple[int, int, str]] = []
    history.undo(
        expected_visible_entry_id=visible_entry.entry_id,
        progress_callback=lambda value, maximum, message: undo_progress.append(
            (value, maximum, message)
        ),
    )

    assert tracks.fetch_track_snapshot(track_id) is not None
    assert undo_progress[0][0] == 0
    assert undo_progress[-1][0] == undo_progress[-1][1]
    assert [value for value, _maximum, _message in undo_progress] == sorted(
        value for value, _maximum, _message in undo_progress
    )
    assert set(value for value, _maximum, _message in undo_progress) == set(
        range(undo_progress[-1][1] + 1)
    )
    undo_messages = [message for _value, _maximum, message in undo_progress]
    assert any("snapshot pair" in message for message in undo_messages)
    assert any("database rows" in message for message in undo_messages)
    assert any("managed files" in message for message in undo_messages)
    assert undo_messages[-1] == "Undo replay completed."

    with pytest.raises(HistoryRecoveryError, match="Redo action changed"):
        history.redo(expected_visible_entry_id=visible_entry.entry_id + 1)
    assert tracks.fetch_track_snapshot(track_id) is not None
    assert history.can_redo()

    redo_progress: list[tuple[int, int, str]] = []
    history.redo(
        expected_visible_entry_id=visible_entry.entry_id,
        progress_callback=lambda value, maximum, message: redo_progress.append(
            (value, maximum, message)
        ),
    )
    assert tracks.fetch_track_snapshot(track_id) is None
    assert redo_progress[-1][0] == redo_progress[-1][1]
    assert redo_progress[-1][2] == "Redo replay completed."

    settings.clear()
    conn.close()


def test_row_scoped_replay_ignores_unrelated_posted_royalty_line_in_changed_table(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    tracks = TrackService(conn)
    mutable_track_id = _create_track(tracks, isrc="NL-ABC-26-00424")
    posted_track_id = _create_track(tracks, isrc="NL-ABC-26-00425")
    party_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Royalty Canary BV",
            display_name="Royalty Canary",
            party_type="organization",
        )
    )
    mutable_calculation_id = int(
        conn.execute(
            """
            INSERT INTO RoyaltyCalculations (party_id, status, currency)
            VALUES (?, 'calculated', 'EUR') RETURNING id
            """,
            (party_id,),
        ).fetchone()[0]
    )
    posted_calculation_id = int(
        conn.execute(
            """
            INSERT INTO RoyaltyCalculations (party_id, status, currency)
            VALUES (?, 'calculated', 'EUR') RETURNING id
            """,
            (party_id,),
        ).fetchone()[0]
    )
    mutable_line_id = int(
        conn.execute(
            """
            INSERT INTO RoyaltyCalculationLines (
                calculation_id, description, net_payable_minor, track_id
            ) VALUES (?, 'Mutable line', 100, ?) RETURNING id
            """,
            (mutable_calculation_id, mutable_track_id),
        ).fetchone()[0]
    )
    posted_line_id = int(
        conn.execute(
            """
            INSERT INTO RoyaltyCalculationLines (
                calculation_id, description, net_payable_minor, track_id
            ) VALUES (?, 'Posted line', 200, ?) RETURNING id
            """,
            (posted_calculation_id, posted_track_id),
        ).fetchone()[0]
    )
    conn.execute(
        "UPDATE RoyaltyCalculations SET status='posted' WHERE id=?",
        (posted_calculation_id,),
    )
    conn.commit()

    run_snapshot_history_action(
        history_manager=history,
        action_label="Delete royalty-linked track",
        action_type="track.delete",
        entity_type="Track",
        entity_id=mutable_track_id,
        mutation=lambda: tracks.delete_track(mutable_track_id),
    )
    assert conn.execute(
        "SELECT track_id FROM RoyaltyCalculationLines WHERE id=?", (mutable_line_id,)
    ).fetchone() == (None,)

    history.undo()
    assert tracks.fetch_track_snapshot(mutable_track_id) is not None
    assert conn.execute(
        "SELECT track_id FROM RoyaltyCalculationLines WHERE id=?", (mutable_line_id,)
    ).fetchone() == (mutable_track_id,)
    assert conn.execute(
        "SELECT track_id FROM RoyaltyCalculationLines WHERE id=?", (posted_line_id,)
    ).fetchone() == (posted_track_id,)

    history.redo()
    assert tracks.fetch_track_snapshot(mutable_track_id) is None
    assert conn.execute(
        "SELECT track_id FROM RoyaltyCalculationLines WHERE id=?", (mutable_line_id,)
    ).fetchone() == (None,)
    assert conn.execute(
        "SELECT track_id FROM RoyaltyCalculationLines WHERE id=?", (posted_line_id,)
    ).fetchone() == (posted_track_id,)

    settings.clear()
    conn.close()


def test_snapshot_replay_fails_safely_when_deleted_primary_key_was_reused(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    tracks = TrackService(conn)
    deleted_track_id = _create_track(tracks, isrc="NL-ABC-26-00429")
    run_snapshot_history_action(
        history_manager=history,
        action_label="Delete primary-key reuse canary",
        action_type="track.delete",
        entity_type="Track",
        entity_id=deleted_track_id,
        mutation=lambda: tracks.delete_track(deleted_track_id),
    )
    replacement_track_id = _create_track(tracks, isrc="NL-ABC-26-00430")
    assert replacement_track_id == deleted_track_id

    with pytest.raises(SnapshotConnectionError, match="row changed after"):
        history.undo()

    replacement = tracks.fetch_track_snapshot(replacement_track_id)
    assert replacement is not None
    assert replacement.isrc == "NL-ABC-26-00430"
    assert history.can_undo()

    settings.clear()
    conn.close()


def test_snapshot_replay_never_restores_accounting_maintenance_bypass(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    tracks = TrackService(conn)
    track_id = _create_track(tracks, isrc="NL-ABC-26-00426")
    conn.execute(
        "INSERT INTO AccountingMaintenanceBypass(scope, reason) VALUES (?, ?)",
        ("invoice_cleanup", "security regression canary"),
    )
    conn.commit()

    def delete_track_and_remove_bypass() -> None:
        tracks.delete_track(track_id)
        with conn:
            conn.execute("DELETE FROM AccountingMaintenanceBypass WHERE scope='invoice_cleanup'")

    run_snapshot_history_action(
        history_manager=history,
        action_label="Delete track without replaying maintenance capability",
        action_type="track.delete",
        entity_type="Track",
        entity_id=track_id,
        mutation=delete_track_and_remove_bypass,
    )

    history.undo()
    assert tracks.fetch_track_snapshot(track_id) is not None
    assert conn.execute("SELECT COUNT(*) FROM AccountingMaintenanceBypass").fetchone() == (0,)

    settings.clear()
    conn.close()


def test_manual_restore_preserves_issued_invoice_while_restoring_catalog_state(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    tracks = TrackService(conn)
    party_id = PartyService(conn).create_party(
        PartyPayload(
            legal_name="Manual Restore Canary BV",
            display_name="Manual Restore Canary",
            party_type="organization",
        )
    )
    snapshot = history.create_manual_snapshot("Before issued invoice and track")
    conn.execute(
        """
        INSERT INTO Invoices (
            party_id, invoice_type, document_status, invoice_number, currency
        ) VALUES (?, 'sales', 'issued', 'INV-MANUAL-CANARY', 'EUR')
        """,
        (party_id,),
    )
    conn.commit()
    track_id = _create_track(tracks, isrc="NL-ABC-26-00428")

    history.restore_snapshot_as_action(snapshot.snapshot_id)
    assert tracks.fetch_track_snapshot(track_id) is None
    assert conn.execute(
        "SELECT invoice_number FROM Invoices WHERE invoice_number='INV-MANUAL-CANARY'"
    ).fetchone() == ("INV-MANUAL-CANARY",)

    history.undo()
    assert tracks.fetch_track_snapshot(track_id) is not None
    assert conn.execute(
        "SELECT invoice_number FROM Invoices WHERE invoice_number='INV-MANUAL-CANARY'"
    ).fetchone() == ("INV-MANUAL-CANARY",)

    history.redo()
    assert tracks.fetch_track_snapshot(track_id) is None
    assert conn.execute(
        "SELECT invoice_number FROM Invoices WHERE invoice_number='INV-MANUAL-CANARY'"
    ).fetchone() == ("INV-MANUAL-CANARY",)

    settings.clear()
    conn.close()


def test_snapshot_replay_rejects_new_foreign_key_violations_and_rolls_back(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)

    def insert_orphan() -> None:
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("""
            INSERT INTO TrackArtists(track_id, party_id, role)
            VALUES (999991, 999992, 'main')
            """)
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")

    run_snapshot_history_action(
        history_manager=history,
        action_label="Insert invalid relationship canary",
        action_type="test.invalid_relationship",
        mutation=insert_orphan,
    )
    history.undo()
    assert conn.execute("SELECT COUNT(*) FROM TrackArtists").fetchone() == (0,)

    with pytest.raises(HistoryRecoveryError, match="foreign-key violations"):
        history.redo()
    assert conn.execute("SELECT COUNT(*) FROM TrackArtists").fetchone() == (0,)

    settings.clear()
    conn.close()


def test_registry_snapshot_replay_keeps_entries_and_sequence_monotonic(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    registry = CodeRegistryService(conn)
    category = registry.fetch_category_by_system_key(BUILTIN_CATEGORY_CATALOG_NUMBER)
    assert category is not None
    registry.update_category(category.id, prefix="HIS")

    generated = run_snapshot_history_action(
        history_manager=history,
        action_label="Generate registry history canary",
        action_type="registry.generate",
        mutation=lambda: registry.generate_next_code(
            category_id=category.id,
            created_via="test.history.monotonic",
        ).entry,
    )
    sequence_before_replay = conn.execute(
        """
        SELECT last_sequence_number FROM CodeRegistrySequences
        WHERE category_id=? AND sequence_year=?
        """,
        (category.id, generated.sequence_year),
    ).fetchone()

    history.undo()
    assert registry.fetch_entry(generated.id) is not None
    assert (
        conn.execute(
            """
        SELECT last_sequence_number FROM CodeRegistrySequences
        WHERE category_id=? AND sequence_year=?
        """,
            (category.id, generated.sequence_year),
        ).fetchone()
        == sequence_before_replay
    )

    history.redo()
    next_entry = registry.generate_next_code(
        category_id=category.id,
        created_via="test.history.monotonic.next",
    ).entry
    assert next_entry.sequence_number is not None
    assert generated.sequence_number is not None
    assert next_entry.sequence_number > generated.sequence_number

    settings.clear()
    conn.close()


def test_scoped_managed_restore_rejects_source_and_destination_symlink_escapes(
    tmp_path: Path,
) -> None:
    managed_root = tmp_path / "managed"
    live_directory = managed_root / "asset_registry"
    live_directory.mkdir(parents=True)
    outside_destination = tmp_path / "outside-destination"
    outside_destination.mkdir()
    (live_directory / "nested").symlink_to(outside_destination, target_is_directory=True)

    snapshot_root = tmp_path / "snapshot-assets" / "asset_registry"
    (snapshot_root / "nested").mkdir(parents=True)
    (snapshot_root / "nested" / "record.json").write_text("snapshot", encoding="utf-8")
    manifest = {
        "managed_directories": {
            "asset_registry": {
                "exists": True,
                "snapshot_path": str(snapshot_root),
                "file_inventory": capture_managed_file_inventory(snapshot_root),
            }
        }
    }
    changed_files = (("asset_registry", ("nested/record.json",)),)

    with pytest.raises(SnapshotConnectionError, match="symbolic link"):
        restore_managed_files(managed_root, manifest, changed_files)
    assert not (outside_destination / "record.json").exists()

    (live_directory / "nested").unlink()
    (live_directory / "nested").mkdir()
    outside_source = tmp_path / "outside-source"
    outside_source.mkdir()
    (outside_source / "record.json").write_text("outside", encoding="utf-8")
    (snapshot_root / "nested" / "record.json").unlink()
    (snapshot_root / "nested").rmdir()
    (snapshot_root / "nested").symlink_to(outside_source, target_is_directory=True)

    with pytest.raises(SnapshotConnectionError, match="symbolic link"):
        restore_managed_files(managed_root, manifest, changed_files)
    assert not (live_directory / "nested" / "record.json").exists()


def test_restore_aborts_before_mutation_when_managed_rollback_capture_fails(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    tracks = TrackService(conn)
    snapshot = history.create_manual_snapshot("Before rollback capture failure")
    track_id = _create_track(tracks, isrc="NL-ABC-26-00427")

    with patch.object(
        history,
        "_capture_managed_state",
        side_effect=OSError("managed rollback capture failed"),
    ):
        with pytest.raises(OSError, match="managed rollback capture failed"):
            history.restore_snapshot(snapshot.snapshot_id)

    assert tracks.fetch_track_snapshot(track_id) is not None
    settings.clear()
    conn.close()


def test_snapshot_replay_preserves_unrelated_later_settings_and_managed_files(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)

    asset_root = tmp_path / "data" / "asset_registry"
    asset_root.mkdir(parents=True)
    action_file = asset_root / "action-record.json"
    action_file.write_text('{"state":"before"}', encoding="utf-8")
    settings.setValue("history/action-setting", "before")
    settings.sync()

    def mutate_action_state() -> None:
        action_file.unlink()
        settings.setValue("history/action-setting", "after")
        settings.sync()

    run_snapshot_history_action(
        history_manager=history,
        action_label="Delete asset registry record",
        action_type="asset.delete",
        mutation=mutate_action_state,
    )

    later_file = asset_root / "later-unrelated.json"
    later_file.write_text('{"state":"later"}', encoding="utf-8")
    settings.setValue("history/later-unrelated-setting", "later")
    settings.sync()

    history.undo()
    assert action_file.read_text(encoding="utf-8") == '{"state":"before"}'
    assert settings.value("history/action-setting") == "before"
    assert later_file.read_text(encoding="utf-8") == '{"state":"later"}'
    assert settings.value("history/later-unrelated-setting") == "later"

    history.redo()
    assert not action_file.exists()
    assert settings.value("history/action-setting") == "after"
    assert later_file.read_text(encoding="utf-8") == '{"state":"later"}'
    assert settings.value("history/later-unrelated-setting") == "later"

    settings.clear()
    conn.close()


def test_managed_snapshot_inventory_fails_closed_for_missing_and_corrupt_files(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)

    asset_root = tmp_path / "data" / "asset_registry"
    asset_root.mkdir(parents=True)
    live_file = asset_root / "integrity.json"
    live_file.write_text("before", encoding="utf-8")
    run_snapshot_history_action(
        history_manager=history,
        action_label="Change managed integrity canary",
        action_type="test.managed_integrity",
        mutation=lambda: live_file.write_text("after", encoding="utf-8"),
    )

    before = next(
        snapshot
        for snapshot in history.list_snapshots(limit=10)
        if snapshot.kind == "pre_test_managed_integrity"
    )
    before_state = before.manifest["managed_directories"]["asset_registry"]
    signature = before_state["file_inventory"]["integrity.json"]
    assert signature["size_bytes"] == len(b"before")
    assert len(signature["sha256"]) == 64
    stored_file = Path(before_state["snapshot_path"]) / "integrity.json"

    stored_file.unlink()
    failed_progress: list[tuple[int, int, str]] = []
    with pytest.raises(SnapshotConnectionError, match="artifact|integrity"):
        history.undo(
            progress_callback=lambda value, maximum, message: failed_progress.append(
                (value, maximum, message)
            )
        )
    assert live_file.read_text(encoding="utf-8") == "after"
    assert history.can_undo()
    assert failed_progress
    assert failed_progress[-1][0] < failed_progress[-1][1]
    assert all(message != "Undo replay completed." for _value, _maximum, message in failed_progress)

    stored_file.write_text("corrupt", encoding="utf-8")
    with pytest.raises(SnapshotConnectionError, match="integrity"):
        history.undo()
    assert live_file.read_text(encoding="utf-8") == "after"
    assert history.can_undo()

    settings.clear()
    conn.close()


def test_snapshot_replay_rejects_same_setting_and_managed_path_conflicts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)

    asset_root = tmp_path / "data" / "asset_registry"
    asset_root.mkdir(parents=True)
    live_file = asset_root / "conflict.json"
    live_file.write_text("before", encoding="utf-8")
    settings.setValue("history/conflict-setting", "before")
    settings.sync()

    def mutate_action_state() -> None:
        live_file.write_text("after", encoding="utf-8")
        settings.setValue("history/conflict-setting", "after")
        settings.sync()

    run_snapshot_history_action(
        history_manager=history,
        action_label="Change conflict canaries",
        action_type="test.external_conflict",
        mutation=mutate_action_state,
    )

    live_file.write_text("later-unrecorded", encoding="utf-8")
    with pytest.raises(SnapshotConnectionError, match="managed file changed"):
        history.undo()
    assert live_file.read_text(encoding="utf-8") == "later-unrecorded"
    assert settings.value("history/conflict-setting") == "after"

    live_file.write_text("after", encoding="utf-8")
    settings.setValue("history/conflict-setting", "later-unrecorded")
    settings.sync()
    with pytest.raises(SnapshotConnectionError, match="setting changed"):
        history.undo()
    assert live_file.read_text(encoding="utf-8") == "after"
    assert settings.value("history/conflict-setting") == "later-unrecorded"

    settings.setValue("history/conflict-setting", "after")
    settings.sync()
    history.undo()
    assert live_file.read_text(encoding="utf-8") == "before"
    assert settings.value("history/conflict-setting") == "before"

    live_file.write_text("later-before-redo", encoding="utf-8")
    with pytest.raises(SnapshotConnectionError, match="managed file changed"):
        history.redo()
    assert live_file.read_text(encoding="utf-8") == "later-before-redo"

    live_file.write_text("before", encoding="utf-8")
    settings.setValue("history/conflict-setting", "later-before-redo")
    settings.sync()
    with pytest.raises(SnapshotConnectionError, match="setting changed"):
        history.redo()

    settings.setValue("history/conflict-setting", "before")
    settings.sync()
    history.redo()
    assert live_file.read_text(encoding="utf-8") == "after"
    assert settings.value("history/conflict-setting") == "after"

    settings.clear()
    conn.close()


def test_snapshot_file_effect_conflict_aborts_before_replay(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)

    before = history.capture_snapshot(kind="pre_file_effect_conflict", label="Before")
    effect_path = tmp_path / "exports" / "effect.txt"
    effect_path.parent.mkdir(parents=True)
    effect_path.write_text("after", encoding="utf-8")
    after_state = history.capture_file_state(effect_path)
    after = history.capture_snapshot(kind="post_file_effect_conflict", label="After")
    history.record_snapshot_action(
        label="Create explicit file effect",
        action_type="test.file_effect_conflict",
        snapshot_before_id=before.snapshot_id,
        snapshot_after_id=after.snapshot_id,
        payload={
            "file_effects": [
                {
                    "target_path": str(effect_path),
                    "before_state": {
                        "target_path": str(effect_path),
                        "companion_suffixes": [],
                        "exists": False,
                        "files": [],
                    },
                    "after_state": after_state,
                }
            ]
        },
    )

    effect_path.write_text("later-unrecorded", encoding="utf-8")
    with pytest.raises(HistoryRecoveryError, match="action-owned file changed"):
        history.undo()
    assert effect_path.read_text(encoding="utf-8") == "later-unrecorded"
    assert history.can_undo()

    settings.clear()
    conn.close()


def test_snapshot_replay_restores_empty_managed_directory_existence(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    empty_directory = tmp_path / "data" / "asset_registry"
    assert not empty_directory.exists()

    run_snapshot_history_action(
        history_manager=history,
        action_label="Create empty managed directory",
        action_type="test.empty_managed_directory",
        mutation=lambda: empty_directory.mkdir(parents=True),
    )
    assert empty_directory.is_dir()

    history.undo()
    assert not empty_directory.exists()
    history.redo()
    assert empty_directory.is_dir()
    assert not any(empty_directory.iterdir())

    settings.clear()
    conn.close()


def test_legacy_managed_file_difference_fails_without_recorded_inventory(
    tmp_path: Path,
) -> None:
    before_root = tmp_path / "before"
    after_root = tmp_path / "after"
    before_root.mkdir()
    after_root.mkdir()
    (before_root / "record.json").write_text("before", encoding="utf-8")
    (after_root / "record.json").write_text("after", encoding="utf-8")
    before = {
        "managed_directories": {
            "asset_registry": {"exists": True, "snapshot_path": str(before_root)}
        }
    }
    after = {
        "managed_directories": {
            "asset_registry": {"exists": True, "snapshot_path": str(after_root)}
        }
    }

    with pytest.raises(SnapshotConnectionError, match="legacy managed-file history"):
        changed_managed_files(before, after)


def test_snapshot_database_digest_rejects_tampered_row_before_undo(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    tracks = TrackService(conn)
    track_id = _create_track(tracks, isrc="NL-ABC-26-00431")

    run_snapshot_history_action(
        history_manager=history,
        action_label="Delete digest canary",
        action_type="track.delete",
        entity_type="Track",
        entity_id=track_id,
        mutation=lambda: tracks.delete_track(track_id),
    )
    before = next(
        snapshot
        for snapshot in history.list_snapshots(limit=10)
        if snapshot.kind == "pre_track_delete"
    )
    tamper_conn = sqlite3.connect(before.db_snapshot_path)
    try:
        tamper_conn.execute(
            "UPDATE Tracks SET track_title='TAMPERED' WHERE id=?",
            (track_id,),
        )
        tamper_conn.commit()
    finally:
        tamper_conn.close()

    with pytest.raises(HistoryRecoveryError, match="logical integrity"):
        history.undo()
    assert tracks.fetch_track_snapshot(track_id) is None
    assert history.can_undo()

    settings.clear()
    conn.close()


def test_full_restore_rejects_managed_manifest_path_escape_before_mutation(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    tracks = TrackService(conn)
    snapshot = history.create_manual_snapshot("Before malicious manifest")
    track_id = _create_track(tracks, isrc="NL-ABC-26-00432")
    victim = tmp_path / "victim"
    victim.mkdir()
    marker = victim / "keep.txt"
    marker.write_text("unrelated", encoding="utf-8")

    malicious_manifest = dict(snapshot.manifest)
    malicious_manifest["managed_directories"] = {
        "../victim": {
            "exists": False,
            "snapshot_path": None,
            "file_inventory": {},
        }
    }
    with conn:
        conn.execute(
            "UPDATE HistorySnapshots SET manifest_json=? WHERE id=?",
            (json.dumps(malicious_manifest), snapshot.snapshot_id),
        )

    with pytest.raises(SnapshotConnectionError, match="unsupported directory"):
        history.restore_snapshot(snapshot.snapshot_id)
    assert marker.read_text(encoding="utf-8") == "unrelated"
    assert tracks.fetch_track_snapshot(track_id) is not None

    settings.clear()
    conn.close()


def test_snapshot_replay_rejects_missing_recorded_table_without_advancing_head(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    with conn:
        conn.execute("CREATE TABLE DriftRows(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO DriftRows(id, value) VALUES (1, 'before')")

    run_snapshot_history_action(
        history_manager=history,
        action_label="Delete schema drift canary",
        action_type="test.schema_drift",
        mutation=lambda: conn.execute("DELETE FROM DriftRows WHERE id=1"),
    )
    with conn:
        conn.execute("DROP TABLE DriftRows")

    with pytest.raises(SnapshotConnectionError, match="live schema"):
        history.undo()
    assert history.can_undo()
    assert (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='DriftRows'"
        ).fetchone()
        is None
    )

    settings.clear()
    conn.close()


def test_managed_root_symlink_is_rejected_before_capture_or_replay(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)

    managed_root = tmp_path / "data"
    action_root = managed_root / "asset_registry"
    action_root.mkdir(parents=True)
    action_file = action_root / "action.json"
    action_file.write_text("before", encoding="utf-8")
    run_snapshot_history_action(
        history_manager=history,
        action_label="Change managed-root symlink canary",
        action_type="test.managed_root_symlink",
        mutation=lambda: action_file.write_text("after", encoding="utf-8"),
    )

    retained_root = tmp_path / "retained-data"
    managed_root.rename(retained_root)
    outside_root = tmp_path / "outside-data"
    outside_file = outside_root / "asset_registry" / "action.json"
    outside_file.parent.mkdir(parents=True)
    outside_file.write_text("after", encoding="utf-8")
    managed_root.symlink_to(outside_root, target_is_directory=True)

    with pytest.raises(SnapshotConnectionError, match="symbolic link"):
        history.capture_snapshot(kind="symlink_capture", label="Unsafe capture")
    with pytest.raises(SnapshotConnectionError, match="symbolic link"):
        history.undo()

    assert outside_file.read_text(encoding="utf-8") == "after"
    assert history.can_undo()
    settings.clear()
    conn.close()


def test_managed_directory_redo_preserves_file_created_after_action(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)

    managed_directory = tmp_path / "data" / "asset_registry"
    action_file = managed_directory / "action.json"

    def create_action_file() -> None:
        managed_directory.mkdir(parents=True)
        action_file.write_text("action", encoding="utf-8")

    run_snapshot_history_action(
        history_manager=history,
        action_label="Create first managed file",
        action_type="test.managed_directory_create",
        mutation=create_action_file,
    )
    later_file = managed_directory / "later.json"
    later_file.write_text("later", encoding="utf-8")

    history.undo()
    assert not action_file.exists()
    assert later_file.read_text(encoding="utf-8") == "later"

    history.redo()
    assert action_file.read_text(encoding="utf-8") == "action"
    assert later_file.read_text(encoding="utf-8") == "later"

    history.undo()
    assert not action_file.exists()
    assert later_file.read_text(encoding="utf-8") == "later"
    settings.clear()
    conn.close()


def test_snapshot_settings_scope_is_type_sensitive_and_retryable(tmp_path: Path) -> None:
    serialized_bool = {"kind": "json", "value": True}
    serialized_int = {"kind": "json", "value": 1}
    serialized_float = {"kind": "json", "value": 1.0}
    assert changed_setting_keys({"flag": serialized_bool}, {"flag": serialized_int}) == {"flag"}
    assert changed_setting_keys({"flag": serialized_int}, {"flag": serialized_float}) == {"flag"}
    with pytest.raises(SnapshotConnectionError, match="setting changed"):
        validate_setting_values_match(
            {"flag": serialized_bool},
            {"flag": serialized_int},
            {"flag"},
        )

    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    settings.setValue("history/typed-setting", 2)
    settings.sync()

    def set_action_value() -> None:
        settings.setValue("history/typed-setting", 1)
        settings.sync()

    run_snapshot_history_action(
        history_manager=history,
        action_label="Change typed setting",
        action_type="test.typed_setting",
        mutation=set_action_value,
    )
    settings.setValue("history/typed-setting", True)
    settings.sync()
    with pytest.raises(SnapshotConnectionError, match="setting changed"):
        history.undo()
    assert history.can_undo()

    settings.setValue("history/typed-setting", 1)
    settings.sync()
    history.undo()
    assert settings.value("history/typed-setting") == 2
    assert type(settings.value("history/typed-setting")) is int
    history.redo()
    assert settings.value("history/typed-setting") == 1
    assert type(settings.value("history/typed-setting")) is int
    settings.clear()
    conn.close()


def test_case_only_managed_filename_change_undoes_and_redoes_on_macos(
    tmp_path: Path,
) -> None:
    managed_directory = tmp_path / "data" / "track_media"
    managed_directory.mkdir(parents=True)
    upper_path = managed_directory / "Track.WAV"
    lower_path = managed_directory / "track.wav"
    upper_path.write_bytes(b"case-sensitive-history")
    if not lower_path.exists():
        pytest.skip("Case-only managed-path replay requires a case-insensitive filesystem")

    db_path = tmp_path / "catalog.db"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _initialize_schema(conn)
    history = _history_manager(conn, settings, tmp_path, db_path)
    run_snapshot_history_action(
        history_manager=history,
        action_label="Rename managed file casing",
        action_type="test.managed_case_rename",
        mutation=lambda: upper_path.rename(lower_path),
    )

    history.undo()
    assert [path.name for path in managed_directory.iterdir()] == ["Track.WAV"]
    assert upper_path.read_bytes() == b"case-sensitive-history"
    history.redo()
    assert [path.name for path in managed_directory.iterdir()] == ["track.wav"]
    assert lower_path.read_bytes() == b"case-sensitive-history"
    history.undo()
    assert [path.name for path in managed_directory.iterdir()] == ["Track.WAV"]

    expected_root = tmp_path / "expected" / "track_media"
    expected_root.mkdir(parents=True)
    (expected_root / "Only.WAV").write_bytes(b"singleton")
    expected_manifest = {
        "managed_directories": {
            "track_media": {
                "exists": True,
                "snapshot_path": str(expected_root),
                "file_inventory": capture_managed_file_inventory(expected_root),
            }
        }
    }
    live_root = tmp_path / "live-singleton"
    live_directory = live_root / "track_media"
    live_directory.mkdir(parents=True)
    (live_directory / "only.wav").write_bytes(b"singleton")
    with pytest.raises(SnapshotConnectionError, match="managed file changed"):
        validate_managed_files_match(
            live_root,
            expected_manifest,
            (("track_media", ("Only.WAV",)),),
        )

    expected_absent_root = tmp_path / "expected-absent" / "track_media"
    expected_absent_root.mkdir(parents=True)
    expected_absent_manifest = {
        "managed_directories": {
            "track_media": {
                "exists": True,
                "snapshot_path": str(expected_absent_root),
                "file_inventory": {},
            }
        }
    }
    with pytest.raises(SnapshotConnectionError, match="managed file changed"):
        validate_managed_files_match(
            live_root,
            expected_absent_manifest,
            (("track_media", ("Only.WAV",)),),
        )

    settings.clear()
    conn.close()


def test_sqlcipher_history_snapshots_stay_encrypted_and_support_undo_redo(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sqlcipher3")
    db_path = tmp_path / "encrypted-catalog.db"
    settings = QSettings(str(tmp_path / "encrypted-settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    passwords = DatabaseSessionPasswordManager()
    passwords.set_password(db_path, "valid-history-secret")
    connection_factory = SQLiteConnectionFactory(password_provider=passwords)
    conn = connection_factory.open(db_path)
    _initialize_schema(conn)
    history = _history_manager(
        conn,
        settings,
        tmp_path,
        db_path,
        connection_factory=connection_factory,
    )
    tracks = TrackService(conn)
    track_id = _create_track(tracks, isrc="NL-ABC-26-00422")

    run_snapshot_history_action(
        history_manager=history,
        action_label="Delete encrypted history track",
        action_type="track.delete",
        entity_type="Track",
        entity_id=track_id,
        mutation=lambda: tracks.delete_track(track_id),
    )

    snapshots = history.list_snapshots(limit=10)
    assert len(snapshots) == 2
    for snapshot in snapshots:
        snapshot_path = Path(snapshot.db_snapshot_path)
        assert is_probably_encrypted_database(snapshot_path)
        with snapshot_path.open("rb") as handle:
            assert handle.read(len(SQLITE_HEADER)) != SQLITE_HEADER

    history.undo()
    assert tracks.fetch_track_snapshot(track_id) is not None
    history.redo()
    assert tracks.fetch_track_snapshot(track_id) is None

    settings.clear()
    conn.close()

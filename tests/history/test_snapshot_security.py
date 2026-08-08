from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSettings

from isrc_manager.history import HistoryManager, SessionHistoryManager
from isrc_manager.history.snapshot_security import (
    HistorySnapshotPasswordError,
    HistorySnapshotPasswordService,
    change_profile_password_with_history,
    referenced_profile_history_databases,
)
from isrc_manager.services.database_security import (
    DatabaseSecurityError,
    DatabaseSessionPasswordManager,
    InvalidDatabasePasswordError,
    SQLCipherDatabaseService,
)
from isrc_manager.services.db_access import SQLiteConnectionFactory
from isrc_manager.services.schema import DatabaseSchemaService
from isrc_manager.services.tracks import TrackCreatePayload, TrackService
from isrc_manager.tasks.history_helpers import run_snapshot_history_action

_OLD_PASSWORD = "history-old-secret"
_NEW_PASSWORD = "history-new-secret"


class _ProfileHistory:
    def __init__(self, snapshots=(), entries=()):
        self.snapshots = list(snapshots)
        self.entries = list(entries)

    def list_snapshots(self, limit=250):
        return self.snapshots[:limit]

    def list_entries(self, limit=250, *, include_hidden=False):
        del include_hidden
        return self.entries[:limit]


class _SessionHistory:
    def __init__(self, references=()):
        self.references = list(references)

    def snapshot_references(self):
        return list(self.references)


class _SessionReplayApp:
    def __init__(self, current_profile: Path) -> None:
        self.current_db_path = str(current_profile)

    def _session_history_delete_profile(self, path: str) -> None:
        Path(path).unlink(missing_ok=True)

    def _session_history_open_profile(self, path: str) -> None:
        self.current_db_path = str(path)

    def _session_history_reload_profiles(self, select_path: str | None = None) -> None:
        if select_path:
            self.current_db_path = str(select_path)


def _create_encrypted_database(path: Path, password: str, value: str) -> None:
    service = SQLCipherDatabaseService()
    conn = service.open(path, password)
    try:
        conn.execute("CREATE TABLE canary(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO canary(id, value) VALUES (1, ?)", (value,))
        conn.commit()
    finally:
        conn.close()


def _read_encrypted_canary(path: Path, password: str) -> str:
    conn = SQLCipherDatabaseService().open(path, password)
    try:
        return str(conn.execute("SELECT value FROM canary").fetchone()[0])
    finally:
        conn.close()


def test_referenced_history_databases_are_exact_and_profile_scoped(tmp_path: Path) -> None:
    history_root = tmp_path / "history"
    profile_path = tmp_path / "profiles" / "catalog.db"
    registered = history_root / "snapshots" / "catalog" / "registered.db"
    archived = history_root / "snapshot_archives" / "catalog" / "archived.db"
    session = history_root / "session_profile_snapshots" / "session.db"
    unrelated = history_root / "snapshots" / "other" / "unrelated.db"
    for path in (registered, archived, session, unrelated):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"database placeholder")

    profile_history = _ProfileHistory(
        snapshots=[SimpleNamespace(db_snapshot_path=str(registered))],
        entries=[
            SimpleNamespace(
                payload={},
                inverse_payload={},
                redo_payload={"archived_snapshot": {"db_snapshot_path": str(archived)}},
            )
        ],
    )
    session_history = _SessionHistory(
        references=[
            {"profile_path": str(profile_path), "snapshot_path": str(session)},
            {
                "profile_path": str(tmp_path / "profiles" / "other.db"),
                "snapshot_path": str(unrelated),
            },
        ]
    )

    discovered = referenced_profile_history_databases(
        history_root=history_root,
        profile_path=profile_path,
        history_manager=profile_history,
        session_history_manager=session_history,
    )
    assert set(discovered) == {archived, registered, session}


def test_history_reference_outside_fixed_snapshot_directories_is_rejected(
    tmp_path: Path,
) -> None:
    history_root = tmp_path / "history"
    history_root.mkdir()
    outside = tmp_path / "unrelated.db"
    outside.write_bytes(b"must not be touched")
    history = _ProfileHistory(snapshots=[SimpleNamespace(db_snapshot_path=str(outside))])

    with pytest.raises(HistorySnapshotPasswordError, match="outside this profile"):
        referenced_profile_history_databases(
            history_root=history_root,
            profile_path=tmp_path / "profiles" / "catalog.db",
            history_manager=history,
            session_history_manager=None,
        )
    assert outside.read_bytes() == b"must not be touched"


def test_symlinked_profile_snapshot_root_is_rejected(tmp_path: Path) -> None:
    history_root = tmp_path / "history"
    profile_path = tmp_path / "profiles" / "catalog.db"
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_snapshot = outside / "referenced.db"
    outside_snapshot.write_bytes(b"must not be touched")
    snapshot_parent = history_root / "snapshots"
    snapshot_parent.mkdir(parents=True)
    linked_root = snapshot_parent / profile_path.stem
    try:
        linked_root.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")
    history = _ProfileHistory(
        snapshots=[SimpleNamespace(db_snapshot_path=str(linked_root / outside_snapshot.name))]
    )

    with pytest.raises(HistorySnapshotPasswordError, match="symbolic links"):
        referenced_profile_history_databases(
            history_root=history_root,
            profile_path=profile_path,
            history_manager=history,
            session_history_manager=None,
        )
    assert outside_snapshot.read_bytes() == b"must not be touched"


def test_history_snapshot_password_service_rekeys_encrypted_and_skips_plaintext(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sqlcipher3")
    encrypted = tmp_path / "encrypted.db"
    plaintext = tmp_path / "legacy-plaintext.db"
    _create_encrypted_database(encrypted, _OLD_PASSWORD, "encrypted")
    plain_conn = sqlite3.connect(plaintext)
    plain_conn.execute("CREATE TABLE canary(value TEXT NOT NULL)")
    plain_conn.execute("INSERT INTO canary(value) VALUES ('plaintext')")
    plain_conn.commit()
    plain_conn.close()

    result = HistorySnapshotPasswordService(SQLCipherDatabaseService()).rekey(
        (encrypted, plaintext),
        current_password=_OLD_PASSWORD,
        new_password=_NEW_PASSWORD,
    )

    assert result.encrypted_artifacts_rekeyed == 1
    assert result.plaintext_artifacts_unchanged == 1
    assert _read_encrypted_canary(encrypted, _NEW_PASSWORD) == "encrypted"
    with pytest.raises(InvalidDatabasePasswordError):
        _read_encrypted_canary(encrypted, _OLD_PASSWORD)
    plain_conn = sqlite3.connect(plaintext)
    try:
        assert plain_conn.execute("SELECT value FROM canary").fetchone() == ("plaintext",)
    finally:
        plain_conn.close()


def test_history_snapshot_rekey_failure_restores_already_changed_artifacts(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sqlcipher3")
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    _create_encrypted_database(first, _OLD_PASSWORD, "first")
    _create_encrypted_database(second, _OLD_PASSWORD, "second")
    delegate = SQLCipherDatabaseService()

    class _FailSecond:
        def change_password(self, path, current_password, new_password):
            if Path(path) == second:
                raise RuntimeError("injected rekey failure")
            delegate.change_password(path, current_password, new_password)

    with pytest.raises(HistorySnapshotPasswordError) as exc_info:
        HistorySnapshotPasswordService(_FailSecond()).rekey(
            (first, second),
            current_password=_OLD_PASSWORD,
            new_password=_NEW_PASSWORD,
        )

    assert _OLD_PASSWORD not in str(exc_info.value)
    assert _NEW_PASSWORD not in str(exc_info.value)
    assert _read_encrypted_canary(first, _OLD_PASSWORD) == "first"
    assert _read_encrypted_canary(second, _OLD_PASSWORD) == "second"
    with pytest.raises(InvalidDatabasePasswordError):
        _read_encrypted_canary(first, _NEW_PASSWORD)


def test_live_profile_failure_rolls_history_artifacts_back_to_old_password(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sqlcipher3")
    history_root = tmp_path / "history"
    profile = tmp_path / "profiles" / "catalog.db"
    snapshot = history_root / "snapshots" / "catalog" / "before.db"
    _create_encrypted_database(profile, _OLD_PASSWORD, "live")
    _create_encrypted_database(snapshot, _OLD_PASSWORD, "snapshot")
    history = _ProfileHistory(snapshots=[SimpleNamespace(db_snapshot_path=str(snapshot))])
    delegate = SQLCipherDatabaseService()

    class _FailLive:
        def change_password(self, path, current_password, new_password):
            if Path(path) == profile:
                raise RuntimeError("injected live rekey failure")
            delegate.change_password(path, current_password, new_password)

    with pytest.raises(RuntimeError, match="live rekey failure"):
        change_profile_password_with_history(
            _FailLive(),
            profile,
            _OLD_PASSWORD,
            _NEW_PASSWORD,
            history_root=history_root,
            history_manager=history,
        )

    assert _read_encrypted_canary(profile, _OLD_PASSWORD) == "live"
    assert _read_encrypted_canary(snapshot, _OLD_PASSWORD) == "snapshot"


def test_profile_and_referenced_history_rotate_to_the_same_password(tmp_path: Path) -> None:
    pytest.importorskip("sqlcipher3")
    history_root = tmp_path / "history"
    profile = tmp_path / "profiles" / "catalog.db"
    snapshot = history_root / "snapshots" / "catalog" / "before.db"
    _create_encrypted_database(profile, _OLD_PASSWORD, "live")
    _create_encrypted_database(snapshot, _OLD_PASSWORD, "snapshot")
    history = _ProfileHistory(snapshots=[SimpleNamespace(db_snapshot_path=str(snapshot))])

    result = change_profile_password_with_history(
        SQLCipherDatabaseService(),
        profile,
        _OLD_PASSWORD,
        _NEW_PASSWORD,
        history_root=history_root,
        history_manager=history,
    )

    assert result.encrypted_artifacts_rekeyed == 1
    assert _read_encrypted_canary(profile, _NEW_PASSWORD) == "live"
    assert _read_encrypted_canary(snapshot, _NEW_PASSWORD) == "snapshot"
    for path in (profile, snapshot):
        with pytest.raises(InvalidDatabasePasswordError):
            _read_encrypted_canary(path, _OLD_PASSWORD)


def test_password_rotation_keeps_existing_encrypted_undo_and_redo_usable(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sqlcipher3")
    profile = tmp_path / "profiles" / "catalog.db"
    history_root = tmp_path / "history"
    passwords = DatabaseSessionPasswordManager()
    passwords.set_password(profile, _OLD_PASSWORD)
    connection_factory = SQLiteConnectionFactory(password_provider=passwords)
    conn = connection_factory.open(profile)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    try:
        schema = DatabaseSchemaService(conn, data_root=tmp_path / "data")
        schema.init_db()
        schema.migrate_schema()
        history = HistoryManager(
            conn,
            settings,
            profile,
            history_root,
            tmp_path / "data",
            tmp_path / "backups",
            connection_factory=connection_factory,
        )
        tracks = TrackService(conn, data_root=tmp_path / "data")
        track_id = tracks.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-00991",
                track_title="Password Rotation Undo",
                artist_name="History Security",
                additional_artists=[],
                album_title=None,
                release_date="2026-08-08",
                track_length_sec=181,
                iswc=None,
                upc=None,
                genre="Test",
            )
        )
        run_snapshot_history_action(
            history_manager=history,
            action_label="Delete encrypted password-rotation track",
            action_type="track.delete",
            entity_type="Track",
            entity_id=track_id,
            mutation=lambda: tracks.delete_track(track_id),
        )

        result = change_profile_password_with_history(
            SQLCipherDatabaseService(),
            profile,
            _OLD_PASSWORD,
            _NEW_PASSWORD,
            history_root=history_root,
            history_manager=history,
            live_connection=conn,
        )
        passwords.set_password(profile, _NEW_PASSWORD)

        assert result.encrypted_artifacts_rekeyed == 2
        history.undo()
        assert tracks.fetch_track_snapshot(track_id) is not None
        history.redo()
        assert tracks.fetch_track_snapshot(track_id) is None
    finally:
        settings.clear()
        conn.close()

    reopened = SQLCipherDatabaseService().open(profile, _NEW_PASSWORD)
    reopened.close()


def test_active_profile_verification_failure_restores_live_and_history_passwords(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sqlcipher3")
    history_root = tmp_path / "history"
    profile = tmp_path / "profiles" / "catalog.db"
    snapshot = history_root / "snapshots" / "catalog" / "before.db"
    _create_encrypted_database(profile, _OLD_PASSWORD, "live")
    _create_encrypted_database(snapshot, _OLD_PASSWORD, "snapshot")
    history = _ProfileHistory(snapshots=[SimpleNamespace(db_snapshot_path=str(snapshot))])

    class _FailFirstNewPasswordVerification(SQLCipherDatabaseService):
        failed = False

        def _verify_password(self, path, password):
            if Path(path) == profile and password == _NEW_PASSWORD and not self.failed:
                self.failed = True
                raise RuntimeError("injected verification failure")
            return super()._verify_password(path, password)

    service = _FailFirstNewPasswordVerification()
    live_connection = service.open(profile, _OLD_PASSWORD)
    try:
        with pytest.raises(DatabaseSecurityError, match="previous password remains"):
            change_profile_password_with_history(
                service,
                profile,
                _OLD_PASSWORD,
                _NEW_PASSWORD,
                history_root=history_root,
                history_manager=history,
                live_connection=live_connection,
            )

        assert live_connection.execute("SELECT value FROM canary").fetchone() == ("live",)
        assert _read_encrypted_canary(profile, _OLD_PASSWORD) == "live"
        assert _read_encrypted_canary(snapshot, _OLD_PASSWORD) == "snapshot"
        for path in (profile, snapshot):
            with pytest.raises(InvalidDatabasePasswordError):
                _read_encrypted_canary(path, _NEW_PASSWORD)
    finally:
        live_connection.close()


def test_session_profile_undo_survives_independent_sqlcipher_rekeys(tmp_path: Path) -> None:
    pytest.importorskip("sqlcipher3")
    history_root = tmp_path / "history"
    profile = tmp_path / "profiles" / "catalog.db"
    previous = tmp_path / "profiles" / "previous.db"
    _create_encrypted_database(profile, _OLD_PASSWORD, "created profile")
    passwords = DatabaseSessionPasswordManager()
    passwords.set_password(profile, _OLD_PASSWORD)
    connection_factory = SQLiteConnectionFactory(password_provider=passwords)
    session_history = SessionHistoryManager(
        history_root,
        connection_factory=connection_factory,
    )
    session_history.record_profile_create(
        created_path=str(profile),
        previous_path=str(previous),
    )
    snapshot = Path(session_history.snapshot_references()[0]["snapshot_path"])

    live_conn = SQLCipherDatabaseService().open(profile, _OLD_PASSWORD)
    try:
        live_conn.execute("CREATE TABLE HistoryEntries(entry_id INTEGER PRIMARY KEY)")
        live_conn.execute("INSERT INTO HistoryEntries(entry_id) VALUES (1)")
        live_conn.commit()
    finally:
        live_conn.close()

    result = change_profile_password_with_history(
        SQLCipherDatabaseService(),
        profile,
        _OLD_PASSWORD,
        _NEW_PASSWORD,
        history_root=history_root,
        session_history_manager=session_history,
    )
    passwords.set_password(profile, _NEW_PASSWORD)

    assert result.encrypted_artifacts_rekeyed == 1
    assert profile.read_bytes() != snapshot.read_bytes()
    app = _SessionReplayApp(profile)
    session_history.undo(app)
    assert not profile.exists()
    session_history.redo(app)
    assert _read_encrypted_canary(profile, _NEW_PASSWORD) == "created profile"
    session_history.undo(app)
    assert not profile.exists()


def test_session_inventory_refresh_failure_rolls_everything_back_and_remains_undoable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sqlcipher3")
    history_root = tmp_path / "history"
    profile = tmp_path / "profiles" / "catalog.db"
    previous = tmp_path / "profiles" / "previous.db"
    _create_encrypted_database(profile, _OLD_PASSWORD, "rollback profile")
    passwords = DatabaseSessionPasswordManager()
    passwords.set_password(profile, _OLD_PASSWORD)
    connection_factory = SQLiteConnectionFactory(password_provider=passwords)
    session_history = SessionHistoryManager(
        history_root,
        connection_factory=connection_factory,
    )
    session_history.record_profile_create(
        created_path=str(profile),
        previous_path=str(previous),
    )
    snapshot = Path(session_history.snapshot_references()[0]["snapshot_path"])
    original_refresh = session_history.refresh_snapshot_inventories
    refresh_calls = 0

    def fail_first_refresh(paths) -> int:
        nonlocal refresh_calls
        refresh_calls += 1
        if refresh_calls == 1:
            raise OSError("injected session inventory save failure")
        return original_refresh(paths)

    monkeypatch.setattr(
        session_history,
        "refresh_snapshot_inventories",
        fail_first_refresh,
    )

    with pytest.raises(HistorySnapshotPasswordError, match="previous password"):
        change_profile_password_with_history(
            SQLCipherDatabaseService(),
            profile,
            _OLD_PASSWORD,
            _NEW_PASSWORD,
            history_root=history_root,
            session_history_manager=session_history,
        )

    assert refresh_calls == 2
    assert _read_encrypted_canary(profile, _OLD_PASSWORD) == "rollback profile"
    assert _read_encrypted_canary(snapshot, _OLD_PASSWORD) == "rollback profile"
    for path in (profile, snapshot):
        with pytest.raises(InvalidDatabasePasswordError):
            _read_encrypted_canary(path, _NEW_PASSWORD)
    session_history.undo(_SessionReplayApp(profile))
    assert not profile.exists()

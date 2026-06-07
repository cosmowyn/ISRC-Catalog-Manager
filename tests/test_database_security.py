from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest

from isrc_manager.constants import SCHEMA_TARGET
from isrc_manager.services import DatabaseSchemaService
from isrc_manager.services.database_security import (
    SQLCIPHER_MEMORY_SECURITY_ENV,
    DatabaseMigrationError,
    DatabasePasswordPolicyError,
    DatabasePasswordRequiredError,
    DatabaseSecurityError,
    DatabaseSessionPasswordManager,
    InvalidDatabasePasswordError,
    KeyringCredentialError,
    KeyringDatabaseCredentialStore,
    SQLCipherDatabaseService,
    SQLCipherUnavailableError,
    apply_sqlcipher_key,
    database_profile_id,
    detect_database_keyring_backend,
    is_plaintext_sqlite_database,
    is_probably_encrypted_database,
    normalize_database_path,
    sqlcipher_memory_security_enabled,
    validate_database_password,
)
from isrc_manager.services.db_access import SQLiteConnectionFactory
from isrc_manager.services.session import DatabaseSessionService


@dataclass(slots=True)
class FakeKeyringBackend:
    available: bool = True
    fail_reads: bool = False
    fail_writes: bool = False
    values: dict[tuple[str, str], str] = field(default_factory=dict)

    def get_password(self, service_name: str, account_key: str) -> str | None:
        if self.fail_reads:
            raise RuntimeError("keyring read failed")
        return self.values.get((service_name, account_key))

    def set_password(self, service_name: str, account_key: str, value: str) -> None:
        if self.fail_writes:
            raise RuntimeError("keyring write failed")
        self.values[(service_name, account_key)] = value

    def delete_password(self, service_name: str, account_key: str) -> None:
        self.values.pop((service_name, account_key), None)


class FakeInsecureKeyringBackend(FakeKeyringBackend):
    pass


FakeInsecureKeyringBackend.__module__ = "keyrings.alt.file"


@dataclass(slots=True)
class RecordingSQLCipherConnection:
    fail_memory_security: bool = False
    statements: list[str] = field(default_factory=list)

    def execute(self, statement: str):
        self.statements.append(statement)
        if self.fail_memory_security and "cipher_memory_security" in statement:
            raise RuntimeError("secure memory unavailable")
        return self


class MissingMethodsBackend:
    available = True


def test_database_password_policy_rejects_blank_short_and_mismatch() -> None:
    with pytest.raises(DatabasePasswordPolicyError):
        validate_database_password("   ")
    with pytest.raises(DatabasePasswordPolicyError):
        validate_database_password("too-short")
    with pytest.raises(DatabasePasswordPolicyError):
        validate_database_password("valid-secret-123", confirmation="valid-secret-456")

    assert validate_database_password("valid-secret-123", confirmation="valid-secret-123")


def test_sqlcipher_memory_security_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SQLCIPHER_MEMORY_SECURITY_ENV, raising=False)
    conn = RecordingSQLCipherConnection()

    apply_sqlcipher_key(conn, "valid-secret-123")

    assert sqlcipher_memory_security_enabled({}) is False
    assert conn.statements == ["PRAGMA key = 'valid-secret-123'"]


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_sqlcipher_memory_security_can_be_enabled_by_environment(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv(SQLCIPHER_MEMORY_SECURITY_ENV, value)
    conn = RecordingSQLCipherConnection()

    apply_sqlcipher_key(conn, "valid-secret-123")

    assert "PRAGMA cipher_memory_security = ON" in conn.statements


def test_sqlcipher_memory_security_can_be_explicitly_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SQLCIPHER_MEMORY_SECURITY_ENV, "true")
    conn = RecordingSQLCipherConnection()

    apply_sqlcipher_key(conn, "valid-secret-123", enable_memory_security=False)

    assert conn.statements == ["PRAGMA key = 'valid-secret-123'"]


def test_sqlcipher_memory_security_failure_does_not_prevent_key_application() -> None:
    conn = RecordingSQLCipherConnection(fail_memory_security=True)

    apply_sqlcipher_key(conn, "valid-secret-123", enable_memory_security=True)

    assert conn.statements == [
        "PRAGMA key = 'valid-secret-123'",
        "PRAGMA cipher_memory_security = ON",
    ]


def test_database_path_ids_session_clear_and_sqlcipher_import_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "profiles" / "catalog.db"
    normalized = normalize_database_path(db_path)

    assert database_profile_id(db_path) == database_profile_id(normalized)

    passwords = DatabaseSessionPasswordManager()
    passwords.set_password(db_path, "valid-secret-123")
    assert passwords.password_for_database(db_path) == "valid-secret-123"
    passwords.clear()
    assert passwords.password_for_database(db_path) is None

    monkeypatch.setattr(
        "isrc_manager.services.database_security.importlib.import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("sqlcipher missing")),
    )
    with pytest.raises(SQLCipherUnavailableError):
        SQLCipherDatabaseService().open(db_path, "valid-secret-123")


def test_keyring_backend_detection_covers_unavailable_and_missing_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_methods = detect_database_keyring_backend(MissingMethodsBackend())
    assert missing_methods.available is False
    assert "required credential methods" in missing_methods.reason

    unavailable = detect_database_keyring_backend(FakeKeyringBackend(available=False))
    assert unavailable.available is False
    assert "unavailable" in unavailable.reason

    monkeypatch.setattr(
        "isrc_manager.services.database_security.importlib.import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("keyring missing")),
    )
    missing_keyring = detect_database_keyring_backend()
    assert missing_keyring.available is False
    assert missing_keyring.backend_name == "none"

    class FailingKeyringModule:
        @staticmethod
        def get_keyring():
            raise RuntimeError("backend unavailable")

    monkeypatch.setattr(
        "isrc_manager.services.database_security.importlib.import_module",
        lambda _name: FailingKeyringModule,
    )
    failing_keyring = detect_database_keyring_backend()
    assert failing_keyring.available is False
    assert failing_keyring.backend_name == "unavailable"


def test_connection_factory_creates_sqlcipher_database_when_session_password_is_set(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    passwords = DatabaseSessionPasswordManager()
    passwords.set_password(db_path, "valid-secret-123")
    factory = SQLiteConnectionFactory(password_provider=passwords)

    conn = factory.open(db_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
        conn.execute("CREATE TABLE tracks(id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO tracks(title) VALUES (?)", ("Song",))
        conn.commit()
    finally:
        conn.close()

    assert is_probably_encrypted_database(db_path)
    assert not is_plaintext_sqlite_database(db_path)
    assert not db_path.with_suffix(".db-wal").exists()
    assert not db_path.with_suffix(".db-shm").exists()
    with pytest.raises(sqlite3.DatabaseError):
        plaintext_conn = sqlite3.connect(str(db_path))
        try:
            plaintext_conn.execute("SELECT title FROM tracks").fetchall()
        finally:
            plaintext_conn.close()

    reopened = factory.open(db_path)
    try:
        assert reopened.execute("SELECT title FROM tracks").fetchone() == ("Song",)
    finally:
        reopened.close()

    passwords.forget_password(db_path)
    with pytest.raises(DatabasePasswordRequiredError):
        factory.open(db_path)


def test_connection_factory_rejects_wrong_sqlcipher_password(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    passwords = DatabaseSessionPasswordManager()
    passwords.set_password(db_path, "valid-secret-123")
    factory = SQLiteConnectionFactory(password_provider=passwords)
    conn = factory.open(db_path)
    try:
        conn.execute("CREATE TABLE demo(value TEXT)")
        conn.execute("INSERT INTO demo(value) VALUES ('ready')")
        conn.commit()
    finally:
        conn.close()

    passwords.set_password(db_path, "wrong-secret-123")
    with pytest.raises(InvalidDatabasePasswordError):
        factory.open(db_path)


def test_database_session_service_uses_encrypted_connection_factory(tmp_path: Path) -> None:
    db_path = tmp_path / "session.db"
    passwords = DatabaseSessionPasswordManager()
    passwords.set_password(db_path, "session-secret-123")
    service = DatabaseSessionService(SQLiteConnectionFactory(password_provider=passwords))

    session = service.open(db_path)
    try:
        session.conn.execute("INSERT INTO app_kv(key, value) VALUES (?, ?)", ("ready", "yes"))
        session.conn.commit()
    finally:
        service.close(session.conn)

    assert is_probably_encrypted_database(db_path)


def test_encrypted_database_session_migrates_reopens_without_wal_sidecars(tmp_path: Path) -> None:
    db_path = tmp_path / "new-profile.db"
    passwords = DatabaseSessionPasswordManager()
    passwords.set_password(db_path, "session-secret-123")
    service = DatabaseSessionService(SQLiteConnectionFactory(password_provider=passwords))

    session = service.open(db_path)
    try:
        schema = DatabaseSchemaService(session.conn, data_root=tmp_path / "data")
        schema.init_db()
        schema.migrate_schema()
        session.conn.commit()
        assert schema.get_db_version() == SCHEMA_TARGET
        assert session.conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert session.conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
    finally:
        service.close(session.conn)

    assert not db_path.with_suffix(".db-wal").exists()
    assert not db_path.with_suffix(".db-shm").exists()

    reopened = service.open(db_path)
    try:
        reopened_schema = DatabaseSchemaService(reopened.conn, data_root=tmp_path / "data")
        assert reopened_schema.get_db_version() == SCHEMA_TARGET
        assert reopened.conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert (
            reopened.conn.execute("SELECT COUNT(*) FROM CodeRegistryCategories").fetchone()[0] > 0
        )
    finally:
        service.close(reopened.conn)


def test_sqlcipher_schema_init_and_migrate_reaches_current_target(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    service = SQLCipherDatabaseService()
    conn = service.open(db_path, "schema-secret-123")
    try:
        schema = DatabaseSchemaService(conn)
        schema.init_db()
        assert schema.get_db_version() == 0

        schema.migrate_schema()

        assert schema.get_db_version() == SCHEMA_TARGET
        assert conn.execute("SELECT COUNT(*) FROM CodeRegistryCategories").fetchone()[0] > 0
    finally:
        conn.close()


@pytest.mark.parametrize("legacy_version", range(1, SCHEMA_TARGET))
def test_sqlcipher_schema_migration_from_legacy_versions_reaches_current_target(
    tmp_path: Path,
    legacy_version: int,
) -> None:
    db_path = tmp_path / f"legacy_{legacy_version}.db"
    service = SQLCipherDatabaseService()
    conn = service.open(db_path, "legacy-secret-123")
    try:
        schema = DatabaseSchemaService(conn, data_root=tmp_path / f"data_{legacy_version}")
        schema.init_db()
        conn.execute(f"PRAGMA user_version = {legacy_version}")
        conn.commit()

        schema.migrate_schema()

        assert schema.get_db_version() == SCHEMA_TARGET
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        conn.close()


def test_sqlcipher_database_service_changes_password(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    service = SQLCipherDatabaseService()
    conn = service.open(db_path, "initial-secret-123")
    try:
        conn.execute("CREATE TABLE demo(value TEXT)")
        conn.execute("INSERT INTO demo(value) VALUES ('before')")
        conn.commit()
    finally:
        conn.close()

    service.change_password(db_path, "initial-secret-123", "changed-secret-123")

    with pytest.raises(InvalidDatabasePasswordError):
        service.open(db_path, "initial-secret-123")
    reopened = service.open(db_path, "changed-secret-123")
    try:
        assert reopened.execute("SELECT value FROM demo").fetchone() == ("before",)
    finally:
        reopened.close()


def test_sqlcipher_database_service_change_password_rolls_back_failures() -> None:
    class FailingConnection:
        def __init__(self):
            self.closed = False
            self.rollback_called = False

        def execute(self, _statement: str):
            raise sqlite3.DatabaseError("rekey failed")

        def commit(self):
            raise AssertionError("commit should not run after execute failure")

        def rollback(self):
            self.rollback_called = True
            raise sqlite3.DatabaseError("rollback failed")

        def close(self):
            self.closed = True

    conn = FailingConnection()

    class FailingService(SQLCipherDatabaseService):
        def open(self, path, password):
            return conn

    with pytest.raises(DatabaseSecurityError, match="Could not change"):
        FailingService().change_password("catalog.db", "current-secret-123", "changed-secret-123")

    assert conn.rollback_called is True
    assert conn.closed is True


def test_sqlcipher_database_service_migrates_plaintext_database_safely(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE demo(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO demo(value) VALUES ('plain')")
        conn.commit()
    assert is_plaintext_sqlite_database(db_path)

    result = SQLCipherDatabaseService().encrypt_plaintext_database(db_path, "migrate-secret-123")

    assert result.database_path == db_path
    assert result.backup_path.exists()
    assert is_plaintext_sqlite_database(result.backup_path)
    assert is_probably_encrypted_database(db_path)
    with pytest.raises(sqlite3.DatabaseError):
        plaintext_conn = sqlite3.connect(str(db_path))
        try:
            plaintext_conn.execute("SELECT value FROM demo").fetchall()
        finally:
            plaintext_conn.close()

    encrypted_conn = SQLCipherDatabaseService().open(db_path, "migrate-secret-123")
    try:
        assert encrypted_conn.execute("SELECT value FROM demo").fetchone() == ("plain",)
    finally:
        encrypted_conn.close()


def test_sqlcipher_migrated_plaintext_legacy_profile_tolerates_invalid_isrc(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy_invalid_isrc.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE Tracks (
                id INTEGER PRIMARY KEY,
                isrc TEXT NOT NULL,
                isrc_compact TEXT,
                track_title TEXT NOT NULL,
                main_artist_id INTEGER NOT NULL,
                album_id INTEGER,
                release_date DATE,
                track_length_sec INTEGER NOT NULL DEFAULT 0,
                iswc TEXT,
                upc TEXT,
                genre TEXT
            );
            CREATE TABLE CustomFieldDefs (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER,
                field_type TEXT NOT NULL DEFAULT 'text',
                options TEXT
            );
            CREATE TABLE CustomFieldValues (
                track_id INTEGER NOT NULL,
                field_def_id INTEGER NOT NULL,
                value TEXT,
                blob_value BLOB,
                mime_type TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (track_id, field_def_id)
            );
            INSERT INTO Tracks(
                id, isrc, isrc_compact, track_title, main_artist_id, album_id,
                release_date, track_length_sec, iswc, upc, genre
            )
            VALUES (1, 'legacy invalid isrc', '', 'Legacy Invalid', 1, NULL, NULL, 0, NULL, NULL, NULL);
            CREATE TRIGGER trg_tracks_isrc_validate_upd
            BEFORE UPDATE ON Tracks
            FOR EACH ROW
            WHEN NOT (
                length(replace(replace(upper(NEW.isrc),'-',''),' ','')) = 12
                AND replace(replace(upper(NEW.isrc),'-',''),' ','') GLOB
                    '[A-Z][A-Z][A-Z0-9][A-Z0-9][A-Z0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                AND upper(NEW.isrc_compact) = replace(replace(upper(NEW.isrc),'-',''),' ','')
            )
            BEGIN
                SELECT RAISE(ABORT, 'ISRC validation failed');
            END;
            """)
        conn.execute("PRAGMA user_version = 12")
        conn.commit()

    SQLCipherDatabaseService().encrypt_plaintext_database(db_path, "legacy-secret-123")
    encrypted_conn = SQLCipherDatabaseService().open(db_path, "legacy-secret-123")
    try:
        schema = DatabaseSchemaService(encrypted_conn, data_root=tmp_path / "data")

        assert schema.get_db_version() == 12
        schema.migrate_schema()

        assert schema.get_db_version() == SCHEMA_TARGET
        assert encrypted_conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert encrypted_conn.execute(
            "SELECT isrc, isrc_compact FROM Tracks WHERE id=1"
        ).fetchone() == ("", "")
        assert "legacy invalid isrc" in str(
            encrypted_conn.execute("SELECT comments FROM Tracks WHERE id=1").fetchone()[0]
        )
    finally:
        encrypted_conn.close()


def test_sqlcipher_database_service_uses_explicit_backup_path(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE demo(value TEXT)")
        conn.execute("INSERT INTO demo(value) VALUES ('plain')")
        conn.commit()
    backup_path = tmp_path / "app-data" / "backups" / "catalog_unencrypted.db"

    result = SQLCipherDatabaseService().encrypt_plaintext_database(
        db_path,
        "explicit-secret-123",
        backup_path=backup_path,
    )

    assert result.backup_path == backup_path
    assert backup_path.exists()
    assert is_plaintext_sqlite_database(backup_path)
    assert is_probably_encrypted_database(db_path)


def test_sqlcipher_database_service_encrypt_plaintext_database_guardrails(
    tmp_path: Path,
) -> None:
    service = SQLCipherDatabaseService()
    missing_db = tmp_path / "missing.db"
    with pytest.raises(DatabaseMigrationError, match="does not exist"):
        service.encrypt_plaintext_database(missing_db, "migrate-secret-123")

    not_sqlite = tmp_path / "not-sqlite.db"
    not_sqlite.write_bytes(b"not a sqlite database")
    with pytest.raises(DatabaseMigrationError, match="not an unencrypted SQLite"):
        service.encrypt_plaintext_database(not_sqlite, "migrate-secret-123")

    plaintext = tmp_path / "catalog.db"
    with sqlite3.connect(plaintext) as conn:
        conn.execute("CREATE TABLE demo(value TEXT)")
        conn.commit()
    backup = tmp_path / "catalog.backup.db"
    backup.write_bytes(b"existing")
    with pytest.raises(DatabaseMigrationError, match="Backup path already exists"):
        service.encrypt_plaintext_database(
            plaintext,
            "migrate-secret-123",
            backup_path=backup,
        )


def test_sqlcipher_database_service_encrypt_plaintext_database_verification_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE demo(value TEXT)")
        conn.execute("PRAGMA user_version = 7")
        conn.commit()

    class ExecuteResult:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return (self.value,)

    class FakeSourceConnection:
        def __init__(self):
            self.closed = False

        def execute(self, statement: str):
            if statement == "PRAGMA user_version":
                return ExecuteResult(7)
            return ExecuteResult(None)

        def close(self):
            self.closed = True

    class FakeSQLCipherModule:
        @staticmethod
        def connect(_path, timeout):
            return FakeSourceConnection()

    monkeypatch.setattr(
        "isrc_manager.services.database_security._sqlcipher_module",
        lambda: FakeSQLCipherModule,
    )

    class BadIntegrityConnection:
        def execute(self, statement: str):
            if statement == "PRAGMA integrity_check":
                return ExecuteResult("corrupt")
            return ExecuteResult(None)

        def commit(self):
            return None

        def close(self):
            return None

    service = SQLCipherDatabaseService()
    service.open = lambda _path, _password: BadIntegrityConnection()

    with pytest.raises(DatabaseMigrationError, match="verification failed"):
        service.encrypt_plaintext_database(db_path, "migrate-secret-123")


def test_keyring_store_remembers_expires_and_clears_database_password(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    backend = FakeKeyringBackend()
    store = KeyringDatabaseCredentialStore(backend=backend, ttl_days=30)
    authenticated_at = datetime(2026, 6, 1, tzinfo=timezone.utc)

    store.remember(db_path, "remember-secret-123", authenticated_at=authenticated_at)

    assert (
        store.load(db_path, now=datetime(2026, 6, 15, tzinfo=timezone.utc)) == "remember-secret-123"
    )
    assert store.load(db_path, now=datetime(2026, 7, 5, tzinfo=timezone.utc)) is None
    assert backend.values == {}


def test_keyring_store_handles_naive_timestamps_missing_values_and_io_errors(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "catalog.db"
    backend = FakeKeyringBackend()
    store = KeyringDatabaseCredentialStore(backend=backend, ttl_days=30)

    store.remember(db_path, "remember-secret-123", authenticated_at=datetime(2026, 6, 1))
    assert store.load(db_path, now=datetime(2026, 6, 2)) == "remember-secret-123"

    store.clear(db_path)
    assert store.load(db_path, now=datetime(2026, 6, 2, tzinfo=timezone.utc)) is None

    backend.set_password(store.service_name, store._password_key(db_path), "remember-secret-123")
    backend.set_password(store.service_name, store._timestamp_key(db_path), "not-a-date")
    assert store.load(db_path, now=datetime(2026, 6, 2, tzinfo=timezone.utc)) is None
    assert backend.values == {}

    failing_read_store = KeyringDatabaseCredentialStore(backend=FakeKeyringBackend(fail_reads=True))
    with pytest.raises(KeyringCredentialError, match="Could not read"):
        failing_read_store.load(db_path)

    class FailingDeleteBackend(FakeKeyringBackend):
        def delete_password(self, service_name: str, account_key: str) -> None:
            raise RuntimeError("delete failed")

    failing_delete_store = KeyringDatabaseCredentialStore(backend=FailingDeleteBackend())
    failing_delete_store.clear(db_path)

    unavailable_store = KeyringDatabaseCredentialStore(backend=FakeKeyringBackend(available=False))
    unavailable_store.clear(db_path)


def test_keyring_store_removes_invalid_stored_password(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    backend = FakeKeyringBackend()
    store = KeyringDatabaseCredentialStore(backend=backend)
    backend.set_password(store.service_name, store._password_key(db_path), "short")
    backend.set_password(
        store.service_name,
        store._timestamp_key(db_path),
        datetime(2026, 6, 1, tzinfo=timezone.utc).isoformat(),
    )

    assert store.load(db_path, now=datetime(2026, 6, 2, tzinfo=timezone.utc)) is None
    assert backend.values == {}


def test_keyring_store_rejects_unsafe_or_failing_backends(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    unsafe_store = KeyringDatabaseCredentialStore(backend=FakeInsecureKeyringBackend())
    assert not unsafe_store.persistent_available
    with pytest.raises(KeyringCredentialError):
        unsafe_store.remember(db_path, "remember-secret-123")

    failing_store = KeyringDatabaseCredentialStore(backend=FakeKeyringBackend(fail_writes=True))
    with pytest.raises(KeyringCredentialError):
        failing_store.remember(db_path, "remember-secret-123")


def test_keyring_store_initializes_without_importable_or_working_keyring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "isrc_manager.services.database_security.importlib.import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("keyring missing")),
    )
    missing_store = KeyringDatabaseCredentialStore()
    assert missing_store.backend is None
    assert missing_store.persistent_available is False

    class FailingKeyringModule:
        @staticmethod
        def get_keyring():
            raise RuntimeError("backend unavailable")

    monkeypatch.setattr(
        "isrc_manager.services.database_security.importlib.import_module",
        lambda _name: FailingKeyringModule,
    )
    failing_store = KeyringDatabaseCredentialStore()
    assert failing_store.backend is None
    assert failing_store.persistent_available is False

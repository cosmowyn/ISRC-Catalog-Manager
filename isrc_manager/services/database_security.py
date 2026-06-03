"""SQLCipher database security services."""

from __future__ import annotations

import hashlib
import importlib
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

SQLITE_HEADER = b"SQLite format 3\x00"
MIN_DATABASE_PASSWORD_LENGTH = 12
REMEMBERED_DATABASE_PASSWORD_TTL_DAYS = 30
DEFAULT_DATABASE_KEYRING_SERVICE = "isrc-catalog-manager.database"
SQLCIPHER_MEMORY_SECURITY_ENV = "ISRC_SQLCIPHER_MEMORY_SECURITY"


class DatabaseSecurityError(RuntimeError):
    """Base class for database security failures."""


class DatabasePasswordPolicyError(DatabaseSecurityError, ValueError):
    """Raised when a database password does not satisfy policy."""


class DatabasePasswordRequiredError(DatabaseSecurityError):
    """Raised when an encrypted database is opened without a session password."""


class InvalidDatabasePasswordError(DatabaseSecurityError):
    """Raised when SQLCipher cannot unlock a database with the supplied password."""


class SQLCipherUnavailableError(DatabaseSecurityError):
    """Raised when the SQLCipher Python binding is not available."""


class DatabaseMigrationError(DatabaseSecurityError):
    """Raised when an unencrypted profile cannot be safely encrypted."""


class KeyringCredentialError(DatabaseSecurityError):
    """Raised when secure keyring persistence is unavailable or fails."""


class DatabasePasswordProvider(Protocol):
    """Provides an in-memory password for a database path."""

    def password_for_database(self, path: str | Path) -> str | None: ...


class KeyringPasswordBackend(Protocol):
    """Subset of the Python keyring backend API used for database credentials."""

    available: bool

    def get_password(self, service_name: str, account_key: str) -> str | None: ...

    def set_password(self, service_name: str, account_key: str, value: str) -> None: ...

    def delete_password(self, service_name: str, account_key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class DatabaseKeyringAvailability:
    """Runtime report for whether a keyring backend can persist passwords safely."""

    available: bool
    safe: bool
    backend_name: str
    reason: str

    @property
    def usable(self) -> bool:
        return self.available and self.safe


@dataclass(frozen=True, slots=True)
class DatabaseMigrationResult:
    """Result of encrypting an existing plaintext SQLite profile."""

    database_path: Path
    backup_path: Path


def normalize_database_path(path: str | Path) -> str:
    """Return a stable key for a database path without requiring it to exist."""

    return str(Path(path).expanduser().resolve(strict=False))


def database_profile_id(path: str | Path) -> str:
    """Return an opaque id for keyring account names."""

    return hashlib.sha256(normalize_database_path(path).encode("utf-8")).hexdigest()


def validate_database_password(password: str, confirmation: str | None = None) -> str:
    """Validate and return a database password."""

    value = str(password or "")
    if not value.strip():
        raise DatabasePasswordPolicyError("Database password cannot be blank.")
    if len(value) < MIN_DATABASE_PASSWORD_LENGTH:
        raise DatabasePasswordPolicyError(
            f"Database password must be at least {MIN_DATABASE_PASSWORD_LENGTH} characters."
        )
    if confirmation is not None and value != str(confirmation or ""):
        raise DatabasePasswordPolicyError("Database password confirmation does not match.")
    return value


def is_plaintext_sqlite_database(path: str | Path) -> bool:
    """Return whether a file has the standard plaintext SQLite header."""

    db_path = Path(path)
    if not db_path.exists() or db_path.stat().st_size < len(SQLITE_HEADER):
        return False
    with db_path.open("rb") as handle:
        return handle.read(len(SQLITE_HEADER)) == SQLITE_HEADER


def is_probably_encrypted_database(path: str | Path) -> bool:
    """Return whether a non-empty file is not readable by the SQLite header check."""

    db_path = Path(path)
    return (
        db_path.exists()
        and db_path.stat().st_size > 0
        and not is_plaintext_sqlite_database(db_path)
    )


def _quote_sql_literal(value: str | Path) -> str:
    return str(value).replace("'", "''")


def sqlcipher_memory_security_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether SQLCipher secure-memory locking was explicitly requested."""

    env = os.environ if environ is None else environ
    value = str(env.get(SQLCIPHER_MEMORY_SECURITY_ENV, "") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _sqlcipher_module() -> Any:
    try:
        return importlib.import_module("sqlcipher3")
    except Exception as exc:
        raise SQLCipherUnavailableError(
            "SQLCipher support is unavailable. Install the sqlcipher3 package."
        ) from exc


def apply_sqlcipher_key(
    conn: Any,
    password: str,
    *,
    enable_memory_security: bool | None = None,
) -> None:
    """Apply a SQLCipher key to a newly opened connection."""

    key = validate_database_password(password)
    conn.execute(f"PRAGMA key = '{_quote_sql_literal(key)}'")
    should_enable_memory_security = (
        sqlcipher_memory_security_enabled()
        if enable_memory_security is None
        else enable_memory_security
    )
    if should_enable_memory_security:
        try:
            conn.execute("PRAGMA cipher_memory_security = ON")
        except Exception:
            pass


def verify_sqlcipher_connection(conn: Any) -> None:
    """Force SQLCipher to validate the database header and key."""

    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except Exception as exc:
        raise InvalidDatabasePasswordError(
            "Could not unlock this database. Check the password or file integrity."
        ) from exc


def open_sqlcipher_connection(
    path: str | Path,
    password: str,
    *,
    timeout_seconds: float = 30.0,
) -> Any:
    """Open a SQLCipher database and verify the supplied password."""

    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sqlcipher3 = _sqlcipher_module()
    conn = sqlcipher3.connect(str(db_path), timeout=float(timeout_seconds))
    try:
        apply_sqlcipher_key(conn, password)
        verify_sqlcipher_connection(conn)
    except Exception:
        try:
            conn.close()
        finally:
            raise
    return conn


class DatabaseSessionPasswordManager:
    """Stores decrypted database passwords for the current app session only."""

    def __init__(self) -> None:
        self._passwords: dict[str, str] = {}

    def set_password(self, path: str | Path, password: str) -> None:
        self._passwords[normalize_database_path(path)] = validate_database_password(password)

    def password_for_database(self, path: str | Path) -> str | None:
        return self._passwords.get(normalize_database_path(path))

    def forget_password(self, path: str | Path) -> None:
        self._passwords.pop(normalize_database_path(path), None)

    def clear(self) -> None:
        self._passwords.clear()


def _backend_name(backend: object | None) -> str:
    if backend is None:
        return "none"
    cls = backend.__class__
    module = str(getattr(cls, "__module__", "") or "")
    name = str(getattr(cls, "__name__", "") or "")
    return f"{module}.{name}".strip(".") or repr(cls)


def detect_database_keyring_backend(
    backend: KeyringPasswordBackend | object | None = None,
) -> DatabaseKeyringAvailability:
    """Return a conservative safety report for a keyring-compatible backend."""

    if backend is None:
        try:
            keyring = importlib.import_module("keyring")
        except Exception:
            return DatabaseKeyringAvailability(
                available=False,
                safe=False,
                backend_name="none",
                reason="Python keyring is not installed.",
            )
        try:
            backend = keyring.get_keyring()
        except Exception:
            return DatabaseKeyringAvailability(
                available=False,
                safe=False,
                backend_name="unavailable",
                reason="Python keyring did not provide a backend.",
            )

    name = _backend_name(backend)
    lower_name = name.lower()
    required_methods = ("get_password", "set_password", "delete_password")
    if not all(callable(getattr(backend, method, None)) for method in required_methods):
        return DatabaseKeyringAvailability(
            available=False,
            safe=False,
            backend_name=name,
            reason="Keyring backend does not implement the required credential methods.",
        )
    if not bool(getattr(backend, "available", True)):
        return DatabaseKeyringAvailability(
            available=False,
            safe=False,
            backend_name=name,
            reason="Keyring backend reports that it is unavailable.",
        )
    if any(token in lower_name for token in ("keyrings.alt", "plaintext", "file")):
        return DatabaseKeyringAvailability(
            available=True,
            safe=False,
            backend_name=name,
            reason="Keyring backend is not safe for database passwords.",
        )
    return DatabaseKeyringAvailability(
        available=True,
        safe=True,
        backend_name=name,
        reason="Safe OS keychain/keyring backend is available.",
    )


class KeyringDatabaseCredentialStore:
    """Stores remembered database passwords only in a safe OS keychain/keyring."""

    def __init__(
        self,
        *,
        backend: KeyringPasswordBackend | object | None = None,
        service_name: str = DEFAULT_DATABASE_KEYRING_SERVICE,
        ttl_days: int = REMEMBERED_DATABASE_PASSWORD_TTL_DAYS,
    ) -> None:
        self.backend = backend
        if self.backend is None:
            try:
                keyring = importlib.import_module("keyring")
            except Exception:
                self.backend = None
            else:
                try:
                    self.backend = keyring.get_keyring()
                except Exception:
                    self.backend = None
        self.service_name = service_name
        self.ttl = timedelta(days=max(1, int(ttl_days)))
        self.availability = detect_database_keyring_backend(self.backend)

    @property
    def persistent_available(self) -> bool:
        return self.availability.usable

    def _require_backend(self) -> KeyringPasswordBackend:
        if not self.availability.usable or self.backend is None:
            raise KeyringCredentialError("Safe OS keychain/keyring storage is unavailable.")
        return self.backend  # type: ignore[return-value]

    @staticmethod
    def _password_key(path: str | Path) -> str:
        return f"database:{database_profile_id(path)}:password"

    @staticmethod
    def _timestamp_key(path: str | Path) -> str:
        return f"database:{database_profile_id(path)}:authenticated_at"

    def remember(
        self,
        path: str | Path,
        password: str,
        *,
        authenticated_at: datetime | None = None,
    ) -> None:
        backend = self._require_backend()
        secret = validate_database_password(password)
        timestamp = authenticated_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        try:
            backend.set_password(self.service_name, self._password_key(path), secret)
            backend.set_password(
                self.service_name,
                self._timestamp_key(path),
                timestamp.astimezone(timezone.utc).isoformat(),
            )
        except Exception as exc:
            raise KeyringCredentialError(
                "Could not store the database password in the OS keychain/keyring."
            ) from exc

    def load(self, path: str | Path, *, now: datetime | None = None) -> str | None:
        backend = self._require_backend()
        try:
            password = backend.get_password(self.service_name, self._password_key(path))
            authenticated_at = backend.get_password(self.service_name, self._timestamp_key(path))
        except Exception as exc:
            raise KeyringCredentialError(
                "Could not read the database password from the OS keychain/keyring."
            ) from exc
        if not password or not authenticated_at:
            return None
        try:
            parsed_timestamp = datetime.fromisoformat(str(authenticated_at))
        except ValueError:
            self.clear(path)
            return None
        if parsed_timestamp.tzinfo is None:
            parsed_timestamp = parsed_timestamp.replace(tzinfo=timezone.utc)
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        if (
            current_time.astimezone(timezone.utc) - parsed_timestamp.astimezone(timezone.utc)
            > self.ttl
        ):
            self.clear(path)
            return None
        try:
            return validate_database_password(str(password))
        except DatabasePasswordPolicyError:
            self.clear(path)
            return None

    def clear(self, path: str | Path) -> None:
        try:
            backend = self._require_backend()
        except KeyringCredentialError:
            return
        for account_key in (self._password_key(path), self._timestamp_key(path)):
            try:
                backend.delete_password(self.service_name, account_key)
            except Exception:
                pass


class SQLCipherDatabaseService:
    """High-level SQLCipher profile operations."""

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    def open(self, path: str | Path, password: str) -> Any:
        return open_sqlcipher_connection(path, password, timeout_seconds=self.timeout_seconds)

    def change_password(self, path: str | Path, current_password: str, new_password: str) -> None:
        validate_database_password(new_password)
        conn = self.open(path, current_password)
        try:
            conn.execute(f"PRAGMA rekey = '{_quote_sql_literal(new_password)}'")
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            raise DatabaseSecurityError("Could not change the database password.") from exc
        finally:
            conn.close()
        verify_conn = self.open(path, new_password)
        verify_conn.close()

    def encrypt_plaintext_database(
        self,
        path: str | Path,
        password: str,
        *,
        backup_path: str | Path | None = None,
    ) -> DatabaseMigrationResult:
        source_path = Path(path)
        if not source_path.exists():
            raise DatabaseMigrationError("Database file does not exist.")
        if not is_plaintext_sqlite_database(source_path):
            raise DatabaseMigrationError("Database file is not an unencrypted SQLite profile.")
        secret = validate_database_password(password)
        backup = (
            Path(backup_path)
            if backup_path is not None
            else source_path.with_name(f"{source_path.name}.unencrypted-{_timestamp_slug()}.bak")
        )
        if backup.exists():
            raise DatabaseMigrationError(f"Backup path already exists: {backup}")
        backup.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = source_path.with_name(f".{source_path.name}.encrypted-{uuid.uuid4().hex}.tmp")
        sqlcipher3 = _sqlcipher_module()
        try:
            conn = sqlcipher3.connect(str(source_path), timeout=float(self.timeout_seconds))
            try:
                conn.execute(
                    f"ATTACH DATABASE '{_quote_sql_literal(tmp_path)}' "
                    f"AS encrypted KEY '{_quote_sql_literal(secret)}'"
                )
                conn.execute("SELECT sqlcipher_export('encrypted')")
                conn.execute("DETACH DATABASE encrypted")
            finally:
                conn.close()

            verify_conn = self.open(tmp_path, secret)
            try:
                integrity = (
                    str(verify_conn.execute("PRAGMA integrity_check").fetchone()[0]).strip().lower()
                )
            finally:
                verify_conn.close()
            if integrity != "ok":
                raise DatabaseMigrationError(f"Encrypted database verification failed: {integrity}")

            source_path.replace(backup)
            try:
                tmp_path.replace(source_path)
            except Exception:
                if backup.exists() and not source_path.exists():
                    backup.replace(source_path)
                raise
        except sqlite3.Error as exc:
            raise DatabaseMigrationError("SQLCipher migration failed.") from exc
        except DatabaseSecurityError:
            raise
        except Exception as exc:
            raise DatabaseMigrationError("Could not encrypt the database safely.") from exc
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
        return DatabaseMigrationResult(database_path=source_path, backup_path=backup)


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

"""Database capture, comparison, and replay for persistent history snapshots."""

from __future__ import annotations

import hashlib
import sqlite3
import struct
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isrc_manager.services.database_security import open_sqlcipher_connection

HISTORY_REPLAY_EXCLUDED_TABLES = frozenset(
    {
        "AuditLog",
        "AccountingMaintenanceBypass",
        "HistoryBackups",
        "HistoryEntries",
        "HistoryHead",
        "HistorySnapshots",
        "_MigrationLog",
    }
)


class SnapshotConnectionError(RuntimeError):
    """Raised when a history snapshot cannot be opened with matching security."""


@dataclass(frozen=True, slots=True)
class SnapshotTableDelta:
    """Primary-key identities changed between two database states."""

    table_name: str
    key_columns: tuple[str, ...]
    changed_keys: tuple[tuple[Any, ...], ...]


@dataclass(frozen=True, slots=True)
class _RestorePlan:
    columns: tuple[str, ...]
    key_columns: tuple[str, ...]
    target_rows: Mapping[tuple[Any, ...], tuple[Any, ...] | None]


class SnapshotDatabaseService:
    """Captures, compares, and replays database snapshots without broad table rewrites."""

    _BATCH_SIZE = 256

    def __init__(
        self,
        live_connection: Any,
        source_db_path: str | Path,
        *,
        excluded_tables: Iterable[str],
        insert_only_tables: Iterable[str],
        monotonic_tables: Mapping[str, Iterable[str]] | None = None,
        connection_factory: object | None = None,
        snapshot_connection_opener: Callable[[Path], Any] | None = None,
    ) -> None:
        self.live_connection = live_connection
        self.source_db_path = Path(source_db_path)
        self.excluded_tables = frozenset(str(name) for name in excluded_tables)
        self.insert_only_tables = frozenset(str(name) for name in insert_only_tables)
        self.monotonic_tables = {
            str(table_name): frozenset(str(column) for column in columns)
            for table_name, columns in (monotonic_tables or {}).items()
        }
        self.connection_factory = connection_factory
        self.snapshot_connection_opener = snapshot_connection_opener

    def capture(self, target_path: str | Path) -> None:
        """Copy the live database using matching plaintext or SQLCipher security."""

        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        destination = None
        try:
            destination = self._open_new_snapshot(target)
            if _uses_sqlcipher(self.live_connection) and not _uses_sqlcipher(destination):
                raise SnapshotConnectionError(
                    "Encrypted profiles require encrypted history snapshot connections."
                )
            self.live_connection.backup(destination)
            destination.commit()
        except Exception:
            if destination is not None:
                try:
                    destination.close()
                except Exception:
                    pass
                destination = None
            _remove_database_bundle(target)
            raise
        finally:
            if destination is not None:
                destination.close()

    def changed_rows_between(
        self,
        before_path: str | Path,
        after_path: str | Path,
    ) -> tuple[SnapshotTableDelta, ...]:
        """Return primary-key rows changed by an action's snapshot pair."""

        before = self._open_existing_snapshot(Path(before_path))
        try:
            after = self._open_existing_snapshot(Path(after_path))
            try:
                return self._changed_rows(before, after)
            finally:
                after.close()
        finally:
            before.close()

    def logical_digest(self, snapshot_path: str | Path) -> str:
        """Return a rekey-stable digest of a snapshot's schema and logical rows."""

        snapshot = self._open_existing_snapshot(Path(snapshot_path))
        try:
            return _logical_database_digest(snapshot)
        except SnapshotConnectionError:
            raise
        except Exception as exc:
            raise SnapshotConnectionError(
                "History database snapshot failed its logical integrity check."
            ) from exc
        finally:
            snapshot.close()

    def changed_rows_from_live(self, target_path: str | Path) -> tuple[SnapshotTableDelta, ...]:
        """Return primary-key rows that differ from the current live database."""

        target = self._open_existing_snapshot(Path(target_path))
        try:
            return self._changed_rows(self.live_connection, target)
        finally:
            target.close()

    def restore_rows(
        self,
        target_path: str | Path,
        table_deltas: Iterable[SnapshotTableDelta],
        *,
        expected_snapshot_path: str | Path | None = None,
    ) -> None:
        """Replay only action-changed primary-key rows from a target snapshot."""

        target = self._open_existing_snapshot(Path(target_path))
        expected = None
        try:
            if expected_snapshot_path is not None:
                expected = self._open_existing_snapshot(Path(expected_snapshot_path))
            live_tables = _table_names(self.live_connection) - self.excluded_tables
            target_tables = _table_names(target) - self.excluded_tables
            recorded_deltas = tuple(table_deltas)
            missing_live = sorted(
                delta.table_name for delta in recorded_deltas if delta.table_name not in live_tables
            )
            missing_target = sorted(
                delta.table_name
                for delta in recorded_deltas
                if delta.table_name not in target_tables
            )
            if missing_live or missing_target:
                missing_parts = []
                if missing_live:
                    missing_parts.append("live schema: " + ", ".join(missing_live))
                if missing_target:
                    missing_parts.append("target snapshot: " + ", ".join(missing_target))
                raise SnapshotConnectionError(
                    "Cannot safely replay history because recorded tables are missing from "
                    + "; ".join(missing_parts)
                    + "."
                )
            deltas = {delta.table_name: delta for delta in recorded_deltas}
            ordered_tables = _dependency_order(self.live_connection, deltas)
            plans = {
                table_name: self._restore_plan(target, deltas[table_name])
                for table_name in ordered_tables
            }
            expected_plans = (
                {
                    table_name: self._restore_plan(expected, deltas[table_name])
                    for table_name in ordered_tables
                }
                if expected is not None
                else None
            )
            if expected_plans is not None:
                self._validate_expected_rows(ordered_tables, expected_plans)

            for table_name in reversed(ordered_tables):
                if table_name in self.insert_only_tables or table_name in self.monotonic_tables:
                    continue
                plan = plans[table_name]
                for key, target_row in plan.target_rows.items():
                    if target_row is None and not _is_conditionally_protected_row(
                        self.live_connection,
                        table_name,
                        plan.key_columns,
                        key,
                    ):
                        _delete_row(
                            self.live_connection,
                            table_name,
                            plan.key_columns,
                            key,
                        )

            for table_name in ordered_tables:
                plan = plans[table_name]
                for key, target_row in plan.target_rows.items():
                    if target_row is None:
                        continue
                    if table_name in self.monotonic_tables:
                        _merge_monotonic_row(
                            self.live_connection,
                            table_name,
                            plan,
                            key,
                            target_row,
                            self.monotonic_tables[table_name],
                        )
                    elif table_name in self.insert_only_tables:
                        _insert_row(
                            self.live_connection,
                            table_name,
                            plan.columns,
                            target_row,
                            or_ignore=True,
                        )
                    else:
                        if _is_conditionally_protected_row(
                            self.live_connection,
                            table_name,
                            plan.key_columns,
                            key,
                        ):
                            continue
                        _upsert_mutable_row(
                            self.live_connection,
                            table_name,
                            plan,
                            key,
                            target_row,
                        )
        finally:
            if expected is not None:
                expected.close()
            target.close()

    def _changed_rows(self, left: Any, right: Any) -> tuple[SnapshotTableDelta, ...]:
        left_tables = _table_names(left) - self.excluded_tables
        right_tables = _table_names(right) - self.excluded_tables
        if left_tables != right_tables:
            changed_tables = sorted(left_tables ^ right_tables)
            raise SnapshotConnectionError(
                "Cannot safely scope history across database table changes: "
                + ", ".join(changed_tables)
            )
        candidates = left_tables
        deltas: list[SnapshotTableDelta] = []
        for table_name in sorted(candidates):
            left_keys = _primary_key_columns(left, table_name)
            right_keys = _primary_key_columns(right, table_name)
            if not left_keys or left_keys != right_keys:
                if _tables_equal(left, right, table_name):
                    continue
                raise SnapshotConnectionError(
                    f"Cannot safely scope history table without matching primary keys: {table_name}"
                )
            changed_keys = _changed_primary_keys(left, right, table_name, left_keys)
            if changed_keys:
                deltas.append(
                    SnapshotTableDelta(
                        table_name=table_name,
                        key_columns=left_keys,
                        changed_keys=changed_keys,
                    )
                )
        return tuple(deltas)

    def _restore_plan(self, target: Any, delta: SnapshotTableDelta) -> _RestorePlan:
        live_keys = _primary_key_columns(self.live_connection, delta.table_name)
        target_keys = _primary_key_columns(target, delta.table_name)
        if live_keys != delta.key_columns or target_keys != delta.key_columns:
            raise SnapshotConnectionError(
                f"History primary-key schema changed for table {delta.table_name}."
            )
        live_columns = tuple(
            str(row[1]) for row in _table_columns(self.live_connection, delta.table_name)
        )
        target_columns = tuple(str(row[1]) for row in _table_columns(target, delta.table_name))
        missing_live_columns = sorted(set(target_columns) - set(live_columns))
        if missing_live_columns:
            raise SnapshotConnectionError(
                f"History schema changed for table {delta.table_name}; missing live columns: "
                + ", ".join(missing_live_columns)
            )
        columns = tuple(column for column in live_columns if column in set(target_columns))
        target_rows = {
            key: _fetch_snapshot_row(
                target,
                delta.table_name,
                columns,
                delta.key_columns,
                key,
            )
            for key in delta.changed_keys
        }
        return _RestorePlan(
            columns=columns,
            key_columns=delta.key_columns,
            target_rows=target_rows,
        )

    def _validate_expected_rows(
        self,
        ordered_tables: tuple[str, ...],
        expected_plans: Mapping[str, _RestorePlan],
    ) -> None:
        for table_name in ordered_tables:
            if table_name in self.insert_only_tables or table_name in self.monotonic_tables:
                continue
            plan = expected_plans[table_name]
            for key, expected_row in plan.target_rows.items():
                if _is_conditionally_protected_row(
                    self.live_connection,
                    table_name,
                    plan.key_columns,
                    key,
                ):
                    continue
                live_row = _fetch_live_row(
                    self.live_connection,
                    table_name,
                    plan.columns,
                    plan.key_columns,
                    key,
                )
                if live_row != expected_row:
                    raise SnapshotConnectionError(
                        "Cannot replay history because an action-owned row changed after "
                        f"the action was recorded: {table_name} {key!r}"
                    )

    def _open_new_snapshot(self, path: Path) -> Any:
        if self.snapshot_connection_opener is not None:
            return self.snapshot_connection_opener(path)
        if _uses_sqlcipher(self.live_connection):
            password = self._source_password()
            if not password:
                raise SnapshotConnectionError(
                    "Encrypted history snapshots require the active profile connection factory."
                )
            return open_sqlcipher_connection(
                path,
                password,
                timeout_seconds=self._timeout_seconds(),
            )
        return sqlite3.connect(str(path))

    def _open_existing_snapshot(self, path: Path) -> Any:
        if not path.exists():
            raise FileNotFoundError(path)
        if _is_plaintext_sqlite(path):
            return sqlite3.connect(str(path))
        if self.snapshot_connection_opener is not None:
            return self.snapshot_connection_opener(path)
        password = self._source_password()
        if not password:
            raise SnapshotConnectionError(
                "Encrypted history snapshot could not be unlocked for this profile."
            )
        return open_sqlcipher_connection(
            path,
            password,
            timeout_seconds=self._timeout_seconds(),
        )

    def _source_password(self) -> str | None:
        provider = getattr(self.connection_factory, "password_provider", None)
        password_for_database = getattr(provider, "password_for_database", None)
        if not callable(password_for_database):
            return None
        password = password_for_database(self.source_db_path)
        return str(password) if password else None

    def _timeout_seconds(self) -> float:
        return float(getattr(self.connection_factory, "timeout_seconds", 30.0))


def profile_database_states_match(
    live_profile_path: str | Path,
    snapshot_path: str | Path,
    *,
    connection_factory: object,
) -> bool:
    """Compare profile domain state while ignoring history's own bookkeeping rows."""

    live_path = Path(live_profile_path)
    provider = getattr(connection_factory, "password_provider", None)
    password_for_database = getattr(provider, "password_for_database", None)
    password = password_for_database(live_path) if callable(password_for_database) else None
    timeout_seconds = float(getattr(connection_factory, "timeout_seconds", 30.0))

    def open_artifact(path: Path) -> Any:
        if _is_plaintext_sqlite(path):
            return sqlite3.connect(str(path))
        if not password:
            raise SnapshotConnectionError(
                "Encrypted profile history could not be compared without its session password."
            )
        return open_sqlcipher_connection(
            path,
            str(password),
            timeout_seconds=timeout_seconds,
        )

    comparison = SnapshotDatabaseService(
        live_connection=None,
        source_db_path=live_path,
        excluded_tables=HISTORY_REPLAY_EXCLUDED_TABLES,
        insert_only_tables=(),
        snapshot_connection_opener=open_artifact,
    )
    return not comparison.changed_rows_between(live_path, snapshot_path)


def _uses_sqlcipher(connection: Any) -> bool:
    return type(connection).__module__.split(".", 1)[0] == "sqlcipher3"


def _is_plaintext_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _remove_database_bundle(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"), Path(f"{path}-journal")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def _logical_database_digest(connection: Any) -> str:
    """Hash logical SQLite content without depending on encrypted page bytes."""

    integrity_rows = connection.execute("PRAGMA quick_check").fetchall()
    if integrity_rows != [("ok",)]:
        raise SnapshotConnectionError("History database snapshot failed SQLite integrity checks.")

    digest = hashlib.sha256()
    digest.update(b"isrc-history-logical-database-v1\x00")
    schema_rows = connection.execute("""
        SELECT type, name, tbl_name, COALESCE(sql, '')
        FROM sqlite_master
        ORDER BY type, name, tbl_name, COALESCE(sql, '')
        """).fetchall()
    for schema_row in schema_rows:
        _digest_record(digest, b"schema", tuple(schema_row))

    table_names = sorted(
        str(row[1]) for row in schema_rows if str(row[0]) == "table" and str(row[1])
    )
    for table_name in table_names:
        table_info = connection.execute(
            f"PRAGMA table_xinfo({_quote_identifier(table_name)})"
        ).fetchall()
        _digest_record(digest, b"table", (table_name,))
        for column_info in table_info:
            _digest_record(digest, b"column", tuple(column_info))

        selected_columns = tuple(
            str(row[1]) for row in table_info if len(row) < 7 or int(row[6] or 0) != 1
        )
        if not selected_columns:
            continue
        primary_keys = tuple(
            str(row[1])
            for row in sorted(table_info, key=lambda row: int(row[5] or 0))
            if int(row[5] or 0) > 0 and str(row[1]) in selected_columns
        )
        columns_sql = ", ".join(_quote_identifier(column) for column in selected_columns)
        quoted_table = _quote_identifier(table_name)
        if primary_keys:
            order_sql = ", ".join(_quote_identifier(column) for column in primary_keys)
            rows = connection.execute(
                f"SELECT {columns_sql} FROM {quoted_table} ORDER BY {order_sql}"
            )
            include_rowid = False
        else:
            try:
                rows = connection.execute(
                    f"SELECT rowid, {columns_sql} FROM {quoted_table} ORDER BY rowid"
                )
                include_rowid = True
            except Exception:
                order_sql = ", ".join(_quote_identifier(column) for column in selected_columns)
                rows = connection.execute(
                    f"SELECT {columns_sql} FROM {quoted_table} ORDER BY {order_sql}"
                )
                include_rowid = False
        digest.update(b"rowid\x01" if include_rowid else b"rowid\x00")
        while batch := rows.fetchmany(SnapshotDatabaseService._BATCH_SIZE):
            for row in batch:
                _digest_record(digest, b"row", tuple(row))
    return digest.hexdigest()


def _digest_record(digest: Any, record_type: bytes, values: tuple[Any, ...]) -> None:
    digest.update(len(record_type).to_bytes(2, "big"))
    digest.update(record_type)
    digest.update(len(values).to_bytes(4, "big"))
    for value in values:
        if value is None:
            tag, payload = b"N", b""
        elif isinstance(value, bytes):
            tag, payload = b"B", value
        elif isinstance(value, (bytearray, memoryview)):
            tag, payload = b"B", bytes(value)
        elif isinstance(value, bool):
            tag, payload = b"I", (b"1" if value else b"0")
        elif isinstance(value, int):
            tag, payload = b"I", str(value).encode("ascii")
        elif isinstance(value, float):
            tag, payload = b"F", struct.pack(">d", value)
        else:
            tag, payload = b"T", str(value).encode("utf-8", errors="surrogatepass")
        digest.update(tag)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _table_names(connection: Any) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(row[0]) for row in rows if row and row[0]}


def _table_columns(connection: Any, table_name: str) -> list[tuple[Any, ...]]:
    rows = connection.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
    return [tuple(row) for row in rows]


def _shared_columns(left: Any, right: Any, table_name: str) -> list[str]:
    left_columns = [str(row[1]) for row in _table_columns(left, table_name)]
    right_columns = {str(row[1]) for row in _table_columns(right, table_name)}
    return [column for column in left_columns if column in right_columns]


def _primary_key_columns(connection: Any, table_name: str) -> tuple[str, ...]:
    rows = _table_columns(connection, table_name)
    return tuple(
        str(row[1])
        for row in sorted(rows, key=lambda row: int(row[5] or 0))
        if int(row[5] or 0) > 0
    )


def _tables_equal(left: Any, right: Any, table_name: str) -> bool:
    columns = _shared_columns(left, right, table_name)
    if not columns:
        return True
    quoted_table = _quote_identifier(table_name)
    left_count = int(left.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()[0])
    right_count = int(right.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()[0])
    if left_count != right_count:
        return False
    if left_count == 0:
        return True

    primary_keys = [
        column for column in _primary_key_columns(left, table_name) if column in columns
    ]
    order_columns = primary_keys or columns
    column_sql = ", ".join(_quote_identifier(column) for column in columns)
    order_sql = ", ".join(_quote_identifier(column) for column in order_columns)
    query = f"SELECT {column_sql} FROM {quoted_table} ORDER BY {order_sql}"
    left_rows = left.execute(query)
    right_rows = right.execute(query)
    while True:
        left_batch = left_rows.fetchmany(SnapshotDatabaseService._BATCH_SIZE)
        right_batch = right_rows.fetchmany(SnapshotDatabaseService._BATCH_SIZE)
        if left_batch != right_batch:
            return False
        if not left_batch:
            return True


def _changed_primary_keys(
    left: Any,
    right: Any,
    table_name: str,
    key_columns: tuple[str, ...],
) -> tuple[tuple[Any, ...], ...]:
    columns = tuple(_shared_columns(left, right, table_name))
    if not columns:
        return ()
    key_indexes = tuple(columns.index(column) for column in key_columns)
    left_rows = iter(_ordered_rows(left, table_name, columns, key_columns))
    right_rows = iter(_ordered_rows(right, table_name, columns, key_columns))
    left_row = next(left_rows, None)
    right_row = next(right_rows, None)
    changed: list[tuple[Any, ...]] = []
    while left_row is not None or right_row is not None:
        if left_row is None:
            assert right_row is not None
            changed.append(_row_key(right_row, key_indexes))
            right_row = next(right_rows, None)
            continue
        if right_row is None:
            changed.append(_row_key(left_row, key_indexes))
            left_row = next(left_rows, None)
            continue
        left_key = _row_key(left_row, key_indexes)
        right_key = _row_key(right_row, key_indexes)
        comparison = _compare_keys(left_key, right_key)
        if comparison < 0:
            changed.append(left_key)
            left_row = next(left_rows, None)
        elif comparison > 0:
            changed.append(right_key)
            right_row = next(right_rows, None)
        else:
            if tuple(left_row) != tuple(right_row):
                changed.append(left_key)
            left_row = next(left_rows, None)
            right_row = next(right_rows, None)
    return tuple(changed)


def _ordered_rows(
    connection: Any,
    table_name: str,
    columns: tuple[str, ...],
    key_columns: tuple[str, ...],
) -> Any:
    column_sql = ", ".join(_quote_identifier(column) for column in columns)
    order_sql = ", ".join(f"CAST({_quote_identifier(column)} AS BLOB)" for column in key_columns)
    return connection.execute(
        f"SELECT {column_sql} FROM {_quote_identifier(table_name)} ORDER BY {order_sql}"
    )


def _row_key(row: tuple[Any, ...], key_indexes: tuple[int, ...]) -> tuple[Any, ...]:
    return tuple(row[index] for index in key_indexes)


def _compare_keys(left: tuple[Any, ...], right: tuple[Any, ...]) -> int:
    left_value = tuple(_key_part(value) for value in left)
    right_value = tuple(_key_part(value) for value in right)
    return (left_value > right_value) - (left_value < right_value)


def _key_part(value: Any) -> tuple[int, bytes]:
    if value is None:
        return (0, b"")
    if isinstance(value, bytes):
        return (1, value)
    return (1, str(value).encode("utf-8", errors="surrogatepass"))


def _fetch_snapshot_row(
    connection: Any,
    table_name: str,
    columns: tuple[str, ...],
    key_columns: tuple[str, ...],
    key: tuple[Any, ...],
) -> tuple[Any, ...] | None:
    where_sql = " AND ".join(f"{_quote_identifier(column)} IS ?" for column in key_columns)
    if table_name != "CustomFieldValues" or "CustomFieldDefs" not in _table_names(connection):
        column_sql = ", ".join(_quote_identifier(column) for column in columns)
        row = connection.execute(
            f"SELECT {column_sql} FROM {_quote_identifier(table_name)} WHERE {where_sql}",
            key,
        ).fetchone()
        return tuple(row) if row is not None else None

    blob_types = "('blob_image','blob_audio')"

    def column_expression(column: str) -> str:
        quoted = _quote_identifier(column)
        if column == "blob_value":
            return (
                f"CASE WHEN COALESCE(cfd.field_type, 'text') IN {blob_types} "
                f"THEN cfv.{quoted} ELSE NULL END"
            )
        if column in {"managed_file_path", "storage_mode", "filename", "mime_type"}:
            return (
                f"CASE WHEN COALESCE(cfd.field_type, 'text') IN {blob_types} "
                f"THEN cfv.{quoted} ELSE '' END"
            )
        if column == "size_bytes":
            return (
                f"CASE WHEN COALESCE(cfd.field_type, 'text') IN {blob_types} "
                f"THEN COALESCE(cfv.{quoted}, 0) ELSE 0 END"
            )
        return f"cfv.{quoted}"

    expressions = ", ".join(column_expression(column) for column in columns)
    aliased_where_sql = " AND ".join(
        f"cfv.{_quote_identifier(column)} IS ?" for column in key_columns
    )
    row = connection.execute(
        f"SELECT {expressions} "
        'FROM "CustomFieldValues" cfv '
        'LEFT JOIN "CustomFieldDefs" cfd ON cfd.id = cfv.field_def_id '
        f"WHERE {aliased_where_sql}",
        key,
    ).fetchone()
    return tuple(row) if row is not None else None


def _fetch_live_row(
    connection: Any,
    table_name: str,
    columns: tuple[str, ...],
    key_columns: tuple[str, ...],
    key: tuple[Any, ...],
) -> tuple[Any, ...] | None:
    column_sql = ", ".join(_quote_identifier(column) for column in columns)
    where_sql = " AND ".join(f"{_quote_identifier(column)} IS ?" for column in key_columns)
    row = connection.execute(
        f"SELECT {column_sql} FROM {_quote_identifier(table_name)} WHERE {where_sql}",
        key,
    ).fetchone()
    return tuple(row) if row is not None else None


def _delete_row(
    connection: Any,
    table_name: str,
    key_columns: tuple[str, ...],
    key: tuple[Any, ...],
) -> None:
    where_sql = " AND ".join(f"{_quote_identifier(column)} IS ?" for column in key_columns)
    connection.execute(
        f"DELETE FROM {_quote_identifier(table_name)} WHERE {where_sql}",
        key,
    )


def _insert_row(
    connection: Any,
    table_name: str,
    columns: tuple[str, ...],
    row: tuple[Any, ...],
    *,
    or_ignore: bool = False,
) -> None:
    insert_verb = "INSERT OR IGNORE" if or_ignore else "INSERT"
    column_sql = ", ".join(_quote_identifier(column) for column in columns)
    placeholders = ", ".join("?" for _column in columns)
    connection.execute(
        f"{insert_verb} INTO {_quote_identifier(table_name)} "
        f"({column_sql}) VALUES ({placeholders})",
        row,
    )


def _upsert_mutable_row(
    connection: Any,
    table_name: str,
    plan: _RestorePlan,
    key: tuple[Any, ...],
    target_row: tuple[Any, ...],
) -> None:
    live_row = _fetch_live_row(
        connection,
        table_name,
        plan.columns,
        plan.key_columns,
        key,
    )
    if live_row is None:
        _insert_row(connection, table_name, plan.columns, target_row)
        return
    if live_row == target_row:
        return
    mutable_columns = tuple(column for column in plan.columns if column not in plan.key_columns)
    if not mutable_columns:
        return
    value_by_column = dict(zip(plan.columns, target_row, strict=True))
    set_sql = ", ".join(f"{_quote_identifier(column)}=?" for column in mutable_columns)
    where_sql = " AND ".join(f"{_quote_identifier(column)} IS ?" for column in plan.key_columns)
    connection.execute(
        f"UPDATE {_quote_identifier(table_name)} SET {set_sql} WHERE {where_sql}",
        tuple(value_by_column[column] for column in mutable_columns) + key,
    )


def _merge_monotonic_row(
    connection: Any,
    table_name: str,
    plan: _RestorePlan,
    key: tuple[Any, ...],
    target_row: tuple[Any, ...],
    monotonic_columns: frozenset[str],
) -> None:
    live_row = _fetch_live_row(
        connection,
        table_name,
        plan.columns,
        plan.key_columns,
        key,
    )
    if live_row is None:
        _insert_row(connection, table_name, plan.columns, target_row, or_ignore=True)
        return
    value_by_column = dict(zip(plan.columns, target_row, strict=True))
    selected_columns = tuple(column for column in plan.columns if column in monotonic_columns)
    if not selected_columns:
        return
    set_sql = ", ".join(
        f"{_quote_identifier(column)}=MAX({_quote_identifier(column)}, ?)"
        for column in selected_columns
    )
    where_sql = " AND ".join(f"{_quote_identifier(column)} IS ?" for column in plan.key_columns)
    connection.execute(
        f"UPDATE {_quote_identifier(table_name)} SET {set_sql} WHERE {where_sql}",
        tuple(value_by_column[column] for column in selected_columns) + key,
    )


def _dependency_order(connection: Any, table_names: Iterable[str]) -> tuple[str, ...]:
    remaining = set(table_names)
    dependencies = {
        table_name: {
            str(row[2])
            for row in connection.execute(
                f"PRAGMA foreign_key_list({_quote_identifier(table_name)})"
            ).fetchall()
            if str(row[2]) in remaining and str(row[2]) != table_name
        }
        for table_name in remaining
    }
    ordered: list[str] = []
    while remaining:
        ready = sorted(
            table_name for table_name in remaining if not (dependencies[table_name] & remaining)
        )
        if not ready:
            ready = [sorted(remaining)[0]]
        for table_name in ready:
            ordered.append(table_name)
            remaining.remove(table_name)
    return tuple(ordered)


def _is_conditionally_protected_row(
    connection: Any,
    table_name: str,
    key_columns: tuple[str, ...],
    key: tuple[Any, ...],
) -> bool:
    where_sql = " AND ".join(f"{_quote_identifier(column)} IS ?" for column in key_columns)
    quoted_table = _quote_identifier(table_name)
    if table_name == "Invoices":
        row = connection.execute(
            f"SELECT document_status, invoice_number, invoice_registry_entry_id "
            f"FROM {quoted_table} WHERE {where_sql}",
            key,
        ).fetchone()
        return bool(
            row and (str(row[0] or "") != "draft" or row[1] is not None or row[2] is not None)
        )
    if table_name in {"InvoiceLineItems", "InvoiceVatBreakdown"}:
        row = connection.execute(
            f"SELECT invoice_id FROM {quoted_table} WHERE {where_sql}",
            key,
        ).fetchone()
        if row is None:
            return False
        parent = connection.execute(
            "SELECT document_status FROM Invoices WHERE id=?",
            (row[0],),
        ).fetchone()
        return bool(parent and str(parent[0] or "") != "draft")
    if table_name == "RoyaltyCalculations":
        row = connection.execute(
            f"SELECT status FROM {quoted_table} WHERE {where_sql}",
            key,
        ).fetchone()
        return bool(row and str(row[0] or "") not in {"calculated", "reviewed"})
    if table_name in {"RoyaltyCalculationLines", "RoyaltyCalculationSourceLinks"}:
        row = connection.execute(
            f"SELECT calculation_id FROM {quoted_table} WHERE {where_sql}",
            key,
        ).fetchone()
        if row is None:
            return False
        parent = connection.execute(
            "SELECT status FROM RoyaltyCalculations WHERE id=?",
            (row[0],),
        ).fetchone()
        if parent is None:
            return False
        status = str(parent[0] or "")
        if table_name == "RoyaltyCalculationSourceLinks":
            return status in {"posted", "statement_generated", "paid", "corrected"}
        return status not in {"calculated", "reviewed"}
    return False

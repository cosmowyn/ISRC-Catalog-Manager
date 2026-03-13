"""Database schema bootstrap and migration services."""

from __future__ import annotations

import logging
import mimetypes
import sqlite3
import time
from pathlib import Path
from typing import Callable

from isrc_manager.constants import PROMOTED_CUSTOM_FIELDS, SCHEMA_BASELINE, SCHEMA_TARGET
from isrc_manager.domain.codes import to_compact_isrc


class DatabaseSchemaService:
    """Owns schema initialization and stepwise migrations for a profile database."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        logger: logging.Logger | None = None,
        audit_callback: Callable[[str, str, str | int | None, str | None], None] | None = None,
        audit_commit: Callable[[], None] | None = None,
        data_root: str | Path | None = None,
    ):
        self.conn = conn
        self.cursor = conn.cursor()
        self.logger = logger or logging.getLogger(__name__)
        self.audit_callback = audit_callback
        self.audit_commit = audit_commit
        self.data_root = Path(data_root) if data_root is not None else None

    def _table_columns(self, table_name: str) -> set[str]:
        return {row[1] for row in self.cursor.execute(f"PRAGMA table_info({table_name})").fetchall()}

    def init_db(self) -> None:
        # Core entities
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Artists (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
            """
        )
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_artists_name ON Artists(name)")

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Albums (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL
            )
            """
        )
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_albums_title ON Albums(title)")

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Tracks (
                id INTEGER PRIMARY KEY,
                isrc TEXT NOT NULL,
                isrc_compact TEXT,
                db_entry_date DATE DEFAULT CURRENT_DATE,
                audio_file_path TEXT,
                audio_file_mime_type TEXT,
                audio_file_size_bytes INTEGER NOT NULL DEFAULT 0,
                track_title TEXT NOT NULL,
                catalog_number TEXT,
                album_art_path TEXT,
                album_art_mime_type TEXT,
                album_art_size_bytes INTEGER NOT NULL DEFAULT 0,
                main_artist_id INTEGER NOT NULL,
                buma_work_number TEXT,
                album_id INTEGER,
                release_date DATE,
                track_length_sec INTEGER NOT NULL DEFAULT 0,
                iswc TEXT,
                upc TEXT,
                genre TEXT,
                FOREIGN KEY (main_artist_id) REFERENCES Artists(id) ON DELETE RESTRICT,
                FOREIGN KEY (album_id) REFERENCES Albums(id) ON DELETE SET NULL
            )
            """
        )
        self._ensure_current_track_columns()
        track_columns = self._table_columns("Tracks")
        if "isrc" in track_columns:
            self.cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_isrc_unique ON Tracks(isrc)")
        if "isrc_compact" in track_columns:
            self.cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_isrc_compact_unique ON Tracks(isrc_compact)"
            )
        if "track_title" in track_columns:
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_title ON Tracks(track_title)")
        if "upc" in track_columns:
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_upc ON Tracks(upc)")
        if "genre" in track_columns:
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_genre ON Tracks(genre)")
        if "catalog_number" in track_columns:
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_catalog_number ON Tracks(catalog_number)")
        if "buma_work_number" in track_columns:
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_buma_work_number ON Tracks(buma_work_number)")
        if "db_entry_date" in track_columns:
            self.cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_tracks_db_entry_date_fill_ins
                AFTER INSERT ON Tracks
                FOR EACH ROW
                WHEN NEW.db_entry_date IS NULL OR NEW.db_entry_date = ''
                BEGIN
                    UPDATE Tracks SET db_entry_date = CURRENT_DATE WHERE id = NEW.id;
                END
                """
            )

        # Licenses & Licensees
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Licensees (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Licenses (
                id INTEGER PRIMARY KEY,
                track_id INTEGER NOT NULL,
                licensee_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY(licensee_id) REFERENCES Licensees(id) ON DELETE RESTRICT
            )
            """
        )
        self.cursor.execute(
            """
            CREATE VIEW IF NOT EXISTS vw_Licenses AS
            SELECT l.id,
                lic.name AS licensee,
                t.track_title AS tracktitle,
                l.uploaded_at,
                l.filename,
                l.file_path,
                l.track_id,
                l.licensee_id
            FROM Licenses l
            JOIN Licensees lic ON lic.id = l.licensee_id
            JOIN Tracks t ON t.id = l.track_id
            """
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS TrackArtists (
                track_id INTEGER NOT NULL,
                artist_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'additional',
                PRIMARY KEY (track_id, artist_id, role),
                FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY (artist_id) REFERENCES Artists(id) ON DELETE RESTRICT
            )
            """
        )

        # Custom fields (definitions + values) with type + options
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS CustomFieldDefs (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER,
                field_type TEXT NOT NULL DEFAULT 'text',
                options TEXT
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS CustomFieldValues (
                track_id INTEGER NOT NULL,
                field_def_id INTEGER NOT NULL,
                value TEXT,
                PRIMARY KEY (track_id, field_def_id),
                FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY (field_def_id) REFERENCES CustomFieldDefs(id) ON DELETE CASCADE
            )
            """
        )

        # Settings (single-row)
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS ISRC_Prefix (id INTEGER PRIMARY KEY, prefix TEXT NOT NULL)"
        )
        self.cursor.execute("CREATE TABLE IF NOT EXISTS SENA (id INTEGER PRIMARY KEY, number TEXT)")
        self.cursor.execute("CREATE TABLE IF NOT EXISTS BTW (id INTEGER PRIMARY KEY, nr TEXT)")
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS BUMA_STEMRA (id INTEGER PRIMARY KEY, relatie_nummer TEXT, ipi TEXT)"
        )

        # Audit log (immutable append-only)
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS AuditLog (
                id INTEGER PRIMARY KEY,
                ts TEXT NOT NULL DEFAULT (datetime('now')),
                user TEXT,
                action TEXT NOT NULL,
                entity TEXT,
                ref_id TEXT,
                details TEXT
            )
            """
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS HistoryEntries (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                label TEXT NOT NULL,
                action_type TEXT NOT NULL,
                entity_type TEXT,
                entity_id TEXT,
                reversible INTEGER NOT NULL DEFAULT 1,
                strategy TEXT NOT NULL,
                payload_json TEXT,
                inverse_json TEXT,
                redo_json TEXT,
                snapshot_before_id INTEGER,
                snapshot_after_id INTEGER,
                status TEXT NOT NULL DEFAULT 'applied'
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS HistoryHead (
                id INTEGER PRIMARY KEY CHECK(id=1),
                current_entry_id INTEGER
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS HistorySnapshots (
                id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                kind TEXT NOT NULL,
                label TEXT NOT NULL,
                db_snapshot_path TEXT NOT NULL,
                settings_json TEXT,
                manifest_json TEXT
            )
            """
        )
        self.cursor.execute(
            "INSERT OR IGNORE INTO HistoryHead (id, current_entry_id) VALUES (1, NULL)"
        )

        self.conn.commit()

    def get_db_version(self) -> int:
        row = self.cursor.execute("PRAGMA user_version").fetchone()
        try:
            return int(row[0]) if row and row[0] is not None else 0
        except Exception:
            return 0

    def _set_db_version(self, version: int) -> None:
        self.conn.execute(f"PRAGMA user_version = {version}")

    def _ensure_migration_log(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS _MigrationLog (
                version     INTEGER PRIMARY KEY,
                applied_at  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                notes       TEXT
            )
            """
        )

    def _record_audit(self, action: str, entity: str, ref_id: str | int | None, details: str | None) -> None:
        if self.audit_callback is None:
            return
        try:
            self.audit_callback(action, entity, ref_id, details)
            if self.audit_commit is not None:
                self.audit_commit()
        except Exception:
            pass

    def _apply_migration(self, from_ver: int, func: Callable[[], None]) -> None:
        self.conn.execute("SAVEPOINT mig")
        try:
            func()
            self._set_db_version(from_ver + 1)
            self.cursor.execute(
                "INSERT OR REPLACE INTO _MigrationLog(version, notes) VALUES (?, ?)",
                (from_ver + 1, func.__name__),
            )
            try:
                self.conn.execute("RELEASE SAVEPOINT mig")
            except sqlite3.OperationalError as exc:
                if "no such savepoint" not in str(exc).lower():
                    raise
            self.conn.commit()
            self.logger.info("Applied migration %s->%s (%s)", from_ver, from_ver + 1, func.__name__)
            self._record_audit("MIGRATE", "DB", f"{from_ver}->{from_ver + 1}", func.__name__)
        except Exception:
            try:
                self.conn.execute("ROLLBACK TO SAVEPOINT mig")
                self.conn.execute("RELEASE SAVEPOINT mig")
            except Exception:
                pass
            self.logger.exception("Migration %s->%s failed", from_ver, from_ver + 1)
            raise

    def migrate_schema(self) -> None:
        self._ensure_migration_log()

        version = self.get_db_version()
        if version == 0:
            self._set_db_version(SCHEMA_BASELINE)
            version = SCHEMA_BASELINE
            self.conn.commit()
            self.logger.info("Initialized DB user_version to baseline %s", SCHEMA_BASELINE)

        while version < SCHEMA_TARGET:
            if version == 1:
                self._apply_migration(1, self._mig_1_to_2)
                version = 2
            elif version == 2:
                self._apply_migration(2, self._mig_2_to_3)
                version = 3
            elif version == 3:
                self._apply_migration(3, self._mig_3_to_4)
                version = 4
            elif version == 4:
                self._apply_migration(4, self._mig_4_to_5)
                version = 5
            elif version == 5:
                self._apply_migration(5, self._mig_5_to_6)
                version = 6
            elif version == 6:
                self._apply_migration(6, self._mig_6_to_7)
                version = 7
            elif version == 7:
                self._apply_migration(7, self._mig_7_to_8)
                version = 8
            elif version == 8:
                self._apply_migration(8, self._mig_8_to_9)
                version = 9
            elif version == 9:
                self._apply_migration(9, self._mig_9_to_10)
                version = 10
            elif version == 10:
                self._apply_migration(10, self._mig_10_to_11)
                version = 11
            elif version == 11:
                self._apply_migration(11, self._mig_11_to_12)
                version = 12
            elif version == 12:
                self._apply_migration(12, self._mig_12_to_13)
                version = 13
            elif version == 13:
                self._apply_migration(13, self._mig_13_to_14)
                version = 14
            else:
                self.logger.warning("Unknown migration path from version %s", version)
                break

    def _mig_1_to_2(self) -> None:
        cols = [row[1] for row in self.cursor.execute("PRAGMA table_info(CustomFieldDefs)").fetchall()]
        if "field_type" not in cols:
            self.cursor.execute("ALTER TABLE CustomFieldDefs ADD COLUMN field_type TEXT NOT NULL DEFAULT 'text'")
        if "options" not in cols:
            self.cursor.execute("ALTER TABLE CustomFieldDefs ADD COLUMN options TEXT")

    def _mig_2_to_3(self) -> None:
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_release_date ON Tracks(release_date)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_cfvalues_field ON CustomFieldValues(field_def_id)")

    def _mig_3_to_4(self) -> None:
        cols = [row[1] for row in self.cursor.execute("PRAGMA table_info(Tracks)").fetchall()]
        if "isrc_compact" not in cols:
            self.cursor.execute("ALTER TABLE Tracks ADD COLUMN isrc_compact TEXT")
        for track_id, isrc in self.cursor.execute(
            "SELECT id, isrc FROM Tracks WHERE isrc_compact IS NULL OR isrc_compact = ''"
        ).fetchall():
            self.cursor.execute("UPDATE Tracks SET isrc_compact=? WHERE id=?", (to_compact_isrc(isrc), track_id))
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_isrc_compact_unique ON Tracks(isrc_compact)"
        )

    def _mig_4_to_5(self) -> None:
        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_auditlog_no_update
            BEFORE UPDATE ON AuditLog
            BEGIN
                SELECT RAISE(ABORT, 'AuditLog is append-only (UPDATE forbidden)');
            END
            """
        )
        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_auditlog_no_delete
            BEFORE DELETE ON AuditLog
            BEGIN
                SELECT RAISE(ABORT, 'AuditLog is append-only (DELETE forbidden)');
            END
            """
        )

    def _mig_5_to_6(self) -> None:
        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tracks_isrc_validate_ins
            BEFORE INSERT ON Tracks
            FOR EACH ROW
            WHEN NOT (
                length(replace(replace(upper(NEW.isrc),'-',''),' ',''))=12
                AND replace(upper(NEW.isrc),'-','') GLOB '[A-Z][A-Z][A-Z0-9][A-Z0-9][A-Z0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                AND NEW.isrc_compact = replace(replace(upper(NEW.isrc),'-',''),' ','')
            )
            BEGIN
                SELECT RAISE(ABORT, 'ISRC validation failed');
            END
            """
        )
        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tracks_isrc_validate_upd
            BEFORE UPDATE ON Tracks
            FOR EACH ROW
            WHEN NOT (
                length(replace(replace(upper(NEW.isrc),'-',''),' ',''))=12
                AND replace(upper(NEW.isrc),'-','') GLOB '[A-Z][A-Z][A-Z0-9][A-Z0-9][A-Z0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                AND NEW.isrc_compact = replace(replace(upper(NEW.isrc),'-',''),' ','')
            )
            BEGIN
                SELECT RAISE(ABORT, 'ISRC validation failed');
            END
            """
        )
        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tracks_upc_check_ins
            BEFORE INSERT ON Tracks
            FOR EACH ROW
            WHEN NEW.upc IS NOT NULL AND NEW.upc <> '' AND length(NEW.upc) NOT IN (12,13)
            BEGIN
                SELECT RAISE(ABORT, 'UPC/EAN must be 12 or 13 digits');
            END
            """
        )
        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tracks_upc_check_upd
            BEFORE UPDATE ON Tracks
            FOR EACH ROW
            WHEN NEW.upc IS NOT NULL AND NEW.upc <> '' AND length(NEW.upc) NOT IN (12,13)
            BEGIN
                SELECT RAISE(ABORT, 'UPC/EAN must be 12 or 13 digits');
            END
            """
        )
        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tracks_reldate_check_ins
            BEFORE INSERT ON Tracks
            FOR EACH ROW
            WHEN NEW.release_date IS NOT NULL AND NEW.release_date <> '' AND NEW.release_date NOT GLOB '____-__-__'
            BEGIN
                SELECT RAISE(ABORT, 'release_date must be YYYY-MM-DD');
            END
            """
        )
        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tracks_reldate_check_upd
            BEFORE UPDATE ON Tracks
            FOR EACH ROW
            WHEN NEW.release_date IS NOT NULL AND NEW.release_date <> '' AND NEW.release_date NOT GLOB '____-__-__'
            BEGIN
                SELECT RAISE(ABORT, 'release_date must be YYYY-MM-DD');
            END
            """
        )

    def _mig_6_to_7(self) -> None:
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_tracks_reldate_check_ins")
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_tracks_reldate_check_upd")

        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tracks_reldate_check_ins
            BEFORE INSERT ON Tracks
            FOR EACH ROW
            WHEN NEW.release_date IS NOT NULL
            AND NEW.release_date <> ''
            AND NEW.release_date NOT LIKE '____-__-__'
            BEGIN
                SELECT RAISE(ABORT, 'release_date must be YYYY-MM-DD');
            END
            """
        )

        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tracks_reldate_check_upd
            BEFORE UPDATE ON Tracks
            FOR EACH ROW
            WHEN NEW.release_date IS NOT NULL
            AND NEW.release_date <> ''
            AND NEW.release_date NOT LIKE '____-__-__'
            BEGIN
                SELECT RAISE(ABORT, 'release_date must be YYYY-MM-DD');
            END
            """
        )

    def _mig_7_to_8(self) -> None:
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_tracks_isrc_validate_ins")
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_tracks_isrc_validate_upd")

        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tracks_isrc_validate_ins
            BEFORE INSERT ON Tracks
            FOR EACH ROW
            WHEN NOT (
                length(replace(replace(upper(NEW.isrc),'-',''),' ','')) = 12
                AND replace(replace(upper(NEW.isrc),'-',''),' ','') GLOB
                    '[A-Z][A-Z][A-Z0-9][A-Z0-9][A-Z0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                AND upper(NEW.isrc_compact) = replace(replace(upper(NEW.isrc),'-',''),' ','')
            )
            BEGIN
                SELECT RAISE(ABORT, 'ISRC validation failed');
            END
            """
        )

        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tracks_isrc_validate_upd
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
            END
            """
        )

    def _mig_8_to_9(self) -> None:
        cols = [row[1] for row in self.cursor.execute("PRAGMA table_info(Tracks)").fetchall()]
        if "track_length_sec" not in cols:
            self.cursor.execute("ALTER TABLE Tracks ADD COLUMN track_length_sec INTEGER NOT NULL DEFAULT 0")

    def _mig_9_to_10(self) -> None:
        cols = [row[1] for row in self.cursor.execute("PRAGMA table_info(CustomFieldValues)").fetchall()]
        if "blob_value" not in cols:
            self.cursor.execute("ALTER TABLE CustomFieldValues ADD COLUMN blob_value BLOB")
        if "mime_type" not in cols:
            self.cursor.execute("ALTER TABLE CustomFieldValues ADD COLUMN mime_type TEXT")
        if "size_bytes" not in cols:
            self.cursor.execute("ALTER TABLE CustomFieldValues ADD COLUMN size_bytes INTEGER NOT NULL DEFAULT 0")

        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cfvalues_track_field
            ON CustomFieldValues(track_id, field_def_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cfvalues_field_track
            ON CustomFieldValues(field_def_id, track_id)
            """
        )

        self.cursor.execute("DROP TRIGGER IF EXISTS trg_cfvalues_blob_enforce_ins")
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_cfvalues_blob_enforce_upd")
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_cfvalues_text_enforce_ins")
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_cfvalues_text_enforce_upd")

        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_cfvalues_blob_enforce_ins
            BEFORE INSERT ON CustomFieldValues
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1 FROM CustomFieldDefs d
                WHERE d.id = NEW.field_def_id AND d.field_type IN ('blob_image','blob_audio')
            )
            AND (
                NEW.blob_value IS NULL
                OR NEW.value IS NOT NULL
                OR NEW.size_bytes < 0
            )
            BEGIN
                SELECT RAISE(ABORT, 'BLOB field requires blob_value (and NULL text); size_bytes must be >= 0');
            END
            """
        )
        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_cfvalues_blob_enforce_upd
            BEFORE UPDATE ON CustomFieldValues
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1 FROM CustomFieldDefs d
                WHERE d.id = NEW.field_def_id AND d.field_type IN ('blob_image','blob_audio')
            )
            AND (
                NEW.blob_value IS NULL
                OR NEW.value IS NOT NULL
                OR NEW.size_bytes < 0
            )
            BEGIN
                SELECT RAISE(ABORT, 'BLOB field requires blob_value (and NULL text); size_bytes must be >= 0');
            END
            """
        )

        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_cfvalues_text_enforce_ins
            BEFORE INSERT ON CustomFieldValues
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1 FROM CustomFieldDefs d
                WHERE d.id = NEW.field_def_id AND d.field_type NOT IN ('blob_image','blob_audio')
            )
            AND NEW.blob_value IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'Non-BLOB field must not store blob_value');
            END
            """
        )
        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_cfvalues_text_enforce_upd
            BEFORE UPDATE ON CustomFieldValues
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1 FROM CustomFieldDefs d
                WHERE d.id = NEW.field_def_id AND d.field_type NOT IN ('blob_image','blob_audio')
            )
            AND NEW.blob_value IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'Non-BLOB field must not store blob_value');
            END
            """
        )

    def _mig_10_to_11(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Licensees (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Licenses (
                id INTEGER PRIMARY KEY,
                track_id INTEGER NOT NULL,
                licensee_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY(licensee_id) REFERENCES Licensees(id) ON DELETE RESTRICT
            )
            """
        )
        self.cursor.execute(
            """
            CREATE VIEW IF NOT EXISTS vw_Licenses AS
            SELECT l.id,
                lic.name AS licensee,
                t.track_title AS tracktitle,
                l.uploaded_at,
                l.filename,
                l.file_path,
                l.track_id,
                l.licensee_id
            FROM Licenses l
            JOIN Licensees lic ON lic.id = l.licensee_id
            JOIN Tracks t ON t.id = l.track_id
            """
        )
        self.conn.commit()

    def _mig_11_to_12(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS HistoryEntries (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                label TEXT NOT NULL,
                action_type TEXT NOT NULL,
                entity_type TEXT,
                entity_id TEXT,
                reversible INTEGER NOT NULL DEFAULT 1,
                strategy TEXT NOT NULL,
                payload_json TEXT,
                inverse_json TEXT,
                redo_json TEXT,
                snapshot_before_id INTEGER,
                snapshot_after_id INTEGER,
                status TEXT NOT NULL DEFAULT 'applied'
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS HistoryHead (
                id INTEGER PRIMARY KEY CHECK(id=1),
                current_entry_id INTEGER
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS HistorySnapshots (
                id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                kind TEXT NOT NULL,
                label TEXT NOT NULL,
                db_snapshot_path TEXT NOT NULL,
                settings_json TEXT,
                manifest_json TEXT
            )
            """
        )
        self.cursor.execute(
            "INSERT OR IGNORE INTO HistoryHead (id, current_entry_id) VALUES (1, NULL)"
        )

    def _mig_12_to_13(self) -> None:
        self._ensure_current_track_columns()
        self._migrate_promoted_custom_fields()

    def _mig_13_to_14(self) -> None:
        # Reconcile promoted defaults again for databases that already reached v13
        # before the typed standard-field and legacy-blob cleanup logic was finalized.
        self._ensure_current_track_columns()
        self._migrate_promoted_custom_fields()

    def _ensure_current_track_columns(self) -> None:
        cols = self._table_columns("Tracks")
        additions = (
            ("db_entry_date", "DATE"),
            ("isrc_compact", "TEXT"),
            ("track_length_sec", "INTEGER NOT NULL DEFAULT 0"),
            ("audio_file_path", "TEXT"),
            ("audio_file_mime_type", "TEXT"),
            ("audio_file_size_bytes", "INTEGER NOT NULL DEFAULT 0"),
            ("catalog_number", "TEXT"),
            ("album_art_path", "TEXT"),
            ("album_art_mime_type", "TEXT"),
            ("album_art_size_bytes", "INTEGER NOT NULL DEFAULT 0"),
            ("buma_work_number", "TEXT"),
        )
        for column_name, column_sql in additions:
            if column_name not in cols:
                self.cursor.execute(f"ALTER TABLE Tracks ADD COLUMN {column_name} {column_sql}")
        if "isrc_compact" in self._table_columns("Tracks"):
            for track_id, isrc in self.cursor.execute(
                "SELECT id, isrc FROM Tracks WHERE isrc_compact IS NULL OR isrc_compact = ''"
            ).fetchall():
                self.cursor.execute("UPDATE Tracks SET isrc_compact=? WHERE id=?", (to_compact_isrc(isrc), track_id))
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_catalog_number ON Tracks(catalog_number)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_buma_work_number ON Tracks(buma_work_number)")

    def _migrate_promoted_custom_fields(self) -> None:
        placeholders = ",".join("?" for _ in PROMOTED_CUSTOM_FIELDS)
        defs = self.cursor.execute(
            f"SELECT id, name, field_type FROM CustomFieldDefs WHERE name IN ({placeholders})",
            tuple(field["name"] for field in PROMOTED_CUSTOM_FIELDS),
        ).fetchall()
        if not defs:
            return

        for field_id, name, field_type in defs:
            spec = next((item for item in PROMOTED_CUSTOM_FIELDS if item["name"] == name), None)
            if spec is None:
                continue
            if str(field_type or "").strip().lower() != str(spec["field_type"]).strip().lower():
                continue

            if spec["field_type"] in ("blob_audio", "blob_image"):
                self._migrate_promoted_blob_field(
                    field_id=int(field_id),
                    field_name=name,
                    path_column=spec["path_column"],
                    mime_column=spec["mime_column"],
                    size_column=spec["size_column"],
                )
            else:
                self._migrate_promoted_text_field(
                    field_id=int(field_id),
                    value_column=spec["value_column"],
                )

            self.cursor.execute("DELETE FROM CustomFieldValues WHERE field_def_id=?", (int(field_id),))
            self.cursor.execute("DELETE FROM CustomFieldDefs WHERE id=?", (int(field_id),))

    def _migrate_promoted_text_field(self, *, field_id: int, value_column: str) -> None:
        rows = self.cursor.execute(
            """
            SELECT track_id, value
            FROM CustomFieldValues
            WHERE field_def_id = ?
              AND value IS NOT NULL
            """,
            (int(field_id),),
        ).fetchall()
        for track_id, value in rows:
            if value is None:
                continue
            current = self.cursor.execute(
                f"SELECT {value_column} FROM Tracks WHERE id=?",
                (int(track_id),),
            ).fetchone()
            if not current:
                continue
            if str(current[0] or "").strip():
                continue
            self.cursor.execute(
                f"UPDATE Tracks SET {value_column}=? WHERE id=?",
                (value, int(track_id)),
            )

    def _migrate_promoted_blob_field(
        self,
        *,
        field_id: int,
        field_name: str,
        path_column: str,
        mime_column: str,
        size_column: str,
    ) -> None:
        rows = self.cursor.execute(
            """
            SELECT track_id, blob_value, mime_type, size_bytes
            FROM CustomFieldValues
            WHERE field_def_id = ?
              AND blob_value IS NOT NULL
            """,
            (int(field_id),),
        ).fetchall()
        for track_id, blob_value, mime_type, size_bytes in rows:
            if blob_value is None:
                continue
            current = self.cursor.execute(
                f"SELECT {path_column}, {mime_column}, {size_column} FROM Tracks WHERE id=?",
                (int(track_id),),
            ).fetchone()
            if not current:
                continue
            current_path, current_mime, current_size = current
            if self._stored_media_needs_backfill(current_path):
                stored_path, resolved_mime, resolved_size = self._write_promoted_blob_file(
                    track_id=int(track_id),
                    field_name=field_name,
                    blob_value=blob_value,
                    mime_type=mime_type,
                    size_bytes=size_bytes,
                )
            else:
                stored_path = str(current_path or "")
                resolved_mime = str(current_mime or mime_type or "")
                resolved_size = int(current_size or 0) or int(size_bytes or 0)
            self.cursor.execute(
                f"""
                UPDATE Tracks
                SET {path_column} = ?, {mime_column} = ?, {size_column} = ?
                WHERE id = ?
                """,
                (stored_path, resolved_mime, resolved_size, int(track_id)),
            )

    def _stored_media_needs_backfill(self, stored_path: str | None) -> bool:
        clean_path = str(stored_path or "").strip()
        if not clean_path:
            return True
        path = Path(clean_path)
        if path.is_absolute():
            return not path.exists()
        if self.data_root is None:
            return False
        return not (self.data_root / path).exists()

    def _write_promoted_blob_file(
        self,
        *,
        track_id: int,
        field_name: str,
        blob_value,
        mime_type: str | None,
        size_bytes: int | None,
    ) -> tuple[str, str, int]:
        if self.data_root is None:
            raise ValueError(
                f"Cannot migrate promoted field '{field_name}' without a configured data_root"
            )

        media_kind = "audio" if "audio" in field_name.lower() else "images"
        store_dir = self.data_root / "track_media" / media_kind
        store_dir.mkdir(parents=True, exist_ok=True)

        mime = (mime_type or "").strip()
        ext = mimetypes.guess_extension(mime) if mime else None
        if not ext:
            ext = ".bin"

        filename = f"{int(time.time_ns())}_{track_id}_{field_name.lower().replace(' ', '_').replace('/', '_')}{ext}"
        destination = store_dir / filename
        data = blob_value if isinstance(blob_value, (bytes, bytearray)) else bytes(blob_value)
        destination.write_bytes(data)

        resolved_mime = mime or (mimetypes.guess_type(destination.name)[0] or "")
        resolved_size = int(size_bytes or len(data))
        return str(destination.relative_to(self.data_root)), resolved_mime, resolved_size

"""Database schema bootstrap and migration services."""

from __future__ import annotations

import logging
import mimetypes
import sqlite3
import time
from pathlib import Path
from typing import Callable

from isrc_manager.constants import PROMOTED_CUSTOM_FIELDS, SCHEMA_BASELINE, SCHEMA_TARGET
from isrc_manager.domain.codes import barcode_validation_status, to_compact_isrc
from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
)


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
        return {
            row[1] for row in self.cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
        }

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
                title TEXT NOT NULL,
                album_art_path TEXT,
                album_art_storage_mode TEXT,
                album_art_blob BLOB,
                album_art_filename TEXT,
                album_art_mime_type TEXT,
                album_art_size_bytes INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._ensure_current_album_columns()
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_albums_title ON Albums(title)")

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Tracks (
                id INTEGER PRIMARY KEY,
                isrc TEXT NOT NULL,
                isrc_compact TEXT,
                db_entry_date DATE DEFAULT CURRENT_DATE,
                audio_file_path TEXT,
                audio_file_storage_mode TEXT,
                audio_file_blob BLOB,
                audio_file_filename TEXT,
                audio_file_mime_type TEXT,
                audio_file_size_bytes INTEGER NOT NULL DEFAULT 0,
                track_title TEXT NOT NULL,
                catalog_number TEXT,
                album_art_path TEXT,
                album_art_storage_mode TEXT,
                album_art_blob BLOB,
                album_art_filename TEXT,
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
                composer TEXT,
                publisher TEXT,
                comments TEXT,
                lyrics TEXT,
                FOREIGN KEY (main_artist_id) REFERENCES Artists(id) ON DELETE RESTRICT,
                FOREIGN KEY (album_id) REFERENCES Albums(id) ON DELETE SET NULL
            )
            """
        )
        self._ensure_current_track_columns()
        track_columns = self._table_columns("Tracks")
        self._ensure_optional_isrc_constraints()
        if "track_title" in track_columns:
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracks_title ON Tracks(track_title)"
            )
        if "upc" in track_columns:
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_upc ON Tracks(upc)")
        if "genre" in track_columns:
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_genre ON Tracks(genre)")
        if "catalog_number" in track_columns:
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracks_catalog_number ON Tracks(catalog_number)"
            )
        if "buma_work_number" in track_columns:
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracks_buma_work_number ON Tracks(buma_work_number)"
            )
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
                file_path TEXT,
                filename TEXT NOT NULL,
                storage_mode TEXT,
                file_blob BLOB,
                mime_type TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY(licensee_id) REFERENCES Licensees(id) ON DELETE RESTRICT
            )
            """
        )
        self._ensure_license_columns()
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
                options TEXT,
                blob_icon_payload TEXT
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS CustomFieldValues (
                track_id INTEGER NOT NULL,
                field_def_id INTEGER NOT NULL,
                value TEXT,
                blob_value BLOB,
                managed_file_path TEXT,
                storage_mode TEXT,
                filename TEXT,
                mime_type TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (track_id, field_def_id),
                FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY (field_def_id) REFERENCES CustomFieldDefs(id) ON DELETE CASCADE
            )
            """
        )
        self._ensure_current_custom_field_value_schema()

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
                status TEXT NOT NULL DEFAULT 'applied',
                visible_in_history INTEGER NOT NULL DEFAULT 1
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
            """
            CREATE TABLE IF NOT EXISTS HistoryBackups (
                id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                kind TEXT NOT NULL,
                label TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                source_db_path TEXT,
                metadata_json TEXT
            )
            """
        )
        self.cursor.execute(
            "INSERT OR IGNORE INTO HistoryHead (id, current_entry_id) VALUES (1, NULL)"
        )

        self._ensure_gs1_metadata_table()
        self._ensure_gs1_template_storage_table()
        self._ensure_release_tables()
        self._ensure_repertoire_tables()
        self._ensure_authenticity_tables()
        self._ensure_derivative_export_tables()
        self._ensure_blob_icon_schema()
        self._backfill_dual_storage_defaults()

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

    def _record_audit(
        self, action: str, entity: str, ref_id: str | int | None, details: str | None
    ) -> None:
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
            elif version == 14:
                self._apply_migration(14, self._mig_14_to_15)
                version = 15
            elif version == 15:
                self._apply_migration(15, self._mig_15_to_16)
                version = 16
            elif version == 16:
                self._apply_migration(16, self._mig_16_to_17)
                version = 17
            elif version == 17:
                self._apply_migration(17, self._mig_17_to_18)
                version = 18
            elif version == 18:
                self._apply_migration(18, self._mig_18_to_19)
                version = 19
            elif version == 19:
                self._apply_migration(19, self._mig_19_to_20)
                version = 20
            elif version == 20:
                self._apply_migration(20, self._mig_20_to_21)
                version = 21
            elif version == 21:
                self._apply_migration(21, self._mig_21_to_22)
                version = 22
            elif version == 22:
                self._apply_migration(22, self._mig_22_to_23)
                version = 23
            elif version == 23:
                self._apply_migration(23, self._mig_23_to_24)
                version = 24
            elif version == 24:
                self._apply_migration(24, self._mig_24_to_25)
                version = 25
            elif version == 25:
                self._apply_migration(25, self._mig_25_to_26)
                version = 26
            elif version == 26:
                self._apply_migration(26, self._mig_26_to_27)
                version = 27
            elif version == 27:
                self._apply_migration(27, self._mig_27_to_28)
                version = 28
            else:
                self.logger.warning("Unknown migration path from version %s", version)
                break

    def _mig_1_to_2(self) -> None:
        cols = [
            row[1] for row in self.cursor.execute("PRAGMA table_info(CustomFieldDefs)").fetchall()
        ]
        if "field_type" not in cols:
            self.cursor.execute(
                "ALTER TABLE CustomFieldDefs ADD COLUMN field_type TEXT NOT NULL DEFAULT 'text'"
            )
        if "options" not in cols:
            self.cursor.execute("ALTER TABLE CustomFieldDefs ADD COLUMN options TEXT")

    def _mig_2_to_3(self) -> None:
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tracks_release_date ON Tracks(release_date)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cfvalues_field ON CustomFieldValues(field_def_id)"
        )

    def _mig_3_to_4(self) -> None:
        cols = [row[1] for row in self.cursor.execute("PRAGMA table_info(Tracks)").fetchall()]
        if "isrc_compact" not in cols:
            self.cursor.execute("ALTER TABLE Tracks ADD COLUMN isrc_compact TEXT")
        for track_id, isrc in self.cursor.execute(
            "SELECT id, isrc FROM Tracks WHERE isrc_compact IS NULL OR isrc_compact = ''"
        ).fetchall():
            self.cursor.execute(
                "UPDATE Tracks SET isrc_compact=? WHERE id=?", (to_compact_isrc(isrc), track_id)
            )
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
            self.cursor.execute(
                "ALTER TABLE Tracks ADD COLUMN track_length_sec INTEGER NOT NULL DEFAULT 0"
            )

    def _mig_9_to_10(self) -> None:
        self._ensure_current_custom_field_value_schema()

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
                file_path TEXT,
                filename TEXT NOT NULL,
                storage_mode TEXT,
                file_blob BLOB,
                mime_type TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY(licensee_id) REFERENCES Licensees(id) ON DELETE RESTRICT
            )
            """
        )
        self._ensure_license_columns()
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
                status TEXT NOT NULL DEFAULT 'applied',
                visible_in_history INTEGER NOT NULL DEFAULT 1
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

    def _mig_14_to_15(self) -> None:
        self._ensure_gs1_metadata_table()

    def _mig_15_to_16(self) -> None:
        self._ensure_gs1_metadata_table()

    def _mig_16_to_17(self) -> None:
        self._ensure_current_album_columns()

    def _mig_17_to_18(self) -> None:
        self._ensure_optional_isrc_constraints()

    def _mig_18_to_19(self) -> None:
        self._ensure_current_track_columns()
        self._ensure_release_tables()
        self._migrate_legacy_releases()

    def _mig_19_to_20(self) -> None:
        self._ensure_gs1_template_storage_table()

    def _mig_20_to_21(self) -> None:
        self._ensure_release_tables()
        self._ensure_repertoire_tables()

    def _mig_21_to_22(self) -> None:
        self._ensure_blob_icon_schema()

    def _mig_22_to_23(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS HistoryBackups (
                id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                kind TEXT NOT NULL,
                label TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                source_db_path TEXT,
                metadata_json TEXT
            )
            """
        )

    def _mig_23_to_24(self) -> None:
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
                status TEXT NOT NULL DEFAULT 'applied',
                visible_in_history INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        cols = [
            row[1] for row in self.cursor.execute("PRAGMA table_info(HistoryEntries)").fetchall()
        ]
        if "visible_in_history" not in cols:
            self.cursor.execute(
                "ALTER TABLE HistoryEntries ADD COLUMN visible_in_history INTEGER NOT NULL DEFAULT 1"
            )

    def _mig_24_to_25(self) -> None:
        self._ensure_current_album_columns()
        self._ensure_current_track_columns()
        self._ensure_current_custom_field_value_schema()
        self._ensure_license_columns()
        self._ensure_gs1_template_storage_table()
        self._ensure_release_tables()
        self._ensure_repertoire_tables()
        self._backfill_dual_storage_defaults()

    def _mig_25_to_26(self) -> None:
        self._ensure_authenticity_tables()

    def _mig_26_to_27(self) -> None:
        self._ensure_derivative_export_tables()

    def _mig_27_to_28(self) -> None:
        self._ensure_derivative_export_tables()

    def _ensure_current_custom_field_value_schema(self) -> None:
        cols = self._table_columns("CustomFieldValues")
        additions = (
            ("blob_value", "BLOB"),
            ("managed_file_path", "TEXT"),
            ("storage_mode", "TEXT"),
            ("filename", "TEXT"),
            ("mime_type", "TEXT"),
            ("size_bytes", "INTEGER NOT NULL DEFAULT 0"),
        )
        for column_name, column_sql in additions:
            if column_name not in cols:
                self.cursor.execute(
                    f"ALTER TABLE CustomFieldValues ADD COLUMN {column_name} {column_sql}"
                )

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

        blob_guard = f"""
            CREATE TRIGGER IF NOT EXISTS {{name}}
            BEFORE {{verb}} ON CustomFieldValues
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1 FROM CustomFieldDefs d
                WHERE d.id = NEW.field_def_id AND d.field_type IN ('blob_image','blob_audio')
            )
            AND (
                NEW.value IS NOT NULL
                OR NEW.size_bytes < 0
                OR COALESCE(trim(NEW.storage_mode), '') NOT IN (
                    '',
                    '{STORAGE_MODE_DATABASE}',
                    '{STORAGE_MODE_MANAGED_FILE}'
                )
                OR (
                    COALESCE(trim(NEW.storage_mode), '') = '{STORAGE_MODE_DATABASE}'
                    AND NEW.blob_value IS NULL
                )
                OR (
                    COALESCE(trim(NEW.storage_mode), '') = '{STORAGE_MODE_MANAGED_FILE}'
                    AND COALESCE(trim(NEW.managed_file_path), '') = ''
                )
                OR (
                    COALESCE(trim(NEW.storage_mode), '') = ''
                    AND NEW.blob_value IS NULL
                    AND COALESCE(trim(NEW.managed_file_path), '') = ''
                )
            )
            BEGIN
                SELECT RAISE(ABORT, 'BLOB field requires either blob_value or managed_file_path; size_bytes must be >= 0');
            END
        """
        self.cursor.execute(blob_guard.format(name="trg_cfvalues_blob_enforce_ins", verb="INSERT"))
        self.cursor.execute(blob_guard.format(name="trg_cfvalues_blob_enforce_upd", verb="UPDATE"))

        text_guard = """
            CREATE TRIGGER IF NOT EXISTS {name}
            BEFORE {verb} ON CustomFieldValues
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1 FROM CustomFieldDefs d
                WHERE d.id = NEW.field_def_id AND d.field_type NOT IN ('blob_image','blob_audio')
            )
            AND (
                NEW.blob_value IS NOT NULL
                OR COALESCE(trim(NEW.managed_file_path), '') != ''
                OR COALESCE(trim(NEW.storage_mode), '') != ''
                OR COALESCE(trim(NEW.filename), '') != ''
                OR COALESCE(trim(NEW.mime_type), '') != ''
                OR NEW.size_bytes != 0
            )
            BEGIN
                SELECT RAISE(ABORT, 'Non-BLOB field must not store binary attachment state');
            END
        """
        self.cursor.execute(text_guard.format(name="trg_cfvalues_text_enforce_ins", verb="INSERT"))
        self.cursor.execute(text_guard.format(name="trg_cfvalues_text_enforce_upd", verb="UPDATE"))

    def _ensure_license_columns(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Licenses (
                id INTEGER PRIMARY KEY,
                track_id INTEGER NOT NULL,
                licensee_id INTEGER NOT NULL,
                file_path TEXT,
                filename TEXT NOT NULL,
                storage_mode TEXT,
                file_blob BLOB,
                mime_type TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY(licensee_id) REFERENCES Licensees(id) ON DELETE RESTRICT
            )
            """
        )
        table_info = {
            str(row[1]): row
            for row in self.cursor.execute("PRAGMA table_info(Licenses)").fetchall()
            if row and row[1]
        }
        file_path_info = table_info.get("file_path")
        file_path_notnull = bool(file_path_info and int(file_path_info[3] or 0))
        if file_path_notnull:
            self.cursor.execute("DROP VIEW IF EXISTS vw_Licenses")
            self.cursor.execute("ALTER TABLE Licenses RENAME TO Licenses_legacy")
            self.cursor.execute(
                """
                CREATE TABLE Licenses (
                    id INTEGER PRIMARY KEY,
                    track_id INTEGER NOT NULL,
                    licensee_id INTEGER NOT NULL,
                    file_path TEXT,
                    filename TEXT NOT NULL,
                    storage_mode TEXT,
                    file_blob BLOB,
                    mime_type TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                    FOREIGN KEY(licensee_id) REFERENCES Licensees(id) ON DELETE RESTRICT
                )
                """
            )
            legacy_cols = {
                str(row[1])
                for row in self.cursor.execute("PRAGMA table_info(Licenses_legacy)").fetchall()
                if row and row[1]
            }
            storage_expr = (
                "storage_mode"
                if "storage_mode" in legacy_cols
                else (
                    f"CASE WHEN COALESCE(file_path, '') != '' THEN '{STORAGE_MODE_MANAGED_FILE}' "
                    f"WHEN file_blob IS NOT NULL THEN '{STORAGE_MODE_DATABASE}' ELSE NULL END"
                    if "file_blob" in legacy_cols
                    else (
                        f"CASE WHEN COALESCE(file_path, '') != '' THEN '{STORAGE_MODE_MANAGED_FILE}' "
                        "ELSE NULL END"
                    )
                )
            )
            file_blob_expr = "file_blob" if "file_blob" in legacy_cols else "NULL"
            mime_expr = "mime_type" if "mime_type" in legacy_cols else "NULL"
            size_expr = "size_bytes" if "size_bytes" in legacy_cols else "0"
            self.cursor.execute(
                f"""
                INSERT INTO Licenses (
                    id,
                    track_id,
                    licensee_id,
                    file_path,
                    filename,
                    storage_mode,
                    file_blob,
                    mime_type,
                    size_bytes,
                    uploaded_at
                )
                SELECT
                    id,
                    track_id,
                    licensee_id,
                    file_path,
                    filename,
                    {storage_expr},
                    {file_blob_expr},
                    {mime_expr},
                    {size_expr},
                    uploaded_at
                FROM Licenses_legacy
                """
            )
            self.cursor.execute("DROP TABLE Licenses_legacy")
            table_info = {
                str(row[1]): row
                for row in self.cursor.execute("PRAGMA table_info(Licenses)").fetchall()
                if row and row[1]
            }

        additions = (
            ("storage_mode", "TEXT"),
            ("file_blob", "BLOB"),
            ("mime_type", "TEXT"),
            ("size_bytes", "INTEGER NOT NULL DEFAULT 0"),
        )
        for column_name, column_sql in additions:
            if column_name not in table_info:
                self.cursor.execute(f"ALTER TABLE Licenses ADD COLUMN {column_name} {column_sql}")

        self.cursor.execute("DROP VIEW IF EXISTS vw_Licenses")
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

    def _backfill_storage_fields(
        self,
        *,
        table_name: str,
        id_columns: tuple[str, ...],
        path_column: str,
        storage_mode_column: str,
        filename_column: str | None = None,
        blob_column: str | None = None,
    ) -> None:
        select_parts = [*id_columns, path_column, storage_mode_column]
        if filename_column:
            select_parts.append(filename_column)
        if blob_column:
            select_parts.append(
                f"CASE WHEN {blob_column} IS NOT NULL THEN 1 ELSE 0 END AS has_blob"
            )
        rows = self.cursor.execute(f"SELECT {', '.join(select_parts)} FROM {table_name}").fetchall()
        for row in rows:
            values = list(row)
            row_ids = values[: len(id_columns)]
            offset = len(id_columns)
            stored_path = str(values[offset] or "").strip()
            storage_mode = str(values[offset + 1] or "").strip()
            filename = str(values[offset + 2] or "").strip() if filename_column is not None else ""
            blob_present = bool(values[-1]) if blob_column is not None else False
            updates: dict[str, object] = {}
            if not storage_mode:
                if stored_path:
                    updates[storage_mode_column] = STORAGE_MODE_MANAGED_FILE
                elif blob_present:
                    updates[storage_mode_column] = STORAGE_MODE_DATABASE
            if filename_column and not filename and stored_path:
                updates[filename_column] = Path(stored_path).name
            if not updates:
                continue
            set_sql = ", ".join(f"{column}=?" for column in updates)
            where_sql = " AND ".join(f"{column}=?" for column in id_columns)
            self.cursor.execute(
                f"UPDATE {table_name} SET {set_sql} WHERE {where_sql}",
                [*updates.values(), *row_ids],
            )

    def _backfill_dual_storage_defaults(self) -> None:
        self._backfill_storage_fields(
            table_name="Tracks",
            id_columns=("id",),
            path_column="audio_file_path",
            storage_mode_column="audio_file_storage_mode",
            filename_column="audio_file_filename",
            blob_column="audio_file_blob",
        )
        self._backfill_storage_fields(
            table_name="Tracks",
            id_columns=("id",),
            path_column="album_art_path",
            storage_mode_column="album_art_storage_mode",
            filename_column="album_art_filename",
            blob_column="album_art_blob",
        )
        self._backfill_storage_fields(
            table_name="Albums",
            id_columns=("id",),
            path_column="album_art_path",
            storage_mode_column="album_art_storage_mode",
            filename_column="album_art_filename",
            blob_column="album_art_blob",
        )
        self._backfill_storage_fields(
            table_name="CustomFieldValues",
            id_columns=("track_id", "field_def_id"),
            path_column="managed_file_path",
            storage_mode_column="storage_mode",
            filename_column="filename",
            blob_column="blob_value",
        )
        self._backfill_storage_fields(
            table_name="Licenses",
            id_columns=("id",),
            path_column="file_path",
            storage_mode_column="storage_mode",
            filename_column="filename",
            blob_column="file_blob",
        )
        self._backfill_storage_fields(
            table_name="GS1TemplateStorage",
            id_columns=("id",),
            path_column="managed_file_path",
            storage_mode_column="storage_mode",
            filename_column="filename",
            blob_column="workbook_blob",
        )
        self._backfill_storage_fields(
            table_name="Releases",
            id_columns=("id",),
            path_column="artwork_path",
            storage_mode_column="artwork_storage_mode",
            filename_column="artwork_filename",
            blob_column="artwork_blob",
        )
        self._backfill_storage_fields(
            table_name="ContractDocuments",
            id_columns=("id",),
            path_column="file_path",
            storage_mode_column="storage_mode",
            filename_column="filename",
            blob_column="file_blob",
        )
        self._backfill_storage_fields(
            table_name="AssetVersions",
            id_columns=("id",),
            path_column="stored_path",
            storage_mode_column="storage_mode",
            filename_column="filename",
            blob_column="file_blob",
        )

    def _ensure_current_track_columns(self) -> None:
        cols = self._table_columns("Tracks")
        additions = (
            ("db_entry_date", "DATE"),
            ("isrc_compact", "TEXT"),
            ("track_length_sec", "INTEGER NOT NULL DEFAULT 0"),
            ("audio_file_path", "TEXT"),
            ("audio_file_storage_mode", "TEXT"),
            ("audio_file_blob", "BLOB"),
            ("audio_file_filename", "TEXT"),
            ("audio_file_mime_type", "TEXT"),
            ("audio_file_size_bytes", "INTEGER NOT NULL DEFAULT 0"),
            ("catalog_number", "TEXT"),
            ("album_art_path", "TEXT"),
            ("album_art_storage_mode", "TEXT"),
            ("album_art_blob", "BLOB"),
            ("album_art_filename", "TEXT"),
            ("album_art_mime_type", "TEXT"),
            ("album_art_size_bytes", "INTEGER NOT NULL DEFAULT 0"),
            ("buma_work_number", "TEXT"),
            ("composer", "TEXT"),
            ("publisher", "TEXT"),
            ("comments", "TEXT"),
            ("lyrics", "TEXT"),
            ("repertoire_status", "TEXT"),
            ("metadata_complete", "INTEGER NOT NULL DEFAULT 0"),
            ("contract_signed", "INTEGER NOT NULL DEFAULT 0"),
            ("rights_verified", "INTEGER NOT NULL DEFAULT 0"),
        )
        for column_name, column_sql in additions:
            if column_name not in cols:
                self.cursor.execute(f"ALTER TABLE Tracks ADD COLUMN {column_name} {column_sql}")
        if "isrc_compact" in self._table_columns("Tracks"):
            for track_id, isrc in self.cursor.execute(
                "SELECT id, isrc FROM Tracks WHERE isrc_compact IS NULL OR isrc_compact = ''"
            ).fetchall():
                self.cursor.execute(
                    "UPDATE Tracks SET isrc_compact=? WHERE id=?", (to_compact_isrc(isrc), track_id)
                )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tracks_catalog_number ON Tracks(catalog_number)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tracks_buma_work_number ON Tracks(buma_work_number)"
        )

    def _ensure_optional_isrc_constraints(self) -> None:
        self.cursor.execute("DROP INDEX IF EXISTS idx_tracks_isrc_unique")
        self.cursor.execute("DROP INDEX IF EXISTS idx_tracks_isrc_compact_unique")
        self.cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_isrc_unique
            ON Tracks(isrc)
            WHERE isrc IS NOT NULL AND trim(isrc) != ''
            """
        )
        self.cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_isrc_compact_unique
            ON Tracks(isrc_compact)
            WHERE isrc_compact IS NOT NULL AND trim(isrc_compact) != ''
            """
        )
        self._ensure_optional_isrc_validation_triggers()

    def _ensure_blob_icon_schema(self) -> None:
        cols = self._table_columns("CustomFieldDefs")
        if "blob_icon_payload" not in cols:
            self.cursor.execute("ALTER TABLE CustomFieldDefs ADD COLUMN blob_icon_payload TEXT")

    def _ensure_optional_isrc_validation_triggers(self) -> None:
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_tracks_isrc_validate_ins")
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_tracks_isrc_validate_upd")

        self.cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_tracks_isrc_validate_ins
            BEFORE INSERT ON Tracks
            FOR EACH ROW
            WHEN (
                COALESCE(trim(NEW.isrc), '') <> ''
                OR COALESCE(trim(NEW.isrc_compact), '') <> ''
            )
            AND NOT (
                length(replace(replace(upper(NEW.isrc),'-',''),' ','')) = 12
                AND replace(replace(upper(NEW.isrc),'-',''),' ','') GLOB
                    '[A-Z][A-Z][A-Z0-9][A-Z0-9][A-Z0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                AND upper(COALESCE(NEW.isrc_compact, '')) = replace(replace(upper(NEW.isrc),'-',''),' ','')
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
            WHEN (
                COALESCE(trim(NEW.isrc), '') <> ''
                OR COALESCE(trim(NEW.isrc_compact), '') <> ''
            )
            AND NOT (
                length(replace(replace(upper(NEW.isrc),'-',''),' ','')) = 12
                AND replace(replace(upper(NEW.isrc),'-',''),' ','') GLOB
                    '[A-Z][A-Z][A-Z0-9][A-Z0-9][A-Z0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                AND upper(COALESCE(NEW.isrc_compact, '')) = replace(replace(upper(NEW.isrc),'-',''),' ','')
            )
            BEGIN
                SELECT RAISE(ABORT, 'ISRC validation failed');
            END
            """
        )

    def _ensure_current_album_columns(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Albums (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                album_art_path TEXT,
                album_art_storage_mode TEXT,
                album_art_blob BLOB,
                album_art_filename TEXT,
                album_art_mime_type TEXT,
                album_art_size_bytes INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cols = self._table_columns("Albums")
        additions = (
            ("album_art_path", "TEXT"),
            ("album_art_storage_mode", "TEXT"),
            ("album_art_blob", "BLOB"),
            ("album_art_filename", "TEXT"),
            ("album_art_mime_type", "TEXT"),
            ("album_art_size_bytes", "INTEGER NOT NULL DEFAULT 0"),
        )
        for column_name, column_sql in additions:
            if column_name not in cols:
                self.cursor.execute(f"ALTER TABLE Albums ADD COLUMN {column_name} {column_sql}")

    def _ensure_gs1_metadata_table(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS GS1Metadata (
                id INTEGER PRIMARY KEY,
                track_id INTEGER NOT NULL UNIQUE,
                contract_number TEXT,
                status TEXT NOT NULL DEFAULT 'Concept',
                product_classification TEXT,
                consumer_unit_flag INTEGER NOT NULL DEFAULT 1,
                packaging_type TEXT,
                target_market TEXT,
                language TEXT,
                product_description TEXT,
                brand TEXT,
                subbrand TEXT,
                quantity TEXT NOT NULL DEFAULT '1',
                unit TEXT,
                image_url TEXT,
                notes TEXT,
                export_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE
            )
            """
        )
        cols = self._table_columns("GS1Metadata")
        if "contract_number" not in cols:
            self.cursor.execute("ALTER TABLE GS1Metadata ADD COLUMN contract_number TEXT")
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_gs1_metadata_track_id ON GS1Metadata(track_id)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_gs1_metadata_export_enabled ON GS1Metadata(export_enabled)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_gs1_metadata_contract_number ON GS1Metadata(contract_number)"
        )

    def _ensure_gs1_template_storage_table(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS GS1TemplateStorage (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                filename TEXT NOT NULL,
                source_path TEXT,
                managed_file_path TEXT,
                storage_mode TEXT,
                workbook_blob BLOB,
                mime_type TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        table_info = {
            str(row[1]): row
            for row in self.cursor.execute("PRAGMA table_info(GS1TemplateStorage)").fetchall()
            if row and row[1]
        }
        workbook_blob_info = table_info.get("workbook_blob")
        workbook_blob_notnull = bool(workbook_blob_info and int(workbook_blob_info[3] or 0))
        if workbook_blob_notnull:
            self.cursor.execute(
                "ALTER TABLE GS1TemplateStorage RENAME TO GS1TemplateStorage_legacy"
            )
            self.cursor.execute(
                """
                CREATE TABLE GS1TemplateStorage (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    filename TEXT NOT NULL,
                    source_path TEXT,
                    managed_file_path TEXT,
                    storage_mode TEXT,
                    workbook_blob BLOB,
                    mime_type TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            legacy_cols = {
                str(row[1])
                for row in self.cursor.execute(
                    "PRAGMA table_info(GS1TemplateStorage_legacy)"
                ).fetchall()
                if row and row[1]
            }
            storage_expr = (
                "storage_mode"
                if "storage_mode" in legacy_cols
                else (
                    f"CASE WHEN COALESCE(managed_file_path, '') != '' THEN '{STORAGE_MODE_MANAGED_FILE}' "
                    f"WHEN workbook_blob IS NOT NULL THEN '{STORAGE_MODE_DATABASE}' ELSE NULL END"
                    if "managed_file_path" in legacy_cols
                    else f"CASE WHEN workbook_blob IS NOT NULL THEN '{STORAGE_MODE_DATABASE}' ELSE NULL END"
                )
            )
            managed_path_expr = (
                "managed_file_path" if "managed_file_path" in legacy_cols else "NULL"
            )
            self.cursor.execute(
                f"""
                INSERT INTO GS1TemplateStorage (
                    id,
                    filename,
                    source_path,
                    managed_file_path,
                    storage_mode,
                    workbook_blob,
                    mime_type,
                    size_bytes,
                    created_at,
                    updated_at
                )
                SELECT
                    id,
                    filename,
                    source_path,
                    {managed_path_expr},
                    {storage_expr},
                    workbook_blob,
                    mime_type,
                    size_bytes,
                    created_at,
                    updated_at
                FROM GS1TemplateStorage_legacy
                """
            )
            self.cursor.execute("DROP TABLE GS1TemplateStorage_legacy")
            table_info = {
                str(row[1]): row
                for row in self.cursor.execute("PRAGMA table_info(GS1TemplateStorage)").fetchall()
                if row and row[1]
            }

        additions = (
            ("managed_file_path", "TEXT"),
            ("storage_mode", "TEXT"),
            ("workbook_blob", "BLOB"),
            ("mime_type", "TEXT"),
            ("size_bytes", "INTEGER NOT NULL DEFAULT 0"),
        )
        for column_name, column_sql in additions:
            if column_name not in table_info:
                self.cursor.execute(
                    f"ALTER TABLE GS1TemplateStorage ADD COLUMN {column_name} {column_sql}"
                )

    def _ensure_release_tables(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Releases (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                version_subtitle TEXT,
                primary_artist TEXT,
                album_artist TEXT,
                release_type TEXT NOT NULL DEFAULT 'album',
                release_date TEXT,
                original_release_date TEXT,
                label TEXT,
                sublabel TEXT,
                catalog_number TEXT,
                upc TEXT,
                barcode_validation_status TEXT NOT NULL DEFAULT 'missing',
                territory TEXT,
                explicit_flag INTEGER NOT NULL DEFAULT 0,
                release_notes TEXT,
                artwork_path TEXT,
                artwork_storage_mode TEXT,
                artwork_blob BLOB,
                artwork_filename TEXT,
                artwork_mime_type TEXT,
                artwork_size_bytes INTEGER NOT NULL DEFAULT 0,
                profile_name TEXT,
                repertoire_status TEXT,
                metadata_complete INTEGER NOT NULL DEFAULT 0,
                contract_signed INTEGER NOT NULL DEFAULT 0,
                rights_verified INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        release_columns = self._table_columns("Releases")
        release_additions = (
            ("artwork_storage_mode", "TEXT"),
            ("artwork_blob", "BLOB"),
            ("artwork_filename", "TEXT"),
            ("repertoire_status", "TEXT"),
            ("metadata_complete", "INTEGER NOT NULL DEFAULT 0"),
            ("contract_signed", "INTEGER NOT NULL DEFAULT 0"),
            ("rights_verified", "INTEGER NOT NULL DEFAULT 0"),
        )
        for column_name, column_sql in release_additions:
            if column_name not in release_columns:
                self.cursor.execute(f"ALTER TABLE Releases ADD COLUMN {column_name} {column_sql}")
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ReleaseTracks (
                release_id INTEGER NOT NULL,
                track_id INTEGER NOT NULL,
                disc_number INTEGER NOT NULL DEFAULT 1,
                track_number INTEGER NOT NULL DEFAULT 1,
                sequence_number INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (release_id, track_id),
                FOREIGN KEY (release_id) REFERENCES Releases(id) ON DELETE CASCADE,
                FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE
            )
            """
        )
        self.cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_release_tracks_order_unique
            ON ReleaseTracks(release_id, disc_number, track_number)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_release_tracks_track
            ON ReleaseTracks(track_id)
            """
        )
        # Older builds enforced release UPC uniqueness at the DB level, which makes
        # legacy migrations fail when historical data legitimately reuses a UPC.
        # Keep UPC indexed for lookups, but detect duplicates in validation/dashboard
        # instead of aborting schema upgrades.
        self.cursor.execute("DROP INDEX IF EXISTS idx_releases_upc_unique")
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_releases_upc
            ON Releases(upc)
            WHERE upc IS NOT NULL AND trim(upc) != ''
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_releases_catalog_number
            ON Releases(catalog_number)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_releases_release_date
            ON Releases(release_date)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_releases_title
            ON Releases(title)
            """
        )

    def _ensure_repertoire_tables(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Parties (
                id INTEGER PRIMARY KEY,
                legal_name TEXT NOT NULL,
                display_name TEXT,
                party_type TEXT NOT NULL DEFAULT 'organization',
                contact_person TEXT,
                email TEXT,
                phone TEXT,
                website TEXT,
                address_line1 TEXT,
                address_line2 TEXT,
                city TEXT,
                region TEXT,
                postal_code TEXT,
                country TEXT,
                tax_id TEXT,
                vat_number TEXT,
                pro_affiliation TEXT,
                ipi_cae TEXT,
                notes TEXT,
                profile_name TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_parties_legal_name ON Parties(legal_name)"
        )
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_parties_email ON Parties(email)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_parties_ipi_cae ON Parties(ipi_cae)")

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Works (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                alternate_titles TEXT,
                version_subtitle TEXT,
                language TEXT,
                lyrics_flag INTEGER NOT NULL DEFAULT 0,
                instrumental_flag INTEGER NOT NULL DEFAULT 0,
                genre_notes TEXT,
                iswc TEXT,
                registration_number TEXT,
                work_status TEXT,
                metadata_complete INTEGER NOT NULL DEFAULT 0,
                contract_signed INTEGER NOT NULL DEFAULT 0,
                rights_verified INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                profile_name TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_works_title ON Works(title)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_works_iswc ON Works(iswc)")
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS WorkContributors (
                id INTEGER PRIMARY KEY,
                work_id INTEGER NOT NULL,
                party_id INTEGER,
                display_name TEXT,
                role TEXT NOT NULL,
                share_percent REAL,
                role_share_percent REAL,
                notes TEXT,
                FOREIGN KEY (work_id) REFERENCES Works(id) ON DELETE CASCADE,
                FOREIGN KEY (party_id) REFERENCES Parties(id) ON DELETE SET NULL
            )
            """
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_contributors_work_id ON WorkContributors(work_id)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_contributors_party_id ON WorkContributors(party_id)"
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS WorkTrackLinks (
                work_id INTEGER NOT NULL,
                track_id INTEGER NOT NULL,
                is_primary INTEGER NOT NULL DEFAULT 1,
                notes TEXT,
                PRIMARY KEY (work_id, track_id),
                FOREIGN KEY (work_id) REFERENCES Works(id) ON DELETE CASCADE,
                FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE
            )
            """
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_track_links_track_id ON WorkTrackLinks(track_id)"
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Contracts (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                contract_type TEXT,
                draft_date TEXT,
                signature_date TEXT,
                effective_date TEXT,
                start_date TEXT,
                end_date TEXT,
                renewal_date TEXT,
                notice_deadline TEXT,
                option_periods TEXT,
                reversion_date TEXT,
                termination_date TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                supersedes_contract_id INTEGER,
                superseded_by_contract_id INTEGER,
                summary TEXT,
                notes TEXT,
                profile_name TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (supersedes_contract_id) REFERENCES Contracts(id) ON DELETE SET NULL,
                FOREIGN KEY (superseded_by_contract_id) REFERENCES Contracts(id) ON DELETE SET NULL
            )
            """
        )
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_contracts_status ON Contracts(status)")
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_contracts_notice_deadline ON Contracts(notice_deadline)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_contracts_end_date ON Contracts(end_date)"
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ContractParties (
                contract_id INTEGER NOT NULL,
                party_id INTEGER NOT NULL,
                role_label TEXT NOT NULL DEFAULT 'counterparty',
                is_primary INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                PRIMARY KEY (contract_id, party_id, role_label),
                FOREIGN KEY (contract_id) REFERENCES Contracts(id) ON DELETE CASCADE,
                FOREIGN KEY (party_id) REFERENCES Parties(id) ON DELETE CASCADE
            )
            """
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_contract_parties_party_id ON ContractParties(party_id)"
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ContractObligations (
                id INTEGER PRIMARY KEY,
                contract_id INTEGER NOT NULL,
                obligation_type TEXT NOT NULL,
                title TEXT NOT NULL,
                due_date TEXT,
                follow_up_date TEXT,
                reminder_date TEXT,
                completed INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                notes TEXT,
                FOREIGN KEY (contract_id) REFERENCES Contracts(id) ON DELETE CASCADE
            )
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contract_obligations_due_date
            ON ContractObligations(due_date)
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ContractDocuments (
                id INTEGER PRIMARY KEY,
                contract_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                document_type TEXT NOT NULL DEFAULT 'other',
                version_label TEXT,
                created_date TEXT,
                received_date TEXT,
                signed_status TEXT,
                signed_by_all_parties INTEGER NOT NULL DEFAULT 0,
                active_flag INTEGER NOT NULL DEFAULT 0,
                supersedes_document_id INTEGER,
                superseded_by_document_id INTEGER,
                file_path TEXT,
                filename TEXT,
                storage_mode TEXT,
                file_blob BLOB,
                checksum_sha256 TEXT,
                notes TEXT,
                uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (contract_id) REFERENCES Contracts(id) ON DELETE CASCADE,
                FOREIGN KEY (supersedes_document_id) REFERENCES ContractDocuments(id) ON DELETE SET NULL,
                FOREIGN KEY (superseded_by_document_id) REFERENCES ContractDocuments(id) ON DELETE SET NULL
            )
            """
        )
        contract_document_columns = self._table_columns("ContractDocuments")
        for column_name, column_sql in (
            ("storage_mode", "TEXT"),
            ("file_blob", "BLOB"),
        ):
            if column_name not in contract_document_columns:
                self.cursor.execute(
                    f"ALTER TABLE ContractDocuments ADD COLUMN {column_name} {column_sql}"
                )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contract_documents_contract_id
            ON ContractDocuments(contract_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contract_documents_active_flag
            ON ContractDocuments(active_flag)
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ContractWorkLinks (
                contract_id INTEGER NOT NULL,
                work_id INTEGER NOT NULL,
                PRIMARY KEY (contract_id, work_id),
                FOREIGN KEY (contract_id) REFERENCES Contracts(id) ON DELETE CASCADE,
                FOREIGN KEY (work_id) REFERENCES Works(id) ON DELETE CASCADE
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ContractTrackLinks (
                contract_id INTEGER NOT NULL,
                track_id INTEGER NOT NULL,
                PRIMARY KEY (contract_id, track_id),
                FOREIGN KEY (contract_id) REFERENCES Contracts(id) ON DELETE CASCADE,
                FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ContractReleaseLinks (
                contract_id INTEGER NOT NULL,
                release_id INTEGER NOT NULL,
                PRIMARY KEY (contract_id, release_id),
                FOREIGN KEY (contract_id) REFERENCES Contracts(id) ON DELETE CASCADE,
                FOREIGN KEY (release_id) REFERENCES Releases(id) ON DELETE CASCADE
            )
            """
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS RightsRecords (
                id INTEGER PRIMARY KEY,
                title TEXT,
                right_type TEXT NOT NULL,
                exclusive_flag INTEGER NOT NULL DEFAULT 0,
                territory TEXT,
                media_use_type TEXT,
                start_date TEXT,
                end_date TEXT,
                perpetual_flag INTEGER NOT NULL DEFAULT 0,
                granted_by_party_id INTEGER,
                granted_to_party_id INTEGER,
                retained_by_party_id INTEGER,
                source_contract_id INTEGER,
                work_id INTEGER,
                track_id INTEGER,
                release_id INTEGER,
                notes TEXT,
                profile_name TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (granted_by_party_id) REFERENCES Parties(id) ON DELETE SET NULL,
                FOREIGN KEY (granted_to_party_id) REFERENCES Parties(id) ON DELETE SET NULL,
                FOREIGN KEY (retained_by_party_id) REFERENCES Parties(id) ON DELETE SET NULL,
                FOREIGN KEY (source_contract_id) REFERENCES Contracts(id) ON DELETE SET NULL,
                FOREIGN KEY (work_id) REFERENCES Works(id) ON DELETE CASCADE,
                FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY (release_id) REFERENCES Releases(id) ON DELETE CASCADE
            )
            """
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_rights_work_id ON RightsRecords(work_id)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_rights_track_id ON RightsRecords(track_id)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_rights_release_id ON RightsRecords(release_id)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_rights_source_contract_id ON RightsRecords(source_contract_id)"
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS AssetVersions (
                id INTEGER PRIMARY KEY,
                track_id INTEGER,
                release_id INTEGER,
                asset_type TEXT NOT NULL,
                filename TEXT NOT NULL,
                stored_path TEXT,
                storage_mode TEXT,
                file_blob BLOB,
                checksum_sha256 TEXT,
                duration_sec INTEGER,
                sample_rate INTEGER,
                bit_depth INTEGER,
                format TEXT,
                derived_from_asset_id INTEGER,
                approved_for_use INTEGER NOT NULL DEFAULT 0,
                primary_flag INTEGER NOT NULL DEFAULT 0,
                version_status TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY (release_id) REFERENCES Releases(id) ON DELETE CASCADE,
                FOREIGN KEY (derived_from_asset_id) REFERENCES AssetVersions(id) ON DELETE SET NULL
            )
            """
        )
        asset_columns = self._table_columns("AssetVersions")
        for column_name, column_sql in (
            ("storage_mode", "TEXT"),
            ("file_blob", "BLOB"),
        ):
            if column_name not in asset_columns:
                self.cursor.execute(
                    f"ALTER TABLE AssetVersions ADD COLUMN {column_name} {column_sql}"
                )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_asset_versions_track_id ON AssetVersions(track_id)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_asset_versions_release_id ON AssetVersions(release_id)"
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_asset_versions_primary_flag
            ON AssetVersions(primary_flag)
            """
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS SavedSearches (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                query_text TEXT NOT NULL,
                entity_types TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_saved_searches_name ON SavedSearches(name)"
        )

    def _ensure_authenticity_tables(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS AuthenticityKeys (
                key_id TEXT PRIMARY KEY,
                algorithm TEXT NOT NULL DEFAULT 'ed25519',
                signer_label TEXT,
                public_key_b64 TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                retired_at TEXT,
                notes TEXT
            )
            """
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_authenticity_keys_created_at ON AuthenticityKeys(created_at)"
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS AuthenticityManifests (
                id INTEGER PRIMARY KEY,
                track_id INTEGER NOT NULL,
                reference_asset_id INTEGER,
                key_id TEXT NOT NULL,
                manifest_schema_version INTEGER NOT NULL DEFAULT 1,
                watermark_version INTEGER NOT NULL DEFAULT 1,
                manifest_id TEXT NOT NULL,
                watermark_id INTEGER NOT NULL,
                watermark_nonce INTEGER NOT NULL,
                manifest_digest_prefix TEXT NOT NULL,
                payload_canonical TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                signature_b64 TEXT NOT NULL,
                reference_audio_sha256 TEXT NOT NULL,
                reference_fingerprint_b64 TEXT NOT NULL,
                reference_source_kind TEXT NOT NULL,
                embed_settings_json TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                revoked_at TEXT,
                FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY (reference_asset_id) REFERENCES AssetVersions(id) ON DELETE SET NULL,
                FOREIGN KEY (key_id) REFERENCES AuthenticityKeys(key_id) ON DELETE RESTRICT
            )
            """
        )
        self.cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_authenticity_manifests_manifest_id
            ON AuthenticityManifests(manifest_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_authenticity_manifests_track_id
            ON AuthenticityManifests(track_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_authenticity_manifests_watermark_id
            ON AuthenticityManifests(watermark_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_authenticity_manifests_key_id
            ON AuthenticityManifests(key_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_authenticity_manifests_payload_sha256
            ON AuthenticityManifests(payload_sha256)
            """
        )

    def _ensure_derivative_export_tables(self) -> None:
        # This ledger is only for managed catalog derivatives and managed authenticity exports.
        # External utility conversions stay outside these tables.
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS DerivativeExportBatches (
                id INTEGER PRIMARY KEY,
                batch_id TEXT NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                workflow_kind TEXT NOT NULL DEFAULT 'managed_audio_derivative',
                derivative_kind TEXT NOT NULL DEFAULT 'unclassified',
                authenticity_basis TEXT NOT NULL DEFAULT 'none',
                package_mode TEXT NOT NULL DEFAULT 'directory',
                output_format TEXT,
                zip_filename TEXT,
                profile_name TEXT,
                app_version TEXT,
                recipe_canonical TEXT NOT NULL,
                recipe_sha256 TEXT NOT NULL,
                requested_count INTEGER NOT NULL DEFAULT 0,
                exported_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
            )
            """
        )
        batch_columns = self._table_columns("DerivativeExportBatches")
        for column_name, column_sql in (
            ("schema_version", "INTEGER NOT NULL DEFAULT 1"),
            ("workflow_kind", "TEXT NOT NULL DEFAULT 'managed_audio_derivative'"),
            ("derivative_kind", "TEXT NOT NULL DEFAULT 'unclassified'"),
            ("authenticity_basis", "TEXT NOT NULL DEFAULT 'none'"),
            ("package_mode", "TEXT NOT NULL DEFAULT 'directory'"),
            ("output_format", "TEXT"),
            ("zip_filename", "TEXT"),
            ("profile_name", "TEXT"),
            ("app_version", "TEXT"),
            ("recipe_canonical", "TEXT NOT NULL DEFAULT '{}'"),
            ("recipe_sha256", "TEXT NOT NULL DEFAULT ''"),
            ("requested_count", "INTEGER NOT NULL DEFAULT 0"),
            ("exported_count", "INTEGER NOT NULL DEFAULT 0"),
            ("skipped_count", "INTEGER NOT NULL DEFAULT 0"),
            ("created_at", "TEXT"),
            ("completed_at", "TEXT"),
            ("status", "TEXT NOT NULL DEFAULT 'pending'"),
        ):
            if column_name not in batch_columns:
                self.cursor.execute(
                    f"ALTER TABLE DerivativeExportBatches ADD COLUMN {column_name} {column_sql}"
                )
        self.cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_derivative_export_batches_batch_id
            ON DerivativeExportBatches(batch_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_derivative_export_batches_created_at
            ON DerivativeExportBatches(created_at)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_derivative_export_batches_status
            ON DerivativeExportBatches(status)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_derivative_export_batches_workflow_kind
            ON DerivativeExportBatches(workflow_kind)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_derivative_export_batches_derivative_kind
            ON DerivativeExportBatches(derivative_kind)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_derivative_export_batches_authenticity_basis
            ON DerivativeExportBatches(authenticity_basis)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_derivative_export_batches_recipe_sha256
            ON DerivativeExportBatches(recipe_sha256)
            """
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS TrackAudioDerivatives (
                id INTEGER PRIMARY KEY,
                export_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                track_id INTEGER NOT NULL,
                sequence_no INTEGER NOT NULL DEFAULT 1,
                target_key TEXT NOT NULL,
                workflow_kind TEXT NOT NULL DEFAULT 'managed_audio_derivative',
                derivative_kind TEXT NOT NULL DEFAULT 'unclassified',
                authenticity_basis TEXT NOT NULL DEFAULT 'none',
                source_kind TEXT NOT NULL,
                source_lineage_ref TEXT,
                source_asset_id INTEGER,
                source_audio_sha256 TEXT NOT NULL,
                source_storage_mode TEXT,
                derivative_asset_id INTEGER,
                parent_manifest_id TEXT,
                derivative_manifest_id TEXT,
                output_format TEXT NOT NULL,
                output_suffix TEXT NOT NULL,
                output_mime_type TEXT,
                output_filename TEXT NOT NULL,
                filename_hash_suffix TEXT NOT NULL,
                watermark_applied INTEGER NOT NULL DEFAULT 0,
                metadata_embedded INTEGER NOT NULL DEFAULT 0,
                output_sha256 TEXT,
                output_size_bytes INTEGER NOT NULL DEFAULT 0,
                managed_file_path TEXT,
                sidecar_path TEXT,
                sidecar_sha256 TEXT,
                package_member_path TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error_text TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (batch_id) REFERENCES DerivativeExportBatches(batch_id) ON DELETE CASCADE,
                FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY (source_asset_id) REFERENCES AssetVersions(id) ON DELETE SET NULL,
                FOREIGN KEY (derivative_asset_id) REFERENCES AssetVersions(id) ON DELETE SET NULL
            )
            """
        )
        derivative_columns = self._table_columns("TrackAudioDerivatives")
        for column_name, column_sql in (
            ("export_id", "TEXT NOT NULL DEFAULT ''"),
            ("batch_id", "TEXT NOT NULL DEFAULT ''"),
            ("track_id", "INTEGER NOT NULL DEFAULT 0"),
            ("sequence_no", "INTEGER NOT NULL DEFAULT 1"),
            ("target_key", "TEXT NOT NULL DEFAULT ''"),
            ("workflow_kind", "TEXT NOT NULL DEFAULT 'managed_audio_derivative'"),
            ("derivative_kind", "TEXT NOT NULL DEFAULT 'unclassified'"),
            ("authenticity_basis", "TEXT NOT NULL DEFAULT 'none'"),
            ("source_kind", "TEXT NOT NULL DEFAULT ''"),
            ("source_lineage_ref", "TEXT"),
            ("source_asset_id", "INTEGER"),
            ("source_audio_sha256", "TEXT NOT NULL DEFAULT ''"),
            ("source_storage_mode", "TEXT"),
            ("derivative_asset_id", "INTEGER"),
            ("parent_manifest_id", "TEXT"),
            ("derivative_manifest_id", "TEXT"),
            ("output_format", "TEXT NOT NULL DEFAULT ''"),
            ("output_suffix", "TEXT NOT NULL DEFAULT ''"),
            ("output_mime_type", "TEXT"),
            ("output_filename", "TEXT NOT NULL DEFAULT ''"),
            ("filename_hash_suffix", "TEXT NOT NULL DEFAULT ''"),
            ("watermark_applied", "INTEGER NOT NULL DEFAULT 0"),
            ("metadata_embedded", "INTEGER NOT NULL DEFAULT 0"),
            ("output_sha256", "TEXT"),
            ("output_size_bytes", "INTEGER NOT NULL DEFAULT 0"),
            ("managed_file_path", "TEXT"),
            ("sidecar_path", "TEXT"),
            ("sidecar_sha256", "TEXT"),
            ("package_member_path", "TEXT"),
            ("status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("error_text", "TEXT"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ):
            if column_name not in derivative_columns:
                self.cursor.execute(
                    f"ALTER TABLE TrackAudioDerivatives ADD COLUMN {column_name} {column_sql}"
                )
        self.cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_track_audio_derivatives_export_id
            ON TrackAudioDerivatives(export_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_track_audio_derivatives_batch_id
            ON TrackAudioDerivatives(batch_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_track_audio_derivatives_track_id
            ON TrackAudioDerivatives(track_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_track_audio_derivatives_workflow_kind
            ON TrackAudioDerivatives(workflow_kind)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_track_audio_derivatives_derivative_kind
            ON TrackAudioDerivatives(derivative_kind)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_track_audio_derivatives_authenticity_basis
            ON TrackAudioDerivatives(authenticity_basis)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_track_audio_derivatives_source_asset_id
            ON TrackAudioDerivatives(source_asset_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_track_audio_derivatives_derivative_asset_id
            ON TrackAudioDerivatives(derivative_asset_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_track_audio_derivatives_parent_manifest_id
            ON TrackAudioDerivatives(parent_manifest_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_track_audio_derivatives_derivative_manifest_id
            ON TrackAudioDerivatives(derivative_manifest_id)
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_track_audio_derivatives_output_sha256
            ON TrackAudioDerivatives(output_sha256)
            """
        )

    def _migrate_legacy_releases(self) -> None:
        tables = {
            row[0]
            for row in self.cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "Tracks" not in tables or "Artists" not in tables:
            return
        existing = self.cursor.execute("SELECT COUNT(*) FROM Releases").fetchone()
        if existing and int(existing[0] or 0) > 0:
            return

        rows = self.cursor.execute(
            """
            SELECT
                t.id,
                t.track_title,
                COALESCE(a.name, '') AS artist_name,
                COALESCE(al.id, 0) AS album_id,
                COALESCE(al.title, '') AS album_title,
                COALESCE(t.release_date, '') AS release_date,
                COALESCE(t.upc, '') AS upc,
                COALESCE(t.catalog_number, '') AS catalog_number,
                COALESCE(al.album_art_path, '') AS album_art_path,
                COALESCE(al.album_art_mime_type, '') AS album_art_mime_type,
                COALESCE(al.album_art_size_bytes, 0) AS album_art_size_bytes,
                COALESCE(t.album_art_path, '') AS track_album_art_path,
                COALESCE(t.album_art_mime_type, '') AS track_album_art_mime_type,
                COALESCE(t.album_art_size_bytes, 0) AS track_album_art_size_bytes
            FROM Tracks t
            LEFT JOIN Artists a ON a.id = t.main_artist_id
            LEFT JOIN Albums al ON al.id = t.album_id
            ORDER BY t.id
            """
        ).fetchall()
        if not rows:
            return

        grouped: dict[tuple[str, str, str, str, str], list[tuple]] = {}
        single_rows: list[tuple] = []
        for row in rows:
            clean_album_title = str(row[4] or "").strip()
            if clean_album_title and clean_album_title.casefold() != "single":
                group_key = (
                    str(row[3] or 0),
                    clean_album_title.casefold(),
                    str(row[2] or "").strip().casefold(),
                    str(row[6] or "").strip(),
                    str(row[7] or "").strip(),
                )
                grouped.setdefault(group_key, []).append(row)
            elif (
                str(row[6] or "").strip() or str(row[7] or "").strip() or str(row[5] or "").strip()
            ):
                single_rows.append(row)

        for group_rows in grouped.values():
            first = group_rows[0]
            title = str(first[4] or "").strip()
            artist_name = str(first[2] or "").strip() or None
            upc = str(first[6] or "").strip() or None
            catalog_number = str(first[7] or "").strip() or None
            release_date = str(first[5] or "").strip() or None
            artwork_path = str(first[8] or "").strip() or str(first[11] or "").strip() or None
            artwork_mime = str(first[9] or "").strip() or str(first[12] or "").strip() or None
            artwork_size = int(first[10] or 0) or int(first[13] or 0)
            track_count = len(group_rows)
            release_type = "album" if track_count >= 7 else ("ep" if track_count >= 2 else "single")
            self.cursor.execute(
                """
                INSERT INTO Releases (
                    title,
                    primary_artist,
                    album_artist,
                    release_type,
                    release_date,
                    catalog_number,
                    upc,
                    barcode_validation_status,
                    artwork_path,
                    artwork_mime_type,
                    artwork_size_bytes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    artist_name,
                    artist_name,
                    release_type,
                    release_date,
                    catalog_number,
                    upc,
                    barcode_validation_status(upc),
                    artwork_path,
                    artwork_mime,
                    artwork_size,
                ),
            )
            release_id = int(self.cursor.lastrowid)
            for sequence_number, group_row in enumerate(group_rows, start=1):
                self.cursor.execute(
                    """
                    INSERT OR IGNORE INTO ReleaseTracks (
                        release_id,
                        track_id,
                        disc_number,
                        track_number,
                        sequence_number
                    )
                    VALUES (?, ?, 1, ?, ?)
                    """,
                    (release_id, int(group_row[0]), sequence_number, sequence_number),
                )

        for row in single_rows:
            title = str(row[4] or "").strip() or str(row[1] or "").strip()
            artist_name = str(row[2] or "").strip() or None
            upc = str(row[6] or "").strip() or None
            catalog_number = str(row[7] or "").strip() or None
            release_date = str(row[5] or "").strip() or None
            artwork_path = str(row[11] or "").strip() or str(row[8] or "").strip() or None
            artwork_mime = str(row[12] or "").strip() or str(row[9] or "").strip() or None
            artwork_size = int(row[13] or 0) or int(row[10] or 0)
            self.cursor.execute(
                """
                INSERT INTO Releases (
                    title,
                    primary_artist,
                    album_artist,
                    release_type,
                    release_date,
                    catalog_number,
                    upc,
                    barcode_validation_status,
                    artwork_path,
                    artwork_mime_type,
                    artwork_size_bytes
                )
                VALUES (?, ?, ?, 'single', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    artist_name,
                    artist_name,
                    release_date,
                    catalog_number,
                    upc,
                    barcode_validation_status(upc),
                    artwork_path,
                    artwork_mime,
                    artwork_size,
                ),
            )
            release_id = int(self.cursor.lastrowid)
            self.cursor.execute(
                """
                INSERT OR IGNORE INTO ReleaseTracks (
                    release_id,
                    track_id,
                    disc_number,
                    track_number,
                    sequence_number
                )
                VALUES (?, ?, 1, 1, 1)
                """,
                (release_id, int(row[0])),
            )

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

            self.cursor.execute(
                "DELETE FROM CustomFieldValues WHERE field_def_id=?", (int(field_id),)
            )
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

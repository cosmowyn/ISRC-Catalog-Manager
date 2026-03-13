"""Database schema bootstrap and migration services."""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable

from isrc_manager.constants import SCHEMA_BASELINE, SCHEMA_TARGET
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
    ):
        self.conn = conn
        self.cursor = conn.cursor()
        self.logger = logger or logging.getLogger(__name__)
        self.audit_callback = audit_callback
        self.audit_commit = audit_commit

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
                track_title TEXT NOT NULL,
                main_artist_id INTEGER NOT NULL,
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
        self.cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_isrc_unique ON Tracks(isrc)")
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_isrc_compact_unique ON Tracks(isrc_compact)"
        )
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_title ON Tracks(track_title)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_upc ON Tracks(upc)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_genre ON Tracks(genre)")

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

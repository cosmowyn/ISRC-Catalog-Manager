"""Application-level ISRC claim registry.

The profile database remains the source of truth for catalog rows. This registry
is a small app-owned index used to keep generated ISRCs unique across every
known profile without scanning all profile databases on every save.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from isrc_manager.domain.codes import to_compact_isrc, to_iso_isrc
from isrc_manager.storage_sizes import clamp_history_storage_budget_mb

APP_REGISTRY_FILENAME = "application_registry.db"
APP_HISTORY_STORAGE_BUDGET_KEY = "history_storage_budget_mb"


@dataclass(frozen=True, slots=True)
class ISRCRegistryConflict:
    isrc_compact: str
    isrc_iso: str
    profile_path: str
    profile_name: str
    track_id: int | None
    track_title: str
    claim_kind: str
    claim_status: str


@dataclass(frozen=True, slots=True)
class ISRCRegistrySyncSummary:
    profile_count: int
    claim_count: int
    conflict_count: int
    conflicts: tuple[ISRCRegistryConflict, ...]


class ApplicationISRCRegistryService:
    """Maintains cross-profile ISRC claims in one app-owned SQLite database."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self.registry_path = self.data_root / APP_REGISTRY_FILENAME

    def ensure_schema(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._ensure_schema(conn)

    def sync_profiles(self, profile_paths: Iterable[str | Path]) -> ISRCRegistrySyncSummary:
        clean_paths = self._normalize_profile_paths(profile_paths)
        conflicts: list[ISRCRegistryConflict] = []
        claim_count = 0
        with self._connect() as conn:
            self._ensure_schema(conn)
            if clean_paths:
                placeholders = ",".join("?" for _ in clean_paths)
                conn.execute(
                    f"""
                    UPDATE registry_profile_sources
                    SET is_active=0, updated_at=datetime('now')
                    WHERE profile_path NOT IN ({placeholders})
                    """,
                    clean_paths,
                )
                conn.execute(
                    f"""
                    DELETE FROM registry_isrc_claims
                    WHERE profile_path NOT IN ({placeholders})
                    """,
                    clean_paths,
                )
            else:
                conn.execute(
                    "UPDATE registry_profile_sources SET is_active=0, updated_at=datetime('now')"
                )
                conn.execute("DELETE FROM registry_isrc_claims")

            for profile_path in clean_paths:
                profile_claims, profile_conflicts = self._sync_profile(conn, Path(profile_path))
                claim_count += profile_claims
                conflicts.extend(profile_conflicts)
        return ISRCRegistrySyncSummary(
            profile_count=len(clean_paths),
            claim_count=claim_count,
            conflict_count=len(conflicts),
            conflicts=tuple(conflicts),
        )

    def find_conflict(
        self,
        isrc: str,
        *,
        profile_path: str | Path | None = None,
        exclude_track_id: int | None = None,
    ) -> ISRCRegistryConflict | None:
        compact = to_compact_isrc(isrc)
        if not compact:
            return None
        normalized_profile = self._normalize_existing_or_raw_path(profile_path)
        with self._connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT isrc_compact, isrc_iso, profile_path, profile_name, track_id,
                       track_title, claim_kind, claim_status
                FROM registry_isrc_claims
                WHERE isrc_compact=?
                  AND claim_status IN ('active', 'reserved')
                """,
                (compact,),
            ).fetchone()
        if row is None:
            return None
        conflict = self._conflict_from_row(row)
        if normalized_profile and conflict.profile_path == normalized_profile:
            if exclude_track_id is not None and conflict.track_id == int(exclude_track_id):
                return None
        return conflict

    def reserve_isrc(
        self,
        isrc: str,
        *,
        profile_path: str | Path,
        profile_name: str | None = None,
        track_title: str | None = None,
        claim_kind: str = "generated",
        exclude_track_id: int | None = None,
    ) -> ISRCRegistryConflict | None:
        compact = to_compact_isrc(isrc)
        if not compact:
            return None
        iso = to_iso_isrc(compact) or str(isrc or "").strip().upper()
        normalized_profile = self._normalize_existing_or_raw_path(profile_path) or str(profile_path)
        clean_profile_name = str(profile_name or Path(normalized_profile).name).strip()
        clean_track_title = str(track_title or "").strip()
        with self._connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT isrc_compact, isrc_iso, profile_path, profile_name, track_id,
                       track_title, claim_kind, claim_status
                FROM registry_isrc_claims
                WHERE isrc_compact=?
                """,
                (compact,),
            ).fetchone()
            if row is not None:
                conflict = self._conflict_from_row(row)
                same_profile = conflict.profile_path == normalized_profile
                same_track = exclude_track_id is not None and conflict.track_id == int(
                    exclude_track_id
                )
                reusable_pending = same_profile and conflict.track_id is None
                if same_track or reusable_pending or conflict.claim_status == "abandoned":
                    conn.execute(
                        """
                        UPDATE registry_isrc_claims
                        SET profile_path=?, profile_name=?, track_title=?, claim_kind=?,
                            claim_status='reserved', updated_at=datetime('now')
                        WHERE isrc_compact=?
                        """,
                        (
                            normalized_profile,
                            clean_profile_name,
                            clean_track_title,
                            claim_kind,
                            compact,
                        ),
                    )
                    return None
                return conflict
            conn.execute(
                """
                INSERT INTO registry_isrc_claims(
                    isrc_compact, isrc_iso, profile_path, profile_name, track_id,
                    track_title, claim_kind, claim_status
                )
                VALUES (?, ?, ?, ?, NULL, ?, ?, 'reserved')
                """,
                (
                    compact,
                    iso,
                    normalized_profile,
                    clean_profile_name,
                    clean_track_title,
                    claim_kind,
                ),
            )
        return None

    def activate_isrc(
        self,
        isrc: str,
        *,
        profile_path: str | Path,
        profile_name: str | None = None,
        track_id: int | None = None,
        track_title: str | None = None,
        claim_kind: str = "profile_sync",
    ) -> ISRCRegistryConflict | None:
        compact = to_compact_isrc(isrc)
        if not compact:
            return None
        iso = to_iso_isrc(compact) or str(isrc or "").strip().upper()
        normalized_profile = self._normalize_existing_or_raw_path(profile_path) or str(profile_path)
        clean_profile_name = str(profile_name or Path(normalized_profile).name).strip()
        clean_track_title = str(track_title or "").strip()
        clean_track_id = int(track_id) if track_id is not None else None
        with self._connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT isrc_compact, isrc_iso, profile_path, profile_name, track_id,
                       track_title, claim_kind, claim_status
                FROM registry_isrc_claims
                WHERE isrc_compact=?
                """,
                (compact,),
            ).fetchone()
            if row is not None:
                conflict = self._conflict_from_row(row)
                same_profile = conflict.profile_path == normalized_profile
                same_track = clean_track_id is not None and conflict.track_id == clean_track_id
                pending_same_profile = same_profile and conflict.track_id is None
                if not (same_track or pending_same_profile or conflict.claim_status == "abandoned"):
                    return conflict
                conn.execute(
                    """
                    UPDATE registry_isrc_claims
                    SET isrc_iso=?, profile_path=?, profile_name=?, track_id=?,
                        track_title=?, claim_kind=?, claim_status='active',
                        updated_at=datetime('now')
                    WHERE isrc_compact=?
                    """,
                    (
                        iso,
                        normalized_profile,
                        clean_profile_name,
                        clean_track_id,
                        clean_track_title,
                        claim_kind,
                        compact,
                    ),
                )
                return None
            conn.execute(
                """
                INSERT INTO registry_isrc_claims(
                    isrc_compact, isrc_iso, profile_path, profile_name, track_id,
                    track_title, claim_kind, claim_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    compact,
                    iso,
                    normalized_profile,
                    clean_profile_name,
                    clean_track_id,
                    clean_track_title,
                    claim_kind,
                ),
            )
        return None

    def release_reserved_isrc(
        self,
        isrc: str,
        *,
        profile_path: str | Path,
    ) -> None:
        compact = to_compact_isrc(isrc)
        if not compact:
            return
        normalized_profile = self._normalize_existing_or_raw_path(profile_path) or str(profile_path)
        with self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                DELETE FROM registry_isrc_claims
                WHERE isrc_compact=?
                  AND profile_path=?
                  AND claim_status='reserved'
                  AND track_id IS NULL
                """,
                (compact, normalized_profile),
            )

    def read_history_storage_budget_mb(self, default: int) -> int:
        with self._connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key=?",
                (APP_HISTORY_STORAGE_BUDGET_KEY,),
            ).fetchone()
        if row is None or row[0] is None:
            return int(default)
        try:
            return int(clamp_history_storage_budget_mb(int(row[0])))
        except Exception:
            return int(default)

    def write_history_storage_budget_mb(self, megabytes: int) -> int:
        value = clamp_history_storage_budget_mb(int(megabytes))
        with self._connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO app_settings(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (APP_HISTORY_STORAGE_BUDGET_KEY, str(value)),
            )
        return int(value)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.registry_path)

    @classmethod
    def _ensure_schema(cls, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS registry_profile_sources (
                profile_path TEXT PRIMARY KEY,
                profile_name TEXT NOT NULL,
                profile_fingerprint TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                isrc_prefix TEXT,
                artist_code TEXT,
                owner_fingerprint TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS registry_isrc_claims (
                isrc_compact TEXT PRIMARY KEY,
                isrc_iso TEXT NOT NULL,
                profile_path TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                track_id INTEGER,
                track_title TEXT,
                claim_kind TEXT NOT NULL DEFAULT 'profile_sync',
                claim_status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_registry_isrc_claims_profile
            ON registry_isrc_claims(profile_path, track_id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )

    @classmethod
    def _sync_profile(
        cls,
        registry_conn: sqlite3.Connection,
        profile_path: Path,
    ) -> tuple[int, list[ISRCRegistryConflict]]:
        normalized_profile = cls._normalize_existing_or_raw_path(profile_path) or str(profile_path)
        profile_name = Path(normalized_profile).name
        fingerprint = cls._profile_fingerprint(profile_path)
        isrc_prefix = ""
        artist_code = ""
        tracks: list[tuple[int, str, str, str]] = []
        try:
            source_conn = sqlite3.connect(str(profile_path))
        except sqlite3.Error:
            source_conn = None
        if source_conn is not None:
            try:
                isrc_prefix = cls._read_scalar(
                    source_conn,
                    "SELECT prefix FROM ISRC_Prefix WHERE id=1",
                )
                artist_code = cls._read_artist_code(source_conn)
                tracks = cls._read_isrc_tracks(source_conn)
            finally:
                source_conn.close()

        registry_conn.execute(
            """
            INSERT INTO registry_profile_sources(
                profile_path, profile_name, profile_fingerprint, is_active,
                isrc_prefix, artist_code, owner_fingerprint
            )
            VALUES (?, ?, ?, 1, ?, ?, '')
            ON CONFLICT(profile_path) DO UPDATE SET
                profile_name=excluded.profile_name,
                profile_fingerprint=excluded.profile_fingerprint,
                is_active=1,
                isrc_prefix=excluded.isrc_prefix,
                artist_code=excluded.artist_code,
                updated_at=datetime('now'),
                last_seen_at=datetime('now')
            """,
            (normalized_profile, profile_name, fingerprint, isrc_prefix, artist_code),
        )

        seen_compacts: set[str] = set()
        conflicts: list[ISRCRegistryConflict] = []
        for track_id, track_title, isrc_iso, isrc_compact in tracks:
            compact = to_compact_isrc(isrc_compact or isrc_iso)
            if not compact:
                continue
            seen_compacts.add(compact)
            iso = to_iso_isrc(compact) or str(isrc_iso or "").strip().upper()
            row = registry_conn.execute(
                """
                SELECT isrc_compact, isrc_iso, profile_path, profile_name, track_id,
                       track_title, claim_kind, claim_status
                FROM registry_isrc_claims
                WHERE isrc_compact=?
                """,
                (compact,),
            ).fetchone()
            if row is not None:
                conflict = cls._conflict_from_row(row)
                same_claim = (
                    conflict.profile_path == normalized_profile and conflict.track_id == track_id
                )
                pending_same_profile = (
                    conflict.profile_path == normalized_profile and conflict.track_id is None
                )
                if not (same_claim or pending_same_profile or conflict.claim_status == "abandoned"):
                    conflicts.append(conflict)
                    continue
                registry_conn.execute(
                    """
                    UPDATE registry_isrc_claims
                    SET isrc_iso=?, profile_path=?, profile_name=?, track_id=?,
                        track_title=?, claim_kind='profile_sync', claim_status='active',
                        updated_at=datetime('now')
                    WHERE isrc_compact=?
                    """,
                    (iso, normalized_profile, profile_name, track_id, track_title, compact),
                )
                continue
            registry_conn.execute(
                """
                INSERT INTO registry_isrc_claims(
                    isrc_compact, isrc_iso, profile_path, profile_name, track_id,
                    track_title, claim_kind, claim_status
                )
                VALUES (?, ?, ?, ?, ?, ?, 'profile_sync', 'active')
                """,
                (compact, iso, normalized_profile, profile_name, track_id, track_title),
            )

        if seen_compacts:
            placeholders = ",".join("?" for _ in seen_compacts)
            registry_conn.execute(
                f"""
                DELETE FROM registry_isrc_claims
                WHERE profile_path=?
                  AND isrc_compact NOT IN ({placeholders})
                """,
                (normalized_profile, *sorted(seen_compacts)),
            )
        else:
            registry_conn.execute(
                "DELETE FROM registry_isrc_claims WHERE profile_path=?",
                (normalized_profile,),
            )
        return len(seen_compacts), conflicts

    @staticmethod
    def _read_scalar(conn: sqlite3.Connection, query: str) -> str:
        try:
            row = conn.execute(query).fetchone()
        except sqlite3.Error:
            return ""
        if row is None or row[0] is None:
            return ""
        return str(row[0]).strip()

    @classmethod
    def _read_artist_code(cls, conn: sqlite3.Connection) -> str:
        try:
            row = conn.execute("SELECT value FROM app_kv WHERE key='isrc_artist_code'").fetchone()
        except sqlite3.Error:
            return ""
        if row is None or row[0] is None:
            return ""
        return str(row[0]).strip()

    @staticmethod
    def _read_isrc_tracks(conn: sqlite3.Connection) -> list[tuple[int, str, str, str]]:
        try:
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(Tracks)").fetchall()
                if row and row[1]
            }
        except sqlite3.Error:
            return []
        if "id" not in columns or "isrc" not in columns:
            return []
        compact_expr = "isrc_compact" if "isrc_compact" in columns else "''"
        title_expr = "track_title" if "track_title" in columns else "''"
        try:
            rows = conn.execute(
                f"""
                SELECT id, {title_expr}, isrc, {compact_expr}
                FROM Tracks
                WHERE COALESCE(trim(isrc), '') != ''
                   OR COALESCE(trim({compact_expr}), '') != ''
                ORDER BY id
                """
            ).fetchall()
        except sqlite3.Error:
            return []
        return [
            (int(row[0]), str(row[1] or ""), str(row[2] or ""), str(row[3] or ""))
            for row in rows
            if row
        ]

    @staticmethod
    def _normalize_profile_paths(profile_paths: Iterable[str | Path]) -> list[str]:
        seen: set[str] = set()
        paths: list[str] = []
        for raw_path in profile_paths:
            normalized = ApplicationISRCRegistryService._normalize_existing_or_raw_path(raw_path)
            if not normalized or normalized in seen:
                continue
            if not Path(normalized).exists():
                continue
            seen.add(normalized)
            paths.append(normalized)
        return paths

    @staticmethod
    def _normalize_existing_or_raw_path(path: str | Path | None) -> str | None:
        if path is None:
            return None
        clean = str(path).strip()
        if not clean:
            return None
        try:
            return str(Path(clean).expanduser().resolve(strict=False))
        except Exception:
            return clean

    @staticmethod
    def _profile_fingerprint(profile_path: Path) -> str:
        try:
            stat = profile_path.stat()
        except OSError:
            return ""
        return f"{int(stat.st_size)}:{int(stat.st_mtime_ns)}"

    @staticmethod
    def _conflict_from_row(row: sqlite3.Row | tuple[object, ...]) -> ISRCRegistryConflict:
        raw_track_id = row[4]
        return ISRCRegistryConflict(
            isrc_compact=str(row[0] or "").strip().upper(),
            isrc_iso=str(row[1] or "").strip().upper(),
            profile_path=str(row[2] or "").strip(),
            profile_name=str(row[3] or "").strip(),
            track_id=int(str(raw_track_id)) if raw_track_id is not None else None,
            track_title=str(row[5] or "").strip(),
            claim_kind=str(row[6] or "").strip(),
            claim_status=str(row[7] or "").strip(),
        )

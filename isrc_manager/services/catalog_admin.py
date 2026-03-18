"""Catalog maintenance services for artists, albums, and licensees."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True)
class ArtistUsage:
    artist_id: int
    name: str
    main_uses: int
    extra_uses: int
    total_uses: int


@dataclass(slots=True)
class AlbumUsage:
    album_id: int
    title: str
    uses: int


@dataclass(slots=True)
class LicenseeUsage:
    licensee_id: int
    name: str
    license_count: int


class CatalogAdminService:
    """Centralizes maintenance operations for catalog support tables."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_artists_with_usage(self) -> list[ArtistUsage]:
        rows = self.conn.execute(
            """
            SELECT
                a.id,
                a.name,
                COALESCE(main_cnt.n, 0) AS main_uses,
                COALESCE(extra_cnt.n, 0) AS extra_uses
            FROM Artists a
            LEFT JOIN (
                SELECT main_artist_id AS artist_id, COUNT(*) AS n
                FROM Tracks
                GROUP BY main_artist_id
            ) AS main_cnt ON main_cnt.artist_id = a.id
            LEFT JOIN (
                SELECT artist_id, COUNT(*) AS n
                FROM TrackArtists
                GROUP BY artist_id
            ) AS extra_cnt ON extra_cnt.artist_id = a.id
            ORDER BY a.name COLLATE NOCASE
            """
        ).fetchall()
        return [
            ArtistUsage(
                artist_id=int(artist_id),
                name=name or "",
                main_uses=int(main_uses or 0),
                extra_uses=int(extra_uses or 0),
                total_uses=int(main_uses or 0) + int(extra_uses or 0),
            )
            for artist_id, name, main_uses, extra_uses in rows
        ]

    def delete_artists(self, artist_ids: Iterable[int]) -> None:
        normalized_ids = sorted({int(artist_id) for artist_id in artist_ids if int(artist_id) > 0})
        if not normalized_ids:
            return
        usage_by_id = {artist.artist_id: artist for artist in self.list_artists_with_usage()}
        blocked = [
            usage_by_id[artist_id].name
            for artist_id in normalized_ids
            if usage_by_id.get(artist_id) is not None and usage_by_id[artist_id].total_uses > 0
        ]
        if blocked:
            raise ValueError(
                "Artist still linked to tracks: " + ", ".join(sorted(set(blocked), key=str.casefold))
            )
        ids = [(artist_id,) for artist_id in normalized_ids]
        with self.conn:
            self.conn.executemany("DELETE FROM Artists WHERE id=?", ids)

    def purge_unused_artists(self) -> list[int]:
        unused_ids = [
            artist.artist_id for artist in self.list_artists_with_usage() if artist.total_uses == 0
        ]
        self.delete_artists(unused_ids)
        return unused_ids

    def list_albums_with_usage(self) -> list[AlbumUsage]:
        rows = self.conn.execute(
            """
            SELECT
                a.id,
                a.title,
                COALESCE(track_cnt.n, 0) AS uses
            FROM Albums a
            LEFT JOIN (
                SELECT album_id, COUNT(*) AS n
                FROM Tracks
                WHERE album_id IS NOT NULL
                GROUP BY album_id
            ) AS track_cnt ON track_cnt.album_id = a.id
            ORDER BY a.title COLLATE NOCASE
            """
        ).fetchall()
        return [
            AlbumUsage(
                album_id=int(album_id),
                title=title or "",
                uses=int(uses or 0),
            )
            for album_id, title, uses in rows
        ]

    def delete_albums(self, album_ids: Iterable[int]) -> None:
        normalized_ids = sorted({int(album_id) for album_id in album_ids if int(album_id) > 0})
        if not normalized_ids:
            return
        usage_by_id = {album.album_id: album for album in self.list_albums_with_usage()}
        blocked = [
            usage_by_id[album_id].title
            for album_id in normalized_ids
            if usage_by_id.get(album_id) is not None and usage_by_id[album_id].uses > 0
        ]
        if blocked:
            raise ValueError(
                "Album still linked to tracks: " + ", ".join(sorted(set(blocked), key=str.casefold))
            )
        ids = [(album_id,) for album_id in normalized_ids]
        with self.conn:
            self.conn.executemany("DELETE FROM Albums WHERE id=?", ids)

    def purge_unused_albums(self) -> list[int]:
        unused_ids = [album.album_id for album in self.list_albums_with_usage() if album.uses == 0]
        self.delete_albums(unused_ids)
        return unused_ids

    def list_licensees_with_usage(self) -> list[LicenseeUsage]:
        rows = self.conn.execute(
            """
            SELECT
                lic.id,
                lic.name,
                COALESCE(cnt.n, 0) AS n
            FROM Licensees lic
            LEFT JOIN (
                SELECT licensee_id, COUNT(*) AS n
                FROM Licenses
                GROUP BY licensee_id
            ) AS cnt ON cnt.licensee_id = lic.id
            ORDER BY lic.name COLLATE NOCASE
            """
        ).fetchall()
        return [
            LicenseeUsage(
                licensee_id=int(licensee_id),
                name=name or "",
                license_count=int(license_count or 0),
            )
            for licensee_id, name, license_count in rows
        ]

    def list_licensee_choices(self) -> list[tuple[int, str]]:
        return [
            (licensee.licensee_id, licensee.name) for licensee in self.list_licensees_with_usage()
        ]

    def ensure_licensee(self, name: str, *, cursor: sqlite3.Cursor | None = None) -> int:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Licensee name is required")
        if cursor is None:
            with self.conn:
                cur = self.conn.cursor()
                try:
                    cur.execute("INSERT INTO Licensees(name) VALUES (?)", (clean_name,))
                except sqlite3.IntegrityError:
                    pass
                row = cur.execute("SELECT id FROM Licensees WHERE name=?", (clean_name,)).fetchone()
        else:
            cur = cursor
            try:
                cur.execute("INSERT INTO Licensees(name) VALUES (?)", (clean_name,))
            except sqlite3.IntegrityError:
                pass
            row = cur.execute("SELECT id FROM Licensees WHERE name=?", (clean_name,)).fetchone()
        if not row:
            raise RuntimeError(f"Could not resolve licensee for name={clean_name!r}")
        return int(row[0])

    def rename_licensee(self, licensee_id: int, new_name: str) -> None:
        clean_name = (new_name or "").strip()
        if not clean_name:
            raise ValueError("Licensee name is required")
        with self.conn:
            self.conn.execute(
                "UPDATE Licensees SET name=? WHERE id=?", (clean_name, int(licensee_id))
            )

    def delete_licensee(self, licensee_id: int) -> None:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM Licenses WHERE licensee_id=?",
            (int(licensee_id),),
        ).fetchone()
        if row and int(row[0] or 0) > 0:
            raise ValueError("Licensee has linked licenses")
        with self.conn:
            self.conn.execute("DELETE FROM Licensees WHERE id=?", (int(licensee_id),))

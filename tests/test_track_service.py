import io
import sqlite3
import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE
from isrc_manager.media import waveform_cache
from isrc_manager.media.waveform_cache import AudioWaveformCacheService, AudioWaveformCacheWorker
from isrc_manager.services import TrackCreatePayload, TrackService, TrackUpdatePayload


def make_track_conn(path: str | Path | None = None):
    conn = sqlite3.connect(str(path) if path is not None else ":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE Artists (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE Albums (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            album_art_path TEXT,
            album_art_mime_type TEXT,
            album_art_size_bytes INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE Tracks (
            id INTEGER PRIMARY KEY,
            db_entry_date TEXT,
            isrc TEXT NOT NULL,
            isrc_compact TEXT,
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
            track_number INTEGER,
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
        );
        CREATE TABLE TrackArtists (
            track_id INTEGER NOT NULL,
            artist_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'additional',
            PRIMARY KEY (track_id, artist_id, role),
            FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
            FOREIGN KEY (artist_id) REFERENCES Artists(id) ON DELETE RESTRICT
        );
        CREATE TABLE AssetVersions (
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
            FOREIGN KEY (derived_from_asset_id) REFERENCES AssetVersions(id) ON DELETE SET NULL
        );
        """
    )
    return conn


def enable_governance_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE Works (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL
        );
        CREATE TABLE WorkTrackLinks (
            work_id INTEGER NOT NULL,
            track_id INTEGER NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 1,
            notes TEXT,
            PRIMARY KEY (work_id, track_id)
        );
        ALTER TABLE Tracks ADD COLUMN work_id INTEGER;
        ALTER TABLE Tracks ADD COLUMN parent_track_id INTEGER;
        ALTER TABLE Tracks ADD COLUMN relationship_type TEXT NOT NULL DEFAULT 'original';
        """
    )


class TrackServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_track_conn()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp_dir.name)
        self.service = TrackService(self.conn, self.data_root)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def _create_media_file(self, name: str, payload: bytes) -> Path:
        path = self.data_root / name
        path.write_bytes(payload)
        return path

    def _create_wav_media_file(self, name: str, *, amplitude: int = 12000) -> Path:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(44100)
            frames = bytearray()
            for index in range(256):
                value = amplitude if index % 2 == 0 else -amplitude
                frames.extend(int(value).to_bytes(2, "little", signed=True))
                frames.extend(int(value // 2).to_bytes(2, "little", signed=True))
            handle.writeframes(bytes(frames))
        return self._create_media_file(name, buffer.getvalue())

    def test_create_track_persists_relations_and_metadata(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00001",
                track_title="First Song",
                artist_name="Main Artist",
                additional_artists=["Guest One", "Guest Two"],
                album_title="Debut Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc="T-123.456.789-0",
                upc="123456789012",
                genre="Pop",
                catalog_number="CAT-001",
                buma_work_number="BUMA-77",
            )
        )

        row = self.conn.execute(
            """
            SELECT t.isrc, t.isrc_compact, t.track_title, a.name, al.title, t.release_date, t.track_length_sec, t.iswc, t.upc, t.genre, t.catalog_number, t.buma_work_number
            FROM Tracks t
            JOIN Artists a ON a.id = t.main_artist_id
            LEFT JOIN Albums al ON al.id = t.album_id
            WHERE t.id = ?
            """,
            (track_id,),
        ).fetchone()
        additional = self.conn.execute(
            """
            SELECT a.name
            FROM TrackArtists ta
            JOIN Artists a ON a.id = ta.artist_id
            WHERE ta.track_id = ?
            ORDER BY a.name
            """,
            (track_id,),
        ).fetchall()

        self.assertEqual(
            row,
            (
                "NL-ABC-26-00001",
                "NLABC2600001",
                "First Song",
                "Main Artist",
                "Debut Album",
                "2026-03-13",
                245,
                "T-123.456.789-0",
                "123456789012",
                "Pop",
                "CAT-001",
                "BUMA-77",
            ),
        )
        self.assertEqual([name for (name,) in additional], ["Guest One", "Guest Two"])
        self.assertEqual(self.service.fetch_track_title(track_id), "First Song")

    def test_create_track_does_not_require_works_table_or_rows(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00003",
                track_title="Track First",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Track First Album",
                release_date=None,
                track_length_sec=0,
                iswc=None,
                upc=None,
                genre=None,
                buma_work_number="BUMA-TRACK-FIRST",
            )
        )

        self.assertGreater(track_id, 0)
        self.assertEqual(
            self.conn.execute(
                "SELECT track_title, buma_work_number FROM Tracks WHERE id=?",
                (track_id,),
            ).fetchone(),
            ("Track First", "BUMA-TRACK-FIRST"),
        )
        self.assertIsNone(
            self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='Works'"
            ).fetchone()
        )

    def test_create_track_requires_linked_work_when_governance_is_enforced(self):
        enable_governance_schema(self.conn)
        self.service = TrackService(
            self.conn,
            self.data_root,
            require_governed_creation=True,
        )

        with self.assertRaisesRegex(ValueError, "linked Work"):
            self.service.create_track(
                TrackCreatePayload(
                    isrc="NL-ABC-26-00004",
                    track_title="Governed Only",
                    artist_name="Main Artist",
                    additional_artists=[],
                    album_title="Governed Album",
                    release_date=None,
                    track_length_sec=0,
                    iswc=None,
                    upc=None,
                    genre=None,
                )
            )

    def test_update_track_replaces_track_and_additional_artist_data(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00001",
                track_title="First Song",
                artist_name="Main Artist",
                additional_artists=["Guest One", "Guest Two"],
                album_title="Debut Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )

        self.service.update_track(
            TrackUpdatePayload(
                track_id=track_id,
                isrc="NL-ABC-26-00002",
                track_title="Second Song",
                artist_name="Renamed Artist",
                additional_artists=["New Guest"],
                album_title="Second Album",
                release_date="2026-03-14",
                track_length_sec=300,
                iswc="T-123.456.789-0",
                upc="1234567890123",
                genre="Electronic",
                catalog_number="CAT-002",
                buma_work_number="BUMA-88",
            )
        )

        row = self.conn.execute(
            """
            SELECT t.isrc, t.isrc_compact, t.track_title, a.name, al.title, t.release_date, t.track_length_sec, t.iswc, t.upc, t.genre, t.catalog_number, t.buma_work_number
            FROM Tracks t
            JOIN Artists a ON a.id = t.main_artist_id
            LEFT JOIN Albums al ON al.id = t.album_id
            WHERE t.id = ?
            """,
            (track_id,),
        ).fetchone()
        additional = self.conn.execute(
            """
            SELECT a.name
            FROM TrackArtists ta
            JOIN Artists a ON a.id = ta.artist_id
            WHERE ta.track_id = ?
            ORDER BY a.name
            """,
            (track_id,),
        ).fetchall()

        self.assertEqual(
            row,
            (
                "NL-ABC-26-00002",
                "NLABC2600002",
                "Second Song",
                "Renamed Artist",
                "Second Album",
                "2026-03-14",
                300,
                "T-123.456.789-0",
                "1234567890123",
                "Electronic",
                "CAT-002",
                "BUMA-88",
            ),
        )
        self.assertEqual([name for (name,) in additional], ["New Guest"])
        self.assertTrue(self.service.is_isrc_taken_normalized("nlabc2600002"))
        self.assertFalse(self.service.is_isrc_taken_normalized("NL-ABC-26-99999"))

    def test_track_number_persists_and_can_be_cleared(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00005",
                track_title="Numbered Song",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Ordered Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre="Pop",
                track_number=7,
            )
        )

        snapshot = self.service.fetch_track_snapshot(track_id)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.track_number, 7)
        self.assertEqual(
            self.conn.execute("SELECT track_number FROM Tracks WHERE id=?", (track_id,)).fetchone(),
            (7,),
        )

        self.service.update_track(
            TrackUpdatePayload(
                track_id=track_id,
                isrc="NL-ABC-26-00005",
                track_title="Numbered Song Updated",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Ordered Album",
                release_date="2026-03-14",
                track_length_sec=246,
                iswc=None,
                upc=None,
                genre="Pop",
            )
        )

        preserved_snapshot = self.service.fetch_track_snapshot(track_id)
        self.assertIsNotNone(preserved_snapshot)
        assert preserved_snapshot is not None
        self.assertEqual(preserved_snapshot.track_number, 7)

        self.service.update_track(
            TrackUpdatePayload(
                track_id=track_id,
                isrc="NL-ABC-26-00005",
                track_title="Numbered Song",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Ordered Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre="Pop",
                track_number=0,
            )
        )

        cleared_snapshot = self.service.fetch_track_snapshot(track_id)
        self.assertIsNotNone(cleared_snapshot)
        assert cleared_snapshot is not None
        self.assertIsNone(cleared_snapshot.track_number)
        self.assertEqual(
            self.conn.execute("SELECT track_number FROM Tracks WHERE id=?", (track_id,)).fetchone(),
            (None,),
        )

    def test_create_track_persists_governance_fields_when_schema_supports_it(self):
        enable_governance_schema(self.conn)
        self.conn.execute("INSERT INTO Works(id, title) VALUES (?, ?)", (1, "Signal Song"))

        parent_track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-01001",
                track_title="Signal Song",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Signal Era",
                release_date="2026-03-15",
                track_length_sec=200,
                iswc=None,
                upc=None,
                genre="Alt",
                work_id=1,
            )
        )
        remix_track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-01002",
                track_title="Signal Song Remix",
                artist_name="Main Artist",
                additional_artists=["Guest Remixer"],
                album_title="Signal Era",
                release_date="2026-03-16",
                track_length_sec=220,
                iswc=None,
                upc=None,
                genre="Alt",
                work_id=1,
                parent_track_id=parent_track_id,
                relationship_type="remix",
            )
        )

        self.assertEqual(
            self.conn.execute(
                """
                SELECT work_id, parent_track_id, relationship_type
                FROM Tracks
                WHERE id=?
                """,
                (remix_track_id,),
            ).fetchone(),
            (1, parent_track_id, "remix"),
        )
        self.assertEqual(
            self.conn.execute(
                """
                SELECT work_id, track_id, is_primary
                FROM WorkTrackLinks
                ORDER BY track_id
                """
            ).fetchall(),
            [(1, parent_track_id, 1), (1, remix_track_id, 0)],
        )

    def test_update_track_preserves_governance_fields_when_callers_do_not_pass_them(self):
        enable_governance_schema(self.conn)
        self.conn.execute("INSERT INTO Works(id, title) VALUES (?, ?)", (1, "Governed Work"))
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-01003",
                track_title="Governed Track",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Governed Album",
                release_date="2026-03-17",
                track_length_sec=201,
                iswc=None,
                upc=None,
                genre="Alt",
                work_id=1,
                relationship_type="alternate master",
            )
        )

        self.service.update_track(
            TrackUpdatePayload(
                track_id=track_id,
                isrc="NL-ABC-26-01003",
                track_title="Governed Track Updated",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Governed Album",
                release_date="2026-03-18",
                track_length_sec=203,
                iswc=None,
                upc=None,
                genre="Alt",
            )
        )

        self.assertEqual(
            self.conn.execute(
                """
                SELECT work_id, parent_track_id, relationship_type
                FROM Tracks
                WHERE id=?
                """,
                (track_id,),
            ).fetchone(),
            (1, None, "alternate_master"),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT work_id, track_id, is_primary FROM WorkTrackLinks"
            ).fetchall(),
            [(1, track_id, 1)],
        )

    def test_create_track_allows_blank_isrc(self):
        first_track = self.service.create_track(
            TrackCreatePayload(
                isrc="",
                track_title="Unassigned Song One",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Indie Release",
                release_date=None,
                track_length_sec=0,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        second_track = self.service.create_track(
            TrackCreatePayload(
                isrc="",
                track_title="Unassigned Song Two",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Indie Release",
                release_date=None,
                track_length_sec=0,
                iswc=None,
                upc=None,
                genre=None,
            )
        )

        rows = self.conn.execute(
            "SELECT id, isrc, isrc_compact FROM Tracks WHERE id IN (?, ?) ORDER BY id",
            (first_track, second_track),
        ).fetchall()
        self.assertEqual(rows, [(first_track, "", ""), (second_track, "", "")])
        self.assertFalse(self.service.is_isrc_taken_normalized(""))

    def test_list_album_group_track_ids_skips_blank_and_single_groups(self):
        album_track_a = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00010",
                track_title="Album Track A",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Shared Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        album_track_b = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00011",
                track_title="Album Track B",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Shared Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        single_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00012",
                track_title="Single Track",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Single",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        blank_album_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00013",
                track_title="Loose Track",
                artist_name="Main Artist",
                additional_artists=[],
                album_title=None,
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )

        self.assertEqual(
            self.service.list_album_group_track_ids(album_track_a),
            [album_track_a, album_track_b],
        )
        self.assertEqual(self.service.list_album_group_track_ids(single_track), [])
        self.assertEqual(self.service.list_album_group_track_ids(blank_album_track), [])

    def test_apply_album_metadata_to_tracks_updates_only_shared_album_fields(self):
        source_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00020",
                track_title="Source Track",
                artist_name="Album Artist",
                additional_artists=["Guest One"],
                album_title="Original Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc="T-123.456.789-0",
                upc="123456789012",
                genre="Pop",
                catalog_number="CAT-001",
                buma_work_number="BUMA-77",
            )
        )
        peer_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00021",
                track_title="Peer Track",
                artist_name="Album Artist",
                additional_artists=["Guest Two"],
                album_title="Original Album",
                release_date="2026-03-13",
                track_length_sec=321,
                iswc="T-123.456.780-0",
                upc="123456789012",
                genre="Pop",
                catalog_number="CAT-001",
                buma_work_number="BUMA-88",
            )
        )

        updated_ids = self.service.apply_album_metadata_to_tracks(
            [peer_track],
            field_updates={
                "artist_name": "Renamed Album Artist",
                "album_title": "Renamed Album",
                "release_date": "2026-04-01",
                "upc": "999999999999",
                "genre": "Ambient",
                "catalog_number": "CAT-002",
            },
        )

        self.assertEqual(updated_ids, [peer_track])
        source_snapshot = self.service.fetch_track_snapshot(source_track)
        peer_snapshot = self.service.fetch_track_snapshot(peer_track)

        self.assertEqual(source_snapshot.artist_name, "Album Artist")
        self.assertEqual(source_snapshot.album_title, "Original Album")
        self.assertEqual(peer_snapshot.artist_name, "Renamed Album Artist")
        self.assertEqual(peer_snapshot.album_title, "Renamed Album")
        self.assertEqual(peer_snapshot.release_date, "2026-04-01")
        self.assertEqual(peer_snapshot.upc, "999999999999")
        self.assertEqual(peer_snapshot.genre, "Ambient")
        self.assertEqual(peer_snapshot.catalog_number, "CAT-002")
        self.assertEqual(peer_snapshot.track_title, "Peer Track")
        self.assertEqual(peer_snapshot.additional_artists, ["Guest Two"])
        self.assertEqual(peer_snapshot.track_length_sec, 321)
        self.assertEqual(peer_snapshot.iswc, "T-123.456.780-0")
        self.assertEqual(peer_snapshot.buma_work_number, "BUMA-88")

    def test_album_art_is_shared_across_real_album_tracks(self):
        lead_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00030",
                track_title="Lead Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Shared Art Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        peer_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00031",
                track_title="Peer Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Shared Art Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )

        source_image = self.data_root / "cover.png"
        source_image.write_bytes(b"shared-album-art")

        self.service.set_media_path(lead_track, "album_art", source_image)

        lead_meta = self.service.get_media_meta(lead_track, "album_art")
        peer_meta = self.service.get_media_meta(peer_track, "album_art")
        self.assertTrue(lead_meta["has_media"])
        self.assertTrue(peer_meta["has_media"])
        self.assertEqual(lead_meta["path"], peer_meta["path"])
        self.assertEqual(lead_meta["mime_type"], "image/png")

        album_row = self.conn.execute(
            """
            SELECT al.album_art_path, al.album_art_mime_type, al.album_art_size_bytes
            FROM Albums al
            JOIN Tracks t ON t.album_id = al.id
            WHERE t.id = ?
            """,
            (lead_track,),
        ).fetchone()
        self.assertEqual(album_row[0], lead_meta["path"])
        self.assertEqual(album_row[1], "image/png")
        self.assertGreater(int(album_row[2] or 0), 0)

        track_rows = self.conn.execute(
            "SELECT album_art_path FROM Tracks WHERE id IN (?, ?) ORDER BY id",
            (lead_track, peer_track),
        ).fetchall()
        self.assertEqual(track_rows, [(None,), (None,)])

        lead_bytes, _ = self.service.fetch_media_bytes(lead_track, "album_art")
        peer_bytes, _ = self.service.fetch_media_bytes(peer_track, "album_art")
        self.assertEqual(lead_bytes, b"shared-album-art")
        self.assertEqual(peer_bytes, b"shared-album-art")

    def test_clearing_shared_album_art_removes_managed_file_when_unreferenced(self):
        lead_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00040",
                track_title="Lead Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Shared Art Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        peer_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00041",
                track_title="Peer Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Shared Art Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )

        source_image = self.data_root / "cover_delete.png"
        source_image.write_bytes(b"delete-me")

        meta = self.service.set_media_path(lead_track, "album_art", source_image)
        managed_path = self.service.resolve_media_path(str(meta["path"] or ""))
        self.assertIsNotNone(managed_path)
        self.assertTrue(managed_path.exists())

        self.service.clear_media(peer_track, "album_art")

        self.assertFalse(self.service.get_media_meta(lead_track, "album_art")["has_media"])
        self.assertFalse(self.service.get_media_meta(peer_track, "album_art")["has_media"])
        album_row = self.conn.execute(
            """
            SELECT al.album_art_path
            FROM Albums al
            JOIN Tracks t ON t.album_id = al.id
            WHERE t.id = ?
            """,
            (lead_track,),
        ).fetchone()
        self.assertEqual(album_row, (None,))
        self.assertFalse(managed_path.exists())

    def test_describe_album_art_edit_state_for_direct_track_art(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00050",
                track_title="Direct Art Track",
                artist_name="Solo Artist",
                additional_artists=[],
                album_title="Single",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        source_image = self._create_media_file("direct-art.png", b"direct-art")

        self.service.set_media_path(track_id, "album_art", source_image)
        state = self.service.describe_album_art_edit_state(track_id)

        self.assertTrue(state.has_effective_art)
        self.assertEqual(state.owner_scope, "track")
        self.assertEqual(state.owner_track_id, track_id)
        self.assertEqual(state.owner_track_title, "Direct Art Track")
        self.assertFalse(state.is_shared_reference)
        self.assertTrue(state.can_replace_directly)

    def test_describe_album_art_edit_state_for_shared_album_master_and_slave(self):
        lead_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00051",
                track_title="Lead Shared Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Shared Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        peer_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00052",
                track_title="Peer Shared Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Shared Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        source_image = self._create_media_file("shared-art-db.png", b"shared-art-db")

        self.service.set_media_path(
            lead_track,
            "album_art",
            source_image,
            storage_mode=STORAGE_MODE_DATABASE,
        )

        master_state = self.service.describe_album_art_edit_state(lead_track)
        slave_state = self.service.describe_album_art_edit_state(peer_track)

        self.assertEqual(master_state.owner_scope, "album")
        self.assertEqual(master_state.owner_track_id, lead_track)
        self.assertEqual(master_state.owner_track_title, "Lead Shared Track")
        self.assertFalse(master_state.is_shared_reference)
        self.assertTrue(master_state.can_replace_directly)

        self.assertEqual(slave_state.owner_scope, "album")
        self.assertEqual(slave_state.owner_track_id, lead_track)
        self.assertEqual(slave_state.owner_track_title, "Lead Shared Track")
        self.assertTrue(slave_state.is_shared_reference)
        self.assertFalse(slave_state.can_replace_directly)

    def test_describe_album_art_edit_state_for_album_track_fallback(self):
        owner_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00053",
                track_title="Fallback Owner",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Legacy Shared Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        peer_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00054",
                track_title="Fallback Peer",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Legacy Shared Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        stored_path = self.service.media_store.write_bytes(
            b"legacy-shared-art",
            filename="legacy-fallback.png",
            subdir="images",
        )
        with self.conn:
            self.conn.execute(
                """
                UPDATE Tracks
                SET album_art_path=?,
                    album_art_storage_mode=?,
                    album_art_filename=?,
                    album_art_mime_type=?,
                    album_art_size_bytes=?
                WHERE id=?
                """,
                (
                    stored_path,
                    STORAGE_MODE_MANAGED_FILE,
                    "legacy-fallback.png",
                    "image/png",
                    len(b"legacy-shared-art"),
                    owner_track,
                ),
            )

        owner_state = self.service.describe_album_art_edit_state(owner_track)
        peer_state = self.service.describe_album_art_edit_state(peer_track)

        self.assertEqual(owner_state.owner_scope, "album_track")
        self.assertEqual(owner_state.owner_track_id, owner_track)
        self.assertTrue(owner_state.can_replace_directly)
        self.assertFalse(owner_state.is_shared_reference)

        self.assertEqual(peer_state.owner_scope, "album_track")
        self.assertEqual(peer_state.owner_track_id, owner_track)
        self.assertEqual(peer_state.owner_track_title, "Fallback Owner")
        self.assertFalse(peer_state.can_replace_directly)
        self.assertTrue(peer_state.is_shared_reference)

    def test_slave_track_cannot_replace_shared_album_art_directly(self):
        lead_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00055",
                track_title="Master Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Guarded Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        peer_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00056",
                track_title="Slave Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Guarded Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        source_image = self._create_media_file("guarded-master.png", b"master-art")
        replacement_image = self._create_media_file("guarded-peer.png", b"peer-art")

        self.service.set_media_path(
            lead_track,
            "album_art",
            source_image,
            storage_mode=STORAGE_MODE_DATABASE,
        )

        with self.assertRaisesRegex(
            ValueError,
            r'Album art for this track is managed by Track #\d+ "Master Track"\. Edit that record to replace the shared image\.',
        ):
            self.service.set_media_path(
                peer_track,
                "album_art",
                replacement_image,
                storage_mode=STORAGE_MODE_DATABASE,
            )

    def test_slave_track_cannot_convert_shared_album_art_storage_mode_directly(self):
        lead_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00057",
                track_title="Master Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Guarded Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        peer_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00058",
                track_title="Slave Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Guarded Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        source_image = self._create_media_file("guarded-managed.png", b"managed-art")

        self.service.set_media_path(lead_track, "album_art", source_image)

        with self.assertRaisesRegex(
            ValueError,
            r'Album art for this track is managed by Track #\d+ "Master Track"\. Edit that record to replace the shared image\.',
        ):
            self.service.convert_media_storage_mode(
                peer_track,
                "album_art",
                STORAGE_MODE_DATABASE,
            )

    def test_master_track_can_still_replace_shared_album_art(self):
        lead_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00059",
                track_title="Master Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Replaceable Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        peer_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00060",
                track_title="Peer Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Replaceable Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        initial_image = self._create_media_file("replace-initial.png", b"initial-art")
        replacement_image = self._create_media_file("replace-final.png", b"replacement-art")

        self.service.set_media_path(
            lead_track,
            "album_art",
            initial_image,
            storage_mode=STORAGE_MODE_DATABASE,
        )
        self.service.set_media_path(
            lead_track,
            "album_art",
            replacement_image,
            storage_mode=STORAGE_MODE_DATABASE,
        )

        lead_bytes, _ = self.service.fetch_media_bytes(lead_track, "album_art")
        peer_bytes, _ = self.service.fetch_media_bytes(peer_track, "album_art")
        self.assertEqual(lead_bytes, b"replacement-art")
        self.assertEqual(peer_bytes, b"replacement-art")

    def test_create_track_with_audio_creates_primary_asset_version(self):
        audio_path = self._create_media_file("primary-master.wav", b"RIFFprimarymaster")

        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00059",
                track_title="Asset Synced Song",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Asset Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
                audio_file_source_path=str(audio_path),
                audio_file_storage_mode=STORAGE_MODE_DATABASE,
            )
        )

        assets = self.service.asset_service.list_assets(track_id=track_id)
        self.assertEqual(len(assets), 1)
        asset = assets[0]
        self.assertEqual(asset.asset_type, "main_master")
        self.assertTrue(asset.primary_flag)
        self.assertTrue(asset.approved_for_use)
        self.assertEqual(asset.storage_mode, STORAGE_MODE_DATABASE)
        self.assertEqual(asset.version_status, "approved")
        asset_bytes, _mime = self.service.asset_service.fetch_asset_bytes(asset.id)
        self.assertEqual(asset_bytes, b"RIFFprimarymaster")

    def test_set_media_path_versions_existing_primary_audio_asset_when_file_changes(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00060",
                track_title="Versioned Asset Song",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Versioned Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        first_audio = self._create_media_file("version-one.wav", b"RIFFversionone")
        second_audio = self._create_media_file("version-two.wav", b"RIFFversiontwo")

        self.service.set_media_path(track_id, "audio_file", first_audio)
        first_asset = self.service.asset_service.list_assets(track_id=track_id)[0]

        self.service.set_media_path(track_id, "audio_file", second_audio)

        assets = self.service.asset_service.list_assets(track_id=track_id)
        self.assertEqual(len(assets), 2)
        current_asset = next(asset for asset in assets if asset.primary_flag)
        prior_asset = next(asset for asset in assets if not asset.primary_flag)
        self.assertEqual(current_asset.derived_from_asset_id, first_asset.id)
        self.assertEqual(prior_asset.id, first_asset.id)
        current_bytes, _mime = self.service.asset_service.fetch_asset_bytes(current_asset.id)
        prior_bytes, _mime = self.service.asset_service.fetch_asset_bytes(prior_asset.id)
        self.assertEqual(current_bytes, b"RIFFversiontwo")
        self.assertEqual(prior_bytes, b"RIFFversionone")

    def test_audio_waveform_cache_is_stored_updated_and_cleaned_with_audio(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00064",
                track_title="Cached Waveform Song",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Cache Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        first_audio = self._create_wav_media_file("cached-one.wav", amplitude=8000)
        second_audio = self._create_wav_media_file("cached-two.wav", amplitude=16000)

        self.service.set_media_path(
            track_id,
            "audio_file",
            first_audio,
            storage_mode=STORAGE_MODE_DATABASE,
        )

        first_row = self.conn.execute(
            """
            SELECT source_fingerprint, peaks_json, light_preview_png, dark_preview_png
            FROM TrackAudioWaveformCache
            WHERE track_id=?
            """,
            (track_id,),
        ).fetchone()
        self.assertIsNotNone(first_row)
        self.assertTrue(first_row[0])
        self.assertIn("[", first_row[1])
        self.assertTrue(bytes(first_row[2]).startswith(b"\x89PNG"))
        self.assertTrue(bytes(first_row[3]).startswith(b"\x89PNG"))

        self.service.set_media_path(
            track_id,
            "audio_file",
            second_audio,
            storage_mode=STORAGE_MODE_DATABASE,
        )
        second_fingerprint = self.conn.execute(
            "SELECT source_fingerprint FROM TrackAudioWaveformCache WHERE track_id=?",
            (track_id,),
        ).fetchone()[0]
        self.assertNotEqual(first_row[0], second_fingerprint)

        inspection = AudioWaveformCacheService(self.conn).inspect_invalid_caches(self.service)
        self.assertEqual(inspection.issue_count, 0)

        self.service.clear_media(track_id, "audio_file")
        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM TrackAudioWaveformCache WHERE track_id=?",
                (track_id,),
            ).fetchone()
        )

    def test_qt_waveform_decoder_is_skipped_without_application_instance(self):
        with mock.patch.object(
            waveform_cache,
            "_qt_application_instance_available",
            return_value=False,
        ):
            self.assertIsNone(
                waveform_cache._load_qt_decoder_peaks(
                    str(self.data_root / "no-app.mp3"),
                    16,
                )
            )

    def test_audio_waveform_cache_can_be_deferred_to_scheduler(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00067",
                track_title="Deferred Waveform Song",
                artist_name="Main Artist",
                additional_artists=[],
                album_title=None,
                release_date=None,
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        audio_path = self._create_wav_media_file("cached-deferred.wav")
        scheduled_track_ids = []
        self.service.waveform_cache_scheduler = scheduled_track_ids.append

        with mock.patch.object(
            self.service.waveform_cache_service,
            "ensure_track_cache",
        ) as ensure_track_cache:
            self.service.set_media_path(track_id, "audio_file", audio_path)

        ensure_track_cache.assert_not_called()
        self.assertEqual(scheduled_track_ids, [track_id])
        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM TrackAudioWaveformCache WHERE track_id=?",
                (track_id,),
            ).fetchone()
        )

    def test_audio_waveform_cache_worker_generates_deferred_cache(self):
        db_path = self.data_root / "worker-cache.db"
        conn = make_track_conn(db_path)
        worker = AudioWaveformCacheWorker(db_path=db_path, data_root=self.data_root)
        try:
            service = TrackService(conn, self.data_root)
            track_id = service.create_track(
                TrackCreatePayload(
                    isrc="NL-ABC-26-00068",
                    track_title="Worker Waveform Song",
                    artist_name="Main Artist",
                    additional_artists=[],
                    album_title=None,
                    release_date=None,
                    track_length_sec=180,
                    iswc=None,
                    upc=None,
                    genre=None,
                )
            )
            audio_path = self._create_wav_media_file("cached-worker.wav")
            service.waveform_cache_scheduler = lambda _track_id: None
            service.set_media_path(track_id, "audio_file", audio_path)
            conn.commit()
            self.assertIsNone(
                conn.execute(
                    "SELECT 1 FROM TrackAudioWaveformCache WHERE track_id=?",
                    (track_id,),
                ).fetchone()
            )

            self.assertTrue(worker.enqueue_track(track_id))
            deadline = time.monotonic() + 5.0
            row = None
            while time.monotonic() < deadline:
                row = conn.execute(
                    """
                    SELECT light_preview_png, dark_preview_png
                    FROM TrackAudioWaveformCache
                    WHERE track_id=?
                    """,
                    (track_id,),
                ).fetchone()
                if row is not None:
                    break
                time.sleep(0.05)

            self.assertIsNotNone(row)
            self.assertTrue(bytes(row[0]).startswith(b"\x89PNG"))
            self.assertTrue(bytes(row[1]).startswith(b"\x89PNG"))
        finally:
            worker.stop(wait=True)
            conn.close()

    def test_delete_track_removes_cached_waveform_rows(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00065",
                track_title="Cached Disposable Song",
                artist_name="Main Artist",
                additional_artists=[],
                album_title=None,
                release_date=None,
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        audio_path = self._create_wav_media_file("cached-delete.wav")
        self.service.set_media_path(track_id, "audio_file", audio_path)
        self.assertIsNotNone(
            self.conn.execute(
                "SELECT 1 FROM TrackAudioWaveformCache WHERE track_id=?",
                (track_id,),
            ).fetchone()
        )

        self.service.delete_track(track_id)

        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM TrackAudioWaveformCache WHERE track_id=?",
                (track_id,),
            ).fetchone()
        )

    def test_waveform_cache_diagnostics_clean_stale_and_orphaned_rows(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00066",
                track_title="Cached Diagnostics Song",
                artist_name="Main Artist",
                additional_artists=[],
                album_title=None,
                release_date=None,
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        audio_path = self._create_wav_media_file("cached-diagnostics.wav")
        self.service.set_media_path(track_id, "audio_file", audio_path)
        self.conn.execute(
            "UPDATE TrackAudioWaveformCache SET source_fingerprint='stale' WHERE track_id=?",
            (track_id,),
        )
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.execute(
            """
            INSERT INTO TrackAudioWaveformCache(
                track_id, source_fingerprint, source_size_bytes, analyzer_version,
                width_px, height_px, peaks_json, light_preview_png, dark_preview_png
            )
            VALUES (?, 'orphan', 0, 0, 1, 1, '[]', X'00', X'00')
            """,
            (99999,),
        )
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = ON")

        cache_service = AudioWaveformCacheService(self.conn)
        inspection = cache_service.inspect_invalid_caches(self.service)
        self.assertEqual(inspection.stale_rows, 1)
        self.assertEqual(inspection.orphaned_rows, 1)

        removed = cache_service.cleanup_invalid_caches(self.service)

        self.assertEqual(removed, 2)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM TrackAudioWaveformCache").fetchone()[0],
            0,
        )

    def test_set_media_path_updates_track_length_from_audio_duration(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00062",
                track_title="Duration Synced Song",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Duration Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        audio_path = self._create_media_file("duration-sync.wav", b"RIFFdurationsync")

        with mock.patch(
            "isrc_manager.services.tracks.MutagenFile",
            return_value=SimpleNamespace(info=SimpleNamespace(length=201.6)),
        ):
            self.service.set_media_path(track_id, "audio_file", audio_path)

        stored_length = self.conn.execute(
            "SELECT track_length_sec FROM Tracks WHERE id=?",
            (track_id,),
        ).fetchone()[0]
        self.assertEqual(stored_length, 201)

    def test_derive_audio_duration_seconds_never_rounds_above_actual_duration(self):
        audio_path = self._create_media_file("duration-floor.wav", b"RIFFdurationfloor")

        with mock.patch(
            "isrc_manager.services.tracks.MutagenFile",
            return_value=SimpleNamespace(info=SimpleNamespace(length=201.999)),
        ):
            duration_seconds = self.service.derive_audio_duration_seconds(audio_path)

        self.assertEqual(duration_seconds, 201)

    def test_update_track_keeps_manual_track_length_after_new_audio_selection(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00063",
                track_title="Manual Length Song",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Manual Length Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        audio_path = self._create_media_file("manual-length.wav", b"RIFFmanuallength")

        with mock.patch(
            "isrc_manager.services.tracks.MutagenFile",
            return_value=SimpleNamespace(info=SimpleNamespace(length=180.2)),
        ):
            self.service.update_track(
                TrackUpdatePayload(
                    track_id=track_id,
                    isrc="NL-ABC-26-00063",
                    track_title="Manual Length Song",
                    artist_name="Main Artist",
                    additional_artists=[],
                    album_title="Manual Length Album",
                    release_date="2026-03-13",
                    track_length_sec=321,
                    iswc=None,
                    upc=None,
                    genre=None,
                    audio_file_source_path=str(audio_path),
                )
            )

        stored_length = self.conn.execute(
            "SELECT track_length_sec FROM Tracks WHERE id=?",
            (track_id,),
        ).fetchone()[0]
        self.assertEqual(stored_length, 321)

    def test_convert_audio_storage_mode_updates_linked_primary_asset_without_new_version(self):
        audio_path = self._create_media_file("mode-shift.wav", b"RIFFmodeshift")
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00061",
                track_title="Storage Mode Sync",
                artist_name="Main Artist",
                additional_artists=[],
                album_title="Storage Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
                audio_file_source_path=str(audio_path),
            )
        )

        original_asset = self.service.asset_service.list_assets(track_id=track_id)[0]

        self.service.convert_media_storage_mode(track_id, "audio_file", STORAGE_MODE_DATABASE)

        assets = self.service.asset_service.list_assets(track_id=track_id)
        self.assertEqual(len(assets), 1)
        updated_asset = assets[0]
        self.assertEqual(updated_asset.id, original_asset.id)
        self.assertEqual(updated_asset.storage_mode, STORAGE_MODE_DATABASE)
        updated_bytes, _mime = self.service.asset_service.fetch_asset_bytes(updated_asset.id)
        self.assertEqual(updated_bytes, b"RIFFmodeshift")

    def test_clearing_shared_album_art_allows_former_slave_to_upload_again(self):
        lead_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00061",
                track_title="Lead Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Resettable Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        peer_track = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00062",
                track_title="Peer Track",
                artist_name="Album Artist",
                additional_artists=[],
                album_title="Resettable Album",
                release_date="2026-03-13",
                track_length_sec=245,
                iswc=None,
                upc=None,
                genre=None,
            )
        )
        initial_image = self._create_media_file("reset-initial.png", b"initial-reset-art")
        replacement_image = self._create_media_file("reset-peer.png", b"peer-reset-art")

        self.service.set_media_path(
            lead_track,
            "album_art",
            initial_image,
            storage_mode=STORAGE_MODE_DATABASE,
        )
        self.service.clear_media(peer_track, "album_art")

        cleared_state = self.service.describe_album_art_edit_state(peer_track)
        self.assertFalse(cleared_state.has_effective_art)
        self.assertTrue(cleared_state.can_replace_directly)

        self.service.set_media_path(
            peer_track,
            "album_art",
            replacement_image,
            storage_mode=STORAGE_MODE_DATABASE,
        )

        lead_bytes, _ = self.service.fetch_media_bytes(lead_track, "album_art")
        peer_bytes, _ = self.service.fetch_media_bytes(peer_track, "album_art")
        self.assertEqual(lead_bytes, b"peer-reset-art")
        self.assertEqual(peer_bytes, b"peer-reset-art")

    def test_delete_track_removes_track_and_join_rows(self):
        track_id = self.service.create_track(
            TrackCreatePayload(
                isrc="NL-ABC-26-00003",
                track_title="Disposable Song",
                artist_name="Main Artist",
                additional_artists=["Guest One"],
                album_title=None,
                release_date=None,
                track_length_sec=180,
                iswc=None,
                upc=None,
                genre=None,
            )
        )

        self.service.delete_track(track_id)

        self.assertIsNone(
            self.conn.execute("SELECT id FROM Tracks WHERE id=?", (track_id,)).fetchone()
        )
        self.assertIsNone(
            self.conn.execute("SELECT 1 FROM TrackArtists WHERE track_id=?", (track_id,)).fetchone()
        )


if __name__ == "__main__":
    unittest.main()

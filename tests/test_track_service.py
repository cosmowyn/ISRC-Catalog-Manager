import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE
from isrc_manager.services import TrackCreatePayload, TrackService, TrackUpdatePayload


def make_track_conn():
    conn = sqlite3.connect(":memory:")
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
        """
    )
    return conn


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

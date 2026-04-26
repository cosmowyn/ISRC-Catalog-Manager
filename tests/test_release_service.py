import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.services import DatabaseSchemaService, TrackCreatePayload, TrackService


class ReleaseServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp_dir.name)
        schema = DatabaseSchemaService(self.conn, data_root=self.data_root)
        schema.init_db()
        schema.migrate_schema()
        self.track_service = TrackService(self.conn, self.data_root)
        self.release_service = ReleaseService(self.conn, self.data_root)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def _create_track(
        self,
        *,
        isrc: str,
        title: str,
        album: str,
        upc: str | None = None,
        catalog: str | None = None,
    ) -> int:
        return self.track_service.create_track(
            TrackCreatePayload(
                isrc=isrc,
                track_title=title,
                artist_name="Release Artist",
                additional_artists=[],
                album_title=album,
                release_date="2026-03-15",
                track_length_sec=210,
                iswc=None,
                upc=upc,
                genre="Ambient",
                catalog_number=catalog,
            )
        )

    def test_create_release_persists_metadata_and_track_order(self):
        track_a = self._create_track(
            isrc="NL-ABC-26-00001", title="Track A", album="Release Album", upc="036000291452"
        )
        track_b = self._create_track(
            isrc="NL-ABC-26-00002", title="Track B", album="Release Album", upc="036000291452"
        )

        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Release Album",
                primary_artist="Release Artist",
                album_artist="Release Artist",
                release_type="album",
                release_date="2026-03-15",
                catalog_number="CAT-900",
                upc="036000291452",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_a, disc_number=1, track_number=1, sequence_number=1
                    ),
                    ReleaseTrackPlacement(
                        track_id=track_b, disc_number=1, track_number=2, sequence_number=2
                    ),
                ],
            )
        )

        summary = self.release_service.fetch_release_summary(release_id)
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary.release.title, "Release Album")
        self.assertEqual(summary.release.barcode_validation_status, "valid")
        self.assertEqual([placement.track_id for placement in summary.tracks], [track_a, track_b])
        self.assertEqual([placement.track_number for placement in summary.tracks], [1, 2])

    def test_create_release_persists_workflow_status_and_readiness_flags(self):
        track_id = self._create_track(
            isrc="NL-ABC-26-00003",
            title="Workflow Track",
            album="Workflow Album",
            upc="036000291452",
        )

        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Workflow Album",
                primary_artist="Release Artist",
                release_type="album",
                repertoire_status="contract_pending",
                metadata_complete=True,
                contract_signed=False,
                rights_verified=True,
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_id,
                        disc_number=1,
                        track_number=1,
                        sequence_number=1,
                    )
                ],
            )
        )

        release = self.release_service.fetch_release(release_id)
        self.assertIsNotNone(release)
        assert release is not None
        self.assertEqual(release.repertoire_status, "contract_pending")
        self.assertTrue(release.metadata_complete)
        self.assertFalse(release.contract_signed)
        self.assertTrue(release.rights_verified)

    def test_add_tracks_to_release_appends_positions(self):
        track_a = self._create_track(isrc="NL-ABC-26-00011", title="Track A", album="Release Album")
        track_b = self._create_track(isrc="NL-ABC-26-00012", title="Track B", album="Release Album")
        track_c = self._create_track(isrc="NL-ABC-26-00013", title="Track C", album="Release Album")

        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Release Album",
                primary_artist="Release Artist",
                placements=[
                    ReleaseTrackPlacement(track_id=track_a, track_number=1, sequence_number=1)
                ],
            )
        )
        added = self.release_service.add_tracks_to_release(release_id, [track_b, track_c])

        self.assertEqual(added, [track_b, track_c])
        placements = self.release_service.list_release_tracks(release_id)
        self.assertEqual([placement.track_number for placement in placements], [1, 2, 3])

    def test_delete_release_removes_release_links_and_unreferenced_artwork(self):
        track_id = self._create_track(
            isrc="NL-ABC-26-00014", title="Delete Release Track", album="Release Album"
        )
        artwork_source = self.data_root / "delete-release-art.png"
        artwork_source.write_bytes(b"fake image bytes")
        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Delete Release",
                primary_artist="Release Artist",
                artwork_source_path=str(artwork_source),
                placements=[ReleaseTrackPlacement(track_id=track_id)],
            )
        )
        release = self.release_service.fetch_release(release_id)
        self.assertIsNotNone(release)
        assert release is not None
        managed_artwork = self.release_service.resolve_artwork_path(release.artwork_path)
        self.assertIsNotNone(managed_artwork)
        assert managed_artwork is not None
        self.assertTrue(managed_artwork.exists())

        self.release_service.delete_release(release_id)

        self.assertIsNone(self.release_service.fetch_release(release_id))
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM ReleaseTracks WHERE release_id=?", (release_id,)
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM Tracks WHERE id=?", (track_id,)).fetchone()[0],
            1,
        )
        self.assertFalse(managed_artwork.exists())

    def test_replace_release_tracks_renumbers_conflicting_disc_track_positions(self):
        track_a = self._create_track(isrc="NL-ABC-26-00021", title="Track A", album="Release Album")
        track_b = self._create_track(isrc="NL-ABC-26-00022", title="Track B", album="Release Album")

        release_id = self.release_service.create_release(
            ReleasePayload(
                title="Release Album",
                primary_artist="Release Artist",
                placements=[
                    ReleaseTrackPlacement(
                        track_id=track_a, disc_number=1, track_number=1, sequence_number=1
                    ),
                    ReleaseTrackPlacement(
                        track_id=track_b, disc_number=1, track_number=1, sequence_number=2
                    ),
                ],
            )
        )

        placements = self.release_service.list_release_tracks(release_id)
        self.assertEqual([placement.track_id for placement in placements], [track_a, track_b])
        self.assertEqual([placement.disc_number for placement in placements], [1, 1])
        self.assertEqual([placement.track_number for placement in placements], [1, 2])
        self.assertEqual([placement.sequence_number for placement in placements], [1, 2])

    def test_duplicate_upc_is_reported_as_warning_and_save_still_possible(self):
        first_release = self.release_service.create_release(
            ReleasePayload(
                title="Existing Release",
                primary_artist="Release Artist",
                upc="036000291452",
            )
        )
        self.assertGreater(first_release, 0)

        issues = self.release_service.validate_release(
            ReleasePayload(
                title="New Release",
                primary_artist="Release Artist",
                upc="036000291452",
            )
        )

        self.assertTrue(
            any(issue.field_name == "upc" and issue.severity == "warning" for issue in issues)
        )

        second_release = self.release_service.create_release(
            ReleasePayload(
                title="New Release",
                primary_artist="Release Artist",
                upc="036000291452",
            )
        )
        self.assertGreater(second_release, 0)

    def test_same_title_duplicate_upc_is_not_reported_as_warning(self):
        self.release_service.create_release(
            ReleasePayload(
                title="Remix Package",
                primary_artist="Artist One",
                upc="036000291452",
            )
        )

        issues = self.release_service.validate_release(
            ReleasePayload(
                title="Remix Package",
                primary_artist="Artist Two",
                upc="036000291452",
            )
        )

        self.assertFalse(
            any(issue.field_name == "upc" and issue.severity == "warning" for issue in issues)
        )

    def test_remix_family_duplicate_upc_is_not_reported_as_warning(self):
        self.release_service.create_release(
            ReleasePayload(
                title="Journeys Beyond the Finite",
                primary_artist="Artist One",
                release_type="album",
                upc="036000291452",
            )
        )

        issues = self.release_service.validate_release(
            ReleasePayload(
                title="Journeys Beyond the Finite - Remix Package",
                primary_artist="Artist Two",
                release_type="remix_package",
                upc="036000291452",
            )
        )

        self.assertFalse(
            any(issue.field_name == "upc" and issue.severity == "warning" for issue in issues)
        )

    def test_schema_migration_allows_duplicate_upc_across_inferred_releases(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.executescript(
                """
                CREATE TABLE Artists (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE Albums (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    album_art_path TEXT,
                    album_art_mime_type TEXT,
                    album_art_size_bytes INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE Tracks (
                    id INTEGER PRIMARY KEY,
                    isrc TEXT NOT NULL,
                    isrc_compact TEXT,
                    db_entry_date DATE,
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
                CREATE TABLE Licensees (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
                CREATE TABLE Licenses (
                    id INTEGER PRIMARY KEY,
                    track_id INTEGER NOT NULL,
                    licensee_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE AuditLog (
                    id INTEGER PRIMARY KEY,
                    ts TEXT NOT NULL DEFAULT (datetime('now')),
                    user TEXT,
                    action TEXT NOT NULL,
                    entity TEXT,
                    ref_id TEXT,
                    details TEXT
                );
                CREATE TABLE HistoryEntries (
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
                );
                CREATE TABLE HistoryHead (id INTEGER PRIMARY KEY CHECK(id=1), current_entry_id INTEGER);
                CREATE TABLE HistorySnapshots (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    kind TEXT NOT NULL,
                    label TEXT NOT NULL,
                    db_snapshot_path TEXT NOT NULL,
                    settings_json TEXT,
                    manifest_json TEXT
                );
                CREATE TABLE TrackArtists (
                    track_id INTEGER NOT NULL,
                    artist_id INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT 'additional',
                    PRIMARY KEY (track_id, artist_id, role)
                );
                CREATE TABLE GS1Metadata (
                    id INTEGER PRIMARY KEY,
                    track_id INTEGER NOT NULL UNIQUE,
                    contract_number TEXT
                );
                INSERT INTO Artists(id, name) VALUES (1, 'Legacy Artist');
                INSERT INTO Albums(id, title) VALUES (1, 'Release A'), (2, 'Release B');
                INSERT INTO Tracks(
                    id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, upc, catalog_number
                ) VALUES
                    (1, 'NL-ABC-26-00111', 'NLABC2600111', 'Track A1', 1, 1, '2026-03-15', 200, '036000291452', 'CAT-A'),
                    (2, 'NL-ABC-26-00112', 'NLABC2600112', 'Track B1', 1, 2, '2026-03-16', 220, '036000291452', 'CAT-B');
                PRAGMA user_version = 18;
                """
            )
            schema = DatabaseSchemaService(conn, data_root=self.data_root)
            schema.migrate_schema()

            releases = conn.execute(
                "SELECT title, upc, catalog_number FROM Releases ORDER BY id"
            ).fetchall()

            self.assertEqual(
                releases,
                [
                    ("Release A", "036000291452", "CAT-A"),
                    ("Release B", "036000291452", "CAT-B"),
                ],
            )
        finally:
            conn.close()

    def test_schema_migration_infers_releases_from_existing_album_tracks(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.executescript(
                """
                CREATE TABLE Artists (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE Albums (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    album_art_path TEXT,
                    album_art_mime_type TEXT,
                    album_art_size_bytes INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE Tracks (
                    id INTEGER PRIMARY KEY,
                    isrc TEXT NOT NULL,
                    isrc_compact TEXT,
                    db_entry_date DATE,
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
                CREATE TABLE Licensees (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
                CREATE TABLE Licenses (
                    id INTEGER PRIMARY KEY,
                    track_id INTEGER NOT NULL,
                    licensee_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE AuditLog (
                    id INTEGER PRIMARY KEY,
                    ts TEXT NOT NULL DEFAULT (datetime('now')),
                    user TEXT,
                    action TEXT NOT NULL,
                    entity TEXT,
                    ref_id TEXT,
                    details TEXT
                );
                CREATE TABLE HistoryEntries (
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
                );
                CREATE TABLE HistoryHead (id INTEGER PRIMARY KEY CHECK(id=1), current_entry_id INTEGER);
                CREATE TABLE HistorySnapshots (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    kind TEXT NOT NULL,
                    label TEXT NOT NULL,
                    db_snapshot_path TEXT NOT NULL,
                    settings_json TEXT,
                    manifest_json TEXT
                );
                CREATE TABLE TrackArtists (
                    track_id INTEGER NOT NULL,
                    artist_id INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT 'additional',
                    PRIMARY KEY (track_id, artist_id, role)
                );
                CREATE TABLE GS1Metadata (
                    id INTEGER PRIMARY KEY,
                    track_id INTEGER NOT NULL UNIQUE,
                    contract_number TEXT
                );
                INSERT INTO Artists(id, name) VALUES (1, 'Legacy Artist');
                INSERT INTO Albums(id, title) VALUES (1, 'Legacy Album');
                INSERT INTO Tracks(
                    id, isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, upc, catalog_number
                ) VALUES
                    (1, 'NL-ABC-26-00101', 'NLABC2600101', 'Legacy Track A', 1, 1, '2026-03-15', 200, '036000291452', 'CAT-1'),
                    (2, 'NL-ABC-26-00102', 'NLABC2600102', 'Legacy Track B', 1, 1, '2026-03-15', 220, '036000291452', 'CAT-1');
                PRAGMA user_version = 18;
                """
            )
            schema = DatabaseSchemaService(conn, data_root=self.data_root)
            schema.migrate_schema()

            releases = conn.execute("SELECT id, title, upc FROM Releases ORDER BY id").fetchall()
            placements = conn.execute(
                "SELECT track_id, track_number FROM ReleaseTracks ORDER BY track_number"
            ).fetchall()

            self.assertEqual(releases, [(1, "Legacy Album", "036000291452")])
            self.assertEqual(placements, [(1, 1), (2, 2)])
        finally:
            conn.close()

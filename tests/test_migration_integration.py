import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QSettings = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.constants import APP_NAME, SCHEMA_TARGET
from isrc_manager.services import (
    DatabaseSchemaService,
    DatabaseSessionService,
    LicenseService,
    TrackCreatePayload,
    TrackService,
)
from isrc_manager.services.db_access import SQLiteConnectionFactory
from isrc_manager.tasks.app_services import BackgroundAppServiceFactory
from tests._legacy_profile_builders import build_legacy_v12_profile

try:
    import ISRC_manager as app_module
except Exception as exc:  # pragma: no cover - environment-specific fallback
    app_module = None
    APP_IMPORT_ERROR = exc
else:
    APP_IMPORT_ERROR = None


def _no_catalog_background_refresh(self, *args, **kwargs):
    on_finished = kwargs.get("on_finished")
    if callable(on_finished):
        on_finished()
    return None


class MigrationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None or QSettings is None:
            raise unittest.SkipTest(f"PySide6 Qt unavailable: {QT_IMPORT_ERROR}")
        if app_module is None:
            raise unittest.SkipTest(f"ISRC_manager import unavailable: {APP_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.local_appdata = self.root / "local-appdata"
        self.data_root = self.local_appdata / APP_NAME
        self.qt_settings_root = self.root / "qt-settings"
        self.db_path = self.root / "Database" / "library.db"
        self.settings_path = self.root / "settings.ini"
        self._patchers = [
            mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.local_appdata)}, clear=False),
            mock.patch.object(
                app_module.QStandardPaths,
                "writableLocation",
                side_effect=self._fake_writable_location,
            ),
            mock.patch.object(
                app_module.App,
                "_refresh_catalog_ui_in_background",
                _no_catalog_background_refresh,
            ),
        ]
        for patcher in self._patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(getattr(self, "_patchers", [])):
            patcher.stop()
        self.tmpdir.cleanup()

    def _fake_writable_location(self, location):
        location_name = getattr(location, "name", str(location)).replace("/", "_")
        path = self.qt_settings_root / location_name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _initialize_profile(self) -> None:
        session = DatabaseSessionService().open(self.db_path)
        try:
            schema = DatabaseSchemaService(session.conn, data_root=self.data_root)
            schema.init_db()
            schema.migrate_schema()
        finally:
            DatabaseSessionService.close(session.conn)

    def test_app_open_database_migrates_legacy_v12_profile_fixture(self):
        legacy_path = self.root / "legacy-v12.db"
        build_legacy_v12_profile(legacy_path)

        window = app_module.App()
        try:
            window.open_database(str(legacy_path))

            self.assertEqual(window.schema_service.get_db_version(), SCHEMA_TARGET)
            snapshot = window.track_service.fetch_track_snapshot(1)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.catalog_number, "CAT-LEGACY-01")
            self.assertEqual(snapshot.buma_work_number, "BUMA-LEGACY-99")
            self.assertTrue(str(snapshot.audio_file_path).startswith("track_media/audio/"))
            self.assertTrue(str(snapshot.album_art_path).startswith("track_media/images/"))
            self.assertTrue((Path(self.data_root) / str(snapshot.audio_file_path)).exists())
            self.assertTrue((Path(self.data_root) / str(snapshot.album_art_path)).exists())
            self.assertEqual(
                (Path(self.data_root) / str(snapshot.audio_file_path)).read_bytes(),
                b"WAVE",
            )
            self.assertEqual(
                (Path(self.data_root) / str(snapshot.album_art_path)).read_bytes(),
                b"PNG!",
            )
            self.assertEqual(
                window.conn.execute("SELECT COUNT(*) FROM CustomFieldDefs").fetchone()[0],
                0,
            )
            self.assertEqual(
                window.conn.execute("SELECT COUNT(*) FROM CustomFieldValues").fetchone()[0],
                0,
            )
        finally:
            window.close()
            window._close_database_connection()
            window.deleteLater()
            self.app.processEvents()

    def test_background_bundle_migrates_legacy_license_archive_on_disk(self):
        self._initialize_profile()
        session = DatabaseSessionService().open(self.db_path)
        try:
            schema = DatabaseSchemaService(session.conn, data_root=self.data_root)
            schema.init_db()
            schema.migrate_schema()
            track_service = TrackService(session.conn, self.data_root)
            track_id = track_service.create_track(
                TrackCreatePayload(
                    isrc="NL-ABC-26-00991",
                    track_title="Legacy Signal",
                    artist_name="Migration Artist",
                    additional_artists=[],
                    album_title="Migration Album",
                    release_date="2026-03-16",
                    track_length_sec=210,
                    iswc=None,
                    upc="036000291452",
                    genre="Pop",
                )
            )
            source_pdf = self.root / "legacy-license.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\nlegacy integration\n")
            license_service = LicenseService(session.conn, self.data_root)
            license_service.add_license(
                track_id=track_id,
                licensee_name="Legacy Label",
                source_pdf_path=source_pdf,
            )
        finally:
            DatabaseSessionService.close(session.conn)

        settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        settings.setFallbacksEnabled(False)
        settings.sync()

        factory = BackgroundAppServiceFactory(
            connection_factory=SQLiteConnectionFactory(),
            data_root=self.data_root,
            history_dir=self.root / "history",
            backups_dir=self.root / "backups",
            settings_path=self.settings_path,
            db_path=self.db_path,
        )

        with factory.open_bundle() as bundle:
            result = bundle.license_migration_service.migrate_all()

        self.assertEqual(result.migrated_license_count, 1)
        self.assertEqual(result.created_contract_count, 1)
        self.assertEqual(result.created_document_count, 1)

        with factory.open_bundle() as bundle:
            contracts = bundle.contract_service.list_contracts()
            self.assertEqual(len(contracts), 1)
            detail = bundle.contract_service.fetch_contract_detail(contracts[0].id)
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail.track_ids, [1])
            self.assertEqual(len(detail.parties), 1)
            self.assertEqual(detail.parties[0].party_name, "Legacy Label")
            self.assertEqual(len(detail.documents), 1)
            document_path = bundle.contract_service.resolve_document_path(
                detail.documents[0].file_path
            )
            self.assertIsNotNone(document_path)
            assert document_path is not None
            self.assertTrue(document_path.exists())
            self.assertEqual(document_path.read_bytes(), b"%PDF-1.4\nlegacy integration\n")
            self.assertEqual(bundle.license_service.list_rows(), [])
            self.assertEqual(
                bundle.conn.execute("SELECT COUNT(*) FROM Licensees").fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()

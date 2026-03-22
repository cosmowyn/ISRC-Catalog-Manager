import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QWidget
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QWidget = None
    QSettings = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.history import HistoryManager
from isrc_manager.history.dialogs import HistoryCleanupDialog, HistoryDialog
from isrc_manager.services import DatabaseSchemaService, SettingsMutationService, SettingsReadService


class _EmptySessionHistory:
    def list_entries(self):
        return []


class _FakeHistoryApp(QWidget):
    def __init__(self, history_manager: HistoryManager, settings_reads=None):
        super().__init__()
        self.history_manager = history_manager
        self.session_history_manager = _EmptySessionHistory()
        self.settings_reads = settings_reads
        self.history_dialog = None

    def _get_best_history_candidate(self, direction: str):
        if direction == "undo":
            entry = self.history_manager.get_current_visible_entry()
        else:
            entry = self.history_manager.get_default_redo_entry()
        return ("profile", entry) if entry is not None else (None, None)

    def open_help_dialog(self, **_kwargs):
        return None

    def history_undo(self):
        return None

    def history_redo(self):
        return None

    def create_manual_snapshot(self):
        return None

    def restore_snapshot_from_history(self, _snapshot_id: int):
        return None

    def delete_snapshot_from_history(self, _snapshot_id: int):
        return None

    def delete_backup_from_history(self, _backup_id: int):
        return None

    def _refresh_history_actions(self):
        return None


class HistoryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def test_history_dialog_shows_visible_history_entries_and_backups_tab(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "library.db"
            conn = sqlite3.connect(db_path)
            settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)
            settings.setFallbacksEnabled(False)
            try:
                schema = DatabaseSchemaService(conn)
                schema.init_db()
                schema.migrate_schema()
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_kv (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                    """
                )
                conn.commit()
                history = HistoryManager(
                    conn,
                    settings,
                    db_path,
                    root / "history",
                )

                visible_key = "display/action_ribbon_visible"
                hidden_key = "display/catalog_table_panel"
                settings.setValue(visible_key, False)
                settings.setValue(hidden_key, False)
                settings.sync()

                before_visible = history.capture_setting_states([visible_key])
                settings.setValue(visible_key, True)
                settings.sync()
                after_visible = history.capture_setting_states([visible_key])
                history.record_setting_bundle_change(
                    label="Update Settings",
                    before_entries=before_visible,
                    after_entries=after_visible,
                    entity_id=visible_key,
                    visible_in_history=True,
                )

                before_hidden = history.capture_setting_states([hidden_key])
                settings.setValue(hidden_key, True)
                settings.sync()
                after_hidden = history.capture_setting_states([hidden_key])
                history.record_setting_bundle_change(
                    label="Internal UI Sync",
                    before_entries=before_hidden,
                    after_entries=after_hidden,
                    entity_id=hidden_key,
                    visible_in_history=False,
                )
                backup_path = root / "backup.db"
                conn.commit()
                sqlite3.connect(str(backup_path)).close()
                history.register_backup(
                    backup_path,
                    kind="manual",
                    label="Dialog Backup",
                    source_db_path=db_path,
                )

                fake_app = _FakeHistoryApp(history)
                dialog = HistoryDialog(fake_app)
                try:
                    self.assertEqual(dialog.property("role"), "panel")
                    self.assertEqual(dialog.session_table.rowCount(), 0)
                    self.assertEqual(dialog.history_table.rowCount(), 1)
                    self.assertEqual(dialog.history_table.item(0, 2).text(), "Update Settings")
                    self.assertEqual(dialog.history_table.item(0, 3).text(), "settings.bundle")
                    self.assertEqual(dialog.tabs.tabText(3), "Backups")
                    self.assertEqual(dialog.backup_table.rowCount(), 1)
                    self.assertEqual(dialog.backup_table.item(0, 2).text(), "Dialog Backup")
                    self.assertEqual(dialog.cleanup_btn.text(), "Cleanup…")
                finally:
                    dialog.close()
                    fake_app.close()
            finally:
                settings.clear()
                settings.sync()
                conn.close()

    def test_history_cleanup_dialog_summary_includes_budget_usage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "library.db"
            conn = sqlite3.connect(db_path)
            settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)
            settings.setFallbacksEnabled(False)
            try:
                schema = DatabaseSchemaService(conn)
                schema.init_db()
                schema.migrate_schema()
                history = HistoryManager(
                    conn,
                    settings,
                    db_path,
                    root / "history",
                )
                mutations = SettingsMutationService(conn, settings)
                mutations.set_history_retention_mode("lean")
                mutations.set_history_storage_budget_mb(1)
                history.capture_snapshot(kind="auto_interval", label="Dialog Auto Snapshot")

                fake_app = _FakeHistoryApp(history, settings_reads=SettingsReadService(conn))
                dialog = HistoryCleanupDialog(fake_app)
                try:
                    text = dialog.summary_label.text()
                    self.assertIn("History storage is using", text)
                    self.assertIn("budget", text)
                finally:
                    dialog.close()
                    fake_app.close()
            finally:
                settings.clear()
                settings.sync()
                conn.close()


if __name__ == "__main__":
    unittest.main()

import unittest

try:
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QTabWidget
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QDialogButtonBox = None
    QTabWidget = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.assets.dialogs import AssetEditorDialog
from isrc_manager.contracts.dialogs import ContractEditorDialog
from isrc_manager.releases.dialogs import ReleaseBrowserDialog
from isrc_manager.rights.dialogs import RightEditorDialog
from isrc_manager.search.dialogs import GlobalSearchDialog
from isrc_manager.works.dialogs import WorkEditorDialog


class _EmptyReleaseService:
    def list_releases(self, search_text=""):
        return []


class _EmptyPartyService:
    def list_parties(self):
        return []


class _EmptyContractService:
    def list_contracts(self):
        return []


class _EmptySearchService:
    def list_saved_searches(self):
        return []

    def search(self, *_args, **_kwargs):
        return []


class _EmptyRelationshipService:
    def describe_links(self, *_args, **_kwargs):
        return []


class RepertoireDialogSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def test_work_editor_uses_two_tab_layout(self):
        dialog = WorkEditorDialog(
            work_service=object(),
            track_title_resolver=lambda track_id: f"Track {track_id}",
            selected_track_ids_provider=lambda: [],
        )
        try:
            tabs = dialog.findChild(QTabWidget)
            self.assertIsNotNone(tabs)
            self.assertEqual(tabs.count(), 2)
        finally:
            dialog.close()

    def test_contract_editor_uses_tabbed_sections(self):
        dialog = ContractEditorDialog(contract_service=object())
        try:
            tabs = dialog.findChild(QTabWidget)
            self.assertIsNotNone(tabs)
            self.assertEqual(tabs.count(), 4)
            buttons = dialog.findChild(QDialogButtonBox)
            self.assertIsNotNone(buttons)
        finally:
            dialog.close()

    def test_right_editor_builds_reference_tabs(self):
        dialog = RightEditorDialog(
            rights_service=object(),
            party_service=_EmptyPartyService(),
            contract_service=_EmptyContractService(),
        )
        try:
            tabs = dialog.findChild(QTabWidget)
            self.assertIsNotNone(tabs)
            self.assertEqual(tabs.count(), 2)
            self.assertEqual(dialog.contract_combo.count(), 1)
        finally:
            dialog.close()

    def test_asset_editor_uses_scrollable_sections(self):
        dialog = AssetEditorDialog(asset_service=object())
        try:
            self.assertTrue(dialog.file_edit.isReadOnly())
            buttons = dialog.findChild(QDialogButtonBox)
            self.assertIsNotNone(buttons)
        finally:
            dialog.close()

    def test_release_browser_initializes_cleanly_with_empty_service(self):
        dialog = ReleaseBrowserDialog(
            release_service=_EmptyReleaseService(),
            track_title_resolver=lambda track_id: f"Track {track_id}",
        )
        try:
            self.assertEqual(dialog.release_count_label.text(), "0 releases shown.")
            self.assertEqual(dialog.track_table.columnCount(), 4)
        finally:
            dialog.close()

    def test_global_search_dialog_uses_results_and_relationship_tabs(self):
        dialog = GlobalSearchDialog(
            search_service=_EmptySearchService(),
            relationship_service=_EmptyRelationshipService(),
        )
        try:
            tabs = dialog.findChild(QTabWidget)
            self.assertIsNotNone(tabs)
            self.assertEqual(tabs.count(), 2)
            self.assertIn("Enter a query", dialog.results_status_label.text())
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()

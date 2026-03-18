import unittest

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtWidgets import (
        QComboBox,
        QDialogButtonBox,
        QLineEdit,
        QScrollArea,
        QTabWidget,
    )

    from isrc_manager.assets.dialogs import AssetEditorDialog
    from isrc_manager.contracts.dialogs import ContractEditorDialog
    from isrc_manager.parties.dialogs import PartyEditorDialog
    from isrc_manager.releases.dialogs import ReleaseBrowserDialog, ReleaseEditorDialog
    from isrc_manager.rights.dialogs import RightEditorDialog
    from isrc_manager.search.dialogs import GlobalSearchDialog
    from isrc_manager.selection_scope import SelectionScopeBanner
    from isrc_manager.works.dialogs import WorkBrowserDialog, WorkEditorDialog
except Exception as exc:  # pragma: no cover - environment-specific fallback
    REPERTOIRE_IMPORT_ERROR = exc
else:
    REPERTOIRE_IMPORT_ERROR = None


class _EmptyReleaseService:
    def list_releases(self, search_text=""):
        return []


class _EmptyPartyService:
    def list_parties(self):
        return []


class _EmptyContractService:
    def list_contracts(self):
        return []


class _EmptyWorkService:
    def list_works(self, **_kwargs):
        return []


class _EmptySearchService:
    def list_saved_searches(self):
        return []

    def search(self, *_args, **_kwargs):
        return []

    def browse_default_view(self, *_args, **_kwargs):
        return []


class _EmptyRelationshipService:
    def describe_links(self, *_args, **_kwargs):
        return []


class RepertoireDialogSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if REPERTOIRE_IMPORT_ERROR is not None:
            raise unittest.SkipTest(
                f"Repertoire dialog modules unavailable: {REPERTOIRE_IMPORT_ERROR}"
            )
        cls.app = require_qapplication()

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
            self.assertLess(dialog.documents_editor.minimumSizeHint().width(), 960)
            self.assertTrue(hasattr(dialog.work_ids_edit, "value_ids"))
            self.assertTrue(hasattr(dialog.track_ids_edit, "value_ids"))
            self.assertTrue(hasattr(dialog.release_ids_edit, "value_ids"))
            self.assertFalse(isinstance(dialog.work_ids_edit, QLineEdit))
            self.assertFalse(isinstance(dialog.documents_editor.supersedes_edit, QLineEdit))
            self.assertFalse(isinstance(dialog.documents_editor.superseded_by_edit, QLineEdit))
            self.assertIsInstance(dialog.documents_editor.detail_scroll_area, QScrollArea)
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

    def test_asset_editor_uses_tabbed_sections(self):
        dialog = AssetEditorDialog(asset_service=object())
        try:
            self.assertTrue(dialog.file_edit.isReadOnly())
            tabs = dialog.findChild(QTabWidget, "assetEditorTabs")
            self.assertIsNotNone(tabs)
            self.assertEqual(
                [tabs.tabText(index) for index in range(tabs.count())],
                [
                    "Target",
                    "Source",
                    "Notes",
                ],
            )
            buttons = dialog.findChild(QDialogButtonBox)
            self.assertIsNotNone(buttons)
            self.assertIsInstance(dialog.track_id_edit, QComboBox)
            self.assertTrue(dialog.track_id_edit.isEditable())
            self.assertIsInstance(dialog.release_id_edit, QComboBox)
            self.assertTrue(dialog.release_id_edit.isEditable())
        finally:
            dialog.close()

    def test_party_editor_uses_identity_contact_and_notes_tabs(self):
        dialog = PartyEditorDialog(party_service=object())
        try:
            tabs = dialog.findChild(QTabWidget, "partyEditorTabs")
            self.assertIsNotNone(tabs)
            self.assertEqual(
                [tabs.tabText(index) for index in range(tabs.count())],
                [
                    "Identity",
                    "Contact",
                    "Notes",
                ],
            )
            buttons = dialog.findChild(QDialogButtonBox)
            self.assertIsNotNone(buttons)
            scroll_areas = dialog.findChildren(QScrollArea)
            self.assertTrue(scroll_areas)
        finally:
            dialog.close()

    def test_release_editor_uses_editable_combos_for_safe_metadata_fields(self):
        dialog = ReleaseEditorDialog(
            release_service=object(),
            track_title_resolver=lambda track_id: f"Track {track_id}",
            selected_track_ids_provider=lambda: [],
        )
        try:
            self.assertIsInstance(dialog.primary_artist_edit, QComboBox)
            self.assertTrue(dialog.primary_artist_edit.isEditable())
            self.assertIsInstance(dialog.album_artist_edit, QComboBox)
            self.assertTrue(dialog.album_artist_edit.isEditable())
            self.assertIsInstance(dialog.label_edit, QComboBox)
            self.assertTrue(dialog.label_edit.isEditable())
            self.assertIsInstance(dialog.sublabel_edit, QComboBox)
            self.assertTrue(dialog.sublabel_edit.isEditable())
            self.assertIsInstance(dialog.catalog_number_edit, QComboBox)
            self.assertTrue(dialog.catalog_number_edit.isEditable())
            self.assertIsInstance(dialog.upc_edit, QComboBox)
            self.assertTrue(dialog.upc_edit.isEditable())
            self.assertIsInstance(dialog.territory_edit, QLineEdit)
        finally:
            dialog.close()

    def test_selection_scope_banner_wraps_action_buttons_more_compactly(self):
        banner = SelectionScopeBanner()
        try:
            self.assertLess(banner.minimumSizeHint().width(), 380)
        finally:
            banner.close()

    def test_release_browser_initializes_cleanly_with_empty_service(self):
        dialog = ReleaseBrowserDialog(
            release_service=_EmptyReleaseService(),
            track_title_resolver=lambda track_id: f"Track {track_id}",
        )
        try:
            self.assertEqual(dialog.release_count_label.text(), "0 releases shown.")
            self.assertEqual(dialog.track_table.columnCount(), 4)
            self.assertIsInstance(dialog.detail_scroll_area, QScrollArea)
            self.assertIsNotNone(dialog.actions_cluster)
        finally:
            dialog.close()

    def test_work_browser_uses_action_cluster_for_top_controls(self):
        dialog = WorkBrowserDialog(
            work_service=_EmptyWorkService(),
            track_title_resolver=lambda track_id: f"Track {track_id}",
            selected_track_ids_provider=lambda: [],
        )
        try:
            self.assertIsNotNone(dialog.manage_actions_cluster)
            self.assertGreaterEqual(dialog.manage_actions_cluster.minimumSizeHint().width(), 0)
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
            self.assertIn("No catalog records", dialog.results_status_label.text())
            self.assertIsInstance(dialog.saved_searches_scroll_area, QScrollArea)
            self.assertIsNotNone(dialog.delete_saved_button)
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()

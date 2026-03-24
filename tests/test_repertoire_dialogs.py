import unittest
import sqlite3
import tempfile
from pathlib import Path

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtWidgets import (
        QComboBox,
        QDialogButtonBox,
        QGroupBox,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QScrollArea,
        QTabWidget,
        QWidget,
    )

    from isrc_manager.assets.dialogs import AssetBrowserPanel, AssetEditorDialog
    from isrc_manager.media.derivatives import DerivativeLedgerService
    from isrc_manager.contracts.dialogs import ContractEditorDialog
    from isrc_manager.parties.dialogs import PartyEditorDialog
    from isrc_manager.releases.dialogs import ReleaseBrowserDialog, ReleaseEditorDialog
    from isrc_manager.services import (
        AssetService,
        DatabaseSchemaService,
        ReleasePayload,
        ReleaseService,
        ReleaseTrackPlacement,
        TrackCreatePayload,
        TrackService,
    )
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


class _DerivativeLedgerHost(QWidget):
    def __init__(self, release_service):
        super().__init__()
        self.release_service = release_service
        self.opened_track_ids: list[int] = []
        self.opened_release_ids: list[int] = []
        self.verified_paths: list[str] = []

    def open_selected_editor(self, track_id: int):
        self.opened_track_ids.append(int(track_id))

    def open_release_editor(self, release_id: int):
        self.opened_release_ids.append(int(release_id))

    def verify_audio_authenticity(self, path: str):
        self.verified_paths.append(str(path))


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
            self.assertTrue(hasattr(dialog.obligations_editor, "obligations"))
            self.assertFalse(isinstance(dialog.work_ids_edit, QLineEdit))
            self.assertFalse(isinstance(dialog.obligations_editor, QPlainTextEdit))
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

    def test_release_editor_uses_compact_grouped_metadata_sections(self):
        dialog = ReleaseEditorDialog(
            release_service=object(),
            track_title_resolver=lambda track_id: f"Track {track_id}",
            selected_track_ids_provider=lambda: [],
        )
        try:
            dialog.show()
            self.app.processEvents()
            self.assertEqual(dialog.objectName(), "releaseEditorDialog")
            self.assertEqual(dialog.minimumWidth(), 880)
            self.assertEqual(dialog.minimumHeight(), 640)
            self.assertEqual(dialog.width(), 960)
            self.assertEqual(dialog.height(), 720)
            self.assertEqual(
                dialog.artwork_storage_mode_combo.itemText(0),
                "Stored in Database",
            )
            self.assertEqual(
                dialog.artwork_storage_mode_combo.itemText(1),
                "Managed File",
            )
            group_titles = {group.title() for group in dialog.findChildren(QGroupBox)}
            self.assertTrue(
                {
                    "Identity & Credits",
                    "Release Details",
                    "Artwork & Notes",
                }.issubset(group_titles)
            )
            self.assertTrue(
                any(label.text() == dialog.windowTitle() for label in dialog.findChildren(QLabel))
            )
        finally:
            dialog.close()

    def test_asset_browser_exposes_derivative_ledger_drill_ins(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            conn = sqlite3.connect(":memory:")
            try:
                schema = DatabaseSchemaService(conn, data_root=data_root)
                schema.init_db()
                schema.migrate_schema()
                track_service = TrackService(conn, data_root=data_root)
                release_service = ReleaseService(conn, data_root=data_root)
                asset_service = AssetService(conn, data_root=data_root)

                track_id = track_service.create_track(
                    TrackCreatePayload(
                        isrc="NL-TST-26-09991",
                        track_title="Ledger Drill In",
                        artist_name="Cosmowyn",
                        additional_artists=[],
                        album_title="Ledger Release",
                        release_date="2026-03-24",
                        track_length_sec=245,
                        iswc=None,
                        upc=None,
                        genre="Ambient",
                        catalog_number=None,
                    )
                )
                release_id = release_service.create_release(
                    ReleasePayload(
                        title="Ledger Release",
                        primary_artist="Cosmowyn",
                        release_date="2026-03-24",
                        placements=[ReleaseTrackPlacement(track_id=track_id)],
                    )
                )
                output_path = data_root / "exports" / "ledger-output.wav"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"RIFFledger-output")

                ledger_service = DerivativeLedgerService(conn)
                batch_id = ledger_service.create_batch(
                    batch_public_id="AEX-LEDGER-DRILLIN-01",
                    track_count=1,
                    output_format="wav",
                    workflow_kind="managed_audio_derivative",
                    derivative_kind="watermark_authentic",
                    authenticity_basis="direct_watermark",
                    profile_name="catalog.db",
                )
                ledger_service.create_derivative(
                    source_track_id=track_id,
                    export_batch_id=batch_id,
                    workflow_kind="managed_audio_derivative",
                    derivative_kind="watermark_authentic",
                    authenticity_basis="direct_watermark",
                    output_format="wav",
                    watermark_applied=True,
                    metadata_embedded=True,
                    final_sha256="b" * 64,
                    output_filename=output_path.name,
                    source_lineage_ref="track-audio:ledger-source.wav",
                    source_sha256="c" * 64,
                    source_storage_mode="database",
                    authenticity_manifest_id="manifest-ledger-001",
                    output_size_bytes=output_path.stat().st_size,
                    filename_hash_suffix="ledgerdrillin",
                    managed_file_path=str(output_path),
                )
                conn.commit()

                host = _DerivativeLedgerHost(release_service)
                panel = AssetBrowserPanel(
                    asset_service_provider=lambda: asset_service,
                    drill_in_host_provider=lambda: host,
                )
                try:
                    panel.focus_derivative_batch(batch_id)
                    self.app.processEvents()

                    ledger_tab = panel.derivative_ledger_tab
                    self.assertEqual(
                        [panel.workspace_tabs.tabText(index) for index in range(panel.workspace_tabs.count())],
                        ["Asset Registry", "Derivative Ledger"],
                    )
                    self.assertTrue(ledger_tab.open_track_button.isEnabled())
                    self.assertTrue(ledger_tab.open_release_button.isEnabled())
                    self.assertTrue(ledger_tab.verify_authenticity_button.isEnabled())

                    ledger_tab.open_track_button.click()
                    ledger_tab.open_release_button.click()
                    ledger_tab.verify_authenticity_button.click()

                    self.assertEqual(host.opened_track_ids, [track_id])
                    self.assertEqual(host.opened_release_ids, [release_id])
                    self.assertEqual(host.verified_paths, [str(output_path)])
                    self.assertIn(str(output_path), ledger_tab.details_edit.toPlainText())
                finally:
                    panel.close()
                    host.close()
            finally:
                conn.close()

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

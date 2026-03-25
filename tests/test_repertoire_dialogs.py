import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QComboBox,
        QDialogButtonBox,
        QGroupBox,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPlainTextEdit,
        QScrollArea,
        QSplitter,
        QTabWidget,
        QWidget,
    )

    from isrc_manager.assets.dialogs import AssetBrowserPanel, AssetEditorDialog
    from isrc_manager.contracts.dialogs import ContractEditorDialog
    from isrc_manager.media.derivatives import DerivativeLedgerService
    from isrc_manager.parties import PartyPayload, PartyService
    from isrc_manager.parties.dialogs import PartyEditorDialog, PartyManagerPanel
    from isrc_manager.releases.dialogs import ReleaseBrowserDialog, ReleaseEditorDialog
    from isrc_manager.rights.dialogs import RightEditorDialog
    from isrc_manager.search.dialogs import GlobalSearchDialog
    from isrc_manager.selection_scope import SelectionScopeBanner
    from isrc_manager.services import (
        AssetService,
        DatabaseSchemaService,
        ReleasePayload,
        ReleaseService,
        ReleaseTrackPlacement,
        TrackCreatePayload,
        TrackService,
    )
    from isrc_manager.ui_common import _confirm_destructive_action
    from isrc_manager.works import WorkContributorPayload, WorkService
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

    def test_work_editor_round_trips_party_linked_contributor_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = sqlite3.connect(":memory:")
            try:
                schema = DatabaseSchemaService(conn, data_root=Path(tmpdir))
                schema.init_db()
                schema.migrate_schema()
                party_service = PartyService(conn)
                work_service = WorkService(conn, party_service=party_service)
                party_id = party_service.create_party(
                    PartyPayload(
                        legal_name="North Star Music Publishing B.V.",
                        display_name="North Star Publishing",
                        party_type="publisher",
                    )
                )

                dialog = WorkEditorDialog(
                    work_service=work_service,
                    track_title_resolver=lambda track_id: f"Track {track_id}",
                    selected_track_ids_provider=lambda: [],
                    contributors=[
                        WorkContributorPayload(
                            role="publisher",
                            name="North Star Publishing",
                            share_percent=100,
                            role_share_percent=100,
                            party_id=party_id,
                        )
                    ],
                )
                try:
                    contributor_combo = dialog.contributors_table.cellWidget(0, 0)
                    self.assertIsInstance(contributor_combo, QComboBox)
                    self.assertTrue(contributor_combo.isEditable())
                    self.assertEqual(contributor_combo.currentData(), party_id)

                    payload = dialog.payload()
                    self.assertEqual(len(payload.contributors), 1)
                    self.assertEqual(payload.contributors[0].party_id, party_id)
                    self.assertEqual(payload.contributors[0].name, "North Star Publishing")
                    self.assertEqual(payload.contributors[0].role, "publisher")
                    self.assertEqual(payload.contributors[0].share_percent, 100.0)
                    self.assertEqual(payload.contributors[0].role_share_percent, 100.0)
                finally:
                    dialog.close()
            finally:
                conn.close()

    def test_work_editor_preserves_typed_contributor_name_without_party_selection(self):
        dialog = WorkEditorDialog(
            work_service=object(),
            track_title_resolver=lambda track_id: f"Track {track_id}",
            selected_track_ids_provider=lambda: [],
        )
        try:
            dialog._add_contributor_row()
            contributor_combo = dialog.contributors_table.cellWidget(0, 0)
            self.assertIsInstance(contributor_combo, QComboBox)
            contributor_combo.setEditText("Unregistered Writer")
            share_item = dialog.contributors_table.item(0, 2)
            role_share_item = dialog.contributors_table.item(0, 3)
            assert share_item is not None
            assert role_share_item is not None
            share_item.setText("50")
            role_share_item.setText("100")

            payload = dialog.payload()
            self.assertEqual(len(payload.contributors), 1)
            self.assertIsNone(payload.contributors[0].party_id)
            self.assertEqual(payload.contributors[0].name, "Unregistered Writer")
            self.assertEqual(payload.contributors[0].role, "songwriter")
            self.assertEqual(payload.contributors[0].share_percent, 50.0)
            self.assertEqual(payload.contributors[0].role_share_percent, 100.0)
        finally:
            dialog.close()

    def test_contract_editor_uses_tabbed_sections(self):
        dialog = ContractEditorDialog(contract_service=object())
        try:
            tabs = dialog.findChild(QTabWidget)
            self.assertIsNotNone(tabs)
            self.assertEqual(tabs.count(), 4)
            self.assertEqual(
                [tabs.tabText(index) for index in range(tabs.count())],
                [
                    "Overview",
                    "Links and Parties",
                    "Obligations",
                    "Documents",
                ],
            )
            buttons = dialog.findChild(QDialogButtonBox)
            self.assertIsNotNone(buttons)
            self.assertTrue(hasattr(dialog.work_ids_edit, "value_ids"))
            self.assertTrue(hasattr(dialog.track_ids_edit, "value_ids"))
            self.assertTrue(hasattr(dialog.release_ids_edit, "value_ids"))
            self.assertTrue(hasattr(dialog.parties_edit, "value"))
            self.assertTrue(hasattr(dialog.obligations_editor, "obligations"))
            self.assertFalse(isinstance(dialog.work_ids_edit, QLineEdit))
            self.assertFalse(isinstance(dialog.parties_edit, QPlainTextEdit))
            self.assertFalse(isinstance(dialog.obligations_editor, QPlainTextEdit))
            self.assertFalse(isinstance(dialog.documents_editor.supersedes_edit, QLineEdit))
            self.assertFalse(isinstance(dialog.documents_editor.superseded_by_edit, QLineEdit))
            self.assertIsInstance(dialog.documents_editor.detail_scroll_area, QScrollArea)
            self.assertEqual(
                dialog.documents_editor.actions_cluster.objectName(),
                "contractDocumentActionsCluster",
            )
            self.assertEqual(
                dialog.documents_editor.detail_scroll_area.objectName(),
                "contractDocumentDetailScrollArea",
            )
            self.assertIsNotNone(
                dialog.documents_editor.findChild(QSplitter, "contractDocumentEditorSplitter")
            )
            self.assertIsNotNone(dialog.findChild(QSplitter, "contractLinksPartiesSplitter"))
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

    def test_party_editor_uses_structured_tabs_and_alias_editor(self):
        dialog = PartyEditorDialog(party_service=object())
        try:
            tabs = dialog.findChild(QTabWidget, "partyEditorTabs")
            self.assertIsNotNone(tabs)
            self.assertEqual(
                [tabs.tabText(index) for index in range(tabs.count())],
                [
                    "Identity",
                    "Artist Aliases",
                    "Address",
                    "Contact",
                    "Business / Legal",
                    "Notes",
                ],
            )
            buttons = dialog.findChild(QDialogButtonBox)
            self.assertIsNotNone(buttons)
            scroll_areas = dialog.findChildren(QScrollArea)
            self.assertTrue(scroll_areas)
            self.assertIsInstance(dialog.artist_name_edit, QLineEdit)
            self.assertIsInstance(dialog.company_name_edit, QLineEdit)
            self.assertIsInstance(dialog.alternative_email_edit, QLineEdit)
            self.assertIsInstance(dialog.bank_account_edit, QLineEdit)
            self.assertEqual(dialog.alias_table.columnCount(), 1)
        finally:
            dialog.close()

    def test_party_editor_round_trips_expanded_fields_and_aliases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = sqlite3.connect(":memory:")
            try:
                schema = DatabaseSchemaService(conn, data_root=Path(tmpdir))
                schema.init_db()
                schema.migrate_schema()
                party_service = PartyService(conn)
                party_id = party_service.create_party(
                    PartyPayload(
                        legal_name="Aeonium Holdings B.V.",
                        display_name="Aeonium",
                        artist_name="Aeonium Official",
                        company_name="Aeonium Holdings",
                        first_name="Lyra",
                        middle_name="Van",
                        last_name="Moonwake",
                        party_type="licensee",
                        contact_person="Lyra Moonwake",
                        email="hello@moonium.test",
                        alternative_email="legal@moonium.test",
                        phone="+31 20 555 0101",
                        street_name="Main Street",
                        street_number="12A",
                        city="Amsterdam",
                        postal_code="1012AB",
                        country="NL",
                        bank_account_number="NL91TEST0123456789",
                        chamber_of_commerce_number="CoC-778899",
                        vat_number="NL001122334B01",
                        pro_affiliation="BUMA/STEMRA",
                        pro_number="PRO-778899",
                        ipi_cae="IPI-778899",
                        artist_aliases=["Aeonium", "Lyra C."],
                    )
                )
                party = party_service.fetch_party(party_id)
                assert party is not None

                dialog = PartyEditorDialog(party_service=party_service, party=party)
                try:
                    self.assertEqual(dialog.artist_name_edit.text(), "Aeonium Official")
                    self.assertEqual(dialog.company_name_edit.text(), "Aeonium Holdings")
                    self.assertEqual(dialog.alternative_email_edit.text(), "legal@moonium.test")
                    self.assertEqual(dialog.bank_account_edit.text(), "NL91TEST0123456789")
                    self.assertEqual(dialog.alias_table.rowCount(), 2)

                    dialog.alias_edit.setText("Lyra Cosmos")
                    dialog._add_alias()
                    payload = dialog.payload()

                    self.assertEqual(payload.artist_name, "Aeonium Official")
                    self.assertEqual(payload.company_name, "Aeonium Holdings")
                    self.assertEqual(payload.alternative_email, "legal@moonium.test")
                    self.assertEqual(payload.chamber_of_commerce_number, "CoC-778899")
                    self.assertEqual(
                        payload.artist_aliases,
                        ["Aeonium", "Lyra C.", "Lyra Cosmos"],
                    )
                finally:
                    dialog.close()
            finally:
                conn.close()

    def test_party_manager_panel_filters_by_type_and_alias_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = sqlite3.connect(":memory:")
            try:
                schema = DatabaseSchemaService(conn, data_root=Path(tmpdir))
                schema.init_db()
                schema.migrate_schema()
                party_service = PartyService(conn)
                party_service.create_party(
                    PartyPayload(
                        legal_name="Aeonium Holdings B.V.",
                        artist_name="Aeonium Official",
                        party_type="licensee",
                        email="licensing@moonium.test",
                        artist_aliases=["Aeonium"],
                    )
                )
                party_service.create_party(
                    PartyPayload(
                        legal_name="North Star Music B.V.",
                        display_name="North Star",
                        party_type="label",
                        email="hello@northstar.test",
                    )
                )

                panel = PartyManagerPanel(party_service_provider=lambda: party_service)
                try:
                    self.assertEqual(panel.table.rowCount(), 2)
                    panel.search_edit.setText("Aeonium")
                    self.app.processEvents()
                    self.assertEqual(panel.table.rowCount(), 1)
                    self.assertEqual(panel.table.item(0, 1).text(), "Aeonium Official")

                    panel.search_edit.clear()
                    label_index = panel.party_type_filter_combo.findData("label")
                    self.assertGreaterEqual(label_index, 0)
                    panel.party_type_filter_combo.setCurrentIndex(label_index)
                    self.app.processEvents()
                    self.assertEqual(panel.table.rowCount(), 1)
                    self.assertEqual(panel.table.item(0, 1).text(), "North Star")
                finally:
                    panel.close()
            finally:
                conn.close()

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
                        artist_name="Moonwake",
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
                        primary_artist="Moonwake",
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
                        [
                            panel.workspace_tabs.tabText(index)
                            for index in range(panel.workspace_tabs.count())
                        ],
                        ["Asset Registry", "Derivative Ledger"],
                    )
                    self.assertEqual(
                        [
                            ledger_tab.batch_workspace_tabs.tabText(index)
                            for index in range(ledger_tab.batch_workspace_tabs.count())
                        ],
                        ["Derivatives", "Details", "Lineage", "Admin"],
                    )
                    self.assertEqual(
                        ledger_tab.workspace_splitter.objectName(),
                        "derivativeLedgerWorkspaceSplitter",
                    )
                    self.assertEqual(ledger_tab.workspace_splitter.orientation(), Qt.Horizontal)
                    self.assertEqual(
                        ledger_tab.batch_workspace_tabs.objectName(),
                        "derivativeLedgerDetailTabs",
                    )
                    self.assertEqual(
                        ledger_tab.derivative_actions_cluster.objectName(),
                        "derivativeLedgerActionsCluster",
                    )
                    self.assertEqual(
                        ledger_tab.admin_actions_cluster.objectName(),
                        "derivativeLedgerAdminActionsCluster",
                    )
                    self.assertEqual(
                        ledger_tab.details_scroll_area.objectName(),
                        "derivativeLedgerDetailsScrollArea",
                    )
                    self.assertEqual(
                        ledger_tab.lineage_scroll_area.objectName(),
                        "derivativeLedgerLineageScrollArea",
                    )
                    self.assertEqual(ledger_tab.batch_id_value.text(), batch_id)
                    self.assertEqual(ledger_tab.output_filename_value.text(), output_path.name)
                    self.assertIn(batch_id, ledger_tab.selection_label.text())
                    self.assertIn(
                        "database row",
                        ledger_tab.admin_summary_label.text().lower(),
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
                finally:
                    panel.close()
                    host.close()
            finally:
                conn.close()

    def test_derivative_ledger_filters_reduce_batches_and_keep_selection_summary_current(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            conn = sqlite3.connect(":memory:")
            try:
                schema = DatabaseSchemaService(conn, data_root=data_root)
                schema.init_db()
                schema.migrate_schema()
                track_service = TrackService(conn, data_root=data_root)
                asset_service = AssetService(conn, data_root=data_root)

                first_track_id = track_service.create_track(
                    TrackCreatePayload(
                        isrc="NL-TST-26-09993",
                        track_title="Authentic WAV",
                        artist_name="Moonwake",
                        additional_artists=[],
                        album_title="Ledger Filters",
                        release_date="2026-03-24",
                        track_length_sec=210,
                        iswc=None,
                        upc=None,
                        genre="Ambient",
                        catalog_number=None,
                    )
                )
                second_track_id = track_service.create_track(
                    TrackCreatePayload(
                        isrc="NL-TST-26-09994",
                        track_title="Lossy MP3",
                        artist_name="Moonwake",
                        additional_artists=[],
                        album_title="Ledger Filters",
                        release_date="2026-03-24",
                        track_length_sec=198,
                        iswc=None,
                        upc=None,
                        genre="Ambient",
                        catalog_number=None,
                    )
                )

                ledger_service = DerivativeLedgerService(conn)
                wav_batch_id = ledger_service.create_batch(
                    batch_public_id="AEX-LEDGER-FILTERS-01",
                    track_count=1,
                    output_format="wav",
                    workflow_kind="managed_audio_derivative",
                    derivative_kind="watermark_authentic",
                    authenticity_basis="direct_watermark",
                    profile_name="catalog.db",
                )
                ledger_service.create_derivative(
                    source_track_id=first_track_id,
                    export_batch_id=wav_batch_id,
                    workflow_kind="managed_audio_derivative",
                    derivative_kind="watermark_authentic",
                    authenticity_basis="direct_watermark",
                    output_format="wav",
                    watermark_applied=True,
                    metadata_embedded=True,
                    final_sha256="1" * 64,
                    output_filename="authentic.wav",
                    source_lineage_ref="track-audio:authentic.wav",
                    source_sha256="2" * 64,
                    source_storage_mode="database",
                    authenticity_manifest_id="manifest-filter-01",
                    output_size_bytes=10_240,
                    filename_hash_suffix="authfilter01",
                )
                ledger_service.update_batch_completion(
                    wav_batch_id,
                    exported_count=1,
                    skipped_count=0,
                    package_mode="directory",
                    status="completed",
                    zip_filename=None,
                )

                mp3_batch_id = ledger_service.create_batch(
                    batch_public_id="AEX-LEDGER-FILTERS-02",
                    track_count=1,
                    output_format="mp3",
                    workflow_kind="managed_audio_derivative",
                    derivative_kind="lossy_derivative",
                    authenticity_basis="catalog_lineage_only",
                    profile_name="catalog.db",
                )
                ledger_service.create_derivative(
                    source_track_id=second_track_id,
                    export_batch_id=mp3_batch_id,
                    workflow_kind="managed_audio_derivative",
                    derivative_kind="lossy_derivative",
                    authenticity_basis="catalog_lineage_only",
                    output_format="mp3",
                    watermark_applied=False,
                    metadata_embedded=True,
                    final_sha256="3" * 64,
                    output_filename="lossy.mp3",
                    source_lineage_ref="track-audio:lossy.mp3",
                    source_sha256="4" * 64,
                    source_storage_mode="database",
                    authenticity_manifest_id="manifest-filter-02",
                    output_size_bytes=5_120,
                    filename_hash_suffix="lossyfilter02",
                )
                conn.commit()

                panel = AssetBrowserPanel(
                    asset_service_provider=lambda: asset_service,
                    drill_in_host_provider=lambda: None,
                )
                try:
                    ledger_tab = panel.derivative_ledger_tab
                    self.assertEqual(ledger_tab.batch_table.rowCount(), 2)
                    self.assertEqual(
                        ledger_tab.format_filter_combo.objectName(),
                        "derivativeLedgerFormatFilter",
                    )
                    self.assertEqual(
                        ledger_tab.kind_filter_combo.objectName(),
                        "derivativeLedgerKindFilter",
                    )
                    self.assertEqual(
                        ledger_tab.status_filter_combo.objectName(),
                        "derivativeLedgerStatusFilter",
                    )
                    self.assertIn("Selected Batch:", ledger_tab.selected_batch_heading.text())

                    format_index = ledger_tab.format_filter_combo.findData("wav")
                    self.assertGreaterEqual(format_index, 0)
                    ledger_tab.format_filter_combo.setCurrentIndex(format_index)
                    self.app.processEvents()

                    self.assertEqual(ledger_tab.batch_table.rowCount(), 1)
                    self.assertEqual(ledger_tab.batch_id_value.text(), wav_batch_id)
                    self.assertIn(wav_batch_id, ledger_tab.selected_batch_heading.text())
                    self.assertEqual(ledger_tab.derivative_table.rowCount(), 1)
                    self.assertEqual(ledger_tab.output_filename_value.text(), "authentic.wav")

                    kind_index = ledger_tab.kind_filter_combo.findData("watermark_authentic")
                    self.assertGreaterEqual(kind_index, 0)
                    ledger_tab.kind_filter_combo.setCurrentIndex(kind_index)
                    self.app.processEvents()
                    self.assertEqual(ledger_tab.batch_table.rowCount(), 1)
                    self.assertEqual(ledger_tab.batch_id_value.text(), wav_batch_id)

                    status_index = ledger_tab.status_filter_combo.findData("pending")
                    self.assertGreaterEqual(status_index, 0)
                    ledger_tab.status_filter_combo.setCurrentIndex(status_index)
                    self.app.processEvents()

                    self.assertEqual(ledger_tab.batch_table.rowCount(), 0)
                    self.assertEqual(ledger_tab.derivative_table.rowCount(), 0)
                    self.assertEqual(ledger_tab.selected_batch_heading.text(), "Selected Batch")
                    self.assertIn("No export batch matches", ledger_tab.selection_label.text())
                finally:
                    panel.close()
            finally:
                conn.close()

    def test_derivative_ledger_admin_actions_confirm_and_preserve_files_on_disk(self):
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
                        isrc="NL-TST-26-09992",
                        track_title="Ledger Cleanup",
                        artist_name="Moonwake",
                        additional_artists=[],
                        album_title="Ledger Cleanup Release",
                        release_date="2026-03-24",
                        track_length_sec=225,
                        iswc=None,
                        upc=None,
                        genre="Ambient",
                        catalog_number=None,
                    )
                )
                release_service.create_release(
                    ReleasePayload(
                        title="Ledger Cleanup Release",
                        primary_artist="Moonwake",
                        release_date="2026-03-24",
                        placements=[ReleaseTrackPlacement(track_id=track_id)],
                    )
                )
                output_path = data_root / "exports" / "ledger-cleanup-output.wav"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"RIFFledger-cleanup")

                ledger_service = DerivativeLedgerService(conn)
                batch_id = ledger_service.create_batch(
                    batch_public_id="AEX-LEDGER-CLEANUP-01",
                    track_count=1,
                    output_format="wav",
                    workflow_kind="managed_audio_derivative",
                    derivative_kind="lossy_derivative",
                    authenticity_basis="catalog_lineage_only",
                    profile_name="catalog.db",
                )
                ledger_service.create_derivative(
                    source_track_id=track_id,
                    export_batch_id=batch_id,
                    workflow_kind="managed_audio_derivative",
                    derivative_kind="lossy_derivative",
                    authenticity_basis="catalog_lineage_only",
                    output_format="wav",
                    watermark_applied=False,
                    metadata_embedded=True,
                    final_sha256="d" * 64,
                    output_filename=output_path.name,
                    source_lineage_ref="track-audio:ledger-cleanup-source.wav",
                    source_sha256="e" * 64,
                    source_storage_mode="database",
                    authenticity_manifest_id="manifest-ledger-cleanup-001",
                    output_size_bytes=output_path.stat().st_size,
                    filename_hash_suffix="ledgercleanup01",
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
                        [
                            ledger_tab.batch_workspace_tabs.tabText(index)
                            for index in range(ledger_tab.batch_workspace_tabs.count())
                        ],
                        ["Derivatives", "Details", "Lineage", "Admin"],
                    )
                    self.assertTrue(ledger_tab.delete_derivative_button.isEnabled())
                    self.assertTrue(ledger_tab.delete_batch_button.isEnabled())

                    with mock.patch.object(
                        QMessageBox, "question", return_value=QMessageBox.No
                    ) as question:
                        ledger_tab.delete_derivative_button.click()
                    question.assert_called_once()
                    self.assertIn("not deleted", question.call_args[0][2].lower())
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM TrackAudioDerivatives").fetchone()[0],
                        1,
                    )
                    self.assertTrue(output_path.exists())

                    with mock.patch.object(
                        QMessageBox, "question", return_value=QMessageBox.Yes
                    ) as question:
                        ledger_tab.delete_derivative_button.click()
                    question.assert_called_once()
                    self.assertIn("historical export totals", question.call_args[0][2].lower())
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM TrackAudioDerivatives").fetchone()[0],
                        0,
                    )
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM DerivativeExportBatches").fetchone()[0],
                        1,
                    )
                    self.assertTrue(output_path.exists())
                    self.assertEqual(ledger_tab.batch_id_value.text(), batch_id)

                    with mock.patch.object(
                        QMessageBox, "question", return_value=QMessageBox.No
                    ) as question:
                        ledger_tab.delete_batch_button.click()
                    question.assert_called_once()
                    self.assertIn("not deleted", question.call_args[0][2].lower())
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM DerivativeExportBatches").fetchone()[0],
                        1,
                    )
                    self.assertTrue(output_path.exists())

                    with mock.patch.object(
                        QMessageBox, "question", return_value=QMessageBox.Yes
                    ) as question:
                        ledger_tab.delete_batch_button.click()
                    question.assert_called_once()
                    self.assertIn("not deleted", question.call_args[0][2].lower())
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM DerivativeExportBatches").fetchone()[0],
                        0,
                    )
                    self.assertTrue(output_path.exists())
                    self.assertEqual(ledger_tab.batch_table.rowCount(), 0)
                finally:
                    panel.close()
                    host.close()
            finally:
                conn.close()

    def test_derivative_ledger_can_delete_retained_output_files_without_removing_ledger_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            conn = sqlite3.connect(":memory:")
            try:
                schema = DatabaseSchemaService(conn, data_root=data_root)
                schema.init_db()
                schema.migrate_schema()
                track_service = TrackService(conn, data_root=data_root)
                asset_service = AssetService(conn, data_root=data_root)

                track_id = track_service.create_track(
                    TrackCreatePayload(
                        isrc="NL-TST-26-09995",
                        track_title="Retained File Cleanup",
                        artist_name="Moonwake",
                        additional_artists=[],
                        album_title="Ledger Cleanup",
                        release_date="2026-03-24",
                        track_length_sec=222,
                        iswc=None,
                        upc=None,
                        genre="Ambient",
                        catalog_number=None,
                    )
                )

                output_path = data_root / "exports" / "cleanup.wav"
                sidecar_path = data_root / "exports" / "cleanup.json"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"RIFFcleanup")
                sidecar_path.write_text('{"manifest": true}', encoding="utf-8")

                ledger_service = DerivativeLedgerService(conn)
                batch_id = ledger_service.create_batch(
                    batch_public_id="AEX-LEDGER-FILES-01",
                    track_count=1,
                    output_format="wav",
                    workflow_kind="managed_audio_derivative",
                    derivative_kind="lossless_derivative",
                    authenticity_basis="catalog_lineage_only",
                    profile_name="catalog.db",
                )
                export_id = ledger_service.create_derivative(
                    source_track_id=track_id,
                    export_batch_id=batch_id,
                    workflow_kind="managed_audio_derivative",
                    derivative_kind="lossless_derivative",
                    authenticity_basis="catalog_lineage_only",
                    output_format="wav",
                    watermark_applied=False,
                    metadata_embedded=True,
                    final_sha256="6" * 64,
                    output_filename="cleanup.wav",
                    source_lineage_ref="track-audio:cleanup.wav",
                    source_sha256="7" * 64,
                    source_storage_mode="database",
                    authenticity_manifest_id="manifest-files-01",
                    output_size_bytes=output_path.stat().st_size,
                    filename_hash_suffix="cleanupfiles01",
                    managed_file_path=str(output_path),
                    sidecar_path=str(sidecar_path),
                )
                conn.commit()

                panel = AssetBrowserPanel(
                    asset_service_provider=lambda: asset_service,
                    drill_in_host_provider=lambda: None,
                )
                try:
                    panel.focus_derivative_batch(batch_id)
                    self.app.processEvents()

                    ledger_tab = panel.derivative_ledger_tab
                    self.assertTrue(ledger_tab.delete_output_files_button.isEnabled())

                    with mock.patch.object(
                        QMessageBox, "question", return_value=QMessageBox.No
                    ) as question:
                        ledger_tab.delete_output_files_button.click()
                    question.assert_called_once()
                    self.assertIn("ledger entry remains", question.call_args[0][2].lower())
                    self.assertTrue(output_path.exists())
                    self.assertTrue(sidecar_path.exists())
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM TrackAudioDerivatives").fetchone()[0],
                        1,
                    )

                    with mock.patch.object(
                        QMessageBox, "question", return_value=QMessageBox.Yes
                    ) as question:
                        ledger_tab.delete_output_files_button.click()
                    question.assert_called_once()
                    self.assertIn("deletes only the files listed", question.call_args[0][2].lower())
                    self.assertFalse(output_path.exists())
                    self.assertFalse(sidecar_path.exists())
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM TrackAudioDerivatives").fetchone()[0],
                        1,
                    )
                    self.assertEqual(
                        conn.execute(
                            "SELECT managed_file_path, sidecar_path FROM TrackAudioDerivatives WHERE export_id=?",
                            (export_id,),
                        ).fetchone(),
                        (None, None),
                    )
                    self.assertEqual(ledger_tab.batch_id_value.text(), batch_id)
                    self.assertEqual(ledger_tab.derivative_table.rowCount(), 1)
                    self.assertFalse(ledger_tab.delete_output_files_button.isEnabled())
                finally:
                    panel.close()
            finally:
                conn.close()

    def test_confirm_destructive_action_formats_consistent_workspace_copy(self):
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as question:
            accepted = _confirm_destructive_action(
                None,
                title="Delete Asset",
                prompt="Delete the selected asset record?",
                consequences=[
                    "This removes the database record only.",
                    "Files on disk are not deleted.",
                ],
            )
        self.assertTrue(accepted)
        question.assert_called_once()
        self.assertEqual(question.call_args[0][1], "Delete Asset")
        self.assertIn("Delete the selected asset record?", question.call_args[0][2])
        self.assertIn("This removes the database record only.", question.call_args[0][2])
        self.assertIn("Files on disk are not deleted.", question.call_args[0][2])

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

import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtWidgets import QPushButton, QTextEdit

from tests.qt_test_helpers import require_qapplication

try:
    from isrc_manager.authenticity.dialogs import (
        AuthenticityExportPreviewDialog,
        AuthenticityKeysDialog,
        AuthenticityVerificationDialog,
    )
    from isrc_manager.authenticity.models import (
        AuthenticityExportPlan,
        AuthenticityExportPlanItem,
        AuthenticityVerificationReport,
    )
except Exception as exc:  # pragma: no cover - environment-specific fallback
    AUTHENTICITY_DIALOG_IMPORT_ERROR = exc
else:
    AUTHENTICITY_DIALOG_IMPORT_ERROR = None


class AuthenticityDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if AUTHENTICITY_DIALOG_IMPORT_ERROR is not None:
            raise unittest.SkipTest(
                f"Authenticity dialog modules unavailable: {AUTHENTICITY_DIALOG_IMPORT_ERROR}"
            )
        cls.app = require_qapplication()

    def test_generate_key_uses_current_owner_party_label_by_default(self):
        key_service = mock.Mock()
        key_service.list_keys.return_value = []
        key_service.generate_keypair.return_value = SimpleNamespace(key_id="key-1")
        dialog = AuthenticityKeysDialog(
            key_service=key_service,
            default_signer_label_provider=lambda: "Current Owner Party",
            signer_party_choices_provider=lambda: [(1, "Fallback Party")],
        )
        try:
            with mock.patch("isrc_manager.authenticity.dialogs.QMessageBox.information"):
                dialog.generate_button.click()
            key_service.generate_keypair.assert_called_once_with(signer_label="Current Owner Party")
        finally:
            dialog.close()

    def test_generate_key_prompts_for_party_choice_when_no_owner_exists(self):
        key_service = mock.Mock()
        key_service.list_keys.return_value = []
        key_service.generate_keypair.return_value = SimpleNamespace(key_id="key-2")
        dialog = AuthenticityKeysDialog(
            key_service=key_service,
            default_signer_label_provider=lambda: None,
            signer_party_choices_provider=lambda: [(7, "Signer Party"), (8, "Other Party")],
        )
        try:
            with (
                mock.patch(
                    "isrc_manager.authenticity.dialogs.QInputDialog.getItem",
                    return_value=("Signer Party", True),
                ),
                mock.patch("isrc_manager.authenticity.dialogs.QMessageBox.information"),
            ):
                dialog.generate_button.click()
            key_service.generate_keypair.assert_called_once_with(signer_label="Signer Party")
        finally:
            dialog.close()

    def test_generate_key_blocks_when_no_parties_exist_and_no_owner_exists(self):
        key_service = mock.Mock()
        key_service.list_keys.return_value = []
        dialog = AuthenticityKeysDialog(
            key_service=key_service,
            default_signer_label_provider=lambda: None,
            signer_party_choices_provider=lambda: [],
        )
        try:
            with mock.patch(
                "isrc_manager.authenticity.dialogs.QMessageBox.information"
            ) as info_mock:
                dialog.generate_button.click()
            key_service.generate_keypair.assert_not_called()
            info_mock.assert_called_once()
        finally:
            dialog.close()

    def test_generate_key_uses_party_choices_when_owner_provider_raises(self):
        key_service = mock.Mock()
        key_service.list_keys.return_value = []
        key_service.generate_keypair.return_value = SimpleNamespace(key_id="key-3")

        def exploding_owner_provider():
            raise RuntimeError("boom")

        dialog = AuthenticityKeysDialog(
            key_service=key_service,
            default_signer_label_provider=exploding_owner_provider,
            signer_party_choices_provider=lambda: [(12, "Primary Party")],
        )
        try:
            with (
                mock.patch(
                    "isrc_manager.authenticity.dialogs.QInputDialog.getItem",
                    return_value=("Primary Party", True),
                ),
                mock.patch("isrc_manager.authenticity.dialogs.QMessageBox.information"),
            ):
                dialog.generate_button.click()
            key_service.generate_keypair.assert_called_once_with(signer_label="Primary Party")
        finally:
            dialog.close()

    def test_generate_key_blocks_when_party_labels_are_blank(self):
        key_service = mock.Mock()
        key_service.list_keys.return_value = []
        dialog = AuthenticityKeysDialog(
            key_service=key_service,
            default_signer_label_provider=None,
            signer_party_choices_provider=lambda: [(12, ""), (13, "   "), (14, None)],
        )
        try:
            with mock.patch(
                "isrc_manager.authenticity.dialogs.QMessageBox.information"
            ) as info_mock:
                dialog.generate_button.click()
            key_service.generate_keypair.assert_not_called()
            info_mock.assert_called_once()
        finally:
            dialog.close()

    def test_generate_key_blocks_when_no_party_provider_is_available(self):
        key_service = mock.Mock()
        key_service.list_keys.return_value = []
        dialog = AuthenticityKeysDialog(
            key_service=key_service,
            default_signer_label_provider=None,
            signer_party_choices_provider=None,
        )
        try:
            with mock.patch(
                "isrc_manager.authenticity.dialogs.QMessageBox.information"
            ) as info_mock:
                dialog.generate_button.click()
            key_service.generate_keypair.assert_not_called()
            info_mock.assert_called_once()
        finally:
            dialog.close()

    def test_generate_key_no_party_selection_no_generate(self):
        key_service = mock.Mock()
        key_service.list_keys.return_value = []
        key_service.generate_keypair.return_value = SimpleNamespace(key_id="key-4")
        dialog = AuthenticityKeysDialog(
            key_service=key_service,
            default_signer_label_provider=None,
            signer_party_choices_provider=lambda: [(1, "Party A")],
        )
        try:
            with mock.patch(
                "isrc_manager.authenticity.dialogs.QInputDialog.getItem",
                return_value=(None, False),
            ):
                dialog.generate_button.click()
            key_service.generate_keypair.assert_not_called()
        finally:
            dialog.close()

    def test_generate_key_notifies_on_generate_failure(self):
        key_service = mock.Mock()
        key_service.list_keys.return_value = []
        key_service.generate_keypair.side_effect = RuntimeError("cannot write key")
        dialog = AuthenticityKeysDialog(
            key_service=key_service,
            default_signer_label_provider=lambda: "Default Party",
            signer_party_choices_provider=lambda: [(1, "Party A")],
        )
        try:
            with mock.patch("isrc_manager.authenticity.dialogs.QMessageBox.critical") as critical:
                dialog._generate_key()
            key_service.generate_keypair.assert_called_once_with(signer_label="Default Party")
            critical.assert_called_once()
        finally:
            dialog.close()

    def test_selected_key_id_returns_none_for_empty_selection(self):
        key_service = mock.Mock()
        key_service.list_keys.return_value = []
        dialog = AuthenticityKeysDialog(key_service=key_service)
        try:
            self.assertIsNone(dialog._selected_key_id())
            key_service.list_keys.assert_called_once()
        finally:
            dialog.close()

    def test_selected_key_id_reads_selected_row_value_and_handles_empty_cell(self):
        key_service = mock.Mock()
        key_record = SimpleNamespace(
            is_default=False,
            key_id="selected-key",
            signer_label="Signer",
            algorithm="Ed25519",
            has_private_key=True,
            created_at="2026-01-01",
        )
        key_service.list_keys.return_value = [key_record]
        dialog = AuthenticityKeysDialog(
            key_service=key_service,
            default_signer_label_provider=None,
            signer_party_choices_provider=lambda: [],
        )
        try:
            dialog.table.selectRow(0)
            self.assertEqual(dialog._selected_key_id(), "selected-key")
            self.assertEqual(dialog._selected_key_id(), "selected-key")

            dialog.table.setItem(0, 1, None)
            self.assertIsNone(dialog._selected_key_id())
        finally:
            dialog.close()

    def test_set_default_no_row_is_blocked_with_informational_message(self):
        key_service = mock.Mock()
        key_service.list_keys.return_value = []
        dialog = AuthenticityKeysDialog(key_service=key_service)
        try:
            with mock.patch(
                "isrc_manager.authenticity.dialogs.QMessageBox.information"
            ) as info_mock:
                dialog.default_button.click()
            key_service.set_default_key.assert_not_called()
            info_mock.assert_called_once()
        finally:
            dialog.close()

    def test_set_default_updates_selected_key(self):
        key_service = mock.Mock()
        key_record = SimpleNamespace(
            is_default=False,
            key_id="selected-key",
            signer_label="Signer",
            algorithm="Ed25519",
            has_private_key=True,
            created_at="2026-01-01",
        )
        key_service.list_keys.return_value = [key_record]
        dialog = AuthenticityKeysDialog(key_service=key_service)
        try:
            key_service.list_keys.return_value = [key_record]
            dialog.table.selectRow(0)

            dialog.default_button.click()
            key_service.set_default_key.assert_called_once_with("selected-key")
        finally:
            dialog.close()

    def test_export_preview_dialog_populates_rows_and_buttons(self):
        plan = AuthenticityExportPlan(
            key_id="pub-key",
            signer_label="Signer One",
            document_type="direct_wm",
            workflow_kind="master",
            items=[
                AuthenticityExportPlanItem(
                    track_id=11,
                    track_title="Track A",
                    source_label="file://source.wav",
                    source_suffix=".wav",
                    suggested_name="track_a",
                    key_id="pub-key",
                    document_type="direct",
                    workflow_kind="master",
                    status="ready",
                    warning="",
                    album_title="Album",
                ),
                AuthenticityExportPlanItem(
                    track_id=12,
                    track_title="Track B",
                    source_label="file://source.mp3",
                    source_suffix=None,
                    suggested_name="track_b",
                    key_id="pub-key",
                    status="unsupported",
                    warning="Missing encoder",
                ),
            ],
        )
        try:
            dialog = AuthenticityExportPreviewDialog(plan=plan)
            self.assertEqual(dialog.windowTitle(), "Export Authenticity Watermarked Audio")
            self.assertEqual(dialog.table.rowCount(), 2)
            self.assertEqual(dialog.table.item(0, 1).text(), "Track A")
            self.assertEqual(dialog.table.item(0, 3).text(), "track_a.wav")
            self.assertEqual(dialog.table.item(1, 3).text(), "track_b")
            buttons = [button.text() for button in dialog.findChildren(QPushButton)]
            self.assertEqual(len(buttons), 2)
            self.assertIn("Continue", buttons)
            self.assertIn("Cancel", buttons)
        finally:
            dialog.close()

    def test_verification_dialog_renders_full_optional_report_details(self):
        report = AuthenticityVerificationReport(
            status="verified_authentic",
            message="Looks good",
            inspected_path="/tmp/a.wav",
            key_id="key-a",
            manifest_id="man-1",
            parent_manifest_id="man-parent",
            watermark_id=11,
            resolution_source="manifest",
            verification_basis="signature+hash",
            document_type="direct_wm",
            workflow_kind="master",
            signature_valid=True,
            exact_hash_match=False,
            fingerprint_similarity=0.9234,
            extraction_confidence=0.8123,
            sidecar_path="/tmp/a.sidecar.json",
            details=["Extra 1", "Extra 2"],
        )
        try:
            dialog = AuthenticityVerificationDialog(report=report)
            details_widgets = dialog.findChildren(QTextEdit)
            self.assertEqual(len(details_widgets), 1)
            details_widget = details_widgets[0]
            report_text = details_widget.toPlainText()
            self.assertIn("Manifest ID: man-1", report_text)
            self.assertIn("Parent Manifest ID: man-parent", report_text)
            self.assertIn("Watermark ID: 11", report_text)
            self.assertIn("Resolved From: manifest", report_text)
            self.assertIn("Verification Basis: signature+hash", report_text)
            self.assertIn("Document Type: direct_wm", report_text)
            self.assertIn("Workflow Kind: master", report_text)
            self.assertIn("Signature Valid: True", report_text)
            self.assertIn("Exact Hash Match: False", report_text)
            self.assertIn("Fingerprint Similarity: 0.923", report_text)
            self.assertIn("Extraction Confidence: 81.2% (0.812)", report_text)
            self.assertIn("Sidecar: /tmp/a.sidecar.json", report_text)
            self.assertIn("Details:", report_text)
            self.assertIn("Extra 1", report_text)
            self.assertIn("Extra 2", report_text)
            self.assertEqual(dialog.windowTitle(), "Audio Authenticity Verification")
        finally:
            dialog.close()

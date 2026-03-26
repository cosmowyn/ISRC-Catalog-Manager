import unittest
from types import SimpleNamespace
from unittest import mock

from tests.qt_test_helpers import require_qapplication

try:
    from isrc_manager.authenticity.dialogs import AuthenticityKeysDialog
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

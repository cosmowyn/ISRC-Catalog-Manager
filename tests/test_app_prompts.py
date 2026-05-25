import unittest
from unittest import mock

from PySide6.QtWidgets import QDialog

from isrc_manager.app_prompts import (
    get_name_from_editable_choice_dialog,
    prompt_storage_mode_choice,
    storage_mode_choice_text,
)
from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE


class AppPromptTests(unittest.TestCase):
    def test_get_name_from_editable_choice_dialog_returns_trimmed_input_on_accept(self):
        combo = mock.Mock()
        combo.currentText.return_value = "Demo Name"
        combo.findText.return_value = -1
        combo.lineEdit.return_value = mock.Mock()
        line_edit = combo.lineEdit.return_value

        dialog = mock.Mock()
        dialog.exec.return_value = QDialog.Accepted

        accept_signal = mock.Mock()
        reject_signal = mock.Mock()

        form_layout = mock.Mock()
        root_layout = mock.Mock()
        button_box = mock.Mock(accepted=accept_signal, rejected=reject_signal)

        qdialog = mock.Mock(
            Accepted=QDialog.Accepted, Rejected=QDialog.Rejected, return_value=dialog
        )
        with (
            mock.patch("isrc_manager.app_prompts.QDialog", qdialog),
            mock.patch("isrc_manager.app_prompts.QComboBox", return_value=combo),
            mock.patch("isrc_manager.app_prompts.QFormLayout", return_value=form_layout),
            mock.patch("isrc_manager.app_prompts.QVBoxLayout", return_value=root_layout),
            mock.patch("isrc_manager.app_prompts.QDialogButtonBox", return_value=button_box),
        ):
            value, accepted = get_name_from_editable_choice_dialog(
                None,
                title="Rename",
                label="Name",
                choices=[" Existing "],
                suggested_name="  Clean Name  ",
            )

        self.assertEqual(value, "Demo Name")
        self.assertTrue(accepted)
        combo.setEditable.assert_called_once_with(True)
        combo.setCurrentIndex.assert_called()
        combo.setCurrentIndex.assert_any_call(0)
        combo.setEditText.assert_called_once_with("Clean Name")
        line_edit.selectAll.assert_called_once()
        dialog.setWindowTitle.assert_called_once_with("Rename")
        accept_signal.connect.assert_called_once_with(dialog.accept)
        reject_signal.connect.assert_called_once_with(dialog.reject)

    def test_get_name_from_editable_choice_dialog_returns_empty_on_reject(self):
        combo = mock.Mock()
        combo.currentText.return_value = "ignored"
        combo.lineEdit.return_value = mock.Mock()

        dialog = mock.Mock()
        dialog.exec.return_value = QDialog.Rejected

        button_box = mock.Mock(accepted=mock.Mock(), rejected=mock.Mock())

        with (
            mock.patch(
                "isrc_manager.app_prompts.QDialog",
                return_value=mock.Mock(
                    Accepted=QDialog.Accepted, Rejected=QDialog.Rejected, return_value=dialog
                ),
            ),
            mock.patch("isrc_manager.app_prompts.QComboBox", return_value=combo),
            mock.patch("isrc_manager.app_prompts.QFormLayout", return_value=mock.Mock()),
            mock.patch("isrc_manager.app_prompts.QVBoxLayout", return_value=mock.Mock()),
            mock.patch("isrc_manager.app_prompts.QDialogButtonBox", return_value=button_box),
        ):
            value, accepted = get_name_from_editable_choice_dialog(
                None,
                title="Rename",
                label="Name",
                choices=[],
                suggested_name="",
            )

        self.assertEqual(value, "")
        self.assertFalse(accepted)

    def test_storage_mode_choice_text_reflects_mode_aliases(self):
        self.assertEqual(storage_mode_choice_text("database"), "Store in Database")
        self.assertEqual(storage_mode_choice_text("file"), "Store as Managed File")
        with self.assertRaises(ValueError):
            storage_mode_choice_text("  unknown ")

    def test_prompt_storage_mode_choice_maps_buttons_to_expected_modes_and_cancel(self):
        db_button = mock.Mock()
        file_button = mock.Mock()
        cancel_button = mock.Mock()
        dialog = mock.Mock()

        def add_button(*args, **kwargs):
            label = args[0]
            if label == "Store in Database":
                return db_button
            if label == "Store as Managed File":
                return file_button
            return cancel_button

        dialog.addButton.side_effect = add_button

        with mock.patch("isrc_manager.app_prompts.QMessageBox", return_value=dialog) as message_box:
            message_box.AcceptRole = 10
            message_box.Cancel = 11
            message_box.Yes = 12
            message_box.No = 13

            dialog.clickedButton.return_value = db_button
            mode = prompt_storage_mode_choice(
                None,
                title="Store test media",
                subject="a demo file",
                default_mode=STORAGE_MODE_DATABASE,
            )

            self.assertEqual(mode, STORAGE_MODE_DATABASE)

            dialog.clickedButton.return_value = file_button
            mode = prompt_storage_mode_choice(
                None,
                title="Store test media",
                subject="a demo file",
                default_mode=STORAGE_MODE_MANAGED_FILE,
            )

            self.assertEqual(mode, STORAGE_MODE_MANAGED_FILE)

            dialog.clickedButton.return_value = cancel_button
            mode = prompt_storage_mode_choice(
                None,
                title="Store test media",
                subject="a demo file",
                default_mode=None,
            )

            self.assertIsNone(mode)

        self.assertEqual(message_box.call_count, 3)
        dialog.addButton.assert_called()


if __name__ == "__main__":
    unittest.main()

import unittest

try:
    from PySide6.QtWidgets import QApplication, QWidget
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QWidget = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.ui_common import (
    DatePickerDialog,
    TwoDigitSpinBox,
    _compose_widget_stylesheet,
    _create_round_help_button,
)


class _ThemeOwner(QWidget):
    def __init__(self):
        super().__init__()
        self.child = QWidget(self)

    def _active_custom_qss(self) -> str:
        return "QWidget { color: red; }"


class _HelpHost(QWidget):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.child = QWidget(self)

    def open_help_dialog(self, *, topic_id=None, parent=None):
        self.calls.append((topic_id, parent))


class UICommonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def test_compose_widget_stylesheet_appends_owner_qss(self):
        owner = _ThemeOwner()
        try:
            combined = _compose_widget_stylesheet(owner.child, "QLabel { font-weight: bold; }")
            self.assertIn("font-weight: bold", combined)
            self.assertIn("User custom QSS", combined)
            self.assertIn("color: red", combined)
        finally:
            owner.close()

    def test_help_button_routes_to_parent_help_host(self):
        host = _HelpHost()
        try:
            button = _create_round_help_button(host.child, "overview")
            button.click()
            self.assertEqual(len(host.calls), 1)
            self.assertEqual(host.calls[0][0], "overview")
            self.assertIs(host.calls[0][1], host.child)
        finally:
            host.close()

    def test_date_picker_clear_returns_none(self):
        dialog = DatePickerDialog(initial_iso_date="2026-03-16")
        try:
            self.assertEqual(dialog.selected_iso(), "2026-03-16")
            dialog.btn_clear.click()
            self.assertIsNone(dialog.selected_iso())
        finally:
            dialog.close()

    def test_two_digit_spinbox_pads_values(self):
        spinbox = TwoDigitSpinBox()
        try:
            self.assertEqual(spinbox.textFromValue(5), "05")
            self.assertEqual(spinbox.textFromValue(12), "12")
        finally:
            spinbox.close()


if __name__ == "__main__":
    unittest.main()

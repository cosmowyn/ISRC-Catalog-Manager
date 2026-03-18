import unittest

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QFormLayout, QLineEdit, QPushButton, QWidget
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    Qt = None
    QDialog = None
    QFormLayout = None
    QLineEdit = None
    QPushButton = None
    QWidget = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.ui_common import (
    DatePickerDialog,
    TwoDigitSpinBox,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
    _compose_widget_stylesheet,
    _configure_standard_form_layout,
    _create_round_help_button,
    _create_scrollable_dialog_content,
    _standard_dialog_stylesheet,
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

    def test_configure_standard_form_layout_sets_repo_defaults(self):
        form = QFormLayout()
        _configure_standard_form_layout(form)
        self.assertEqual(form.horizontalSpacing(), 12)
        self.assertEqual(form.verticalSpacing(), 10)
        self.assertEqual(form.fieldGrowthPolicy(), QFormLayout.AllNonFixedFieldsGrow)
        self.assertEqual(form.rowWrapPolicy(), QFormLayout.WrapLongRows)

    def test_scrollable_dialog_content_wraps_expanding_widget(self):
        owner = QWidget()
        try:
            scroll_area, content, layout = _create_scrollable_dialog_content(owner)
            self.assertIs(scroll_area.widget(), content)
            self.assertIs(content.parentWidget(), scroll_area.viewport())
            self.assertEqual(layout.spacing(), 14)
        finally:
            owner.close()

    def test_compact_dialog_control_heights_raise_fields_and_buttons(self):
        owner = QWidget()
        try:
            line_edit = QLineEdit(owner)
            button = QPushButton("Save", owner)
            _apply_compact_dialog_control_heights(owner)
            self.assertGreaterEqual(
                line_edit.minimumHeight(), line_edit.fontMetrics().lineSpacing() + 16
            )
            self.assertGreaterEqual(button.minimumHeight(), button.fontMetrics().lineSpacing() + 14)
            self.assertGreaterEqual(button.minimumWidth(), 0)
        finally:
            owner.close()

    def test_standard_dialog_stylesheet_does_not_override_compact_control_group_background(self):
        stylesheet = _standard_dialog_stylesheet("demoDialog")
        self.assertNotIn('QFrame[role="compactControlGroup"]', stylesheet)
        self.assertNotIn("palette(base)", stylesheet)

    def test_apply_standard_dialog_chrome_tags_panel_root(self):
        dialog = QDialog()
        try:
            _apply_standard_dialog_chrome(dialog, "demoDialog")
            self.assertEqual(dialog.objectName(), "demoDialog")
            self.assertEqual(dialog.property("role"), "panel")
            self.assertTrue(dialog.testAttribute(Qt.WA_StyledBackground))
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()

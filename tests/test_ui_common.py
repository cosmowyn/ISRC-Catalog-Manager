import unittest
from unittest import mock

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent, QValidator
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QFormLayout,
        QFrame,
        QLineEdit,
        QPushButton,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QEvent = None
    QKeyEvent = None
    Qt = None
    QDialog = None
    QFormLayout = None
    QFrame = None
    QLineEdit = None
    QPushButton = None
    QValidator = None
    QWidget = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.ui_common import (
    DatePickerDialog,
    StorageBudgetSpinBox,
    TwoDigitSpinBox,
    _abbreviate_middle_text,
    _apply_compact_dialog_control_heights,
    _apply_dialog_width_constraints,
    _apply_standard_dialog_chrome,
    _compose_widget_stylesheet,
    _configure_standard_form_layout,
    _create_action_button_cluster,
    _create_round_help_button,
    _create_scrollable_dialog_content,
    _create_standard_section,
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

    def test_storage_budget_spinbox_formats_and_parses_human_units(self):
        spinbox = StorageBudgetSpinBox()
        try:
            self.assertEqual(spinbox.textFromValue(512), "512 MB")
            self.assertEqual(spinbox.textFromValue(1536), "1.5 GB")
            self.assertEqual(spinbox.textFromValue(1048576), "1 TB")
            self.assertEqual(spinbox.valueFromText("1,5 GB"), 1536)
            self.assertEqual(spinbox.valueFromText("1 tb"), 1048576)
            self.assertEqual(
                spinbox.validate("1.5 gb", 6)[0],
                QValidator.Acceptable,
            )
            self.assertEqual(
                spinbox.validate("1.", 2)[0],
                QValidator.Intermediate,
            )
        finally:
            spinbox.close()

    def test_storage_budget_spinbox_accelerates_held_steps_and_resets_after_release(self):
        spinbox = StorageBudgetSpinBox()
        spinbox.setRange(128, 1048576)
        spinbox.setValue(512)
        try:
            with mock.patch(
                "isrc_manager.ui_common.monotonic",
                side_effect=[float(index) / 10.0 for index in range(40)],
            ):
                for _ in range(11):
                    spinbox.stepBy(1)
                self.assertEqual(spinbox.value(), 523)

                spinbox.stepBy(1)
                self.assertEqual(spinbox.value(), 623)

                spinbox.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, Qt.Key_Up, Qt.NoModifier))
                spinbox.stepBy(1)
                self.assertEqual(spinbox.value(), 624)

            with mock.patch(
                "isrc_manager.ui_common.monotonic",
                side_effect=[10.0 + (float(index) / 10.0) for index in range(40)],
            ):
                for _ in range(11):
                    spinbox.stepBy(-1)
                self.assertEqual(spinbox.value(), 613)

                spinbox.stepBy(-1)
                self.assertEqual(spinbox.value(), 513)
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
            self.assertEqual(scroll_area.property("role"), "workspaceCanvas")
            self.assertEqual(content.property("role"), "workspaceCanvas")
            self.assertEqual(scroll_area.frameShape(), QFrame.NoFrame)
            self.assertTrue(scroll_area.widgetResizable())
        finally:
            owner.close()

    def test_scrollable_dialog_content_can_preserve_outer_page_identity(self):
        owner = QWidget()
        page = QWidget(owner)
        try:
            scroll_area, content, layout = _create_scrollable_dialog_content(
                owner,
                page=page,
                role="workspaceCanvas",
            )
            self.assertIs(page.layout().itemAt(0).widget(), scroll_area)
            self.assertIs(scroll_area.parentWidget(), page)
            self.assertIs(scroll_area.widget(), content)
            self.assertEqual(page.property("role"), "workspaceCanvas")
            self.assertEqual(scroll_area.property("role"), "workspaceCanvas")
            self.assertEqual(scroll_area.viewport().property("role"), "workspaceCanvas")
            self.assertEqual(content.property("role"), "workspaceCanvas")
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

    def test_action_button_cluster_sets_spacing_role_and_min_widths(self):
        owner = QWidget()
        try:
            buttons = [
                QPushButton("One", owner),
                QPushButton("Two", owner),
                QPushButton("Three", owner),
            ]
            cluster = _create_action_button_cluster(owner, buttons, columns=2, min_button_width=180)
            layout = cluster.layout()
            self.assertEqual(cluster.property("role"), "compactControlGroup")
            self.assertEqual(layout.horizontalSpacing(), 12)
            self.assertEqual(layout.verticalSpacing(), 10)
            for button in buttons:
                self.assertGreaterEqual(button.minimumWidth(), 180)
        finally:
            owner.close()

    def test_action_button_cluster_accepts_compact_spacing(self):
        owner = QWidget()
        try:
            buttons = [QPushButton("One", owner), QPushButton("Two", owner)]
            cluster = _create_action_button_cluster(
                owner,
                buttons,
                columns=2,
                outer_margins=(6, 6, 6, 6),
                horizontal_spacing=6,
                vertical_spacing=8,
            )
            layout = cluster.layout()
            margins = layout.contentsMargins()
            self.assertEqual(layout.horizontalSpacing(), 6)
            self.assertEqual(layout.verticalSpacing(), 8)
            self.assertEqual(
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                (6, 6, 6, 6),
            )
        finally:
            owner.close()

    def test_standard_section_uses_compact_title_top_inset(self):
        owner = QWidget()
        try:
            _box, layout = _create_standard_section(owner, "Details")
            margins = layout.contentsMargins()
            self.assertEqual(
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                (14, 12, 14, 14),
            )
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

    def test_apply_dialog_width_constraints_caps_dialog_width(self):
        dialog = QDialog()
        try:
            dialog.resize(900, 200)
            _apply_dialog_width_constraints(dialog, min_width=360, max_width=480)
            self.assertEqual(dialog.minimumWidth(), 360)
            self.assertEqual(dialog.maximumWidth(), 480)
            self.assertGreaterEqual(dialog.width(), 360)
            self.assertLessEqual(dialog.width(), 480)
        finally:
            dialog.close()

    def test_abbreviate_middle_text_preserves_short_values_and_compacts_long_values(self):
        short_value = "Short export title"
        long_value = (
            "This is a deliberately long export filename that should keep the most useful edges"
        )

        self.assertEqual(_abbreviate_middle_text(short_value), short_value)
        self.assertEqual(
            _abbreviate_middle_text(long_value),
            "This is a deliberate...eep the most useful edges",
        )


if __name__ == "__main__":
    unittest.main()

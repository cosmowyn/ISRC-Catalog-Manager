import unittest
from unittest import mock

try:
    from PySide6.QtCore import QDate, QEvent, QPointF, Qt
    from PySide6.QtGui import QFocusEvent, QKeyEvent, QMouseEvent, QShowEvent, QValidator
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QFormLayout,
        QFrame,
        QLineEdit,
        QPushButton,
        QScrollArea,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QDate = None
    QEvent = None
    QFocusEvent = None
    QKeyEvent = None
    QMouseEvent = None
    QPointF = None
    QShowEvent = None
    Qt = None
    QDialog = None
    QFormLayout = None
    QFrame = None
    QLineEdit = None
    QPushButton = None
    QScrollArea = None
    QVBoxLayout = None
    QValidator = None
    QWidget = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.ui_common import (
    DatePickerDialog,
    FocusWheelCalendarWidget,
    FocusWheelComboBox,
    FocusWheelSlider,
    StorageBudgetSpinBox,
    TwoDigitSpinBox,
    _abbreviate_middle_text,
    _apply_compact_dialog_control_heights,
    _apply_dialog_width_constraints,
    _apply_standard_dialog_chrome,
    _apply_standard_widget_chrome,
    _compose_widget_stylesheet,
    _configure_standard_form_layout,
    _confirm_destructive_action,
    _create_action_button_cluster,
    _create_action_button_grid,
    _create_round_help_button,
    _create_scrollable_dialog_content,
    _create_standard_section,
    _prompt_compact_choice_dialog,
    _standard_dialog_stylesheet,
    _WheelIntentMixin,
)


class _ThemeOwner(QWidget):
    def __init__(self):
        super().__init__()
        self.child = QWidget(self)

    def _active_custom_qss(self) -> str:
        return "QWidget { color: red; }"


class _BrokenThemeOwner(QWidget):
    def __init__(self):
        super().__init__()
        self.child = QWidget(self)

    def _active_custom_qss(self) -> str:
        raise RuntimeError("broken qss")


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

    def test_compose_widget_stylesheet_can_return_owner_qss_without_base(self):
        owner = _ThemeOwner()
        try:
            self.assertEqual(
                _compose_widget_stylesheet(owner.child, "   "),
                "QWidget { color: red; }",
            )
        finally:
            owner.close()

    def test_compose_widget_stylesheet_ignores_broken_owner_qss(self):
        owner = _BrokenThemeOwner()
        try:
            self.assertEqual(
                _compose_widget_stylesheet(owner.child, "QLabel { color: blue; }"),
                "QLabel { color: blue; }",
            )
            self.assertEqual(_compose_widget_stylesheet(QWidget(), ""), "")
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

    def test_help_button_without_host_is_a_safe_noop(self):
        owner = QWidget()
        try:
            button = _create_round_help_button(owner, "overview")
            button.click()
            self.assertEqual(button.objectName(), "overviewHelpButton")
        finally:
            owner.close()

    def test_help_button_routes_to_app_help_host(self):
        owner = QWidget()
        calls = []
        owner.app = mock.Mock(
            open_help_dialog=mock.Mock(side_effect=lambda **kwargs: calls.append(kwargs))
        )
        try:
            button = _create_round_help_button(owner, "metadata-dates", tooltip="Help me")
            self.assertEqual(button.toolTip(), "Help me")
            button.click()
            self.assertEqual(calls, [{"topic_id": "metadata-dates", "parent": owner}])
        finally:
            owner.close()

    def test_confirm_destructive_action_builds_message_and_returns_answer(self):
        owner = QWidget()
        try:
            with mock.patch(
                "isrc_manager.ui_common.QMessageBox.question",
                return_value=mock.Mock(),
            ) as question:
                self.assertFalse(
                    _confirm_destructive_action(
                        owner,
                        title="Delete",
                        prompt="Delete the selected item?",
                        consequences=["This cannot be undone.", "", "Backups remain available."],
                    )
                )
            question.assert_called_once()
            self.assertEqual(question.call_args.args[1], "Delete")
            self.assertEqual(
                question.call_args.args[2],
                "Delete the selected item?\n\nThis cannot be undone.\n\nBackups remain available.",
            )

            yes_sentinel = object()
            with mock.patch(
                "isrc_manager.ui_common.QMessageBox.Yes",
                yes_sentinel,
            ):
                with mock.patch(
                    "isrc_manager.ui_common.QMessageBox.question",
                    return_value=yes_sentinel,
                ):
                    self.assertTrue(
                        _confirm_destructive_action(
                            owner,
                            title="Delete",
                            prompt="Delete the selected item?",
                        )
                    )
        finally:
            owner.close()

    def test_date_picker_clear_returns_none(self):
        dialog = DatePickerDialog(initial_iso_date="2026-03-16")
        try:
            self.assertEqual(dialog.selected_iso(), "2026-03-16")
            dialog.btn_clear.click()
            self.assertIsNone(dialog.selected_iso())
        finally:
            dialog.close()

    def test_date_picker_defaults_invalid_or_missing_dates_to_today(self):
        today = QDate.currentDate().toString("yyyy-MM-dd")
        missing = DatePickerDialog()
        invalid = DatePickerDialog(initial_iso_date="not-a-date")
        try:
            self.assertEqual(missing.selected_iso(), today)
            self.assertEqual(invalid.selected_iso(), today)
            self.assertIsNotNone(missing.btn_ok)
            self.assertFalse(missing.btn_cancel.autoDefault())
        finally:
            missing.close()
            invalid.close()

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

    def test_storage_budget_spinbox_focus_and_mouse_release_reset_repeat_state(self):
        spinbox = StorageBudgetSpinBox()
        try:
            spinbox._repeat_direction = 1
            spinbox._repeat_moved_mb = 20
            spinbox._last_step_timestamp = 123.0
            spinbox.focusOutEvent(QFocusEvent(QEvent.FocusOut))
            self.assertEqual(spinbox._repeat_direction, 0)
            self.assertEqual(spinbox._repeat_moved_mb, 0)
            self.assertEqual(spinbox._last_step_timestamp, 0.0)

            spinbox._repeat_direction = -1
            spinbox._repeat_moved_mb = 40
            spinbox._last_step_timestamp = 456.0
            spinbox.mouseReleaseEvent(
                QMouseEvent(
                    QEvent.MouseButtonRelease,
                    QPointF(1, 1),
                    Qt.LeftButton,
                    Qt.LeftButton,
                    Qt.NoModifier,
                )
            )
            self.assertEqual(spinbox._repeat_direction, 0)
            self.assertEqual(spinbox._repeat_moved_mb, 0)
            self.assertEqual(spinbox._last_step_timestamp, 0.0)
        finally:
            spinbox.close()

    def test_storage_budget_spinbox_validation_invalid_and_zero_step(self):
        spinbox = StorageBudgetSpinBox()
        spinbox.setRange(0, 1048576)
        spinbox.setValue(512)
        try:
            self.assertEqual(spinbox.validate("", 0)[0], QValidator.Intermediate)
            self.assertEqual(spinbox.validate("budget!", 4)[0], QValidator.Invalid)
            spinbox.stepBy(0)
            self.assertEqual(spinbox.value(), 512)
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

    def test_scrollable_dialog_content_reuses_existing_page_layout(self):
        owner = QWidget()
        page = QWidget(owner)
        existing_layout = QVBoxLayout(page)
        try:
            scroll_area, _content, _layout = _create_scrollable_dialog_content(
                owner,
                page=page,
                role="detailsPanel",
            )
            self.assertIs(page.layout(), existing_layout)
            self.assertIs(page.layout().itemAt(0).widget(), scroll_area)
            self.assertEqual(page.property("role"), "detailsPanel")
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

    def test_action_button_grid_places_buttons_across_requested_columns(self):
        owner = QWidget()
        try:
            buttons = [
                QPushButton("One", owner),
                QPushButton("Two", owner),
                QPushButton("Three", owner),
            ]
            grid = _create_action_button_grid(owner, buttons, columns=2)
            layout = grid.layout()
            self.assertIs(layout.itemAtPosition(0, 0).widget(), buttons[0])
            self.assertIs(layout.itemAtPosition(0, 1).widget(), buttons[1])
            self.assertIs(layout.itemAtPosition(1, 0).widget(), buttons[2])
            self.assertEqual(layout.columnStretch(0), 1)
            self.assertEqual(layout.columnStretch(1), 1)
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

    def test_action_button_cluster_can_span_single_button_last_row(self):
        owner = QWidget()
        try:
            buttons = [
                QPushButton("One", owner),
                QPushButton("Two", owner),
                QPushButton("Three", owner),
            ]
            cluster = _create_action_button_cluster(
                owner,
                buttons,
                columns=2,
                span_last_row=True,
                lock_minimum_height=False,
            )
            row, column, row_span, column_span = cluster.layout().getItemPosition(2)
            self.assertEqual((row, column, row_span, column_span), (1, 0, 1, 2))
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

    def test_apply_standard_widget_chrome_adds_object_and_custom_stylesheet(self):
        owner = _ThemeOwner()
        try:
            _apply_standard_widget_chrome(
                owner.child, "demoWidget", extra_qss="QLabel { color: green; }"
            )
            self.assertEqual(owner.child.objectName(), "demoWidget")
            self.assertIn("demoWidget", owner.child.styleSheet())
            self.assertIn("color: green", owner.child.styleSheet())
            self.assertIn("User custom QSS", owner.child.styleSheet())
        finally:
            owner.close()

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

    def test_abbreviate_middle_text_returns_empty_for_falsey_value(self):
        self.assertEqual(_abbreviate_middle_text(""), "")
        self.assertEqual(_abbreviate_middle_text(None), "")

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

    def test_prompt_compact_choice_dialog_handles_empty_rejected_and_accepted_choices(self):
        self.assertIsNone(
            _prompt_compact_choice_dialog(
                None,
                title="Choose",
                prompt="Pick one",
                choices=[],
            )
        )

        with mock.patch("isrc_manager.ui_common.QDialog.exec", return_value=QDialog.Rejected):
            self.assertIsNone(
                _prompt_compact_choice_dialog(
                    None,
                    title="Choose",
                    prompt="Pick one",
                    choices=[("one", "One")],
                )
            )

        with mock.patch("isrc_manager.ui_common.QDialog.exec", return_value=QDialog.Accepted):
            self.assertEqual(
                _prompt_compact_choice_dialog(
                    None,
                    title="Choose",
                    prompt="Pick one",
                    choices=[("one", "One"), ("two", "Two")],
                    ok_text="Apply",
                ),
                "one",
            )
            self.assertIsNone(
                _prompt_compact_choice_dialog(
                    None,
                    title="Choose",
                    prompt="Pick one",
                    choices=[("", "Empty")],
                )
            )

    def test_wheel_intent_mixin_reports_focus_and_ignores_unfocused_wheel_events(self):
        combo = FocusWheelComboBox()
        child = QLineEdit(combo)

        class _PopupCombo(FocusWheelComboBox):
            def view(self):
                return mock.Mock(isVisible=mock.Mock(return_value=True))

        class _FailingPopupCombo(FocusWheelComboBox):
            def view(self):
                raise RuntimeError("popup unavailable")

        class _WheelEvent:
            ignored = False

            def ignore(self):
                self.ignored = True

        try:
            fake_app = mock.Mock()
            with mock.patch("isrc_manager.ui_common.QApplication.instance", return_value=fake_app):
                fake_app.focusWidget.return_value = None
                self.assertFalse(combo._wheel_has_user_focus())

                fake_app.focusWidget.return_value = combo
                self.assertTrue(combo._wheel_has_user_focus())

                fake_app.focusWidget.return_value = child
                self.assertTrue(combo._wheel_has_user_focus())

                popup_combo = _PopupCombo()
                try:
                    fake_app.focusWidget.return_value = QWidget()
                    self.assertTrue(popup_combo._wheel_has_user_focus())
                finally:
                    popup_combo.close()

                failing_popup_combo = _FailingPopupCombo()
                try:
                    fake_app.focusWidget.return_value = QWidget()
                    self.assertFalse(failing_popup_combo._wheel_has_user_focus())
                finally:
                    failing_popup_combo.close()

                fake_app.focusWidget.return_value = None
                event = _WheelEvent()
                combo.wheelEvent(event)
                self.assertTrue(event.ignored)
        finally:
            combo.close()

    def test_wheel_intent_mixin_forwards_focused_wheel_events_to_super(self):
        class _BaseWheelHandler:
            def __init__(self):
                self.forwarded_event = None

            def wheelEvent(self, event):
                self.forwarded_event = event

        class _Harness(_WheelIntentMixin, _BaseWheelHandler):
            def _wheel_has_user_focus(self):
                return True

        event = object()
        harness = _Harness()
        harness.wheelEvent(event)
        self.assertIs(harness.forwarded_event, event)

    def test_focus_wheel_slider_double_click_reset_clamps_value(self):
        slider = FocusWheelSlider(Qt.Horizontal)
        slider.setRange(0, 10)
        slider.setValue(2)
        slider.setDoubleClickResetValue(99)

        class _Event:
            accepted = False

            def button(self):
                return Qt.LeftButton

            def accept(self):
                self.accepted = True

        event = _Event()
        try:
            slider.mouseDoubleClickEvent(event)
            self.assertEqual(slider.value(), 10)
            self.assertTrue(event.accepted)
        finally:
            slider.close()

    def test_focus_wheel_slider_double_click_without_reset_uses_default_handler(self):
        slider = FocusWheelSlider(Qt.Horizontal)
        try:
            slider.setValue(2)
            slider.mouseDoubleClickEvent(
                QMouseEvent(
                    QEvent.MouseButtonDblClick,
                    QPointF(1, 1),
                    Qt.RightButton,
                    Qt.RightButton,
                    Qt.NoModifier,
                )
            )
            self.assertEqual(slider.value(), 2)
        finally:
            slider.close()

    def test_two_digit_spinbox_falls_back_when_value_cannot_be_int(self):
        spinbox = TwoDigitSpinBox()

        class _BadInt:
            def __int__(self):
                raise TypeError("no integer")

            def __str__(self):
                return "bad"

        try:
            self.assertEqual(spinbox.textFromValue(_BadInt()), "bad")
        finally:
            spinbox.close()

    def test_calendar_wheel_filter_install_show_and_forwarding_edge_cases(self):
        calendar = FocusWheelCalendarWidget()

        class _Delta:
            def __init__(self, value):
                self._value = value

            def y(self):
                return self._value

        class _WheelEvent:
            def __init__(self, *, pixel=0, angle=0):
                self.accepted = False
                self.ignored = False
                self._pixel = pixel
                self._angle = angle

            def type(self):
                return QEvent.Wheel

            def pixelDelta(self):
                return _Delta(self._pixel)

            def angleDelta(self):
                return _Delta(self._angle)

            def accept(self):
                self.accepted = True

            def ignore(self):
                self.ignored = True

        try:
            calendar.showEvent(QShowEvent())
            self.assertIsNone(FocusWheelCalendarWidget._find_scroll_area_parent(None))

            no_parent_event = _WheelEvent(angle=120)
            self.assertFalse(
                calendar._forward_wheel_to_parent_scroll_area(calendar, no_parent_event)
            )
            self.assertTrue(calendar.eventFilter(calendar, no_parent_event))
            self.assertTrue(no_parent_event.ignored)

            zero_delta_event = _WheelEvent()
            self.assertFalse(
                calendar._forward_wheel_to_parent_scroll_area(calendar, zero_delta_event)
            )

            self.assertFalse(calendar.eventFilter(calendar, QEvent(QEvent.FocusIn)))
        finally:
            calendar.close()

    def test_calendar_wheel_filter_scrolls_pixel_delta_and_wheel_event_paths(self):
        scroll = QScrollArea()
        content = QWidget()
        scroll.setWidget(content)
        calendar = FocusWheelCalendarWidget(content)
        scrollbar = scroll.verticalScrollBar()
        scrollbar.setRange(0, 500)
        scrollbar.setValue(250)
        scrollbar.setSingleStep(10)

        class _Delta:
            def __init__(self, value):
                self._value = value

            def y(self):
                return self._value

        class _WheelEvent:
            def __init__(self, *, pixel=0, angle=0):
                self.accepted = False
                self.ignored = False
                self._pixel = pixel
                self._angle = angle

            def type(self):
                return QEvent.Wheel

            def pixelDelta(self):
                return _Delta(self._pixel)

            def angleDelta(self):
                return _Delta(self._angle)

            def accept(self):
                self.accepted = True

            def ignore(self):
                self.ignored = True

        try:
            pixel_event = _WheelEvent(pixel=15)
            self.assertTrue(calendar.eventFilter(calendar, pixel_event))
            self.assertTrue(pixel_event.accepted)
            self.assertEqual(scrollbar.value(), 235)

            wheel_event = _WheelEvent(angle=-120)
            calendar.wheelEvent(wheel_event)
            self.assertTrue(wheel_event.accepted)
            self.assertEqual(scrollbar.value(), 307)

            orphan = FocusWheelCalendarWidget()
            try:
                ignored_event = _WheelEvent(angle=120)
                orphan.wheelEvent(ignored_event)
                self.assertTrue(ignored_event.ignored)
            finally:
                orphan.close()
        finally:
            scroll.close()

    def test_calendar_wheel_forwarding_scrolls_parent_scroll_area(self):
        scroll = QScrollArea()
        content = QWidget()
        scroll.setWidget(content)
        calendar = FocusWheelCalendarWidget(content)
        scrollbar = scroll.verticalScrollBar()
        scrollbar.setRange(0, 500)
        scrollbar.setValue(250)
        scrollbar.setSingleStep(10)

        class _Delta:
            def __init__(self, value):
                self._value = value

            def y(self):
                return self._value

        class _WheelEvent:
            def pixelDelta(self):
                return _Delta(0)

            def angleDelta(self):
                return _Delta(120)

        try:
            self.assertIs(FocusWheelCalendarWidget._find_scroll_area_parent(content), scroll)
            self.assertTrue(calendar._forward_wheel_to_parent_scroll_area(calendar, _WheelEvent()))
            self.assertEqual(scrollbar.value(), 178)
        finally:
            scroll.close()


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest import mock

try:
    from PySide6.QtCore import QEvent, Qt
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    Qt = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.selection_scope import (
    SelectionScopeBanner,
    SelectionScopeState,
    TrackChoice,
    TrackSelectionChooserDialog,
    build_selection_preview,
)
from tests.qt_test_helpers import require_qapplication


class SelectionScopePreviewTests(unittest.TestCase):
    def test_build_selection_preview_falls_back_and_deduplicates(self):
        def lookup(track_id: int) -> str:
            return {1: "Track 1", 2: "Track 1", 3: "", 4: "Track 4"}.get(track_id, "")

        preview = build_selection_preview([1, 2, 3, 4], lookup)
        self.assertEqual(preview, "Track 1, Track 3, Track 4 +1 more")

    def test_build_selection_preview_fallback_text_and_short_circuit(self):
        preview = build_selection_preview((99,), lambda track_id: None, max_titles=1)
        self.assertEqual(preview, "Track 99")

        no_tracks = build_selection_preview([], lambda track_id: "ignored")
        self.assertEqual(no_tracks, "No tracks selected.")


class SelectionScopeBannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if Qt is None:
            raise unittest.SkipTest(f"PySide6.QtCore unavailable: {QT_IMPORT_ERROR}")
        cls._app = require_qapplication()

    def test_set_state_toggles_clear_override_and_counts(self):
        banner = SelectionScopeBanner(
            chooser_label="Choose",
            show_use_current_button=True,
            show_choose_button=True,
            show_clear_override_button=True,
        )

        banner.set_state(
            SelectionScopeState(
                source_label="Catalog",
                track_ids=(1, 2, 3),
                preview_text="1,2,3",
                override_active=False,
            )
        )
        self.assertEqual(banner.scope_label.text(), "Catalog")
        self.assertEqual(banner.count_label.text(), "3 tracks")
        self.assertEqual(banner.preview_label.text(), "1,2,3")
        self.assertFalse(banner.clear_override_button.isEnabled())

        banner.set_state(
            SelectionScopeState(
                source_label="Manual",
                track_ids=(4,),
                preview_text="Manual track",
                override_active=True,
            )
        )
        self.assertTrue(banner.clear_override_button.isEnabled())

    def test_set_header_visibility_path(self):
        banner = SelectionScopeBanner(show_header=False)
        self.assertFalse(banner.scope_label.isVisible())


class TrackSelectionChooserDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if Qt is None:
            raise unittest.SkipTest(f"PySide6.QtCore unavailable: {QT_IMPORT_ERROR}")
        cls._app = require_qapplication()

    def _create_choices(self):
        return [
            TrackChoice(101, "First", "Catalog row 1"),
            TrackChoice(102, "Second", "Catalog row 2"),
            TrackChoice(103, "Third", "Other"),
        ]

    def test_filter_and_checkbox_actions(self):
        dialog = TrackSelectionChooserDialog(
            track_choices=self._create_choices(),
            initial_track_ids=(102,),
            parent=None,
        )
        try:
            self.assertEqual(dialog.selection_table.rowCount(), 3)
            first_checkbox = dialog.selection_table.item(0, 0)
            second_checkbox = dialog.selection_table.item(1, 0)
            self.assertIsNotNone(first_checkbox)
            self.assertIsNotNone(second_checkbox)
            self.assertEqual(first_checkbox.checkState(), Qt.Unchecked)
            self.assertEqual(second_checkbox.checkState(), Qt.Checked)

            dialog.filter_edit.setText("third")
            self.assertTrue(dialog.selection_table.isRowHidden(0))
            self.assertTrue(dialog.selection_table.isRowHidden(1))
            self.assertFalse(dialog.selection_table.isRowHidden(2))

            dialog.filter_edit.setText("")
            self.assertFalse(dialog.selection_table.isRowHidden(1))
            dialog._select_all_visible()
            self.assertEqual(dialog.selection_table.item(0, 0).checkState(), Qt.Checked)

            dialog._clear_all()
            self.assertEqual(dialog.selection_table.item(1, 0).checkState(), Qt.Unchecked)
        finally:
            dialog.close()

    def test_selected_track_ids_returns_only_checked_rows(self):
        dialog = TrackSelectionChooserDialog(
            track_choices=self._create_choices(),
            initial_track_ids=(101, 103),
            parent=None,
        )
        try:
            first_checkbox = dialog.selection_table.item(0, 0)
            second_checkbox = dialog.selection_table.item(1, 0)
            third_checkbox = dialog.selection_table.item(2, 0)
            self.assertIsNotNone(first_checkbox)
            self.assertIsNotNone(second_checkbox)
            first_checkbox.setCheckState(Qt.Checked)
            second_checkbox.setCheckState(Qt.Unchecked)
            third_checkbox.setCheckState(Qt.Unchecked)

            selected = dialog.selected_track_ids()
            self.assertEqual(selected, [101])
        finally:
            dialog.close()

    def test_build_selection_preview_with_lookup_exception_falls_back(self):
        def lookup(track_id: int) -> str:
            raise RuntimeError(f"lookup failed for {track_id}")

        preview = build_selection_preview((21, 22), lookup, max_titles=1)

        self.assertEqual(preview, "Track 21 +1 more")

    def test_select_all_visible_only_updates_visible_rows(self):
        dialog = TrackSelectionChooserDialog(
            track_choices=self._create_choices(),
            initial_track_ids=(),
            parent=None,
        )
        try:
            dialog.filter_edit.setText("Third")
            self.assertTrue(dialog.selection_table.isRowHidden(0))
            self.assertTrue(dialog.selection_table.isRowHidden(1))
            self.assertFalse(dialog.selection_table.isRowHidden(2))

            first_checkbox = dialog.selection_table.item(0, 0)
            second_checkbox = dialog.selection_table.item(1, 0)
            third_checkbox = dialog.selection_table.item(2, 0)
            self.assertIsNotNone(first_checkbox)
            self.assertIsNotNone(second_checkbox)
            self.assertIsNotNone(third_checkbox)
            first_checkbox.setCheckState(Qt.Unchecked)
            second_checkbox.setCheckState(Qt.Unchecked)
            third_checkbox.setCheckState(Qt.Checked)

            dialog._select_all_visible()

            self.assertEqual(first_checkbox.checkState(), Qt.Unchecked)
            self.assertEqual(second_checkbox.checkState(), Qt.Unchecked)
            self.assertEqual(third_checkbox.checkState(), Qt.Checked)
        finally:
            dialog.close()

    def test_selected_track_ids_ignores_invalid_user_data(self):
        dialog = TrackSelectionChooserDialog(
            track_choices=self._create_choices(),
            parent=None,
        )
        try:
            first_checkbox = dialog.selection_table.item(0, 0)
            second_checkbox = dialog.selection_table.item(1, 0)
            self.assertIsNotNone(first_checkbox)
            self.assertIsNotNone(second_checkbox)

            first_checkbox.setCheckState(Qt.Checked)
            second_checkbox.setCheckState(Qt.Checked)
            first_checkbox.setData(Qt.UserRole, "bad-id")

            selected = dialog.selected_track_ids()

            self.assertEqual(selected, [102])
        finally:
            dialog.close()

    def test_event_invokes_layout_sync_for_relevant_events(self):
        banner = SelectionScopeBanner()
        try:
            spy = mock.Mock()
            banner._sync_layout_height = spy
            banner.event(QEvent(QEvent.FontChange))

            spy.assert_called_once()
        finally:
            banner.close()

    def test_event_ignores_non_layout_event_types(self):
        banner = SelectionScopeBanner()
        try:
            spy = mock.Mock()
            banner._sync_layout_height = spy
            banner.event(QEvent(QEvent.FocusIn))

            spy.assert_not_called()
        finally:
            banner.close()

    def test_event_does_not_reenter_layout_sync_when_busy(self):
        banner = SelectionScopeBanner()
        try:
            with mock.patch.object(banner, "layout") as layout_patch:
                banner._syncing_height = True
                banner._sync_layout_height()

            layout_patch.assert_not_called()
        finally:
            banner.close()

    def test_row_text_handles_missing_items_and_selected_ids_skip_bad_entries(self):
        dialog = TrackSelectionChooserDialog(
            track_choices=self._create_choices(),
            initial_track_ids=(101,),
            parent=None,
        )
        try:
            empty_row = dialog.selection_table.rowCount()
            dialog.selection_table.insertRow(empty_row)

            self.assertEqual(dialog._row_text(empty_row), "")

            blank_item = dialog.selection_table.item(0, 0)
            self.assertIsNotNone(blank_item)
            blank_item.setData(Qt.UserRole, None)
            dialog.selection_table.item(2, 0).setData(Qt.UserRole, 303)
            dialog.selection_table.item(2, 0).setCheckState(Qt.Checked)
            selected = dialog.selected_track_ids()

            self.assertEqual(selected, [303])
            dialog.filter_edit.setText("nothing")
            self.assertTrue(dialog.selection_table.isRowHidden(empty_row))
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()

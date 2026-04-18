import json

from isrc_manager.catalog_table.header_state import (
    HEADER_COLUMN_KEYS_JSON_KEY,
    HEADER_LABELS_JSON_KEY,
    HEADER_LABELS_KEY,
    HEADER_STATE_KEY,
    HIDDEN_COLUMN_KEYS_JSON_KEY,
    HIDDEN_COLUMNS_JSON_KEY,
)
from tests.app._app_shell_support import AppShellTestCase


class AppShellCatalogHeaderStateTests(AppShellTestCase):
    test_programmatic_header_resize_does_not_record_history = (
        AppShellTestCase.case_programmatic_header_resize_does_not_record_history
    )
    test_interactive_header_resize_records_a_single_visible_history_entry = (
        AppShellTestCase.case_interactive_header_resize_records_a_single_visible_history_entry
    )

    def _visual_header_labels(self) -> list[str]:
        header = self.window.table.horizontalHeader()
        return [
            self.window.table.horizontalHeaderItem(logical_index).text()
            for logical_index in sorted(
                range(self.window.table.columnCount()),
                key=lambda idx: (
                    header.visualIndex(idx) if header.visualIndex(idx) >= 0 else 10_000 + idx
                ),
            )
            if self.window.table.horizontalHeaderItem(logical_index) is not None
        ]

    def _column_visibility_state(self) -> dict[str, bool]:
        return {
            action.text(): bool(action.isChecked())
            for action in getattr(self.window, "column_visibility_actions", [])
            if action.text()
        }

    def test_header_reorder_hide_show_and_columns_movable_persist_across_restart(self):
        self._create_track(index=210, title="Header Round Trip One")
        self._create_track(index=211, title="Header Round Trip Two")
        self.window.refresh_table()

        self.window._toggle_columns_movable(True)
        self.app.processEvents()

        header = self.window.table.horizontalHeader()
        artist_column = self.window._column_index_by_header("Artist Name")
        genre_column = self.window._column_index_by_header("Genre")
        self.assertGreaterEqual(artist_column, 0)
        self.assertGreaterEqual(genre_column, 0)

        header.moveSection(header.visualIndex(artist_column), 2)
        self.app.processEvents()
        self.window._toggle_column_visibility(genre_column, False)
        self.app.processEvents()
        self.window._save_header_state(record_history=False)

        settings_prefix = self.window._table_settings_prefix()
        self.assertTrue(
            self.window.settings.contains(f"{settings_prefix}/{HEADER_COLUMN_KEYS_JSON_KEY}")
        )
        self.assertTrue(
            self.window.settings.contains(f"{settings_prefix}/{HIDDEN_COLUMN_KEYS_JSON_KEY}")
        )

        header_order_before = self._visual_header_labels()
        visibility_before = self._column_visibility_state()

        self._reopen_window(skip_background_prepare=True)

        self.assertTrue(self.window.act_reorder_columns.isChecked())
        self.assertTrue(self.window.table.horizontalHeader().sectionsMovable())
        self.assertEqual(self._visual_header_labels(), header_order_before)
        self.assertTrue(
            self.window.table.isColumnHidden(self.window._column_index_by_header("Genre"))
        )
        self.assertEqual(self._column_visibility_state().get("Genre"), False)
        self.assertEqual(self._column_visibility_state().get("Artist Name"), True)
        self.assertEqual(self._column_visibility_state(), visibility_before)

    def test_key_based_restore_prefers_column_keys_over_conflicting_legacy_payloads(self):
        self._create_track(index=212, title="Header Key Order One")
        self._create_track(index=213, title="Header Key Order Two")
        self.window.refresh_table()

        self.assertTrue(
            self.window._apply_custom_field_configuration(
                [
                    {
                        "id": None,
                        "name": "Session Notes",
                        "field_type": "text",
                        "options": None,
                    },
                    {
                        "id": None,
                        "name": "Mix Notes",
                        "field_type": "text",
                        "options": None,
                    },
                ],
                action_label="Add Custom Columns: Session Notes, Mix Notes",
                action_type="fields.add",
            )
        )
        self.window.refresh_table()

        header = self.window.table.horizontalHeader()
        mix_notes_column = self.window._column_index_by_header("Mix Notes")
        session_notes_column = self.window._column_index_by_header("Session Notes")
        track_title_column = self.window._column_index_by_header("Track Title")
        self.assertGreaterEqual(mix_notes_column, 0)
        self.assertGreaterEqual(session_notes_column, 0)
        self.assertGreaterEqual(track_title_column, 0)

        header.moveSection(header.visualIndex(mix_notes_column), 2)
        self.app.processEvents()
        self.window._toggle_column_visibility(session_notes_column, False)
        self.app.processEvents()
        self.window._save_header_state(record_history=False)

        settings_prefix = self.window._table_settings_prefix()
        settings = self.window.settings
        saved_key_order = json.loads(
            settings.value(f"{settings_prefix}/{HEADER_COLUMN_KEYS_JSON_KEY}", "[]", str)
        )
        saved_hidden_keys = json.loads(
            settings.value(f"{settings_prefix}/{HIDDEN_COLUMN_KEYS_JSON_KEY}", "[]", str)
        )
        self.assertTrue(saved_key_order)
        self.assertTrue(saved_hidden_keys)

        legacy_label_order = [
            self.window.table.horizontalHeaderItem(logical_index).text()
            for logical_index in range(self.window.table.columnCount())
            if self.window.table.horizontalHeaderItem(logical_index) is not None
        ]
        settings.remove(f"{settings_prefix}/{HEADER_STATE_KEY}")
        settings.setValue(f"{settings_prefix}/{HEADER_LABELS_KEY}", legacy_label_order)
        settings.setValue(
            f"{settings_prefix}/{HEADER_LABELS_JSON_KEY}",
            json.dumps(legacy_label_order),
        )
        settings.setValue(f"{settings_prefix}/{HIDDEN_COLUMNS_JSON_KEY}", json.dumps([]))
        settings.sync()

        previous_suspend_state = self.window._suspend_layout_history
        self.window._suspend_layout_history = True
        try:
            self.window.table.setColumnHidden(session_notes_column, False)
            header.moveSection(
                header.visualIndex(mix_notes_column),
                self.window.table.columnCount() - 1,
            )
        finally:
            self.window._suspend_layout_history = previous_suspend_state

        self.window._load_header_state()
        self.app.processEvents()

        visual_labels = self._visual_header_labels()
        self.assertLess(visual_labels.index("Mix Notes"), visual_labels.index("Track Title"))
        self.assertTrue(
            self.window.table.isColumnHidden(self.window._column_index_by_header("Session Notes"))
        )


del AppShellTestCase

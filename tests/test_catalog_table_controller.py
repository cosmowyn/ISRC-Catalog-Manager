import unittest

from tests.qt_test_helpers import pump_events, require_qapplication

try:
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QAbstractItemView = None
    QItemSelectionModel = None
    QTableWidget = None
    QTableWidgetItem = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.catalog_table.controller import CatalogTableController


class CatalogTableControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def setUp(self):
        if QTableWidget is None or QTableWidgetItem is None or QItemSelectionModel is None:
            raise unittest.SkipTest(f"PySide6 Qt unavailable: {QT_IMPORT_ERROR}")
        self._tables: list[QTableWidget] = []

    def tearDown(self):
        for table in self._tables:
            table.close()
            table.deleteLater()
        pump_events(app=self.app, cycles=2)

    def _make_table(self) -> tuple[QTableWidget, CatalogTableController]:
        table = QTableWidget(3, 4)
        table.setHorizontalHeaderLabels(["ID", "Audio File", "Track Title", "Mood"])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        rows = (
            ("1", "", "One", "Bright"),
            ("2", "", "Two", "Warm"),
            ("3", "", "Three", "Dark"),
        )
        for row_index, row_values in enumerate(rows):
            for column_index, value in enumerate(row_values):
                table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
        table.show()
        self._tables.append(table)
        pump_events(app=self.app, cycles=2)

        controller = CatalogTableController()
        controller.bind_view(table)
        controller.bind_widget_seams(
            track_id_for_row=lambda row: int(table.item(int(row), 0).text()),
            is_row_hidden=table.isRowHidden,
        )
        return table, controller

    def test_widget_selection_helpers_skip_hidden_rows_and_preserve_export_semantics(self):
        table, controller = self._make_table()
        table.setRowHidden(1, True)
        table.selectAll()
        pump_events(app=self.app, cycles=2)

        self.assertEqual(controller.selected_track_ids(), (1, 3))
        self.assertEqual(controller.visible_track_ids(), (1, 3))
        self.assertEqual(controller.selected_or_visible_track_ids(), (1, 3))

        table.clearSelection()
        selection_model = table.selectionModel()
        selection_model.select(
            table.model().index(2, 0),
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        pump_events(app=self.app, cycles=2)

        self.assertEqual(controller.default_conversion_track_ids(), (3,))

    def test_prepare_context_menu_selection_preserves_multi_select_on_selected_row(self):
        table, controller = self._make_table()
        selection_model = table.selectionModel()
        for row in (0, 1):
            selection_model.select(
                table.model().index(row, 0),
                QItemSelectionModel.Select | QItemSelectionModel.Rows,
            )
        pump_events(app=self.app, cycles=2)

        selected_index = controller.prepare_context_menu_selection(table.model().index(0, 1))
        self.assertEqual(selected_index.row(), 0)
        self.assertEqual(controller.selected_track_ids(), (1, 2))
        self.assertEqual(controller.effective_context_menu_track_ids(selected_index), (1, 2))

        other_index = controller.prepare_context_menu_selection(table.model().index(2, 1))
        self.assertEqual(other_index.row(), 2)
        self.assertEqual(controller.selected_track_ids(), (3,))
        self.assertEqual(controller.effective_context_menu_track_ids(other_index), (3,))

    def test_cell_target_resolves_standard_and_custom_columns_for_widget_backend(self):
        table, controller = self._make_table()
        custom_fields = [{"id": 7, "name": "Mood", "field_type": "text", "options": None}]

        audio_target = controller.cell_target(
            table.model().index(0, 1),
            base_column_count=3,
            custom_fields=custom_fields,
        )
        self.assertEqual(audio_target.track_id, 1)
        self.assertEqual(audio_target.kind, "standard")
        self.assertEqual(audio_target.standard_field_key, "audio_file")
        self.assertEqual(audio_target.standard_media_key, "audio_file")

        title_target = controller.cell_target(
            table.model().index(0, 2),
            base_column_count=3,
            custom_fields=custom_fields,
        )
        self.assertEqual(title_target.kind, "standard")
        self.assertEqual(title_target.standard_field_key, "track_title")
        self.assertIsNone(title_target.standard_media_key)

        custom_target = controller.cell_target(
            table.model().index(0, 3),
            base_column_count=3,
            custom_fields=custom_fields,
        )
        self.assertEqual(custom_target.track_id, 1)
        self.assertEqual(custom_target.kind, "custom")
        self.assertEqual(custom_target.custom_field_id, 7)
        self.assertEqual(custom_target.custom_field_type, "text")

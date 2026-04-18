import unittest

from tests.qt_test_helpers import pump_events, require_qapplication

try:
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QAbstractItemView, QTableView
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QAbstractItemView = None
    QItemSelectionModel = None
    QTableView = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.catalog_table.controller import CatalogTableController
from isrc_manager.catalog_table.filter_proxy import CatalogFilterProxyModel
from isrc_manager.catalog_table.models import (
    CatalogCellValue,
    CatalogColumnSpec,
    CatalogRowSnapshot,
    CatalogSnapshot,
)
from isrc_manager.catalog_table.table_model import CatalogTableModel


class CatalogTableControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def setUp(self):
        if QTableView is None or QItemSelectionModel is None:
            raise unittest.SkipTest(f"PySide6 Qt unavailable: {QT_IMPORT_ERROR}")
        self._views: list[QTableView] = []
        self._models: list[CatalogTableModel] = []

    def tearDown(self):
        for view in self._views:
            view.close()
            view.deleteLater()
        pump_events(app=self.app, cycles=2)
        self._models.clear()

    def _make_table(
        self,
    ) -> tuple[QTableView, CatalogTableController, CatalogFilterProxyModel]:
        model = CatalogTableModel(
            snapshot=CatalogSnapshot(
                column_specs=(
                    CatalogColumnSpec(key="base:id", header_text="ID"),
                    CatalogColumnSpec(key="base:audio_file", header_text="Audio File"),
                    CatalogColumnSpec(key="base:track_title", header_text="Track Title"),
                    CatalogColumnSpec(key="custom:7", header_text="Mood"),
                ),
                rows=(
                    CatalogRowSnapshot(
                        track_id=1,
                        cells_by_key={
                            "base:id": CatalogCellValue(display_text="1", raw_value=1),
                            "base:audio_file": CatalogCellValue(display_text=""),
                            "base:track_title": CatalogCellValue(display_text="One"),
                            "custom:7": CatalogCellValue(display_text="Bright"),
                        },
                    ),
                    CatalogRowSnapshot(
                        track_id=2,
                        cells_by_key={
                            "base:id": CatalogCellValue(display_text="2", raw_value=2),
                            "base:audio_file": CatalogCellValue(display_text=""),
                            "base:track_title": CatalogCellValue(display_text="Two"),
                            "custom:7": CatalogCellValue(display_text="Warm"),
                        },
                    ),
                    CatalogRowSnapshot(
                        track_id=3,
                        cells_by_key={
                            "base:id": CatalogCellValue(display_text="3", raw_value=3),
                            "base:audio_file": CatalogCellValue(display_text=""),
                            "base:track_title": CatalogCellValue(display_text="Three"),
                            "custom:7": CatalogCellValue(display_text="Dark"),
                        },
                    ),
                ),
            )
        )
        proxy = CatalogFilterProxyModel()
        proxy.setSourceModel(model)
        table = QTableView()
        table.setModel(proxy)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.show()
        self._views.append(table)
        self._models.append(model)
        pump_events(app=self.app, cycles=2)

        controller = CatalogTableController()
        controller.bind_view(table)
        controller.bind_models(table_model=model, filter_proxy=proxy)
        return table, controller, proxy

    def test_model_selection_helpers_use_proxy_visible_rows_for_export_semantics(self):
        table, controller, proxy = self._make_table()
        proxy.set_explicit_track_ids([1, 3])
        table.selectAll()
        pump_events(app=self.app, cycles=2)

        self.assertEqual(controller.selected_track_ids(), (1, 3))
        self.assertEqual(controller.visible_track_ids(), (1, 3))
        self.assertEqual(controller.selected_or_visible_track_ids(), (1, 3))

        table.clearSelection()
        selection_model = table.selectionModel()
        selection_model.select(
            table.model().index(1, 0),
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        pump_events(app=self.app, cycles=2)

        self.assertEqual(controller.default_conversion_track_ids(), (3,))

    def test_prepare_context_menu_selection_preserves_multi_select_on_selected_row(self):
        table, controller, _proxy = self._make_table()
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
        table, controller, _proxy = self._make_table()
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

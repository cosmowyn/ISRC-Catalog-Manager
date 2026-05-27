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

    def test_unbound_controller_helpers_return_empty_state_safely(self):
        controller = CatalogTableController()

        self.assertIsNone(controller.source_model())
        self.assertIsNone(controller.proxy_model())
        self.assertIsNone(controller.active_model())
        self.assertFalse(controller.map_to_source(CatalogTableModel().index(-1, -1)).isValid())
        self.assertFalse(controller.map_from_source(CatalogTableModel().index(-1, -1)).isValid())
        self.assertFalse(controller.source_index_for_track_id(1).isValid())
        self.assertIsNone(controller.column_for_key(""))
        self.assertIsNone(controller.column_for_key("base:track_title"))
        self.assertEqual(controller.visible_indexes(), ())
        self.assertEqual(controller.visible_indexes(column=-1), ())
        self.assertIsNone(controller.track_id_for_index(CatalogTableModel().index(-1, -1)))
        self.assertIsNone(controller.track_id_for_source_row(0))
        self.assertIsNone(controller.source_row_for_track_id(1))
        self.assertIsNone(controller.current_track_id())
        self.assertEqual(controller.selected_track_ids(), ())
        self.assertEqual(controller.visible_track_ids(), ())
        self.assertEqual(controller.prepare_context_menu_selection(None).isValid(), False)
        self.assertEqual(controller.effective_context_menu_track_ids("bad"), ())
        self.assertEqual(controller.effective_context_menu_track_ids(-1), ())
        self.assertEqual(controller._header_text_for_column(-1), "")
        self.assertEqual(controller._column_key_for_column(-1), "")
        self.assertEqual(
            controller._unique_track_ids([None, "bad", 0, -1, "7", 7, 8]),
            (7, 8),
        )

    def test_selection_falls_back_to_cell_indexes_and_current_index(self):
        table, controller, _proxy = self._make_table()
        selection_model = table.selectionModel()
        selection_model.select(
            table.model().index(0, 2),
            QItemSelectionModel.ClearAndSelect,
        )
        selection_model.select(
            table.model().index(0, 3),
            QItemSelectionModel.Select,
        )
        pump_events(app=self.app, cycles=2)

        self.assertEqual(controller.selected_track_ids(), (1,))

        table.clearSelection()
        selection_model.setCurrentIndex(
            table.model().index(1, 2),
            QItemSelectionModel.NoUpdate,
        )
        pump_events(app=self.app, cycles=2)

        self.assertEqual(controller.current_track_id(), 2)
        self.assertEqual(controller.selected_track_ids(), (2,))

    def test_controller_uses_bound_models_when_view_is_absent_or_source_only(self):
        model = CatalogTableModel(
            snapshot=CatalogSnapshot(
                column_specs=(CatalogColumnSpec(key="base:id", header_text="ID"),),
                rows=(
                    CatalogRowSnapshot(
                        track_id=9,
                        cells_by_key={"base:id": CatalogCellValue(display_text="9", raw_value=9)},
                    ),
                ),
            )
        )
        self._models.append(model)
        controller = CatalogTableController()
        controller.bind_models(table_model=model)

        self.assertIs(controller.active_model(), model)
        self.assertEqual(controller.column_for_key("base:id"), 0)
        self.assertEqual([index.row() for index in controller.visible_indexes()], [0])
        self.assertEqual(controller.visible_track_ids(), (9,))
        self.assertEqual(controller.default_conversion_track_ids(), ())
        self.assertEqual(controller.effective_context_menu_track_ids(9), (9,))

    def test_context_selection_and_cell_targets_cover_unknown_and_fallback_custom_fields(self):
        table, controller, _proxy = self._make_table()
        index = table.model().index(0, 3)

        fallback_custom = controller.cell_target(
            index,
            base_column_count=3,
            custom_fields=[{"id": "not-int", "name": "Mood", "field_type": "dropdown"}],
        )
        self.assertEqual(fallback_custom.kind, "custom")
        self.assertIsNone(fallback_custom.custom_field_id)
        self.assertEqual(fallback_custom.custom_field_type, "dropdown")

        unknown_custom = controller.cell_target(
            index,
            base_column_count=3,
            custom_fields=[],
        )
        self.assertEqual(unknown_custom.kind, "unknown")
        self.assertIsNone(unknown_custom.custom_field)

        standard_by_label = controller.cell_target(
            table.model().index(0, 2),
            base_column_count=3,
            custom_fields=None,
        )
        self.assertEqual(standard_by_label.standard_field_key, "track_title")

        self.assertEqual(
            controller.effective_context_menu_track_ids(
                table.model().index(2, 0),
                selected_track_ids=(1, 2),
            ),
            (3,),
        )
        self.assertEqual(
            controller.effective_context_menu_track_ids(
                table.model().index(1, 0),
                selected_track_ids=(1, 2),
            ),
            (1, 2),
        )

    def test_hidden_row_and_row_guard_paths_do_not_leak_track_ids(self):
        table, controller, _proxy = self._make_table()
        table.hideRow(1)

        self.assertTrue(controller.has_filtered_rows())
        self.assertEqual(controller.visible_track_ids(), (1, 3))

        controller._view = type(
            "ExplodingView",
            (),
            {
                "isRowHidden": lambda self, _row: (_ for _ in ()).throw(RuntimeError("boom")),
                "selectionModel": lambda self: None,
                "model": lambda self: None,
            },
        )()
        self.assertFalse(controller._row_is_hidden(0))

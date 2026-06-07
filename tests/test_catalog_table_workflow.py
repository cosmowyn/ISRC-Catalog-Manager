from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

from tests.qt_test_helpers import pump_events, require_qapplication

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit, QTableView, QWidget
except ImportError as exc:
    QApplication = None
    QLabel = None
    QComboBox = None
    QLineEdit = None
    QTableView = None
    QWidget = None
    QEvent = None
    Qt = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.catalog_table import (
    CatalogFilterProxyModel,
    CatalogTableController,
    CatalogTableModel,
    ColumnKeyRole,
    workflow,
)
from isrc_manager.tasks import TaskFailure


def _fallback_column_key(header_text: str, *, prefix: str, logical_index: int) -> str:
    clean_header = str(header_text or "").strip().lower().replace(" ", "_") or "blank"
    return f"{prefix}:{logical_index}:{clean_header}"


class CatalogTableWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = require_qapplication()

    def setUp(self):
        if QTableView is None or QLabel is None or QLineEdit is None or QComboBox is None:
            raise unittest.SkipTest(f"PySide6 widgets unavailable: {QT_IMPORT_ERROR}")
        self._views: list[QTableView] = []

    def tearDown(self):
        for view in self._views:
            view.close()
            view.deleteLater()
        pump_events(app=self.qt_app, cycles=2)

    def test_column_specs_and_sort_values_cover_fallbacks_hidden_and_custom_types(self):
        app = SimpleNamespace(
            BASE_HEADERS=("ID", "Unknown Header"),
            active_custom_fields=(
                {"id": 7, "name": "Notes", "field_type": "text"},
                {"id": "bad", "name": "", "field_type": "checkbox"},
            ),
            _fallback_header_column_key=_fallback_column_key,
        )

        specs = workflow._catalog_table_column_specs_for_fields(app)

        self.assertEqual(
            [spec.key for spec in specs],
            ["base:id", "base:1:unknown_header", "custom:7", "custom:3:custom_2"],
        )
        self.assertEqual(specs[2].header_text, "Notes")
        self.assertTrue(specs[2].hidden_by_default)
        self.assertEqual(specs[3].header_text, "Custom 2")

        sort_value = workflow._sort_value_for_catalog_cell
        self.assertEqual(
            sort_value(app, header_text="ID", display_text="42", raw_value=None),
            42,
        )
        self.assertEqual(
            sort_value(
                app,
                header_text="Track Length (hh:mm:ss)",
                display_text="00:01:02",
                raw_value=None,
            ),
            62,
        )
        self.assertEqual(
            sort_value(app, header_text="Entry Date", display_text="2026-05-27", raw_value=None),
            20260527,
        )
        self.assertEqual(
            sort_value(
                app,
                header_text="Custom Date",
                display_text="2026-01-02",
                raw_value=None,
                custom_def={"field_type": "date"},
            ),
            20260102,
        )
        self.assertEqual(
            sort_value(
                app,
                header_text="Checkbox",
                display_text="checked",
                raw_value=None,
                custom_def={"field_type": "checkbox"},
            ),
            1,
        )
        self.assertEqual(
            sort_value(app, header_text="Number", display_text="3.5", raw_value=None),
            3.5,
        )
        self.assertEqual(
            sort_value(app, header_text="Text", display_text="Side A", raw_value=None),
            "Side A",
        )

    def test_snapshot_builds_media_badges_and_typed_custom_cells(self):
        app = SimpleNamespace(
            BASE_HEADERS=("ID", "Audio File", "Track Length (hh:mm:ss)"),
            active_custom_fields=(
                {"id": 9, "name": "Recorded", "field_type": "date"},
                {"id": 10, "name": "Artwork Blob", "field_type": "blob_image"},
                {"id": 11, "name": "Approved", "field_type": "checkbox"},
            ),
            _fallback_header_column_key=_fallback_column_key,
        )
        app._catalog_table_column_specs_for_fields = (
            lambda fields=None: workflow._catalog_table_column_specs_for_fields(app, fields)
        )
        app._sort_value_for_catalog_cell = lambda **kwargs: workflow._sort_value_for_catalog_cell(
            app, **kwargs
        )
        app._catalog_cell_value = lambda value, **kwargs: workflow._catalog_cell_value(
            app, value, **kwargs
        )
        app._media_badge_cell_value = lambda meta, **kwargs: workflow._media_badge_cell_value(
            app, meta, **kwargs
        )
        app._standard_media_header_map = lambda: {"Audio File": "audio_file"}
        app._standard_media_key_for_header = lambda _header: "audio_file"
        app._format_blob_badge = lambda mime_type, size_bytes: f"{mime_type}:{size_bytes}"
        app._blob_icon_kind_for_standard_media = lambda _media_key, *, meta: "audio"
        app._standard_media_badge_tooltip = lambda media_key, meta, display: (
            f"{media_key} {meta['storage_mode']} {display}"
        )
        app._blob_icon_spec_for_standard_media = lambda _media_key, *, meta: {
            "system": meta["storage_mode"]
        }
        app._blob_icon_kind_for_storage = lambda kind, *, storage_mode: f"{kind}:{storage_mode}"
        app._storage_mode_badge_label = lambda storage_mode: f"mode:{storage_mode}"
        app._blob_icon_spec_for_custom_field_with_meta = lambda field, *, meta: {
            "field": field["id"],
            "storage": meta["storage_mode"],
        }
        app._resolve_blob_badge_icon = lambda *, spec, kind: f"{kind}:{spec}"
        progress: list[tuple[int, int, str]] = []

        snapshot = workflow._catalog_snapshot_from_dataset(
            app,
            [(5, "", "00:01:05")],
            {(5, 9): "2026-05-27", (5, 11): "yes"},
            blob_badges={
                "standard_media": {
                    (5, "audio_file"): {
                        "has_media": True,
                        "mime_type": "audio/wav",
                        "size_bytes": 123,
                        "storage_mode": "database",
                    }
                },
                "custom_fields": {
                    (5, 10): {
                        "has_blob": True,
                        "mime_type": "image/png",
                        "size_bytes": 64,
                        "storage_mode": "managed_file",
                    }
                },
            },
            progress_callback=lambda value, maximum, message: progress.append(
                (value, maximum, message)
            ),
        )

        row = snapshot.rows[0]
        self.assertEqual(row.track_id, 5)
        self.assertEqual(row.cells_by_key["base:track_length_sec"].display_text, "00:01:05")
        self.assertEqual(row.cells_by_key["base:track_length_sec"].raw_value, 65)
        self.assertEqual(row.cells_by_key["base:audio_file"].raw_value, (5, "audio_file"))
        self.assertEqual(row.cells_by_key["base:audio_file"].decoration_key, "audio")
        self.assertIn("database", str(row.cells_by_key["base:audio_file"].tooltip))
        self.assertEqual(row.cells_by_key["custom:9"].sort_value, 20260527)
        self.assertEqual(row.cells_by_key["custom:10"].raw_value, (5, 10))
        self.assertIn("mode:managed_file", str(row.cells_by_key["custom:10"].tooltip))
        self.assertEqual(row.cells_by_key["custom:11"].sort_value, 1)
        self.assertEqual(progress[-1][:2], (1, 1))

    def test_apply_catalog_model_dataset_updates_filters_counts_duration_and_combos(self):
        source_model = CatalogTableModel()
        proxy_model = CatalogFilterProxyModel()
        proxy_model.setSourceModel(source_model)
        table = QTableView()
        table.setModel(proxy_model)
        table.show()
        self._views.append(table)

        controller = CatalogTableController()
        controller.bind_view(table)
        controller.bind_models(table_model=source_model, filter_proxy=proxy_model)

        calls: list[str] = []
        combo_payloads: list[dict[str, list[str]]] = []
        progress: list[tuple[int, int, str]] = []
        app = SimpleNamespace(
            BASE_HEADERS=("ID", "Track Title", "Track Length (hh:mm:ss)"),
            active_custom_fields=[],
            table=table,
            search_field=QLineEdit(),
            search_column_combo=QComboBox(),
            count_label=QLabel(),
            duration_label=QLabel(),
            _catalog_table_model=source_model,
            _catalog_filter_proxy_model=proxy_model,
            _fallback_header_column_key=_fallback_column_key,
        )
        app._catalog_source_model = lambda: workflow._catalog_source_model(app)
        app._catalog_proxy_model = lambda: workflow._catalog_proxy_model(app)
        app._catalog_view_row_count = lambda: workflow._catalog_view_row_count(app)
        app._catalog_view_column_count = lambda: workflow._catalog_view_column_count(app)
        app._catalog_table_controller = lambda: controller
        app._selected_search_column_key = lambda: workflow._selected_search_column_key(app)
        app._apply_catalog_search_filter = lambda: workflow._apply_catalog_search_filter(app)
        app._sync_catalog_count_label = lambda: workflow._sync_catalog_count_label(app)
        app._sync_catalog_duration_label = lambda: workflow._sync_catalog_duration_label(app)
        app._refresh_workspace_selection_scopes = lambda: calls.append("workspace scopes")
        app._rebuild_table_headers = lambda: calls.append("headers rebuilt")
        app._apply_catalog_combo_values = lambda values: combo_payloads.append(values)
        app._catalog_table_column_specs_for_fields = (
            lambda fields=None: workflow._catalog_table_column_specs_for_fields(app, fields)
        )
        app._sort_value_for_catalog_cell = lambda **kwargs: workflow._sort_value_for_catalog_cell(
            app, **kwargs
        )
        app._catalog_cell_value = lambda value, **kwargs: workflow._catalog_cell_value(
            app, value, **kwargs
        )
        app._media_badge_cell_value = lambda meta, **kwargs: workflow._media_badge_cell_value(
            app, meta, **kwargs
        )
        app._standard_media_header_map = lambda: {}
        app._catalog_snapshot_from_dataset = lambda rows, cf_map, **kwargs: (
            workflow._catalog_snapshot_from_dataset(app, rows, cf_map, **kwargs)
        )
        app._scaled_progress_callback = lambda callback, *, start, end: (
            lambda value, maximum, message: callback(
                start + int(((value or 0) / max(int(maximum or 1), 1)) * (end - start)),
                end,
                message,
            )
        )

        workflow._apply_catalog_model_dataset(
            app,
            {
                "active_custom_fields": [],
                "rows": [(1, "First", 95), (2, "Second", "00:01:05")],
                "cf_map": {},
                "blob_badges": {},
                "combo_values": {"genres": ["ambient"], "artists": ["Ada"]},
            },
            progress_callback=lambda value, maximum, message: progress.append(
                (value, maximum, message)
            ),
        )

        self.assertEqual(source_model.rowCount(), 2)
        self.assertEqual(proxy_model.search_text(), "")
        self.assertEqual(app.count_label.text(), "showing: 2 records")
        self.assertEqual(app.duration_label.text(), "total: 00:02:40")
        self.assertEqual(combo_payloads, [{"genres": ["ambient"], "artists": ["Ada"]}])
        self.assertIn("headers rebuilt", calls)
        self.assertIn("workspace scopes", calls)
        self.assertTrue(any("Applied prepared media badges" in item[2] for item in progress))

    def test_initialization_dataset_loading_reset_and_sync_refresh_paths(self):
        class _AppWidget(QWidget):
            def __init__(self):
                super().__init__()
                self.table = QTableView(self)
                self.connected = 0

            def _connect_catalog_selection_model(self):
                self.connected += 1

        app_widget = _AppWidget()
        self._views.append(app_widget.table)
        try:
            workflow._initialize_catalog_table_model_view(app_widget)

            self.assertIsInstance(app_widget._catalog_table_model, CatalogTableModel)
            self.assertIsInstance(app_widget._catalog_filter_proxy_model, CatalogFilterProxyModel)
            self.assertTrue(app_widget.table.isSortingEnabled())
            self.assertEqual(app_widget.connected, 1)

            rebuild_calls: list[str] = []
            app_widget.BASE_HEADERS = ("ID", "Track Title")
            app_widget.active_custom_fields = []
            app_widget._fallback_header_column_key = _fallback_column_key
            app_widget._catalog_source_model = lambda: workflow._catalog_source_model(app_widget)
            app_widget._catalog_table_column_specs_for_fields = (
                lambda fields=None: workflow._catalog_table_column_specs_for_fields(
                    app_widget, fields
                )
            )
            app_widget._apply_saved_column_visibility = lambda: rebuild_calls.append("visibility")
            app_widget._rebuild_search_column_choices = lambda: rebuild_calls.append(
                "search choices"
            )
            app_widget._refresh_column_visibility_menu = lambda: rebuild_calls.append("menu")

            workflow._rebuild_table_headers(app_widget)

            self.assertEqual(
                rebuild_calls,
                ["visibility", "search choices", "menu"],
            )
            self.assertEqual(app_widget._catalog_table_model.rowCount(), 0)
        finally:
            app_widget.close()
            app_widget.deleteLater()

        class _SearchField:
            def __init__(self):
                self.text_value = "needle"
                self.blocked: list[bool] = []

            def blockSignals(self, value):
                self.blocked.append(bool(value))

            def clear(self):
                self.text_value = ""

            def setText(self, text):
                self.text_value = str(text)

            def text(self):
                return self.text_value

        search_combo = QComboBox()
        search_combo.addItem("Track Title", "base:track_title")
        reset_calls: list[str] = []
        reset_app = SimpleNamespace(
            search_field=_SearchField(),
            search_column_combo=search_combo,
            _explicit_row_filter_track_ids=(1,),
            _apply_catalog_search_filter=lambda: reset_calls.append("applied"),
        )
        workflow.reset_search(reset_app)
        self.assertIsNone(reset_app._explicit_row_filter_track_ids)
        self.assertEqual(reset_app.search_field.text(), "")
        self.assertEqual(reset_calls, ["applied"])

        workflow._set_catalog_filter_text(reset_app, None)
        self.assertEqual(reset_app.search_field.text(), "")
        workflow._set_catalog_filter_from_current_cell(SimpleNamespace(table=None))

        class _Definitions:
            def list_active_fields(self):
                return [{"id": 1, "name": "Mood", "field_type": "text"}]

        class _Reads:
            def __init__(self):
                self.progress_callbacks = []

            def fetch_rows_with_customs(self, fields, *, progress_callback=None):
                self.progress_callbacks.append(progress_callback)
                if progress_callback is not None:
                    progress_callback(1, 2, "rows")
                return [(9, "Track")], {(9, 1): "bright"}

            def fetch_blob_badge_payload(self, track_ids, fields, **kwargs):
                self.progress_callbacks.append(kwargs.get("progress_callback"))
                return {"standard_media": {}, "custom_fields": {}}

        progress: list[tuple[int, int, str]] = []
        reads = _Reads()
        load_app = SimpleNamespace(
            conn=object(),
            catalog_reads=reads,
            track_service=object(),
            custom_field_values=object(),
            load_active_custom_fields=mock.Mock(
                side_effect=AssertionError("explicit service expected")
            ),
            _scaled_progress_callback=lambda callback, *, start, end: callback,
            _catalog_combo_values_from_connection=lambda conn, progress_callback=None: (
                progress_callback(1, 1, "combos") if progress_callback else None
            )
            or {"artists": ["Ada"]},
        )

        dataset = workflow._load_catalog_ui_dataset(
            load_app,
            custom_field_definitions=_Definitions(),
            catalog_reads=reads,
            conn=object(),
            progress_callback=lambda *args: progress.append(args),
        )

        self.assertEqual(dataset["active_custom_fields"][0]["name"], "Mood")
        self.assertEqual(dataset["rows"], [(9, "Track")])
        self.assertEqual(dataset["combo_values"], {"artists": ["Ada"]})
        self.assertTrue(any("Prepared catalog dataset" in item[2] for item in progress))
        self.assertTrue(all(callback is not None for callback in reads.progress_callbacks))
        with self.assertRaisesRegex(ValueError, "Catalog dataset services"):
            workflow._load_catalog_ui_dataset(
                SimpleNamespace(
                    conn=None,
                    catalog_reads=None,
                    load_active_custom_fields=lambda: [],
                )
            )

        empty_snapshot_progress: list[tuple[int, int, str]] = []
        empty_snapshot_app = SimpleNamespace(
            BASE_HEADERS=("ID",),
            active_custom_fields=[],
            _fallback_header_column_key=_fallback_column_key,
        )
        empty_snapshot_app._catalog_table_column_specs_for_fields = (
            lambda fields=None: workflow._catalog_table_column_specs_for_fields(
                empty_snapshot_app, fields
            )
        )
        empty_snapshot = workflow._catalog_snapshot_from_dataset(
            empty_snapshot_app,
            [],
            {},
            progress_callback=lambda *args: empty_snapshot_progress.append(args),
        )
        self.assertEqual(empty_snapshot.rows, ())
        self.assertEqual(empty_snapshot_progress, [(1, 1, "No catalog rows needed to be applied.")])

        class _Header:
            def sortIndicatorSection(self):
                return 1

            def sortIndicatorOrder(self):
                return Qt.DescendingOrder

        class _RefreshTable:
            def __init__(self):
                self.sorting = True
                self.sort_history: list[bool] = []

            def isSortingEnabled(self):
                return self.sorting

            def setSortingEnabled(self, value):
                self.sorting = bool(value)
                self.sort_history.append(self.sorting)

            def horizontalHeader(self):
                return _Header()

        refresh_calls: list[object] = []
        refresh_table = _RefreshTable()
        refresh_app = SimpleNamespace(
            table=refresh_table,
            _suspend_layout_history=False,
            _load_catalog_ui_dataset=lambda: {"rows": []},
            _clear_catalog_table_model=lambda: refresh_calls.append("clear"),
            _apply_catalog_model_dataset=lambda dataset: refresh_calls.append(("apply", dataset)),
            _sort_catalog_table=lambda column, order: refresh_calls.append(("sort", column, order)),
        )

        workflow.refresh_table(refresh_app)

        self.assertFalse(refresh_app._suspend_layout_history)
        self.assertEqual(refresh_table.sort_history, [False, True])
        self.assertIn(("sort", 1, Qt.DescendingOrder), refresh_calls)

        refresh_table.sorting = False
        refresh_table.sort_history.clear()
        refresh_calls.clear()
        workflow.refresh_table(refresh_app)
        self.assertEqual(refresh_table.sort_history, [False])
        self.assertNotIn(("sort", 1, Qt.DescendingOrder), refresh_calls)

        class _DurationModel:
            def rowCount(self):
                return 2

            def index(self, row, column):
                return (row, column)

            def data(self, index, role=None):
                if role == workflow.RawValueRole:
                    return "not numeric"
                if index[0] == 0:
                    return "00:00:05"
                raise RuntimeError("bad duration")

        duration_label = QLabel()
        duration_model = _DurationModel()
        duration_table = SimpleNamespace(model=lambda: duration_model)
        duration_app = SimpleNamespace(
            table=duration_table,
            duration_label=duration_label,
            _catalog_table_controller=lambda: SimpleNamespace(column_for_key=lambda _key: 0),
            _catalog_view_row_count=lambda: 2,
        )

        workflow._sync_catalog_duration_label(duration_app)
        self.assertEqual(duration_label.text(), "total: 00:00:05")
        workflow._sync_catalog_duration_label(SimpleNamespace(duration_label=None))

    def test_search_helpers_use_current_cell_selection_and_column_keys_safely(self):
        class _FakeIndex:
            def __init__(self, valid: bool, display: str = ""):
                self._valid = valid
                self._display = display

            def isValid(self) -> bool:
                return self._valid

            def data(self, _role=None) -> str:
                return self._display

        class _Selection:
            def __init__(self, indexes):
                self._indexes = indexes

            def selectedIndexes(self):
                return self._indexes

        class _Table:
            def __init__(self, current, selected, model=None):
                self._current = current
                self._selection = _Selection(selected)
                self._model = model

            def currentIndex(self):
                return self._current

            def selectionModel(self):
                return self._selection

            def model(self):
                return self._model

        class _Combo:
            def __init__(self, value):
                self.value = value

            def currentData(self):
                return self.value

        class _HeaderModel:
            def columnCount(self):
                return 2

            def headerData(self, column, _orientation, role=None):
                if role == ColumnKeyRole:
                    return ("base:id", "base:track_title")[column]
                return ("ID", "Track Title")[column]

        captured_filters: list[str] = []
        app = SimpleNamespace(
            table=_Table(_FakeIndex(False), [_FakeIndex(True, "Filtered Title")]),
            _set_catalog_filter_text=captured_filters.append,
        )
        workflow._set_catalog_filter_from_current_cell(app)
        self.assertEqual(captured_filters, ["Filtered Title"])

        app.table = _Table(_FakeIndex(False), [])
        workflow._set_catalog_filter_from_current_cell(app)
        self.assertEqual(captured_filters, ["Filtered Title"])

        app.table = _Table(_FakeIndex(True, "Current Title"), [])
        workflow._set_catalog_filter_from_current_cell(app)
        self.assertEqual(captured_filters[-1], "Current Title")

        key_app = SimpleNamespace(
            table=_Table(_FakeIndex(False), [], model=_HeaderModel()),
            search_column_combo=_Combo(-1),
        )
        self.assertIsNone(workflow._selected_search_column_key(key_app))
        key_app.search_column_combo = _Combo("custom:7")
        self.assertEqual(workflow._selected_search_column_key(key_app), "custom:7")
        key_app.search_column_combo = _Combo("not-a-number")
        self.assertEqual(workflow._selected_search_column_key(key_app), "not-a-number")
        key_app.search_column_combo = _Combo(1)
        self.assertEqual(workflow._selected_search_column_key(key_app), "base:track_title")
        key_app.search_column_combo = _Combo(5)
        self.assertIsNone(workflow._selected_search_column_key(key_app))

    def test_catalog_workflow_guard_helpers_and_lookup_fallbacks(self):
        class _Signal:
            def __init__(self, *, raises: bool = False):
                self.raises = raises
                self.callbacks = []

            def connect(self, callback):
                if self.raises:
                    raise RuntimeError("connect blocked")
                self.callbacks.append(callback)

        class _SelectionModel:
            def __init__(self, *, raises: bool = False):
                self.selectionChanged = _Signal(raises=raises)

        class _Table:
            def __init__(self, selection_model=None, model=None):
                self._selection_model = selection_model
                self._model = model
                self.hidden_columns: set[int] = set()

            def selectionModel(self):
                return self._selection_model

            def model(self):
                return self._model

            def isColumnHidden(self, index):
                return index in self.hidden_columns

        class _HeaderModel:
            def columnCount(self):
                return 4

            def rowCount(self):
                return 3

            def headerData(self, column, _orientation, role=None):
                if role == ColumnKeyRole:
                    return ("base:id", "base:blank", "base:title", "custom:7")[column]
                return ("ID", "", "Track Title", "Custom")[column]

        class _Combo:
            def __init__(self):
                self.items: list[tuple[str, object]] = []
                self.current = -1
                self.blocked: list[bool] = []

            def count(self):
                return len(self.items)

            def currentData(self):
                return self.items[self.current][1] if 0 <= self.current < len(self.items) else -1

            def blockSignals(self, value):
                self.blocked.append(bool(value))
                return not value

            def clear(self):
                self.items.clear()
                self.current = -1

            def addItem(self, text, data):
                self.items.append((text, data))

            def findData(self, data):
                for index, (_text, item_data) in enumerate(self.items):
                    if item_data == data:
                        return index
                return -1

            def setCurrentIndex(self, index):
                self.current = int(index)

        callbacks: list[str] = []
        app = SimpleNamespace(
            table=_Table(None), _on_catalog_selection_changed=lambda: callbacks.append("changed")
        )
        workflow._connect_catalog_selection_model(SimpleNamespace())
        workflow._connect_catalog_selection_model(app)
        self.assertFalse(hasattr(app, "_catalog_selection_model_connection"))

        selection = _SelectionModel()
        app.table = _Table(selection)
        workflow._connect_catalog_selection_model(app)
        workflow._connect_catalog_selection_model(app)
        self.assertIs(app._catalog_selection_model_connection, selection)
        self.assertEqual(len(selection.selectionChanged.callbacks), 1)
        selection.selectionChanged.callbacks[0]()
        self.assertEqual(callbacks, ["changed"])

        raising_app = SimpleNamespace(table=_Table(_SelectionModel(raises=True)))
        workflow._connect_catalog_selection_model(raising_app)
        self.assertIsNotNone(raising_app._catalog_selection_model_connection)

        header_app = SimpleNamespace(table=_Table(model=None))
        self.assertEqual(workflow._catalog_header_text_for_column(header_app, 0), "")
        header_app.table = _Table(model=_HeaderModel())
        self.assertEqual(workflow._catalog_header_text_for_column(header_app, -1), "")
        self.assertEqual(workflow._catalog_header_text_for_column(header_app, 99), "")
        self.assertEqual(workflow._catalog_header_text_for_column(header_app, 2), "Track Title")

        self.assertEqual(workflow._catalog_view_row_count(SimpleNamespace()), 0)
        self.assertEqual(workflow._catalog_view_column_count(SimpleNamespace()), 0)

        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE TABLE Albums(title TEXT)")
            conn.execute("CREATE TABLE Tracks(genre TEXT)")
            conn.execute("INSERT INTO Albums(title) VALUES ('Album A')")
            conn.execute("INSERT INTO Tracks(genre) VALUES ('Ambient')")
            progress: list[tuple[int, int, str]] = []

            combo_values = workflow._catalog_combo_values_from_connection(
                conn,
                progress_callback=lambda *args: progress.append(args),
            )

            self.assertEqual(combo_values["artists"], [])
            self.assertEqual(combo_values["albums"], ["Album A"])
            self.assertEqual(combo_values["genres"], ["Ambient"])
            self.assertEqual(combo_values["upcs"], [])
            self.assertEqual(combo_values["catalog_numbers"], [])
            self.assertEqual(progress[-1][0], 5)
        finally:
            conn.close()

        populated: list[tuple[object, tuple[str, ...], bool]] = []
        combo_app = SimpleNamespace(
            artist_field=object(),
            additional_artist_field=object(),
            album_title_field=object(),
            upc_field=object(),
            genre_field=object(),
            catalog_number_field=object(),
            _populate_combobox=lambda field, values, allow_empty=False: populated.append(
                (field, tuple(values), allow_empty)
            ),
        )
        workflow._apply_catalog_combo_values(
            combo_app,
            {
                "artists": ["Ada"],
                "albums": ["Album"],
                "upcs": ["123"],
                "genres": ["Pop"],
                "catalog_numbers": ["CAT-1"],
            },
        )
        self.assertEqual(populated[-1][1:], (("CAT-1",), True))

        refresh_calls: list[str] = []
        combo_app.catalog_number_field = SimpleNamespace(
            refresh=lambda: refresh_calls.append("refresh")
        )
        workflow._apply_catalog_combo_values(combo_app, {"catalog_numbers": ["ignored"]})
        self.assertEqual(refresh_calls, ["refresh"])

        no_conn_app = SimpleNamespace(conn=None)
        workflow.populate_all_comboboxes(no_conn_app)
        populated_conn_app = SimpleNamespace(
            conn=object(),
            _catalog_combo_values_from_connection=lambda conn: {"artists": ["Ada"]},
            _apply_catalog_combo_values=lambda values: refresh_calls.append(str(values)),
            _refresh_add_track_artist_party_choices=lambda: refresh_calls.append("artist choices"),
        )
        workflow.populate_all_comboboxes(populated_conn_app)
        self.assertIn("{'artists': ['Ada']}", refresh_calls)
        self.assertIn("artist choices", refresh_calls)

        search_combo = _Combo()
        search_combo.items = [("Custom", "custom:7")]
        search_combo.current = 0
        search_app = SimpleNamespace(
            table=_Table(model=_HeaderModel()),
            search_column_combo=search_combo,
        )
        search_app.table.hidden_columns.add(3)
        workflow._rebuild_search_column_choices(search_app)
        self.assertEqual(
            search_combo.items,
            [("All columns", -1), ("ID", "base:id"), ("Track Title", "base:title")],
        )
        self.assertEqual(search_combo.current, 0)

        filter_calls: list[str] = []
        workflow._apply_catalog_search_filter(
            SimpleNamespace(
                _catalog_proxy_model=lambda: None,
                _sync_catalog_count_label=lambda: filter_calls.append("count"),
                _sync_catalog_duration_label=lambda: filter_calls.append("duration"),
                _refresh_workspace_selection_scopes=lambda: filter_calls.append("workspace"),
            )
        )
        self.assertEqual(filter_calls, ["count", "duration", "workspace"])

    def test_apply_refresh_request_clear_sort_labels_and_restore_branches(self):
        class _Table:
            def __init__(self):
                self.sorting = True
                self.sort_calls: list[tuple[int, object]] = []
                self._model = None

            def isSortingEnabled(self):
                return self.sorting

            def setSortingEnabled(self, value):
                self.sorting = bool(value)

            def sortByColumn(self, column, order):
                self.sort_calls.append((column, order))

            def model(self):
                return self._model

            def verticalScrollBar(self):
                return SimpleNamespace(
                    setValue=lambda value: setattr(self, "v_scroll", value), value=lambda: 0
                )

            def horizontalScrollBar(self):
                return SimpleNamespace(
                    setValue=lambda value: setattr(self, "h_scroll", value), value=lambda: 0
                )

        class _SourceModel:
            def __init__(self):
                self.snapshots = []

            def set_snapshot(self, snapshot):
                self.snapshots.append(snapshot)

        class _Proxy:
            def __init__(self):
                self.track_ids = None

            def set_explicit_track_ids(self, track_ids):
                self.track_ids = track_ids

        class _Label:
            def __init__(self):
                self.text = None

            def setText(self, text):
                self.text = text

        class _Combo:
            def __init__(self):
                self.index = None
                self.blocked: list[bool] = []

            def blockSignals(self, value):
                self.blocked.append(bool(value))
                return False

            def findData(self, data):
                return 2 if data == -1 else -1

            def setCurrentIndex(self, index):
                self.index = index

            def currentData(self):
                return -1

        table = _Table()
        source_model = _SourceModel()
        proxy = _Proxy()
        progress: list[tuple[object, object, str]] = []
        calls: list[object] = []

        @contextmanager
        def _context(name):
            calls.append((name, "enter"))
            try:
                yield
            finally:
                calls.append((name, "exit"))

        app = SimpleNamespace(
            table=table,
            logger=SimpleNamespace(warning=lambda *args: calls.append(("warning", args))),
            search_field=SimpleNamespace(
                text=lambda: "old",
                blockSignals=lambda value: False,
                setText=lambda text: calls.append(("filter", text)),
            ),
            search_column_combo=_Combo(),
            count_label=_Label(),
            duration_label=_Label(),
            _catalog_table_model=source_model,
            _catalog_filter_proxy_model=proxy,
            _explicit_row_filter_track_ids=(1, 2),
            BASE_HEADERS=("ID", "Track Length (hh:mm:ss)"),
            active_custom_fields=[],
            _fallback_header_column_key=_fallback_column_key,
        )
        app._catalog_source_model = lambda: source_model
        app._catalog_proxy_model = lambda: proxy
        app._catalog_table_column_specs_for_fields = (
            lambda fields=None: workflow._catalog_table_column_specs_for_fields(app, fields)
        )
        app._clear_catalog_table_model = lambda: workflow._clear_catalog_table_model(app)
        app._catalog_view_column_count = lambda: 2
        app._sort_catalog_table = lambda column, order: workflow._sort_catalog_table(
            app, column, order
        )
        app._suspend_table_layout_history = lambda: _context("layout")
        app._suspend_catalog_view_updates = lambda: _context("updates")
        app._apply_catalog_model_dataset = lambda dataset, **kwargs: calls.append(
            ("apply", dataset, kwargs)
        )
        app._scaled_progress_callback = lambda callback, *, start, end: callback
        app._load_header_state = mock.Mock(side_effect=RuntimeError("bad header state"))
        app._restore_view_state = lambda state: calls.append(("restore", state))
        app._select_row_by_id = lambda track_id: calls.append(("focus", track_id))
        app._reload_profiles_list = lambda **kwargs: calls.append(("profiles", kwargs))
        app._update_add_data_generated_fields = lambda: calls.append("generated")
        app._refresh_history_actions = lambda: calls.append("history")
        app._refresh_add_track_artist_party_choices = lambda: calls.append("artist choices")
        app._refresh_work_track_creation_context_ui = lambda: calls.append("work context")
        app._flush_pending_catalog_repaints = lambda **kwargs: calls.append(("flush", kwargs))

        workflow._apply_catalog_refresh_request(
            app,
            {"rows": []},
            {
                "view_state": {"sort_col": "bad", "sort_order": Qt.DescendingOrder},
                "sort_enabled": False,
                "focus_id": 8,
                "select_path": "profile.db",
            },
            progress_callback=lambda *args: progress.append(args),
            refresh_history_actions=False,
            refresh_add_track_controls=False,
        )

        self.assertTrue(table.sorting)
        self.assertIn(("focus", 8), calls)
        self.assertIn(("profiles", {"select_path": "profile.db"}), calls)
        self.assertIn("generated", calls)
        self.assertNotIn("history", calls)
        self.assertTrue(any("Restoring saved" in item[2] for item in progress))
        self.assertTrue(app._load_header_state.called)

        table.sorting = False
        calls.clear()
        progress.clear()
        workflow._apply_catalog_refresh_request(
            app,
            {"rows": ["sorted"]},
            {
                "view_state": {"sort_col": 1, "sort_order": Qt.DescendingOrder},
                "sort_enabled": True,
            },
            progress_callback=lambda *args: progress.append(args),
        )
        self.assertTrue(table.sorting)
        self.assertIn("history", calls)
        self.assertIn("artist choices", calls)
        self.assertIn("work context", calls)

        workflow._clear_catalog_table_model(app)
        self.assertTrue(source_model.snapshots)
        self.assertEqual(proxy.track_ids, (1, 2))
        workflow._clear_catalog_table_model(
            SimpleNamespace(
                _catalog_source_model=lambda: None,
                _catalog_proxy_model=lambda: None,
            )
        )

        workflow._sort_catalog_table(app, "not a number", Qt.AscendingOrder)
        self.assertEqual(table.sort_calls[-1][0], 0)
        workflow._sort_catalog_table(app, 20, Qt.AscendingOrder)
        self.assertEqual(table.sort_calls[-1][0], 0)

        workflow._sync_catalog_count_label(SimpleNamespace(table=table))
        app.count_label = None
        workflow._sync_catalog_count_label(app)

        duration_app = SimpleNamespace(duration_label=_Label())
        duration_app._catalog_table_controller = lambda: SimpleNamespace(
            column_for_key=lambda _key: None
        )
        workflow._sync_catalog_duration_label(duration_app)
        self.assertEqual(duration_app.duration_label.text, "")

        restore_calls: list[object] = []
        restore_app = SimpleNamespace(
            search_field=SimpleNamespace(
                blockSignals=lambda value: False,
                setText=lambda text: restore_calls.append(("filter", text)),
            ),
            search_column_combo=_Combo(),
            table=table,
            _sort_catalog_table=lambda column, order: restore_calls.append(("sort", column, order)),
            _apply_catalog_search_filter=lambda: restore_calls.append("filter applied"),
            _normalize_track_ids=lambda values: [int(value) for value in values],
            _select_track_ids_in_table=lambda ids: restore_calls.append(("selected", ids)),
            _select_row_by_id=lambda track_id: restore_calls.append(("current", track_id)),
        )
        workflow._restore_view_state(
            restore_app,
            {
                "filter_text": "needle",
                "search_column_data": "missing",
                "sort_col": 1,
                "sort_order": Qt.DescendingOrder,
                "selected_track_ids": ["3"],
                "current_track_id": 4,
                "v_scroll": 11,
                "h_scroll": 12,
            },
        )
        self.assertEqual(restore_app.search_column_combo.index, 2)
        self.assertIn(("selected", [3]), restore_calls)
        self.assertEqual(table.v_scroll, 11)

        capture_table = SimpleNamespace(
            isSortingEnabled=lambda: True,
            horizontalHeader=lambda: SimpleNamespace(
                sortIndicatorSection=lambda: 2,
                sortIndicatorOrder=lambda: Qt.DescendingOrder,
            ),
            verticalScrollBar=lambda: SimpleNamespace(value=lambda: 4),
            horizontalScrollBar=lambda: SimpleNamespace(value=lambda: 5),
        )
        capture_app = SimpleNamespace(
            table=capture_table,
            search_field=SimpleNamespace(text=lambda: "needle"),
            search_column_combo=SimpleNamespace(currentData=lambda: "custom:7"),
            _catalog_table_controller=lambda: SimpleNamespace(
                selected_track_ids=lambda: (7, 8),
                current_track_id=lambda: 8,
            ),
            _capture_view_state=lambda: {"already": "captured"},
        )
        self.assertEqual(workflow._capture_view_state(capture_app)["selected_track_ids"], [7, 8])
        self.assertEqual(
            workflow._capture_catalog_refresh_request(
                capture_app,
                focus_id=9,
                select_path="profile.db",
            ),
            {
                "view_state": {"already": "captured"},
                "sort_enabled": True,
                "focus_id": 9,
                "select_path": "profile.db",
            },
        )

        bundle_calls: list[object] = []
        bundle_app = SimpleNamespace(
            _load_catalog_ui_dataset=lambda **kwargs: bundle_calls.append(kwargs) or {"ok": True},
            _scaled_progress_callback=lambda callback, *, start, end: (callback, start, end),
        )
        bundle = SimpleNamespace(
            custom_field_definitions="defs",
            catalog_reads="reads",
            track_service="tracks",
            custom_field_values="values",
            conn="conn",
        )
        ctx = SimpleNamespace(report_progress=lambda *_args: None)
        self.assertEqual(
            workflow._load_catalog_ui_dataset_from_bundle(
                bundle_app,
                bundle,
                ctx,
                progress_start=3,
                progress_end=9,
            ),
            {"ok": True},
        )
        self.assertEqual(bundle_calls[0]["catalog_reads"], "reads")

    def test_repaint_update_suspension_and_background_task_edge_paths(self):
        if QWidget is None or QApplication is None or QEvent is None:
            raise unittest.SkipTest(f"PySide6 widgets unavailable: {QT_IMPORT_ERROR}")

        class _BadUpdatesWidget(QWidget):
            def updatesEnabled(self):  # noqa: N802 - Qt API shape
                raise RuntimeError("cannot read updates")

        class _BadSetWidget(QWidget):
            def updatesEnabled(self):  # noqa: N802 - Qt API shape
                return True

            def setUpdatesEnabled(self, _value):  # noqa: N802 - Qt API shape
                raise RuntimeError("cannot set updates")

        class _BadRestoreWidget(QWidget):
            def updatesEnabled(self):  # noqa: N802 - Qt API shape
                return True

            def updateGeometry(self):  # noqa: N802 - Qt API shape
                raise RuntimeError("cannot update geometry")

        widgets = [_BadUpdatesWidget(), _BadSetWidget(), _BadRestoreWidget()]
        try:
            with workflow._suspend_catalog_view_updates(SimpleNamespace(table=widgets[0])):
                pass
            with workflow._suspend_catalog_view_updates(SimpleNamespace(table=widgets[1])):
                pass
            with workflow._suspend_catalog_view_updates(SimpleNamespace(table=widgets[2])):
                pass

            progress: list[tuple[object, object, str]] = []
            with mock.patch.object(workflow.QApplication, "instance", return_value=None):
                workflow._flush_pending_catalog_repaints(
                    SimpleNamespace(),
                    progress_callback=lambda *args: progress.append(args),
                    value=1,
                    maximum=2,
                    message="paint",
                )
            self.assertEqual(progress, [(1, 2, "paint")])

            class _Target:
                def __init__(self, mode):
                    self.mode = mode
                    self.repaint_calls = 0

                def isVisible(self):
                    if self.mode == "visible-error":
                        raise RuntimeError("visible blocked")
                    return self.mode != "hidden"

                def updateGeometry(self):
                    if self.mode == "geometry-error":
                        raise RuntimeError("geometry blocked")

                def update(self):
                    if self.mode == "update-error":
                        raise RuntimeError("update blocked")

                def repaint(self):
                    self.repaint_calls += 1
                    if self.mode == "repaint-error":
                        raise RuntimeError("repaint blocked")

            class _QApp:
                def processEvents(self):
                    raise RuntimeError("process blocked")

            targets = [
                _Target("hidden"),
                _Target("visible-error"),
                _Target("geometry-error"),
                _Target("update-error"),
                _Target("repaint-error"),
                _Target("ok"),
            ]
            repaint_app = SimpleNamespace(_catalog_repaint_targets=lambda: targets)
            with (
                mock.patch.object(workflow.QApplication, "instance", return_value=_QApp()),
                mock.patch.object(
                    workflow,
                    "QCoreApplication",
                    SimpleNamespace(
                        sendPostedEvents=mock.Mock(side_effect=RuntimeError("send blocked"))
                    ),
                ),
            ):
                workflow._flush_pending_catalog_repaints(repaint_app, passes=0)
            self.assertEqual(targets[-1].repaint_calls, 1)

            class _FakeTable:
                def viewport(self):
                    raise RuntimeError("no viewport")

                def horizontalHeader(self):
                    raise RuntimeError("no header")

                def verticalHeader(self):
                    raise RuntimeError("no vertical")

            class _RepaintApp(QWidget):
                def __init__(self):
                    super().__init__()
                    self.table = _FakeTable()

                def centralWidget(self):  # noqa: N802 - Qt API shape
                    return self

                def statusBar(self):  # noqa: N802 - Qt API shape
                    raise RuntimeError("no status")

                def findChildren(self, _type):  # noqa: N802 - Qt API shape
                    return []

            targets = workflow._catalog_repaint_targets(_RepaintApp())
            self.assertEqual(len(targets), 1)

            class _Table:
                def __init__(self):
                    self.sorting = False

                def isSortingEnabled(self):
                    return self.sorting

                def setSortingEnabled(self, value):
                    self.sorting = bool(value)

            callbacks: dict[str, object] = {}
            progress_updates: list[tuple[int, int, str]] = []
            completed: list[str] = []
            app = SimpleNamespace(conn=object(), table=_Table())
            app._capture_catalog_refresh_request = lambda **_kwargs: {
                "sort_enabled": False,
                "view_state": {},
                "focus_id": None,
                "select_path": None,
            }
            app._clear_catalog_table_model = lambda: None
            app._sync_catalog_count_label = lambda: None
            app._sync_catalog_duration_label = lambda: None
            app._load_catalog_ui_dataset_from_bundle = lambda *_args, **_kwargs: {}
            app._scaled_progress_callback = lambda callback, *, start, end: callback
            app._scaled_ui_progress_callback = lambda callback, *, start, end: callback
            app._apply_catalog_refresh_request = lambda *_args, **_kwargs: None
            app._advance_task_ui_progress = lambda *_args, **_kwargs: None
            app._show_background_task_error = lambda *_args, **_kwargs: None
            app._refresh_catalog_ui_in_background = lambda **_kwargs: None
            app._submit_background_bundle_task = lambda **kwargs: callbacks.update(kwargs) or None

            task_id = workflow._refresh_catalog_ui_in_background(
                app,
                on_complete=lambda: completed.append("complete"),
                progress_callback=lambda value, maximum, message: progress_updates.append(
                    (value, maximum, message)
                ),
            )

            self.assertIsNone(task_id)
            self.assertEqual(completed, ["complete"])
            callbacks["on_finished"]()
            self.assertFalse(app.table.sorting)
            callbacks["on_progress"](SimpleNamespace(value=3, maximum=5, message="loading"))
            self.assertEqual(progress_updates, [(3, 5, "loading")])
            callbacks["on_error"](TaskFailure(message="failed", traceback_text="trace"))
            self.assertEqual(completed, ["complete"])
        finally:
            for widget in widgets:
                widget.close()
                widget.deleteLater()

    def test_refresh_catalog_ui_background_callbacks_handle_success_retry_and_failures(self):
        class _Table:
            def __init__(self):
                self.sorting = True

            def isSortingEnabled(self):
                return self.sorting

            def setSortingEnabled(self, value):
                self.sorting = bool(value)

        class _Connection:
            def __init__(self):
                self.commit_calls = 0

            def commit(self):
                self.commit_calls += 1
                raise RuntimeError("commit race")

        class _Context:
            def __init__(self):
                self.statuses: list[str] = []

            def set_status(self, message):
                self.statuses.append(message)

        table = _Table()
        conn = _Connection()
        callbacks: dict[str, object] = {}
        completed: list[str] = []
        app = SimpleNamespace(
            conn=conn,
            table=table,
            refresh_requests=[],
            loaded=[],
            applied=[],
            advanced=[],
            errors=[],
        )
        app._capture_catalog_refresh_request = lambda **kwargs: {
            "sort_enabled": True,
            "view_state": {"sort_col": 1, "sort_order": Qt.DescendingOrder},
            "focus_id": kwargs.get("focus_id"),
            "select_path": kwargs.get("select_path"),
        }
        app._clear_catalog_table_model = lambda: app.refresh_requests.append("clear")
        app._sync_catalog_count_label = lambda: app.refresh_requests.append("count")
        app._sync_catalog_duration_label = lambda: app.refresh_requests.append("duration")
        app._load_catalog_ui_dataset_from_bundle = lambda bundle, ctx, **kwargs: (
            app.loaded.append((bundle, kwargs, tuple(ctx.statuses))) or {"rows": [1]}
        )
        app._scaled_ui_progress_callback = lambda callback, *, start, end: (
            lambda value, maximum, message: callback(value, maximum, f"{start}-{end}:{message}")
        )

        def _apply_refresh_request(dataset, request, **kwargs):
            app.applied.append((dataset, request, kwargs))
            table.setSortingEnabled(bool(request.get("sort_enabled")))

        app._apply_catalog_refresh_request = _apply_refresh_request
        app._advance_task_ui_progress = lambda progress, **kwargs: app.advanced.append(kwargs)
        app._show_background_task_error = lambda title, failure, **kwargs: app.errors.append(
            (title, failure.message, kwargs)
        )
        app._submit_background_bundle_task = lambda **kwargs: callbacks.update(kwargs) or "task-1"
        app._refresh_catalog_ui_in_background = lambda **kwargs: app.refresh_requests.append(
            ("retry", kwargs)
        )

        task_id = workflow._refresh_catalog_ui_in_background(
            app,
            focus_id=7,
            select_path="profile-a",
            on_finished=lambda: completed.append("finished"),
            on_complete=lambda: completed.append("complete"),
        )

        self.assertEqual(task_id, "task-1")
        self.assertFalse(table.sorting)
        context = _Context()
        self.assertEqual(
            callbacks["task_fn"](SimpleNamespace(name="bundle"), context),
            {"rows": [1]},
        )
        callbacks["on_success_before_cleanup"]({"rows": [2]}, lambda *_args: None)
        callbacks["on_success_after_cleanup"]({"rows": [2]})
        callbacks["on_finished"]()

        self.assertEqual(conn.commit_calls, 1)
        self.assertEqual(app.loaded[0][1], {"progress_start": 0, "progress_end": 74})
        self.assertEqual(app.applied[0][0], {"rows": [2]})
        self.assertEqual(app.advanced[0]["value"], 100)
        self.assertEqual(completed, ["finished", "complete"])
        self.assertTrue(table.sorting)

        callbacks.clear()
        completed.clear()
        workflow._refresh_catalog_ui_in_background(
            app,
            on_complete=lambda: completed.append("done"),
        )
        with mock.patch.object(workflow.QTimer, "singleShot", side_effect=lambda _ms, fn: fn()):
            callbacks["on_error"](
                TaskFailure(
                    message="Exclusive database task is currently running",
                    traceback_text="",
                )
            )
        self.assertEqual(app.refresh_requests[-1][0], "retry")
        self.assertEqual(app.refresh_requests[-1][1]["retry_count"], 1)
        self.assertEqual(completed, [])

        callbacks["on_error"](TaskFailure(message="database unavailable", traceback_text="trace"))
        self.assertEqual(app.errors[-1][0], "Load Catalog")
        self.assertEqual(app.errors[-1][1], "database unavailable")
        self.assertEqual(completed, ["done"])

        no_connection_complete: list[str] = []
        self.assertIsNone(
            workflow._refresh_catalog_ui_in_background(
                SimpleNamespace(conn=None),
                on_complete=lambda: no_connection_complete.append("done"),
            )
        )
        self.assertEqual(no_connection_complete, ["done"])


if __name__ == "__main__":
    unittest.main()

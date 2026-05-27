from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from tests.qt_test_helpers import pump_events, require_qapplication

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QTableView
except ImportError as exc:
    QLabel = None
    QComboBox = None
    QLineEdit = None
    QTableView = None
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

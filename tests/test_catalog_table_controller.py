import sys
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

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

from isrc_manager.catalog_table import context_menu
from isrc_manager.catalog_table.controller import CatalogTableController
from isrc_manager.catalog_table.filter_proxy import CatalogFilterProxyModel
from isrc_manager.catalog_table.models import (
    CatalogCellValue,
    CatalogColumnSpec,
    CatalogRowSnapshot,
    CatalogSnapshot,
)
from isrc_manager.catalog_table.table_model import CatalogTableModel


class _FakeSignal:
    def __init__(self):
        self._callback = None

    def connect(self, callback):
        self._callback = callback

    def trigger(self):
        if self._callback is not None:
            return self._callback()
        return None


class _FakeAction:
    def __init__(self, text, _parent=None):
        self._text = text
        self.triggered = _FakeSignal()

    def text(self):
        return self._text

    def trigger(self):
        return self.triggered.trigger()


class _FakeMenu:
    instances = []

    def __init__(self, *_args, title=""):
        self.title = title
        self.items = []
        self.executed_at = None
        self.__class__.instances.append(self)

    @classmethod
    def reset(cls):
        cls.instances = []

    def addAction(self, action):
        self.items.append(action)
        return action

    def addSeparator(self):
        self.items.append(None)

    def addMenu(self, title):
        menu = self.__class__(title=title)
        self.items.append(menu)
        return menu

    def exec(self, pos):
        self.executed_at = pos


class _FakeMessageBox:
    Yes = 1
    No = 2
    answer = Yes
    questions = []
    informations = []
    criticals = []

    @classmethod
    def reset(cls):
        cls.answer = cls.Yes
        cls.questions = []
        cls.informations = []
        cls.criticals = []

    @classmethod
    def question(cls, *args):
        cls.questions.append(args)
        return cls.answer

    @classmethod
    def information(cls, *args):
        cls.informations.append(args)

    @classmethod
    def critical(cls, *args):
        cls.criticals.append(args)


class _FakeIndex:
    def __init__(self, row=0, column=0, *, valid=True, text="", siblings=None):
        self._row = row
        self._column = column
        self._valid = valid
        self._text = text
        self._siblings = dict(siblings or {})

    def isValid(self):
        return self._valid

    def row(self):
        return self._row

    def column(self):
        return self._column

    def data(self, _role=None):
        return self._text

    def siblingAtColumn(self, column):
        value = self._siblings.get(column, "")
        if isinstance(value, _FakeIndex):
            return value
        return _FakeIndex(
            self._row,
            column,
            valid=value is not None,
            text=str(value or ""),
            siblings=self._siblings,
        )


class _FakeCatalogTable:
    def __init__(self, index):
        self._index = index
        self._model = SimpleNamespace(
            index=lambda row, column: _FakeIndex(row, column, text=f"r{row}c{column}")
        )

    def indexAt(self, _pos):
        return self._index

    def model(self):
        return self._model

    def viewport(self):
        return SimpleNamespace(mapToGlobal=lambda pos: ("global", pos))


class _FakeCatalogController:
    def __init__(
        self,
        target,
        *,
        selected_ids=(),
        effective_ids=None,
        columns=None,
        audio_index=None,
    ):
        self.target = target
        self.selected_ids = tuple(selected_ids)
        self.effective_ids = tuple(effective_ids or selected_ids)
        self.columns = dict(columns or {})
        self.audio_index = audio_index or _FakeIndex(valid=True)

    def prepare_context_menu_selection(self, index):
        return index

    def cell_target(self, *_args, **_kwargs):
        return self.target

    def selected_track_ids(self):
        return self.selected_ids

    def effective_context_menu_track_ids(self, *_args, **_kwargs):
        return self.effective_ids

    def column_for_key(self, key):
        return self.columns.get(key)

    def view_index_for_track_id(self, _track_id, *, column=None):
        if column is None:
            return None
        return self.audio_index


class _FakeConnection:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


class _FakeLogger:
    def __init__(self):
        self.exceptions = []

    def exception(self, *args):
        self.exceptions.append(args)


class _FakeCustomFieldDefinitions:
    def __init__(self, name="", *, raises=False):
        self.name = name
        self.raises = raises

    def get_field_name(self, _field_id):
        if self.raises:
            raise RuntimeError("field lookup failed")
        return self.name


class _FakeContextMenuApp:
    BASE_HEADERS = ("ID", "Audio File", "Track Title")
    active_custom_fields = ()

    def __init__(
        self,
        target,
        index=None,
        *,
        selected_ids=(),
        effective_ids=None,
        ordered_ids=None,
        columns=None,
        standard_payload=True,
        custom_payload=True,
        track_media=False,
        proxy_model=object(),
        standard_targets=(),
        custom_targets=(),
        media_export_spec=None,
        release_id=None,
        linked_works=(),
        track_title="Track Title",
        custom_field_name="",
        custom_field_name_raises=False,
        cf_has_blob=True,
        cf_fetch_blob=b"blob",
    ):
        self.table = _FakeCatalogTable(index or _FakeIndex(text="cell"))
        self.controller = _FakeCatalogController(
            target,
            selected_ids=selected_ids,
            effective_ids=effective_ids,
            columns=columns,
        )
        self.calls = []
        self.release_service = (
            SimpleNamespace(
                find_primary_release_for_track=lambda _track_id: SimpleNamespace(id=release_id)
            )
            if release_id is not None
            else None
        )
        self.work_service = (
            SimpleNamespace(list_works_for_track=lambda _track_id: list(linked_works))
            if linked_works is not None
            else None
        )
        self.ordered_ids = list(ordered_ids) if ordered_ids is not None else None
        self.standard_payload = standard_payload
        self.custom_payload = custom_payload
        self.track_media = track_media
        self.proxy_model = proxy_model
        self.standard_targets = tuple(standard_targets)
        self.custom_targets = tuple(custom_targets)
        self.media_export_spec = media_export_spec
        self.track_title = track_title
        self.track_title_raises = False
        self.custom_field_definitions = _FakeCustomFieldDefinitions(
            custom_field_name,
            raises=custom_field_name_raises,
        )
        self.cf_has_blob_value = cf_has_blob
        self.cf_has_blob_raises = False
        self.cf_fetch_blob_value = cf_fetch_blob
        self.cf_fetch_blob_raises = False
        self.history_raises = False
        self.conn = _FakeConnection()
        self.logger = _FakeLogger()

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def _catalog_table_controller(self):
        return self.controller

    def _proxy_ordered_track_ids(self, track_ids):
        return self.ordered_ids or list(track_ids)

    def open_selected_editor(self, *args, **kwargs):
        self._record("open_selected_editor", *args, **kwargs)

    def open_album_track_ordering_dialog(self, *args, **kwargs):
        self._record("open_album_track_ordering_dialog", *args, **kwargs)

    def open_gs1_dialog(self, *args, **kwargs):
        self._record("open_gs1_dialog", *args, **kwargs)

    def open_soundcloud_publish_dialog(self, *args, **kwargs):
        self._record("open_soundcloud_publish_dialog", *args, **kwargs)

    def open_release_editor(self, *args, **kwargs):
        self._record("open_release_editor", *args, **kwargs)

    def open_work_manager(self, *args, **kwargs):
        self._record("open_work_manager", *args, **kwargs)

    def delete_entry(self, *args, **kwargs):
        self._record("delete_entry", *args, **kwargs)

    def _standard_media_column_key(self, key):
        return f"base:{key}"

    def _media_cell_has_payload(self, _index, *, media_key=None, field_id=None):
        if media_key is not None:
            return self.standard_payload
        if field_id is not None:
            return self.custom_payload
        return False

    def track_has_media(self, *args, **kwargs):
        self._record("track_has_media", *args, **kwargs)
        return self.track_media

    def _catalog_proxy_model(self):
        return self.proxy_model

    def import_tags_from_audio(self, *args, **kwargs):
        self._record("import_tags_from_audio", *args, **kwargs)

    def convert_selected_audio(self, *args, **kwargs):
        self._record("convert_selected_audio", *args, **kwargs)

    def export_authenticity_watermarked_audio(self, *args, **kwargs):
        self._record("export_authenticity_watermarked_audio", *args, **kwargs)

    def export_authenticity_provenance_audio(self, *args, **kwargs):
        self._record("export_authenticity_provenance_audio", *args, **kwargs)

    def export_forensic_watermarked_audio(self, *args, **kwargs):
        self._record("export_forensic_watermarked_audio", *args, **kwargs)

    def export_catalog_audio_copies(self, *args, **kwargs):
        self._record("export_catalog_audio_copies", *args, **kwargs)

    def inspect_forensic_watermark(self, *args, **kwargs):
        self._record("inspect_forensic_watermark", *args, **kwargs)

    def verify_audio_authenticity(self, *args, **kwargs):
        self._record("verify_audio_authenticity", *args, **kwargs)

    def _set_catalog_filter_text(self, *args, **kwargs):
        self._record("_set_catalog_filter_text", *args, **kwargs)

    def _copy_selection_to_clipboard(self, *args, **kwargs):
        self._record("_copy_selection_to_clipboard", *args, **kwargs)

    def _standard_media_storage_conversion_scope(self, *_args, **_kwargs):
        return {"allowed_targets": list(self.standard_targets)}

    def _custom_blob_storage_conversion_scope(self, *_args, **_kwargs):
        return {"allowed_targets": list(self.custom_targets)}

    def _storage_conversion_action_label(self, mode, *, selection_count):
        return f"Move to {mode} ({selection_count})"

    def _convert_standard_media_for_track(self, *args, **kwargs):
        self._record("_convert_standard_media_for_track", *args, **kwargs)

    def _convert_custom_blob_storage_mode(self, *args, **kwargs):
        self._record("_convert_custom_blob_storage_mode", *args, **kwargs)

    def _preview_standard_media_for_track(self, *args, **kwargs):
        self._record("_preview_standard_media_for_track", *args, **kwargs)

    def _attach_standard_media_for_track(self, *args, **kwargs):
        self._record("_attach_standard_media_for_track", *args, **kwargs)

    def _media_export_basename_for_track(self, track_id, media_key):
        return f"track-{track_id}-{media_key}"

    def _export_standard_media_for_track(self, *args, **kwargs):
        self._record("_export_standard_media_for_track", *args, **kwargs)

    def _delete_standard_media_for_track(self, *args, **kwargs):
        self._record("_delete_standard_media_for_track", *args, **kwargs)

    def _focused_media_export_spec(self, _column):
        return self.media_export_spec

    def _export_focused_media_column(self, *args, **kwargs):
        self._record("_export_focused_media_column", *args, **kwargs)

    def _preview_catalog_blob_for_cell(self, *args, **kwargs):
        self._record("_preview_catalog_blob_for_cell", *args, **kwargs)

    def _attach_blob_for_cell(self, *args, **kwargs):
        self._record("_attach_blob_for_cell", *args, **kwargs)

    def cf_export_blob(self, *args, **kwargs):
        self._record("cf_export_blob", *args, **kwargs)

    def _run_snapshot_history_action(self, *args, **kwargs):
        self._record("_run_snapshot_history_action", *args, **kwargs)
        if self.history_raises:
            raise RuntimeError("history failed")
        kwargs["mutation"]()

    def cf_delete_blob(self, *args, **kwargs):
        self._record("cf_delete_blob", *args, **kwargs)

    def refresh_table_preserve_view(self, *args, **kwargs):
        self._record("refresh_table_preserve_view", *args, **kwargs)

    def _get_track_title(self, *args, **kwargs):
        self._record("_get_track_title", *args, **kwargs)
        if self.track_title_raises:
            raise RuntimeError("title failed")
        return self.track_title

    def cf_has_blob(self, *args, **kwargs):
        self._record("cf_has_blob", *args, **kwargs)
        if self.cf_has_blob_raises:
            raise RuntimeError("blob check failed")
        return self.cf_has_blob_value

    def _audio_preview_source_spec_for_custom_field(self, *args, **kwargs):
        self._record("_audio_preview_source_spec_for_custom_field", *args, **kwargs)
        return {"field_id": args[0], "field_name": kwargs.get("field_name")}

    def _open_audio_preview_for_track(self, *args, **kwargs):
        self._record("_open_audio_preview_for_track", *args, **kwargs)

    def cf_fetch_blob(self, *args, **kwargs):
        self._record("cf_fetch_blob", *args, **kwargs)
        if self.cf_fetch_blob_raises:
            raise RuntimeError("fetch failed")
        return self.cf_fetch_blob_value

    def _open_image_preview(self, *args, **kwargs):
        self._record("_open_image_preview", *args, **kwargs)

    def _preview_blob_bytes(self, *args, **kwargs):
        self._record("_preview_blob_bytes", *args, **kwargs)


def _target(**overrides):
    values = {
        "kind": "standard",
        "track_id": 7,
        "standard_media_key": None,
        "standard_field_key": None,
        "custom_field": None,
        "custom_field_id": None,
        "custom_field_type": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _iter_actions(menu):
    for item in menu.items:
        if isinstance(item, _FakeAction):
            yield item
        elif isinstance(item, _FakeMenu):
            yield from _iter_actions(item)


def _find_action(menu, text_prefix):
    for action in _iter_actions(menu):
        if action.text().startswith(text_prefix):
            return action
    raise AssertionError(f"Action starting with {text_prefix!r} was not created")


def _action_texts(menu):
    return [action.text() for action in _iter_actions(menu)]


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


class CatalogTableContextMenuTests(unittest.TestCase):
    @contextmanager
    def _patched_context_menu_widgets(self):
        _FakeMenu.reset()
        _FakeMessageBox.reset()
        root_module = SimpleNamespace(QMenu=_FakeMenu, QMessageBox=_FakeMessageBox)
        with (
            patch.object(context_menu, "QAction", _FakeAction),
            patch.dict(sys.modules, {"isrc_manager.main_window": root_module}),
        ):
            yield

    def test_context_menu_ignores_invalid_selection(self):
        app = _FakeContextMenuApp(_target(), _FakeIndex(valid=False))

        with self._patched_context_menu_widgets():
            context_menu._on_catalog_table_context_menu(app, (1, 2))

        self.assertEqual(_FakeMenu.instances, [])

    def test_standard_media_context_menu_actions_execute_callbacks(self):
        target = _target(kind="standard", standard_media_key="audio_file")
        index = _FakeIndex(text="needle")
        app = _FakeContextMenuApp(
            target,
            index,
            selected_ids=(7, 8),
            effective_ids=(7, 8),
            ordered_ids=(8, 7),
            columns={"base:audio_file": 1},
            standard_payload=True,
            standard_targets=("database", "external"),
            media_export_spec={"column_label": "Audio File"},
            release_id=44,
            linked_works=(SimpleNamespace(id=9),),
        )

        with self._patched_context_menu_widgets():
            context_menu._on_catalog_table_context_menu(app, (4, 5))

        menu = _FakeMenu.instances[0]
        self.assertEqual(menu.executed_at, ("global", (4, 5)))
        texts = _action_texts(menu)
        self.assertTrue(any(text.startswith("Bulk Edit 2") for text in texts))
        self.assertIn("Delete Track", texts)
        self.assertIn("Move to database (2)", texts)
        self.assertIn("Move to external (2)", texts)

        _find_action(menu, "Bulk Edit 2").trigger()
        _find_action(menu, "Album Track Ordering").trigger()
        _find_action(menu, "GS1 Metadata").trigger()
        _find_action(menu, "Publish to SoundCloud").trigger()
        _find_action(menu, "Open Primary Release").trigger()
        _find_action(menu, "Open Linked Work").trigger()
        _find_action(menu, "Link Selected Track").trigger()
        _find_action(menu, "Delete Track").trigger()
        _find_action(menu, "Import Metadata").trigger()
        _find_action(menu, "Export Audio Derivatives").trigger()
        _find_action(menu, "Export Authentic Masters").trigger()
        _find_action(menu, "Export Provenance Copies").trigger()
        _find_action(menu, "Export Forensic Watermarked Audio").trigger()
        _find_action(menu, "Export Catalog Audio Copies").trigger()
        _find_action(menu, "Inspect Forensic Watermark").trigger()
        _find_action(menu, "Verify Audio Authenticity").trigger()
        _find_action(menu, "Set Filter").trigger()
        _find_action(menu, "Copy").trigger()
        _find_action(menu, "Copy with Headers").trigger()
        _find_action(menu, "Preview File").trigger()
        _find_action(menu, "Attach/Replace File").trigger()
        _find_action(menu, "Export 'track-7-audio_file'").trigger()
        _find_action(menu, "Delete File").trigger()
        _find_action(menu, "Move to database").trigger()
        _find_action(menu, "Export 2 Files").trigger()

        self.assertIn(("open_selected_editor", (7,), {}), app.calls)
        self.assertIn(("open_soundcloud_publish_dialog", (), {"track_ids": [8, 7]}), app.calls)
        self.assertIn(("open_release_editor", (44,), {}), app.calls)
        self.assertIn(("open_work_manager", (), {"linked_track_id": 7}), app.calls)
        self.assertIn(("open_work_manager", (), {}), app.calls)
        self.assertIn(("convert_selected_audio", ([8, 7],), {}), app.calls)
        self.assertIn(
            ("_convert_standard_media_for_track", ([8, 7], "audio_file", "database"), {}),
            app.calls,
        )
        self.assertIn(
            ("_export_focused_media_column", (0,), {"track_ids": [8, 7]}),
            app.calls,
        )

    def test_standard_media_context_menu_uses_database_fallback_payload_check(self):
        target = _target(kind="standard", standard_media_key="album_art")
        app = _FakeContextMenuApp(
            target,
            _FakeIndex(text="cover"),
            columns={"base:album_art": 2},
            standard_payload=False,
            track_media=True,
            proxy_model=None,
        )

        with self._patched_context_menu_widgets():
            context_menu._on_catalog_table_context_menu(app, (0, 0))

        menu = _FakeMenu.instances[0]
        _find_action(menu, "Preview File").trigger()

        self.assertIn(("track_has_media", (7, "album_art"), {}), app.calls)
        self.assertIn(("_preview_standard_media_for_track", (7, "album_art"), {}), app.calls)

    def test_custom_blob_context_menu_actions_confirm_and_report_failures(self):
        target = _target(
            kind="custom",
            custom_field={"id": 9, "name": "Cover"},
            custom_field_id=9,
            custom_field_type="blob_image",
        )
        app = _FakeContextMenuApp(
            target,
            _FakeIndex(row=2, column=5, text="image"),
            selected_ids=(7,),
            effective_ids=(7,),
            columns={},
            custom_payload=True,
            custom_targets=("external",),
            track_title="",
        )

        with self._patched_context_menu_widgets():
            context_menu._on_catalog_table_context_menu(app, (3, 4))

            menu = _FakeMenu.instances[0]
            _find_action(menu, "Preview File").trigger()
            _find_action(menu, "Attach/Replace File").trigger()
            _find_action(menu, "Export 'track_7'").trigger()
            _find_action(menu, "Move to external").trigger()

            delete_action = _find_action(menu, "Delete File")
            _FakeMessageBox.answer = _FakeMessageBox.No
            delete_action.trigger()
            self.assertNotIn(("cf_delete_blob", (7, 9), {}), app.calls)

            _FakeMessageBox.answer = _FakeMessageBox.Yes
            delete_action.trigger()
            app.history_raises = True
            delete_action.trigger()

        self.assertIn(("_preview_catalog_blob_for_cell", (2, 5), {}), app.calls)
        self.assertIn(("_attach_blob_for_cell", (7, 9, "blob_image", "Cover"), {}), app.calls)
        self.assertIn(("cf_export_blob", (7, 9, app, "track_7"), {}), app.calls)
        self.assertIn(("_convert_custom_blob_storage_mode", ([7], 9, "external"), {}), app.calls)
        self.assertIn(("cf_delete_blob", (7, 9), {}), app.calls)
        self.assertIn(("refresh_table_preserve_view", (), {"focus_id": 7}), app.calls)
        self.assertEqual(app.conn.rollbacks, 1)
        self.assertTrue(app.logger.exceptions)
        self.assertTrue(_FakeMessageBox.criticals)

    def test_preview_catalog_blob_handles_standard_and_guard_paths(self):
        app = _FakeContextMenuApp(
            _target(kind="standard", track_id=None, standard_media_key="audio_file")
        )
        context_menu._preview_catalog_blob_for_cell(app, 0, 1)
        self.assertFalse(app.calls)

        app = _FakeContextMenuApp(
            _target(kind="standard", track_id=11, standard_media_key="audio_file")
        )
        context_menu._preview_catalog_blob_for_cell(app, 0, 1)
        self.assertIn(("_preview_standard_media_for_track", (11, "audio_file"), {}), app.calls)

        app = _FakeContextMenuApp(_target(kind="custom", custom_field=None))
        context_menu._preview_catalog_blob_for_cell(app, 0, 1)
        self.assertFalse(app.calls)

        app = _FakeContextMenuApp(
            _target(
                kind="custom",
                custom_field={"name": "Cover"},
                custom_field_id=9,
                custom_field_type="blob_image",
            ),
            cf_has_blob=False,
        )
        context_menu._preview_catalog_blob_for_cell(app, 0, 1)
        self.assertEqual(app.calls, [("cf_has_blob", (7, 9), {})])

    def test_preview_catalog_blob_routes_audio_image_empty_and_generic_data(self):
        audio_target = _target(
            kind="custom",
            custom_field={"field_name": "Fallback Audio"},
            custom_field_id=9,
            custom_field_type="blob_audio",
        )
        audio_app = _FakeContextMenuApp(
            audio_target,
            custom_field_name_raises=True,
            track_title="",
        )

        with self._patched_context_menu_widgets():
            context_menu._preview_catalog_blob_for_cell(audio_app, 0, 1)

        self.assertIn(
            (
                "_audio_preview_source_spec_for_custom_field",
                (9,),
                {"field_name": "Fallback Audio"},
            ),
            audio_app.calls,
        )
        self.assertTrue(any(call[0] == "_open_audio_preview_for_track" for call in audio_app.calls))

        image_target = _target(
            kind="custom",
            custom_field={"name": "Cover"},
            custom_field_id=10,
            custom_field_type="blob_image",
        )
        image_app = _FakeContextMenuApp(
            image_target,
            track_title="Song",
            custom_field_name="Cover",
            cf_fetch_blob=(b"image-bytes", "metadata"),
        )
        context_menu._preview_catalog_blob_for_cell(image_app, 0, 1)
        self.assertIn(
            ("_open_image_preview", (b"image-bytes", "Song \u2014 Cover"), {}),
            image_app.calls,
        )

        empty_app = _FakeContextMenuApp(
            image_target,
            custom_field_name="Cover",
            cf_fetch_blob=None,
        )
        with self._patched_context_menu_widgets():
            context_menu._preview_catalog_blob_for_cell(empty_app, 0, 1)
        self.assertTrue(_FakeMessageBox.informations)

        generic_target = _target(
            kind="custom",
            custom_field={"name": "Document"},
            custom_field_id=11,
            custom_field_type="blob_document",
        )
        generic_app = _FakeContextMenuApp(generic_target, track_title="Document Track")
        context_menu._preview_catalog_blob_for_cell(generic_app, 0, 1)
        self.assertIn(
            ("_preview_blob_bytes", (b"blob", "Document Track"), {}),
            generic_app.calls,
        )

    def test_preview_catalog_blob_rolls_back_and_reports_exceptions(self):
        target = _target(
            kind="custom",
            custom_field={"name": "Cover"},
            custom_field_id=9,
            custom_field_type="blob_image",
        )
        app = _FakeContextMenuApp(target)
        app.cf_has_blob_raises = True

        with self._patched_context_menu_widgets():
            context_menu._preview_catalog_blob_for_cell(app, 0, 1)

        self.assertEqual(app.conn.rollbacks, 1)
        self.assertTrue(app.logger.exceptions)
        self.assertTrue(_FakeMessageBox.criticals)

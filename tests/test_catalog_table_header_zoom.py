import json
import tempfile
import time
import unittest
from pathlib import Path

from tests.qt_test_helpers import pump_events, require_qapplication, wait_for

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QHeaderView, QTableView
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QSettings = None
    QHeaderView = None
    QTableView = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.catalog_table.header_state import (
    COLUMNS_MOVABLE_KEY,
    HEADER_COLUMN_KEYS_JSON_KEY,
    HEADER_LABELS_KEY,
    HIDDEN_COLUMN_KEYS_JSON_KEY,
    HIDDEN_COLUMNS_JSON_KEY,
    CatalogHeaderStateManager,
)
from isrc_manager.catalog_table.models import (
    CatalogCellValue,
    CatalogColumnSpec,
    CatalogRowSnapshot,
    CatalogSnapshot,
)
from isrc_manager.catalog_table.table_model import CatalogTableModel
from isrc_manager.catalog_table.zoom import (
    CATALOG_ZOOM_LAYOUT_KEY,
    CatalogZoomController,
)


def _build_snapshot(column_specs) -> CatalogSnapshot:
    return CatalogSnapshot(
        column_specs=tuple(column_specs),
        rows=(
            CatalogRowSnapshot(
                track_id=1,
                cells_by_key={
                    spec.key: CatalogCellValue(display_text=f"{spec.header_text} value")
                    for spec in column_specs
                },
            ),
        ),
    )


class CatalogHeaderStateManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def setUp(self):
        if QSettings is None or QTableView is None or QHeaderView is None:
            raise unittest.SkipTest(f"PySide6 Qt unavailable: {QT_IMPORT_ERROR}")
        self._tempdir = tempfile.TemporaryDirectory()
        self._settings_path = Path(self._tempdir.name) / "header_state.ini"
        self.settings = QSettings(str(self._settings_path), QSettings.IniFormat)
        self.settings.clear()
        self.settings.sync()
        self.manager = CatalogHeaderStateManager(
            self.settings,
            settings_prefix="table/test-profile",
        )
        self._views: list[QTableView] = []

    def tearDown(self):
        for view in self._views:
            view.close()
            view.deleteLater()
        pump_events(app=self.app, cycles=2)
        self.settings.sync()
        self._tempdir.cleanup()

    def _make_view(self, column_specs) -> tuple[QTableView, CatalogTableModel]:
        view = QTableView()
        model = CatalogTableModel(snapshot=_build_snapshot(column_specs))
        view.setModel(model)
        header = view.horizontalHeader()
        header.setSectionsMovable(True)
        for column in range(model.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            header.resizeSection(column, 110 + (column * 15))
        view.show()
        self._views.append(view)
        pump_events(app=self.app, cycles=2)
        return view, model

    @staticmethod
    def _visual_key_order(view: QTableView, column_specs) -> list[str]:
        header = view.horizontalHeader()
        return [
            column_specs[logical_index].key
            for logical_index in sorted(
                range(len(column_specs)),
                key=lambda index: header.visualIndex(index),
            )
        ]

    def test_save_state_writes_legacy_and_key_based_payloads(self):
        column_specs = (
            CatalogColumnSpec(key="id", header_text="ID"),
            CatalogColumnSpec(key="title", header_text="Title"),
            CatalogColumnSpec(key="length", header_text="Length"),
        )
        view, _ = self._make_view(column_specs)
        header = view.horizontalHeader()
        header.moveSection(header.visualIndex(2), 0)
        header.setSectionHidden(1, True)
        header.resizeSection(0, 240)
        pump_events(app=self.app, cycles=2)

        self.manager.save_state(header, column_specs=column_specs)

        self.assertEqual(
            self.settings.value(self.manager.settings_key(HEADER_LABELS_KEY), [], list),
            ["Length", "ID", "Title"],
        )
        self.assertEqual(
            json.loads(self.settings.value(self.manager.settings_key(HEADER_COLUMN_KEYS_JSON_KEY))),
            ["length", "id", "title"],
        )
        self.assertEqual(
            json.loads(self.settings.value(self.manager.settings_key(HIDDEN_COLUMN_KEYS_JSON_KEY))),
            ["title"],
        )
        self.assertEqual(
            json.loads(self.settings.value(self.manager.settings_key(HIDDEN_COLUMNS_JSON_KEY))),
            [{"key": "title", "label": "Title", "occurrence": 0}],
        )
        self.assertTrue(
            self.settings.value(self.manager.settings_key(COLUMNS_MOVABLE_KEY), False, bool)
        )

    def test_restore_state_prefers_key_based_payloads_when_labels_change(self):
        original_specs = (
            CatalogColumnSpec(key="id", header_text="ID"),
            CatalogColumnSpec(key="title", header_text="Title"),
            CatalogColumnSpec(key="length", header_text="Length"),
        )
        original_view, _ = self._make_view(original_specs)
        original_header = original_view.horizontalHeader()
        original_header.moveSection(original_header.visualIndex(2), 0)
        original_header.setSectionHidden(1, True)
        pump_events(app=self.app, cycles=2)
        self.manager.save_state(original_header, column_specs=original_specs)

        changed_specs = (
            CatalogColumnSpec(key="id", header_text="Track ID"),
            CatalogColumnSpec(key="title", header_text="Track Title"),
            CatalogColumnSpec(key="length", header_text="Duration"),
        )
        restored_view, _ = self._make_view(changed_specs)
        restored_header = restored_view.horizontalHeader()
        restored_header.setSectionsMovable(False)

        restored = self.manager.restore_state(restored_header, column_specs=changed_specs)

        self.assertTrue(restored)
        self.assertEqual(
            self._visual_key_order(restored_view, changed_specs),
            ["length", "id", "title"],
        )
        self.assertTrue(restored_header.isSectionHidden(1))
        self.assertTrue(restored_header.sectionsMovable())

    def test_restore_state_falls_back_to_legacy_label_occurrence_tokens(self):
        column_specs = (
            CatalogColumnSpec(key="id", header_text="ID"),
            CatalogColumnSpec(key="title", header_text="Title"),
            CatalogColumnSpec(key="custom_a", header_text="Custom"),
            CatalogColumnSpec(key="custom_b", header_text="Custom"),
        )
        view, _ = self._make_view(column_specs)
        header = view.horizontalHeader()
        self.settings.setValue(
            self.manager.settings_key(HEADER_LABELS_KEY),
            ["Custom", "ID", "Custom", "Title"],
        )
        self.settings.setValue(
            self.manager.settings_key(HIDDEN_COLUMNS_JSON_KEY),
            json.dumps([{"label": "Custom", "occurrence": 1}]),
        )
        self.settings.setValue(self.manager.settings_key(COLUMNS_MOVABLE_KEY), False)
        self.settings.sync()

        restored = self.manager.restore_state(header, column_specs=column_specs)

        self.assertTrue(restored)
        self.assertEqual(
            self._visual_key_order(view, column_specs),
            ["custom_a", "id", "custom_b", "title"],
        )
        self.assertFalse(header.isSectionHidden(2))
        self.assertTrue(header.isSectionHidden(3))
        self.assertFalse(header.sectionsMovable())


class CatalogZoomControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def test_zoom_state_machine_clamps_steps_and_restores_layout_payloads(self):
        controller = CatalogZoomController(throttle_ms=0)
        applied: list[int] = []
        changed: list[int] = []
        controller.set_apply_callback(lambda view, percent: applied.append(percent))
        controller.zoom_percent_changed.connect(changed.append)

        self.assertEqual(controller.set_zoom_percent(79, immediate=True), 80)
        self.assertEqual(controller.step_zoom(3, immediate=True), 95)
        self.assertEqual(controller.apply_pinch_scale(1.21, immediate=True), 115)
        self.assertEqual(controller.layout_state(), {CATALOG_ZOOM_LAYOUT_KEY: 115})
        self.assertEqual(
            controller.restore_layout_state(
                {CATALOG_ZOOM_LAYOUT_KEY: 157},
                immediate=True,
            ),
            155,
        )
        self.assertEqual(controller.on_profile_changed(immediate=True), 100)

        self.assertEqual(applied, [80, 95, 115, 155, 100])
        self.assertEqual(changed, [80, 95, 115, 155, 100])

    def test_zoom_throttle_coalesces_multiple_updates_to_one_apply(self):
        controller = CatalogZoomController(throttle_ms=40)
        applied: list[int] = []
        controller.set_apply_callback(lambda view, percent: applied.append(percent))

        controller.set_zoom_percent(110)
        controller.set_zoom_percent(125)
        controller.set_zoom_percent(130)

        self.assertEqual(controller.zoom_percent(), 130)
        self.assertTrue(controller.has_pending_apply())
        self.assertEqual(applied, [])

        wait_for(
            lambda: applied == [130],
            app=self.app,
            timeout_ms=500,
            description="coalesced zoom apply",
        )
        self.assertFalse(controller.has_pending_apply())

    def test_flush_pending_apply_emits_once_and_cancels_late_timer_delivery(self):
        controller = CatalogZoomController(throttle_ms=120)
        applied: list[int] = []
        controller.set_apply_callback(lambda view, percent: applied.append(percent))

        controller.set_zoom_percent(140)
        self.assertTrue(controller.has_pending_apply())

        self.assertEqual(controller.flush_pending_apply(), 140)
        self.assertEqual(applied, [140])
        self.assertFalse(controller.has_pending_apply())

        time.sleep(0.16)
        pump_events(app=self.app, cycles=4)
        self.assertEqual(applied, [140])


if __name__ == "__main__":
    unittest.main()

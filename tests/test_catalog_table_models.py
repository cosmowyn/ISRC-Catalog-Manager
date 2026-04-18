import unittest

from tests.qt_test_helpers import pump_events, require_qapplication

try:
    from PySide6.QtCore import Qt
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    Qt = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.catalog_table.filter_proxy import CatalogFilterProxyModel
from isrc_manager.catalog_table.models import (
    CatalogCellValue,
    CatalogColumnSpec,
    CatalogRowSnapshot,
    CatalogSnapshot,
    ColumnKeyRole,
    RawValueRole,
    SearchTextRole,
    SortRole,
    TrackIdRole,
)
from isrc_manager.catalog_table.table_model import CatalogTableModel


class _ExplosiveValue:
    def __str__(self) -> str:  # pragma: no cover - exercised only on failure
        raise AssertionError("CatalogTableModel.data() should not stringify raw payloads.")


def _build_snapshot() -> CatalogSnapshot:
    return CatalogSnapshot(
        column_specs=(
            CatalogColumnSpec(
                key="title",
                header_text="Title",
                notes="Primary catalog title column.",
            ),
            CatalogColumnSpec(
                key="length",
                header_text="Track Length (hh:mm:ss)",
            ),
            CatalogColumnSpec(
                key="private_note",
                header_text="Private Note",
                searchable=False,
            ),
        ),
        rows=(
            CatalogRowSnapshot(
                track_id=101,
                cells_by_key={
                    "title": CatalogCellValue(
                        display_text="Track 2",
                        search_text="Track 2 second",
                    ),
                    "length": CatalogCellValue(
                        display_text="00:03:15",
                        sort_value=195,
                        raw_value=195,
                    ),
                    "private_note": CatalogCellValue(display_text="Hidden alpha"),
                },
            ),
            CatalogRowSnapshot(
                track_id=102,
                cells_by_key={
                    "title": CatalogCellValue(
                        display_text="Track 10",
                        search_text="Track 10 tenth",
                    ),
                    "length": CatalogCellValue(
                        display_text="00:01:00",
                        sort_value=60,
                        raw_value=60,
                    ),
                    "private_note": CatalogCellValue(display_text="Hidden beta"),
                },
            ),
            CatalogRowSnapshot(
                track_id=103,
                cells_by_key={
                    "title": CatalogCellValue(
                        display_text="Track 1",
                        search_text="Track 1 first",
                    ),
                    "length": CatalogCellValue(
                        display_text="00:10:00",
                        sort_value=600,
                        raw_value=600,
                    ),
                    "private_note": CatalogCellValue(display_text="Special match"),
                },
            ),
        ),
    )


class CatalogTableModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def setUp(self):
        if Qt is None:
            raise unittest.SkipTest(f"PySide6 Qt unavailable: {QT_IMPORT_ERROR}")
        self.model = CatalogTableModel(snapshot=_build_snapshot())

    def test_snapshot_rejects_duplicate_column_keys_and_track_ids(self):
        with self.assertRaises(ValueError):
            CatalogSnapshot(
                column_specs=(
                    CatalogColumnSpec(key="title", header_text="Title"),
                    CatalogColumnSpec(key="title", header_text="Duplicate"),
                )
            )

        with self.assertRaises(ValueError):
            CatalogSnapshot(
                column_specs=(CatalogColumnSpec(key="title", header_text="Title"),),
                rows=(
                    CatalogRowSnapshot(track_id=1, cells_by_key={"title": "One"}),
                    CatalogRowSnapshot(track_id=1, cells_by_key={"title": "Two"}),
                ),
            )

    def test_model_exposes_catalog_roles_and_header_metadata(self):
        index = self.model.index(0, 0)

        self.assertEqual(self.model.data(index, int(Qt.ItemDataRole.DisplayRole)), "Track 2")
        self.assertEqual(self.model.data(index, SearchTextRole), "Track 2 second")
        self.assertEqual(self.model.data(index, TrackIdRole), 101)
        self.assertEqual(self.model.data(index, ColumnKeyRole), "title")
        self.assertEqual(self.model.headerData(0, Qt.Orientation.Horizontal), "Title")
        self.assertEqual(
            self.model.headerData(0, Qt.Orientation.Horizontal, int(Qt.ItemDataRole.ToolTipRole)),
            "Primary catalog title column.",
        )
        self.assertEqual(
            self.model.headerData(0, Qt.Orientation.Horizontal, ColumnKeyRole),
            "title",
        )
        self.assertEqual(self.model.track_id_for_source_row(2), 103)
        self.assertEqual(self.model.source_row_for_track_id(102), 1)

    def test_model_data_returns_precomputed_payloads_without_side_effects(self):
        explosive = _ExplosiveValue()
        snapshot = CatalogSnapshot(
            column_specs=(CatalogColumnSpec(key="title", header_text="Title"),),
            rows=(
                CatalogRowSnapshot(
                    track_id=501,
                    cells_by_key={
                        "title": CatalogCellValue(
                            display_text="Safe display",
                            search_text="safe search",
                            raw_value=explosive,
                            sort_value=explosive,
                            tooltip="Safe tooltip",
                            text_alignment=int(
                                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                            ),
                        )
                    },
                ),
            ),
        )
        model = CatalogTableModel(snapshot=snapshot)
        index = model.index(0, 0)

        self.assertEqual(model.data(index, int(Qt.ItemDataRole.DisplayRole)), "Safe display")
        self.assertEqual(model.data(index, SearchTextRole), "safe search")
        self.assertEqual(model.data(index, int(Qt.ItemDataRole.ToolTipRole)), "Safe tooltip")
        self.assertIs(model.data(index, RawValueRole), explosive)
        self.assertIs(model.data(index, SortRole), explosive)
        self.assertEqual(
            model.data(index, int(Qt.ItemDataRole.TextAlignmentRole)),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        )

    def test_set_snapshot_resets_model_row_and_column_mappings(self):
        replacement = CatalogSnapshot(
            column_specs=(
                CatalogColumnSpec(key="title", header_text="Title"),
                CatalogColumnSpec(key="status", header_text="Status"),
            ),
            rows=(CatalogRowSnapshot(track_id=999, cells_by_key={"title": "Only row"}),),
        )

        self.model.set_snapshot(replacement)

        self.assertEqual(self.model.rowCount(), 1)
        self.assertEqual(self.model.columnCount(), 2)
        self.assertEqual(self.model.track_id_for_source_row(0), 999)
        self.assertEqual(self.model.source_row_for_track_id(999), 0)


class CatalogFilterProxyModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def setUp(self):
        if Qt is None:
            raise unittest.SkipTest(f"PySide6 Qt unavailable: {QT_IMPORT_ERROR}")
        self.model = CatalogTableModel(snapshot=_build_snapshot())
        self.proxy = CatalogFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        pump_events(app=self.app)

    def _proxy_track_ids(self) -> list[int]:
        return [
            int(self.proxy.index(row, 0).data(TrackIdRole)) for row in range(self.proxy.rowCount())
        ]

    def test_proxy_sorts_using_precomputed_sort_values_and_natural_text(self):
        self.proxy.sort(0, Qt.SortOrder.AscendingOrder)
        pump_events(app=self.app)
        self.assertEqual(self._proxy_track_ids(), [103, 101, 102])

        self.proxy.sort(1, Qt.SortOrder.AscendingOrder)
        pump_events(app=self.app)
        self.assertEqual(self._proxy_track_ids(), [102, 101, 103])

    def test_proxy_searches_all_searchable_columns_and_can_target_specific_column_keys(self):
        self.proxy.set_search_text("special match")
        pump_events(app=self.app)
        self.assertEqual(self._proxy_track_ids(), [])

        self.proxy.set_search_column_key("private_note")
        pump_events(app=self.app)
        self.assertEqual(self._proxy_track_ids(), [103])

        self.proxy.set_search_text("track 10")
        self.proxy.set_search_column_key(None)
        pump_events(app=self.app)
        self.assertEqual(self._proxy_track_ids(), [102])

    def test_proxy_applies_explicit_track_filters_in_combination_with_search(self):
        self.proxy.set_search_text("track")
        self.proxy.set_explicit_track_ids([101, 103])
        pump_events(app=self.app)
        self.assertEqual(self.proxy.explicit_track_ids(), frozenset({101, 103}))
        self.assertEqual(self._proxy_track_ids(), [101, 103])

        self.proxy.set_explicit_track_ids([])
        pump_events(app=self.app)
        self.assertEqual(self._proxy_track_ids(), [])

        self.proxy.set_explicit_track_ids(None)
        pump_events(app=self.app)
        self.assertEqual(self._proxy_track_ids(), [101, 102, 103])


if __name__ == "__main__":
    unittest.main()

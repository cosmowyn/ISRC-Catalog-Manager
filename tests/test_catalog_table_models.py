import unittest

from tests.qt_test_helpers import pump_events, require_qapplication

try:
    from PySide6.QtCore import QModelIndex, Qt
    from PySide6.QtGui import QStandardItemModel
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QModelIndex = None
    QStandardItemModel = None
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
    comparison_sort_key,
    natural_sort_key,
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

    def test_sort_key_and_snapshot_value_objects_cover_validation_edges(self):
        class NamedObject:
            def __str__(self):
                return "Object 12"

        self.assertEqual(comparison_sort_key(None), (4, ()))
        self.assertEqual(comparison_sort_key(True), (0, 1))
        self.assertEqual(comparison_sort_key(12.5), (0, 12.5))
        self.assertEqual(comparison_sort_key("Track 10"), (1, natural_sort_key("Track 10")))
        self.assertEqual(
            comparison_sort_key(("A2", None)),
            (2, (comparison_sort_key("A2"), comparison_sort_key(None))),
        )
        self.assertEqual(
            comparison_sort_key(["B1", False]),
            (2, (comparison_sort_key("B1"), comparison_sort_key(False))),
        )
        self.assertEqual(comparison_sort_key(NamedObject()), (3, natural_sort_key("Object 12")))

        with self.assertRaisesRegex(ValueError, "column keys"):
            CatalogColumnSpec(key="  ", header_text="Title")
        with self.assertRaisesRegex(ValueError, "column headers"):
            CatalogColumnSpec(key="title", header_text="")

        spec = CatalogColumnSpec(
            key=" title ",
            header_text=" Title ",
            legacy_header_labels=(" Old Title ", "", "Alt"),
            notes=" Primary title ",
        )
        self.assertEqual(spec.key, "title")
        self.assertEqual(spec.header_text, "Title")
        self.assertEqual(spec.all_header_labels, ("Title", "Old Title", "Alt"))
        self.assertEqual(spec.notes, "Primary title")

        with self.assertRaisesRegex(ValueError, "row cells"):
            CatalogRowSnapshot(track_id="5", cells_by_key={" ": "bad"})

        row = CatalogRowSnapshot(track_id="5", cells_by_key={" title ": "Orbit"})
        self.assertEqual(row.track_id, 5)
        self.assertEqual(row.cell("title").display_text, "Orbit")

        snapshot = CatalogSnapshot(
            column_specs=(spec,),
            rows=(row,),
            metadata={"source": "unit-test"},
        )
        self.assertEqual(CatalogSnapshot.empty().column_keys, ())
        self.assertEqual(snapshot.column_keys, ("title",))
        self.assertEqual(snapshot.column_index("title"), 0)
        self.assertIsNone(snapshot.column_index("missing"))
        self.assertIs(snapshot.column_spec("title"), spec)
        self.assertIsNone(snapshot.column_spec("missing"))
        self.assertEqual(snapshot.metadata, {"source": "unit-test"})

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

    def test_model_guard_paths_for_invalid_indexes_headers_and_empty_snapshots(self):
        parent_index = self.model.index(0, 0)
        self.assertEqual(self.model.rowCount(parent_index), 0)
        self.assertEqual(self.model.columnCount(parent_index), 0)
        self.assertIsNone(self.model.data(QModelIndex()))
        self.assertIsNone(self.model.data(self.model.createIndex(99, 0)))
        self.assertIsNone(self.model.data(self.model.createIndex(0, 99)))

        self.assertIsNone(self.model.headerData(0, Qt.Orientation.Vertical))
        self.assertIsNone(self.model.headerData(99, Qt.Orientation.Horizontal))
        self.assertIsNone(
            self.model.headerData(
                0,
                Qt.Orientation.Horizontal,
                int(Qt.ItemDataRole.DecorationRole),
            )
        )
        self.assertIsNone(self.model.column_spec(-1))
        self.assertIsNone(self.model.track_id_for_source_row(-1))
        self.assertIsNone(self.model.track_id_for_source_row(99))
        self.assertIn(SortRole, self.model.roleNames())
        self.assertEqual(self.model.roleNames()[RawValueRole], b"rawValue")

        self.model.set_snapshot(None)

        self.assertEqual(self.model.rowCount(), 0)
        self.assertEqual(self.model.columnCount(), 0)
        self.assertIsNone(self.model.source_row_for_track_id(101))


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

    def test_proxy_edge_guards_legacy_invalidation_and_source_model_absence(self):
        if QModelIndex is None or QStandardItemModel is None:
            raise unittest.SkipTest(f"PySide6 Qt unavailable: {QT_IMPORT_ERROR}")

        class LegacyInvalidationProxy(CatalogFilterProxyModel):
            beginFilterChange = None
            endFilterChange = None

            def __init__(self):
                super().__init__()
                self.invalidated = 0

            def invalidateFilter(self):
                self.invalidated += 1
                super().invalidateFilter()

        legacy_proxy = LegacyInvalidationProxy()
        legacy_proxy.set_search_text(" legacy ")
        self.assertEqual(legacy_proxy.search_text(), "legacy")
        self.assertEqual(legacy_proxy.invalidated, 1)
        legacy_proxy.set_search_text("legacy")
        self.assertEqual(legacy_proxy.invalidated, 1)
        legacy_proxy.set_search_column_key("title")
        self.assertEqual(legacy_proxy.search_column_key(), "title")
        legacy_proxy.set_search_column_key(" title ")
        self.assertEqual(legacy_proxy.invalidated, 2)

        self.proxy.set_explicit_track_ids(["bad", object(), -1, 101])
        self.assertEqual(self.proxy.explicit_track_ids(), frozenset({101}))
        self.proxy.set_explicit_track_ids([101])

        no_source_proxy = CatalogFilterProxyModel()
        self.assertFalse(no_source_proxy.filterAcceptsRow(0, QModelIndex()))
        self.assertFalse(no_source_proxy.lessThan(QModelIndex(), QModelIndex()))
        self.assertIsNone(no_source_proxy._track_id_for_source_row(0, source_parent=QModelIndex()))
        self.assertEqual(no_source_proxy._searchable_source_columns(), ())
        self.assertIsNone(no_source_proxy._source_column_for_key("title"))

        standard_model = QStandardItemModel(1, 2)
        no_spec_proxy = CatalogFilterProxyModel()
        no_spec_proxy.setSourceModel(standard_model)
        self.assertEqual(no_spec_proxy._searchable_source_columns(), (0, 1))
        self.assertIsNone(no_spec_proxy._source_column_for_key(""))
        self.assertIsNone(no_spec_proxy._source_column_for_key("missing"))

    def test_proxy_less_than_uses_track_id_and_row_tie_breakers(self):
        equal_display_snapshot = CatalogSnapshot(
            column_specs=(CatalogColumnSpec(key="title", header_text="Title"),),
            rows=(
                CatalogRowSnapshot(
                    track_id=20,
                    cells_by_key={
                        "title": CatalogCellValue(
                            display_text="Same",
                            search_text="Same",
                            sort_value="Same",
                        )
                    },
                ),
                CatalogRowSnapshot(
                    track_id=10,
                    cells_by_key={
                        "title": CatalogCellValue(
                            display_text="Same",
                            search_text="Same",
                            sort_value="Same",
                        )
                    },
                ),
            ),
        )
        model = CatalogTableModel(snapshot=equal_display_snapshot)
        proxy = CatalogFilterProxyModel()
        proxy.setSourceModel(model)

        self.assertFalse(proxy.lessThan(model.index(0, 0), model.index(1, 0)))
        self.assertTrue(proxy.lessThan(model.index(1, 0), model.index(0, 0)))

        class EqualTrackIdModel(CatalogTableModel):
            def data(self, index, role=int(Qt.ItemDataRole.DisplayRole)):
                if role == TrackIdRole:
                    return 5
                return super().data(index, role)

        equal_track_snapshot = CatalogSnapshot(
            column_specs=(CatalogColumnSpec(key="title", header_text="Title"),),
            rows=(
                CatalogRowSnapshot(
                    track_id=5,
                    cells_by_key={"title": CatalogCellValue(display_text="Same")},
                ),
                CatalogRowSnapshot(
                    track_id=6,
                    cells_by_key={"title": CatalogCellValue(display_text="Same")},
                ),
            ),
        )
        equal_track_model = EqualTrackIdModel(snapshot=equal_track_snapshot)
        equal_track_proxy = CatalogFilterProxyModel()
        equal_track_proxy.setSourceModel(equal_track_model)

        self.assertTrue(
            equal_track_proxy.lessThan(
                equal_track_model.index(0, 0),
                equal_track_model.index(1, 0),
            )
        )
        self.assertFalse(
            equal_track_proxy.lessThan(
                equal_track_model.index(1, 0),
                equal_track_model.index(0, 0),
            )
        )


if __name__ == "__main__":
    unittest.main()

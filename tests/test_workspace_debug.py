import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtCore import QRect, QSize, Qt
    from PySide6.QtWidgets import (
        QComboBox,
        QDockWidget,
        QFormLayout,
        QLabel,
        QMainWindow,
        QScrollArea,
        QWidget,
    )
except ImportError:  # pragma: no cover - environment-specific fallback
    QRect = None
    QSize = None
    Qt = None
    QComboBox = None
    QDockWidget = None
    QFormLayout = None
    QLabel = None
    QMainWindow = None
    QScrollArea = None
    QWidget = None

from isrc_manager.workspace_debug import (
    _combo_summary,
    _enum_payload,
    _json_safe,
    _label_summary,
    _rect_payload,
    _scroll_area_summary,
    _size_payload,
    _widget_descriptor,
    summarize_catalog_workspace_dock,
    summarize_contract_template_panel,
    summarize_panel_layout_snapshot,
    summarize_qdockwidget,
    summarize_workspace_host,
    workspace_debug_enabled,
    workspace_debug_log,
)


class WorkspaceDebugTests(unittest.TestCase):
    def test_layout_flag_enables_debug_topic(self):
        with mock.patch.dict(os.environ, {"ISRC_CT_LAYOUT_DEBUG": "1"}, clear=False):
            self.assertTrue(workspace_debug_enabled("layout"))
            self.assertFalse(workspace_debug_enabled("preview"))

    def test_workspace_debug_topic_list_enables_only_requested_topics(self):
        with mock.patch.dict(
            os.environ,
            {"ISRC_CT_WORKSPACE_DEBUG": "layout, preview"},
            clear=False,
        ):
            self.assertTrue(workspace_debug_enabled("layout"))
            self.assertTrue(workspace_debug_enabled("preview"))
            self.assertFalse(workspace_debug_enabled("events"))

    def test_debug_log_writes_jsonl_record_when_file_flag_is_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "contract-template-workspace-debug.jsonl"
            with mock.patch.dict(
                os.environ,
                {
                    "ISRC_CT_LAYOUT_DEBUG": "1",
                    "ISRC_CT_WORKSPACE_DEBUG_FILE": str(log_path),
                },
                clear=False,
            ):
                workspace_debug_log(
                    "layout",
                    "workspace_host.capture_layout_state.captured",
                    state={"example": True},
                )

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["topic"], "layout")
            self.assertEqual(record["event"], "workspace_host.capture_layout_state.captured")
            self.assertEqual(record["payload"]["state"], {"example": True})

    def test_summarize_panel_layout_snapshot_compacts_dock_state_payload(self):
        snapshot = {
            "contract_templates": {
                "schema_version": 1,
                "current_tab": "fill",
                "tabs": {
                    "fill": {
                        "dock_state_b64": "abc123",
                        "layout_locked": True,
                        "layout_version": 4,
                        "dock_object_names": ["contractTemplateHtmlPreviewDock"],
                        "dock_visibility": {"contractTemplateHtmlPreviewDock": False},
                    }
                },
            }
        }

        summary = summarize_panel_layout_snapshot(snapshot)

        self.assertEqual(summary["contract_templates"]["current_tab"], "fill")
        self.assertEqual(
            summary["contract_templates"]["tabs"]["fill"]["dock_state_b64_len"],
            6,
        )
        self.assertTrue(summary["contract_templates"]["tabs"]["fill"]["dock_state_digest"])
        self.assertFalse(
            summary["contract_templates"]["tabs"]["fill"]["dock_visibility"][
                "contractTemplateHtmlPreviewDock"
            ]
        )

    def test_contract_template_debug_helpers_handle_missing_widgets(self):
        self.assertEqual(summarize_contract_template_panel(None), {"valid": False})
        self.assertEqual(summarize_catalog_workspace_dock(None), {"valid": False})

    def test_contract_template_debug_helpers_handle_qformlayout_enums(self):
        if QWidget is None or QFormLayout is None:
            self.skipTest("PySide6 QtWidgets unavailable")
        require_qapplication()
        panel = QWidget()
        panel.fill_auto_form = QFormLayout()
        panel.fill_selector_form = QFormLayout()
        panel.fill_manual_form = QFormLayout()

        summary = summarize_contract_template_panel(panel)

        self.assertTrue(summary["valid"])
        self.assertEqual(summary["fill_auto_form"]["row_count"], 0)
        self.assertIsNotNone(summary["fill_auto_form"]["field_growth_policy"])
        self.assertIsNotNone(summary["fill_auto_form"]["row_wrap_policy"])

    def test_workspace_debug_widget_summary_helpers_cover_valid_and_invalid_qt_objects(self):
        if (
            QWidget is None
            or QComboBox is None
            or QLabel is None
            or QScrollArea is None
            or QDockWidget is None
            or QMainWindow is None
        ):
            self.skipTest("PySide6 QtWidgets unavailable")
        require_qapplication()

        self.assertIsNone(_rect_payload("not-a-rect"))
        self.assertEqual(
            _rect_payload(QRect(1, 2, 3, 4)), {"x": 1, "y": 2, "width": 3, "height": 4}
        )
        self.assertIsNone(_size_payload("not-a-size"))
        self.assertEqual(_size_payload(QSize(5, 6)), {"width": 5, "height": 6})
        self.assertEqual(_json_safe({"path": Path("demo"), "values": {2, 1}})["path"], "demo")
        self.assertEqual(_json_safe(QRect(1, 2, 3, 4))["width"], 3)
        self.assertEqual(_json_safe(QSize(5, 6))["height"], 6)

        class BadString:
            def __str__(self):
                raise RuntimeError("no string")

            def __repr__(self):
                return "<bad-string>"

        self.assertEqual(_json_safe(BadString()), "<bad-string>")
        self.assertEqual(_enum_payload(None), None)
        self.assertEqual(_enum_payload(SimpleEnumValue("raw")), "raw")

        combo = QComboBox()
        combo.addItems(["One", "Two"])
        combo.setCurrentIndex(1)
        self.assertEqual(_combo_summary(combo)["current_text"], "Two")
        self.assertIsNone(_combo_summary(None))

        label = QLabel("Ready")
        self.assertEqual(_label_summary(label)["text"], "Ready")
        self.assertIsNone(_label_summary(None))

        scroll = QScrollArea()
        content = QWidget()
        child = QLabel("Visible child", content)
        child.setObjectName("childLabel")
        scroll.setWidget(content)
        scroll_summary = _scroll_area_summary(scroll)
        self.assertEqual(scroll_summary["direct_child_widget_count"], 1)
        self.assertIsNone(_scroll_area_summary(None))

        window = QMainWindow()
        dock = QDockWidget("Preview", window)
        dock.setObjectName("previewDock")
        dock.setWidget(scroll)
        window.addDockWidget(Qt.RightDockWidgetArea, dock)
        dock_summary = summarize_qdockwidget(dock, host=window)
        self.assertTrue(dock_summary["valid"])
        self.assertEqual(dock_summary["object_name"], "previewDock")
        self.assertEqual(dock_summary["widget_class_name"], "QScrollArea")
        self.assertEqual(summarize_qdockwidget("bad")["valid"], False)

        window._docks = [dock]
        window._pending_state = {"dock_state_b64": "abc", "dock_object_names": ["previewDock"]}
        window._stable_layout_state = {"layout_version": 2}
        window.tab_key = "contracts"
        host_summary = summarize_workspace_host(window)
        self.assertTrue(host_summary["valid"])
        self.assertEqual(host_summary["docks"][0]["object_name"], "previewDock")
        self.assertEqual(summarize_workspace_host(None), {"valid": False})

        with mock.patch("isrc_manager.workspace_debug._qt_object_is_valid", return_value=False):
            self.assertIsNone(_widget_descriptor(QWidget()))

    def test_workspace_debug_exception_summaries_are_contained(self):
        if QWidget is None or QDockWidget is None:
            self.skipTest("PySide6 QtWidgets unavailable")
        require_qapplication()

        dock = QDockWidget("Broken")
        with mock.patch(
            "isrc_manager.workspace_debug._scroll_area_summary",
            side_effect=RuntimeError("summary boom"),
        ):
            self.assertFalse(summarize_qdockwidget(dock)["valid"])

        host = QWidget()
        host._docks = [dock]
        with mock.patch(
            "isrc_manager.workspace_debug.summarize_qdockwidget",
            side_effect=RuntimeError("host boom"),
        ):
            self.assertFalse(summarize_workspace_host(host)["valid"])

        panel = QWidget()
        panel._current_tab_key = mock.Mock(side_effect=RuntimeError("tab gone"))
        panel._selected_fill_revision_id = mock.Mock(side_effect=RuntimeError("selection gone"))
        panel._tab_hosts = {"fill": host}
        summary = summarize_contract_template_panel(panel)
        self.assertTrue(summary["valid"])
        self.assertEqual(summary["current_tab"], "")
        self.assertIsNone(summary["selected_fill_revision_id"])

        dock._panel = panel
        dock._pending_panel_layout_state = {"tabs": {}}
        catalog_summary = summarize_catalog_workspace_dock(dock)
        self.assertTrue(catalog_summary["valid"])
        self.assertTrue(catalog_summary["panel_materialized"])

        with mock.patch(
            "isrc_manager.workspace_debug.summarize_qdockwidget",
            side_effect=RuntimeError("dock boom"),
        ):
            self.assertFalse(summarize_catalog_workspace_dock(dock)["valid"])

    def test_workspace_debug_log_handles_stack_and_unwritable_file_edges(self):
        with mock.patch.dict(
            os.environ,
            {
                "ISRC_CT_WORKSPACE_DEBUG": "all",
                "ISRC_CT_DEBUG_STACKS": "1",
            },
            clear=False,
        ):
            self.assertTrue(workspace_debug_enabled("anything"))
            workspace_debug_log("layout", "stacked", value=object())

        with mock.patch.dict(
            os.environ,
            {
                "ISRC_CT_LAYOUT_DEBUG": "1",
                "ISRC_CT_WORKSPACE_DEBUG_FILE": "/dev/null/not-writable.jsonl",
            },
            clear=False,
        ):
            workspace_debug_log("layout", "unwritable")


class SimpleEnumValue:
    def __init__(self, value):
        self.value = value

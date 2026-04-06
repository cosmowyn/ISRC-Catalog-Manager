import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtWidgets import QFormLayout, QWidget
except ImportError:  # pragma: no cover - environment-specific fallback
    QFormLayout = None
    QWidget = None

from isrc_manager.workspace_debug import (
    summarize_catalog_workspace_dock,
    summarize_contract_template_panel,
    summarize_panel_layout_snapshot,
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

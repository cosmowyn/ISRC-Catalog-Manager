import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QWidget

from isrc_manager.catalog_workspace import CatalogWorkspaceDock
from tests.qt_test_helpers import pump_events, require_qapplication


class _WorkspaceTestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.scheduled_saves = 0
        self._is_restoring_workspace_layout = False

    def _schedule_main_dock_state_save(self):
        self.scheduled_saves += 1


class _DummyPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.restore_calls: list[dict[str, object] | None] = []
        self.stabilize_calls = 0
        self.captured_states: list[dict[str, object]] = []
        self.refresh_calls = 0
        self.events: list[str] = []

    def restore_layout_state(self, state):
        self.events.append("restore")
        self.restore_calls.append(dict(state) if isinstance(state, dict) else None)

    def stabilize_layout_after_restore(self):
        self.events.append("stabilize")
        self.stabilize_calls += 1

    def capture_layout_state(self):
        self.events.append("capture")
        state = {"restore_calls": len(self.restore_calls), "stabilize_calls": self.stabilize_calls}
        self.captured_states.append(dict(state))
        return state

    def refresh(self):
        self.events.append("refresh")
        self.refresh_calls += 1

    def begin_layout_restore(self):
        self.events.append("begin_layout_restore")

    def finish_layout_restore(self):
        self.events.append("finish_layout_restore")


class CatalogWorkspaceDockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def test_restore_panel_layout_state_calls_live_panel_restore_once(self):
        window = _WorkspaceTestWindow()
        panel = _DummyPanel()
        dock = CatalogWorkspaceDock(
            window,
            dock_title="Contract Template Workspace",
            dock_object_name="contractTemplateWorkspaceDock",
            panel_factory=lambda _dock: panel,
        )
        try:
            window.resize(1200, 900)
            window.addDockWidget(Qt.RightDockWidgetArea, dock)
            window.show()
            dock.show()
            pump_events(app=self.app, cycles=4)
            dock.panel()
            pump_events(app=self.app, cycles=4)
            dock.restore_panel_layout_state({"schema_version": 1, "current_tab": "fill"})
            pump_events(app=self.app, cycles=4)

            self.assertEqual(panel.restore_calls, [{"schema_version": 1, "current_tab": "fill"}])
        finally:
            dock.close()
            dock.deleteLater()
            window.close()
            window.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_pending_panel_layout_state_applies_once_when_panel_materializes(self):
        window = _WorkspaceTestWindow()
        panel = _DummyPanel()
        dock = CatalogWorkspaceDock(
            window,
            dock_title="Contract Template Workspace",
            dock_object_name="contractTemplateWorkspaceDock",
            panel_factory=lambda _dock: panel,
        )
        try:
            window.resize(1200, 900)
            window.addDockWidget(Qt.RightDockWidgetArea, dock)
            window.show()
            dock.hide()
            pump_events(app=self.app, cycles=2)
            dock.restore_panel_layout_state({"schema_version": 1, "current_tab": "import"})
            pump_events(app=self.app, cycles=2)
            self.assertEqual(panel.restore_calls, [])

            dock.show()
            pump_events(app=self.app, cycles=4)
            dock.panel()
            pump_events(app=self.app, cycles=4)

            self.assertEqual(panel.restore_calls, [{"schema_version": 1, "current_tab": "import"}])
        finally:
            dock.close()
            dock.deleteLater()
            window.close()
            window.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_pending_panel_layout_state_waits_for_outer_workspace_restore_to_finish(self):
        window = _WorkspaceTestWindow()
        panel = _DummyPanel()
        dock = CatalogWorkspaceDock(
            window,
            dock_title="Contract Template Workspace",
            dock_object_name="contractTemplateWorkspaceDock",
            panel_factory=lambda _dock: panel,
        )
        try:
            window.resize(1200, 900)
            window.addDockWidget(Qt.RightDockWidgetArea, dock)
            window.show()
            dock.show()
            pump_events(app=self.app, cycles=4)
            dock.panel()
            pump_events(app=self.app, cycles=4)

            window._is_restoring_workspace_layout = True
            dock.restore_panel_layout_state({"schema_version": 1, "current_tab": "fill"})
            pump_events(app=self.app, cycles=4)
            self.assertEqual(panel.restore_calls, [])

            window._is_restoring_workspace_layout = False
            dock.stabilize_panel_layout_after_restore()
            pump_events(app=self.app, cycles=4)

            self.assertEqual(panel.restore_calls, [{"schema_version": 1, "current_tab": "fill"}])
        finally:
            dock.close()
            dock.deleteLater()
            window.close()
            window.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_visibility_during_outer_restore_defers_panel_materialization(self):
        window = _WorkspaceTestWindow()
        panel = _DummyPanel()
        dock = CatalogWorkspaceDock(
            window,
            dock_title="Contract Template Workspace",
            dock_object_name="contractTemplateWorkspaceDock",
            panel_factory=lambda _dock: panel,
        )
        try:
            window.resize(1200, 900)
            window.addDockWidget(Qt.RightDockWidgetArea, dock)
            dock.hide()
            window.show()
            pump_events(app=self.app, cycles=2)
            self.assertIsNone(dock._panel)

            window._is_restoring_workspace_layout = True
            dock.show()
            pump_events(app=self.app, cycles=4)

            self.assertIsNone(dock._panel)
            self.assertEqual(panel.refresh_calls, 0)
        finally:
            dock.close()
            dock.deleteLater()
            window.close()
            window.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_capture_panel_layout_state_runs_panel_stabilizer_before_capture(self):
        window = _WorkspaceTestWindow()
        panel = _DummyPanel()
        dock = CatalogWorkspaceDock(
            window,
            dock_title="Contract Template Workspace",
            dock_object_name="contractTemplateWorkspaceDock",
            panel_factory=lambda _dock: panel,
        )
        try:
            window.resize(1200, 900)
            window.addDockWidget(Qt.RightDockWidgetArea, dock)
            window.show()
            dock.show()
            pump_events(app=self.app, cycles=4)
            dock.panel()
            pump_events(app=self.app, cycles=4)

            state = dock.capture_panel_layout_state()

            self.assertEqual(panel.stabilize_calls, 1)
            self.assertEqual(state, {"restore_calls": 0, "stabilize_calls": 1})
            self.assertEqual(panel.captured_states, [state])
        finally:
            dock.close()
            dock.deleteLater()
            window.close()
            window.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_capture_panel_layout_state_preserves_pending_hidden_materialized_panel_state(self):
        window = _WorkspaceTestWindow()
        panel = _DummyPanel()
        dock = CatalogWorkspaceDock(
            window,
            dock_title="Contract Template Workspace",
            dock_object_name="contractTemplateWorkspaceDock",
            panel_factory=lambda _dock: panel,
        )
        try:
            pending_state = {"schema_version": 1, "current_tab": "fill"}
            window.resize(1200, 900)
            window.addDockWidget(Qt.RightDockWidgetArea, dock)
            window.show()
            dock.show()
            pump_events(app=self.app, cycles=4)
            dock.panel()
            pump_events(app=self.app, cycles=4)

            dock.hide()
            pump_events(app=self.app, cycles=2)
            dock.restore_panel_layout_state(pending_state)
            pump_events(app=self.app, cycles=2)

            captured = dock.capture_panel_layout_state()

            self.assertEqual(captured, pending_state)
            self.assertEqual(panel.restore_calls, [])
            self.assertEqual(panel.captured_states, [])
        finally:
            dock.close()
            dock.deleteLater()
            window.close()
            window.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_showing_pending_hidden_panel_restores_before_refreshing(self):
        window = _WorkspaceTestWindow()
        panel = _DummyPanel()
        dock = CatalogWorkspaceDock(
            window,
            dock_title="Contract Template Workspace",
            dock_object_name="contractTemplateWorkspaceDock",
            panel_factory=lambda _dock: panel,
        )
        try:
            pending_state = {"schema_version": 1, "current_tab": "fill"}
            window.resize(1200, 900)
            window.addDockWidget(Qt.RightDockWidgetArea, dock)
            window.show()
            dock.show()
            pump_events(app=self.app, cycles=4)
            dock.panel()
            pump_events(app=self.app, cycles=4)

            dock.hide()
            panel.events.clear()
            pump_events(app=self.app, cycles=2)
            dock.restore_panel_layout_state(pending_state)
            pump_events(app=self.app, cycles=2)

            dock.show_panel()
            pump_events(app=self.app, cycles=4)

            self.assertTrue(panel.events)
            self.assertEqual(panel.events[0], "begin_layout_restore")
            self.assertEqual(panel.events[1], "restore")
            self.assertIn("finish_layout_restore", panel.events)
            self.assertEqual(panel.restore_calls, [pending_state])
        finally:
            dock.close()
            dock.deleteLater()
            window.close()
            window.deleteLater()
            pump_events(app=self.app, cycles=2)

    def test_visibility_change_during_outer_restore_does_not_refresh_existing_panel(self):
        window = _WorkspaceTestWindow()
        panel = _DummyPanel()
        dock = CatalogWorkspaceDock(
            window,
            dock_title="Contract Template Workspace",
            dock_object_name="contractTemplateWorkspaceDock",
            panel_factory=lambda _dock: panel,
        )
        try:
            window.resize(1200, 900)
            window.addDockWidget(Qt.RightDockWidgetArea, dock)
            window.show()
            dock.show()
            pump_events(app=self.app, cycles=4)
            dock.panel()
            panel.refresh_calls = 0
            panel.events.clear()
            pump_events(app=self.app, cycles=2)

            window._is_restoring_workspace_layout = True
            dock.hide()
            pump_events(app=self.app, cycles=2)
            dock.show()
            pump_events(app=self.app, cycles=4)

            self.assertEqual(panel.refresh_calls, 0)
            self.assertNotIn("refresh", panel.events)
        finally:
            dock.close()
            dock.deleteLater()
            window.close()
            window.deleteLater()
            pump_events(app=self.app, cycles=2)

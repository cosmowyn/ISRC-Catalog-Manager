import unittest
from types import SimpleNamespace
from unittest import mock

from tests.qt_test_helpers import pump_events, require_qapplication

try:
    from PySide6.QtGui import QAction

    import ISRC_manager as app_module
except Exception as exc:  # pragma: no cover - environment-specific fallback
    QAction = None
    APP_IMPORT_ERROR = exc
else:
    APP_IMPORT_ERROR = None


class HistoryBudgetHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QAction is None:
            raise unittest.SkipTest(f"PySide6 app import unavailable: {APP_IMPORT_ERROR}")
        cls.app = require_qapplication()

    def test_schedule_history_storage_budget_enforcement_runs_once(self):
        target = SimpleNamespace(
            _history_budget_enforcement_trigger_label="history update",
            _history_budget_enforcement_scheduled=False,
            _history_budget_enforcement_running=False,
            _enforce_history_storage_budget=mock.Mock(),
        )

        app_module.App._schedule_history_storage_budget_enforcement(
            target,
            trigger_label="initial update",
        )
        app_module.App._schedule_history_storage_budget_enforcement(
            target,
            trigger_label="later update",
        )
        pump_events(cycles=4)

        target._enforce_history_storage_budget.assert_called_once_with(
            trigger_label="later update",
            interactive=False,
        )
        self.assertFalse(target._history_budget_enforcement_scheduled)
        self.assertFalse(target._history_budget_enforcement_running)

    def test_refresh_history_actions_schedules_budget_enforcement(self):
        undo_action = QAction()
        redo_action = QAction()
        target = SimpleNamespace(
            undo_action=undo_action,
            redo_action=redo_action,
            history_dialog=None,
            _get_best_history_candidate=lambda _direction: (None, None),
            _schedule_history_storage_budget_enforcement=mock.Mock(),
        )

        app_module.App._refresh_history_actions(target)

        self.assertEqual(undo_action.text(), "Undo")
        self.assertFalse(undo_action.isEnabled())
        self.assertEqual(redo_action.text(), "Redo")
        self.assertFalse(redo_action.isEnabled())
        target._schedule_history_storage_budget_enforcement.assert_called_once_with(
            trigger_label="history update"
        )


if __name__ == "__main__":
    unittest.main()

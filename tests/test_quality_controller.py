import unittest
from types import SimpleNamespace
from unittest import mock

from isrc_manager.quality.controller import (
    _apply_quality_fix,
    _open_issue_from_dashboard,
    _scan_quality_dashboard_in_background,
    open_quality_dashboard,
)
from isrc_manager.quality.models import QualityIssue


class QualityControllerTests(unittest.TestCase):
    def test_open_quality_dashboard_warns_when_service_missing(self):
        app = SimpleNamespace(quality_service=None)

        with mock.patch("isrc_manager.quality.controller._message_box") as message_box:
            box = mock.Mock()
            message_box.return_value = box
            self.assertIsNone(open_quality_dashboard(app))
            box.warning.assert_called_once_with(
                app,
                "Data Quality Dashboard",
                "Open a profile first.",
            )

    def test_open_quality_dashboard_refreshes_existing_dialog(self):
        dialog = mock.Mock()
        app = SimpleNamespace(
            quality_service=mock.Mock(),
            quality_dashboard_dialog=dialog,
        )
        result = open_quality_dashboard(app)

        self.assertIs(result, dialog)
        dialog.refresh_scan.assert_called_once_with()
        dialog.show.assert_called_once_with()
        dialog.raise_.assert_called_once_with()
        dialog.activateWindow.assert_called_once_with()

    def test_open_quality_dashboard_creates_dialog_when_absent(self):
        dialog_instance = mock.Mock()
        dialog_class = mock.Mock(return_value=dialog_instance)
        app = SimpleNamespace(
            quality_service=mock.Mock(),
            background_tasks=object(),
            _scan_quality_dashboard_in_background=mock.Mock(),
            _release_choices=mock.Mock(return_value=[(1, "Release")]),
            _apply_quality_fix=mock.Mock(),
            _open_issue_from_dashboard=mock.Mock(),
            quality_dashboard_dialog=None,
        )

        with mock.patch(
            "isrc_manager.quality.controller._root_attr",
            side_effect=lambda name, fallback: (
                dialog_class if name == "QualityDashboardDialog" else fallback
            ),
        ):
            result = open_quality_dashboard(app)

        self.assertIs(result, dialog_instance)
        dialog_class.assert_called_once_with(
            service=app.quality_service,
            scan_callback=app._scan_quality_dashboard_in_background,
            task_manager=app.background_tasks,
            release_choices_provider=app._release_choices,
            apply_fix_callback=app._apply_quality_fix,
            open_issue_callback=app._open_issue_from_dashboard,
            parent=app,
        )
        dialog_instance.show.assert_called_once_with()

    def test_scan_quality_dashboard_in_background_uses_service_factory(self):
        bundle = mock.Mock(quality_service=mock.Mock(scan=mock.Mock(return_value="scan-result")))
        context = mock.Mock(
            __enter__=mock.Mock(return_value=bundle), __exit__=mock.Mock(return_value=False)
        )
        app = SimpleNamespace(
            background_service_factory=mock.Mock(open_bundle=mock.Mock(return_value=context)),
        )

        result = _scan_quality_dashboard_in_background(app)

        self.assertEqual(result, "scan-result")
        app.background_service_factory.open_bundle.assert_called_once_with()
        bundle.quality_service.scan.assert_called_once_with()

    def test_apply_quality_fix_requires_fix_key(self):
        app = SimpleNamespace(
            quality_service=mock.Mock(),
            _run_snapshot_history_action=mock.Mock(),
            _log_event=mock.Mock(),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
            refresh_table_preserve_view=mock.Mock(),
            populate_all_comboboxes=mock.Mock(),
        )
        issue = QualityIssue(
            issue_type="fill_from_release",
            severity="warning",
            title="Missing fields",
            details="",
            entity_type="track",
            entity_id=1,
            fix_key="   ",
        )

        with self.assertRaises(ValueError):
            _apply_quality_fix(app, issue)

    def test_apply_quality_fix_applies_fix_and_records_audit(self):
        app = SimpleNamespace(
            quality_service=mock.Mock(),
            _run_snapshot_history_action=mock.Mock(return_value="quality-fixed"),
            _log_event=mock.Mock(),
            _audit=mock.Mock(),
            _audit_commit=mock.Mock(),
            refresh_table_preserve_view=mock.Mock(),
            populate_all_comboboxes=mock.Mock(),
        )
        issue = QualityIssue(
            issue_type="fill_from_release",
            severity="warning",
            title="Missing fields",
            details="",
            entity_type="track",
            entity_id=12,
            fix_key="fill_from_release",
            release_id=2,
            track_id=4,
        )

        result = _apply_quality_fix(app, issue)

        self.assertEqual(result, "quality-fixed")
        app._run_snapshot_history_action.assert_called_once()
        app._log_event.assert_called_once_with(
            "quality.fix",
            "Applied quality fix",
            fix_key="fill_from_release",
            message_text="quality-fixed",
        )
        app._audit.assert_called_once_with(
            "REPAIR",
            "QualityIssue",
            ref_id="fill_from_release",
            details="quality-fixed",
        )
        app._audit_commit.assert_called_once_with()
        app.refresh_table_preserve_view.assert_called_once_with()
        app.populate_all_comboboxes.assert_called_once_with()

    def test_open_issue_from_dashboard_routes_to_work_open(self):
        app = SimpleNamespace(
            open_work_manager=mock.Mock(),
            open_selected_editor=mock.Mock(),
            open_release_editor=mock.Mock(),
        )
        issue = QualityIssue(
            issue_type="track_missing_linked_work",
            severity="warning",
            title="Missing link",
            details="",
            entity_type="work",
            entity_id=55,
            track_id=9,
        )

        _open_issue_from_dashboard(app, issue)

        app.open_work_manager.assert_called_once_with(work_id=55)
        app.open_selected_editor.assert_not_called()
        app.open_release_editor.assert_not_called()

    def test_open_issue_from_dashboard_routes_to_track_editor(self):
        app = SimpleNamespace(
            open_work_manager=mock.Mock(),
            open_selected_editor=mock.Mock(),
            open_release_editor=mock.Mock(),
        )
        issue = QualityIssue(
            issue_type="unlinked",
            severity="warning",
            title="Track issue",
            details="",
            entity_type="track",
            entity_id=7,
            track_id=9,
        )

        _open_issue_from_dashboard(app, issue)

        app.open_selected_editor.assert_called_once_with(9)
        app.open_work_manager.assert_not_called()
        app.open_release_editor.assert_not_called()

    def test_open_issue_from_dashboard_routes_to_release_editor(self):
        app = SimpleNamespace(
            open_work_manager=mock.Mock(),
            open_selected_editor=mock.Mock(),
            open_release_editor=mock.Mock(),
        )
        issue = QualityIssue(
            issue_type="unlinked",
            severity="warning",
            title="Release issue",
            details="",
            entity_type="release",
            entity_id=77,
            release_id=99,
        )

        _open_issue_from_dashboard(app, issue)

        app.open_release_editor.assert_called_once_with(99)
        app.open_work_manager.assert_not_called()
        app.open_selected_editor.assert_not_called()

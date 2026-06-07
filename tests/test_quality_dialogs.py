import unittest
from unittest import mock

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QFileDialog, QListView, QMessageBox
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    Qt = None
    QApplication = None
    QListView = None
    QMessageBox = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.quality.dialogs import QualityDashboardDialog, _create_filter_combo
from isrc_manager.quality.models import QualityIssue, QualityScanResult


class _DummyQualityService:
    def __init__(self, result: QualityScanResult):
        self._result = result
        self.csv_exports = []
        self.json_exports = []

    def scan(self) -> QualityScanResult:
        return self._result

    def export_csv(self, result: QualityScanResult, path: str) -> None:
        self.csv_exports.append((result, path))

    def export_json(self, result: QualityScanResult, path: str) -> None:
        self.json_exports.append((result, path))


class QualityDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def test_quality_dashboard_dialog_uses_scan_result(self):
        result = QualityScanResult(
            issues=[
                QualityIssue(
                    issue_type="missing_isrc",
                    severity="warning",
                    title="Missing ISRC",
                    details="Track is missing an ISRC.",
                    entity_type="track",
                    entity_id=1,
                    track_id=1,
                )
            ],
            counts_by_severity={"warning": 1},
            counts_by_type={"missing_isrc": 1},
        )
        dialog = QualityDashboardDialog(
            service=_DummyQualityService(result),
            scan_callback=None,
            task_manager=None,
            release_choices_provider=lambda: [],
            apply_fix_callback=lambda _issue: "",
            open_issue_callback=lambda _issue: None,
        )
        try:
            self.assertEqual(dialog.property("role"), "panel")
            self.assertFalse(dialog.isModal())
            self.assertEqual(dialog.windowModality(), Qt.NonModal)
            self.assertEqual(dialog.total_label.text(), "Total issues: 1")
            self.assertEqual(dialog.warning_label.text(), "Warnings: 1")
            self.assertEqual(dialog.issue_table.rowCount(), 1)
            self.assertIn("Track is missing an ISRC.", dialog.details.toPlainText())
            self.assertTrue(dialog.open_button.isEnabled())
            self.assertFalse(dialog.fix_button.isEnabled())
        finally:
            dialog.close()

    def test_quality_dashboard_dialog_passes_selected_issue_to_fix_callback(self):
        result = QualityScanResult(
            issues=[
                QualityIssue(
                    issue_type="track_can_fill_from_release",
                    severity="info",
                    title="Track Can Inherit Release Metadata",
                    details="Track can inherit missing values from the linked release.",
                    entity_type="track",
                    entity_id=4,
                    release_id=2,
                    track_id=4,
                    fix_key="fill_from_release",
                )
            ],
            counts_by_severity={"info": 1},
            counts_by_type={"track_can_fill_from_release": 1},
        )
        applied = []
        dialog = QualityDashboardDialog(
            service=_DummyQualityService(result),
            scan_callback=None,
            task_manager=None,
            release_choices_provider=lambda: [(2, "Orbit Release")],
            apply_fix_callback=lambda issue: applied.append(issue) or "Applied",
            open_issue_callback=lambda _issue: None,
        )
        try:
            self.assertTrue(dialog.fix_button.isEnabled())
            with mock.patch.object(QMessageBox, "information", return_value=None) as info:
                dialog._apply_selected_fix()
            info.assert_called_once()
            self.assertEqual(len(applied), 1)
            self.assertEqual(applied[0].fix_key, "fill_from_release")
            self.assertEqual(applied[0].track_id, 4)
        finally:
            dialog.close()

    def test_filter_combo_uses_qt_list_popup(self):
        combo = _create_filter_combo(minimum_contents_length=12)
        self.assertIsInstance(combo.view(), QListView)
        self.assertEqual(combo.minimumContentsLength(), 12)
        self.assertEqual(combo.maxVisibleItems(), 18)

    def test_quality_dashboard_table_double_click_opens_selected_issue(self):
        issue = QualityIssue(
            issue_type="missing_isrc",
            severity="warning",
            title="Missing ISRC",
            details="Track is missing an ISRC.",
            entity_type="track",
            entity_id=7,
            track_id=7,
        )
        result = QualityScanResult(
            issues=[issue],
            counts_by_severity={"warning": 1},
            counts_by_type={"missing_isrc": 1},
        )
        opened = []
        dialog = QualityDashboardDialog(
            service=_DummyQualityService(result),
            scan_callback=None,
            task_manager=None,
            release_choices_provider=lambda: [],
            apply_fix_callback=lambda _issue: "",
            open_issue_callback=lambda selected_issue: opened.append(selected_issue),
        )
        try:
            dialog.issue_table.itemDoubleClicked.emit(dialog.issue_table.item(0, 0))
            self.assertEqual(opened, [issue])
        finally:
            dialog.close()

    def test_quality_dashboard_dialog_populates_entity_filter_from_scan_result(self):
        result = QualityScanResult(
            issues=[
                QualityIssue(
                    issue_type="work_missing_creators",
                    severity="warning",
                    title="Work Missing Creators",
                    details="Work needs credited writers.",
                    entity_type="work",
                    entity_id=12,
                ),
                QualityIssue(
                    issue_type="missing_isrc",
                    severity="warning",
                    title="Missing ISRC",
                    details="Track is missing an ISRC.",
                    entity_type="track",
                    entity_id=1,
                    track_id=1,
                ),
            ],
            counts_by_severity={"warning": 2},
            counts_by_type={"work_missing_creators": 1, "missing_isrc": 1},
        )
        dialog = QualityDashboardDialog(
            service=_DummyQualityService(result),
            scan_callback=None,
            task_manager=None,
            release_choices_provider=lambda: [],
            apply_fix_callback=lambda _issue: "",
            open_issue_callback=lambda _issue: None,
        )
        try:
            entity_values = [
                dialog.entity_combo.itemData(index) for index in range(dialog.entity_combo.count())
            ]
            self.assertEqual(entity_values[0], "")
            self.assertIn("work", entity_values)
            self.assertIn("track", entity_values)

            dialog.entity_combo.setCurrentIndex(dialog.entity_combo.findData("work"))
            self.app.processEvents()
            self.assertEqual(dialog.issue_table.rowCount(), 1)
            self.assertIn("work missing creators", dialog.details.toPlainText().lower())
            self.assertEqual(dialog.open_button.text(), "Open Related Surface")
        finally:
            dialog.close()

    def test_quality_dashboard_task_manager_busy_and_failure_paths(self):
        result = QualityScanResult(issues=[])
        service = _DummyQualityService(result)

        class _BusyTaskManager:
            def __init__(self):
                self.submissions = []

            def submit(self, **kwargs):
                self.submissions.append(kwargs)
                return None

        task_manager = _BusyTaskManager()
        dialog = QualityDashboardDialog(
            service=service,
            scan_callback=service.scan,
            task_manager=task_manager,
            release_choices_provider=lambda: [],
            apply_fix_callback=lambda _issue: "",
            open_issue_callback=lambda _issue: None,
        )
        try:
            self.assertEqual(len(task_manager.submissions), 1)
            self.assertTrue(dialog.refresh_button.isEnabled())
            self.assertEqual(dialog.details.toPlainText(), "A quality scan is already running.")

            dialog._active_scan_task_id = "scan-1"
            dialog.details.setPlainText("unchanged")
            dialog.refresh_scan()
            self.assertEqual(dialog.details.toPlainText(), "unchanged")
            self.assertEqual(dialog._active_scan_task_id, "scan-1")

            dialog._finish_scan_request()
            self.assertIsNone(dialog._active_scan_task_id)
            self.assertTrue(dialog.refresh_button.isEnabled())

            with mock.patch.object(QMessageBox, "critical", return_value=None) as critical:
                dialog._fail_scan("scan exploded")
            critical.assert_called_once()
            self.assertEqual(dialog.details.toPlainText(), "scan exploded")
            self.assertFalse(dialog.open_button.isEnabled())
            self.assertFalse(dialog.fix_button.isEnabled())
        finally:
            dialog.close()

    def test_quality_dashboard_filters_selection_guards_and_fix_errors(self):
        issues = [
            QualityIssue(
                issue_type="missing_isrc",
                severity="warning",
                title="Missing ISRC",
                details="Track is missing an ISRC.",
                entity_type="track",
                entity_id=1,
                release_id=1,
                track_id=1,
            ),
            QualityIssue(
                issue_type="broken_media",
                severity="error",
                title="Broken Media",
                details="Media file is missing.",
                entity_type="asset",
                entity_id=2,
                release_id=2,
                fix_key="repair_media",
            ),
        ]
        result = QualityScanResult(
            issues=issues,
            counts_by_severity={"warning": 1, "error": 1},
            counts_by_type={"missing_isrc": 1, "broken_media": 1},
        )
        opened = []
        dialog = QualityDashboardDialog(
            service=_DummyQualityService(result),
            scan_callback=None,
            task_manager=None,
            release_choices_provider=lambda: [(1, "Release One"), (2, "Release Two")],
            apply_fix_callback=lambda _issue: (_ for _ in ()).throw(RuntimeError("repair failed")),
            open_issue_callback=lambda issue: opened.append(issue),
        )
        try:
            dialog.severity_combo.setCurrentText("error")
            self.app.processEvents()
            self.assertEqual(dialog.issue_table.rowCount(), 1)
            self.assertIn("Broken Media", dialog.details.toPlainText())

            dialog.severity_combo.setCurrentText("All severities")
            dialog.issue_type_combo.setCurrentIndex(
                dialog.issue_type_combo.findData("missing_isrc")
            )
            self.app.processEvents()
            self.assertEqual(dialog.issue_table.rowCount(), 1)
            self.assertIn("Missing ISRC", dialog.details.toPlainText())

            dialog.release_combo.setCurrentIndex(dialog.release_combo.findData(2))
            self.app.processEvents()
            self.assertEqual(dialog.issue_table.rowCount(), 0)
            self.assertEqual(dialog.details.toPlainText(), "")
            self.assertFalse(dialog.open_button.isEnabled())
            self.assertFalse(dialog.fix_button.isEnabled())

            dialog.issue_table.setRowCount(1)
            dialog.issue_table.setCurrentCell(0, 0)
            self.assertIsNone(dialog._selected_issue())
            dialog._load_issue_details()
            dialog._open_selected_issue()
            dialog._apply_selected_fix()
            self.assertEqual(opened, [])

            dialog.issue_type_combo.setCurrentIndex(0)
            dialog.release_combo.setCurrentIndex(dialog.release_combo.findData(2))
            self.app.processEvents()
            self.assertEqual(dialog.issue_table.rowCount(), 1)
            dialog._open_selected_issue()
            self.assertEqual(opened, [issues[1]])
            with mock.patch.object(QMessageBox, "critical", return_value=None) as critical:
                dialog._apply_selected_fix()
            critical.assert_called_once()
        finally:
            dialog.close()

    def test_quality_dashboard_export_cancel_and_filtered_payloads(self):
        issues = [
            QualityIssue(
                issue_type="missing_isrc",
                severity="warning",
                title="Missing ISRC",
                details="Track is missing an ISRC.",
                entity_type="track",
                entity_id=1,
                release_id=1,
                track_id=1,
            ),
            QualityIssue(
                issue_type="broken_media",
                severity="error",
                title="Broken Media",
                details="Media file is missing.",
                entity_type="asset",
                entity_id=2,
                release_id=2,
            ),
        ]
        result = QualityScanResult(
            issues=issues,
            counts_by_severity={"warning": 1, "error": 1},
            counts_by_type={"missing_isrc": 1, "broken_media": 1},
        )
        service = _DummyQualityService(result)
        dialog = QualityDashboardDialog(
            service=service,
            scan_callback=None,
            task_manager=None,
            release_choices_provider=lambda: [(1, "Release One"), (2, "Release Two")],
            apply_fix_callback=lambda _issue: "",
            open_issue_callback=lambda _issue: None,
        )
        try:
            dialog.severity_combo.setCurrentText("warning")
            self.app.processEvents()

            with mock.patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
                dialog._export_csv()
                dialog._export_json()
            self.assertEqual(service.csv_exports, [])
            self.assertEqual(service.json_exports, [])

            with mock.patch.object(
                QFileDialog,
                "getSaveFileName",
                side_effect=[("/tmp/quality.csv", ""), ("/tmp/quality.json", "")],
            ):
                dialog._export_csv()
                dialog._export_json()

            self.assertEqual(service.csv_exports[0][1], "/tmp/quality.csv")
            self.assertEqual(service.json_exports[0][1], "/tmp/quality.json")
            self.assertEqual(service.csv_exports[0][0].issues, [issues[0]])
            self.assertEqual(service.json_exports[0][0].issues, [issues[0]])
            self.assertEqual(service.csv_exports[0][0].counts_by_type, result.counts_by_type)
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()

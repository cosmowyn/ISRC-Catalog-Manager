import unittest
from unittest import mock

try:
    from PySide6.QtWidgets import QApplication, QListView, QMessageBox
except ImportError as exc:  # pragma: no cover - environment-specific fallback
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

    def scan(self) -> QualityScanResult:
        return self._result


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


if __name__ == "__main__":
    unittest.main()

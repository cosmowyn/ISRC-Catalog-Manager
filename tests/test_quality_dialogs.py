import unittest

try:
    from PySide6.QtWidgets import QApplication, QListView
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QListView = None
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
            apply_fix_callback=lambda _fix_key: "",
            open_issue_callback=lambda _issue: None,
        )
        try:
            self.assertEqual(dialog.total_label.text(), "Total issues: 1")
            self.assertEqual(dialog.warning_label.text(), "Warnings: 1")
            self.assertEqual(dialog.issue_table.rowCount(), 1)
            self.assertIn("Track is missing an ISRC.", dialog.details.toPlainText())
        finally:
            dialog.close()

    def test_filter_combo_uses_qt_list_popup(self):
        combo = _create_filter_combo(minimum_contents_length=12)
        self.assertIsInstance(combo.view(), QListView)
        self.assertEqual(combo.minimumContentsLength(), 12)
        self.assertEqual(combo.maxVisibleItems(), 18)


if __name__ == "__main__":
    unittest.main()

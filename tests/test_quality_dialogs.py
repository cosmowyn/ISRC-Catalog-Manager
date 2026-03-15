import unittest

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QListView

from isrc_manager.quality.dialogs import _QualityScanThread, _create_filter_combo
from isrc_manager.quality.models import QualityIssue, QualityScanResult


class QualityDialogThreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_quality_scan_thread_uses_callback_result(self):
        expected = QualityScanResult(
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
        loop = QEventLoop()
        captured = {}
        thread = _QualityScanThread(lambda: expected)
        thread.finished_result.connect(lambda result: (captured.setdefault("result", result), loop.quit()))
        thread.failed.connect(lambda message: (captured.setdefault("failed", message), loop.quit()))
        thread.finished.connect(thread.deleteLater)
        QTimer.singleShot(2000, loop.quit)

        thread.start()
        loop.exec()
        thread.wait(2000)

        self.assertNotIn("failed", captured)
        self.assertIn("result", captured)
        self.assertEqual(captured["result"].issues[0].issue_type, "missing_isrc")


class QualityDialogFilterComboTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_filter_combo_uses_qt_list_popup(self):
        combo = _create_filter_combo(minimum_contents_length=12)
        self.assertIsInstance(combo.view(), QListView)
        self.assertEqual(combo.minimumContentsLength(), 12)
        self.assertEqual(combo.maxVisibleItems(), 18)


if __name__ == "__main__":
    unittest.main()

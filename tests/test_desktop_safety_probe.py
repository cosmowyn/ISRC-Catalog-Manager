import os
import unittest

from PySide6.QtCore import QCoreApplication, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog

from isrc_manager.external_launch import (
    TEST_BLOCK_ENV_VAR,
    clear_recorded_external_launches,
    external_launch_blocking_enabled,
    external_launch_guard_active,
    get_recorded_external_launches,
)


class DesktopSafetyDiscoveryProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        clear_recorded_external_launches()

    def test_discovery_bootstrap_blocks_desktop_integrations_by_default(self):
        self.assertEqual(os.environ.get(TEST_BLOCK_ENV_VAR), "1")
        self.assertTrue(external_launch_guard_active())
        self.assertTrue(external_launch_blocking_enabled())
        self.assertTrue(QCoreApplication.testAttribute(Qt.AA_DontUseNativeDialogs))

        open_result = QDesktopServices.openUrl(QUrl.fromLocalFile("/tmp/discovery-probe.txt"))
        dialog_result = QFileDialog.getOpenFileName(
            None,
            "Select Discovery Probe",
            "/tmp/discovery",
            "All Files (*)",
        )

        self.assertTrue(open_result)
        self.assertEqual(dialog_result, ("", ""))
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].via, "external_launch.open_external_url")
        self.assertEqual(requests[1].via, "QFileDialog.getOpenFileName")
        self.assertTrue(all(request.blocked for request in requests))

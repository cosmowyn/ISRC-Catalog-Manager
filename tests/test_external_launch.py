import os
import subprocess
import tempfile
import unittest
import webbrowser
from pathlib import Path
from unittest import mock

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QWidget

    from isrc_manager.app_dialogs import HelpContentsDialog
    from isrc_manager.external_launch import (
        TEST_BLOCK_ENV_VAR,
        clear_recorded_external_launches,
        external_launch_blocking_enabled,
        external_launch_guard_active,
        get_recorded_external_launches,
        open_external_url,
        temporary_external_launch_blocking,
    )
except Exception as exc:  # pragma: no cover - environment-specific fallback
    QUrl = None
    QDesktopServices = None
    QWidget = None
    HelpContentsDialog = None
    EXTERNAL_LAUNCH_IMPORT_ERROR = exc
else:
    EXTERNAL_LAUNCH_IMPORT_ERROR = None


class _HelpDialogHost(QWidget):
    def __init__(self, help_path: Path):
        super().__init__()
        self._help_path = help_path
        self.opened_paths = []

    def _ensure_help_file(self) -> Path:
        return self._help_path

    def _help_html(self) -> str:
        return (
            "<html><body><h1 id='overview'>Overview</h1>"
            "<a href='https://example.com/docs'>External Docs</a>"
            "</body></html>"
        )

    def _open_local_path(self, path, _title):
        self.opened_paths.append(Path(path))
        return True


class ExternalLaunchPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if EXTERNAL_LAUNCH_IMPORT_ERROR is not None:
            raise unittest.SkipTest(
                f"External launch helpers unavailable: {EXTERNAL_LAUNCH_IMPORT_ERROR}"
            )
        cls.app = require_qapplication()

    def setUp(self):
        clear_recorded_external_launches()

    def test_suite_bootstrap_enables_external_launch_guard(self):
        self.assertEqual(os.environ.get(TEST_BLOCK_ENV_VAR), "1")
        self.assertTrue(external_launch_guard_active())
        self.assertTrue(external_launch_blocking_enabled())

    def test_qdesktopservices_open_url_is_blocked_and_recorded(self):
        result = QDesktopServices.openUrl(QUrl("data:text/html;charset=UTF-8,<html></html>"))

        self.assertTrue(result)
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].source, "QDesktopServices.openUrl")
        self.assertTrue(requests[0].blocked)
        self.assertTrue(requests[0].target.startswith("data:text/html"))

    def test_webbrowser_open_is_blocked_and_recorded(self):
        result = webbrowser.open("https://example.com/reference")

        self.assertTrue(result)
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].via, "webbrowser.open")
        self.assertEqual(requests[0].target, "https://example.com/reference")
        self.assertTrue(requests[0].blocked)

    def test_macos_open_command_is_blocked_and_recorded(self):
        result = subprocess.run(
            ["open", "/tmp/example.pdf"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].via, "subprocess.run")
        self.assertEqual(requests[0].target, "/tmp/example.pdf")
        self.assertTrue(requests[0].blocked)

    def test_macos_open_popen_is_blocked_and_recorded(self):
        process = subprocess.Popen(
            ["open", "/tmp/example-folder"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate()

        self.assertEqual(process.returncode, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].via, "subprocess.Popen")
        self.assertEqual(requests[0].target, "/tmp/example-folder")
        self.assertTrue(requests[0].blocked)

    def test_osascript_pages_launch_is_blocked_and_recorded(self):
        result = subprocess.run(
            ["/usr/bin/osascript"],
            input=(
                'tell application "Pages"\n'
                '    open POSIX file "/tmp/template.pages"\n'
                "end tell\n"
            ),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].via, "subprocess.run")
        self.assertEqual(requests[0].target, "/usr/bin/osascript")
        self.assertTrue(requests[0].blocked)

    def test_help_dialog_external_anchor_is_recorded_without_os_launch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            help_path = Path(tmpdir) / "help.html"
            help_path.write_text(
                "<html><body><h1 id='overview'>Overview</h1></body></html>",
                encoding="utf-8",
            )
            host = _HelpDialogHost(help_path)
            dialog = HelpContentsDialog(host)
            try:
                dialog._on_anchor_clicked(QUrl("https://example.com/docs"))
            finally:
                dialog.close()
                host.close()

        self.assertEqual(host.opened_paths, [])
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].source, "HelpContentsDialog.anchorClicked")
        self.assertEqual(requests[0].target, "https://example.com/docs")
        self.assertTrue(requests[0].blocked)

    def test_runtime_mode_delegates_to_real_launcher_callable(self):
        with temporary_external_launch_blocking(False):
            with mock.patch(
                "isrc_manager.external_launch._ORIGINAL_QDESKTOPSERVICES_OPENURL",
                autospec=True,
                return_value=True,
            ) as open_url:
                result = open_external_url(
                    QUrl("https://example.com/runtime"),
                    source="runtime-test",
                )

        self.assertTrue(result)
        open_url.assert_called_once()
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertFalse(requests[0].blocked)
        self.assertEqual(requests[0].target, "https://example.com/runtime")

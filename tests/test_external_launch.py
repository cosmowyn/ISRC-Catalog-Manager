import json
import os
import subprocess
import sys
import tempfile
import unittest
import webbrowser
from pathlib import Path
from unittest import mock

from tests.qt_test_helpers import require_qapplication

try:
    from PySide6.QtCore import QCoreApplication, Qt, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QFileDialog, QWidget

    from isrc_manager.app_dialogs import HelpContentsDialog
    from isrc_manager.external_launch import (
        TEST_BLOCK_ENV_VAR,
        clear_recorded_external_launches,
        external_launch_blocking_enabled,
        external_launch_guard_active,
        get_recorded_external_launches,
        open_external_url,
        run_external_launcher_subprocess,
        temporary_external_launch_blocking,
    )
except Exception as exc:  # pragma: no cover - environment-specific fallback
    QCoreApplication = None
    Qt = None
    QUrl = None
    QDesktopServices = None
    QFileDialog = None
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
        self.assertIsNotNone(QCoreApplication)
        self.assertIsNotNone(Qt)
        self.assertTrue(QCoreApplication.testAttribute(Qt.AA_DontUseNativeDialogs))

    def test_qdesktopservices_open_url_is_blocked_and_recorded(self):
        result = QDesktopServices.openUrl(QUrl("data:text/html;charset=UTF-8,<html></html>"))

        self.assertTrue(result)
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].source, "QDesktopServices.openUrl")
        self.assertTrue(requests[0].blocked)
        self.assertTrue(requests[0].target.startswith("data:text/html"))

    def test_qdesktopservices_open_local_file_is_blocked_and_recorded(self):
        result = QDesktopServices.openUrl(QUrl.fromLocalFile("/tmp/example-preview.pdf"))

        self.assertTrue(result)
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].source, "QDesktopServices.openUrl")
        self.assertTrue(requests[0].blocked)
        self.assertTrue(requests[0].target.startswith("file:///tmp/example-preview.pdf"))

    def test_qfiledialog_requests_are_blocked_and_recorded(self):
        selected_path, selected_filter = QFileDialog.getOpenFileName(
            None,
            "Select Contract",
            "/tmp/contracts",
            "Documents (*.pdf *.docx)",
        )
        save_path, save_filter = QFileDialog.getSaveFileName(
            None,
            "Export Contract",
            "/tmp/exports/agreement.pdf",
            "PDF Files (*.pdf)",
        )
        selected_directory = QFileDialog.getExistingDirectory(
            None,
            "Select Export Folder",
            "/tmp/exports",
        )

        self.assertEqual(selected_path, "")
        self.assertEqual(selected_filter, "")
        self.assertEqual(save_path, "")
        self.assertEqual(save_filter, "")
        self.assertEqual(selected_directory, "")
        requests = get_recorded_external_launches()
        self.assertEqual([request.via for request in requests], [
            "QFileDialog.getOpenFileName",
            "QFileDialog.getSaveFileName",
            "QFileDialog.getExistingDirectory",
        ])
        self.assertTrue(all(request.blocked for request in requests))
        self.assertEqual(requests[0].metadata.get("directory"), "/tmp/contracts")
        self.assertEqual(requests[1].metadata.get("directory"), "/tmp/exports/agreement.pdf")
        self.assertEqual(requests[2].metadata.get("directory"), "/tmp/exports")

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

    def test_shell_open_command_is_blocked_and_recorded(self):
        result = subprocess.run(
            "open /tmp/example-shell.pdf",
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].via, "subprocess.run")
        self.assertEqual(requests[0].target, "/tmp/example-shell.pdf")
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

    def test_macos_open_system_call_is_blocked_and_recorded(self):
        result = os.system("open /tmp/example-system-call.pdf")

        self.assertEqual(result, 0)
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].via, "os.system")
        self.assertEqual(requests[0].target, "/tmp/example-system-call.pdf")
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

    def test_osascript_chooser_launch_is_blocked_and_recorded(self):
        result = subprocess.run(
            ["/usr/bin/osascript"],
            input='choose file with prompt "Select a contract template"\n',
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

    def test_central_launcher_subprocess_helper_blocks_and_records(self):
        result = run_external_launcher_subprocess(
            ["/usr/bin/osascript"],
            input='tell application "Pages"\nactivate\nend tell\n',
            capture_output=True,
            text=True,
            source="unit-test",
            metadata={"integration": "pages_export"},
        )

        self.assertEqual(result.returncode, 0)
        requests = get_recorded_external_launches()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].via, "external_launch.run_external_launcher_subprocess")
        self.assertEqual(requests[0].source, "unit-test")
        self.assertEqual(requests[0].target, "/usr/bin/osascript")
        self.assertEqual(requests[0].metadata.get("integration"), "pages_export")
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

    def test_direct_test_script_bootstraps_guard_without_importing_tests_package(self):
        probe_path = Path(__file__).with_name("_external_launch_probe.py")
        repo_root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop(TEST_BLOCK_ENV_VAR, None)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        env["PYTHONPATH"] = str(repo_root)
        completed = subprocess.run(
            [sys.executable, str(probe_path)],
            capture_output=True,
            text=True,
            check=True,
            env=env,
            cwd=repo_root,
        )

        payload = json.loads(completed.stdout.strip())
        self.assertEqual(payload["env"], "1")
        self.assertTrue(payload["guard_active"])
        self.assertTrue(payload["blocking_enabled"])
        self.assertTrue(payload["native_dialogs_disabled"])
        self.assertTrue(payload["open_result"])
        self.assertEqual(payload["request_count"], 1)
        self.assertEqual(payload["first_via"], "external_launch.open_external_url")
        self.assertTrue(payload["first_blocked"])
        self.assertTrue(str(payload["first_target"]).startswith("file:///tmp/external-launch-probe"))

    def test_unittest_discover_bootstraps_guard_for_top_level_gui_modules(self):
        repo_root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop(TEST_BLOCK_ENV_VAR, None)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_desktop_safety_probe.py",
                "-v",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            cwd=repo_root,
        )

        self.assertEqual(
            completed.returncode,
            0,
            msg=f"unittest discover probe failed:\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}",
        )

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

    def test_non_launcher_subprocess_is_not_blocked_or_recorded(self):
        result = subprocess.run(
            [sys.executable, "-c", 'print("ok")'],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "ok")
        self.assertEqual(get_recorded_external_launches(), ())

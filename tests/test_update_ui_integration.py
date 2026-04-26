import unittest
from types import SimpleNamespace
from unittest import mock

from isrc_manager.update_checker import ReleaseManifest, UpdateCheckResult, UpdateCheckStatus

try:
    import ISRC_manager as app_module
except Exception as exc:  # pragma: no cover - environment-specific fallback
    app_module = None
    APP_IMPORT_ERROR = exc
else:
    APP_IMPORT_ERROR = None


def _manifest_mapping(version="3.3.1", **overrides):
    tag = f"v{version}"
    payload = {
        "version": version,
        "released_at": "2026-04-26",
        "summary": "A focused update summary.",
        "release_notes_url": (
            "https://github.com/cosmowyn/ISRC-Catalog-Manager/" f"blob/main/docs/releases/{tag}.md"
        ),
        "assets": {
            "windows": {
                "name": f"ISRCManager-{tag}-windows-x64.zip",
                "url": (
                    "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                    f"releases/download/{tag}/ISRCManager-{tag}-windows-x64.zip"
                ),
                "sha256": "a" * 64,
            },
            "macos": {
                "name": f"ISRCManager-{tag}-macos-arm64.zip",
                "url": (
                    "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                    f"releases/download/{tag}/ISRCManager-{tag}-macos-arm64.zip"
                ),
                "sha256": "b" * 64,
            },
            "linux": {
                "name": f"ISRCManager-{tag}-linux-x64.tar.gz",
                "url": (
                    "https://github.com/cosmowyn/ISRC-Catalog-Manager/"
                    f"releases/download/{tag}/ISRCManager-{tag}-linux-x64.tar.gz"
                ),
                "sha256": "c" * 64,
            },
        },
    }
    payload.update(overrides)
    return payload


class UpdateUiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if app_module is None:
            raise unittest.SkipTest(f"ISRC_manager import unavailable: {APP_IMPORT_ERROR}")

    def test_post_ready_tasks_schedule_startup_update_check(self):
        calls = []
        fake_app = SimpleNamespace(
            _update_add_data_generated_fields=lambda: calls.append("generated-fields"),
            _schedule_owner_party_bootstrap=lambda: calls.append("owner-bootstrap"),
            _offer_settings_on_first_launch_if_pending=lambda: calls.append("first-launch"),
            _schedule_startup_update_check=lambda: calls.append("update-check"),
        )

        app_module.App._run_post_ready_startup_tasks(fake_app)

        self.assertEqual(
            calls,
            ["generated-fields", "owner-bootstrap", "first-launch", "update-check"],
        )

    def test_startup_update_check_uses_non_manual_path(self):
        start_check = mock.Mock()
        fake_app = SimpleNamespace(_start_update_check=start_check)

        app_module.App._run_startup_update_check(fake_app)

        start_check.assert_called_once_with(manual=False)

    def test_start_update_check_suppresses_ignored_versions_only_on_startup(self):
        class _Context:
            def set_status(self, _message):
                return None

        class _Checker:
            def __init__(self):
                self.calls = []

            def check(self, current_version, *, ignored_version=None):
                self.calls.append((current_version, ignored_version))
                return UpdateCheckResult(
                    status=UpdateCheckStatus.CURRENT,
                    current_version=str(current_version),
                )

        class _FakeApp:
            def __init__(self):
                self.update_preferences = SimpleNamespace(
                    ignored_version=mock.Mock(return_value="3.3.0")
                )
                self.check_for_updates_action = SimpleNamespace(setEnabled=mock.Mock())
                self.checker = _Checker()
                self.submissions = []
                self.results = []

            def _app_version_text(self):
                return "3.2.0"

            def _build_update_checker(self):
                return self.checker

            def _handle_update_check_result(self, result, *, manual):
                self.results.append((result.status, manual))

            def _submit_background_task(self, **kwargs):
                self.submissions.append(kwargs)
                result = kwargs["task_fn"](_Context())
                kwargs["on_success"](result)
                kwargs["on_finished"]()
                return "task-id"

        fake_app = _FakeApp()

        app_module.App._start_update_check(fake_app, manual=False)
        app_module.App._start_update_check(fake_app, manual=True)

        self.assertEqual(
            fake_app.checker.calls,
            [("3.2.0", "3.3.0"), ("3.2.0", "")],
        )
        fake_app.update_preferences.ignored_version.assert_called_once_with()
        self.assertEqual(
            [
                (submission["show_dialog"], submission["requires_profile"])
                for submission in fake_app.submissions
            ],
            [(False, False), (True, False)],
        )
        self.assertEqual(
            fake_app.results,
            [
                (UpdateCheckStatus.CURRENT, False),
                (UpdateCheckStatus.CURRENT, True),
            ],
        )
        fake_app.check_for_updates_action.setEnabled.assert_has_calls(
            [mock.call(False), mock.call(True)]
        )

    def test_update_available_release_notes_button_uses_internal_dialog(self):
        manifest = ReleaseManifest.from_mapping(_manifest_mapping())
        result = UpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            current_version="3.3.0",
            latest_version="3.3.1",
            manifest=manifest,
        )
        shown_versions = []

        class _FakeMessageBox:
            Information = object()
            ActionRole = object()
            RejectRole = object()
            AcceptRole = object()

            def __init__(self, _parent):
                self.release_notes_button = None
                self.clicked_button = None

            def setWindowTitle(self, _title):
                return None

            def setIcon(self, _icon):
                return None

            def setText(self, _text):
                return None

            def addButton(self, text, _role):
                button = object()
                if text == "Release Notes":
                    self.release_notes_button = button
                return button

            def setDefaultButton(self, _button):
                return None

            def exec(self):
                self.clicked_button = self.release_notes_button

            def clickedButton(self):
                return self.clicked_button

        fake_app = SimpleNamespace(
            _show_update_release_notes=lambda release_manifest: shown_versions.append(
                release_manifest.version
            ),
            update_preferences=SimpleNamespace(set_ignored_version=mock.Mock()),
        )

        with (
            mock.patch.object(app_module, "QMessageBox", _FakeMessageBox),
            mock.patch.object(app_module.sys, "frozen", False, create=True),
        ):
            app_module.App._show_update_available_message(fake_app, result)

        self.assertEqual(shown_versions, ["3.3.1"])
        fake_app.update_preferences.set_ignored_version.assert_not_called()

    def test_update_available_download_button_starts_internal_installer(self):
        manifest = ReleaseManifest.from_mapping(_manifest_mapping())
        result = UpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            current_version="3.3.0",
            latest_version="3.3.1",
            manifest=manifest,
        )
        started_versions = []

        class _FakeMessageBox:
            Information = object()
            ActionRole = object()
            RejectRole = object()
            AcceptRole = object()

            def __init__(self, _parent):
                self.install_button = None
                self.clicked_button = None

            def setWindowTitle(self, _title):
                return None

            def setIcon(self, _icon):
                return None

            def setText(self, _text):
                return None

            def addButton(self, text, _role):
                button = object()
                if text == "Download and Install":
                    self.install_button = button
                return button

            def setDefaultButton(self, _button):
                return None

            def exec(self):
                self.clicked_button = self.install_button

            def clickedButton(self):
                return self.clicked_button

        fake_app = SimpleNamespace(
            _confirm_and_start_update_install=lambda release_manifest: started_versions.append(
                release_manifest.version
            ),
            update_preferences=SimpleNamespace(set_ignored_version=mock.Mock()),
        )

        with (
            mock.patch.object(app_module, "QMessageBox", _FakeMessageBox),
            mock.patch.object(app_module.sys, "frozen", True, create=True),
        ):
            app_module.App._show_update_available_message(fake_app, result)

        self.assertEqual(started_versions, ["3.3.1"])
        fake_app.update_preferences.set_ignored_version.assert_not_called()

    def test_update_available_download_button_is_offered_from_source_checkout(self):
        manifest = ReleaseManifest.from_mapping(_manifest_mapping())
        result = UpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            current_version="3.3.0",
            latest_version="3.3.1",
            manifest=manifest,
        )
        started_versions = []

        class _FakeMessageBox:
            Information = object()
            ActionRole = object()
            RejectRole = object()
            AcceptRole = object()

            def __init__(self, _parent):
                self.install_button = None
                self.clicked_button = None

            def setWindowTitle(self, _title):
                return None

            def setIcon(self, _icon):
                return None

            def setText(self, _text):
                return None

            def addButton(self, text, _role):
                button = object()
                if text == "Download and Install":
                    self.install_button = button
                return button

            def setDefaultButton(self, _button):
                return None

            def exec(self):
                self.clicked_button = self.install_button

            def clickedButton(self):
                return self.clicked_button

        fake_app = SimpleNamespace(
            _confirm_and_start_update_install=lambda release_manifest: started_versions.append(
                release_manifest.version
            ),
            update_preferences=SimpleNamespace(set_ignored_version=mock.Mock()),
        )

        with (
            mock.patch.object(app_module, "QMessageBox", _FakeMessageBox),
            mock.patch.object(app_module.sys, "frozen", False, create=True),
        ):
            app_module.App._show_update_available_message(fake_app, result)

        self.assertEqual(started_versions, ["3.3.1"])
        fake_app.update_preferences.set_ignored_version.assert_not_called()

    def test_release_notes_loader_fetches_markdown_inside_the_app(self):
        manifest = ReleaseManifest.from_mapping(
            _manifest_mapping(release_notes_url="https://example.com/releases/v3.3.1.md")
        )

        class _Context:
            def set_status(self, _message):
                return None

        class _FakeApp:
            def __init__(self):
                self.presented = []
                self.submissions = []

            def _submit_background_task(self, **kwargs):
                self.submissions.append(kwargs)
                result = kwargs["task_fn"](_Context())
                kwargs["on_success"](result)
                return "task-id"

            def _present_update_release_notes(self, release_manifest, markdown):
                self.presented.append((release_manifest.version, markdown))

        fake_app = _FakeApp()

        with mock.patch.object(
            app_module,
            "fetch_release_notes_text",
            return_value="# Release Notes\n\nLoaded internally.",
        ) as fetch:
            app_module.App._show_update_release_notes(fake_app, manifest)

        fetch.assert_called_once_with(
            "https://example.com/releases/v3.3.1.md",
            app_module.DEFAULT_RELEASE_NOTES_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            fake_app.presented,
            [("3.3.1", "# Release Notes\n\nLoaded internally.")],
        )
        self.assertEqual(
            [
                (
                    submission["kind"],
                    submission["requires_profile"],
                    submission["show_dialog"],
                )
                for submission in fake_app.submissions
            ],
            [("network", False, True)],
        )


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path
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
            _finalize_update_backup_handoff=lambda **_kwargs: calls.append("backup-cleanup"),
            _schedule_startup_update_check=lambda: calls.append("update-check"),
        )

        app_module.App._run_post_ready_startup_tasks(fake_app)

        self.assertEqual(
            calls,
            [
                "generated-fields",
                "owner-bootstrap",
                "first-launch",
                "backup-cleanup",
                "update-check",
            ],
        )

    def test_update_backup_handoff_cleanup_logs_failure(self):
        log_events = []
        fake_app = SimpleNamespace(
            _log_event=lambda *args, **kwargs: log_events.append((args, kwargs))
        )

        with mock.patch.object(
            app_module,
            "cleanup_ready_update_backup",
            side_effect=OSError("delete blocked"),
        ):
            app_module.App._cleanup_ready_update_backup_handoff(fake_app, phase="startup")

        self.assertEqual(log_events[0][0][0], "updates.backup_cleanup_failed")
        self.assertEqual(log_events[0][1]["phase"], "startup")
        self.assertIn("delete blocked", log_events[0][1]["error"])

    def test_update_backup_handoff_is_marked_ready_only_after_startup(self):
        fake_app = SimpleNamespace(_startup_ready_emitted=False, _log_event=mock.Mock())

        with mock.patch.object(app_module, "mark_update_backup_ready_for_deletion") as mark_ready:
            app_module.App._finalize_update_backup_handoff(fake_app, phase="startup-ready")

        mark_ready.assert_not_called()

    def test_update_backup_handoff_ready_close_runs_cleanup(self):
        finalize = mock.Mock()
        fake_app = SimpleNamespace(_finalize_update_backup_handoff=finalize)

        app_module.App._mark_update_backup_handoff_ready_on_close(fake_app)

        finalize.assert_called_once_with(phase="close")

    def test_update_backup_handoff_close_defers_cleanup_while_helper_installs(self):
        finalize = mock.Mock()
        log_events = []
        fake_app = SimpleNamespace(
            _update_install_handoff_in_progress=True,
            _finalize_update_backup_handoff=finalize,
            _log_event=lambda *args, **kwargs: log_events.append((args, kwargs)),
        )

        app_module.App._mark_update_backup_handoff_ready_on_close(fake_app)

        finalize.assert_not_called()
        self.assertEqual(log_events[0][0][0], "updates.cache_cleanup_deferred")
        self.assertEqual(log_events[0][1]["phase"], "close")

    def test_launch_prepared_update_marks_close_as_update_handoff(self):
        information_messages = []
        log_events = []
        quit_calls = []

        class _FakeMessageBox:
            @staticmethod
            def information(_parent, title, text):
                information_messages.append((title, text))

        class _FakeApplication:
            def quit(self):
                quit_calls.append("quit")

        fake_app = SimpleNamespace(
            _is_closing=False,
            _update_install_handoff_in_progress=False,
            _log_event=lambda *args, **kwargs: log_events.append((args, kwargs)),
        )
        plan = app_module.UpdateInstallPlan(
            helper_command=("/tmp/helper", app_module.HELPER_MODE_ARGUMENT),
            target_path=Path("/Applications/Music Catalog Manager.app"),
            replacement_path=Path("/tmp/update-workspace/staging/Music Catalog Manager.app"),
            backup_path=Path("/Applications/Music Catalog Manager.app.backup-before-v3.9.2"),
            handoff_path=Path("/tmp/update-workspace/update_backup_handoff.json"),
            restart_command=("/usr/bin/open", "/Applications/Music Catalog Manager.app"),
            log_path=Path("/tmp/update-workspace/install.log"),
            expected_version="3.9.2",
        )

        with (
            mock.patch.object(app_module, "QMessageBox", _FakeMessageBox),
            mock.patch.object(app_module, "launch_update_helper") as launch_helper,
            mock.patch.object(app_module.QApplication, "instance", return_value=_FakeApplication()),
            mock.patch.object(
                app_module.QTimer,
                "singleShot",
                side_effect=lambda _delay, callback: callback(),
            ),
        ):
            app_module.App._launch_prepared_update(fake_app, plan)

        launch_helper.assert_called_once_with(plan.helper_command)
        self.assertTrue(fake_app._update_install_handoff_in_progress)
        self.assertTrue(fake_app._is_closing)
        self.assertEqual(quit_calls, ["quit"])
        self.assertEqual(information_messages[0][0], "Installing Update")
        self.assertEqual(log_events[0][0][0], "updates.helper_launched")

    def test_update_backup_handoff_startup_ready_runs_cleanup(self):
        cleanup = mock.Mock()
        fake_app = SimpleNamespace(
            _startup_ready_emitted=True,
            _cleanup_ready_update_backup_handoff=cleanup,
            _cleanup_legacy_update_backup_siblings=mock.Mock(),
            _cleanup_update_cache_artifacts=mock.Mock(),
        )

        with mock.patch.object(
            app_module,
            "mark_update_backup_ready_for_deletion",
            return_value={"status": "ready_for_deletion"},
        ) as mark_ready:
            app_module.App._finalize_update_backup_handoff(fake_app, phase="startup-ready")

        mark_ready.assert_called_once_with()
        cleanup.assert_called_once_with(phase="startup-ready")
        fake_app._cleanup_legacy_update_backup_siblings.assert_called_once_with()
        fake_app._cleanup_update_cache_artifacts.assert_called_once_with()

    def test_legacy_update_backup_cleanup_removes_packaged_backup_siblings(self):
        log_events = []
        fake_app = SimpleNamespace(
            _app_version_text=lambda: "3.6.9",
            _log_event=lambda *args, **kwargs: log_events.append((args, kwargs)),
        )
        installed_target = Path("/Applications/Music Catalog Manager.app")
        removed_backup = Path(
            "/Applications/ISRCManager-3.6.8-macos.app.backup-before-v3.6.9-20260427"
        )

        with (
            mock.patch.object(app_module.sys, "frozen", True, create=True),
            mock.patch.object(
                app_module,
                "resolve_installed_target_path",
                return_value=installed_target,
            ) as resolve_target,
            mock.patch.object(
                app_module,
                "cleanup_update_backup_siblings",
                return_value=[removed_backup],
            ) as cleanup_siblings,
            mock.patch.object(
                app_module, "cleanup_legacy_update_backups_for_version"
            ) as cleanup_legacy,
        ):
            app_module.App._cleanup_legacy_update_backup_siblings(fake_app)

        resolve_target.assert_called_once_with()
        cleanup_siblings.assert_called_once_with(installed_target)
        cleanup_legacy.assert_not_called()
        self.assertEqual(log_events[0][0][0], "updates.legacy_backup_cleanup")
        self.assertEqual(log_events[0][1]["count"], 1)

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

    def test_release_notes_dialog_update_button_continues_to_installer(self):
        manifest = ReleaseManifest.from_mapping(_manifest_mapping())
        started_versions = []
        dialog_kwargs = []

        class _FakeReleaseNotesDialog:
            def __init__(self, **kwargs):
                dialog_kwargs.append(kwargs)

            def exec(self):
                return None

            def install_requested(self):
                return True

        fake_app = SimpleNamespace(
            _confirm_and_start_update_install=lambda release_manifest: started_versions.append(
                release_manifest.version
            )
        )

        with mock.patch.object(app_module, "ReleaseNotesDialog", _FakeReleaseNotesDialog):
            app_module.App._present_update_release_notes(fake_app, manifest, "# Notes")

        self.assertEqual(started_versions, ["3.3.1"])
        self.assertEqual(dialog_kwargs[0]["release_notes_markdown"], "# Notes")
        self.assertTrue(dialog_kwargs[0]["allow_update_install"])

    def test_install_update_prepare_error_surfaces_specific_failure_message(self):
        manifest = ReleaseManifest.from_mapping(_manifest_mapping())
        warnings = []
        log_events = []

        class _FakeMessageBox:
            @staticmethod
            def warning(_parent, title, text):
                warnings.append((title, text))

            @staticmethod
            def information(_parent, title, text):
                raise AssertionError(f"Unexpected information dialog: {title}: {text}")

        class _FakeApp:
            def _submit_background_task(self, **kwargs):
                kwargs["on_error"](
                    app_module.TaskFailure(
                        message="Automatic updates cannot replace an app running from macOS App Translocation.",
                        traceback_text="",
                    )
                )
                return "task-id"

            def _log_event(self, *args, **kwargs):
                log_events.append((args, kwargs))

        with (
            mock.patch.object(app_module, "QMessageBox", _FakeMessageBox),
            mock.patch.object(app_module, "detect_platform_key", return_value="macos"),
            mock.patch.object(
                app_module,
                "resolve_installed_target_path",
                return_value=Path("/Applications/ISRCManager.app"),
            ),
            mock.patch.object(app_module, "validate_install_target_is_replaceable"),
            mock.patch.object(
                app_module,
                "update_workspace_root",
                return_value=Path("/tmp/isrc-updates/v3.3.1-macos"),
            ),
        ):
            app_module.App._start_update_install(_FakeApp(), manifest)

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0][0], "Install Update")
        self.assertIn("App Translocation", warnings[0][1])
        self.assertNotIn("Check your internet connection", warnings[0][1])
        self.assertEqual(log_events[0][1]["error"], warnings[0][1].split("\n\n", 1)[1])

    def test_install_update_task_passes_cancellation_callback_to_installer_pipeline(self):
        manifest = ReleaseManifest.from_mapping(_manifest_mapping())
        captured = {}

        class _Context:
            def __init__(self):
                self.cancel_checks = 0
                self.statuses = []

            def is_cancelled(self):
                self.cancel_checks += 1
                return False

            def raise_if_cancelled(self):
                self.is_cancelled()

            def report_progress(self, *_args):
                return None

            def set_status(self, message):
                self.statuses.append(message)

        class _FakeApp:
            def _submit_background_task(self, **kwargs):
                ctx = _Context()
                captured["context"] = ctx
                kwargs["task_fn"](ctx)
                return "task-id"

        def _download(_asset, _destination, **kwargs):
            captured["download_cancel"] = kwargs["is_cancelled"]
            kwargs["is_cancelled"]()
            return SimpleNamespace(package_path=Path("/tmp/update.zip"))

        def _prepare(_manifest, _package_path, **kwargs):
            captured["prepare_cancel"] = kwargs["is_cancelled"]
            kwargs["is_cancelled"]()
            return object()

        with (
            mock.patch.object(app_module, "detect_platform_key", return_value="macos"),
            mock.patch.object(
                app_module,
                "resolve_installed_target_path",
                return_value=Path("/Applications/ISRCManager.app"),
            ),
            mock.patch.object(app_module, "validate_install_target_is_replaceable"),
            mock.patch.object(
                app_module,
                "update_workspace_root",
                return_value=Path("/tmp/isrc-updates/v3.3.1-macos"),
            ),
            mock.patch.object(app_module, "download_update_asset", side_effect=_download),
            mock.patch.object(app_module, "prepare_update_install_plan", side_effect=_prepare),
        ):
            app_module.App._start_update_install(_FakeApp(), manifest)

        ctx = captured["context"]
        self.assertIs(captured["download_cancel"].__self__, ctx)
        self.assertIs(captured["prepare_cancel"].__self__, ctx)
        self.assertGreaterEqual(ctx.cancel_checks, 4)
        self.assertEqual(
            ctx.statuses,
            ["Downloading update package...", "Preparing update installer..."],
        )

    def test_install_update_preflight_failure_stops_before_download_task(self):
        manifest = ReleaseManifest.from_mapping(_manifest_mapping())
        information_messages = []

        class _FakeMessageBox:
            @staticmethod
            def information(_parent, title, text):
                information_messages.append((title, text))

        class _FakeApp:
            def _submit_background_task(self, **_kwargs):
                raise AssertionError("Download task should not start after preflight failure.")

        with (
            mock.patch.object(app_module, "QMessageBox", _FakeMessageBox),
            mock.patch.object(app_module, "detect_platform_key", return_value="macos"),
            mock.patch.object(
                app_module,
                "resolve_installed_target_path",
                return_value=Path("/private/var/folders/example/AppTranslocation/UUID/d/App.app"),
            ),
            mock.patch.object(
                app_module,
                "validate_install_target_is_replaceable",
                side_effect=app_module.UpdateInstallerError(
                    "Automatic updates cannot replace an app running from macOS App Translocation."
                ),
            ),
        ):
            app_module.App._start_update_install(_FakeApp(), manifest)

        self.assertEqual(len(information_messages), 1)
        self.assertEqual(information_messages[0][0], "Install Update")
        self.assertIn("App Translocation", information_messages[0][1])


if __name__ == "__main__":
    unittest.main()

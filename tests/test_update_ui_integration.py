import unittest
from types import SimpleNamespace
from unittest import mock

from isrc_manager.update_checker import UpdateCheckResult, UpdateCheckStatus

try:
    import ISRC_manager as app_module
except Exception as exc:  # pragma: no cover - environment-specific fallback
    app_module = None
    APP_IMPORT_ERROR = exc
else:
    APP_IMPORT_ERROR = None


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


if __name__ == "__main__":
    unittest.main()

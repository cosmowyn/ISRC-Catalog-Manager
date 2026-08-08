from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from PySide6.QtWidgets import QPushButton, QWidget

import isrc_manager.credential_reset_controller as controller_module
from isrc_manager.credential_reset import CredentialResetResult
from isrc_manager.credential_reset_controller import CredentialResetController
from tests.qt_test_helpers import require_qapplication


class _TaskContext:
    def __init__(self) -> None:
        self.statuses: list[str] = []

    def set_status(self, message: str) -> None:
        self.statuses.append(message)


def _owner() -> QWidget:
    require_qapplication()
    owner = QWidget()
    owner.reset_stored_credentials_button = QPushButton(owner)  # type: ignore[attr-defined]
    owner.reset_stored_credentials_button.setEnabled(True)  # type: ignore[attr-defined]
    owner.soundcloud_panel = mock.Mock()  # type: ignore[attr-defined]
    return owner


def _app() -> SimpleNamespace:
    app = SimpleNamespace(
        _log_event=mock.Mock(),
        _play_notice_sound=mock.Mock(),
        _play_warning_sound=mock.Mock(),
    )
    app.submissions = []

    def _submit_background_task(**kwargs):
        app.submissions.append(kwargs)
        return "credential-reset-task"

    app._submit_background_task = _submit_background_task
    return app


def test_manual_reset_runs_as_exclusive_background_task_and_reports_success(
    monkeypatch,
) -> None:
    app = _app()
    owner = _owner()
    result = CredentialResetResult(database_items_deleted=2, soundcloud_items_deleted=3)
    service = mock.Mock(supported=True, reset=mock.Mock(return_value=result))
    snapshot = object()
    monkeypatch.setattr(controller_module, "soundcloud_settings_snapshot", lambda _app: snapshot)
    information = mock.Mock()
    monkeypatch.setattr(controller_module.QMessageBox, "information", information)

    controller = CredentialResetController(app, service=service)

    assert controller.start(owner) == "credential-reset-task"
    assert owner.reset_stored_credentials_button.isEnabled() is False  # type: ignore[attr-defined]
    service.reset.assert_not_called()
    submission = app.submissions[0]
    assert submission["kind"] == "exclusive"
    assert submission["unique_key"] == "security.credentials_reset"
    assert submission["requires_profile"] is False
    assert submission["cancellable"] is False
    assert submission["owner"] is owner

    context = _TaskContext()
    assert submission["task_fn"](context) is result
    assert context.statuses == ["Removing only this app's macOS Keychain credentials..."]
    service.reset.assert_called_once_with()

    submission["on_success"](result)
    owner.soundcloud_panel.set_snapshot.assert_called_once_with(snapshot)  # type: ignore[attr-defined]
    app._play_notice_sound.assert_called_once_with()
    app._log_event.assert_called_once_with(
        "security.credentials_reset",
        "App-owned macOS Keychain credentials reset",
        deleted_items=5,
    )
    assert "Other Keychain passwords were not changed" in information.call_args.args[2]
    assert "remote SoundCloud access was not revoked" in information.call_args.args[2]

    submission["on_finished"]()
    assert owner.reset_stored_credentials_button.isEnabled() is True  # type: ignore[attr-defined]


def test_reset_error_is_truthful_about_partial_deletion_and_reenables_button(
    monkeypatch,
) -> None:
    app = _app()
    owner = _owner()
    service = mock.Mock(supported=True)
    critical = mock.Mock()
    monkeypatch.setattr(controller_module.QMessageBox, "critical", critical)

    controller = CredentialResetController(app, service=service)
    controller.start(owner)
    submission = app.submissions[0]

    submission["on_error"](
        SimpleNamespace(
            message=(
                "Application Keychain reset was incomplete after removing 2 app-owned "
                "credential item(s). isrc-catalog-manager.database: authorization was "
                "cancelled."
            )
        )
    )

    app._play_warning_sound.assert_called_once_with()
    assert "Some app-owned credentials may already have been removed" in critical.call_args.args[2]
    assert "outside this app's fixed allowlist" in critical.call_args.args[2]
    assert "after removing 2 app-owned credential item(s)" in critical.call_args.args[2]
    assert "authorization was cancelled" in critical.call_args.args[2]
    assert owner.reset_stored_credentials_button.isEnabled() is True  # type: ignore[attr-defined]


def test_reset_is_unavailable_without_supported_macos_service(monkeypatch) -> None:
    app = _app()
    owner = _owner()
    service = mock.Mock(supported=False)
    warning = mock.Mock()
    monkeypatch.setattr(controller_module.QMessageBox, "warning", warning)

    controller = CredentialResetController(app, service=service)

    assert controller.available is False
    assert controller.start(owner) is None
    assert app.submissions == []
    assert "/usr/bin/security" in warning.call_args.args[2]


def test_reset_never_runs_without_background_task_boundary(monkeypatch) -> None:
    app = _app()
    del app._submit_background_task
    owner = _owner()
    service = mock.Mock(supported=True)
    critical = mock.Mock()
    monkeypatch.setattr(controller_module.QMessageBox, "critical", critical)

    controller = CredentialResetController(app, service=service)

    assert controller.start(owner) is None
    service.reset.assert_not_called()
    assert "no credentials were changed" in critical.call_args.args[2]


def test_reset_recovers_when_background_task_submission_raises(monkeypatch) -> None:
    app = _app()
    app._submit_background_task = mock.Mock(side_effect=RuntimeError("task manager stopped"))
    owner = _owner()
    service = mock.Mock(supported=True)
    critical = mock.Mock()
    monkeypatch.setattr(controller_module.QMessageBox, "critical", critical)

    controller = CredentialResetController(app, service=service)

    assert controller.start(owner) is None
    service.reset.assert_not_called()
    assert owner.reset_stored_credentials_button.isEnabled() is True  # type: ignore[attr-defined]
    assert "no credentials were changed" in critical.call_args.args[2]

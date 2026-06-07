from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from isrc_manager import update_controller
from isrc_manager.update_checker import UpdateCheckResult, UpdateCheckStatus
from isrc_manager.update_installer import UpdateInstallerError, UpdateInstallPlan


class _MessageBox:
    def __init__(self) -> None:
        self.information_calls: list[tuple[object, str, str]] = []

    def information(self, parent: object, title: str, text: str) -> None:
        self.information_calls.append((parent, title, text))


class _RichMessageBox:
    Information = "information-icon"
    ActionRole = "action-role"
    RejectRole = "reject-role"
    AcceptRole = "accept-role"
    Yes = 1
    No = 2

    calls: list[tuple[str, str, str]] = []
    instances: list["_RichMessageBox"] = []
    next_clicked_text = "Later"
    next_question_reply = No

    def __init__(self, parent=None) -> None:
        self.parent = parent
        self.buttons = {}
        self.window_title = ""
        self.icon = None
        self.text = ""
        self.default_button = None
        self.exec_calls = 0
        self.__class__.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls.instances = []
        cls.next_clicked_text = "Later"
        cls.next_question_reply = cls.No

    @classmethod
    def information(cls, _parent: object, title: str, text: str) -> None:
        cls.calls.append(("information", title, text))

    @classmethod
    def warning(cls, _parent: object, title: str, text: str) -> None:
        cls.calls.append(("warning", title, text))

    @classmethod
    def critical(cls, _parent: object, title: str, text: str) -> None:
        cls.calls.append(("critical", title, text))

    @classmethod
    def question(cls, _parent, title, text, _buttons, _default):
        cls.calls.append(("question", title, text))
        return cls.next_question_reply

    def setWindowTitle(self, title: str) -> None:
        self.window_title = title

    def setIcon(self, icon) -> None:
        self.icon = icon

    def setText(self, text: str) -> None:
        self.text = text

    def addButton(self, text: str, role):
        button = SimpleNamespace(text=text, role=role)
        self.buttons[text] = button
        return button

    def setDefaultButton(self, button) -> None:
        self.default_button = button

    def exec(self) -> None:
        self.exec_calls += 1

    def clickedButton(self):
        return self.buttons.get(self.next_clicked_text)


class _EventApp:
    def __init__(self, tmp_path) -> None:
        self.storage_layout = SimpleNamespace(preferred_data_root=tmp_path)
        self.events: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self._startup_ready_emitted = True
        self._update_install_handoff_in_progress = False

    def _app_version_text(self) -> str:
        return "1.2.3"

    def _log_event(self, *args, **kwargs) -> None:
        self.events.append((args, kwargs))


def test_cleanup_legacy_update_backup_siblings_branches(monkeypatch, tmp_path) -> None:
    app = _EventApp(tmp_path)
    removed = [tmp_path / "old-backup"]

    monkeypatch.setattr(update_controller, "_root_sys", lambda: SimpleNamespace(frozen=False))
    update_controller._cleanup_legacy_update_backup_siblings(app)
    assert app.events == []

    monkeypatch.setattr(update_controller, "_root_sys", lambda: SimpleNamespace(frozen=True))
    monkeypatch.setattr(
        update_controller,
        "_resolve_installed_target_path",
        lambda: tmp_path / "app",
    )
    monkeypatch.setattr(
        update_controller,
        "_cleanup_update_backup_siblings",
        lambda _target: removed,
    )

    update_controller._cleanup_legacy_update_backup_siblings(app)

    assert app.events[-1][0][:2] == (
        "updates.legacy_backup_cleanup",
        "Removed legacy update backup(s)",
    )
    assert app.events[-1][1]["level"] == logging.INFO
    assert app.events[-1][1]["paths"] == [str(removed[0])]

    app.events.clear()
    monkeypatch.setattr(update_controller, "_cleanup_update_backup_siblings", lambda _target: [])
    monkeypatch.setattr(
        update_controller,
        "_cleanup_legacy_update_backups_for_version",
        lambda _target, _version: removed,
    )
    update_controller._cleanup_legacy_update_backup_siblings(app)
    assert app.events[-1][1]["count"] == 1

    app.events.clear()
    monkeypatch.setattr(
        update_controller,
        "_resolve_installed_target_path",
        mock.Mock(side_effect=RuntimeError("no target")),
    )
    update_controller._cleanup_legacy_update_backup_siblings(app)
    assert app.events[-1][0][0] == "updates.legacy_backup_cleanup_failed"
    assert app.events[-1][1]["error"] == "no target"


def test_cleanup_update_cache_artifacts_branches(monkeypatch, tmp_path) -> None:
    app = _EventApp(tmp_path)
    removed = [tmp_path / "updates" / "asset.zip"]

    monkeypatch.setattr(update_controller, "_root_sys", lambda: SimpleNamespace(frozen=False))
    update_controller._cleanup_update_cache_artifacts(app)
    assert app.events == []

    monkeypatch.setattr(update_controller, "_root_sys", lambda: SimpleNamespace(frozen=True))
    helper = mock.Mock(return_value=removed)
    monkeypatch.setattr(update_controller, "_cleanup_update_cache_artifacts_helper", helper)
    update_controller._cleanup_update_cache_artifacts(app)

    helper.assert_called_once_with(update_root=tmp_path / "updates")
    assert app.events[-1][0][0] == "updates.cache_cleanup"
    assert app.events[-1][1]["paths"] == [str(removed[0])]

    app.events.clear()
    helper.side_effect = RuntimeError("cleanup failed")
    update_controller._cleanup_update_cache_artifacts(app)
    assert app.events[-1][0][0] == "updates.cache_cleanup_failed"
    assert app.events[-1][1]["level"] == logging.WARNING


def test_finalize_update_backup_handoff_and_close_defer(monkeypatch, tmp_path) -> None:
    app = _EventApp(tmp_path)
    calls: list[tuple[str, str | None]] = []
    app._cleanup_ready_update_backup_handoff = lambda *, phase: calls.append(("ready", phase))
    app._cleanup_legacy_update_backup_siblings = lambda: calls.append(("legacy", None))
    app._cleanup_update_cache_artifacts = lambda: calls.append(("cache", None))

    app._startup_ready_emitted = False
    update_controller._finalize_update_backup_handoff(app, phase="startup")
    assert calls == []

    app._startup_ready_emitted = True
    monkeypatch.setattr(
        update_controller,
        "_mark_update_backup_ready_for_deletion",
        mock.Mock(side_effect=RuntimeError("handoff failed")),
    )
    update_controller._finalize_update_backup_handoff(app, phase="startup")
    assert app.events[-1][0][0] == "updates.backup_handoff_ready_failed"
    assert calls == []

    app.events.clear()
    monkeypatch.setattr(
        update_controller,
        "_mark_update_backup_ready_for_deletion",
        mock.Mock(return_value={"ready": True}),
    )
    update_controller._finalize_update_backup_handoff(app, phase="startup")
    assert calls == [("ready", "startup"), ("legacy", None), ("cache", None)]

    app._update_install_handoff_in_progress = True
    app._finalize_update_backup_handoff = lambda *, phase: calls.append(("finalize", phase))
    update_controller._mark_update_backup_handoff_ready_on_close(app)
    assert app.events[-1][0][0] == "updates.cache_cleanup_deferred"


def test_startup_update_check_suppresses_only_shutdown_runtime_errors() -> None:
    start = mock.Mock()
    app = SimpleNamespace(_is_closing=True, _start_update_check=start)

    update_controller._run_startup_update_check(app)
    start.assert_not_called()

    app._is_closing = False
    app._start_update_check = mock.Mock(
        side_effect=RuntimeError("Internal C++ object already deleted")
    )
    update_controller._run_startup_update_check(app)

    app._start_update_check = mock.Mock(side_effect=RuntimeError("network task failed"))
    with pytest.raises(RuntimeError, match="network task failed"):
        update_controller._run_startup_update_check(app)


def test_handle_update_check_result_routes_statuses(monkeypatch) -> None:
    messages = _MessageBox()
    monkeypatch.setattr(update_controller, "_message_box", lambda: messages)
    shown: list[UpdateCheckResult] = []
    events: list[tuple[tuple[object, ...], dict[str, object]]] = []
    app = SimpleNamespace(
        _show_update_available_message=lambda result: shown.append(result),
        _log_event=lambda *args, **kwargs: events.append((args, kwargs)),
    )
    available = UpdateCheckResult(
        status=UpdateCheckStatus.UPDATE_AVAILABLE,
        current_version="1.0.0",
        latest_version="2.0.0",
    )

    update_controller._handle_update_check_result(app, available, manual=True)
    update_controller._handle_update_check_result(
        app,
        UpdateCheckResult(status=UpdateCheckStatus.CURRENT, current_version="2.0.0"),
        manual=True,
    )
    update_controller._handle_update_check_result(
        app,
        UpdateCheckResult(status=UpdateCheckStatus.IGNORED, current_version="1.0.0"),
        manual=False,
    )
    update_controller._handle_update_check_result(
        app,
        UpdateCheckResult(status=UpdateCheckStatus.FAILED, current_version="1.0.0"),
        manual=True,
    )
    update_controller._handle_update_check_result(
        app,
        UpdateCheckResult(status=UpdateCheckStatus.FAILED, current_version="1.0.0"),
        manual=False,
    )

    assert shown == [available]
    assert [call[1] for call in messages.information_calls] == [
        "Check for Updates",
        "Check for Updates",
    ]
    assert "latest available version" in messages.information_calls[0][2]
    assert "unavailable right now" in messages.information_calls[1][2]
    assert events[-1][0][0] == "updates.check_unavailable"


def test_start_update_check_handles_manual_task_edges(monkeypatch) -> None:
    monkeypatch.setattr(update_controller, "_root_sys", lambda: SimpleNamespace(frozen=True))
    messages = _MessageBox()
    monkeypatch.setattr(update_controller, "_message_box", lambda: messages)
    action = SimpleNamespace(setEnabled=mock.Mock())
    statuses: list[str] = []

    class _Context:
        def set_status(self, text: str) -> None:
            statuses.append(text)

    checker = SimpleNamespace(check=mock.Mock(return_value="not-a-result"))
    submissions: list[dict[str, object]] = []

    def _submit_background_task(**kwargs):
        submissions.append(kwargs)
        result = kwargs["task_fn"](_Context())
        kwargs["on_success"](result)
        kwargs["on_error"](SimpleNamespace(message="offline"))
        kwargs["on_finished"]()
        return "task-id"

    app = SimpleNamespace(
        check_for_updates_action=action,
        update_preferences=SimpleNamespace(ignored_version=mock.Mock(return_value="9.9.9")),
        _app_version_text=lambda: "1.2.3",
        _build_update_checker=lambda: checker,
        _submit_background_task=_submit_background_task,
    )

    update_controller._start_update_check(app, manual=True)

    action.setEnabled.assert_has_calls([mock.call(False), mock.call(True)])
    checker.check.assert_called_once_with("1.2.3", ignored_version="")
    assert statuses == ["Checking for updates..."]
    assert [call[1] for call in messages.information_calls] == [
        "Check for Updates",
        "Check for Updates",
    ]
    assert submissions[0]["unique_key"] == "updates.check"
    assert submissions[0]["show_dialog"] is True

    action.setEnabled.reset_mock()
    app._submit_background_task = mock.Mock(return_value=None)
    update_controller._start_update_check(app, manual=True)
    action.setEnabled.assert_has_calls([mock.call(False), mock.call(True)])


def test_start_update_check_logs_automatic_failures(monkeypatch) -> None:
    monkeypatch.setattr(update_controller, "_root_sys", lambda: SimpleNamespace(frozen=True))
    events: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _submit_background_task(**kwargs):
        kwargs["on_error"](SimpleNamespace(message="offline"))
        kwargs["on_finished"]()
        return "task-id"

    app = SimpleNamespace(
        check_for_updates_action=SimpleNamespace(setEnabled=mock.Mock()),
        update_preferences=SimpleNamespace(ignored_version=mock.Mock(return_value="1.2.2")),
        _app_version_text=lambda: "1.2.3",
        _build_update_checker=mock.Mock(),
        _submit_background_task=_submit_background_task,
        _log_event=lambda *args, **kwargs: events.append((args, kwargs)),
    )

    update_controller._start_update_check(app, manual=False)

    app.update_preferences.ignored_version.assert_called_once_with()
    app.check_for_updates_action.setEnabled.assert_not_called()
    assert events == [
        (
            ("updates.check_failed", "Startup update check failed"),
            {"level": logging.INFO, "error": "offline"},
        )
    ]


def test_start_update_check_skips_source_builds(monkeypatch) -> None:
    monkeypatch.setattr(update_controller, "_root_sys", lambda: SimpleNamespace(frozen=False))
    action = SimpleNamespace(setEnabled=mock.Mock())
    app = SimpleNamespace(
        check_for_updates_action=action,
        update_preferences=SimpleNamespace(ignored_version=mock.Mock(return_value="1.2.2")),
        _app_version_text=mock.Mock(return_value="1.2.3"),
        _build_update_checker=mock.Mock(),
        _submit_background_task=mock.Mock(return_value="task-id"),
    )

    update_controller._start_update_check(app, manual=False)
    update_controller._start_update_check(app, manual=True)

    app._submit_background_task.assert_not_called()
    app._build_update_checker.assert_not_called()
    app._app_version_text.assert_not_called()
    app.update_preferences.ignored_version.assert_not_called()
    action.setEnabled.assert_not_called()


def test_update_controller_root_wrappers_and_schedule(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def fake_root_attr(name, fallback):
        def _wrapped(*args, **kwargs):
            calls.append((name, args, kwargs))
            if name == "UpdateChecker":
                return "checker"
            if name == "cleanup_update_cache_artifacts":
                return ["cache"]
            if name == "cleanup_legacy_update_backups_for_version":
                return ["legacy"]
            return fallback(*args, **kwargs)

        return _wrapped

    monkeypatch.setattr(update_controller, "_root_attr", fake_root_attr)
    monkeypatch.setattr(
        update_controller.QTimer,
        "singleShot",
        lambda delay, callback: calls.append(("singleShot", (delay, callback), {})),
    )
    monkeypatch.setattr(update_controller, "UpdateChecker", lambda: "checker")
    app = SimpleNamespace(
        _run_startup_update_check=mock.Mock(),
        _start_update_check=mock.Mock(),
    )

    assert update_controller._cleanup_legacy_update_backups_for_version(
        tmp_path / "target", "1.2.3"
    ) == ["legacy"]
    assert update_controller._cleanup_update_cache_artifacts_helper(
        update_root=tmp_path / "updates"
    ) == ["cache"]
    update_controller._schedule_startup_update_check(app)
    update_controller.check_for_updates(app)
    checker = update_controller._build_update_checker(app)

    assert checker == "checker"
    assert calls[-1][0] == "singleShot"
    assert calls[-1][1][0] == 1000
    app._start_update_check.assert_called_once_with(manual=True)


def test_show_update_available_message_handles_missing_manifest_and_button_paths(
    monkeypatch,
) -> None:
    _RichMessageBox.reset()
    monkeypatch.setattr(update_controller, "_message_box", lambda: _RichMessageBox)
    monkeypatch.setattr(
        update_controller, "_select_platform_asset", mock.Mock(return_value=object())
    )
    status_messages: list[tuple[str, int]] = []
    app = SimpleNamespace(
        update_preferences=SimpleNamespace(set_ignored_version=mock.Mock()),
        statusBar=lambda: SimpleNamespace(
            showMessage=lambda text, timeout: status_messages.append((text, timeout))
        ),
        _show_update_release_notes=mock.Mock(),
        _confirm_and_start_update_install=mock.Mock(),
    )

    update_controller._show_update_available_message(
        app,
        UpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            current_version="1.0.0",
            manifest=None,
        ),
    )
    assert _RichMessageBox.instances == []

    manifest = SimpleNamespace(
        version="2.0.0",
        summary="Safer updates.",
        release_notes_url="https://example.com/release-notes.md",
    )
    _RichMessageBox.next_clicked_text = "Ignore This Version"
    update_controller._show_update_available_message(
        app,
        UpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            current_version="1.0.0",
            manifest=manifest,
        ),
    )

    app.update_preferences.set_ignored_version.assert_called_once_with("2.0.0")
    assert status_messages == [("Ignoring update 2.0.0.", 5000)]

    _RichMessageBox.next_clicked_text = "Release Notes"
    update_controller._show_update_available_message(
        app,
        UpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            current_version="1.0.0",
            manifest=manifest,
        ),
    )
    app._show_update_release_notes.assert_called_once_with(manifest)

    _RichMessageBox.next_clicked_text = "Download and Install"
    update_controller._show_update_available_message(
        app,
        UpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            current_version="1.0.0",
            manifest=manifest,
        ),
    )
    app._confirm_and_start_update_install.assert_called_once_with(manifest)

    monkeypatch.setattr(
        update_controller,
        "_select_platform_asset",
        mock.Mock(side_effect=UpdateInstallerError("no package")),
    )
    _RichMessageBox.next_clicked_text = "Later"
    update_controller._show_update_available_message(
        app,
        UpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            current_version="1.0.0",
            manifest=manifest,
        ),
    )
    assert (
        "Automatic installation is not available: no package" in _RichMessageBox.instances[-1].text
    )
    assert "Download and Install" not in _RichMessageBox.instances[-1].buttons


def test_confirm_update_install_respects_packaged_state_and_question_reply(monkeypatch) -> None:
    _RichMessageBox.reset()
    monkeypatch.setattr(update_controller, "_message_box", lambda: _RichMessageBox)
    app = SimpleNamespace(_start_update_install=mock.Mock())
    manifest = SimpleNamespace(version="2.0.0")

    monkeypatch.setattr(update_controller, "_root_sys", lambda: SimpleNamespace(frozen=False))
    update_controller._confirm_and_start_update_install(app, manifest)
    assert _RichMessageBox.calls[-1][0] == "information"
    app._start_update_install.assert_not_called()

    monkeypatch.setattr(update_controller, "_root_sys", lambda: SimpleNamespace(frozen=True))
    _RichMessageBox.next_question_reply = _RichMessageBox.No
    update_controller._confirm_and_start_update_install(app, manifest)
    app._start_update_install.assert_not_called()

    _RichMessageBox.next_question_reply = _RichMessageBox.Yes
    update_controller._confirm_and_start_update_install(app, manifest)
    app._start_update_install.assert_called_once_with(manifest)


def _update_plan(tmp_path: Path) -> UpdateInstallPlan:
    return UpdateInstallPlan(
        helper_command=("helper", "--install"),
        target_path=tmp_path / "app",
        replacement_path=tmp_path / "replacement",
        backup_path=tmp_path / "backup",
        handoff_path=tmp_path / "handoff.json",
        restart_command=("app",),
        log_path=tmp_path / "update.log",
        expected_version="2.0.0",
    )


def test_start_update_install_handles_preflight_task_callbacks_and_busy_task(
    monkeypatch,
    tmp_path,
) -> None:
    _RichMessageBox.reset()
    monkeypatch.setattr(update_controller, "_message_box", lambda: _RichMessageBox)
    manifest = SimpleNamespace(version="2.0.0")

    monkeypatch.setattr(
        update_controller,
        "_detect_platform_key",
        mock.Mock(side_effect=UpdateInstallerError("unsupported")),
    )
    update_controller._start_update_install(SimpleNamespace(), manifest)
    assert _RichMessageBox.calls[-1] == ("information", "Install Update", "unsupported")

    asset = SimpleNamespace(name="asset.zip")
    downloaded = SimpleNamespace(package_path=tmp_path / "asset.zip")
    plan = _update_plan(tmp_path)
    submissions: list[dict[str, object]] = []
    events: list[tuple[tuple[object, ...], dict[str, object]]] = []
    statuses: list[str] = []
    progress_calls: list[tuple[object, ...]] = []
    app = SimpleNamespace(
        _submit_background_task=lambda **kwargs: submissions.append(kwargs) or "task-id",
        _launch_prepared_update=mock.Mock(),
        _log_event=lambda *args, **kwargs: events.append((args, kwargs)),
    )
    monkeypatch.setattr(update_controller, "_detect_platform_key", mock.Mock(return_value="macos"))
    monkeypatch.setattr(update_controller, "_select_platform_asset", mock.Mock(return_value=asset))
    monkeypatch.setattr(update_controller, "_validate_install_target_is_replaceable", mock.Mock())
    monkeypatch.setattr(
        update_controller,
        "_resolve_installed_target_path",
        mock.Mock(return_value=tmp_path / "app"),
    )
    monkeypatch.setattr(
        update_controller,
        "_update_workspace_root",
        mock.Mock(return_value=tmp_path / "updates" / "v2"),
    )
    monkeypatch.setattr(
        update_controller, "_download_update_asset", mock.Mock(return_value=downloaded)
    )
    monkeypatch.setattr(
        update_controller, "_prepare_update_install_plan", mock.Mock(return_value=plan)
    )

    update_controller._start_update_install(app, manifest)

    assert submissions[0]["unique_key"] == "updates.install"
    ctx = SimpleNamespace(
        raise_if_cancelled=mock.Mock(),
        set_status=lambda text: statuses.append(text),
        report_progress=lambda *args: progress_calls.append(args),
        is_cancelled=lambda: False,
    )
    assert submissions[0]["task_fn"](ctx) is plan
    assert statuses == ["Downloading update package...", "Preparing update installer..."]

    submissions[0]["on_success"](plan)
    app._launch_prepared_update.assert_called_once_with(plan)

    submissions[0]["on_success"]("not-a-plan")
    assert _RichMessageBox.calls[-1][0] == "warning"

    submissions[0]["on_error"](SimpleNamespace(message=""))
    assert events[-1][0][0] == "updates.install_prepare_failed"
    assert "try again later" in _RichMessageBox.calls[-1][2]

    busy_app = SimpleNamespace(_submit_background_task=mock.Mock(return_value=None))
    update_controller._start_update_install(busy_app, manifest)
    assert _RichMessageBox.calls[-1] == (
        "information",
        "Install Update",
        "Another update task is already running.",
    )


def test_launch_prepared_update_reports_helper_failure_and_closes_without_qapplication(
    monkeypatch,
    tmp_path,
) -> None:
    _RichMessageBox.reset()
    monkeypatch.setattr(update_controller, "_message_box", lambda: _RichMessageBox)
    plan = _update_plan(tmp_path)
    events: list[tuple[tuple[object, ...], dict[str, object]]] = []
    app = SimpleNamespace(
        _log_event=lambda *args, **kwargs: events.append((args, kwargs)),
        close=mock.Mock(),
    )

    monkeypatch.setattr(
        update_controller,
        "_launch_update_helper",
        mock.Mock(side_effect=RuntimeError("launch failed")),
    )
    update_controller._launch_prepared_update(app, plan)
    assert events[-1][0][0] == "updates.helper_launch_failed"
    assert _RichMessageBox.calls[-1][0] == "critical"

    events.clear()
    monkeypatch.setattr(update_controller, "_launch_update_helper", mock.Mock())
    monkeypatch.setattr(update_controller.QApplication, "instance", lambda: None)
    update_controller._launch_prepared_update(app, plan)

    assert app._update_install_handoff_in_progress is True
    assert app._is_closing is True
    app.close.assert_called_once_with()
    assert events[-1][0][0] == "updates.helper_launched"


def test_release_notes_paths_cover_empty_url_task_error_busy_and_dialog_install(
    monkeypatch,
) -> None:
    manifest = SimpleNamespace(
        version="2.0.0",
        released_at="2026-06-07",
        summary="Release summary",
        release_notes_url="",
    )
    presented: list[tuple[object, str]] = []
    app = SimpleNamespace(
        _present_update_release_notes=lambda release_manifest, text: presented.append(
            (release_manifest, text)
        ),
        _submit_background_task=mock.Mock(return_value=None),
        _log_event=mock.Mock(),
    )

    update_controller._show_update_release_notes(app, manifest)
    assert presented == [(manifest, "")]

    manifest.release_notes_url = "https://example.com/notes.md"
    update_controller._show_update_release_notes(app, manifest)
    assert presented[-1] == (manifest, "")

    submissions: list[dict[str, object]] = []

    def _submit_background_task(**kwargs):
        submissions.append(kwargs)
        kwargs["on_error"](SimpleNamespace(message="offline"))
        return "task-id"

    app._submit_background_task = _submit_background_task
    update_controller._show_update_release_notes(app, manifest)
    assert app._log_event.call_args.args[0] == "updates.release_notes_unavailable"
    assert presented[-1] == (manifest, "")

    dialog_instances = []

    class _FakeReleaseNotesDialog:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.exec_calls = 0
            dialog_instances.append(self)

        def exec(self):
            self.exec_calls += 1

        def install_requested(self):
            return False

    monkeypatch.setattr(
        update_controller,
        "_root_attr",
        lambda name, fallback: (
            _FakeReleaseNotesDialog if name == "ReleaseNotesDialog" else fallback
        ),
    )
    monkeypatch.setattr(
        update_controller,
        "_select_platform_asset",
        mock.Mock(side_effect=UpdateInstallerError("no installer")),
    )
    app = SimpleNamespace(_confirm_and_start_update_install=mock.Mock())

    update_controller._present_update_release_notes(app, manifest, "## Notes")

    assert dialog_instances[-1].kwargs["release_notes_markdown"] == "## Notes"
    assert dialog_instances[-1].kwargs["allow_update_install"] is False
    app._confirm_and_start_update_install.assert_not_called()

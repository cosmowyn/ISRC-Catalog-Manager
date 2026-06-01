from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest import mock

import pytest

from isrc_manager import update_controller
from isrc_manager.update_checker import UpdateCheckResult, UpdateCheckStatus


class _MessageBox:
    def __init__(self) -> None:
        self.information_calls: list[tuple[object, str, str]] = []

    def information(self, parent: object, title: str, text: str) -> None:
        self.information_calls.append((parent, title, text))


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

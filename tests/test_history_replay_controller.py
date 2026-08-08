from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from isrc_manager.history import replay_controller


class _ProgressContext:
    def __init__(self) -> None:
        self.updates: list[tuple[int | None, int | None, str | None]] = []

    def report_progress(self, value=None, maximum=None, message=None) -> None:
        self.updates.append((value, maximum, message))


class _Host:
    def __init__(self, tmp_path: Path, *, direction: str = "redo") -> None:
        self.current_db_path = str(tmp_path / "catalog.db")
        self.entry = SimpleNamespace(
            entry_id=7,
            label="Delete Track: Threaded Song",
            created_at="2026-08-08T10:00:00",
        )
        self.direction = direction
        self.history_dialog = SimpleNamespace(
            isVisible=lambda: True,
            refresh_data=lambda: None,
        )
        self.history_manager = SimpleNamespace()
        self.session_history_manager = SimpleNamespace()
        self.settings = SimpleNamespace(sync=self._sync_settings)
        self.logger = SimpleNamespace(exception=lambda _message: None)
        self.submissions: list[dict[str, object]] = []
        self.refresh_actions = 0
        self.refresh_after = 0
        self.settings_syncs = 0
        self.errors: list[tuple[str, str]] = []

    def _sync_settings(self) -> None:
        self.settings_syncs += 1

    def _get_best_history_candidate(self, direction: str):
        assert direction == self.direction
        return "profile", self.entry

    def _submit_background_bundle_task(self, **kwargs):
        self.submissions.append(kwargs)
        return "history-task"

    def _refresh_after_history_change(self) -> None:
        self.refresh_after += 1
        self._refresh_history_actions()

    def _refresh_history_actions(self) -> None:
        self.refresh_actions += 1

    def _advance_task_ui_progress(
        self,
        ui_progress,
        *,
        value: int,
        message: str,
        maximum: int = 100,
    ) -> None:
        ui_progress.report_progress(value=value, maximum=maximum, message=message)

    def _show_background_task_error(self, title, failure, *, user_message) -> None:
        self.errors.append((title, f"{user_message} {failure.message}"))


class _WorkerHistoryManager:
    def __init__(self, host: _Host, *, direction: str) -> None:
        self.db_path = host.current_db_path
        self.entry = host.entry
        self.direction = direction
        self.replay_calls = 0

    def get_current_visible_entry(self):
        return self.entry if self.direction == "undo" else None

    def get_default_redo_entry(self):
        return self.entry if self.direction == "redo" else None

    def undo(self, *, expected_visible_entry_id, progress_callback):
        assert self.direction == "undo"
        assert expected_visible_entry_id == self.entry.entry_id
        return self._replay(progress_callback)

    def redo(self, *, expected_visible_entry_id, progress_callback):
        assert self.direction == "redo"
        assert expected_visible_entry_id == self.entry.entry_id
        return self._replay(progress_callback)

    def _replay(self, progress_callback):
        self.replay_calls += 1
        progress_callback(0, 0, "Validating history artifacts...")
        progress_callback(1, 4, "Compared one of four snapshot tables.")
        progress_callback(4, 4, "Committed replay changes.")
        return self.entry


@pytest.mark.parametrize(
    ("direction", "command"), [("undo", replay_controller.undo), ("redo", replay_controller.redo)]
)
def test_profile_history_replay_uses_exclusive_worker_bundle_and_ui_finalization(
    tmp_path,
    direction,
    command,
) -> None:
    host = _Host(tmp_path, direction=direction)

    assert command(host) == "history-task"
    assert host._history_replay_in_progress is True
    assert host.refresh_actions == 0

    submission = host.submissions[-1]
    assert submission["kind"] == "exclusive"
    assert submission["unique_key"] == "history.replay"
    assert submission["cancellable"] is False
    assert submission["owner"] is host.history_dialog
    assert submission["worker_completion_progress"][0] < 100

    worker_history = _WorkerHistoryManager(host, direction=direction)
    worker_context = _ProgressContext()
    result = submission["task_fn"](
        SimpleNamespace(history_manager=worker_history),
        worker_context,
    )
    assert result == {"entry_id": 7, "label": "Delete Track: Threaded Song"}
    assert worker_history.replay_calls == 1
    assert worker_context.updates[0][1] == 100
    assert worker_context.updates[1] == (0, 100, "Validating history artifacts...")
    assert worker_context.updates[-1][0] == 90
    assert worker_context.updates[-1][1] == 100

    ui_progress = _ProgressContext()
    submission["on_success_before_cleanup"](result, ui_progress)
    assert host.settings_syncs == 1
    assert host.refresh_after == 1
    assert ui_progress.updates[-1][0] == 100
    assert "ready" in str(ui_progress.updates[-1][2]).lower()

    submission["on_finished"]()
    assert host._history_replay_in_progress is False
    assert host.refresh_actions == 2


def test_profile_history_replay_rejects_stale_worker_candidate(tmp_path) -> None:
    host = _Host(tmp_path)
    assert replay_controller.redo(host) == "history-task"
    submission = host.submissions[-1]
    worker_history = _WorkerHistoryManager(host, direction="redo")
    worker_history.entry = SimpleNamespace(entry_id=8, label="Newer action")

    with pytest.raises(RuntimeError, match="History changed"):
        submission["task_fn"](
            SimpleNamespace(history_manager=worker_history),
            _ProgressContext(),
        )


def test_profile_history_replay_honors_explicit_progress_owner(tmp_path) -> None:
    host = _Host(tmp_path)
    explicit_owner = object()

    assert replay_controller.redo(host, owner=explicit_owner) == "history-task"

    assert host.submissions[-1]["owner"] is explicit_owner


def test_profile_history_replay_submission_failure_clears_reentry_guard(tmp_path) -> None:
    host = _Host(tmp_path)
    host._submit_background_bundle_task = lambda **_kwargs: None

    assert replay_controller.redo(host) is None
    assert host._history_replay_in_progress is False
    assert host.refresh_actions == 1


def test_profile_history_replay_error_resynchronizes_ui_before_reporting(tmp_path) -> None:
    host = _Host(tmp_path)
    assert replay_controller.redo(host) == "history-task"
    submission = host.submissions[-1]
    failure = SimpleNamespace(message="replay conflict")

    submission["on_error"](failure)

    assert host.settings_syncs == 1
    assert host.refresh_after == 1
    assert host.errors == [("Redo Error", "Could not redo the action: replay conflict")]


def test_worker_progress_remains_determinate_and_never_regresses() -> None:
    context = _ProgressContext()
    report = replay_controller._worker_progress(context)

    report(1, 2, "Half complete")
    report(0, 0, "Checking an unbounded operation")
    report(1, 4, "A later phase reported a smaller ratio")

    assert context.updates == [
        (45, 100, "Half complete"),
        (45, 100, "Checking an unbounded operation"),
        (45, 100, "A later phase reported a smaller ratio"),
    ]


def test_profile_history_replay_ignores_reentry_while_active(tmp_path) -> None:
    host = _Host(tmp_path)
    host._history_replay_in_progress = True

    assert replay_controller.redo(host) is None
    assert host.submissions == []

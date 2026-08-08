"""UI orchestration for undo and redo replay."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from PySide6.QtWidgets import QMessageBox

HistoryDirection = Literal["undo", "redo"]


class HistoryReplayHost(Protocol):
    """Narrow host surface required by history replay commands."""

    current_db_path: str
    history_dialog: Any
    history_manager: Any
    session_history_manager: Any
    settings: Any
    logger: Any

    def _get_best_history_candidate(self, direction: str) -> tuple[str | None, Any | None]: ...

    def _submit_background_bundle_task(self, **kwargs: Any) -> str | None: ...

    def _refresh_after_history_change(self) -> None: ...

    def _refresh_history_actions(self) -> None: ...

    def _advance_task_ui_progress(
        self,
        ui_progress: Any,
        *,
        value: int,
        message: str,
        maximum: int = 100,
    ) -> None: ...

    def _show_background_task_error(
        self,
        title: str,
        failure: Any,
        *,
        user_message: str,
    ) -> None: ...


def undo(host: HistoryReplayHost, *, owner: Any | None = None) -> str | None:
    """Run the newest Undo candidate on its safe execution surface."""

    return _run(host, "undo", owner=owner)


def redo(host: HistoryReplayHost, *, owner: Any | None = None) -> str | None:
    """Run the newest Redo candidate on its safe execution surface."""

    return _run(host, "redo", owner=owner)


def _run(
    host: HistoryReplayHost,
    direction: HistoryDirection,
    *,
    owner: Any | None = None,
) -> str | None:
    if bool(getattr(host, "_history_replay_in_progress", False)):
        return None

    source, entry = host._get_best_history_candidate(direction)
    if source is None or entry is None:
        return None
    if source == "session":
        _run_session_replay(host, direction)
        return None
    return _start_profile_replay(host, direction, entry, owner=owner)


def _run_session_replay(host: HistoryReplayHost, direction: HistoryDirection) -> None:
    """Keep profile-navigation history on the UI thread until it has a split service API."""

    operation = direction.title()
    try:
        replay = getattr(host.session_history_manager, direction)
        entry = replay(host)
        if entry is not None:
            host._refresh_history_actions()
            dialog = getattr(host, "history_dialog", None)
            if dialog is not None and dialog.isVisible():
                dialog.refresh_data()
    except Exception as exc:
        host.logger.exception(f"{operation} failed: {exc}")
        _show_sync_error(host, direction, exc)


def _start_profile_replay(
    host: HistoryReplayHost,
    direction: HistoryDirection,
    expected_entry: Any,
    *,
    owner: Any | None = None,
) -> str | None:
    operation = direction.title()
    expected_entry_id = int(expected_entry.entry_id)
    expected_label = str(getattr(expected_entry, "label", "") or operation)
    expected_profile_path = Path(str(host.current_db_path)).absolute()
    progress_owner = owner if owner is not None else _progress_owner(host)
    setattr(host, "_history_replay_in_progress", True)
    _disable_replay_actions(host)

    def _worker(bundle: Any, ctx: Any) -> dict[str, object]:
        worker_manager = bundle.history_manager
        worker_profile_path = Path(worker_manager.db_path).absolute()
        if worker_profile_path != expected_profile_path:
            raise RuntimeError(f"The active profile changed before {direction} could begin.")

        ctx.report_progress(
            value=0,
            maximum=100,
            message=f"Preparing to {direction} {expected_label}...",
        )
        current_entry = (
            worker_manager.get_current_visible_entry()
            if direction == "undo"
            else worker_manager.get_default_redo_entry()
        )
        if current_entry is None or int(current_entry.entry_id) != expected_entry_id:
            raise RuntimeError(
                f"History changed before {direction} could begin. Review Undo History and try again."
            )

        replay = getattr(worker_manager, direction)
        result = replay(
            expected_visible_entry_id=expected_entry_id,
            progress_callback=_worker_progress(ctx),
        )
        if result is None or int(result.entry_id) != expected_entry_id:
            past_tense = "undone" if direction == "undo" else "redone"
            raise RuntimeError(f"The selected history entry could not be {past_tense}.")
        return {
            "entry_id": int(result.entry_id),
            "label": str(getattr(result, "label", "") or expected_label),
        }

    def _before_cleanup(_result: dict[str, object], ui_progress: Any) -> None:
        host._advance_task_ui_progress(
            ui_progress,
            value=95,
            message=f"Synchronizing settings after {direction}...",
        )
        host.settings.sync()
        host._advance_task_ui_progress(
            ui_progress,
            value=97,
            message=f"Refreshing the interface after {direction}...",
        )
        host._refresh_after_history_change()
        host._advance_task_ui_progress(
            ui_progress,
            value=100,
            message=f"{operation} complete. The interface is ready.",
        )

    def _on_error(failure: Any) -> None:
        _refresh_after_worker_error(host, direction)
        host._show_background_task_error(
            f"{operation} Error",
            failure,
            user_message=(
                "Could not undo the last action:"
                if direction == "undo"
                else "Could not redo the action:"
            ),
        )

    def _on_finished() -> None:
        setattr(host, "_history_replay_in_progress", False)
        _refresh_action_state(host)

    task_id = host._submit_background_bundle_task(
        title=f"{operation} History Action",
        description=f"Preparing to {direction} {expected_label}...",
        task_fn=_worker,
        kind="exclusive",
        unique_key="history.replay",
        owner=progress_owner,
        cancellable=False,
        worker_completion_progress=(94, f"{operation} committed. Preparing the interface..."),
        on_success_before_cleanup=_before_cleanup,
        on_error=_on_error,
        on_finished=_on_finished,
    )
    if task_id is None:
        setattr(host, "_history_replay_in_progress", False)
        _refresh_action_state(host)
    return task_id


def _worker_progress(
    ctx: Any,
) -> Callable[[int | None, int | None, str | None], None]:
    """Map replay progress below the UI-finalization range without inventing progress."""

    last_value = 0

    def _report(
        value: int | None = None,
        maximum: int | None = None,
        message: str | None = None,
    ) -> None:
        nonlocal last_value
        if maximum is None or int(maximum) <= 0 or value is None:
            ctx.report_progress(
                value=last_value,
                maximum=100,
                message=str(message or "Undo/Redo is still working..."),
            )
            return
        bounded_maximum = max(1, int(maximum))
        bounded_value = min(max(int(value), 0), bounded_maximum)
        last_value = max(
            last_value,
            min(90, round((bounded_value / bounded_maximum) * 90)),
        )
        ctx.report_progress(
            value=last_value,
            maximum=100,
            message=str(message or "Replaying history..."),
        )

    return _report


def _progress_owner(host: HistoryReplayHost) -> Any:
    dialog = getattr(host, "history_dialog", None)
    if dialog is not None and dialog.isVisible():
        return dialog
    return host


def _disable_replay_actions(host: HistoryReplayHost) -> None:
    for name in ("undo_action", "redo_action"):
        action = getattr(host, name, None)
        if action is not None:
            action.setEnabled(False)
    dialog = getattr(host, "history_dialog", None)
    if dialog is None or not dialog.isVisible():
        return
    for name in ("undo_btn", "redo_btn"):
        button = getattr(dialog, name, None)
        if button is not None:
            button.setEnabled(False)


def _refresh_after_worker_error(
    host: HistoryReplayHost,
    direction: HistoryDirection,
) -> None:
    try:
        host.settings.sync()
    except Exception as exc:
        host.logger.exception(f"Could not synchronize settings after failed {direction}: {exc}")
    try:
        host._refresh_after_history_change()
    except Exception as exc:
        host.logger.exception(f"Could not refresh the interface after failed {direction}: {exc}")


def _refresh_action_state(host: HistoryReplayHost) -> None:
    refresh = getattr(host, "_refresh_history_actions", None)
    if callable(refresh):
        refresh()


def _show_sync_error(
    host: HistoryReplayHost,
    direction: HistoryDirection,
    error: Exception,
) -> None:
    if direction == "undo":
        title = "Undo Error"
        message = f"Could not undo the last action:\n{error}"
    else:
        title = "Redo Error"
        message = f"Could not redo the action:\n{error}"
    QMessageBox.critical(cast(Any, host), title, message)

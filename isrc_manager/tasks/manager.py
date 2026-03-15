"""Reusable Qt-compatible background task execution helpers."""

from __future__ import annotations

import traceback
import uuid
from dataclasses import dataclass
from threading import Event
from typing import Callable

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import QProgressDialog, QWidget

from .models import TaskCancelledError, TaskFailure, TaskProgressUpdate


class BackgroundTaskContext:
    """Mutable task context shared with worker functions."""

    def __init__(self):
        self._cancel_event = Event()
        self._progress_callback: Callable[[TaskProgressUpdate], None] | None = None
        self._status_callback: Callable[[str], None] | None = None

    def bind_callbacks(
        self,
        *,
        progress_callback: Callable[[TaskProgressUpdate], None],
        status_callback: Callable[[str], None],
    ) -> None:
        self._progress_callback = progress_callback
        self._status_callback = status_callback

    def cancel(self) -> None:
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise TaskCancelledError("The operation was cancelled.")

    def set_status(self, message: str) -> None:
        if self._status_callback is not None:
            self._status_callback(str(message or ""))

    def report_progress(
        self,
        value: int | None = None,
        maximum: int | None = None,
        *,
        message: str | None = None,
    ) -> None:
        if self._progress_callback is not None:
            self._progress_callback(
                TaskProgressUpdate(
                    value=value,
                    maximum=maximum,
                    message=message,
                )
            )


class _BackgroundTaskWorker(QObject):
    progress = Signal(object)
    status = Signal(str)
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, task_fn: Callable[[BackgroundTaskContext], object], context: BackgroundTaskContext):
        super().__init__()
        self._task_fn = task_fn
        self._context = context
        self._context.bind_callbacks(progress_callback=self.progress.emit, status_callback=self.status.emit)

    @Slot()
    def run(self) -> None:
        try:
            result = self._task_fn(self._context)
            if self._context.is_cancelled():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)
        except TaskCancelledError:
            self.cancelled.emit()
        except InterruptedError:
            if self._context.is_cancelled():
                self.cancelled.emit()
            else:
                self.failed.emit(
                    TaskFailure(
                        message="The background task was interrupted.",
                        traceback_text=traceback.format_exc(),
                    )
                )
        except Exception as exc:  # pragma: no cover - defensive UI path
            self.failed.emit(
                TaskFailure(
                    message=str(exc),
                    traceback_text=traceback.format_exc(),
                )
            )
        finally:
            self.finished.emit()


class _TaskCallbackRelay(QObject):
    """Routes worker-thread signals back onto the manager/UI thread."""

    def __init__(
        self,
        *,
        progress_handler: Callable[[TaskProgressUpdate], None],
        status_handler: Callable[[str], None],
        success_handler: Callable[[object], None] | None,
        error_handler: Callable[[TaskFailure], None] | None,
        cancelled_handler: Callable[[], None] | None,
        finished_handler: Callable[[], None] | None,
        cleanup_handler: Callable[[], None],
    ):
        super().__init__()
        self._progress_handler = progress_handler
        self._status_handler = status_handler
        self._success_handler = success_handler
        self._error_handler = error_handler
        self._cancelled_handler = cancelled_handler
        self._finished_handler = finished_handler
        self._cleanup_handler = cleanup_handler

    @Slot(object)
    def handle_progress(self, update: object) -> None:
        if isinstance(update, TaskProgressUpdate):
            self._progress_handler(update)
        else:
            self._progress_handler(TaskProgressUpdate(message=str(update or "")))

    @Slot(str)
    def handle_status(self, message: str) -> None:
        self._status_handler(message)

    @Slot(object)
    def handle_success(self, result: object) -> None:
        if self._success_handler is not None:
            self._success_handler(result)

    @Slot(object)
    def handle_error(self, failure: object) -> None:
        if self._error_handler is None:
            return
        if isinstance(failure, TaskFailure):
            self._error_handler(failure)
            return
        self._error_handler(TaskFailure(message=str(failure or "Background task failed."), traceback_text=""))

    @Slot()
    def handle_cancelled(self) -> None:
        if self._cancelled_handler is not None:
            self._cancelled_handler()

    @Slot()
    def handle_finished(self) -> None:
        if self._finished_handler is not None:
            self._finished_handler()

    @Slot()
    def handle_cleanup(self) -> None:
        self._cleanup_handler()


@dataclass(slots=True)
class _TaskRecord:
    task_id: str
    title: str
    kind: str
    unique_key: str | None
    context: BackgroundTaskContext
    thread: QThread
    worker: _BackgroundTaskWorker
    relay: _TaskCallbackRelay
    dialog: QProgressDialog | None


class BackgroundTaskManager(QObject):
    """Centralized background-task runner built on QThread + QObject workers."""

    task_state_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._tasks: dict[str, _TaskRecord] = {}

    def has_running_tasks(self) -> bool:
        return bool(self._tasks)

    def has_active_write_task(self) -> bool:
        return any(record.kind in {"write", "exclusive"} for record in self._tasks.values())

    def active_task_titles(self) -> list[str]:
        return [record.title for record in self._tasks.values()]

    def can_start(self, *, kind: str = "read", unique_key: str | None = None) -> tuple[bool, str | None]:
        clean_kind = str(kind or "read")
        if unique_key:
            for record in self._tasks.values():
                if record.unique_key == unique_key:
                    return False, f"'{record.title}' is already running."
        if clean_kind == "exclusive" and self._tasks:
            return False, "Another background task is already running."
        if clean_kind == "write":
            if any(record.kind in {"write", "exclusive"} for record in self._tasks.values()):
                return False, "Another write operation is already running."
        if clean_kind == "read":
            if any(record.kind == "exclusive" for record in self._tasks.values()):
                return False, "An exclusive database task is currently running."
        return True, None

    def submit(
        self,
        *,
        title: str,
        description: str,
        task_fn: Callable[[BackgroundTaskContext], object],
        kind: str = "read",
        unique_key: str | None = None,
        owner: QWidget | None = None,
        show_dialog: bool = True,
        cancellable: bool = False,
        on_success: Callable[[object], None] | None = None,
        on_error: Callable[[TaskFailure], None] | None = None,
        on_cancelled: Callable[[], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        on_progress: Callable[[TaskProgressUpdate], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> str | None:
        allowed, reason = self.can_start(kind=kind, unique_key=unique_key)
        if not allowed:
            if on_error is not None:
                on_error(TaskFailure(message=reason or "Task could not start.", traceback_text=""))
            return None

        task_id = uuid.uuid4().hex
        thread = QThread(self)
        context = BackgroundTaskContext()
        worker = _BackgroundTaskWorker(task_fn, context)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        dialog = None
        if show_dialog:
            dialog = QProgressDialog(description, "Cancel" if cancellable else "", 0, 0, owner)
            dialog.setWindowTitle(title)
            dialog.setWindowModality(Qt.WindowModal)
            dialog.setAutoClose(False)
            dialog.setAutoReset(False)
            dialog.setMinimumDuration(0)
            dialog.setValue(0)
            if not cancellable:
                dialog.setCancelButton(None)
            else:
                dialog.canceled.connect(context.cancel)
            dialog.show()

        def _apply_progress(update: TaskProgressUpdate) -> None:
            if dialog is not None:
                if update.message:
                    dialog.setLabelText(update.message)
                if update.maximum is not None and update.value is not None:
                    dialog.setMaximum(max(0, int(update.maximum)))
                    dialog.setValue(max(0, int(update.value)))
                elif update.maximum is not None:
                    dialog.setMaximum(max(0, int(update.maximum)))
                elif update.value is not None:
                    dialog.setValue(max(0, int(update.value)))
            if on_progress is not None:
                on_progress(update)

        def _apply_status(message: str) -> None:
            if dialog is not None and message:
                dialog.setLabelText(message)
            if on_status is not None:
                on_status(message)

        def _cleanup() -> None:
            current = self._tasks.pop(task_id, None)
            if current is not None and current.dialog is not None:
                current.dialog.close()
                current.dialog.deleteLater()
            thread.deleteLater()
            self.task_state_changed.emit()
            if on_finished is not None:
                on_finished()
            relay.deleteLater()

        relay = _TaskCallbackRelay(
            progress_handler=_apply_progress,
            status_handler=_apply_status,
            success_handler=on_success,
            error_handler=on_error,
            cancelled_handler=on_cancelled,
            finished_handler=None,
            cleanup_handler=_cleanup,
        )
        relay.setParent(self)

        record = _TaskRecord(
            task_id=task_id,
            title=str(title or "Background Task"),
            kind=str(kind or "read"),
            unique_key=str(unique_key).strip() if unique_key else None,
            context=context,
            thread=thread,
            worker=worker,
            relay=relay,
            dialog=dialog,
        )
        self._tasks[task_id] = record
        self.task_state_changed.emit()

        worker.progress.connect(relay.handle_progress, Qt.QueuedConnection)
        worker.status.connect(relay.handle_status, Qt.QueuedConnection)
        worker.succeeded.connect(relay.handle_success, Qt.QueuedConnection)
        worker.failed.connect(relay.handle_error, Qt.QueuedConnection)
        worker.cancelled.connect(relay.handle_cancelled, Qt.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        thread.finished.connect(relay.handle_cleanup, Qt.QueuedConnection)
        thread.start()
        return task_id

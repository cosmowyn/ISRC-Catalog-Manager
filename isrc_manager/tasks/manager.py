"""Reusable Qt-compatible background task execution helpers."""

from __future__ import annotations

import traceback
import uuid
from dataclasses import dataclass
from threading import Event
from typing import Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QWidget,
)
from shiboken6 import isValid as _qt_object_is_valid

from ..theme_builder import effective_theme_settings
from ..ui_common import _abbreviate_middle_text, _compose_widget_stylesheet
from .models import TaskCancelledError, TaskFailure, TaskProgressUpdate

_PROGRESS_DIALOG_MIN_WIDTH = 360
_PROGRESS_DIALOG_MAX_WIDTH = 480
_PROGRESS_DIALOG_MIN_HEIGHT = 118
_PROGRESS_DIALOG_MAX_HEIGHT = 220
_PROGRESS_DIALOG_SIDE_PADDING = 36
_PROGRESS_DIALOG_BUTTON_GAP = 12
_PROGRESS_DIALOG_LABEL_MIN_WIDTH = 220
_PROGRESS_DIALOG_PROGRESS_MIN_WIDTH = 180
_PROGRESS_DIALOG_BUTTON_MIN_WIDTH = 76
_PROGRESS_DIALOG_BUTTON_MAX_WIDTH = 110
_PROGRESS_DIALOG_LONG_TEXT_THRESHOLD = 60
_PROGRESS_DIALOG_CORNER_RADIUS = 18
_PROGRESS_DIALOG_TOP_PADDING = 16
_PROGRESS_DIALOG_BOTTOM_PADDING = 16
_PROGRESS_DIALOG_LABEL_BAR_GAP = 8


def _rgba(color_value: object, alpha: int) -> str:
    color = QColor(str(color_value or "#000000"))
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {max(0, min(255, int(alpha)))})"


def _progress_dialog_theme(owner: QWidget | None) -> dict[str, object]:
    current = owner
    while current is not None:
        getter = getattr(current, "_effective_theme_settings", None)
        if callable(getter):
            try:
                values = dict(getter() or {})
            except Exception:
                values = {}
            if values:
                return values
        raw_settings = getattr(current, "theme_settings", None)
        if isinstance(raw_settings, dict):
            return effective_theme_settings(raw_settings)
        current = current.parentWidget()
    return effective_theme_settings({})


def _progress_dialog_stylesheet(owner: QWidget | None) -> str:
    theme = _progress_dialog_theme(owner)
    progress_radius = max(2, int(theme.get("progress_radius", 8)))
    chunk_radius = max(1, progress_radius - 1)
    return f"""
    QProgressDialog#backgroundTaskProgressDialog {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 {_rgba(theme.get("panel_bg"), 246)},
            stop: 1 {_rgba(theme.get("panel_alt_bg"), 252)}
        );
        border: 1px solid {_rgba(theme.get("menu_border"), 218)};
        border-radius: {_PROGRESS_DIALOG_CORNER_RADIUS}px;
    }}
    QProgressDialog#backgroundTaskProgressDialog QLabel#backgroundTaskProgressLabel {{
        background: transparent;
        color: {theme["window_fg"]};
        font-size: 14px;
        font-weight: 600;
        padding: 0;
        margin: 0;
    }}
    QProgressDialog#backgroundTaskProgressDialog QProgressBar#backgroundTaskProgressBar {{
        min-height: 14px;
        max-height: 14px;
    }}
    QProgressDialog#backgroundTaskProgressDialog QProgressBar#backgroundTaskProgressBar::chunk {{
        border-radius: {chunk_radius}px;
        margin: 1px;
    }}
    QProgressDialog#backgroundTaskProgressDialog QPushButton#backgroundTaskProgressButton {{
        min-height: 30px;
        padding: 0 14px;
    }}
    """


def _apply_progress_dialog_chrome(dialog: QProgressDialog) -> None:
    dialog.setObjectName("backgroundTaskProgressDialog")
    dialog.setProperty("role", "panel")
    dialog.setAttribute(Qt.WA_StyledBackground, True)
    app = QApplication.instance()
    if app is not None:
        dialog.setPalette(app.palette())
    dialog.setStyleSheet(_compose_widget_stylesheet(dialog, _progress_dialog_stylesheet(dialog)))


def _repolish_widget_tree(root: QWidget) -> None:
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        try:
            style = widget.style()
            if style is not None:
                style.unpolish(widget)
                style.polish(widget)
        except Exception:
            pass
        try:
            widget.update()
        except Exception:
            pass


def _prepare_progress_dialog_controls(dialog: QProgressDialog) -> tuple[list[QPushButton], int]:
    buttons = [button for button in dialog.findChildren(QPushButton) if not button.isHidden()]
    button_width = 0
    for button in buttons:
        button.setObjectName("backgroundTaskProgressButton")
        button.setCursor(Qt.PointingHandCursor)
        preferred_width = max(_PROGRESS_DIALOG_BUTTON_MIN_WIDTH, button.sizeHint().width())
        button_width = max(button_width, min(_PROGRESS_DIALOG_BUTTON_MAX_WIDTH, preferred_width))
    label_max_width = max(
        _PROGRESS_DIALOG_LABEL_MIN_WIDTH,
        _progress_dialog_target_width(dialog) - _PROGRESS_DIALOG_SIDE_PADDING,
    )
    progress_max_width = max(
        _PROGRESS_DIALOG_PROGRESS_MIN_WIDTH,
        _progress_dialog_target_width(dialog) - _PROGRESS_DIALOG_SIDE_PADDING,
    )
    for label in dialog.findChildren(QLabel):
        label.setObjectName("backgroundTaskProgressLabel")
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextWordWrap)
        label.setMinimumWidth(0)
        label.setMaximumWidth(label_max_width)
    for progress_bar in dialog.findChildren(QProgressBar):
        progress_bar.setObjectName("backgroundTaskProgressBar")
        progress_bar.setTextVisible(False)
        progress_bar.setMinimumWidth(min(_PROGRESS_DIALOG_PROGRESS_MIN_WIDTH, progress_max_width))
        progress_bar.setMaximumWidth(progress_max_width)
        progress_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return buttons, button_width


def refresh_progress_dialog_theme(dialog: QProgressDialog) -> None:
    if dialog is None or not _qt_object_is_valid(dialog):
        return
    _prepare_progress_dialog_controls(dialog)
    _apply_progress_dialog_chrome(dialog)
    _repolish_widget_tree(dialog)
    _refresh_progress_dialog_height(dialog)


def _progress_dialog_target_width(dialog: QProgressDialog) -> int:
    current_width = dialog.width()
    if current_width > 0:
        return min(_PROGRESS_DIALOG_MAX_WIDTH, max(_PROGRESS_DIALOG_MIN_WIDTH, current_width))
    parent_widget = dialog.parentWidget()
    if parent_widget is not None and parent_widget.width() > 0:
        return min(
            _PROGRESS_DIALOG_MAX_WIDTH,
            max(_PROGRESS_DIALOG_MIN_WIDTH, int(parent_widget.width() * 0.34)),
        )
    return _PROGRESS_DIALOG_MIN_WIDTH


def _format_progress_dialog_message(message: str | None) -> str:
    raw_text = str(message or "").strip()
    if not raw_text:
        return ""
    formatted_lines: list[str] = []
    for line in raw_text.splitlines() or [raw_text]:
        clean_line = str(line).strip()
        if not clean_line:
            formatted_lines.append("")
            continue
        prefix, separator, remainder = clean_line.partition(": ")
        if separator and len(remainder) > _PROGRESS_DIALOG_LONG_TEXT_THRESHOLD:
            formatted_lines.append(
                f"{prefix}{separator}"
                f"{_abbreviate_middle_text(remainder, threshold=_PROGRESS_DIALOG_LONG_TEXT_THRESHOLD)}"
            )
            continue
        formatted_lines.append(
            _abbreviate_middle_text(clean_line, threshold=_PROGRESS_DIALOG_LONG_TEXT_THRESHOLD)
        )
    return "\n".join(formatted_lines)


def _configure_progress_dialog(dialog: QProgressDialog) -> None:
    dialog.setMinimumWidth(_PROGRESS_DIALOG_MIN_WIDTH)
    dialog.setMaximumWidth(_PROGRESS_DIALOG_MAX_WIDTH)
    dialog.setMinimumHeight(_PROGRESS_DIALOG_MIN_HEIGHT)
    dialog.setMaximumHeight(_PROGRESS_DIALOG_MAX_HEIGHT)
    dialog.setSizeGripEnabled(False)
    buttons, button_width = _prepare_progress_dialog_controls(dialog)
    _apply_progress_dialog_chrome(dialog)
    _repolish_widget_tree(dialog)
    if button_width:
        for button in buttons:
            button.setMinimumWidth(button_width)
            button.setMaximumWidth(button_width)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    _refresh_progress_dialog_height(dialog)


def _refresh_progress_dialog_height(dialog: QProgressDialog) -> None:
    width = _progress_dialog_target_width(dialog)
    label = next(iter(dialog.findChildren(QLabel)), None)
    progress_bar = next(iter(dialog.findChildren(QProgressBar)), None)
    buttons = [button for button in dialog.findChildren(QPushButton) if not button.isHidden()]
    label_width = max(_PROGRESS_DIALOG_LABEL_MIN_WIDTH, width - _PROGRESS_DIALOG_SIDE_PADDING)
    label_height = 0
    if label is not None:
        label_height = max(
            label.fontMetrics().lineSpacing() + 2,
            label.heightForWidth(label_width) if label.wordWrap() else label.sizeHint().height(),
        )
    progress_height = progress_bar.sizeHint().height() if progress_bar is not None else 14
    button_height = max((button.sizeHint().height() for button in buttons), default=0)
    preferred_height = (
        _PROGRESS_DIALOG_TOP_PADDING
        + label_height
        + _PROGRESS_DIALOG_LABEL_BAR_GAP
        + progress_height
        + _PROGRESS_DIALOG_BOTTOM_PADDING
    )
    if button_height:
        preferred_height += _PROGRESS_DIALOG_BUTTON_GAP + button_height
    height = min(
        _PROGRESS_DIALOG_MAX_HEIGHT,
        max(
            _PROGRESS_DIALOG_MIN_HEIGHT,
            int(preferred_height),
        ),
    )
    dialog.resize(width, int(height))
    _relayout_progress_dialog(dialog)


def _relayout_progress_dialog(dialog: QProgressDialog) -> None:
    label = next(iter(dialog.findChildren(QLabel)), None)
    progress_bar = next(iter(dialog.findChildren(QProgressBar)), None)
    buttons = [button for button in dialog.findChildren(QPushButton) if not button.isHidden()]
    if label is None or progress_bar is None:
        return

    content_rect = dialog.rect().adjusted(
        _PROGRESS_DIALOG_SIDE_PADDING // 2,
        _PROGRESS_DIALOG_TOP_PADDING,
        -(_PROGRESS_DIALOG_SIDE_PADDING // 2),
        -_PROGRESS_DIALOG_BOTTOM_PADDING,
    )
    label_width = max(_PROGRESS_DIALOG_LABEL_MIN_WIDTH, content_rect.width())
    label_height = max(
        label.fontMetrics().lineSpacing() + 2,
        label.heightForWidth(label_width) if label.wordWrap() else label.sizeHint().height(),
    )
    progress_height = max(progress_bar.minimumHeight(), progress_bar.sizeHint().height())
    stack_height = label_height + _PROGRESS_DIALOG_LABEL_BAR_GAP + progress_height

    button_height = 0
    button_top = content_rect.bottom() + 1
    if buttons:
        button = buttons[0]
        button_width = min(
            _PROGRESS_DIALOG_BUTTON_MAX_WIDTH,
            max(_PROGRESS_DIALOG_BUTTON_MIN_WIDTH, button.sizeHint().width()),
        )
        button_height = max(button.minimumHeight(), button.sizeHint().height())
        button_top = content_rect.bottom() - button_height + 1
        button_left = content_rect.left() + max(0, (content_rect.width() - button_width) // 2)
        button.setGeometry(button_left, button_top, button_width, button_height)

    available_bottom = (
        button_top - _PROGRESS_DIALOG_BUTTON_GAP if button_height else content_rect.bottom() + 1
    )
    available_height = max(0, available_bottom - content_rect.top())
    stack_top = content_rect.top() + max(0, (available_height - stack_height) // 2)

    label.setGeometry(content_rect.left(), stack_top, content_rect.width(), label_height)
    progress_top = label.geometry().bottom() + 1 + _PROGRESS_DIALOG_LABEL_BAR_GAP
    progress_bar.setGeometry(
        content_rect.left(),
        progress_top,
        content_rect.width(),
        progress_height,
    )


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


@dataclass(slots=True)
class TaskUiProgressContext:
    """UI-thread progress proxy used for truthful post-worker finalization."""

    progress_handler: Callable[[TaskProgressUpdate], None]
    status_handler: Callable[[str], None]

    def report_progress(
        self,
        value: int | None = None,
        maximum: int | None = None,
        message: str | None = None,
    ) -> None:
        self.progress_handler(
            TaskProgressUpdate(
                value=value,
                maximum=maximum,
                message=message,
            )
        )

    def set_status(self, message: str) -> None:
        self.status_handler(str(message or ""))


class _BackgroundTaskWorker(QObject):
    progress = Signal(object)
    status = Signal(str)
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal()
    finished = Signal()

    def __init__(
        self, task_fn: Callable[[BackgroundTaskContext], object], context: BackgroundTaskContext
    ):
        super().__init__()
        self._task_fn = task_fn
        self._context = context
        self._context.bind_callbacks(
            progress_callback=self.progress.emit, status_callback=self.status.emit
        )

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
        success_before_cleanup_handler: Callable[[object, TaskUiProgressContext], None] | None,
        success_handler: Callable[[object], None] | None,
        success_after_cleanup_handler: Callable[[object], None] | None,
        error_handler: Callable[[TaskFailure], None] | None,
        cancelled_handler: Callable[[], None] | None,
        finished_handler: Callable[[], None] | None,
        cleanup_handler: Callable[[], None],
    ):
        super().__init__()
        self._progress_handler = progress_handler
        self._status_handler = status_handler
        self._success_before_cleanup_handler = success_before_cleanup_handler
        self._success_handler = success_handler
        self._success_after_cleanup_handler = success_after_cleanup_handler
        self._error_handler = error_handler
        self._cancelled_handler = cancelled_handler
        self._finished_handler = finished_handler
        self._cleanup_handler = cleanup_handler
        self._ui_progress_context = TaskUiProgressContext(
            progress_handler=progress_handler,
            status_handler=status_handler,
        )
        self._success_result = None
        self._success_pending = False

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
        self._success_result = result
        self._success_pending = True
        try:
            if self._success_before_cleanup_handler is not None:
                self._success_before_cleanup_handler(result, self._ui_progress_context)
            if self._success_handler is not None:
                self._success_handler(result)
        except Exception as exc:  # pragma: no cover - defensive UI path
            self._success_pending = False
            if self._error_handler is not None:
                self._error_handler(
                    TaskFailure(
                        message=str(exc),
                        traceback_text=traceback.format_exc(),
                    )
                )

    @Slot(object)
    def handle_error(self, failure: object) -> None:
        if self._error_handler is None:
            return
        if isinstance(failure, TaskFailure):
            self._error_handler(failure)
            return
        self._error_handler(
            TaskFailure(message=str(failure or "Background task failed."), traceback_text="")
        )

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
        try:
            self._cleanup_handler()
            if self._success_pending and self._success_after_cleanup_handler is not None:
                self._success_after_cleanup_handler(self._success_result)
        finally:
            if self._finished_handler is not None:
                self._finished_handler()
            self.deleteLater()


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

    def refresh_active_progress_dialogs(self) -> None:
        for record in list(self._tasks.values()):
            dialog = record.dialog
            if dialog is None or not _qt_object_is_valid(dialog):
                continue
            refresh_progress_dialog_theme(dialog)

    def can_start(
        self, *, kind: str = "read", unique_key: str | None = None
    ) -> tuple[bool, str | None]:
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
        on_success_before_cleanup: Callable[[object, TaskUiProgressContext], None] | None = None,
        on_success: Callable[[object], None] | None = None,
        on_success_after_cleanup: Callable[[object], None] | None = None,
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
        dialog_label = None
        dialog_progress = None
        if show_dialog:
            dialog_label = QLabel(_format_progress_dialog_message(description), owner)
            dialog_label.setWordWrap(True)
            dialog_label.setTextFormat(Qt.PlainText)
            dialog_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            dialog_progress = QProgressBar(owner)
            dialog_progress.setTextVisible(False)
            dialog = QProgressDialog(
                "",
                "",
                0,
                0,
                owner,
            )
            dialog.setWindowTitle(title)
            dialog.setWindowModality(Qt.WindowModal)
            dialog.setAutoClose(False)
            dialog.setAutoReset(False)
            dialog.setMinimumDuration(0)
            dialog.setLabel(dialog_label)
            dialog.setBar(dialog_progress)
            dialog_progress.setValue(0)
            if not cancellable:
                dialog.setCancelButton(None)
            else:
                cancel_button = QPushButton("Cancel", owner)
                dialog.setCancelButton(cancel_button)
                dialog.canceled.connect(context.cancel)
            _configure_progress_dialog(dialog)
            dialog.show()

        ui_state: dict[str, object] = {
            "active": True,
            "dialog": dialog,
            "label": dialog_label,
            "bar": dialog_progress,
        }

        def _clear_progress_surface() -> None:
            ui_state["dialog"] = None
            ui_state["label"] = None
            ui_state["bar"] = None

        def _current_progress_surface() -> tuple[QProgressDialog, QLabel, QProgressBar] | None:
            current_dialog = ui_state.get("dialog")
            current_label = ui_state.get("label")
            current_bar = ui_state.get("bar")
            if current_dialog is None or current_label is None or current_bar is None:
                return None
            if not (
                _qt_object_is_valid(current_dialog)
                and _qt_object_is_valid(current_label)
                and _qt_object_is_valid(current_bar)
            ):
                _clear_progress_surface()
                return None
            return current_dialog, current_label, current_bar

        if dialog is not None:
            dialog.destroyed.connect(_clear_progress_surface)
        if dialog_label is not None:
            dialog_label.destroyed.connect(_clear_progress_surface)
        if dialog_progress is not None:
            dialog_progress.destroyed.connect(_clear_progress_surface)

        def _apply_progress(update: TaskProgressUpdate) -> None:
            if not bool(ui_state.get("active", False)):
                return
            progress_surface = _current_progress_surface()
            if progress_surface is not None:
                current_dialog, current_label, current_bar = progress_surface
                if update.message:
                    current_label.setText(_format_progress_dialog_message(update.message))
                if update.maximum is not None and update.value is not None:
                    current_bar.setMaximum(max(0, int(update.maximum)))
                    current_bar.setValue(max(0, int(update.value)))
                elif update.maximum is not None:
                    current_bar.setMaximum(max(0, int(update.maximum)))
                elif update.value is not None:
                    current_bar.setValue(max(0, int(update.value)))
                _refresh_progress_dialog_height(current_dialog)
            if on_progress is not None:
                on_progress(update)

        def _apply_status(message: str) -> None:
            if not bool(ui_state.get("active", False)):
                return
            progress_surface = _current_progress_surface()
            if progress_surface is not None and message:
                current_dialog, current_label, _current_bar = progress_surface
                current_label.setText(_format_progress_dialog_message(message))
                _refresh_progress_dialog_height(current_dialog)
            if on_status is not None:
                on_status(message)

        def _cleanup() -> None:
            current = self._tasks.pop(task_id, None)
            ui_state["active"] = False
            progress_surface = _current_progress_surface()
            dialog_to_cleanup = progress_surface[0] if progress_surface is not None else None
            _clear_progress_surface()
            if dialog_to_cleanup is None and current is not None:
                candidate_dialog = current.dialog
                if candidate_dialog is not None and _qt_object_is_valid(candidate_dialog):
                    dialog_to_cleanup = candidate_dialog
            if current is not None:
                try:
                    current.thread.started.disconnect(current.worker.run)
                except Exception:
                    pass
                try:
                    current.worker.finished.disconnect(current.thread.quit)
                except Exception:
                    pass
            if dialog_to_cleanup is not None:
                try:
                    dialog_to_cleanup.close()
                except Exception:
                    pass
                try:
                    dialog_to_cleanup.deleteLater()
                except Exception:
                    pass
            thread.deleteLater()
            self.task_state_changed.emit()

        relay = _TaskCallbackRelay(
            progress_handler=_apply_progress,
            status_handler=_apply_status,
            success_before_cleanup_handler=on_success_before_cleanup,
            success_handler=on_success,
            success_after_cleanup_handler=on_success_after_cleanup,
            error_handler=on_error,
            cancelled_handler=on_cancelled,
            finished_handler=on_finished,
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
        # Avoid deleting Python QObject workers inside their own QThread.
        # PySide/Shiboken can crash during wrapper teardown on newer runtimes,
        # so we let the wrapper fall out of scope on the manager thread instead.
        worker.finished.connect(thread.quit)
        thread.finished.connect(relay.handle_cleanup, Qt.QueuedConnection)
        thread.start()
        return task_id

"""Shared Qt widgets and dialog chrome helpers."""

from __future__ import annotations

from time import monotonic

from PySide6.QtCore import QDate, QEvent, Qt
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QCalendarWidget,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.help_content import help_topic_title
from isrc_manager.storage_sizes import (
    clamp_history_storage_budget_mb,
    format_budget_megabytes,
    parse_storage_text_to_megabytes,
)

_MIDDLE_ABBREVIATION_PREFIX_LENGTH = 20
_MIDDLE_ABBREVIATION_SUFFIX_LENGTH = 25
_MIDDLE_ABBREVIATION_THRESHOLD = 60


def _find_theme_owner(widget: QWidget | None):
    current = widget
    while current is not None:
        getter = getattr(current, "_active_custom_qss", None)
        if callable(getter):
            return current
        current = current.parentWidget()
    return None


def _compose_widget_stylesheet(widget: QWidget | None, base_qss: str) -> str:
    qss = (base_qss or "").strip()
    owner = _find_theme_owner(widget)
    extra_qss = ""
    if owner is not None:
        try:
            extra_qss = (owner._active_custom_qss() or "").strip()
        except Exception:
            extra_qss = ""
    if extra_qss:
        if qss:
            return f"{qss}\n\n/* User custom QSS */\n{extra_qss}\n"
        return extra_qss
    return qss


def _resolve_help_host(widget: QWidget | None):
    current = widget
    while current is not None:
        open_help = getattr(current, "open_help_dialog", None)
        if callable(open_help):
            return current
        app = getattr(current, "app", None)
        if app is not None and callable(getattr(app, "open_help_dialog", None)):
            return app
        current = current.parentWidget()
    return None


def _create_round_help_button(
    owner: QWidget, topic_id: str, tooltip: str | None = None
) -> QToolButton:
    button = QToolButton(owner)
    button.setText("?")
    button.setCursor(Qt.PointingHandCursor)
    button.setAutoRaise(False)
    button.setFixedSize(28, 28)
    button.setProperty("role", "helpButton")
    button.setToolTip(tooltip or f"Open help for {help_topic_title(topic_id)}")
    button.setObjectName(f"{topic_id.replace('-', '_')}HelpButton")

    def _open():
        host = _resolve_help_host(owner)
        if host is not None:
            host.open_help_dialog(topic_id=topic_id, parent=owner)

    button.clicked.connect(_open)
    return button


def _standard_container_stylesheet(selector: str, extra_qss: str = "") -> str:
    base_qss = f"""
    {selector} QLabel[role="dialogTitle"] {{
        font-size: 26px;
        font-weight: 700;
    }}
    {selector} QLabel[role="dialogSubtitle"] {{
        font-size: 15px;
    }}
    {selector} QLabel[role="sectionDescription"],
    {selector} QLabel[role="supportingText"],
    {selector} QLabel[role="secondary"],
    {selector} QLabel[role="meta"],
    {selector} QLabel[role="statusText"] {{
    }}
    {selector} QGroupBox {{
        font-size: 15px;
        margin-top: 10px;
    }}
    {selector} QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        font-weight: 600;
    }}
    """
    if extra_qss.strip():
        return f"{base_qss}\n{extra_qss.strip()}\n"
    return base_qss


def _standard_dialog_stylesheet(object_name: str, extra_qss: str = "") -> str:
    return _standard_container_stylesheet(
        f"QDialog#{object_name}",
        extra_qss=extra_qss,
    )


def _apply_standard_dialog_chrome(
    dialog: QDialog, object_name: str, *, extra_qss: str = ""
) -> None:
    dialog.setObjectName(object_name)
    dialog.setProperty("role", "panel")
    dialog.setAttribute(Qt.WA_StyledBackground, True)
    dialog.setStyleSheet(
        _compose_widget_stylesheet(
            dialog,
            _standard_dialog_stylesheet(object_name, extra_qss=extra_qss),
        )
    )


def _apply_standard_widget_chrome(
    widget: QWidget, object_name: str, *, extra_qss: str = ""
) -> None:
    widget.setObjectName(object_name)
    widget.setStyleSheet(
        _compose_widget_stylesheet(
            widget,
            _standard_container_stylesheet(
                f"QWidget#{object_name}",
                extra_qss=extra_qss,
            ),
        )
    )


def _add_standard_dialog_header(
    layout: QVBoxLayout,
    owner: QWidget,
    *,
    title: str,
    subtitle: str | None = None,
    help_topic_id: str | None = None,
) -> tuple[QLabel, QLabel | None]:
    title_row = QHBoxLayout()
    title_row.setSpacing(12)

    title_label = QLabel(title, owner)
    title_label.setProperty("role", "dialogTitle")
    title_row.addWidget(title_label)
    title_row.addStretch(1)
    if help_topic_id:
        title_row.addWidget(_create_round_help_button(owner, help_topic_id), 0, Qt.AlignTop)
    layout.addLayout(title_row)

    subtitle_label = None
    if subtitle:
        subtitle_label = QLabel(subtitle, owner)
        subtitle_label.setProperty("role", "dialogSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)

    return title_label, subtitle_label


def _create_standard_section(
    owner: QWidget,
    title: str,
    description: str | None = None,
) -> tuple[QGroupBox, QVBoxLayout]:
    box = QGroupBox(title, owner)
    box_layout = QVBoxLayout(box)
    box_layout.setContentsMargins(14, 12, 14, 14)
    box_layout.setSpacing(10)
    if description:
        desc_label = QLabel(description, box)
        desc_label.setProperty("role", "sectionDescription")
        desc_label.setWordWrap(True)
        box_layout.addWidget(desc_label)
    return box, box_layout


def _configure_standard_form_layout(form: QFormLayout) -> None:
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)
    form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(10)


def _confirm_destructive_action(
    owner: QWidget | None,
    *,
    title: str,
    prompt: str,
    consequences: list[str] | tuple[str, ...] | None = None,
) -> bool:
    sections = [str(prompt or "").strip()]
    for consequence in consequences or ():
        clean = str(consequence or "").strip()
        if clean:
            sections.append(clean)
    message = "\n\n".join(section for section in sections if section)
    return QMessageBox.question(owner, title, message) == QMessageBox.Yes


def _create_scrollable_dialog_content(
    owner: QWidget,
    *,
    role: str = "workspaceCanvas",
    page: QWidget | None = None,
) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    scroll_parent = page or owner
    scroll_area = QScrollArea(scroll_parent)
    scroll_area.setWidgetResizable(True)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll_area.setFrameShape(QFrame.NoFrame)
    scroll_area.setProperty("role", role)
    scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    viewport = scroll_area.viewport()
    if viewport is not None:
        viewport.setProperty("role", role)

    content = QWidget(scroll_area)
    content.setProperty("role", role)
    content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)

    scroll_area.setWidget(content)

    if page is not None:
        page.setProperty("role", role)
        page_layout = page.layout()
        if page_layout is None:
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(0)
        page_layout.addWidget(scroll_area)

    return scroll_area, content, layout


def _apply_compact_dialog_control_heights(owner: QWidget) -> None:
    for widget in owner.findChildren(QWidget):
        if isinstance(widget, QToolButton) and widget.property("role") == "helpButton":
            continue

        if isinstance(widget, (QLineEdit, QComboBox, QFontComboBox, QSpinBox)):
            target_height = max(widget.minimumHeight(), widget.fontMetrics().lineSpacing() + 16)
            widget.setMinimumHeight(target_height)
            continue

        if isinstance(widget, QPushButton):
            target_height = max(widget.minimumHeight(), widget.fontMetrics().lineSpacing() + 14)
            widget.setMinimumHeight(target_height)


def _apply_dialog_width_constraints(
    dialog: QDialog,
    *,
    min_width: int = 360,
    max_width: int = 500,
) -> None:
    dialog.setMinimumWidth(int(min_width))
    dialog.setMaximumWidth(int(max_width))
    dialog.adjustSize()
    hint = dialog.sizeHint()
    width = min(max(int(hint.width()), int(min_width)), int(max_width))
    dialog.resize(width, int(hint.height()))


def _abbreviate_middle_text(
    value: str | object,
    *,
    threshold: int = _MIDDLE_ABBREVIATION_THRESHOLD,
    prefix_length: int = _MIDDLE_ABBREVIATION_PREFIX_LENGTH,
    suffix_length: int = _MIDDLE_ABBREVIATION_SUFFIX_LENGTH,
) -> str:
    text = str(value or "")
    if not text:
        return ""
    minimum_abbreviated_length = int(prefix_length) + int(suffix_length) + 3
    if len(text) <= max(int(threshold), minimum_abbreviated_length):
        return text
    return f"{text[: int(prefix_length)]}...{text[-int(suffix_length) :]}"


def _prompt_compact_choice_dialog(
    parent: QWidget | None,
    *,
    title: str,
    prompt: str,
    choices: list[tuple[str, str]],
    object_name: str = "compactChoiceDialog",
    ok_text: str = "Continue",
    min_width: int = 320,
    max_width: int = 420,
) -> str | None:
    if not choices:
        return None
    dialog = QDialog(parent)
    dialog.setWindowTitle(str(title or "Choose Option"))
    dialog.setModal(True)
    _apply_standard_dialog_chrome(dialog, object_name)

    root = QVBoxLayout(dialog)
    root.setContentsMargins(16, 16, 16, 16)
    root.setSpacing(12)

    prompt_label = QLabel(str(prompt or ""), dialog)
    prompt_label.setWordWrap(True)
    root.addWidget(prompt_label)

    combo = QComboBox(dialog)
    combo.setMinimumWidth(0)
    combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    for value, label in choices:
        combo.addItem(str(label), str(value))
    root.addWidget(combo)

    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, dialog)
    ok_button = buttons.button(QDialogButtonBox.Ok)
    if ok_button is not None:
        ok_button.setText(str(ok_text or "Continue"))
        ok_button.setAutoDefault(True)
        ok_button.setDefault(True)
    buttons.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    root.addWidget(buttons)

    _apply_compact_dialog_control_heights(dialog)
    _apply_dialog_width_constraints(dialog, min_width=min_width, max_width=max_width)
    if dialog.exec() != QDialog.Accepted:
        return None
    return str(combo.currentData() or "").strip() or None


def _create_action_button_grid(
    owner: QWidget,
    buttons: list[QPushButton],
    *,
    columns: int = 2,
) -> QWidget:
    container = QWidget(owner)
    container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    layout = QGridLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(12)
    layout.setVerticalSpacing(10)
    total_columns = max(1, int(columns or 1))
    for column in range(total_columns):
        layout.setColumnStretch(column, 1)
    for index, button in enumerate(buttons):
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(button, index // total_columns, index % total_columns)
    return container


def _create_action_button_cluster(
    owner: QWidget,
    buttons: list[QPushButton],
    *,
    columns: int = 2,
    min_button_width: int = 160,
    outer_margins: tuple[int, int, int, int] = (2, 2, 2, 2),
    horizontal_spacing: int = 12,
    vertical_spacing: int = 10,
    span_last_row: bool = False,
    lock_minimum_height: bool = True,
) -> QWidget:
    container = QFrame(owner)
    container.setProperty("role", "compactControlGroup")
    container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    layout = QGridLayout(container)
    left, top, right, bottom = outer_margins
    layout.setContentsMargins(left, top, right, bottom)
    layout.setHorizontalSpacing(int(horizontal_spacing))
    layout.setVerticalSpacing(int(vertical_spacing))
    total_columns = max(1, int(columns or 1))
    for column in range(total_columns):
        layout.setColumnStretch(column, 1)
    last_index = len(buttons) - 1
    button_heights: list[int] = []
    for index, button in enumerate(buttons):
        button.setMinimumWidth(max(button.minimumWidth(), int(min_button_width or 0)))
        target_height = max(button.minimumHeight(), button.fontMetrics().lineSpacing() + 14)
        button.setMinimumHeight(target_height)
        button_heights.append(target_height)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row = index // total_columns
        column = index % total_columns
        if (
            span_last_row
            and total_columns > 1
            and index == last_index
            and len(buttons) % total_columns == 1
        ):
            layout.addWidget(button, row, 0, 1, total_columns)
            continue
        layout.addWidget(button, row, column)
    total_rows = ((len(buttons) - 1) // total_columns) + 1 if buttons else 0
    lower_bound_height = 0
    if total_rows and button_heights:
        lower_bound_height = (
            top
            + bottom
            + (max(button_heights) * total_rows)
            + (layout.verticalSpacing() * max(0, total_rows - 1))
        )
    layout.activate()
    container.ensurePolished()
    if lock_minimum_height:
        container.setMinimumHeight(
            max(
                int(lower_bound_height or 0),
                int(container.minimumSizeHint().height()),
                int(container.sizeHint().height()),
            )
        )
    return container


class _WheelIntentMixin:
    """Ignore wheel changes unless the widget is actively focused by the user."""

    def _wheel_has_user_focus(self) -> bool:
        app = QApplication.instance()
        focus_widget = app.focusWidget() if app is not None else None
        if focus_widget is None:
            return False
        if focus_widget is self:
            return True
        if isinstance(focus_widget, QWidget) and self.isAncestorOf(focus_widget):
            return True
        view = getattr(self, "view", None)
        if callable(view):
            try:
                popup = view()
                if popup is not None and popup.isVisible():
                    return True
            except Exception:
                pass
        return False

    def wheelEvent(self, event):
        if self._wheel_has_user_focus():
            super().wheelEvent(event)
            return
        event.ignore()


class FocusWheelComboBox(_WheelIntentMixin, QComboBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)


class FocusWheelSpinBox(_WheelIntentMixin, QSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)


class StorageBudgetSpinBox(FocusWheelSpinBox):
    """Unit-aware spinbox for profile history storage budgets."""

    _REPEAT_WINDOW_SECONDS = 0.35
    _REPEAT_THRESHOLD_MB = 10
    _ACCELERATED_STEP_MB = 100

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAlignment(Qt.AlignRight)
        self._repeat_direction = 0
        self._repeat_moved_mb = 0
        self._last_step_timestamp = 0.0

    def textFromValue(self, value: int) -> str:
        return format_budget_megabytes(int(value or 0))

    def valueFromText(self, text: str) -> int:
        return parse_storage_text_to_megabytes(text)

    def validate(self, text: str, pos: int):
        clean = str(text or "").strip()
        if not clean:
            return (QValidator.Intermediate, text, pos)
        try:
            parse_storage_text_to_megabytes(clean)
        except ValueError:
            lowered = clean.lower().replace(",", ".")
            if (
                lowered.endswith((".", ",", "m", "mb", "g", "gb", "t", "tb"))
                or lowered[-1:].isdigit()
            ):
                return (QValidator.Intermediate, text, pos)
            return (QValidator.Invalid, text, pos)
        return (QValidator.Acceptable, text, pos)

    def stepBy(self, steps: int) -> None:
        direction = 0
        if steps > 0:
            direction = 1
        elif steps < 0:
            direction = -1
        if direction == 0:
            return

        now = monotonic()
        continuing_repeat = (
            direction == self._repeat_direction
            and (now - self._last_step_timestamp) <= self._REPEAT_WINDOW_SECONDS
        )
        if not continuing_repeat:
            self._reset_repeat_state()
            self._repeat_direction = direction

        remaining_steps = abs(int(steps))
        current_value = int(self.value())
        while remaining_steps > 0:
            step_size_mb = 1
            if continuing_repeat and self._repeat_moved_mb >= self._REPEAT_THRESHOLD_MB:
                step_size_mb = self._ACCELERATED_STEP_MB
            current_value = clamp_history_storage_budget_mb(
                current_value + (direction * step_size_mb)
            )
            if continuing_repeat:
                self._repeat_moved_mb += step_size_mb
            remaining_steps -= 1

        self._last_step_timestamp = now
        self.setValue(current_value)

    def focusOutEvent(self, event):
        self._reset_repeat_state()
        super().focusOutEvent(event)

    def keyReleaseEvent(self, event):
        self._reset_repeat_state()
        super().keyReleaseEvent(event)

    def mouseReleaseEvent(self, event):
        self._reset_repeat_state()
        super().mouseReleaseEvent(event)

    def _reset_repeat_state(self) -> None:
        self._repeat_direction = 0
        self._repeat_moved_mb = 0
        self._last_step_timestamp = 0.0


class FocusWheelFontComboBox(_WheelIntentMixin, QFontComboBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)


class FocusWheelCalendarWidget(_WheelIntentMixin, QCalendarWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)

    def showEvent(self, event):
        self._install_calendar_wheel_filter()
        super().showEvent(event)

    def _install_calendar_wheel_filter(self):
        self.installEventFilter(self)
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)

    @staticmethod
    def _find_scroll_area_parent(widget: QWidget | None):
        current = widget
        while current is not None:
            if isinstance(current, QAbstractScrollArea):
                return current
            current = current.parentWidget()
        return None

    def _forward_wheel_to_parent_scroll_area(self, source: QWidget, event) -> bool:
        scroll_area = self._find_scroll_area_parent(source.parentWidget())
        if scroll_area is None:
            return False
        scrollbar = scroll_area.verticalScrollBar()
        if scrollbar is None:
            return False

        pixel_delta = event.pixelDelta().y()
        if pixel_delta:
            scroll_delta = -pixel_delta
        else:
            step = max(24, scrollbar.singleStep())
            scroll_delta = int(-(event.angleDelta().y() / 120.0) * step * 3)
        if not scroll_delta:
            return False

        scrollbar.setValue(scrollbar.value() + scroll_delta)
        return True

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and isinstance(obj, QWidget):
            if self._forward_wheel_to_parent_scroll_area(obj, event):
                event.accept()
            else:
                event.ignore()
            return True
        return super().eventFilter(obj, event)

    def wheelEvent(self, event):
        if self._forward_wheel_to_parent_scroll_area(self, event):
            event.accept()
            return
        event.ignore()


class FocusWheelSlider(_WheelIntentMixin, QSlider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._double_click_reset_value: int | None = None
        self.setFocusPolicy(Qt.StrongFocus)

    def setDoubleClickResetValue(self, value: int | None) -> None:
        self._double_click_reset_value = None if value is None else int(value)

    def mouseDoubleClickEvent(self, event):
        if (
            self._double_click_reset_value is not None
            and hasattr(event, "button")
            and event.button() == Qt.LeftButton
        ):
            reset_value = max(self.minimum(), min(self.maximum(), self._double_click_reset_value))
            self.setValue(reset_value)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class TwoDigitSpinBox(FocusWheelSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAlignment(Qt.AlignRight)

    def textFromValue(self, value: int) -> str:
        try:
            return f"{int(value):02d}"
        except Exception:
            return str(value)


class DatePickerDialog(QDialog):
    """Simple calendar picker for custom 'date' fields."""

    def __init__(
        self, parent=None, initial_iso_date: str | None = None, title: str = "Pick a date"
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(500, 460)
        self.setMinimumSize(460, 420)
        _apply_standard_dialog_chrome(self, "datePickerDialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        _add_standard_dialog_header(
            layout,
            self,
            title=title,
            subtitle="Choose a calendar date or clear the field completely.",
            help_topic_id="metadata-dates",
        )

        calendar_box, calendar_layout = _create_standard_section(self, "Calendar")
        self.calendar = FocusWheelCalendarWidget()
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.calendar.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        if initial_iso_date:
            selected_date = QDate.fromString(initial_iso_date, "yyyy-MM-dd")
            self.calendar.setSelectedDate(
                selected_date if selected_date.isValid() else QDate.currentDate()
            )
        else:
            self.calendar.setSelectedDate(QDate.currentDate())
        calendar_layout.addWidget(self.calendar, 0, Qt.AlignCenter)
        layout.addWidget(calendar_box, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal,
            self,
        )
        self.btn_clear = buttons.addButton("Clear", QDialogButtonBox.ResetRole)
        self.btn_ok = buttons.button(QDialogButtonBox.Ok)
        self.btn_cancel = buttons.button(QDialogButtonBox.Cancel)
        if self.btn_ok is not None:
            self.btn_ok.setDefault(True)
        if self.btn_cancel is not None:
            self.btn_cancel.setAutoDefault(False)
        layout.addWidget(buttons)

        self._cleared = False
        self.btn_clear.clicked.connect(self._on_clear)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def _on_clear(self):
        self._cleared = True
        self.accept()

    def selected_iso(self) -> str | None:
        if self._cleared:
            return None
        return self.calendar.selectedDate().toString("yyyy-MM-dd")

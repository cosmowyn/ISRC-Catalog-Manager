"""Shared Qt widgets and dialog chrome helpers."""

from __future__ import annotations

from PySide6.QtCore import QDate, QEvent, Qt
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
        font-weight: 600;
        margin-top: 10px;
    }}
    {selector} QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
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
    box_layout.setContentsMargins(14, 18, 14, 14)
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


def _create_scrollable_dialog_content(
    owner: QWidget,
) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    scroll_area = QScrollArea(owner)
    scroll_area.setWidgetResizable(True)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll_area.setFrameShape(QFrame.NoFrame)
    scroll_area.setProperty("role", "workspaceCanvas")
    scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    viewport = scroll_area.viewport()
    if viewport is not None:
        viewport.setProperty("role", "workspaceCanvas")

    content = QWidget(scroll_area)
    content.setProperty("role", "workspaceCanvas")
    content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)

    scroll_area.setWidget(content)
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
        self.setFocusPolicy(Qt.StrongFocus)


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

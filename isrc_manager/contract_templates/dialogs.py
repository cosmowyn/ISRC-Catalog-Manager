"""Workspace panels for contract template placeholder tools."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # pragma: no cover - environment-specific fallback
    QWebEnginePage = None
    QWebEngineView = None

from isrc_manager.external_launch import open_external_path, open_external_url
from isrc_manager.file_storage import STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE
from isrc_manager.ui_common import (
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_widget_chrome,
    _configure_standard_form_layout,
    _confirm_destructive_action,
    _create_action_button_cluster,
    _create_standard_section,
)

from .ingestion import detect_template_source_format
from .models import (
    ContractTemplateCatalogEntry,
    ContractTemplateDraftPayload,
    ContractTemplateDraftRecord,
    ContractTemplateFormAutoField,
    ContractTemplateFormDefinition,
    ContractTemplateFormManualField,
    ContractTemplateFormSelectorField,
    ContractTemplateOutputArtifactRecord,
    ContractTemplatePayload,
    ContractTemplatePlaceholderRecord,
    ContractTemplateRecord,
    ContractTemplateResolvedSnapshotRecord,
    ContractTemplateRevisionPayload,
    ContractTemplateRevisionRecord,
)


def _clean_text(value: object | None) -> str | None:
    clean = str(value or "").strip()
    return clean or None


def _serialize_dock_state(state) -> str:
    if state is None or not hasattr(state, "isEmpty") or state.isEmpty():
        return ""
    try:
        return bytes(state.toBase64()).decode("ascii")
    except Exception:
        return ""


def _deserialize_dock_state(value):
    if value is None:
        return None
    clean = str(value or "").strip()
    if not clean:
        return None
    try:
        from PySide6.QtCore import QByteArray

        return QByteArray.fromBase64(clean.encode("ascii"))
    except Exception:
        return None


def _dock_area_value(area) -> int:
    try:
        return int(getattr(area, "value", area))
    except Exception:
        return 0


@dataclass
class _PreviewCandidate:
    generation: int
    root_path: Path
    html_path: Path


class _ContractTemplatePreviewPage(QWebEnginePage if QWebEnginePage is not None else object):
    """Blocks in-place external navigation for the live preview surface."""

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):  # pragma: no cover - Qt
        if QWebEnginePage is None:
            return True
        scheme = str(url.scheme() or "").strip().lower()
        if url.isLocalFile() or scheme in {
            "",
            "about",
            "blob",
            "chrome",
            "chrome-error",
            "data",
            "devtools",
            "qrc",
        }:
            return super().acceptNavigationRequest(url, navigation_type, is_main_frame)
        if is_main_frame:
            open_external_url(
                url,
                source="ContractTemplatePreviewPage",
                metadata={
                    "is_main_frame": bool(is_main_frame),
                    "navigation_type": str(navigation_type),
                },
            )
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)


class _InteractiveHtmlPreviewView(QWebEngineView if QWebEngineView is not None else QWidget):
    """QWebEngine preview surface with fit, zoom, and pan affordances."""

    zoom_percent_changed = Signal(int)

    def __init__(self, parent=None):
        if QWebEngineView is None:  # pragma: no cover - runtime guard
            super().__init__(parent)
            return
        super().__init__(parent)
        self._gesture_platform = (QApplication.platformName() or "").strip().lower()
        self._user_zoomed = False
        self._space_pan_active = False
        self._mouse_pan_active = False
        self._last_pan_pos = QPoint()
        self._document_css_width = 0.0
        self._fit_measure_serial = 0
        self._fit_measure_timer = QTimer(self)
        self._fit_measure_timer.setSingleShot(True)
        self._fit_measure_timer.timeout.connect(self._measure_and_apply_fit)
        self.setObjectName("contractTemplateHtmlPreviewView")
        self.setProperty("role", "workspaceCanvas")
        self.setPage(_ContractTemplatePreviewPage(self))
        self.page().contentsSizeChanged.connect(self._on_contents_size_changed)
        self.loadFinished.connect(self._on_load_finished)
        self.setZoomFactor(1.0)

    def current_zoom_percent(self) -> int:
        if QWebEngineView is None:  # pragma: no cover - runtime guard
            return 100
        return max(10, min(400, int(round(self.zoomFactor() * 100.0))))

    def set_zoom_percent(self, percent: int, *, user_initiated: bool = False) -> None:
        if QWebEngineView is None:  # pragma: no cover - runtime guard
            return
        clamped = max(10, min(400, int(round(percent))))
        if user_initiated:
            self._user_zoomed = True
        self.setZoomFactor(clamped / 100.0)
        self.zoom_percent_changed.emit(clamped)

    def reset_to_fit(self) -> None:
        if QWebEngineView is None:  # pragma: no cover - runtime guard
            return
        self._user_zoomed = False
        self._schedule_fit(delay_ms=0)

    def mark_programmatic_reload(self) -> None:
        if QWebEngineView is None:  # pragma: no cover - runtime guard
            return
        self._fit_measure_timer.stop()
        self._fit_measure_serial += 1

    def _schedule_fit(self, *, delay_ms: int = 90) -> None:
        if QWebEngineView is None:  # pragma: no cover - runtime guard
            return
        if self._user_zoomed:
            return
        self._fit_measure_serial += 1
        self._fit_measure_timer.start(max(0, int(delay_ms)))

    def _on_contents_size_changed(self, _size) -> None:  # pragma: no cover - Qt callback
        self._schedule_fit(delay_ms=140)

    def _on_load_finished(self, ok: bool) -> None:  # pragma: no cover - Qt callback
        if ok and not self._user_zoomed:
            self._schedule_fit(delay_ms=140)

    def _fit_zoom_percent(self) -> int:
        if QWebEngineView is None:  # pragma: no cover - runtime guard
            return 100
        contents_width = max(1.0, float(self._document_css_width or 0.0))
        viewport_width = max(1.0, float(self.contentsRect().width() - 40))
        ratio = min(1.0, viewport_width / contents_width) if contents_width > 0 else 1.0
        return max(10, min(100, int(round(ratio * 100.0))))

    def _apply_fit_if_needed(self) -> None:
        if QWebEngineView is None:  # pragma: no cover - runtime guard
            return
        if self._user_zoomed:
            return
        target_percent = self._fit_zoom_percent()
        if abs(target_percent - self.current_zoom_percent()) <= 1:
            return
        self.set_zoom_percent(target_percent, user_initiated=False)

    def _measure_and_apply_fit(self) -> None:
        if QWebEngineView is None:  # pragma: no cover - runtime guard
            return
        if self._user_zoomed:
            return
        request_serial = int(self._fit_measure_serial)
        script = """
            (function() {
                const doc = document.documentElement || {};
                const body = document.body || {};
                return Math.max(
                    Number(doc.scrollWidth || 0),
                    Number(doc.offsetWidth || 0),
                    Number(body.scrollWidth || 0),
                    Number(body.offsetWidth || 0)
                );
            })();
        """

        def _apply_measured_width(result) -> None:
            if QWebEngineView is None:  # pragma: no cover - runtime guard
                return
            if request_serial != self._fit_measure_serial or self._user_zoomed:
                return
            try:
                measured_width = float(result or 0.0)
            except Exception:
                measured_width = 0.0
            if measured_width <= 0:
                try:
                    measured_width = float(self.page().contentsSize().width()) / max(
                        0.1,
                        float(self.zoomFactor()),
                    )
                except Exception:
                    measured_width = 0.0
            if measured_width > 0:
                self._document_css_width = measured_width
            self._apply_fit_if_needed()

        self.page().runJavaScript(script, _apply_measured_width)

    @staticmethod
    def _zoom_steps_from_event(event) -> int:
        pixel_delta = event.pixelDelta()
        angle_delta = event.angleDelta()
        if not pixel_delta.isNull():
            dominant = (
                pixel_delta.y() if abs(pixel_delta.y()) >= abs(pixel_delta.x()) else pixel_delta.x()
            )
            return int(round(dominant / 40.0))
        if not angle_delta.isNull():
            dominant = (
                angle_delta.y() if abs(angle_delta.y()) >= abs(angle_delta.x()) else angle_delta.x()
            )
            return int(round(dominant / 120.0))
        return 0

    def _scroll_by(self, dx: int, dy: int) -> None:
        if QWebEngineView is None:  # pragma: no cover - runtime guard
            return
        self.page().runJavaScript(f"window.scrollBy({int(dx)}, {int(dy)});")

    def keyPressEvent(self, event):  # pragma: no cover - Qt input
        if event.key() == Qt.Key_Space:
            self._space_pan_active = True
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):  # pragma: no cover - Qt input
        if event.key() == Qt.Key_Space:
            self._space_pan_active = False
            event.accept()
            return
        super().keyReleaseEvent(event)

    def wheelEvent(self, event):  # pragma: no cover - Qt input
        modifiers = event.modifiers() if hasattr(event, "modifiers") else Qt.NoModifier
        if modifiers & (Qt.ControlModifier | Qt.MetaModifier):
            steps = self._zoom_steps_from_event(event)
            if steps:
                self.set_zoom_percent(
                    self.current_zoom_percent() + (int(steps) * 10),
                    user_initiated=True,
                )
                event.accept()
                return
        super().wheelEvent(event)

    def mousePressEvent(self, event):  # pragma: no cover - Qt input
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and self._space_pan_active
        ):
            self._mouse_pan_active = True
            self._last_pan_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # pragma: no cover - Qt input
        if self._mouse_pan_active:
            current_pos = event.position().toPoint()
            delta = current_pos - self._last_pan_pos
            self._last_pan_pos = current_pos
            if not delta.isNull():
                self._scroll_by(-delta.x(), -delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # pragma: no cover - Qt input
        if self._mouse_pan_active and event.button() in {Qt.LeftButton, Qt.MiddleButton}:
            self._mouse_pan_active = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # pragma: no cover - Qt input
        if event.button() == Qt.LeftButton:
            self.reset_to_fit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def event(self, event):  # pragma: no cover - Qt input
        if event.type() == QEvent.NativeGesture:
            gesture_type = event.gestureType() if hasattr(event, "gestureType") else None
            if gesture_type == Qt.ZoomNativeGesture:
                value = float(event.value() if hasattr(event, "value") else 0.0)
                if abs(value) > 0.0001:
                    self.set_zoom_percent(
                        int(round(self.current_zoom_percent() * (1.0 + value))),
                        user_initiated=True,
                    )
                    event.accept()
                    return True
            if gesture_type == Qt.SmartZoomNativeGesture:
                self.reset_to_fit()
                event.accept()
                return True
        return super().event(event)

    def resizeEvent(self, event):  # pragma: no cover - Qt callback
        super().resizeEvent(event)
        if not self._user_zoomed:
            self._schedule_fit(delay_ms=120)


class _WorkspaceDockTitleBar(QWidget):
    """Custom dock title bar with quick placement controls."""

    def __init__(self, host: "_DockableWorkspaceTab", dock: QDockWidget):
        super().__init__(dock)
        self.host = host
        self.dock = dock
        self.setObjectName(f"{dock.objectName()}TitleBar")
        self.setProperty("role", "dockTitleBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.title_label = QLabel(dock.windowTitle(), self)
        self.title_label.setObjectName(f"{dock.objectName()}TitleLabel")
        self.title_label.setProperty("role", "dockTitle")
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.title_label, 1)

        self.options_button = QPushButton("Dock", self)
        self.options_button.setObjectName(f"{dock.objectName()}OptionsButton")
        self.options_button.setProperty("role", "dockControlButton")
        self.options_button.setAutoDefault(False)
        self.options_menu = QMenu(self.options_button)
        self.options_menu.setObjectName(f"{dock.objectName()}OptionsMenu")
        self.options_button.setMenu(self.options_menu)
        layout.addWidget(self.options_button, 0)

        self._move_left_action = self.options_menu.addAction("Dock Left")
        self._move_left_action.triggered.connect(
            lambda: self.host.move_dock_to_area(self.dock, Qt.LeftDockWidgetArea)
        )
        self._move_right_action = self.options_menu.addAction("Dock Right")
        self._move_right_action.triggered.connect(
            lambda: self.host.move_dock_to_area(self.dock, Qt.RightDockWidgetArea)
        )
        self._move_top_action = self.options_menu.addAction("Dock Top")
        self._move_top_action.triggered.connect(
            lambda: self.host.move_dock_to_area(self.dock, Qt.TopDockWidgetArea)
        )
        self._move_bottom_action = self.options_menu.addAction("Dock Bottom")
        self._move_bottom_action.triggered.connect(
            lambda: self.host.move_dock_to_area(self.dock, Qt.BottomDockWidgetArea)
        )
        self.options_menu.addSeparator()
        self._move_up_action = self.options_menu.addAction("Move Up In Stack")
        self._move_up_action.triggered.connect(lambda: self.host.move_dock_in_stack(self.dock, -1))
        self._move_down_action = self.options_menu.addAction("Move Down In Stack")
        self._move_down_action.triggered.connect(lambda: self.host.move_dock_in_stack(self.dock, 1))
        self.options_menu.addSeparator()
        self._float_action = self.options_menu.addAction("Float Panel")
        self._float_action.triggered.connect(lambda: self.host.float_dock(self.dock))
        self._hide_action = self.options_menu.addAction("Hide Panel")
        self._hide_action.triggered.connect(lambda: self.host.hide_dock(self.dock))
        self.options_menu.addSeparator()
        self._reset_action = self.options_menu.addAction("Reset Workspace Layout")
        self._reset_action.triggered.connect(self.host.reset_to_default_layout)
        self.options_menu.aboutToShow.connect(self._refresh_menu_state)

        dock.windowTitleChanged.connect(self.title_label.setText)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _refresh_menu_state(self) -> None:
        unlocked = not bool(self.host._locked)
        for action in (
            self._move_left_action,
            self._move_right_action,
            self._move_top_action,
            self._move_bottom_action,
            self._float_action,
            self._hide_action,
        ):
            action.setEnabled(unlocked)
        self._move_up_action.setEnabled(
            unlocked and self.host.can_move_dock_in_stack(self.dock, -1)
        )
        self._move_down_action.setEnabled(
            unlocked and self.host.can_move_dock_in_stack(self.dock, 1)
        )

    def _show_context_menu(self, position) -> None:
        self._refresh_menu_state()
        self.options_menu.exec(self.mapToGlobal(position))

    def mousePressEvent(self, event):  # pragma: no cover - drag passthrough
        event.ignore()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # pragma: no cover - drag passthrough
        event.ignore()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # pragma: no cover - drag passthrough
        event.ignore()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # pragma: no cover - drag passthrough
        event.ignore()
        super().mouseDoubleClickEvent(event)


class _DockableWorkspaceTab(QMainWindow):
    """Embedded dock host for one top-level Contract Templates tab."""

    def __init__(
        self,
        *,
        tab_key: str,
        host_object_name: str,
        reset_handler,
        layout_changed_handler,
        parent=None,
    ):
        super().__init__(parent)
        self.tab_key = str(tab_key)
        self._reset_handler = reset_handler
        self._layout_changed_handler = layout_changed_handler
        self._docks: list[QDockWidget] = []
        self._pending_state: dict[str, object] | None = None
        self._locked = True
        self._applying_layout_state = False
        self._compacting_layout = False
        self.main_window = self
        self.setObjectName(host_object_name)
        self.setProperty("role", "workspaceCanvas")

        self.chrome_row = QWidget(self)
        self.chrome_row.setObjectName(f"{host_object_name}Chrome")
        self.chrome_row.setProperty("role", "compactControlGroup")
        chrome_layout = QHBoxLayout(self.chrome_row)
        chrome_layout.setContentsMargins(10, 8, 10, 8)
        chrome_layout.setSpacing(8)

        self.lock_layout_button = QPushButton("Unlock Layout", self.chrome_row)
        self.lock_layout_button.setObjectName(f"{host_object_name}LockButton")
        self.lock_layout_button.clicked.connect(self._toggle_locked_state)
        chrome_layout.addWidget(self.lock_layout_button, 0)

        self.panels_button = QToolButton(self.chrome_row)
        self.panels_button.setObjectName(f"{host_object_name}PanelsButton")
        self.panels_button.setText("Panels")
        self.panels_button.setPopupMode(QToolButton.InstantPopup)
        self.panels_menu = QMenu(self.panels_button)
        self.panels_menu.setObjectName(f"{host_object_name}PanelsMenu")
        self.panels_button.setMenu(self.panels_menu)
        chrome_layout.addWidget(self.panels_button, 0)

        self.reset_layout_button = QPushButton("Reset Layout", self.chrome_row)
        self.reset_layout_button.setObjectName(f"{host_object_name}ResetButton")
        self.reset_layout_button.clicked.connect(self.reset_to_default_layout)
        chrome_layout.addWidget(self.reset_layout_button, 0)
        chrome_layout.addStretch(1)
        self.setMenuWidget(self.chrome_row)

        self.setDockNestingEnabled(True)
        self.setDockOptions(QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks)
        for area in (
            Qt.LeftDockWidgetArea,
            Qt.RightDockWidgetArea,
            Qt.TopDockWidgetArea,
            Qt.BottomDockWidgetArea,
        ):
            self.setTabPosition(area, QTabWidget.North)
        central = QWidget(self)
        central.setObjectName(f"{host_object_name}Central")
        central.setProperty("role", "workspaceCanvas")
        self.setCentralWidget(central)

        self._compact_layout_timer = QTimer(self)
        self._compact_layout_timer.setSingleShot(True)
        self._compact_layout_timer.timeout.connect(self._compact_empty_dock_space)

    def register_docks(self, docks: list[QDockWidget]) -> None:
        self._docks = list(docks)
        self.panels_menu.clear()
        for index, dock in enumerate(self._docks):
            dock.setProperty("dockOrderHint", index)
            dock.setProperty("lastDockArea", _dock_area_value(self.dockWidgetArea(dock)))
            dock.setTitleBarWidget(_WorkspaceDockTitleBar(self, dock))
            toggle_action = dock.toggleViewAction()
            self.panels_menu.addAction(toggle_action)
            dock.dockLocationChanged.connect(
                lambda *_args, _dock=dock: self._on_dock_layout_event(_dock)
            )
            dock.topLevelChanged.connect(
                lambda *_args, _dock=dock: self._on_dock_layout_event(_dock)
            )
            dock.visibilityChanged.connect(
                lambda *_args, _dock=dock: self._on_dock_layout_event(_dock)
            )
        self._refresh_dock_order_hints()
        self._apply_lock_state(notify=False)
        self._apply_pending_state_if_ready()

    def capture_layout_state(self) -> dict[str, object]:
        if self._docks:
            self._pending_state = {
                "dock_state_b64": _serialize_dock_state(self.main_window.saveState(1)),
                "layout_locked": bool(self._locked),
            }
        return dict(self._pending_state or {"dock_state_b64": "", "layout_locked": True})

    def restore_layout_state(self, state: dict[str, object] | None) -> None:
        normalized = {
            "dock_state_b64": str((state or {}).get("dock_state_b64") or ""),
            "layout_locked": bool((state or {}).get("layout_locked", True)),
        }
        self._pending_state = normalized
        self._apply_pending_state_if_ready()

    def reset_to_default_layout(self) -> None:
        self._applying_layout_state = True
        try:
            if callable(self._reset_handler):
                self._reset_handler()
            self._pending_state = None
            self.set_locked(True)
        finally:
            self._applying_layout_state = False
        self._queue_layout_compaction()
        self._notify_layout_changed()

    def set_locked(self, locked: bool) -> None:
        self._locked = bool(locked)
        self._apply_lock_state(notify=True)

    def _toggle_locked_state(self) -> None:
        self.set_locked(not self._locked)

    def _apply_lock_state(self, *, notify: bool) -> None:
        features = (
            QDockWidget.NoDockWidgetFeatures
            if self._locked
            else (
                QDockWidget.DockWidgetClosable
                | QDockWidget.DockWidgetMovable
                | QDockWidget.DockWidgetFloatable
            )
        )
        for dock in self._docks:
            dock.setFeatures(features)
        self.lock_layout_button.setText("Unlock Layout" if self._locked else "Lock Layout")
        if notify:
            self._notify_layout_changed()

    def _apply_pending_state_if_ready(self) -> None:
        if not self._docks or not self._pending_state:
            return
        self._locked = bool(self._pending_state.get("layout_locked", True))
        self._applying_layout_state = True
        for dock in self._docks:
            dock.setFeatures(
                QDockWidget.DockWidgetClosable
                | QDockWidget.DockWidgetMovable
                | QDockWidget.DockWidgetFloatable
            )
        dock_state = _deserialize_dock_state(self._pending_state.get("dock_state_b64"))
        try:
            restored_state = False
            if (
                dock_state is not None
                and hasattr(dock_state, "isEmpty")
                and not dock_state.isEmpty()
            ):
                try:
                    restored_state = bool(self.main_window.restoreState(dock_state, 1))
                except Exception:
                    restored_state = False
            if dock_state is not None and not restored_state and callable(self._reset_handler):
                self._reset_handler()
            self._apply_lock_state(notify=False)
        finally:
            self._applying_layout_state = False
        self._refresh_dock_order_hints()
        self._queue_layout_compaction()

    def _notify_layout_changed(self) -> None:
        if callable(self._layout_changed_handler):
            self._layout_changed_handler()

    def move_dock_to_area(self, dock: QDockWidget, area) -> None:
        if self._locked or dock not in self._docks:
            return
        if dock.isFloating():
            dock.setFloating(False)
        dock.show()
        self.addDockWidget(area, dock)
        dock.setProperty("lastDockArea", _dock_area_value(area))
        self._queue_layout_compaction()
        self._notify_layout_changed()

    def can_move_dock_in_stack(self, dock: QDockWidget, step: int) -> bool:
        if dock not in self._docks or dock.isFloating():
            return False
        area = self.dockWidgetArea(dock)
        groups = self._ordered_visible_area_groups(area)
        for group in groups:
            if dock not in group:
                continue
            target_index = group.index(dock) + int(step)
            return 0 <= target_index < len(group)
        return False

    def move_dock_in_stack(self, dock: QDockWidget, step: int) -> None:
        if self._locked or dock not in self._docks or dock.isFloating():
            return
        area = self.dockWidgetArea(dock)
        groups = self._ordered_visible_area_groups(area)
        for group in groups:
            if dock not in group:
                continue
            current_index = group.index(dock)
            target_index = current_index + int(step)
            if not (0 <= target_index < len(group)):
                return
            group[current_index], group[target_index] = group[target_index], group[current_index]
            self._applying_layout_state = True
            try:
                self._rebuild_area_groups(area, groups)
            finally:
                self._applying_layout_state = False
            self._queue_layout_compaction()
            self._notify_layout_changed()
            return

    def float_dock(self, dock: QDockWidget) -> None:
        if self._locked or dock not in self._docks:
            return
        dock.show()
        dock.setFloating(True)
        self._notify_layout_changed()

    def hide_dock(self, dock: QDockWidget) -> None:
        if self._locked or dock not in self._docks:
            return
        dock.hide()
        self._queue_layout_compaction()
        self._notify_layout_changed()

    def _on_dock_layout_event(self, dock: QDockWidget) -> None:
        if dock in self._docks and not dock.isFloating():
            try:
                dock.setProperty("lastDockArea", _dock_area_value(self.dockWidgetArea(dock)))
            except Exception:
                pass
        self._refresh_dock_order_hints()
        self._queue_layout_compaction()
        self._notify_layout_changed()

    def _queue_layout_compaction(self) -> None:
        if self._applying_layout_state or self._compacting_layout:
            return
        self._compact_layout_timer.start(0)

    def _compact_empty_dock_space(self) -> None:
        if self._applying_layout_state or self._compacting_layout:
            return
        self._compacting_layout = True
        try:
            for area in (
                Qt.LeftDockWidgetArea,
                Qt.RightDockWidgetArea,
                Qt.TopDockWidgetArea,
                Qt.BottomDockWidgetArea,
            ):
                self._compact_area(area)
        finally:
            self._compacting_layout = False

    def _compact_area(self, area) -> None:
        groups = self._ordered_visible_area_groups(area)
        if not groups:
            return
        if not self._area_has_gaps(area, groups):
            return
        self._rebuild_area_groups(area, groups)

    def _ordered_visible_area_groups(self, area) -> list[list[QDockWidget]]:
        visible_docks = [
            dock
            for dock in self._docks
            if dock.isVisible() and not dock.isFloating() and self.dockWidgetArea(dock) == area
        ]
        if not visible_docks:
            return []
        if any(
            peer in visible_docks and peer.isVisible()
            for dock in visible_docks
            for peer in self.tabifiedDockWidgets(dock)
        ):
            return []
        primary_is_x = area in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea)

        def primary_coord(dock: QDockWidget) -> int:
            return dock.geometry().x() if primary_is_x else dock.geometry().y()

        def secondary_coord(dock: QDockWidget) -> int:
            return dock.geometry().y() if primary_is_x else dock.geometry().x()

        ordered = sorted(
            visible_docks,
            key=lambda dock: (
                primary_coord(dock),
                secondary_coord(dock),
                int(dock.property("dockOrderHint") or 0),
            ),
        )
        groups: list[list[QDockWidget]] = []
        group_anchors: list[int] = []
        tolerance = 24
        for dock in ordered:
            coord = int(primary_coord(dock))
            placed = False
            for index, anchor in enumerate(group_anchors):
                if abs(coord - anchor) <= tolerance:
                    groups[index].append(dock)
                    count = len(groups[index])
                    group_anchors[index] = int(round(((anchor * (count - 1)) + coord) / count))
                    placed = True
                    break
            if not placed:
                groups.append([dock])
                group_anchors.append(coord)
        for group in groups:
            group.sort(
                key=lambda dock: (
                    secondary_coord(dock),
                    primary_coord(dock),
                    int(dock.property("dockOrderHint") or 0),
                )
            )
        groups.sort(
            key=lambda group: (
                primary_coord(group[0]),
                secondary_coord(group[0]),
                int(group[0].property("dockOrderHint") or 0),
            )
        )
        return groups

    def _area_has_gaps(self, area, groups: list[list[QDockWidget]]) -> bool:
        if not groups:
            return False
        primary_is_x = area in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea)

        def primary_start(dock: QDockWidget) -> int:
            return dock.geometry().x() if primary_is_x else dock.geometry().y()

        def primary_end(dock: QDockWidget) -> int:
            return dock.geometry().right() if primary_is_x else dock.geometry().bottom()

        def secondary_start(dock: QDockWidget) -> int:
            return dock.geometry().y() if primary_is_x else dock.geometry().x()

        def secondary_end(dock: QDockWidget) -> int:
            return dock.geometry().bottom() if primary_is_x else dock.geometry().right()

        threshold = 16
        secondary_origin = 0
        menu_widget = self.menuWidget()
        if primary_is_x and isinstance(menu_widget, QWidget):
            secondary_origin = max(0, menu_widget.geometry().bottom() + 1)
        for group in groups:
            if secondary_start(group[0]) - secondary_origin > threshold:
                return True
            if any(
                secondary_start(group[index]) - secondary_end(group[index - 1]) - 1 > threshold
                for index in range(1, len(group))
            ):
                return True
        for index in range(1, len(groups)):
            previous_end = max(primary_end(dock) for dock in groups[index - 1])
            current_start = min(primary_start(dock) for dock in groups[index])
            if current_start - previous_end - 1 > threshold:
                return True
        return False

    def _rebuild_area_groups(self, area, groups: list[list[QDockWidget]]) -> None:
        if not groups:
            return
        split_between_groups = (
            Qt.Horizontal
            if area in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea)
            else Qt.Vertical
        )
        split_within_group = (
            Qt.Vertical
            if area in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea)
            else Qt.Horizontal
        )
        for group in groups:
            for dock in group:
                dock.show()
                if dock.isFloating():
                    dock.setFloating(False)
        first_group = groups[0]
        self.addDockWidget(area, first_group[0])
        previous = first_group[0]
        for dock in first_group[1:]:
            self.splitDockWidget(previous, dock, split_within_group)
            previous = dock
        previous_group_anchor = first_group[0]
        for group in groups[1:]:
            self.splitDockWidget(previous_group_anchor, group[0], split_between_groups)
            previous = group[0]
            for dock in group[1:]:
                self.splitDockWidget(previous, dock, split_within_group)
                previous = dock
            previous_group_anchor = group[0]
        self._refresh_dock_order_hints(groups)

    def _refresh_dock_order_hints(
        self, groups_by_area: dict[int, list[list[QDockWidget]]] | None = None
    ) -> None:
        sequence = 0
        for area in (
            Qt.LeftDockWidgetArea,
            Qt.RightDockWidgetArea,
            Qt.TopDockWidgetArea,
            Qt.BottomDockWidgetArea,
        ):
            groups = (
                groups_by_area.get(area, [])
                if isinstance(groups_by_area, dict)
                else self._ordered_visible_area_groups(area)
            )
            for group in groups:
                for dock in group:
                    dock.setProperty("dockOrderHint", sequence)
                    sequence += 1


class _FillHtmlPreviewController(QWidget):
    """Owns transient live HTML preview rendering and stale/current transitions."""

    def __init__(self, panel: "ContractTemplateWorkspacePanel", parent=None):
        super().__init__(parent)
        self.panel = panel
        self._latest_generation = 0
        self._inflight_generation: int | None = None
        self._awaiting_load_generation: int | None = None
        self._latest_requested_reason = ""
        self._current_revision_id: int | None = None
        self._latest_payload: dict[str, object] | None = None
        self._active_candidate: _PreviewCandidate | None = None
        self._active_tree: Path | None = None
        self._pending_candidate: _PreviewCandidate | None = None
        self._stale = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._start_refresh_if_idle)
        if self.panel.fill_html_preview_view is not None:
            self.panel.fill_html_preview_view.loadFinished.connect(self._on_view_load_finished)

    def initialize(self) -> None:
        export_service = self.panel._export_service()
        prune = getattr(export_service, "prune_html_preview_sessions", None)
        if callable(prune):
            prune()

    def cleanup(self) -> None:
        self._refresh_timer.stop()
        if self._pending_candidate is not None:
            self._delete_tree(self._pending_candidate.root_path)
            self._pending_candidate = None
        if self._active_tree is not None:
            self._delete_tree(self._active_tree)
            self._active_tree = None

    def set_revision_context(self, revision_id: int | None) -> None:
        self._current_revision_id = int(revision_id) if revision_id is not None else None

    def mark_stale(self, message: str | None = None) -> None:
        self._stale = True
        stale_label = getattr(self.panel, "fill_preview_stale_label", None)
        if isinstance(stale_label, QLabel):
            stale_label.setVisible(True)
            stale_label.setText(message or "Preview stale")
        status = getattr(self.panel, "fill_preview_status_label", None)
        if isinstance(status, QLabel) and message:
            status.setText(message)

    def clear(self, *, keep_status: bool = False) -> None:
        self._refresh_timer.stop()
        self._latest_payload = None
        self._latest_requested_reason = ""
        self._latest_generation += 1
        self._inflight_generation = None
        self._awaiting_load_generation = None
        if self.panel.fill_html_preview_view is not None:
            self.panel.fill_html_preview_view.setHtml("")
        if self._pending_candidate is not None:
            self._delete_tree(self._pending_candidate.root_path)
            self._pending_candidate = None
        if self._active_tree is not None:
            self._delete_tree(self._active_tree)
            self._active_tree = None
        self._stale = False
        stale_label = getattr(self.panel, "fill_preview_stale_label", None)
        if isinstance(stale_label, QLabel):
            stale_label.setVisible(False)
            stale_label.setText("Preview stale")
        if not keep_status and hasattr(self.panel, "fill_preview_status_label"):
            self.panel.fill_preview_status_label.setText(
                "HTML preview becomes available when the selected revision is a native HTML template."
            )

    def request_refresh(self, *, reason: str, delay_ms: int = 180) -> None:
        view = self.panel.fill_html_preview_view
        if view is None or QWebEngineView is None:
            return
        revision_id = self._current_revision_id
        if revision_id is None:
            return
        self._latest_generation += 1
        self._latest_payload = dict(self.panel.current_fill_state() or {})
        self._latest_requested_reason = str(reason or "").strip()
        self.mark_stale("Preview stale. Refreshing current draft state...")
        self._refresh_timer.start(max(0, int(delay_ms)))

    def _start_refresh_if_idle(self) -> None:
        if self._inflight_generation is not None:
            return
        revision_id = self._current_revision_id
        export_service = self.panel._export_service()
        view = self.panel.fill_html_preview_view
        if revision_id is None or export_service is None or view is None:
            return
        generation = int(self._latest_generation)
        self._inflight_generation = generation
        payload = dict(self._latest_payload or {})
        try:
            session_root = export_service.create_html_preview_session_root()
            root_path, html_path, _warnings = export_service.materialize_html_preview_session(
                revision_id=revision_id,
                editable_payload=payload,
                session_root=session_root,
            )
        except Exception as exc:
            self._inflight_generation = None
            self.mark_stale("Preview stale. Latest refresh failed.")
            self.panel.fill_preview_status_label.setText(f"Unable to refresh HTML preview: {exc}")
            return
        candidate = _PreviewCandidate(
            generation=generation,
            root_path=Path(root_path),
            html_path=Path(html_path),
        )
        if generation != self._latest_generation:
            self._delete_tree(candidate.root_path)
            self._inflight_generation = None
            if self._latest_generation > generation:
                self._refresh_timer.start(0)
            return
        if self._pending_candidate is not None:
            self._delete_tree(self._pending_candidate.root_path)
        self._pending_candidate = candidate
        self._awaiting_load_generation = generation
        view.mark_programmatic_reload()
        view.load(QUrl.fromLocalFile(str(candidate.html_path.resolve())))
        self.panel.fill_preview_status_label.setText(
            "Refreshing HTML preview from current draft state..."
        )

    def _on_view_load_finished(self, ok: bool) -> None:  # pragma: no cover - Qt callback
        generation = self._awaiting_load_generation
        candidate = self._pending_candidate
        self._awaiting_load_generation = None
        self._inflight_generation = None
        if generation is None or candidate is None:
            return
        if not ok or generation != self._latest_generation:
            self._delete_tree(candidate.root_path)
            self._pending_candidate = None
            if not ok:
                self.mark_stale("Preview stale. Latest refresh failed to load.")
                self.panel.fill_preview_status_label.setText(
                    "Unable to load the refreshed HTML preview."
                )
            if self._latest_generation > generation:
                self._refresh_timer.start(0)
            return
        old_tree = self._active_tree
        self._active_tree = candidate.root_path
        self._active_candidate = candidate
        self._pending_candidate = None
        self._stale = False
        if isinstance(self.panel.fill_preview_stale_label, QLabel):
            self.panel.fill_preview_stale_label.setVisible(False)
        self.panel.fill_preview_status_label.setText(
            self._latest_requested_reason or "Previewing current HTML draft state."
        )
        if old_tree is not None and old_tree != self._active_tree:
            self._delete_tree(old_tree)
        if self._latest_generation > generation:
            self.mark_stale("Preview stale. Refreshing current draft state...")
            self._refresh_timer.start(0)

    @staticmethod
    def _delete_tree(path: Path | None) -> None:
        if path is None:
            return
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass


class ContractTemplateWorkspacePanel(QWidget):
    """Docked workspace for placeholder generation and dynamic fill forms."""

    TAB_ORDER = ("import", "symbols", "fill")
    _IMPORT_TAB_KEY = "import"
    _SYMBOLS_TAB_KEY = "symbols"
    _FILL_TAB_KEY = "fill"

    def __init__(
        self,
        *,
        catalog_service_provider,
        template_service_provider=None,
        form_service_provider=None,
        export_service_provider=None,
        parent=None,
    ):
        super().__init__(parent)
        self.catalog_service_provider = catalog_service_provider
        self.template_service_provider = template_service_provider or (lambda: None)
        self.form_service_provider = form_service_provider or (lambda: None)
        self.export_service_provider = export_service_provider or (lambda: None)
        self._visible_entries: list[ContractTemplateCatalogEntry] = []
        self._visible_drafts: list[ContractTemplateDraftRecord] = []
        self._visible_admin_templates: list[ContractTemplateRecord] = []
        self._visible_admin_revisions: list[ContractTemplateRevisionRecord] = []
        self._visible_admin_placeholders: list[ContractTemplatePlaceholderRecord] = []
        self._visible_admin_drafts: list[ContractTemplateDraftRecord] = []
        self._visible_admin_snapshots: list[ContractTemplateResolvedSnapshotRecord] = []
        self._visible_admin_artifacts: list[ContractTemplateOutputArtifactRecord] = []
        self._fill_definition: ContractTemplateFormDefinition | None = None
        self._loaded_draft_id: int | None = None
        self._fill_dirty = False
        self._suspend_fill_updates = False
        self._suspend_admin_updates = False
        self._fill_type_overrides: dict[str, str] = {}
        self._fill_payload_extras: dict[str, object] = {}
        self.fill_html_preview_view = None
        self.fill_preview_stale_label = None
        self.fill_preview_zoom_label = None
        self.selector_widgets: dict[str, QWidget] = {}
        self.manual_widgets: dict[str, QWidget] = {}
        self._tab_pages: dict[str, QWidget] = {}
        self._tab_hosts: dict[str, _DockableWorkspaceTab] = {}
        self._pending_tab_layout_states: dict[str, dict[str, object] | None] = {
            key: None for key in self.TAB_ORDER
        }
        self._fill_preview_controller: _FillHtmlPreviewController | None = None
        self.setObjectName("contractTemplateWorkspacePanel")
        _apply_standard_widget_chrome(self, "contractTemplateWorkspacePanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            self,
            title="Contract Templates",
            subtitle=(
                "Generate copy-ready placeholder symbols from authoritative app data, "
                "import scanned template revisions, fill detected placeholders, and "
                "resume editable drafts through one coherent workspace."
            ),
        )

        self.workspace_tabs = QTabWidget(self)
        self.workspace_tabs.setObjectName("contractTemplateWorkspaceTabs")
        self.workspace_tabs.setDocumentMode(True)
        root.addWidget(self.workspace_tabs, 1)
        self.workspace_tabs.currentChanged.connect(self._on_workspace_tab_changed)

        self._build_import_tab()
        self._build_symbol_generator_tab()
        self._build_fill_form_tab()

        _apply_compact_dialog_control_heights(self)
        self.focus_tab("import")
        self.refresh()

    def closeEvent(self, event):  # pragma: no cover - QWidget lifecycle
        if self._fill_preview_controller is not None:
            self._fill_preview_controller.cleanup()
        super().closeEvent(event)

    def _build_import_tab(self) -> None:
        self.import_tab = self._create_workspace_tab_page(
            self._IMPORT_TAB_KEY,
            "Import",
            "contractTemplateImportTab",
        )
        self.admin_tab = self.import_tab

    def _build_admin_tab(self) -> None:
        if not hasattr(self, "import_tab"):
            self._build_import_tab()

    def _build_symbol_generator_tab(self) -> None:
        self.symbol_generator_tab = self._create_workspace_tab_page(
            self._SYMBOLS_TAB_KEY,
            "Symbol Generator",
            "contractTemplateSymbolGeneratorTab",
        )

    def _build_fill_form_tab(self) -> None:
        self.fill_form_tab = self._create_workspace_tab_page(
            self._FILL_TAB_KEY,
            "Fill Form",
            "contractTemplateFillFormTab",
        )

    def _create_workspace_tab_page(self, key: str, label: str, object_name: str) -> QWidget:
        page = QWidget(self.workspace_tabs)
        page.setObjectName(object_name)
        page.setProperty("role", "workspaceCanvas")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._tab_pages[str(key)] = page
        self.workspace_tabs.addTab(page, label)
        return page

    def _surface_widget(
        self,
        parent: QWidget,
        *,
        object_name: str,
        description: str | None = None,
    ) -> tuple[QWidget, QVBoxLayout]:
        widget = QWidget(parent)
        widget.setObjectName(object_name)
        widget.setProperty("role", "workspaceCanvas")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        if description:
            label = QLabel(description, widget)
            label.setWordWrap(True)
            label.setProperty("role", "secondary")
            layout.addWidget(label)
        return widget, layout

    def _create_workspace_dock(
        self,
        host: _DockableWorkspaceTab,
        *,
        title: str,
        object_name: str,
        content: QWidget,
        scrollable: bool = True,
    ) -> QDockWidget:
        dock = QDockWidget(title, host.main_window)
        dock.setObjectName(object_name)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        if scrollable:
            scroll = QScrollArea(dock)
            scroll.setObjectName(f"{object_name}ScrollArea")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setProperty("role", "workspaceCanvas")
            scroll.setWidget(content)
            dock.setWidget(scroll)
        else:
            dock.setWidget(content)
        return dock

    @staticmethod
    def _show_docks(*docks: QDockWidget) -> None:
        for dock in docks:
            dock.show()
            dock.raise_()
            if dock.isFloating():
                dock.setFloating(False)

    def _ensure_workspace_container(
        self,
        *,
        key: str,
        host_object_name: str,
        reset_handler,
    ) -> _DockableWorkspaceTab:
        host = self._tab_hosts.get(key)
        if host is not None:
            return host
        page = self._tab_pages[key]
        host = _DockableWorkspaceTab(
            tab_key=key,
            host_object_name=host_object_name,
            reset_handler=reset_handler,
            layout_changed_handler=self._notify_layout_state_changed,
            parent=self.workspace_tabs,
        )
        pending_state = self._pending_tab_layout_states.get(key)
        if pending_state is not None:
            host.restore_layout_state(pending_state)
        tab_index = self.workspace_tabs.indexOf(page)
        tab_label = self.workspace_tabs.tabText(tab_index) if tab_index >= 0 else ""
        was_current = self.workspace_tabs.currentWidget() is page
        was_blocked = self.workspace_tabs.blockSignals(True)
        try:
            if tab_index >= 0:
                self.workspace_tabs.removeTab(tab_index)
                self.workspace_tabs.insertTab(tab_index, host, tab_label)
                if was_current:
                    self.workspace_tabs.setCurrentIndex(tab_index)
        finally:
            self.workspace_tabs.blockSignals(was_blocked)
        if page is not None:
            page.deleteLater()
        self._tab_pages[key] = host
        if key == self._IMPORT_TAB_KEY:
            self.import_tab = host
            self.admin_tab = host
        elif key == self._SYMBOLS_TAB_KEY:
            self.symbol_generator_tab = host
        elif key == self._FILL_TAB_KEY:
            self.fill_form_tab = host
        self._tab_hosts[key] = host
        return host

    def _ensure_import_workspace(self) -> _DockableWorkspaceTab:
        host = self._tab_hosts.get(self._IMPORT_TAB_KEY)
        if host is not None:
            return host
        host = self._ensure_workspace_container(
            key=self._IMPORT_TAB_KEY,
            host_object_name="contractTemplateImportWorkspaceWindow",
            reset_handler=self._reset_import_workspace_layout,
        )

        import_surface, import_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateImportAdminSurface",
            description=(
                "Manage imported template families, add new revisions, and keep the "
                "library honest about archive versus delete semantics."
            ),
        )
        self.admin_template_table = self._create_admin_table(
            import_surface,
            columns=("ID", "Name", "Format", "Active Revision", "Archived", "Updated"),
            object_name="contractTemplateAdminTemplateTable",
        )
        self.admin_template_table.itemSelectionChanged.connect(self._on_admin_template_changed)
        import_layout.addWidget(self.admin_template_table)
        self.admin_template_actions_cluster = _create_action_button_cluster(
            import_surface,
            [
                self._create_button(
                    import_surface,
                    "Import Template…",
                    "contractTemplateAdminImportButton",
                    self.import_template_from_file,
                ),
                self._create_button(
                    import_surface,
                    "Add Revision…",
                    "contractTemplateAdminAddRevisionButton",
                    self.add_revision_from_file,
                ),
                self._create_button(
                    import_surface,
                    "Duplicate Template",
                    "contractTemplateAdminDuplicateTemplateButton",
                    self.duplicate_selected_template,
                ),
                self._create_button(
                    import_surface,
                    "Archive / Restore Template",
                    "contractTemplateAdminArchiveTemplateButton",
                    self.toggle_selected_template_archive,
                ),
                self._create_button(
                    import_surface,
                    "Delete Template Record…",
                    "contractTemplateAdminDeleteTemplateButton",
                    self.delete_selected_template_record,
                ),
                self._create_button(
                    import_surface,
                    "Delete Template + Files…",
                    "contractTemplateAdminDeleteTemplateFilesButton",
                    self.delete_selected_template_with_files,
                ),
            ],
            columns=2,
            min_button_width=210,
            span_last_row=True,
        )
        self.admin_template_actions_cluster.setObjectName(
            "contractTemplateAdminTemplateActionsCluster"
        )
        import_layout.addWidget(self.admin_template_actions_cluster)

        revision_surface, revision_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateRevisionInventorySurface",
            description=(
                "Inspect scan status and binding refresh actions for the selected template."
            ),
        )
        self.admin_revision_table = self._create_admin_table(
            revision_surface,
            columns=("ID", "Revision", "Format", "Scan Status", "Placeholders", "Active"),
            object_name="contractTemplateAdminRevisionTable",
        )
        self.admin_revision_table.itemSelectionChanged.connect(self._on_admin_revision_changed)
        revision_layout.addWidget(self.admin_revision_table)
        self.admin_revision_actions_cluster = _create_action_button_cluster(
            revision_surface,
            [
                self._create_button(
                    revision_surface,
                    "Rescan Revision",
                    "contractTemplateAdminRescanRevisionButton",
                    self.rescan_selected_revision,
                ),
                self._create_button(
                    revision_surface,
                    "Rebind Placeholders",
                    "contractTemplateAdminRebindRevisionButton",
                    self.rebind_selected_revision,
                ),
                self._create_button(
                    revision_surface,
                    "Set Active Revision",
                    "contractTemplateAdminActivateRevisionButton",
                    self.activate_selected_revision,
                ),
            ],
            columns=3,
            min_button_width=190,
        )
        self.admin_revision_actions_cluster.setObjectName(
            "contractTemplateAdminRevisionActionsCluster"
        )
        revision_layout.addWidget(self.admin_revision_actions_cluster)
        self.admin_revision_status_label = QLabel(
            "Select a revision to inspect detected placeholders and scan diagnostics.",
            revision_surface,
        )
        self.admin_revision_status_label.setObjectName("contractTemplateAdminRevisionStatusLabel")
        self.admin_revision_status_label.setWordWrap(True)
        self.admin_revision_status_label.setProperty("role", "secondary")
        revision_layout.addWidget(self.admin_revision_status_label)

        placeholder_surface, placeholder_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplatePlaceholderInventorySurface",
            description="Detected placeholder inventory for the selected revision.",
        )
        self.admin_placeholder_table = self._create_admin_table(
            placeholder_surface,
            columns=("Symbol", "Label", "Type", "Required", "Occurrences"),
            object_name="contractTemplateAdminPlaceholderTable",
        )
        placeholder_layout.addWidget(self.admin_placeholder_table)

        draft_surface, draft_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateDraftArchiveSurface",
            description=(
                "Browse mutable drafts separately from immutable snapshots and retained output."
            ),
        )
        self.admin_draft_table = self._create_admin_table(
            draft_surface,
            columns=("ID", "Draft", "Storage", "Status", "Last Snapshot", "Updated"),
            object_name="contractTemplateAdminDraftTable",
        )
        self.admin_draft_table.itemSelectionChanged.connect(self._on_admin_draft_changed)
        draft_layout.addWidget(self.admin_draft_table)
        self.admin_draft_actions_cluster = _create_action_button_cluster(
            draft_surface,
            [
                self._create_button(
                    draft_surface,
                    "Open Draft In Fill Tab",
                    "contractTemplateAdminOpenDraftButton",
                    self.open_selected_draft_in_fill_tab,
                ),
                self._create_button(
                    draft_surface,
                    "Export Selected Draft PDF",
                    "contractTemplateAdminExportDraftButton",
                    self.export_selected_admin_draft,
                ),
                self._create_button(
                    draft_surface,
                    "Archive / Restore Draft",
                    "contractTemplateAdminArchiveDraftButton",
                    self.toggle_selected_draft_archive,
                ),
                self._create_button(
                    draft_surface,
                    "Delete Draft Record…",
                    "contractTemplateAdminDeleteDraftButton",
                    self.delete_selected_draft_record,
                ),
                self._create_button(
                    draft_surface,
                    "Delete Draft + Files…",
                    "contractTemplateAdminDeleteDraftFilesButton",
                    self.delete_selected_draft_with_files,
                ),
            ],
            columns=2,
            min_button_width=210,
            span_last_row=True,
        )
        self.admin_draft_actions_cluster.setObjectName("contractTemplateAdminDraftActionsCluster")
        draft_layout.addWidget(self.admin_draft_actions_cluster)

        snapshots_surface, snapshots_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateSnapshotsArtifactsSurface",
            description=(
                "Snapshots and artifacts stay grouped here so archival output remains "
                "manageable without fragmenting the workspace."
            ),
        )
        snapshot_artifact_splitter = QSplitter(Qt.Vertical, snapshots_surface)
        snapshot_artifact_splitter.setObjectName("contractTemplateSnapshotsArtifactsSplitter")
        snapshot_artifact_splitter.setChildrenCollapsible(False)

        snapshot_container, snapshot_layout = self._surface_widget(
            snapshot_artifact_splitter,
            object_name="contractTemplateSnapshotsSurface",
            description="Immutable resolved snapshots for the selected template.",
        )
        self.admin_snapshot_table = self._create_admin_table(
            snapshot_container,
            columns=("Snapshot", "Draft", "Checksum", "Created"),
            object_name="contractTemplateAdminSnapshotTable",
        )
        snapshot_layout.addWidget(self.admin_snapshot_table)

        artifact_container, artifact_layout = self._surface_widget(
            snapshot_artifact_splitter,
            object_name="contractTemplateArtifactsSurface",
            description="Retained output artifacts and explicit file lifecycle actions.",
        )
        self.admin_artifact_table = self._create_admin_table(
            artifact_container,
            columns=("Artifact", "Type", "Filename", "Status", "Retained", "Created"),
            object_name="contractTemplateAdminArtifactTable",
        )
        artifact_layout.addWidget(self.admin_artifact_table)
        self.admin_artifact_actions_cluster = _create_action_button_cluster(
            artifact_container,
            [
                self._create_button(
                    artifact_container,
                    "Open Selected Artifact",
                    "contractTemplateAdminOpenArtifactButton",
                    self.open_selected_artifact,
                ),
                self._create_button(
                    artifact_container,
                    "Delete Artifact Record…",
                    "contractTemplateAdminDeleteArtifactButton",
                    self.delete_selected_artifact_record,
                ),
                self._create_button(
                    artifact_container,
                    "Delete Artifact File + Record…",
                    "contractTemplateAdminDeleteArtifactFileButton",
                    self.delete_selected_artifact_with_file,
                ),
                self._create_button(
                    artifact_container,
                    "Refresh Admin View",
                    "contractTemplateAdminRefreshButton",
                    self.refresh_admin_workspace,
                ),
            ],
            columns=2,
            min_button_width=210,
        )
        self.admin_artifact_actions_cluster.setObjectName(
            "contractTemplateAdminArtifactActionsCluster"
        )
        artifact_layout.addWidget(self.admin_artifact_actions_cluster)
        self.admin_status_label = QLabel(
            "Admin actions keep database records separate from managed source, draft, and artifact files.",
            artifact_container,
        )
        self.admin_status_label.setObjectName("contractTemplateAdminStatusLabel")
        self.admin_status_label.setWordWrap(True)
        self.admin_status_label.setProperty("role", "secondary")
        artifact_layout.addWidget(self.admin_status_label)
        snapshot_artifact_splitter.addWidget(snapshot_container)
        snapshot_artifact_splitter.addWidget(artifact_container)
        snapshot_artifact_splitter.setStretchFactor(0, 4)
        snapshot_artifact_splitter.setStretchFactor(1, 5)
        snapshots_layout.addWidget(snapshot_artifact_splitter, 1)

        import_dock = self._create_workspace_dock(
            host,
            title="Import / Admin",
            object_name="contractTemplateImportAdminDock",
            content=import_surface,
        )
        revision_dock = self._create_workspace_dock(
            host,
            title="Revision Inventory",
            object_name="contractTemplateRevisionInventoryDock",
            content=revision_surface,
        )
        placeholder_dock = self._create_workspace_dock(
            host,
            title="Placeholder Inventory",
            object_name="contractTemplatePlaceholderInventoryDock",
            content=placeholder_surface,
        )
        draft_dock = self._create_workspace_dock(
            host,
            title="Draft Archive",
            object_name="contractTemplateDraftArchiveDock",
            content=draft_surface,
        )
        snapshots_dock = self._create_workspace_dock(
            host,
            title="Snapshots / Artifacts",
            object_name="contractTemplateSnapshotsArtifactsDock",
            content=snapshots_surface,
        )
        host.register_docks(
            [import_dock, revision_dock, placeholder_dock, draft_dock, snapshots_dock]
        )
        self._reset_import_workspace_layout()
        return host

    def _reset_import_workspace_layout(self) -> None:
        host = self._tab_hosts.get(self._IMPORT_TAB_KEY)
        if host is None:
            return
        docks = {dock.objectName(): dock for dock in host._docks}
        import_dock = docks["contractTemplateImportAdminDock"]
        revision_dock = docks["contractTemplateRevisionInventoryDock"]
        placeholder_dock = docks["contractTemplatePlaceholderInventoryDock"]
        draft_dock = docks["contractTemplateDraftArchiveDock"]
        snapshots_dock = docks["contractTemplateSnapshotsArtifactsDock"]
        self._show_docks(import_dock, revision_dock, placeholder_dock, draft_dock, snapshots_dock)
        window = host.main_window
        window.addDockWidget(Qt.LeftDockWidgetArea, import_dock)
        window.splitDockWidget(import_dock, draft_dock, Qt.Vertical)
        window.addDockWidget(Qt.RightDockWidgetArea, revision_dock)
        window.splitDockWidget(revision_dock, placeholder_dock, Qt.Vertical)
        window.splitDockWidget(placeholder_dock, snapshots_dock, Qt.Vertical)

    def _ensure_symbol_workspace(self) -> _DockableWorkspaceTab:
        host = self._tab_hosts.get(self._SYMBOLS_TAB_KEY)
        if host is not None:
            return host
        host = self._ensure_workspace_container(
            key=self._SYMBOLS_TAB_KEY,
            host_object_name="contractTemplateSymbolWorkspaceWindow",
            reset_handler=self._reset_symbol_workspace_layout,
        )

        controls_surface, controls_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateGeneratorControlsSurface",
            description=(
                "Filter the known database symbol catalog and copy canonical placeholders "
                "into your external document template."
            ),
        )
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(8)
        self.search_edit = QLineEdit(controls_surface)
        self.search_edit.setObjectName("contractTemplateCatalogSearchEdit")
        self.search_edit.setPlaceholderText(
            "Search labels, namespaces, symbols, or descriptions..."
        )
        self.search_edit.textChanged.connect(self.refresh_symbol_generator)
        search_row.addWidget(self.search_edit, 1)
        self.namespace_combo = QComboBox(controls_surface)
        self.namespace_combo.setObjectName("contractTemplateNamespaceCombo")
        self.namespace_combo.currentIndexChanged.connect(self.refresh_symbol_generator)
        search_row.addWidget(self.namespace_combo)
        controls_layout.addLayout(search_row)

        refresh_button = QPushButton("Refresh", controls_surface)
        refresh_button.clicked.connect(self.refresh_symbol_generator)
        copy_selected_button = QPushButton("Copy Selected Symbol", controls_surface)
        copy_selected_button.setObjectName("contractTemplateCopySelectedButton")
        copy_selected_button.clicked.connect(self.copy_selected_symbol)
        copy_visible_button = QPushButton("Copy Visible Symbols", controls_surface)
        copy_visible_button.setObjectName("contractTemplateCopyVisibleButton")
        copy_visible_button.clicked.connect(self.copy_visible_symbols)
        self.symbol_actions_cluster = _create_action_button_cluster(
            controls_surface,
            [refresh_button, copy_selected_button, copy_visible_button],
            columns=2,
            min_button_width=170,
            span_last_row=True,
        )
        self.symbol_actions_cluster.setObjectName("contractTemplateSymbolActionsCluster")
        controls_layout.addWidget(self.symbol_actions_cluster)
        self.status_label = QLabel(
            "Open a profile to browse the contract template symbol catalog.",
            controls_surface,
        )
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "secondary")
        controls_layout.addWidget(self.status_label)

        known_symbols_surface, known_symbols_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateKnownSymbolsSurface",
            description=(
                "Each symbol is canonical, copy-ready, and tied to a real field or "
                "custom-field definition already present in the app."
            ),
        )
        self.table = QTableWidget(0, 5, known_symbols_surface)
        self.table.setObjectName("contractTemplateCatalogTable")
        self.table.setHorizontalHeaderLabels(["Namespace", "Field", "Type", "Scope", "Symbol"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._update_selected_details)
        self.table.doubleClicked.connect(self._copy_symbol_from_index)
        known_symbols_layout.addWidget(self.table, 1)

        selected_surface, selected_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateSelectedSymbolSurface",
            description=(
                "Review the selected symbol's type, scope, source, and canonical text "
                "before copying it into your template."
            ),
        )
        selected_form = QFormLayout()
        _configure_standard_form_layout(selected_form)
        self.selected_label_value = QLabel("No symbol selected.", selected_surface)
        self.selected_label_value.setWordWrap(True)
        self.selected_namespace_value = QLabel("-", selected_surface)
        self.selected_type_value = QLabel("-", selected_surface)
        self.selected_scope_value = QLabel("-", selected_surface)
        self.selected_source_value = QLabel("-", selected_surface)
        self.selected_symbol_edit = QLineEdit(selected_surface)
        self.selected_symbol_edit.setObjectName("contractTemplateSelectedSymbolEdit")
        self.selected_symbol_edit.setReadOnly(True)
        selected_form.addRow("Label", self.selected_label_value)
        selected_form.addRow("Namespace", self.selected_namespace_value)
        selected_form.addRow("Field Type", self.selected_type_value)
        selected_form.addRow("Scope", self.selected_scope_value)
        selected_form.addRow("Source", self.selected_source_value)
        selected_form.addRow("Canonical Symbol", self.selected_symbol_edit)
        selected_layout.addLayout(selected_form)
        self.detail_resolver_label = QLabel("Resolver Target: -", selected_surface)
        self.detail_resolver_label.setWordWrap(True)
        self.detail_source_label = QLabel("Source Kind: -", selected_surface)
        self.detail_source_label.setWordWrap(True)
        self.detail_source_label.setProperty("role", "secondary")
        selected_layout.addWidget(self.detail_resolver_label)
        selected_layout.addWidget(self.detail_source_label)
        self.selected_description_value = QLabel(
            "Choose a symbol to see more detail.",
            selected_surface,
        )
        self.selected_description_value.setWordWrap(True)
        self.selected_description_value.setProperty("role", "secondary")
        selected_layout.addWidget(self.selected_description_value)
        guidance = QLabel(
            "Use db symbols for authoritative catalog values. Use manual symbols only when "
            "a template needs a user-supplied value that does not already live in the database.",
            selected_surface,
        )
        guidance.setWordWrap(True)
        guidance.setProperty("role", "secondary")
        selected_layout.addWidget(guidance)

        manual_surface, manual_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateManualSymbolSurface",
            description=(
                "Use this when a value is intentionally not pulled from the current "
                "database. The helper keeps the token parser-safe and copy-ready."
            ),
        )
        manual_form = QFormLayout()
        _configure_standard_form_layout(manual_form)
        self.manual_key_edit = QLineEdit(manual_surface)
        self.manual_key_edit.setObjectName("contractTemplateManualKeyEdit")
        self.manual_key_edit.setPlaceholderText("Example: License Date")
        self.manual_key_edit.textChanged.connect(self._refresh_manual_symbol_preview)
        self.manual_symbol_edit = QLineEdit(manual_surface)
        self.manual_symbol_edit.setObjectName("contractTemplateManualSymbolEdit")
        self.manual_symbol_edit.setReadOnly(True)
        manual_form.addRow("Human Label", self.manual_key_edit)
        manual_form.addRow("Generated Symbol", self.manual_symbol_edit)
        manual_layout.addLayout(manual_form)
        self.manual_feedback_label = QLabel(
            "Generated manual symbols use the canonical Phase 1 grammar: {{manual.your_field_name}}.",
            manual_surface,
        )
        self.manual_feedback_label.setWordWrap(True)
        self.manual_feedback_label.setProperty("role", "secondary")
        manual_layout.addWidget(self.manual_feedback_label)
        copy_manual_button = QPushButton("Copy Manual Symbol", manual_surface)
        copy_manual_button.setObjectName("contractTemplateCopyManualButton")
        copy_manual_button.clicked.connect(self.copy_manual_symbol)
        manual_layout.addWidget(copy_manual_button)

        controls_dock = self._create_workspace_dock(
            host,
            title="Symbol Generator",
            object_name="contractTemplateGeneratorControlsDock",
            content=controls_surface,
        )
        known_symbols_dock = self._create_workspace_dock(
            host,
            title="Known Database Symbols",
            object_name="contractTemplateKnownSymbolsDock",
            content=known_symbols_surface,
        )
        selected_dock = self._create_workspace_dock(
            host,
            title="Selected Symbol",
            object_name="contractTemplateSelectedSymbolDock",
            content=selected_surface,
        )
        manual_dock = self._create_workspace_dock(
            host,
            title="Manual Symbol Helper",
            object_name="contractTemplateManualSymbolDock",
            content=manual_surface,
        )
        host.register_docks([controls_dock, known_symbols_dock, selected_dock, manual_dock])
        self._populate_namespace_combo(())
        self._refresh_manual_symbol_preview()
        self._reset_symbol_workspace_layout()
        return host

    def _reset_symbol_workspace_layout(self) -> None:
        host = self._tab_hosts.get(self._SYMBOLS_TAB_KEY)
        if host is None:
            return
        docks = {dock.objectName(): dock for dock in host._docks}
        controls_dock = docks["contractTemplateGeneratorControlsDock"]
        known_symbols_dock = docks["contractTemplateKnownSymbolsDock"]
        selected_dock = docks["contractTemplateSelectedSymbolDock"]
        manual_dock = docks["contractTemplateManualSymbolDock"]
        self._show_docks(controls_dock, known_symbols_dock, selected_dock, manual_dock)
        window = host.main_window
        window.addDockWidget(Qt.LeftDockWidgetArea, controls_dock)
        window.splitDockWidget(controls_dock, known_symbols_dock, Qt.Vertical)
        window.addDockWidget(Qt.RightDockWidgetArea, selected_dock)
        window.splitDockWidget(selected_dock, manual_dock, Qt.Vertical)

    def _ensure_fill_workspace(self) -> _DockableWorkspaceTab:
        host = self._tab_hosts.get(self._FILL_TAB_KEY)
        if host is not None:
            return host
        host = self._ensure_workspace_container(
            key=self._FILL_TAB_KEY,
            host_object_name="contractTemplateFillWorkspaceWindow",
            reset_handler=self._reset_fill_workspace_layout,
        )

        revision_surface, revision_surface_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateFillRevisionSurface",
        )
        selection_box, selection_layout = _create_standard_section(
            revision_surface,
            "Template Revision",
            "Choose a scanned template revision, then let the app synthesize one editable control per detected placeholder.",
        )
        selection_form = QFormLayout()
        _configure_standard_form_layout(selection_form)
        self.fill_template_combo = QComboBox(selection_box)
        self.fill_template_combo.setObjectName("contractTemplateFillTemplateCombo")
        self.fill_template_combo.currentIndexChanged.connect(self._on_fill_template_changed)
        self.fill_revision_combo = QComboBox(selection_box)
        self.fill_revision_combo.setObjectName("contractTemplateFillRevisionCombo")
        self.fill_revision_combo.currentIndexChanged.connect(self._on_fill_revision_changed)
        selection_form.addRow("Template", self.fill_template_combo)
        selection_form.addRow("Revision", self.fill_revision_combo)
        selection_layout.addLayout(selection_form)
        refresh_fill_button = QPushButton("Refresh Fill Form", selection_box)
        refresh_fill_button.setObjectName("contractTemplateFillRefreshButton")
        refresh_fill_button.clicked.connect(self.refresh_fill_form)
        selection_layout.addWidget(refresh_fill_button)
        self.fill_status_label = QLabel(
            "Open a profile to browse imported template revisions.",
            selection_box,
        )
        self.fill_status_label.setWordWrap(True)
        self.fill_status_label.setObjectName("contractTemplateFillStatusLabel")
        self.fill_warning_label = QLabel("", selection_box)
        self.fill_warning_label.setWordWrap(True)
        self.fill_warning_label.setProperty("role", "secondary")
        self.fill_warning_label.setObjectName("contractTemplateFillWarningLabel")
        selection_layout.addWidget(self.fill_status_label)
        selection_layout.addWidget(self.fill_warning_label)
        revision_surface_layout.addWidget(selection_box)
        revision_surface_layout.addStretch(1)

        draft_surface, draft_surface_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateFillDraftWorkspaceSurface",
        )
        draft_box, draft_layout = _create_standard_section(
            draft_surface,
            "Draft Workspace",
            "Save the current editable state for this revision, reopen it later, and choose whether the draft payload stays embedded in the database or lives as a managed file.",
        )
        draft_form = QFormLayout()
        _configure_standard_form_layout(draft_form)
        self.fill_draft_name_edit = QLineEdit(draft_box)
        self.fill_draft_name_edit.setObjectName("contractTemplateDraftNameEdit")
        self.fill_draft_name_edit.setPlaceholderText("Draft name")
        self.fill_draft_storage_combo = QComboBox(draft_box)
        self.fill_draft_storage_combo.setObjectName("contractTemplateDraftStorageCombo")
        self.fill_draft_storage_combo.addItem("Database Embedded", STORAGE_MODE_DATABASE)
        self.fill_draft_storage_combo.addItem("Managed File", STORAGE_MODE_MANAGED_FILE)
        self.fill_draft_combo = QComboBox(draft_box)
        self.fill_draft_combo.setObjectName("contractTemplateDraftCombo")
        self.fill_draft_combo.currentIndexChanged.connect(self._on_fill_draft_changed)
        draft_form.addRow("Draft Name", self.fill_draft_name_edit)
        draft_form.addRow("Storage Mode", self.fill_draft_storage_combo)
        draft_form.addRow("Saved Drafts", self.fill_draft_combo)
        draft_layout.addLayout(draft_form)
        refresh_drafts_button = QPushButton("Refresh Drafts", draft_box)
        refresh_drafts_button.setObjectName("contractTemplateRefreshDraftsButton")
        refresh_drafts_button.clicked.connect(self.refresh_fill_drafts)
        save_new_draft_button = QPushButton("Save New Draft", draft_box)
        save_new_draft_button.setObjectName("contractTemplateSaveNewDraftButton")
        save_new_draft_button.clicked.connect(self.save_new_draft)
        save_selected_draft_button = QPushButton("Save Draft Changes", draft_box)
        save_selected_draft_button.setObjectName("contractTemplateSaveDraftChangesButton")
        save_selected_draft_button.clicked.connect(self.save_selected_draft)
        load_selected_draft_button = QPushButton("Load Selected Draft", draft_box)
        load_selected_draft_button.setObjectName("contractTemplateLoadDraftButton")
        load_selected_draft_button.clicked.connect(self.load_selected_draft)
        reset_fill_form_button = QPushButton("Reset Form", draft_box)
        reset_fill_form_button.setObjectName("contractTemplateResetFillFormButton")
        reset_fill_form_button.clicked.connect(self.reset_fill_form)
        self.fill_draft_actions_cluster = _create_action_button_cluster(
            draft_box,
            [
                refresh_drafts_button,
                save_new_draft_button,
                save_selected_draft_button,
                load_selected_draft_button,
                reset_fill_form_button,
            ],
            columns=2,
            min_button_width=170,
            span_last_row=True,
        )
        self.fill_draft_actions_cluster.setObjectName("contractTemplateDraftActionsCluster")
        draft_layout.addWidget(self.fill_draft_actions_cluster)
        self.fill_draft_status_label = QLabel(
            "Drafts are revision-specific and restore the last editable state.",
            draft_box,
        )
        self.fill_draft_status_label.setObjectName("contractTemplateDraftStatusLabel")
        self.fill_draft_status_label.setWordWrap(True)
        self.fill_draft_status_label.setProperty("role", "secondary")
        draft_layout.addWidget(self.fill_draft_status_label)
        draft_surface_layout.addWidget(draft_box)
        draft_surface_layout.addStretch(1)

        export_surface, export_surface_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateFillResolvedExportSurface",
        )
        export_box, export_layout = _create_standard_section(
            export_surface,
            "Resolved Export",
            "Export saves the current editable state to a draft, resolves placeholders against the selected records and manual values, then writes managed artifact files for the resolved document and PDF output.",
        )
        self.fill_export_button = QPushButton("Export PDF", export_box)
        self.fill_export_button.setObjectName("contractTemplateExportPdfButton")
        self.fill_export_button.clicked.connect(self.export_current_pdf)
        self.fill_open_latest_pdf_button = QPushButton("Open Latest PDF", export_box)
        self.fill_open_latest_pdf_button.setObjectName("contractTemplateOpenLatestPdfButton")
        self.fill_open_latest_pdf_button.clicked.connect(self.open_latest_pdf_for_current_draft)
        self.fill_export_actions_cluster = _create_action_button_cluster(
            export_box,
            [self.fill_export_button, self.fill_open_latest_pdf_button],
            columns=2,
            min_button_width=170,
        )
        self.fill_export_actions_cluster.setObjectName("contractTemplateExportActionsCluster")
        export_layout.addWidget(self.fill_export_actions_cluster)
        self.fill_export_status_label = QLabel(
            "Export uses the current draft payload and records immutable snapshots plus file-backed artifacts.",
            export_box,
        )
        self.fill_export_status_label.setObjectName("contractTemplateExportStatusLabel")
        self.fill_export_status_label.setWordWrap(True)
        self.fill_export_status_label.setProperty("role", "secondary")
        export_layout.addWidget(self.fill_export_status_label)
        export_surface_layout.addWidget(export_box)
        export_surface_layout.addStretch(1)

        notes_surface, notes_surface_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateFillDraftNotesSurface",
        )
        guidance_box, guidance_layout = _create_standard_section(
            notes_surface,
            "Draft Notes",
            "Draft resume restores the last editable payload for this revision, and resolved export now creates immutable snapshots plus retained PDF artifacts.",
        )
        self.fill_guidance_label = QLabel(
            "Database-backed placeholders are grouped into one authoritative record selector per entity scope, settings-backed owner placeholders resolve automatically, and manual entries stay isolated from both.",
            guidance_box,
        )
        self.fill_guidance_label.setWordWrap(True)
        self.fill_guidance_label.setProperty("role", "secondary")
        guidance_layout.addWidget(self.fill_guidance_label)
        notes_surface_layout.addWidget(guidance_box)
        notes_surface_layout.addStretch(1)

        auto_surface, auto_surface_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateFillAutomaticFieldsSurface",
        )
        auto_box, auto_layout = _create_standard_section(
            auto_surface,
            "Automatic Fields",
            "Settings-backed placeholders resolve automatically from authoritative application settings and do not require a draft-time selector.",
        )
        self.fill_auto_empty_label = QLabel(
            "No automatic settings-backed placeholders are available for this revision.",
            auto_box,
        )
        self.fill_auto_empty_label.setWordWrap(True)
        self.fill_auto_empty_label.setProperty("role", "secondary")
        auto_layout.addWidget(self.fill_auto_empty_label)
        self.fill_auto_form = QFormLayout()
        _configure_standard_form_layout(self.fill_auto_form)
        auto_layout.addLayout(self.fill_auto_form)
        auto_surface_layout.addWidget(auto_box)
        auto_surface_layout.addStretch(1)

        selector_surface, selector_surface_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateFillDatabaseFieldsSurface",
        )
        selector_box, selector_layout = _create_standard_section(
            selector_surface,
            "Database-Linked Fields",
            "Known placeholders become selector-driven controls so users choose authoritative records instead of typing catalog data by hand.",
        )
        self.fill_selector_empty_label = QLabel(
            "No database-linked placeholders are available for this revision.",
            selector_box,
        )
        self.fill_selector_empty_label.setWordWrap(True)
        self.fill_selector_empty_label.setProperty("role", "secondary")
        selector_layout.addWidget(self.fill_selector_empty_label)
        self.fill_selector_form = QFormLayout()
        _configure_standard_form_layout(self.fill_selector_form)
        selector_layout.addLayout(self.fill_selector_form)
        selector_surface_layout.addWidget(selector_box)
        selector_surface_layout.addStretch(1)

        manual_surface, manual_surface_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateFillManualFieldsSurface",
        )
        manual_box, manual_layout = _create_standard_section(
            manual_surface,
            "Manual Fields",
            "Unknown or intentionally manual placeholders become typed inputs such as text, date, number, boolean, or option lists.",
        )
        self.fill_manual_empty_label = QLabel(
            "No manual placeholders are available for this revision.",
            manual_box,
        )
        self.fill_manual_empty_label.setWordWrap(True)
        self.fill_manual_empty_label.setProperty("role", "secondary")
        manual_layout.addWidget(self.fill_manual_empty_label)
        self.fill_manual_form = QFormLayout()
        _configure_standard_form_layout(self.fill_manual_form)
        manual_layout.addLayout(self.fill_manual_form)
        manual_surface_layout.addWidget(manual_box)
        manual_surface_layout.addStretch(1)

        preview_surface, preview_layout = self._surface_widget(
            host.main_window,
            object_name="contractTemplateHtmlPreviewSurface",
            description=(
                "The live HTML preview always renders from the current editable state. "
                "Stale content is marked immediately until the refreshed page becomes current."
            ),
        )
        preview_toolbar = QWidget(preview_surface)
        preview_toolbar.setObjectName("contractTemplatePreviewToolbar")
        preview_toolbar.setProperty("role", "compactControlGroup")
        preview_toolbar_layout = QHBoxLayout(preview_toolbar)
        preview_toolbar_layout.setContentsMargins(10, 8, 10, 8)
        preview_toolbar_layout.setSpacing(8)
        self.fill_preview_button = QPushButton("Refresh HTML Preview", preview_toolbar)
        self.fill_preview_button.setObjectName("contractTemplateRefreshHtmlPreviewButton")
        self.fill_preview_button.clicked.connect(self.refresh_current_html_preview)
        preview_toolbar_layout.addWidget(self.fill_preview_button, 0)
        self.fill_preview_clear_button = QPushButton("Clear Preview", preview_toolbar)
        self.fill_preview_clear_button.setObjectName("contractTemplateClearHtmlPreviewButton")
        self.fill_preview_clear_button.clicked.connect(self.clear_html_preview)
        preview_toolbar_layout.addWidget(self.fill_preview_clear_button, 0)
        fit_preview_button = QPushButton("Fit View", preview_toolbar)
        fit_preview_button.setObjectName("contractTemplateFitHtmlPreviewButton")
        preview_toolbar_layout.addWidget(fit_preview_button, 0)
        zoom_out_button = QPushButton("-", preview_toolbar)
        zoom_out_button.setObjectName("contractTemplateHtmlPreviewZoomOutButton")
        preview_toolbar_layout.addWidget(zoom_out_button, 0)
        zoom_in_button = QPushButton("+", preview_toolbar)
        zoom_in_button.setObjectName("contractTemplateHtmlPreviewZoomInButton")
        preview_toolbar_layout.addWidget(zoom_in_button, 0)
        self.fill_preview_zoom_label = QLabel("100%", preview_toolbar)
        self.fill_preview_zoom_label.setObjectName("contractTemplatePreviewZoomLabel")
        self.fill_preview_zoom_label.setProperty("role", "statusText")
        preview_toolbar_layout.addWidget(self.fill_preview_zoom_label, 0)
        preview_toolbar_layout.addStretch(1)
        preview_layout.addWidget(preview_toolbar)
        self.fill_preview_status_label = QLabel(
            "HTML preview becomes available when the selected revision is a native HTML template.",
            preview_surface,
        )
        self.fill_preview_status_label.setObjectName("contractTemplatePreviewStatusLabel")
        self.fill_preview_status_label.setWordWrap(True)
        self.fill_preview_status_label.setProperty("role", "secondary")
        preview_layout.addWidget(self.fill_preview_status_label)
        self.fill_preview_stale_label = QLabel("Preview stale", preview_surface)
        self.fill_preview_stale_label.setObjectName("contractTemplatePreviewStaleLabel")
        self.fill_preview_stale_label.setProperty("role", "secondary")
        self.fill_preview_stale_label.setVisible(False)
        preview_layout.addWidget(self.fill_preview_stale_label)
        if QWebEngineView is not None:
            self.fill_html_preview_view = _InteractiveHtmlPreviewView(preview_surface)
            self.fill_html_preview_view.setMinimumHeight(420)
            self.fill_html_preview_view.zoom_percent_changed.connect(
                lambda value: self.fill_preview_zoom_label.setText(f"{int(value)}%")
            )
            fit_preview_button.clicked.connect(self.fill_html_preview_view.reset_to_fit)
            zoom_out_button.clicked.connect(
                lambda: self.fill_html_preview_view.set_zoom_percent(
                    self.fill_html_preview_view.current_zoom_percent() - 10,
                    user_initiated=True,
                )
            )
            zoom_in_button.clicked.connect(
                lambda: self.fill_html_preview_view.set_zoom_percent(
                    self.fill_html_preview_view.current_zoom_percent() + 10,
                    user_initiated=True,
                )
            )
            preview_layout.addWidget(self.fill_html_preview_view, 1)
        else:
            self.fill_preview_unavailable_label = QLabel(
                "Qt WebEngine is unavailable in this runtime, so native HTML preview cannot be shown here.",
                preview_surface,
            )
            self.fill_preview_unavailable_label.setWordWrap(True)
            self.fill_preview_unavailable_label.setProperty("role", "secondary")
            preview_layout.addWidget(self.fill_preview_unavailable_label)
        self._fill_preview_controller = _FillHtmlPreviewController(self, host)
        self._fill_preview_controller.initialize()

        revision_dock = self._create_workspace_dock(
            host,
            title="Template Revision",
            object_name="contractTemplateFillRevisionDock",
            content=revision_surface,
        )
        draft_dock = self._create_workspace_dock(
            host,
            title="Draft Workspace",
            object_name="contractTemplateFillDraftWorkspaceDock",
            content=draft_surface,
        )
        export_dock = self._create_workspace_dock(
            host,
            title="Resolved Export",
            object_name="contractTemplateFillResolvedExportDock",
            content=export_surface,
        )
        notes_dock = self._create_workspace_dock(
            host,
            title="Draft Notes",
            object_name="contractTemplateFillDraftNotesDock",
            content=notes_surface,
        )
        auto_dock = self._create_workspace_dock(
            host,
            title="Automatic Fields",
            object_name="contractTemplateFillAutomaticFieldsDock",
            content=auto_surface,
        )
        selector_dock = self._create_workspace_dock(
            host,
            title="Database-Linked Fields",
            object_name="contractTemplateFillDatabaseFieldsDock",
            content=selector_surface,
        )
        manual_dock = self._create_workspace_dock(
            host,
            title="Manual Fields",
            object_name="contractTemplateFillManualFieldsDock",
            content=manual_surface,
        )
        preview_dock = self._create_workspace_dock(
            host,
            title="HTML Preview",
            object_name="contractTemplateHtmlPreviewDock",
            content=preview_surface,
            scrollable=False,
        )
        host.register_docks(
            [
                revision_dock,
                draft_dock,
                export_dock,
                notes_dock,
                auto_dock,
                selector_dock,
                manual_dock,
                preview_dock,
            ]
        )
        self._reset_fill_workspace_layout()
        return host

    def _reset_fill_workspace_layout(self) -> None:
        host = self._tab_hosts.get(self._FILL_TAB_KEY)
        if host is None:
            return
        docks = {dock.objectName(): dock for dock in host._docks}
        revision_dock = docks["contractTemplateFillRevisionDock"]
        draft_dock = docks["contractTemplateFillDraftWorkspaceDock"]
        export_dock = docks["contractTemplateFillResolvedExportDock"]
        notes_dock = docks["contractTemplateFillDraftNotesDock"]
        auto_dock = docks["contractTemplateFillAutomaticFieldsDock"]
        selector_dock = docks["contractTemplateFillDatabaseFieldsDock"]
        manual_dock = docks["contractTemplateFillManualFieldsDock"]
        preview_dock = docks["contractTemplateHtmlPreviewDock"]
        self._show_docks(
            revision_dock,
            draft_dock,
            export_dock,
            notes_dock,
            auto_dock,
            selector_dock,
            manual_dock,
            preview_dock,
        )
        window = host.main_window
        window.addDockWidget(Qt.LeftDockWidgetArea, revision_dock)
        window.splitDockWidget(revision_dock, draft_dock, Qt.Vertical)
        window.splitDockWidget(draft_dock, export_dock, Qt.Vertical)
        window.splitDockWidget(export_dock, notes_dock, Qt.Vertical)
        window.splitDockWidget(revision_dock, auto_dock, Qt.Horizontal)
        window.splitDockWidget(auto_dock, preview_dock, Qt.Horizontal)
        window.splitDockWidget(auto_dock, selector_dock, Qt.Vertical)
        window.splitDockWidget(selector_dock, manual_dock, Qt.Vertical)
        try:
            window.resizeDocks(
                [revision_dock, auto_dock, preview_dock],
                [360, 420, 760],
                Qt.Horizontal,
            )
            window.resizeDocks(
                [revision_dock, draft_dock, export_dock, notes_dock],
                [280, 360, 200, 160],
                Qt.Vertical,
            )
            window.resizeDocks(
                [auto_dock, selector_dock, manual_dock],
                [180, 320, 260],
                Qt.Vertical,
            )
        except Exception:
            pass

    def _normalize_tab_key(self, tab_name: str | None) -> str:
        clean_name = str(tab_name or "import").strip().lower()
        if clean_name == "admin":
            return self._IMPORT_TAB_KEY
        if clean_name in self.TAB_ORDER:
            return clean_name
        return self._IMPORT_TAB_KEY

    def _current_tab_key(self) -> str:
        widget = self.workspace_tabs.currentWidget()
        for key, page in self._tab_pages.items():
            if page is widget:
                return key
        return self._IMPORT_TAB_KEY

    def _ensure_tab_workspace(self, key: str) -> _DockableWorkspaceTab:
        normalized = self._normalize_tab_key(key)
        if normalized == self._SYMBOLS_TAB_KEY:
            return self._ensure_symbol_workspace()
        if normalized == self._FILL_TAB_KEY:
            return self._ensure_fill_workspace()
        return self._ensure_import_workspace()

    def _on_workspace_tab_changed(self, index: int) -> None:
        page = self.workspace_tabs.widget(index)
        if page is None:
            return
        key = next(
            (
                candidate
                for candidate, candidate_page in self._tab_pages.items()
                if candidate_page is page
            ),
            self._IMPORT_TAB_KEY,
        )
        self._ensure_tab_workspace(key)
        if key == self._SYMBOLS_TAB_KEY:
            self.refresh_symbol_generator()
        elif key == self._FILL_TAB_KEY:
            self.refresh_fill_form()
        else:
            self.refresh_admin_workspace()
        self._notify_layout_state_changed()

    def focus_tab(self, tab_name: str = "import") -> None:
        key = self._normalize_tab_key(tab_name)
        self._ensure_tab_workspace(key)
        target_page = self._tab_pages[key]
        self.workspace_tabs.setCurrentWidget(target_page)
        if key == self._FILL_TAB_KEY:
            self.refresh_fill_form()
        elif key == self._SYMBOLS_TAB_KEY:
            self.refresh_symbol_generator()
        else:
            self.refresh_admin_workspace()

    def focus_namespace(self, namespace: str | None = None) -> None:
        self._ensure_symbol_workspace()
        clean_namespace = str(namespace or "").strip().lower() or None
        target_index = 0
        for index in range(self.namespace_combo.count()):
            if self.namespace_combo.itemData(index) == clean_namespace:
                target_index = index
                break
        self.namespace_combo.setCurrentIndex(target_index)
        self.refresh_symbol_generator()

    def refresh(self) -> None:
        if self._SYMBOLS_TAB_KEY in self._tab_hosts:
            self.refresh_symbol_generator()
        if self._FILL_TAB_KEY in self._tab_hosts:
            self.refresh_fill_form()
        if self._IMPORT_TAB_KEY in self._tab_hosts:
            self.refresh_admin_workspace()

    def capture_layout_state(self) -> dict[str, object]:
        tabs_payload: dict[str, dict[str, object]] = {}
        for key in self.TAB_ORDER:
            host = self._tab_hosts.get(key)
            if host is not None:
                tabs_payload[key] = host.capture_layout_state()
            elif self._pending_tab_layout_states.get(key) is not None:
                tabs_payload[key] = dict(self._pending_tab_layout_states[key] or {})
            else:
                tabs_payload[key] = {"dock_state_b64": "", "layout_locked": True}
        return {
            "schema_version": 1,
            "current_tab": self._current_tab_key(),
            "tabs": tabs_payload,
        }

    def restore_layout_state(self, state: dict[str, object] | None) -> None:
        payload = dict(state or {})
        tabs_payload = dict(payload.get("tabs") or {})
        has_nested_state = bool(tabs_payload)
        for key in self.TAB_ORDER:
            entry = tabs_payload.get(key)
            normalized_entry = (
                {
                    "dock_state_b64": str((entry or {}).get("dock_state_b64") or ""),
                    "layout_locked": bool((entry or {}).get("layout_locked", True)),
                }
                if entry is not None
                else None
            )
            self._pending_tab_layout_states[key] = normalized_entry
            host = self._tab_hosts.get(key)
            if host is not None and normalized_entry is not None:
                host.restore_layout_state(normalized_entry)
            elif host is not None:
                host.reset_to_default_layout()
        current_tab = self._normalize_tab_key(payload.get("current_tab"))
        if not has_nested_state:
            current_tab = self._IMPORT_TAB_KEY
        self.workspace_tabs.setCurrentWidget(self._tab_pages[current_tab])
        self._ensure_tab_workspace(current_tab)

    def _notify_layout_state_changed(self) -> None:
        try:
            window = self.window()
        except RuntimeError:
            return
        schedule = getattr(window, "_schedule_main_dock_state_save", None)
        if callable(schedule):
            schedule()

    def _catalog_service(self):
        return self.catalog_service_provider()

    def _template_service(self):
        return self.template_service_provider()

    def _form_service(self):
        return self.form_service_provider()

    def _export_service(self):
        return self.export_service_provider()

    @staticmethod
    def _create_button(parent: QWidget, label: str, object_name: str, slot) -> QPushButton:
        button = QPushButton(label, parent)
        button.setObjectName(object_name)
        button.clicked.connect(slot)
        return button

    @staticmethod
    def _create_admin_table(
        parent: QWidget,
        *,
        columns: tuple[str, ...],
        object_name: str,
    ) -> QTableWidget:
        table = QTableWidget(0, len(columns), parent)
        table.setObjectName(object_name)
        table.setHorizontalHeaderLabels(list(columns))
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        return table

    def refresh_symbol_generator(self) -> None:
        if self._SYMBOLS_TAB_KEY not in self._tab_hosts:
            return
        selected_symbol = self._selected_symbol()
        service = self._catalog_service()
        if service is None:
            self._visible_entries = []
            self._populate_namespace_combo(())
            self.table.setRowCount(0)
            self.status_label.setText(
                "Open a profile to browse the contract template symbol catalog."
            )
            self._update_selected_details()
            return

        current_namespace = self.namespace_combo.currentData()
        namespaces = service.list_namespaces()
        self._populate_namespace_combo(namespaces, selected_namespace=current_namespace)
        self._visible_entries = service.list_known_symbols(
            search_text=self.search_edit.text(),
            namespace=self.namespace_combo.currentData(),
        )
        self.table.setRowCount(0)
        for entry in self._visible_entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(entry.namespace or ""),
                entry.display_label,
                entry.field_type.replace("_", " "),
                self._scope_label(entry),
                entry.canonical_symbol,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    item.setData(Qt.UserRole, entry.canonical_symbol)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        count = len(self._visible_entries)
        self.status_label.setText(
            f"Showing {count} known symbol{'s' if count != 1 else ''}."
            if count
            else "No known symbols match the current filters."
        )
        self._restore_selection(selected_symbol)
        self._update_selected_details()

    def refresh_fill_form(self) -> None:
        if self._FILL_TAB_KEY not in self._tab_hosts:
            return
        template_service = self._template_service()
        form_service = self._form_service()
        selected_template_id = self._selected_fill_template_id()
        selected_revision_id = self._selected_fill_revision_id()
        selected_draft_id = self._selected_fill_draft_id()

        if template_service is None or form_service is None:
            self._fill_definition = None
            self._populate_fill_template_combo(())
            self._populate_fill_revision_combo(())
            self._clear_fill_fields()
            self._clear_fill_drafts("Open a profile to browse and resume contract template drafts.")
            self.fill_status_label.setText("Open a profile to browse imported template revisions.")
            self.fill_warning_label.setText("")
            self._sync_html_preview_state(None)
            return

        templates = tuple(template_service.list_templates())
        self._populate_fill_template_combo(templates, selected_template_id=selected_template_id)
        template_id = self._selected_fill_template_id()
        if template_id is None:
            self._fill_definition = None
            self._populate_fill_revision_combo(())
            self._clear_fill_fields()
            self._clear_fill_drafts("Choose a template revision before saving or loading drafts.")
            self.fill_status_label.setText(
                "No contract template records exist yet. Import a scanned revision in "
                "Phase 2 tooling or seed one through the service layer."
            )
            self.fill_warning_label.setText("")
            self._sync_html_preview_state(None)
            return

        active_revision_id = None
        template_record = template_service.fetch_template(template_id)
        if template_record is not None:
            active_revision_id = template_record.active_revision_id
        revisions = tuple(template_service.list_revisions(template_id))
        self._populate_fill_revision_combo(
            revisions,
            selected_revision_id=selected_revision_id,
            active_revision_id=active_revision_id,
        )
        revision_id = self._selected_fill_revision_id()
        if revision_id is None:
            self._fill_definition = None
            self._clear_fill_fields()
            self._clear_fill_drafts(
                "The selected template does not have any drafts because it has no active revision context yet."
            )
            self.fill_status_label.setText(
                "The selected template does not have any stored revisions yet."
            )
            self.fill_warning_label.setText("")
            self._sync_html_preview_state(None)
            return

        preserved_state = None
        if self._fill_definition is not None and self._fill_definition.revision_id == revision_id:
            preserved_state = self.current_fill_state()

        try:
            form_definition = form_service.build_form_definition(revision_id)
        except Exception as exc:
            self._fill_definition = None
            self._clear_fill_fields()
            self._clear_fill_drafts(
                f"Unable to load drafts because revision #{int(revision_id)} could not build a fill form."
            )
            self.fill_status_label.setText(
                f"Unable to build a fill form for revision #{int(revision_id)}."
            )
            self.fill_warning_label.setText(str(exc))
            self._sync_html_preview_state(revision_id)
            return

        self._fill_definition = form_definition
        self._rebuild_fill_fields(form_definition)
        if preserved_state is not None and int(preserved_state.get("revision_id") or 0) == int(
            revision_id
        ):
            self.apply_editable_payload(preserved_state)
        else:
            self._fill_dirty = False
        self.refresh_fill_drafts(selected_draft_id=selected_draft_id)
        status_bits = [
            f"{len(form_definition.auto_fields)} automatic field"
            f"{'s' if len(form_definition.auto_fields) != 1 else ''}",
            f"{len(form_definition.selector_fields)} selector"
            f"{'s' if len(form_definition.selector_fields) != 1 else ''}",
            f"{len(form_definition.manual_fields)} manual field"
            f"{'s' if len(form_definition.manual_fields) != 1 else ''}",
        ]
        revision_label = _clean_text(form_definition.revision_label) or f"Revision #{revision_id}"
        self.fill_status_label.setText(
            f"{form_definition.template_name} / {revision_label} is {form_definition.scan_status}. "
            f"Generated {', '.join(status_bits)}."
        )
        warning_lines = list(form_definition.warnings)
        if form_definition.unresolved_placeholders:
            warning_lines.append(
                "Unresolved placeholders: " + ", ".join(form_definition.unresolved_placeholders)
            )
        if form_definition.scan_status != "scan_ready":
            warning_lines.insert(
                0,
                "This revision is not fully scan-ready, so the editable form may be incomplete.",
            )
        self.fill_warning_label.setText("\n".join(line for line in warning_lines if line))
        self._sync_html_preview_state(revision_id)

    def current_fill_state(self) -> dict[str, object]:
        revision_id = self._selected_fill_revision_id()
        form_service = self._form_service()
        if revision_id is None or form_service is None:
            return {
                "revision_id": None,
                "db_selections": {},
                "manual_values": {},
                "type_overrides": {},
            }
        db_selections = {
            key: value
            for key, widget in self.selector_widgets.items()
            for value in [self._read_widget_value(widget)]
            if value is not None
        }
        manual_values = {
            key: value
            for key, widget in self.manual_widgets.items()
            for value in [self._read_widget_value(widget)]
            if value is not None
        }
        payload = form_service.build_editable_payload(
            revision_id,
            db_selections=db_selections,
            manual_values=manual_values,
            type_overrides=self._fill_type_overrides,
        )
        payload.update(self._fill_payload_extras)
        return payload

    def refresh_fill_drafts(self, *, selected_draft_id: int | None = None) -> None:
        if self._FILL_TAB_KEY not in self._tab_hosts:
            return
        template_service = self._template_service()
        revision_id = self._selected_fill_revision_id()
        if template_service is None or revision_id is None:
            self._clear_fill_drafts("Choose a revision before saving or loading drafts.")
            self._sync_fill_export_status(None)
            return
        draft_records = tuple(template_service.list_drafts(revision_id=revision_id))
        self._visible_drafts = list(draft_records)
        visible_ids = {int(record.draft_id) for record in draft_records}
        target_id = selected_draft_id or self._loaded_draft_id
        if target_id is not None and int(target_id) not in visible_ids:
            self._loaded_draft_id = None
            self._fill_type_overrides = {}
            self._fill_payload_extras = {}
            target_id = None
        self._populate_fill_draft_combo(draft_records, selected_draft_id=target_id)
        selected = self._selected_fill_draft_record()
        if selected is None:
            self._sync_draft_controls_from_selection(None)
            if not draft_records:
                self.fill_draft_status_label.setText("No saved drafts exist for this revision yet.")
            self._sync_fill_export_status(None)
            return
        self._sync_draft_controls_from_selection(selected)
        self._sync_fill_export_status(selected)

    def save_new_draft(self) -> None:
        self._save_draft(save_as_new=True)

    def save_selected_draft(self) -> None:
        self._save_draft(save_as_new=False)

    def _save_draft(self, *, save_as_new: bool) -> bool:
        template_service = self._template_service()
        export_service = self._export_service()
        revision_id = self._selected_fill_revision_id()
        if template_service is None or revision_id is None:
            self.fill_draft_status_label.setText("Choose a revision before saving a draft.")
            return False
        draft_payload = self._draft_payload_for_revision(revision_id)
        selected = self._selected_fill_draft_record()
        target = None if save_as_new else (selected or self._loaded_draft_record())
        try:
            saved = (
                template_service.create_draft(draft_payload)
                if target is None
                else template_service.update_draft(target.draft_id, draft_payload)
            )
        except Exception as exc:
            self.fill_draft_status_label.setText(f"Unable to save draft: {exc}")
            QMessageBox.warning(self, "Draft Workspace", str(exc))
            return False
        html_synced = False
        if export_service is not None:
            revision = template_service.fetch_revision(saved.revision_id)
            if revision is not None and str(revision.source_format or "").strip().lower() == "html":
                try:
                    export_service.synchronize_html_draft(saved.draft_id)
                    html_synced = True
                except Exception as exc:
                    self.fill_draft_status_label.setText(
                        f"Saved draft #{saved.draft_id}, but HTML preview copy could not be refreshed: {exc}"
                    )
                    QMessageBox.warning(self, "Draft Workspace", str(exc))
                    return False
        self._loaded_draft_id = saved.draft_id
        self._fill_dirty = False
        self.refresh_fill_drafts(selected_draft_id=saved.draft_id)
        self.fill_draft_status_label.setText(
            f"Saved draft #{saved.draft_id} using {self._storage_label(saved.storage_mode)} storage."
            + (" Native HTML working copy refreshed." if html_synced else "")
        )
        if self._fill_preview_controller is not None:
            self._fill_preview_controller.request_refresh(
                reason=f"Previewing current HTML draft state for draft #{saved.draft_id}.",
                delay_ms=0,
            )
        return True

    def load_selected_draft(self) -> None:
        template_service = self._template_service()
        draft = self._selected_fill_draft_record()
        if template_service is None or draft is None:
            self.fill_draft_status_label.setText(
                "Select a draft to restore the last editable state."
            )
            return
        try:
            revision = template_service.fetch_revision(draft.revision_id)
            payload = template_service.fetch_draft_payload(draft.draft_id) or {}
            if revision is None:
                raise ValueError(f"Revision {draft.revision_id} not found")
        except Exception as exc:
            self.fill_draft_status_label.setText(f"Unable to load draft: {exc}")
            QMessageBox.warning(self, "Draft Workspace", str(exc))
            return
        self._select_revision_context(revision.template_id, draft.revision_id)
        self.apply_editable_payload(payload)
        self.fill_draft_name_edit.setText(draft.name)
        self._set_storage_mode_value(draft.storage_mode or STORAGE_MODE_DATABASE)
        self._loaded_draft_id = draft.draft_id
        self._fill_dirty = False
        self.refresh_fill_drafts(selected_draft_id=draft.draft_id)
        self.fill_draft_status_label.setText(
            f"Loaded draft #{draft.draft_id} and restored its editable state."
        )
        if self._fill_preview_controller is not None:
            self._fill_preview_controller.request_refresh(
                reason=f"Previewing current HTML draft state for draft #{draft.draft_id}.",
                delay_ms=0,
            )

    def reset_fill_form(self) -> None:
        self._clear_fill_input_values()
        self._loaded_draft_id = None
        self._fill_dirty = False
        self._fill_type_overrides = {}
        self._fill_payload_extras = {}
        self.fill_draft_name_edit.setText(self._draft_name_value())
        self._set_storage_mode_value(STORAGE_MODE_DATABASE)
        self._select_combo_data(self.fill_draft_combo, None)
        self.fill_draft_status_label.setText(
            "Cleared the current fill form. Saved drafts remain available to load."
        )
        self._sync_fill_export_status(None)
        if self._fill_preview_controller is not None:
            self._fill_preview_controller.request_refresh(
                reason="Previewing current HTML draft state after reset.",
                delay_ms=0,
            )
        else:
            self.clear_html_preview()

    def export_current_pdf(self) -> None:
        export_service = self._export_service()
        if export_service is None:
            self.fill_export_status_label.setText(
                "Open a profile to export contract template PDFs."
            )
            return
        try:
            draft = self._ensure_export_draft_record()
            if draft is None:
                self.fill_export_status_label.setText(
                    "Save or select a draft before exporting a PDF."
                )
                return
            result = export_service.export_draft_to_pdf(draft.draft_id)
        except Exception as exc:
            self.fill_export_status_label.setText(f"Unable to export PDF: {exc}")
            QMessageBox.warning(self, "Contract Template Export", str(exc))
            return
        self.refresh_fill_drafts(selected_draft_id=draft.draft_id)
        self.refresh_admin_workspace(
            selected_template_id=self._selected_fill_template_id(),
            selected_revision_id=self._selected_fill_revision_id(),
            selected_draft_id=draft.draft_id,
        )
        warning_text = ""
        if result.warnings:
            warning_text = " Warnings: " + " ".join(result.warnings)
        self.fill_export_status_label.setText(
            f"Exported PDF for draft #{draft.draft_id} to {result.pdf_artifact.output_path}.{warning_text}"
        )
        if self._fill_preview_controller is not None:
            self._fill_preview_controller.request_refresh(
                reason=f"Previewing current HTML draft state for draft #{draft.draft_id}.",
                delay_ms=0,
            )

    def refresh_current_html_preview(self) -> None:
        template_service = self._template_service()
        if self._fill_preview_controller is None or template_service is None:
            self.fill_preview_status_label.setText(
                "Open a profile to preview HTML contract template drafts."
            )
            return
        if QWebEngineView is None or self.fill_html_preview_view is None:
            self.fill_preview_status_label.setText(
                "Qt WebEngine is unavailable, so native HTML preview cannot be shown."
            )
            return
        revision_id = self._selected_fill_revision_id()
        revision = template_service.fetch_revision(revision_id) if revision_id is not None else None
        if revision is None or str(revision.source_format or "").strip().lower() != "html":
            self.fill_preview_status_label.setText(
                "Select an HTML template revision to render a native draft preview."
            )
            self.clear_html_preview()
            return
        self._fill_preview_controller.request_refresh(
            reason="Previewing current HTML draft state.",
            delay_ms=0,
        )

    def clear_html_preview(self) -> None:
        if self._fill_preview_controller is not None:
            self._fill_preview_controller.clear()
            return
        if self.fill_html_preview_view is not None:
            self.fill_html_preview_view.setHtml("")
        if hasattr(self, "fill_preview_status_label"):
            self.fill_preview_status_label.setText(
                "HTML preview becomes available when the selected revision is a native HTML template."
            )

    def open_latest_pdf_for_current_draft(self) -> None:
        draft = self._selected_fill_draft_record() or self._loaded_draft_record()
        artifact = self._latest_pdf_artifact_for_draft(draft)
        if artifact is None:
            self.fill_export_status_label.setText(
                "No retained PDF artifact exists for the current draft yet."
            )
            return
        opened = open_external_path(
            artifact.output_path,
            source="ContractTemplateWorkspacePanel.open_latest_pdf_for_current_draft",
            metadata={"artifact_type": artifact.artifact_type},
        )
        self.fill_export_status_label.setText(
            f"{'Opened' if opened else 'Could not open'} PDF artifact: {artifact.output_path}"
        )

    def apply_editable_payload(self, payload: object | None) -> None:
        payload_map = dict(payload or {})
        self._fill_type_overrides = {
            str(key): str(value)
            for key, value in dict(payload_map.get("type_overrides") or {}).items()
        }
        self._fill_payload_extras = {
            key: value
            for key, value in payload_map.items()
            if key not in {"revision_id", "db_selections", "manual_values", "type_overrides"}
        }
        self._clear_fill_input_values()
        db_values = dict(payload_map.get("db_selections") or {})
        manual_values = dict(payload_map.get("manual_values") or {})
        previous_suspend = self._suspend_fill_updates
        self._suspend_fill_updates = True
        try:
            for key, value in db_values.items():
                widget = self.selector_widgets.get(str(key))
                if widget is not None:
                    self._write_widget_value(widget, value, explicit=True)
            for key, value in manual_values.items():
                widget = self.manual_widgets.get(str(key))
                if widget is not None:
                    self._write_widget_value(widget, value, explicit=True)
        finally:
            self._suspend_fill_updates = previous_suspend
        self._fill_dirty = False
        if self._fill_preview_controller is not None:
            self._fill_preview_controller.request_refresh(
                reason="Previewing current HTML draft state.",
                delay_ms=0,
            )

    def copy_selected_symbol(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        self._copy_to_clipboard(entry.canonical_symbol)

    def _copy_symbol_from_index(self, index) -> None:
        if not index.isValid():
            return
        self.table.selectRow(index.row())
        entry = self._selected_entry()
        if entry is None and 0 <= index.row() < len(self._visible_entries):
            entry = self._visible_entries[index.row()]
        if entry is None:
            return
        self._copy_to_clipboard(entry.canonical_symbol)

    def copy_visible_symbols(self) -> None:
        if not self._visible_entries:
            return
        self._copy_to_clipboard("\n".join(item.canonical_symbol for item in self._visible_entries))

    def copy_manual_symbol(self) -> None:
        text = self.manual_symbol_edit.text().strip()
        if not text:
            return
        self._copy_to_clipboard(text)

    def _populate_namespace_combo(
        self,
        namespaces: tuple[str, ...],
        *,
        selected_namespace: str | None = None,
    ) -> None:
        current = str(selected_namespace or "").strip().lower() or None
        self.namespace_combo.blockSignals(True)
        self.namespace_combo.clear()
        self.namespace_combo.addItem("All Namespaces", None)
        selected_index = 0
        for index, namespace in enumerate(namespaces, start=1):
            label = namespace.replace("_", " ").title()
            self.namespace_combo.addItem(label, namespace)
            if current == namespace:
                selected_index = index
        self.namespace_combo.setCurrentIndex(selected_index)
        self.namespace_combo.blockSignals(False)

    def _populate_fill_template_combo(
        self,
        templates: tuple[object, ...],
        *,
        selected_template_id: int | None = None,
    ) -> None:
        self.fill_template_combo.blockSignals(True)
        self.fill_template_combo.clear()
        self.fill_template_combo.addItem("Choose Template", None)
        selected_index = 0
        for index, template in enumerate(templates, start=1):
            label = str(getattr(template, "name", "") or f"Template #{index}")
            if getattr(template, "active_revision_id", None) is not None:
                label = f"{label} (active revision)"
            self.fill_template_combo.addItem(label, int(template.template_id))
            if selected_template_id is not None and int(template.template_id) == int(
                selected_template_id
            ):
                selected_index = index
        if selected_index == 0 and len(templates) == 1:
            selected_index = 1
        self.fill_template_combo.setCurrentIndex(selected_index)
        self.fill_template_combo.blockSignals(False)

    def _populate_fill_revision_combo(
        self,
        revisions: tuple[object, ...],
        *,
        selected_revision_id: int | None = None,
        active_revision_id: int | None = None,
    ) -> None:
        self.fill_revision_combo.blockSignals(True)
        self.fill_revision_combo.clear()
        self.fill_revision_combo.addItem("Choose Revision", None)
        selected_index = 0
        for index, revision in enumerate(revisions, start=1):
            label_bits = [
                _clean_text(getattr(revision, "revision_label", None))
                or str(getattr(revision, "source_filename", "") or f"Revision #{index}"),
                str(getattr(revision, "scan_status", "") or "scan_pending"),
            ]
            if active_revision_id is not None and int(revision.revision_id) == int(
                active_revision_id
            ):
                label_bits.append("active")
            label = " | ".join(bit for bit in label_bits if bit)
            self.fill_revision_combo.addItem(label, int(revision.revision_id))
            if selected_revision_id is not None and int(revision.revision_id) == int(
                selected_revision_id
            ):
                selected_index = index
            elif (
                selected_index == 0
                and active_revision_id is not None
                and int(revision.revision_id) == int(active_revision_id)
            ):
                selected_index = index
        if selected_index == 0 and len(revisions) == 1:
            selected_index = 1
        self.fill_revision_combo.setCurrentIndex(selected_index)
        self.fill_revision_combo.blockSignals(False)

    def _populate_fill_draft_combo(
        self,
        drafts: tuple[ContractTemplateDraftRecord, ...],
        *,
        selected_draft_id: int | None = None,
    ) -> None:
        self.fill_draft_combo.blockSignals(True)
        self.fill_draft_combo.clear()
        self.fill_draft_combo.addItem("Choose Saved Draft", None)
        selected_index = 0
        for index, draft in enumerate(drafts, start=1):
            label = (
                f"{draft.name} | {self._storage_label(draft.storage_mode)}"
                f" | {draft.updated_at or draft.created_at or 'recent'}"
            )
            self.fill_draft_combo.addItem(label, int(draft.draft_id))
            if selected_draft_id is not None and int(draft.draft_id) == int(selected_draft_id):
                selected_index = index
        if selected_index == 0 and len(drafts) == 1:
            selected_index = 1
        self.fill_draft_combo.setCurrentIndex(selected_index)
        self.fill_draft_combo.blockSignals(False)

    def refresh_admin_workspace(
        self,
        *,
        selected_template_id: int | None = None,
        selected_revision_id: int | None = None,
        selected_draft_id: int | None = None,
        selected_snapshot_id: int | None = None,
        selected_artifact_id: int | None = None,
    ) -> None:
        if self._IMPORT_TAB_KEY not in self._tab_hosts:
            return
        template_service = self._template_service()
        selected_template_id = selected_template_id or self._selected_admin_template_id()
        selected_revision_id = selected_revision_id or self._selected_admin_revision_id()
        selected_draft_id = selected_draft_id or self._selected_admin_draft_id()
        selected_snapshot_id = selected_snapshot_id or self._selected_admin_snapshot_id()
        selected_artifact_id = selected_artifact_id or self._selected_admin_artifact_id()

        if template_service is None:
            self._suspend_admin_updates = True
            try:
                self._visible_admin_templates = []
                self._visible_admin_revisions = []
                self._visible_admin_placeholders = []
                self._visible_admin_drafts = []
                self._visible_admin_snapshots = []
                self._visible_admin_artifacts = []
                for table in (
                    self.admin_template_table,
                    self.admin_revision_table,
                    self.admin_placeholder_table,
                    self.admin_draft_table,
                    self.admin_snapshot_table,
                    self.admin_artifact_table,
                ):
                    table.setRowCount(0)
            finally:
                self._suspend_admin_updates = False
            self.admin_revision_status_label.setText(
                "Open a profile to inspect revisions and placeholder inventories."
            )
            self.admin_status_label.setText(
                "Open a profile to manage template archives, drafts, and retained output artifacts."
            )
            return

        templates = tuple(template_service.list_templates(include_archived=True))
        self._visible_admin_templates = list(templates)
        if selected_template_id is None and templates:
            selected_template_id = int(templates[0].template_id)
        self._populate_admin_template_table(templates, selected_template_id=selected_template_id)
        template_record = self._selected_admin_template_record()

        revisions: tuple[ContractTemplateRevisionRecord, ...] = ()
        if template_record is not None:
            revisions = tuple(template_service.list_revisions(template_record.template_id))
        self._visible_admin_revisions = list(revisions)
        if selected_revision_id is None and template_record is not None:
            selected_revision_id = template_record.active_revision_id
        self._populate_admin_revision_table(
            revisions,
            selected_revision_id=selected_revision_id,
            active_revision_id=(
                template_record.active_revision_id if template_record is not None else None
            ),
        )
        revision_record = self._selected_admin_revision_record()

        placeholders: tuple[ContractTemplatePlaceholderRecord, ...] = ()
        if revision_record is not None:
            placeholders = tuple(template_service.list_placeholders(revision_record.revision_id))
        self._visible_admin_placeholders = list(placeholders)
        self._populate_admin_placeholder_table(placeholders)
        if revision_record is None:
            self.admin_revision_status_label.setText(
                "Select a revision to inspect scan diagnostics and placeholder inventory."
            )
        else:
            diagnostic_text = _clean_text(revision_record.scan_error) or "No scan error recorded."
            self.admin_revision_status_label.setText(
                f"Revision #{revision_record.revision_id} is {revision_record.scan_status}. {diagnostic_text}"
            )

        drafts: tuple[ContractTemplateDraftRecord, ...] = ()
        snapshots: tuple[ContractTemplateResolvedSnapshotRecord, ...] = ()
        artifacts: tuple[ContractTemplateOutputArtifactRecord, ...] = ()
        if template_record is not None:
            drafts = tuple(
                template_service.list_template_drafts(
                    template_record.template_id,
                    include_archived=True,
                )
            )
            snapshots = tuple(
                template_service.list_template_resolved_snapshots(template_record.template_id)
            )
            artifacts = tuple(
                template_service.list_template_output_artifacts(template_record.template_id)
            )
        self._visible_admin_drafts = list(drafts)
        self._visible_admin_snapshots = list(snapshots)
        self._visible_admin_artifacts = list(artifacts)
        self._populate_admin_draft_table(drafts, selected_draft_id=selected_draft_id)
        self._populate_admin_snapshot_table(snapshots, selected_snapshot_id=selected_snapshot_id)
        self._populate_admin_artifact_table(artifacts, selected_artifact_id=selected_artifact_id)
        if template_record is None:
            self.admin_status_label.setText(
                "Import a template to start managing revisions, drafts, and retained artifacts."
            )
        else:
            self.admin_status_label.setText(
                f"Template '{template_record.name}' has {len(revisions)} revision(s), "
                f"{len(drafts)} draft(s), {len(snapshots)} snapshot(s), and {len(artifacts)} artifact(s). "
                "Deleting records does not remove files unless the action label says it does."
            )

    def _populate_admin_template_table(
        self,
        templates: tuple[ContractTemplateRecord, ...],
        *,
        selected_template_id: int | None,
    ) -> None:
        self._suspend_admin_updates = True
        try:
            self.admin_template_table.setRowCount(0)
            selected_row = 0
            for row_index, template in enumerate(templates):
                self.admin_template_table.insertRow(row_index)
                row_values = (
                    (str(template.template_id), template.template_id),
                    (template.name, None),
                    (str(template.source_format or "-"), None),
                    (str(template.active_revision_id or "-"), None),
                    ("Yes" if template.archived else "No", None),
                    (str(template.updated_at or template.created_at or "-"), None),
                )
                for column, (text, user_value) in enumerate(row_values):
                    item = QTableWidgetItem(text)
                    if column == 0:
                        item.setData(Qt.UserRole, int(template.template_id))
                    elif user_value is not None:
                        item.setData(Qt.UserRole, user_value)
                    self.admin_template_table.setItem(row_index, column, item)
                if selected_template_id is not None and int(template.template_id) == int(
                    selected_template_id
                ):
                    selected_row = row_index
            if templates:
                self.admin_template_table.selectRow(selected_row)
            self.admin_template_table.resizeColumnsToContents()
        finally:
            self._suspend_admin_updates = False

    def _populate_admin_revision_table(
        self,
        revisions: tuple[ContractTemplateRevisionRecord, ...],
        *,
        selected_revision_id: int | None,
        active_revision_id: int | None,
    ) -> None:
        self._suspend_admin_updates = True
        try:
            self.admin_revision_table.setRowCount(0)
            selected_row = 0
            for row_index, revision in enumerate(revisions):
                self.admin_revision_table.insertRow(row_index)
                revision_label = _clean_text(revision.revision_label) or revision.source_filename
                row_values = (
                    (str(revision.revision_id), revision.revision_id),
                    (revision_label, None),
                    (revision.source_format, None),
                    (revision.scan_status, None),
                    (str(revision.placeholder_count), None),
                    (
                        (
                            "Active"
                            if active_revision_id is not None
                            and int(revision.revision_id) == int(active_revision_id)
                            else ""
                        ),
                        None,
                    ),
                )
                for column, (text, user_value) in enumerate(row_values):
                    item = QTableWidgetItem(text)
                    if column == 0:
                        item.setData(Qt.UserRole, int(revision.revision_id))
                    elif user_value is not None:
                        item.setData(Qt.UserRole, user_value)
                    self.admin_revision_table.setItem(row_index, column, item)
                if selected_revision_id is not None and int(revision.revision_id) == int(
                    selected_revision_id
                ):
                    selected_row = row_index
                elif (
                    selected_revision_id is None
                    and active_revision_id is not None
                    and int(revision.revision_id) == int(active_revision_id)
                ):
                    selected_row = row_index
            if revisions:
                self.admin_revision_table.selectRow(selected_row)
            self.admin_revision_table.resizeColumnsToContents()
        finally:
            self._suspend_admin_updates = False

    def _populate_admin_placeholder_table(
        self, placeholders: tuple[ContractTemplatePlaceholderRecord, ...]
    ) -> None:
        self.admin_placeholder_table.setRowCount(0)
        for row_index, placeholder in enumerate(placeholders):
            self.admin_placeholder_table.insertRow(row_index)
            row_values = (
                placeholder.canonical_symbol,
                placeholder.display_label or placeholder.placeholder_key,
                placeholder.inferred_field_type or "-",
                "Yes" if placeholder.required else "No",
                str(placeholder.source_occurrence_count),
            )
            for column, text in enumerate(row_values):
                item = QTableWidgetItem(str(text or ""))
                if column == 0:
                    item.setData(Qt.UserRole, placeholder.canonical_symbol)
                self.admin_placeholder_table.setItem(row_index, column, item)
        self.admin_placeholder_table.resizeColumnsToContents()

    def _populate_admin_draft_table(
        self,
        drafts: tuple[ContractTemplateDraftRecord, ...],
        *,
        selected_draft_id: int | None,
    ) -> None:
        self._suspend_admin_updates = True
        try:
            self.admin_draft_table.setRowCount(0)
            selected_row = 0
            for row_index, draft in enumerate(drafts):
                self.admin_draft_table.insertRow(row_index)
                row_values = (
                    (str(draft.draft_id), draft.draft_id),
                    (draft.name, None),
                    (self._storage_label(draft.storage_mode), None),
                    (draft.status, None),
                    (str(draft.last_resolved_snapshot_id or "-"), None),
                    (str(draft.updated_at or draft.created_at or "-"), None),
                )
                for column, (text, _user_value) in enumerate(row_values):
                    item = QTableWidgetItem(text)
                    if column == 0:
                        item.setData(Qt.UserRole, int(draft.draft_id))
                    self.admin_draft_table.setItem(row_index, column, item)
                if selected_draft_id is not None and int(draft.draft_id) == int(selected_draft_id):
                    selected_row = row_index
            if drafts:
                self.admin_draft_table.selectRow(selected_row)
            self.admin_draft_table.resizeColumnsToContents()
        finally:
            self._suspend_admin_updates = False

    def _populate_admin_snapshot_table(
        self,
        snapshots: tuple[ContractTemplateResolvedSnapshotRecord, ...],
        *,
        selected_snapshot_id: int | None,
    ) -> None:
        self._suspend_admin_updates = True
        try:
            self.admin_snapshot_table.setRowCount(0)
            selected_row = 0
            for row_index, snapshot in enumerate(snapshots):
                self.admin_snapshot_table.insertRow(row_index)
                row_values = (
                    (str(snapshot.snapshot_id), snapshot.snapshot_id),
                    (str(snapshot.draft_id), None),
                    (str(snapshot.resolved_checksum_sha256 or "-"), None),
                    (str(snapshot.created_at or "-"), None),
                )
                for column, (text, _user_value) in enumerate(row_values):
                    item = QTableWidgetItem(text)
                    if column == 0:
                        item.setData(Qt.UserRole, int(snapshot.snapshot_id))
                    self.admin_snapshot_table.setItem(row_index, column, item)
                if selected_snapshot_id is not None and int(snapshot.snapshot_id) == int(
                    selected_snapshot_id
                ):
                    selected_row = row_index
            if snapshots:
                self.admin_snapshot_table.selectRow(selected_row)
            self.admin_snapshot_table.resizeColumnsToContents()
        finally:
            self._suspend_admin_updates = False

    def _populate_admin_artifact_table(
        self,
        artifacts: tuple[ContractTemplateOutputArtifactRecord, ...],
        *,
        selected_artifact_id: int | None,
    ) -> None:
        self._suspend_admin_updates = True
        try:
            self.admin_artifact_table.setRowCount(0)
            selected_row = 0
            for row_index, artifact in enumerate(artifacts):
                self.admin_artifact_table.insertRow(row_index)
                row_values = (
                    (str(artifact.artifact_id), artifact.artifact_id),
                    (artifact.artifact_type, None),
                    (artifact.output_filename, None),
                    (artifact.status, None),
                    ("Yes" if artifact.retained else "No", None),
                    (str(artifact.created_at or "-"), None),
                )
                for column, (text, _user_value) in enumerate(row_values):
                    item = QTableWidgetItem(text)
                    if column == 0:
                        item.setData(Qt.UserRole, int(artifact.artifact_id))
                    self.admin_artifact_table.setItem(row_index, column, item)
                if selected_artifact_id is not None and int(artifact.artifact_id) == int(
                    selected_artifact_id
                ):
                    selected_row = row_index
            if artifacts:
                self.admin_artifact_table.selectRow(selected_row)
            self.admin_artifact_table.resizeColumnsToContents()
        finally:
            self._suspend_admin_updates = False

    def _selected_table_id(self, table: QTableWidget) -> int | None:
        selection_model = table.selectionModel()
        if selection_model is None:
            return None
        rows = selection_model.selectedRows()
        if not rows:
            return None
        item = table.item(rows[0].row(), 0)
        if item is None:
            return None
        try:
            return int(item.data(Qt.UserRole))
        except (TypeError, ValueError):
            return None

    def _selected_admin_template_id(self) -> int | None:
        return self._selected_table_id(self.admin_template_table)

    def _selected_admin_revision_id(self) -> int | None:
        return self._selected_table_id(self.admin_revision_table)

    def _selected_admin_draft_id(self) -> int | None:
        return self._selected_table_id(self.admin_draft_table)

    def _selected_admin_snapshot_id(self) -> int | None:
        return self._selected_table_id(self.admin_snapshot_table)

    def _selected_admin_artifact_id(self) -> int | None:
        return self._selected_table_id(self.admin_artifact_table)

    def _selected_admin_template_record(self) -> ContractTemplateRecord | None:
        template_id = self._selected_admin_template_id()
        if template_id is None:
            return None
        for record in self._visible_admin_templates:
            if int(record.template_id) == int(template_id):
                return record
        return None

    def _selected_admin_revision_record(self) -> ContractTemplateRevisionRecord | None:
        revision_id = self._selected_admin_revision_id()
        if revision_id is None:
            return None
        for record in self._visible_admin_revisions:
            if int(record.revision_id) == int(revision_id):
                return record
        return None

    def _selected_admin_draft_record(self) -> ContractTemplateDraftRecord | None:
        draft_id = self._selected_admin_draft_id()
        if draft_id is None:
            return None
        for record in self._visible_admin_drafts:
            if int(record.draft_id) == int(draft_id):
                return record
        return None

    def _selected_admin_artifact_record(self) -> ContractTemplateOutputArtifactRecord | None:
        artifact_id = self._selected_admin_artifact_id()
        if artifact_id is None:
            return None
        for record in self._visible_admin_artifacts:
            if int(record.artifact_id) == int(artifact_id):
                return record
        return None

    def _choose_template_source_path(self, *, title: str) -> Path | None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            "Template Documents (*.docx *.pages *.html *.htm *.zip);;HTML Templates (*.html *.htm);;HTML Template Packages (*.zip);;Word Documents (*.docx);;Pages Documents (*.pages)",
        )
        clean_path = str(file_path or "").strip()
        return Path(clean_path) if clean_path else None

    def import_template_from_file(self) -> None:
        template_service = self._template_service()
        if template_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        source_path = self._choose_template_source_path(title="Import Contract Template")
        if source_path is None:
            return
        default_name = source_path.stem or "Contract Template"
        name, accepted = QInputDialog.getText(
            self,
            "Import Contract Template",
            "Template Name",
            text=default_name,
        )
        if not accepted:
            return
        clean_name = _clean_text(name) or default_name
        try:
            is_zip_package = source_path.suffix.lower() == ".zip"
            source_format = (
                "html"
                if is_zip_package
                else detect_template_source_format(source_filename=source_path.name)
            )
            template = template_service.create_template(
                ContractTemplatePayload(name=clean_name, source_format=source_format)
            )
            if is_zip_package:
                result = template_service.import_html_package_from_path(
                    template.template_id,
                    source_path,
                    payload=ContractTemplateRevisionPayload(
                        source_filename=source_path.name,
                        source_format="html",
                    ),
                )
            else:
                result = template_service.import_revision_from_path(
                    template.template_id,
                    source_path,
                    payload=ContractTemplateRevisionPayload(
                        source_filename=source_path.name,
                        source_format=source_format,
                    ),
                )
        except Exception as exc:
            QMessageBox.warning(self, "Import Contract Template", str(exc))
            self.admin_status_label.setText(f"Unable to import template: {exc}")
            return
        self.refresh()
        self.refresh_admin_workspace(
            selected_template_id=template.template_id,
            selected_revision_id=result.revision.revision_id,
        )
        self.admin_status_label.setText(
            f"Imported template '{template.name}' with revision #{result.revision.revision_id} ({result.scan_result.scan_status})."
        )

    def add_revision_from_file(self) -> None:
        template_service = self._template_service()
        template = self._selected_admin_template_record()
        if template_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if template is None:
            QMessageBox.information(
                self,
                "Add Template Revision",
                "Select a template row before adding a new revision.",
            )
            return
        source_path = self._choose_template_source_path(title="Add Contract Template Revision")
        if source_path is None:
            return
        try:
            if source_path.suffix.lower() == ".zip":
                result = template_service.import_html_package_from_path(
                    template.template_id,
                    source_path,
                    payload=ContractTemplateRevisionPayload(
                        source_filename=source_path.name,
                        source_format="html",
                    ),
                )
            else:
                source_format = detect_template_source_format(source_filename=source_path.name)
                result = template_service.import_revision_from_path(
                    template.template_id,
                    source_path,
                    payload=ContractTemplateRevisionPayload(
                        source_filename=source_path.name,
                        source_format=source_format,
                    ),
                )
        except Exception as exc:
            QMessageBox.warning(self, "Add Template Revision", str(exc))
            self.admin_status_label.setText(f"Unable to add revision: {exc}")
            return
        self.refresh()
        self.refresh_admin_workspace(
            selected_template_id=template.template_id,
            selected_revision_id=result.revision.revision_id,
        )
        self.admin_status_label.setText(
            f"Added revision #{result.revision.revision_id} to '{template.name}' ({result.scan_result.scan_status})."
        )

    def duplicate_selected_template(self) -> None:
        template_service = self._template_service()
        template = self._selected_admin_template_record()
        if template_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if template is None:
            QMessageBox.information(
                self,
                "Duplicate Template",
                "Select a template row before duplicating it.",
            )
            return
        try:
            duplicated = template_service.duplicate_template(template.template_id)
        except Exception as exc:
            QMessageBox.warning(self, "Duplicate Template", str(exc))
            self.admin_status_label.setText(f"Unable to duplicate template: {exc}")
            return
        self.refresh()
        self.refresh_admin_workspace(selected_template_id=duplicated.template_id)
        self.admin_status_label.setText(
            f"Duplicated template '{template.name}' as '{duplicated.name}'."
        )

    def toggle_selected_template_archive(self) -> None:
        template_service = self._template_service()
        template = self._selected_admin_template_record()
        if template_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if template is None:
            QMessageBox.information(self, "Archive Template", "Select a template row first.")
            return
        try:
            updated = template_service.archive_template(
                template.template_id,
                archived=not template.archived,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Archive Template", str(exc))
            self.admin_status_label.setText(f"Unable to update template archive state: {exc}")
            return
        self.refresh()
        self.refresh_admin_workspace(selected_template_id=updated.template_id)
        self.admin_status_label.setText(
            f"{'Archived' if updated.archived else 'Restored'} template '{updated.name}'."
        )

    def delete_selected_template_record(self) -> None:
        template_service = self._template_service()
        template = self._selected_admin_template_record()
        if template_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if template is None:
            QMessageBox.information(self, "Delete Template Record", "Select a template row first.")
            return
        if not _confirm_destructive_action(
            self,
            title="Delete Contract Template Record",
            prompt=f"Delete the database record for '{template.name}'?",
            consequences=[
                "This removes template, revision, draft, snapshot, and artifact rows from the database only.",
                "Managed source, draft, and artifact files remain on disk unless you choose a delete-with-files action instead.",
            ],
        ):
            return
        try:
            template_service.delete_template(template.template_id)
        except Exception as exc:
            QMessageBox.warning(self, "Delete Template Record", str(exc))
            self.admin_status_label.setText(f"Unable to delete template record: {exc}")
            return
        self.refresh()
        self.admin_status_label.setText(
            f"Deleted the database record for template '{template.name}'."
        )

    def delete_selected_template_with_files(self) -> None:
        template_service = self._template_service()
        template = self._selected_admin_template_record()
        if template_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if template is None:
            QMessageBox.information(self, "Delete Template + Files", "Select a template row first.")
            return
        if not _confirm_destructive_action(
            self,
            title="Delete Contract Template And Files",
            prompt=f"Delete '{template.name}' and its retained managed files?",
            consequences=[
                "This removes the database record and also deletes managed source, draft, and artifact files under the contract template storage roots.",
                "Only managed files inside the contract template storage roots are deleted.",
            ],
        ):
            return
        try:
            template_service.delete_template(
                template.template_id,
                remove_source_files=True,
                remove_draft_files=True,
                remove_output_files=True,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Delete Template + Files", str(exc))
            self.admin_status_label.setText(f"Unable to delete template and files: {exc}")
            return
        self.refresh()
        self.admin_status_label.setText(
            f"Deleted template '{template.name}' and its managed files."
        )

    def rescan_selected_revision(self) -> None:
        template_service = self._template_service()
        template = self._selected_admin_template_record()
        revision = self._selected_admin_revision_record()
        if template_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if revision is None:
            QMessageBox.information(self, "Rescan Revision", "Select a revision row first.")
            return
        try:
            result = template_service.rescan_revision(
                revision.revision_id,
                preserve_bindings=True,
                activate_if_ready=(
                    template is not None
                    and template.active_revision_id is not None
                    and int(template.active_revision_id) == int(revision.revision_id)
                ),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Rescan Revision", str(exc))
            self.admin_status_label.setText(f"Unable to rescan revision: {exc}")
            return
        self.refresh()
        self.refresh_admin_workspace(
            selected_template_id=revision.template_id,
            selected_revision_id=revision.revision_id,
        )
        self.admin_status_label.setText(
            f"Rescanned revision #{revision.revision_id} ({result.scan_status})."
        )

    def rebind_selected_revision(self) -> None:
        form_service = self._form_service()
        revision = self._selected_admin_revision_record()
        if form_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if revision is None:
            QMessageBox.information(
                self,
                "Rebind Placeholders",
                "Select a revision row before refreshing placeholder bindings.",
            )
            return
        try:
            bindings = form_service.synchronize_bindings(revision.revision_id)
        except Exception as exc:
            QMessageBox.warning(self, "Rebind Placeholders", str(exc))
            self.admin_status_label.setText(f"Unable to rebind placeholders: {exc}")
            return
        self.refresh_admin_workspace(
            selected_template_id=revision.template_id,
            selected_revision_id=revision.revision_id,
        )
        self.admin_status_label.setText(
            f"Rebound {len(bindings)} placeholder binding(s) for revision #{revision.revision_id}."
        )

    def activate_selected_revision(self) -> None:
        template_service = self._template_service()
        revision = self._selected_admin_revision_record()
        if template_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if revision is None:
            QMessageBox.information(self, "Set Active Revision", "Select a revision row first.")
            return
        try:
            template_service.set_active_revision(revision.revision_id)
        except Exception as exc:
            QMessageBox.warning(self, "Set Active Revision", str(exc))
            self.admin_status_label.setText(f"Unable to activate revision: {exc}")
            return
        self.refresh()
        self.refresh_admin_workspace(
            selected_template_id=revision.template_id,
            selected_revision_id=revision.revision_id,
        )
        self.admin_status_label.setText(
            f"Set revision #{revision.revision_id} as the active revision."
        )

    def open_selected_draft_in_fill_tab(self) -> None:
        draft = self._selected_admin_draft_record()
        template_service = self._template_service()
        if template_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if draft is None:
            QMessageBox.information(self, "Open Draft In Fill Tab", "Select a draft row first.")
            return
        revision = template_service.fetch_revision(draft.revision_id)
        if revision is None:
            QMessageBox.warning(
                self,
                "Open Draft In Fill Tab",
                f"Revision #{draft.revision_id} no longer exists.",
            )
            return
        self.focus_tab("fill")
        self._select_revision_context(revision.template_id, revision.revision_id)
        self.refresh_fill_drafts(selected_draft_id=draft.draft_id)
        self._select_combo_data(self.fill_draft_combo, draft.draft_id)
        self.load_selected_draft()

    def export_selected_admin_draft(self) -> None:
        export_service = self._export_service()
        draft = self._selected_admin_draft_record()
        if export_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if draft is None:
            QMessageBox.information(
                self,
                "Export Selected Draft PDF",
                "Select a draft row before exporting it.",
            )
            return
        try:
            result = export_service.export_draft_to_pdf(draft.draft_id)
        except Exception as exc:
            QMessageBox.warning(self, "Export Selected Draft PDF", str(exc))
            self.admin_status_label.setText(f"Unable to export draft: {exc}")
            return
        self.refresh()
        self.refresh_admin_workspace(
            selected_template_id=self._selected_admin_template_id(),
            selected_draft_id=draft.draft_id,
            selected_snapshot_id=result.snapshot.snapshot_id,
            selected_artifact_id=result.pdf_artifact.artifact_id,
        )
        self.admin_status_label.setText(
            f"Exported draft #{draft.draft_id} to {result.pdf_artifact.output_path}."
        )

    def toggle_selected_draft_archive(self) -> None:
        template_service = self._template_service()
        draft = self._selected_admin_draft_record()
        if template_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if draft is None:
            QMessageBox.information(self, "Archive Draft", "Select a draft row first.")
            return
        try:
            updated = template_service.archive_draft(
                draft.draft_id,
                archived=str(draft.status or "").strip().lower() != "archived",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Archive Draft", str(exc))
            self.admin_status_label.setText(f"Unable to update draft archive state: {exc}")
            return
        self.refresh_admin_workspace(
            selected_template_id=self._selected_admin_template_id(),
            selected_draft_id=updated.draft_id,
        )
        self.admin_status_label.setText(
            f"{'Archived' if updated.status == 'archived' else 'Restored'} draft '{updated.name}'."
        )

    def delete_selected_draft_record(self) -> None:
        template_service = self._template_service()
        draft = self._selected_admin_draft_record()
        if template_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if draft is None:
            QMessageBox.information(self, "Delete Draft Record", "Select a draft row first.")
            return
        if not _confirm_destructive_action(
            self,
            title="Delete Contract Template Draft Record",
            prompt=f"Delete the database record for draft '{draft.name}'?",
            consequences=[
                "This removes the draft row and its snapshot/artifact rows from the database only.",
                "Managed draft payloads and retained output files remain on disk unless you choose delete-with-files.",
            ],
        ):
            return
        try:
            template_service.delete_draft(draft.draft_id)
        except Exception as exc:
            QMessageBox.warning(self, "Delete Draft Record", str(exc))
            self.admin_status_label.setText(f"Unable to delete draft record: {exc}")
            return
        self.refresh()
        self.refresh_admin_workspace(selected_template_id=self._selected_admin_template_id())
        self.admin_status_label.setText(f"Deleted the database record for draft '{draft.name}'.")

    def delete_selected_draft_with_files(self) -> None:
        template_service = self._template_service()
        draft = self._selected_admin_draft_record()
        if template_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if draft is None:
            QMessageBox.information(self, "Delete Draft + Files", "Select a draft row first.")
            return
        if not _confirm_destructive_action(
            self,
            title="Delete Contract Template Draft And Files",
            prompt=f"Delete draft '{draft.name}' and its retained managed files?",
            consequences=[
                "This removes the draft row and also deletes its managed payload plus retained output artifacts inside the contract template storage roots.",
                "Only managed files inside the contract template storage roots are deleted.",
            ],
        ):
            return
        try:
            template_service.delete_draft(
                draft.draft_id,
                remove_managed_payload=True,
                remove_output_files=True,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Delete Draft + Files", str(exc))
            self.admin_status_label.setText(f"Unable to delete draft and files: {exc}")
            return
        self.refresh()
        self.refresh_admin_workspace(selected_template_id=self._selected_admin_template_id())
        self.admin_status_label.setText(f"Deleted draft '{draft.name}' and its managed files.")

    def open_selected_artifact(self) -> None:
        artifact = self._selected_admin_artifact_record()
        if artifact is None:
            QMessageBox.information(
                self,
                "Open Selected Artifact",
                "Select an artifact row first.",
            )
            return
        opened = open_external_path(
            artifact.output_path,
            source="ContractTemplateWorkspacePanel.open_selected_artifact",
            metadata={"artifact_type": artifact.artifact_type},
        )
        self.admin_status_label.setText(
            f"{'Opened' if opened else 'Could not open'} artifact: {artifact.output_path}"
        )

    def delete_selected_artifact_record(self) -> None:
        self._delete_selected_artifact(remove_file=False)

    def delete_selected_artifact_with_file(self) -> None:
        self._delete_selected_artifact(remove_file=True)

    def _delete_selected_artifact(self, *, remove_file: bool) -> None:
        template_service = self._template_service()
        artifact = self._selected_admin_artifact_record()
        if template_service is None:
            QMessageBox.warning(self, "Contract Template Workspace", "Open a profile first.")
            return
        if artifact is None:
            QMessageBox.information(
                self,
                "Delete Artifact",
                "Select an artifact row first.",
            )
            return
        title = "Delete Artifact File + Record" if remove_file else "Delete Artifact Record"
        consequences = [
            (
                "This removes only the database record for the selected artifact."
                if not remove_file
                else "This removes the database record and deletes the retained managed artifact file."
            )
        ]
        if not remove_file:
            consequences.append(
                "The retained PDF or resolved DOCX file remains on disk unless you choose the file-delete action instead."
            )
        if not _confirm_destructive_action(
            self,
            title=title,
            prompt=f"Delete artifact '{artifact.output_filename}'?",
            consequences=consequences,
        ):
            return
        try:
            template_service.delete_output_artifact(artifact.artifact_id, remove_file=remove_file)
        except Exception as exc:
            QMessageBox.warning(self, title, str(exc))
            self.admin_status_label.setText(f"Unable to delete artifact: {exc}")
            return
        self.refresh_admin_workspace(selected_template_id=self._selected_admin_template_id())
        self.admin_status_label.setText(
            f"Deleted artifact '{artifact.output_filename}'"
            + (" and its retained file." if remove_file else ".")
        )

    def _on_admin_template_changed(self) -> None:
        if self._suspend_admin_updates:
            return
        self.refresh_admin_workspace(selected_template_id=self._selected_admin_template_id())

    def _on_admin_revision_changed(self) -> None:
        if self._suspend_admin_updates:
            return
        self.refresh_admin_workspace(
            selected_template_id=self._selected_admin_template_id(),
            selected_revision_id=self._selected_admin_revision_id(),
            selected_draft_id=self._selected_admin_draft_id(),
            selected_snapshot_id=self._selected_admin_snapshot_id(),
            selected_artifact_id=self._selected_admin_artifact_id(),
        )

    def _on_admin_draft_changed(self) -> None:
        if self._suspend_admin_updates:
            return
        draft = self._selected_admin_draft_record()
        if draft is None:
            return
        self.admin_status_label.setText(
            f"Selected draft #{draft.draft_id} is {self._storage_label(draft.storage_mode)} and currently {draft.status}."
        )

    def _selected_symbol(self) -> str | None:
        if not hasattr(self, "table"):
            return None
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return None
        rows = selection_model.selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 4)
        if item is None:
            return None
        return str(item.data(Qt.UserRole) or item.text() or "").strip() or None

    def _selected_fill_template_id(self) -> int | None:
        if not hasattr(self, "fill_template_combo"):
            return None
        value = self.fill_template_combo.currentData()
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _selected_fill_revision_id(self) -> int | None:
        if not hasattr(self, "fill_revision_combo"):
            return None
        value = self.fill_revision_combo.currentData()
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _selected_fill_draft_id(self) -> int | None:
        if not hasattr(self, "fill_draft_combo"):
            return None
        value = self.fill_draft_combo.currentData()
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _selected_fill_draft_record(self) -> ContractTemplateDraftRecord | None:
        draft_id = self._selected_fill_draft_id()
        if draft_id is None:
            return None
        for record in self._visible_drafts:
            if int(record.draft_id) == int(draft_id):
                return record
        return None

    def _loaded_draft_record(self) -> ContractTemplateDraftRecord | None:
        if self._loaded_draft_id is None:
            return None
        for record in self._visible_drafts:
            if int(record.draft_id) == int(self._loaded_draft_id):
                return record
        return None

    def _draft_payload_for_revision(self, revision_id: int) -> ContractTemplateDraftPayload:
        current_record = self._selected_fill_draft_record() or self._loaded_draft_record()
        return ContractTemplateDraftPayload(
            revision_id=int(revision_id),
            name=self._draft_name_value(),
            editable_payload=self.current_fill_state(),
            status=(current_record.status if current_record is not None else "draft"),
            scope_entity_type=(
                current_record.scope_entity_type if current_record is not None else None
            ),
            scope_entity_id=(
                current_record.scope_entity_id if current_record is not None else None
            ),
            storage_mode=self._selected_storage_mode_value(),
            filename=(current_record.filename if current_record is not None else None),
            mime_type=(
                current_record.mime_type if current_record is not None else "application/json"
            ),
            last_resolved_snapshot_id=(
                current_record.last_resolved_snapshot_id if current_record is not None else None
            ),
        )

    def _draft_name_value(self) -> str:
        clean_name = _clean_text(self.fill_draft_name_edit.text())
        if clean_name:
            return clean_name
        if self._fill_definition is None:
            return "Contract Template Draft"
        revision_label = _clean_text(self._fill_definition.revision_label) or (
            f"Revision {self._fill_definition.revision_id}"
        )
        return f"{self._fill_definition.template_name} - {revision_label} Draft"

    def _selected_storage_mode_value(self) -> str:
        clean_mode = _clean_text(self.fill_draft_storage_combo.currentData())
        if clean_mode in {STORAGE_MODE_DATABASE, STORAGE_MODE_MANAGED_FILE}:
            return str(clean_mode)
        return STORAGE_MODE_DATABASE

    def _set_storage_mode_value(self, storage_mode: str) -> None:
        self._select_combo_data(self.fill_draft_storage_combo, storage_mode)

    def _sync_html_preview_state(self, revision_id: int | None) -> None:
        template_service = self._template_service()
        revision = (
            template_service.fetch_revision(revision_id)
            if template_service is not None and revision_id is not None
            else None
        )
        is_html = (
            revision is not None and str(revision.source_format or "").strip().lower() == "html"
        )
        if hasattr(self, "fill_preview_button"):
            self.fill_preview_button.setEnabled(
                bool(is_html and self.fill_html_preview_view is not None)
            )
        if hasattr(self, "fill_preview_clear_button"):
            self.fill_preview_clear_button.setEnabled(self.fill_html_preview_view is not None)
        if self._fill_preview_controller is not None:
            self._fill_preview_controller.set_revision_context(revision_id if is_html else None)
        if not is_html:
            self.clear_html_preview()
        elif self._fill_preview_controller is not None:
            self._fill_preview_controller.request_refresh(
                reason="Previewing current HTML draft state.",
                delay_ms=0,
            )

    @staticmethod
    def _storage_label(storage_mode: str | None) -> str:
        return (
            "managed file"
            if _clean_text(storage_mode) == STORAGE_MODE_MANAGED_FILE
            else "database embedded"
        )

    def _clear_fill_drafts(self, status_text: str) -> None:
        self._visible_drafts = []
        self._loaded_draft_id = None
        self._fill_type_overrides = {}
        self._fill_payload_extras = {}
        self._populate_fill_draft_combo(())
        self.fill_draft_name_edit.setText(self._draft_name_value())
        self._set_storage_mode_value(STORAGE_MODE_DATABASE)
        self.fill_draft_status_label.setText(status_text)
        self._sync_fill_export_status(None)

    def _sync_draft_controls_from_selection(
        self, record: ContractTemplateDraftRecord | None
    ) -> None:
        if record is None:
            self.fill_draft_name_edit.setText(self._draft_name_value())
            return
        self.fill_draft_name_edit.setText(record.name)
        self._set_storage_mode_value(record.storage_mode or STORAGE_MODE_DATABASE)
        self.fill_draft_status_label.setText(
            f"Selected draft #{record.draft_id} is {self._storage_label(record.storage_mode)} "
            f"and was last updated {record.updated_at or record.created_at or 'recently'}."
        )

    def _sync_fill_export_status(self, record: ContractTemplateDraftRecord | None) -> None:
        artifact = self._latest_pdf_artifact_for_draft(record)
        if record is None:
            self.fill_export_status_label.setText(
                "Export saves the current editable state to a draft before writing PDF artifacts."
            )
            return
        if artifact is None:
            self.fill_export_status_label.setText(
                f"Draft #{record.draft_id} has not produced a retained PDF artifact yet."
            )
            return
        self.fill_export_status_label.setText(
            f"Latest PDF for draft #{record.draft_id}: {artifact.output_path}"
        )

    def _ensure_export_draft_record(self) -> ContractTemplateDraftRecord | None:
        target = self._loaded_draft_record() or self._selected_fill_draft_record()
        if target is None:
            if not self._save_draft(save_as_new=True):
                return None
            return self._loaded_draft_record() or self._selected_fill_draft_record()
        if self._fill_dirty:
            if not self._save_draft(save_as_new=False):
                return None
            return self._loaded_draft_record() or self._selected_fill_draft_record()
        return self._loaded_draft_record() or self._selected_fill_draft_record()

    def _latest_pdf_artifact_for_draft(
        self, draft: ContractTemplateDraftRecord | None
    ) -> ContractTemplateOutputArtifactRecord | None:
        if draft is None:
            return None
        template_service = self._template_service()
        if template_service is None:
            return None
        snapshot_id = draft.last_resolved_snapshot_id
        if snapshot_id is not None:
            artifacts = template_service.list_output_artifacts(snapshot_id=int(snapshot_id))
            for artifact in artifacts:
                if artifact.artifact_type == "pdf":
                    return artifact
        for snapshot in template_service.list_resolved_snapshots(draft_id=draft.draft_id):
            for artifact in template_service.list_output_artifacts(
                snapshot_id=snapshot.snapshot_id
            ):
                if artifact.artifact_type == "pdf":
                    return artifact
        return None

    def _clear_fill_input_values(self) -> None:
        previous_suspend = self._suspend_fill_updates
        self._suspend_fill_updates = True
        try:
            for widget in self.selector_widgets.values():
                previous_signal_state = widget.blockSignals(True)
                try:
                    self._write_widget_value(widget, None, explicit=False)
                finally:
                    widget.blockSignals(previous_signal_state)
            for widget in self.manual_widgets.values():
                previous_signal_state = widget.blockSignals(True)
                try:
                    self._write_widget_value(widget, None, explicit=False)
                finally:
                    widget.blockSignals(previous_signal_state)
        finally:
            self._suspend_fill_updates = previous_suspend
        self._fill_dirty = False

    def _write_widget_value(
        self,
        widget: QWidget,
        value: object | None,
        *,
        explicit: bool,
    ) -> None:
        if isinstance(widget, QComboBox):
            if not explicit or value is None:
                widget.setCurrentIndex(0)
                return
            index = widget.findData(value)
            if index < 0:
                index = widget.findData(str(value))
            if index < 0:
                index = widget.findText(str(value))
            widget.setCurrentIndex(index if index >= 0 else 0)
            return
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value) if explicit else False)
            widget.setProperty("has_user_value", bool(explicit))
            return
        if isinstance(widget, QDoubleSpinBox):
            widget.setValue(float(value) if explicit and value is not None else 0.0)
            widget.setProperty("has_user_value", bool(explicit))
            return
        if isinstance(widget, QDateEdit):
            if explicit and value is not None:
                date_value = QDate.fromString(str(value), Qt.ISODate)
                if not date_value.isValid():
                    date_value = QDate.fromString(str(value), "yyyy-MM-dd")
                widget.setDate(date_value if date_value.isValid() else QDate.currentDate())
                widget.setProperty("has_user_value", bool(date_value.isValid()))
            else:
                widget.setDate(QDate.currentDate())
                widget.setProperty("has_user_value", False)
            return
        if isinstance(widget, QLineEdit):
            widget.setText(str(value) if explicit and value is not None else "")

    @staticmethod
    def _read_widget_value(widget: QWidget) -> object | None:
        if isinstance(widget, QComboBox):
            value = widget.currentData()
            return value if value is not None else None
        if isinstance(widget, QCheckBox):
            if not bool(widget.property("has_user_value")):
                return None
            return bool(widget.isChecked())
        if isinstance(widget, QDoubleSpinBox):
            if not bool(widget.property("has_user_value")):
                return None
            value = float(widget.value())
            return int(value) if value.is_integer() else value
        if isinstance(widget, QDateEdit):
            if not bool(widget.property("has_user_value")):
                return None
            return widget.date().toString("yyyy-MM-dd")
        if isinstance(widget, QLineEdit):
            return _clean_text(widget.text())
        return None

    def _mark_fill_dirty(self) -> None:
        if self._suspend_fill_updates:
            return
        self._fill_dirty = True
        if "_html_draft" in self._fill_payload_extras:
            self._fill_payload_extras.pop("_html_draft", None)
        if self._loaded_draft_id is not None:
            self.fill_draft_status_label.setText(
                f"Draft #{self._loaded_draft_id} has unsaved changes."
            )
        else:
            self.fill_draft_status_label.setText("Current fill form has unsaved changes.")
        if self._fill_preview_controller is not None:
            self._fill_preview_controller.mark_stale(
                "Preview stale. Refreshing current draft state..."
            )
            self._fill_preview_controller.request_refresh(
                reason="Previewing current HTML draft state.",
                delay_ms=180,
            )

    def _select_combo_data(self, combo: QComboBox, data_value: object | None) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == data_value:
                combo.setCurrentIndex(index)
                return
        combo.setCurrentIndex(0)

    def _select_revision_context(self, template_id: int, revision_id: int) -> None:
        previous_suspend = self._suspend_fill_updates
        self._suspend_fill_updates = True
        try:
            self._select_combo_data(self.fill_template_combo, int(template_id))
        finally:
            self._suspend_fill_updates = previous_suspend
        self.refresh_fill_form()
        previous_suspend = self._suspend_fill_updates
        self._suspend_fill_updates = True
        try:
            self._select_combo_data(self.fill_revision_combo, int(revision_id))
        finally:
            self._suspend_fill_updates = previous_suspend
        self.refresh_fill_form()

    def _restore_selection(self, canonical_symbol: str | None) -> None:
        if canonical_symbol:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 4)
                if item is None:
                    continue
                candidate = str(item.data(Qt.UserRole) or item.text() or "").strip()
                if candidate == canonical_symbol:
                    self.table.selectRow(row)
                    return
        if self.table.rowCount() > 0:
            self.table.selectRow(0)
        else:
            self.table.clearSelection()

    def _selected_entry(self) -> ContractTemplateCatalogEntry | None:
        canonical_symbol = self._selected_symbol()
        if not canonical_symbol:
            return None
        for entry in self._visible_entries:
            if entry.canonical_symbol == canonical_symbol:
                return entry
        return None

    def _update_selected_details(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            self.selected_label_value.setText("No symbol selected.")
            self.selected_namespace_value.setText("-")
            self.selected_type_value.setText("-")
            self.selected_scope_value.setText("-")
            self.selected_source_value.setText("-")
            self.selected_symbol_edit.clear()
            self.detail_resolver_label.setText("Resolver Target: -")
            self.detail_source_label.setText("Source Kind: -")
            self.selected_description_value.setText("Choose a symbol to see more detail.")
            return

        self.selected_label_value.setText(entry.display_label)
        self.selected_namespace_value.setText(str(entry.namespace or "-"))
        self.selected_type_value.setText(entry.field_type.replace("_", " "))
        self.selected_scope_value.setText(self._scope_label(entry))
        source_parts = [part for part in (entry.source_table, entry.source_column) if part]
        self.selected_source_value.setText(".".join(source_parts) if source_parts else "-")
        self.selected_symbol_edit.setText(entry.canonical_symbol)
        resolver_parts = []
        if entry.scope_entity_type:
            resolver_parts.append(str(entry.scope_entity_type).replace("_", " ").title())
        if entry.scope_policy:
            resolver_parts.append(self._scope_label(entry))
        resolver_text = " | ".join(resolver_parts) if resolver_parts else "-"
        self.detail_resolver_label.setText(f"Resolver Target: {resolver_text}")
        self.detail_source_label.setText(f"Source Kind: {entry.source_kind}")
        description = str(entry.description or "").strip()
        if entry.custom_field_id is not None:
            custom_field_note = f"Custom Field ID: {entry.custom_field_id}"
            description = (
                f"{description}\n{custom_field_note}" if description else custom_field_note
            )
        if entry.options:
            option_text = ", ".join(entry.options)
            description = (
                f"{description}\nOptions: {option_text}"
                if description
                else f"Options: {option_text}"
            )
        self.selected_description_value.setText(description or "No additional guidance recorded.")

    def _refresh_manual_symbol_preview(self) -> None:
        service = self._catalog_service()
        raw_value = self.manual_key_edit.text()
        if service is None:
            self.manual_symbol_edit.clear()
            self.manual_feedback_label.setText(
                "Open a profile to use the manual placeholder helper."
            )
            return
        if not raw_value.strip():
            self.manual_symbol_edit.clear()
            self.manual_feedback_label.setText(
                "Generated manual symbols use the canonical Phase 1 grammar: "
                "{{manual.your_field_name}}."
            )
            return
        try:
            symbol = service.build_manual_symbol(raw_value)
        except ValueError as exc:
            self.manual_symbol_edit.clear()
            self.manual_feedback_label.setText(str(exc))
            return
        self.manual_symbol_edit.setText(symbol)
        self.manual_feedback_label.setText(
            "Manual symbols are parser-safe and remain outside the authoritative "
            "DB-backed catalog."
        )

    def _on_fill_template_changed(self) -> None:
        if self._suspend_fill_updates:
            return
        self._loaded_draft_id = None
        self._fill_type_overrides = {}
        self._fill_payload_extras = {}
        self._fill_dirty = False
        self.refresh_fill_form()

    def _on_fill_revision_changed(self) -> None:
        if self._suspend_fill_updates:
            return
        self._loaded_draft_id = None
        self._fill_type_overrides = {}
        self._fill_payload_extras = {}
        self._fill_dirty = False
        self.refresh_fill_form()

    def _on_fill_draft_changed(self) -> None:
        if self._suspend_fill_updates:
            return
        record = self._selected_fill_draft_record()
        self._sync_draft_controls_from_selection(record)
        self._sync_fill_export_status(record)

    def _rebuild_fill_fields(self, form_definition: ContractTemplateFormDefinition) -> None:
        self._clear_fill_fields()
        for field in form_definition.auto_fields:
            widget = self._build_auto_field_widget(field)
            self.fill_auto_form.addRow(field.display_label, widget)
        for field in form_definition.selector_fields:
            widget = self._build_selector_widget(field)
            for placeholder_symbol in field.placeholder_symbols:
                self.selector_widgets[placeholder_symbol] = widget
            self.fill_selector_form.addRow(field.display_label, widget)
        for field in form_definition.manual_fields:
            widget = self._build_manual_widget(field)
            self.manual_widgets[field.canonical_symbol] = widget
            self.fill_manual_form.addRow(field.display_label, widget)
        self.fill_auto_empty_label.setVisible(not bool(form_definition.auto_fields))
        self.fill_selector_empty_label.setVisible(not bool(form_definition.selector_fields))
        self.fill_manual_empty_label.setVisible(not bool(form_definition.manual_fields))

    def _clear_fill_fields(self) -> None:
        self._clear_form_layout(self.fill_auto_form)
        self._clear_form_layout(self.fill_selector_form)
        self._clear_form_layout(self.fill_manual_form)
        self.selector_widgets = {}
        self.manual_widgets = {}
        self.fill_auto_empty_label.setVisible(True)
        self.fill_selector_empty_label.setVisible(True)
        self.fill_manual_empty_label.setVisible(True)

    def _clear_form_layout(self, layout: QFormLayout) -> None:
        while layout.rowCount() > 0:
            layout.removeRow(0)

    def _build_selector_widget(self, field: ContractTemplateFormSelectorField) -> QComboBox:
        combo = QComboBox(self.fill_form_tab)
        combo.setObjectName("contractTemplateSelectorWidget")
        combo.setProperty("selector_key", field.selector_key)
        combo.setProperty("placeholder_symbols", list(field.placeholder_symbols))
        combo.setProperty("scope_entity_type", field.scope_entity_type)
        combo.setProperty("scope_policy", field.scope_policy)
        combo.setProperty("widget_kind", field.widget_kind)
        if field.description:
            combo.setToolTip(field.description)
        combo.addItem(f"Choose {field.display_label}", None)
        for choice in field.choices:
            combo.addItem(choice.label, choice.value)
            if choice.description:
                combo.setItemData(combo.count() - 1, choice.description, Qt.ToolTipRole)
        combo.currentIndexChanged.connect(self._mark_fill_dirty)
        return combo

    def _build_auto_field_widget(self, field: ContractTemplateFormAutoField) -> QLabel:
        label = QLabel(field.source_label, self.fill_form_tab)
        label.setWordWrap(True)
        label.setProperty("role", "secondary")
        tooltip_parts = [field.canonical_symbol]
        if field.description:
            tooltip_parts.append(field.description)
        label.setToolTip("\n".join(part for part in tooltip_parts if part))
        return label

    def _build_manual_widget(self, field: ContractTemplateFormManualField) -> QWidget:
        if field.field_type == "boolean":
            checkbox = QCheckBox("Yes", self.fill_form_tab)
            checkbox.setObjectName("contractTemplateManualBooleanWidget")
            checkbox.setProperty("canonical_symbol", field.canonical_symbol)
            checkbox.setProperty("field_type", field.field_type)
            checkbox.setProperty("widget_kind", field.widget_kind)
            checkbox.setProperty("has_user_value", False)

            def _handle_boolean_toggle(_checked: bool, *, widget=checkbox) -> None:
                widget.setProperty("has_user_value", True)
                self._mark_fill_dirty()

            checkbox.toggled.connect(_handle_boolean_toggle)
            return checkbox

        if field.options:
            combo = QComboBox(self.fill_form_tab)
            combo.setObjectName("contractTemplateManualOptionsWidget")
            combo.setProperty("canonical_symbol", field.canonical_symbol)
            combo.setProperty("field_type", field.field_type)
            combo.setProperty("widget_kind", field.widget_kind)
            combo.addItem(f"Choose {field.display_label}", None)
            for option in field.options:
                combo.addItem(option, option)
            combo.currentIndexChanged.connect(self._mark_fill_dirty)
            return combo

        if field.field_type == "number":
            spin = QDoubleSpinBox(self.fill_form_tab)
            spin.setObjectName("contractTemplateManualNumberWidget")
            spin.setProperty("canonical_symbol", field.canonical_symbol)
            spin.setProperty("field_type", field.field_type)
            spin.setProperty("widget_kind", field.widget_kind)
            spin.setProperty("has_user_value", False)
            spin.setRange(-999999999.0, 999999999.0)
            spin.setDecimals(6)

            def _handle_number_change(_value: float, *, widget=spin) -> None:
                widget.setProperty("has_user_value", True)
                self._mark_fill_dirty()

            spin.valueChanged.connect(_handle_number_change)
            return spin

        if field.field_type == "date":
            edit = QDateEdit(self.fill_form_tab)
            edit.setObjectName("contractTemplateManualDateWidget")
            edit.setProperty("canonical_symbol", field.canonical_symbol)
            edit.setProperty("field_type", field.field_type)
            edit.setProperty("widget_kind", field.widget_kind)
            edit.setProperty("has_user_value", False)
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setDate(QDate.currentDate())

            def _handle_date_change(_date: QDate, *, widget=edit) -> None:
                widget.setProperty("has_user_value", True)
                self._mark_fill_dirty()

            edit.dateChanged.connect(_handle_date_change)
            return edit

        line_edit = QLineEdit(self.fill_form_tab)
        line_edit.setObjectName("contractTemplateManualTextWidget")
        line_edit.setProperty("canonical_symbol", field.canonical_symbol)
        line_edit.setProperty("field_type", field.field_type)
        line_edit.setProperty("widget_kind", field.widget_kind)
        if field.field_type == "date":
            line_edit.setPlaceholderText("YYYY-MM-DD")
        elif field.field_type == "number":
            line_edit.setPlaceholderText("Enter a numeric value")
        else:
            line_edit.setPlaceholderText(f"Enter {field.display_label}")
        line_edit.textChanged.connect(self._mark_fill_dirty)
        return line_edit

    @staticmethod
    def _scope_label(entry: ContractTemplateCatalogEntry) -> str:
        mapping = {
            "track_context": "Track context",
            "owner_settings_context": "Current owner party",
            "release_selection_required": "Needs release selection",
            "work_selection_required": "Needs work selection",
            "contract_selection_required": "Needs contract selection",
            "party_selection_required": "Needs party selection",
            "right_selection_required": "Needs right selection",
            "asset_selection_required": "Needs asset selection",
            "manual_entry": "Manual entry",
        }
        return mapping.get(str(entry.scope_policy or ""), str(entry.scope_policy or "-"))

    def _copy_to_clipboard(self, text: str) -> None:
        app = QApplication.instance()
        if app is None:
            return
        clipboard = app.clipboard()
        if clipboard is None:
            return
        clipboard.setText(str(text or ""))

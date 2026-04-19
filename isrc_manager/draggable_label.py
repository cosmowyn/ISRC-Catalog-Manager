"""Draggable overlay label used by catalog sizing hints."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QLabel

from isrc_manager.paths import configure_qt_application_identity, settings_path


class DraggableLabel(QLabel):
    """Floating label that persists its position and records settings history."""

    def __init__(self, parent=None, settings_key="hint_pos"):
        super().__init__(parent)
        self.settings_key = settings_key
        self._drag_pos = None
        self._history_before_settings = None
        self._user_moved = False
        self.setWindowFlags(Qt.WindowType.SubWindow | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            app = self.window()
            if (
                hasattr(app, "history_manager")
                and getattr(app, "history_manager", None) is not None
            ):
                self._history_before_settings = app.history_manager.capture_setting_states(
                    [self.settings_key]
                )
            else:
                self._history_before_settings = None
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            self._user_moved = True
            app = self.window()
            settings = getattr(app, "settings", None)
            if settings is None:
                configure_qt_application_identity()
                settings = QSettings(str(settings_path()), QSettings.IniFormat)
                settings.setFallbacksEnabled(False)
            settings.setValue(self.settings_key, self.pos())
            settings.sync()
            if (
                self._history_before_settings is not None
                and hasattr(app, "_record_setting_bundle_from_entries")
                and getattr(app, "history_manager", None) is not None
            ):
                after_settings = app.history_manager.capture_setting_states([self.settings_key])
                label_name = (self.objectName() or self.settings_key).replace("_", " ").strip()
                app._record_setting_bundle_from_entries(
                    action_label=f"Move {label_name}",
                    before_entries=self._history_before_settings,
                    after_entries=after_settings,
                    entity_id=self.settings_key,
                )
            self._history_before_settings = None
            event.accept()

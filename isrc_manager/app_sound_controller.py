"""Application sound settings and playback orchestration."""

from __future__ import annotations

import logging
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from isrc_manager.app_sounds import (
    APP_SOUND_DEFAULTS,
    APP_SOUND_FILENAMES,
    APP_SOUND_IDS,
    APP_SOUND_NOTICE,
    APP_SOUND_SETTINGS_KEYS,
    APP_SOUND_STARTUP,
    APP_SOUND_WARNING,
    coerce_sound_bool,
)
from isrc_manager.paths import RES_DIR

_QT_MESSAGE_BOX_CLASS = QMessageBox


def _coerce_settings_bool(value, *, default: bool = False) -> bool:
    return coerce_sound_bool(value, default=default)


def _app_sound_enabled(app, sound_id: str) -> bool:
    clean_id = str(sound_id or "").strip().lower()
    if clean_id not in APP_SOUND_SETTINGS_KEYS:
        return False
    default = bool(APP_SOUND_DEFAULTS.get(clean_id, True))
    key = APP_SOUND_SETTINGS_KEYS[clean_id]
    try:
        return bool(
            app.settings.value(
                key,
                default,
                bool,
            )
        )
    except TypeError:
        return app._coerce_settings_bool(
            app.settings.value(key, default),
            default=default,
        )


def _startup_sound_enabled(app) -> bool:
    return app._app_sound_enabled(APP_SOUND_STARTUP)


def _current_app_sound_settings(app) -> dict[str, bool]:
    return {sound_id: app._app_sound_enabled(sound_id) for sound_id in APP_SOUND_IDS}


def _app_sound_path(app, sound_id: str) -> Path:
    return RES_DIR() / "sounds" / APP_SOUND_FILENAMES[str(sound_id)]


def _startup_sound_path(app) -> Path:
    return app._app_sound_path(APP_SOUND_STARTUP)


def _app_sound_effect(app, sound_id: str) -> QSoundEffect:
    clean_id = str(sound_id or "").strip().lower()
    effect = app._app_sound_effects.get(clean_id)
    if effect is None:
        effect = QSoundEffect(app)
        effect.setLoopCount(1)
        effect.setVolume(float(app.APP_SOUND_VOLUMES.get(clean_id, 0.4)))
        app._app_sound_effects[clean_id] = effect
        if clean_id == APP_SOUND_STARTUP:
            app._startup_sound_effect = effect
    return effect


def _play_app_sound(
    app,
    sound_id: str,
    *,
    throttle_key: str | None = None,
    throttle_ms: int = 0,
) -> None:
    clean_id = str(sound_id or "").strip().lower()
    if clean_id not in APP_SOUND_FILENAMES:
        return
    if not app._app_sound_enabled(clean_id):
        return
    effective_throttle_key = throttle_key or clean_id
    throttle_seconds = max(0.0, float(throttle_ms or 0) / 1000.0)
    if throttle_seconds:
        now = monotonic()
        last_played = float(app._app_sound_last_played.get(effective_throttle_key, 0.0))
        if now - last_played < throttle_seconds:
            return
        app._app_sound_last_played[effective_throttle_key] = now

    sound_path = app._app_sound_path(clean_id)
    if not sound_path.exists():
        if clean_id not in app._app_sound_missing_reported:
            app._app_sound_missing_reported.add(clean_id)
            app._log_event(
                "app_sound.missing",
                "Application sound file was not found",
                level=logging.DEBUG,
                sound=clean_id,
                path=str(sound_path),
            )
        return
    try:
        effect = app._app_sound_effect(clean_id)
        source = QUrl.fromLocalFile(str(sound_path))
        if effect.source() != source:
            effect.setSource(source)
        effect.play()
    except Exception as exc:
        app._log_event(
            "app_sound.failed",
            "Application sound could not be played",
            level=logging.WARNING,
            sound=clean_id,
            error=str(exc),
        )


def _schedule_startup_sound_after_startup(app) -> None:
    if getattr(app, "_startup_sound_played", False):
        return
    if not getattr(app, "_startup_sound_has_startup_feedback", False):
        return
    if not app._startup_sound_enabled():
        return
    app._startup_sound_played = True
    QTimer.singleShot(app.STARTUP_SOUND_DELAY_MS, app._play_startup_sound)


def _play_startup_sound(app) -> None:
    app._play_app_sound(APP_SOUND_STARTUP)


def _play_notice_sound(app) -> None:
    app._play_app_sound(
        APP_SOUND_NOTICE,
        throttle_ms=int(app.APP_SOUND_THROTTLE_MS[APP_SOUND_NOTICE]),
    )


def _play_warning_sound(app) -> None:
    app._play_app_sound(
        APP_SOUND_WARNING,
        throttle_ms=int(app.APP_SOUND_THROTTLE_MS[APP_SOUND_WARNING]),
    )


def _enable_app_interaction_sounds(app) -> None:
    app._app_sound_interactions_ready = True
    app._install_app_sound_widget_hooks()
    timer = getattr(app, "_app_sound_hook_timer", None)
    if timer is not None and not timer.isActive():
        timer.start()


def _install_app_sound_widget_hooks(app, root: QWidget | None = None) -> None:
    qt_app = QApplication.instance()
    if qt_app is None:
        return
    widgets: list[QWidget]
    if isinstance(root, QWidget):
        widgets = [root, *root.findChildren(QWidget)]
    else:
        widgets = [widget for widget in qt_app.allWidgets() if isinstance(widget, QWidget)]
    for widget in widgets:
        app._play_message_box_sound_once(widget)


def _message_box_notice_worthy(app, message_box: QMessageBox) -> bool:
    text = " ".join(
        str(part or "").casefold()
        for part in (
            message_box.windowTitle(),
            message_box.text(),
            message_box.informativeText(),
        )
    )
    return any(keyword in text for keyword in app.NOTICE_MESSAGE_KEYWORDS)


def _play_message_box_sound_once(app, widget: QWidget) -> None:
    if not isinstance(widget, _QT_MESSAGE_BOX_CLASS):
        return
    try:
        if bool(widget.property("_appSoundPlayed")):
            return
        widget.setProperty("_appSoundPlayed", True)
        icon = widget.icon()
    except Exception:
        return
    if icon in (_QT_MESSAGE_BOX_CLASS.Warning, _QT_MESSAGE_BOX_CLASS.Critical):
        app._play_warning_sound()
    elif icon == _QT_MESSAGE_BOX_CLASS.Information and app._message_box_notice_worthy(widget):
        app._play_notice_sound()

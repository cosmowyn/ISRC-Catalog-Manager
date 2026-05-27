from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from isrc_manager import app_sound_controller as sound
from isrc_manager.app_sounds import (
    APP_SOUND_NOTICE,
    APP_SOUND_SETTINGS_KEYS,
    APP_SOUND_STARTUP,
    APP_SOUND_WARNING,
)


def _qapp():
    return QApplication.instance() or QApplication([])


class _Settings:
    def __init__(self, values=None, *, reject_typed_bool: bool = False):
        self.values = dict(values or {})
        self.reject_typed_bool = reject_typed_bool

    def value(self, key, default=None, value_type=None):
        if value_type is bool and self.reject_typed_bool:
            raise TypeError("typed bool unsupported")
        return self.values.get(key, default)


class _FakeEffect:
    def __init__(self, _parent=None, *, fail_play: bool = False):
        self.loop_count = None
        self.volume = None
        self._source = QUrl()
        self.fail_play = fail_play
        self.play_count = 0
        self.sources = []

    def setLoopCount(self, loop_count):
        self.loop_count = loop_count

    def setVolume(self, volume):
        self.volume = volume

    def source(self):
        return self._source

    def setSource(self, source):
        self.sources.append(source)
        self._source = source

    def play(self):
        if self.fail_play:
            raise RuntimeError("audio device unavailable")
        self.play_count += 1


def test_sound_settings_use_unknown_default_and_qsettings_type_fallback():
    app = SimpleNamespace(
        settings=_Settings(
            {APP_SOUND_SETTINGS_KEYS[APP_SOUND_NOTICE]: "yes"},
            reject_typed_bool=True,
        ),
        _coerce_settings_bool=mock.Mock(return_value=True),
    )

    assert sound._app_sound_enabled(app, APP_SOUND_NOTICE) is True
    app._coerce_settings_bool.assert_called_once_with("yes", default=True)
    assert sound._app_sound_enabled(app, "not-a-sound") is False
    assert sound._coerce_settings_bool("no", default=True) is False


def test_sound_path_helpers_and_effect_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(sound, "RES_DIR", lambda: tmp_path)
    monkeypatch.setattr(sound, "QSoundEffect", _FakeEffect)
    app = SimpleNamespace(
        _app_sound_effects={},
        APP_SOUND_VOLUMES={APP_SOUND_STARTUP: 0.75},
        _app_sound_enabled=lambda sound_id: sound_id == APP_SOUND_NOTICE,
        _app_sound_path=lambda sound_id: sound._app_sound_path(app, sound_id),
    )

    assert sound._current_app_sound_settings(app)[APP_SOUND_NOTICE] is True
    assert sound._startup_sound_path(app) == tmp_path / "sounds" / "startup.wav"

    startup_effect = sound._app_sound_effect(app, APP_SOUND_STARTUP)
    assert startup_effect.loop_count == 1
    assert startup_effect.volume == 0.75
    assert app._startup_sound_effect is startup_effect
    assert sound._app_sound_effect(app, APP_SOUND_STARTUP) is startup_effect

    notice_effect = sound._app_sound_effect(app, APP_SOUND_NOTICE)
    assert notice_effect.volume == 0.4


def test_play_app_sound_handles_disabled_throttle_missing_success_and_failure(
    monkeypatch, tmp_path
):
    sound_file = tmp_path / "notice.wav"
    sound_file.write_bytes(b"RIFF")
    missing_file = tmp_path / "missing.wav"
    logs = []
    effect = _FakeEffect()
    app = SimpleNamespace(
        _app_sound_enabled=mock.Mock(return_value=True),
        _app_sound_path=mock.Mock(side_effect=lambda sound_id: sound_file),
        _app_sound_last_played={},
        _app_sound_missing_reported=set(),
        _app_sound_effect=mock.Mock(return_value=effect),
        _log_event=lambda *args, **kwargs: logs.append((args, kwargs)),
    )
    times = iter((10.0, 10.1, 10.7))
    monkeypatch.setattr(sound, "monotonic", lambda: next(times))

    sound._play_app_sound(app, "unknown")
    app._app_sound_effect.assert_not_called()

    app._app_sound_enabled.return_value = False
    sound._play_app_sound(app, APP_SOUND_NOTICE)
    app._app_sound_effect.assert_not_called()

    app._app_sound_enabled.return_value = True
    sound._play_app_sound(app, APP_SOUND_NOTICE, throttle_ms=500)
    sound._play_app_sound(app, APP_SOUND_NOTICE, throttle_ms=500)
    sound._play_app_sound(app, APP_SOUND_NOTICE, throttle_ms=500)
    assert effect.play_count == 2
    assert effect.sources[-1] == QUrl.fromLocalFile(str(sound_file))

    app._app_sound_path = mock.Mock(return_value=missing_file)
    sound._play_app_sound(app, APP_SOUND_WARNING)
    sound._play_app_sound(app, APP_SOUND_WARNING)
    assert APP_SOUND_WARNING in app._app_sound_missing_reported
    assert [entry[0][0] for entry in logs].count("app_sound.missing") == 1

    failing_effect = _FakeEffect(fail_play=True)
    app._app_sound_path = mock.Mock(return_value=sound_file)
    app._app_sound_effect = mock.Mock(return_value=failing_effect)
    sound._play_app_sound(app, APP_SOUND_WARNING)
    assert logs[-1][0][0] == "app_sound.failed"


def test_startup_notice_warning_and_interaction_scheduling(monkeypatch):
    single_shots = []
    monkeypatch.setattr(
        sound.QTimer,
        "singleShot",
        lambda delay, callback: single_shots.append((delay, callback)),
    )
    app = SimpleNamespace(
        STARTUP_SOUND_DELAY_MS=123,
        _startup_sound_played=False,
        _startup_sound_has_startup_feedback=True,
        _startup_sound_enabled=mock.Mock(return_value=True),
        _play_startup_sound=mock.Mock(),
        _play_app_sound=mock.Mock(),
        APP_SOUND_THROTTLE_MS={APP_SOUND_NOTICE: 250, APP_SOUND_WARNING: 500},
        _install_app_sound_widget_hooks=mock.Mock(),
        _app_sound_hook_timer=mock.Mock(isActive=mock.Mock(return_value=False), start=mock.Mock()),
    )

    sound._schedule_startup_sound_after_startup(app)
    assert app._startup_sound_played is True
    assert single_shots == [(123, app._play_startup_sound)]

    sound._play_startup_sound(app)
    sound._play_notice_sound(app)
    sound._play_warning_sound(app)
    assert app._play_app_sound.call_args_list == [
        mock.call(APP_SOUND_STARTUP),
        mock.call(APP_SOUND_NOTICE, throttle_ms=250),
        mock.call(APP_SOUND_WARNING, throttle_ms=500),
    ]

    sound._enable_app_interaction_sounds(app)
    assert app._app_sound_interactions_ready is True
    app._app_sound_hook_timer.start.assert_called_once()

    app._app_sound_hook_timer.isActive.return_value = True
    sound._enable_app_interaction_sounds(app)
    app._app_sound_hook_timer.start.assert_called_once()

    app._startup_sound_played = True
    single_shots.clear()
    sound._schedule_startup_sound_after_startup(app)
    assert single_shots == []


def test_widget_hooking_and_message_box_classification(monkeypatch):
    _qapp()
    root = QWidget()
    child = QWidget(root)
    app = SimpleNamespace(
        _play_message_box_sound_once=mock.Mock(),
        NOTICE_MESSAGE_KEYWORDS=("saved", "complete"),
        _play_warning_sound=mock.Mock(),
        _play_notice_sound=mock.Mock(),
    )
    app._message_box_notice_worthy = lambda widget: sound._message_box_notice_worthy(app, widget)

    sound._install_app_sound_widget_hooks(app, root)
    app._play_message_box_sound_once.assert_has_calls([mock.call(root), mock.call(child)])

    info_box = QMessageBox()
    info_box.setWindowTitle("Export Complete")
    info_box.setText("Saved successfully")
    assert sound._message_box_notice_worthy(app, info_box) is True

    sound._play_message_box_sound_once(app, "not-a-widget")
    warning_box = QMessageBox()
    warning_box.setIcon(QMessageBox.Warning)
    sound._play_message_box_sound_once(app, warning_box)
    sound._play_message_box_sound_once(app, warning_box)
    app._play_warning_sound.assert_called_once()

    notice_box = QMessageBox()
    notice_box.setIcon(QMessageBox.Information)
    notice_box.setText("Saved")
    sound._play_message_box_sound_once(app, notice_box)
    app._play_notice_sound.assert_called_once()

"""Application-wide sound effect settings and descriptors."""

from __future__ import annotations

from collections.abc import Mapping

APP_SOUND_STARTUP = "startup"
APP_SOUND_CLICK = "click"
APP_SOUND_NOTICE = "notice"
APP_SOUND_WARNING = "warning"

APP_SOUND_IDS = (
    APP_SOUND_STARTUP,
    APP_SOUND_CLICK,
    APP_SOUND_NOTICE,
    APP_SOUND_WARNING,
)

APP_SOUND_FILENAMES = {
    APP_SOUND_STARTUP: "startup.wav",
    APP_SOUND_CLICK: "click.wav",
    APP_SOUND_NOTICE: "notice.wav",
    APP_SOUND_WARNING: "warning.wav",
}

APP_SOUND_SETTINGS_KEYS = {
    APP_SOUND_STARTUP: "startup/play_startup_sound",
    APP_SOUND_CLICK: "sounds/click_enabled",
    APP_SOUND_NOTICE: "sounds/notice_enabled",
    APP_SOUND_WARNING: "sounds/warning_enabled",
}

APP_SOUND_DEFAULTS = {
    APP_SOUND_STARTUP: True,
    APP_SOUND_CLICK: True,
    APP_SOUND_NOTICE: True,
    APP_SOUND_WARNING: True,
}

APP_SOUND_SPECS = (
    (
        APP_SOUND_STARTUP,
        "Startup",
        "Play startup sound after loading",
        "Play the bundled startup sound once after loading finishes.",
    ),
    (
        APP_SOUND_CLICK,
        "Click",
        "Play click sounds while scrolling or sliding",
        "Play a subtle click when scrollbars or sliders move.",
    ),
    (
        APP_SOUND_NOTICE,
        "Notice",
        "Play notice sound for completed actions",
        "Play when an operation completes, such as saving settings or finishing an export.",
    ),
    (
        APP_SOUND_WARNING,
        "Warning",
        "Play warning sound for errors",
        "Play when the app reports that something went wrong.",
    ),
)


def coerce_sound_bool(value, *, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in {"", "0", "false", "no", "off"}


def normalize_app_sound_settings(
    values: Mapping[str, object] | None = None,
    *,
    startup_sound_enabled: object | None = None,
) -> dict[str, bool]:
    normalized = dict(APP_SOUND_DEFAULTS)
    raw_values = dict(values or {})

    if startup_sound_enabled is not None:
        raw_values.setdefault(APP_SOUND_STARTUP, startup_sound_enabled)

    legacy_aliases = {
        "startup_sound_enabled": APP_SOUND_STARTUP,
        "click_sound_enabled": APP_SOUND_CLICK,
        "notice_sound_enabled": APP_SOUND_NOTICE,
        "warning_sound_enabled": APP_SOUND_WARNING,
    }
    for alias, sound_id in legacy_aliases.items():
        if alias in raw_values and sound_id not in raw_values:
            raw_values[sound_id] = raw_values[alias]

    for sound_id in APP_SOUND_IDS:
        if sound_id in raw_values:
            normalized[sound_id] = coerce_sound_bool(
                raw_values.get(sound_id),
                default=APP_SOUND_DEFAULTS[sound_id],
            )
    return normalized

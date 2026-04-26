"""App-wide update notification preferences."""

from __future__ import annotations

from PySide6.QtCore import QSettings

from isrc_manager.versioning import SemVerError, parse_semver

IGNORED_UPDATE_VERSION_KEY = "updates/ignored_version"


class UpdatePreferenceService:
    """Persist update notification choices in app-wide QSettings."""

    def __init__(self, settings: QSettings):
        self.settings = settings

    def ignored_version(self) -> str:
        value = str(self.settings.value(IGNORED_UPDATE_VERSION_KEY, "", str) or "").strip()
        if not value:
            return ""
        try:
            return str(parse_semver(value))
        except SemVerError:
            return ""

    def set_ignored_version(self, version: object) -> str:
        clean_version = str(parse_semver(version))
        self.settings.setValue(IGNORED_UPDATE_VERSION_KEY, clean_version)
        self.settings.sync()
        return clean_version

    def clear_ignored_version(self) -> None:
        self.settings.remove(IGNORED_UPDATE_VERSION_KEY)
        self.settings.sync()

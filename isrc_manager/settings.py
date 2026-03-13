"""Application settings and single-instance helpers."""

import uuid
from pathlib import Path

from PySide6.QtCore import QLockFile, QSettings, QStandardPaths

from .constants import APP_NAME, SETTINGS_BASENAME


def init_settings() -> QSettings:
    """
    Use the OS-recommended app data dir (per-user, writable)
      - Windows: C:/Users/<you>/AppData/Roaming/GenericVendor/ISRCManager/
      - macOS:   ~/Library/Application Support/GenericVendor/ISRCManager/
      - Linux:   ~/.local/share/GenericVendor/ISRCManager/
    """
    base_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    base_dir.mkdir(parents=True, exist_ok=True)

    ini_path = base_dir / SETTINGS_BASENAME
    settings = QSettings(str(ini_path), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)

    first_run = settings.value("app/initialized", False, type=bool) is False
    if first_run:
        settings.setValue("app/initialized", True)
        settings.setValue("app/schema_version", 1)
        settings.setValue("ui/theme", "system")
        settings.setValue("paths/database_dir", str((base_dir.parent / "Database").resolve()))
        settings.setValue("app/uid", str(uuid.uuid4()))
        settings.sync()

    return settings


def enforce_single_instance(timeout_ms: int = 60000):
    """Return a QLockFile if we obtained the lock; otherwise None."""
    lock_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(lock_dir / f"{APP_NAME}.lock"))
    lock.setStaleLockTime(timeout_ms)
    if not lock.tryLock(0):
        return None
    return lock


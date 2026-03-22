"""Application settings and single-instance helpers."""

import uuid

from PySide6.QtCore import QLockFile, QSettings

from .paths import (
    STORAGE_ACTIVE_DATA_ROOT_KEY,
    configure_qt_application_identity,
    lock_path,
    preferred_data_root,
    settings_path,
)


def init_settings() -> QSettings:
    """
    Use the OS-recommended app data dir (per-user, writable)
      - Windows: C:/Users/<you>/AppData/Roaming/GenericVendor/ISRCManager/
      - macOS:   ~/Library/Application Support/GenericVendor/ISRCManager/
      - Linux:   ~/.local/share/GenericVendor/ISRCManager/
    """
    configure_qt_application_identity()
    ini_path = settings_path()
    base_dir = ini_path.parent
    base_dir.mkdir(parents=True, exist_ok=True)
    settings = QSettings(str(ini_path), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)

    first_run = settings.value("app/initialized", False, type=bool) is False
    if first_run:
        preferred_root = preferred_data_root()
        settings.setValue("app/initialized", True)
        settings.setValue("app/schema_version", 1)
        settings.setValue("ui/theme", "system")
        if not settings.contains("startup/offer_open_settings_on_first_launch_pending"):
            settings.setValue("startup/offer_open_settings_on_first_launch_pending", True)
        settings.setValue("paths/database_dir", str((preferred_root / "Database").resolve()))
        settings.setValue(STORAGE_ACTIVE_DATA_ROOT_KEY, str(preferred_root))
        settings.setValue("app/uid", str(uuid.uuid4()))
        settings.sync()

    return settings


def enforce_single_instance(timeout_ms: int = 60000):
    """Return a QLockFile if we obtained the lock; otherwise None."""
    configure_qt_application_identity()
    current_lock_path = lock_path()
    current_lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(current_lock_path))
    lock.setStaleLockTime(timeout_ms)
    if not lock.tryLock(0):
        return None
    return lock

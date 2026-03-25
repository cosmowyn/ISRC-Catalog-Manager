"""Filesystem path helpers."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths
except Exception:  # pragma: no cover - optional Qt fallback for helper imports
    QCoreApplication = None
    QSettings = None
    QStandardPaths = None

from .constants import APP_NAME, APP_ORG, SETTINGS_BASENAME

STORAGE_ACTIVE_DATA_ROOT_KEY = "storage/active_data_root"
STORAGE_LEGACY_DATA_ROOT_KEY = "storage/legacy_data_root"
STORAGE_MIGRATION_STATE_KEY = "storage/migration_state"
STORAGE_MIGRATION_JOURNAL_BASENAME = "storage_migration.json"
STORAGE_STATE_DEFERRED = "deferred"
STORAGE_STATE_COMPLETE = "complete"
STORAGE_STATE_FAILED = "failed"

DATABASE_SUBDIR = "Database"
EXPORTS_SUBDIR = "exports"
LOGS_SUBDIR = "logs"
BACKUPS_SUBDIR = "backups"
HISTORY_SUBDIR = "history"
HELP_SUBDIR = "help"

MANAGED_STORAGE_SUBDIRS = (
    "track_media",
    "release_media",
    "licenses",
    "contract_documents",
    "asset_registry",
    "custom_field_media",
    "gs1_templates",
    "contract_template_sources",
    "contract_template_drafts",
)


@dataclass(slots=True)
class AppStorageLayout:
    app_name: str
    portable: bool
    settings_root: Path
    settings_path: Path
    lock_path: Path
    preferred_data_root: Path
    active_data_root: Path
    legacy_data_roots: tuple[Path, ...]
    database_dir: Path
    exports_dir: Path
    logs_dir: Path
    backups_dir: Path
    history_dir: Path
    help_dir: Path

    @property
    def data_root(self) -> Path:
        return self.active_data_root

    @property
    def migration_journal_path(self) -> Path:
        return self.active_data_root / STORAGE_MIGRATION_JOURNAL_BASENAME

    def managed_storage_dir(self, name: str) -> Path:
        return self.active_data_root / str(name)

    def iter_standard_dirs(self) -> tuple[Path, ...]:
        return (
            self.active_data_root,
            self.database_dir,
            self.exports_dir,
            self.logs_dir,
            self.backups_dir,
            self.history_dir,
            self.help_dir,
            *tuple(self.managed_storage_dir(name) for name in MANAGED_STORAGE_SUBDIRS),
        )


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _portable_mode_requested(portable: bool | None = None) -> bool:
    return portable is True or (BIN_DIR() / ".portable").exists()


def _unique_paths(paths: list[Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        normalized = str(path.resolve())
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(path.resolve())
    return tuple(unique)


def _fallback_qt_root(*, local: bool, app_name: str = APP_NAME) -> Path:
    if sys.platform.startswith("win"):
        if local:
            base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        else:
            base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        return (base / APP_ORG / app_name).resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / APP_ORG / app_name).resolve()
    if local:
        return (Path.home() / ".local" / "share" / APP_ORG / app_name).resolve()
    return (Path.home() / ".config" / APP_ORG / app_name).resolve()


def _qt_path(location, *, local_fallback: bool, app_name: str = APP_NAME) -> Path:
    if QStandardPaths is not None:
        try:
            raw = str(QStandardPaths.writableLocation(location) or "").strip()
        except Exception:
            raw = ""
        if raw:
            base = Path(raw).resolve()
            if app_name != APP_NAME:
                return (base.parent / app_name).resolve()
            return base
    return _fallback_qt_root(local=local_fallback, app_name=app_name)


def configure_qt_application_identity(app=None) -> None:
    """Apply the repo-defined Qt organization/app metadata before path lookups."""
    if app is not None:
        try:
            app.setOrganizationName(APP_ORG)
            app.setApplicationName(APP_NAME)
            return
        except Exception:
            pass
    if QCoreApplication is not None:
        try:
            QCoreApplication.setOrganizationName(APP_ORG)
            QCoreApplication.setApplicationName(APP_NAME)
        except Exception:
            pass


def BIN_DIR() -> Path:
    """Folder of the actual .exe (PyInstaller) or script dir in dev."""
    return (
        Path(sys.executable).resolve().parent
        if _is_frozen()
        else Path(__file__).resolve().parent.parent
    )


def RES_DIR() -> Path:
    """Read-only bundled resources at runtime; equals src dir in dev."""
    return Path(getattr(sys, "_MEIPASS", BIN_DIR())) if _is_frozen() else BIN_DIR()


def settings_root(app_name: str = APP_NAME) -> Path:
    configure_qt_application_identity()
    location = QStandardPaths.AppDataLocation if QStandardPaths is not None else None
    return _qt_path(location, local_fallback=False, app_name=app_name)


def settings_path(app_name: str = APP_NAME) -> Path:
    return settings_root(app_name=app_name) / SETTINGS_BASENAME


def lock_path(app_name: str = APP_NAME) -> Path:
    return settings_root(app_name=app_name) / f"{app_name}.lock"


def preferred_data_root(app_name: str = APP_NAME) -> Path:
    configure_qt_application_identity()
    location = QStandardPaths.AppLocalDataLocation if QStandardPaths is not None else None
    return _qt_path(location, local_fallback=True, app_name=app_name)


def legacy_data_root(app_name: str = APP_NAME, portable: bool | None = None) -> Path:
    if _portable_mode_requested(portable):
        return BIN_DIR()
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return (base / app_name).resolve()


def resolve_app_storage_layout(
    *,
    settings: QSettings | None = None,
    app_name: str = APP_NAME,
    portable: bool | None = None,
    active_data_root: str | Path | None = None,
) -> AppStorageLayout:
    portable_mode = _portable_mode_requested(portable)
    settings_dir = BIN_DIR() if portable_mode else settings_root(app_name=app_name)
    settings_file = settings_dir / SETTINGS_BASENAME
    lock_file = settings_dir / f"{app_name}.lock"
    preferred_root = BIN_DIR() if portable_mode else preferred_data_root(app_name=app_name)
    legacy_roots = ()
    if portable_mode:
        chosen_root = BIN_DIR()
    else:
        legacy_candidates = [legacy_data_root(app_name=app_name)]
        legacy_roots = tuple(
            path for path in _unique_paths(legacy_candidates) if path != preferred_root
        )
        chosen_root = preferred_root
        if active_data_root is not None:
            chosen_root = Path(active_data_root).resolve()
        elif settings is not None:
            stored_active = str(settings.value(STORAGE_ACTIVE_DATA_ROOT_KEY, "", str) or "").strip()
            if stored_active:
                chosen_root = Path(stored_active).resolve()
            else:
                stored_state = str(
                    settings.value(STORAGE_MIGRATION_STATE_KEY, "", str) or ""
                ).strip()
                stored_legacy = str(
                    settings.value(STORAGE_LEGACY_DATA_ROOT_KEY, "", str) or ""
                ).strip()
                if stored_state == STORAGE_STATE_DEFERRED and stored_legacy:
                    chosen_root = Path(stored_legacy).resolve()
    chosen_root = chosen_root.resolve()
    return AppStorageLayout(
        app_name=app_name,
        portable=portable_mode,
        settings_root=settings_dir,
        settings_path=settings_file,
        lock_path=lock_file,
        preferred_data_root=preferred_root.resolve(),
        active_data_root=chosen_root,
        legacy_data_roots=legacy_roots,
        database_dir=chosen_root / DATABASE_SUBDIR,
        exports_dir=chosen_root / EXPORTS_SUBDIR,
        logs_dir=chosen_root / LOGS_SUBDIR,
        backups_dir=chosen_root / BACKUPS_SUBDIR,
        history_dir=chosen_root / HISTORY_SUBDIR,
        help_dir=chosen_root / HELP_SUBDIR,
    )


def DATA_DIR(
    app_name: str = APP_NAME,
    portable: bool | None = None,
    *,
    settings: QSettings | None = None,
) -> Path:
    """
    Return the active app-owned data root.

    Portable mode still resolves to the binary directory. Non-portable mode prefers
    the native Qt local app-data location but can honor a stored active root when
    migration has been deferred or completed.
    """
    return resolve_app_storage_layout(
        settings=settings, app_name=app_name, portable=portable
    ).data_root

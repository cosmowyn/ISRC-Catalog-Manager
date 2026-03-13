"""Filesystem path helpers."""

import os
import sys
from pathlib import Path

from .constants import APP_NAME


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def BIN_DIR() -> Path:
    """Folder of the actual .exe (PyInstaller) or script dir in dev."""
    return Path(sys.executable).resolve().parent if _is_frozen() else Path(__file__).resolve().parent.parent


def RES_DIR() -> Path:
    """Read-only bundled resources at runtime; equals src dir in dev."""
    return Path(getattr(sys, "_MEIPASS", BIN_DIR())) if _is_frozen() else BIN_DIR()


def DATA_DIR(app_name: str = APP_NAME, portable: bool | None = None) -> Path:
    """
    Writes go here (DB, logs, exports).
    - Portable mode if a '.portable' file exists next to the exe, or portable=True is passed.
    - Otherwise %LOCALAPPDATA%\\ISRCManager on Windows.
    """
    if portable is True or (BIN_DIR() / ".portable").exists():
        return BIN_DIR()
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return (base / app_name).resolve()


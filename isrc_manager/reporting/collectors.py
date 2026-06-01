"""Diagnostic collectors for privacy-safe reports."""

from __future__ import annotations

import os
import platform
from pathlib import Path

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import qVersion

from .sanitizer import ReportSanitizer

MAX_LOG_BYTES = 96_000
MAX_TRACEBACK_BYTES = 48_000


def collect_system_context(*, app_version: str, sanitizer: ReportSanitizer) -> dict[str, str]:
    raw = {
        "application_version": app_version,
        "build_commit": _env_value("ISRC_BUILD_COMMIT", "GIT_COMMIT", "BUILD_COMMIT"),
        "build_id": _env_value("ISRC_BUILD_ID", "BUILD_ID"),
        "operating_system": platform.platform(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "qt_version": qVersion(),
        "pyside_version": pyside_version,
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": str(os.cpu_count() or ""),
    }
    return sanitizer.sanitize_mapping({key: value for key, value in raw.items() if value})


def collect_recent_logs(
    logs_dir: Path,
    *,
    sanitizer: ReportSanitizer,
    max_files: int = 4,
    max_bytes_per_file: int = MAX_LOG_BYTES,
) -> list[tuple[str, str]]:
    logs_dir = Path(logs_dir)
    if not logs_dir.exists():
        return []

    try:
        children = list(logs_dir.iterdir())
    except Exception:
        return []
    candidates = [
        path
        for path in children
        if _safe_is_file(path) and path.suffix.lower() in {".log", ".jsonl", ".txt"}
    ]
    candidates.sort(key=_safe_mtime, reverse=True)
    return [
        (path.name, _read_tail(path, max_bytes=max_bytes_per_file, sanitizer=sanitizer))
        for path in candidates[:max_files]
    ]


def collect_traceback_files(
    search_dirs: list[Path],
    *,
    sanitizer: ReportSanitizer,
    max_files: int = 3,
) -> list[tuple[str, str]]:
    candidates: list[Path] = []
    for search_dir in search_dirs:
        path = Path(search_dir)
        if not path.exists():
            continue
        try:
            children = list(path.iterdir())
        except Exception:
            continue
        for child in children:
            if not _safe_is_file(child):
                continue
            name = child.name.lower()
            if "traceback" in name or "exception" in name or "faulthandler" in name:
                candidates.append(child)
    candidates.sort(key=_safe_mtime, reverse=True)
    return [
        (path.name, _read_tail(path, max_bytes=MAX_TRACEBACK_BYTES, sanitizer=sanitizer))
        for path in candidates[:max_files]
    ]


def _read_tail(path: Path, *, max_bytes: int, sanitizer: ReportSanitizer) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes), os.SEEK_SET)
            data = handle.read(max_bytes)
    except Exception as exc:
        return sanitizer.sanitize_text(f"Unable to read diagnostic file: {exc}")
    text = data.decode("utf-8", errors="replace")
    if len(data) >= max_bytes:
        text = "[tail of diagnostic file]\n" + text
    return sanitizer.sanitize_text(text)


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except Exception:
        return 0.0


def _safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except Exception:
        return False


def _env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""

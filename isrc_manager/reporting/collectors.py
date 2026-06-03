"""Diagnostic collectors for privacy-safe reports."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import qVersion

from .sanitizer import ReportSanitizer

MAX_LOG_BYTES = 96_000
MAX_TRACEBACK_BYTES = 48_000
MAX_OS_CONTEXT_BYTES = 64_000
OS_CONTEXT_TIMEOUT_SECONDS = 3.0
OS_CONTEXT_MAX_LINES = 80
OS_CONTEXT_WINDOW_BEFORE_SECONDS = 300
OS_CONTEXT_WINDOW_AFTER_SECONDS = 180
DEFAULT_CRASH_PROCESS_NAMES = (
    "Music Catalog Manager",
    "Music Catalog Manager.exe",
    "ISRCManager",
    "ISRCManager.exe",
    "ISRC Manager",
    "ISRC_manager",
)


@dataclass(frozen=True)
class _CrashLogWindow:
    start_utc: datetime
    end_utc: datetime

    @property
    def label(self) -> str:
        return f"{_iso_utc(self.start_utc)} to {_iso_utc(self.end_utc)}"


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


def collect_os_crash_context(
    *,
    pid: int,
    started_at: str = "",
    last_seen_at: str = "",
    sanitizer: ReportSanitizer,
    process_names: Sequence[str] = DEFAULT_CRASH_PROCESS_NAMES,
    timeout_seconds: float = OS_CONTEXT_TIMEOUT_SECONDS,
    max_bytes: int = MAX_OS_CONTEXT_BYTES,
) -> list[tuple[str, str]]:
    """Collect bounded read-only OS crash context for the previous app process.

    The collector intentionally executes only platform-native read-only log queries,
    never uses a shell, never requests elevation, and sanitises every returned byte
    before it enters the report preview or submission payload.
    """

    previous_pid = _coerce_pid(pid)
    if previous_pid <= 0:
        return [
            (
                "Sanitised OS Crash Context",
                "OS crash context was not collected because the previous session PID was invalid.",
            )
        ]

    window = _crash_log_window(started_at=started_at, last_seen_at=last_seen_at)
    system = platform.system().lower()
    names = tuple(_normalise_process_names(process_names))
    if system == "darwin":
        return _collect_macos_crash_context(
            pid=previous_pid,
            window=window,
            process_names=names,
            sanitizer=sanitizer,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
    if system == "windows":
        return _collect_windows_crash_context(
            pid=previous_pid,
            window=window,
            process_names=names,
            sanitizer=sanitizer,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
    if system == "linux":
        return _collect_linux_crash_context(
            pid=previous_pid,
            window=window,
            sanitizer=sanitizer,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
    return [
        (
            "Sanitised OS Crash Context",
            sanitizer.sanitize_text(
                "OS crash context collection is not supported on this operating system."
            ),
        )
    ]


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


def _collect_macos_crash_context(
    *,
    pid: int,
    window: _CrashLogWindow,
    process_names: Sequence[str],
    sanitizer: ReportSanitizer,
    timeout_seconds: float,
    max_bytes: int,
) -> list[tuple[str, str]]:
    if shutil.which("log") is None:
        return [
            (
                "Sanitised OS Crash Context (macOS)",
                "macOS unified log collection was unavailable because the log tool was not found.",
            )
        ]
    predicate_parts = [f"processIdentifier == {pid}"]
    predicate_parts.extend(
        f'process == "{_macos_predicate_string(name)}"' for name in process_names
    )
    command = [
        "log",
        "show",
        "--style",
        "compact",
        "--predicate",
        " || ".join(predicate_parts),
        "--start",
        _macos_log_time(window.start_utc),
        "--end",
        _macos_log_time(window.end_utc),
    ]
    output = _run_read_only_log_query(
        command,
        sanitizer=sanitizer,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
    )
    return [
        (
            "Sanitised OS Crash Context (macOS)",
            _format_os_context_body(
                source="macOS unified log",
                pid=pid,
                window=window,
                output=output,
                sanitizer=sanitizer,
            ),
        )
    ]


def _collect_windows_crash_context(
    *,
    pid: int,
    window: _CrashLogWindow,
    process_names: Sequence[str],
    sanitizer: ReportSanitizer,
    timeout_seconds: float,
    max_bytes: int,
) -> list[tuple[str, str]]:
    if shutil.which("wevtutil") is None:
        return [
            (
                "Sanitised OS Crash Context (Windows)",
                "Windows Event Log collection was unavailable because wevtutil was not found.",
            )
        ]
    providers = (
        "Application Error",
        "Application Hang",
        "Windows Error Reporting",
        ".NET Runtime",
        "SideBySide",
    )
    provider_filter = " or ".join(f"Provider[@Name='{provider}']" for provider in providers)
    time_filter = (
        f"TimeCreated[@SystemTime>='{_windows_event_time(window.start_utc)}' "
        f"and @SystemTime<='{_windows_event_time(window.end_utc)}']"
    )
    query = f"*[System[({provider_filter}) and {time_filter}]]"
    command = [
        "wevtutil",
        "qe",
        "Application",
        f"/q:{query}",
        "/f:text",
        f"/c:{OS_CONTEXT_MAX_LINES}",
        "/rd:true",
    ]
    raw_output = _run_read_only_log_query(
        command,
        sanitizer=sanitizer,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        sanitize=False,
    )
    if _is_log_query_diagnostic_message(raw_output):
        filtered = raw_output
    else:
        filtered = _filter_windows_event_blocks(
            raw_output,
            pid=pid,
            process_names=process_names,
            max_blocks=16,
        )
    output = sanitizer.sanitize_text(filtered, max_chars=max_bytes)
    return [
        (
            "Sanitised OS Crash Context (Windows)",
            _format_os_context_body(
                source="Windows Application event log",
                pid=pid,
                window=window,
                output=output,
                sanitizer=sanitizer,
            ),
        )
    ]


def _collect_linux_crash_context(
    *,
    pid: int,
    window: _CrashLogWindow,
    sanitizer: ReportSanitizer,
    timeout_seconds: float,
    max_bytes: int,
) -> list[tuple[str, str]]:
    if shutil.which("journalctl") is None:
        return [
            (
                "Sanitised OS Crash Context (Linux)",
                "Linux journal collection was unavailable because journalctl was not found.",
            )
        ]
    command = [
        "journalctl",
        "--no-pager",
        "--output=short-iso",
        f"--since=@{int(window.start_utc.timestamp())}",
        f"--until=@{int(window.end_utc.timestamp())}",
        f"_PID={pid}",
        "-n",
        str(OS_CONTEXT_MAX_LINES),
    ]
    output = _run_read_only_log_query(
        command,
        sanitizer=sanitizer,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
    )
    if not output.strip():
        user_command = command[:1] + ["--user"] + command[1:]
        output = _run_read_only_log_query(
            user_command,
            sanitizer=sanitizer,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
    return [
        (
            "Sanitised OS Crash Context (Linux)",
            _format_os_context_body(
                source="systemd journal",
                pid=pid,
                window=window,
                output=output,
                sanitizer=sanitizer,
            ),
        )
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


def _run_read_only_log_query(
    command: Sequence[str],
    *,
    sanitizer: ReportSanitizer,
    timeout_seconds: float,
    max_bytes: int,
    sanitize: bool = True,
) -> str:
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(0.5, float(timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return sanitizer.sanitize_text(
            "OS log query timed out before returning bounded crash context."
        )
    except Exception as exc:
        return sanitizer.sanitize_text(f"OS log query was unavailable: {exc}")

    output_parts = []
    stdout = _limit_text_bytes(completed.stdout or "", max_bytes=max_bytes)
    stderr = _limit_text_bytes(completed.stderr or "", max_bytes=max(4_000, max_bytes // 8))
    if stdout:
        output_parts.append(stdout)
    if completed.returncode != 0 and stderr:
        output_parts.append(f"[diagnostic command stderr]\n{stderr}")
    output = "\n".join(output_parts).strip()
    if not output and completed.returncode != 0:
        output = f"OS log query exited with status {completed.returncode} and no output."
    return sanitizer.sanitize_text(output, max_chars=max_bytes) if sanitize else output


def _format_os_context_body(
    *,
    source: str,
    pid: int,
    window: _CrashLogWindow,
    output: str,
    sanitizer: ReportSanitizer,
) -> str:
    policy = (
        "Collection policy: read-only native OS log query; no shell execution; "
        "no privilege elevation; bounded timeout; bounded output; local sanitisation "
        "before preview or submission."
    )
    details = "\n".join(
        (
            policy,
            f"Source: {source}",
            f"Previous session PID: {pid}",
            f"UTC query window: {window.label}",
            "",
            output.strip() or "No matching OS log entries were returned for the crash window.",
        )
    )
    return sanitizer.sanitize_text(details)


def _filter_windows_event_blocks(
    raw_output: str,
    *,
    pid: int,
    process_names: Sequence[str],
    max_blocks: int,
) -> str:
    raw_output = str(raw_output or "")
    if not raw_output.strip():
        return ""
    blocks = _split_windows_event_blocks(raw_output)
    terms = {str(pid).lower()}
    terms.update(name.lower() for name in process_names if name)
    selected = [block for block in blocks if any(term and term in block.lower() for term in terms)]
    return "\n\n".join(selected[:max_blocks])


def _split_windows_event_blocks(raw_output: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in raw_output.splitlines():
        if line.startswith("Event[") and current:
            blocks.append("\n".join(current).strip())
            current = [line]
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def _is_log_query_diagnostic_message(raw_output: str) -> bool:
    text = str(raw_output or "").lstrip()
    return text.startswith("OS log query") or text.startswith("[diagnostic command stderr]")


def _crash_log_window(*, started_at: str, last_seen_at: str) -> _CrashLogWindow:
    anchor = _parse_utc_timestamp(last_seen_at) or _parse_utc_timestamp(started_at)
    if anchor is None:
        anchor = datetime.now(UTC)
    start_utc = anchor - timedelta(seconds=OS_CONTEXT_WINDOW_BEFORE_SECONDS)
    end_utc = anchor + timedelta(seconds=OS_CONTEXT_WINDOW_AFTER_SECONDS)
    now = datetime.now(UTC) + timedelta(seconds=30)
    if end_utc > now:
        end_utc = now
    if end_utc <= start_utc:
        end_utc = start_utc + timedelta(seconds=60)
    return _CrashLogWindow(start_utc=start_utc, end_utc=end_utc)


def _parse_utc_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalise_process_names(process_names: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for name in process_names:
        clean = str(name or "").strip()
        if not clean or clean.lower() in seen:
            continue
        seen.add(clean.lower())
        result.append(clean[:80])
    return result


def _coerce_pid(value: int) -> int:
    try:
        return int(value)
    except TypeError, ValueError:
        return 0


def _macos_predicate_string(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _macos_log_time(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _windows_event_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _limit_text_bytes(value: str, *, max_bytes: int) -> str:
    max_bytes = max(1, int(max_bytes))
    encoded = str(value or "").encode("utf-8")
    if len(encoded) <= max_bytes:
        return str(value or "")
    omitted = len(encoded) - max_bytes
    tail = encoded[-max_bytes:].decode("utf-8", errors="replace")
    return f"[tail of OS diagnostic output; omitted {omitted} bytes]\n{tail}"


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

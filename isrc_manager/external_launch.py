"""Centralized external URL/path launch policy with test-safe blocking hooks."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

try:
    from PySide6.QtCore import QCoreApplication, Qt, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QFileDialog
except ImportError:  # pragma: no cover - environment-specific fallback
    QCoreApplication = None
    Qt = None
    QUrl = None
    QDesktopServices = None
    QFileDialog = None


TEST_BLOCK_ENV_VAR = "ISRC_MANAGER_BLOCK_EXTERNAL_LAUNCHES"


@dataclass(frozen=True)
class ExternalLaunchRequest:
    via: str
    target: str
    blocked: bool
    source: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class _BlockedPopen:
    """Minimal successful Popen-like object for blocked launcher commands in tests."""

    def __init__(self, args, *, text_mode: bool):
        self.args = args
        self.returncode = 0
        self._stdout = "" if text_mode else b""
        self._stderr = "" if text_mode else b""
        self.stdout = None
        self.stderr = None

    def communicate(self, input=None, timeout=None):  # pragma: no cover - simple shim
        del input, timeout
        return self._stdout, self._stderr

    def wait(self, timeout=None):  # pragma: no cover - simple shim
        del timeout
        return self.returncode

    def poll(self):  # pragma: no cover - simple shim
        return self.returncode

    def kill(self):  # pragma: no cover - simple shim
        self.returncode = -9

    def terminate(self):  # pragma: no cover - simple shim
        self.returncode = -15

    def __enter__(self):  # pragma: no cover - simple shim
        return self

    def __exit__(self, exc_type, exc, tb):  # pragma: no cover - simple shim
        del exc_type, exc, tb
        return False


class _ExternalLaunchState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.block_external_launches = False
        self.blocked_return_value = True
        self.installed = False
        self.history: list[ExternalLaunchRequest] = []


_STATE = _ExternalLaunchState()

_ORIGINAL_QDESKTOPSERVICES_OPENURL = (
    QDesktopServices.openUrl if QDesktopServices is not None else None
)
_ORIGINAL_WEBBROWSER_OPEN = webbrowser.open
_ORIGINAL_WEBBROWSER_OPEN_NEW = webbrowser.open_new
_ORIGINAL_WEBBROWSER_OPEN_NEW_TAB = webbrowser.open_new_tab
_ORIGINAL_SUBPROCESS_RUN = subprocess.run
_ORIGINAL_SUBPROCESS_POPEN = subprocess.Popen
_ORIGINAL_SUBPROCESS_CALL = subprocess.call
_ORIGINAL_SUBPROCESS_CHECK_CALL = subprocess.check_call
_ORIGINAL_SUBPROCESS_CHECK_OUTPUT = subprocess.check_output
_ORIGINAL_OS_SYSTEM = os.system
_ORIGINAL_OS_STARTFILE = getattr(os, "startfile", None)
_ORIGINAL_QFILEDIALOG_GET_OPEN_FILE_NAME = (
    QFileDialog.getOpenFileName if QFileDialog is not None else None
)
_ORIGINAL_QFILEDIALOG_GET_OPEN_FILE_NAMES = (
    QFileDialog.getOpenFileNames if QFileDialog is not None else None
)
_ORIGINAL_QFILEDIALOG_GET_SAVE_FILE_NAME = (
    QFileDialog.getSaveFileName if QFileDialog is not None else None
)
_ORIGINAL_QFILEDIALOG_GET_EXISTING_DIRECTORY = (
    QFileDialog.getExistingDirectory if QFileDialog is not None else None
)
_ORIGINAL_QFILEDIALOG_GET_EXISTING_DIRECTORY_URL = (
    getattr(QFileDialog, "getExistingDirectoryUrl", None) if QFileDialog is not None else None
)
_ORIGINAL_QFILEDIALOG_GET_OPEN_FILE_URL = (
    getattr(QFileDialog, "getOpenFileUrl", None) if QFileDialog is not None else None
)
_ORIGINAL_QFILEDIALOG_GET_OPEN_FILE_URLS = (
    getattr(QFileDialog, "getOpenFileUrls", None) if QFileDialog is not None else None
)
_ORIGINAL_QFILEDIALOG_GET_SAVE_FILE_URL = (
    getattr(QFileDialog, "getSaveFileUrl", None) if QFileDialog is not None else None
)


def _looks_like_test_process(argv: list[str] | tuple[str, ...] | None = None) -> bool:
    if os.environ.get(TEST_BLOCK_ENV_VAR) == "1":
        return True
    for marker in ("PYTEST_CURRENT_TEST", "PYTEST_VERSION"):
        if os.environ.get(marker):
            return True
    values = [str(value) for value in (argv or sys.argv or []) if str(value).strip()]
    if not values:
        return False
    for value in values:
        lowered = value.replace("\\", "/").lower()
        base_name = Path(lowered).name
        if "pytest" in lowered or "unittest" in lowered:
            return True
        if lowered.startswith("tests/") or "/tests/" in lowered:
            return True
        if base_name.startswith("test_") or base_name.endswith("_test.py"):
            return True
    return False


def _enable_qt_test_gui_safety() -> None:
    if QCoreApplication is None or Qt is None:
        return
    try:
        if QCoreApplication.instance() is not None:
            return
        QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    except Exception:
        return


def install_test_process_desktop_safety(*, blocked_return_value: bool = True) -> None:
    os.environ.setdefault(TEST_BLOCK_ENV_VAR, "1")
    _enable_qt_test_gui_safety()
    install_test_external_launch_guard(blocked_return_value=blocked_return_value)


def install_test_process_desktop_safety_if_needed(*, blocked_return_value: bool = True) -> bool:
    if not _looks_like_test_process():
        return False
    install_test_process_desktop_safety(blocked_return_value=blocked_return_value)
    return True


def install_unittest_test_process_desktop_safety_hook() -> None:
    try:
        import unittest
    except Exception:
        return

    discover = getattr(unittest.TestLoader, "discover", None)
    if getattr(discover, "_isrc_manager_desktop_safety_hook", False):
        return

    original_discover = unittest.TestLoader.discover
    original_load_from_name = unittest.TestLoader.loadTestsFromName
    original_load_from_names = unittest.TestLoader.loadTestsFromNames

    def _patched_discover(self, *args, **kwargs):
        install_test_process_desktop_safety()
        return original_discover(self, *args, **kwargs)

    def _maybe_install_for_name(name: object) -> None:
        name_text = str(name or "").replace("\\", "/")
        lowered = name_text.lower()
        if lowered.startswith("test_") or lowered.startswith("tests.") or "/tests/" in lowered:
            install_test_process_desktop_safety()

    def _patched_load_from_name(self, name, module=None):
        _maybe_install_for_name(name)
        return original_load_from_name(self, name, module)

    def _patched_load_from_names(self, names, module=None):
        for name in tuple(names or ()):
            _maybe_install_for_name(name)
        return original_load_from_names(self, names, module)

    _patched_discover._isrc_manager_desktop_safety_hook = True  # type: ignore[attr-defined]
    _patched_load_from_name._isrc_manager_desktop_safety_hook = True  # type: ignore[attr-defined]
    _patched_load_from_names._isrc_manager_desktop_safety_hook = True  # type: ignore[attr-defined]
    unittest.TestLoader.discover = _patched_discover
    unittest.TestLoader.loadTestsFromName = _patched_load_from_name
    unittest.TestLoader.loadTestsFromNames = _patched_load_from_names


def _normalize_qurl(url: QUrl | str | Path) -> QUrl | str:
    if QUrl is None:
        return str(url)
    if isinstance(url, QUrl):
        return QUrl(url)
    if isinstance(url, Path):
        return QUrl.fromLocalFile(str(url))
    text = str(url or "")
    candidate = QUrl(text)
    if candidate.isValid() and str(candidate.scheme() or "").strip():
        return candidate
    return QUrl.fromLocalFile(str(Path(text)))


def _url_text(url: QUrl | str | Path) -> str:
    normalized = _normalize_qurl(url)
    if QUrl is not None and isinstance(normalized, QUrl):
        return normalized.toString()
    return str(normalized)


def _record_launch(
    *,
    via: str,
    target: str,
    blocked: bool,
    source: str | None = None,
    metadata: dict[str, object] | None = None,
) -> ExternalLaunchRequest:
    request = ExternalLaunchRequest(
        via=str(via),
        target=str(target),
        blocked=bool(blocked),
        source=str(source) if source else None,
        metadata=dict(metadata or {}),
    )
    with _STATE.lock:
        _STATE.history.append(request)
    return request


def _as_text(value: object) -> str:
    if QUrl is not None and isinstance(value, QUrl):
        return value.toString()
    return str(value or "")


def external_launch_history() -> tuple[ExternalLaunchRequest, ...]:
    with _STATE.lock:
        return tuple(_STATE.history)


def get_recorded_external_launches() -> tuple[ExternalLaunchRequest, ...]:
    """Return recorded external-launch attempts for assertions and diagnostics."""
    return external_launch_history()


def clear_external_launch_history() -> None:
    with _STATE.lock:
        _STATE.history.clear()


def clear_recorded_external_launches() -> None:
    """Clear recorded external-launch attempts."""
    clear_external_launch_history()


def external_launch_guard_active() -> bool:
    with _STATE.lock:
        return bool(_STATE.installed)


def external_launch_blocking_enabled() -> bool:
    with _STATE.lock:
        return bool(_STATE.block_external_launches)


def set_external_launch_blocking(
    blocked: bool,
    *,
    blocked_return_value: bool = True,
) -> None:
    with _STATE.lock:
        _STATE.block_external_launches = bool(blocked)
        _STATE.blocked_return_value = bool(blocked_return_value)


@contextmanager
def temporary_external_launch_blocking(
    blocked: bool,
    *,
    blocked_return_value: bool = True,
):
    with _STATE.lock:
        previous_blocked = _STATE.block_external_launches
        previous_return_value = _STATE.blocked_return_value
        _STATE.block_external_launches = bool(blocked)
        _STATE.blocked_return_value = bool(blocked_return_value)
    try:
        yield
    finally:
        with _STATE.lock:
            _STATE.block_external_launches = previous_blocked
            _STATE.blocked_return_value = previous_return_value


def open_external_url(
    url: QUrl | str | Path,
    *,
    source: str | None = None,
    metadata: dict[str, object] | None = None,
) -> bool:
    normalized = _normalize_qurl(url)
    target = _url_text(normalized)
    blocked = external_launch_blocking_enabled()
    _record_launch(
        via="external_launch.open_external_url",
        target=target,
        blocked=blocked,
        source=source,
        metadata=metadata,
    )
    if blocked:
        return bool(_STATE.blocked_return_value)
    if _ORIGINAL_QDESKTOPSERVICES_OPENURL is None:
        return False
    try:
        return bool(_ORIGINAL_QDESKTOPSERVICES_OPENURL(normalized))
    except Exception:
        return False


def open_external_path(
    path: str | Path,
    *,
    source: str | None = None,
    metadata: dict[str, object] | None = None,
) -> bool:
    target = Path(path)
    metadata_payload = dict(metadata or {})
    metadata_payload.setdefault("local_path", str(target))
    return open_external_url(
        target,
        source=source,
        metadata=metadata_payload,
    )


def run_external_launcher_subprocess(
    command: object,
    *,
    source: str | None = None,
    metadata: dict[str, object] | None = None,
    shell: bool = False,
    **kwargs,
):
    blocked = external_launch_blocking_enabled()
    metadata_payload = dict(metadata or {})
    metadata_payload.setdefault("command", str(command))
    metadata_payload.setdefault("shell", bool(shell))
    if kwargs.get("input") is not None:
        metadata_payload.setdefault("has_input", True)
    _record_launch(
        via="external_launch.run_external_launcher_subprocess",
        target=_launch_target_from_command(command, shell=shell),
        blocked=blocked,
        source=source,
        metadata=metadata_payload,
    )
    if blocked:
        return _blocked_completed_process(command, kwargs)
    return _ORIGINAL_SUBPROCESS_RUN(command, shell=shell, **kwargs)


def _patched_qdesktopservices_open_url(url) -> bool:
    return open_external_url(
        url,
        source="QDesktopServices.openUrl",
        metadata={"patched": True},
    )


def _patched_webbrowser_open(url, new=0, autoraise=True):
    blocked = external_launch_blocking_enabled()
    _record_launch(
        via="webbrowser.open",
        target=str(url),
        blocked=blocked,
        source="webbrowser.open",
        metadata={"new": new, "autoraise": autoraise},
    )
    if blocked:
        return bool(_STATE.blocked_return_value)
    return bool(_ORIGINAL_WEBBROWSER_OPEN(url, new=new, autoraise=autoraise))


def _patched_webbrowser_open_new(url):
    blocked = external_launch_blocking_enabled()
    _record_launch(
        via="webbrowser.open_new",
        target=str(url),
        blocked=blocked,
        source="webbrowser.open_new",
    )
    if blocked:
        return bool(_STATE.blocked_return_value)
    return bool(_ORIGINAL_WEBBROWSER_OPEN_NEW(url))


def _patched_webbrowser_open_new_tab(url):
    blocked = external_launch_blocking_enabled()
    _record_launch(
        via="webbrowser.open_new_tab",
        target=str(url),
        blocked=blocked,
        source="webbrowser.open_new_tab",
    )
    if blocked:
        return bool(_STATE.blocked_return_value)
    return bool(_ORIGINAL_WEBBROWSER_OPEN_NEW_TAB(url))


def _looks_like_external_launch_command(
    command: object,
    *,
    shell: bool,
    input_payload: object | None = None,
) -> bool:
    tokens = _command_tokens(command, shell=shell)
    if not tokens:
        return False
    executable = Path(str(tokens[0])).name.lower()
    if executable in {"open", "xdg-open", "gio", "gio-open", "explorer", "explorer.exe"}:
        return True
    if executable == "cmd":
        lowered = [str(token).lower() for token in tokens[1:4]]
        return lowered[:2] == ["/c", "start"]
    if executable in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        lowered = " ".join(str(token).lower() for token in tokens[1:])
        return "start-process" in lowered
    if executable == "osascript":
        lowered = " ".join(str(token).lower() for token in tokens[1:])
        if input_payload is not None:
            if isinstance(input_payload, bytes):
                lowered += " " + input_payload.decode("utf-8", errors="ignore").lower()
            else:
                lowered += " " + str(input_payload).lower()
        return any(
            marker in lowered
            for marker in (
                "activate",
                "choose application",
                "choose file",
                "choose folder",
                "choose from list",
                "display alert",
                "display dialog",
                "open location",
                "reveal",
                'tell application "finder"',
                'tell application "preview"',
                'tell application "pages"',
                'tell application "safari"',
                'tell application "system events"',
            )
        )
    return False


def _command_tokens(command: object, *, shell: bool) -> list[str]:
    if isinstance(command, (list, tuple)):
        return [str(part) for part in command]
    if isinstance(command, str):
        if shell:
            try:
                return shlex.split(command)
            except Exception:
                return command.split()
        return [command]
    return [str(command)]


def _launch_target_from_command(command: object, *, shell: bool) -> str:
    tokens = _command_tokens(command, shell=shell)
    if not tokens:
        return ""
    if len(tokens) == 1:
        return str(tokens[0])
    return str(tokens[-1])


def _blocked_completed_process(
    command: object, kwargs: dict[str, object]
) -> subprocess.CompletedProcess:
    text_mode = bool(
        kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding") is not None
    )
    return subprocess.CompletedProcess(
        args=command,
        returncode=0,
        stdout="" if text_mode else b"",
        stderr="" if text_mode else b"",
    )


def _record_subprocess_launch(
    *,
    via: str,
    command: object,
    shell: bool,
) -> None:
    blocked = external_launch_blocking_enabled()
    _record_launch(
        via=via,
        target=_launch_target_from_command(command, shell=shell),
        blocked=blocked,
        source=via,
        metadata={"command": str(command), "shell": bool(shell)},
    )


def _patched_subprocess_run(*popenargs, **kwargs):
    command = popenargs[0] if popenargs else kwargs.get("args")
    shell = bool(kwargs.get("shell"))
    if _looks_like_external_launch_command(
        command,
        shell=shell,
        input_payload=kwargs.get("input"),
    ):
        _record_subprocess_launch(via="subprocess.run", command=command, shell=shell)
        if external_launch_blocking_enabled():
            return _blocked_completed_process(command, kwargs)
    return _ORIGINAL_SUBPROCESS_RUN(*popenargs, **kwargs)


def _patched_subprocess_call(*popenargs, **kwargs):
    command = popenargs[0] if popenargs else kwargs.get("args")
    shell = bool(kwargs.get("shell"))
    if _looks_like_external_launch_command(
        command,
        shell=shell,
        input_payload=kwargs.get("input"),
    ):
        _record_subprocess_launch(via="subprocess.call", command=command, shell=shell)
        if external_launch_blocking_enabled():
            return 0
    return _ORIGINAL_SUBPROCESS_CALL(*popenargs, **kwargs)


def _patched_subprocess_check_call(*popenargs, **kwargs):
    command = popenargs[0] if popenargs else kwargs.get("args")
    shell = bool(kwargs.get("shell"))
    if _looks_like_external_launch_command(
        command,
        shell=shell,
        input_payload=kwargs.get("input"),
    ):
        _record_subprocess_launch(via="subprocess.check_call", command=command, shell=shell)
        if external_launch_blocking_enabled():
            return 0
    return _ORIGINAL_SUBPROCESS_CHECK_CALL(*popenargs, **kwargs)


def _patched_subprocess_check_output(*popenargs, **kwargs):
    command = popenargs[0] if popenargs else kwargs.get("args")
    shell = bool(kwargs.get("shell"))
    if _looks_like_external_launch_command(
        command,
        shell=shell,
        input_payload=kwargs.get("input"),
    ):
        _record_subprocess_launch(via="subprocess.check_output", command=command, shell=shell)
        if external_launch_blocking_enabled():
            text_mode = bool(
                kwargs.get("text")
                or kwargs.get("universal_newlines")
                or kwargs.get("encoding") is not None
            )
            return "" if text_mode else b""
    return _ORIGINAL_SUBPROCESS_CHECK_OUTPUT(*popenargs, **kwargs)


def _patched_subprocess_popen(*popenargs, **kwargs):
    command = popenargs[0] if popenargs else kwargs.get("args")
    shell = bool(kwargs.get("shell"))
    if _looks_like_external_launch_command(command, shell=shell):
        _record_subprocess_launch(via="subprocess.Popen", command=command, shell=shell)
        if external_launch_blocking_enabled():
            text_mode = bool(
                kwargs.get("text")
                or kwargs.get("universal_newlines")
                or kwargs.get("encoding") is not None
            )
            return _BlockedPopen(command, text_mode=text_mode)
    return _ORIGINAL_SUBPROCESS_POPEN(*popenargs, **kwargs)


def _patched_os_startfile(path, operation=None):  # pragma: no cover - Windows-specific shim
    blocked = external_launch_blocking_enabled()
    _record_launch(
        via="os.startfile",
        target=str(path),
        blocked=blocked,
        source="os.startfile",
        metadata={"operation": operation},
    )
    if blocked:
        return bool(_STATE.blocked_return_value)
    if _ORIGINAL_OS_STARTFILE is None:
        raise AttributeError("os.startfile is unavailable on this platform")
    return _ORIGINAL_OS_STARTFILE(path, operation)


def _patched_os_system(command):
    if _looks_like_external_launch_command(command, shell=True):
        _record_subprocess_launch(via="os.system", command=command, shell=True)
        if external_launch_blocking_enabled():
            return 0
    return _ORIGINAL_OS_SYSTEM(command)


def _file_dialog_kwargs(args: tuple[object, ...], kwargs: dict[str, object]) -> dict[str, object]:
    details: dict[str, object] = {}
    if len(args) >= 2:
        details["caption"] = _as_text(args[1])
    elif "caption" in kwargs:
        details["caption"] = _as_text(kwargs.get("caption"))
    if len(args) >= 3:
        details["directory"] = _as_text(args[2])
    elif "dir" in kwargs:
        details["directory"] = _as_text(kwargs.get("dir"))
    elif "directory" in kwargs:
        details["directory"] = _as_text(kwargs.get("directory"))
    if len(args) >= 4:
        details["filter"] = _as_text(args[3])
    elif "filter" in kwargs:
        details["filter"] = _as_text(kwargs.get("filter"))
    if len(args) >= 5:
        details["selected_filter"] = _as_text(args[4])
    elif "selectedFilter" in kwargs:
        details["selected_filter"] = _as_text(kwargs.get("selectedFilter"))
    options = kwargs.get("options")
    if options is None and len(args) >= 6:
        options = args[5]
    if options is not None:
        details["options"] = _as_text(options)
    return {key: value for key, value in details.items() if str(value).strip()}


def _record_file_dialog(via: str, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
    details = _file_dialog_kwargs(args, kwargs)
    target = str(details.get("directory") or details.get("caption") or "")
    _record_launch(
        via=via,
        target=target,
        blocked=True,
        source=via,
        metadata={"desktop_dialog": True, **details},
    )


def _patched_qfiledialog_get_open_file_name(*args, **kwargs):
    _record_file_dialog("QFileDialog.getOpenFileName", args, kwargs)
    return "", ""


def _patched_qfiledialog_get_open_file_names(*args, **kwargs):
    _record_file_dialog("QFileDialog.getOpenFileNames", args, kwargs)
    return [], ""


def _patched_qfiledialog_get_save_file_name(*args, **kwargs):
    _record_file_dialog("QFileDialog.getSaveFileName", args, kwargs)
    return "", ""


def _patched_qfiledialog_get_existing_directory(*args, **kwargs):
    _record_file_dialog("QFileDialog.getExistingDirectory", args, kwargs)
    return ""


def _patched_qfiledialog_get_existing_directory_url(*args, **kwargs):
    _record_file_dialog("QFileDialog.getExistingDirectoryUrl", args, kwargs)
    if QUrl is None:
        return ""
    return QUrl()


def _patched_qfiledialog_get_open_file_url(*args, **kwargs):
    _record_file_dialog("QFileDialog.getOpenFileUrl", args, kwargs)
    if QUrl is None:
        return "", ""
    return QUrl(), ""


def _patched_qfiledialog_get_open_file_urls(*args, **kwargs):
    _record_file_dialog("QFileDialog.getOpenFileUrls", args, kwargs)
    return [], ""


def _patched_qfiledialog_get_save_file_url(*args, **kwargs):
    _record_file_dialog("QFileDialog.getSaveFileUrl", args, kwargs)
    if QUrl is None:
        return "", ""
    return QUrl(), ""


def install_test_external_launch_guard(*, blocked_return_value: bool = True) -> None:
    os.environ.setdefault(TEST_BLOCK_ENV_VAR, "1")
    set_external_launch_blocking(True, blocked_return_value=blocked_return_value)
    with _STATE.lock:
        if _STATE.installed:
            return
        _STATE.installed = True
    if QDesktopServices is not None:
        QDesktopServices.openUrl = staticmethod(_patched_qdesktopservices_open_url)
    webbrowser.open = _patched_webbrowser_open
    webbrowser.open_new = _patched_webbrowser_open_new
    webbrowser.open_new_tab = _patched_webbrowser_open_new_tab
    subprocess.run = _patched_subprocess_run
    subprocess.call = _patched_subprocess_call
    subprocess.check_call = _patched_subprocess_check_call
    subprocess.check_output = _patched_subprocess_check_output
    subprocess.Popen = _patched_subprocess_popen
    os.system = _patched_os_system
    if _ORIGINAL_OS_STARTFILE is not None:
        os.startfile = _patched_os_startfile  # type: ignore[attr-defined]
    if QFileDialog is not None:
        QFileDialog.getOpenFileName = staticmethod(_patched_qfiledialog_get_open_file_name)
        QFileDialog.getOpenFileNames = staticmethod(_patched_qfiledialog_get_open_file_names)
        QFileDialog.getSaveFileName = staticmethod(_patched_qfiledialog_get_save_file_name)
        QFileDialog.getExistingDirectory = staticmethod(_patched_qfiledialog_get_existing_directory)
        if _ORIGINAL_QFILEDIALOG_GET_EXISTING_DIRECTORY_URL is not None:
            QFileDialog.getExistingDirectoryUrl = staticmethod(
                _patched_qfiledialog_get_existing_directory_url
            )
        if _ORIGINAL_QFILEDIALOG_GET_OPEN_FILE_URL is not None:
            QFileDialog.getOpenFileUrl = staticmethod(_patched_qfiledialog_get_open_file_url)
        if _ORIGINAL_QFILEDIALOG_GET_OPEN_FILE_URLS is not None:
            QFileDialog.getOpenFileUrls = staticmethod(_patched_qfiledialog_get_open_file_urls)
        if _ORIGINAL_QFILEDIALOG_GET_SAVE_FILE_URL is not None:
            QFileDialog.getSaveFileUrl = staticmethod(_patched_qfiledialog_get_save_file_url)


try:  # pragma: no cover - environment entrypoint
    install_test_process_desktop_safety_if_needed()
except Exception:
    pass

"""Centralized external URL/path launch policy with test-safe blocking hooks."""

from __future__ import annotations

import os
import shlex
import subprocess
import threading
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

try:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
except ImportError:  # pragma: no cover - environment-specific fallback
    QUrl = None
    QDesktopServices = None


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
_ORIGINAL_OS_STARTFILE = getattr(os, "startfile", None)


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
                "open location",
                'tell application "finder"',
                'tell application "pages"',
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


def install_test_external_launch_guard(*, blocked_return_value: bool = True) -> None:
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
    if _ORIGINAL_OS_STARTFILE is not None:
        os.startfile = _patched_os_startfile  # type: ignore[attr-defined]


if os.environ.get(TEST_BLOCK_ENV_VAR) == "1":  # pragma: no cover - environment entrypoint
    install_test_external_launch_guard()

"""Mock and guard helpers for no-network QA execution."""

from __future__ import annotations

import socket
from types import TracebackType
from unittest import mock


class NoNetworkGuard:
    """Blocks outbound socket connection attempts during UI PQ tests."""

    def __init__(self) -> None:
        self._patcher: mock._patch | None = None

    def __enter__(self) -> "NoNetworkGuard":
        def _blocked_connect(_socket: socket.socket, address: object) -> None:
            raise RuntimeError(f"UI PQ no-network mode blocked socket connection to {address!r}")

        self._patcher = mock.patch.object(socket.socket, "connect", _blocked_connect)
        self._patcher.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        if self._patcher is not None:
            self._patcher.stop()
            self._patcher = None

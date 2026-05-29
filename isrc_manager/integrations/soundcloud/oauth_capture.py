"""User-facing OAuth callback capture helpers for SoundCloud."""

from __future__ import annotations

import http.server
import threading
import webbrowser
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from PySide6.QtWidgets import QInputDialog, QLineEdit, QWidget

from .client import redact_text


class SoundCloudOAuthCallbackCaptureError(RuntimeError):
    """Raised when the OAuth callback cannot be captured safely."""


@dataclass(frozen=True, slots=True)
class SoundCloudOAuthCaptureConfig:
    timeout_seconds: float = 180.0


def _is_loopback_redirect(redirect_uri: str) -> bool:
    parsed = urlparse(redirect_uri)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "127.0.0.1",
        "localhost",
        "::1",
    }


class _LoopbackCallbackHandler(http.server.BaseHTTPRequestHandler):
    server: "_LoopbackHTTPServer"

    def log_message(self, _format: str, *_args) -> None:
        return

    def do_GET(self) -> None:
        parsed_redirect = urlparse(self.server.redirect_uri)
        request_url = urlunparse(
            (
                parsed_redirect.scheme,
                parsed_redirect.netloc,
                self.path.split("?", 1)[0],
                "",
                self.path.split("?", 1)[1] if "?" in self.path else "",
                "",
            )
        )
        if self.path.split("?", 1)[0] != parsed_redirect.path:
            self.send_response(404)
            self.end_headers()
            return
        self.server.callback_url = request_url
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h1>SoundCloud authorization received.</h1>"
            b"<p>You may return to ISRC Catalog Manager.</p></body></html>"
        )


class _LoopbackHTTPServer(http.server.HTTPServer):
    def __init__(self, server_address: tuple[str, int], redirect_uri: str) -> None:
        super().__init__(server_address, _LoopbackCallbackHandler)
        self.redirect_uri = redirect_uri
        self.callback_url: str | None = None


class SoundCloudOAuthCallbackProvider:
    """Open the authorization URL and capture the callback without persisting it."""

    def __init__(
        self,
        *,
        parent: QWidget | None = None,
        config: SoundCloudOAuthCaptureConfig | None = None,
    ) -> None:
        self.parent = parent
        self.config = config or SoundCloudOAuthCaptureConfig()

    def capture(self, *, auth_url: str, expected_state: str, redirect_uri: str) -> str:
        del expected_state
        webbrowser.open(auth_url)
        if _is_loopback_redirect(redirect_uri):
            return self._capture_loopback(redirect_uri)
        return self._prompt_hidden_callback()

    def _capture_loopback(self, redirect_uri: str) -> str:
        parsed = urlparse(redirect_uri)
        host = parsed.hostname or "127.0.0.1"
        port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
        server = _LoopbackHTTPServer((host, port), redirect_uri)
        server.timeout = float(self.config.timeout_seconds)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        thread.join(timeout=float(self.config.timeout_seconds) + 1.0)
        server.server_close()
        if not server.callback_url:
            raise SoundCloudOAuthCallbackCaptureError(
                "SoundCloud OAuth callback was not received before timeout."
            )
        return server.callback_url

    def _prompt_hidden_callback(self) -> str:
        callback_url, accepted = QInputDialog.getText(
            self.parent,
            "SoundCloud OAuth Callback",
            "Paste the full SoundCloud callback URL. The value is hidden and not stored.",
            QLineEdit.EchoMode.Password,
            "",
        )
        if not accepted or not str(callback_url or "").strip():
            raise SoundCloudOAuthCallbackCaptureError("SoundCloud OAuth callback was cancelled.")
        return str(callback_url).strip()


def redacted_callback_error(exc: Exception) -> str:
    return redact_text(str(exc))


__all__ = [
    "SoundCloudOAuthCallbackCaptureError",
    "SoundCloudOAuthCallbackProvider",
    "SoundCloudOAuthCaptureConfig",
    "redacted_callback_error",
]

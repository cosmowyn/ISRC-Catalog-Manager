"""Manual app-owned credential reset workflow orchestration."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMessageBox, QWidget

from isrc_manager.credential_reset import (
    CredentialResetResult,
    MacOSCredentialResetService,
)
from isrc_manager.integrations.soundcloud.workflow import soundcloud_settings_snapshot


class CredentialResetController:
    """Run the explicit macOS Keychain reset without blocking the settings UI."""

    def __init__(
        self,
        app: Any,
        *,
        service: MacOSCredentialResetService | None = None,
    ) -> None:
        self.app = app
        self.service = service or MacOSCredentialResetService()

    @property
    def available(self) -> bool:
        """Return whether the narrow macOS reset mechanism can run."""

        return bool(self.service.supported)

    @staticmethod
    def _reset_button(owner: QWidget):
        return getattr(owner, "reset_stored_credentials_button", None)

    def _set_button_enabled(self, owner: QWidget, enabled: bool) -> None:
        button = self._reset_button(owner)
        setter = getattr(button, "setEnabled", None)
        if callable(setter):
            setter(bool(enabled))

    def _record_event(self, event: str, message: str, **details: object) -> None:
        reporter = getattr(self.app, "_log_event", None)
        if callable(reporter):
            reporter(event, message, **details)

    def _show_success(self, owner: QWidget, result: CredentialResetResult) -> None:
        deleted_count = int(result.total_items_deleted)
        self._record_event(
            "security.credentials_reset",
            "App-owned macOS Keychain credentials reset",
            deleted_items=deleted_count,
        )

        soundcloud_panel = getattr(owner, "soundcloud_panel", None)
        set_snapshot = getattr(soundcloud_panel, "set_snapshot", None)
        if callable(set_snapshot):
            try:
                set_snapshot(soundcloud_settings_snapshot(self.app))
            except Exception:
                # The reset result remains valid even if an optional settings summary
                # cannot be refreshed while its dialog is closing.
                pass

        play_notice = getattr(self.app, "_play_notice_sound", None)
        if callable(play_notice):
            play_notice()

        if deleted_count:
            opening = (
                f"Removed {deleted_count} credential item(s) stored by this app from "
                "macOS Keychain."
            )
        else:
            opening = "No stored macOS Keychain credentials for this app were found."
        QMessageBox.information(
            owner,
            "Stored Credentials Reset",
            (
                f"{opening}\n\n"
                "Only the app's fixed database and SoundCloud credential namespaces "
                "were targeted. Other Keychain passwords were not changed.\n\n"
                "Quit and reopen the app for a completely fresh session, then enter "
                "database passwords and reconnect SoundCloud as needed. Database "
                "encryption passwords were not changed, and remote SoundCloud access "
                "was not revoked."
            ),
        )

    def _show_error(self, owner: QWidget, failure: object) -> None:
        message = str(getattr(failure, "message", "") or "").strip()
        self._record_event(
            "security.credentials_reset_failed",
            "App-owned macOS Keychain credential reset failed",
            error=message or "Credential reset did not complete.",
        )
        play_warning = getattr(self.app, "_play_warning_sound", None)
        if callable(play_warning):
            play_warning()
        detail = f"\n\n{message}" if message else ""
        QMessageBox.critical(
            owner,
            "Credential Reset Incomplete",
            (
                "The reset did not finish. Some app-owned credentials may already "
                "have been removed. No credential namespaces outside this app's fixed "
                f"allowlist were targeted.{detail}\n\n"
                "Quit and reopen the app, then try the manual reset again."
            ),
        )

    def start(self, owner: QWidget) -> str | None:
        """Start the already-confirmed reset as a non-cancellable exclusive task."""

        if not self.available:
            QMessageBox.warning(
                owner,
                "Credential Reset Unavailable",
                "The manual app-credential reset is available only on macOS when "
                "/usr/bin/security is present.",
            )
            return None

        submit = getattr(self.app, "_submit_background_task", None)
        if not callable(submit):
            QMessageBox.critical(
                owner,
                "Credential Reset Unavailable",
                "The background task service is unavailable, so no credentials were changed.",
            )
            return None

        self._set_button_enabled(owner, False)

        def _task(ctx):
            ctx.set_status("Removing only this app's macOS Keychain credentials...")
            return self.service.reset()

        def _success(result: object) -> None:
            if not isinstance(result, CredentialResetResult):
                self._show_error(owner, object())
                return
            self._show_success(owner, result)

        def _error(failure: object) -> None:
            self._show_error(owner, failure)
            self._set_button_enabled(owner, self.available)

        def _finished() -> None:
            self._set_button_enabled(owner, self.available)

        try:
            task_id = submit(
                title="Reset Stored Credentials",
                description="Removing only this app's macOS Keychain credentials...",
                task_fn=_task,
                kind="exclusive",
                unique_key="security.credentials_reset",
                requires_profile=False,
                show_dialog=True,
                cancellable=False,
                owner=owner,
                on_success=_success,
                on_error=_error,
                on_finished=_finished,
            )
        except Exception:
            self._set_button_enabled(owner, self.available)
            QMessageBox.critical(
                owner,
                "Credential Reset Unavailable",
                "The reset task could not start, so no credentials were changed.",
            )
            return None
        if task_id is None:
            self._set_button_enabled(owner, self.available)
        return task_id


__all__ = ["CredentialResetController"]

"""Security controls for the Application Settings dialog."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

DatabasePasswordChangeCallback = Callable[[], object]
CredentialResetCallback = Callable[[QDialog], object]


class ApplicationSettingsSecurityPanel(QGroupBox):
    """Focused security settings and manual credential-reset actions."""

    def __init__(
        self,
        *,
        owner: QDialog,
        remember_database_password: bool = False,
        suppress_unencrypted_profile_warnings: bool = False,
        database_password_change_callback: DatabasePasswordChangeCallback | None = None,
        credential_reset_callback: CredentialResetCallback | None = None,
    ) -> None:
        super().__init__("Security", owner)
        self._owner = owner
        self._database_password_change_callback = database_password_change_callback
        self._credential_reset_callback = credential_reset_callback
        self._remember_database_password_warning_shown = bool(remember_database_password)
        self._suppress_unencrypted_profile_warning_notice_shown = bool(
            suppress_unencrypted_profile_warnings
        )

        grid = QGridLayout(self)
        self._configure_grid(grid)

        self.remember_database_password_check = QCheckBox(
            "Remember database password on this device"
        )
        self.remember_database_password_check.setChecked(bool(remember_database_password))
        self.remember_database_password_check.setMinimumWidth(360)
        self.remember_database_password_check.toggled.connect(
            self._confirm_remember_database_password
        )

        self.change_database_password_button = QPushButton("Change Password...")
        self.change_database_password_button.setAutoDefault(False)
        self.change_database_password_button.setEnabled(
            callable(self._database_password_change_callback)
        )
        self.change_database_password_button.clicked.connect(self._change_database_password)

        password_widget = QWidget(self)
        password_row = QHBoxLayout(password_widget)
        password_row.setContentsMargins(0, 0, 0, 0)
        password_row.setSpacing(8)
        password_row.addWidget(self.remember_database_password_check)
        password_row.addWidget(self.change_database_password_button)
        password_row.addStretch(1)
        self._add_row(
            grid,
            0,
            "Database Password",
            password_widget,
            "Stores the profile password only in the operating-system keychain/keyring and "
            "expires remembered login after 30 days.",
        )

        self.suppress_unencrypted_profile_warnings_check = QCheckBox(
            "Do not warn when opening unencrypted profiles"
        )
        self.suppress_unencrypted_profile_warnings_check.setChecked(
            bool(suppress_unencrypted_profile_warnings)
        )
        self.suppress_unencrypted_profile_warnings_check.setMinimumWidth(360)
        self.suppress_unencrypted_profile_warnings_check.toggled.connect(
            self._confirm_unencrypted_profile_warning_suppression
        )
        self._add_row(
            grid,
            1,
            "Unencrypted Profiles",
            self.suppress_unencrypted_profile_warnings_check,
            "Turns off all unencrypted-profile safety prompts. Leave this off unless you "
            "intentionally accept the risk.",
        )

        self.reset_stored_credentials_button = QPushButton("Reset Stored Credentials…")
        self.reset_stored_credentials_button.setObjectName("resetStoredCredentialsButton")
        self.reset_stored_credentials_button.setAutoDefault(False)
        self.reset_stored_credentials_button.setEnabled(callable(self._credential_reset_callback))
        self.reset_stored_credentials_button.clicked.connect(self._reset_stored_credentials)
        reset_widget = QWidget(self)
        reset_row = QHBoxLayout(reset_widget)
        reset_row.setContentsMargins(0, 0, 0, 0)
        reset_row.addWidget(self.reset_stored_credentials_button)
        reset_row.addStretch(1)
        self._add_row(
            grid,
            2,
            "Stored Credentials",
            reset_widget,
            "Immediately removes only this application's remembered database and SoundCloud "
            "credentials from the operating-system keychain/keyring. Other applications' "
            "credentials are not changed, and cancelling Application Settings cannot undo the "
            "reset.",
        )

    @staticmethod
    def _configure_grid(grid: QGridLayout) -> None:
        grid.setColumnMinimumWidth(0, 0)
        grid.setColumnMinimumWidth(1, 300)
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

    @staticmethod
    def _make_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        padding = label.fontMetrics().horizontalAdvance("  ")
        min_width = label.fontMetrics().horizontalAdvance("M" * 10)
        max_width = label.fontMetrics().horizontalAdvance("M" * 18)
        label_width = max(min_width, min(max_width, label.sizeHint().width() + padding))
        label.setFixedWidth(label_width)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return label

    @staticmethod
    def _make_hint(text: str) -> QLabel:
        hint = QLabel(text)
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        return hint

    def _add_row(
        self,
        grid: QGridLayout,
        row: int,
        label: str,
        editor: QWidget,
        hint: str | None = None,
    ) -> None:
        grid.addWidget(self._make_label(label), row, 0)
        if not hint:
            grid.addWidget(editor, row, 1)
            return
        editor_box = QWidget(self)
        editor_layout = QVBoxLayout(editor_box)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(4)
        editor_layout.addWidget(editor)
        editor_layout.addWidget(self._make_hint(hint))
        grid.addWidget(editor_box, row, 1)

    def _confirm_remember_database_password(self, checked: bool) -> None:
        if not checked or self._remember_database_password_warning_shown:
            return
        result = QMessageBox.warning(
            self,
            "Remember Database Password",
            (
                "The database password will be stored in the operating-system "
                "keychain/keyring on this device and reused for up to 30 days. "
                "Do not enable this on shared or untrusted machines."
            ),
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if result != QMessageBox.Ok:
            self.remember_database_password_check.blockSignals(True)
            self.remember_database_password_check.setChecked(False)
            self.remember_database_password_check.blockSignals(False)
            return
        self._remember_database_password_warning_shown = True

    def _confirm_unencrypted_profile_warning_suppression(self, checked: bool) -> None:
        if not checked or self._suppress_unencrypted_profile_warning_notice_shown:
            return
        result = QMessageBox.warning(
            self,
            "Unencrypted Profile Warnings",
            (
                "This turns off warnings for every unencrypted profile. Unencrypted SQLite "
                "profiles do not protect catalog data or backups if copied or stolen. "
                "Enable this only if you intentionally accept that risk."
            ),
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if result != QMessageBox.Ok:
            self.suppress_unencrypted_profile_warnings_check.blockSignals(True)
            self.suppress_unencrypted_profile_warnings_check.setChecked(False)
            self.suppress_unencrypted_profile_warnings_check.blockSignals(False)
            return
        self._suppress_unencrypted_profile_warning_notice_shown = True

    def _change_database_password(self) -> None:
        if callable(self._database_password_change_callback):
            self._database_password_change_callback()

    def _reset_stored_credentials(self) -> None:
        if not callable(self._credential_reset_callback):
            return
        result = QMessageBox.warning(
            self,
            "Reset Stored Credentials",
            (
                "Immediately remove all credentials stored by this application from the "
                "operating-system keychain/keyring?\n\n"
                "This removes remembered database passwords for all profiles and SoundCloud "
                "client secrets and OAuth tokens.\n\n"
                "It does not change database encryption passwords, profile or catalog data, "
                "application settings, credentials stored by other applications, or revoke "
                "remote SoundCloud access.\n\n"
                "This action runs immediately. Cancelling Application Settings afterwards "
                "cannot undo it. You will need to re-enter database passwords and reconnect "
                "SoundCloud."
            ),
            QMessageBox.Reset | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if result != QMessageBox.Reset:
            return
        self._credential_reset_callback(self._owner)


__all__ = ["ApplicationSettingsSecurityPanel"]

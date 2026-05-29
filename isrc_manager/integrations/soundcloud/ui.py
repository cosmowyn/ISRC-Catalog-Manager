"""Qt widgets for SoundCloud settings and publish planning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .client import redact_text
from .models import (
    SoundCloudExecutionStatus,
    SoundCloudPlanAction,
    SoundCloudPlanItemStatus,
    SoundCloudPublishExecutionResult,
    SoundCloudPublishOptions,
    SoundCloudPublishPlanResult,
)

_SOUNDCLOUD_ICON_DIR = Path(__file__).resolve().parents[3] / "icons"
_SOUNDCLOUD_LOGO_BLACK = _SOUNDCLOUD_ICON_DIR / "SoundCloud_Horizontal Black (transparent).png"
_SOUNDCLOUD_LOGO_WHITE = _SOUNDCLOUD_ICON_DIR / "SoundCloud_Horizontal White (transparent).png"


def _soundcloud_logo_path_for_palette(palette: QPalette) -> Path:
    background = palette.color(QPalette.ColorRole.Window)
    return _SOUNDCLOUD_LOGO_WHITE if background.lightness() < 128 else _SOUNDCLOUD_LOGO_BLACK


@dataclass(frozen=True, slots=True)
class SoundCloudSettingsSnapshot:
    """Non-secret SoundCloud settings and connection status for UI display."""

    client_id: str = ""
    redirect_uri: str = ""
    prefer_persistent_tokens: bool = True
    persistent_available: bool = False
    connected: bool = False
    account_label: str = "Disconnected"
    token_storage_label: str = "Session-only"
    status_message: str = ""
    reconnect_required: bool = False


@dataclass(frozen=True, slots=True)
class SoundCloudCatalogTrackChoice:
    """Safe catalog row used by the publish dialog picker."""

    track_id: int
    title: str
    album: str = ""
    artist: str = ""
    isrc: str = ""
    duration_seconds: int = 0


@dataclass(frozen=True, slots=True)
class SoundCloudPublishRunSummary:
    """Non-secret publish-run summary for the history dialog."""

    run_id: int
    status: str
    created_at: str
    items_total: int
    items_succeeded: int
    items_failed: int
    items_skipped: int


@dataclass(frozen=True, slots=True)
class SoundCloudExistingUploadChoice:
    """Non-secret SoundCloud upload candidate for manual catalog matching."""

    remote_urn: str
    remote_numeric_id: int | None
    remote_url: str | None
    title: str = ""
    genre: str = ""
    created_at: str = ""
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SoundCloudMetadataComparisonRow:
    """One side-by-side catalog-vs-remote metadata row."""

    field: str
    catalog_value: str
    remote_value: str
    changed: bool = False
    state: str | None = None


class SoundCloudConnectionActions(Protocol):
    """UI-safe connection actions implemented by the SoundCloud service layer."""

    def snapshot(self) -> SoundCloudSettingsSnapshot: ...

    def connect(self, *, client_id: str, redirect_uri: str) -> SoundCloudSettingsSnapshot: ...

    def refresh(self, *, client_id: str, redirect_uri: str) -> SoundCloudSettingsSnapshot: ...

    def disconnect(self) -> SoundCloudSettingsSnapshot: ...

    def save_client_secret(
        self, *, client_id: str, client_secret: str
    ) -> SoundCloudSettingsSnapshot: ...


class NullSoundCloudConnectionActions:
    """Fallback action set used when the application has no SoundCloud runtime."""

    def __init__(self, snapshot: SoundCloudSettingsSnapshot | None = None) -> None:
        self._snapshot = snapshot or SoundCloudSettingsSnapshot()

    def snapshot(self) -> SoundCloudSettingsSnapshot:
        return self._snapshot

    def connect(self, *, client_id: str, redirect_uri: str) -> SoundCloudSettingsSnapshot:
        raise RuntimeError("SoundCloud connection service is not configured.")

    def refresh(self, *, client_id: str, redirect_uri: str) -> SoundCloudSettingsSnapshot:
        raise RuntimeError("SoundCloud connection service is not configured.")

    def disconnect(self) -> SoundCloudSettingsSnapshot:
        return self._snapshot

    def save_client_secret(
        self, *, client_id: str, client_secret: str
    ) -> SoundCloudSettingsSnapshot:
        del client_id, client_secret
        raise RuntimeError("SoundCloud credential service is not configured.")


def _format_duration(seconds: int) -> str:
    clean = max(0, int(seconds or 0))
    minutes, remaining = divmod(clean, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remaining:02d}"
    return f"{minutes}:{remaining:02d}"


class SoundCloudSettingsPanel(QWidget):
    """Settings tab for safe SoundCloud connection configuration."""

    def __init__(
        self,
        *,
        snapshot: SoundCloudSettingsSnapshot | None = None,
        actions: SoundCloudConnectionActions | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("soundcloudSettingsPanel")
        self.actions = actions or NullSoundCloudConnectionActions(snapshot)
        self._snapshot = snapshot or self.actions.snapshot()

        root = QVBoxLayout(self)
        root.setSpacing(12)

        intro = QLabel(
            "Prepare and manage the explicit SoundCloud account connection. "
            "Secrets and OAuth callback query strings are never displayed here."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        connection_group = QGroupBox("Connection")
        grid = QGridLayout(connection_group)
        grid.setColumnStretch(1, 1)

        self.client_id_edit = QLineEdit()
        self.client_id_edit.setObjectName("soundcloudClientIdEdit")
        self.client_id_edit.setPlaceholderText("SoundCloud app client id")
        grid.addWidget(QLabel("Client id"), 0, 0)
        grid.addWidget(self.client_id_edit, 0, 1)

        self.redirect_uri_edit = QLineEdit()
        self.redirect_uri_edit.setObjectName("soundcloudRedirectUriEdit")
        self.redirect_uri_edit.setPlaceholderText("https://example.invalid/soundcloud/callback")
        grid.addWidget(QLabel("Redirect URI"), 1, 0)
        grid.addWidget(self.redirect_uri_edit, 1, 1)

        self.account_status_label = QLabel()
        self.account_status_label.setObjectName("soundcloudConnectionStatusLabel")
        self.account_status_label.setWordWrap(True)
        grid.addWidget(QLabel("Account"), 2, 0)
        grid.addWidget(self.account_status_label, 2, 1)

        self.token_mode_label = QLabel()
        self.token_mode_label.setObjectName("soundcloudTokenModeLabel")
        self.token_mode_label.setWordWrap(True)
        grid.addWidget(QLabel("Token storage"), 3, 0)
        grid.addWidget(self.token_mode_label, 3, 1)

        self.persistent_check = QCheckBox("Prefer persistent OS keychain/keyring storage")
        self.persistent_check.setObjectName("soundcloudPersistentTokenModeCheck")
        grid.addWidget(self.persistent_check, 4, 1)

        self.keychain_status_label = QLabel()
        self.keychain_status_label.setObjectName("soundcloudKeychainStatusLabel")
        self.keychain_status_label.setWordWrap(True)
        grid.addWidget(QLabel("Keychain"), 5, 0)
        grid.addWidget(self.keychain_status_label, 5, 1)

        self.session_fallback_label = QLabel()
        self.session_fallback_label.setObjectName("soundcloudSessionFallbackLabel")
        self.session_fallback_label.setWordWrap(True)
        grid.addWidget(self.session_fallback_label, 6, 1)

        self.client_secret_edit = QLineEdit()
        self.client_secret_edit.setObjectName("soundcloudClientSecretEdit")
        self.client_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_secret_edit.setPlaceholderText("Write-only client secret")
        self.save_secret_button = QPushButton("Store client secret securely")
        self.save_secret_button.setObjectName("soundcloudSaveClientSecretButton")
        secret_box = QWidget(self)
        secret_layout = QHBoxLayout(secret_box)
        secret_layout.setContentsMargins(0, 0, 0, 0)
        secret_layout.addWidget(self.client_secret_edit, 1)
        secret_layout.addWidget(self.save_secret_button)
        grid.addWidget(QLabel("Client secret"), 7, 0)
        grid.addWidget(secret_box, 7, 1)

        buttons = QHBoxLayout()
        self.connect_button = QPushButton("Connect to SoundCloud")
        self.connect_button.setObjectName("soundcloudConnectButton")
        self.refresh_button = QPushButton("Refresh connection")
        self.refresh_button.setObjectName("soundcloudRefreshButton")
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setObjectName("soundcloudDisconnectButton")
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.disconnect_button)
        buttons.addStretch(1)
        grid.addLayout(buttons, 8, 1)

        self.message_label = QLabel()
        self.message_label.setObjectName("soundcloudSettingsMessageLabel")
        self.message_label.setWordWrap(True)
        grid.addWidget(self.message_label, 9, 1)

        root.addWidget(connection_group)
        root.addStretch(1)

        self.connect_button.clicked.connect(self._connect_clicked)
        self.refresh_button.clicked.connect(self._refresh_clicked)
        self.disconnect_button.clicked.connect(self._disconnect_clicked)
        self.save_secret_button.clicked.connect(self._save_secret_clicked)
        self.set_snapshot(self._snapshot)

    def set_snapshot(self, snapshot: SoundCloudSettingsSnapshot) -> None:
        self._snapshot = snapshot
        self.client_id_edit.setText(snapshot.client_id)
        self.redirect_uri_edit.setText(snapshot.redirect_uri)
        account = snapshot.account_label or ("Connected" if snapshot.connected else "Disconnected")
        self.account_status_label.setText(account)
        self.token_mode_label.setText(snapshot.token_storage_label or "Session-only")
        self.persistent_check.setEnabled(snapshot.persistent_available)
        self.persistent_check.setChecked(
            bool(snapshot.prefer_persistent_tokens and snapshot.persistent_available)
        )
        if snapshot.persistent_available:
            self.keychain_status_label.setText(
                "Available: safe OS keychain/keyring backend detected."
            )
            self.session_fallback_label.setText(
                "Persistent keychain/keyring storage is available for OAuth tokens."
            )
        else:
            self.keychain_status_label.setText("Unavailable: persistent storage is disabled.")
            self.session_fallback_label.setText(
                "Session-only fallback is active because OS keychain/keyring storage is unavailable."
            )
        message = redact_text(snapshot.status_message or "")
        if snapshot.reconnect_required:
            message = (
                f"{message}\n" if message else ""
            ) + "Reconnect is required before persistent SoundCloud publishing can continue."
        self.message_label.setText(message)
        self.refresh_button.setEnabled(snapshot.connected)
        self.disconnect_button.setEnabled(snapshot.connected)

    def values(self) -> dict[str, object]:
        return {
            "soundcloud_client_id": self.client_id_edit.text().strip(),
            "soundcloud_redirect_uri": self.redirect_uri_edit.text().strip(),
            "soundcloud_prefer_persistent_tokens": bool(
                self.persistent_check.isEnabled() and self.persistent_check.isChecked()
            ),
        }

    def focus_default(self) -> None:
        self.client_id_edit.setFocus(Qt.OtherFocusReason)
        self.client_id_edit.selectAll()

    def _connect_clicked(self) -> None:
        self._run_action("connect")

    def _refresh_clicked(self) -> None:
        self._run_action("refresh")

    def _disconnect_clicked(self) -> None:
        self._run_action("disconnect")

    def _save_secret_clicked(self) -> None:
        self._run_action("save_secret")

    def _hide_for_external_auth(self) -> tuple[QWidget | None, bool]:
        window = self.window()
        if window is None:
            return None, False
        was_visible = bool(window.isVisible())
        if was_visible:
            window.hide()
            QApplication.processEvents()
        return window, was_visible

    def _restore_after_external_auth(self, window: QWidget | None, was_visible: bool) -> None:
        if window is None or not was_visible:
            return
        window.show()
        raise_window = getattr(window, "raise_", None)
        if callable(raise_window):
            raise_window()
        activate_window = getattr(window, "activateWindow", None)
        if callable(activate_window):
            activate_window()
        QApplication.processEvents()

    def _run_action(self, action_name: str) -> None:
        auth_window: QWidget | None = None
        auth_window_was_visible = False
        try:
            if action_name == "connect":
                auth_window, auth_window_was_visible = self._hide_for_external_auth()
                snapshot = self.actions.connect(
                    client_id=self.client_id_edit.text().strip(),
                    redirect_uri=self.redirect_uri_edit.text().strip(),
                )
            elif action_name == "refresh":
                snapshot = self.actions.refresh(
                    client_id=self.client_id_edit.text().strip(),
                    redirect_uri=self.redirect_uri_edit.text().strip(),
                )
            elif action_name == "save_secret":
                snapshot = self.actions.save_client_secret(
                    client_id=self.client_id_edit.text().strip(),
                    client_secret=self.client_secret_edit.text(),
                )
                self.client_secret_edit.clear()
            else:
                snapshot = self.actions.disconnect()
        except Exception as exc:
            self.client_secret_edit.clear()
            self.message_label.setText(redact_text(str(exc)))
            return
        finally:
            self._restore_after_external_auth(auth_window, auth_window_was_visible)
        self.set_snapshot(snapshot)


class SoundCloudPublishHistoryDialog(QDialog):
    """Simple non-secret SoundCloud publish-run history browser."""

    def __init__(
        self,
        *,
        runs: list[SoundCloudPublishRunSummary],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("soundcloudPublishHistoryDialog")
        self.setWindowTitle("SoundCloud Publish History")
        self.resize(860, 420)
        root = QVBoxLayout(self)
        self.table = QTableWidget(0, 7)
        self.table.setObjectName("soundcloudPublishHistoryTable")
        self.table.setHorizontalHeaderLabels(
            ["Run", "Status", "Created", "Total", "Succeeded", "Failed", "Skipped"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)
        root.addWidget(self.table, 1)
        self._populate(runs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _populate(self, runs: list[SoundCloudPublishRunSummary]) -> None:
        self.table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            values = [
                run.run_id,
                run.status,
                run.created_at,
                run.items_total,
                run.items_succeeded,
                run.items_failed,
                run.items_skipped,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))


class SoundCloudCatalogTrackSelectionDialog(QDialog):
    """Catalog track picker with filtering, sorting, and checkbox selection."""

    def __init__(
        self,
        *,
        choices: list[SoundCloudCatalogTrackChoice],
        selected_track_ids: tuple[int, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("soundcloudCatalogTrackSelectionDialog")
        self.setWindowTitle("Select Catalog Tracks for SoundCloud")
        self.resize(980, 620)
        self._choices = list(choices)
        self._selected_track_ids = tuple(int(track_id) for track_id in selected_track_ids)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Choose catalog tracks for this SoundCloud publish run. Use the filter for quick "
            "browsing and click table headers to sort by album, title, artist, ISRC, or duration."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("soundcloudCatalogFilterEdit")
        self.filter_edit.setPlaceholderText("Filter by title, album, artist, ISRC, or id")
        root.addWidget(self.filter_edit)

        self.table = QTableWidget(0, 6)
        self.table.setObjectName("soundcloudCatalogSelectionTable")
        self.table.setHorizontalHeaderLabels(
            ["Publish", "Title", "Album", "Artist", "ISRC", "Duration"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for column in range(1, 6):
            header.setSectionResizeMode(column, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 110)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setStyleSheet("""
            QTableWidget#soundcloudCatalogSelectionTable::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #f5d76e;
                border-radius: 4px;
                background: #111827;
            }
            QTableWidget#soundcloudCatalogSelectionTable::indicator:checked {
                border: 2px solid #eaf6ff;
                background: #1e9bff;
            }
            QTableWidget#soundcloudCatalogSelectionTable::item {
                padding: 5px;
            }
            """)
        self.table.setSortingEnabled(True)
        root.addWidget(self.table, 1)

        self.selection_summary_label = QLabel()
        self.selection_summary_label.setObjectName("soundcloudCatalogSelectionSummaryLabel")
        root.addWidget(self.selection_summary_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        root.addWidget(self.button_box)

        self.filter_edit.textChanged.connect(self._filter_rows)
        self.table.cellClicked.connect(self._toggle_selection_cell)
        self.table.itemChanged.connect(self._handle_item_changed)
        self._populate()

    def selected_track_ids(self) -> tuple[int, ...]:
        selected: list[int] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None or item.checkState() != Qt.Checked:
                continue
            selected.append(int(item.data(Qt.UserRole)))
        return tuple(sorted(set(selected)))

    def _populate(self) -> None:
        self.table.blockSignals(True)
        try:
            self.table.setSortingEnabled(False)
            self.table.setRowCount(len(self._choices))
            selected = set(self._selected_track_ids)
            for row, choice in enumerate(self._choices):
                check_item = QTableWidgetItem("")
                check_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                check_item.setCheckState(
                    Qt.Checked if int(choice.track_id) in selected else Qt.Unchecked
                )
                check_item.setTextAlignment(Qt.AlignCenter)
                check_item.setData(Qt.UserRole, int(choice.track_id))
                self._sync_check_item_label(check_item)
                self.table.setItem(row, 0, check_item)
                values = [
                    choice.title,
                    choice.album,
                    choice.artist,
                    choice.isrc,
                    _format_duration(choice.duration_seconds),
                ]
                for offset, value in enumerate(values, start=1):
                    item = QTableWidgetItem(str(value))
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    item.setData(Qt.UserRole, int(choice.track_id))
                    self.table.setItem(row, offset, item)
        finally:
            self.table.setSortingEnabled(True)
            self.table.blockSignals(False)
        self._filter_rows()
        self._refresh_summary()

    def _filter_rows(self) -> None:
        text = self.filter_edit.text().strip().casefold()
        for row in range(self.table.rowCount()):
            haystack = " ".join(
                (
                    self.table.item(row, column).text()
                    if self.table.item(row, column) is not None
                    else ""
                )
                for column in range(1, self.table.columnCount())
            ).casefold()
            track_id_item = self.table.item(row, 0)
            track_id = str(track_id_item.data(Qt.UserRole)) if track_id_item is not None else ""
            self.table.setRowHidden(row, bool(text and text not in haystack + " " + track_id))

    def _toggle_selection_cell(self, row: int, column: int) -> None:
        if column != 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    def _handle_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            self._sync_check_item_label(item)
        self._refresh_summary()

    def _sync_check_item_label(self, item: QTableWidgetItem) -> None:
        label = "Yes" if item.checkState() == Qt.Checked else "No"
        if item.text() == label:
            return
        previous = self.table.blockSignals(True)
        try:
            item.setText(label)
            item.setToolTip(
                "Click this Publish cell to include or exclude the track from this run."
            )
        finally:
            self.table.blockSignals(previous)

    def _refresh_summary(self) -> None:
        count = len(self.selected_track_ids())
        self.selection_summary_label.setText(f"{count} track(s) checked for publishing.")


class SoundCloudExistingUploadSelectionDialog(QDialog):
    """Manual matcher for SoundCloud uploads that already exist online."""

    def __init__(
        self,
        *,
        choices: list[SoundCloudExistingUploadChoice],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("soundcloudExistingUploadSelectionDialog")
        self.setWindowTitle("Match Existing SoundCloud Upload")
        self.resize(980, 560)
        self._choices = list(choices)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Choose the existing SoundCloud upload that belongs to this catalog track. "
            "Nothing is updated online until you review the update preflight."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("soundcloudExistingUploadFilterEdit")
        self.filter_edit.setPlaceholderText("Filter by title, URL, genre, id, or URN")
        root.addWidget(self.filter_edit)

        self.table = QTableWidget(0, 5)
        self.table.setObjectName("soundcloudExistingUploadTable")
        self.table.setHorizontalHeaderLabels(
            ["Title", "SoundCloud URL", "Remote", "Genre", "Created"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        root.addWidget(self.table, 1)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        root.addWidget(self.button_box)

        self.filter_edit.textChanged.connect(self._filter_rows)
        self.table.cellDoubleClicked.connect(lambda *_args: self.accept())
        self._populate()

    def selected_upload(self) -> SoundCloudExistingUploadChoice | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        item = self.table.item(selected[0].row(), 0)
        if item is None:
            return None
        row_index = item.data(Qt.UserRole)
        if row_index is None:
            return None
        return self._choices[int(row_index)]

    def _populate(self) -> None:
        self.table.setRowCount(len(self._choices))
        for row, choice in enumerate(self._choices):
            remote = choice.remote_urn or (
                str(choice.remote_numeric_id) if choice.remote_numeric_id is not None else ""
            )
            values = [
                choice.title,
                choice.remote_url or "",
                remote,
                choice.genre,
                choice.created_at,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setData(Qt.UserRole, row)
                self.table.setItem(row, column, item)
        if self.table.rowCount():
            self.table.selectRow(0)

    def _filter_rows(self) -> None:
        text = self.filter_edit.text().strip().casefold()
        for row in range(self.table.rowCount()):
            haystack = " ".join(
                (
                    self.table.item(row, column).text()
                    if self.table.item(row, column) is not None
                    else ""
                )
                for column in range(self.table.columnCount())
            ).casefold()
            self.table.setRowHidden(row, bool(text and text not in haystack))


class SoundCloudMetadataComparisonDialog(QDialog):
    """Side-by-side review of local catalog metadata and current SoundCloud metadata."""

    def __init__(
        self,
        *,
        rows: list[SoundCloudMetadataComparisonRow],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("soundcloudMetadataComparisonDialog")
        self.setWindowTitle("Compare SoundCloud Metadata")
        self.resize(1040, 620)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Review what the catalog will send to SoundCloud. Rows marked Changed differ from "
            "the current remote metadata."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("soundcloudMetadataComparisonTable")
        self.table.setHorizontalHeaderLabels(
            ["Field", "Catalog value", "Current SoundCloud value", "State"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        root.addWidget(self.table, 1)

        self.status_label = QLabel()
        self.status_label.setObjectName("soundcloudMetadataComparisonStatusLabel")
        root.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._populate(rows)

    def _populate(self, rows: list[SoundCloudMetadataComparisonRow]) -> None:
        self.table.setRowCount(len(rows))
        changed_count = 0
        for row, comparison in enumerate(rows):
            state = comparison.state or ("Changed" if comparison.changed else "Same")
            if comparison.changed:
                changed_count += 1
            values = [
                comparison.field,
                comparison.catalog_value,
                comparison.remote_value,
                state,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(row, column, item)
        self.status_label.setText(f"{changed_count} changed field(s) found.")


class SoundCloudPublishDialog(QDialog):
    """Dry-run review and live execution control for SoundCloud publishing."""

    def __init__(
        self,
        *,
        track_ids: list[int] | tuple[int, ...],
        planner,
        publish_runner: Callable[[SoundCloudPublishPlanResult], object] | None = None,
        settings_opener: Callable[[], object] | None = None,
        album_track_resolver: Callable[[tuple[int, ...]], list[int]] | None = None,
        catalog_track_provider: Callable[[], list[SoundCloudCatalogTrackChoice]] | None = None,
        history_provider: Callable[[], list[SoundCloudPublishRunSummary]] | None = None,
        publication_linker: Callable[[int, str], object] | None = None,
        existing_upload_provider: Callable[[], list[SoundCloudExistingUploadChoice]] | None = None,
        metadata_comparison_provider: (
            Callable[[SoundCloudPublishPlanResult], list[SoundCloudMetadataComparisonRow]] | None
        ) = None,
        error_log_opener: Callable[[], object] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("soundcloudPublishDialog")
        self.setWindowTitle("Publish to SoundCloud")
        self.resize(1180, 780)
        self.track_ids = tuple(int(track_id) for track_id in track_ids)
        self.planner = planner
        self.publish_runner = publish_runner
        self.settings_opener = settings_opener
        self.album_track_resolver = album_track_resolver
        self.catalog_track_provider = catalog_track_provider
        self.history_provider = history_provider
        self.publication_linker = publication_linker
        self.existing_upload_provider = existing_upload_provider
        self.metadata_comparison_provider = metadata_comparison_provider
        self.error_log_opener = error_log_opener
        self.current_plan: SoundCloudPublishPlanResult | None = None
        self._cancel_requested = False

        root = QVBoxLayout(self)
        root.setSpacing(10)

        header_row = QHBoxLayout()
        header = QLabel("Review the SoundCloud preflight plan before starting live publishing.")
        header.setWordWrap(True)
        self.soundcloud_logo_label = QLabel()
        self.soundcloud_logo_label.setObjectName("soundcloudPublishLogoLabel")
        self.soundcloud_logo_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.soundcloud_logo_label.setMinimumSize(180, 44)
        self.soundcloud_logo_label.setToolTip("SoundCloud publishing")
        header_row.addWidget(header, 1)
        header_row.addWidget(self.soundcloud_logo_label, 0, Qt.AlignRight | Qt.AlignTop)
        root.addLayout(header_row)
        self._refresh_soundcloud_logo()

        options_group = QGroupBox("Per-run options")
        options_layout = QGridLayout(options_group)
        options_layout.setColumnStretch(1, 1)

        self.sharing_combo = QComboBox()
        self.sharing_combo.setObjectName("soundcloudSharingCombo")
        self.sharing_combo.addItem("Private", "private")
        self.sharing_combo.addItem("Public", "public")
        options_layout.addWidget(QLabel("Sharing"), 0, 0)
        options_layout.addWidget(self.sharing_combo, 0, 1)

        self.tags_edit = QLineEdit()
        self.tags_edit.setObjectName("soundcloudTagsEdit")
        self.tags_edit.setPlaceholderText("Optional tags for this run")
        options_layout.addWidget(QLabel("Tags"), 1, 0)
        options_layout.addWidget(self.tags_edit, 1, 1)

        self.description_edit = QTextEdit()
        self.description_edit.setObjectName("soundcloudDescriptionEdit")
        self.description_edit.setPlaceholderText("Optional SoundCloud description for this run")
        self.description_edit.setAcceptRichText(False)
        self.description_edit.setFixedHeight(76)
        options_layout.addWidget(QLabel("Description"), 2, 0)
        options_layout.addWidget(self.description_edit, 2, 1)

        self.purchase_url_edit = QLineEdit()
        self.purchase_url_edit.setObjectName("soundcloudPurchaseUrlEdit")
        self.purchase_url_edit.setPlaceholderText("Optional buy link")
        options_layout.addWidget(QLabel("Buy link"), 3, 0)
        options_layout.addWidget(self.purchase_url_edit, 3, 1)

        self.record_label_edit = QLineEdit()
        self.record_label_edit.setObjectName("soundcloudRecordLabelEdit")
        self.record_label_edit.setPlaceholderText("Prefilled from publisher when available")
        options_layout.addWidget(QLabel("Record label"), 4, 0)
        options_layout.addWidget(self.record_label_edit, 4, 1)

        self.contains_music_check = QCheckBox("Contains music")
        self.contains_music_check.setObjectName("soundcloudContainsMusicCheck")
        self.contains_music_check.setChecked(True)
        self.contains_explicit_check = QCheckBox("Contains explicit content")
        self.contains_explicit_check.setObjectName("soundcloudContainsExplicitCheck")
        self.contains_explicit_check.setChecked(False)
        options_layout.addWidget(self.contains_music_check, 5, 1)
        options_layout.addWidget(self.contains_explicit_check, 6, 1)

        self.commentable_check = QCheckBox("Allow comments")
        self.commentable_check.setObjectName("soundcloudCommentableCheck")
        self.commentable_check.setChecked(True)
        self.reveal_stats_check = QCheckBox("Reveal stats")
        self.reveal_stats_check.setObjectName("soundcloudRevealStatsCheck")
        self.reveal_stats_check.setChecked(True)
        self.reveal_comments_check = QCheckBox("Reveal comments")
        self.reveal_comments_check.setObjectName("soundcloudRevealCommentsCheck")
        self.reveal_comments_check.setChecked(True)
        options_layout.addWidget(self.commentable_check, 7, 1)
        options_layout.addWidget(self.reveal_stats_check, 8, 1)
        options_layout.addWidget(self.reveal_comments_check, 9, 1)

        safety_label = QLabel("Downloadable remains false and streamable remains true.")
        safety_label.setWordWrap(True)
        options_layout.addWidget(safety_label, 10, 1)
        root.addWidget(options_group)

        self.table = QTableWidget(0, 8)
        self.table.setObjectName("soundcloudPreflightTable")
        self.table.setHorizontalHeaderLabels(
            [
                "Track title",
                "Operation",
                "Metadata",
                "Audio / artwork",
                "Warnings",
                "Blocking errors",
                "Sharing",
                "Remote status",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        root.addWidget(self.table, 1)

        self.status_label = QLabel()
        self.status_label.setObjectName("soundcloudPublishStatusLabel")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.error_log_button = QPushButton("Publish error occurred. View latest error log")
        self.error_log_button.setObjectName("soundcloudViewLatestErrorLogButton")
        self.error_log_button.setVisible(False)
        root.addWidget(self.error_log_button)

        buttons = QHBoxLayout()
        self.album_button = QPushButton("Use album selection")
        self.album_button.setObjectName("soundcloudUseAlbumSelectionButton")
        self.catalog_button = QPushButton("Choose tracks...")
        self.catalog_button.setObjectName("soundcloudChooseTracksButton")
        self.plan_button = QPushButton("Refresh preflight")
        self.plan_button.setObjectName("soundcloudRefreshPreflightButton")
        self.settings_button = QPushButton("SoundCloud Settings...")
        self.settings_button.setObjectName("soundcloudSettingsShortcutButton")
        self.history_button = QPushButton("Publish history")
        self.history_button.setObjectName("soundcloudPublishHistoryButton")
        self.link_button = QPushButton("Link existing upload...")
        self.link_button.setObjectName("soundcloudLinkExistingUploadButton")
        self.browse_existing_button = QPushButton("Browse existing uploads...")
        self.browse_existing_button.setObjectName("soundcloudBrowseExistingUploadsButton")
        self.compare_button = QPushButton("Compare remote vs catalog...")
        self.compare_button.setObjectName("soundcloudCompareRemoteCatalogButton")
        self.update_button = QPushButton("Update published metadata")
        self.update_button.setObjectName("soundcloudUpdatePublishedMetadataButton")
        self.publish_button = QPushButton("Publish")
        self.publish_button.setObjectName("soundcloudPublishButton")
        self.cancel_button = QPushButton("Cancel publish")
        self.cancel_button.setObjectName("soundcloudCancelPublishButton")
        buttons.addWidget(self.album_button)
        buttons.addWidget(self.catalog_button)
        buttons.addWidget(self.plan_button)
        buttons.addWidget(self.settings_button)
        buttons.addWidget(self.history_button)
        buttons.addWidget(self.link_button)
        buttons.addWidget(self.browse_existing_button)
        buttons.addWidget(self.compare_button)
        buttons.addStretch(1)
        buttons.addWidget(self.update_button)
        buttons.addWidget(self.publish_button)
        buttons.addWidget(self.cancel_button)
        root.addLayout(buttons)

        self.plan_button.clicked.connect(self.refresh_plan)
        self.publish_button.clicked.connect(self.publish)
        self.cancel_button.clicked.connect(self.cancel_publish)
        self.settings_button.clicked.connect(self.open_settings)
        self.album_button.clicked.connect(self.use_album_selection)
        self.catalog_button.clicked.connect(self.open_catalog_track_selection)
        self.history_button.clicked.connect(self.open_history)
        self.link_button.clicked.connect(self.link_existing_upload)
        self.browse_existing_button.clicked.connect(self.browse_existing_uploads)
        self.compare_button.clicked.connect(self.compare_remote_metadata)
        self.update_button.clicked.connect(self.update_published_metadata)
        self.error_log_button.clicked.connect(self.open_error_log)
        self.history_button.setEnabled(self.history_provider is not None)
        self.album_button.setEnabled(self.album_track_resolver is not None and bool(self.track_ids))
        self.catalog_button.setEnabled(self.catalog_track_provider is not None)
        self.link_button.setEnabled(
            self.publication_linker is not None and len(self.track_ids) == 1
        )
        self.browse_existing_button.setEnabled(
            self.publication_linker is not None
            and self.existing_upload_provider is not None
            and len(self.track_ids) == 1
        )
        self.compare_button.setEnabled(False)
        self.update_button.setEnabled(False)

        self.refresh_plan()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.StyleChange,
        }:
            self._refresh_soundcloud_logo()

    def _refresh_soundcloud_logo(self) -> None:
        logo_path = _soundcloud_logo_path_for_palette(self.palette())
        pixmap = QPixmap(str(logo_path))
        if pixmap.isNull():
            self.soundcloud_logo_label.clear()
            self.soundcloud_logo_label.setVisible(False)
            return
        screen = self.screen() or QApplication.primaryScreen()
        device_ratio = max(
            1.0,
            float(self.devicePixelRatioF()),
            float(screen.devicePixelRatio()) if screen is not None else 1.0,
        )
        logical_width = 260
        logical_height = 64
        scaled = pixmap.scaled(
            int(logical_width * device_ratio),
            int(logical_height * device_ratio),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(device_ratio)
        self.soundcloud_logo_label.setVisible(True)
        self.soundcloud_logo_label.setMinimumSize(logical_width, logical_height)
        self.soundcloud_logo_label.setPixmap(scaled)

    def options(self) -> SoundCloudPublishOptions:
        tag_list = self.tags_edit.text().strip() or None
        return SoundCloudPublishOptions(
            sharing=str(self.sharing_combo.currentData() or "private"),
            tag_list=tag_list,
            description=self.description_edit.toPlainText().strip() or None,
            downloadable=False,
            streamable=True,
            commentable=self.commentable_check.isChecked(),
            reveal_stats=self.reveal_stats_check.isChecked(),
            reveal_comments=self.reveal_comments_check.isChecked(),
            purchase_url=self.purchase_url_edit.text().strip() or None,
            record_label=self.record_label_edit.text().strip() or None,
            contains_music=self.contains_music_check.isChecked(),
            contains_explicit=self.contains_explicit_check.isChecked(),
        )

    def refresh_plan(self) -> None:
        self.error_log_button.setVisible(False)
        if not self.track_ids:
            self.current_plan = SoundCloudPublishPlanResult(
                track_ids=(),
                items=(),
                options=self.options(),
                quota_snapshot=None,
            )
            self._populate_plan(self.current_plan)
            self.status_label.setText("No tracks selected. Choose tracks in the catalog first.")
            return
        self.current_plan = self.planner.plan_tracks(list(self.track_ids), self.options())
        self._prefill_record_label_from_plan(self.current_plan)
        if self.current_plan.options != self.options():
            self.current_plan = self.planner.plan_tracks(list(self.track_ids), self.options())
        self._populate_plan(self.current_plan)
        blocked = sum(
            1 for item in self.current_plan.items if item.status == SoundCloudPlanItemStatus.BLOCKED
        )
        warnings = sum(
            1 for item in self.current_plan.items if item.status == SoundCloudPlanItemStatus.WARN
        )
        if blocked:
            self.status_label.setText(f"Preflight found {blocked} blocking item(s).")
        elif self.current_plan.has_warning_items:
            self.status_label.setText(f"Preflight ready with {warnings} warning item(s).")
        else:
            self.status_label.setText("Preflight ready.")

    def _prefill_record_label_from_plan(self, plan: SoundCloudPublishPlanResult) -> None:
        if self.record_label_edit.text().strip():
            return
        labels = {
            str(item.metadata.label_name or "").strip()
            for item in plan.items
            if item.metadata is not None and str(item.metadata.label_name or "").strip()
        }
        if len(labels) != 1:
            return
        self.record_label_edit.setText(next(iter(labels)))

    def _populate_plan(self, plan: SoundCloudPublishPlanResult) -> None:
        self.table.setRowCount(len(plan.items))
        for row, item in enumerate(plan.items):
            warning_messages = [issue.message for issue in item.issues if not issue.is_blocking]
            blocking_messages = [issue.message for issue in item.issues if issue.is_blocking]
            metadata_ready = "Ready" if item.metadata is not None else "Missing"
            audio_ready = "Audio"
            if item.metadata is None or not item.metadata.asset_data:
                audio_ready = (
                    "No audio replacement" if item.action.value == "update" else "Missing audio"
                )
            artwork_ready = (
                "artwork" if item.metadata and item.metadata.artwork_data else "no artwork"
            )
            remote_status = item.remote_urn or (
                "Existing publication" if item.action.value == "update" else "New"
            )
            values = [
                item.title or f"Track {item.track_id}",
                item.action.value,
                metadata_ready,
                f"{audio_ready}; {artwork_ready}",
                "\n".join(warning_messages),
                "\n".join(blocking_messages),
                plan.options.sharing,
                remote_status,
            ]
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                if blocking_messages:
                    table_item.setData(Qt.UserRole, "blocked")
                elif warning_messages:
                    table_item.setData(Qt.UserRole, "warning")
                self.table.setItem(row, column, table_item)
        can_publish = bool(plan.items) and not plan.has_blocking_items
        can_update = can_publish and all(
            item.action == SoundCloudPlanAction.UPDATE for item in plan.items
        )
        has_update_items = any(item.action == SoundCloudPlanAction.UPDATE for item in plan.items)
        self.publish_button.setEnabled(can_publish)
        self.update_button.setEnabled(can_update and self.publish_runner is not None)
        self.link_button.setEnabled(
            self.publication_linker is not None and len(self.track_ids) == 1
        )
        self.browse_existing_button.setEnabled(
            self.publication_linker is not None
            and self.existing_upload_provider is not None
            and len(self.track_ids) == 1
        )
        self.compare_button.setEnabled(
            bool(plan.items)
            and has_update_items
            and not plan.has_blocking_items
            and self.metadata_comparison_provider is not None
        )

    def publish(self) -> None:
        self.error_log_button.setVisible(False)
        if self.current_plan is None or self.current_plan.options != self.options():
            self.refresh_plan()
        plan = self.current_plan
        if plan is None or not plan.items:
            self.status_label.setText("No SoundCloud publish plan is available.")
            return
        if plan.has_blocking_items:
            self.status_label.setText("Resolve blocking preflight errors before publishing.")
            return
        if self.publish_runner is None:
            self.status_label.setText("SoundCloud publish execution service is not configured.")
            return
        self._cancel_requested = False
        self.status_label.setText("SoundCloud publish submitted.")
        self.publish_runner(plan)

    def update_published_metadata(self) -> None:
        if self.current_plan is None or self.current_plan.options != self.options():
            self.refresh_plan()
        plan = self.current_plan
        if plan is None or not plan.items:
            self.status_label.setText("No SoundCloud update plan is available.")
            return
        if any(item.action != SoundCloudPlanAction.UPDATE for item in plan.items):
            self.status_label.setText(
                "Link selected tracks to existing SoundCloud uploads before using metadata update."
            )
            return
        self.publish()

    def link_existing_upload(self) -> None:
        self.error_log_button.setVisible(False)
        if self.publication_linker is None:
            self.status_label.setText("SoundCloud link workflow is not configured.")
            return
        if len(self.track_ids) != 1:
            self.status_label.setText("Select exactly one catalog track before linking an upload.")
            return
        remote_ref, accepted = QInputDialog.getText(
            self,
            "Link existing SoundCloud upload",
            "Paste the SoundCloud track URL, track id, or URN:",
        )
        if not accepted or not str(remote_ref or "").strip():
            return
        try:
            self.publication_linker(int(self.track_ids[0]), str(remote_ref).strip())
        except Exception as exc:
            self.status_label.setText(redact_text(str(exc)))
            return
        self.refresh_plan()
        self.status_label.setText("Linked existing SoundCloud upload. Review the update preflight.")

    def browse_existing_uploads(self) -> None:
        """Open a browsable SoundCloud upload matcher for the selected catalog track."""

        self.error_log_button.setVisible(False)
        if self.publication_linker is None or self.existing_upload_provider is None:
            self.status_label.setText("SoundCloud upload browsing is not available.")
            return
        if len(self.track_ids) != 1:
            self.status_label.setText("Choose exactly one catalog track before matching an upload.")
            return
        try:
            choices = list(self.existing_upload_provider())
        except Exception as exc:
            self.status_label.setText(redact_text(str(exc)))
            return
        if not choices:
            self.status_label.setText(
                "No existing SoundCloud uploads were returned for this account."
            )
            return
        dialog = SoundCloudExistingUploadSelectionDialog(choices=choices, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        selected = dialog.selected_upload()
        if selected is None:
            self.status_label.setText("Select one SoundCloud upload to link.")
            return
        remote_ref = selected.remote_url or selected.remote_urn
        if not remote_ref and selected.remote_numeric_id is not None:
            remote_ref = str(selected.remote_numeric_id)
        if not remote_ref:
            self.status_label.setText("Selected SoundCloud upload has no usable remote identifier.")
            return
        try:
            self.publication_linker(int(self.track_ids[0]), remote_ref)
        except Exception as exc:
            self.status_label.setText(redact_text(str(exc)))
            return
        self.refresh_plan()
        self.status_label.setText("Linked existing SoundCloud upload. Review the update preflight.")

    def compare_remote_metadata(self) -> None:
        """Show a side-by-side remote-vs-catalog metadata review before update."""

        self.error_log_button.setVisible(False)
        if self.metadata_comparison_provider is None:
            self.status_label.setText("SoundCloud metadata comparison is not available.")
            return
        plan = self.current_plan
        if plan is None or plan.options != self.options():
            self.refresh_plan()
            plan = self.current_plan
        if plan is None or not any(
            item.action == SoundCloudPlanAction.UPDATE for item in plan.items
        ):
            self.status_label.setText("No linked SoundCloud update items are available to compare.")
            return
        try:
            rows = list(self.metadata_comparison_provider(plan))
        except Exception as exc:
            self.status_label.setText(redact_text(str(exc)))
            return
        if not rows:
            self.status_label.setText("No comparable SoundCloud metadata fields were returned.")
            return
        SoundCloudMetadataComparisonDialog(rows=rows, parent=self).exec()

    def cancel_publish(self) -> None:
        self._cancel_requested = True
        self.error_log_button.setVisible(False)
        self.status_label.setText("Cancellation requested. In-flight item commits remain intact.")

    def apply_execution_result(self, result: SoundCloudPublishExecutionResult) -> None:
        self.error_log_button.setVisible(False)
        if result.status == SoundCloudExecutionStatus.CANCELLED:
            self.status_label.setText("SoundCloud publish cancelled.")
            return
        rich_metadata_warnings = [
            item
            for item in result.item_results
            if item.operation_message
            and "rich web-editor metadata was rejected" in item.operation_message
        ]
        if rich_metadata_warnings:
            self.status_label.setText(
                "SoundCloud publish finished with rich metadata warning: "
                f"{result.items_succeeded} succeeded, {len(rich_metadata_warnings)} "
                "item(s) need manual SoundCloud web-editor metadata."
            )
            return
        self.status_label.setText(
            "SoundCloud publish finished: "
            f"{result.items_succeeded} succeeded, {result.items_failed} failed, "
            f"{result.items_skipped} skipped."
        )

    def apply_execution_error(self, exc: object) -> None:
        message = str(getattr(exc, "message", "") or exc)
        del message
        self.status_label.setText("SoundCloud publish failed.")
        self.error_log_button.setVisible(True)
        self.error_log_button.setEnabled(self.error_log_opener is not None)

    def open_error_log(self) -> None:
        if self.error_log_opener is not None:
            self.error_log_opener()

    def open_settings(self) -> None:
        if self.settings_opener is not None:
            self.settings_opener()

    def open_history(self) -> None:
        if self.history_provider is None:
            return
        dialog = SoundCloudPublishHistoryDialog(runs=list(self.history_provider()), parent=self)
        dialog.exec()

    def open_catalog_track_selection(self) -> None:
        if self.catalog_track_provider is None:
            return
        dialog = SoundCloudCatalogTrackSelectionDialog(
            choices=list(self.catalog_track_provider()),
            selected_track_ids=self.track_ids,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self.track_ids = dialog.selected_track_ids()
        self.refresh_plan()

    def use_album_selection(self) -> None:
        if self.album_track_resolver is None:
            return
        resolved = self.album_track_resolver(self.track_ids)
        if resolved:
            self.track_ids = tuple(int(track_id) for track_id in resolved)
            self.refresh_plan()


__all__ = [
    "SoundCloudCatalogTrackChoice",
    "SoundCloudCatalogTrackSelectionDialog",
    "SoundCloudExistingUploadChoice",
    "SoundCloudExistingUploadSelectionDialog",
    "SoundCloudMetadataComparisonDialog",
    "SoundCloudMetadataComparisonRow",
    "NullSoundCloudConnectionActions",
    "SoundCloudPublishHistoryDialog",
    "SoundCloudConnectionActions",
    "SoundCloudPublishDialog",
    "SoundCloudPublishRunSummary",
    "SoundCloudSettingsPanel",
    "SoundCloudSettingsSnapshot",
]

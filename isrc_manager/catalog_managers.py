"""Live catalog manager and diagnostics cleanup panels."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.parties import party_authority_notifier
from isrc_manager.ui_common import (
    _apply_standard_widget_chrome,
    _compose_widget_stylesheet,
    _create_round_help_button,
    _create_scrollable_dialog_content,
)


class _CatalogManagerPaneBase(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app

    @property
    def catalog_service(self):
        return self.app.catalog_service

    @staticmethod
    def _configure_table(table: QTableWidget) -> None:
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        table.setMinimumHeight(420)

    @staticmethod
    def _make_info_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setMinimumHeight(44)
        return label

    @staticmethod
    def _prepare_button(button: QPushButton, *, width: int = 148) -> QPushButton:
        button.setMinimumWidth(width)
        button.setMinimumHeight(34)
        button.setAutoDefault(False)
        return button

    def _after_mutation(self) -> None:
        try:
            self.app.populate_all_comboboxes()
        except Exception:
            pass


class _CatalogArtistsPane(_CatalogManagerPaneBase):
    def __init__(self, app, parent=None):
        super().__init__(app, parent)

        self.scroll_area, self.scroll_content, root = _create_scrollable_dialog_content(
            self, page=self
        )
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        root.addWidget(
            self._make_info_label(
                "Stored artists can only be removed when they are not used as a main artist or additional artist."
            )
        )

        group = QGroupBox("Stored Artists")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(14, 18, 14, 14)
        group_layout.setSpacing(12)

        self.summary_label = QLabel()
        group_layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ["Artist", "Main Uses", "Additional Uses", "Total Uses", "Status", "Delete"]
        )
        self._configure_table(self.table)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        group_layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.refresh_btn = self._prepare_button(QPushButton("Refresh"))
        self.purge_btn = self._prepare_button(QPushButton("Purge All Unused"), width=172)
        self.delete_btn = self._prepare_button(QPushButton("Delete Selected"), width=160)
        buttons.addWidget(self.refresh_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.purge_btn)
        buttons.addWidget(self.delete_btn)
        group_layout.addLayout(buttons)

        root.addWidget(group, 1)

        self.refresh_btn.clicked.connect(self.reload)
        self.purge_btn.clicked.connect(self._purge_unused)
        self.delete_btn.clicked.connect(self._delete_selected)
        party_authority_notifier().changed.connect(self.reload)

        self.reload()

    def reload(self):
        if self.catalog_service is None:
            self.table.setRowCount(0)
            self.summary_label.setText("Open a profile to manage stored artists.")
            return
        artists = self.catalog_service.list_artists_with_usage()
        self.table.setRowCount(0)
        unused_count = 0
        for artist in artists:
            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(artist.name))
            for col, value in enumerate(
                (artist.main_uses, artist.extra_uses, artist.total_uses), start=1
            ):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)

            is_unused = int(artist.total_uses) == 0
            if is_unused:
                unused_count += 1
            status = QTableWidgetItem("Unused" if is_unused else "In Use")
            status.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, status)

            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox.setCheckState(Qt.Checked if is_unused else Qt.Unchecked)
            if not is_unused:
                checkbox.setFlags(Qt.NoItemFlags)
            checkbox.setData(Qt.UserRole, artist.artist_id)
            self.table.setItem(row, 5, checkbox)

        self.summary_label.setText(
            f"{len(artists)} stored artist(s). {unused_count} currently unused and safe to remove."
        )

    def _selected_unused_ids(self) -> list[int]:
        artist_ids = []
        for row in range(self.table.rowCount()):
            total_item = self.table.item(row, 3)
            checkbox = self.table.item(row, 5)
            if not total_item or not checkbox:
                continue
            try:
                total_uses = int(total_item.text())
            except Exception:
                total_uses = 1
            if total_uses == 0 and checkbox.checkState() == Qt.Checked:
                artist_ids.append(int(checkbox.data(Qt.UserRole)))
        return artist_ids

    def _delete_selected(self):
        artist_ids = self._selected_unused_ids()
        if not artist_ids:
            QMessageBox.information(self, "Nothing to Delete", "No unused artists are selected.")
            return
        if (
            QMessageBox.question(
                self,
                "Delete Artists",
                f"Delete {len(artist_ids)} unused artist(s)?",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return

        if hasattr(self.app, "_run_snapshot_history_action"):
            self.app._run_snapshot_history_action(
                action_label=f"Delete Unused Artists: {len(artist_ids)}",
                action_type="catalog.artists_delete",
                entity_type="Artist",
                entity_id="batch",
                payload={"artist_ids": artist_ids, "count": len(artist_ids)},
                mutation=lambda: self.catalog_service.delete_artists(artist_ids),
            )
        else:
            self.catalog_service.delete_artists(artist_ids)

        self.reload()
        self._after_mutation()

    def _purge_unused(self):
        if self.catalog_service is None:
            QMessageBox.warning(self, "Artists", "Open a profile first.")
            return
        artist_ids = [
            artist.artist_id
            for artist in self.catalog_service.list_artists_with_usage()
            if artist.total_uses == 0
        ]
        if not artist_ids:
            QMessageBox.information(self, "Nothing to Purge", "No unused artists were found.")
            return
        if (
            QMessageBox.question(
                self,
                "Purge Unused Artists",
                f"Purge all {len(artist_ids)} unused artist(s)?",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return

        if hasattr(self.app, "_run_snapshot_history_action"):
            self.app._run_snapshot_history_action(
                action_label=f"Purge Unused Artists: {len(artist_ids)}",
                action_type="catalog.artists_purge",
                entity_type="Artist",
                entity_id="batch",
                payload={"artist_ids": artist_ids, "count": len(artist_ids)},
                mutation=lambda: self.catalog_service.delete_artists(artist_ids),
            )
        else:
            self.catalog_service.delete_artists(artist_ids)

        self.reload()
        self._after_mutation()


class _CatalogAlbumsPane(_CatalogManagerPaneBase):
    def __init__(self, app, parent=None):
        super().__init__(app, parent)

        self.scroll_area, self.scroll_content, root = _create_scrollable_dialog_content(
            self, page=self
        )
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        root.addWidget(
            self._make_info_label(
                "Stored album names can only be removed when they are not linked to any tracks."
            )
        )

        group = QGroupBox("Stored Albums")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(14, 18, 14, 14)
        group_layout.setSpacing(12)

        self.summary_label = QLabel()
        group_layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Album Title", "Uses", "Status", "Delete"])
        self._configure_table(self.table)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        group_layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.refresh_btn = self._prepare_button(QPushButton("Refresh"))
        self.purge_btn = self._prepare_button(QPushButton("Purge All Unused"), width=172)
        self.delete_btn = self._prepare_button(QPushButton("Delete Selected"), width=160)
        buttons.addWidget(self.refresh_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.purge_btn)
        buttons.addWidget(self.delete_btn)
        group_layout.addLayout(buttons)

        root.addWidget(group, 1)

        self.refresh_btn.clicked.connect(self.reload)
        self.purge_btn.clicked.connect(self._purge_unused)
        self.delete_btn.clicked.connect(self._delete_selected)

        self.reload()

    def reload(self):
        if self.catalog_service is None:
            self.table.setRowCount(0)
            self.summary_label.setText("Open a profile to manage stored album titles.")
            return
        albums = self.catalog_service.list_albums_with_usage()
        self.table.setRowCount(0)
        unused_count = 0
        for album in albums:
            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(album.title))
            uses_item = QTableWidgetItem(str(album.uses))
            uses_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, uses_item)

            is_unused = int(album.uses) == 0
            if is_unused:
                unused_count += 1
            status = QTableWidgetItem("Unused" if is_unused else "In Use")
            status.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, status)

            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox.setCheckState(Qt.Checked if is_unused else Qt.Unchecked)
            if not is_unused:
                checkbox.setFlags(Qt.NoItemFlags)
            checkbox.setData(Qt.UserRole, album.album_id)
            self.table.setItem(row, 3, checkbox)

        self.summary_label.setText(
            f"{len(albums)} stored album title(s). {unused_count} currently unused and safe to remove."
        )

    def _selected_unused_ids(self) -> list[int]:
        album_ids = []
        for row in range(self.table.rowCount()):
            uses_item = self.table.item(row, 1)
            checkbox = self.table.item(row, 3)
            if not uses_item or not checkbox:
                continue
            try:
                uses = int(uses_item.text())
            except Exception:
                uses = 1
            if uses == 0 and checkbox.checkState() == Qt.Checked:
                album_ids.append(int(checkbox.data(Qt.UserRole)))
        return album_ids

    def _delete_selected(self):
        album_ids = self._selected_unused_ids()
        if not album_ids:
            QMessageBox.information(self, "Nothing to Delete", "No unused albums are selected.")
            return
        if (
            QMessageBox.question(
                self,
                "Delete Albums",
                f"Delete {len(album_ids)} unused album title(s)?",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return

        if hasattr(self.app, "_delete_unused_albums_in_background"):
            self.app._delete_unused_albums_in_background(
                album_ids,
                owner=self,
                title="Delete Albums",
                description="Deleting selected unused album titles and refreshing lookup values...",
                action_label=f"Delete Unused Albums: {len(album_ids)}",
                action_type="catalog.albums_delete",
                on_ui_ready=lambda: (
                    self.reload(),
                    self._after_mutation(),
                ),
            )
        else:
            self.catalog_service.delete_albums(album_ids)
            self.reload()
            self._after_mutation()

    def _purge_unused(self):
        if self.catalog_service is None:
            QMessageBox.warning(self, "Albums", "Open a profile first.")
            return
        album_ids = [
            album.album_id
            for album in self.catalog_service.list_albums_with_usage()
            if album.uses == 0
        ]
        if not album_ids:
            QMessageBox.information(self, "Nothing to Purge", "No unused albums were found.")
            return
        if (
            QMessageBox.question(
                self,
                "Purge Unused Albums",
                f"Purge all {len(album_ids)} unused album title(s)?",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return

        if hasattr(self.app, "_delete_unused_albums_in_background"):
            self.app._delete_unused_albums_in_background(
                album_ids,
                owner=self,
                title="Purge Unused Albums",
                description="Purging unused album titles and refreshing lookup values...",
                action_label=f"Purge Unused Albums: {len(album_ids)}",
                action_type="catalog.albums_purge",
                on_ui_ready=lambda: (
                    self.reload(),
                    self._after_mutation(),
                ),
            )
        else:
            self.catalog_service.delete_albums(album_ids)
            self.reload()
            self._after_mutation()


class DiagnosticsCatalogCleanupPanel(QWidget):
    TAB_ORDER = ("artists", "albums")

    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.setObjectName("diagnosticsCatalogCleanupPanel")
        self.setProperty("role", "workspaceCanvas")
        _apply_standard_widget_chrome(self, "diagnosticsCatalogCleanupPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        summary_label = QLabel(
            "Review and clean stored artist and album names that are no longer referenced by the current profile."
        )
        summary_label.setWordWrap(True)
        summary_label.setProperty("role", "supportingText")
        root.addWidget(summary_label)

        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.artists_tab = _CatalogArtistsPane(app, self)
        self.albums_tab = _CatalogAlbumsPane(app, self)
        self.tabs.addTab(self.artists_tab, "Artists")
        self.tabs.addTab(self.albums_tab, "Albums")
        root.addWidget(self.tabs, 1)

    def focus_tab(self, tab_name: str = "artists") -> None:
        try:
            index = self.TAB_ORDER.index(tab_name)
        except ValueError:
            index = 0
        self.tabs.setCurrentIndex(index)

    def refresh(self) -> None:
        self.artists_tab.reload()
        self.albums_tab.reload()


class CatalogManagersPanel(QWidget):
    TAB_ORDER = ("artists", "albums")

    def __init__(self, app, *, initial_tab: str = "artists", parent=None):
        super().__init__(parent or app)
        self.app = app
        self.setObjectName("catalogManagersPanel")
        _apply_standard_widget_chrome(self, "catalogManagersPanel")

        self.setStyleSheet(
            _compose_widget_stylesheet(
                self,
                """
                QWidget#catalogManagersPanel QLabel#catalogTitle {
                    font-size: 18px;
                    font-weight: 600;
                }
                QWidget#catalogManagersPanel QLabel#catalogSubtitle {
                    color: #5f6b76;
                }
                QWidget#catalogManagersPanel QGroupBox {
                    font-weight: 600;
                    margin-top: 10px;
                }
                QWidget#catalogManagersPanel QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 4px;
                }
                """,
            )
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        help_row = QHBoxLayout()
        help_row.addStretch(1)
        help_row.addWidget(_create_round_help_button(self, "catalog-managers"))
        root.addLayout(help_row)

        title_label = QLabel("Catalog Managers")
        title_label.setObjectName("catalogTitle")
        root.addWidget(title_label)

        subtitle_label = QLabel("Manage stored artists and album names here.")
        subtitle_label.setObjectName("catalogSubtitle")
        subtitle_label.setWordWrap(True)
        root.addWidget(subtitle_label)

        self.tabs = QTabWidget()
        self.artists_tab = _CatalogArtistsPane(app, self)
        self.albums_tab = _CatalogAlbumsPane(app, self)
        self.tabs.addTab(self.artists_tab, "Artists")
        self.tabs.addTab(self.albums_tab, "Albums")
        root.addWidget(self.tabs, 1)

        self.focus_tab(initial_tab)

    def focus_tab(self, tab_name: str = "artists") -> None:
        try:
            index = self.TAB_ORDER.index(tab_name)
        except ValueError:
            index = 0
        self.tabs.setCurrentIndex(index)

    def refresh(self) -> None:
        self.artists_tab.reload()
        self.albums_tab.reload()


__all__ = [
    "_CatalogManagerPaneBase",
    "_CatalogArtistsPane",
    "_CatalogAlbumsPane",
    "DiagnosticsCatalogCleanupPanel",
    "CatalogManagersPanel",
]

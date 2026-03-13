# ------------------------------------------------------------
# Created by M. van de Kleut
# 22-aug-2025
#
# License:
# This software is provided "as is", without warranty of any kind.
# Free to use, copy, and distribute for any purpose, provided that
# original credits are retained. Not for resale.
# ------------------------------------------------------------

import os
import sys
import re
import json
import time
import hashlib
import shutil
import sqlite3
import tempfile
import platform
import logging
import mimetypes
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import(QRegularExpression, Signal, QEvent,
    Qt, QDate, QPoint, QSettings, QStandardPaths, QByteArray, QUrl, QEvent, QTimer, QSortFilterProxyModel, )

from PySide6.QtGui import (QDesktopServices, QCursor, QAction,
    QIcon, QAction, QKeySequence, QImage, QPixmap, QStandardItemModel, QStandardItem
)
from PySide6.QtWidgets import ( QListView, QMenuBar, QListWidget, QListWidgetItem, 
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox,
    QCalendarWidget, QRadioButton, QMenuBar, QMenu, QInputDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QMainWindow, QSizePolicy, QComboBox, QCompleter, QListWidget,
    QListWidgetItem, QFileDialog, QToolBar, QFrame, QSpinBox, QScrollArea, QSlider, QAbstractItemView, QFormLayout, QTableView, QTabWidget
)

from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from isrc_manager.history import HistoryManager, SessionHistoryManager
from isrc_manager.history.dialogs import HistoryDialog
from isrc_manager.constants import (
    APP_NAME,
    DEFAULT_ICON_PATH,
    DEFAULT_WINDOW_TITLE,
    FIELD_TYPE_CHOICES,
)
from isrc_manager.domain.codes import (
    is_blank,
    is_valid_isrc_compact_or_iso,
    is_valid_iswc_any,
    normalize_isrc,
    normalize_iswc,
    to_compact_isrc,
    to_iso_isrc,
    to_iso_iswc,
    valid_upc_ean,
)
from isrc_manager.domain.timecode import hms_to_seconds, parse_hms_text, seconds_to_hms
from isrc_manager.paths import DATA_DIR
from isrc_manager.services import (
    CatalogAdminService,
    CatalogReadService,
    CustomFieldDefinitionService,
    CustomFieldValueService,
    DatabaseMaintenanceService,
    DatabaseSchemaService,
    DatabaseSessionService,
    XMLExportService,
    XMLImportService,
    LicenseService,
    ProfileKVService,
    ProfileStoreService,
    ProfileWorkflowService,
    SettingsReadService,
    SettingsMutationService,
    TrackCreatePayload,
    TrackSnapshot,
    TrackService,
    TrackUpdatePayload,
)
from isrc_manager.settings import enforce_single_instance, init_settings


# =============================================================================
# Custom Columns Dialog (with type + options)
# =============================================================================
class CustomColumnsDialog(QDialog):
    """
    Manage custom field definitions:
    - Add (name, type: text/dropdown/checkbox; options for dropdown)
    - Rename
    - Change type
    - Edit options (dropdown)
    - Remove
    """
    def __init__(self, fields, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Custom Columns")

        # fields: [{"id": int|None, "name": str, "field_type": "text|dropdown|checkbox|date", "options": str|None}]
        self.fields = [dict(f) for f in fields]

        layout = QVBoxLayout(self)

        self.listw = QListWidget()
        layout.addWidget(self.listw)

        row1 = QHBoxLayout()
        self.btn_add = QPushButton("Add…")
        self.btn_remove = QPushButton("Remove")
        self.btn_rename = QPushButton("Rename…")
        self.btn_type = QPushButton("Change Type…")
        self.btn_opts = QPushButton("Edit Options…")
        row1.addWidget(self.btn_add)
        row1.addWidget(self.btn_remove)
        row1.addWidget(self.btn_rename)
        row1.addWidget(self.btn_type)
        row1.addWidget(self.btn_opts)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        ok = QPushButton("OK")
        cancel = QPushButton("Cancel")
        row2.addWidget(ok)
        row2.addWidget(cancel)
        layout.addLayout(row2)

        self.btn_add.clicked.connect(self._add)
        self.btn_remove.clicked.connect(self._remove)
        self.btn_rename.clicked.connect(self._rename)
        self.btn_type.clicked.connect(self._change_type)
        self.btn_opts.clicked.connect(self._edit_options)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)

        self._refresh_list()

    # ----- helpers -----
    def _refresh_list(self):
        self.listw.clear()
        for i, f in enumerate(self.fields):
            label = f"{f['name']}  ·  {f.get('field_type','text')}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, i)  # store INDEX, not dict
            self.listw.addItem(item)

    def _current_index(self):
        it = self.listw.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _current_field(self):
        idx = self._current_index()
        return (self.fields[idx] if idx is not None else None), idx

    # ----- actions -----
    def _add(self):
        name, ok = QInputDialog.getText(self, "Add Column", "Column name:")
        name = (name or "").strip()
        if not (ok and name):
            return
        if any(f["name"] == name for f in self.fields):
            QMessageBox.warning(self, "Exists", f"Column '{name}' already exists.")
            return

        field_type, ok = QInputDialog.getItem(
            self, "Field Type", "Choose type:", FIELD_TYPE_CHOICES, 0, False
        )
        if not ok:
            return

        newf = {"id": None, "name": name, "field_type": field_type, "options": None}

        if field_type == "dropdown":
            opts, ok2 = QInputDialog.getMultiLineText(
                self, "Dropdown Options", "Enter options (one per line):"
            )
            if ok2:
                options = [o.strip() for o in (opts or "").splitlines() if o.strip()]
                newf["options"] = json.dumps(options) if options else json.dumps([])

        self.fields.append(newf)
        self._refresh_list()
        self.listw.setCurrentRow(self.listw.count() - 1)

    def _remove(self):
        idx = self._current_index()
        if idx is None:
            return

        cf = self.fields[idx]
        if QMessageBox.question(
            self, "Remove Column",
            f"Are you sure you want to remove '{cf['name']}'?",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        del self.fields[idx]
        self._refresh_list()
        if self.listw.count():
            self.listw.setCurrentRow(min(idx, self.listw.count() - 1))

    def _rename(self):
        cf, idx = self._current_field()
        if cf is None:
            return

        new_name, ok = QInputDialog.getText(self, "Rename Column", "New name:", text=cf["name"])
        new_name = (new_name or "").strip()
        if not (ok and new_name):
            return

        if any(i != idx and f["name"] == new_name for i, f in enumerate(self.fields)):
            QMessageBox.warning(self, "Exists", f"Column '{new_name}' already exists.")
            return

        self.fields[idx]["name"] = new_name
        self._refresh_list()
        self.listw.setCurrentRow(idx)

    def _change_type(self):
        cf, idx = self._current_field()
        if cf is None:
            return

        cur = FIELD_TYPE_CHOICES.index(cf.get("field_type", "text")) if cf.get("field_type", "text") in FIELD_TYPE_CHOICES else 0
        field_type, ok = QInputDialog.getItem(self, "Change Field Type", "Choose type:", FIELD_TYPE_CHOICES, cur, False
        )
        if not ok:
            return

        self.fields[idx]["field_type"] = field_type

        if field_type != "dropdown":
            self.fields[idx]["options"] = None
        else:
            if not self.fields[idx].get("options"):
                opts, ok2 = QInputDialog.getMultiLineText(
                    self, "Dropdown Options", "Enter options (one per line):"
                )
                if ok2:
                    options = [o.strip() for o in (opts or "").splitlines() if o.strip()]
                    self.fields[idx]["options"] = json.dumps(options) if options else json.dumps([])

        self._refresh_list()
        self.listw.setCurrentRow(idx)

    def _edit_options(self):
        cf, idx = self._current_field()
        if cf is None or cf.get("field_type") != "dropdown":
            return

        existing = json.loads(cf.get("options") or "[]")
        lines_default = "\n".join(existing)

        opts, ok = QInputDialog.getMultiLineText(
            self, "Dropdown Options", "Enter options (one per line):", text=lines_default
        )
        if not ok:
            return

        options = [o.strip() for o in (opts or "").splitlines() if o.strip()]
        self.fields[idx]["options"] = json.dumps(options)
        self._refresh_list()
        self.listw.setCurrentRow(idx)

    # ----- output -----
    def get_fields(self):
        return self.fields

# =============================================================================
# Floating Hint bubble with pixel values for rows and columns (draggable)
# =============================================================================
class DraggableLabel(QLabel):
    def __init__(self, parent=None, settings_key="hint_pos"):
        super().__init__(parent)
        self.settings_key = settings_key
        self._drag_pos = None
        self._history_before_settings = None
        self._user_moved = False  # flag to avoid auto-reposition after user moves
        self.setWindowFlags(Qt.SubWindow | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            app = self.window()
            if hasattr(app, "history_manager") and getattr(app, "history_manager", None) is not None:
                self._history_before_settings = app.history_manager.capture_setting_states([self.settings_key])
            else:
                self._history_before_settings = None
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = None
            self._user_moved = True
            app = self.window()
            s = getattr(app, "settings", None)
            if s is None:
                ini_path = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / "settings.ini"
                s = QSettings(str(ini_path), QSettings.IniFormat)
                s.setFallbacksEnabled(False)
            s.setValue(self.settings_key, self.pos())
            s.sync()
            if (
                self._history_before_settings is not None
                and hasattr(app, "_record_setting_bundle_from_entries")
                and getattr(app, "history_manager", None) is not None
            ):
                after_settings = app.history_manager.capture_setting_states([self.settings_key])
                label_name = (self.objectName() or self.settings_key).replace("_", " ").strip()
                app._record_setting_bundle_from_entries(
                    action_label=f"Move {label_name}",
                    before_entries=self._history_before_settings,
                    after_entries=after_settings,
                    entity_id=self.settings_key,
                )
            self._history_before_settings = None
            event.accept()


# =============================================================================
# Tiny Date Picker Widget
# =============================================================================
class DatePickerDialog(QDialog):
    """Simple calendar picker for custom 'date' fields."""
    def __init__(self, parent=None, initial_iso_date: str | None = None, title: str = "Pick a date"):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)

        self.calendar = QCalendarWidget()
        if initial_iso_date:
            qd = QDate.fromString(initial_iso_date, "yyyy-MM-dd")
            self.calendar.setSelectedDate(qd if qd.isValid() else QDate.currentDate())
        else:
            self.calendar.setSelectedDate(QDate.currentDate())
        lay.addWidget(self.calendar)

        btns = QHBoxLayout()
        self.btn_clear = QPushButton("Clear")
        self.btn_ok = QPushButton("OK")
        self.btn_cancel = QPushButton("Cancel")
        btns.addWidget(self.btn_clear)
        btns.addStretch(1)
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        lay.addLayout(btns)

        self._cleared = False
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

    def _on_clear(self):
        self._cleared = True
        self.accept()

    def selected_iso(self) -> str | None:
        """Return yyyy-MM-dd or None if cleared."""
        if self._cleared:
            return None
        return self.calendar.selectedDate().toString("yyyy-MM-dd")


# =============================================================================
# Subclas for natural sorting
# =============================================================================
class _SortItem(QTableWidgetItem):
    """Sorts by a hidden key (Qt.UserRole) when present; otherwise natural text."""
    def __lt__(self, other):
        # Keyed (numeric/date) compare first
        a = self.data(Qt.UserRole)
        b = other.data(Qt.UserRole) if isinstance(other, QTableWidgetItem) else None
        if a is not None and b is not None:
            return a < b

        # Fallback: natural text compare (no super().__lt__ to avoid recursion)
        ta = self.text()
        tb = other.text() if isinstance(other, QTableWidgetItem) else ""
        na = [int(s) if s.isdigit() else s.lower() for s in re.split(r'(\d+)', ta)]
        nb = [int(s) if s.isdigit() else s.lower() for s in re.split(r'(\d+)', tb)]
        return na < nb


# =============================================================================
# Padded Spinboxes for tracklength
# =============================================================================
class TwoDigitSpinBox(QSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAlignment(Qt.AlignRight)

    # Always render at least two digits (00–99). 100+ still shows "100".
    def textFromValue(self, v: int) -> str:
        try:
            return f"{int(v):02d}"
        except Exception:
            return str(v)

class _ManageArtistsDialog(QDialog):
    """Safely purge only unused artists (no refs in Tracks or TrackArtists)."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Manage stored artists")
        self.setModal(True)
        self.catalog_service = parent.catalog_service

        v = QVBoxLayout(self)
        v.addWidget(QLabel("Only artists with 0 references can be deleted."))

        self.tbl = QTableWidget(0, 5, self)
        self.tbl.setHorizontalHeaderLabels(["Artist", "Main uses", "Extra uses", "Total", "Delete?"])
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3, 4): hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(self.tbl)

        h = QHBoxLayout()
        btn_refresh = QPushButton("Refresh"); btn_purge = QPushButton("Purge all unused")
        btn_delete  = QPushButton("Delete selected"); btn_close = QPushButton("Close")
        h.addWidget(btn_refresh); h.addWidget(btn_purge); h.addWidget(btn_delete); h.addStretch(1); h.addWidget(btn_close)
        v.addLayout(h)

        btn_refresh.clicked.connect(self._load)
        btn_purge.clicked.connect(self._purge_unused)
        btn_delete.clicked.connect(self._delete_selected)
        btn_close.clicked.connect(self.accept)

        self._load()

    def _load(self):
        self.tbl.setRowCount(0)
        for artist in self.catalog_service.list_artists_with_usage():
            r = self.tbl.rowCount(); self.tbl.insertRow(r)

            self.tbl.setItem(r, 0, QTableWidgetItem(artist.name))
            it_main = QTableWidgetItem(str(artist.main_uses)); it_main.setTextAlignment(Qt.AlignCenter)
            it_extra = QTableWidgetItem(str(artist.extra_uses)); it_extra.setTextAlignment(Qt.AlignCenter)
            it_total = QTableWidgetItem(str(artist.total_uses));  it_total.setTextAlignment(Qt.AlignCenter)
            self.tbl.setItem(r, 1, it_main); self.tbl.setItem(r, 2, it_extra); self.tbl.setItem(r, 3, it_total)

            chk = QTableWidgetItem(); chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if artist.total_uses == 0 else Qt.Unchecked)
            if artist.total_uses > 0: chk.setFlags(Qt.NoItemFlags)
            chk.setData(Qt.UserRole, artist.artist_id)  # keep id
            self.tbl.setItem(r, 4, chk)

    def _selected_unused_ids(self):
        ids = []
        for r in range(self.tbl.rowCount()):
            total = int(self.tbl.item(r, 3).text())
            it = self.tbl.item(r, 4)
            if total == 0 and it and it.checkState() == Qt.Checked:
                ids.append(int(it.data(Qt.UserRole)))
        return ids

    def _delete_selected(self):
        ids = self._selected_unused_ids()
        if not ids:
            QMessageBox.information(self, "Nothing to delete", "No unused artists selected."); return
        if QMessageBox.question(self, "Confirm", f"Delete {len(ids)} unused artist(s)?") != QMessageBox.Yes:
            return
        app = self.parentWidget()
        if app is not None and hasattr(app, "_run_snapshot_history_action"):
            app._run_snapshot_history_action(
                action_label=f"Delete Unused Artists: {len(ids)}",
                action_type="catalog.artists_delete",
                entity_type="Artist",
                entity_id="batch",
                payload={"artist_ids": ids, "count": len(ids)},
                mutation=lambda: self.catalog_service.delete_artists(ids),
            )
        else:
            self.catalog_service.delete_artists(ids)
        self._load()

    def _purge_unused(self):
        to_del = [artist.artist_id for artist in self.catalog_service.list_artists_with_usage() if artist.total_uses == 0]
        if not to_del:
            QMessageBox.information(self, "Nothing to purge", "No unused artists found."); return
        if QMessageBox.question(self, "Confirm", f"Purge {len(to_del)} unused artist(s)?") != QMessageBox.Yes:
            return
        app = self.parentWidget()
        if app is not None and hasattr(app, "_run_snapshot_history_action"):
            app._run_snapshot_history_action(
                action_label=f"Purge Unused Artists: {len(to_del)}",
                action_type="catalog.artists_purge",
                entity_type="Artist",
                entity_id="batch",
                payload={"artist_ids": to_del, "count": len(to_del)},
                mutation=lambda: self.catalog_service.delete_artists(to_del),
            )
        else:
            self.catalog_service.delete_artists(to_del)
        self._load()


class _ManageAlbumsDialog(QDialog):
    """Safely purge only unused albums (no refs in Tracks.album_id)."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Manage stored album names")
        self.setModal(True)
        self.catalog_service = parent.catalog_service

        v = QVBoxLayout(self)
        v.addWidget(QLabel("Only albums with 0 references can be deleted."))

        self.tbl = QTableWidget(0, 3, self)
        self.tbl.setHorizontalHeaderLabels(["Album", "Uses", "Delete?"])
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(self.tbl)

        h = QHBoxLayout()
        btn_refresh = QPushButton("Refresh"); btn_purge = QPushButton("Purge all unused")
        btn_delete  = QPushButton("Delete selected"); btn_close = QPushButton("Close")
        h.addWidget(btn_refresh); h.addWidget(btn_purge); h.addWidget(btn_delete); h.addStretch(1); h.addWidget(btn_close)
        v.addLayout(h)

        btn_refresh.clicked.connect(self._load)
        btn_purge.clicked.connect(self._purge_unused)
        btn_delete.clicked.connect(self._delete_selected)
        btn_close.clicked.connect(self.accept)

        self._load()

    def _load(self):
        self.tbl.setRowCount(0)
        for album in self.catalog_service.list_albums_with_usage():
            r = self.tbl.rowCount(); self.tbl.insertRow(r)
            self.tbl.setItem(r, 0, QTableWidgetItem(album.title))
            it_uses = QTableWidgetItem(str(album.uses)); it_uses.setTextAlignment(Qt.AlignCenter)
            self.tbl.setItem(r, 1, it_uses)

            chk = QTableWidgetItem(); chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if album.uses == 0 else Qt.Unchecked)
            if album.uses > 0: chk.setFlags(Qt.NoItemFlags)
            chk.setData(Qt.UserRole, album.album_id)
            self.tbl.setItem(r, 2, chk)

    def _selected_unused_ids(self):
        ids = []
        for r in range(self.tbl.rowCount()):
            uses = int(self.tbl.item(r, 1).text())
            it = self.tbl.item(r, 2)
            if uses == 0 and it and it.checkState() == Qt.Checked:
                ids.append(int(it.data(Qt.UserRole)))
        return ids

    def _delete_selected(self):
        ids = self._selected_unused_ids()
        if not ids:
            QMessageBox.information(self, "Nothing to delete", "No unused albums selected."); return
        if QMessageBox.question(self, "Confirm", f"Delete {len(ids)} unused album(s)?") != QMessageBox.Yes:
            return
        app = self.parentWidget()
        if app is not None and hasattr(app, "_run_snapshot_history_action"):
            app._run_snapshot_history_action(
                action_label=f"Delete Unused Albums: {len(ids)}",
                action_type="catalog.albums_delete",
                entity_type="Album",
                entity_id="batch",
                payload={"album_ids": ids, "count": len(ids)},
                mutation=lambda: self.catalog_service.delete_albums(ids),
            )
        else:
            self.catalog_service.delete_albums(ids)
        self._load()

    def _purge_unused(self):
        to_del = [album.album_id for album in self.catalog_service.list_albums_with_usage() if album.uses == 0]
        if not to_del:
            QMessageBox.information(self, "Nothing to purge", "No unused albums found."); return
        if QMessageBox.question(self, "Confirm", f"Purge {len(to_del)} unused album(s)?") != QMessageBox.Yes:
            return
        app = self.parentWidget()
        if app is not None and hasattr(app, "_run_snapshot_history_action"):
            app._run_snapshot_history_action(
                action_label=f"Purge Unused Albums: {len(to_del)}",
                action_type="catalog.albums_purge",
                entity_type="Album",
                entity_id="batch",
                payload={"album_ids": to_del, "count": len(to_del)},
                mutation=lambda: self.catalog_service.delete_albums(to_del),
            )
        else:
            self.catalog_service.delete_albums(to_del)
        self._load()

# =============================================================================
# App (Relational schema; auto-ISO; custom field editors; auto-learn)
# =============================================================================
# ====== License Management: Helpers & Dialogs ======
class LicenseUploadDialog(QDialog):
    saved = Signal()

    def __init__(self, license_service, tracks, licensees, preselect_track_id=None, parent=None):
        super().__init__(parent)
        self.license_service = license_service
        self.setWindowTitle("Add License (PDF)")
        self.setModal(True)

        # --- Controls ---
        self.track_combo = QComboBox()
        for tid, title in tracks:
            self.track_combo.addItem(title, tid)
        if preselect_track_id:
            idx = self.track_combo.findData(preselect_track_id)
            if idx >= 0:
                self.track_combo.setCurrentIndex(idx)

        self.lic_combo = QComboBox()
        self.lic_combo.setEditable(True)
        for lid, name in licensees:
            self.lic_combo.addItem(name, lid)

        self.file_label = QLabel("No file chosen")
        self.btn_pick = QPushButton("Upload PDF…")
        self.btn_pick.clicked.connect(self._pick_pdf)

        self.btn_save = QPushButton("Save")
        self.btn_save.setEnabled(False)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save.clicked.connect(self._save)

        # --- Layout ---
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.addRow("Track", self.track_combo)
        form.addRow("Licensee", self.lic_combo)

        file_row = QHBoxLayout()
        file_row.addWidget(self.file_label, 1)
        file_row.addSpacing(12)
        file_row.addWidget(self.btn_pick, 0, Qt.AlignRight)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)
        main_layout.addLayout(form)
        main_layout.addLayout(file_row)
        main_layout.addStretch(1)  # push content up/left

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.btn_cancel)
        buttons.addSpacing(16)
        buttons.addWidget(self.btn_save)
        buttons.addStretch(1)
        main_layout.addLayout(buttons)

        self.resize(560, 240)
        self._picked_path = None

    def _pick_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select signed license (PDF)", "", "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            QMessageBox.warning(self, "Invalid", "Please select a .pdf file.")
            return
        self._picked_path = path
        self.file_label.setText(Path(path).name)
        self.btn_save.setEnabled(True)

    def _save(self):
        try:
            lic_text = self.lic_combo.currentText().strip()
            if not lic_text:
                QMessageBox.warning(self, "Missing", "Licensee is required.")
                return
            track_id = self.track_combo.currentData()
            if not self._picked_path:
                QMessageBox.warning(self, "Missing", "Please choose a PDF.")
                return

            app = self.parentWidget()
            mutation = lambda: self.license_service.add_license(
                track_id=track_id,
                licensee_name=lic_text,
                source_pdf_path=self._picked_path,
            )
            if app is not None and hasattr(app, "_run_snapshot_history_action"):
                app._run_snapshot_history_action(
                    action_label="Add License PDF",
                    action_type="license.add",
                    entity_type="License",
                    entity_id=track_id,
                    payload={"track_id": track_id, "licensee": lic_text},
                    mutation=mutation,
                )
            else:
                mutation()
            self.saved.emit()
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))


class LicensesBrowserDialog(QDialog):
    def __init__(self, license_service, track_filter_id=None, parent=None):
        super().__init__(parent)
        self.license_service = license_service
        self.setWindowTitle("Licenses")
        self.setModal(True)
        self.resize(900, 520)

        # --- model/proxy ---
        self.model = QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels(["Licensee", "Track", "Uploaded", "Filename", "_file", "_id"])
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)

        # --- views ---
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._ctx_menu)
        self.table.installEventFilter(self)

        self.list = QListView()
        self.list.setModel(self.proxy)
        self.list.setSelectionMode(QListView.SingleSelection)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._ctx_menu)
        self.list.installEventFilter(self)

        tabs = QTabWidget()
        tabs.addTab(self.table, "Table")
        tabs.addTab(self.list, "List")

        # --- filter ---
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Fuzzy filter…")
        self.filter_edit.textChanged.connect(self._apply_filter)

        # --- actions (single instances, reused in menu + context) ---
        self.act_preview = QAction("Preview (Space)", self)
        self.act_preview.triggered.connect(self._preview_pdf)

        self.act_download = QAction("Download PDF…", self)
        self.act_download.triggered.connect(self._download_pdf)

        self.act_edit = QAction("Edit…", self)
        self.act_edit.triggered.connect(self._edit_selected)

        self.act_delete = QAction("Delete Selected", self)
        self.act_delete.triggered.connect(self._delete_selected)

        # --- menubar ---
        mbar = QMenuBar(self)
        act_menu = mbar.addMenu("Actions")
        act_menu.addAction(self.act_preview)
        act_menu.addAction(self.act_download)
        act_menu.addSeparator()
        act_menu.addAction(self.act_edit)
        act_menu.addAction(self.act_delete)

        # --- layout ---
        v = QVBoxLayout(self)
        v.setMenuBar(mbar)
        v.addWidget(self.filter_edit)
        v.addWidget(tabs)

        # --- init/load ---
        self._track_filter_id = track_filter_id
        self._load_rows(self._track_filter_id)

        # after views exist, hook selection signals
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._update_action_states())
        self.list.selectionModel().selectionChanged.connect(lambda *_: self._update_action_states())
        self._update_action_states()

    # ---------- helpers ----------
    def _update_action_states(self):
        has = bool(self._selected_record())
        for a in (self.act_preview, self.act_download, self.act_edit, self.act_delete):
            a.setEnabled(has)

    def refresh_data(self):
        filt = self.filter_edit.text()
        self._load_rows(self._track_filter_id)
        self.filter_edit.setText(filt)
        self._update_action_states()

    def _apply_filter(self, text):
        pattern = ".*".join(map(re.escape, text.strip()))
        self.proxy.setFilterRegularExpression(QRegularExpression(pattern, QRegularExpression.CaseInsensitiveOption))

    def _load_rows(self, track_filter_id=None):
        if track_filter_id is None:
            track_filter_id = self._track_filter_id
        self.model.removeRows(0, self.model.rowCount())
        for row in self.license_service.list_rows(track_filter_id):
            items = [
                QStandardItem(row.licensee),
                QStandardItem(row.track_title),
                QStandardItem(row.uploaded_at),
                QStandardItem(row.filename),
                QStandardItem(row.file_path),
                QStandardItem(str(row.record_id)),
            ]
            for it in items:
                it.setEditable(False)
            self.model.appendRow(items)
        self.table.setColumnHidden(4, True)  # _file
        self.table.setColumnHidden(5, True)  # _id
        self.table.resizeColumnsToContents()

    def _selected_record(self):
        # prefer the view that has focus; fall back to table
        idx = self.table.currentIndex() if self.table.hasFocus() else self.list.currentIndex()
        if not idx.isValid():
            idx = self.table.currentIndex()
            if not idx.isValid():
                return None
        src = self.proxy.mapToSource(idx)
        row = src.row()
        file_path = self.model.item(row, 4).text()
        rec_id = int(self.model.item(row, 5).text())
        return rec_id, file_path

    def _ctx_menu(self, _pos):
        # reuse same actions as menu bar
        menu = QMenu(self)
        menu.addAction(self.act_preview)
        menu.addAction(self.act_download)
        menu.addSeparator()
        menu.addAction(self.act_edit)
        menu.addAction(self.act_delete)
        self._update_action_states()
        menu.exec(QCursor.pos())

    # ---------- actions ----------
    def _preview_pdf(self):
        rec = self._selected_record()
        if not rec:
            return
        _, path = rec

        # resolve relative -> absolute
        abs_path = self.license_service.resolve_path(path)
        if not abs_path.exists():
            QMessageBox.warning(self, "Missing file", "The file could not be found.")
            return

        try:
            from PySide6.QtPdfWidgets import QPdfView
            from PySide6.QtPdf import QPdfDocument

            dlg = QDialog(self)
            dlg.setWindowTitle(abs_path.name)
            dlg.resize(900, 640)

            doc = QPdfDocument(dlg)
            if doc.load(str(abs_path)) != QPdfDocument.NoError:
                raise RuntimeError("Failed to load PDF")

            view = QPdfView(dlg)
            view.setDocument(doc)
            view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            view.setPageMode(QPdfView.PageMode.SinglePage)

            layout = QVBoxLayout(dlg)
            layout.addWidget(view)

            from PySide6.QtCore import QTimer
            dlg.finished.connect(lambda _: QTimer.singleShot(200, doc.deleteLater))
            dlg.finished.connect(lambda _: QTimer.singleShot(250, view.deleteLater))

            dlg.exec()
        except Exception:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(abs_path)))

    def _download_pdf(self):
        rec = self._selected_record()
        if not rec:
            return
        _, path = rec
        abs_path = self.license_service.resolve_path(path)
        if not abs_path.exists():
            QMessageBox.warning(self, "Missing", "File not found.")
            return
        dst, _ = QFileDialog.getSaveFileName(self, "Save PDF as…", abs_path.name, "PDF (*.pdf)")
        if dst:
            app = self.parentWidget()
            mutation = lambda: shutil.copy2(str(abs_path), dst)
            if app is not None and hasattr(app, "_run_file_history_action"):
                app._run_file_history_action(
                    action_label=f"Download License PDF: {Path(dst).name}",
                    action_type="file.download_license_pdf",
                    target_path=dst,
                    mutation=mutation,
                    entity_type="License",
                    entity_id=str(dst),
                    payload={"source_path": str(abs_path), "target_path": str(dst)},
                )
            else:
                mutation()

    def _edit_selected(self):
        rec = self._selected_record()
        if not rec:
            return
        rec_id, path = rec
        record = self.license_service.fetch_license(rec_id)
        row = (record.track_id, record.licensee_id) if record else None
        if not row:
            return
        track_id, licensee_id = row
        d = QDialog(self)
        d.setWindowTitle("Edit License")
        track_lbl = QLabel("Track cannot be changed")
        lic_combo = QComboBox()
        lic_combo.setEditable(True)
        # load licensees
        for lid, name in self.license_service.list_licensee_choices():
            lic_combo.addItem(name, lid)
        idx = lic_combo.findData(licensee_id)
        if idx >= 0:
            lic_combo.setCurrentIndex(idx)
        file_lbl = QLabel(Path(path).name if path else "No file")
        pick_btn = QPushButton("Replace PDF…")
        new_path = {"p": None}

        def pick():
            p, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "PDF (*.pdf)")
            if p:
                new_path["p"] = p
                file_lbl.setText(Path(p).name)

        pick_btn.clicked.connect(pick)
        btn_ok = QPushButton("Save")
        btn_ok.clicked.connect(lambda: d.accept())
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(lambda: d.reject())
        f = QFormLayout(d)
        f.addRow(track_lbl)
        f.addRow("Licensee", lic_combo)
        h = QHBoxLayout()
        h.addWidget(file_lbl)
        h.addWidget(pick_btn)
        f.addRow("File", h)
        bb = QHBoxLayout()
        bb.addStretch()
        bb.addWidget(btn_cancel)
        bb.addWidget(btn_ok)
        f.addRow(bb)
        if d.exec() != QDialog.Accepted:
            return
        new_name = lic_combo.currentText().strip()
        if not new_name:
            new_name = lic_combo.currentText().strip() or ""
        try:
            app = self.parentWidget()
            mutation = lambda: self.license_service.update_license(
                record_id=rec_id,
                licensee_name=new_name,
                replacement_pdf_path=new_path["p"],
            )
            if app is not None and hasattr(app, "_run_snapshot_history_action"):
                app._run_snapshot_history_action(
                    action_label="Edit License",
                    action_type="license.update",
                    entity_type="License",
                    entity_id=rec_id,
                    payload={
                        "record_id": rec_id,
                        "licensee": new_name,
                        "replaced_pdf": bool(new_path["p"]),
                    },
                    mutation=mutation,
                )
            else:
                mutation()
            self.refresh_data()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _delete_selected(self):
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            QMessageBox.information(self, "Delete Licenses", "No records selected.")
            return

        ids, paths = [], []
        for proxy_idx in sel:
            src_idx = self.proxy.mapToSource(proxy_idx)
            row = src_idx.row()
            rec_id = int(self.model.item(row, 5).text())  # _id
            fpath = self.model.item(row, 4).text()        # _file
            ids.append(rec_id)
            paths.append(fpath)

        confirm = QMessageBox.question(
            self, "Delete Licenses",
            f"Delete {len(ids)} selected license(s)?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        delete_files = QMessageBox.question(
            self, "Delete Files",
            "Also delete the stored PDF files (if any)?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes

        try:
            app = self.parentWidget()
            mutation = lambda: self.license_service.delete_licenses(ids, delete_files=delete_files)
            if app is not None and hasattr(app, "_run_snapshot_history_action"):
                app._run_snapshot_history_action(
                    action_label=f"Delete Licenses: {len(ids)}",
                    action_type="license.delete",
                    entity_type="License",
                    entity_id="batch",
                    payload={"record_ids": ids, "count": len(ids), "delete_files": delete_files},
                    mutation=mutation,
                )
            else:
                mutation()
        except Exception as e:
            QMessageBox.critical(self, "Delete Licenses", str(e))
            return

        QMessageBox.information(self, "Done", f"Deleted {len(ids)} license(s).")
        self.refresh_data()

    def _reload_current(self):
        self.refresh_data()

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Space:
            self._preview_pdf()
            return True
        return super().eventFilter(obj, ev)


class LicenseeManagerDialog(QDialog):
    def __init__(self, catalog_service, parent=None):
        super().__init__(parent)
        self.catalog_service = catalog_service
        self.setWindowTitle("Manage Licensees")
        self.resize(420, 480)

        self.list = QListWidget()
        self._reload()

        btn_add = QPushButton("Add")
        btn_ren = QPushButton("Rename")
        btn_del = QPushButton("Delete")
        btn_add.clicked.connect(self._add)
        btn_ren.clicked.connect(self._rename)
        btn_del.clicked.connect(self._delete)

        h = QHBoxLayout()
        h.addWidget(btn_add)
        h.addWidget(btn_ren)
        h.addWidget(btn_del)
        v = QVBoxLayout(self)
        v.addWidget(self.list)
        v.addLayout(h)

    def _reload(self):
        self.list.clear()
        for licensee in self.catalog_service.list_licensees_with_usage():
            it = QListWidgetItem(f"{licensee.name} ({licensee.license_count})")
            it.setData(Qt.UserRole, licensee.licensee_id)
            it.setData(Qt.UserRole + 1, licensee.license_count)  # store count
            it.setToolTip(f"{licensee.name}\nLinked licenses: {licensee.license_count}")
            self.list.addItem(it)

    def _add(self):
        text, ok = QInputDialog.getText(self, "Add licensee", "Name:")
        if not ok or not text.strip():
            return
        try:
            app = self.parentWidget()
            mutation = lambda: self.catalog_service.ensure_licensee(text.strip())
            if app is not None and hasattr(app, "_run_snapshot_history_action"):
                app._run_snapshot_history_action(
                    action_label=f"Add Licensee: {text.strip()}",
                    action_type="licensee.add",
                    entity_type="Licensee",
                    entity_id=text.strip(),
                    payload={"name": text.strip()},
                    mutation=mutation,
                )
            else:
                mutation()
        except Exception:
            pass
        self._reload()

    def _rename(self):
        it = self.list.currentItem()
        if not it:
            return
        # strip " (n)" display suffix for default text
        old = it.text().rsplit(" (", 1)[0]
        text, ok = QInputDialog.getText(self, "Rename licensee", "Name:", text=old)
        if not ok or not text.strip():
            return
        try:
            app = self.parentWidget()
            mutation = lambda: self.catalog_service.rename_licensee(it.data(Qt.UserRole), text.strip())
            if app is not None and hasattr(app, "_run_snapshot_history_action"):
                app._run_snapshot_history_action(
                    action_label=f"Rename Licensee: {old}",
                    action_type="licensee.rename",
                    entity_type="Licensee",
                    entity_id=it.data(Qt.UserRole),
                    payload={"licensee_id": it.data(Qt.UserRole), "old_name": old, "new_name": text.strip()},
                    mutation=mutation,
                )
            else:
                mutation()
            self._reload()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _delete(self):
        it = self.list.currentItem()
        if not it:
            return
        lid = it.data(Qt.UserRole)
        n = it.data(Qt.UserRole + 1) or 0
        name = it.text().rsplit(" (", 1)[0]

        if n > 0:
            QMessageBox.warning(
                self,
                "In use",
                f"“{name}” has {n} linked license record(s).\n"
                "Remove or reassign those licenses before deleting this licensee.",
            )
            return

        if (
            QMessageBox.question(
                self,
                "Delete licensee",
                f"Delete “{name}”?\nThis cannot be undone.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return

        try:
            app = self.parentWidget()
            mutation = lambda: self.catalog_service.delete_licensee(lid)
            if app is not None and hasattr(app, "_run_snapshot_history_action"):
                app._run_snapshot_history_action(
                    action_label=f"Delete Licensee: {name}",
                    action_type="licensee.delete",
                    entity_type="Licensee",
                    entity_id=lid,
                    payload={"licensee_id": lid, "name": name},
                    mutation=mutation,
                )
            else:
                mutation()
            self._reload()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
        
class App(QMainWindow):
    BASE_HEADERS = [
        'ID', 'ISRC', 'Entry Date', 'Track Title', 'Artist Name',
        'Additional Artists', 'Album Title', 'Release Date', 'Track Length (hh:mm:ss)', 'ISWC', 'UPC', 'Genre'
    ]

    def __init__(self):
        super().__init__()

        # --- File system: per-user writable dirs (cross-platform) ---
        self.database_dir = DATA_DIR() / "Database"
        self.database_dir.mkdir(parents=True, exist_ok=True)

        self.exports_dir = DATA_DIR() / "exports"
        self.exports_dir.mkdir(parents=True, exist_ok=True)

        self.logs_dir = DATA_DIR() / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.logs_dir / "app.log"

        self.backups_dir = DATA_DIR() / "backups"
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir = DATA_DIR() / "history"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.database_session = DatabaseSessionService()
        self.profile_store = ProfileStoreService(self.database_dir)
        self.profile_workflows = ProfileWorkflowService(self.database_dir, self.profile_store)
        self.database_maintenance = DatabaseMaintenanceService(self.backups_dir)
        self.schema_service = None

        # default DB file (used if no previous DB is selected)
        DB_PATH = self.database_dir / "default.db"

        # --- Logging setup (rotating file handler) ---
        self.logger = logging.getLogger("ISRCManager")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            h = RotatingFileHandler(self.log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
            fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
            h.setFormatter(fmt)
            self.logger.addHandler(h)
            sh = logging.StreamHandler()
            sh.setLevel(logging.WARNING)
            sh.setFormatter(fmt)
            self.logger.addHandler(sh)

        self.logger.info("Application start")

        # --- Settings / identity ---
        ini_path = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / "settings.ini"
        self.settings = QSettings(str(ini_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)

        self.identity = self._load_identity()
        self._apply_identity()

        # --- Choose DB (last used or default) ---
        last_db = self.settings.value("db/last_path", "", str)
        if not last_db:
            last_db = str(DB_PATH)

        self.conn = None
        self.cursor = None
        self.history_manager = None
        self.session_history_manager = SessionHistoryManager(self.history_dir)
        self.history_dialog = None
        self._suspend_layout_history = False
        self.track_service = None
        self.settings_reads = None
        self.settings_mutations = None
        self.catalog_service = None
        self.catalog_reads = None
        self.license_service = None
        self.profile_kv = None
        self.custom_field_definitions = None
        self.custom_field_values = None
        self.xml_export_service = None
        self.xml_import_service = None
        self.open_database(last_db)

        # ----- Menus -----
        self.menu_bar = QMenuBar(self)
        self.setMenuBar(self.menu_bar)

        # Settings menu
        settings_menu = QMenu("Settings", self)
        self.menu_bar.addMenu(settings_menu)

        self.identity_action = QAction("Branding & Identity…", self)
        self.identity_action.triggered.connect(self.edit_identity)
        settings_menu.addAction(self.identity_action)

        self.prefix_action = QAction("Set ISRC Prefix", self)
        self.prefix_action.triggered.connect(self.set_isrc_prefix)
        settings_menu.addAction(self.prefix_action)

        # NEW: Artist Code (AA)
        self.artist_code_action = QAction("Set ISRC Artist Code (00–99)", self)
        self.artist_code_action.triggered.connect(self.set_artist_code)
        settings_menu.addAction(self.artist_code_action)

        self.sena_action = QAction("Set SENA Number", self)
        self.sena_action.triggered.connect(self.set_sena_number)
        settings_menu.addAction(self.sena_action)

        self.btw_action = QAction("Set BTW Number", self)
        self.btw_action.triggered.connect(self.set_btw_number)
        settings_menu.addAction(self.btw_action)

        self.buma_action = QAction("Set BUMA/STEMRA Relation number", self)
        self.buma_action.triggered.connect(self.set_buma_info)
        settings_menu.addAction(self.buma_action)

        self.ipi_action = QAction("Set IPI number", self)
        self.ipi_action.triggered.connect(self.set_ipi_info)
        settings_menu.addAction(self.ipi_action)

        # Export menu
        export_menu = QMenu("Export", self)
        self.menu_bar.addMenu(export_menu)

        xml_action = QAction("Export All to XML…", self)
        xml_action.triggered.connect(self.export_full_to_xml)
        export_menu.addAction(xml_action)

        xml_selected_action = QAction("Export Selected to XML…", self)
        xml_selected_action.triggered.connect(self.export_selected_to_xml)
        export_menu.addAction(xml_selected_action)

        import_action = QAction("Import from XML…", self)
        import_action.triggered.connect(self.import_from_xml)
        export_menu.addAction(import_action)

        # Database menu (Backups / Integrity)
        db_menu = QMenu("Database", self)
        self.menu_bar.addMenu(db_menu)

        self.backup_action = QAction("Backup Database", self)
        self.backup_action.triggered.connect(self.backup_database)
        db_menu.addAction(self.backup_action)

        self.verify_action = QAction("Verify Integrity", self)
        self.verify_action.triggered.connect(self.verify_integrity)
        db_menu.addAction(self.verify_action)

        self.restore_action = QAction("Restore from Backup…", self)
        self.restore_action.triggered.connect(self.restore_database)
        db_menu.addAction(self.restore_action)

        # View menu
        view_menu = QMenu("View", self)


        act_view_licenses = QAction("Licenses…", self)
        act_view_licenses.triggered.connect(lambda: self.open_licenses_browser(track_filter_id=None))
        view_menu.addAction(act_view_licenses)
        self.menu_bar.addMenu(view_menu)

        table_view_menu = QMenu("Table View", self)
        view_menu.addMenu(table_view_menu)

        self.col_width_action = QAction("Change Column Widths", self)
        self.col_width_action.setCheckable(True)
        self.col_width_action.toggled.connect(self._on_toggle_col_width)
        table_view_menu.addAction(self.col_width_action)

        self.row_height_action = QAction("Change Row Heights", self)
        self.row_height_action.setCheckable(True)
        self.row_height_action.toggled.connect(self._on_toggle_row_height)
        table_view_menu.addAction(self.row_height_action)

        # Allow Column Reordering
        self.act_reorder_columns = QAction("Allow Column Reordering", self)
        self.act_reorder_columns.setCheckable(True)
        try:
            movable = self.settings.value(f"{self._table_settings_prefix()}/columns_movable", False, bool)
        except Exception:
            movable = False
        self.act_reorder_columns.setChecked(bool(movable))
        self.act_reorder_columns.toggled.connect(self._toggle_columns_movable)
        table_view_menu.addAction(self.act_reorder_columns)

        self.add_data_action = QAction("Add Data Panel", self)
        self.add_data_action.setCheckable(True)
        self.add_data_action.toggled.connect(self._on_toggle_add_data)
        view_menu.addAction(self.add_data_action)

        self.view_info_action = QAction("Show App Info…", self)
        self.view_info_action.triggered.connect(self.show_settings_summary)
        view_menu.addAction(self.view_info_action)

        # Open logs folder (cross-platform)
        self.open_logs_action = QAction("Open Logs Folder…", self)
        def _open_logs():
            try:
                if sys.platform.startswith("win"):
                    os.startfile(self.logs_dir)
                elif sys.platform == "darwin":
                    os.system(f'open "{self.logs_dir}"')
                else:
                    os.system(f'xdg-open "{self.logs_dir}"')
            except Exception as e:
                QMessageBox.warning(self, "Open Logs", f"Could not open logs folder:\n{e}")
        self.open_logs_action.triggered.connect(_open_logs)
        view_menu.addAction(self.open_logs_action)


        fields_menu = QMenu("Fields", self)
        self.menu_bar.addMenu(fields_menu)
        manage_fields_action = QAction("Manage Custom Columns…", self)
        manage_fields_action.triggered.connect(self.manage_custom_columns)
        fields_menu.addAction(manage_fields_action)

        # --- Edit menu
        edit_menu = QMenu("Edit", self)
        self.menu_bar.addMenu(edit_menu)

        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.triggered.connect(self.history_undo)
        edit_menu.addAction(self.undo_action)

        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Y"), QKeySequence("Meta+Y")])
        self.redo_action.triggered.connect(self.history_redo)
        edit_menu.addAction(self.redo_action)

        edit_menu.addSeparator()

        act_manage_artists = QAction("Manage stored artists…", self)
        act_manage_artists.triggered.connect(self._manage_stored_artists)
        edit_menu.addAction(act_manage_artists)

        act_manage_albums = QAction("Manage stored album names…", self)


        act_manage_licensees = QAction("Manage licensee parties…", self)
        act_manage_licensees.triggered.connect(lambda: LicenseeManagerDialog(self.catalog_service, parent=self).exec())
        edit_menu.addAction(act_manage_licensees)
        act_manage_albums.triggered.connect(self._manage_stored_albums)
        edit_menu.addAction(act_manage_albums)

        history_menu = QMenu("History", self)
        self.menu_bar.addMenu(history_menu)
        history_menu.addAction(self.undo_action)
        history_menu.addAction(self.redo_action)
        history_menu.addSeparator()

        self.show_history_action = QAction("Show Undo History…", self)
        self.show_history_action.triggered.connect(self.open_history_dialog)
        history_menu.addAction(self.show_history_action)

        self.create_snapshot_action = QAction("Create Snapshot…", self)
        self.create_snapshot_action.triggered.connect(self.create_manual_snapshot)
        history_menu.addAction(self.create_snapshot_action)

        # ----- Profiles toolbar (quick DB switch)
        self.toolbar = QToolBar("Profiles", self)
        self.addToolBar(self.toolbar)
        self.toolbar.setMovable(True)
        self.toolbar.addWidget(QLabel("Profile: "))
        self.profile_combo = QComboBox()
        self.toolbar.addWidget(self.profile_combo)

        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        self._reload_profiles_list(select_path=last_db)

        btn_new = QPushButton("New…")
        btn_new.clicked.connect(self.create_new_profile)
        self.toolbar.addWidget(btn_new)

        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self.browse_profile)
        self.toolbar.addWidget(btn_browse)

        btn_reload = QPushButton("Reload List")
        btn_reload.clicked.connect(lambda: self._reload_profiles_list(select_path=self.current_db_path))
        self.toolbar.addWidget(btn_reload)

        btn_remove = QPushButton("Remove…")
        btn_remove.clicked.connect(self.remove_selected_profile)
        self.toolbar.addWidget(btn_remove)

        # ----- Central Layout -----
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        self.super_layout = QHBoxLayout(main_widget)
        self.super_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        # Left form
        self.left_panel = QVBoxLayout()
        self.left_panel.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.artist_label = QLabel("Artist")
        self.artist_field = QComboBox()
        self.artist_field.setEditable(True)

        self.additional_artist_label = QLabel("Additional Artist")
        self.additional_artist_field = QComboBox()
        self.additional_artist_field.setEditable(True)

        self.track_title_label = QLabel("Track Title")
        self.track_title_field = QLineEdit()

        self.album_title_label = QLabel("Album Title")
        self.album_title_field = QComboBox()
        self.album_title_field.setEditable(True)
        self.album_title_field.setCurrentText("")
        self.album_title_field.currentTextChanged.connect(self.autofill_album_metadata)

        self.release_date_label = QLabel("Release Date")
        self.release_date_field = QCalendarWidget()
        self.release_date_field.setSelectedDate(QDate.currentDate())
        if hasattr(self, "track_len_h"):
            track_seconds = hms_to_seconds(
                self.track_len_h.value(),
                self.track_len_m.value(),
                self.track_len_s.value(),
            )
        else:
            track_seconds = 0
        self.release_date_field.setFixedHeight(250)

        self.iswc_label = QLabel("ISWC")
        self.iswc_field = QLineEdit()

        self.upc_label = QLabel("UPC/EAN")
        self.upc_field = QComboBox()
        self.upc_field.setEditable(True)
        self.upc_field.setCurrentText("")

        self.genre_label = QLabel("Genre")
        self.genre_field = QComboBox()
        self.genre_field.setEditable(True)
        self.genre_field.setCurrentText("")

        # Top group
        for w in [self.artist_label, self.artist_field, self.additional_artist_label, self.additional_artist_field,
                self.track_title_label, self.track_title_field, self.album_title_label, self.album_title_field,
                self.release_date_label, self.release_date_field]:
            self.left_panel.addWidget(w)

        self.track_len_label = QLabel("Track Length (hh:mm:ss)")
        self.track_len_h = TwoDigitSpinBox(); self.track_len_h.setRange(0, 99);  self.track_len_h.setFixedWidth(60)
        self.track_len_m = TwoDigitSpinBox(); self.track_len_m.setRange(0, 59);  self.track_len_m.setFixedWidth(50)
        self.track_len_s = TwoDigitSpinBox(); self.track_len_s.setRange(0, 59);  self.track_len_s.setFixedWidth(50)

        _row_len = QHBoxLayout()
        _row_len.setContentsMargins(0, 0, 0, 0)
        _row_len.setSpacing(6)
        _row_len.addWidget(self.track_len_h); _row_len.addWidget(QLabel(":"))
        _row_len.addWidget(self.track_len_m); _row_len.addWidget(QLabel(":"))
        _row_len.addWidget(self.track_len_s)

        self.left_panel.addWidget(self.track_len_label)
        self.left_panel.addLayout(_row_len)

        # Bottom group
        for w in [self.iswc_label, self.iswc_field, self.upc_label, self.upc_field, self.genre_label, self.genre_field]:
            self.left_panel.addWidget(w)

        self.prev_release_toggle = QRadioButton("Previous Release")
        self.left_panel.addWidget(self.prev_release_toggle)

        btn_row = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.clear_form_fields)
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_entry)
        btn_row.addWidget(self.cancel_button)
        btn_row.addWidget(self.save_button)
        btn_row.addWidget(self.delete_button)
        self.left_panel.addLayout(btn_row)

        self.left_widget_container = QWidget()
        self.left_widget_container.setLayout(self.left_panel)
        # CHANGED: make left side scrollable (prevents overlap on small viewports)
        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setWidget(self.left_widget_container)
        self.left_scroll.setMinimumWidth(350)
        self.super_layout.addWidget(self.left_scroll)

        # Right panel (search + table)
        right_panel = QVBoxLayout()
        self.search_layout = QHBoxLayout()

        self.search_column_combo = QComboBox()
        self.search_column_combo.setFixedHeight(25)
        self.search_column_combo.setMinimumWidth(180)
        self.search_layout.addWidget(self.search_column_combo)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search...")
        self.search_field.setFixedSize(300, 25)

        self.search_button = QPushButton("Reset")
        self.search_button.setFixedSize(100, 25)

        # Count label (existing)
        self.count_label = QLabel("showing: 0 records")
        self.count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.count_label.setMinimumWidth(160)
        self.count_label.setStyleSheet("color: #666;")
        self.duration_label = QLabel("total: 00:00:00")
        self.duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.duration_label.setMinimumWidth(180)
        self.duration_label.setStyleSheet("color: #666;")

        # Wire up search actions
        self.search_field.textChanged.connect(self.apply_search_filter)
        self.search_column_combo.currentIndexChanged.connect(self.apply_search_filter)
        self.search_button.clicked.connect(self.reset_search)

        self.search_layout.addWidget(self.search_field)
        self.search_layout.addWidget(self.count_label, 1)
        self.search_layout.addWidget(self.duration_label)
        self.search_layout.addWidget(self.search_button)
        right_panel.addLayout(self.search_layout)

        self.table = QTableWidget()
        self._rebuild_table_headers()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)

        #patched: 24-aug-2025
        # Consistent width-only resize (default)
        self.table.setWordWrap(False)  # avoid multi-line height calculations by default

        # Prevent tiny rows when modes flip
        vh = self.table.verticalHeader()
        vh.setDefaultSectionSize(24)
        vh.setMinimumSectionSize(24)

        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionsMovable(bool(movable))
        self.table.installEventFilter(self)

        # -- Copy selection shortcuts
        act_copy = QAction("Copy", self)
        act_copy.setShortcut(QKeySequence.Copy)
        act_copy.triggered.connect(lambda: self._copy_selection_to_clipboard(False))
        self.addAction(act_copy)

        act_copy_hdrs = QAction("Copy with headers", self)
        # cross-platform: Win/Linux Ctrl, macOS Meta
        act_copy_hdrs.setShortcuts([QKeySequence("Shift+Ctrl+C"), QKeySequence("Shift+Meta+C")])
        act_copy_hdrs.triggered.connect(lambda: self._copy_selection_to_clipboard(True))
        self.addAction(act_copy_hdrs)

        # restore header state (order/widths) and watch for moves
        try:
            self._load_header_state()
        except Exception:
            pass
        self._bind_header_state_signals()

        # save header state on app exit
        try:
            if QApplication.instance() is not None:
                QApplication.instance().aboutToQuit.connect(
                    lambda: self._save_header_state(record_history=False)
                )
        except Exception:
            pass

        try:
            self._rebuild_search_column_choices()
        except AttributeError:
            pass

        # Hint labels for live resize feedback
        self.col_hint_label = None
        self.row_hint_label = None

        # Route double-clicks (base columns -> EditDialog; custom columns -> inline editor)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)

        # Context menu
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)

        right_panel.addWidget(self.table)
        self.super_layout.addLayout(right_panel, 1)

        # Default table-only
        self.add_data_action.setChecked(False)
        self._on_toggle_add_data(False)

        self.refresh_table()
        self.populate_all_comboboxes()
        self.resize(1280, 800)
        self._refresh_history_actions()


    def closeEvent(self, e):
        self.settings.sync()
        self.logger.info("Settings synced to disk")
        super().closeEvent(e)

    def _init_services(self):
        self.schema_service = (
            DatabaseSchemaService(
                self.conn,
                logger=self.logger,
                audit_callback=self._audit,
                audit_commit=self._audit_commit,
            )
            if self.conn is not None
            else None
        )
        self.history_manager = (
            HistoryManager(self.conn, self.settings, self.current_db_path, self.history_dir, DATA_DIR())
            if self.conn is not None and getattr(self, "current_db_path", None)
            else None
        )
        self.track_service = TrackService(self.conn) if self.conn is not None else None
        self.settings_reads = SettingsReadService(self.conn) if self.conn is not None else None
        self.settings_mutations = (
            SettingsMutationService(self.conn, self.settings) if self.conn is not None else None
        )
        self.catalog_service = CatalogAdminService(self.conn) if self.conn is not None else None
        self.catalog_reads = CatalogReadService(self.conn) if self.conn is not None else None
        self.license_service = LicenseService(self.conn, DATA_DIR()) if self.conn is not None else None
        self.profile_kv = ProfileKVService(self.conn) if self.conn is not None else None
        self.custom_field_definitions = (
            CustomFieldDefinitionService(self.conn) if self.conn is not None else None
        )
        self.custom_field_values = (
            CustomFieldValueService(self.conn, self.custom_field_definitions) if self.conn is not None else None
        )
        self.xml_export_service = XMLExportService(self.conn) if self.conn is not None else None
        self.xml_import_service = (
            XMLImportService(self.conn, self.track_service, self.custom_field_definitions)
            if self.conn is not None
            else None
        )


    # -------------------------------------------------------------------------
    # Identity & Profiles
    # -------------------------------------------------------------------------
    def _load_identity(self):
        title = self.settings.value("identity/window_title", DEFAULT_WINDOW_TITLE, str)
        icon  = self.settings.value("identity/icon_path", DEFAULT_ICON_PATH, str)
        return {"window_title": title, "icon_path": icon}

    def _apply_identity(self):
        self.setWindowTitle(self.identity.get("window_title") or DEFAULT_WINDOW_TITLE)
        icon_path = self.identity.get("icon_path") or ""
        if icon_path and Path(icon_path).exists():
            try:
                self.setWindowIcon(QIcon(icon_path))
            except Exception:
                pass

    def edit_identity(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Branding & Identity")
        lay = QVBoxLayout(dlg)

        # Title
        lay.addWidget(QLabel("Window Title"))
        title_edit = QLineEdit(self.identity.get("window_title") or DEFAULT_WINDOW_TITLE)
        lay.addWidget(title_edit)

        # Icon
        lay.addWidget(QLabel("Application Icon (optional)"))
        icon_row = QHBoxLayout()
        icon_edit = QLineEdit(self.identity.get("icon_path") or "")
        icon_browse = QPushButton("Browse…")
        def pick_icon():
            path, _ = QFileDialog.getOpenFileName(self, "Choose Icon", "", "Images (*.ico *.png *.jpg *.jpeg *.bmp)")
            if path:
                icon_edit.setText(path)
        icon_browse.clicked.connect(pick_icon)
        icon_row.addWidget(icon_edit)
        icon_row.addWidget(icon_browse)
        lay.addLayout(icon_row)

        btns = QHBoxLayout()
        save_btn = QPushButton("Save")
        close_btn = QPushButton("Close")
        btns.addWidget(save_btn)
        btns.addWidget(close_btn)
        lay.addLayout(btns)

        def do_save():
            before_identity = dict(self.identity)
            self.identity = self.settings_mutations.set_identity(
                window_title=title_edit.text().strip() or DEFAULT_WINDOW_TITLE,
                icon_path=icon_edit.text().strip(),
            )
            self.logger.info("Settings synced to disk")
            self._apply_identity()
            self.logger.info("Branding & identity updated")
            self._audit("SETTINGS", "Identity", ref_id="QSettings", details=f"title={self.identity['window_title']}")
            self._audit_commit()
            self.history_manager.record_setting_change(
                key="identity",
                label="Update Branding & Identity",
                before_value=before_identity,
                after_value=self.identity,
            )
            self._refresh_history_actions()
            QMessageBox.information(self, "Saved", "Branding and identity updated.")
        save_btn.clicked.connect(do_save)
        close_btn.clicked.connect(dlg.accept)
        dlg.exec()

    # --- Artist Code (AA) ---
    def _migrate_artist_code_from_qsettings_if_needed(self):
        if self.profile_kv.get("isrc_artist_code") is None:
            legacy = self.settings.value("isrc/artist_code", None)
            code = str(legacy) if legacy is not None else ""
            if not re.fullmatch(r"\d{2}", code):
                code = "00"
            self.profile_kv.set("isrc_artist_code", code)
            self.logger.info("Migrated ISRC artist code from QSettings into profile DB")


    def load_artist_code(self) -> str:
        code = self.profile_kv.get("isrc_artist_code", None)
        if not (isinstance(code, str) and re.fullmatch(r"\d{2}", (code or ""))):
            code = "00"
            self.profile_kv.set("isrc_artist_code", code)
            self.logger.info("Normalized invalid/empty ISRC artist code to '00'")
        return code


    def set_artist_code(self, val: str | None = None):
        # If no value provided or empty, open dialog prefilled with current code
        if not val:
            current = self.load_artist_code()
            text, ok = QInputDialog.getText(
                self, "Set ISRC Artist Code", "Enter 2 digits (00–99):", text=current
            )
            if not ok:
                return
            val = (text or "").strip()
        else:
            val = (val or "").strip()

        if len(val) != 2 or not val.isdigit():
            QMessageBox.warning(self, "Invalid artist code", "Artist code must be two digits (00–99).")
            return

        before_value = self.load_artist_code()
        self.settings_mutations.set_artist_code(val)
        self.logger.info(f"ISRC artist code set to '{val}' (profile DB)")
        self.history_manager.record_setting_change(
            key="artist_code",
            label=f"Set ISRC Artist Code: {val}",
            before_value=before_value,
            after_value=val,
        )
        self._refresh_history_actions()
        if hasattr(self, "artist_edit"):
            self.artist_edit.setText(val)


    def _reload_profiles_list(self, select_path: str | None = None):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        current_path = getattr(self, "current_db_path", None)
        for choice in self.profile_workflows.list_profile_choices(current_db_path=current_path):
            self.profile_combo.addItem(choice.label, choice.path)
        if select_path:
            idx = self.profile_combo.findData(select_path)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)


    def _on_profile_changed(self, idx: int):
        if idx < 0:
            return
        path = self.profile_combo.itemData(idx)
        if not path or path == self.current_db_path:
            return
        if QMessageBox.question(
            self, "Switch Profile",
            f"Switch to database:\n{path}?",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        previous_path = self.current_db_path
        self._activate_profile(path)
        self.logger.info(f"Switched profile to: {path}")
        self._audit("PROFILE", "Database", ref_id=path, details="switch_profile")
        self._audit_commit()
        self.session_history_manager.record_profile_switch(
            from_path=previous_path,
            to_path=path,
            action_type="profile.switch",
        )
        self._refresh_history_actions()

    def create_new_profile(self):
        name, ok = QInputDialog.getText(self, "New Profile", "Database file name (no path, e.g., mylabel.db):")
        if not ok or not name.strip():
            return
        previous_path = self.current_db_path
        try:
            new_path = str(self.profile_workflows.build_new_profile_path(name))
        except FileExistsError:
            QMessageBox.warning(self, "Exists", "A database with this name already exists.")
            return
        self._activate_profile(new_path)
        self.logger.info(f"Created new profile DB: {new_path}")
        self._audit("PROFILE", "Database", ref_id=new_path, details="create_new_profile")
        self._audit_commit()
        self.session_history_manager.record_profile_create(
            created_path=new_path,
            previous_path=previous_path,
        )
        self._refresh_history_actions()
        QMessageBox.information(self, "Profile Created", f"Database created:\n{new_path}")

    def browse_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Database", str(self.database_dir), "SQLite DB (*.db);;All Files (*)")
        if not path:
            return
        previous_path = self.current_db_path
        self._activate_profile(path)
        self.logger.info(f"Opened external profile DB via browse: {path}")
        self._audit("PROFILE", "Database", ref_id=path, details="browse_profile")
        self._audit_commit()
        self.session_history_manager.record_profile_switch(
            from_path=previous_path,
            to_path=path,
            action_type="profile.browse",
            label=f"Browse Profile: {Path(path).name}",
        )
        self._refresh_history_actions()

    def remove_selected_profile(self):
        idx = self.profile_combo.currentIndex()
        if idx < 0:
            return
        path = self.profile_combo.itemData(idx)
        if not path:
            return

        if QMessageBox.question(
            self, "Remove Profile",
            f"Delete this database file from disk?\n\n{path}\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        deleting_current = (getattr(self, "current_db_path", None) == path)
        current_path = self.current_db_path
        removed_snapshot_path = None

        try:
            removed_snapshot_path = self.session_history_manager.capture_profile_snapshot(
                path,
                kind="profile_remove",
            )
            if deleting_current:
                self._close_database_connection()

            result = self.profile_workflows.delete_profile(path, getattr(self, "current_db_path", None))

            self._reload_profiles_list(select_path=None)

            if result.deleting_current and result.fallback_path:
                self.open_database(result.fallback_path)
                self._reload_profiles_list(select_path=result.fallback_path)

            self.refresh_table_preserve_view()
            self.populate_all_comboboxes()
            self.logger.warning(f"Removed profile DB from disk: {path}")
            self._audit("PROFILE", "Database", ref_id=path, details="remove_profile")
            self._audit_commit()
            self.session_history_manager.record_profile_remove(
                deleted_path=path,
                current_path=current_path,
                fallback_path=result.fallback_path,
                deleting_current=result.deleting_current,
                snapshot_path=removed_snapshot_path,
            )
            self._refresh_history_actions()
            QMessageBox.information(self, "Profile Removed", f"Deleted:\n{path}")
        except Exception as e:
            if hasattr(self, "conn") and self.conn:
                self.conn.rollback()
            self.logger.exception(f"Remove profile failed: {e}")
            QMessageBox.critical(self, "Remove Error", f"Could not delete the database:\n{e}")


    def _manage_stored_artists(self):
        dlg = _ManageArtistsDialog(self)
        dlg.exec()
        self.populate_all_comboboxes()

    def _manage_stored_albums(self):
        dlg = _ManageAlbumsDialog(self)
        dlg.exec()
        self.populate_all_comboboxes()

    def _close_database_connection(self):
        self.database_session.close(self.conn)
        self.conn = None
        self.cursor = None
        self.schema_service = None
        self.history_manager = None
        self.profile_kv = None
        self.settings_reads = None

    # -------------------------------------------------------------------------
    # DB: open/init helpers + MIGRATIONS
    # -------------------------------------------------------------------------
    def open_database(self, path: str):
        """Open (or create) the SQLite DB at path; initialize schema if needed."""
        self._close_database_connection()
        session = self.database_session.open(path)
        self.conn = session.conn
        self.cursor = session.cursor
        self.current_db_path = path
        self._init_services()

        self._migrate_artist_code_from_qsettings_if_needed()

        current_code = self.load_artist_code()

        self.logger.info(f"Profile ISRC artist code active: '{current_code}'")

        self.database_session.remember_last_path(self.settings, path)
        self.logger.info("Settings synced to disk")

        # Create base tables/indices if missing
        self.init_db()

        # Run schema migrations and then refresh caches that depend on schema
        try:
            self.migrate_schema()
        except Exception as e:
            self.logger.exception(f"Schema migration failed: {e}")
            QMessageBox.critical(self, "Migration Error", f"Database migration failed:\n{e}")
            # keep going; DB might still be usable

        self.active_custom_fields = self.load_active_custom_fields()

        # now it's safe to write AuditLog
        self.logger.info(f"Opened database: {path}")
        self._audit("PROFILE", "Database", ref_id=path, details="open_database()")
        self._audit_commit()
        self._refresh_history_actions()

    def init_db(self):
        self.schema_service.init_db()

    def _get_db_version(self) -> int:
        return self.schema_service.get_db_version()

    def migrate_schema(self):
        self.schema_service.migrate_schema()


    # --- Audit helpers ---
    def _audit(self, action: str, entity: str, ref_id: str | int | None = None, details: str | None = None, user: str | None = None):
        """Append an entry to AuditLog and write to file logger."""
        try:
            self.cursor.execute(
                "INSERT INTO AuditLog (user, action, entity, ref_id, details) VALUES (?, ?, ?, ?, ?)",
                (user, action, entity, str(ref_id) if ref_id is not None else None, details)
            )
        except Exception as e:
            self.logger.exception(f"Failed to write AuditLog: {e}")

    def _audit_commit(self):
        try:
            self.conn.commit()
        except Exception as e:
            self.logger.exception(f"Audit commit error: {e}")

    def _refresh_history_actions(self):
        if not hasattr(self, "undo_action"):
            return

        undo_source, undo_entry = self._get_best_history_candidate("undo")
        redo_source, redo_entry = self._get_best_history_candidate("redo")
        undo_label = undo_entry.label if undo_entry is not None else None
        redo_label = redo_entry.label if redo_entry is not None else None

        self.undo_action.setText(f"Undo {undo_label}" if undo_label else "Undo")
        self.undo_action.setEnabled(bool(undo_label))

        self.redo_action.setText(f"Redo {redo_label}" if redo_label else "Redo")
        self.redo_action.setEnabled(bool(redo_label))

        if self.history_dialog is not None and self.history_dialog.isVisible():
            self.history_dialog.refresh_data()

    def _refresh_after_history_change(self):
        self.identity = self._load_identity()
        self._apply_identity()
        self.active_custom_fields = self.load_active_custom_fields()
        self._rebuild_table_headers()
        try:
            self._load_header_state()
        except Exception:
            pass
        self._apply_saved_hint_positions()
        self.populate_all_comboboxes()
        self.refresh_table_preserve_view()
        self._refresh_history_actions()

    def _apply_saved_hint_positions(self):
        for attr_name, settings_key in (
            ("col_hint_label", "display/col_hint_pos"),
            ("row_hint_label", "display/row_hint_pos"),
        ):
            label = getattr(self, attr_name, None)
            if label is None:
                continue
            pos = self.settings.value(settings_key, type=QPoint)
            if pos:
                label.move(pos)

    def _on_header_layout_changed(self, *_args):
        if getattr(self, "_suspend_layout_history", False):
            return
        self._save_header_state()

    def _bind_header_state_signals(self):
        header = self.table.horizontalHeader()
        for signal in (header.sectionMoved, header.sectionResized):
            try:
                signal.disconnect(self._on_header_layout_changed)
            except (TypeError, RuntimeError):
                pass
        header.sectionMoved.connect(self._on_header_layout_changed)
        header.sectionResized.connect(self._on_header_layout_changed)

    def _record_setting_bundle_from_entries(
        self,
        *,
        action_label: str,
        before_entries: list[dict],
        after_entries: list[dict],
        entity_id: str | None = None,
    ):
        if self.history_manager is None or before_entries == after_entries:
            return
        self.history_manager.record_setting_bundle_change(
            label=action_label,
            before_entries=before_entries,
            after_entries=after_entries,
            entity_id=entity_id,
        )
        self._refresh_history_actions()

    def _run_setting_bundle_history_action(
        self,
        *,
        action_label: str,
        setting_keys: list[str],
        mutation,
        entity_id: str | None = None,
    ):
        if self.history_manager is None:
            return mutation()
        before_entries = self.history_manager.capture_setting_states(setting_keys)
        try:
            result = mutation()
        except Exception:
            try:
                self.history_manager.apply_setting_entries(before_entries)
            except Exception as restore_error:
                self.logger.exception(f"Settings rollback failed for {action_label}: {restore_error}")
            raise
        after_entries = self.history_manager.capture_setting_states(setting_keys)
        self._record_setting_bundle_from_entries(
            action_label=action_label,
            before_entries=before_entries,
            after_entries=after_entries,
            entity_id=entity_id,
        )
        return result

    def _run_file_history_action(
        self,
        *,
        action_label,
        action_type: str,
        target_path: str | Path,
        mutation,
        companion_suffixes: tuple[str, ...] = (),
        entity_type: str | None = "File",
        entity_id: str | None = None,
        payload=None,
    ):
        if self.history_manager is None:
            return mutation()
        before_state = self.history_manager.capture_file_state(
            target_path,
            companion_suffixes=companion_suffixes,
        )
        try:
            result = mutation()
        except Exception:
            try:
                self.history_manager.restore_file_state(target_path, before_state)
            except Exception as restore_error:
                self.logger.exception(f"File rollback failed for {action_type}: {restore_error}")
            raise
        after_state = self.history_manager.capture_file_state(
            target_path,
            companion_suffixes=companion_suffixes,
        )
        if before_state != after_state:
            final_label = action_label(result) if callable(action_label) else action_label
            final_payload = payload(result) if callable(payload) else (payload or {})
            self.history_manager.record_file_write_action(
                label=final_label,
                action_type=action_type,
                target_path=target_path,
                before_state=before_state,
                after_state=after_state,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=final_payload,
            )
            self._refresh_history_actions()
        return result

    def _table_setting_keys(self, *, include_columns_movable: bool = False) -> list[str]:
        prefix = self._table_settings_prefix()
        keys = [
            f"{prefix}/header_state",
            f"{prefix}/header_labels",
            f"{prefix}/header_labels_json",
        ]
        if include_columns_movable:
            keys.append(f"{prefix}/columns_movable")
        return keys

    def _activate_profile(self, path: str, *, save_current_header: bool = True):
        if save_current_header:
            try:
                self._save_header_state(record_history=False)
            except Exception:
                pass

        self.open_database(path)

        try:
            self.active_custom_fields = self.load_active_custom_fields()
            self._rebuild_table_headers()
            self._load_header_state()
        except Exception:
            pass

        self._reload_profiles_list(select_path=path)
        self.refresh_table_preserve_view()
        self.populate_all_comboboxes()
        self._refresh_history_actions()

    @staticmethod
    def _history_time_key(entry):
        if entry is None or not entry.created_at:
            return datetime.min
        try:
            return datetime.fromisoformat(entry.created_at)
        except ValueError:
            return datetime.min

    def _get_best_history_candidate(self, direction: str):
        candidates = []

        if direction == "undo":
            if self.history_manager is not None and self.history_manager.can_undo():
                candidates.append(("profile", self.history_manager.get_current_entry()))
            if self.session_history_manager.can_undo():
                candidates.append(("session", self.session_history_manager.get_current_entry()))
        else:
            if self.history_manager is not None:
                redo_entry = self.history_manager.get_default_redo_entry()
                if redo_entry is not None:
                    candidates.append(("profile", redo_entry))
            redo_entry = self.session_history_manager.get_default_redo_entry()
            if redo_entry is not None:
                candidates.append(("session", redo_entry))

        if not candidates:
            return None, None
        return max(candidates, key=lambda item: (self._history_time_key(item[1]), item[1].entry_id))

    def _session_history_open_profile(self, path: str):
        self._activate_profile(path)

    def _session_history_reload_profiles(self, select_path: str | None = None):
        chosen_path = select_path or getattr(self, "current_db_path", None)
        self._reload_profiles_list(select_path=chosen_path)
        if self.conn is not None:
            self.refresh_table_preserve_view()
            self.populate_all_comboboxes()
        self._refresh_history_actions()

    def _session_history_delete_profile(self, path: str):
        profile_path = str(Path(path))
        if getattr(self, "current_db_path", None) == profile_path and self.conn is not None:
            self._close_database_connection()
        self.profile_workflows.profile_store.delete_profile(profile_path)

    def _run_snapshot_history_action(
        self,
        *,
        action_label: str,
        action_type: str,
        mutation,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        payload: dict | None = None,
        before_kind: str | None = None,
        before_label: str | None = None,
        after_kind: str | None = None,
        after_label: str | None = None,
    ):
        if self.history_manager is None:
            return mutation()

        safe_kind = action_type.replace(".", "_")
        before_snapshot = self.history_manager.capture_snapshot(
            kind=before_kind or f"pre_{safe_kind}",
            label=before_label or f"Before {action_label}",
        )
        try:
            result = mutation()
        except Exception:
            try:
                self.history_manager.restore_snapshot(before_snapshot.snapshot_id)
            except Exception as restore_error:
                self.logger.exception(f"Snapshot rollback failed for {action_type}: {restore_error}")
            try:
                self.history_manager.delete_snapshot(before_snapshot.snapshot_id)
            except Exception:
                pass
            raise

        try:
            after_snapshot = self.history_manager.capture_snapshot(
                kind=after_kind or f"post_{safe_kind}",
                label=after_label or f"After {action_label}",
            )
            self.history_manager.record_snapshot_action(
                label=action_label,
                action_type=action_type,
                entity_type=entity_type,
                entity_id=str(entity_id) if entity_id is not None else None,
                payload=payload or {},
                snapshot_before_id=before_snapshot.snapshot_id,
                snapshot_after_id=after_snapshot.snapshot_id,
            )
            self._refresh_history_actions()
        except Exception as e:
            self.logger.exception(f"History recording failed for {action_type}: {e}")
        return result

    def open_history_dialog(self):
        self.history_dialog = HistoryDialog(self, parent=self)
        self.history_dialog.exec()

    def history_undo(self):
        source, _ = self._get_best_history_candidate("undo")
        if source is None:
            return
        try:
            if source == "session":
                entry = self.session_history_manager.undo(self)
                if entry is not None:
                    self._refresh_history_actions()
                    if self.history_dialog is not None and self.history_dialog.isVisible():
                        self.history_dialog.refresh_data()
            else:
                entry = self.history_manager.undo()
                if entry is not None:
                    self._refresh_after_history_change()
        except Exception as e:
            self.logger.exception(f"Undo failed: {e}")
            QMessageBox.critical(self, "Undo Error", f"Could not undo the last action:\n{e}")

    def history_redo(self):
        source, _ = self._get_best_history_candidate("redo")
        if source is None:
            return
        try:
            if source == "session":
                entry = self.session_history_manager.redo(self)
                if entry is not None:
                    self._refresh_history_actions()
                    if self.history_dialog is not None and self.history_dialog.isVisible():
                        self.history_dialog.refresh_data()
            else:
                entry = self.history_manager.redo()
                if entry is not None:
                    self._refresh_after_history_change()
        except Exception as e:
            self.logger.exception(f"Redo failed: {e}")
            QMessageBox.critical(self, "Redo Error", f"Could not redo the action:\n{e}")

    def create_manual_snapshot(self):
        if self.history_manager is None:
            return
        label, ok = QInputDialog.getText(self, "Create Snapshot", "Snapshot label (optional):")
        if not ok:
            return
        try:
            snapshot = self.history_manager.create_manual_snapshot(label.strip() or None)
            self.logger.info(f"Created snapshot {snapshot.snapshot_id}: {snapshot.label}")
            QMessageBox.information(self, "Snapshot Created", f"Snapshot saved:\n{snapshot.label}")
            self._refresh_history_actions()
            if self.history_dialog is not None and self.history_dialog.isVisible():
                self.history_dialog.refresh_data()
        except Exception as e:
            self.logger.exception(f"Create snapshot failed: {e}")
            QMessageBox.critical(self, "Snapshot Error", f"Could not create snapshot:\n{e}")

    def delete_snapshot_from_history(self, snapshot_id: int):
        if self.history_manager is None:
            return
        self.history_manager.delete_snapshot_as_action(snapshot_id)
        self._refresh_history_actions()
        if self.history_dialog is not None and self.history_dialog.isVisible():
            self.history_dialog.refresh_data()

    def restore_snapshot_from_history(self, snapshot_id: int):
        if self.history_manager is None:
            return
        if QMessageBox.question(
            self,
            "Restore Snapshot",
            "Restore this snapshot into the current profile?\n\nThe current state can be undone afterward.",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            self.history_manager.restore_snapshot_as_action(snapshot_id)
            self._refresh_after_history_change()
        except Exception as e:
            self.logger.exception(f"Restore snapshot failed: {e}")
            QMessageBox.critical(self, "Restore Snapshot", f"Could not restore the snapshot:\n{e}")

    def _collect_catalog_cleanup_targets(
        self,
        *,
        artist_name: str,
        additional_artists: list[str],
        album_title: str | None,
    ) -> tuple[list[str], list[str]]:
        artist_names = {
            (artist_name or "").strip(),
            *[(name or "").strip() for name in additional_artists],
        }
        new_artists = sorted(
            {
                name
                for name in artist_names
                if name and not self.track_service.artist_exists(name, cursor=self.cursor)
            }
        )
        clean_album = (album_title or "").strip()
        new_albums = []
        if clean_album and not self.track_service.album_exists(clean_album, cursor=self.cursor):
            new_albums.append(clean_album)
        return new_artists, new_albums

    # --- NEW: Variant helpers (repurposed as Artist Code AA) ---
    def load_isrc_prefix(self):
        return self.settings_reads.load_isrc_prefix()

    def load_active_custom_fields(self):
        return self.custom_field_definitions.list_active_fields()

    # =============================================================================
    # UI helpers
    # =============================================================================

    def _make_item(self, col_idx, text, *, custom_def=None):
            it = _SortItem("" if text is None else str(text))
            t = it.text()
            key = None
            header = self.table.horizontalHeaderItem(col_idx).text()

            if header == "ID":
                try:
                    key = int(t)
                except:
                    pass
            elif header in ("Entry Date", "Release Date"):
                if t:  # stored as yyyy-MM-dd → yyyymmdd int
                    key = int(t.replace("-", ""))
            elif custom_def and custom_def.get("field_type") == "date":
                if t:
                    key = int(t.replace("-", ""))
            elif custom_def and custom_def.get("field_type") == "checkbox":
                key = 1 if t.lower() in ("1","true","yes","y","checked") else 0
            elif header == "Track Length (hh:mm:ss)":
                key = parse_hms_text(t)
            else:
                # numeric-looking strings sort numerically
                try:
                    key = float(t) if "." in t else int(t)
                except:
                    pass

            if key is not None:
                it.setData(Qt.UserRole, key)
            return it


    def _rebuild_table_headers(self):
        headers = self.BASE_HEADERS + [f["name"] for f in self.active_custom_fields]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self._rebuild_search_column_choices()

    def populate_all_comboboxes(self):
        artists = [r[0] for r in self.cursor.execute(
            "SELECT DISTINCT name FROM Artists WHERE name IS NOT NULL AND name != '' ORDER BY name"
        ).fetchall()]
        self._populate_combobox(self.artist_field, artists)
        self._populate_combobox(self.additional_artist_field, artists, allow_empty=True)

        albums = [r[0] for r in self.cursor.execute(
            "SELECT DISTINCT title FROM Albums WHERE title IS NOT NULL AND title != '' ORDER BY title"
        ).fetchall()]
        self._populate_combobox(self.album_title_field, albums, allow_empty=True)

        upcs = [r[0] for r in self.cursor.execute(
            "SELECT DISTINCT upc FROM Tracks WHERE upc IS NOT NULL AND upc != '' ORDER BY upc"
        ).fetchall()]
        self._populate_combobox(self.upc_field, upcs, allow_empty=True)

        genres = [r[0] for r in self.cursor.execute(
            "SELECT DISTINCT genre FROM Tracks WHERE genre IS NOT NULL AND genre != '' ORDER BY genre"
        ).fetchall()]
        self._populate_combobox(self.genre_field, genres, allow_empty=True)

    @staticmethod
    def _populate_combobox(combo: QComboBox, items, allow_empty=False):
        combo.clear()
        if allow_empty:
            combo.addItem("")
        combo.addItems(items)
        comp = QCompleter(items)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        combo.setCompleter(comp)

    def clear_form_fields(self):
        self.artist_field.setCurrentText("")
        self.additional_artist_field.setCurrentText("")
        self.track_title_field.clear()
        self.album_title_field.setCurrentText("")
        self.release_date_field.setSelectedDate(QDate.currentDate())
        self.iswc_field.clear()
        self.upc_field.setCurrentText("")
        self.genre_field.setCurrentText("")
        self.prev_release_toggle.setChecked(False)

    # =============================================================================
    # Search / table refresh (with view preservation)
    # =============================================================================
    def _rebuild_search_column_choices(self):
        cur_data = self.search_column_combo.currentData() if self.search_column_combo.count() else -1
        self.search_column_combo.blockSignals(True)
        self.search_column_combo.clear()
        self.search_column_combo.addItem("All columns", -1)

        headers = self.BASE_HEADERS + [f["name"] for f in self.active_custom_fields]
        for idx, name in enumerate(headers):
            self.search_column_combo.addItem(name, idx)

        restore = self.search_column_combo.findData(cur_data)
        self.search_column_combo.setCurrentIndex(restore if restore != -1 else 0)
        self.search_column_combo.blockSignals(False)

    def apply_search_filter(self):
        text = self.search_field.text().lower()
        col_sel = self.search_column_combo.currentData()  # -1 = all
        for row  in range(self.table.rowCount()):
            if col_sel == -1:
                match = any(
                    self.table.item(row, c) and text in self.table.item(row, c).text().lower()
                    for c in range(self.table.columnCount())
                )
            else:
                it = self.table.item(row, int(col_sel))
                match = bool(it and text in it.text().lower())
            self.table.setRowHidden(row, not match)
        self._update_count_label()

        self._update_duration_label()
    # =============================================================================
    # Header label helpers for robust persistence (rev09)
    # =============================================================================
    def _header_labels(self):
        m = self.table.model()
        return [str(m.headerData(c, Qt.Horizontal, Qt.DisplayRole) or "") for c in range(m.columnCount())]

    def _labels_with_occurrence(self, labels):
        seen = {}
        out = []
        for lbl in labels:
            n = seen.get(lbl, 0)
            out.append((lbl, n))
            seen[lbl] = n + 1
        return out


    def reset_search(self):
        self.search_field.clear()
        idx = self.search_column_combo.findData(-1)  # “All columns”
        self.search_column_combo.setCurrentIndex(idx if idx != -1 else 0)
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row, False)
        self.refresh_table()
        self._update_count_label()
        self._update_duration_label()


    def refresh_table(self):
        # Ensure custom fields and headers are ready
        if not hasattr(self, "active_custom_fields") or self.active_custom_fields is None:
            self.active_custom_fields = self.load_active_custom_fields()
            self._rebuild_table_headers()

        previous_suspend_state = self._suspend_layout_history
        self._suspend_layout_history = True
        try:
            _prev_sort_enabled = self.table.isSortingEnabled()
            if _prev_sort_enabled:
                self.table.setSortingEnabled(False)
            self.table.setSortingEnabled(False)
            self.table.setRowCount(0)

            rows, cf_map = self.catalog_reads.fetch_rows_with_customs(self.active_custom_fields)
            base_cols = len(self.BASE_HEADERS)
            self.table.setRowCount(len(rows))

            for row_idx, row_data in enumerate(rows):
                for col_idx in range(base_cols):
                    header = self.table.horizontalHeaderItem(col_idx).text()
                    val_raw = row_data[col_idx]
                    if header == 'Track Length (hh:mm:ss)':
                        secs = 0
                        try:
                            secs = int(val_raw or 0)
                        except Exception:
                            secs = parse_hms_text(str(val_raw))
                        disp = seconds_to_hms(secs)
                        it = self._make_item(col_idx, disp)
                        it.setData(Qt.UserRole, secs)
                        self.table.setItem(row_idx, col_idx, it)
                    else:
                        val = '' if val_raw is None else str(val_raw)
                        self.table.setItem(row_idx, col_idx, self._make_item(col_idx, val))

                track_id = row_data[0]
                for offset, field in enumerate(self.active_custom_fields):
                    val = cf_map.get((track_id, field["id"]), "")
                    self.table.setItem(row_idx, base_cols + offset, self._make_item(base_cols + offset, val, custom_def=field))

            self.table.resizeColumnsToContents()
            self._update_count_label()
            self._update_duration_label()
            self._apply_blob_badges()
            self.table.setSortingEnabled(True)
            if _prev_sort_enabled:
                self.table.setSortingEnabled(True)
                try:
                    self.table.sortItems(self._last_sort_col, self._last_sort_order)
                except Exception:
                    pass
        finally:
            self._suspend_layout_history = previous_suspend_state


    def _update_count_label(self):
        # updates 'showing: N records'
        if not hasattr(self, "count_label") or self.count_label is None:
            return
        visible = sum(not self.table.isRowHidden(r) for r in range(self.table.rowCount()))
        self.count_label.setText(f"showing: {visible} record{'s' if visible != 1 else ''}")


    def _update_duration_label(self):
        if not hasattr(self, 'duration_label') or self.duration_label is None:
            return
        # find column index for Track Length
        col_idx = -1
        try:
            for c in range(self.table.columnCount()):
                if self.table.horizontalHeaderItem(c).text() == 'Track Length (hh:mm:ss)':
                    col_idx = c; break
        except Exception:
            pass
        if col_idx == -1:
            self.duration_label.setText("")
            return
        total_sec = 0
        try:
            for r in range(self.table.rowCount()):
                if self.table.isRowHidden(r):
                    continue
                it = self.table.item(r, col_idx)
                if not it:
                    continue
                v = it.data(Qt.UserRole)
                if isinstance(v, (int, float)):
                    total_sec += int(v)
                else:
                    total_sec += parse_hms_text(it.text())
        except Exception:
            pass
        self.duration_label.setText(f"total: {seconds_to_hms(total_sec)}")
    # --- Preserve view wrapper ---
    def _capture_view_state(self):
        hh = self.table.horizontalHeader()
        state = {
            "filter_text": self.search_field.text(),
            "sort_col": hh.sortIndicatorSection(),
            "sort_order": hh.sortIndicatorOrder(),
            "v_scroll": self.table.verticalScrollBar().value(),
            "h_scroll": self.table.horizontalScrollBar().value(),
        }
        return state

    def _restore_view_state(self, state):
        sort_col = state.get("sort_col", 0)
        sort_order = state.get("sort_order", Qt.AscendingOrder)
        if 0 <= sort_col < self.table.columnCount():
            self.table.sortItems(sort_col, sort_order)
        self.apply_search_filter()
        self.table.verticalScrollBar().setValue(state.get("v_scroll", 0))
        self.table.horizontalScrollBar().setValue(state.get("h_scroll", 0))

    def _select_row_by_id(self, focus_id: int):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.text() == str(focus_id):
                self.table.setCurrentCell(r, 0)
                self.table.scrollToItem(it, QTableWidget.PositionAtCenter)
                break

    def refresh_table_preserve_view(self, focus_id: int | None = None):
        _prev_sort_enabled = self.table.isSortingEnabled()
        if _prev_sort_enabled:
            self.table.setSortingEnabled(False)

        # Capture current viewport
        state = self._capture_view_state()

        # Refresh schema + headers
        self.active_custom_fields = self.load_active_custom_fields()
        self._rebuild_table_headers()

        # Always rebind first (safe if duplicated)
        try:
            self._bind_header_state_signals()
        except Exception as e:
            logging.warning("Failed to rebind sectionMoved: %s", e)

        # Then load header state (visual order + widths)
        try:
            self._load_header_state()
        except Exception as e:
            logging.warning("Failed to load header state: %s", e)

        # Refresh data and restore view state
        self.refresh_table()
        self._restore_view_state(state)
        self._update_count_label()

        if focus_id is not None:
            self._select_row_by_id(focus_id)

        # Re-apply blob markers
        self._apply_blob_badges()

        # Restore sorting after refresh
        if _prev_sort_enabled:
            self.table.setSortingEnabled(True)
            try:
                self.table.sortItems(self._last_sort_col, self._last_sort_order)
            except Exception:
                pass

    # =============================================================================
    # Relational helpers
    # =============================================================================

    def get_or_create_artist(self, name: str) -> int:
        return self.track_service.get_or_create_artist(name, cursor=self.cursor)

    def get_or_create_album(self, title: str) -> int | None:
        return self.track_service.get_or_create_album(title, cursor=self.cursor)

    @staticmethod
    def _parse_additional_artists(s: str):
        return TrackService.parse_additional_artists(s)

    def _replace_additional_artists_for_track(self, track_id: int, names):
        self.track_service.replace_additional_artists(track_id, names, cursor=self.cursor)

    # =============================================================================
    # ISRC duplicate check across formats (uses new compact column)
    # =============================================================================
    def is_isrc_taken_normalized(self, candidate: str, exclude_track_id: int | None = None) -> bool:
        return self.track_service.is_isrc_taken_normalized(
            candidate,
            exclude_track_id=exclude_track_id,
            cursor=self.cursor,
        )

    # =============================================================================
    # Save / Edit / Delete
    # =============================================================================
    def save(self):
        if is_blank(self.track_title_field.text()) or is_blank(self.artist_field.currentText()):
            QMessageBox.warning(self, "Missing data", "Track Title and Artist are required.")
            return
        if not valid_upc_ean(self.upc_field.currentText()):
            QMessageBox.warning(self, "Invalid UPC/EAN", "UPC/EAN must be 12 or 13 digits (or leave empty).")
            return
        try:
            # ISWC (optional)
            raw_iswc = (self.iswc_field.text() or "").strip()
            iso_iswc = None
            if raw_iswc:
                iso_iswc = to_iso_iswc(raw_iswc)
                if not iso_iswc or not is_valid_iswc_any(iso_iswc):
                    QMessageBox.warning(
                        self, "Invalid ISWC",
                        "ISWC must be like T-123.456.789-0 or T1234567890 (checksum 0–9 or X), or leave empty."
                    )
                    return

            # ISRC (generated)
            generated_iso = self.generate_isrc()  # ISO-hyphenated or '' if missing settings
            if not generated_iso:
                return
            comp = to_compact_isrc(generated_iso)
            if not comp or not is_valid_isrc_compact_or_iso(generated_iso):
                QMessageBox.critical(self, "ISRC Error", "Generated ISRC is invalid. Check prefix/artist code settings.")
                return

            if self.is_isrc_taken_normalized(generated_iso):
                QMessageBox.critical(self, "ISRC Error", "A track with this ISRC already exists.")
                return

            release_date_sql = self.release_date_field.selectedDate().toString("yyyy-MM-dd")

            track_seconds = hms_to_seconds(self.track_len_h.value(), self.track_len_m.value(), self.track_len_s.value())
            cleanup_artist_names, cleanup_album_titles = self._collect_catalog_cleanup_targets(
                artist_name=self.artist_field.currentText(),
                additional_artists=self._parse_additional_artists(self.additional_artist_field.currentText()),
                album_title=self.album_title_field.currentText().strip() or None,
            )
            self.logger.info(f"About to insert ISRC iso={generated_iso} compact={comp}")
            track_id = self.track_service.create_track(
                TrackCreatePayload(
                    isrc=generated_iso,
                    track_title=self.track_title_field.text().strip(),
                    artist_name=self.artist_field.currentText(),
                    additional_artists=self._parse_additional_artists(self.additional_artist_field.currentText()),
                    album_title=self.album_title_field.currentText().strip() or None,
                    release_date=release_date_sql,
                    track_length_sec=track_seconds,
                    iswc=(iso_iswc or None),
                    upc=(self.upc_field.currentText().strip() or None),
                    genre=(self.genre_field.currentText().strip() or None),
                )
            )
            self.logger.info(f"Track created id={track_id} isrc={generated_iso}")
            self._audit("CREATE", "Track", ref_id=track_id, details=f"isrc={generated_iso}")
            self._audit_commit()
            self.history_manager.record_track_create(
                track_id=track_id,
                cleanup_artist_names=cleanup_artist_names,
                cleanup_album_titles=cleanup_album_titles,
            )

            self.refresh_table_preserve_view(focus_id=track_id)
            self.populate_all_comboboxes()
            self.clear_form_fields()
            self._refresh_history_actions()
            QMessageBox.information(self, "Success", "Track info saved successfully!")
        except sqlite3.IntegrityError as e:
            self.conn.rollback()
            self.logger.exception(f"Save failed (integrity): {e}")
            QMessageBox.critical(self, "Save Error", f"Database constraint error:\n{e}")
        except Exception as e:
            self.conn.rollback()
            self.logger.exception(f"Save failed: {e}")
            QMessageBox.critical(self, "Save Error", f"Failed to save record:\n{e}")

    def edit_entry(self, item):
        row_idx = item.row()
        base_cols = len(self.BASE_HEADERS)
        row_data = [self.table.item(row_idx, i).text() if self.table.item(row_idx, i) else "" for i in range(base_cols)]
        dlg = EditDialog(row_data, self)
        dlg.exec()
        self.populate_all_comboboxes()

    def delete_entry(self):
        current_row = self.table.currentRow()
        if current_row == -1:
            QMessageBox.warning(self, "Warning", "No row selected for deletion!")
            return
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setText("Are you sure you want to delete this entry?")
        msg_box.setWindowTitle("Delete Entry")
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        if msg_box.exec() == QMessageBox.Yes:
            try:
                row_id_item = self.table.item(current_row, 0)
                if not row_id_item:
                    QMessageBox.warning(self, "Delete", "Could not determine record ID.")
                    return
                row_id = int(row_id_item.text())
                before_snapshot = self.track_service.fetch_track_snapshot(row_id)
                if before_snapshot is None:
                    QMessageBox.warning(self, "Delete", "Could not load the selected track for deletion.")
                    return
                self.track_service.delete_track(row_id)
                self.refresh_table_preserve_view()
                self.populate_all_comboboxes()
                self.logger.warning(f"Track deleted id={row_id}")
                self._audit("DELETE", "Track", ref_id=row_id, details="delete_entry")
                self._audit_commit()
                self.history_manager.record_track_delete(before_snapshot=before_snapshot)
                self._refresh_history_actions()
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Delete failed: {e}")
                QMessageBox.critical(self, "Delete Error", f"Failed to delete:\n{e}")

    def init_form(self):
        self.refresh_table_preserve_view()
        self.populate_all_comboboxes()
        self.clear_form_fields()

    # =============================================================================
    # Album autofill
    # =============================================================================
    def autofill_album_metadata(self):
        title = (self.album_title_field.currentText() or "").strip()
        if not title:
            return
        row = self.catalog_reads.find_album_metadata(title)
        if row:
            rd, upc, genre = row
            if rd:
                qd = QDate.fromString(rd, "yyyy-MM-dd")
                self.release_date_field.setSelectedDate(qd if qd.isValid() else QDate.currentDate())
            if upc:
                self.upc_field.setCurrentText(upc)
            if genre:
                self.genre_field.setCurrentText(genre)
            self.prev_release_toggle.setChecked(True)

    # =============================================================================
    # ISRC generation (YY + AA + SSS) with strict ISO compliance
    # =============================================================================
    def generate_isrc(self) -> str:
        prefix = (self.load_isrc_prefix() or "").upper().strip()
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}", prefix or ""):
            QMessageBox.warning(
                self, "ISRC Prefix Required",
                "Set a valid 5-char ISRC prefix (CC+XXX), e.g., 'XXX0Y'."
            )
            return ""

        # YY = assignment year (or album year if 'previous release' checked)
        year = datetime.now().year % 100
        if self.prev_release_toggle.isChecked():
            year = self.release_date_field.selectedDate().year() % 100
        yy = f"{year:02d}"

        # AA = 2-digit artist code (00–99)
        artist_code = self.load_artist_code()
        if not re.fullmatch(r"\d{2}", artist_code or ""):
            QMessageBox.warning(
                self, "Artist Code Required",
                "Set a 2-digit ISRC artist code (00–99) in Settings."
            )
            return ""

        # We sub-allocate NNNNN as AA(2) + SSS(3). Build compact stem CCXXXYYAA.
        stem_compact = f"{prefix}{yy}{artist_code}"

        # Find next free SSS in 001..999
        for seq in range(1, 1000):
            sss = f"{seq:03d}"
            candidate_compact = f"{stem_compact}{sss}"  # CCXXXYYAASSS (12 chars)
            # Uniqueness check using compact column
            row = self.cursor.execute(
                "SELECT 1 FROM Tracks WHERE isrc_compact=? LIMIT 1",
                (candidate_compact,)
            ).fetchone()
            if not row:
                # Return ISO-hyphenated form for storage/export consistency
                return f"{prefix[0:2]}-{prefix[2:5]}-{yy}-{artist_code}{sss}"

        QMessageBox.critical(self, "ISRC Exhausted",
                             "No free sequence (001–999) left for this artist/year.")
        return ""

    # =============================================================================
    # Export / Import (with location picker, overwrite confirm, dry-run option)
    # =============================================================================
    def export_full_to_xml(self):
        try:
            default_name = f"full_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
            default_path = str(self.exports_dir / default_name)
            path, sel = QFileDialog.getSaveFileName(
                self, "Export All to XML", default_path, "XML Files (*.xml)"
            )
            if not path:
                return

            if Path(path).exists():
                if QMessageBox.question(
                    self, "Overwrite?",
                    f"File exists:\n{path}\n\nOverwrite?",
                    QMessageBox.Yes | QMessageBox.No
                ) != QMessageBox.Yes:
                    return

            exported = self._run_file_history_action(
                action_label=lambda count: f"Export XML: {count} tracks",
                action_type="file.export_xml_all",
                target_path=path,
                mutation=lambda: self.xml_export_service.export_all(path),
                entity_type="Export",
                entity_id=path,
                payload=lambda count: {"path": path, "count": count},
            )
            QMessageBox.information(self, "Export", f"All data exported:\n{path}")
            self.logger.info(f"Exported {exported} rows to {path}")
            self._audit("EXPORT", "Tracks", ref_id=path, details=f"all rows incl. duration+customs count={exported}")
            self._audit_commit()
        except Exception as e:
            self.logger.exception(f"Export failed: {e}")
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n{e}")

    def export_selected_to_xml(self):
        """Export visible rows if a filter is active; otherwise export explicitly selected rows."""
        # --- Collect Track IDs (prefer visible/filtered rows) ---
        row_count = self.table.rowCount()
        any_hidden = any(self.table.isRowHidden(r) for r in range(row_count))
        if any_hidden:
            rows = [r for r in range(row_count) if not self.table.isRowHidden(r)]
        else:
            sel = self.table.selectionModel()
            if not sel or not sel.hasSelection():
                QMessageBox.information(self, "Export Selected", "Select one or more rows (or apply a filter) first.")
                return
            rows = [idx.row() for idx in sel.selectedRows()]

        track_ids = sorted({
            int(self.table.item(r, 0).text())
            for r in rows
            if self.table.item(r, 0) and self.table.item(r, 0).text().strip().isdigit()
        })
        if not track_ids:
            QMessageBox.warning(self, "Export Selected", "No valid track IDs found to export.")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"Selected_Tracks_{ts}.xml"
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Export Selected to XML", str(self.exports_dir / default_name), "XML Files (*.xml)"
        )
        if not out_path:
            return

        try:
            exported = self._run_file_history_action(
                action_label=lambda count: f"Export Selected XML: {count} tracks",
                action_type="file.export_xml_selected",
                target_path=out_path,
                mutation=lambda: self.xml_export_service.export_selected(
                    out_path,
                    track_ids,
                    current_db_path=str(self.current_db_path),
                ),
                entity_type="Export",
                entity_id=out_path,
                payload=lambda count: {"path": out_path, "count": count, "track_ids": track_ids},
            )
            self.logger.info(f"Exported {exported} rows to XML (ids={track_ids}) -> {out_path}")
            QMessageBox.information(self, "Export Complete", f"Saved:\n{out_path}")
        except Exception as e:
            self.logger.exception(f"Export Selected failed: {e}")
            QMessageBox.critical(self, "Export Error", f"Could not write file:\n{e}")

    def import_from_xml(self):
        """
        Robust import:
        - Accepts both schemas:
            1) DeclarationOfSoundRecordingRightsClaimMessage/SoundRecording (full export)
            2) ISRCExport/Tracks/Track (selected export)
        - Imports TrackLength (hh:mm:ss) -> track_length_sec
        - Imports custom columns (non-blob). If any required custom column is missing or type mismatched,
        inform user + log and abort gracefully (no changes).
        - Namespace-/case-robust tag handling
        - Normalize ISRC/ISWC to ISO; skip invalid; skip dupes
        - Per-row savepoints
        - Dry-run with optional "Proceed with import?" to commit without re-picking file
        """
        try:
            file_path, _ = QFileDialog.getOpenFileName(self, "Import from XML", "", "XML Files (*.xml)")
            if not file_path:
                return

            before_snapshot = None

            dry = QMessageBox.question(
                self, "Dry Run?",
                "Run a dry-run first (no changes will be written) to see the summary?",
                QMessageBox.Yes | QMessageBox.No
            ) == QMessageBox.Yes

            try:
                inspection = self.xml_import_service.inspect_file(file_path)
            except Exception as e:
                QMessageBox.critical(self, "Import Error", str(e))
                return

            if inspection.missing_custom_fields:
                msg = "Missing custom columns (name : type):\n" + "\n".join(
                    f"- {name} : {field_type}" for name, field_type in inspection.missing_custom_fields
                )
                self.logger.warning(
                    "Import aborted due to missing custom columns: %s",
                    inspection.missing_custom_fields,
                )
                QMessageBox.critical(self, "Import Error", msg + "\n\nNo changes were made.")
                return

            # If dry-run, show summary then optionally proceed
            if dry:
                self.logger.info(
                    "Dry-run: would_insert=%s, dupes=%s, invalid=%s, errors=0",
                    inspection.would_insert,
                    inspection.duplicate_count,
                    inspection.invalid_count,
                )
                proceed = QMessageBox.question(
                    self, "Dry-run finished",
                    f"Would insert: {inspection.would_insert}\n"
                    f"Skipped (duplicates): {inspection.duplicate_count}\n"
                    f"Skipped (invalid): {inspection.invalid_count}\n"
                    f"Errors: 0\n\n"
                    f"Proceed with import now?",
                    QMessageBox.Yes | QMessageBox.No
                ) == QMessageBox.Yes
                if not proceed:
                    self._audit(
                        "IMPORT",
                        "Tracks",
                        ref_id=file_path,
                        details=(
                            f"mode=dry_only, would_ins={inspection.would_insert}, "
                            f"dup={inspection.duplicate_count}, inv={inspection.invalid_count}, err=0"
                        ),
                    )
                    self._audit_commit()
                    return

            try:
                before_snapshot = self.history_manager.capture_snapshot(
                    kind="pre_import",
                    label=f"Before Import XML: {Path(file_path).name}",
                )
                result = self.xml_import_service.execute_import(file_path)
            except Exception as e:
                if before_snapshot is not None:
                    try:
                        self.history_manager.delete_snapshot(before_snapshot.snapshot_id)
                    except Exception:
                        pass
                self.conn.rollback()
                self.logger.exception(f"Import transaction failed: {e}")
                QMessageBox.critical(self, "Import Error", f"Import failed:\n{e}")
                return

            self.refresh_table_preserve_view()
            self.populate_all_comboboxes()

            mode = "Import finished" if not dry else "Import finished (after dry-run)"
            self.logger.info(
                "%s: inserted=%s, dupes=%s, invalid=%s, errors=%s",
                mode,
                result.inserted,
                result.duplicate_count,
                result.invalid_count,
                result.error_count,
            )
            self._audit(
                "IMPORT",
                "Tracks",
                ref_id=file_path,
                details=(
                    f"mode={'commit_after_dry' if dry else 'commit'}, "
                    f"ins={result.inserted}, dup={result.duplicate_count}, "
                    f"inv={result.invalid_count}, err={result.error_count}"
                ),
            )
            self._audit_commit()

            if result.inserted > 0 and before_snapshot is not None:
                after_snapshot = self.history_manager.capture_snapshot(
                    kind="post_import",
                    label=f"After Import XML: {Path(file_path).name}",
                )
                self.history_manager.record_snapshot_action(
                    label=f"Import XML: {result.inserted} tracks",
                    action_type="import.xml",
                    entity_type="Import",
                    entity_id=file_path,
                    payload={
                        "path": file_path,
                        "inserted": result.inserted,
                        "duplicate_count": result.duplicate_count,
                        "invalid_count": result.invalid_count,
                        "error_count": result.error_count,
                    },
                    snapshot_before_id=before_snapshot.snapshot_id,
                    snapshot_after_id=after_snapshot.snapshot_id,
                )
            else:
                self.history_manager.record_event(
                    label=f"Import XML: {result.inserted} tracks",
                    action_type="import.xml",
                    entity_type="Import",
                    entity_id=file_path,
                    payload={
                        "path": file_path,
                        "inserted": result.inserted,
                        "duplicate_count": result.duplicate_count,
                        "invalid_count": result.invalid_count,
                        "error_count": result.error_count,
                    },
                )
            self._refresh_history_actions()

            QMessageBox.information(
                self, mode,
                f"Inserted: {result.inserted}\n"
                f"Skipped (duplicates): {result.duplicate_count}\n"
                f"Skipped (invalid): {result.invalid_count}\n"
                f"Errors: {result.error_count}"
            )
        except Exception as e:
            self.logger.exception(f"Import failed: {e}")
            QMessageBox.critical(self, "Import Error", f"Unexpected error:\n{e}")

    # =============================================================================
    # Settings (prefix / numbers) + summary dialog
    # =============================================================================
    def set_isrc_prefix(self):
        current = self.load_isrc_prefix()
        prefix, ok = QInputDialog.getText(self, "Set ISRC Prefix", "Enter ISRC prefix (e.g., XXX0Y):", text=current)
        if ok:
            pref = (prefix or "").strip().upper()
            if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}", pref):
                QMessageBox.warning(self, "Invalid Prefix", "Prefix must be CC+XXX (5 chars).")
                return
            try:
                self.settings_mutations.set_isrc_prefix(pref)
                self.logger.info(f"ISRC prefix updated to '{pref}'")
                self._audit("SETTINGS", "ISRC_Prefix", ref_id=1, details=f"prefix={pref}")
                self._audit_commit()
                self.history_manager.record_setting_change(
                    key="isrc_prefix",
                    label=f"Set ISRC Prefix: {pref}",
                    before_value=current,
                    after_value=pref,
                )
                self._refresh_history_actions()
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Set ISRC prefix failed: {e}")
                QMessageBox.critical(self, "Error", f"Could not save prefix:\n{e}")

    def set_sena_number(self):
        current = self.settings_reads.load_sena_number()
        text, ok = QInputDialog.getText(self, "Set SENA Number", "Enter SENA Number:", text=current)
        if ok:
            try:
                updated = (text or "").strip()
                self.settings_mutations.set_sena_number(updated)
                self.logger.info("SENA number updated")
                self._audit("SETTINGS", "SENA", ref_id=1, details="updated")
                self._audit_commit()
                self.history_manager.record_setting_change(
                    key="sena_number",
                    label="Set SENA Number",
                    before_value=current,
                    after_value=updated,
                )
                self._refresh_history_actions()
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Set SENA number failed: {e}")
                QMessageBox.critical(self, "Error", f"Could not save SENA number:\n{e}")

    def set_btw_number(self):
        current = self.settings_reads.load_btw_number()
        text, ok = QInputDialog.getText(self, "Set BTW Number", "Enter BTW Number:", text=current)
        if ok:
            try:
                updated = (text or "").strip()
                self.settings_mutations.set_btw_number(updated)
                self.logger.info("BTW number updated")
                self._audit("SETTINGS", "BTW", ref_id=1, details="updated")
                self._audit_commit()
                self.history_manager.record_setting_change(
                    key="btw_number",
                    label="Set BTW Number",
                    before_value=current,
                    after_value=updated,
                )
                self._refresh_history_actions()
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Set BTW failed: {e}")
                QMessageBox.critical(self, "Error", f"Could not save BTW number:\n{e}")

    def set_buma_info(self):
        current_rel = self.settings_reads.load_buma_relatie_nummer()
        relatie_nummer, ok = QInputDialog.getText(self, "Set BUMA Relatie Nummer", "Enter Relatie Nummer:", text=current_rel)
        if ok:
            try:
                updated = (relatie_nummer or "").strip()
                self.settings_mutations.set_buma_relatie_nummer(updated)
                self.logger.info("BUMA/STEMRA relatie nummer updated")
                self._audit("SETTINGS", "BUMA_STEMRA", ref_id=1, details="relatie_nummer updated")
                self._audit_commit()
                self.history_manager.record_setting_change(
                    key="buma_relatie_nummer",
                    label="Set BUMA/STEMRA Relation Number",
                    before_value=current_rel,
                    after_value=updated,
                )
                self._refresh_history_actions()
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Set BUMA relatie nummer failed: {e}")
                QMessageBox.critical(self, "Error", f"Could not save BUMA relatie nummer:\n{e}")

    def set_ipi_info(self):
        current_ipi = self.settings_reads.load_buma_ipi()
        ipi, ok = QInputDialog.getText(self, "Set BUMA IPI", "Enter IPI Number:", text=current_ipi)
        if ok:
            try:
                updated = (ipi or "").strip()
                self.settings_mutations.set_buma_ipi(updated)
                self.logger.info("BUMA/STEMRA IPI updated")
                self._audit("SETTINGS", "BUMA_STEMRA", ref_id=1, details="ipi updated")
                self._audit_commit()
                self.history_manager.record_setting_change(
                    key="buma_ipi",
                    label="Set BUMA IPI",
                    before_value=current_ipi,
                    after_value=updated,
                )
                self._refresh_history_actions()
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Set BUMA IPI failed: {e}")
                QMessageBox.critical(self, "Error", f"Could not save BUMA IPI:\n{e}")

    def show_settings_summary(self):
        """View-only summary dialog (no editing)."""
        registration = self.settings_reads.load_registration_settings()
        isrc = registration.isrc_prefix or "(not set)"
        sena_txt = registration.sena_number or "(not set)"
        btw_txt = registration.btw_number or "(not set)"
        rel_txt = registration.buma_relatie_nummer or "(not set)"
        ipi_txt = registration.buma_ipi or "(not set)"
        db_ver   = self._get_db_version()

        dlg = QDialog(self)
        dlg.setWindowTitle("App Info")
        lay = QVBoxLayout(dlg)

        def add_label(text):
            lbl = QLabel(text)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            lay.addWidget(lbl)
            return lbl

        # Info labels
        add_label(f"<b>Window Title:</b> {self.identity.get('window_title') or DEFAULT_WINDOW_TITLE}")
        add_label(f"<b>Icon:</b> {self.identity.get('icon_path') or '(not set)'}")
        add_label(f"<b>Current Database:</b> {self.current_db_path}")
        add_label(f"<b>DB Schema Version:</b> {db_ver}")

        # Horizontal line
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        lay.addWidget(line)

        add_label("<b>Registration & Codes</b>")
        add_label(f"ISRC Prefix: {isrc}")
        add_label(f"Artist Code (AA): {self.load_artist_code() or '(not set)'}")
        add_label(f"SENA Number: {sena_txt}")
        add_label(f"BTW Number: {btw_txt}")
        add_label(f"BUMA/STEMRA Relatie Nummer: {rel_txt}")
        add_label(f"BUMA/STEMRA IPI: {ipi_txt}")

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        lay.addWidget(close_btn, alignment=Qt.AlignRight)

        dlg.exec()

    # =============================================================================
    # View settings (interactive resize + draggable hints)
    # =============================================================================
    def _form_has_focus(self) -> bool:
        w = QApplication.focusWidget()
        return bool(w and hasattr(self, "left_widget_container")
                    and self.left_widget_container.isAncestorOf(w))

    def _apply_table_view_settings(self):
        self.table.horizontalHeader().setVisible(True)
        self.table.verticalHeader().setVisible(True)

    def _on_toggle_col_width(self, enabled: bool):
        hh = self.table.horizontalHeader()
        if enabled:
            for i in range(self.table.columnCount()):
                hh.setSectionResizeMode(i, QHeaderView.Interactive)
            hh.setStretchLastSection(False)
            try:
                hh.sectionResized.disconnect(self._update_col_hint)
            except TypeError:
                pass
            hh.sectionResized.connect(self._update_col_hint)
            self._ensure_col_hint_label()
            self.col_hint_label.show()
            self._apply_table_view_settings()
        else:
            for i in range(self.table.columnCount()):
                hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
            hh.setStretchLastSection(True)
            self.table.resizeColumnsToContents()
            try:
                hh.sectionResized.disconnect(self._update_col_hint)
            except TypeError:
                pass
            if self.col_hint_label:
                self.col_hint_label.hide()
            self._apply_table_view_settings()
        self._reset_hint_label()

    def _on_toggle_row_height(self, enabled: bool):
        vh = self.table.verticalHeader()
        if enabled:
            vh.setSectionResizeMode(QHeaderView.Interactive)
            try:
                vh.sectionResized.disconnect(self._update_row_hint)
            except TypeError:
                pass
            vh.sectionResized.connect(self._update_row_hint)
            self._ensure_row_hint_label()
            self.row_hint_label.show()
        else:
            vh.setSectionResizeMode(QHeaderView.Fixed)
            for i in range(self.table.rowCount()):
                self.table.setRowHeight(i, 24)
            try:
                vh.sectionResized.disconnect(self._update_row_hint)
            except TypeError:
                pass
            if self.row_hint_label:
                self.row_hint_label.hide()
        self._apply_table_view_settings()
        self._reset_hint_label()

    def _reset_hint_label(self):
        if self.col_hint_label:
            self.col_hint_label._user_moved = False
        if self.row_hint_label:
            self.row_hint_label._user_moved = False

    def _on_toggle_add_data(self, enabled: bool):
        """
        Toggle visibility of the left 'add data' pane.
        When disabled, the table view expands to occupy the full window.
        """
        enabled = bool(enabled)

        # If the scroll container exists (rev11), toggle it.
        if hasattr(self, "left_scroll") and isinstance(self.left_scroll, QWidget):
            if enabled:
                # Restore normal width and show
                try:
                    self.left_scroll.setMaximumWidth(16777215)  # Qt max
                    self.left_scroll.setMinimumWidth(350)       # your original
                except Exception:
                    pass
                self.left_scroll.show()
            else:
                # Hide completely and collapse width so layout gives all space to the table
                self.left_scroll.hide()
                try:
                    self.left_scroll.setMinimumWidth(0)
                    self.left_scroll.setMaximumWidth(0)
                except Exception:
                    pass

        # Make sure the right side stretches to fill
        try:
            # Left index = 0 (left_scroll), right index = 1 (right_panel)
            # Give all stretch to the right side; left can be 0
            self.super_layout.setStretch(0, 0)
            self.super_layout.setStretch(1, 1)
        except Exception:
            pass

        # If you also programmatically control the QAction state elsewhere, keep it in sync
        try:
            self.add_data_action.blockSignals(True)
            self.add_data_action.setChecked(enabled)
        finally:
            self.add_data_action.blockSignals(False)


    def _ensure_col_hint_label(self):
        if self.col_hint_label is None:
            self.col_hint_label = DraggableLabel(self, settings_key="display/col_hint_pos")
            self.col_hint_label.setObjectName("colHint")
            self.col_hint_label.setStyleSheet(
                "QLabel#colHint { background: rgba(0,0,0,0.75); color: white; padding: 4px 8px; border-radius: 6px; font: 11px 'Segoe UI'; }"
            )
            s = self.settings
            pos = s.value("display/col_hint_pos", type=QPoint)
            if pos:
                self.col_hint_label.move(pos)
            self.col_hint_label.hide()

    def _ensure_row_hint_label(self):
        if self.row_hint_label is None:
            self.row_hint_label = DraggableLabel(self, settings_key="display/row_hint_pos")
            self.row_hint_label.setObjectName("rowHint")
            self.row_hint_label.setStyleSheet(
                "QLabel#rowHint { background: rgba(0,0,0,0.75); color: white; padding: 4px 8px; border-radius: 6px; font: 11px 'Segoe UI'; }"
            )
            s = self.settings
            pos = s.value("display/row_hint_pos", type=QPoint)
            if pos:
                self.row_hint_label.move(pos)
            self.row_hint_label.hide()

    def _update_col_hint(self, logical_index: int, old_size: int, new_size: int):
        self._ensure_col_hint_label()
        self.col_hint_label.setText(f"Col {logical_index + 1}: {new_size}px")
        if not getattr(self.col_hint_label, "_user_moved", False):
            hh = self.table.horizontalHeader()
            x = hh.sectionViewportPosition(logical_index) + new_size + 6
            y = hh.height() // 2
            pt = hh.viewport().mapTo(self, QPoint(x, y))
            self.col_hint_label.move(pt)
        self.col_hint_label.show()
        self.col_hint_label.raise_()

    def _update_row_hint(self, logical_index: int, old_size: int, new_size: int):
        self._ensure_row_hint_label()
        self.row_hint_label.setText(f"Row {logical_index + 1}: {new_size}px")
        if not getattr(self.row_hint_label, "_user_moved", False):
            vh = self.table.verticalHeader()
            x = vh.width() // 2
            y = vh.sectionViewportPosition(logical_index) + new_size + 6
            pt = vh.viewport().mapTo(self, QPoint(x, y))
            self.row_hint_label.move(pt)
        self.row_hint_label.show()
        self.row_hint_label.raise_()

    # ============================================================
    # Manage custom columns (persist type + options)
    # ============================================================
    def manage_custom_columns(self):
        dlg = CustomColumnsDialog(self.active_custom_fields, self)
        if dlg.exec() == QDialog.Accepted:
            new_fields = dlg.get_fields()
            current_summary = [
                {
                    "id": field.get("id"),
                    "name": field.get("name"),
                    "field_type": field.get("field_type"),
                    "options": field.get("options"),
                }
                for field in self.active_custom_fields
            ]
            new_summary = [
                {
                    "id": field.get("id"),
                    "name": field.get("name"),
                    "field_type": field.get("field_type"),
                    "options": field.get("options"),
                }
                for field in new_fields
            ]
            if current_summary == new_summary:
                return

            before_snapshot = self.history_manager.capture_snapshot(
                kind="pre_custom_fields",
                label="Before Manage Custom Columns",
            )

            try:
                self.custom_field_definitions.sync_fields(self.active_custom_fields, new_fields)
            except Exception as e:
                try:
                    self.history_manager.delete_snapshot(before_snapshot.snapshot_id)
                except Exception:
                    pass
                self.conn.rollback()
                self.logger.exception(f"Custom fields update failed: {e}")
                QMessageBox.critical(self, "Fields Error", f"Could not update fields:\n{e}")
                return

            self.active_custom_fields = self.load_active_custom_fields()
            self._rebuild_table_headers()
            self.refresh_table_preserve_view()

            try:
                changed_summary = json.dumps([{"id": f.get("id"), "name": f["name"], "type": f.get("field_type")} for f in new_fields])
            except Exception:
                changed_summary = "fields changed"
            self.logger.info("Custom fields updated")
            self._audit("FIELDS", "CustomFieldDefs", ref_id="batch", details=changed_summary)
            self._audit_commit()
            after_snapshot = self.history_manager.capture_snapshot(
                kind="post_custom_fields",
                label="After Manage Custom Columns",
            )
            self.history_manager.record_snapshot_action(
                label="Manage Custom Columns",
                action_type="fields.manage",
                entity_type="CustomFieldDefs",
                entity_id="batch",
                payload={"summary": changed_summary},
                snapshot_before_id=before_snapshot.snapshot_id,
                snapshot_after_id=after_snapshot.snapshot_id,
            )
            self._refresh_history_actions()


    def _on_custom_fields_changed(self):
        self.active_custom_fields = self.load_active_custom_fields()
        self._rebuild_table_headers()

        # Always rebind first (safe if duplicated)
        try:
            self._bind_header_state_signals()
        except Exception as e:
            logging.warning("Failed to rebind sectionMoved after custom fields change: %s", e)

        # Then load header state (visual order + widths)
        try:
            self._load_header_state()
        except Exception as e:
            logging.warning("Failed to load header state after custom fields change: %s", e)

        self.refresh_table()
        self._update_count_label()
        self._apply_blob_badges()


    # ============================================================
    # Double-click editing: base vs custom fields
    # ============================================================
    def _on_item_double_clicked(self, item: QTableWidgetItem):
        col = item.column()
        if col < len(self.BASE_HEADERS):
            self.edit_entry(item)
            return

        # --- Custom field context ---
        field = self.active_custom_fields[col - len(self.BASE_HEADERS)]
        id_item = self.table.item(item.row(), 0)
        if not id_item:
            return
        track_id = int(id_item.text())
        field_id = field["id"]
        field_type = field.get("field_type", "text")
        options = json.loads(field.get("options") or "[]") if field_type == "dropdown" else None

        # --- BLOB fields -> file picker + save, then return ---
        if field_type in ("blob_image", "blob_audio"):
            if field_type == "blob_image":
                flt = "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff);;All files (*)"
            else:
                flt = "Audio (*.wav *.aif *.aiff *.mp3 *.flac *.m4a *.aac *.ogg *.opus);;All files (*)"
            new_path, _ = QFileDialog.getOpenFileName(self, f"Attach file: {field['name']}", "", flt)
            if not new_path:
                return
            try:
                self._run_snapshot_history_action(
                    action_label=f"Attach Custom File: {field['name']}",
                    action_type="custom_field.blob_attach",
                    entity_type="CustomFieldValue",
                    entity_id=f"{track_id}:{field_id}",
                    payload={"track_id": track_id, "field_id": field_id, "field_name": field["name"]},
                    mutation=lambda: self.cf_save_value(track_id, field_id, value=None, blob_path=new_path),
                )
                self.refresh_table_preserve_view(focus_id=track_id)
                return
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Custom BLOB save failed: {e}")
                QMessageBox.critical(self, "Custom Field Error", f"Failed to save file:\n{e}")
                return

        # --- Non-BLOB editors (unchanged) ---
        current_val = self.custom_field_values.get_text_value(track_id, field_id)

        options_updated = False
        if field_type == "dropdown":
            choices = options[:] if options else []
            original_options = list(choices)
            if current_val and current_val not in choices:
                choices.append(current_val)
            new_val, ok = QInputDialog.getItem(
                self, f"Edit: {field['name']}", field['name'],
                choices, current=choices.index(current_val) if current_val in choices else 0, editable=True
            )
            if not ok:
                return
            if new_val and options is not None and new_val not in options:
                options.append(new_val)
            options_updated = options != original_options
        elif field_type == "checkbox":
            choice, ok = QInputDialog.getItem(
                self, f"Edit: {field['name']}", field['name'],
                ["True", "False"], current=0 if (current_val == "True") else 1, editable=False
            )
            if not ok:
                return
            new_val = "True" if choice == "True" else "False"
        elif field_type == "date":
            init = current_val if re.match(r"^\d{4}-\d{2}-\d{2}$", (current_val or "")) else None
            dlg = DatePickerDialog(self, initial_iso_date=init, title=f"Edit: {field['name']}")
            if dlg.exec() != QDialog.Accepted:
                return
            sel = dlg.selected_iso()
            new_val = "" if sel is None else sel
        else:
            new_val, ok = QInputDialog.getMultiLineText(self, f"Edit: {field['name']}", f"{field['name']}:", text=current_val)
            if not ok:
                return

        # Upsert for non-BLOB fields
        if new_val == current_val and not options_updated:
            return
        try:
            def mutation():
                if field_type == "dropdown" and options_updated:
                    self.custom_field_definitions.update_dropdown_options(field_id, options)
                self.custom_field_values.save_value(track_id, field_id, value=new_val)

            self._run_snapshot_history_action(
                action_label=f"Update Custom Field: {field['name']}",
                action_type="custom_field.value_update",
                entity_type="CustomFieldValue",
                entity_id=f"{track_id}:{field_id}",
                payload={"track_id": track_id, "field_id": field_id, "field_name": field["name"]},
                mutation=mutation,
            )
            self.refresh_table_preserve_view(focus_id=track_id)
        except Exception as e:
            self.conn.rollback()
            self.logger.exception(f"Custom field save failed: {e}")
            QMessageBox.critical(self, "Custom Field Error", f"Failed to save custom field:\n{e}")

    # =============================================================================
    # Table context menu
    # =============================================================================
    def _on_table_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        col = index.column()
        self.table.setCurrentCell(row, col)

        menu = QMenu(self)
        act_edit = QAction("Edit Entry", self)
        act_edit.triggered.connect(lambda: self.edit_entry(self.table.item(row, col)))
        menu.addAction(act_edit)

        act_delete = QAction("Delete Entry", self)
        act_delete.triggered.connect(self.delete_entry)
        menu.addAction(act_delete)
            
        menu.addSeparator()
        # Licenses actions
        try:
            id_item = self.table.item(row, 0)
            track_id = int(id_item.text()) if id_item else None
        except Exception:
            track_id = None
        if track_id:
            act_add_license = QAction("Add License to this Track…", self)
            act_add_license.triggered.connect(lambda: self.open_license_upload(preselect_track_id=track_id))
            menu.addAction(act_add_license)

            act_view_licenses = QAction("View Licenses for this Track…", self)
            act_view_licenses.triggered.connect(lambda: self.open_licenses_browser(track_filter_id=track_id))
            menu.addAction(act_view_licenses)


        cell_item = self.table.item(row, col)
        cell_text = cell_item.text() if cell_item else ""
        act_filter = QAction(f"Set Filter: '{cell_text}'", self)
        act_filter.triggered.connect(lambda: self.search_field.setText(cell_text))
        menu.addAction(act_filter)


        # Copy actions
        act_copy = QAction("Copy", self)
        act_copy.triggered.connect(lambda: self._copy_selection_to_clipboard(False))
        menu.addAction(act_copy)

        act_copy_hdrs = QAction("Copy with headers", self)
        act_copy_hdrs.triggered.connect(lambda: self._copy_selection_to_clipboard(True))
        menu.addAction(act_copy_hdrs)

        menu.addSeparator()

        # Preview file action for custom blob columns
        if col >= len(self.BASE_HEADERS):
            field = self.active_custom_fields[col - len(self.BASE_HEADERS)]
            if self.cf_has_blob(int(self.table.item(row, 0).text()), field["id"]):
                id_item = self.table.item(row, 0)
                if id_item:
                    track_id = int(id_item.text())
                    act_prev = QAction("Preview File…", self)
                    def _do_prev():
                        try:
                            data = self.cf_fetch_blob(track_id, field["id"])  # must return bytes or memoryview
                            if not data:
                                QMessageBox.information(self, "Preview", "No data stored in this cell.")
                                return
                            # Use the actual track title for the preview dialog
                            try:
                                track_title = self._get_track_title(track_id) or f"track_{track_id}"
                            except Exception:
                                track_title = f"track_{track_id}"
                            title = f"{track_title} — {field.get('label') or field.get('name') or 'File'}"
                            self._preview_blob_bytes(data, title)
                        except Exception as e:
                            self.conn.rollback()
                            self.logger.exception(f"Preview blob failed: {e}")
                            QMessageBox.critical(self, "Custom Field Error", f"Failed to preview file:\n{e}")
                    act_prev.triggered.connect(_do_prev)
                    menu.addAction(act_prev)

        # Blob field actions for custom columns
        if col >= len(self.BASE_HEADERS):
            field = self.active_custom_fields[col - len(self.BASE_HEADERS)]
            field_id = field["id"]
            id_item = self.table.item(row, 0)
            title_item = self.table.item(row, 3)  # Track title column
            if id_item and field.get("field_type") in ("blob_image", "blob_audio"):
                track_id = int(id_item.text())
                track_title = title_item.text() if title_item else f"track_{track_id}"

                menu.addSeparator()
                act_attach = QAction("Attach/Replace File…", self)
                act_attach.triggered.connect(
                    lambda: self._attach_blob_for_cell(track_id, field_id, field.get("field_type"), field.get("name"))
                )
                menu.addAction(act_attach)

                # Use track title for export action label
                act_export = QAction(f"Export '{track_title}'…", self)
                act_export.triggered.connect(
                    lambda: self.cf_export_blob(track_id, field_id, self, track_title)
                )
                menu.addAction(act_export)

        # Delete blob action for custom blob columns
        if col >= len(self.BASE_HEADERS):
            field = self.active_custom_fields[col - len(self.BASE_HEADERS)]
            if self.cf_has_blob(int(self.table.item(row, 0).text()), field["id"]):
                id_item = self.table.item(row, 0)
                if id_item:
                    track_id = int(id_item.text())
                    if self.cf_has_blob(track_id, field["id"]):
                        act_del = QAction("Delete File…", self)
                        def _do_del():
                            if QMessageBox.question(self, "Delete File", "Remove the stored file from this cell?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                                try:
                                    self._run_snapshot_history_action(
                                        action_label=f"Delete Custom File: {field['name']}",
                                        action_type="custom_field.blob_delete",
                                        entity_type="CustomFieldValue",
                                        entity_id=f"{track_id}:{field['id']}",
                                        payload={"track_id": track_id, "field_id": field["id"], "field_name": field["name"]},
                                        mutation=lambda: self.cf_delete_blob(track_id, field["id"]),
                                    )
                                    self.refresh_table_preserve_view(focus_id=track_id)
                                except Exception as e:
                                    self.conn.rollback()
                                    self.logger.exception(f"Delete blob failed: {e}")
                                    QMessageBox.critical(self, "Custom Field Error", f"Failed to delete file:\n{e}")
                        act_del.triggered.connect(_do_del)
                        menu.addAction(act_del)

        menu.exec(self.table.viewport().mapToGlobal(pos))


    def _preview_blob_for_cell(self, row: int, col: int):
        """Directly preview the blob in the given cell (image/audio)."""
        if col < len(self.BASE_HEADERS):
            return  # only custom blob columns

        field = self.active_custom_fields[col - len(self.BASE_HEADERS)]
        id_item = self.table.item(row, 0)
        if not id_item:
            return

        try:
            track_id = int(id_item.text())
            if not self.cf_has_blob(track_id, field["id"]):
                return

            data = self.cf_fetch_blob(track_id, field["id"])  # must return bytes or memoryview
            if not data:
                QMessageBox.information(self, "Preview", "No data stored in this cell.")
                return

            # Use the actual track title for the preview dialog
            try:
                track_title = self._get_track_title(track_id) or f"track_{track_id}"
            except Exception:
                track_title = f"track_{track_id}"
            title = track_title
            self._preview_blob_bytes(data, title)
        except Exception as e:
            self.conn.rollback()
            self.logger.exception(f"Preview blob failed: %s", e)
            QMessageBox.critical(self, "Custom Field Error", f"Failed to preview file:\n{e}")

    def _do_prev(self, row, col):
        self._preview_blob_for_cell(row, col)############################################################################

    def _preview_blob_bytes(self, data, title: str) -> None:
        # Unwrap tuple returns: (bytes|memoryview, optional_mime)
        provided_mime = ""
        if isinstance(data, tuple):
            if len(data) >= 1:
                data_bytes = data[0]
            if len(data) >= 2 and isinstance(data[1], str):
                provided_mime = data[1]
            data = data_bytes
        if isinstance(data, memoryview):
            data = data.tobytes()

        # Prefer provided MIME if present and plausible
        mime = provided_mime.lower().strip() if provided_mime else ""
        if not (mime.startswith("audio/") or mime.startswith("image/")):
            mime = (self._detect_mime(data) or "").lower()

        # Try image decode first regardless of mime: cheap and robust
        try:
            img = QImage.fromData(data)
            if not img.isNull():
                self._open_image_preview(data, title)
                return
        except Exception:
            pass

        # Audio path if mime says audio, otherwise try common audio fallback
        audio_mime = mime if mime.startswith("audio/") else ""
        if not audio_mime:
            # Heuristic: raw looks not like image and not empty -> try wav
            audio_mime = "audio/wav"

        self._open_audio_preview(data, audio_mime, title)


    def _detect_mime(self, b: bytes) -> str:
        # --- images ---
        if len(b) >= 8 and b[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if len(b) >= 2 and b[:2] == b"\xFF\xD8":
            return "image/jpeg"
        if len(b) >= 6 and b[:6] in (b"GIF89a", b"GIF87a"):
            return "image/gif"
        if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            return "image/webp"

        # --- audio ---
        if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WAVE":
            return "audio/wav"
        if len(b) >= 4 and b[:4] == b"fLaC":
            return "audio/flac"
        if len(b) >= 4 and b[:4] == b"OggS":
            if b"OpusHead" in b[:64]:
                return "audio/opus"
            return "audio/ogg"
        # MP3: ID3 header or MPEG frame sync (common cases)
        if len(b) >= 3 and b[:3] == b"ID3":
            return "audio/mpeg"
        if len(b) >= 2 and (b[0] == 0xFF and (b[1] & 0xE0) == 0xE0):
            return "audio/mpeg"

        return ""

    def _open_image_preview(self, data: bytes, title: str) -> None:
        img = QImage.fromData(data)
        if img.isNull():
            QMessageBox.warning(self, "Preview", "Could not decode image data.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Image preview — {title}")
        layout = QVBoxLayout(dlg)

        # Zoom row
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("Zoom"))
        zoom_slider = QSlider(Qt.Horizontal)
        zoom_slider.setRange(10, 400)   # percent
        zoom_value_lbl = QLabel("")
        zoom_row.addWidget(zoom_slider, 1)
        zoom_row.addWidget(zoom_value_lbl)
        layout.addLayout(zoom_row)

        # Image area
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        base_pix = QPixmap.fromImage(img)

        sc = QScrollArea()
        sc.setWidget(lbl)
        sc.setWidgetResizable(True)
        layout.addWidget(sc, 1)

        dlg.resize(960, 720)

        def fit_percent():
            avail_w = max(1, dlg.width() - 40)
            avail_h = max(1, dlg.height() - 120)
            sx = avail_w / max(1, base_pix.width())
            sy = avail_h / max(1, base_pix.height())
            pct = int(max(10, min(100, (min(sx, sy) * 100))))
            return pct

        current_pct = fit_percent()
        zoom_slider.setValue(current_pct)
        zoom_value_lbl.setText(f"{current_pct}%")

        def apply_zoom(pct: int):
            nonlocal current_pct
            current_pct = max(10, min(400, int(pct)))
            zoom_value_lbl.setText(f"{current_pct}%")
            w = max(1, int(base_pix.width() * (current_pct / 100.0)))
            h = max(1, int(base_pix.height() * (current_pct / 100.0)))
            lbl.setPixmap(base_pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        apply_zoom(current_pct)

        zoom_slider.valueChanged.connect(apply_zoom)

        _user_zoomed = {"touched": False}
        def on_slider_touched():
            _user_zoomed["touched"] = True
        zoom_slider.sliderPressed.connect(on_slider_touched)

        def on_resize(e):
            if not _user_zoomed["touched"]:
                apply_zoom(fit_percent())
            QDialog.resizeEvent(dlg, e)
        dlg.resizeEvent = on_resize

        dlg.exec()


    # =============================================================================
    # Copy selection helper
    # =============================================================================
    def _copy_selection_to_clipboard(self, include_headers: bool = False):
        view = self.table
        sel_model = view.selectionModel()
        # If nothing selected, copy entire table
        if not sel_model.hasSelection():
            view.selectAll()
        # Try preferred rectangular ranges
        rows_out = []
        ranges = getattr(view, "selectedRanges", lambda: [])()
        if ranges:
            for r in ranges:
                r0, r1 = r.topRow(), r.bottomRow()
                c0, c1 = r.leftColumn(), r.rightColumn()
                if include_headers:
                    header_texts = []
                    for c in range(c0, c1 + 1):
                        header_item = view.horizontalHeaderItem(c)
                        header_texts.append(header_item.text() if header_item is not None else str(view.model().headerData(c, Qt.Horizontal)))
                    rows_out.append("\t".join(header_texts))
                for row in range(r0, r1 + 1):
                    cells = []
                    for col in range(c0, c1 + 1):
                        item = view.item(row, col)
                        cells.append("" if item is None else str(item.text()))
                    rows_out.append("\t".join(cells))
            QApplication.clipboard().setText("\n".join(rows_out))
            return
        # Generic path: fill rectangle from selected indexes
        indexes = sorted(sel_model.selectedIndexes(), key=lambda i: (i.row(), i.column()))
        if not indexes:
            QApplication.clipboard().setText("")
            return
        r0, r1 = indexes[0].row(), indexes[-1].row()
        c0, c1 = min(i.column() for i in indexes), max(i.column() for i in indexes)
        idx_set = {(i.row(), i.column()): i for i in indexes}
        if include_headers:
            header_texts = []
            for c in range(c0, c1 + 1):
                header_item = view.horizontalHeaderItem(c)
                header_texts.append(header_item.text() if header_item is not None else str(view.model().headerData(c, Qt.Horizontal)))
            rows_out.append("\t".join(header_texts))
        for r in range(r0, r1 + 1):
            line = []
            for c in range(c0, c1 + 1):
                idx = idx_set.get((r, c))
                if idx is None:
                    line.append("")
                else:
                    line.append(view.model().data(idx, Qt.DisplayRole) or "")
            rows_out.append("\t".join(line))
        QApplication.clipboard().setText("\n".join(rows_out))

    # =============================================================================
    # Table header order persistence
    # =============================================================================
    def _table_settings_prefix(self) -> str:
        """Per-profile (per-DB) settings namespace for table header state."""
        db = getattr(self, "current_db_path", "") or ""
        h = hashlib.sha1(db.encode("utf-8")).hexdigest()[:8]
        return f"table/{h}"


    def _toggle_columns_movable(self, enabled: bool):
        try:
            def mutation():
                self.table.horizontalHeader().setSectionsMovable(bool(enabled))
                self._save_header_state(record_history=False)
                self.settings.setValue(f"{self._table_settings_prefix()}/columns_movable", bool(enabled))
                self.settings.sync()

            self._run_setting_bundle_history_action(
                action_label="Toggle Column Reordering",
                setting_keys=self._table_setting_keys(include_columns_movable=True),
                mutation=mutation,
                entity_id=f"{self._table_settings_prefix()}/columns_movable",
            )
        except Exception as e:
            logging.warning("Exception while toggling columns movable: %s", e)
            pass


    def _save_header_state(self, *, record_history: bool = True):
        try:
            def mutation():
                header = self.table.horizontalHeader()
                state = header.saveState()
                prefix = self._table_settings_prefix()

                # Native state
                self.settings.setValue(f"{prefix}/header_state", state)

                # Visual label order (robust fallback)
                m = self.table.model()
                logicals = list(range(m.columnCount()))
                visual_order = sorted(logicals, key=lambda li: header.visualIndex(li))
                labels_visual = [
                    str(m.headerData(li, Qt.Horizontal, Qt.DisplayRole) or "")
                    for li in visual_order
                ]
                self.settings.setValue(f"{prefix}/header_labels", labels_visual)
                try:
                    self.settings.setValue(f"{prefix}/header_labels_json", json.dumps(labels_visual))
                except Exception as e:
                    self.logger.warning("Failed to save header visual order JSON: %s", e)

                self.settings.sync()

            if record_history:
                self._run_setting_bundle_history_action(
                    action_label="Update Table Layout",
                    setting_keys=self._table_setting_keys(include_columns_movable=False),
                    mutation=mutation,
                    entity_id=self._table_settings_prefix(),
                )
            else:
                mutation()
        except Exception as e:
            self.logger.exception("Error saving header state: %s", e)

    def _load_header_state(self):
        header = None
        old_signal_state = False
        try:
            header = self.table.horizontalHeader()
            prefix = self._table_settings_prefix()
            old_signal_state = header.blockSignals(True)

            # Current labels after (re)building headers — includes any new custom fields
            current_labels = [
                self.table.horizontalHeaderItem(i).text()
                for i in range(self.table.columnCount())
            ]

            # Our robust, visual-order fallback list from last save
            saved_labels = self.settings.value(f"{prefix}/header_labels", [], list)

            # Native state blob (may be stale when columns changed)
            state = self.settings.value(f"{prefix}/header_state", None, QByteArray)

            # Only apply native restore if the label sets match (prevents dropping new columns)
            if isinstance(state, QByteArray) and not state.isEmpty():
                if saved_labels and set(saved_labels) == set(current_labels):
                    if header.restoreState(state):
                        return  # done; perfect match
                # else: mismatch → skip native restore on purpose

            # Fallback: reorder by labels we know; any new labels remain visible at the end
            if saved_labels:
                # Map the first occurrence of each label to its current logical index
                seen_pos = {}
                target_logicals = []
                for lbl in saved_labels:
                    start = seen_pos.get(lbl, 0)
                    try:
                        idx = current_labels.index(lbl, start)
                    except ValueError:
                        continue  # label no longer exists
                    target_logicals.append(idx)
                    seen_pos[lbl] = idx + 1

                # Move sections to match saved visual order for known labels
                for visual_pos, logical in enumerate(target_logicals):
                    cur_visual = header.visualIndex(logical)
                    if cur_visual != -1 and cur_visual != visual_pos:
                        header.moveSection(cur_visual, visual_pos)

            # No exception: leave new columns as-is (visible at the end)
        except Exception as e:
            self.logger.exception("Error loading header state: %s", e)
        finally:
            try:
                if header is not None:
                    header.blockSignals(old_signal_state)
            except Exception:
                pass

    # =============================================================================
    # DB backup / restore / verify (RC blocker #7)
    # =============================================================================

    def backup_database(self):
        """Create a full-fidelity backup of the current SQLite database.

        This uses the SQLite Online Backup API when available to capture the
        **entire** database (all tables, custom columns, indexes, triggers, data).
        If that fails (older Python/SQLite), it falls back to `VACUUM INTO`,
        and finally to a safe file copy after closing the connection.
        """
        try:
            src = Path(self.current_db_path)
            if not src.exists():
                QMessageBox.warning(self, "Backup", "No current database to backup.")
                return

            result = self.database_maintenance.create_backup(
                self.conn,
                src,
                close_connection=self._close_database_connection,
                reopen_connection=lambda: self.open_database(str(src)),
            )

            QMessageBox.information(self, "Backup", f"Backup created:\n{result.backup_path}")
            self.logger.info(f"Database backed up to {result.backup_path} using {result.method}")
            try:
                self._audit(
                    "BACKUP",
                    "DB",
                    ref_id=str(result.backup_path),
                    details=f"Full DB (schema+data), method={result.method}",
                )
                self._audit_commit()
            except Exception:
                pass
            before_state = {
                "target_path": str(result.backup_path),
                "companion_suffixes": list(self.history_manager.FILE_COMPANION_SUFFIXES),
                "exists": False,
                "files": [],
            }
            after_state = self.history_manager.capture_file_state(
                result.backup_path,
                companion_suffixes=self.history_manager.FILE_COMPANION_SUFFIXES,
            )
            self.history_manager.record_file_write_action(
                label="Create Database Backup",
                action_type="file.db_backup",
                target_path=result.backup_path,
                before_state=before_state,
                after_state=after_state,
                entity_type="DB",
                entity_id=str(result.backup_path),
                payload={"path": str(result.backup_path), "method": result.method},
            )
            self._refresh_history_actions()

        except Exception as e:
            self.logger.exception(f"Backup failed: {e}")
            QMessageBox.critical(self, "Backup Error", f"Failed to backup:\n{e}")

    def verify_integrity(self):
        try:
            res = self.database_maintenance.verify_integrity(self.current_db_path)
            QMessageBox.information(self, "Integrity Check", f"Result: {res}")
            self.logger.info(f"Integrity check: {res}")
            self._audit("VERIFY", "DB", ref_id=self.current_db_path, details=res)
            self._audit_commit()
            self.history_manager.record_event(
                label=f"Verify Integrity: {res}",
                action_type="db.verify",
                entity_type="DB",
                entity_id=str(self.current_db_path),
                payload={"result": res, "path": str(self.current_db_path)},
            )
        except Exception as e:
            self.logger.exception(f"Integrity check failed: {e}")
            QMessageBox.critical(self, "Integrity Error", f"Failed to verify:\n{e}")


    def restore_database(self):
        """Restore the database from a backup .db file.

        This completely replaces the current DB file with the selected backup,
        ensuring that **all** schema (including user-added columns) and data are restored.
        """
        pre_restore_snapshot = None
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, "Restore...Backup", str(self.backups_dir), "SQLite DB (*.db)"
            )
            if not path:
                return

            # Extra confirmation
            if QMessageBox.question(
                self, "Restore",
                f"This will replace your current database with:\n{path}\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No
            ) != QMessageBox.Yes:
                return

            if self.history_manager is not None:
                pre_restore_snapshot = self.history_manager.capture_snapshot(
                    kind="pre_db_restore",
                    label=f"Before Database Restore: {Path(path).name}",
                )

            self._close_database_connection()
            result = self.database_maintenance.restore_database(path, self.current_db_path)
            self.open_database(str(result.restored_path))

            self.refresh_table_preserve_view()
            QMessageBox.information(self, "Restore", "Database restored successfully (schema + data).")
            self.logger.warning(f"Database restored from {path}")
            try:
                details = f"restored to {result.restored_path}"
                if result.safety_copy_path is not None:
                    details += f"; safety_copy={result.safety_copy_path}"
                self._audit("RESTORE", "DB", ref_id=path, details=details)
                self._audit_commit()
            except Exception:
                pass
            payload = {
                "source_backup": str(path),
                "restored_path": str(result.restored_path),
                "safety_copy_path": str(result.safety_copy_path) if result.safety_copy_path else None,
            }
            if result.safety_copy_path is not None and self.history_manager is not None:
                payload["file_effects"] = [
                    {
                        "target_path": str(result.safety_copy_path),
                        "before_state": {
                            "target_path": str(result.safety_copy_path),
                            "companion_suffixes": list(self.history_manager.FILE_COMPANION_SUFFIXES),
                            "exists": False,
                            "files": [],
                        },
                        "after_state": self.history_manager.capture_file_state(
                            result.safety_copy_path,
                            companion_suffixes=self.history_manager.FILE_COMPANION_SUFFIXES,
                        ),
                    }
                ]
            if pre_restore_snapshot is not None and self.history_manager is not None:
                registered_before = self.history_manager.register_snapshot(
                    pre_restore_snapshot,
                    kind="pre_db_restore_registered",
                    label=pre_restore_snapshot.label,
                )
                after_snapshot = self.history_manager.capture_snapshot(
                    kind="post_db_restore",
                    label=f"After Database Restore: {Path(path).name}",
                )
                self.history_manager.record_snapshot_action(
                    label="Restore Database from Backup",
                    action_type="db.restore",
                    entity_type="DB",
                    entity_id=str(path),
                    payload=payload,
                    snapshot_before_id=registered_before.snapshot_id,
                    snapshot_after_id=after_snapshot.snapshot_id,
                )
            elif self.history_manager is not None:
                self.history_manager.record_event(
                    label="Restore Database from Backup",
                    action_type="db.restore",
                    entity_type="DB",
                    entity_id=str(path),
                    payload=payload,
                )
            self._refresh_history_actions()

        except Exception as e:
            self.logger.exception(f"Restore failed: {e}")
            QMessageBox.critical(self, "Restore Error", f"Failed to restore:\n{e}")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.delete_entry()
        elif event.key() == Qt.Key_Escape:
            self.init_form()
            self.reset_search()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            # Only save when the Add Data panel is active AND focus is inside that panel
            panel_enabled = getattr(self, "add_data_action", None) and self.add_data_action.isChecked()
            if panel_enabled and self._form_has_focus():
                self.save()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, source, event):
        """Ensure we return a bool. Handle table key events here."""
        if source is self.table and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Space:
                idx = self.table.currentIndex()
                if idx.isValid():
                    self._preview_blob_for_cell(idx.row(), idx.column())
                event.accept()
                return True  # IMPORTANT: return bool to satisfy Qt
        # Defer to base for unhandled events
        return super().eventFilter(source, event)

# =============================================================================
# Edit Dialog (with Copy ISO / Copy compact buttons) + compact sync
# =============================================================================

    # ---------------------- BLOB CF helpers (DB IO + export) ----------------------
    def cf_get_field_type(self, field_def_id: int) -> str:
        return self.custom_field_definitions.get_field_type(field_def_id)

    def cf_save_value(self, track_id: int, field_def_id: int, *, value=None, blob_path: str|None=None):
        self.custom_field_values.save_value(track_id, field_def_id, value=value, blob_path=blob_path)

    def _attach_blob_for_cell(self, track_id: int, field_def_id: int, field_type: str, field_name: str):
        if field_type == "blob_image":
            flt = "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff);;All files (*)"
        else:
            flt = "Audio (*.wav *.aif *.aiff *.mp3 *.flac *.m4a *.aac *.ogg *.opus);;All files (*)"
        p, _ = QFileDialog.getOpenFileName(self, f"Attach file: {field_name}", "", flt)
        if not p:
            return
        try:
            self._run_snapshot_history_action(
                action_label=f"Attach Custom File: {field_name}",
                action_type="custom_field.blob_attach",
                entity_type="CustomFieldValue",
                entity_id=f"{track_id}:{field_def_id}",
                payload={"track_id": track_id, "field_id": field_def_id, "field_name": field_name},
                mutation=lambda: self.cf_save_value(track_id, field_def_id, value=None, blob_path=p),
            )
            self.refresh_table_preserve_view(focus_id=track_id)
        except Exception as e:
            self.conn.rollback()
            self.logger.exception(f"Attach blob failed: {e}")
            QMessageBox.critical(self, "Custom Field Error", f"Failed to attach file:\n{e}")

    # ---------------------- BLOB CF helpers v2 (get/export/delete/format) ----------------------
    def cf_get_value_meta(self, track_id: int, field_def_id: int):
        return self.custom_field_values.get_value_meta(track_id, field_def_id)

    def cf_has_blob(self, track_id: int, field_def_id: int) -> bool:
        return self.custom_field_values.has_blob(track_id, field_def_id)

    def cf_blob_size(self, track_id: int, field_def_id: int) -> int:
        return self.custom_field_values.blob_size(track_id, field_def_id)

    def cf_fetch_blob(self, track_id: int, field_def_id: int):
        return self.custom_field_values.fetch_blob(track_id, field_def_id)

    def cf_export_blob(self, track_id: int, field_def_id: int, parent_widget=None, suggested_basename: str|None=None):
        try:
            data, mime = self.cf_fetch_blob(track_id, field_def_id)
        except Exception as e:
            QMessageBox.critical(parent_widget or None, "Export failed", str(e))
            return
        # choose extension
        ext = None
        if mime:
            import mimetypes as _m
            ext = _m.guess_extension(mime) or None
        if not ext:
            ext = ".png" if (mime and mime.startswith("image/")) else (".wav" if (mime and mime.startswith("audio/")) else ".bin")
        if suggested_basename is None:
            suggested_basename = self.custom_field_definitions.get_field_name(field_def_id)
        default_filename = f"{suggested_basename}{ext}"
        dest_path, _ = QFileDialog.getSaveFileName(parent_widget or None, "Export file", default_filename, "All files (*)")
        if not dest_path:
            return
        try:
            self._run_file_history_action(
                action_label=f"Export Custom File: {Path(dest_path).name}",
                action_type="file.export_custom_blob",
                target_path=dest_path,
                mutation=lambda: Path(dest_path).write_bytes(data),
                entity_type="CustomFieldValue",
                entity_id=f"{track_id}:{field_def_id}",
                payload={"path": str(dest_path), "track_id": track_id, "field_id": field_def_id},
            )
            QMessageBox.information(parent_widget or None, "Export", f"Saved:\n{dest_path}")
        except Exception as e:
            QMessageBox.critical(parent_widget or None, "Export failed", str(e))

    def cf_delete_blob(self, track_id: int, field_def_id: int):
        self.custom_field_values.delete_blob(track_id, field_def_id)

    def _human_size(self, n: int) -> str:
        try:
            n = int(n or 0)
        except Exception:
            n = 0
        thresh = 1024.0
        units = ["B","KB","MB","GB","TB"]
        u = 0
        val = float(n)
        while val >= thresh and u < len(units)-1:
            val /= thresh
            u += 1
        return f"{val:.0f} {units[u]}" if u==0 else f"{val:.1f} {units[u]}"

    def _format_blob_badge(self, mime_type: str|None, size_bytes: int) -> str:
        icon = "🖼️" if (mime_type and mime_type.startswith("image/")) else ("🎵" if (mime_type and mime_type.startswith("audio/")) else "📎")
        return f"{icon} {self._human_size(size_bytes)}"


    def _row_for_id(self, track_id: int) -> int:
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.text().isdigit() and int(it.text()) == track_id:
                return r
        return -1

    def _custom_field_index_by_id(self, field_id: int) -> int:
        for i, f in enumerate(self.active_custom_fields):
            if f.get("id") == field_id:
                return i
        return -1

    def _get_track_title(self, track_id: int) -> str:
        return self.track_service.fetch_track_title(track_id, cursor=self.cursor)

    def _sanitize_filename(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return "file"
        cleaned = re.sub(r'[<>:"/\\\\|?*\\x00-\\x1f]+', "_", text)
        cleaned = re.sub(r"\\s+", " ", cleaned).strip().rstrip(".")
        return cleaned or "file"

    def _set_blob_indicator(self, row: int, col: int, track_id: int, field_id: int) -> None:
        try:
            meta = self.cf_get_value_meta(track_id, field_id)
        except Exception:
            meta = {"has_blob": False, "mime_type": None, "size_bytes": 0}
        display = self._format_blob_badge(meta.get("mime_type"), meta.get("size_bytes", 0)) if meta.get("has_blob") else "—"
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem(display)
            self.table.setItem(row, col, item)
        else:
            item.setText(display)
        # optional: set an icon here if you have one available
        item.setData(Qt.UserRole, (track_id, field_id) if meta.get("has_blob") else None)

    def _get_row_pk(self, row: int) -> int | None:
        """Return the primary key for a visual row, preferring Qt.UserRole on column 0."""
        it = self.table.item(row, 0)
        if not it:
            return None
        val = it.data(Qt.UserRole)
        if isinstance(val, int):
            return val
        try:
            return int(str(it.text()).strip())
        except Exception:
            return None

    def _apply_blob_badges(self):
        """Deterministically compute blob badges from source, not cached meta."""
        base = len(self.BASE_HEADERS)
        total_rows = self.table.rowCount()
        for row_idx in range(total_rows):
            # Resolve PK for this visual row
            pk = self._get_row_pk(row_idx) if hasattr(self, "_get_row_pk") else None
            if pk is None:
                id_item = self.table.item(row_idx, 0)
                if not id_item:
                    continue
                try:
                    pk = int(id_item.text())
                except Exception:
                    continue

            # Walk active custom fields by display order
            for j, cf in enumerate(self.active_custom_fields):
                col = base + j
                ftype = str(cf.get("field_type", "")).lower()
                if ftype not in ("blob_image", "blob_audio"):
                    continue

                has_blob = False
                size_bytes = 0
                mime = None
                try:
                    # First: a fast existence check
                    has_blob = bool(self.cf_has_blob(pk, cf["id"]))
                except Exception:
                    has_blob = False

                if has_blob:
                    # Try a cheap size metadata call; else fetch once and compute
                    try:
                        size_bytes = int(self.cf_blob_size(pk, cf["id"]))
                    except Exception:
                        try:
                            blob = self.cf_fetch_blob(pk, cf["id"])
                            data = blob[0] if isinstance(blob, tuple) else blob
                            if isinstance(data, memoryview):
                                data = data.tobytes()
                            size_bytes = len(data) if isinstance(data, (bytes, bytearray)) else 0
                            mime = self._detect_mime(data) if size_bytes else None
                        except Exception:
                            size_bytes = 0
                            mime = None

                display = self._format_blob_badge(mime, size_bytes) if has_blob else "—"
                item = self.table.item(row_idx, col)
                if item is None:
                    item = QTableWidgetItem(display)
                    self.table.setItem(row_idx, col, item)
                else:
                    item.setText(display)
                item.setData(Qt.UserRole, (pk, cf["id"]) if has_blob else None)


    def _make_default_export_filename(self, track_id: int, field_def: dict, mime: str) -> str:
        # Use track title only
        title = self._get_track_title(track_id)
        base = self._sanitize_filename(title)

        # Extension from MIME type
        ext = mimetypes.guess_extension(mime or "")
        if not ext:
            ext = ".bin"
        return base + ext

    def _open_audio_preview(self, data: bytes, mime: str, title: str) -> None:
        ext = {
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "audio/ogg": ".ogg",
            "audio/opus": ".opus",
            "audio/flac": ".flac",
        }.get(mime, ".bin")

        try:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            tf.write(data); tf.flush(); tf.close()
        except Exception as e:
            QMessageBox.critical(self, "Preview", f"Could not create temp file: {e}")
            return

        dlg = _AudioPreviewDialog(self, tf.name, title)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)   # cleanup on close
        dlg.setWindowFlag(Qt.Window, True)            # make it a top-level window
        dlg.setModal(False)                           # explicitly non-modal
        dlg.show()
        dlg._player.play()

    def _list_all_tracks(self):
        return self.catalog_reads.list_tracks()

    def _list_licensees(self):
        return self.catalog_service.list_licensee_choices()

    def open_license_upload(self, preselect_track_id=None):
        dlg = LicenseUploadDialog(
            self.license_service,
            self._list_all_tracks(),
            self._list_licensees(),
            preselect_track_id=preselect_track_id,
            parent=self,
        )
        dlg.saved.connect(lambda: self.statusBar().showMessage("License saved", 3000))
        dlg.exec()

    def open_licenses_browser(self, track_filter_id=None):
        LicensesBrowserDialog(self.license_service, track_filter_id=track_filter_id, parent=self).exec()


class EditDialog(QDialog):
    """Edits a single Track row (base columns only)."""
    def __init__(self, row_data, parent: App):
        super().__init__(parent)
        self.parent = parent        

        self.setWindowTitle("Edit Entry")
        self.setModal(True)

        # === Main dialog layout ===
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # === Scrollable form container (single layout; do NOT replace later) ===
        self._form_container = QWidget(self)
        form_layout = QVBoxLayout()
        form_layout.setContentsMargins(6, 6, 6, 6)
        form_layout.setSpacing(8)
        self._form_container.setLayout(form_layout)

        def add_row(label_text, w):
            row = QVBoxLayout()
            lbl = QLabel(label_text)
            row.addWidget(lbl)
            row.addWidget(w)
            form_layout.addLayout(row)

        # Safe accessor for row_data
        def _val(i):
            try:
                return row_data[i] if row_data[i] is not None else ""
            except Exception:
                return ""

        # --- ISRC (read-only) ---
        self.isrc_field = QLineEdit(str(_val(1)))
        add_row("ISRC", self.isrc_field)

        row_isrc_btns = QHBoxLayout()
        btn_isrc_copy_iso = QPushButton("Copy ISO")
        btn_isrc_copy_compact = QPushButton("Copy compact")
        row_isrc_btns.addWidget(btn_isrc_copy_iso)
        row_isrc_btns.addWidget(btn_isrc_copy_compact)
        form_layout.addLayout(row_isrc_btns)
        btn_isrc_copy_iso.clicked.connect(self._copy_isrc_iso)
        btn_isrc_copy_iso.setDefault(False)
        btn_isrc_copy_compact.clicked.connect(self._copy_isrc_compact)

        # --- Entry Date (read-only) ---
        self.entry_date_field = QLineEdit(str(_val(2)))
        self.entry_date_field.setReadOnly(True)
        add_row("Entry Date", self.entry_date_field)

        # --- Track Title ---
        self.track_title = QLineEdit(str(_val(3)))
        add_row("Track Title", self.track_title)

        def combo(label, value, source_query, allow_empty=True):
            cb = QComboBox()
            cb.setEditable(True)
            items = [r[0] for r in self.parent.cursor.execute(source_query).fetchall()]
            if allow_empty:
                cb.addItem("")
            cb.addItems(items)
            cb.setCurrentText(value)
            comp = QCompleter(items)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            cb.setCompleter(comp)
            add_row(label, cb)
            return cb

        self.artist_name = combo("Artist", row_data[4], "SELECT DISTINCT name FROM Artists ORDER BY name", allow_empty=False)
        self.additional_artist = combo("Additional Artist(s)", row_data[5], "SELECT DISTINCT name FROM Artists ORDER BY name")
        self.album_title = combo("Album Title", row_data[6], "SELECT DISTINCT title FROM Albums ORDER BY title")
        self.genre = combo('Genre', row_data[11], "SELECT DISTINCT genre FROM Tracks WHERE genre IS NOT NULL AND genre != '' ORDER BY genre")
            


        # --- Release Date ---
        self.release_date = QCalendarWidget()
        self.release_date.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.release_date.setMaximumHeight(320)
        # parse existing date
        d = None
        try:
            s = str(_val(7)).strip()
            if s:
                for fmt in ("dd-MMM-yyyy", "yyyy-MM-dd", "dd/MM/yyyy", "dd-MM-yyyy"):
                    qd = QDate.fromString(s, fmt)
                    if qd.isValid():
                        d = qd
                        break
        except Exception:
            d = None
        self.release_date.setSelectedDate(d if d and d.isValid() else QDate.currentDate())
        add_row("Release Date", self.release_date)

        # --- Track Length (hh:mm:ss) ---
        self.len_h = TwoDigitSpinBox(); self.len_h.setRange(0, 99);  self.len_h.setFixedWidth(60)
        self.len_m = TwoDigitSpinBox(); self.len_m.setRange(0, 59);  self.len_m.setFixedWidth(50)
        self.len_s = TwoDigitSpinBox(); self.len_s.setRange(0, 59);  self.len_s.setFixedWidth(50)
        try:
            parts = str(_val(8)).split(":")
            if len(parts) == 3:
                self.len_h.setValue(int(parts[0]) if parts[0].isdigit() else 0)
                self.len_m.setValue(int(parts[1]) if parts[1].isdigit() else 0)
                self.len_s.setValue(int(parts[2]) if parts[2].isdigit() else 0)
        except Exception:
            pass
        tl = QHBoxLayout()
        tl.addWidget(self.len_h); tl.addWidget(QLabel(":"))
        tl.addWidget(self.len_m); tl.addWidget(QLabel(":"))
        tl.addWidget(self.len_s)
        tlw = QWidget(); tlw.setLayout(tl)
        add_row("Track Length (hh:mm:ss)", tlw)

        # --- ISWC / UPC / Genre ---
        self.iswc = QLineEdit(str(_val(9)))
        add_row("ISWC", self.iswc)

        row_iswc_btns = QHBoxLayout()
        btn_iswc_copy_iso = QPushButton("Copy ISO")
        btn_iswc_copy_compact = QPushButton("Copy compact")
        row_iswc_btns.addWidget(btn_iswc_copy_iso)
        row_iswc_btns.addWidget(btn_iswc_copy_compact)
        form_layout.addLayout(row_iswc_btns)
        btn_iswc_copy_iso.clicked.connect(self._copy_iswc_iso)
        btn_iswc_copy_iso.setDefault(False)
        btn_iswc_copy_compact.clicked.connect(self._copy_iswc_compact)

        self.upc = QLineEdit(str(_val(10)))
        add_row("UPC/EAN", self.upc)

        add_row("Genre", self.genre)

        # === Scroll area ===
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._form_container)
        main_layout.addWidget(scroll, 1)

        # === Buttons (outside scroll, always visible) ===
        btns = QHBoxLayout()
        btns.addStretch(1)
        save_btn = QPushButton("Save Changes")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.save_changes)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        main_layout.addLayout(btns)

        self.resize(400, 650)

    # --- Copy helpers ---
    def _copy_isrc_iso(self):
        txt = (self.isrc_field.text() or "").strip()
        iso = to_iso_isrc(txt) or txt
        QApplication.clipboard().setText(iso)

    def _copy_isrc_compact(self):
        txt = (self.isrc_field.text() or "").strip()
        compact = to_compact_isrc(txt)
        QApplication.clipboard().setText(compact or normalize_isrc(txt))

    def _copy_iswc_iso(self):
        txt = (self.iswc.text() or "").strip()
        iso = to_iso_iswc(txt) or txt
        QApplication.clipboard().setText(iso)

    def _copy_iswc_compact(self):
        txt = (self.iswc.text() or "").strip()
        compact = normalize_iswc(txt)
        QApplication.clipboard().setText(compact)


    def save_changes(self):
        new_isrc_raw = (self.isrc_field.text() or "").strip()
        new_iswc_raw = (self.iswc.currentText() if hasattr(self.iswc, "currentText") else self.iswc.text()).strip()
        new_upc_raw  = (self.upc.currentText() if hasattr(self.upc, "currentText") else self.upc.text()).strip()
        new_genre    = (self.genre.currentText() if hasattr(self.genre, "currentText") else self.genre.text()).strip()
        new_track_title = (self.track_title.text() or "").strip()
        new_additional_artist = self.parent._parse_additional_artists((self.additional_artist.currentText() if hasattr(self.additional_artist, "currentText") else self.additional_artist.text()).strip())


        iso_isrc = to_iso_isrc(new_isrc_raw)
        comp = to_compact_isrc(iso_isrc)
        if not comp or not is_valid_isrc_compact_or_iso(iso_isrc):
            QMessageBox.warning(self, "Invalid ISRC", "ISRC must look like CCXXXYYNNNNN or CC-XXX-YY-NNNNN.")
            return

        iso_iswc = None
        if new_iswc_raw:
            iso_iswc = to_iso_iswc(new_iswc_raw)
            if not iso_iswc or not is_valid_iswc_any(iso_iswc):
                QMessageBox.warning(
                    self, "Invalid ISWC",
                    "ISWC must be like T-123.456.789-0 or T1234567890 (checksum 0–9 or X), or leave empty."
                )
                return

        if is_blank(self.track_title.text()) or is_blank(self.artist_name.currentText()):
            QMessageBox.warning(self, "Missing data", "Track Title and Artist are required.")
            return

        if new_upc_raw and not valid_upc_ean(new_upc_raw):
            QMessageBox.warning(self, "Invalid UPC/EAN", "UPC/EAN must be 12 or 13 digits (or leave empty).")
            return

        try:
            parent = self.parentWidget() 
            if parent is None:
                QMessageBox.critical(self, "Update Error", "No parent window set.")
                return

            current_row = parent.table.currentRow()
            if current_row < 0:
                QMessageBox.warning(self, "No selection", "No row selected in table.")
                return

            row_item = parent.table.item(current_row, 0)
            if row_item is None:
                QMessageBox.warning(self, "Invalid row", "Could not determine record ID.")
                return
            row_id = int(parent.table.item(parent.table.currentRow(), 0).text())
            before_snapshot = parent.track_service.fetch_track_snapshot(row_id)
            if before_snapshot is None:
                QMessageBox.warning(self, "Update Error", "Could not load the selected track.")
                return

            if parent.is_isrc_taken_normalized(iso_isrc, exclude_track_id=row_id):
                QMessageBox.critical(self, "Duplicate ISRC", "Another record already uses this ISRC.")
                return

            cleanup_artist_names, cleanup_album_titles = parent._collect_catalog_cleanup_targets(
                artist_name=self.artist_name.currentText(),
                additional_artists=new_additional_artist,
                album_title=self.album_title.currentText().strip() or None,
            )
            parent.track_service.update_track(
                TrackUpdatePayload(
                    track_id=row_id,
                    isrc=iso_isrc,
                    track_title=new_track_title,
                    artist_name=self.artist_name.currentText(),
                    additional_artists=new_additional_artist,
                    album_title=self.album_title.currentText().strip() or None,
                    release_date=self.release_date.selectedDate().toString("yyyy-MM-dd"),
                    track_length_sec=hms_to_seconds(self.len_h.value(), self.len_m.value(), self.len_s.value()),
                    iswc=(iso_iswc or None),
                    upc=(new_upc_raw or None),
                    genre=(new_genre or None),
                )
            )
            # --- patched: ensure WAL contents are flushed to the main db file ---
            parent.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

            try:
                parent.logger.info(f"Track updated id={row_id} isrc={iso_isrc}")
                parent._audit("UPDATE", "Track", ref_id=row_id, details=f"isrc={iso_isrc}")
                parent._audit_commit()
            except Exception as audit_err:
                parent.logger.warning(f"Audit failed: {audit_err}")

            parent.history_manager.record_track_update(
                before_snapshot=before_snapshot,
                cleanup_artist_names=cleanup_artist_names,
                cleanup_album_titles=cleanup_album_titles,
            )
            parent._refresh_history_actions()

            parent.refresh_table_preserve_view(focus_id=row_id)
            self.accept()

        except Exception as e:
            parent = self.parentWidget()
            if parent and hasattr(parent, "conn"):
                parent.conn.rollback()
                parent.logger.exception(f"Update failed: {e}")
            QMessageBox.critical(self, "Update Error", f"Failed to update record:\n{e}")


class _AudioPreviewDialog(QDialog):
    def __init__(self, parent, file_path: str, title: str):
        super().__init__(parent)
        self._tmp_path = file_path

        if platform.system().lower() == "darwin":
            os.environ.setdefault("PATH", "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", ""))
        elif platform.system().lower() == "windows":
            extra = [
                r"C:\Program Files\ffmpeg\bin",
                r"C:\ffmpeg\bin",
                r"C:\ProgramData\chocolatey\bin",                  # choco install ffmpeg
                os.path.expandvars(r"%USERPROFILE%\scoop\shims"),  # scoop install ffmpeg
            ]
            os.environ["PATH"] = ";".join([*extra, os.environ.get("PATH", "")])


        v = QVBoxLayout(self)

        # --- waveform ---
        self.wave = WaveformWidget(self)
        v.addWidget(self.wave)

        # transport row
        h = QHBoxLayout()
        btn_play = QPushButton("Play"); btn_pause = QPushButton("Pause"); btn_stop = QPushButton("Stop")
        h.addWidget(btn_play); h.addWidget(btn_pause); h.addWidget(btn_stop)
        v.addLayout(h)

        # --- audio backend ---
        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        self._player.setSource(QUrl.fromLocalFile(file_path))

        btn_play.clicked.connect(self._player.play)
        btn_pause.clicked.connect(self._player.pause)
        btn_stop.clicked.connect(self._player.stop)

        # REMOVE: self._player.positionChanged.connect(self._on_pos)
        self._player.durationChanged.connect(lambda d: self.wave.set_duration_ms(d))

        # smooth playhead
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(lambda: self.wave.set_playhead_ms(self._player.position()))
        self._player.playbackStateChanged.connect(
            lambda st: self._anim_timer.start() if st == QMediaPlayer.PlayingState else self._anim_timer.stop()
        )

        # slider + time
        self._slider = QSlider(Qt.Horizontal)
        self._label_time = QLabel("0:00 / 0:00")
        v.addWidget(self._slider); v.addWidget(self._label_time)

        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._slider.sliderMoved.connect(self._on_slider_moved)

        # load peaks for current width (fallback 480)
        self._peaks_src = file_path
        peaks = load_wav_peaks(file_path, max(self.wave.width(), 480))
        self.wave.set_peaks(peaks)

        if not peaks:
            self.wave.hide()
            self._peaks_src = None
            self.adjustSize()
        else:
            self._resize_timer = QTimer(self)
            self._resize_timer.setSingleShot(True)
            self._resize_timer.setInterval(50)
            self._resize_timer.timeout.connect(self._reload_peaks_for_current_width)
            self.resize(640, 220)

        self.setWindowTitle(f'Now playing: {title}')

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_resize_timer"):
            self._resize_timer.start()

    def _reload_peaks_for_current_width(self):
        if not self._peaks_src:
            return
        w = max(self.wave.width(), 100)
        self.wave.set_peaks(load_wav_peaks(self._peaks_src, w))

    # --- unchanged helpers ---
    def _on_duration_changed(self, dur):
        self._slider.setRange(0, dur)
        self._update_time_label(self._player.position(), dur)

    def _on_position_changed(self, pos):
        if not self._slider.isSliderDown():
            self._slider.setValue(pos)
        self._update_time_label(pos, self._player.duration())

    def _on_slider_moved(self, val):
        self._player.setPosition(val)

    def _update_time_label(self, pos, dur):
        def fmt(ms):
            s = ms // 1000
            return f"{s//60}:{s%60:02d}"
        self._label_time.setText(f"{fmt(pos)} / {fmt(dur)}")

    # --- new: hard teardown that actually releases the backend ---
    def _teardown_audio(self):
        try:
            if self._player.state() != QMediaPlayer.StoppedState:
                self._player.stop()
        except Exception:
            pass
        try:
            self._audio_out.stop()
        except Exception:
            pass
        try:
            # Fully detach to force backend release
            self._player.setAudioOutput(None)
        except Exception:
            pass
        try:
            self._player.setSource(QUrl())  # clears source
        except Exception:
            pass

    # Stop audio before removing tmp and closing
    def closeEvent(self, e):
        self._teardown_audio()
        try:
            os.remove(self._tmp_path)
        except Exception:
            pass
        super().closeEvent(e)

    # Also cover accept()/reject() paths
    def accept(self):
        self._teardown_audio()
        super().accept()

    def reject(self):
        self._teardown_audio()
        super().reject()


    # --- key handling ---
    def keyPressEvent(self, e):
        STEP_MS = 5000  # 5 s per key press

        if e.key() == Qt.Key_Space:
            PlayingState = getattr(QMediaPlayer, "PlaybackState", QMediaPlayer).PlayingState
            if self._player.playbackState() == PlayingState:
                self._player.pause()
            else:
                self._player.play()
            e.accept(); return

        elif e.key() == Qt.Key_Right:
            # Scrub forward
            new_pos = min(self._player.duration(), self._player.position() + STEP_MS)
            self._player.setPosition(new_pos)
            e.accept(); return

        elif e.key() == Qt.Key_Left:
            # Scrub backward
            new_pos = max(0, self._player.position() - STEP_MS)
            self._player.setPosition(new_pos)
            e.accept(); return

        elif e.key() == Qt.Key_Escape:
            self.close()
            e.accept(); return

        super().keyPressEvent(e)



# ==== Licenses: helpers & actions ====
def open_license_upload(self, preselect_track_id=None):
    dlg = LicenseUploadDialog(self.license_service, self._list_all_tracks(), self._list_licensees(),
                              preselect_track_id=preselect_track_id, parent=self)
    dlg.saved.connect(lambda: self.statusBar().showMessage("License saved", 3000))
    dlg.exec()

def open_licenses_browser(self, track_filter_id=None):
    LicensesBrowserDialog(self.license_service, track_filter_id=track_filter_id, parent=self).exec()

class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._peaks = []
        self._duration = 1
        self._playhead = 0
        self.setMinimumHeight(90)

    def set_peaks(self, peaks):
        self._peaks = peaks or []
        self.update()

    def set_duration_ms(self, ms):
        self._duration = max(1, int(ms))
        self.update()

    def set_playhead_ms(self, ms):
        self._playhead = max(0, min(int(ms), self._duration))
        self.update()

    def paintEvent(self, e):
        from PySide6.QtGui import QPainter, QPainterPath, QPen, QColor
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect()
        mid = r.center().y()

        # Decide colors based on window background brightness
        pal = self.palette()
        bg = pal.window().color()
        # Relative luminance (simple RGB weighted sum)
        lum = 0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()
        light_mode = lum >= 0.5

        waveform_color = QColor(0, 0, 0) if light_mode else QColor(255, 255, 255)
        playhead_color = QColor(255, 255, 255) if light_mode else QColor(0, 0, 0)

        # waveform (vertical min–max bars)
        if self._peaks:
            w = len(self._peaks)
            xscale = (r.width() - 1) / max(1, w - 1)
            path = QPainterPath()
            for i, (lo, hi) in enumerate(self._peaks):
                x = r.left() + i * xscale
                y1 = mid - hi * (r.height() * 0.45)
                y2 = mid - lo * (r.height() * 0.45)
                path.moveTo(x, y1)
                path.lineTo(x, y2)
            p.setPen(QPen(waveform_color))
            p.drawPath(path)

        # playhead
        if self._duration > 0:
            x = r.left() + (r.width() - 1) * (self._playhead / self._duration)
            p.setPen(QPen(playhead_color))
            p.drawLine(int(x), r.top(), int(x), r.bottom())

def load_wav_peaks(path: str, width_px: int):
    """
    Build min/max peaks for drawing a waveform.
    - Fast path: RIFF/WAVE (16, 24, 32-bit PCM) via `wave`.
    - Generic path: decode any compressed format to mono s16le via ffmpeg (if present),
      else fallback to `audioread` (pure-Python wrapper over system decoders).
    Returns: list[(lo, hi)] in [-1.0, 1.0].
    """
    import os, struct, shutil, subprocess

    width_px = max(1, int(width_px))
    buckets = width_px * 4  # ~4 samples/bucket for smooth lines

    # --- helper: best-effort find a binary on common paths ---
    def _which(name: str):
        import shutil, os, platform
        p = shutil.which(name)
        if p:
            return p

        sysname = platform.system().lower()
        search_dirs = []
        if sysname == "darwin":
            search_dirs = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
        elif sysname == "linux":
            search_dirs = ["/usr/bin", "/usr/local/bin"]
        elif sysname == "windows":
            search_dirs = [
                r"C:\Program Files\ffmpeg\bin",
                r"C:\ffmpeg\bin",
                r"C:\ProgramData\chocolatey\bin",
                os.path.expandvars(r"%USERPROFILE%\scoop\shims"),
            ]

        # try plain name and .exe on Windows
        candidates = [name]
        if sysname == "windows" and not name.lower().endswith(".exe"):
            candidates.append(name + ".exe")

        for d in search_dirs:
            for cand in candidates:
                full = os.path.join(d, cand)
                if os.path.exists(full):
                    return full
        return None

    # --- WAV fast path -------------------------------------------------------
    try:
        with open(path, "rb") as f:
            head = f.read(12)
        if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE":
            import wave
            with wave.open(path, "rb") as w:
                ch = w.getnchannels()
                sampwidth = w.getsampwidth()  # bytes: 2, 3, 4
                nframes = w.getnframes()
                if nframes <= 0:
                    return []

                step = max(1, nframes // buckets)
                fs = 32768.0 if sampwidth == 2 else (8388608.0 if sampwidth == 3 else 2147483648.0)

                peaks = []
                for i in range(0, nframes, step):
                    w.setpos(i)
                    frames = min(step, nframes - i)
                    raw = w.readframes(frames)
                    if not raw:
                        continue

                    if sampwidth == 2:
                        count = len(raw) // 2
                        if count == 0:
                            continue
                        vals = struct.unpack("<" + "h" * count, raw)
                        if ch > 1:
                            vals = vals[0::ch]  # ch0 only
                    elif sampwidth == 3:
                        b = raw
                        count = len(b) // (3 * ch)
                        if count <= 0:
                            continue
                        vals = []
                        step_bytes = 3 * ch
                        for off in range(0, count * step_bytes, step_bytes):
                            b0, b1, b2 = b[off], b[off + 1], b[off + 2]
                            v = b0 | (b1 << 8) | (b2 << 16)
                            if v & 0x800000:
                                v -= 0x1000000
                            vals.append(v)
                    elif sampwidth == 4:
                        count = len(raw) // 4
                        if count == 0:
                            continue
                        vals = struct.unpack("<" + "i" * count, raw)
                        if ch > 1:
                            vals = vals[0::ch]
                    else:
                        continue

                    if not vals:
                        continue
                    lo = float(min(vals)) / fs
                    hi = float(max(vals)) / fs
                    if lo < -1.0: lo = -1.0
                    if hi >  1.0: hi =  1.0
                    peaks.append((lo, hi))
                return peaks
    except Exception:
        pass

    # --- Generic path A: ffmpeg streaming to mono s16le ----------------------
    ffmpeg = _which("ffmpeg")
    if ffmpeg:
        sr = 44100
        # Try to get duration for bucket sizing
        total_samples = None
        ffprobe = _which("ffprobe")
        if ffprobe:
            try:
                out = subprocess.check_output(
                    [ffprobe, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=nw=1:nk=1", os.fspath(path)],
                    stderr=subprocess.STDOUT
                ).decode("utf-8", "replace").strip()
                if out:
                    d = float(out)
                    if d > 0:
                        total_samples = int(sr * d)
            except Exception:
                total_samples = None

        target_step = max(1, (total_samples // buckets) if total_samples else (sr // 100))  # ~10 ms if unknown

        try:
            p = subprocess.Popen(
                [ffmpeg, "-v", "error", "-nostdin", "-vn", "-i", os.fspath(path),
                 "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(sr), "-"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            peaks = []
            fs = 32768.0
            need = target_step
            lo, hi = +1.0, -1.0
            buf = bytearray()

            while True:
                chunk = p.stdout.read(8192)
                if not chunk:
                    break
                buf.extend(chunk)

                # process full samples (2 bytes/sample)
                n_samples = len(buf) // 2
                if n_samples <= 0:
                    continue

                off_samples = 0
                import struct as _st
                while n_samples > 0:
                    take = min(need, n_samples)
                    data_len = take * 2
                    data = bytes(buf[off_samples * 2 : off_samples * 2 + data_len])  # copy; safe to resize buf
                    for i in range(0, len(data), 2):
                        v = _st.unpack_from("<h", data, i)[0] / fs
                        if v < lo: lo = v
                        if v > hi: hi = v
                    need -= take
                    off_samples += take
                    n_samples -= take

                    if need == 0:
                        peaks.append((max(-1.0, lo), min(1.0, hi)))
                        lo, hi = +1.0, -1.0
                        need = target_step

                # drop consumed bytes
                del buf[:off_samples * 2]

            p.stdout.close()
            try:
                p.wait(timeout=2)
            except Exception:
                p.kill()

            if lo <= hi:
                peaks.append((max(-1.0, lo), min(1.0, hi)))

            return peaks or [(-0.0, 0.0)]
        except Exception:
            pass  # fall through to audioread

    # --- Generic path B: audioread fallback (pip install audioread) ----------
    try:
        import audioread, struct as _st
        peaks = []
        with audioread.audio_open(path) as f:
            sr = f.samplerate or 44100
            duration = getattr(f, "duration", None)
            total_samples = int(sr * duration) if duration else None
            # frames = samples *per channel*; audioread blocks are interleaved across channels
            ch = max(1, getattr(f, "channels", 1))
            frame_bytes = 2 * ch  # 16-bit signed little-endian per sample * channels
            target_step = max(1, (total_samples // buckets) if total_samples else (sr // 100))  # ~10 ms if unknown

            fs = 32768.0
            need = target_step
            lo, hi = +1.0, -1.0
            buf = bytearray()

            for block in f:  # raw 16-bit little-endian PCM
                buf.extend(block)
                frames = len(buf) // frame_bytes
                if frames <= 0:
                    continue

                off_frames = 0
                while frames > 0:
                    take = min(need, frames)
                    data_len = take * frame_bytes
                    data = bytes(buf[off_frames * frame_bytes : off_frames * frame_bytes + data_len])  # copy
                    # pick channel 0 only → cheap mono
                    for i in range(0, len(data), frame_bytes):
                        v = _st.unpack_from("<h", data, i)[0] / fs
                        if v < lo: lo = v
                        if v > hi: hi = v
                    need -= take
                    off_frames += take
                    frames -= take
                    if need == 0:
                        peaks.append((max(-1.0, lo), min(1.0, hi)))
                        lo, hi = +1.0, -1.0
                        need = target_step

                del buf[:off_frames * frame_bytes]

            if lo <= hi:
                peaks.append((max(-1.0, lo), min(1.0, hi)))

            return peaks or [(-0.0, 0.0)]
    except Exception:
        pass

    # Last resort
    return []


# =============================================================================
# Application Startup (Settings bootstrap + Single-instance enforcement)
# =============================================================================
def main() -> int:
    settings = init_settings()

    app = QApplication(sys.argv)

    lock = enforce_single_instance(60000)
    if lock is None:
        QMessageBox.warning(None, "Already running", f"{APP_NAME} is already running.")
        return 0

    app._single_instance_lock = lock

    window = App()
    window.showMaximized()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())

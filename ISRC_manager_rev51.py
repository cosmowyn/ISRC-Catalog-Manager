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
import uuid
import hashlib
import shutil
import sqlite3
import tempfile
import platform
import logging
import mimetypes
from pathlib import Path
from datetime import datetime
from functools import lru_cache
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import (
    Qt, QDate, QPoint, QSettings, QStandardPaths, QLockFile, QByteArray, QUrl, QEvent, QTimer
)
from PySide6.QtGui import (
    QIcon, QAction, QKeySequence, QImage, QPixmap
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox,
    QCalendarWidget, QRadioButton, QMenuBar, QMenu, QInputDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QMainWindow, QSizePolicy, QComboBox, QCompleter, QListWidget,
    QListWidgetItem, QFileDialog, QToolBar, QFrame, QSpinBox, QScrollArea, QSlider, QAbstractItemView
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

# ---------------------------------------------------------------------
# Path helpers: use _MEIPASS ONLY for bundled assets, never for writes.
# ---------------------------------------------------------------------
def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)

def BIN_DIR() -> Path:
    """Folder of the actual .exe (PyInstaller) or script dir in dev."""
    return Path(sys.executable).resolve().parent if _is_frozen() else Path(__file__).resolve().parent

def RES_DIR() -> Path:
    """Read-only bundled resources at runtime; equals src dir in dev."""
    return Path(getattr(sys, "_MEIPASS", BIN_DIR())) if _is_frozen() else BIN_DIR()

def DATA_DIR(app_name: str = "ISRCManager", portable: bool | None = None) -> Path:
    """
    Writes go here (DB, logs, exports).
    - Portable mode if a '.portable' file exists next to the exe, or portable=True is passed.
    - Otherwise %LOCALAPPDATA%\\ISRCManager on Windows.
    """
    if portable is True or (BIN_DIR() / ".portable").exists():
        return BIN_DIR()
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return (base / app_name).resolve()

# =============================================================================
# Application Configuration (QSettings + Single-instance Helpers)
# =============================================================================
APP_ORG = "GenericVendor"
APP_NAME = "ISRCManager"
SETTINGS_BASENAME = "settings.ini"

def init_settings() -> QSettings:
    """
    Use the OS-recommended app data dir (per-user, writable)
      - Windows: C:/Users/<you>/AppData/Roaming/GenericVendor/ISRCManager/
      - macOS:   ~/Library/Application Support/GenericVendor/ISRCManager/
      - Linux:   ~/.local/share/GenericVendor/ISRCManager/
    """
    base_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    base_dir.mkdir(parents=True, exist_ok=True)

    ini_path = base_dir / SETTINGS_BASENAME
    settings = QSettings(str(ini_path), QSettings.IniFormat)
    settings.setFallbacksEnabled(False)  # force only this file

    # First-run detection
    first_run = settings.value("app/initialized", False, type=bool) is False
    if first_run:
        settings.setValue("app/initialized", True)
        settings.setValue("app/schema_version", 1)
        settings.setValue("ui/theme", "system")
        settings.setValue("paths/database_dir", str((base_dir.parent / "Database").resolve()))
        # Persistent app UID (stays the same across launches for this user+install)
        settings.setValue("app/uid", str(uuid.uuid4()))
        settings.sync()

    return settings

def enforce_single_instance(timeout_ms: int = 60000):
    """Return a QLockFile if we obtained the lock; otherwise None."""
    lock_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(lock_dir / f"{APP_NAME}.lock"))
    lock.setStaleLockTime(timeout_ms)  # if previous instance crashed, lock becomes stealable after timeout
    if not lock.tryLock(0):
        return None
    return lock  # keep alive for app lifetime

# =============================================================================
# App constants (generic, user-editable via "Branding & Identity..." dialog)
# =============================================================================
QSETTINGS_ORG = APP_ORG
QSETTINGS_APP = APP_NAME

DEFAULT_WINDOW_TITLE = "ISRC Manager"
DEFAULT_ICON_PATH = ""  # user can set later

FIELD_TYPE_CHOICES = ["text", "dropdown", "checkbox", "date", "blob_image", "blob_audio"]

# ---- DB schema versioning ----
SCHEMA_BASELINE = 1   # First schema version
SCHEMA_TARGET   = 10  # Bump when you add a new migration


# =============================================================================
# Validators & Formatting Helpers (ISO + compact)
# =============================================================================ss
def seconds_to_hms(total: int) -> str:
    try:
        total = max(0, int(total or 0))
    except Exception:
        total = 0
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def hms_to_seconds(h: int, m: int, s: int) -> int:
    try:
        h = max(0, int(h or 0)); m = max(0, int(m or 0)); s = max(0, int(s or 0))
    except Exception:
        h, m, s = 0, 0, 0
    if m > 59 or s > 59:
        m = min(m, 59); s = min(s, 59)
    return h*3600 + m*60 + s

def parse_hms_text(t: str) -> int:
    try:
        parts = [int(x) for x in (t or "").split(":")]
        if len(parts) == 3:
            return hms_to_seconds(parts[0], parts[1], parts[2])
    except Exception:
        pass
    return 0

_ISRC_COMPACT_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{2}\d{5}$", re.IGNORECASE)
_ISRC_ISO_RE     = re.compile(r"^[A-Z]{2}-[A-Z0-9]{3}-\d{2}-\d{5}$", re.IGNORECASE)

# Accept both compact (T1234567890) and ISO (T-123.456.789-0)
_ISWC_ANY_RE     = re.compile(r"^(?:T\d{9}[\dX]|T-\d{3}\.\d{3}\.\d{3}-[\dX])$", re.IGNORECASE)
_ISWC_ISO_RE     = re.compile(r"^T-\d{3}\.\d{3}\.\d{3}-[\dX]$", re.IGNORECASE)

_UPC_EAN_RE = re.compile(r"^\d{12,13}$")  # optional; 12 or 13 digits

def is_blank(s: str) -> bool:
    return s is None or str(s).strip() == ""

# ---------- ISRC ----------
def normalize_isrc(s: str) -> str:
    """Compact uppercase (e.g., XXX0X2512345)."""
    if is_blank(s): return ""
    return re.sub(r"[^A-Z0-9]", "", s.upper())

def to_iso_isrc(s: str) -> str:
    """From any to ISO CC-XXX-YY-NNNNN. '' if cannot format."""
    sc = normalize_isrc(s)
    if not _ISRC_COMPACT_RE.match(sc):
        return ""
    return f"{sc[0:2]}-{sc[2:5]}-{sc[5:7]}-{sc[7:12]}"

def is_valid_isrc_compact_or_iso(s: str) -> bool:
    if is_blank(s): return False
    s = s.strip().upper()
    return bool(_ISRC_COMPACT_RE.match(normalize_isrc(s)) or _ISRC_ISO_RE.match(s))

def to_compact_isrc(s: str) -> str:
    """Return strict compact 12-char ISRC or ''."""
    sc = normalize_isrc(s)
    return sc if _ISRC_COMPACT_RE.match(sc) else ""

# ---------- ISWC ----------
def normalize_iswc(s: str) -> str:
    """Compact uppercase (e.g., T1234567890)."""
    if is_blank(s): return ""
    return re.sub(r"[^A-Z0-9]", "", s.upper())

def to_iso_iswc(s: str) -> str:
    """From any to ISO T-###.###.###-C. '' if cannot format."""
    sc = normalize_iswc(s)
    if not sc.startswith("T") or len(sc) != 11:
        return ""
    body = sc[1:10]   # 9 digits
    chk  = sc[10]     # checksum 0-9 or X
    if not (body.isdigit() and (chk.isdigit() or chk == "X")):
        return ""
    return f"T-{body[0:3]}.{body[3:6]}.{body[6:9]}-{chk}"

def is_valid_iswc_any(s: str) -> bool:
    if is_blank(s):  # optional
        return True
    return bool(_ISWC_ANY_RE.match(s.strip()))

# ---------- UPC ----------
def valid_upc_ean(s: str) -> bool:
    if is_blank(s): return True
    return bool(_UPC_EAN_RE.match(s.strip()))


# ----- Custom column kinds -----
CUSTOM_KIND_TEXT = "text"
CUSTOM_KIND_INT = "int"
CUSTOM_KIND_DATE = "date"
CUSTOM_KIND_BLOB_IMAGE = "blob_image"
CUSTOM_KIND_BLOB_AUDIO = "blob_audio"

# Allowed custom kinds exposed in UI (order matters for dropdowns)
ALLOWED_CUSTOM_KINDS = [
    CUSTOM_KIND_TEXT,
    CUSTOM_KIND_INT,
    CUSTOM_KIND_DATE,
    CUSTOM_KIND_BLOB_IMAGE,
    CUSTOM_KIND_BLOB_AUDIO,
]

# File validation for BLOBs
BLOB_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
BLOB_AUDIO_EXTS = {".wav", ".aif", ".aiff", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus"}
MAX_BLOB_BYTES = 256 * 1024 * 1024  # 256 MB hard limit

def _ext(p: str) -> str:
    return Path(p).suffix.lower()

@lru_cache(maxsize=256)
def _guess_mime(p: str) -> str:
    mime, _ = mimetypes.guess_type(p)
    return mime or ""

def _is_valid_image_path(p: str) -> bool:
    return _ext(p) in BLOB_IMAGE_EXTS or _guess_mime(p).startswith("image/")

def _is_valid_audio_path(p: str) -> bool:
    return _ext(p) in BLOB_AUDIO_EXTS or _guess_mime(p).startswith("audio/")

def _read_blob_from_path(path: str) -> bytes:
    b = Path(path).read_bytes()
    if len(b) > MAX_BLOB_BYTES:
        raise ValueError(f"Selected file is too large (> {MAX_BLOB_BYTES} bytes)")
    return b


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
        self._user_moved = False  # flag to avoid auto-reposition after user moves
        self.setWindowFlags(Qt.SubWindow | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = None
            self._user_moved = True
            ini_path = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / "settings.ini"
            s = QSettings(str(ini_path), QSettings.IniFormat)
            s.setFallbacksEnabled(False)
            s.setValue(self.settings_key, self.pos())
            s.sync()
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
        self.conn = parent.conn
        self.cur  = parent.cursor

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

    def _usage_counts(self, artist_id: int):
        self.cur.execute("SELECT COUNT(*) FROM Tracks WHERE main_artist_id=?", (artist_id,))
        main_uses = int(self.cur.fetchone()[0])
        self.cur.execute("SELECT COUNT(*) FROM TrackArtists WHERE artist_id=?", (artist_id,))
        extra_uses = int(self.cur.fetchone()[0])
        return main_uses, extra_uses, main_uses + extra_uses

    def _load(self):
        self.tbl.setRowCount(0)
        self.cur.execute("SELECT id, name FROM Artists ORDER BY name COLLATE NOCASE")
        for (aid, name) in self.cur.fetchall():
            main_u, extra_u, total = self._usage_counts(aid)
            r = self.tbl.rowCount(); self.tbl.insertRow(r)

            self.tbl.setItem(r, 0, QTableWidgetItem(name or ""))
            it_main = QTableWidgetItem(str(main_u)); it_main.setTextAlignment(Qt.AlignCenter)
            it_extra = QTableWidgetItem(str(extra_u)); it_extra.setTextAlignment(Qt.AlignCenter)
            it_total = QTableWidgetItem(str(total));  it_total.setTextAlignment(Qt.AlignCenter)
            self.tbl.setItem(r, 1, it_main); self.tbl.setItem(r, 2, it_extra); self.tbl.setItem(r, 3, it_total)

            chk = QTableWidgetItem(); chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if total == 0 else Qt.Unchecked)
            if total > 0: chk.setFlags(Qt.NoItemFlags)
            chk.setData(Qt.UserRole, aid)  # keep id
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
        for aid in ids:
            self.cur.execute("DELETE FROM Artists WHERE id=?", (aid,))
        self.conn.commit()
        self._load()

    def _purge_unused(self):
        self.cur.execute("SELECT id FROM Artists")
        all_ids = [row[0] for row in self.cur.fetchall()]
        to_del = []
        for aid in all_ids:
            _, _, total = self._usage_counts(aid)
            if total == 0: to_del.append(aid)
        if not to_del:
            QMessageBox.information(self, "Nothing to purge", "No unused artists found."); return
        if QMessageBox.question(self, "Confirm", f"Purge {len(to_del)} unused artist(s)?") != QMessageBox.Yes:
            return
        for aid in to_del:
            self.cur.execute("DELETE FROM Artists WHERE id=?", (aid,))
        self.conn.commit()
        self._load()


class _ManageAlbumsDialog(QDialog):
    """Safely purge only unused albums (no refs in Tracks.album_id)."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Manage stored album names")
        self.setModal(True)
        self.conn = parent.conn
        self.cur  = parent.cursor

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

    def _usage(self, album_id: int) -> int:
        self.cur.execute("SELECT COUNT(*) FROM Tracks WHERE album_id=?", (album_id,))
        return int(self.cur.fetchone()[0])

    def _load(self):
        self.tbl.setRowCount(0)
        self.cur.execute("SELECT id, title FROM Albums ORDER BY title COLLATE NOCASE")
        for (aid, title) in self.cur.fetchall():
            uses = self._usage(aid)
            r = self.tbl.rowCount(); self.tbl.insertRow(r)
            self.tbl.setItem(r, 0, QTableWidgetItem(title or ""))
            it_uses = QTableWidgetItem(str(uses)); it_uses.setTextAlignment(Qt.AlignCenter)
            self.tbl.setItem(r, 1, it_uses)

            chk = QTableWidgetItem(); chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if uses == 0 else Qt.Unchecked)
            if uses > 0: chk.setFlags(Qt.NoItemFlags)
            chk.setData(Qt.UserRole, aid)
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
        for aid in ids:
            self.cur.execute("DELETE FROM Albums WHERE id=?", (aid,))
        self.conn.commit()
        self._load()

    def _purge_unused(self):
        self.cur.execute("SELECT id FROM Albums")
        to_del = [aid for (aid,) in self.cur.fetchall() if self._usage(aid) == 0]
        if not to_del:
            QMessageBox.information(self, "Nothing to purge", "No unused albums found."); return
        if QMessageBox.question(self, "Confirm", f"Purge {len(to_del)} unused album(s)?") != QMessageBox.Yes:
            return
        for aid in to_del:
            self.cur.execute("DELETE FROM Albums WHERE id=?", (aid,))
        self.conn.commit()
        self._load()

# =============================================================================
# App (Relational schema; auto-ISO; custom field editors; auto-learn)
# =============================================================================
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

        act_manage_artists = QAction("Manage stored artists…", self)
        act_manage_artists.triggered.connect(self._manage_stored_artists)
        edit_menu.addAction(act_manage_artists)

        act_manage_albums = QAction("Manage stored album names…", self)
        act_manage_albums.triggered.connect(self._manage_stored_albums)
        edit_menu.addAction(act_manage_albums)

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
        self.table.horizontalHeader().sectionMoved.connect(self._save_header_state)

        # save header state on app exit
        try:
            if QApplication.instance() is not None:
                QApplication.instance().aboutToQuit.connect(self._save_header_state)
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


    def closeEvent(self, e):
        self.settings.sync()
        self.logger.info("Settings synced to disk")
        super().closeEvent(e)


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
            self.identity["window_title"] = title_edit.text().strip() or DEFAULT_WINDOW_TITLE
            self.identity["icon_path"] = icon_edit.text().strip()
            self.settings.setValue("identity/window_title", self.identity["window_title"])
            self.settings.setValue("identity/icon_path", self.identity["icon_path"])
            self.settings.sync()
            self.logger.info("Settings synced to disk")
            self._apply_identity()
            self.logger.info("Branding & identity updated")
            self._audit("SETTINGS", "Identity", ref_id="QSettings", details=f"title={self.identity['window_title']}")
            self._audit_commit()
            QMessageBox.information(self, "Saved", "Branding and identity updated.")
        save_btn.clicked.connect(do_save)
        close_btn.clicked.connect(dlg.accept)
        dlg.exec()

    # --- Artist Code (AA) ---
    def _migrate_artist_code_from_qsettings_if_needed(self):
        if self._profile_get("isrc_artist_code") is None:
            legacy = self.settings.value("isrc/artist_code", None)
            code = str(legacy) if legacy is not None else ""
            if not re.fullmatch(r"\d{2}", code):
                code = "00"
            self._profile_set("isrc_artist_code", code)
            self.logger.info("Migrated ISRC artist code from QSettings into profile DB")


    def load_artist_code(self) -> str:
        code = self._profile_get("isrc_artist_code", None)
        if not (isinstance(code, str) and re.fullmatch(r"\d{2}", (code or ""))):
            code = "00"
            self._profile_set("isrc_artist_code", code)
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

        self._profile_set("isrc_artist_code", val)
        self.logger.info(f"ISRC artist code set to '{val}' (profile DB)")
        if hasattr(self, "artist_edit"):
            self.artist_edit.setText(val)


    def _list_profiles(self):
        """Return list of absolute file paths to *.db files in Database/."""
        if not self.database_dir.exists():
            return []
        return [str(p) for p in sorted(self.database_dir.glob("*.db"))]

    def _reload_profiles_list(self, select_path: str | None = None):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        profiles = self._list_profiles()
        for path in profiles:
            self.profile_combo.addItem(Path(path).name, path)
        # ensure current path is present (might be outside Database/)
        if hasattr(self, "current_db_path") and self.current_db_path and self.current_db_path not in profiles:
            self.profile_combo.addItem(Path(self.current_db_path).name + " (external)", self.current_db_path)
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

        # NEW: persist current profile's header state
        try:
            self._save_header_state()
        except Exception:
            pass

        self.open_database(path)

        # Rebuild headers for the new profile and restore its saved order
        try:
            self.active_custom_fields = self.load_active_custom_fields()
            self._rebuild_table_headers()
            self._load_header_state()
        except Exception:
            pass

        self.refresh_table_preserve_view()
        self.populate_all_comboboxes()
        self.logger.info(f"Switched profile to: {path}")
        self._audit("PROFILE", "Database", ref_id=path, details="switch_profile")
        self._audit_commit()

    def create_new_profile(self):
        name, ok = QInputDialog.getText(self, "New Profile", "Database file name (no path, e.g., mylabel.db):")
        if not ok or not name.strip():
            return
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name.strip())
        if not safe.lower().endswith(".db"):
            safe += ".db"
        new_path = str(self.database_dir / safe)
        if Path(new_path).exists():
            QMessageBox.warning(self, "Exists", "A database with this name already exists.")
            return
        self.open_database(new_path)
        self._reload_profiles_list(select_path=new_path)
        self.refresh_table_preserve_view()
        self.populate_all_comboboxes()
        self.logger.info(f"Created new profile DB: {new_path}")
        self._audit("PROFILE", "Database", ref_id=new_path, details="create_new_profile")
        self._audit_commit()
        QMessageBox.information(self, "Profile Created", f"Database created:\n{new_path}")

    def browse_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Database", str(self.database_dir), "SQLite DB (*.db);;All Files (*)")
        if not path:
            return
        self.open_database(path)
        self._reload_profiles_list(select_path=path)
        self.refresh_table_preserve_view()
        self.populate_all_comboboxes()
        self.logger.info(f"Opened external profile DB via browse: {path}")
        self._audit("PROFILE", "Database", ref_id=path, details="browse_profile")
        self._audit_commit()

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

        try:
            if deleting_current and self.conn:
                try:
                    self.conn.commit()
                except Exception:
                    pass
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
                self.cursor = None

            try:
                os.remove(path)
            except FileNotFoundError:
                pass  # already gone

            self._reload_profiles_list(select_path=None)

            if deleting_current:
                profiles = self._list_profiles()
                if profiles:
                    fallback = profiles[0]
                else:
                    fallback = str(self.database_dir / "library.db")
                self.open_database(fallback)
                self._reload_profiles_list(select_path=fallback)

            self.refresh_table_preserve_view()
            self.populate_all_comboboxes()
            self.logger.warning(f"Removed profile DB from disk: {path}")
            self._audit("PROFILE", "Database", ref_id=path, details="remove_profile")
            self._audit_commit()
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

    # -------------------------------------------------------------------------
    # DB: open/init helpers + MIGRATIONS
    # -------------------------------------------------------------------------
    def open_database(self, path: str):
        """Open (or create) the SQLite DB at path; initialize schema if needed."""
        try:
            if self.conn:
                try:
                    self.conn.commit()
                except Exception:
                    pass
                self.conn.close()
        except Exception:
            pass

        Path(path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(path)

        self._ensure_profile_store()

        self._migrate_artist_code_from_qsettings_if_needed()

        current_code = self.load_artist_code()

        self.logger.info(f"Profile ISRC artist code active: '{current_code}'")

        self.cursor = self.conn.cursor()
        self.cursor.execute("PRAGMA foreign_keys = ON")
        self.cursor.execute("PRAGMA journal_mode = WAL")
        self.cursor.execute("PRAGMA synchronous = NORMAL")

        self.current_db_path = path
        self.settings.setValue("db/last_path", path)
        self.settings.sync()
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

    def init_db(self):
        # Core entities
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Artists (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
        """)
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_artists_name ON Artists(name)")

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Albums (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL
            )
        """)
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_albums_title ON Albums(title)")

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Tracks (
                id INTEGER PRIMARY KEY,
                isrc TEXT NOT NULL,
                isrc_compact TEXT,                 -- added in migration v4 (filled & made NOT NULL with unique index)
                db_entry_date DATE DEFAULT CURRENT_DATE,
                track_title TEXT NOT NULL,
                main_artist_id INTEGER NOT NULL,
                album_id INTEGER,
                release_date DATE,
                track_length_sec INTEGER NOT NULL DEFAULT 0,
                iswc TEXT,
                upc TEXT,
                genre TEXT,
                FOREIGN KEY (main_artist_id) REFERENCES Artists(id) ON DELETE RESTRICT,
                FOREIGN KEY (album_id) REFERENCES Albums(id) ON DELETE SET NULL
            )
        """)
        self.cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_isrc_unique ON Tracks(isrc)")  # legacy
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_title ON Tracks(track_title)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_upc ON Tracks(upc)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_genre ON Tracks(genre)")

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS TrackArtists (
                track_id INTEGER NOT NULL,
                artist_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'additional',
                PRIMARY KEY (track_id, artist_id, role),
                FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY (artist_id) REFERENCES Artists(id) ON DELETE RESTRICT
            )
        """)

        # Custom fields (definitions + values) with type + options
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS CustomFieldDefs (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER,
                field_type TEXT NOT NULL DEFAULT 'text',   -- 'text' | 'dropdown' | 'checkbox' | 'date'
                options TEXT                                -- JSON array for dropdown options (nullable)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS CustomFieldValues (
                track_id INTEGER NOT NULL,
                field_def_id INTEGER NOT NULL,
                value TEXT,
                PRIMARY KEY (track_id, field_def_id),
                FOREIGN KEY (track_id) REFERENCES Tracks(id) ON DELETE CASCADE,
                FOREIGN KEY (field_def_id) REFERENCES CustomFieldDefs(id) ON DELETE CASCADE
            )
        """)

        # Settings (single-row)
        self.cursor.execute("""CREATE TABLE IF NOT EXISTS ISRC_Prefix (id INTEGER PRIMARY KEY, prefix TEXT NOT NULL)""")
        self.cursor.execute("""CREATE TABLE IF NOT EXISTS SENA (id INTEGER PRIMARY KEY, number TEXT)""")
        self.cursor.execute("""CREATE TABLE IF NOT EXISTS BTW (id INTEGER PRIMARY KEY, nr TEXT)""")
        self.cursor.execute("""CREATE TABLE IF NOT EXISTS BUMA_STEMRA (id INTEGER PRIMARY KEY, relatie_nummer TEXT, ipi TEXT)""")

        # --- Audit log (immutable append-only) ---
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS AuditLog (
                id INTEGER PRIMARY KEY,
                ts TEXT NOT NULL DEFAULT (datetime('now')),
                user TEXT,
                action TEXT NOT NULL,
                entity TEXT,
                ref_id TEXT,
                details TEXT
            )
        """)

        self.conn.commit()


    # ---- Schema version helpers & migrator ----
    def _get_db_version(self) -> int:
        row = self.cursor.execute("PRAGMA user_version").fetchone()
        try:
            return int(row[0]) if row and row[0] is not None else 0
        except Exception:
            return 0

    def _set_db_version(self, v: int):
        self.conn.execute(f"PRAGMA user_version = {v}")

    def _ensure_migration_log(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS _MigrationLog (
                version     INTEGER PRIMARY KEY,
                applied_at  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                notes       TEXT
            )
        """)

    def _apply_migration(self, from_ver: int, func):
        self.conn.execute("SAVEPOINT mig")
        try:
            func()  # must NOT call commit/rollback
            self._set_db_version(from_ver + 1)
            self.cursor.execute(
                "INSERT OR REPLACE INTO _MigrationLog(version, notes) VALUES (?, ?)",
                (from_ver + 1, func.__name__)
            )
            try:
                self.conn.execute("RELEASE SAVEPOINT mig")
            except sqlite3.OperationalError as e:
                # If a migration mistakenly committed, the savepoint was already ended.
                if "no such savepoint" not in str(e).lower():
                    raise
            self.conn.commit()
            self.logger.info(f"Applied migration {from_ver}->{from_ver+1} ({func.__name__})")
            self._audit("MIGRATE", "DB", ref_id=f"{from_ver}->{from_ver+1}", details=func.__name__)
            self._audit_commit()
        except Exception as e:
            try:
                self.conn.execute("ROLLBACK TO SAVEPOINT mig")
                self.conn.execute("RELEASE SAVEPOINT mig")
            except Exception:
                pass
            self.logger.exception(f"Migration {from_ver}->{from_ver+1} failed: {e}")
            raise

    # -------------------------------------------------------------------------
    # Profile Key/Value store (per-database)
    # -------------------------------------------------------------------------
    def _ensure_profile_store(self):
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_kv (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        self.conn.commit()

    def _profile_get(self, key: str, default=None):
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM app_kv WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else default

    def _profile_set(self, key: str, value):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO app_kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.conn.commit()


    def migrate_schema(self):
        # Ensure log table exists
        self._ensure_migration_log()

        v = self._get_db_version()
        if v == 0:
            # Fresh/unknown DB → set to baseline after core tables exist
            self._set_db_version(SCHEMA_BASELINE)
            v = SCHEMA_BASELINE
            self.conn.commit()
            self.logger.info(f"Initialized DB user_version to baseline {SCHEMA_BASELINE}")

        # Stepwise migrations until target
        while v < SCHEMA_TARGET:
            if v == 1:
                self._apply_migration(1, self._mig_1_to_2)
                v = 2
            elif v == 2:
                self._apply_migration(2, self._mig_2_to_3)
                v = 3
            elif v == 3:
                self._apply_migration(3, self._mig_3_to_4)
                v = 4
            elif v == 4:
                self._apply_migration(4, self._mig_4_to_5)
                v = 5
            elif v == 5:
                self._apply_migration(5, self._mig_5_to_6)
                v = 6
            elif v == 6:
                self._apply_migration(6, self._mig_6_to_7)
                v = 7
            elif v == 7:
                self._apply_migration(7, self._mig_7_to_8)
                v = 8
            elif v == 8:
                self._apply_migration(8, self._mig_8_to_9)
                v = 9
            elif v == 9:
                self._apply_migration(9, self._mig_9_to_10)
                v = 10
            else:
                self.logger.warning(f"Unknown migration path from version {v}")
                break

    # ---- Concrete migrations ----
    def _mig_1_to_2(self):
        # Add CustomFieldDefs.field_type/options if missing (idempotent)
        cols = [r[1] for r in self.cursor.execute("PRAGMA table_info(CustomFieldDefs)").fetchall()]
        if "field_type" not in cols:
            self.cursor.execute("ALTER TABLE CustomFieldDefs ADD COLUMN field_type TEXT NOT NULL DEFAULT 'text'")
        if "options" not in cols:
            self.cursor.execute("ALTER TABLE CustomFieldDefs ADD COLUMN options TEXT")

    def _mig_2_to_3(self):
        # Add useful indexes; safe if they already exist
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_release_date ON Tracks(release_date)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_cfvalues_field ON CustomFieldValues(field_def_id)")

    def _mig_3_to_4(self):
        # Add isrc_compact column + unique index, backfill
        cols = [r[1] for r in self.cursor.execute("PRAGMA table_info(Tracks)").fetchall()]
        if "isrc_compact" not in cols:
            self.cursor.execute("ALTER TABLE Tracks ADD COLUMN isrc_compact TEXT")
            # backfill
            for (pk, isrc,) in self.cursor.execute("SELECT id, isrc FROM Tracks").fetchall():
                comp = to_compact_isrc(isrc)
                self.cursor.execute("UPDATE Tracks SET isrc_compact=? WHERE id=?", (comp, pk))
            # unique index on compact
            self.cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_isrc_compact_unique ON Tracks(isrc_compact)"
            )

    def _mig_4_to_5(self):
        # Add triggers to make AuditLog append-only
        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_auditlog_no_update
            BEFORE UPDATE ON AuditLog
            BEGIN
                SELECT RAISE(ABORT, 'AuditLog is append-only (UPDATE forbidden)');
            END
        """)
        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_auditlog_no_delete
            BEFORE DELETE ON AuditLog
            BEGIN
                SELECT RAISE(ABORT, 'AuditLog is append-only (DELETE forbidden)');
            END
        """)

    def _mig_5_to_6(self):
        # Data validation triggers (ISRC, UPC/EAN, release_date) on Tracks
        # ISRC + compact consistency
        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_tracks_isrc_validate_ins
            BEFORE INSERT ON Tracks
            FOR EACH ROW
            WHEN NOT (
                length(replace(replace(upper(NEW.isrc),'-',''),' ',''))=12
                AND replace(upper(NEW.isrc),'-','') GLOB '[A-Z][A-Z][A-Z0-9][A-Z0-9][A-Z0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                AND NEW.isrc_compact = replace(replace(upper(NEW.isrc),'-',''),' ','')
            )
            BEGIN
                SELECT RAISE(ABORT, 'ISRC validation failed');
            END
        """)
        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_tracks_isrc_validate_upd
            BEFORE UPDATE ON Tracks
            FOR EACH ROW
            WHEN NOT (
                length(replace(replace(upper(NEW.isrc),'-',''),' ',''))=12
                AND replace(upper(NEW.isrc),'-','') GLOB '[A-Z][A-Z][A-Z0-9][A-Z0-9][A-Z0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                AND NEW.isrc_compact = replace(replace(upper(NEW.isrc),'-',''),' ','')
            )
            BEGIN
                SELECT RAISE(ABORT, 'ISRC validation failed');
            END
        """)
        # UPC length 12 or 13 if provided
        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_tracks_upc_check_ins
            BEFORE INSERT ON Tracks
            FOR EACH ROW
            WHEN NEW.upc IS NOT NULL AND NEW.upc <> '' AND length(NEW.upc) NOT IN (12,13)
            BEGIN
                SELECT RAISE(ABORT, 'UPC/EAN must be 12 or 13 digits');
            END
        """)
        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_tracks_upc_check_upd
            BEFORE UPDATE ON Tracks
            FOR EACH ROW
            WHEN NEW.upc IS NOT NULL AND NEW.upc <> '' AND length(NEW.upc) NOT IN (12,13)
            BEGIN
                SELECT RAISE(ABORT, 'UPC/EAN must be 12 or 13 digits');
            END
        """)
        # release_date format YYYY-MM-DD if provided
        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_tracks_reldate_check_ins
            BEFORE INSERT ON Tracks
            FOR EACH ROW
            WHEN NEW.release_date IS NOT NULL AND NEW.release_date <> '' AND NEW.release_date NOT GLOB '____-__-__'
            BEGIN
                SELECT RAISE(ABORT, 'release_date must be YYYY-MM-DD');
            END
        """)
        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_tracks_reldate_check_upd
            BEFORE UPDATE ON Tracks
            FOR EACH ROW
            WHEN NEW.release_date IS NOT NULL AND NEW.release_date <> '' AND NEW.release_date NOT GLOB '____-__-__'
            BEGIN
                SELECT RAISE(ABORT, 'release_date must be YYYY-MM-DD');
            END
        """)

    def _mig_6_to_7(self):
        # Fix release_date validator: use LIKE with '_' wildcard instead of GLOB
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_tracks_reldate_check_ins")
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_tracks_reldate_check_upd")

        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_tracks_reldate_check_ins
            BEFORE INSERT ON Tracks
            FOR EACH ROW
            WHEN NEW.release_date IS NOT NULL
            AND NEW.release_date <> ''
            AND NEW.release_date NOT LIKE '____-__-__'
            BEGIN
                SELECT RAISE(ABORT, 'release_date must be YYYY-MM-DD');
            END
        """)

        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_tracks_reldate_check_upd
            BEFORE UPDATE ON Tracks
            FOR EACH ROW
            WHEN NEW.release_date IS NOT NULL
            AND NEW.release_date <> ''
            AND NEW.release_date NOT LIKE '____-__-__'
            BEGIN
                SELECT RAISE(ABORT, 'release_date must be YYYY-MM-DD');
            END
        """)

    def _mig_7_to_8(self):
        # Fix ISRC validator: GLOB had 8 trailing [0-9] groups; should be 7
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_tracks_isrc_validate_ins")
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_tracks_isrc_validate_upd")

        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_tracks_isrc_validate_ins
            BEFORE INSERT ON Tracks
            FOR EACH ROW
            WHEN NOT (
                length(replace(replace(upper(NEW.isrc),'-',''),' ','')) = 12
                AND replace(replace(upper(NEW.isrc),'-',''),' ','') GLOB
                    '[A-Z][A-Z][A-Z0-9][A-Z0-9][A-Z0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                AND upper(NEW.isrc_compact) = replace(replace(upper(NEW.isrc),'-',''),' ','')
            )
            BEGIN
                SELECT RAISE(ABORT, 'ISRC validation failed');
            END
        """)

        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_tracks_isrc_validate_upd
            BEFORE UPDATE ON Tracks
            FOR EACH ROW
            WHEN NOT (
                length(replace(replace(upper(NEW.isrc),'-',''),' ','')) = 12
                AND replace(replace(upper(NEW.isrc),'-',''),' ','') GLOB
                    '[A-Z][A-Z][A-Z0-9][A-Z0-9][A-Z0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
                AND upper(NEW.isrc_compact) = replace(replace(upper(NEW.isrc),'-',''),' ','')
            )
            BEGIN
                SELECT RAISE(ABORT, 'ISRC validation failed');
            END
        """)

    def _mig_8_to_9(self):
        # Add track_length_sec to Tracks if missing
        cols = [r[1] for r in self.cursor.execute("PRAGMA table_info(Tracks)").fetchall()]
        if "track_length_sec" not in cols:
            self.cursor.execute("ALTER TABLE Tracks ADD COLUMN track_length_sec INTEGER NOT NULL DEFAULT 0")


    def _mig_9_to_10(self):
        """
        Enable BLOB custom fields (image/audio) within existing CustomFieldDefs/CustomFieldValues.
        - Adds storage columns on CustomFieldValues:
            * blob_value   BLOB
            * mime_type    TEXT (optional hint)
            * size_bytes   INTEGER NOT NULL DEFAULT 0
        - Adds constraints via triggers so:
            * For field_type in ('blob_image','blob_audio'): blob_value required, value must be NULL.
            * For other field_types: blob_value must be NULL (text/number/date use 'value').
        - Adds helpful indexes.
        """
        # 1) Add columns if missing (idempotent)
        cols = [r[1] for r in self.cursor.execute("PRAGMA table_info(CustomFieldValues)").fetchall()]
        if "blob_value" not in cols:
            self.cursor.execute("ALTER TABLE CustomFieldValues ADD COLUMN blob_value BLOB")
        if "mime_type" not in cols:
            self.cursor.execute("ALTER TABLE CustomFieldValues ADD COLUMN mime_type TEXT")
        if "size_bytes" not in cols:
            self.cursor.execute("ALTER TABLE CustomFieldValues ADD COLUMN size_bytes INTEGER NOT NULL DEFAULT 0")

        # 2) Indexes to keep lookups fast
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_cfvalues_track_field
            ON CustomFieldValues(track_id, field_def_id)
        """)
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_cfvalues_field_track
            ON CustomFieldValues(field_def_id, track_id)
        """)

        # 3) Drop old enforcement triggers if they exist (so we can recreate cleanly)
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_cfvalues_blob_enforce_ins")
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_cfvalues_blob_enforce_upd")
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_cfvalues_text_enforce_ins")
        self.cursor.execute("DROP TRIGGER IF EXISTS trg_cfvalues_text_enforce_upd")

        # 4) Enforce BLOB semantics for blob_* field types (INSERT/UPDATE)
        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_cfvalues_blob_enforce_ins
            BEFORE INSERT ON CustomFieldValues
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1 FROM CustomFieldDefs d
                WHERE d.id = NEW.field_def_id AND d.field_type IN ('blob_image','blob_audio')
            )
            AND (
                NEW.blob_value IS NULL
                OR NEW.value IS NOT NULL
                OR NEW.size_bytes < 0
            )
            BEGIN
                SELECT RAISE(ABORT, 'BLOB field requires blob_value (and NULL text); size_bytes must be >= 0');
            END
        """)
        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_cfvalues_blob_enforce_upd
            BEFORE UPDATE ON CustomFieldValues
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1 FROM CustomFieldDefs d
                WHERE d.id = NEW.field_def_id AND d.field_type IN ('blob_image','blob_audio')
            )
            AND (
                NEW.blob_value IS NULL
                OR NEW.value IS NOT NULL
                OR NEW.size_bytes < 0
            )
            BEGIN
                SELECT RAISE(ABORT, 'BLOB field requires blob_value (and NULL text); size_bytes must be >= 0');
            END
        """)

        # 5) Enforce NON-BLOB semantics for other field types (INSERT/UPDATE)
        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_cfvalues_text_enforce_ins
            BEFORE INSERT ON CustomFieldValues
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1 FROM CustomFieldDefs d
                WHERE d.id = NEW.field_def_id AND d.field_type NOT IN ('blob_image','blob_audio')
            )
            AND NEW.blob_value IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'Non-BLOB field must not store blob_value');
            END
        """)
        self.cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_cfvalues_text_enforce_upd
            BEFORE UPDATE ON CustomFieldValues
            FOR EACH ROW
            WHEN EXISTS (
                SELECT 1 FROM CustomFieldDefs d
                WHERE d.id = NEW.field_def_id AND d.field_type NOT IN ('blob_image','blob_audio')
            )
            AND NEW.blob_value IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'Non-BLOB field must not store blob_value');
            END
        """)


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

    # --- NEW: Variant helpers (repurposed as Artist Code AA) ---
    def load_isrc_prefix(self):
        row = self.cursor.execute("SELECT prefix FROM ISRC_Prefix WHERE id = 1").fetchone()
        return (row[0] or "").strip() if row else ""

    def load_active_custom_fields(self):
        fields = []
        for row in self.cursor.execute(
            "SELECT id, name, field_type, options "
            "FROM CustomFieldDefs WHERE active=1 "
            "ORDER BY COALESCE(sort_order, 999999), name"
        ).fetchall():
            fields.append({
                "id": row[0],
                "name": row[1],
                "field_type": row[2] or "text",
                "options": row[3]
            })
        return fields

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


    def _xml_local(self, tag: str) -> str:
        """Return local tag name without XML namespace."""
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

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


    def _fetch_rows_with_customs(self):
        """
        Performance path: single base query + one shot fetch of all custom field values into a dict.
        Avoids per-row SELECTs for CustomFieldValues.
        """
        # Base rows with pre-joined additional artists (GROUP_CONCAT)
        base_rows = self.cursor.execute("""
            SELECT
                t.id,
                t.isrc,
                t.db_entry_date,
                t.track_title,
                COALESCE(a.name, '') AS artist_name,
                COALESCE((
                    SELECT GROUP_CONCAT(ar.name, ', ')
                    FROM TrackArtists ta
                    JOIN Artists ar ON ar.id = ta.artist_id
                    WHERE ta.track_id = t.id AND ta.role = 'additional'
                ), '') AS additional_artists,
                COALESCE(al.title, '') AS album_title,
                COALESCE(t.release_date, '') AS release_date,
                COALESCE(t.track_length_sec, 0) AS track_length_sec,
                COALESCE(t.iswc, '') AS iswc,
                COALESCE(t.upc, '') AS upc,
                COALESCE(t.genre, '') AS genre
            FROM Tracks t
            LEFT JOIN Artists a ON a.id = t.main_artist_id
            LEFT JOIN Albums  al ON al.id = t.album_id
            ORDER BY t.id
        """).fetchall()

        # Prefetch all custom values into dict {(track_id, field_id): value}
        cf_map = {}
        if self.active_custom_fields:
            # Fetch only for fields currently active
            active_ids = tuple(f["id"] for f in self.active_custom_fields)
            if len(active_ids) == 1:
                q = "SELECT track_id, field_def_id, value FROM CustomFieldValues WHERE field_def_id=?"
                rows = self.cursor.execute(q, (active_ids[0],)).fetchall()
            else:
                q = f"SELECT track_id, field_def_id, value FROM CustomFieldValues WHERE field_def_id IN ({','.join('?'*len(active_ids))})"
                rows = self.cursor.execute(q, active_ids).fetchall()
            for trk, fid, val in rows:
                cf_map[(trk, fid)] = "" if val is None else str(val)
        return base_rows, cf_map

    def refresh_table(self):
        # Ensure custom fields and headers are ready
        if not hasattr(self, "active_custom_fields") or self.active_custom_fields is None:
            self.active_custom_fields = self.load_active_custom_fields()
            self._rebuild_table_headers()

        _prev_sort_enabled = self.table.isSortingEnabled()
        if _prev_sort_enabled:
            self.table.setSortingEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        rows, cf_map = self._fetch_rows_with_customs()
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
            self.table.horizontalHeader().sectionMoved.connect(
                lambda *_: self._save_header_state()
            )
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
        name = (name or "").strip()
        if is_blank(name):
            raise ValueError("Artist name is required")
        row = self.cursor.execute("SELECT id FROM Artists WHERE name=? ORDER BY id LIMIT 1", (name,)).fetchone()
        if row:
            return int(row[0])
        self.cursor.execute("INSERT INTO Artists (name) VALUES (?)", (name,))
        return int(self.cursor.lastrowid)

    def get_or_create_album(self, title: str) -> int | None:
        title = (title or "").strip()
        if is_blank(title):
            return None
        row = self.cursor.execute("SELECT id FROM Albums WHERE title=? ORDER BY id LIMIT 1", (title,)).fetchone()
        if row:
            return int(row[0])
        self.cursor.execute("INSERT INTO Albums (title) VALUES (?)", (title,))
        return int(self.cursor.lastrowid)

    @staticmethod
    def _parse_additional_artists(s: str):
        parts = [p.strip() for p in (s or "").split(",")]
        return [p for p in parts if p]

    def _replace_additional_artists_for_track(self, track_id: int, names):
        self.cursor.execute("DELETE FROM TrackArtists WHERE track_id=? AND role='additional'", (track_id,))
        for nm in names:
            try:
                aid = self.get_or_create_artist(nm)
                self.cursor.execute(
                    "INSERT OR IGNORE INTO TrackArtists (track_id, artist_id, role) VALUES (?, ?, 'additional')",
                    (track_id, aid)
                )
            except ValueError:
                pass

    # =============================================================================
    # ISRC duplicate check across formats (uses new compact column)
    # =============================================================================
    def is_isrc_taken_normalized(self, candidate: str, exclude_track_id: int | None = None) -> bool:
        norm = to_compact_isrc(candidate)
        if not norm:
            return False
        if exclude_track_id is None:
            row = self.cursor.execute(
                "SELECT 1 FROM Tracks WHERE isrc_compact = ? LIMIT 1",
                (norm,)
            ).fetchone()
        else:
            row = self.cursor.execute(
                "SELECT 1 FROM Tracks WHERE isrc_compact = ? AND id != ? LIMIT 1",
                (norm, exclude_track_id)
            ).fetchone()
        return bool(row)

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
            main_artist_id = self.get_or_create_artist(self.artist_field.currentText())
            album_id = self.get_or_create_album(self.album_title_field.currentText())

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
            self.logger.info(f"About to insert ISRC iso={generated_iso} compact={comp}")
            self.cursor.execute("""
                INSERT INTO Tracks (isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                generated_iso,
                comp,
                self.track_title_field.text().strip(),
                main_artist_id,
                album_id,
                release_date_sql,
                track_seconds,
                (iso_iswc or None),
                (self.upc_field.currentText().strip() or None),
                (self.genre_field.currentText().strip() or None),
            ))
            track_id = int(self.cursor.lastrowid)

            extras = self._parse_additional_artists(self.additional_artist_field.currentText())
            self._replace_additional_artists_for_track(track_id, extras)

            self.conn.commit()
            self.logger.info(f"Track created id={track_id} isrc={generated_iso}")
            self._audit("CREATE", "Track", ref_id=track_id, details=f"isrc={generated_iso}")
            self._audit_commit()

            self.refresh_table_preserve_view(focus_id=track_id)
            self.populate_all_comboboxes()
            self.clear_form_fields()
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
                self.cursor.execute("DELETE FROM Tracks WHERE id=?", (row_id,))
                self.conn.commit()
                self.refresh_table_preserve_view()
                self.populate_all_comboboxes()
                self.logger.warning(f"Track deleted id={row_id}")
                self._audit("DELETE", "Track", ref_id=row_id, details="delete_entry")
                self._audit_commit()
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
        row = self.cursor.execute("""
            SELECT t.release_date, t.upc, t.genre
            FROM Tracks t
            JOIN Albums a ON a.id = t.album_id
            WHERE a.title = ?
            LIMIT 1
        """, (title,)).fetchone()
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
            import xml.etree.ElementTree as ET

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

            # Base rows (+ track_length_sec)
            self.cursor.execute("""
                SELECT
                    t.id                       AS id,
                    t.isrc                     AS isrc,
                    t.db_entry_date            AS db_entry_date,
                    t.track_title              AS track_title,
                    COALESCE(a.name, '')       AS artist_name,
                    COALESCE((
                        SELECT GROUP_CONCAT(ar.name, ', ')
                        FROM TrackArtists ta
                        JOIN Artists ar ON ar.id = ta.artist_id
                        WHERE ta.track_id = t.id AND ta.role = 'additional'
                    ), '')                     AS additional_artists,
                    COALESCE(al.title, '')     AS album_title,
                    COALESCE(t.release_date, '') AS release_date,
                    COALESCE(t.track_length_sec, 0) AS track_length_sec,
                    COALESCE(t.iswc, '')       AS iswc,
                    COALESCE(t.upc, '')        AS upc,
                    COALESCE(t.genre, '')      AS genre
                FROM Tracks t
                LEFT JOIN Artists a ON a.id = t.main_artist_id
                LEFT JOIN Albums  al ON al.id = t.album_id
                ORDER BY t.id
            """)
            cols = [d[0] for d in self.cursor.description]
            rows = self.cursor.fetchall()
            track_ids = [r[0] for r in rows]  # first col = id

            # Custom defs + values (active only)
            defs = self.cursor.execute("""
                SELECT id, name, field_type, COALESCE(options,'[]') AS options
                FROM CustomFieldDefs
                WHERE active=1
                ORDER BY COALESCE(sort_order, 999999), name
            """).fetchall()
            defmap = {d[0]: {"name": d[1], "field_type": d[2]} for d in defs}

            custom_by_track = {}
            if track_ids:
                qmarks = ",".join("?" * len(track_ids))
                cv = self.cursor.execute(f"""
                    SELECT track_id, field_def_id, value, mime_type, size_bytes
                    FROM CustomFieldValues
                    WHERE track_id IN ({qmarks})
                """, track_ids).fetchall()
                for tid, fid, val, mime, size in cv:
                    d = defmap.get(fid)
                    if not d:
                        continue
                    custom_by_track.setdefault(tid, []).append({
                        "name": d["name"],
                        "field_type": d["field_type"],
                        "value": val,
                        "mime_type": mime,
                        "size_bytes": int(size or 0),
                    })

            # XML
            root = ET.Element("DeclarationOfSoundRecordingRightsClaimMessage")
            for row in rows:
                item = ET.SubElement(root, "SoundRecording")
                row_dict = dict(zip(cols, row))
                for col in cols:
                    # Write TrackLength in hh:mm:ss; keep original numeric too for back-compat (optional)
                    if col == "track_length_sec":
                        ET.SubElement(item, "TrackLength").text = seconds_to_hms(int(row_dict[col] or 0))
                    sub = ET.SubElement(item, col)
                    sub.text = "" if row_dict[col] is None else str(row_dict[col])

                # Custom fields
                c_el = ET.SubElement(item, "CustomFields")
                for c in custom_by_track.get(row_dict["id"], []):
                    f_el = ET.SubElement(c_el, "Field", name=c["name"], type=c["field_type"])
                    if c["field_type"] in ("blob_image", "blob_audio"):
                        if c.get("mime_type"):
                            ET.SubElement(f_el, "MimeType").text = c["mime_type"]
                        ET.SubElement(f_el, "SizeBytes").text = str(int(c.get("size_bytes", 0)))
                    else:
                        ET.SubElement(f_el, "Value").text = c["value"] or ""

            Path(path).parent.mkdir(parents=True, exist_ok=True)
            ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
            QMessageBox.information(self, "Export", f"All data exported:\n{path}")
            self.logger.info(f"Exported all data to {path}")
            self._audit("EXPORT", "Tracks", ref_id=path, details="all rows incl. duration+customs")
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

        qmarks = ",".join(["?"] * len(track_ids))
        base_rows = self.cursor.execute(f"""
            SELECT
                t.id,
                t.isrc,
                COALESCE(t.db_entry_date, '') AS db_entry_date,
                t.track_title,
                COALESCE(a.name, '') AS artist_name,
                COALESCE((
                    SELECT GROUP_CONCAT(ar.name, ', ')
                    FROM TrackArtists ta
                    JOIN Artists ar ON ar.id = ta.artist_id
                    WHERE ta.track_id = t.id AND ta.role = 'additional'
                ), '') AS additional_artists,
                COALESCE(al.title, '') AS album_title,
                COALESCE(t.release_date, '') AS release_date,
                COALESCE(t.track_length_sec, 0) AS track_length_sec,
                COALESCE(t.iswc, '') AS iswc,
                COALESCE(t.upc, '') AS upc,
                COALESCE(t.genre, '') AS genre
            FROM Tracks t
            LEFT JOIN Artists a ON a.id = t.main_artist_id
            LEFT JOIN Albums  al ON al.id = t.album_id
            WHERE t.id IN ({qmarks})
            ORDER BY t.id
        """, track_ids).fetchall()

        defs = self.cursor.execute("""
            SELECT id, name, field_type, COALESCE(options,'[]') AS options
            FROM CustomFieldDefs
            WHERE active=1
            ORDER BY COALESCE(sort_order, 999999), name
        """).fetchall()
        defmap = {d[0]: {"name": d[1], "field_type": d[2]} for d in defs}

        cv = self.cursor.execute(f"""
            SELECT track_id, field_def_id, value, mime_type, size_bytes
            FROM CustomFieldValues
            WHERE track_id IN ({qmarks})
        """, track_ids).fetchall()

        custom_by_track = {}
        for tid, fid, val, mime, size in cv:
            d = defmap.get(fid)
            if not d:
                continue
            custom_by_track.setdefault(tid, []).append({
                "name": d["name"],
                "field_type": d["field_type"],
                "value": val,
                "mime_type": mime,
                "size_bytes": int(size or 0),
            })

        from xml.etree.ElementTree import Element, SubElement, ElementTree
        root = Element("ISRCExport")
        meta = SubElement(root, "Meta")
        SubElement(meta, "CreatedAt").text = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        SubElement(meta, "ProfileDB").text = str(self.current_db_path)

        tracks_el = SubElement(root, "Tracks")
        for (tid, isrc, dbdate, title, artist, addl, album, rdate, tlen, iswc, upc, genre) in base_rows:
            t_el = SubElement(tracks_el, "Track", id=str(tid))
            SubElement(t_el, "ISRC").text = to_iso_isrc(isrc) or to_compact_isrc(isrc) or (isrc or "")
            SubElement(t_el, "DBEntryDate").text = dbdate or ""
            SubElement(t_el, "Title").text = title or ""
            SubElement(t_el, "MainArtist").text = artist or ""
            SubElement(t_el, "AdditionalArtists").text = addl or ""
            SubElement(t_el, "Album").text = album or ""
            SubElement(t_el, "ReleaseDate").text = rdate or ""
            SubElement(t_el, "TrackLength").text = seconds_to_hms(int(tlen or 0))
            SubElement(t_el, "ISWC").text = iswc or ""
            SubElement(t_el, "UPCEAN").text = upc or ""
            SubElement(t_el, "Genre").text = genre or ""

            c_el = SubElement(t_el, "CustomFields")
            for c in custom_by_track.get(tid, []):
                f_el = SubElement(c_el, "Field", name=c["name"], type=c["field_type"])
                if c["field_type"] in ("blob_image", "blob_audio"):
                    if c.get("mime_type"):
                        SubElement(f_el, "MimeType").text = c["mime_type"]
                    SubElement(f_el, "SizeBytes").text = str(int(c.get("size_bytes", 0)))
                else:
                    SubElement(f_el, "Value").text = c["value"] or ""

        try:
            ElementTree(root).write(out_path, encoding="utf-8", xml_declaration=True)
            self.logger.info(f"Exported {len(base_rows)} rows to XML (ids={track_ids}) -> {out_path}")
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

            dry = QMessageBox.question(
                self, "Dry Run?",
                "Run a dry-run first (no changes will be written) to see the summary?",
                QMessageBox.Yes | QMessageBox.No
            ) == QMessageBox.Yes

            import xml.etree.ElementTree as ET
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()
            except Exception as e:
                QMessageBox.critical(self, "Import Error", f"Could not read XML:\n{e}")
                return

            rtag = self._xml_local(root.tag)
            records = []
            schema = None  # "full" or "selected"

            if rtag == "DeclarationOfSoundRecordingRightsClaimMessage":
                records = list(root.findall("SoundRecording"))
                schema = "full"
            else:
                tracks_el = None
                if rtag == "Tracks":
                    tracks_el = root
                else:
                    for el in root.iter():
                        if self._xml_local(el.tag) == "Tracks":
                            tracks_el = el
                            break
                if tracks_el is not None:
                    records = [el for el in tracks_el if self._xml_local(el.tag) == "Track"]
                    if records:
                        schema = "selected"

            if not records:
                QMessageBox.critical(self, "Import Error", f"Unexpected XML root element: <{rtag}> or no importable records found.")
                return

            # ---------- Parse all records first ----------
            parsed = []  # list of dicts with all fields, including custom_fields[]
            def lower_map(el):
                m = {}
                for ch in el:
                    k = self._xml_local(ch.tag or "").strip().lower()
                    v = "" if ch.text is None else ch.text.strip()
                    m[k] = v
                return m

            for rec in records:
                child_map = lower_map(rec)
                # custom fields subtree
                customs = []
                for ch in rec:
                    if self._xml_local(ch.tag) == "CustomFields":
                        for fld in ch:
                            if self._xml_local(fld.tag) != "Field":
                                continue
                            name = (fld.attrib.get("name") or "").strip()
                            ftype = (fld.attrib.get("type") or "text").strip()
                            val = ""
                            mime = None
                            sz = None
                            for sub in fld:
                                tagl = self._xml_local(sub.tag).lower()
                                if tagl == "value":
                                    val = "" if sub.text is None else sub.text.strip()
                                elif tagl == "mimetype":
                                    mime = (sub.text or "").strip()
                                elif tagl == "sizebytes":
                                    try: sz = int((sub.text or "0").strip())
                                    except: sz = 0
                            customs.append({"name": name, "type": ftype, "value": val, "mime": mime, "size": sz})

                def get_any(m, *keys):
                    for k in keys:
                        v = m.get(k)
                        if v is not None and v != "": return v
                    return ""

                if schema == "full":
                    isrc_raw = get_any(child_map, "isrc")
                    title    = get_any(child_map, "track_title")
                    artist   = get_any(child_map, "artist_name")
                    addl     = get_any(child_map, "additional_artists")
                    album    = get_any(child_map, "album_title")
                    rel_date = get_any(child_map, "release_date")
                    iswc_raw = get_any(child_map, "iswc")
                    upc      = get_any(child_map, "upc")
                    genre    = get_any(child_map, "genre")
                    tlen_txt = get_any(child_map, "tracklength")  # hh:mm:ss (new)
                else:
                    isrc_raw = get_any(child_map, "isrc")
                    title    = get_any(child_map, "title")
                    artist   = get_any(child_map, "mainartist")
                    addl     = get_any(child_map, "additionalartists")
                    album    = get_any(child_map, "album")
                    rel_date = get_any(child_map, "releasedate")
                    iswc_raw = get_any(child_map, "iswc")
                    upc      = get_any(child_map, "upcean", "upc")
                    genre    = get_any(child_map, "genre")
                    tlen_txt = get_any(child_map, "tracklength")

                iso_isrc = to_iso_isrc(isrc_raw)
                comp_isrc = to_compact_isrc(iso_isrc)
                if not comp_isrc or not is_valid_isrc_compact_or_iso(iso_isrc):
                    parsed.append({"skip":"invalid_isrc"});  # mark skip
                    continue
                if is_blank(title) or is_blank(artist):
                    parsed.append({"skip":"missing_title_artist"});
                    continue

                iso_iswc = None
                if iswc_raw:
                    iso_iswc = to_iso_iswc(iswc_raw)
                    if not iso_iswc or not is_valid_iswc_any(iso_iswc):
                        parsed.append({"skip":"invalid_iswc"})
                        continue

                if rel_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", rel_date):
                    rel_date = None

                # track length parse
                tlen_sec = None
                if tlen_txt:
                    try:
                        tlen_sec = parse_hms_text(tlen_txt)
                    except Exception:
                        tlen_sec = None

                parsed.append({
                    "iso_isrc": iso_isrc, "comp_isrc": comp_isrc,
                    "title": title, "artist": artist, "addl": addl,
                    "album": album, "rel_date": rel_date, "iso_iswc": iso_iswc,
                    "upc": upc or None, "genre": genre or None,
                    "tlen_sec": tlen_sec,
                    "custom_fields": customs
                })

            # Filter out the ones marked for skip
            valid = [p for p in parsed if "skip" not in p]

            # ---------- Custom fields schema validation BEFORE writing ----------
            # Build required set { (name, type) } from incoming (non-blob only; blobs are metadata-only)
            required = {(c["name"], c["type"]) for p in valid for c in p["custom_fields"]
                        if c["name"] and c["type"] and c["type"] not in ("blob_image","blob_audio")}
            missing = []
            if required:
                existing = self.cursor.execute("""
                    SELECT name, field_type FROM CustomFieldDefs WHERE active=1
                """).fetchall()
                exist_set = {(n, t) for (n, t) in existing}
                for name, ftype in sorted(required):
                    if (name, ftype) not in exist_set:
                        missing.append((name, ftype))

            if missing:
                msg = "Missing custom columns (name : type):\n" + "\n".join(f"- {n} : {t}" for n,t in missing)
                self.logger.warning(f"Import aborted due to missing custom columns: {missing}")
                QMessageBox.critical(self, "Import Error", msg + "\n\nNo changes were made.")
                return

            # Map custom name->id for inserts
            name_to_id = {}
            if required:
                rows = self.cursor.execute("""
                    SELECT id, name, field_type FROM CustomFieldDefs WHERE active=1
                """).fetchall()
                for fid, nm, tp in rows:
                    name_to_id[(nm, tp)] = fid

            # ---------- Do the import (or dry-run summary) ----------
            inserted = skipped_dupe = skipped_invalid = errors = 0

            # Count duplicates/invalids based on existing DB for reporting
            for p in valid:
                if self.is_isrc_taken_normalized(p["iso_isrc"]):
                    skipped_dupe += 1

            # Skips already counted in parsed for invalid; compute:
            skipped_invalid = len([p for p in parsed if "skip" in p])

            # If dry-run, show summary then optionally proceed
            if dry:
                would_insert = len([p for p in valid if not self.is_isrc_taken_normalized(p["iso_isrc"])])
                self.logger.info(f"Dry-run: would_insert={would_insert}, dupes={skipped_dupe}, invalid={skipped_invalid}, errors={errors}")
                proceed = QMessageBox.question(
                    self, "Dry-run finished",
                    f"Would insert: {would_insert}\n"
                    f"Skipped (duplicates): {skipped_dupe}\n"
                    f"Skipped (invalid): {skipped_invalid}\n"
                    f"Errors: {errors}\n\n"
                    f"Proceed with import now?",
                    QMessageBox.Yes | QMessageBox.No
                ) == QMessageBox.Yes
                if not proceed:
                    self._audit("IMPORT", "Tracks", ref_id=file_path, details=f"mode=dry_only, would_ins={would_insert}, dup={skipped_dupe}, inv={skipped_invalid}, err={errors}")
                    self._audit_commit()
                    return
                # If proceeding, fall through to commit using the parsed data.

            # Commit path
            self.conn.execute("BEGIN")
            try:
                for p in valid:
                    if self.is_isrc_taken_normalized(p["iso_isrc"]):
                        continue  # counted as dupes already
                    self.conn.execute("SAVEPOINT row_import")
                    try:
                        main_artist_id = self.get_or_create_artist(p["artist"])
                        album_id = self.get_or_create_album(p["album"])

                        self.cursor.execute("""
                            INSERT INTO Tracks (isrc, isrc_compact, track_title, main_artist_id, album_id, release_date, track_length_sec, iswc, upc, genre)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            p["iso_isrc"], p["comp_isrc"], p["title"],
                            main_artist_id, album_id,
                            (p["rel_date"] or None),
                            (p["tlen_sec"] if p["tlen_sec"] is not None else None),
                            (p["iso_iswc"] or None),
                            p["upc"], p["genre"],
                        ))
                        track_id = int(self.cursor.lastrowid)

                        extras = self._parse_additional_artists(p["addl"])
                        self._replace_additional_artists_for_track(track_id, extras)

                        # Custom values (non-blob only)
                        for c in p["custom_fields"]:
                            if not c["name"] or not c["type"]:
                                continue
                            if c["type"] in ("blob_image","blob_audio"):
                                continue  # metadata-only export; nothing to import
                            fid = name_to_id.get((c["name"], c["type"]))
                            if not fid:
                                continue  # should not happen after pre-check
                            self.cursor.execute("""
                                INSERT INTO CustomFieldValues (track_id, field_def_id, value)
                                VALUES (?, ?, ?)
                                ON CONFLICT(track_id, field_def_id) DO UPDATE SET value=excluded.value
                            """, (track_id, fid, c.get("value") or ""))

                        self.conn.execute("RELEASE SAVEPOINT row_import")
                        inserted += 1
                    except Exception as e:
                        self.conn.execute("ROLLBACK TO SAVEPOINT row_import")
                        self.conn.execute("RELEASE SAVEPOINT row_import")
                        errors += 1
                self.conn.commit()
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Import transaction failed: {e}")
                QMessageBox.critical(self, "Import Error", f"Import failed:\n{e}")
                return

            self.refresh_table_preserve_view()
            self.populate_all_comboboxes()

            mode = "Import finished" if not dry else "Import finished (after dry-run)"
            self.logger.info(f"{mode}: inserted={inserted}, dupes={skipped_dupe}, invalid={skipped_invalid}, errors={errors}")
            self._audit("IMPORT", "Tracks", ref_id=file_path, details=f"mode={'commit_after_dry' if dry else 'commit'}, ins={inserted}, dup={skipped_dupe}, inv={skipped_invalid}, err={errors}")
            self._audit_commit()

            QMessageBox.information(
                self, mode,
                f"Inserted: {inserted}\n"
                f"Skipped (duplicates): {skipped_dupe}\n"
                f"Skipped (invalid): {skipped_invalid}\n"
                f"Errors: {errors}"
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
                self.cursor.execute(
                    "INSERT INTO ISRC_Prefix (id, prefix) VALUES (1, ?) "
                    "ON CONFLICT(id) DO UPDATE SET prefix=excluded.prefix",
                    (pref,)
                )
                self.conn.commit()
                self.logger.info(f"ISRC prefix updated to '{pref}'")
                self._audit("SETTINGS", "ISRC_Prefix", ref_id=1, details=f"prefix={pref}")
                self._audit_commit()
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Set ISRC prefix failed: {e}")
                QMessageBox.critical(self, "Error", f"Could not save prefix:\n{e}")

    def set_sena_number(self):
        row = self.cursor.execute("SELECT number FROM SENA WHERE id=1").fetchone()
        current = str(row[0]) if row else ""
        text, ok = QInputDialog.getText(self, "Set SENA Number", "Enter SENA Number:", text=current)
        if ok:
            try:
                self.cursor.execute(
                    "INSERT INTO SENA (id, number) VALUES (1, ?) "
                    "ON CONFLICT(id) DO UPDATE SET number=excluded.number",
                    ((text or "").strip(),)
                )
                self.conn.commit()
                self.logger.info("SENA number updated")
                self._audit("SETTINGS", "SENA", ref_id=1, details="updated")
                self._audit_commit()
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Set SENA number failed: {e}")
                QMessageBox.critical(self, "Error", f"Could not save SENA number:\n{e}")

    def set_btw_number(self):
        row = self.cursor.execute("SELECT nr FROM BTW WHERE id=1").fetchone()
        current = row[0] if row else ""
        text, ok = QInputDialog.getText(self, "Set BTW Number", "Enter BTW Number:", text=current)
        if ok:
            try:
                self.cursor.execute(
                    "INSERT INTO BTW (id, nr) VALUES (1, ?) "
                    "ON CONFLICT(id) DO UPDATE SET nr=excluded.nr",
                    ((text or "").strip(),)
                )
                self.conn.commit()
                self.logger.info("BTW number updated")
                self._audit("SETTINGS", "BTW", ref_id=1, details="updated")
                self._audit_commit()
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Set BTW failed: {e}")
                QMessageBox.critical(self, "Error", f"Could not save BTW number:\n{e}")

    def set_buma_info(self):
        row = self.cursor.execute("SELECT relatie_nummer FROM BUMA_STEMRA WHERE id=1").fetchone()
        current_rel = str(row[0]) if row else ""
        relatie_nummer, ok = QInputDialog.getText(self, "Set BUMA Relatie Nummer", "Enter Relatie Nummer:", text=current_rel)
        if ok:
            try:
                self.cursor.execute("""
                    INSERT INTO BUMA_STEMRA (id, relatie_nummer, ipi)
                    VALUES (1, ?, COALESCE((SELECT ipi FROM BUMA_STEMRA WHERE id=1), NULL))
                    ON CONFLICT(id) DO UPDATE SET relatie_nummer=excluded.relatie_nummer
                """, ((relatie_nummer or "").strip(),))
                self.conn.commit()
                self.logger.info("BUMA/STEMRA relatie nummer updated")
                self._audit("SETTINGS", "BUMA_STEMRA", ref_id=1, details="relatie_nummer updated")
                self._audit_commit()
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Set BUMA relatie nummer failed: {e}")
                QMessageBox.critical(self, "Error", f"Could not save BUMA relatie nummer:\n{e}")

    def set_ipi_info(self):
        row = self.cursor.execute("SELECT ipi FROM BUMA_STEMRA WHERE id=1").fetchone()
        current_ipi = str(row[0]) if row else ""
        ipi, ok = QInputDialog.getText(self, "Set BUMA IPI", "Enter IPI Number:", text=current_ipi)
        if ok:
            try:
                self.cursor.execute("""
                    INSERT INTO BUMA_STEMRA (id, relatie_nummer, ipi)
                    VALUES (1, COALESCE((SELECT relatie_nummer FROM BUMA_STEMRA WHERE id=1), NULL), ?)
                    ON CONFLICT(id) DO UPDATE SET ipi=excluded.ipi
                """, ((ipi or "").strip(),))
                self.conn.commit()
                self.logger.info("BUMA/STEMRA IPI updated")
                self._audit("SETTINGS", "BUMA_STEMRA", ref_id=1, details="ipi updated")
                self._audit_commit()
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Set BUMA IPI failed: {e}")
                QMessageBox.critical(self, "Error", f"Could not save BUMA IPI:\n{e}")

    def show_settings_summary(self):
        """View-only summary dialog (no editing)."""
        isrc = self.load_isrc_prefix() or "(not set)"
        sena = self.cursor.execute("SELECT number FROM SENA WHERE id=1").fetchone()
        btw  = self.cursor.execute("SELECT nr FROM BTW WHERE id=1").fetchone()
        buma = self.cursor.execute("SELECT relatie_nummer, ipi FROM BUMA_STEMRA WHERE id=1").fetchone()

        sena_txt = sena[0] if sena and sena[0] else "(not set)"
        btw_txt  = btw[0]  if btw  and btw[0]  else "(not set)"
        rel_txt  = buma[0] if buma and buma[0] else "(not set)"
        ipi_txt  = buma[1] if buma and buma[1] else "(not set)"
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
            ini_path = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / "settings.ini"
            s = QSettings(str(ini_path), QSettings.IniFormat)
            s.setFallbacksEnabled(False)
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
            ini_path = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / "settings.ini"
            s = QSettings(str(ini_path), QSettings.IniFormat)
            s.setFallbacksEnabled(False)

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
            keep_ids = {f["id"] for f in new_fields if f["id"] is not None}

            # Remove deleted defs (values cascade)
            for old in self.active_custom_fields:
                if old["id"] not in keep_ids:
                    self.cursor.execute("DELETE FROM CustomFieldDefs WHERE id=?", (old["id"],))

            # Upsert & order
            order = 0
            for f in new_fields:
                name = f["name"].strip()
                ftype = (f.get("field_type") or "text").strip()
                opts = f.get("options")
                if f["id"] is None:
                    self.cursor.execute(
                        "INSERT INTO CustomFieldDefs (name, active, sort_order, field_type, options) "
                        "VALUES (?, 1, ?, ?, ?)",
                        (name, order, ftype, opts)
                    )
                else:
                    self.cursor.execute(
                        "UPDATE CustomFieldDefs SET name=?, active=1, sort_order=?, field_type=?, options=? WHERE id=?",
                        (name, order, ftype, opts, f["id"])
                    )
                order += 1

            try:
                self.conn.commit()
            except Exception as e:
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


    def _on_custom_fields_changed(self):
        self.active_custom_fields = self.load_active_custom_fields()
        self._rebuild_table_headers()

        # Always rebind first (safe if duplicated)
        try:
            self.table.horizontalHeader().sectionMoved.connect(
                lambda *_: self._save_header_state()
            )
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
                # writes blob_value, mime_type, size_bytes (value=NULL) and respects triggers
                self.cf_save_value(track_id, field_id, value=None, blob_path=new_path)
                self.refresh_table_preserve_view(focus_id=track_id)
                return
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Custom BLOB save failed: {e}")
                QMessageBox.critical(self, "Custom Field Error", f"Failed to save file:\n{e}")
                return

        # --- Non-BLOB editors (unchanged) ---
        row = self.cursor.execute(
            "SELECT value FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
            (track_id, field_id)
        ).fetchone()
        current_val = row[0] if row else ""

        if field_type == "dropdown":
            choices = options[:] if options else []
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
                try:
                    self.cursor.execute(
                        "UPDATE CustomFieldDefs SET options=? WHERE id=?",
                        (json.dumps(options), field_id)
                    )
                    self.conn.commit()
                except Exception as e:
                    self.logger.exception(f"Failed to update dropdown options: {e}")
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
        try:
            self.cursor.execute("""
                INSERT INTO CustomFieldValues (track_id, field_def_id, value)
                VALUES (?, ?, ?)
                ON CONFLICT(track_id, field_def_id) DO UPDATE SET value=excluded.value
            """, (track_id, field_id, new_val))
            self.conn.commit()
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
                                if hasattr(self, "_get_track_title"):
                                    track_title = self._get_track_title(track_id) or f"track_{track_id}"
                                else:
                                    row_title = self.cursor.execute("SELECT track_title FROM Tracks WHERE id=?", (track_id,)).fetchone()
                                    track_title = row_title[0] if row_title and row_title[0] else f"track_{track_id}"
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
                                    self.cf_delete_blob(track_id, field["id"])
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
                if hasattr(self, "_get_track_title"):
                    track_title = self._get_track_title(track_id) or f"track_{track_id}"
                else:
                    row_title = self.cursor.execute("SELECT track_title FROM Tracks WHERE id=?", (track_id,)).fetchone()
                    track_title = row_title[0] if row_title and row_title[0] else f"track_{track_id}"
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

        # Short debug — safe and fast
        try:
            head = data[:16] if isinstance(data, (bytes, bytearray)) else b""
            print("[DEBUG] First 16 bytes (hex):", head.hex(), " len:", len(data) if hasattr(data, "__len__") else "n/a")
        except Exception:
            pass

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
            self.table.horizontalHeader().setSectionsMovable(bool(enabled))
            self._save_header_state()
            self.settings.setValue(f"{self._table_settings_prefix()}/columns_movable", bool(enabled))
            self.settings.sync()
        except Exception as e:
            logging.warning("Exception while toggling columns movable: %s", e)
            pass


    def _save_header_state(self):
        try:
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
                # self.logger.info("Saved header visual order (%s): %s", prefix, labels_visual)
            except Exception as e:
                self.logger.warning("Failed to save header visual order JSON: %s", e)

            self.settings.sync()
        except Exception as e:
            self.logger.exception("Error saving header state: %s", e)

    def _load_header_state(self):
        try:
            header = self.table.horizontalHeader()
            prefix = self._table_settings_prefix()

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

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            bkp_dir = self.database_dir / "backups"
            bkp_dir.mkdir(parents=True, exist_ok=True)
            dst = bkp_dir / f"{src.stem}_{ts}.db"

            # Ensure all writes are flushed
            try:
                self.conn.commit()
            except Exception:
                pass

            backed_up = False
            # Preferred: Online Backup API (includes all schema + data, even custom columns)
            try:
                with sqlite3.connect(str(dst)) as bkp_conn:
                    self.conn.backup(bkp_conn)
                backed_up = True
                self.logger.info("Backup: used sqlite3.Connection.backup API")
            except Exception as e:
                self.logger.warning(f"Backup API failed, trying VACUUM INTO: {e}")

            # Fallback: VACUUM INTO (SQLite 3.27+)
            if not backed_up:
                try:
                    with sqlite3.connect(str(src)) as src_conn:
                        src_conn.execute(f"VACUUM INTO '{dst.as_posix()}'")
                    backed_up = True
                    self.logger.info("Backup: used VACUUM INTO")
                except Exception as e:
                    self.logger.warning(f"VACUUM INTO failed, falling back to file copy: {e}")

            # Last resort: file copy (also copy companion WAL/SHM if present)
            if not backed_up:
                try:
                    # Close current connection temporarily to ensure file consistency
                    try:
                        self.conn.close()
                    except Exception:
                        pass

                    shutil.copy2(src, dst)
                    for ext in (".wal", ".shm"):
                        comp = src.with_suffix(src.suffix + ext)
                        if comp.exists():
                            shutil.copy2(comp, dst.with_suffix(dst.suffix + ext))

                    # Reopen
                    self.open_database(str(src))
                    backed_up = True
                    self.logger.info("Backup: used file copy")
                except Exception as e:
                    raise RuntimeError(f"Backup failed during file copy: {e}")

            # Verify integrity of backup
            try:
                with sqlite3.connect(str(dst)) as check_conn:
                    row = check_conn.execute("PRAGMA integrity_check").fetchone()
                    res = row[0] if row else "unknown"
                    if res.lower() != "ok":
                        raise RuntimeError(f"Integrity check failed for backup: {res}")
            except Exception as e:
                raise RuntimeError(f"Backup created but integrity verification failed: {e}")

            QMessageBox.information(self, "Backup", f"Backup created:\n{dst}")
            self.logger.info(f"Database backed up to {dst}")
            try:
                self._audit("BACKUP", "DB", ref_id=str(dst), details="Full DB (schema+data), custom columns included")
                self._audit_commit()
            except Exception:
                pass

        except Exception as e:
            self.logger.exception(f"Backup failed: {e}")
            QMessageBox.critical(self, "Backup Error", f"Failed to backup:\n{e}")

    def verify_integrity(self):
        try:
            row = self.cursor.execute("PRAGMA integrity_check").fetchone()
            res = row[0] if row else "unknown"
            QMessageBox.information(self, "Integrity Check", f"Result: {res}")
            self.logger.info(f"Integrity check: {res}")
            self._audit("VERIFY", "DB", ref_id=self.current_db_path, details=res)
            self._audit_commit()
        except Exception as e:
            self.logger.exception(f"Integrity check failed: {e}")
            QMessageBox.critical(self, "Integrity Error", f"Failed to verify:\n{e}")


    def restore_database(self):
        """Restore the database from a backup .db file.

        This completely replaces the current DB file with the selected backup,
        ensuring that **all** schema (including user-added columns) and data are restored.
        """
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, "Restore...Backup", str(self.database_dir / "backups"), "SQLite DB (*.db)"
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

            # Close current connection to release file handles
            try:
                self.conn.commit()
            except Exception:
                pass
            try:
                self.conn.close()
            except Exception:
                pass

            dst = Path(self.current_db_path)
            src = Path(path)

            # Safety copy of current DB (one-shot undo)
            try:
                safe_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_dir = self.database_dir / "backups" / "pre_restore"
                safe_dir.mkdir(parents=True, exist_ok=True)
                safe_copy = safe_dir / f"{dst.stem}_pre_restore_{safe_ts}.db"
                if dst.exists():
                    shutil.copy2(dst, safe_copy)
                    for ext in (".wal", ".shm"):
                        comp = dst.with_suffix(dst.suffix + ext)
                        if comp.exists():
                            shutil.copy2(comp, safe_copy.with_suffix(safe_copy.suffix + ext))
                self.logger.info(f"Pre-restore safety copy saved to {safe_copy}")
            except Exception as e:
                # Non-fatal; continue restoring
                self.logger.warning(f"Failed to create pre-restore safety copy: {e}")

            # Replace DB file
            shutil.copy2(src, dst)

            # Remove any stale WAL/SHM from previous DB
            for ext in (".wal", ".shm"):
                stale = dst.with_suffix(dst.suffix + ext)
                try:
                    if stale.exists():
                        stale.unlink()
                except Exception:
                    pass

            # Re-open the restored DB
            self.open_database(str(dst))

            # Verify integrity, then refresh UI
            try:
                row = self.cursor.execute("PRAGMA integrity_check").fetchone()
                res = row[0] if row else "unknown"
                if str(res).lower() != "ok":
                    raise RuntimeError(f"Integrity check failed after restore: {res}")
            except Exception as e:
                raise RuntimeError(f"Restore integrity verification failed: {e}")

            self.refresh_table_preserve_view()
            QMessageBox.information(self, "Restore", "Database restored successfully (schema + data).")
            self.logger.warning(f"Database restored from {path}")
            try:
                self._audit("RESTORE", "DB", ref_id=path, details=f"restored to {dst}")
                self._audit_commit()
            except Exception:
                pass

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
        row = self.cursor.execute(
            "SELECT field_type FROM CustomFieldDefs WHERE id=?", (field_def_id,)
        ).fetchone()
        return row[0] if row else "text"

    def cf_save_value(self, track_id: int, field_def_id: int, *, value=None, blob_path: str|None=None):
        ftype = self.cf_get_field_type(field_def_id)
        if ftype in ("blob_image", "blob_audio"):
            # If no path provided (e.g., user cancelled), do nothing to avoid violating triggers
            if blob_path is None:
                return
            if ftype == "blob_image":
                if not _is_valid_image_path(blob_path):
                    raise ValueError("Selected file is not a recognized image")
            else:
                if not _is_valid_audio_path(blob_path):
                    raise ValueError("Selected file is not a recognized audio format")

            blob_data = _read_blob_from_path(blob_path)
            mime, _ = mimetypes.guess_type(blob_path)
            size = len(blob_data)

            self.cursor.execute(
                "INSERT INTO CustomFieldValues (track_id, field_def_id, value, blob_value, mime_type, size_bytes) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(track_id, field_def_id) DO UPDATE SET "
                "value=excluded.value, blob_value=excluded.blob_value, mime_type=excluded.mime_type, size_bytes=excluded.size_bytes",
                (track_id, field_def_id, None, sqlite3.Binary(blob_data), mime, size)
            )
            self.conn.commit()
            return

        # Non-BLOB types
        self.cursor.execute(
            "INSERT INTO CustomFieldValues (track_id, field_def_id, value, blob_value, mime_type, size_bytes) "
            "VALUES (?, ?, ?, NULL, NULL, 0) "
            "ON CONFLICT(track_id, field_def_id) DO UPDATE SET "
            "value=excluded.value, blob_value=NULL, mime_type=NULL, size_bytes=0",
            (track_id, field_def_id, value)
        )
        self.conn.commit()


    def cf_fetch_blob(self, track_id: int, field_def_id: int):
        row = self.cursor.execute(
            "SELECT blob_value, mime_type FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
            (track_id, field_def_id)
        ).fetchone()
        if not row or row[0] is None:
            raise FileNotFoundError("No file stored for this field.")
        return row[0], row[1]

    def cf_export_blob(self, track_id: int, field_def_id: int, parent_widget=None, suggested_basename: str|None=None):
        try:
            data, mime = self.cf_fetch_blob(track_id, field_def_id)
        except Exception as e:
            QMessageBox.critical(parent_widget or None, "Export failed", str(e))
            return
        ext = None
        if mime:
            ext = mimetypes.guess_extension(mime) or None
        if not ext:
            ext = ".png" if (mime and mime.startswith("image/")) else (".wav" if (mime and mime.startswith("audio/")) else ".bin")
        if suggested_basename is None:
            name_row = self.cursor.execute("SELECT name FROM CustomFieldDefs WHERE id=?", (field_def_id,)).fetchone()
            suggested_basename = (name_row[0] if name_row and name_row[0] else "file")

        default_filename = self._make_default_export_filename(track_id, field_def_id, mime)
        dest_path, _ = QFileDialog.getSaveFileName(parent_widget or None, "Export file", default_filename, "All files (*)")
        if not dest_path:
            return
        try:
            Path(dest_path).write_bytes(data)
            QMessageBox.information(parent_widget or None, "Export", f"Saved:\n{dest_path}")
        except Exception as e:
            QMessageBox.critical(parent_widget or None, "Export failed", str(e))

    def _attach_blob_for_cell(self, track_id: int, field_def_id: int, field_type: str, field_name: str):
        if field_type == "blob_image":
            flt = "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff);;All files (*)"
        else:
            flt = "Audio (*.wav *.aif *.aiff *.mp3 *.flac *.m4a *.aac *.ogg *.opus);;All files (*)"
        p, _ = QFileDialog.getOpenFileName(self, f"Attach file: {field_name}", "", flt)
        if not p:
            return
        try:
            self.cf_save_value(track_id, field_def_id, value=None, blob_path=p)
            self.refresh_table_preserve_view(focus_id=track_id)
        except Exception as e:
            self.conn.rollback()
            self.logger.exception(f"Attach blob failed: {e}")
            QMessageBox.critical(self, "Custom Field Error", f"Failed to attach file:\n{e}")

    # ---------------------- BLOB CF helpers v2 (get/export/delete/format) ----------------------
    def cf_get_value_meta(self, track_id: int, field_def_id: int):
        """
        Returns dict with keys for a custom field value:
            - value (TEXT)
            - has_blob (bool)
            - size_bytes (int or 0)
            - mime_type (str or None)
        """
        row = self.cursor.execute(
            "SELECT value, blob_value, size_bytes, mime_type FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
            (track_id, field_def_id)
        ).fetchone()
        if not row:
            return {"value": None, "has_blob": False, "size_bytes": 0, "mime_type": None}
        value, blob_value, size_bytes, mime_type = row
        return {
            "value": value,
            "has_blob": blob_value is not None,
            "size_bytes": int(size_bytes or 0) if size_bytes is not None else 0,
            "mime_type": mime_type,
        }

    def cf_has_blob(self, track_id: int, field_def_id: int) -> bool:
        row = self.cursor.execute(
            "SELECT blob_value FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
            (track_id, field_def_id)
        ).fetchone()
        return bool(row and row[0] is not None)

    def cf_fetch_blob(self, track_id: int, field_def_id: int):
        row = self.cursor.execute(
            "SELECT blob_value, mime_type FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
            (track_id, field_def_id)
        ).fetchone()
        if not row or row[0] is None:
            raise FileNotFoundError("No file stored for this field.")
        return row[0], row[1]

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
            name_row = self.cursor.execute("SELECT name FROM CustomFieldDefs WHERE id=?", (field_def_id,)).fetchone()
            suggested_basename = (name_row[0] if name_row and name_row[0] else "file")
        default_filename = f"{suggested_basename}{ext}"
        dest_path, _ = QFileDialog.getSaveFileName(parent_widget or None, "Export file", default_filename, "All files (*)")
        if not dest_path:
            return
        try:
            Path(dest_path).write_bytes(data)
            QMessageBox.information(parent_widget or None, "Export", f"Saved:\n{dest_path}")
        except Exception as e:
            QMessageBox.critical(parent_widget or None, "Export failed", str(e))

    def cf_delete_blob(self, track_id: int, field_def_id: int):
        """
        Remove the BLOB by deleting the row from CustomFieldValues for this (track_id, field_def_id).
        This avoids violating triggers that require blob_value on UPDATE for blob fields.
        """
        self.cursor.execute(
            "DELETE FROM CustomFieldValues WHERE track_id=? AND field_def_id=?",
            (track_id, field_def_id)
        )
        self.conn.commit()

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

            if parent.is_isrc_taken_normalized(iso_isrc, exclude_track_id=row_id):
                QMessageBox.critical(self, "Duplicate ISRC", "Another record already uses this ISRC.")
                return

            main_artist_id = parent.get_or_create_artist(self.artist_name.currentText())
            album_id = parent.get_or_create_album(self.album_title.currentText())
            

            # --- patched: use shared cursor, not a new one ---
            cur = parent.cursor
            cur.execute("""
                UPDATE Tracks SET
                    isrc=?, isrc_compact=?, track_title=?, main_artist_id=?, album_id=?, release_date=?,
                    track_length_sec=?, iswc=?, upc=?, genre=?
                WHERE id=?
            """, (
                iso_isrc,
                comp,
                new_track_title,
                main_artist_id,
                album_id,
                self.release_date.selectedDate().toString("yyyy-MM-dd"),
                hms_to_seconds(self.len_h.value(), self.len_m.value(), self.len_s.value()),
                (iso_iswc or None),
                (new_upc_raw or None),
                (new_genre or None),
                row_id
            ))

            self.parent._replace_additional_artists_for_track(row_id, new_additional_artist)

            parent.conn.commit()
            # --- patched: ensure WAL contents are flushed to the main db file ---
            parent.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

            try:
                parent.logger.info(f"Track updated id={row_id} isrc={iso_isrc}")
                parent._audit("UPDATE", "Track", ref_id=row_id, details=f"isrc={iso_isrc}")
                parent._audit_commit()
            except Exception as audit_err:
                parent.logger.warning(f"Audit failed: {audit_err}")

            parent.refresh_table_preserve_view(focus_id=row_id)
            self.accept()

        except Exception as e:
            parent = self.parent()
            if parent and hasattr(parent, "conn"):
                parent.conn.rollback()
                parent.logger.exception(f"Update failed: {e}")
            QMessageBox.critical(self, "Update Error", f"Failed to update record:\n{e}")


class _AudioPreviewDialog(QDialog):
    def __init__(self, parent, file_path: str, title: str):
        super().__init__(parent)

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
if __name__ == '__main__':
    settings = init_settings()
    APP_UID = settings.value("app/uid", type=str)

    # Qt app
    app = QApplication(sys.argv)

    # Single-instance with crash recovery (60 s stale timeout)
    lock = enforce_single_instance(60000)
    if lock is None:
        QMessageBox.warning(None, "Already running", f"{APP_NAME} is already running.")
        sys.exit(0)

    # Keep the lock alive for the app lifetime
    app._single_instance_lock = lock

    window = App()
    window.showMaximized()
    sys.exit(app.exec())

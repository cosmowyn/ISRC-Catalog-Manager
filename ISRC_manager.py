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
from dataclasses import fields as dataclass_fields
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import (
    QRegularExpression,
    Signal,
    QEvent,
    Qt,
    QDate,
    QPoint,
    QRect,
    QSettings,
    QStandardPaths,
    QByteArray,
    QUrl,
    QEvent,
    QTimer,
    QEventLoop,
    QSortFilterProxyModel,
    QItemSelectionModel,
    QtMsgType,
    qInstallMessageHandler,
)

from PySide6.QtGui import (
    QDesktopServices,
    QCursor,
    QAction,
    QIcon,
    QAction,
    QKeySequence,
    QImage,
    QPixmap,
    QStandardItemModel,
    QStandardItem,
    QColor,
    QFont,
    QPalette,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QListView,
    QMenuBar,
    QListWidget,
    QListWidgetItem,
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QCalendarWidget,
    QRadioButton,
    QMenuBar,
    QMenu,
    QInputDialog,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QDialog,
    QMainWindow,
    QSizePolicy,
    QComboBox,
    QCompleter,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QToolBar,
    QFrame,
    QSpinBox,
    QScrollArea,
    QSlider,
    QAbstractItemView,
    QFormLayout,
    QProgressBar,
    QTableView,
    QTabWidget,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QPlainTextEdit,
    QStatusBar,
    QCheckBox,
    QColorDialog,
    QFontComboBox,
    QTextBrowser,
    QToolButton,
    QSplitter,
    QDockWidget,
)

from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QAudioDecoder, QAudioFormat

from isrc_manager.authenticity import (
    AUTHENTICITY_FEATURE_AVAILABLE,
    AudioAuthenticityService,
    AudioWatermarkService,
    AuthenticityExportPreviewDialog,
    AuthenticityKeysDialog,
    AuthenticityKeyService,
    AuthenticityManifestService,
    AuthenticityVerificationDialog,
    PROVENANCE_ONLY_SUFFIXES,
    VERIFICATION_INPUT_SUFFIXES,
    authenticity_unavailable_message,
)
from isrc_manager.history import (
    HistoryCleanupBlockedError,
    HistoryManager,
    HistoryStorageCleanupService,
    SessionHistoryManager,
)
from isrc_manager.history.dialogs import HistoryCleanupDialog, HistoryDialog
from isrc_manager.constants import (
    APP_NAME,
    DEFAULT_AUTO_SNAPSHOT_ENABLED,
    DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    DEFAULT_BASE_HEADERS,
    DEFAULT_HIDDEN_CUSTOM_COLUMN_NAMES,
    DEFAULT_HISTORY_AUTO_CLEANUP_ENABLED,
    DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
    DEFAULT_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
    DEFAULT_HISTORY_RETENTION_MODE,
    DEFAULT_HISTORY_STORAGE_BUDGET_MB,
    DEFAULT_ICON_PATH,
    DEFAULT_WINDOW_TITLE,
    FIELD_TYPE_CHOICES,
    HISTORY_RETENTION_MODE_BALANCED,
    HISTORY_RETENTION_MODE_CHOICES,
    HISTORY_RETENTION_MODE_CUSTOM,
    HISTORY_RETENTION_MODE_LEAN,
    HISTORY_RETENTION_MODE_MAXIMUM_SAFETY,
    HISTORY_RETENTION_MODE_PRESETS,
    MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    MAX_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
    MAX_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
    MAX_HISTORY_STORAGE_BUDGET_MB,
    MIN_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    MIN_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
    MIN_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
    MIN_HISTORY_STORAGE_BUDGET_MB,
    PROMOTED_CUSTOM_FIELD_NAMES,
    SCHEMA_TARGET,
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
from isrc_manager.domain.standard_fields import (
    standard_field_spec_for_label,
    standard_media_specs_by_label,
)
from isrc_manager.domain.timecode import hms_to_seconds, parse_hms_text, seconds_to_hms
from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    infer_storage_mode,
    normalize_storage_mode,
    sanitize_export_basename,
)
from isrc_manager.services.gs1_mapping import (
    COMMON_CLASSIFICATION_CHOICES,
    COMMON_LANGUAGE_CHOICES,
    COMMON_MARKET_CHOICES,
    COMMON_PACKAGING_CHOICES,
)
from isrc_manager.help_content import render_help_html
from isrc_manager.app_bootstrap import run_desktop_application
from isrc_manager.blob_icons import (
    BlobIconDialog,
    BlobIconEditorWidget,
    BlobIconSettingsService,
    default_blob_icon_settings,
    describe_blob_icon_spec,
    finalize_blob_icon_spec,
    icon_from_blob_icon_spec,
    normalize_blob_icon_settings,
)
from isrc_manager.catalog_workspace import (
    ensure_catalog_workspace_dock,
    refresh_catalog_workspace_docks,
)
from isrc_manager.main_window_shell import build_main_window_shell
from isrc_manager.paths import (
    STORAGE_STATE_DEFERRED,
    configure_qt_application_identity,
    resolve_app_storage_layout,
    settings_path,
)
from isrc_manager.qss_autocomplete import QssCodeEditor
from isrc_manager.qss_reference import (
    QssReferenceEntry,
    collect_qss_reference_entries,
    ensure_widget_object_names as _ensure_qss_widget_object_names,
    repolish_widget_tree as _repolish_qss_widget_tree,
)
from isrc_manager.theme_builder import (
    THEME_COLOR_FIELD_SPECS,
    THEME_METRIC_FIELD_SPECS,
    THEME_PAGE_SPECS,
    build_theme_palette as build_app_theme_palette,
    build_theme_stylesheet as build_app_theme_stylesheet,
    color_relative_luminance as theme_color_relative_luminance,
    contrast_ratio as theme_contrast_ratio,
    effective_theme_settings as build_effective_theme_settings,
    normalize_theme_color as normalize_app_theme_color,
    normalize_theme_font_family as normalize_app_theme_font_family,
    normalize_theme_settings as normalize_app_theme_settings,
    normalize_theme_string as normalize_app_theme_string,
    pick_contrasting_color as pick_theme_contrasting_color,
    shift_color as shift_theme_color,
    theme_setting_defaults as default_theme_settings,
    theme_setting_keys as app_theme_setting_keys,
)
from isrc_manager.starter_themes import (
    STARTER_THEME_SPECS,
    starter_theme_descriptions,
    starter_theme_library,
    starter_theme_names,
)
from isrc_manager.gs1_dialog import GS1MetadataDialog
from isrc_manager.assets import AssetService
from isrc_manager.assets.dialogs import AssetBrowserDialog, AssetBrowserPanel
from isrc_manager.app_dialogs import (
    AboutDialog,
    ActionRibbonDialog,
    ApplicationLogDialog,
    CustomColumnsDialog,
    DiagnosticsDialog,
    HelpContentsDialog,
)
from isrc_manager.contracts import ContractService
from isrc_manager.contracts.dialogs import ContractBrowserDialog, ContractBrowserPanel
from isrc_manager.exchange.dialogs import ExchangeImportDialog
from isrc_manager.exchange.repertoire_service import RepertoireExchangeService
from isrc_manager.exchange.models import ExchangeImportReport, ExchangeInspection
from isrc_manager.exchange.service import ExchangeService
from isrc_manager.parties import PartyService
from isrc_manager.parties.dialogs import PartyManagerDialog, PartyManagerPanel
from isrc_manager.quality.dialogs import QualityDashboardDialog
from isrc_manager.quality.models import QualityIssue
from isrc_manager.quality.service import QualityDashboardService
from isrc_manager.releases import (
    ReleasePayload,
    ReleaseRecord,
    ReleaseService,
    ReleaseTrackPlacement,
)
from isrc_manager.releases.dialogs import ReleaseBrowserPanel, ReleaseEditorDialog
from isrc_manager.rights import RightsService
from isrc_manager.rights.dialogs import RightsBrowserDialog, RightsBrowserPanel
from isrc_manager.search import GlobalSearchService, RelationshipExplorerService
from isrc_manager.search.dialogs import GlobalSearchPanel
from isrc_manager.selection_scope import TrackChoice
from isrc_manager.startup_progress import StartupPhase, startup_phase_label
from isrc_manager.startup_splash import StartupFeedbackProtocol
from isrc_manager.services.db_access import DatabaseWriteCoordinator, SQLiteConnectionFactory
from isrc_manager.services.bulk_edit import MIXED_VALUE, shared_bulk_value, should_apply_bulk_change
from isrc_manager.services.sqlite_utils import safe_wal_checkpoint
from isrc_manager.services import (
    AssetVersionPayload,
    CatalogAdminService,
    CatalogReadService,
    ContractPayload,
    CustomFieldDefinitionService,
    CustomFieldValueService,
    DatabaseMaintenanceService,
    DatabaseSchemaService,
    DatabaseSessionService,
    GS1ContractEntry,
    GS1ContractImportError,
    GS1IntegrationService,
    GS1ProfileDefaults,
    GS1MetadataRepository,
    GS1SettingsService,
    GS1TemplateAsset,
    HistoryRetentionSettings,
    LegacyLicenseMigrationService,
    LegacyPromotedFieldRepairService,
    XMLExportService,
    XMLImportService,
    LicenseService,
    PartyPayload,
    ProfileKVService,
    ProfileStoreService,
    ProfileWorkflowService,
    RepertoireWorkflowService,
    RightPayload,
    SettingsReadService,
    SettingsMutationService,
    TrackCreatePayload,
    TrackSnapshot,
    TrackService,
    TrackUpdatePayload,
    WorkPayload,
)
from isrc_manager.settings import enforce_single_instance, init_settings
from isrc_manager.tasks import BackgroundTaskManager, TaskFailure
from isrc_manager.tasks.app_services import BackgroundAppServiceFactory
from isrc_manager.tasks.history_helpers import run_file_history_action, run_snapshot_history_action
from isrc_manager.media import AudioConversionService
from isrc_manager.media.derivatives import (
    MANAGED_DERIVATIVE_KIND_LOSSY,
    MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC,
    ExternalAudioConversionCoordinator,
    ExternalAudioConversionRequest,
    ExternalAudioConversionResult,
    ManagedDerivativeExportCoordinator,
    ManagedDerivativeExportRequest,
    ManagedDerivativeExportResult,
)
from isrc_manager.storage_migration import (
    PREFERRED_STATE_CONFLICT,
    PREFERRED_STATE_EMPTY,
    PREFERRED_STATE_RESUMABLE_STAGE,
    PREFERRED_STATE_SAFE_NOISE,
    PREFERRED_STATE_VALID_COMPLETE,
    StorageMigrationService,
)
from isrc_manager.tags import (
    AudioTagService,
    BulkAudioAttachService,
    TaggedAudioExportService,
    build_catalog_tag_data,
    catalog_metadata_to_tags,
    merge_imported_tags,
)
from isrc_manager.tags.dialogs import BulkAudioAttachDialog, TagPreviewDialog
from isrc_manager.tags.models import (
    AudioTagData,
    ArtworkPayload,
    BulkAudioAttachTrackCandidate,
    TaggedAudioExportItem,
    TaggedAudioExportPlanItem,
)
from isrc_manager.ui_common import (
    DatePickerDialog,
    FocusWheelCalendarWidget,
    FocusWheelComboBox,
    FocusWheelFontComboBox,
    FocusWheelSlider,
    FocusWheelSpinBox,
    TwoDigitSpinBox,
    _add_standard_dialog_header,
    _apply_standard_dialog_chrome,
    _apply_standard_widget_chrome,
    _compose_widget_stylesheet,
    _create_action_button_grid,
    _create_scrollable_dialog_content,
    _create_round_help_button,
    _create_standard_section,
)
from isrc_manager.works import WorkService
from isrc_manager.works.dialogs import WorkBrowserPanel, WorkEditorDialog


class _JsonLogFormatter(logging.Formatter):
    """Writes structured JSON lines for troubleshooting and traceability."""

    EXTRA_ATTRS = (
        "event",
        "action",
        "entity",
        "entity_id",
        "ref_id",
        "status",
        "profile",
        "db_path",
        "details",
        "path",
        "result",
        "repair_key",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for attr in self.EXTRA_ATTRS:
            value = getattr(record, attr, None)
            if value in (None, "", [], {}, ()):
                continue
            payload[attr] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, default=str)


_PREVIOUS_QT_MESSAGE_HANDLER = None


def _storage_mode_choice_text(mode: str | None) -> str:
    normalized = normalize_storage_mode(mode, default=None)
    if normalized == STORAGE_MODE_DATABASE:
        return "Store in Database"
    return "Store as Managed File"


def _prompt_storage_mode_choice(
    parent,
    *,
    title: str,
    subject: str,
    default_mode: str | None = None,
) -> str | None:
    default_normalized = normalize_storage_mode(default_mode, default=STORAGE_MODE_MANAGED_FILE)
    dialog = QMessageBox(parent)
    dialog.setIcon(QMessageBox.Question)
    dialog.setWindowTitle(title)
    dialog.setText(f"How should {subject} be stored?")
    dialog.setInformativeText(
        "Database mode keeps the raw file bytes in the profile database. "
        "Managed file mode copies the file into the app-controlled storage folder and stores only the managed path."
    )
    db_button = dialog.addButton("Store in Database", QMessageBox.AcceptRole)
    file_button = dialog.addButton("Store as Managed File", QMessageBox.AcceptRole)
    dialog.addButton(QMessageBox.Cancel)
    dialog.setDefaultButton(
        file_button if default_normalized == STORAGE_MODE_MANAGED_FILE else db_button
    )
    dialog.exec()
    clicked = dialog.clickedButton()
    if clicked is db_button:
        return STORAGE_MODE_DATABASE
    if clicked is file_button:
        return STORAGE_MODE_MANAGED_FILE
    return None


def _install_qt_message_filter() -> None:
    global _PREVIOUS_QT_MESSAGE_HANDLER
    if _PREVIOUS_QT_MESSAGE_HANDLER is not None:
        return

    def _handler(mode, context, message):
        category = getattr(context, "category", "") or ""
        if category == "qt.multimedia.ffmpeg" and mode in (
            QtMsgType.QtDebugMsg,
            QtMsgType.QtInfoMsg,
        ):
            return
        if category == "qt.qpa.fonts" and "Populating font family aliases took" in message:
            return
        if _PREVIOUS_QT_MESSAGE_HANDLER is not None:
            _PREVIOUS_QT_MESSAGE_HANDLER(mode, context, message)
            return
        sys.stderr.write(f"{message}\n")

    _PREVIOUS_QT_MESSAGE_HANDLER = qInstallMessageHandler(_handler)


# =============================================================================
# Custom Columns Dialog (with type + options)
# =============================================================================
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
            if (
                hasattr(app, "history_manager")
                and getattr(app, "history_manager", None) is not None
            ):
                self._history_before_settings = app.history_manager.capture_setting_states(
                    [self.settings_key]
                )
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
                configure_qt_application_identity()
                s = QSettings(str(settings_path()), QSettings.IniFormat)
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
# Consolidated Application Settings Dialog
# =============================================================================
class ApplicationSettingsDialog(QDialog):
    CUSTOM_THEME_LABEL = "Custom Theme"
    COLOR_FIELD_SPECS = THEME_COLOR_FIELD_SPECS
    METRIC_FIELD_SPECS = THEME_METRIC_FIELD_SPECS
    THEME_PAGE_SPECS = THEME_PAGE_SPECS
    HISTORY_RETENTION_MODE_SPECS = (
        (
            HISTORY_RETENTION_MODE_MAXIMUM_SAFETY,
            "Maximum Safety",
            "Keeps more automatic snapshots and never ages pre-restore safety copies automatically.",
        ),
        (
            HISTORY_RETENTION_MODE_BALANCED,
            "Balanced",
            "Balances automatic cleanup with a moderate automatic snapshot history and aged safety-copy pruning.",
        ),
        (
            HISTORY_RETENTION_MODE_LEAN,
            "Lean",
            "Uses a smaller automatic snapshot history and faster cleanup for constrained storage budgets.",
        ),
        (
            HISTORY_RETENTION_MODE_CUSTOM,
            "Custom",
            "Uses your manual cleanup and retention values instead of a preset.",
        ),
    )

    def __init__(
        self,
        *,
        window_title: str,
        icon_path: str,
        artist_code: str,
        auto_snapshot_enabled: bool,
        auto_snapshot_interval_minutes: int,
        isrc_prefix: str,
        sena_number: str,
        btw_number: str,
        buma_relatie_nummer: str,
        buma_ipi: str,
        gs1_template_asset: GS1TemplateAsset | None,
        gs1_contracts_csv_path: str,
        gs1_contract_entries: tuple[GS1ContractEntry, ...] | list[GS1ContractEntry],
        gs1_active_contract_number: str,
        gs1_target_market: str,
        gs1_language: str,
        gs1_brand: str,
        gs1_subbrand: str,
        gs1_packaging_type: str,
        gs1_product_classification: str,
        theme_settings: dict[str, object] | None,
        stored_themes: dict[str, dict[str, object]] | None,
        current_profile_path: str,
        blob_icon_settings: dict[str, object] | None = None,
        history_retention_mode: str = DEFAULT_HISTORY_RETENTION_MODE,
        history_auto_cleanup_enabled: bool = DEFAULT_HISTORY_AUTO_CLEANUP_ENABLED,
        history_storage_budget_mb: int = DEFAULT_HISTORY_STORAGE_BUDGET_MB,
        history_auto_snapshot_keep_latest: int = DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
        history_prune_pre_restore_copies_after_days: int = (
            DEFAULT_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS
        ),
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("applicationSettingsDialog")
        self.setWindowTitle("Application Settings")
        self.setModal(True)
        self.setMinimumSize(1320, 880)
        self.resize(1400, 920)
        self._theme_settings = dict(theme_settings or {})
        self._bundled_theme_order = tuple(spec.name for spec in STARTER_THEME_SPECS)
        self._bundled_theme_names = frozenset(self._bundled_theme_order)
        self._bundled_theme_descriptions = starter_theme_descriptions()
        self._stored_themes = starter_theme_library()
        self._stored_themes.update(
            {
                str(name): dict(values or {})
                for name, values in dict(stored_themes or {}).items()
                if str(name).strip() and str(name) not in self._bundled_theme_names
            }
        )
        self._theme_color_edits = {}
        self._theme_color_swatches = {}
        self._theme_metric_spins = {}
        self._blob_icon_settings = normalize_blob_icon_settings(blob_icon_settings)
        self._blob_icon_original_values = normalize_blob_icon_settings(blob_icon_settings)
        self._blob_icon_editors: dict[str, BlobIconEditorWidget] = {}
        self._blob_icon_preview_labels: dict[str, QLabel] = {}
        self._qss_reference_entries: list[QssReferenceEntry] = []
        self._qss_filtered_reference_entries: list[QssReferenceEntry] = []
        self._theme_change_tracking_enabled = True
        self._history_retention_sync_enabled = True
        self._theme_original_values = normalize_app_theme_settings(self._theme_settings)
        self._settings_builder_specs = (
            *self.THEME_PAGE_SPECS[:-1],
            (
                "blob_icons",
                "Blob Icons",
                "Choose the audio and image badges shown when a record contains stored blob media. These settings stay separate from theme presets.",
            ),
            self.THEME_PAGE_SPECS[-1],
        )
        self._theme_preview_timer = QTimer(self)
        self._theme_preview_timer.setSingleShot(True)
        self._theme_preview_timer.setInterval(120)
        self._theme_preview_timer.timeout.connect(self._refresh_theme_previews)
        self.gs1_integration_service = getattr(parent, "gs1_integration_service", None)
        self._gs1_template_profile = None
        self._gs1_template_asset = gs1_template_asset
        self._pending_gs1_template_path = ""
        self._gs1_default_option_combos: dict[str, QComboBox] = {}
        self._gs1_contract_entries = tuple(gs1_contract_entries or ())
        self._gs1_contracts_csv_path = str(gs1_contracts_csv_path or "").strip()
        self.setProperty("role", "panel")
        self.setAttribute(Qt.WA_StyledBackground, True)

        self.setStyleSheet(
            _compose_widget_stylesheet(
                self,
                """
                QDialog#applicationSettingsDialog QLabel#settingsTitle {
                    font-size: 18px;
                    font-weight: 600;
                }
                QDialog#applicationSettingsDialog QLabel#settingsSubtitle {
                }
                QDialog#applicationSettingsDialog QLabel[role="hint"] {
                }
                QDialog#applicationSettingsDialog QLabel[role="sectionHelp"] {
                }
                QDialog#applicationSettingsDialog QLabel[role="themeNote"] {
                }
                QDialog#applicationSettingsDialog QGroupBox {
                    font-weight: 600;
                    margin-top: 10px;
                }
                QDialog#applicationSettingsDialog QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 4px;
                }
                QDialog#applicationSettingsDialog QLabel[role="colorSwatch"] {
                    border: 1px solid palette(mid);
                    border-radius: 5px;
                    min-width: 28px;
                    max-width: 28px;
                    min-height: 22px;
                    max-height: 22px;
                }
                """,
            )
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        help_row = QHBoxLayout()
        help_row.addStretch(1)
        help_row.addWidget(_create_round_help_button(self, "settings"))
        root.addLayout(help_row)

        title_lbl = QLabel("Application Settings")
        title_lbl.setObjectName("settingsTitle")
        title_lbl.setProperty("role", "dialogTitle")
        root.addWidget(title_lbl)

        subtitle_lbl = QLabel(
            "Edit application identity, theme styling, and profile-specific registration settings in one place."
        )
        subtitle_lbl.setObjectName("settingsSubtitle")
        subtitle_lbl.setProperty("role", "dialogSubtitle")
        subtitle_lbl.setWordWrap(True)
        root.addWidget(subtitle_lbl)

        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)

        general_page = QWidget(self)
        general_page.setProperty("role", "workspaceCanvas")
        general_layout = QVBoxLayout(general_page)
        general_layout.setContentsMargins(10, 10, 10, 10)
        general_layout.setSpacing(14)

        profile_box = QGroupBox("Current Profile")
        profile_grid = QGridLayout(profile_box)
        profile_grid.setColumnMinimumWidth(0, 0)
        profile_grid.setColumnStretch(1, 1)
        profile_grid.setHorizontalSpacing(10)
        profile_grid.setVerticalSpacing(8)

        profile_name = (
            Path(current_profile_path).name if current_profile_path else "(not connected)"
        )
        profile_name_lbl = QLabel(profile_name)
        profile_name_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        profile_path_lbl = QLabel(current_profile_path or "")
        profile_path_lbl.setWordWrap(True)
        profile_path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        profile_grid.addWidget(self._make_label("Profile"), 0, 0)
        profile_grid.addWidget(profile_name_lbl, 0, 1)
        profile_grid.addWidget(self._make_label("Path"), 1, 0)
        profile_grid.addWidget(profile_path_lbl, 1, 1)
        general_layout.addWidget(profile_box)

        app_box = QGroupBox("Application")
        app_grid = QGridLayout(app_box)
        self._configure_grid(app_grid)
        general_layout.addWidget(app_box)

        self.window_title_edit = QLineEdit(window_title or DEFAULT_WINDOW_TITLE)
        self.window_title_edit.setClearButtonEnabled(True)
        self.window_title_edit.setPlaceholderText(DEFAULT_WINDOW_TITLE)
        self.window_title_edit.setMinimumWidth(320)
        self.window_title_edit.setMaximumWidth(460)
        self._add_row(
            app_grid,
            0,
            "Window Title",
            self.window_title_edit,
            "Displayed in the main window title bar.",
        )

        self.icon_path_edit = QLineEdit(icon_path or "")
        self.icon_path_edit.setClearButtonEnabled(True)
        self.icon_path_edit.setPlaceholderText("Optional icon path")
        self.icon_path_edit.setMinimumWidth(360)
        browse_btn = QPushButton("Browse…")
        browse_btn.setAutoDefault(False)
        browse_btn.clicked.connect(self._browse_icon)
        clear_btn = QPushButton("Clear")
        clear_btn.setAutoDefault(False)
        clear_btn.clicked.connect(self.icon_path_edit.clear)

        icon_widget = QWidget(self)
        icon_row = QHBoxLayout(icon_widget)
        icon_row.setContentsMargins(0, 0, 0, 0)
        icon_row.setSpacing(8)
        icon_row.addWidget(self.icon_path_edit, 1)
        icon_row.addWidget(browse_btn)
        icon_row.addWidget(clear_btn)
        icon_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._add_row(
            app_grid,
            1,
            "Application Icon",
            icon_widget,
            "Optional image file used as the app icon.",
        )

        registration_box = QGroupBox("Registration & Codes")
        registration_grid = QGridLayout(registration_box)
        self._configure_grid(registration_grid)
        general_layout.addWidget(registration_box)

        self.isrc_prefix_edit = QLineEdit((isrc_prefix or "").upper().strip())
        self.isrc_prefix_edit.setClearButtonEnabled(True)
        self.isrc_prefix_edit.setMaxLength(5)
        self.isrc_prefix_edit.setPlaceholderText("Example: NLABC")
        self.isrc_prefix_edit.setMinimumWidth(180)
        self.isrc_prefix_edit.setMaximumWidth(260)
        self._add_row(
            registration_grid,
            0,
            "ISRC Prefix",
            self.isrc_prefix_edit,
            "Five characters: country code plus registrant code.",
        )

        self.artist_code_edit = QLineEdit((artist_code or "00").strip())
        self.artist_code_edit.setClearButtonEnabled(True)
        self.artist_code_edit.setMaxLength(2)
        self.artist_code_edit.setPlaceholderText("00")
        self.artist_code_edit.setMinimumWidth(180)
        self.artist_code_edit.setMaximumWidth(260)
        self._add_row(
            registration_grid,
            1,
            "ISRC Artist Code",
            self.artist_code_edit,
            "Two digits used in generated ISRC values.",
        )

        self.sena_number_edit = QLineEdit((sena_number or "").strip())
        self.sena_number_edit.setClearButtonEnabled(True)
        self.sena_number_edit.setMinimumWidth(180)
        self.sena_number_edit.setMaximumWidth(320)
        self._add_row(registration_grid, 2, "SENA Number", self.sena_number_edit)

        self.btw_number_edit = QLineEdit((btw_number or "").strip())
        self.btw_number_edit.setClearButtonEnabled(True)
        self.btw_number_edit.setMinimumWidth(180)
        self.btw_number_edit.setMaximumWidth(320)
        self._add_row(registration_grid, 3, "VAT / BTW Number", self.btw_number_edit)

        self.buma_relatie_edit = QLineEdit((buma_relatie_nummer or "").strip())
        self.buma_relatie_edit.setClearButtonEnabled(True)
        self.buma_relatie_edit.setMinimumWidth(180)
        self.buma_relatie_edit.setMaximumWidth(320)
        self._add_row(
            registration_grid,
            4,
            "BUMA/STEMRA Relation Number",
            self.buma_relatie_edit,
        )

        self.buma_ipi_edit = QLineEdit((buma_ipi or "").strip())
        self.buma_ipi_edit.setClearButtonEnabled(True)
        self.buma_ipi_edit.setMinimumWidth(180)
        self.buma_ipi_edit.setMaximumWidth(320)
        self._add_row(
            registration_grid,
            5,
            "BUMA/STEMRA IPI Number",
            self.buma_ipi_edit,
        )

        snapshots_box = QGroupBox("Snapshots")
        snapshots_grid = QGridLayout(snapshots_box)
        self._configure_grid(snapshots_grid)
        general_layout.addWidget(snapshots_box)

        self.auto_snapshot_enabled_check = QCheckBox("Create snapshots automatically")
        self.auto_snapshot_enabled_check.setChecked(bool(auto_snapshot_enabled))
        self.auto_snapshot_enabled_check.setMinimumWidth(320)
        self._add_row(
            snapshots_grid,
            0,
            "Automatic Snapshots",
            self.auto_snapshot_enabled_check,
            "Background restore points are created while this profile is open. Turn this off to keep manual snapshots only.",
        )

        self.auto_snapshot_interval_spin = FocusWheelSpinBox()
        self.auto_snapshot_interval_spin.setRange(
            MIN_AUTO_SNAPSHOT_INTERVAL_MINUTES,
            MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES,
        )
        self.auto_snapshot_interval_spin.setValue(
            max(
                MIN_AUTO_SNAPSHOT_INTERVAL_MINUTES,
                min(
                    MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES,
                    int(auto_snapshot_interval_minutes or DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES),
                ),
            )
        )
        self.auto_snapshot_interval_spin.setSuffix(" min")
        self.auto_snapshot_interval_spin.setMinimumWidth(180)
        self.auto_snapshot_interval_spin.setMaximumWidth(220)
        self._add_row(
            snapshots_grid,
            1,
            "Snapshot Interval",
            self.auto_snapshot_interval_spin,
            "Choose how often the app stores an automatic snapshot for this profile.",
        )
        self.auto_snapshot_enabled_check.toggled.connect(
            self.auto_snapshot_interval_spin.setEnabled
        )
        self.auto_snapshot_interval_spin.setEnabled(self.auto_snapshot_enabled_check.isChecked())

        self.history_retention_mode_combo = FocusWheelComboBox()
        for mode_key, label, _description in self.HISTORY_RETENTION_MODE_SPECS:
            self.history_retention_mode_combo.addItem(label, mode_key)
        self.history_retention_mode_combo.setMinimumWidth(220)
        self.history_retention_mode_combo.setMaximumWidth(320)
        self._add_row(
            snapshots_grid,
            2,
            "Retention & Safety Level",
            self.history_retention_mode_combo,
            "Choose a practical cleanup posture for automatic history artifacts. Manual snapshots and protected restore points stay protected by default.",
        )
        self.history_retention_mode_hint = self._make_hint("")
        snapshots_grid.addWidget(self.history_retention_mode_hint, 3, 1, 1, 2)

        self.history_auto_cleanup_enabled_check = QCheckBox(
            "Automatically clean safe history artifacts"
        )
        self.history_auto_cleanup_enabled_check.setChecked(bool(history_auto_cleanup_enabled))
        self.history_auto_cleanup_enabled_check.setMinimumWidth(320)
        self._add_row(
            snapshots_grid,
            4,
            "Automatic Cleanup",
            self.history_auto_cleanup_enabled_check,
            "Allow the app to remove older automatic snapshots, unreferenced bundles, and aged pre-restore safety copies when the retention policy allows it.",
        )

        self.history_storage_budget_spin = FocusWheelSpinBox()
        self.history_storage_budget_spin.setRange(
            MIN_HISTORY_STORAGE_BUDGET_MB,
            MAX_HISTORY_STORAGE_BUDGET_MB,
        )
        self.history_storage_budget_spin.setValue(
            max(
                MIN_HISTORY_STORAGE_BUDGET_MB,
                min(
                    MAX_HISTORY_STORAGE_BUDGET_MB,
                    int(history_storage_budget_mb or DEFAULT_HISTORY_STORAGE_BUDGET_MB),
                ),
            )
        )
        self.history_storage_budget_spin.setSuffix(" MB")
        self.history_storage_budget_spin.setMinimumWidth(180)
        self.history_storage_budget_spin.setMaximumWidth(220)
        self._add_row(
            snapshots_grid,
            5,
            "Storage Budget",
            self.history_storage_budget_spin,
            "Set a soft cap for history snapshots, backups, and artifact bundles stored for this profile.",
        )

        self.history_auto_snapshot_keep_latest_spin = FocusWheelSpinBox()
        self.history_auto_snapshot_keep_latest_spin.setRange(
            MIN_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
            MAX_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
        )
        self.history_auto_snapshot_keep_latest_spin.setValue(
            max(
                MIN_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
                min(
                    MAX_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
                    int(
                        history_auto_snapshot_keep_latest
                        or DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST
                    ),
                ),
            )
        )
        self.history_auto_snapshot_keep_latest_spin.setMinimumWidth(180)
        self.history_auto_snapshot_keep_latest_spin.setMaximumWidth(220)
        self._add_row(
            snapshots_grid,
            6,
            "Keep Latest Auto Snapshots",
            self.history_auto_snapshot_keep_latest_spin,
            "Older automatic snapshots beyond this count can be trimmed automatically when they are no longer referenced by retained history.",
        )

        self.history_prune_pre_restore_copies_after_days_spin = FocusWheelSpinBox()
        self.history_prune_pre_restore_copies_after_days_spin.setRange(
            MIN_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
            MAX_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
        )
        self.history_prune_pre_restore_copies_after_days_spin.setValue(
            max(
                MIN_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
                min(
                    MAX_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
                    int(
                        history_prune_pre_restore_copies_after_days
                        or DEFAULT_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS
                    ),
                ),
            )
        )
        self.history_prune_pre_restore_copies_after_days_spin.setSpecialValueText("Never")
        self.history_prune_pre_restore_copies_after_days_spin.setSuffix(" days")
        self.history_prune_pre_restore_copies_after_days_spin.setMinimumWidth(180)
        self.history_prune_pre_restore_copies_after_days_spin.setMaximumWidth(220)
        self._add_row(
            snapshots_grid,
            7,
            "Prune Restore Safety Copies",
            self.history_prune_pre_restore_copies_after_days_spin,
            "Optionally remove pre-restore safety backups after they age past this many days. Set to Never to keep them until you clean them manually.",
        )

        self.history_retention_mode_combo.currentIndexChanged.connect(
            self._apply_selected_history_retention_mode
        )
        self.history_auto_cleanup_enabled_check.toggled.connect(
            self.history_storage_budget_spin.setEnabled
        )
        self.history_auto_cleanup_enabled_check.toggled.connect(
            self.history_auto_snapshot_keep_latest_spin.setEnabled
        )
        self.history_auto_cleanup_enabled_check.toggled.connect(
            self.history_prune_pre_restore_copies_after_days_spin.setEnabled
        )
        self.history_storage_budget_spin.setEnabled(
            self.history_auto_cleanup_enabled_check.isChecked()
        )
        self.history_auto_snapshot_keep_latest_spin.setEnabled(
            self.history_auto_cleanup_enabled_check.isChecked()
        )
        self.history_prune_pre_restore_copies_after_days_spin.setEnabled(
            self.history_auto_cleanup_enabled_check.isChecked()
        )
        self.history_auto_cleanup_enabled_check.toggled.connect(
            self._sync_history_retention_mode_from_controls
        )
        self.history_auto_snapshot_keep_latest_spin.valueChanged.connect(
            self._sync_history_retention_mode_from_controls
        )
        self.history_prune_pre_restore_copies_after_days_spin.valueChanged.connect(
            self._sync_history_retention_mode_from_controls
        )
        self._set_history_retention_mode_state(
            self._detect_history_retention_mode(preferred_mode=history_retention_mode)
        )

        general_layout.addStretch(1)
        self.tabs.addTab(self._wrap_tab_page(general_page), "General")

        gs1_page = QWidget(self)
        gs1_page.setProperty("role", "workspaceCanvas")
        gs1_layout = QVBoxLayout(gs1_page)
        gs1_layout.setContentsMargins(10, 10, 10, 10)
        gs1_layout.setSpacing(14)

        gs1_template_box = QGroupBox("Official Workbook")
        gs1_template_grid = QGridLayout(gs1_template_box)
        self._configure_grid(gs1_template_grid)

        self.gs1_template_path_edit = QLineEdit("")
        self.gs1_template_path_edit.setReadOnly(True)
        self.gs1_template_path_edit.setPlaceholderText("No official GS1 workbook stored yet")
        self.gs1_template_path_edit.setMinimumWidth(420)
        self.gs1_template_store_btn = QPushButton("Upload…")
        self.gs1_template_store_btn.setAutoDefault(False)
        self.gs1_template_store_btn.clicked.connect(self._browse_gs1_template)
        self.gs1_template_export_btn = QPushButton("Export…")
        self.gs1_template_export_btn.setAutoDefault(False)
        self.gs1_template_export_btn.clicked.connect(self._export_gs1_template)
        self.gs1_template_storage_combo = FocusWheelComboBox()
        self.gs1_template_storage_combo.addItem("Store in Database", STORAGE_MODE_DATABASE)
        self.gs1_template_storage_combo.addItem("Store as Managed File", STORAGE_MODE_MANAGED_FILE)
        gs1_template_widget = QWidget(self)
        gs1_template_row = QHBoxLayout(gs1_template_widget)
        gs1_template_row.setContentsMargins(0, 0, 0, 0)
        gs1_template_row.setSpacing(8)
        gs1_template_row.addWidget(self.gs1_template_path_edit, 1)
        gs1_template_row.addWidget(self.gs1_template_storage_combo)
        gs1_template_row.addWidget(self.gs1_template_store_btn)
        gs1_template_row.addWidget(self.gs1_template_export_btn)
        self._add_row(
            gs1_template_grid,
            0,
            "Template Workbook",
            gs1_template_widget,
            "Upload the official Excel workbook once so it is stored inside the current profile database. "
            "Export saves a copy of the embedded workbook back to disk when you need it.",
        )
        self.gs1_template_status_label = QLabel("")
        self.gs1_template_status_label.setWordWrap(True)
        self.gs1_template_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._add_row(
            gs1_template_grid,
            1,
            "Workbook Status",
            self.gs1_template_status_label,
            "Replace lets you update the stored workbook later without keeping the original file path around.",
        )
        gs1_layout.addWidget(gs1_template_box)

        gs1_contracts_box = QGroupBox("GTIN Contracts")
        gs1_contracts_grid = QGridLayout(gs1_contracts_box)
        self._configure_grid(gs1_contracts_grid)

        self.gs1_contracts_csv_edit = QLineEdit(self._gs1_contracts_csv_path)
        self.gs1_contracts_csv_edit.setClearButtonEnabled(True)
        self.gs1_contracts_csv_edit.setPlaceholderText("GS1 contracts CSV export path")
        self.gs1_contracts_csv_edit.setMinimumWidth(420)
        gs1_contracts_browse_btn = QPushButton("Import CSV…")
        gs1_contracts_browse_btn.setAutoDefault(False)
        gs1_contracts_browse_btn.clicked.connect(self._browse_gs1_contracts_csv)
        gs1_contracts_reload_btn = QPushButton("Reload")
        gs1_contracts_reload_btn.setAutoDefault(False)
        gs1_contracts_reload_btn.clicked.connect(self._reload_gs1_contracts_csv)
        gs1_contracts_clear_btn = QPushButton("Clear")
        gs1_contracts_clear_btn.setAutoDefault(False)
        gs1_contracts_clear_btn.clicked.connect(self._clear_gs1_contracts)
        gs1_contracts_widget = QWidget(self)
        gs1_contracts_row = QHBoxLayout(gs1_contracts_widget)
        gs1_contracts_row.setContentsMargins(0, 0, 0, 0)
        gs1_contracts_row.setSpacing(8)
        gs1_contracts_row.addWidget(self.gs1_contracts_csv_edit, 1)
        gs1_contracts_row.addWidget(gs1_contracts_browse_btn)
        gs1_contracts_row.addWidget(gs1_contracts_reload_btn)
        gs1_contracts_row.addWidget(gs1_contracts_clear_btn)
        self._add_row(
            gs1_contracts_grid,
            0,
            "Contracts CSV",
            gs1_contracts_widget,
            "Import the contracts export from your GS1 portal. GTIN contract numbers from that file become available for defaults and export routing.",
        )

        self.gs1_active_contract_edit = self._create_gs1_contract_combo(
            initial_text=gs1_active_contract_number
        )
        self._add_row(
            gs1_contracts_grid,
            1,
            "Active Contract",
            self.gs1_active_contract_edit,
            "Default contract number used for new GS1 records. The export writes each row into the worksheet tab with this contract number.",
        )

        self.gs1_contracts_status_label = QLabel("")
        self.gs1_contracts_status_label.setWordWrap(True)
        self.gs1_contracts_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._add_row(
            gs1_contracts_grid,
            2,
            "Imported Contracts",
            self.gs1_contracts_status_label,
            "Only GTIN-capable contracts with numeric start and end ranges are imported from the CSV.",
        )

        gs1_layout.addWidget(gs1_contracts_box)

        gs1_defaults_box = QGroupBox("Profile Defaults")
        gs1_defaults_grid = QGridLayout(gs1_defaults_box)
        self._configure_grid(gs1_defaults_grid)

        self.gs1_target_market_edit = self._create_gs1_default_combo(
            initial_text=gs1_target_market,
            placeholder="Choose or type a target market",
        )
        self._add_row(
            gs1_defaults_grid,
            0,
            "Target Market",
            self.gs1_target_market_edit,
            "Default market or region used for new GS1 records.",
        )

        self.gs1_language_edit = self._create_gs1_default_combo(
            initial_text=gs1_language,
            placeholder="Choose or type a language",
        )
        self._add_row(
            gs1_defaults_grid,
            1,
            "Language",
            self.gs1_language_edit,
            "Default language used for new GS1 records.",
        )

        self.gs1_brand_edit = self._create_gs1_default_combo(
            initial_text=gs1_brand,
            placeholder="Choose or type a brand",
        )
        self._add_row(
            gs1_defaults_grid,
            2,
            "Brand",
            self.gs1_brand_edit,
            "Default brand for new GS1 records.",
        )

        self.gs1_subbrand_edit = self._create_gs1_default_combo(
            initial_text=gs1_subbrand,
            placeholder="Choose or type a subbrand",
        )
        self._add_row(
            gs1_defaults_grid,
            3,
            "Subbrand",
            self.gs1_subbrand_edit,
            "Optional default subbrand for new GS1 records.",
        )

        self.gs1_packaging_type_edit = self._create_gs1_default_combo(
            initial_text=gs1_packaging_type,
            placeholder="Choose or type a packaging type",
        )
        self._add_row(
            gs1_defaults_grid,
            4,
            "Packaging Type",
            self.gs1_packaging_type_edit,
            "Default packaging type used when a new GS1 record is created.",
        )

        self.gs1_product_classification_edit = self._create_gs1_default_combo(
            initial_text=gs1_product_classification,
            placeholder="Choose or type a product classification",
        )
        self._add_row(
            gs1_defaults_grid,
            5,
            "Product Classification",
            self.gs1_product_classification_edit,
            "Default product classification used when a new GS1 record is created.",
        )

        gs1_layout.addWidget(gs1_defaults_box)
        gs1_layout.addStretch(1)
        self.tabs.addTab(self._wrap_tab_page(gs1_page), "GS1")

        theme_page = QWidget(self)
        theme_page.setProperty("role", "workspaceCanvas")
        theme_layout = QVBoxLayout(theme_page)
        theme_layout.setContentsMargins(10, 10, 10, 10)
        theme_layout.setSpacing(14)

        theme_library_box = QGroupBox("Theme Library")
        theme_library_grid = QGridLayout(theme_library_box)
        self._configure_grid(theme_library_grid)

        self.theme_preset_combo = FocusWheelComboBox(self)
        self.theme_preset_combo.setMinimumWidth(240)
        self.theme_preset_combo.setMaximumWidth(340)
        self.theme_load_button = QPushButton("Load Selected")
        self.theme_load_button.setAutoDefault(False)
        self.theme_save_button = QPushButton("Save Theme…")
        self.theme_save_button.setAutoDefault(False)
        self.theme_delete_button = QPushButton("Delete Theme")
        self.theme_delete_button.setAutoDefault(False)
        self.theme_import_button = QPushButton("Import Theme…")
        self.theme_import_button.setAutoDefault(False)
        self.theme_export_button = QPushButton("Export Theme…")
        self.theme_export_button.setAutoDefault(False)
        self.theme_reset_button = QPushButton("Reset to Defaults")
        self.theme_reset_button.setAutoDefault(False)

        theme_preset_widget = QWidget(self)
        theme_preset_row = QHBoxLayout(theme_preset_widget)
        theme_preset_row.setContentsMargins(0, 0, 0, 0)
        theme_preset_row.setSpacing(8)
        theme_preset_row.addWidget(self.theme_preset_combo)
        theme_preset_row.addWidget(self.theme_load_button)
        theme_preset_row.addWidget(self.theme_save_button)
        theme_preset_row.addWidget(self.theme_delete_button)
        theme_preset_row.addWidget(self.theme_import_button)
        theme_preset_row.addWidget(self.theme_export_button)
        theme_preset_row.addWidget(self.theme_reset_button)
        theme_preset_row.addStretch(1)
        self._add_row(
            theme_library_grid,
            0,
            "Theme Library",
            theme_preset_widget,
            "Bundled starter themes ship with the app. Load one, save a copy of it as a reusable preset, import/export shared themes, or remove custom themes you no longer need.",
        )

        self.theme_font_family_combo = FocusWheelFontComboBox(self)
        self.theme_font_family_combo.setMinimumWidth(260)
        self.theme_font_family_combo.setMaximumWidth(360)
        font_family = str(self._theme_settings.get("font_family") or "").strip()
        if font_family:
            self.theme_font_family_combo.setCurrentFont(QFont(font_family))

        self.theme_auto_contrast_check = QCheckBox("Auto-fix unreadable text colors")
        self.theme_auto_contrast_check.setChecked(
            bool(self._theme_settings.get("auto_contrast_enabled", True))
        )
        self.theme_live_preview_check = QCheckBox("Preview changes across the app while editing")
        self.theme_live_preview_check.setChecked(False)
        self._add_row(
            theme_library_grid,
            1,
            "Live Preview",
            self.theme_live_preview_check,
            "When enabled, the current theme draft is applied to the running app in real time. Canceling the dialog restores the original theme.",
        )

        theme_layout.addWidget(theme_library_box)

        theme_intro = QLabel(
            "The visual theme builder now covers the full application surface: typography, workspace canvases, panels, group titles, compact frames, buttons, inputs, data views, tab panes, toolbar and status chrome, the action ribbon surface, help buttons, and state styling. "
            "A dedicated Blob Icons tab keeps media badges separate from visual theme presets, and the Action Ribbon tab isolates ribbon chrome without introducing a separate ribbon-button token set in this pass."
        )
        theme_intro.setWordWrap(True)
        theme_intro.setProperty("role", "secondary")
        theme_layout.addWidget(theme_intro)

        theme_splitter = QSplitter(Qt.Horizontal, theme_page)

        theme_editor_host = QWidget(theme_splitter)
        theme_editor_layout = QVBoxLayout(theme_editor_host)
        theme_editor_layout.setContentsMargins(0, 0, 0, 0)
        theme_editor_layout.setSpacing(10)
        self.theme_builder_tabs = QTabWidget(theme_editor_host)
        self.theme_builder_tabs.setDocumentMode(True)
        theme_editor_layout.addWidget(self.theme_builder_tabs, 1)
        self._build_theme_builder_tabs()

        theme_preview_host = QWidget(theme_splitter)
        theme_preview_layout = QVBoxLayout(theme_preview_host)
        theme_preview_layout.setContentsMargins(0, 0, 0, 0)
        theme_preview_layout.setSpacing(10)
        preview_title = QLabel("Live Preview", theme_preview_host)
        preview_title.setProperty("role", "sectionTitle")
        theme_preview_layout.addWidget(preview_title)
        preview_subtitle = QLabel(
            "Hover, click, switch tabs, focus fields, and inspect disabled states here before you save the theme.",
            theme_preview_host,
        )
        preview_subtitle.setProperty("role", "secondary")
        preview_subtitle.setWordWrap(True)
        theme_preview_layout.addWidget(preview_subtitle)
        self.theme_preview_status_label = QLabel("", theme_preview_host)
        self.theme_preview_status_label.setWordWrap(True)
        self.theme_preview_status_label.setProperty("role", "secondary")
        theme_preview_layout.addWidget(self.theme_preview_status_label)
        self.theme_preview_tabs = QTabWidget(theme_preview_host)
        self.theme_preview_tabs.setDocumentMode(True)
        self.theme_preview_tabs.tabBar().hide()
        theme_preview_layout.addWidget(self.theme_preview_tabs, 1)
        self._build_theme_preview_tabs()

        theme_splitter.addWidget(theme_editor_host)
        theme_splitter.addWidget(theme_preview_host)
        theme_splitter.setStretchFactor(0, 3)
        theme_splitter.setStretchFactor(1, 2)
        theme_layout.addWidget(theme_splitter, 1)

        self.tabs.addTab(self._wrap_tab_page(theme_page), "Theme")

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            Qt.Horizontal,
            self,
        )
        self.button_box.accepted.connect(self._accept_if_valid)
        self.button_box.rejected.connect(self.reject)
        root.addWidget(self.button_box)
        self.finished.connect(self._handle_theme_dialog_finished)

        self._focus_map = {
            "window_title": (0, self.window_title_edit),
            "icon_path": (0, self.icon_path_edit),
            "isrc_prefix": (0, self.isrc_prefix_edit),
            "artist_code": (0, self.artist_code_edit),
            "auto_snapshot_enabled": (0, self.auto_snapshot_enabled_check),
            "auto_snapshot_interval_minutes": (0, self.auto_snapshot_interval_spin),
            "history_retention_mode": (0, self.history_retention_mode_combo),
            "history_auto_cleanup_enabled": (0, self.history_auto_cleanup_enabled_check),
            "history_storage_budget_mb": (0, self.history_storage_budget_spin),
            "history_auto_snapshot_keep_latest": (0, self.history_auto_snapshot_keep_latest_spin),
            "history_prune_pre_restore_copies_after_days": (
                0,
                self.history_prune_pre_restore_copies_after_days_spin,
            ),
            "sena_number": (0, self.sena_number_edit),
            "btw_number": (0, self.btw_number_edit),
            "buma_relatie_nummer": (0, self.buma_relatie_edit),
            "buma_ipi": (0, self.buma_ipi_edit),
            "gs1_template_path": (1, self.gs1_template_path_edit),
            "gs1_contracts_csv_path": (1, self.gs1_contracts_csv_edit),
            "gs1_active_contract_number": (1, self.gs1_active_contract_edit),
            "gs1_target_market": (1, self.gs1_target_market_edit),
            "gs1_language": (1, self.gs1_language_edit),
            "gs1_brand": (1, self.gs1_brand_edit),
            "gs1_subbrand": (1, self.gs1_subbrand_edit),
            "gs1_packaging_type": (1, self.gs1_packaging_type_edit),
            "gs1_product_classification": (1, self.gs1_product_classification_edit),
            "theme_font_family": (2, self.theme_font_family_combo),
            "theme_font_size": (2, self.theme_font_size_spin),
            "theme_custom_qss": (2, self.theme_custom_qss_edit),
            "theme_preset": (2, self.theme_preset_combo),
        }

        self._bind_theme_field_change_tracking()
        self._refresh_theme_preset_combo()
        initial_selected_theme = str(self._theme_settings.get("selected_name") or "").strip()
        self._set_theme_preset_selection(initial_selected_theme)
        self._update_theme_preset_actions()
        self._configure_gs1_contract_combo()
        self._configure_gs1_default_option_combos()
        self._refresh_gs1_template_options(show_errors=False)
        self._refresh_qss_selector_reference()

    @staticmethod
    def _configure_grid(grid: QGridLayout):
        grid.setColumnMinimumWidth(0, 0)
        grid.setColumnMinimumWidth(1, 300)
        grid.setColumnStretch(1, 2)
        grid.setColumnMinimumWidth(2, 240)
        grid.setColumnStretch(2, 1)
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
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return label

    @staticmethod
    def _make_hint(text: str) -> QLabel:
        hint = QLabel(text)
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        return hint

    @classmethod
    def _history_retention_preset(cls, mode: str) -> dict[str, object]:
        return dict(HISTORY_RETENTION_MODE_PRESETS.get(str(mode or "").strip().lower(), {}))

    @classmethod
    def _history_retention_mode_description(cls, mode: str) -> str:
        normalized = str(mode or "").strip().lower()
        for mode_key, _label, description in cls.HISTORY_RETENTION_MODE_SPECS:
            if mode_key == normalized:
                return description
        return ""

    def _history_retention_control_payload(self) -> dict[str, object]:
        return {
            "auto_cleanup_enabled": self.history_auto_cleanup_enabled_check.isChecked(),
            "auto_snapshot_keep_latest": int(self.history_auto_snapshot_keep_latest_spin.value()),
            "prune_pre_restore_copies_after_days": int(
                self.history_prune_pre_restore_copies_after_days_spin.value()
            ),
        }

    def _set_history_retention_control_payload(self, payload: dict[str, object]) -> None:
        previous_state = self._history_retention_sync_enabled
        self._history_retention_sync_enabled = False
        try:
            self.history_auto_cleanup_enabled_check.setChecked(
                bool(payload.get("auto_cleanup_enabled", True))
            )
            self.history_auto_snapshot_keep_latest_spin.setValue(
                int(
                    payload.get(
                        "auto_snapshot_keep_latest", DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST
                    )
                )
            )
            self.history_prune_pre_restore_copies_after_days_spin.setValue(
                int(
                    payload.get(
                        "prune_pre_restore_copies_after_days",
                        DEFAULT_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
                    )
                )
            )
        finally:
            self._history_retention_sync_enabled = previous_state

    def _set_history_retention_mode_state(self, mode: str) -> None:
        normalized = str(mode or "").strip().lower()
        if normalized not in HISTORY_RETENTION_MODE_CHOICES:
            normalized = DEFAULT_HISTORY_RETENTION_MODE
        previous_state = self._history_retention_sync_enabled
        self._history_retention_sync_enabled = False
        try:
            for index in range(self.history_retention_mode_combo.count()):
                if str(self.history_retention_mode_combo.itemData(index) or "") == normalized:
                    self.history_retention_mode_combo.setCurrentIndex(index)
                    break
        finally:
            self._history_retention_sync_enabled = previous_state
        self.history_retention_mode_hint.setText(
            self._history_retention_mode_description(normalized)
        )

    def _detect_history_retention_mode(self, *, preferred_mode: str = "") -> str:
        payload = self._history_retention_control_payload()
        preferred = str(preferred_mode or "").strip().lower()
        if (
            preferred in HISTORY_RETENTION_MODE_PRESETS
            and payload == self._history_retention_preset(preferred)
        ):
            return preferred
        for mode_key in HISTORY_RETENTION_MODE_PRESETS:
            if payload == self._history_retention_preset(mode_key):
                return mode_key
        return HISTORY_RETENTION_MODE_CUSTOM

    def _apply_selected_history_retention_mode(self, *_args) -> None:
        if not self._history_retention_sync_enabled:
            return
        mode = str(self.history_retention_mode_combo.currentData() or "").strip().lower()
        if mode in HISTORY_RETENTION_MODE_PRESETS:
            self._set_history_retention_control_payload(self._history_retention_preset(mode))
        self._set_history_retention_mode_state(
            self._detect_history_retention_mode(preferred_mode=mode)
        )

    def _sync_history_retention_mode_from_controls(self, *_args) -> None:
        if not self._history_retention_sync_enabled:
            return
        self._set_history_retention_mode_state(
            self._detect_history_retention_mode(
                preferred_mode=str(self.history_retention_mode_combo.currentData() or "")
            )
        )

    @staticmethod
    def _wrap_tab_page(content: QWidget) -> QScrollArea:
        if content.property("role") is None:
            content.setProperty("role", "workspaceCanvas")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setProperty("role", "workspaceCanvas")
        viewport = scroll.viewport()
        if viewport is not None:
            viewport.setProperty("role", "workspaceCanvas")
        scroll.setWidget(content)
        return scroll

    def _add_row(
        self, grid: QGridLayout, row: int, label: str, editor: QWidget, hint: str | None = None
    ):
        grid.addWidget(self._make_label(label), row, 0)
        grid.addWidget(editor, row, 1)
        if hint:
            grid.addWidget(self._make_hint(hint), row, 2)

    def _create_color_editor(self, key: str, value: str, *, placeholder: str = "Auto") -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        swatch = QLabel(row)
        swatch.setProperty("role", "colorSwatch")
        swatch.setObjectName(f"{key}Swatch")
        swatch.setFixedSize(30, 24)
        swatch.setAlignment(Qt.AlignCenter)

        edit = QLineEdit(value.strip())
        edit.setClearButtonEnabled(True)
        edit.setPlaceholderText(placeholder)
        edit.setMinimumWidth(170)
        edit.setMaximumWidth(230)

        pick_btn = QPushButton("Pick…", row)
        pick_btn.setAutoDefault(False)
        clear_btn = QPushButton("Default", row)
        clear_btn.setAutoDefault(False)

        layout.addWidget(swatch)
        layout.addWidget(edit)
        layout.addWidget(pick_btn)
        layout.addWidget(clear_btn)
        layout.addStretch(1)

        self._theme_color_edits[key] = edit
        self._theme_color_swatches[key] = swatch
        edit.textChanged.connect(lambda _text, name=key: self._sync_color_swatch(name))
        pick_btn.clicked.connect(lambda *_args, name=key: self._pick_theme_color(name))
        clear_btn.clicked.connect(edit.clear)
        self._sync_color_swatch(key)
        return row

    def _create_metric_editor(self, spec) -> FocusWheelSpinBox:
        spin = FocusWheelSpinBox(self)
        spin.setRange(spec.minimum, spec.maximum)
        spin.setValue(
            max(
                spec.minimum,
                min(spec.maximum, int(self._theme_settings.get(spec.key) or spec.default)),
            )
        )
        if spec.suffix:
            spin.setSuffix(spec.suffix)
        spin.setMinimumWidth(160)
        spin.setMaximumWidth(220)
        self._theme_metric_spins[spec.key] = spin
        if spec.key == "font_size":
            self.theme_font_size_spin = spin
        return spin

    @staticmethod
    def _group_theme_specs_by_section(specs):
        grouped: dict[str, list[object]] = {}
        for spec in specs:
            grouped.setdefault(spec.section, []).append(spec)
        return grouped

    def _build_theme_builder_tabs(self) -> None:
        self._theme_builder_page_keys = []
        for page_key, page_title, page_description in self._settings_builder_specs:
            if page_key == "advanced":
                page = self._build_theme_advanced_page()
            elif page_key == "blob_icons":
                page = self._build_blob_icon_builder_page(page_description)
            else:
                page = self._build_theme_builder_page(page_key, page_description)
            self.theme_builder_tabs.addTab(page, page_title)
            self._theme_builder_page_keys.append(page_key)

    def _build_theme_builder_page(self, page_key: str, description: str) -> QWidget:
        page = QWidget(self)
        page.setProperty("role", "workspaceCanvas")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(12)

        intro = QLabel(description, page)
        intro.setWordWrap(True)
        intro.setProperty("role", "secondary")
        page_layout.addWidget(intro)

        color_specs = [spec for spec in self.COLOR_FIELD_SPECS if spec.page == page_key]
        metric_specs = [spec for spec in self.METRIC_FIELD_SPECS if spec.page == page_key]

        if page_key == "typography":
            typography_box = QGroupBox("Fonts & Readability", page)
            typography_grid = QGridLayout(typography_box)
            self._configure_grid(typography_grid)
            self._add_row(
                typography_grid,
                0,
                "Application Font",
                self.theme_font_family_combo,
                "Used across menus, dialogs, inputs, tables, and labels unless overridden by advanced QSS.",
            )
            self._add_row(
                typography_grid,
                1,
                "Text Contrast Guard",
                self.theme_auto_contrast_check,
                "Keeps foreground colors readable against their backgrounds. Turn this off to fully override colors yourself.",
            )
            page_layout.addWidget(typography_box)

        for section_title, section_specs in self._group_theme_specs_by_section(color_specs).items():
            group = QGroupBox(section_title, page)
            grid = QGridLayout(group)
            self._configure_grid(grid)
            for row, spec in enumerate(section_specs):
                editor = self._create_color_editor(
                    spec.key,
                    str(self._theme_settings.get(spec.key) or ""),
                    placeholder=spec.placeholder,
                )
                self._add_row(grid, row, spec.label, editor, spec.hint)
            page_layout.addWidget(group)

        for section_title, section_specs in self._group_theme_specs_by_section(
            metric_specs
        ).items():
            group = QGroupBox(section_title, page)
            grid = QGridLayout(group)
            self._configure_grid(grid)
            for row, spec in enumerate(section_specs):
                editor = self._create_metric_editor(spec)
                self._add_row(grid, row, spec.label, editor, spec.hint)
            page_layout.addWidget(group)

        page_layout.addStretch(1)
        return self._wrap_tab_page(page)

    def _build_blob_icon_builder_page(self, description: str) -> QWidget:
        page = QWidget(self)
        page.setProperty("role", "workspaceCanvas")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(12)

        intro = QLabel(description, page)
        intro.setWordWrap(True)
        intro.setProperty("role", "secondary")
        page_layout.addWidget(intro)

        builder_box = QGroupBox("Blob Media Icons", page)
        builder_grid = QGridLayout(builder_box)
        self._configure_grid(builder_grid)

        audio_editor = BlobIconEditorWidget(kind="audio", allow_inherit=False, parent=builder_box)
        audio_editor.set_spec(self._blob_icon_settings.get("audio"))
        self._blob_icon_editors["audio"] = audio_editor
        self._add_row(
            builder_grid,
            0,
            "Audio Blob Icon",
            audio_editor,
            "Shown when the Audio File column or an audio BLOB field contains stored media.",
        )

        audio_lossy_editor = BlobIconEditorWidget(
            kind="audio_lossy",
            allow_inherit=False,
            parent=builder_box,
        )
        audio_lossy_editor.set_spec(self._blob_icon_settings.get("audio_lossy"))
        self._blob_icon_editors["audio_lossy"] = audio_lossy_editor
        self._add_row(
            builder_grid,
            1,
            "Lossy Primary Audio Icon",
            audio_lossy_editor,
            "Shown when the Audio File column contains a lossy primary source such as MP3, AAC, or OGG.",
        )

        image_editor = BlobIconEditorWidget(kind="image", allow_inherit=False, parent=builder_box)
        image_editor.set_spec(self._blob_icon_settings.get("image"))
        self._blob_icon_editors["image"] = image_editor
        self._add_row(
            builder_grid,
            2,
            "Image Blob Icon",
            image_editor,
            "Shown when Album Art or an image BLOB field contains stored media.",
        )
        page_layout.addWidget(builder_box)

        note_box = QGroupBox("How It Works", page)
        note_layout = QVBoxLayout(note_box)
        note_layout.setContentsMargins(14, 18, 14, 14)
        note_layout.setSpacing(8)
        for text in (
            "Blob icons are profile-specific and stay separate from visual theme presets.",
            "Primary audio can use a dedicated lossy badge so MP3/AAC/OGG sources stand apart from WAV, FLAC, and AIFF masters.",
            "Platform icons use the current operating system's built-in icon set through Qt.",
            "Custom images are scaled down and compressed before they are written into the database, so large source files only occupy a small amount of storage.",
            "Custom BLOB columns can either inherit these global defaults or define their own icon override.",
        ):
            label = QLabel(text, note_box)
            label.setWordWrap(True)
            label.setProperty("role", "secondary")
            note_layout.addWidget(label)
        page_layout.addWidget(note_box)
        page_layout.addStretch(1)
        return self._wrap_tab_page(page)

    def _build_theme_advanced_page(self) -> QWidget:
        advanced_page = QWidget(self)
        advanced_page.setProperty("role", "workspaceCanvas")
        advanced_layout = QVBoxLayout(advanced_page)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(10)

        advanced_note = QLabel(
            "All visible controls receive object names automatically, so you can target specific widgets here. "
            "Attribute-backed widgets use their attribute name when available; other widgets receive generated names."
        )
        advanced_note.setProperty("role", "themeNote")
        advanced_note.setWordWrap(True)
        advanced_layout.addWidget(advanced_note)

        qss_help = QLabel(
            "Example selectors: `QPushButton`, `QLineEdit`, `QDockWidget::title`, `#profilesToolbar QPushButton`, or `QToolBar#actionRibbonToolbar`. "
            "Press Ctrl+Space in the editor for context-aware autocomplete with selectors, pseudo-states, subcontrols, "
            "property lines, value suggestions, and full rule templates."
        )
        qss_help.setProperty("role", "hint")
        qss_help.setWordWrap(True)
        advanced_layout.addWidget(qss_help)

        self.theme_qss_tabs = QTabWidget(self)
        self.theme_qss_tabs.setDocumentMode(True)
        advanced_layout.addWidget(self.theme_qss_tabs, 1)

        qss_editor_page = QWidget(self)
        qss_editor_page.setProperty("role", "workspaceCanvas")
        qss_editor_layout = QVBoxLayout(qss_editor_page)
        qss_editor_layout.setContentsMargins(0, 0, 0, 0)
        qss_editor_layout.setSpacing(10)
        self.theme_custom_qss_edit = QssCodeEditor(self)
        self.theme_custom_qss_edit.setPlaceholderText(
            "/* Advanced QSS */\nQPushButton#saveButton {\n    font-weight: 600;\n}\n"
        )
        self.theme_custom_qss_edit.setMinimumHeight(220)
        self.theme_custom_qss_edit.setPlainText(str(self._theme_settings.get("custom_qss") or ""))
        qss_editor_layout.addWidget(self.theme_custom_qss_edit, 1)
        self.theme_qss_tabs.addTab(qss_editor_page, "Editor")

        qss_reference_page = QWidget(self)
        qss_reference_page.setProperty("role", "workspaceCanvas")
        qss_reference_layout = QVBoxLayout(qss_reference_page)
        qss_reference_layout.setContentsMargins(0, 0, 0, 0)
        qss_reference_layout.setSpacing(10)

        qss_reference_note = QLabel(
            "The reference catalog is built from the currently open app windows and dialogs. "
            "Open the screen you want to style, then refresh the catalog to harvest its generated object names. "
            "Object-name entries are inserted as references, so they append safely to an existing widget selector "
            "instead of rewriting it."
        )
        qss_reference_note.setWordWrap(True)
        qss_reference_note.setProperty("role", "hint")
        qss_reference_layout.addWidget(qss_reference_note)

        qss_reference_controls = QWidget(self)
        qss_reference_controls_layout = QHBoxLayout(qss_reference_controls)
        qss_reference_controls_layout.setContentsMargins(0, 0, 0, 0)
        qss_reference_controls_layout.setSpacing(8)
        self.qss_reference_filter_edit = QLineEdit(self)
        self.qss_reference_filter_edit.setPlaceholderText(
            "Filter selectors by widget type, object name, role, or note..."
        )
        self.qss_reference_filter_edit.setClearButtonEnabled(True)
        self.qss_reference_filter_edit.textChanged.connect(self._apply_qss_reference_filter)
        self.qss_reference_refresh_button = QPushButton("Refresh Catalog", self)
        self.qss_reference_refresh_button.setAutoDefault(False)
        self.qss_reference_refresh_button.clicked.connect(self._refresh_qss_selector_reference)
        self.qss_reference_status_label = QLabel("", self)
        self.qss_reference_status_label.setProperty("role", "secondary")
        self.qss_reference_status_label.setWordWrap(True)
        qss_reference_controls_layout.addWidget(self.qss_reference_filter_edit, 1)
        qss_reference_controls_layout.addWidget(self.qss_reference_refresh_button)
        qss_reference_layout.addWidget(qss_reference_controls)
        qss_reference_layout.addWidget(self.qss_reference_status_label)

        self.qss_reference_table = QTableWidget(0, 3, self)
        self.qss_reference_table.setHorizontalHeaderLabels(["Category", "Selector", "Details"])
        self.qss_reference_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.qss_reference_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.qss_reference_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.qss_reference_table.verticalHeader().setVisible(False)
        self.qss_reference_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.qss_reference_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.qss_reference_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.qss_reference_table.itemSelectionChanged.connect(self._update_qss_reference_actions)
        self.qss_reference_table.doubleClicked.connect(
            lambda _index: self._insert_selected_qss_selector()
        )
        qss_reference_layout.addWidget(self.qss_reference_table, 1)

        qss_reference_button_row = QHBoxLayout()
        qss_reference_button_row.setContentsMargins(0, 0, 0, 0)
        qss_reference_button_row.setSpacing(8)
        qss_reference_button_row.addStretch(1)
        self.qss_reference_copy_button = QPushButton("Copy Selector", self)
        self.qss_reference_copy_button.setAutoDefault(False)
        self.qss_reference_copy_button.clicked.connect(self._copy_selected_qss_selector)
        self.qss_reference_insert_button = QPushButton("Insert Into Editor", self)
        self.qss_reference_insert_button.setAutoDefault(False)
        self.qss_reference_insert_button.clicked.connect(self._insert_selected_qss_selector)
        qss_reference_button_row.addWidget(self.qss_reference_copy_button)
        qss_reference_button_row.addWidget(self.qss_reference_insert_button)
        qss_reference_layout.addLayout(qss_reference_button_row)
        self.theme_qss_tabs.addTab(qss_reference_page, "Selector Reference")

        return advanced_page

    def _build_theme_preview_tabs(self) -> None:
        self._theme_preview_roots = []
        self._theme_preview_tab_indices = {}
        self._theme_preview_labels = {
            "typography": "Typography",
            "surfaces": "Surfaces",
            "buttons": "Buttons",
            "inputs": "Inputs",
            "data_views": "Data Views",
            "navigation": "Navigation",
            "action_ribbon": "Action Ribbon",
            "blob_icons": "Blob Icons",
            "advanced": "Advanced QSS",
        }
        preview_factories = {
            "typography": self._build_theme_preview_typography_page,
            "surfaces": self._build_theme_preview_surfaces_page,
            "buttons": self._build_theme_preview_buttons_page,
            "inputs": self._build_theme_preview_inputs_page,
            "data_views": self._build_theme_preview_data_views_page,
            "navigation": self._build_theme_preview_navigation_page,
            "action_ribbon": self._build_theme_preview_action_ribbon_page,
            "blob_icons": self._build_theme_preview_blob_icons_page,
            "advanced": self._build_theme_preview_advanced_page,
        }
        for page_key, _page_title, _page_description in self._settings_builder_specs:
            preview_page = preview_factories[page_key]()
            preview_index = self.theme_preview_tabs.addTab(
                preview_page, self._theme_preview_labels[page_key]
            )
            self._theme_preview_tab_indices[page_key] = preview_index
        self.theme_builder_tabs.currentChanged.connect(self._sync_theme_preview_to_builder_tab)
        self._sync_theme_preview_to_builder_tab(self.theme_builder_tabs.currentIndex())
        self._refresh_theme_previews()

    def _create_theme_preview_page(self, object_name: str) -> tuple[QWidget, QWidget, QVBoxLayout]:
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        preview_root = QWidget(page)
        preview_root.setObjectName(object_name)
        preview_root.setProperty("role", "panel")
        layout = QVBoxLayout(preview_root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        page_layout.addWidget(self._wrap_tab_page(preview_root), 1)
        self._theme_preview_roots.append(preview_root)
        return page, preview_root, layout

    def _build_theme_preview_typography_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewTypographyRoot")

        hero_box = QGroupBox("Text Hierarchy", preview_root)
        hero_layout = QVBoxLayout(hero_box)
        hero_layout.setContentsMargins(14, 18, 14, 14)
        hero_layout.setSpacing(8)
        title = QLabel("Theme Builder Preview", hero_box)
        title.setProperty("role", "dialogTitle")
        subtitle = QLabel(
            "Review how the selected font and size scale across titles, subtitles, body text, and support text.",
            hero_box,
        )
        subtitle.setProperty("role", "dialogSubtitle")
        subtitle.setWordWrap(True)
        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)
        section_title = QLabel("Section Title Example", hero_box)
        section_title.setProperty("role", "sectionTitle")
        hero_layout.addWidget(section_title)
        body = QLabel(
            "Body text stays readable across the application and should remain comfortable for long metadata sessions.",
            hero_box,
        )
        body.setWordWrap(True)
        hero_layout.addWidget(body)
        secondary = QLabel(
            "Secondary text, metadata captions, and helper text use a softer hierarchy without feeling disconnected.",
            hero_box,
        )
        secondary.setProperty("role", "secondary")
        secondary.setWordWrap(True)
        hero_layout.addWidget(secondary)
        hint = QLabel("Hint text sample used under forms and grouped settings.", hero_box)
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        hero_layout.addWidget(hint)
        layout.addWidget(hero_box)

        controls_box = QGroupBox("Text In Controls", preview_root)
        controls_layout = QVBoxLayout(controls_box)
        controls_layout.setContentsMargins(14, 18, 14, 14)
        controls_layout.setSpacing(10)
        control_row = QWidget(controls_box)
        control_row_layout = QHBoxLayout(control_row)
        control_row_layout.setContentsMargins(0, 0, 0, 0)
        control_row_layout.setSpacing(10)
        line_edit = QLineEdit("Line edit text preview", control_row)
        combo = FocusWheelComboBox(control_row)
        combo.addItems(["Font sample", "Secondary sample", "Compact sample"])
        combo.setCurrentIndex(0)
        button = QPushButton("Button Label", control_row)
        control_row_layout.addWidget(line_edit, 2)
        control_row_layout.addWidget(combo, 1)
        control_row_layout.addWidget(button)
        controls_layout.addWidget(control_row)
        layout.addWidget(controls_box)
        layout.addStretch(1)
        return page

    def _build_theme_preview_surfaces_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewSurfacesRoot")

        primary_panel = QGroupBox("Primary Surface", preview_root)
        primary_layout = QVBoxLayout(primary_panel)
        primary_layout.setContentsMargins(14, 18, 14, 14)
        primary_layout.setSpacing(8)
        primary_layout.addWidget(
            QLabel("Panels, borders, and helper text are previewed here.", primary_panel)
        )
        secondary = QLabel(
            "Adjust surface colors, panel backgrounds, borders, overlays, tooltips, and supporting text without unrelated controls crowding the preview.",
            primary_panel,
        )
        secondary.setProperty("role", "secondary")
        secondary.setWordWrap(True)
        primary_layout.addWidget(secondary)
        layout.addWidget(primary_panel)

        secondary_panel = QGroupBox("Secondary Surface", preview_root)
        secondary_layout = QVBoxLayout(secondary_panel)
        secondary_layout.setContentsMargins(14, 18, 14, 14)
        secondary_layout.setSpacing(8)
        workspace_canvas = QFrame(secondary_panel)
        workspace_canvas.setProperty("role", "workspaceCanvas")
        workspace_canvas_layout = QVBoxLayout(workspace_canvas)
        workspace_canvas_layout.setContentsMargins(10, 10, 10, 10)
        workspace_canvas_layout.setSpacing(6)
        workspace_canvas_layout.addWidget(QLabel("Workspace canvas preview", workspace_canvas))
        workspace_note = QLabel(
            "Use this color for large page backgrounds, dock canvases, and the empty workspace area.",
            workspace_canvas,
        )
        workspace_note.setWordWrap(True)
        workspace_note.setProperty("role", "secondary")
        workspace_canvas_layout.addWidget(workspace_note)
        secondary_layout.addWidget(workspace_canvas)
        hint = QLabel("Hint text example", secondary_panel)
        hint.setProperty("role", "hint")
        secondary_layout.addWidget(hint)
        overlay = QLabel("Overlay hint example", secondary_panel)
        overlay.setProperty("role", "overlayHint")
        overlay.setAlignment(Qt.AlignCenter)
        secondary_layout.addWidget(overlay, 0, Qt.AlignLeft)
        compact_group = QFrame(secondary_panel)
        compact_group.setProperty("role", "compactControlGroup")
        compact_group.setAttribute(Qt.WA_StyledBackground, True)
        compact_layout = QHBoxLayout(compact_group)
        compact_layout.setContentsMargins(10, 8, 10, 8)
        compact_layout.setSpacing(8)
        compact_layout.addWidget(QLabel("Compact group preview", compact_group))
        compact_chip = QLabel("Badge", compact_group)
        compact_chip.setProperty("role", "overlayHint")
        compact_layout.addWidget(compact_chip, 0, Qt.AlignLeft)
        compact_layout.addStretch(1)
        secondary_layout.addWidget(compact_group)
        layout.addWidget(secondary_panel)
        layout.addStretch(1)
        return page

    def _build_theme_preview_buttons_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewButtonsRoot")

        button_box = QGroupBox("Button States", preview_root)
        button_layout = QVBoxLayout(button_box)
        button_layout.setContentsMargins(14, 18, 14, 14)
        button_layout.setSpacing(10)
        top_row = QWidget(button_box)
        top_row_layout = QHBoxLayout(top_row)
        top_row_layout.setContentsMargins(0, 0, 0, 0)
        top_row_layout.setSpacing(10)
        normal_btn = QPushButton("Primary Action", top_row)
        checked_btn = QToolButton(top_row)
        checked_btn.setText("Checked")
        checked_btn.setCheckable(True)
        checked_btn.setChecked(True)
        disabled_btn = QPushButton("Disabled", top_row)
        disabled_btn.setEnabled(False)
        top_row_layout.addWidget(normal_btn)
        top_row_layout.addWidget(checked_btn)
        top_row_layout.addWidget(disabled_btn)
        top_row_layout.addStretch(1)
        button_layout.addWidget(top_row)

        help_row = QWidget(button_box)
        help_row_layout = QHBoxLayout(help_row)
        help_row_layout.setContentsMargins(0, 0, 0, 0)
        help_row_layout.setSpacing(10)
        help_btn = _create_round_help_button(self, "theme-settings")
        help_btn.setParent(help_row)
        help_btn.setToolTip("Round help button preview")
        help_disabled = _create_round_help_button(self, "settings")
        help_disabled.setParent(help_row)
        help_disabled.setEnabled(False)
        help_row_layout.addWidget(QLabel("Round Help Buttons", help_row))
        help_row_layout.addWidget(help_btn)
        help_row_layout.addWidget(help_disabled)
        help_row_layout.addStretch(1)
        button_layout.addWidget(help_row)
        layout.addWidget(button_box)
        layout.addStretch(1)
        return page

    def _build_theme_preview_inputs_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewInputsRoot")

        editor_box = QGroupBox("Editors", preview_root)
        editor_grid = QGridLayout(editor_box)
        self._configure_grid(editor_grid)
        preview_line_edit = QLineEdit("Focused line edit", editor_box)
        preview_line_edit.setPlaceholderText("Placeholder preview")
        preview_combo = FocusWheelComboBox(editor_box)
        preview_combo.addItems(["Global", "Europe", "United States"])
        preview_combo.setCurrentIndex(1)
        preview_spin = FocusWheelSpinBox(editor_box)
        preview_spin.setRange(0, 100)
        preview_spin.setValue(42)
        disabled_edit = QLineEdit("Disabled", editor_box)
        disabled_edit.setEnabled(False)
        editor_grid.addWidget(self._make_label("Line Edit"), 0, 0)
        editor_grid.addWidget(preview_line_edit, 0, 1)
        editor_grid.addWidget(
            self._make_hint("Use this field to test focus, placeholder, and border styling."),
            0,
            2,
        )
        editor_grid.addWidget(self._make_label("Combo Box"), 1, 0)
        editor_grid.addWidget(preview_combo, 1, 1)
        editor_grid.addWidget(
            self._make_hint("Dropdowns inherit the same input palette and focus rules."), 1, 2
        )
        editor_grid.addWidget(self._make_label("Spin Box"), 2, 0)
        editor_grid.addWidget(preview_spin, 2, 1)
        editor_grid.addWidget(
            self._make_hint(
                "Numeric editors preview the same QAbstractSpinBox chrome used elsewhere."
            ),
            2,
            2,
        )
        editor_grid.addWidget(self._make_label("Disabled"), 3, 0)
        editor_grid.addWidget(disabled_edit, 3, 1)
        editor_grid.addWidget(
            self._make_hint(
                "Disabled fields preview their own background, text, and border settings."
            ),
            3,
            2,
        )
        layout.addWidget(editor_box)

        indicator_box = QGroupBox("Indicators", preview_root)
        indicator_layout = QHBoxLayout(indicator_box)
        indicator_layout.setContentsMargins(14, 18, 14, 14)
        indicator_layout.setSpacing(12)
        preview_check = QCheckBox("Checked checkbox", indicator_box)
        preview_check.setChecked(True)
        preview_radio = QRadioButton("Radio option", indicator_box)
        preview_radio.setChecked(True)
        indicator_disabled = QCheckBox("Disabled", indicator_box)
        indicator_disabled.setEnabled(False)
        indicator_layout.addWidget(preview_check)
        indicator_layout.addWidget(preview_radio)
        indicator_layout.addWidget(indicator_disabled)
        indicator_layout.addStretch(1)
        layout.addWidget(indicator_box)
        layout.addStretch(1)
        preview_line_edit.setFocus(Qt.OtherFocusReason)
        return page

    def _build_theme_preview_data_views_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewDataViewsRoot")

        data_box = QGroupBox("Tables, Lists & Progress", preview_root)
        data_layout = QVBoxLayout(data_box)
        data_layout.setContentsMargins(14, 18, 14, 14)
        data_layout.setSpacing(10)
        preview_table = QTableWidget(3, 3, data_box)
        preview_table.setAlternatingRowColors(True)
        preview_table.setHorizontalHeaderLabels(["ID", "Title", "Status"])
        preview_table.verticalHeader().setVisible(False)
        preview_table.setItem(0, 0, QTableWidgetItem("1"))
        preview_table.setItem(0, 1, QTableWidgetItem("Orbit"))
        preview_table.setItem(0, 2, QTableWidgetItem("Active"))
        preview_table.setItem(1, 0, QTableWidgetItem("2"))
        preview_table.setItem(1, 1, QTableWidgetItem("Subconscious"))
        preview_table.setItem(1, 2, QTableWidgetItem("Pending"))
        preview_table.setItem(2, 0, QTableWidgetItem("3"))
        preview_table.setItem(2, 1, QTableWidgetItem("Guided Drift"))
        preview_table.setItem(2, 2, QTableWidgetItem("Archived"))
        preview_table.selectRow(1)
        preview_table.setMinimumHeight(170)
        data_layout.addWidget(preview_table)
        list_row = QWidget(data_box)
        list_row_layout = QHBoxLayout(list_row)
        list_row_layout.setContentsMargins(0, 0, 0, 0)
        list_row_layout.setSpacing(10)
        preview_list = QListWidget(list_row)
        preview_list.addItems(["Saved Theme", "Catalog Search", "History Snapshot"])
        preview_list.setCurrentRow(0)
        preview_list.setMinimumHeight(120)
        browser = QTextBrowser(list_row)
        browser.setPlainText(
            "Text browsers and previews inherit the table/list palette and selection styling."
        )
        browser.setMinimumHeight(120)
        list_row_layout.addWidget(preview_list, 1)
        list_row_layout.addWidget(browser, 1)
        data_layout.addWidget(list_row)
        progress = QProgressBar(data_box)
        progress.setRange(0, 100)
        progress.setValue(68)
        progress.setFormat("Indexing %p%")
        data_layout.addWidget(progress)
        layout.addWidget(data_box)
        layout.addStretch(1)
        return page

    def _build_theme_preview_navigation_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewNavigationRoot")

        menu_box = QGroupBox("Menus & Tabs", preview_root)
        menu_layout = QVBoxLayout(menu_box)
        menu_layout.setContentsMargins(14, 18, 14, 14)
        menu_layout.setSpacing(8)
        preview_menu_bar = QMenuBar(menu_box)
        preview_file_menu = preview_menu_bar.addMenu("File")
        preview_file_menu.addAction("New")
        preview_file_menu.addAction("Open")
        preview_view_menu = preview_menu_bar.addMenu("View")
        preview_view_menu.addAction("Theme")
        menu_layout.addWidget(preview_menu_bar)
        preview_tabs = QTabWidget(menu_box)
        preview_tabs.setDocumentMode(True)
        preview_tabs.addTab(QLabel("Selected tab content", preview_tabs), "Selected")
        preview_tabs.addTab(QLabel("Inactive tab content", preview_tabs), "Other Tab")
        menu_layout.addWidget(preview_tabs)
        preview_toolbar = QToolBar("Preview Toolbar", menu_box)
        preview_toolbar.setObjectName("themePreviewToolbar")
        preview_toolbar.addAction("Refresh")
        preview_toolbar.addAction("Export")
        preview_toolbar.addSeparator()
        toolbar_label = QLabel("Toolbar label", preview_toolbar)
        preview_toolbar.addWidget(toolbar_label)
        menu_layout.addWidget(preview_toolbar)
        preview_status = QStatusBar(menu_box)
        preview_status.setObjectName("themePreviewStatusBar")
        preview_status.showMessage("Status preview: 3 ready, 1 warning")
        preview_status.addPermanentWidget(QLabel("Profile: Demo", preview_status))
        menu_layout.addWidget(preview_status)
        layout.addWidget(menu_box)

        header_box = QGroupBox("Headers", preview_root)
        header_layout = QVBoxLayout(header_box)
        header_layout.setContentsMargins(14, 18, 14, 14)
        header_layout.setSpacing(8)
        header_table = QTableWidget(2, 2, header_box)
        header_table.setHorizontalHeaderLabels(["Column", "Value"])
        header_table.verticalHeader().setVisible(False)
        header_table.setItem(0, 0, QTableWidgetItem("Status"))
        header_table.setItem(0, 1, QTableWidgetItem("Active"))
        header_table.setItem(1, 0, QTableWidgetItem("Owner"))
        header_table.setItem(1, 1, QTableWidgetItem("Cosmowyn Records"))
        header_layout.addWidget(header_table)
        layout.addWidget(header_box)
        layout.addStretch(1)
        return page

    def _build_theme_preview_action_ribbon_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewActionRibbonRoot")

        ribbon_box = QGroupBox("Ribbon Over Workspace Tabs", preview_root)
        ribbon_layout = QVBoxLayout(ribbon_box)
        ribbon_layout.setContentsMargins(14, 18, 14, 14)
        ribbon_layout.setSpacing(8)
        intro = QLabel(
            "This preview keeps the action ribbon directly above tab chrome so you can judge separation and color contrast. Ribbon buttons still use the shared Buttons styling in this pass.",
            ribbon_box,
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "secondary")
        ribbon_layout.addWidget(intro)

        preview_toolbar = QToolBar("Preview Action Ribbon", ribbon_box)
        preview_toolbar.setObjectName("actionRibbonToolbar")
        preview_toolbar.setProperty("role", "actionRibbonToolbar")
        preview_toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        for label, checked in (("Catalog", True), ("Search", False), ("Releases", False)):
            button = QToolButton(preview_toolbar)
            button.setText(label)
            button.setCheckable(True)
            button.setChecked(checked)
            button.setProperty("role", "actionRibbonButton")
            preview_toolbar.addWidget(button)
        preview_toolbar.addSeparator()
        pinned_button = QToolButton(preview_toolbar)
        pinned_button.setText("Pinned")
        pinned_button.setCheckable(True)
        pinned_button.setProperty("role", "actionRibbonButton")
        preview_toolbar.addWidget(pinned_button)
        ribbon_layout.addWidget(preview_toolbar)

        workspace_tabs = QTabWidget(ribbon_box)
        workspace_tabs.setDocumentMode(True)
        first_page = QWidget(workspace_tabs)
        first_page.setProperty("role", "workspaceCanvas")
        first_layout = QVBoxLayout(first_page)
        first_layout.setContentsMargins(14, 14, 14, 14)
        first_layout.setSpacing(8)
        first_layout.addWidget(QLabel("Workspace tab content preview", first_page))
        first_note = QLabel(
            "Use the separate Action Ribbon tab to differentiate ribbon chrome from the dock and tab chrome below it.",
            first_page,
        )
        first_note.setWordWrap(True)
        first_note.setProperty("role", "secondary")
        first_layout.addWidget(first_note)
        first_layout.addStretch(1)
        second_page = QWidget(workspace_tabs)
        second_page.setProperty("role", "workspaceCanvas")
        second_layout = QVBoxLayout(second_page)
        second_layout.setContentsMargins(14, 14, 14, 14)
        second_layout.setSpacing(8)
        second_layout.addWidget(QLabel("Inactive workspace tab", second_page))
        second_layout.addStretch(1)
        workspace_tabs.addTab(first_page, "Catalog Managers")
        workspace_tabs.addTab(second_page, "Release Browser")
        ribbon_layout.addWidget(workspace_tabs)

        layout.addWidget(ribbon_box)
        layout.addStretch(1)
        return page

    def _build_theme_preview_blob_icons_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewBlobIconsRoot")

        preview_box = QGroupBox("Blob Badge Preview", preview_root)
        preview_layout = QGridLayout(preview_box)
        self._configure_grid(preview_layout)

        audio_icon = QLabel(preview_box)
        audio_icon.setFixedSize(34, 34)
        audio_icon.setAlignment(Qt.AlignCenter)
        audio_icon.setStyleSheet(
            "border: 1px solid palette(mid); border-radius: 6px; background: palette(base);"
        )
        audio_text = QLabel("71.3 MB", preview_box)
        audio_text.setProperty("role", "secondary")
        audio_row = QWidget(preview_box)
        audio_row_layout = QHBoxLayout(audio_row)
        audio_row_layout.setContentsMargins(0, 0, 0, 0)
        audio_row_layout.setSpacing(10)
        audio_row_layout.addWidget(audio_icon)
        audio_row_layout.addWidget(audio_text)
        audio_row_layout.addStretch(1)
        self._blob_icon_preview_labels["audio"] = audio_icon
        self._add_row(
            preview_layout,
            0,
            "Audio Column",
            audio_row,
            "Preview for the main Audio File column and inherited audio BLOB custom fields.",
        )

        image_icon = QLabel(preview_box)
        image_icon.setFixedSize(34, 34)
        image_icon.setAlignment(Qt.AlignCenter)
        image_icon.setStyleSheet(
            "border: 1px solid palette(mid); border-radius: 6px; background: palette(base);"
        )
        image_text = QLabel("2.4 MB", preview_box)
        image_text.setProperty("role", "secondary")
        image_row = QWidget(preview_box)
        image_row_layout = QHBoxLayout(image_row)
        image_row_layout.setContentsMargins(0, 0, 0, 0)
        image_row_layout.setSpacing(10)
        image_row_layout.addWidget(image_icon)
        image_row_layout.addWidget(image_text)
        image_row_layout.addStretch(1)
        self._blob_icon_preview_labels["image"] = image_icon
        self._add_row(
            preview_layout,
            1,
            "Image Column",
            image_row,
            "Preview for Album Art and inherited image BLOB custom fields.",
        )

        custom_hint_box = QGroupBox("Custom Column Override", preview_root)
        custom_hint_layout = QVBoxLayout(custom_hint_box)
        custom_hint_layout.setContentsMargins(14, 18, 14, 14)
        custom_hint_layout.setSpacing(8)
        hint = QLabel(
            "Each custom BLOB column can stay on the global icon or store its own override with the same system-icon, emoji, and custom-image options.",
            custom_hint_box,
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "secondary")
        custom_hint_layout.addWidget(hint)
        layout.addWidget(preview_box)
        layout.addWidget(custom_hint_box)
        layout.addStretch(1)
        return page

    def _build_theme_preview_advanced_page(self) -> QWidget:
        page, preview_root, layout = self._create_theme_preview_page("themePreviewAdvancedRoot")

        advanced_box = QGroupBox("Selector Playground", preview_root)
        advanced_layout = QVBoxLayout(advanced_box)
        advanced_layout.setContentsMargins(14, 18, 14, 14)
        advanced_layout.setSpacing(8)
        intro = QLabel(
            "Use this compact playground while writing Advanced QSS. The preview follows the advanced tab so you can test selectors without the other theme categories crowding the pane.",
            advanced_box,
        )
        intro.setProperty("role", "secondary")
        intro.setWordWrap(True)
        advanced_layout.addWidget(intro)
        playground_row = QWidget(advanced_box)
        playground_row.setObjectName("themePreviewPlayground")
        playground_layout = QHBoxLayout(playground_row)
        playground_layout.setContentsMargins(0, 0, 0, 0)
        playground_layout.setSpacing(10)
        advanced_button = QPushButton("Preview Button", playground_row)
        advanced_button.setObjectName("themePreviewButton")
        advanced_input = QLineEdit("Preview Field", playground_row)
        advanced_input.setObjectName("themePreviewField")
        advanced_help = _create_round_help_button(self, "theme-settings")
        advanced_help.setParent(playground_row)
        advanced_help.setObjectName("themePreviewHelpButton")
        playground_layout.addWidget(advanced_button)
        playground_layout.addWidget(advanced_input, 1)
        playground_layout.addWidget(advanced_help)
        advanced_layout.addWidget(playground_row)
        selector_hint = QLabel(
            'Example object names: `#themePreviewButton`, `#themePreviewField`, `#themePreviewHelpButton`, `#themePreviewPlayground QPushButton`, and `QToolButton[role="actionRibbonButton"]`.',
            advanced_box,
        )
        selector_hint.setProperty("role", "hint")
        selector_hint.setWordWrap(True)
        advanced_layout.addWidget(selector_hint)
        layout.addWidget(advanced_box)
        layout.addStretch(1)
        return page

    def _sync_theme_preview_to_builder_tab(self, index: int) -> None:
        if not hasattr(self, "_theme_builder_page_keys") or not self._theme_builder_page_keys:
            return
        if index < 0 or index >= len(self._theme_builder_page_keys):
            index = 0
        page_key = self._theme_builder_page_keys[index]
        preview_index = self._theme_preview_tab_indices.get(page_key, 0)
        self.theme_preview_tabs.setCurrentIndex(preview_index)
        self._queue_theme_preview_update()

    def _queue_theme_preview_update(self, *_args) -> None:
        if not self._theme_change_tracking_enabled:
            return
        self._theme_preview_timer.start()

    def _refresh_theme_previews(self) -> None:
        try:
            theme_values = self._theme_value_payload()
        except Exception:
            return
        stylesheet = build_app_theme_stylesheet(theme_values)
        for widget in getattr(self, "_theme_preview_roots", []):
            widget.setStyleSheet(stylesheet)
            _repolish_qss_widget_tree(widget)
        self._refresh_blob_icon_previews()
        current_preview_name = self.theme_preview_tabs.tabText(
            self.theme_preview_tabs.currentIndex()
        )
        if self._theme_builder_page_keys[self.theme_builder_tabs.currentIndex()] == "blob_icons":
            self.theme_preview_status_label.setText(
                "Showing the blob icons preview for the current profile draft. Audio and image media badges can use platform icons, emojis, or compressed custom images stored inside the database."
            )
        else:
            self.theme_preview_status_label.setText(
                "Showing the "
                + current_preview_name.lower()
                + " preview for "
                + (
                    f"saved theme '{self._current_theme_preset_name()}'"
                    if self._current_theme_preset_name()
                    else "the current custom draft"
                )
                + f". {len(self._theme_color_edits)} color slots and {len(self._theme_metric_spins)} geometry/typography controls are available in the builder."
            )
        if self.theme_live_preview_check.isChecked():
            self._apply_live_theme_preview(theme_values)
        elif (
            hasattr(self, "theme_preview_status_label")
            and self._theme_builder_page_keys[self.theme_builder_tabs.currentIndex()]
            != "blob_icons"
        ):
            self.theme_preview_status_label.setText(
                self.theme_preview_status_label.text()
                + " Turn on Live Preview to apply the draft to the whole running app while you edit."
            )

    def _refresh_blob_icon_previews(self) -> None:
        specs = self._blob_icon_value_payload()
        style = self.style() if hasattr(self, "style") else None
        for kind, label in self._blob_icon_preview_labels.items():
            icon = icon_from_blob_icon_spec(
                specs.get(kind),
                kind=kind,
                style=style,
                fallback_spec=self._blob_icon_original_values.get(kind),
                size=22,
            )
            label.setPixmap(icon.pixmap(24, 24))

    def _apply_live_theme_preview(self, values: dict[str, object]) -> None:
        owner = self.parent()
        if owner is not None and callable(getattr(owner, "_apply_theme", None)):
            owner._apply_theme(values)

    def _restore_original_application_theme(self) -> None:
        owner = self.parent()
        if owner is not None and callable(getattr(owner, "_apply_theme", None)):
            owner._apply_theme(self._theme_original_values)

    def _handle_theme_live_preview_toggled(self, checked: bool) -> None:
        if checked:
            self._refresh_theme_previews()
        else:
            self._restore_original_application_theme()

    def _handle_theme_dialog_finished(self, result: int) -> None:
        self._theme_preview_timer.stop()
        if result != QDialog.Accepted:
            self._restore_original_application_theme()

    def _create_gs1_default_combo(self, *, initial_text: str, placeholder: str) -> QComboBox:
        combo = FocusWheelComboBox(self)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setMinimumWidth(320)
        combo.setMaximumWidth(520)
        combo.setCurrentText(str(initial_text or "").strip())
        line_edit = combo.lineEdit()
        if line_edit is not None:
            line_edit.setClearButtonEnabled(True)
            line_edit.setPlaceholderText(placeholder)
        return combo

    def _create_gs1_contract_combo(self, *, initial_text: str) -> QComboBox:
        combo = FocusWheelComboBox(self)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setMinimumWidth(320)
        combo.setMaximumWidth(520)
        combo.setCurrentText(str(initial_text or "").strip())
        line_edit = combo.lineEdit()
        if line_edit is not None:
            line_edit.setClearButtonEnabled(True)
            line_edit.setPlaceholderText("Choose or type a contract number")
        return combo

    def _configure_gs1_default_option_combos(self) -> None:
        self._gs1_default_option_combos = {
            "target_market": self.gs1_target_market_edit,
            "language": self.gs1_language_edit,
            "brand": self.gs1_brand_edit,
            "subbrand": self.gs1_subbrand_edit,
            "packaging_type": self.gs1_packaging_type_edit,
            "product_classification": self.gs1_product_classification_edit,
        }

    def _configure_gs1_contract_combo(self) -> None:
        entries = tuple(self._gs1_contract_entries or ())
        current_text = self.gs1_active_contract_edit.currentText().strip()
        self.gs1_active_contract_edit.blockSignals(True)
        self.gs1_active_contract_edit.clear()
        self.gs1_active_contract_edit.addItem("")
        for entry in entries:
            self.gs1_active_contract_edit.addItem(entry.contract_number)
            index = self.gs1_active_contract_edit.count() - 1
            details = " | ".join(
                part
                for part in (
                    entry.product,
                    f"Status: {entry.status}" if entry.status else "",
                    (
                        f"Range: {entry.start_number}-{entry.end_number}"
                        if entry.start_number and entry.end_number
                        else ""
                    ),
                )
                if part
            )
            if details:
                self.gs1_active_contract_edit.setItemData(index, details, Qt.ToolTipRole)
        if (
            current_text
            and self.gs1_active_contract_edit.findText(current_text, Qt.MatchFixedString) < 0
        ):
            self.gs1_active_contract_edit.addItem(current_text)
        self.gs1_active_contract_edit.setCurrentText(current_text)
        self.gs1_active_contract_edit.blockSignals(False)
        self._refresh_gs1_contract_status()

    def _refresh_gs1_contract_status(self) -> None:
        entries = tuple(self._gs1_contract_entries or ())
        if not entries:
            self.gs1_contracts_status_label.setText(
                "No GTIN contract list has been imported yet. Import the CSV export from your GS1 portal to populate contract choices."
            )
            return
        previews = []
        for entry in entries[:6]:
            parts = [entry.contract_number]
            if entry.product:
                parts.append(entry.product)
            if entry.status:
                parts.append(entry.status)
            previews.append(" - ".join(parts))
        suffix = "" if len(entries) <= 6 else f"\n…and {len(entries) - 6} more."
        self.gs1_contracts_status_label.setText(
            f"Loaded {len(entries)} GTIN contract(s) from:\n{self.gs1_contracts_csv_edit.text().strip() or '(path not saved)'}\n\n"
            + "\n".join(previews)
            + suffix
        )

    def _refresh_gs1_template_status(self) -> None:
        asset = self._gs1_template_asset
        pending_path = self._pending_gs1_template_path.strip()
        if pending_path:
            self.gs1_template_path_edit.setText(pending_path)
            self.gs1_template_store_btn.setText("Replace…")
            self.gs1_template_export_btn.setEnabled(bool(asset is not None))
            summary = self._gs1_template_profile_summary()
            if summary:
                self.gs1_template_status_label.setText(
                    "Selected replacement workbook. Save settings to store it using the chosen storage mode.\n\n"
                    + summary
                )
            else:
                self.gs1_template_status_label.setText(
                    "Selected replacement workbook. Save settings to store it using the chosen storage mode."
                )
            return

        if asset is None:
            self.gs1_template_path_edit.clear()
            self.gs1_template_store_btn.setText("Upload…")
            self.gs1_template_export_btn.setEnabled(False)
            self.gs1_template_storage_combo.setCurrentIndex(
                max(0, self.gs1_template_storage_combo.findData(STORAGE_MODE_DATABASE))
            )
            self.gs1_template_status_label.setText(
                "No official GS1 workbook is stored in this profile yet."
            )
            return

        self.gs1_template_path_edit.setText(asset.label)
        self.gs1_template_store_btn.setText("Replace…")
        self.gs1_template_export_btn.setEnabled(True)
        storage_index = self.gs1_template_storage_combo.findData(
            normalize_storage_mode(asset.storage_mode, default=STORAGE_MODE_DATABASE)
        )
        self.gs1_template_storage_combo.setCurrentIndex(max(0, storage_index))
        lines = []
        if asset.stored_in_database:
            lines.append("Workbook is stored inside the current profile database.")
        else:
            lines.append("Workbook is stored as a managed local file inside the app workspace.")
        if asset.filename:
            lines.append(f"Filename: {asset.filename}")
        if asset.size_bytes:
            lines.append(f"Size: {asset.size_bytes} bytes")
        if asset.updated_at:
            lines.append(f"Updated: {asset.updated_at}")
        summary = self._gs1_template_profile_summary()
        if summary:
            lines.append("")
            lines.append(summary)
        self.gs1_template_status_label.setText("\n".join(lines))

    def _gs1_template_profile_summary(self) -> str:
        profile = self._gs1_template_profile
        if profile is None:
            return ""
        available_sheets = list(profile.available_sheet_names)
        if len(available_sheets) == 1:
            return (
                f"Verified workbook sheet: {available_sheets[0]} "
                f"(header row {profile.header_row})"
            )
        if available_sheets:
            return (
                "Verified workbook sheets: "
                + ", ".join(available_sheets)
                + f"\nDefault matched sheet: {profile.sheet_name} (header row {profile.header_row})"
            )
        return ""

    @staticmethod
    def _set_combo_items(combo: QComboBox, values, *, preserve_text: str = "") -> None:
        clean_values: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in clean_values:
                clean_values.append(text)
        current_text = str(preserve_text or combo.currentText() or "").strip()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")
        combo.addItems(clean_values)
        if current_text and combo.findText(current_text, Qt.MatchFixedString) < 0:
            combo.addItem(current_text)
        combo.setCurrentText(current_text)
        completer = QCompleter(clean_values)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        combo.setCompleter(completer)
        combo.blockSignals(False)

    def _refresh_gs1_template_options(self, *, show_errors: bool) -> None:
        self._gs1_template_profile = None
        options_by_field: dict[str, tuple[str, ...]] = {}
        template_path = self._pending_gs1_template_path.strip()
        if self.gs1_integration_service is not None:
            try:
                if template_path:
                    self._gs1_template_profile = self.gs1_integration_service.load_template_profile(
                        template_path
                    )
                elif self._gs1_template_asset is not None:
                    self._gs1_template_profile = (
                        self.gs1_integration_service.load_template_profile()
                    )
                options_by_field = dict(self._gs1_template_profile.field_options)
            except Exception as exc:
                if show_errors:
                    QMessageBox.warning(self, "GS1 Workbook", str(exc))
        self._refresh_gs1_template_status()
        builtin_options = {
            "target_market": COMMON_MARKET_CHOICES,
            "language": COMMON_LANGUAGE_CHOICES,
            "packaging_type": COMMON_PACKAGING_CHOICES,
            "product_classification": COMMON_CLASSIFICATION_CHOICES,
        }
        for field_name, combo in self._gs1_default_option_combos.items():
            merged_values: list[str] = []
            if field_name == "target_market":
                for value in builtin_options.get(field_name, ()):
                    text = str(value or "").strip()
                    if text and text not in merged_values:
                        merged_values.append(text)
            for value in options_by_field.get(field_name, ()):
                text = str(value or "").strip()
                if text and text not in merged_values:
                    merged_values.append(text)
            if field_name != "target_market":
                for value in builtin_options.get(field_name, ()):
                    text = str(value or "").strip()
                    if text and text not in merged_values:
                        merged_values.append(text)
            self._set_combo_items(combo, merged_values, preserve_text=combo.currentText())

    def _bind_theme_field_change_tracking(self) -> None:
        self.theme_font_family_combo.currentFontChanged.connect(self._mark_theme_selection_custom)
        self.theme_auto_contrast_check.toggled.connect(self._mark_theme_selection_custom)
        self.theme_live_preview_check.toggled.connect(self._handle_theme_live_preview_toggled)
        self.theme_custom_qss_edit.textChanged.connect(self._mark_theme_selection_custom)
        for edit in self._theme_color_edits.values():
            edit.textChanged.connect(self._mark_theme_selection_custom)
            edit.textChanged.connect(self._queue_theme_preview_update)
        for spin in self._theme_metric_spins.values():
            spin.valueChanged.connect(self._mark_theme_selection_custom)
            spin.valueChanged.connect(self._queue_theme_preview_update)
        self.theme_font_family_combo.currentFontChanged.connect(self._queue_theme_preview_update)
        self.theme_auto_contrast_check.toggled.connect(self._queue_theme_preview_update)
        self.theme_custom_qss_edit.textChanged.connect(self._queue_theme_preview_update)
        for editor in self._blob_icon_editors.values():
            editor.specChanged.connect(self._queue_theme_preview_update)
        self.theme_preset_combo.currentIndexChanged.connect(self._update_theme_preset_actions)
        self.theme_load_button.clicked.connect(self._load_selected_theme_preset)
        self.theme_save_button.clicked.connect(self._save_current_theme_preset)
        self.theme_delete_button.clicked.connect(self._delete_selected_theme_preset)
        self.theme_import_button.clicked.connect(self._import_theme_from_file)
        self.theme_export_button.clicked.connect(self._export_theme_to_file)
        self.theme_reset_button.clicked.connect(self._reset_theme_to_defaults)

    def _collect_qss_reference_entries(self) -> list[QssReferenceEntry]:
        app = QApplication.instance()
        widgets: list[QWidget] = []
        if app is not None:
            widgets = [widget for widget in app.topLevelWidgets() if isinstance(widget, QWidget)]
        if self not in widgets:
            widgets.append(self)
        for widget in widgets:
            _ensure_qss_widget_object_names(widget)
        return collect_qss_reference_entries(widgets)

    def _refresh_qss_selector_reference(self) -> None:
        self._qss_reference_entries = self._collect_qss_reference_entries()
        self.theme_custom_qss_edit.set_reference_entries(self._qss_reference_entries)
        self._apply_qss_reference_filter()

    def _apply_qss_reference_filter(self) -> None:
        filter_text = str(self.qss_reference_filter_edit.text() or "").strip().lower()
        if not filter_text:
            visible_entries = list(self._qss_reference_entries)
        else:
            visible_entries = [
                entry
                for entry in self._qss_reference_entries
                if filter_text in entry.category.lower()
                or filter_text in entry.selector.lower()
                or filter_text in entry.details.lower()
            ]
        self._qss_filtered_reference_entries = visible_entries
        self.qss_reference_table.setRowCount(0)
        for entry in visible_entries:
            row = self.qss_reference_table.rowCount()
            self.qss_reference_table.insertRow(row)
            self.qss_reference_table.setItem(row, 0, QTableWidgetItem(entry.category))
            self.qss_reference_table.setItem(row, 1, QTableWidgetItem(entry.selector))
            self.qss_reference_table.setItem(row, 2, QTableWidgetItem(entry.details))
        total = len(self._qss_reference_entries)
        shown = len(visible_entries)
        if total == 0:
            self.qss_reference_status_label.setText(
                "No selectors discovered yet. Open another window or dialog and refresh the catalog."
            )
        elif shown == total:
            self.qss_reference_status_label.setText(
                f"{total} selectors available for autocomplete and copy/insert."
            )
        else:
            self.qss_reference_status_label.setText(
                f"Showing {shown} of {total} selectors after filtering."
            )
        self._update_qss_reference_actions()

    def _selected_qss_selector(self) -> str:
        rows = self.qss_reference_table.selectionModel().selectedRows()
        if not rows:
            return ""
        item = self.qss_reference_table.item(rows[0].row(), 1)
        return item.text().strip() if item is not None else ""

    def _update_qss_reference_actions(self) -> None:
        has_selection = bool(self._selected_qss_selector())
        self.qss_reference_copy_button.setEnabled(has_selection)
        self.qss_reference_insert_button.setEnabled(has_selection)

    def _copy_selected_qss_selector(self) -> None:
        selector = self._selected_qss_selector()
        if not selector:
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(selector)

    def _insert_selected_qss_selector(self) -> None:
        selector = self._selected_qss_selector()
        if not selector:
            return
        self.theme_qss_tabs.setCurrentIndex(0)
        cursor = self.theme_custom_qss_edit.textCursor()
        cursor.insertText(selector)
        self.theme_custom_qss_edit.setTextCursor(cursor)
        self.theme_custom_qss_edit.setFocus()

    def _theme_value_payload(self) -> dict[str, object]:
        values = {
            "font_family": self.theme_font_family_combo.currentFont().family().strip(),
            "auto_contrast_enabled": self.theme_auto_contrast_check.isChecked(),
            "custom_qss": self.theme_custom_qss_edit.toPlainText(),
            "selected_name": self._current_theme_preset_name(),
        }
        for key in self._theme_color_edits:
            values[key] = self._theme_color_edits[key].text().strip()
        for key, spin in self._theme_metric_spins.items():
            values[key] = int(spin.value())
        return values

    def _blob_icon_value_payload(self) -> dict[str, dict[str, object]]:
        values = dict(self._blob_icon_settings or {})
        for kind, editor in self._blob_icon_editors.items():
            values[kind] = editor.current_spec()
        return normalize_blob_icon_settings(values)

    def _theme_preview_value_payload(self) -> dict[str, object]:
        values = dict(self._theme_settings or {})
        values["selected_name"] = self._current_theme_preset_name()

        font_combo = getattr(self, "theme_font_family_combo", None)
        if font_combo is not None:
            values["font_family"] = font_combo.currentFont().family().strip()

        auto_contrast_check = getattr(self, "theme_auto_contrast_check", None)
        if auto_contrast_check is not None:
            values["auto_contrast_enabled"] = auto_contrast_check.isChecked()

        custom_qss_edit = getattr(self, "theme_custom_qss_edit", None)
        if custom_qss_edit is not None:
            values["custom_qss"] = custom_qss_edit.toPlainText()

        for theme_key, theme_edit in self._theme_color_edits.items():
            values[theme_key] = theme_edit.text().strip()
        for metric_key, spin in self._theme_metric_spins.items():
            values[metric_key] = int(spin.value())
        return values

    def _apply_theme_values_to_fields(
        self, theme_values: dict[str, object], *, selected_name: str = ""
    ) -> None:
        self._theme_change_tracking_enabled = False
        try:
            font_family = str(theme_values.get("font_family") or "").strip()
            if font_family:
                self.theme_font_family_combo.setCurrentFont(QFont(font_family))
            self.theme_auto_contrast_check.setChecked(
                bool(theme_values.get("auto_contrast_enabled", True))
            )
            self.theme_custom_qss_edit.setPlainText(str(theme_values.get("custom_qss") or ""))
            for key, edit in self._theme_color_edits.items():
                edit.setText(str(theme_values.get(key) or "").strip())
            for key, spin in self._theme_metric_spins.items():
                try:
                    value = int(theme_values.get(key) or spin.value())
                except Exception:
                    value = spin.value()
                spin.setValue(max(spin.minimum(), min(spin.maximum(), value)))
            self._set_theme_preset_selection(selected_name)
        finally:
            self._theme_change_tracking_enabled = True
        self._update_theme_preset_actions()
        self._refresh_theme_previews()

    def _refresh_theme_preset_combo(self) -> None:
        current_name = self._current_theme_preset_name()
        self.theme_preset_combo.blockSignals(True)
        self.theme_preset_combo.clear()
        self.theme_preset_combo.addItem(self.CUSTOM_THEME_LABEL, "")
        for name in self._bundled_theme_order:
            if name not in self._stored_themes:
                continue
            self.theme_preset_combo.addItem(name, name)
            self.theme_preset_combo.setItemData(
                self.theme_preset_combo.count() - 1,
                f"Starter theme: {self._bundled_theme_descriptions.get(name, '')}".strip(),
                Qt.ToolTipRole,
            )
        for name in sorted(
            theme_name
            for theme_name in self._stored_themes
            if theme_name not in self._bundled_theme_names
        ):
            self.theme_preset_combo.addItem(name, name)
            self.theme_preset_combo.setItemData(
                self.theme_preset_combo.count() - 1,
                "Saved custom theme preset.",
                Qt.ToolTipRole,
            )
        self.theme_preset_combo.blockSignals(False)
        self._set_theme_preset_selection(current_name)

    def _set_theme_preset_selection(self, theme_name: str) -> None:
        clean_name = str(theme_name or "").strip()
        index = self.theme_preset_combo.findData(clean_name)
        if index < 0:
            index = 0
        self.theme_preset_combo.blockSignals(True)
        self.theme_preset_combo.setCurrentIndex(index)
        self.theme_preset_combo.blockSignals(False)
        self._update_theme_preset_actions()

    def _current_theme_preset_name(self) -> str:
        return str(self.theme_preset_combo.currentData() or "").strip()

    def _update_theme_preset_actions(self, *_args) -> None:
        selected_name = self._current_theme_preset_name()
        has_named_theme = bool(selected_name)
        is_bundled_theme = selected_name in self._bundled_theme_names
        self.theme_load_button.setEnabled(has_named_theme)
        self.theme_delete_button.setEnabled(has_named_theme and not is_bundled_theme)
        if is_bundled_theme:
            self.theme_delete_button.setToolTip(
                "Starter themes are packaged with the app and cannot be deleted."
            )
        else:
            self.theme_delete_button.setToolTip("Delete the selected saved theme.")

    def _mark_theme_selection_custom(self, *_args) -> None:
        if not self._theme_change_tracking_enabled:
            return
        if self._current_theme_preset_name():
            self._set_theme_preset_selection("")

    def _load_selected_theme_preset(self) -> None:
        selected_name = self._current_theme_preset_name()
        if not selected_name:
            return
        theme_values = self._stored_themes.get(selected_name)
        if not theme_values:
            QMessageBox.warning(
                self, "Theme Not Found", "The selected theme preset is no longer available."
            )
            self._set_theme_preset_selection("")
            return
        self._apply_theme_values_to_fields(theme_values, selected_name=selected_name)

    def _save_current_theme_preset(self) -> None:
        suggested_name = self._current_theme_preset_name() or "My Theme"
        if suggested_name in self._bundled_theme_names:
            suggested_name = f"{suggested_name} Copy"
        name, ok = QInputDialog.getText(self, "Save Theme", "Theme name:", text=suggested_name)
        if not ok:
            return
        clean_name = str(name or "").strip()
        if not clean_name:
            QMessageBox.warning(
                self, "Theme Name Required", "Please enter a name for the saved theme."
            )
            return
        if clean_name in self._bundled_theme_names:
            QMessageBox.information(
                self,
                "Starter Theme Protected",
                "Bundled starter themes cannot be overwritten. Save this draft under a new name instead.",
            )
            return
        if clean_name in self._stored_themes:
            answer = QMessageBox.question(
                self,
                "Overwrite Theme",
                f"A saved theme named '{clean_name}' already exists.\n\nOverwrite it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        theme_values = dict(self._theme_value_payload())
        theme_values["selected_name"] = ""
        self._stored_themes[clean_name] = theme_values
        self._refresh_theme_preset_combo()
        self._set_theme_preset_selection(clean_name)

    def _delete_selected_theme_preset(self) -> None:
        selected_name = self._current_theme_preset_name()
        if not selected_name:
            return
        if selected_name in self._bundled_theme_names:
            QMessageBox.information(
                self,
                "Starter Theme Protected",
                "Bundled starter themes are packaged with the app and cannot be deleted.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Delete Theme",
            f"Remove the saved theme '{selected_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._stored_themes.pop(selected_name, None)
        self._refresh_theme_preset_combo()
        self._set_theme_preset_selection("")

    def _import_theme_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Theme",
            str(Path.home()),
            "Theme JSON (*.json)",
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.warning(self, "Import Theme", f"Could not read theme file:\n{exc}")
            return

        theme_values = payload.get("theme") if isinstance(payload, dict) else None
        if not isinstance(theme_values, dict):
            theme_values = payload if isinstance(payload, dict) else None
        if not isinstance(theme_values, dict):
            QMessageBox.warning(
                self,
                "Import Theme",
                "The selected file does not contain a valid theme payload.",
            )
            return
        imported_name = ""
        if isinstance(payload, dict):
            imported_name = str(payload.get("name") or "").strip()
        self._apply_theme_values_to_fields(theme_values, selected_name="")
        self._set_theme_preset_selection("")
        if imported_name:
            self.theme_preview_status_label.setText(
                f"Imported theme draft '{imported_name}'. Save it to the library if you want to keep it as a preset."
            )

    def _export_theme_to_file(self) -> None:
        suggested_name = self._current_theme_preset_name() or "custom-theme"
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", suggested_name.strip()) or "custom-theme"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Theme",
            str(Path.home() / f"{safe_name}.json"),
            "Theme JSON (*.json)",
        )
        if not path:
            return
        payload = {
            "schema": "isrc-manager-theme",
            "version": 2,
            "name": self._current_theme_preset_name() or "Custom Theme",
            "theme": {
                **normalize_app_theme_settings(self._theme_value_payload()),
                "selected_name": "",
            },
        }
        try:
            Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "Export Theme", f"Could not save theme file:\n{exc}")
            return
        QMessageBox.information(self, "Export Theme", f"Saved theme to:\n{path}")

    def _reset_theme_to_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset Theme",
            "Reset the current theme draft back to the built-in defaults?\n\nThis does not remove any saved presets.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        defaults = default_theme_settings()
        defaults["selected_name"] = ""
        self._apply_theme_values_to_fields(defaults, selected_name="")
        self._set_theme_preset_selection("")

    def _sync_color_swatch(self, key: str) -> None:
        edit = self._theme_color_edits[key]
        swatch = self._theme_color_swatches[key]
        color_text = edit.text().strip()

        def apply_swatch(fill_color: QColor, text_color: QColor) -> None:
            border_color = (
                fill_color.darker(140)
                if fill_color.lightnessF() >= 0.58
                else fill_color.lighter(165)
            )
            swatch.setStyleSheet(
                "; ".join(
                    (
                        f"background-color: {fill_color.name().upper()}",
                        f"color: {text_color.name().upper()}",
                        f"border: 1px solid {border_color.name().upper()}",
                        "border-radius: 5px",
                    )
                )
            )

        if not color_text:
            effective_value = str(
                build_effective_theme_settings(self._theme_preview_value_payload()).get(key) or ""
            )
            effective_color = QColor(effective_value)
            if effective_color.isValid():
                fill_color = effective_color
            else:
                fill_color = QColor("#D1D5DB")
            text_color = QColor("#111827") if fill_color.lightnessF() >= 0.55 else QColor("#F9FAFB")
            swatch.setText("A")
            swatch.setToolTip(
                "Using the automatic derived/default color for this slot."
                + (
                    f"\nResolved preview: {fill_color.name().upper()}"
                    if fill_color.isValid()
                    else ""
                )
            )
            apply_swatch(fill_color, text_color)
        else:
            color = QColor(color_text)
            if color.isValid():
                text_color = QColor("#111827") if color.lightnessF() >= 0.55 else QColor("#F9FAFB")
                swatch.setText("")
                swatch.setToolTip(color.name().upper())
                apply_swatch(color, text_color)
            else:
                fill_color = QColor("#F87171")
                text_color = QColor("#111827")
                swatch.setText("!")
                swatch.setToolTip(
                    "Invalid color. Use values like #112233, #abc, or named Qt colors."
                )
                apply_swatch(fill_color, text_color)

    def _pick_theme_color(self, key: str) -> None:
        current_text = self._theme_color_edits[key].text().strip()
        initial = QColor(current_text) if current_text else QColor("#ffffff")
        color = QColorDialog.getColor(initial, self, f"Choose {key.replace('_', ' ').title()}")
        if color.isValid():
            self._theme_color_edits[key].setText(color.name().upper())

    def _browse_icon(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Icon",
            "",
            "Images (*.ico *.png *.jpg *.jpeg *.bmp)",
        )
        if path:
            self.icon_path_edit.setText(path)

    def _browse_gs1_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Official GS1 Workbook",
            self._pending_gs1_template_path
            or self.gs1_template_path_edit.text().strip()
            or str(Path.home()),
            "Excel Workbook (*.xlsx *.xlsm *.xltx *.xltm)",
        )
        if path:
            if self.gs1_integration_service is not None:
                try:
                    self.gs1_integration_service.load_template_profile(path)
                except Exception as exc:
                    QMessageBox.warning(self, "GS1 Workbook", str(exc))
                    return
            self._pending_gs1_template_path = str(path)
            self._refresh_gs1_template_options(show_errors=False)

    def _export_gs1_template(self):
        if self.gs1_integration_service is None:
            return
        asset = self._gs1_template_asset
        if asset is None:
            QMessageBox.information(
                self,
                "GS1 Workbook",
                "No GS1 workbook is stored in this profile yet.",
            )
            return
        suggested_path = str(Path.home() / (asset.filename or "gs1-template.xlsx"))
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Stored GS1 Workbook",
            suggested_path,
            "Excel Workbook (*.xlsx *.xlsm *.xltx *.xltm)",
        )
        if not path:
            return
        destination = Path(path)
        if not destination.suffix:
            destination = destination.with_suffix(asset.suffix)
        if destination.exists():
            overwrite = QMessageBox.question(
                self,
                "Overwrite File?",
                f"The file already exists:\n{destination}\n\nOverwrite it?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if overwrite != QMessageBox.Yes:
                return
        try:
            saved_path = self.gs1_integration_service.export_template_workbook(destination)
        except Exception as exc:
            QMessageBox.warning(self, "GS1 Workbook", str(exc))
            return
        QMessageBox.information(
            self,
            "GS1 Workbook",
            f"Saved the stored GS1 workbook to:\n{saved_path}",
        )

    def _browse_gs1_contracts_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import GS1 Contracts CSV",
            self.gs1_contracts_csv_edit.text().strip() or "",
            "CSV File (*.csv)",
        )
        if path:
            self._import_gs1_contracts_csv(path, show_errors=True)

    def _reload_gs1_contracts_csv(self):
        path = self.gs1_contracts_csv_edit.text().strip()
        if not path:
            QMessageBox.information(self, "GS1 Contracts", "Choose a GS1 contracts CSV first.")
            return
        self._import_gs1_contracts_csv(path, show_errors=True)

    def _import_gs1_contracts_csv(self, path: str, *, show_errors: bool) -> bool:
        if self.gs1_integration_service is None:
            return False
        try:
            entries = self.gs1_integration_service.contract_import_service.load_contracts(path)
        except GS1ContractImportError as exc:
            if show_errors:
                QMessageBox.warning(self, "GS1 Contracts", str(exc))
            return False
        self._gs1_contract_entries = tuple(entries)
        self._gs1_contracts_csv_path = str(path)
        self.gs1_contracts_csv_edit.setText(str(path))
        current_contract = self.gs1_active_contract_edit.currentText().strip()
        if not current_contract:
            active_entry = next(
                (entry for entry in self._gs1_contract_entries if entry.is_active), None
            )
            if active_entry is not None:
                self.gs1_active_contract_edit.setCurrentText(active_entry.contract_number)
        self._configure_gs1_contract_combo()
        return True

    def _clear_gs1_contracts(self):
        self._gs1_contract_entries = ()
        self._gs1_contracts_csv_path = ""
        self.gs1_contracts_csv_edit.clear()
        self.gs1_active_contract_edit.setCurrentText("")
        self._configure_gs1_contract_combo()

    def focus_field(self, name: str | None):
        target = self._focus_map.get(name or "")
        if target is None:
            return
        tab_index, widget = target
        self.tabs.setCurrentIndex(tab_index)
        widget.setFocus(Qt.OtherFocusReason)
        if isinstance(widget, QLineEdit):
            widget.selectAll()
        elif isinstance(widget, QComboBox):
            line_edit = widget.lineEdit()
            if line_edit is not None:
                line_edit.selectAll()

    def values(self) -> dict[str, object]:
        theme_values = self._theme_value_payload()
        blob_icon_values = self._blob_icon_value_payload()
        return {
            "window_title": self.window_title_edit.text().strip() or DEFAULT_WINDOW_TITLE,
            "icon_path": self.icon_path_edit.text().strip(),
            "isrc_prefix": self.isrc_prefix_edit.text().strip().upper(),
            "artist_code": self.artist_code_edit.text().strip(),
            "auto_snapshot_enabled": self.auto_snapshot_enabled_check.isChecked(),
            "auto_snapshot_interval_minutes": int(self.auto_snapshot_interval_spin.value()),
            "history_retention_mode": str(
                self.history_retention_mode_combo.currentData() or DEFAULT_HISTORY_RETENTION_MODE
            ),
            "history_auto_cleanup_enabled": self.history_auto_cleanup_enabled_check.isChecked(),
            "history_storage_budget_mb": int(self.history_storage_budget_spin.value()),
            "history_auto_snapshot_keep_latest": int(
                self.history_auto_snapshot_keep_latest_spin.value()
            ),
            "history_prune_pre_restore_copies_after_days": int(
                self.history_prune_pre_restore_copies_after_days_spin.value()
            ),
            "sena_number": self.sena_number_edit.text().strip(),
            "btw_number": self.btw_number_edit.text().strip(),
            "buma_relatie_nummer": self.buma_relatie_edit.text().strip(),
            "buma_ipi": self.buma_ipi_edit.text().strip(),
            "gs1_template_asset": self._gs1_template_asset,
            "gs1_template_import_path": self._pending_gs1_template_path.strip(),
            "gs1_template_storage_mode": self.gs1_template_storage_combo.currentData(),
            "gs1_contracts_csv_path": self.gs1_contracts_csv_edit.text().strip(),
            "gs1_contract_entries": tuple(self._gs1_contract_entries),
            "gs1_active_contract_number": self.gs1_active_contract_edit.currentText().strip(),
            "gs1_target_market": self.gs1_target_market_edit.currentText().strip(),
            "gs1_language": self.gs1_language_edit.currentText().strip(),
            "gs1_brand": self.gs1_brand_edit.currentText().strip(),
            "gs1_subbrand": self.gs1_subbrand_edit.currentText().strip(),
            "gs1_packaging_type": self.gs1_packaging_type_edit.currentText().strip(),
            "gs1_product_classification": self.gs1_product_classification_edit.currentText().strip(),
            "theme_settings": theme_values,
            "theme_library": dict(self._stored_themes),
            "blob_icon_settings": blob_icon_values,
        }

    def _accept_if_valid(self):
        values = self.values()
        if values["isrc_prefix"] and not re.fullmatch(
            r"[A-Z]{2}[A-Z0-9]{3}", values["isrc_prefix"]
        ):
            QMessageBox.warning(
                self, "Invalid Prefix", "ISRC Prefix must be 5 characters: CC + 3 letters/numbers."
            )
            self.focus_field("isrc_prefix")
            return
        if not re.fullmatch(r"\d{2}", values["artist_code"]):
            QMessageBox.warning(
                self, "Invalid Artist Code", "ISRC Artist Code must be exactly two digits (00–99)."
            )
            self.focus_field("artist_code")
            return
        gs1_template_import_path = str(values["gs1_template_import_path"] or "").strip()
        if gs1_template_import_path and self.gs1_integration_service is not None:
            try:
                self.gs1_integration_service.load_template_profile(gs1_template_import_path)
            except Exception as exc:
                QMessageBox.warning(self, "GS1 Workbook", str(exc))
                self.focus_field("gs1_template_path")
                return
        gs1_contracts_csv_path = str(values["gs1_contracts_csv_path"] or "").strip()
        if gs1_contracts_csv_path and Path(gs1_contracts_csv_path).suffix.lower() != ".csv":
            QMessageBox.warning(
                self,
                "Invalid GS1 Contracts File",
                "GS1 contracts must be imported from a .csv export file.",
            )
            self.focus_field("gs1_contracts_csv_path")
            return
        if gs1_contracts_csv_path and (
            gs1_contracts_csv_path != self._gs1_contracts_csv_path or not self._gs1_contract_entries
        ):
            if not self._import_gs1_contracts_csv(gs1_contracts_csv_path, show_errors=True):
                self.focus_field("gs1_contracts_csv_path")
                return
        for kind, spec in normalize_blob_icon_settings(values.get("blob_icon_settings")).items():
            mode = str(spec.get("mode") or "").strip().lower()
            if mode == "emoji" and not str(spec.get("emoji") or "").strip():
                QMessageBox.warning(
                    self,
                    "Blob Icon Required",
                    f"Choose or type an emoji for the {kind} blob icon.",
                )
                self.tabs.setCurrentIndex(2)
                return
            if mode == "image" and not (
                str(spec.get("image_path") or "").strip()
                or str(spec.get("image_png_base64") or "").strip()
            ):
                QMessageBox.warning(
                    self,
                    "Blob Icon Required",
                    f"Choose a custom image for the {kind} blob icon.",
                )
                self.tabs.setCurrentIndex(2)
                return
        for key, edit in self._theme_color_edits.items():
            color_text = edit.text().strip()
            if color_text and not QColor(color_text).isValid():
                QMessageBox.warning(
                    self,
                    "Invalid Theme Color",
                    f"{key.replace('_', ' ').title()} must be a valid color value like #112233, #abc, or a named Qt color.",
                )
                self.tabs.setCurrentIndex(2)
                edit.setFocus(Qt.OtherFocusReason)
                edit.selectAll()
                return
        self.accept()


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
        na = [int(s) if s.isdigit() else s.lower() for s in re.split(r"(\d+)", ta)]
        nb = [int(s) if s.isdigit() else s.lower() for s in re.split(r"(\d+)", tb)]
        return na < nb


class _ManageArtistsDialog(QDialog):
    """Safely purge only unused artists (no refs in Tracks or TrackArtists)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Manage stored artists")
        self.setModal(True)
        self.resize(900, 620)
        self.setMinimumSize(820, 560)
        self.catalog_service = parent.catalog_service
        _apply_standard_dialog_chrome(self, "manageArtistsDialog")

        self.tbl = QTableWidget(0, 5, self)
        self.tbl.setHorizontalHeaderLabels(
            ["Artist", "Main uses", "Extra uses", "Total", "Delete?"]
        )
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setMinimumHeight(380)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(14)
        _add_standard_dialog_header(
            v,
            self,
            title="Stored Artists",
            subtitle="Review artist names stored in the catalog and safely remove entries that are no longer used anywhere.",
            help_topic_id="catalog-managers",
        )

        table_box, table_layout = _create_standard_section(
            self,
            "Artist Usage",
            "Only artists with zero references can be deleted or purged from the stored artist list.",
        )
        table_layout.addWidget(self.tbl, 1)

        btn_refresh = QPushButton("Refresh")
        btn_purge = QPushButton("Purge All Unused")
        btn_delete = QPushButton("Delete Selected")
        btn_close = QPushButton("Close")
        table_layout.addWidget(
            _create_action_button_grid(
                self,
                [btn_refresh, btn_purge, btn_delete, btn_close],
                columns=2,
            )
        )
        v.addWidget(table_box, 1)

        btn_refresh.clicked.connect(self._load)
        btn_purge.clicked.connect(self._purge_unused)
        btn_delete.clicked.connect(self._delete_selected)
        btn_close.clicked.connect(self.accept)

        self._load()

    def _load(self):
        self.tbl.setRowCount(0)
        for artist in self.catalog_service.list_artists_with_usage():
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)

            self.tbl.setItem(r, 0, QTableWidgetItem(artist.name))
            it_main = QTableWidgetItem(str(artist.main_uses))
            it_main.setTextAlignment(Qt.AlignCenter)
            it_extra = QTableWidgetItem(str(artist.extra_uses))
            it_extra.setTextAlignment(Qt.AlignCenter)
            it_total = QTableWidgetItem(str(artist.total_uses))
            it_total.setTextAlignment(Qt.AlignCenter)
            self.tbl.setItem(r, 1, it_main)
            self.tbl.setItem(r, 2, it_extra)
            self.tbl.setItem(r, 3, it_total)

            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if artist.total_uses == 0 else Qt.Unchecked)
            if artist.total_uses > 0:
                chk.setFlags(Qt.NoItemFlags)
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
            QMessageBox.information(self, "Nothing to delete", "No unused artists selected.")
            return
        if (
            QMessageBox.question(self, "Confirm", f"Delete {len(ids)} unused artist(s)?")
            != QMessageBox.Yes
        ):
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
        to_del = [
            artist.artist_id
            for artist in self.catalog_service.list_artists_with_usage()
            if artist.total_uses == 0
        ]
        if not to_del:
            QMessageBox.information(self, "Nothing to purge", "No unused artists found.")
            return
        if (
            QMessageBox.question(self, "Confirm", f"Purge {len(to_del)} unused artist(s)?")
            != QMessageBox.Yes
        ):
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
        self.resize(860, 600)
        self.setMinimumSize(780, 540)
        self.catalog_service = parent.catalog_service
        _apply_standard_dialog_chrome(self, "manageAlbumsDialog")

        self.tbl = QTableWidget(0, 3, self)
        self.tbl.setHorizontalHeaderLabels(["Album", "Uses", "Delete?"])
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setMinimumHeight(360)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(14)
        _add_standard_dialog_header(
            v,
            self,
            title="Stored Albums",
            subtitle="Review stored album titles and safely remove records that are no longer linked to any tracks.",
            help_topic_id="catalog-managers",
        )

        table_box, table_layout = _create_standard_section(
            self,
            "Album Usage",
            "Only album titles with zero linked tracks can be deleted or purged from the catalog list.",
        )
        table_layout.addWidget(self.tbl, 1)

        btn_refresh = QPushButton("Refresh")
        btn_purge = QPushButton("Purge All Unused")
        btn_delete = QPushButton("Delete Selected")
        btn_close = QPushButton("Close")
        table_layout.addWidget(
            _create_action_button_grid(
                self,
                [btn_refresh, btn_purge, btn_delete, btn_close],
                columns=2,
            )
        )
        v.addWidget(table_box, 1)

        btn_refresh.clicked.connect(self._load)
        btn_purge.clicked.connect(self._purge_unused)
        btn_delete.clicked.connect(self._delete_selected)
        btn_close.clicked.connect(self.accept)

        self._load()

    def _load(self):
        self.tbl.setRowCount(0)
        for album in self.catalog_service.list_albums_with_usage():
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            self.tbl.setItem(r, 0, QTableWidgetItem(album.title))
            it_uses = QTableWidgetItem(str(album.uses))
            it_uses.setTextAlignment(Qt.AlignCenter)
            self.tbl.setItem(r, 1, it_uses)

            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if album.uses == 0 else Qt.Unchecked)
            if album.uses > 0:
                chk.setFlags(Qt.NoItemFlags)
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
            QMessageBox.information(self, "Nothing to delete", "No unused albums selected.")
            return
        if (
            QMessageBox.question(self, "Confirm", f"Delete {len(ids)} unused album(s)?")
            != QMessageBox.Yes
        ):
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
        to_del = [
            album.album_id
            for album in self.catalog_service.list_albums_with_usage()
            if album.uses == 0
        ]
        if not to_del:
            QMessageBox.information(self, "Nothing to purge", "No unused albums found.")
            return
        if (
            QMessageBox.question(self, "Confirm", f"Purge {len(to_del)} unused album(s)?")
            != QMessageBox.Yes
        ):
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
        self.resize(720, 420)
        self.setMinimumSize(640, 360)
        _apply_standard_dialog_chrome(self, "licenseUploadDialog")

        # --- Controls ---
        self.track_combo = FocusWheelComboBox()
        for tid, title in tracks:
            self.track_combo.addItem(title, tid)
        if preselect_track_id:
            idx = self.track_combo.findData(preselect_track_id)
            if idx >= 0:
                self.track_combo.setCurrentIndex(idx)

        self.lic_combo = FocusWheelComboBox()
        self.lic_combo.setEditable(True)
        for lid, name in licensees:
            self.lic_combo.addItem(name, lid)
        self.storage_mode_combo = FocusWheelComboBox()
        self.storage_mode_combo.addItem("Store in Database", STORAGE_MODE_DATABASE)
        self.storage_mode_combo.addItem("Store as Managed File", STORAGE_MODE_MANAGED_FILE)
        self.storage_mode_combo.setCurrentIndex(1)

        self.file_label = QLabel("No signed PDF selected yet.")
        self.file_label.setProperty("role", "supportingText")
        self.file_label.setWordWrap(True)
        self.btn_pick = QPushButton("Upload PDF…")
        self.btn_pick.clicked.connect(self._pick_pdf)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)
        _add_standard_dialog_header(
            main_layout,
            self,
            title="Attach Signed License PDF",
            subtitle="Link a signed PDF to one catalog track and choose whether the file is stored in the database or in the managed license archive.",
            help_topic_id="licenses",
        )

        details_box, details_layout = _create_standard_section(
            self,
            "License Details",
            "Choose the track and licensee that this uploaded PDF should belong to.",
        )
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.addRow("Track", self.track_combo)
        form.addRow("Licensee", self.lic_combo)
        form.addRow("Storage", self.storage_mode_combo)
        details_layout.addLayout(form)
        main_layout.addWidget(details_box)

        file_box, file_layout = _create_standard_section(
            self,
            "Signed PDF",
            "The selected file is copied into the app-managed license storage when you save.",
        )
        file_row = QHBoxLayout()
        file_row.setSpacing(10)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(self.btn_pick)
        file_layout.addLayout(file_row)
        main_layout.addWidget(file_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, Qt.Horizontal, self
        )
        self.btn_save = buttons.button(QDialogButtonBox.Save)
        self.btn_cancel = buttons.button(QDialogButtonBox.Cancel)
        if self.btn_save is not None:
            self.btn_save.setEnabled(False)
            self.btn_save.setDefault(True)
        if self.btn_cancel is not None:
            self.btn_cancel.setAutoDefault(False)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        self._picked_path = None

    def _pick_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select signed license (PDF)", "", "PDF (*.pdf)"
        )
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
                storage_mode=self.storage_mode_combo.currentData(),
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


class LicensesBrowserPanel(QWidget):
    close_requested = Signal()

    def __init__(self, *, app, license_service_provider, track_filter_id=None, parent=None):
        super().__init__(parent)
        self.app = app
        self.license_service_provider = license_service_provider
        self.setObjectName("licensesBrowserPanel")
        _apply_standard_widget_chrome(self, "licensesBrowserPanel")

        # --- model/proxy ---
        self.model = QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels(
            ["Licensee", "Track", "Uploaded", "Filename", "_file", "_id"]
        )
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
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._ctx_menu)
        self.table.installEventFilter(self)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.list = QListView()
        self.list.setModel(self.proxy)
        self.list.setSelectionMode(QListView.SingleSelection)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._ctx_menu)
        self.list.installEventFilter(self)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.table, "Table")
        self.tabs.addTab(self.list, "List")

        # --- filter ---
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Fuzzy filter…")
        self.filter_edit.setClearButtonEnabled(True)
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

        self.act_store_db = QAction("Store in Database", self)
        self.act_store_db.triggered.connect(
            lambda: self._convert_selected_storage_mode(STORAGE_MODE_DATABASE)
        )

        self.act_store_file = QAction("Store as Managed File", self)
        self.act_store_file.triggered.connect(
            lambda: self._convert_selected_storage_mode(STORAGE_MODE_MANAGED_FILE)
        )

        # --- layout ---
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(14)
        _add_standard_dialog_header(
            v,
            self,
            title="License Archive",
            subtitle="Browse stored license PDFs, preview the documents, and manage the records linked to your catalog tracks.",
            help_topic_id="licenses",
        )

        filter_box, filter_layout = _create_standard_section(
            self,
            "Find Licenses",
            "Search by licensee, track title, upload date, or filename. The table view supports multi-select deletion.",
        )
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(8)
        filter_row.addWidget(self.filter_edit, 1)
        filter_layout.addLayout(filter_row)
        v.addWidget(filter_box)

        browser_box, browser_layout = _create_standard_section(
            self,
            "Stored License Records",
            "Use the action buttons or the context menu to preview, download, edit, or delete the selected license records.",
        )
        self.preview_button = QPushButton("Preview")
        self.download_button = QPushButton("Download PDF…")
        self.edit_button = QPushButton("Edit…")
        self.delete_button = QPushButton("Delete Selected")
        self.store_db_button = QPushButton("Store in Database")
        self.store_file_button = QPushButton("Store as Managed File")
        self.migrate_button = QPushButton("Migrate to Contracts…")
        self.refresh_button = QPushButton("Refresh")
        self.preview_button.clicked.connect(self._preview_pdf)
        self.download_button.clicked.connect(self._download_pdf)
        self.edit_button.clicked.connect(self._edit_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.store_db_button.clicked.connect(
            lambda: self._convert_selected_storage_mode(STORAGE_MODE_DATABASE)
        )
        self.store_file_button.clicked.connect(
            lambda: self._convert_selected_storage_mode(STORAGE_MODE_MANAGED_FILE)
        )
        self.migrate_button.clicked.connect(self._migrate_to_contracts)
        self.refresh_button.clicked.connect(self.refresh_data)
        browser_layout.addWidget(
            _create_action_button_grid(
                self,
                [
                    self.preview_button,
                    self.download_button,
                    self.edit_button,
                    self.delete_button,
                    self.store_db_button,
                    self.store_file_button,
                    self.migrate_button,
                    self.refresh_button,
                ],
                columns=4,
            )
        )
        browser_layout.addWidget(self.tabs, 1)
        v.addWidget(browser_box, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close_requested.emit)
        close_row.addWidget(close_button)
        v.addLayout(close_row)

        # --- init/load ---
        self._track_filter_id = track_filter_id
        self._load_rows(self._track_filter_id)

        # after views exist, hook selection signals
        self.table.selectionModel().selectionChanged.connect(
            lambda *_: self._update_action_states()
        )
        self.list.selectionModel().selectionChanged.connect(lambda *_: self._update_action_states())
        self.tabs.currentChanged.connect(lambda *_: self._update_action_states())
        self._update_action_states()

    def _license_service(self):
        return self.license_service_provider()

    def set_track_filter_id(self, track_filter_id=None):
        self._track_filter_id = track_filter_id
        self.refresh_data()

    # ---------- helpers ----------
    def _update_action_states(self):
        has = bool(self._selected_record())
        for a in (
            self.act_preview,
            self.act_download,
            self.act_edit,
            self.act_delete,
            self.act_store_db,
            self.act_store_file,
        ):
            a.setEnabled(has)
        for button in (
            getattr(self, "preview_button", None),
            getattr(self, "download_button", None),
            getattr(self, "edit_button", None),
            getattr(self, "delete_button", None),
            getattr(self, "store_db_button", None),
            getattr(self, "store_file_button", None),
        ):
            if button is not None:
                button.setEnabled(has)

    def refresh_data(self):
        filt = self.filter_edit.text()
        self._load_rows(self._track_filter_id)
        self.filter_edit.setText(filt)
        self._update_action_states()

    def _apply_filter(self, text):
        pattern = ".*".join(map(re.escape, text.strip()))
        self.proxy.setFilterRegularExpression(
            QRegularExpression(pattern, QRegularExpression.CaseInsensitiveOption)
        )

    def _load_rows(self, track_filter_id=None):
        service = self._license_service()
        if track_filter_id is None:
            track_filter_id = self._track_filter_id
        self.model.removeRows(0, self.model.rowCount())
        if service is None:
            self._update_action_states()
            return
        for row in service.list_rows(track_filter_id):
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
        current_view = self.tabs.currentWidget()
        idx = current_view.currentIndex() if current_view is not None else self.table.currentIndex()
        if not idx.isValid():
            idx = self.table.currentIndex()
        if not idx.isValid():
            idx = self.list.currentIndex()
        if not idx.isValid():
            return None
        src = self.proxy.mapToSource(idx)
        row = src.row()
        file_path = self.model.item(row, 4).text()
        rec_id = int(self.model.item(row, 5).text())
        return rec_id, file_path

    def _selected_records(self) -> list[tuple[int, str]]:
        current_view = self.tabs.currentWidget()
        proxy_indices = []
        if current_view is self.table:
            proxy_indices = list(self.table.selectionModel().selectedRows())
        else:
            idx = self.list.currentIndex()
            if idx.isValid():
                proxy_indices = [idx]

        if not proxy_indices:
            if self.table.selectionModel() is not None:
                proxy_indices = list(self.table.selectionModel().selectedRows())
            elif self.list.currentIndex().isValid():
                proxy_indices = [self.list.currentIndex()]

        rows: list[tuple[int, str]] = []
        seen_ids: set[int] = set()
        for proxy_idx in proxy_indices:
            if not proxy_idx.isValid():
                continue
            src_idx = self.proxy.mapToSource(proxy_idx)
            row = src_idx.row()
            rec_id = int(self.model.item(row, 5).text())
            if rec_id in seen_ids:
                continue
            seen_ids.add(rec_id)
            rows.append((rec_id, self.model.item(row, 4).text()))
        return rows

    def _ctx_menu(self, _pos):
        # reuse same actions as menu bar
        menu = QMenu(self)
        menu.addAction(self.act_preview)
        menu.addAction(self.act_download)
        menu.addSeparator()
        menu.addAction(self.act_edit)
        menu.addAction(self.act_delete)
        menu.addSeparator()
        menu.addAction(self.act_store_db)
        menu.addAction(self.act_store_file)
        self._update_action_states()
        menu.exec(QCursor.pos())

    def _selected_license_record(self):
        rec = self._selected_record()
        if not rec:
            return None
        service = self._license_service()
        if service is None:
            return None
        record = service.fetch_license(rec[0])
        if record is None:
            return None
        return record

    def _materialize_license_pdf(self, record_id: int) -> tuple[Path, bool]:
        service = self._license_service()
        if service is None:
            raise FileNotFoundError(record_id)
        record = service.fetch_license(record_id)
        if record is None:
            raise FileNotFoundError(record_id)
        if record.file_path and record.storage_mode != STORAGE_MODE_DATABASE:
            resolved = service.resolve_path(record.file_path)
            if resolved.exists():
                return resolved, False
        data, _mime = service.fetch_license_bytes(record_id)
        suffix = Path(record.filename or "license.pdf").suffix or ".pdf"
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        with temp_file:
            temp_file.write(data)
        return Path(temp_file.name), True

    # ---------- actions ----------
    def _preview_pdf(self):
        record = self._selected_license_record()
        if record is None:
            return
        service = self._license_service()
        if service is None:
            QMessageBox.warning(self, "License Archive", "Open a profile first.")
            return
        try:
            abs_path, remove_after = self._materialize_license_pdf(record.record_id)
        except FileNotFoundError:
            QMessageBox.warning(self, "Missing file", "The stored PDF could not be found.")
            return

        try:
            opened_externally = False
            from PySide6.QtPdfWidgets import QPdfView
            from PySide6.QtPdf import QPdfDocument

            dlg = QDialog(self)
            dlg.setWindowTitle(abs_path.name)
            dlg.resize(980, 760)
            dlg.setMinimumSize(860, 660)
            _apply_standard_dialog_chrome(dlg, "licensePdfPreviewDialog")

            doc = QPdfDocument(dlg)
            if doc.load(str(abs_path)) != QPdfDocument.NoError:
                raise RuntimeError("Failed to load PDF")

            view = QPdfView(dlg)
            view.setDocument(doc)
            view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            view.setPageMode(QPdfView.PageMode.SinglePage)

            layout = QVBoxLayout(dlg)
            layout.setContentsMargins(18, 18, 18, 18)
            layout.setSpacing(14)
            _add_standard_dialog_header(
                layout,
                dlg,
                title="License PDF Preview",
                subtitle=f"Review the stored signed PDF for {abs_path.name}.",
                help_topic_id="licenses",
            )

            preview_box, preview_layout = _create_standard_section(
                dlg,
                "Document Preview",
                "This window opens the managed PDF directly from the license archive so you can verify the stored document before downloading or editing it.",
            )
            preview_layout.addWidget(view, 1)
            layout.addWidget(preview_box, 1)

            buttons = QDialogButtonBox(QDialogButtonBox.Close, Qt.Horizontal, dlg)
            buttons.rejected.connect(dlg.reject)
            layout.addWidget(buttons)

            from PySide6.QtCore import QTimer

            dlg.finished.connect(lambda _: QTimer.singleShot(200, doc.deleteLater))
            dlg.finished.connect(lambda _: QTimer.singleShot(250, view.deleteLater))

            dlg.exec()
        except Exception:
            opened_externally = True
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(abs_path)))
        finally:
            if remove_after and not opened_externally:
                try:
                    abs_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _download_pdf(self):
        record = self._selected_license_record()
        if record is None:
            return
        service = self._license_service()
        if service is None:
            QMessageBox.warning(self, "License Archive", "Open a profile first.")
            return
        try:
            data, _mime = service.fetch_license_bytes(record.record_id)
        except FileNotFoundError:
            QMessageBox.warning(self, "Missing", "The stored PDF could not be found.")
            return
        suggested_name = record.filename or "license.pdf"
        dst, _ = QFileDialog.getSaveFileName(self, "Save PDF as…", suggested_name, "PDF (*.pdf)")
        if dst:
            mutation = lambda: Path(dst).write_bytes(data)
            if self.app is not None and hasattr(self.app, "_run_file_history_action"):
                self.app._run_file_history_action(
                    action_label=f"Download License PDF: {Path(dst).name}",
                    action_type="file.download_license_pdf",
                    target_path=dst,
                    mutation=mutation,
                    entity_type="License",
                    entity_id=str(dst),
                    payload={"record_id": record.record_id, "target_path": str(dst)},
                )
            else:
                mutation()

    def _edit_selected(self):
        rec = self._selected_record()
        if not rec:
            return
        service = self._license_service()
        if service is None:
            QMessageBox.warning(self, "License Archive", "Open a profile first.")
            return
        rec_id, _path = rec
        record = service.fetch_license(rec_id)
        row = (record.track_id, record.licensee_id) if record else None
        if not row:
            return
        track_id, licensee_id = row
        d = QDialog(self)
        d.setWindowTitle("Edit License")
        d.setModal(True)
        d.resize(680, 420)
        d.setMinimumSize(620, 360)
        _apply_standard_dialog_chrome(d, "editLicenseDialog")
        track_lbl = QLabel(f"Track ID {track_id}")
        track_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        lic_combo = FocusWheelComboBox()
        lic_combo.setEditable(True)
        # load licensees
        for lid, name in service.list_licensee_choices():
            lic_combo.addItem(name, lid)
        idx = lic_combo.findData(licensee_id)
        if idx >= 0:
            lic_combo.setCurrentIndex(idx)
        file_lbl = QLabel(record.filename or "No file")
        storage_mode_combo = FocusWheelComboBox()
        storage_mode_combo.addItem("Store in Database", STORAGE_MODE_DATABASE)
        storage_mode_combo.addItem("Store as Managed File", STORAGE_MODE_MANAGED_FILE)
        current_storage_mode = normalize_storage_mode(
            record.storage_mode, default=STORAGE_MODE_MANAGED_FILE
        )
        current_storage_index = storage_mode_combo.findData(current_storage_mode)
        storage_mode_combo.setCurrentIndex(max(0, current_storage_index))
        pick_btn = QPushButton("Replace PDF…")
        new_path = {"p": None}

        def pick():
            p, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "PDF (*.pdf)")
            if p:
                new_path["p"] = p
                file_lbl.setText(Path(p).name)

        pick_btn.clicked.connect(pick)
        root = QVBoxLayout(d)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        _add_standard_dialog_header(
            root,
            d,
            title="Edit License Record",
            subtitle="Update the linked licensee or replace the stored PDF while keeping the track relationship fixed.",
            help_topic_id="licenses",
        )

        details_box, details_layout = _create_standard_section(
            d,
            "License Details",
            "The associated track stays fixed for this record. Use this form to correct the licensee name or swap in a newer signed PDF.",
        )
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.addRow("Track", track_lbl)
        form.addRow("Licensee", lic_combo)
        form.addRow("Storage", storage_mode_combo)
        h = QHBoxLayout()
        h.setSpacing(8)
        h.addWidget(file_lbl, 1)
        h.addWidget(pick_btn)
        form.addRow("PDF", h)
        details_layout.addLayout(form)
        root.addWidget(details_box, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, Qt.Horizontal, d
        )
        buttons.accepted.connect(d.accept)
        buttons.rejected.connect(d.reject)
        root.addWidget(buttons)
        if d.exec() != QDialog.Accepted:
            return
        new_name = lic_combo.currentText().strip()
        if not new_name:
            new_name = lic_combo.currentText().strip() or ""
        try:
            mutation = lambda: service.update_license(
                record_id=rec_id,
                licensee_name=new_name,
                replacement_pdf_path=new_path["p"],
                storage_mode=storage_mode_combo.currentData(),
            )
            if self.app is not None and hasattr(self.app, "_run_snapshot_history_action"):
                self.app._run_snapshot_history_action(
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

    def _convert_selected_storage_mode(self, target_mode: str) -> None:
        record = self._selected_license_record()
        if record is None:
            return
        service = self._license_service()
        if service is None:
            QMessageBox.warning(self, "License Archive", "Open a profile first.")
            return
        current_mode = normalize_storage_mode(record.storage_mode, default=None)
        clean_target = normalize_storage_mode(target_mode)
        if current_mode == clean_target:
            return
        try:
            mutation = lambda: service.convert_storage_mode(record.record_id, clean_target)
            if self.app is not None and hasattr(self.app, "_run_snapshot_history_action"):
                self.app._run_snapshot_history_action(
                    action_label=f"Convert License Storage: {record.filename or record.record_id}",
                    action_type="license.convert_storage_mode",
                    entity_type="License",
                    entity_id=record.record_id,
                    payload={
                        "record_id": record.record_id,
                        "target_mode": clean_target,
                    },
                    mutation=mutation,
                )
            else:
                mutation()
            self.refresh_data()
        except Exception as exc:
            QMessageBox.critical(self, "License Archive", str(exc))

    def _delete_selected(self):
        selected_records = self._selected_records()
        if not selected_records:
            QMessageBox.information(self, "Delete Licenses", "No records selected.")
            return

        ids = [record_id for record_id, _path in selected_records]

        confirm = QMessageBox.question(
            self,
            "Delete Licenses",
            f"Delete {len(ids)} selected license(s)?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        delete_files = (
            QMessageBox.question(
                self,
                "Delete Files",
                "Also delete the stored PDF files (if any)?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        )

        try:
            service = self._license_service()
            if service is None:
                QMessageBox.warning(self, "Delete Licenses", "Open a profile first.")
                return
            mutation = lambda: service.delete_licenses(ids, delete_files=delete_files)
            if self.app is not None and hasattr(self.app, "_run_snapshot_history_action"):
                self.app._run_snapshot_history_action(
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

    def _migrate_to_contracts(self):
        if self.app is None or not hasattr(self.app, "migrate_legacy_licenses_to_contracts"):
            QMessageBox.information(
                self,
                "Legacy License Migration",
                "This action is only available when the browser is opened from the main window.",
            )
            return
        self.close_requested.emit()
        self.app.migrate_legacy_licenses_to_contracts()

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Space:
            self._preview_pdf()
            return True
        return super().eventFilter(obj, ev)


class LicensesBrowserDialog(QDialog):
    def __init__(self, license_service, track_filter_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Licenses")
        self.setModal(True)
        self.resize(1080, 760)
        self.setMinimumSize(980, 680)
        _apply_standard_dialog_chrome(self, "licensesBrowserDialog")

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.panel = LicensesBrowserPanel(
            app=parent,
            license_service_provider=lambda: license_service,
            track_filter_id=track_filter_id,
            parent=self,
        )
        self.panel.close_requested.connect(self.accept)
        v.addWidget(self.panel)

    def __getattr__(self, name: str):
        panel = self.__dict__.get("panel")
        if panel is not None and hasattr(panel, name):
            return getattr(panel, name)
        raise AttributeError(name)


class LicenseeManagerDialog(QDialog):
    def __init__(self, catalog_service, parent=None):
        super().__init__(parent)
        self.catalog_service = catalog_service
        self.setWindowTitle("Manage Licensees")
        self.setModal(True)
        self.resize(720, 560)
        self.setMinimumSize(640, 500)
        _apply_standard_dialog_chrome(self, "licenseeManagerDialog")

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.setMinimumHeight(320)
        self._reload()

        btn_add = QPushButton("Add")
        btn_ren = QPushButton("Rename")
        btn_del = QPushButton("Delete")
        btn_close = QPushButton("Close")
        btn_add.clicked.connect(self._add)
        btn_ren.clicked.connect(self._rename)
        btn_del.clicked.connect(self._delete)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(14)
        _add_standard_dialog_header(
            v,
            self,
            title="Manage Licensees",
            subtitle="Keep the stored licensee directory tidy by adding new names or renaming and removing entries that are no longer in use.",
            help_topic_id="licenses",
        )

        list_box, list_layout = _create_standard_section(
            self,
            "Stored Licensees",
            "Licensees with linked license records cannot be deleted until those records are removed or reassigned.",
        )
        list_layout.addWidget(self.list, 1)

        list_layout.addWidget(
            _create_action_button_grid(
                self,
                [btn_add, btn_ren, btn_del, btn_close],
                columns=2,
            )
        )
        v.addWidget(list_box, 1)

        btn_close.clicked.connect(self.accept)

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
            mutation = lambda: self.catalog_service.rename_licensee(
                it.data(Qt.UserRole), text.strip()
            )
            if app is not None and hasattr(app, "_run_snapshot_history_action"):
                app._run_snapshot_history_action(
                    action_label=f"Rename Licensee: {old}",
                    action_type="licensee.rename",
                    entity_type="Licensee",
                    entity_id=it.data(Qt.UserRole),
                    payload={
                        "licensee_id": it.data(Qt.UserRole),
                        "old_name": old,
                        "new_name": text.strip(),
                    },
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

        if hasattr(self.app, "_run_snapshot_history_action"):
            self.app._run_snapshot_history_action(
                action_label=f"Delete Unused Albums: {len(album_ids)}",
                action_type="catalog.albums_delete",
                entity_type="Album",
                entity_id="batch",
                payload={"album_ids": album_ids, "count": len(album_ids)},
                mutation=lambda: self.catalog_service.delete_albums(album_ids),
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

        if hasattr(self.app, "_run_snapshot_history_action"):
            self.app._run_snapshot_history_action(
                action_label=f"Purge Unused Albums: {len(album_ids)}",
                action_type="catalog.albums_purge",
                entity_type="Album",
                entity_id="batch",
                payload={"album_ids": album_ids, "count": len(album_ids)},
                mutation=lambda: self.catalog_service.delete_albums(album_ids),
            )
        else:
            self.catalog_service.delete_albums(album_ids)

        self.reload()
        self._after_mutation()


class _CatalogLicenseesPane(_CatalogManagerPaneBase):
    def __init__(self, app, parent=None):
        super().__init__(app, parent)

        self.scroll_area, self.scroll_content, root = _create_scrollable_dialog_content(
            self, page=self
        )
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        add_group = QGroupBox("Add Licensee")
        add_layout = QGridLayout(add_group)
        add_layout.setContentsMargins(14, 18, 14, 14)
        add_layout.setHorizontalSpacing(12)
        add_layout.setVerticalSpacing(10)
        name_label = QLabel("Name")
        name_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        name_label.setMinimumWidth(120)
        self.new_name_edit = QLineEdit()
        self.new_name_edit.setPlaceholderText("Enter a licensee name")
        self.new_name_edit.setClearButtonEnabled(True)
        self.new_name_edit.setMinimumWidth(360)
        self.add_btn = self._prepare_button(QPushButton("Add Licensee"), width=156)
        add_hint = self._make_info_label(
            "Licensees can be renamed later, but in-use licensees cannot be deleted."
        )
        add_layout.addWidget(name_label, 0, 0)
        add_layout.addWidget(self.new_name_edit, 0, 1)
        add_layout.addWidget(self.add_btn, 0, 2)
        add_layout.addWidget(add_hint, 1, 1, 1, 2)
        add_layout.setColumnStretch(1, 1)
        root.addWidget(add_group)

        list_group = QGroupBox("Stored Licensees")
        list_layout = QVBoxLayout(list_group)
        list_layout.setContentsMargins(14, 18, 14, 14)
        list_layout.setSpacing(12)

        self.summary_label = QLabel()
        list_layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Licensee", "Linked Licenses", "Status"])
        self._configure_table(self.table)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        list_layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.refresh_btn = self._prepare_button(QPushButton("Refresh"))
        self.rename_btn = self._prepare_button(QPushButton("Rename Selected"), width=156)
        self.delete_btn = self._prepare_button(QPushButton("Delete Selected"), width=160)
        buttons.addWidget(self.refresh_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.rename_btn)
        buttons.addWidget(self.delete_btn)
        list_layout.addLayout(buttons)

        root.addWidget(list_group, 1)

        self.add_btn.clicked.connect(self._add)
        self.new_name_edit.returnPressed.connect(self._add)
        self.refresh_btn.clicked.connect(self.reload)
        self.rename_btn.clicked.connect(self._rename)
        self.delete_btn.clicked.connect(self._delete)
        self.table.itemSelectionChanged.connect(self._update_button_states)

        self.reload()

    def reload(self):
        if self.catalog_service is None:
            self.table.setRowCount(0)
            self.summary_label.setText("Open a profile to manage stored licensees.")
            self._update_button_states()
            return
        licensees = self.catalog_service.list_licensees_with_usage()
        self.table.setRowCount(0)
        unused_count = 0
        for licensee in licensees:
            row = self.table.rowCount()
            self.table.insertRow(row)

            name_item = QTableWidgetItem(licensee.name)
            name_item.setData(Qt.UserRole, licensee.licensee_id)
            self.table.setItem(row, 0, name_item)

            count_item = QTableWidgetItem(str(licensee.license_count))
            count_item.setTextAlignment(Qt.AlignCenter)
            count_item.setData(Qt.UserRole, licensee.license_count)
            self.table.setItem(row, 1, count_item)

            is_unused = int(licensee.license_count) == 0
            if is_unused:
                unused_count += 1
            status_item = QTableWidgetItem("Unused" if is_unused else "In Use")
            status_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, status_item)

        self.summary_label.setText(
            f"{len(licensees)} stored licensee(s). {unused_count} currently have no linked license records."
        )
        self._update_button_states()

    def _current_selection(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        name_item = self.table.item(row, 0)
        count_item = self.table.item(row, 1)
        if name_item is None or count_item is None:
            return None
        return {
            "row": row,
            "licensee_id": int(name_item.data(Qt.UserRole)),
            "name": name_item.text(),
            "license_count": int(count_item.data(Qt.UserRole) or 0),
        }

    def _update_button_states(self):
        selection = self._current_selection()
        has_selection = selection is not None
        self.rename_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(bool(selection and selection["license_count"] == 0))

    def _add(self):
        if self.catalog_service is None:
            QMessageBox.warning(self, "Add Licensee", "Open a profile first.")
            return
        name = self.new_name_edit.text().strip()
        if not name:
            QMessageBox.information(self, "Missing Name", "Enter a licensee name first.")
            self.new_name_edit.setFocus(Qt.OtherFocusReason)
            return
        try:
            if hasattr(self.app, "_run_snapshot_history_action"):
                self.app._run_snapshot_history_action(
                    action_label=f"Add Licensee: {name}",
                    action_type="licensee.add",
                    entity_type="Licensee",
                    entity_id=name,
                    payload={"name": name},
                    mutation=lambda: self.catalog_service.ensure_licensee(name),
                )
            else:
                self.catalog_service.ensure_licensee(name)
        except Exception as e:
            QMessageBox.critical(self, "Add Licensee", str(e))
            return

        self.new_name_edit.clear()
        self.reload()
        self._after_mutation()

    def _rename(self):
        if self.catalog_service is None:
            QMessageBox.warning(self, "Rename Licensee", "Open a profile first.")
            return
        selection = self._current_selection()
        if selection is None:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Licensee",
            "New name:",
            text=selection["name"],
        )
        new_name = (new_name or "").strip()
        if not ok or not new_name:
            return
        try:
            if hasattr(self.app, "_run_snapshot_history_action"):
                self.app._run_snapshot_history_action(
                    action_label=f"Rename Licensee: {selection['name']}",
                    action_type="licensee.rename",
                    entity_type="Licensee",
                    entity_id=selection["licensee_id"],
                    payload={
                        "licensee_id": selection["licensee_id"],
                        "old_name": selection["name"],
                        "new_name": new_name,
                    },
                    mutation=lambda: self.catalog_service.rename_licensee(
                        selection["licensee_id"], new_name
                    ),
                )
            else:
                self.catalog_service.rename_licensee(selection["licensee_id"], new_name)
        except Exception as e:
            QMessageBox.critical(self, "Rename Licensee", str(e))
            return

        self.reload()
        self._after_mutation()

    def _delete(self):
        if self.catalog_service is None:
            QMessageBox.warning(self, "Delete Licensee", "Open a profile first.")
            return
        selection = self._current_selection()
        if selection is None:
            return
        if selection["license_count"] > 0:
            QMessageBox.warning(
                self,
                "In Use",
                f"“{selection['name']}” has {selection['license_count']} linked license record(s).\n"
                "Remove or reassign those licenses before deleting this licensee.",
            )
            return
        if (
            QMessageBox.question(
                self,
                "Delete Licensee",
                f"Delete “{selection['name']}”?\nThis cannot be undone.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        try:
            if hasattr(self.app, "_run_snapshot_history_action"):
                self.app._run_snapshot_history_action(
                    action_label=f"Delete Licensee: {selection['name']}",
                    action_type="licensee.delete",
                    entity_type="Licensee",
                    entity_id=selection["licensee_id"],
                    payload={
                        "licensee_id": selection["licensee_id"],
                        "name": selection["name"],
                    },
                    mutation=lambda: self.catalog_service.delete_licensee(selection["licensee_id"]),
                )
            else:
                self.catalog_service.delete_licensee(selection["licensee_id"])
        except Exception as e:
            QMessageBox.critical(self, "Delete Licensee", str(e))
            return

        self.reload()
        self._after_mutation()


class CatalogManagersPanel(QWidget):
    TAB_ORDER = ("artists", "albums", "licensees")

    def __init__(self, app, *, initial_tab: str = "artists", parent=None):
        super().__init__(parent or app)
        self.app = app
        self.setObjectName("catalogManagersPanel")
        _apply_standard_widget_chrome(self, "catalogManagersPanel")

        self.setStyleSheet(
            _compose_widget_stylesheet(
                self,
                """
                QDialog#catalogManagersDialog QLabel#catalogTitle,
                QWidget#catalogManagersPanel QLabel#catalogTitle {
                    font-size: 18px;
                    font-weight: 600;
                }
                QDialog#catalogManagersDialog QLabel#catalogSubtitle,
                QWidget#catalogManagersPanel QLabel#catalogSubtitle {
                    color: #5f6b76;
                }
                QDialog#catalogManagersDialog QGroupBox,
                QWidget#catalogManagersPanel QGroupBox {
                    font-weight: 600;
                    margin-top: 10px;
                }
                QDialog#catalogManagersDialog QGroupBox::title,
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

        subtitle_label = QLabel(
            "Manage stored artists and album names here, and keep the legacy license archive separate but still accessible."
        )
        subtitle_label.setObjectName("catalogSubtitle")
        subtitle_label.setWordWrap(True)
        root.addWidget(subtitle_label)

        self.tabs = QTabWidget()
        self.artists_tab = _CatalogArtistsPane(app, self)
        self.albums_tab = _CatalogAlbumsPane(app, self)
        self.licensees_tab = _CatalogLicenseesPane(app, self)
        self.tabs.addTab(self.artists_tab, "Artists")
        self.tabs.addTab(self.albums_tab, "Albums")
        self.tabs.addTab(self.licensees_tab, "Legacy Licensees")
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
        self.licensees_tab.reload()


class CatalogManagersDialog(QDialog):
    TAB_ORDER = ("artists", "albums", "licensees")

    def __init__(self, app, *, initial_tab: str = "artists", parent=None):
        super().__init__(parent or app)
        self.app = app
        self.setObjectName("catalogManagersDialog")
        self.setWindowTitle("Catalog Managers")
        self.setModal(True)
        self.setMinimumSize(1100, 720)
        self.resize(1180, 760)
        _apply_standard_dialog_chrome(self, "catalogManagersDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.panel = CatalogManagersPanel(app, initial_tab=initial_tab, parent=self)
        self.tabs = self.panel.tabs
        self.artists_tab = self.panel.artists_tab
        self.albums_tab = self.panel.albums_tab
        self.licensees_tab = self.panel.licensees_tab
        root.addWidget(self.panel, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, Qt.Horizontal, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self.focus_tab(initial_tab)


class App(QMainWindow):
    startupReady = Signal()
    BASE_HEADERS = list(DEFAULT_BASE_HEADERS)
    TOP_CHROME_DOCK_GAP = 5

    def __init__(self, *, startup_feedback: StartupFeedbackProtocol | None = None):
        super().__init__()
        self.setObjectName("mainWindow")
        configure_qt_application_identity(self)
        self._startup_feedback = startup_feedback
        self._startup_feedback_completed = False
        self._post_ready_startup_tasks_scheduled = False
        self.startupReady.connect(self.complete_startup_feedback)
        self.startupReady.connect(self._schedule_post_ready_startup_tasks)

        self.settings = QSettings(str(settings_path()), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)
        self.logger = logging.getLogger("ISRCManager")
        self.trace_logger = logging.getLogger("ISRCManager.trace")
        self._logging_configured = False
        self._bootstrap_log_buffer: list[tuple[str, int, str, dict | None]] = []
        self.storage_layout = resolve_app_storage_layout(settings=self.settings)
        self.storage_migration_service = StorageMigrationService(
            self.storage_layout,
            settings=self.settings,
            reporter=self._log_event,
        )
        self._report_startup_phase(StartupPhase.RESOLVING_STORAGE)
        startup_root = self._reconcile_startup_storage_root()
        self._apply_storage_layout(active_data_root=startup_root)

        self.sqlite_connection_factory = SQLiteConnectionFactory()
        self.database_session = DatabaseSessionService(self.sqlite_connection_factory)
        self.profile_store = ProfileStoreService(self.database_dir)
        self.profile_workflows = ProfileWorkflowService(self.database_dir, self.profile_store)
        self.database_maintenance = DatabaseMaintenanceService(self.backups_dir)
        self.background_tasks = BackgroundTaskManager(self)
        self.background_tasks.task_state_changed.connect(self._on_background_task_state_changed)
        self.background_service_factory = BackgroundAppServiceFactory(
            connection_factory=self.sqlite_connection_factory,
            data_root=self.data_root,
            history_dir=self.history_dir,
            backups_dir=self.backups_dir,
        )
        self.schema_service = None

        # default DB file (used if no previous DB is selected)
        DB_PATH = self.database_dir / "default.db"

        # --- Logging setup (daily human log + structured trace log) ---
        self._configure_logging()
        self._log_event(
            "app.start",
            "Application start",
            data_dir=self.data_root,
            log_path=self.log_path,
            trace_log_path=self.trace_log_path,
        )
        self.background_service_factory.configure(settings_path=self.settings.fileName())

        self._report_startup_phase(StartupPhase.INITIALIZING_SETTINGS)
        self.identity = self._load_identity()
        self.theme_settings = self._load_theme_settings()
        self.blob_icon_settings = default_blob_icon_settings()
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
        self.help_dialog = None
        self.auto_snapshot_timer = QTimer(self)
        self.auto_snapshot_timer.setSingleShot(False)
        self.auto_snapshot_timer.timeout.connect(self._on_auto_snapshot_timer)
        self._last_auto_snapshot_marker = None
        self._last_history_budget_warning_signature = None
        self._suspend_layout_history = False
        self._suspend_dock_state_sync = False
        self._is_closing = False
        self._is_restoring_workspace_layout = False
        self._workspace_layout_restore_pending = True
        self._workspace_layout_restore_scheduled = False
        self._workspace_layout_restore_complete = False
        self._restored_main_dock_state = False
        self._dock_state_save_timer = None
        self._window_geometry_save_timer = None
        self._header_layout_signals_bound = False
        self._col_hint_signal_bound = False
        self._row_hint_signal_bound = False
        self.track_service = None
        self.settings_reads = None
        self.settings_mutations = None
        self.blob_icon_settings_service = None
        self.gs1_settings_service = None
        self.gs1_integration_service = None
        self.catalog_service = None
        self.catalog_reads = None
        self.license_service = None
        self.license_migration_service = None
        self.profile_kv = None
        self.custom_field_definitions = None
        self.custom_field_values = None
        self.xml_export_service = None
        self.xml_import_service = None
        self.release_service = None
        self.authenticity_key_service = None
        self.authenticity_manifest_service = None
        self.audio_watermark_service = None
        self.audio_authenticity_service = None
        self.audio_tag_service = None
        self.tagged_audio_export_service = None
        self.exchange_service = None
        self.quality_service = None
        self.release_browser_dialog = None
        self._explicit_row_filter_track_ids = None
        self._background_write_lock = None
        self._report_startup_phase(StartupPhase.OPENING_PROFILE_DB)
        self.open_database(last_db)

        try:
            movable = self.settings.value(
                f"{self._table_settings_prefix()}/columns_movable", False, bool
            )
        except Exception:
            movable = False

        self._report_startup_phase(StartupPhase.FINALIZING_INTERFACE)
        build_main_window_shell(self, last_db=last_db, movable=bool(movable))
        self.tabifiedDockWidgetActivated.connect(
            lambda *_args: self._schedule_main_dock_state_save()
        )
        self._ensure_persistent_workspace_dock_shells()

        self._apply_saved_view_preferences(apply_workspace_panel_visibility=False)

        self.resize(1280, 800)
        self._refresh_history_actions()
        app_instance = QApplication.instance()
        if app_instance is not None:
            app_instance.installEventFilter(self)
        self._ensure_widget_object_names(self)
        self._apply_theme()
        self._refresh_catalog_ui_in_background(unique_key="catalog.ui.startup")

    def _report_startup_phase(
        self,
        phase: StartupPhase,
        message_override: str | None = None,
    ) -> None:
        controller = getattr(self, "_startup_feedback", None)
        if controller is None or getattr(self, "_startup_feedback_completed", False):
            return
        set_phase = getattr(controller, "set_phase", None)
        if callable(set_phase):
            try:
                set_phase(StartupPhase(phase), message_override)
                return
            except Exception:
                pass
        set_status = getattr(controller, "set_status", None)
        if callable(set_status):
            try:
                set_status(str(message_override or startup_phase_label(StartupPhase(phase))))
            except Exception:
                pass

    @staticmethod
    def _drain_qt_events() -> None:
        app = QApplication.instance()
        process_events = getattr(app, "processEvents", None) if app is not None else None
        if callable(process_events):
            process_events()

    def _suspend_startup_feedback(self) -> None:
        controller = getattr(self, "_startup_feedback", None)
        suspend = getattr(controller, "suspend", None)
        if callable(suspend):
            try:
                suspend()
            except Exception:
                pass
        self._drain_qt_events()

    def _resume_startup_feedback(self) -> None:
        controller = getattr(self, "_startup_feedback", None)
        resume = getattr(controller, "resume", None)
        if callable(resume):
            try:
                resume()
            except Exception:
                pass
        self._drain_qt_events()

    def _run_startup_message_box(
        self,
        *,
        title: str,
        icon,
        text: str,
        configure=None,
    ):
        self._suspend_startup_feedback()
        try:
            parent = self if self.isVisible() else None
            message_box = QMessageBox(parent)
            if hasattr(message_box, "setWindowTitle"):
                message_box.setWindowTitle(title)
            if hasattr(message_box, "setIcon"):
                message_box.setIcon(icon)
            if hasattr(message_box, "setText"):
                message_box.setText(text)
            if hasattr(message_box, "setWindowModality"):
                message_box.setWindowModality(Qt.ApplicationModal)
            if callable(configure):
                configure(message_box)
            elif hasattr(message_box, "addButton"):
                ok_button = message_box.addButton("OK", QMessageBox.AcceptRole)
                if hasattr(message_box, "setDefaultButton"):
                    message_box.setDefaultButton(ok_button)
            message_box.exec()
            return message_box
        finally:
            self._resume_startup_feedback()

    def complete_startup_feedback(self) -> None:
        controller = getattr(self, "_startup_feedback", None)
        if controller is None or getattr(self, "_startup_feedback_completed", False):
            return
        self._startup_feedback_completed = True
        try:
            set_phase = getattr(controller, "set_phase", None)
            if callable(set_phase):
                try:
                    set_phase(StartupPhase.READY)
                except Exception:
                    pass
            finish = getattr(controller, "finish", None)
            if callable(finish):
                finish(self)
        finally:
            self._startup_feedback = None

    def _schedule_post_ready_startup_tasks(self) -> None:
        if self._post_ready_startup_tasks_scheduled:
            return
        self._post_ready_startup_tasks_scheduled = True
        QTimer.singleShot(0, self._run_post_ready_startup_tasks)

    def _run_post_ready_startup_tasks(self) -> None:
        self._update_add_data_generated_fields()
        self._offer_settings_on_first_launch_if_pending()

    def _offer_settings_on_first_launch_if_pending(self) -> None:
        setting_key = "startup/offer_open_settings_on_first_launch_pending"
        if not self.settings.value(setting_key, False, bool):
            return

        open_settings_button = None

        def _configure(message_box):
            nonlocal open_settings_button
            open_settings_button = message_box.addButton("Open Settings", QMessageBox.AcceptRole)
            skip_button = message_box.addButton("Not Now", QMessageBox.RejectRole)
            if hasattr(message_box, "setDefaultButton"):
                message_box.setDefaultButton(open_settings_button or skip_button)

        message_box = self._run_startup_message_box(
            title="Open Settings",
            icon=QMessageBox.Question,
            text=(
                "This looks like the first time the app has been opened here.\n\n"
                "Do you want to open Application Settings now? You can skip this and keep the defaults."
            ),
            configure=_configure,
        )
        self.settings.setValue(setting_key, False)
        self.settings.sync()

        if (
            message_box is not None
            and hasattr(message_box, "clickedButton")
            and message_box.clickedButton() is open_settings_button
        ):
            self.open_settings_dialog()

    def _apply_storage_layout(self, *, active_data_root: str | Path | None = None) -> None:
        self.storage_layout = resolve_app_storage_layout(
            settings=self.settings,
            active_data_root=active_data_root,
        )
        self.storage_migration_service = StorageMigrationService(
            self.storage_layout,
            settings=self.settings,
            reporter=self._log_event,
        )
        self.data_root = self.storage_layout.data_root
        self.database_dir = self.storage_layout.database_dir
        self.exports_dir = self.storage_layout.exports_dir
        self.logs_dir = self.storage_layout.logs_dir
        self.backups_dir = self.storage_layout.backups_dir
        self.history_dir = self.storage_layout.history_dir
        self.help_dir = self.storage_layout.help_dir

        for directory in (
            self.data_root,
            self.database_dir,
            self.exports_dir,
            self.logs_dir,
            self.backups_dir,
            self.history_dir,
            self.help_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        today_stamp = datetime.now().strftime("%Y-%m-%d")
        self.log_path = self.logs_dir / f"isrc_manager_{today_stamp}.log"
        self.trace_log_path = self.logs_dir / f"isrc_manager_trace_{today_stamp}.jsonl"
        self.help_file_path = self.help_dir / "isrc_catalog_manager_help.html"
        factory = getattr(self, "background_service_factory", None)
        if factory is not None:
            factory.configure(
                data_root=self.data_root,
                history_dir=self.history_dir,
                backups_dir=self.backups_dir,
                settings_path=self.settings.fileName(),
            )

    def _reconcile_startup_storage_root(self) -> Path:
        inspection = self.storage_migration_service.inspect()
        preferred_root = self.storage_layout.preferred_data_root.resolve()
        if self.storage_layout.portable:
            self._log_event(
                "storage.migration.startup",
                "Portable mode is active; storage migration is skipped",
                data_root=preferred_root,
            )
            return preferred_root

        if inspection.preferred_state == PREFERRED_STATE_VALID_COMPLETE:
            result = self.storage_migration_service.migrate()
            self._log_event(
                "storage.migration.startup",
                "Adopted verified preferred app-data root during startup",
                action=result.action,
                source_root=result.source_root,
                target_root=result.target_root,
            )
            return result.target_root.resolve()

        if inspection.preferred_state == PREFERRED_STATE_RESUMABLE_STAGE:
            result = self.storage_migration_service.migrate()
            self._log_event(
                "storage.migration.startup",
                "Resumed staged app-data migration during startup",
                action=result.action,
                source_root=result.source_root,
                target_root=result.target_root,
            )
            return result.target_root.resolve()

        if inspection.preferred_state == PREFERRED_STATE_CONFLICT:
            self._log_event(
                "storage.migration.startup_conflict",
                "Preferred app-data root contains conflicting content; keeping the current managed root",
                level=logging.WARNING,
                preferred_root=preferred_root,
                conflict_items=list(inspection.conflict_items),
            )
            if inspection.legacy_root is not None and inspection.legacy_items:
                return inspection.legacy_root.resolve()
            return preferred_root

        if inspection.legacy_root is None or not inspection.legacy_items:
            self._log_event(
                "storage.migration.startup",
                "No legacy app-data migration is needed on startup",
                active_root=preferred_root,
                preferred_state=inspection.preferred_state,
            )
            return preferred_root

        if inspection.deferred and self.storage_layout.active_data_root == inspection.legacy_root:
            self._log_event(
                "storage.migration.startup_deferred",
                "Startup is honoring the deferred legacy app-data root",
                legacy_root=inspection.legacy_root,
            )
            return inspection.legacy_root.resolve()

        lines = [
            "A legacy app-data folder was found.",
            "",
            f"Current folder: {inspection.legacy_root}",
            f"New folder: {self.storage_layout.preferred_data_root}",
            "",
            "The migration will copy app-owned profiles, history, backups, logs, exports, help files, and managed media into the new app folder.",
            "Legacy data will stay in place until you choose to remove it later.",
            "",
            "Migrate to the new app folder now?",
        ]
        migrate_button = None
        keep_button = None

        def _configure_message_box(message_box) -> None:
            nonlocal migrate_button, keep_button
            migrate_button = message_box.addButton("Migrate Now", QMessageBox.AcceptRole)
            keep_button = message_box.addButton(
                "Keep Current Folder For Now",
                QMessageBox.RejectRole,
            )
            if hasattr(message_box, "setDefaultButton"):
                message_box.setDefaultButton(migrate_button)

        message_box = self._run_startup_message_box(
            title="App Data Migration",
            icon=QMessageBox.Warning,
            text="\n".join(lines),
            configure=_configure_message_box,
        )

        if message_box.clickedButton() is keep_button:
            self.storage_migration_service.defer(inspection.legacy_root)
            self._log_event(
                "storage.migration.deferred",
                "Startup app-data migration was deferred by the user",
                legacy_root=inspection.legacy_root,
                preferred_root=preferred_root,
            )
            return inspection.legacy_root.resolve()

        try:
            result = self.storage_migration_service.migrate()
        except Exception as exc:
            self.storage_migration_service.defer(inspection.legacy_root)
            self._log_event(
                "storage.migration.startup_failed",
                "Startup app-data migration could not be completed; continuing with the legacy root",
                level=logging.WARNING,
                legacy_root=inspection.legacy_root,
                preferred_root=preferred_root,
                error=str(exc),
            )
            self._run_startup_message_box(
                title="App Data Migration",
                icon=QMessageBox.Warning,
                text=(
                    "The app-data migration could not be completed.\n\n"
                    f"{exc}\n\nThe app will continue to use the current folder for now."
                ),
            )
            return inspection.legacy_root.resolve()

        self._run_startup_message_box(
            title="App Data Migration",
            icon=QMessageBox.Information,
            text=(
                f"App-owned data was {result.action} successfully.\n\n"
                f"Items: {', '.join(result.copied_items)}"
            ),
        )
        self._log_event(
            "storage.migration.startup",
            "Startup selected the preferred app-data root after migration",
            action=result.action,
            source_root=result.source_root,
            target_root=result.target_root,
        )
        return result.target_root.resolve()

    def _maybe_run_storage_layout_migration(self) -> Path:
        return self._reconcile_startup_storage_root()

    def _run_storage_layout_migration(self):
        if hasattr(self, "background_tasks") and self.background_tasks.has_running_tasks():
            raise RuntimeError(
                "Finish any running background tasks before migrating app-owned storage."
            )

        inspection = self.storage_migration_service.inspect()
        source_root = (
            inspection.legacy_root.resolve() if inspection.legacy_root is not None else None
        )
        previous_current_path = str(getattr(self, "current_db_path", "") or "").strip()
        previous_was_open = getattr(self, "conn", None) is not None

        if previous_was_open:
            self._prepare_for_background_db_task()
            self._close_database_connection()

        try:
            result = self.storage_migration_service.migrate()
        except Exception:
            if previous_was_open and previous_current_path and Path(previous_current_path).exists():
                self.open_database(previous_current_path)
                self._reload_profiles_list(select_path=previous_current_path)
            raise

        source_root = result.source_root.resolve()
        target_root = result.target_root.resolve()

        self._apply_storage_layout(active_data_root=target_root)
        self._configure_logging()

        if previous_was_open and previous_current_path:
            reopened_path = previous_current_path
            try:
                relative = Path(previous_current_path).resolve().relative_to(source_root)
            except Exception:
                relative = None
            if relative is not None:
                migrated_path = (target_root / relative).resolve()
                if not migrated_path.exists():
                    raise RuntimeError(
                        "The active profile did not appear in the migrated app-data folder."
                    )
                reopened_path = str(migrated_path)
            self.open_database(reopened_path)
            self._reload_profiles_list(select_path=reopened_path)
        else:
            self._configure_background_runtime()

        self._log_event(
            "storage.migration",
            "Completed app-owned storage recovery",
            source_root=source_root,
            target_root=target_root,
            action=result.action,
            migrated_items=list(result.copied_items),
        )
        return result

    def closeEvent(self, e):
        if hasattr(self, "background_tasks") and self.background_tasks.has_running_tasks():
            titles = self.background_tasks.active_task_titles()
            summary = "\n".join(f"- {title}" for title in titles[:8])
            QMessageBox.warning(
                self,
                "Background Tasks Running",
                "Wait for the current background task(s) to finish before closing the app.\n\n"
                + summary,
            )
            e.ignore()
            return
        self._is_closing = True
        self._save_main_window_geometry(sync=False)
        self._store_workspace_panel_visibility_preferences(sync=False)
        self._save_main_dock_state(sync=False)
        self.settings.sync()
        self.logger.info("Settings synced to disk")
        super().closeEvent(e)

    def _configure_logging(self) -> None:
        app_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
        trace_formatter = _JsonLogFormatter()
        self._logging_configured = False

        for logger in (self.logger, self.trace_logger):
            logger.setLevel(logging.INFO)
            logger.propagate = False
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

        app_handler = RotatingFileHandler(
            self.log_path, maxBytes=1_000_000, backupCount=7, encoding="utf-8"
        )
        app_handler.setLevel(logging.INFO)
        app_handler.setFormatter(app_formatter)
        self.logger.addHandler(app_handler)

        trace_handler = RotatingFileHandler(
            self.trace_log_path,
            maxBytes=2_000_000,
            backupCount=10,
            encoding="utf-8",
        )
        trace_handler.setLevel(logging.INFO)
        trace_handler.setFormatter(trace_formatter)
        self.trace_logger.addHandler(trace_handler)

        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.WARNING)
        stream_handler.setFormatter(app_formatter)
        self.logger.addHandler(stream_handler)
        self._logging_configured = True
        self._flush_bootstrap_log_buffer()

    def _flush_bootstrap_log_buffer(self) -> None:
        if not self._logging_configured:
            return
        buffered_records = list(self._bootstrap_log_buffer)
        self._bootstrap_log_buffer.clear()
        for record_type, level, message, extra in buffered_records:
            if record_type == "trace":
                self.trace_logger.log(level, message, extra=extra or {})
            else:
                self.logger.log(level, message)

    @staticmethod
    def _normalize_log_value(value):
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, (list, tuple, set)):
            return [App._normalize_log_value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): App._normalize_log_value(val) for key, val in value.items()}
        return value

    def _trace_context(self, **fields) -> dict:
        payload = {
            "profile": (
                Path(self.current_db_path).name if getattr(self, "current_db_path", "") else None
            ),
            "db_path": str(self.current_db_path) if getattr(self, "current_db_path", "") else None,
        }
        payload.update(fields)
        return {
            key: self._normalize_log_value(value)
            for key, value in payload.items()
            if value not in (None, "", [], {}, ())
        }

    def _log_trace(
        self, event: str, *, message: str | None = None, level: int = logging.INFO, **fields
    ) -> None:
        if not hasattr(self, "trace_logger") or self.trace_logger is None:
            return
        extra = {"event": event}
        extra.update(self._trace_context(**fields))
        if not getattr(self, "_logging_configured", False):
            self._bootstrap_log_buffer.append(("trace", level, message or event, extra))
            return
        self.trace_logger.log(level, message or event, extra=extra)

    def _log_event(self, event: str, message: str, *, level: int = logging.INFO, **fields) -> None:
        summary_parts = []
        for key, value in fields.items():
            if value in (None, "", [], {}, ()):
                continue
            normalized = self._normalize_log_value(value)
            if isinstance(normalized, list):
                normalized = ", ".join(str(item) for item in normalized)
            summary_parts.append(f"{key}={normalized}")
        line = message if not summary_parts else f"{message} | " + " | ".join(summary_parts)
        if not getattr(self, "_logging_configured", False):
            self._bootstrap_log_buffer.append(("app", level, line, None))
            self._log_trace(event, message=message, level=level, **fields)
            return
        self.logger.log(level, line)
        self._log_trace(event, message=message, level=level, **fields)

    def _create_action(
        self,
        text: str,
        *,
        slot=None,
        toggled_slot=None,
        standard_key=None,
        shortcuts: tuple[str, ...] | list[str] | None = None,
        checkable: bool = False,
        checked: bool | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if checkable:
            action.setCheckable(True)
            if checked is not None:
                action.setChecked(bool(checked))
        if standard_key is not None:
            action.setShortcuts(QKeySequence.keyBindings(standard_key))
        elif shortcuts:
            action.setShortcuts([QKeySequence(seq) for seq in shortcuts])
        if slot is not None:
            action.triggered.connect(slot)
        if toggled_slot is not None:
            action.toggled.connect(toggled_slot)
        self.addAction(action)
        return action

    def _app_version_text(self) -> str:
        for package_name in ("isrc-catalog-manager", APP_NAME):
            try:
                return metadata.version(package_name)
            except metadata.PackageNotFoundError:
                continue
            except Exception:
                break
        return "2.0.0"

    def _help_html(self) -> str:
        return render_help_html(
            "ISRC Catalog Manager",
            self._app_version_text(),
            theme=self._effective_theme_settings(),
        )

    def _ensure_help_file(self) -> Path:
        self.help_dir.mkdir(parents=True, exist_ok=True)
        html_text = self._help_html()
        try:
            current_text = self.help_file_path.read_text(encoding="utf-8")
        except Exception:
            current_text = None
        if current_text != html_text:
            self.help_file_path.write_text(html_text, encoding="utf-8")
        return self.help_file_path

    def open_help_dialog(self, topic_id: str | None = None, parent=None):
        self._ensure_help_file()
        if isinstance(parent, QDialog) and parent.isModal():
            dlg = HelpContentsDialog(self, parent=parent)
            dlg.setWindowModality(Qt.WindowModal)
            dlg.refresh_help_source()
            dlg.open_topic(topic_id or "overview", focus_search=False)
            dlg.exec()
            return
        if self.help_dialog is None:
            self.help_dialog = HelpContentsDialog(self, parent=self)
        self.help_dialog.refresh_help_source()
        self.help_dialog.open_topic(topic_id or "overview", focus_search=False)
        self.help_dialog.show()
        self.help_dialog.raise_()
        self.help_dialog.activateWindow()

    def _open_local_path(self, path: str | Path, action_label: str = "Open") -> bool:
        target = Path(path)
        if not target.exists():
            QMessageBox.warning(self, action_label, f"Path does not exist:\n{target}")
            return False
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            QMessageBox.warning(self, action_label, f"Could not open:\n{target}")
            return False
        return True

    def _available_log_files(self) -> list[Path]:
        if not self.logs_dir.exists():
            return []
        return sorted(
            (
                path
                for path in self.logs_dir.iterdir()
                if path.is_file() and (".log" in path.name or ".jsonl" in path.name)
            ),
            key=lambda item: (item.stat().st_mtime, item.name.lower()),
            reverse=True,
        )

    def _read_log_for_viewer(self, path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"Could not read log file:\n{exc}"

        if ".jsonl" not in path.name:
            return text

        rendered = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                rendered.append(raw)
                continue

            timestamp = payload.get("timestamp", "?")
            level = str(payload.get("level", "INFO")).upper()
            event = payload.get("event", payload.get("logger", "trace"))
            message = payload.get("message", "")
            rendered.append(f"[{timestamp}] {level} {event}")
            if message:
                rendered.append(f"  {message}")

            for key, value in payload.items():
                if key in {"timestamp", "level", "logger", "event", "message"}:
                    continue
                rendered.append(f"  {key}: {value}")
            rendered.append("")

        return "\n".join(rendered).strip() or "(No trace entries found.)"

    def _history_snapshot_summary(self, conn=None) -> str:
        connection = conn if conn is not None else self.conn
        if connection is None:
            return "History unavailable"
        try:
            count_row = connection.execute("SELECT COUNT(*) FROM HistorySnapshots").fetchone()
            total = int(count_row[0] or 0) if count_row else 0
            latest = connection.execute(
                "SELECT label, created_at FROM HistorySnapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not latest:
                return "0 snapshot(s)"
            latest_label = latest[0] or "Unnamed snapshot"
            latest_time = latest[1] or "unknown time"
            return f"{total} snapshot(s), latest: {latest_label} @ {latest_time}"
        except Exception:
            return "Snapshot history unavailable"

    def _custom_value_field_column_name(self, conn=None) -> str | None:
        connection = conn if conn is not None else self.conn
        if connection is None:
            return None
        try:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(CustomFieldValues)").fetchall()
            }
        except Exception:
            return None
        if "field_def_id" in columns:
            return "field_def_id"
        if "custom_field_id" in columns:
            return "custom_field_id"
        return None

    def _count_orphaned_custom_values(self, conn=None) -> int:
        connection = conn if conn is not None else self.conn
        if connection is None:
            return 0
        field_column = self._custom_value_field_column_name(conn=connection)
        if field_column is None:
            return 0
        row = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM CustomFieldValues cfv
            LEFT JOIN CustomFieldDefs cfd ON cfd.id = cfv.{field_column}
            LEFT JOIN Tracks t ON t.id = cfv.track_id
            WHERE cfd.id IS NULL OR t.id IS NULL
            """
        ).fetchone()
        return int(row[0] or 0) if row else 0

    def _legacy_promoted_field_repair_candidates(self, conn=None):
        connection = conn if conn is not None else self.conn
        if connection is None:
            return []
        return LegacyPromotedFieldRepairService(connection).inspect_candidates()

    def _preview_diagnostics_repair(self, repair_key: str, check: dict | None = None) -> str:
        if repair_key == "storage_layout_migrate":
            inspection = self.storage_migration_service.inspect()
            if inspection.legacy_root is None and inspection.preferred_state not in (
                PREFERRED_STATE_VALID_COMPLETE,
                PREFERRED_STATE_RESUMABLE_STAGE,
            ):
                return "No legacy app-owned storage was detected, so no migration is needed."
            if inspection.preferred_state == PREFERRED_STATE_VALID_COMPLETE:
                return (
                    "This will adopt the verified app-owned data already present in the preferred app folder "
                    "and refresh startup settings to use it automatically."
                )
            if inspection.preferred_state == PREFERRED_STATE_RESUMABLE_STAGE:
                return (
                    "This will resume the preserved staged app-data migration, verify the staged databases, "
                    "and promote the staged root into the preferred app folder."
                )
            if inspection.preferred_state == PREFERRED_STATE_CONFLICT:
                conflict_text = (
                    "\n".join(f"- {item}" for item in inspection.conflict_items[:10])
                    or "- (unknown)"
                )
                return (
                    "The preferred app folder contains conflicting managed content that cannot be overwritten "
                    "automatically.\n\n"
                    f"Conflicting items:\n{conflict_text}"
                )
            return (
                "This will copy app-owned storage into the preferred app folder, rewrite known internal "
                "history and snapshot paths, verify copied databases, and keep the legacy folder intact.\n\n"
                f"Legacy folder: {inspection.legacy_root}\n"
                f"Preferred folder: {self.storage_layout.preferred_data_root}\n"
                f"Items to migrate: {', '.join(inspection.legacy_items)}"
            )
        if repair_key == "schema_migrate":
            return "This will re-run the schema bootstrap and migrations for the current profile."
        if repair_key == "custom_value_cleanup":
            count = None
            if check is not None:
                count = check.get("orphan_count")
            if count is None:
                count = self._count_orphaned_custom_values()
            return (
                f"This will delete {int(count)} orphaned custom value row(s) that no longer point to a valid "
                "track or custom field definition."
            )
        if repair_key == "legacy_promoted_field_repair":
            candidates = self._legacy_promoted_field_repair_candidates()
            if not candidates:
                return "No legacy custom fields currently overlap promoted default columns."
            eligible = [candidate for candidate in candidates if candidate.eligible]
            blocked = [candidate for candidate in candidates if not candidate.eligible]
            lines = [
                (
                    f"- {candidate.field_name}: "
                    f"{candidate.non_empty_value_count} stored value(s), "
                    f"{candidate.blank_target_count} blank target row(s), "
                    f"{len(candidate.conflicting_track_ids)} conflicting track(s)"
                )
                for candidate in candidates[:10]
            ]
            summary = [
                "This will merge safe legacy custom-field values into their promoted default columns, then remove the redundant custom field definitions and values.",
                "",
                f"Safe candidates: {len(eligible)}",
                f"Blocked by conflicting values: {len(blocked)}",
            ]
            if lines:
                summary.extend(["", "Fields:", *lines])
            if blocked:
                summary.extend(
                    [
                        "",
                        "Fields with conflicting values will be skipped so no existing default-column data is overwritten silently.",
                    ]
                )
            return "\n".join(summary)
        if repair_key == "history_reconcile":
            issue_count = 0
            if check is not None:
                issue_count = int(check.get("issue_count") or 0)
            return (
                f"This will reconcile {issue_count} history and recovery issue(s), repair stale current pointers, "
                "restore missing snapshots and backups from archived history artifacts when possible, re-register "
                "orphaned snapshot or backup files that still have metadata, and rebuild missing backup artifacts "
                "from live files when the current data is intact. Irrecoverable references will be left in place "
                "and reported as unresolved so the history trail is not silently erased."
            )
        raise ValueError(f"Unknown diagnostics repair: {repair_key}")

    def _run_diagnostics_repair(self, repair_key: str, check: dict | None = None) -> str:
        if repair_key == "storage_layout_migrate":
            result = self._run_storage_layout_migration()
            return (
                f"App-owned data was {result.action} into the preferred storage layout.\n\n"
                f"Source: {result.source_root}\n"
                f"Target: {result.target_root}\n"
                f"Items: {', '.join(result.copied_items)}"
            )

        if repair_key == "schema_migrate":
            self.init_db()
            self.migrate_schema()
            self.active_custom_fields = self.load_active_custom_fields()
            self.refresh_table_preserve_view()
            self.populate_all_comboboxes()
            self._audit("REPAIR", "Schema", ref_id=self.current_db_path, details="schema_migrate")
            self._audit_commit()
            self._log_event(
                "diagnostics.repair.schema_migrate",
                "Diagnostics repair applied",
                repair_key=repair_key,
                status="ok",
            )
            return "Schema bootstrap and migration completed successfully."

        if repair_key == "custom_value_cleanup":
            field_column = self._custom_value_field_column_name()
            if field_column is None:
                raise RuntimeError("Could not determine the custom field reference column.")
            before_count = self._count_orphaned_custom_values()
            with self.conn:
                self.conn.execute(
                    f"""
                    DELETE FROM CustomFieldValues
                    WHERE NOT EXISTS (
                        SELECT 1 FROM CustomFieldDefs cfd WHERE cfd.id = CustomFieldValues.{field_column}
                    )
                    OR NOT EXISTS (
                        SELECT 1 FROM Tracks t WHERE t.id = CustomFieldValues.track_id
                    )
                    """
                )
            after_count = self._count_orphaned_custom_values()
            removed = max(0, before_count - after_count)
            self._audit(
                "REPAIR",
                "CustomFieldValues",
                ref_id="orphans",
                details=f"removed={removed}; remaining={after_count}",
            )
            self._audit_commit()
            self._log_event(
                "diagnostics.repair.custom_value_cleanup",
                "Diagnostics repair applied",
                repair_key=repair_key,
                removed=removed,
                remaining=after_count,
            )
            return f"Removed {removed} orphaned custom value row(s)."

        if repair_key == "legacy_promoted_field_repair":
            if self.conn is None:
                raise RuntimeError("Open a profile first.")
            result = LegacyPromotedFieldRepairService(self.conn).repair_candidates()
            self.active_custom_fields = self.load_active_custom_fields()
            self.refresh_table_preserve_view()
            self.populate_all_comboboxes()
            self._audit(
                "REPAIR",
                "CustomFieldDefs",
                ref_id="legacy_promoted_field_repair",
                details=(
                    f"repaired={len(result.repaired_field_names)};"
                    f" skipped={len(result.skipped_field_names)};"
                    f" merged_values={result.merged_value_count}"
                ),
            )
            self._audit_commit()
            self._log_event(
                "diagnostics.repair.legacy_promoted_field_repair",
                "Diagnostics repair applied",
                repair_key=repair_key,
                repaired=len(result.repaired_field_names),
                skipped=len(result.skipped_field_names),
                merged_values=result.merged_value_count,
            )
            summary_parts = []
            if result.repaired_field_names:
                summary_parts.append(
                    "Repaired fields:\n" + "\n".join(sorted(result.repaired_field_names))
                )
            else:
                summary_parts.append("No safe legacy default-column custom fields required repair.")
            if result.skipped_field_names:
                summary_parts.append(
                    "Skipped because conflicting default-column values already exist:\n"
                    + "\n".join(sorted(result.skipped_field_names))
                )
            summary_parts.append(
                f"Merged {result.merged_value_count} blank default-column value(s) and removed "
                f"{result.removed_field_count} redundant custom field definition(s)."
            )
            return "\n\n".join(summary_parts)

        if repair_key == "history_reconcile":
            if self.history_manager is None:
                raise RuntimeError("Open a profile first.")
            result = self.history_manager.repair_recovery_state()
            self._refresh_history_actions()
            self._audit(
                "REPAIR", "History", ref_id=self.current_db_path, details="history_reconcile"
            )
            self._audit_commit()
            self._log_event(
                "diagnostics.repair.history_reconcile",
                "History diagnostics repair applied",
                repair_key=repair_key,
                changes=len(result.changes),
                unresolved=len(result.unresolved),
            )
            summary_parts = []
            if result.changes:
                summary_parts.append("\n".join(result.changes))
            else:
                summary_parts.append("No registry changes were needed.")
            if result.unresolved:
                summary_parts.append("Unresolved:\n" + "\n".join(result.unresolved))
            return "\n\n".join(summary_parts)

        raise ValueError(f"Unknown diagnostics repair: {repair_key}")

    def _build_diagnostics_report(
        self,
        *,
        conn=None,
        schema_service=None,
        current_db_path: str | Path | None = None,
        data_root: str | Path | None = None,
        logs_dir: str | Path | None = None,
        track_service=None,
        license_service=None,
        history_manager=None,
        database_maintenance=None,
        storage_migration_service=None,
        app_version: str | None = None,
        status_callback=None,
    ) -> dict[str, object]:
        connection = conn if conn is not None else self.conn
        current_path = str(
            current_db_path if current_db_path is not None else getattr(self, "current_db_path", "")
        ).strip()
        current_data_root = Path(data_root if data_root is not None else self.data_root)
        current_logs_dir = Path(logs_dir if logs_dir is not None else self.logs_dir)
        active_track_service = track_service if track_service is not None else self.track_service
        active_license_service = (
            license_service if license_service is not None else self.license_service
        )
        active_history_manager = (
            history_manager if history_manager is not None else self.history_manager
        )
        active_database_maintenance = (
            database_maintenance if database_maintenance is not None else self.database_maintenance
        )
        active_storage_migration_service = (
            storage_migration_service
            if storage_migration_service is not None
            else self.storage_migration_service
        )
        active_schema_service = schema_service
        if active_schema_service is None and connection is not None:
            active_schema_service = DatabaseSchemaService(connection, data_root=current_data_root)

        def _set_status(message: str) -> None:
            if callable(status_callback):
                status_callback(str(message))

        db_version = 0
        schema_version_text = "Unknown"
        if active_schema_service is not None:
            try:
                db_version = int(active_schema_service.get_db_version())
                schema_version_text = str(db_version)
            except Exception:
                db_version = 0

        environment = {
            "App version": str(app_version or self._app_version_text()),
            "Schema version": schema_version_text,
            "Current profile": Path(current_path).name if current_path else "(none)",
            "Database path": current_path or "(none)",
            "Data folder": str(current_data_root),
            "Log folder": str(current_logs_dir),
            "Restore points": self._history_snapshot_summary(conn=connection),
            "Platform": f"{platform.system()} {platform.release()}",
            "Python": platform.python_version(),
        }

        checks = []

        def add_check(
            title: str,
            status: str,
            summary: str,
            details: str,
            *,
            repair_key: str | None = None,
            repair_label: str | None = None,
            orphan_count: int | None = None,
            **extra,
        ) -> None:
            checks.append(
                {
                    "title": title,
                    "status": status,
                    "summary": summary,
                    "details": details,
                    "repair_key": repair_key,
                    "repair_label": repair_label,
                    "orphan_count": orphan_count,
                    **extra,
                }
            )

        _set_status("Inspecting storage layout...")
        try:
            storage_inspection = active_storage_migration_service.inspect()
            active_layout = active_storage_migration_service.layout
            if active_layout.portable:
                add_check(
                    "Storage layout",
                    "ok",
                    "Portable mode is active.",
                    "Portable mode keeps app-owned data beside the executable, so no app-data migration is required.",
                )
            elif storage_inspection.legacy_root is None or not storage_inspection.legacy_items:
                add_check(
                    "Storage layout",
                    "ok",
                    "App-owned data already uses the preferred app folder layout.",
                    f"Active data root: {active_layout.active_data_root}\nPreferred data root: {active_layout.preferred_data_root}",
                )
            else:
                current_root = active_layout.active_data_root
                preferred_state_text = (
                    ", ".join(storage_inspection.preferred_items)
                    if storage_inspection.preferred_items
                    else "(empty)"
                )
                summary = "Legacy app-owned storage was detected."
                status = "warning"
                if storage_inspection.preferred_state == PREFERRED_STATE_VALID_COMPLETE:
                    summary = "Verified app-owned data already exists in the preferred app folder."
                elif storage_inspection.preferred_state == PREFERRED_STATE_RESUMABLE_STAGE:
                    summary = "A staged app-data migration can be resumed."
                elif storage_inspection.preferred_state == PREFERRED_STATE_CONFLICT:
                    summary = "The preferred app folder contains conflicting managed content."
                    status = "error"
                add_check(
                    "Storage layout",
                    status,
                    summary,
                    "\n".join(
                        [
                            f"Legacy root: {storage_inspection.legacy_root}",
                            f"Active root: {current_root}",
                            f"Preferred root: {active_layout.preferred_data_root}",
                            f"Legacy items: {', '.join(storage_inspection.legacy_items)}",
                            f"Preferred state: {storage_inspection.preferred_state}",
                            f"Preferred-root contents: {preferred_state_text}",
                            (
                                "Conflict items: "
                                + ", ".join(storage_inspection.conflict_items[:10])
                                if storage_inspection.conflict_items
                                else ""
                            ),
                            "",
                            "Use the migration action to collect managed app data into the preferred app folder without deleting the legacy copy.",
                        ]
                    ),
                    repair_key="storage_layout_migrate",
                    repair_label="Migrate App Data",
                )
        except Exception as exc:
            add_check(
                "Storage layout",
                "error",
                "Storage layout could not be inspected.",
                f"An exception occurred while checking the app-data layout:\n{exc}",
                repair_key="storage_layout_migrate",
                repair_label="Migrate App Data",
            )

        _set_status("Checking schema version...")
        if db_version == SCHEMA_TARGET:
            add_check(
                "Schema version",
                "ok",
                f"Database is at schema {db_version}.",
                f"Current user_version: {db_version}\nExpected schema target: {SCHEMA_TARGET}\n\nThe active profile matches the current app schema target.",
            )
        else:
            level = "warning" if db_version < SCHEMA_TARGET else "error"
            add_check(
                "Schema version",
                level,
                f"Expected schema {SCHEMA_TARGET}, found {db_version}.",
                f"Current user_version: {db_version}\nExpected schema target: {SCHEMA_TARGET}\n\nThis profile should be migrated before relying on the latest features.",
                repair_key="schema_migrate",
                repair_label="Run Schema Migration",
            )

        _set_status("Inspecting schema layout...")
        try:
            table_names = (
                {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if connection is not None
                else set()
            )
            required_tables = {
                "Tracks",
                "Artists",
                "Albums",
                "TrackArtists",
                "CustomFieldDefs",
                "CustomFieldValues",
                "Licenses",
                "Licensees",
                "HistoryEntries",
                "HistoryHead",
                "HistoryBackups",
                "HistorySnapshots",
                "app_kv",
            }
            missing_tables = sorted(required_tables - table_names)

            track_columns = (
                {row[1] for row in connection.execute("PRAGMA table_info(Tracks)").fetchall()}
                if connection is not None and "Tracks" in table_names
                else set()
            )
            required_track_columns = {
                "id",
                "isrc",
                "isrc_compact",
                "db_entry_date",
                "audio_file_path",
                "audio_file_mime_type",
                "audio_file_size_bytes",
                "track_title",
                "catalog_number",
                "album_art_path",
                "album_art_mime_type",
                "album_art_size_bytes",
                "main_artist_id",
                "buma_work_number",
                "album_id",
                "release_date",
                "track_length_sec",
                "iswc",
                "upc",
                "genre",
            }
            missing_columns = sorted(required_track_columns - track_columns)

            if not missing_tables and not missing_columns:
                add_check(
                    "Schema layout",
                    "ok",
                    "Required tables and promoted columns are present.",
                    "All expected core tables exist, and the Tracks table includes the current promoted standard columns and media fields.",
                )
            else:
                details = [
                    "The current database layout is missing expected schema elements.",
                    "",
                    f"Missing tables: {', '.join(missing_tables) if missing_tables else '(none)'}",
                    f"Missing Tracks columns: {', '.join(missing_columns) if missing_columns else '(none)'}",
                ]
                add_check(
                    "Schema layout",
                    "error",
                    "Database layout is incomplete for the current app version.",
                    "\n".join(details),
                    repair_key="schema_migrate",
                    repair_label="Repair Schema Layout",
                )
        except Exception as exc:
            add_check(
                "Schema layout",
                "error",
                "Schema layout could not be inspected.",
                f"An exception occurred while reading table metadata:\n{exc}",
            )

        _set_status("Running SQLite integrity checks...")
        try:
            if active_database_maintenance is None or not current_path:
                raise RuntimeError("No active profile is open.")
            result = active_database_maintenance.verify_integrity(current_path)
            status = "ok" if str(result).strip().lower() == "ok" else "error"
            add_check(
                "SQLite integrity",
                status,
                str(result),
                f"PRAGMA integrity_check returned:\n{result}",
            )
        except Exception as exc:
            add_check(
                "SQLite integrity",
                "error",
                "Integrity check failed to run.",
                f"An exception occurred while running PRAGMA integrity_check:\n{exc}",
            )

        _set_status("Checking foreign-key consistency...")
        try:
            fk_rows = (
                connection.execute("PRAGMA foreign_key_check").fetchall()
                if connection is not None
                else []
            )
            if not fk_rows:
                add_check(
                    "Foreign-key consistency",
                    "ok",
                    "0 issue(s) detected.",
                    "PRAGMA foreign_key_check returned no rows.",
                )
            else:
                preview = "\n".join(
                    f"table={row[0]}, rowid={row[1]}, parent={row[2]}, fk_index={row[3]}"
                    for row in fk_rows[:25]
                )
                add_check(
                    "Foreign-key consistency",
                    "error",
                    f"{len(fk_rows)} issue(s) detected.",
                    f"PRAGMA foreign_key_check returned {len(fk_rows)} row(s).\n\n{preview}",
                )
        except Exception as exc:
            add_check(
                "Foreign-key consistency",
                "error",
                "Foreign-key validation failed to run.",
                f"An exception occurred while running PRAGMA foreign_key_check:\n{exc}",
            )

        _set_status("Checking custom-value integrity...")
        try:
            orphan_count = self._count_orphaned_custom_values(conn=connection)
            if orphan_count == 0:
                add_check(
                    "Custom-value integrity",
                    "ok",
                    "0 orphaned custom value row(s) detected.",
                    "Every CustomFieldValues row points to an existing field definition and track.",
                )
            else:
                add_check(
                    "Custom-value integrity",
                    "warning",
                    f"{orphan_count} orphaned custom value row(s) detected.",
                    "Some CustomFieldValues rows reference a deleted track or custom field definition.",
                    repair_key="custom_value_cleanup",
                    repair_label="Delete Orphaned Custom Values",
                    orphan_count=orphan_count,
                )
        except Exception as exc:
            add_check(
                "Custom-value integrity",
                "error",
                "Custom-value validation failed to run.",
                f"An exception occurred while checking CustomFieldValues:\n{exc}",
                repair_key="custom_value_cleanup",
                repair_label="Delete Orphaned Custom Values",
            )

        _set_status("Checking legacy default-column custom fields...")
        try:
            legacy_candidates = self._legacy_promoted_field_repair_candidates(conn=connection)
            if not legacy_candidates:
                add_check(
                    "Legacy default-column custom fields",
                    "ok",
                    "0 legacy custom/default overlaps detected.",
                    "No legacy custom field definitions currently overlap promoted default columns.",
                )
            else:
                details = []
                safe_count = 0
                for candidate in legacy_candidates:
                    if candidate.eligible:
                        safe_count += 1
                    details.append(
                        (
                            f"{candidate.field_name} "
                            f"(custom {candidate.custom_field_type} -> default {candidate.default_field_type}): "
                            f"{candidate.non_empty_value_count} stored value(s), "
                            f"{candidate.blank_target_count} blank target row(s), "
                            f"{len(candidate.conflicting_track_ids)} conflicting track(s)"
                        )
                    )
                details.append("")
                details.append(
                    "The repair action merges safe values into the promoted default column first and removes the redundant custom field only when no conflicting default-column data would be overwritten."
                )
                add_check(
                    "Legacy default-column custom fields",
                    "warning",
                    f"{len(legacy_candidates)} legacy custom/default overlap(s) detected.",
                    "\n".join(details),
                    repair_key="legacy_promoted_field_repair",
                    repair_label="Merge Into Default Columns",
                    safe_candidate_count=safe_count,
                    conflict_candidate_count=len(legacy_candidates) - safe_count,
                )
        except Exception as exc:
            add_check(
                "Legacy default-column custom fields",
                "error",
                "Legacy custom/default overlap inspection failed.",
                f"An exception occurred while checking for redundant promoted custom fields:\n{exc}",
                repair_key="legacy_promoted_field_repair",
                repair_label="Merge Into Default Columns",
            )

        _set_status("Checking managed files...")
        try:
            missing_files = []

            if connection is not None:
                media_rows = connection.execute(
                    """
                    SELECT id, track_title, audio_file_path
                    FROM Tracks
                    ORDER BY id
                    """
                ).fetchall()
                for track_id, track_title, audio_path in media_rows:
                    if audio_path:
                        resolved = (
                            active_track_service.resolve_media_path(audio_path)
                            if active_track_service
                            else Path(audio_path)
                        )
                        if resolved is not None and not resolved.exists():
                            missing_files.append(
                                f"Track #{track_id} '{track_title}': missing audio file -> {resolved}"
                            )

                album_art_rows = connection.execute(
                    """
                    SELECT id, title, album_art_path
                    FROM Albums
                    WHERE album_art_path IS NOT NULL AND album_art_path != ''
                    ORDER BY id
                    """
                ).fetchall()
                for album_id, album_title, art_path in album_art_rows:
                    resolved = (
                        active_track_service.resolve_media_path(art_path)
                        if active_track_service
                        else Path(art_path)
                    )
                    if resolved is not None and not resolved.exists():
                        missing_files.append(
                            f"Album #{album_id} '{album_title or 'Untitled Album'}': missing album art -> {resolved}"
                        )

                license_rows = connection.execute(
                    "SELECT id, filename, file_path FROM Licenses ORDER BY id"
                ).fetchall()
                for record_id, filename, file_path in license_rows:
                    if not file_path:
                        continue
                    resolved = (
                        active_license_service.resolve_path(file_path)
                        if active_license_service
                        else Path(file_path)
                    )
                    if not resolved.exists():
                        missing_files.append(
                            f"License #{record_id} '{filename or 'unnamed'}': missing file -> {resolved}"
                        )

            if not missing_files:
                add_check(
                    "Managed files",
                    "ok",
                    "0 missing managed file(s) detected.",
                    "All tracked audio files, album art files, and license PDFs that are referenced in the database are present on disk.",
                )
            else:
                preview = "\n".join(missing_files[:25])
                add_check(
                    "Managed files",
                    "warning",
                    f"{len(missing_files)} missing managed file(s) detected.",
                    f"Some database rows point to files that are no longer present on disk.\n\n{preview}",
                )
        except Exception as exc:
            add_check(
                "Managed files",
                "error",
                "Managed file validation failed to run.",
                f"An exception occurred while checking managed media and license files:\n{exc}",
            )

        _set_status("Inspecting history snapshots and backups...")
        try:
            if active_history_manager is None:
                raise RuntimeError("No active history manager")
            recovery_issues = active_history_manager.inspect_recovery_state()

            snapshot_issues = [
                issue
                for issue in recovery_issues
                if issue.issue_type
                in {
                    "missing_snapshot_artifact",
                    "missing_snapshot_archive",
                    "orphan_snapshot_file",
                    "dangling_snapshot_reference",
                }
            ]
            snapshot_details = "\n\n".join(
                "\n".join(
                    [issue.message]
                    + ([str(issue.path)] if issue.path else [])
                    + ([f"Details: {issue.details}"] if issue.details else [])
                )
                for issue in snapshot_issues[:20]
            )
            snapshot_total = len(active_history_manager.list_snapshots(limit=10_000))
            if not snapshot_issues:
                add_check(
                    "History snapshots",
                    "ok",
                    f"{snapshot_total} snapshot record(s) available.",
                    "Snapshot records and their registered artifacts are internally consistent.",
                )
            else:
                add_check(
                    "History snapshots",
                    "warning",
                    f"{len(snapshot_issues)} snapshot issue(s) detected.",
                    snapshot_details,
                    repair_key="history_reconcile",
                    repair_label="Repair History Artifacts",
                    orphan_count=len(snapshot_issues),
                )

            backup_issues = [
                issue
                for issue in recovery_issues
                if issue.issue_type
                in {
                    "missing_backup_file",
                    "missing_backup_history_artifact",
                    "orphan_backup_file",
                }
            ]
            backup_details = "\n\n".join(
                "\n".join([issue.message] + ([str(issue.path)] if issue.path else []))
                for issue in backup_issues[:20]
            )
            backup_total = len(active_history_manager.list_backups(limit=10_000))
            if not backup_issues:
                add_check(
                    "Backup artifacts",
                    "ok",
                    f"{backup_total} backup record(s) tracked.",
                    "Registered backup files and on-disk backup artifacts are internally consistent.",
                )
            else:
                add_check(
                    "Backup artifacts",
                    "warning",
                    f"{len(backup_issues)} backup issue(s) detected.",
                    backup_details,
                    repair_key="history_reconcile",
                    repair_label="Repair History Artifacts",
                    orphan_count=len(backup_issues),
                )

            invariant_issues = [
                issue for issue in recovery_issues if issue.issue_type == "stale_current_head"
            ]
            invariant_details = "\n\n".join(issue.message for issue in invariant_issues[:20])
            if not invariant_issues:
                add_check(
                    "History invariants",
                    "ok",
                    "History head and entry references are coherent.",
                    "The current history pointer resolves to a valid entry, and no repair is needed.",
                )
            else:
                add_check(
                    "History invariants",
                    "warning",
                    f"{len(invariant_issues)} history invariant issue(s) detected.",
                    invariant_details,
                    repair_key="history_reconcile",
                    repair_label="Repair History Artifacts",
                    orphan_count=len(invariant_issues),
                )

            total_history_issues = len(snapshot_issues) + len(backup_issues) + len(invariant_issues)
            if total_history_issues:
                for check in checks[-3:]:
                    check["issue_count"] = total_history_issues

            cleanup_service = HistoryStorageCleanupService(active_history_manager)
            retention_settings = (
                SettingsReadService(connection).load_history_retention_settings()
                if connection is not None
                else HistoryRetentionSettings()
            )
            budget_preview = cleanup_service.preview_storage_budget(retention_settings)
            mode_labels = {
                mode_key: label
                for mode_key, label, _description in ApplicationSettingsDialog.HISTORY_RETENTION_MODE_SPECS
            }
            reclaimable_bytes = sum(
                int(item.bytes_on_disk or 0) for item in budget_preview.candidate_items
            )
            budget_details = [
                f"Retention level: {mode_labels.get(retention_settings.retention_mode, retention_settings.retention_mode)}",
                (
                    "Automatic cleanup: enabled"
                    if retention_settings.auto_cleanup_enabled
                    else "Automatic cleanup: disabled"
                ),
                f"Storage budget: {self._human_size(budget_preview.budget_bytes)}",
                f"Current usage: {self._human_size(budget_preview.total_bytes)}",
                f"Keep latest auto snapshots: {retention_settings.auto_snapshot_keep_latest}",
                (
                    "Prune pre-restore safety copies: never"
                    if retention_settings.prune_pre_restore_copies_after_days <= 0
                    else (
                        "Prune pre-restore safety copies after "
                        f"{retention_settings.prune_pre_restore_copies_after_days} day(s)"
                    )
                ),
                f"Current safe cleanup candidates: {len(budget_preview.candidate_items)}",
                f"Safe reclaimable space: {self._human_size(reclaimable_bytes)}",
            ]
            if budget_preview.over_budget_bytes <= 0:
                add_check(
                    "History storage budget",
                    "ok",
                    "History storage is within the configured budget.",
                    "\n".join(budget_details),
                )
            else:
                warning_summary = f"History storage is over budget by {self._human_size(budget_preview.over_budget_bytes)}."
                if budget_preview.auto_cleanup_enabled and budget_preview.candidate_items:
                    warning_summary += " Safe cleanup candidates are available."
                elif budget_preview.protected_over_budget_items:
                    warning_summary += (
                        " Remaining space is protected by retained history or manual artifacts."
                    )
                budget_details.extend(
                    [
                        "",
                        f"Over budget by: {self._human_size(budget_preview.over_budget_bytes)}",
                    ]
                )
                add_check(
                    "History storage budget",
                    "warning",
                    warning_summary,
                    "\n".join(budget_details),
                )
        except Exception as exc:
            add_check(
                "History snapshots",
                "error",
                "Snapshot storage could not be inspected.",
                f"An exception occurred while checking history artifacts:\n{exc}",
                repair_key="history_reconcile",
                repair_label="Repair History Artifacts",
                orphan_count=0,
            )

        return {"environment": environment, "checks": checks}

    def _load_diagnostics_report_async(
        self,
        *,
        owner: QWidget | None = None,
        on_success=None,
        on_error=None,
        on_cancelled=None,
        on_finished=None,
        on_status=None,
    ):
        current_path = str(getattr(self, "current_db_path", "") or "").strip()
        if not current_path:
            report = self._build_diagnostics_report()
            if on_success is not None:
                on_success(report)
            if on_finished is not None:
                on_finished()
            return None

        app_version = self._app_version_text()
        data_root = self.data_root
        logs_dir = self.logs_dir
        storage_layout = self.storage_layout

        def _task(bundle, ctx):
            ctx.set_status("Loading diagnostics...")
            storage_service = StorageMigrationService(storage_layout, settings=bundle.settings)
            schema_service = DatabaseSchemaService(bundle.conn, data_root=data_root)
            return self._build_diagnostics_report(
                conn=bundle.conn,
                schema_service=schema_service,
                current_db_path=current_path,
                data_root=data_root,
                logs_dir=logs_dir,
                track_service=bundle.track_service,
                license_service=bundle.license_service,
                history_manager=bundle.history_manager,
                database_maintenance=bundle.database_maintenance,
                storage_migration_service=storage_service,
                app_version=app_version,
                status_callback=ctx.set_status,
            )

        return self._submit_background_bundle_task(
            title="Diagnostics",
            description="Loading diagnostics...",
            task_fn=_task,
            kind="read",
            unique_key="diagnostics.report",
            show_dialog=False,
            owner=owner or self,
            on_success=on_success,
            on_error=on_error,
            on_cancelled=on_cancelled,
            on_finished=on_finished,
            on_status=on_status,
        )

    def _run_bundle_diagnostics_repair(
        self,
        repair_key: str,
        check: dict | None = None,
        *,
        bundle,
        current_db_path: str,
        data_root: str | Path,
        status_callback=None,
    ) -> dict[str, object]:
        def _set_status(message: str) -> None:
            if callable(status_callback):
                status_callback(str(message))

        if repair_key == "schema_migrate":
            _set_status("Applying schema migration...")
            schema_service = DatabaseSchemaService(bundle.conn, data_root=data_root)
            schema_service.init_db()
            schema_service.migrate_schema()
            return {
                "result_text": "Schema bootstrap and migration completed successfully.",
                "post_action": "refresh_schema",
                "audit_entity": "Schema",
                "audit_ref_id": current_db_path,
                "audit_details": "schema_migrate",
                "log_event": "diagnostics.repair.schema_migrate",
                "log_message": "Diagnostics repair applied",
                "log_fields": {
                    "repair_key": repair_key,
                    "status": "ok",
                },
            }

        if repair_key == "custom_value_cleanup":
            _set_status("Deleting orphaned custom values...")
            field_column = self._custom_value_field_column_name(conn=bundle.conn)
            if field_column is None:
                raise RuntimeError("Could not determine the custom field reference column.")
            before_count = self._count_orphaned_custom_values(conn=bundle.conn)
            with bundle.conn:
                bundle.conn.execute(
                    f"""
                    DELETE FROM CustomFieldValues
                    WHERE NOT EXISTS (
                        SELECT 1 FROM CustomFieldDefs cfd WHERE cfd.id = CustomFieldValues.{field_column}
                    )
                    OR NOT EXISTS (
                        SELECT 1 FROM Tracks t WHERE t.id = CustomFieldValues.track_id
                    )
                    """
                )
            after_count = self._count_orphaned_custom_values(conn=bundle.conn)
            removed = max(0, before_count - after_count)
            return {
                "result_text": f"Removed {removed} orphaned custom value row(s).",
                "audit_entity": "CustomFieldValues",
                "audit_ref_id": "orphans",
                "audit_details": f"removed={removed}; remaining={after_count}",
                "log_event": "diagnostics.repair.custom_value_cleanup",
                "log_message": "Diagnostics repair applied",
                "log_fields": {
                    "repair_key": repair_key,
                    "removed": removed,
                    "remaining": after_count,
                },
            }

        if repair_key == "legacy_promoted_field_repair":
            _set_status("Merging legacy custom fields into default columns...")
            result = LegacyPromotedFieldRepairService(bundle.conn).repair_candidates()
            summary_parts = []
            if result.repaired_field_names:
                summary_parts.append(
                    "Repaired fields:\n" + "\n".join(sorted(result.repaired_field_names))
                )
            else:
                summary_parts.append("No safe legacy default-column custom fields required repair.")
            if result.skipped_field_names:
                summary_parts.append(
                    "Skipped because conflicting default-column values already exist:\n"
                    + "\n".join(sorted(result.skipped_field_names))
                )
            summary_parts.append(
                f"Merged {result.merged_value_count} blank default-column value(s) and removed "
                f"{result.removed_field_count} redundant custom field definition(s)."
            )
            return {
                "result_text": "\n\n".join(summary_parts),
                "post_action": "refresh_schema",
                "audit_entity": "CustomFieldDefs",
                "audit_ref_id": "legacy_promoted_field_repair",
                "audit_details": (
                    f"repaired={len(result.repaired_field_names)};"
                    f" skipped={len(result.skipped_field_names)};"
                    f" merged_values={result.merged_value_count}"
                ),
                "log_event": "diagnostics.repair.legacy_promoted_field_repair",
                "log_message": "Diagnostics repair applied",
                "log_fields": {
                    "repair_key": repair_key,
                    "repaired": len(result.repaired_field_names),
                    "skipped": len(result.skipped_field_names),
                    "merged_values": result.merged_value_count,
                },
            }

        if repair_key == "history_reconcile":
            if bundle.history_manager is None:
                raise RuntimeError("Open a profile first.")
            _set_status("Reconciling history artifacts...")
            result = bundle.history_manager.repair_recovery_state()
            summary_parts = []
            if result.changes:
                summary_parts.append("\n".join(result.changes))
            else:
                summary_parts.append("No registry changes were needed.")
            if result.unresolved:
                summary_parts.append("Unresolved:\n" + "\n".join(result.unresolved))
            return {
                "result_text": "\n\n".join(summary_parts),
                "post_action": "refresh_history",
                "audit_entity": "History",
                "audit_ref_id": current_db_path,
                "audit_details": "history_reconcile",
                "log_event": "diagnostics.repair.history_reconcile",
                "log_message": "History diagnostics repair applied",
                "log_fields": {
                    "repair_key": repair_key,
                    "changes": len(result.changes),
                    "unresolved": len(result.unresolved),
                },
            }

        raise ValueError(f"Unknown diagnostics repair: {repair_key}")

    def _apply_diagnostics_repair_result(
        self, repair_key: str, result: dict[str, object] | None
    ) -> str:
        payload = dict(result or {})
        post_action = str(payload.get("post_action") or "").strip()
        if post_action == "refresh_schema":
            if self.conn is not None:
                try:
                    self.conn.commit()
                except Exception:
                    pass
            self.active_custom_fields = self.load_active_custom_fields()
            self.refresh_table_preserve_view()
            self.populate_all_comboboxes()
        elif post_action == "refresh_history":
            self._refresh_history_actions()
            if self.history_dialog is not None and self.history_dialog.isVisible():
                self.history_dialog.refresh_data()

        audit_entity = str(payload.get("audit_entity") or "").strip()
        if audit_entity:
            self._audit(
                "REPAIR",
                audit_entity,
                ref_id=payload.get("audit_ref_id"),
                details=(
                    str(payload.get("audit_details"))
                    if payload.get("audit_details") is not None
                    else None
                ),
            )
            self._audit_commit()

        event_name = str(payload.get("log_event") or "").strip()
        if event_name:
            log_fields = dict(payload.get("log_fields") or {})
            self._log_event(
                event_name,
                str(payload.get("log_message") or "Diagnostics repair applied"),
                **log_fields,
            )

        return str(payload.get("result_text") or "")

    def _run_diagnostics_repair_async(
        self,
        repair_key: str,
        check: dict | None = None,
        *,
        owner: QWidget | None = None,
        on_success=None,
        on_error=None,
        on_cancelled=None,
        on_finished=None,
        on_status=None,
    ):
        current_path = str(getattr(self, "current_db_path", "") or "").strip()

        def _handle_success(result: dict[str, object]) -> None:
            result_text = self._apply_diagnostics_repair_result(repair_key, result)
            if on_success is not None:
                on_success(result_text)

        def _task(bundle, ctx):
            return self._run_bundle_diagnostics_repair(
                repair_key,
                check,
                bundle=bundle,
                current_db_path=current_path,
                data_root=self.data_root,
                status_callback=ctx.set_status,
            )

        return self._submit_background_bundle_task(
            title="Diagnostics Repair",
            description=(
                str((check or {}).get("repair_label") or "Applying diagnostics repair...")
            ),
            task_fn=_task,
            kind="write",
            unique_key=f"diagnostics.repair.{repair_key}",
            show_dialog=False,
            owner=owner or self,
            on_success=_handle_success,
            on_error=on_error,
            on_cancelled=on_cancelled,
            on_finished=on_finished,
            on_status=on_status,
        )

    def open_application_log_dialog(self):
        ApplicationLogDialog(self, parent=self).exec()

    def open_diagnostics_dialog(self):
        DiagnosticsDialog(self, parent=self).exec()

    def _init_services(self):
        self.schema_service = (
            DatabaseSchemaService(
                self.conn,
                logger=self.logger,
                audit_callback=self._audit,
                audit_commit=self._audit_commit,
                data_root=self.data_root,
            )
            if self.conn is not None
            else None
        )
        self.history_manager = (
            HistoryManager(
                self.conn,
                self.settings,
                self.current_db_path,
                self.history_dir,
                self.data_root,
                self.backups_dir,
            )
            if self.conn is not None and getattr(self, "current_db_path", None)
            else None
        )
        self.history_cleanup_service = (
            HistoryStorageCleanupService(self.history_manager)
            if self.history_manager is not None
            else None
        )
        self.track_service = (
            TrackService(self.conn, self.data_root) if self.conn is not None else None
        )
        self.settings_reads = SettingsReadService(self.conn) if self.conn is not None else None
        self.settings_mutations = (
            SettingsMutationService(self.conn, self.settings) if self.conn is not None else None
        )
        self.blob_icon_settings_service = (
            BlobIconSettingsService(self.conn) if self.conn is not None else None
        )
        self.gs1_settings_service = (
            GS1SettingsService(self.conn, self.settings, data_root=self.data_root)
            if self.conn is not None
            else None
        )
        self.catalog_service = CatalogAdminService(self.conn) if self.conn is not None else None
        self.catalog_reads = CatalogReadService(self.conn) if self.conn is not None else None
        self.license_service = (
            LicenseService(self.conn, self.data_root) if self.conn is not None else None
        )
        self.profile_kv = ProfileKVService(self.conn) if self.conn is not None else None
        self.custom_field_definitions = (
            CustomFieldDefinitionService(self.conn) if self.conn is not None else None
        )
        self.custom_field_values = (
            CustomFieldValueService(self.conn, self.custom_field_definitions, self.data_root)
            if self.conn is not None
            else None
        )
        self.xml_export_service = XMLExportService(self.conn) if self.conn is not None else None
        self.xml_import_service = (
            XMLImportService(self.conn, self.track_service, self.custom_field_definitions)
            if self.conn is not None
            else None
        )
        self.release_service = (
            ReleaseService(self.conn, self.data_root) if self.conn is not None else None
        )
        self.party_service = PartyService(self.conn) if self.conn is not None else None
        self.work_service = (
            WorkService(self.conn, party_service=self.party_service)
            if self.conn is not None
            else None
        )
        self.contract_service = (
            ContractService(self.conn, self.data_root, party_service=self.party_service)
            if self.conn is not None
            else None
        )
        self.license_migration_service = (
            LegacyLicenseMigrationService(
                self.conn,
                license_service=self.license_service,
                party_service=self.party_service,
                contract_service=self.contract_service,
                release_service=self.release_service,
                work_service=self.work_service,
            )
            if self.conn is not None
            and self.license_service is not None
            and self.party_service is not None
            and self.contract_service is not None
            else None
        )
        self.rights_service = RightsService(self.conn) if self.conn is not None else None
        self.asset_service = (
            AssetService(self.conn, self.data_root) if self.conn is not None else None
        )
        self.authenticity_key_service = (
            AuthenticityKeyService(
                self.conn,
                profile_kv=self.profile_kv,
                settings_root=Path(self.settings.fileName()).resolve().parent,
            )
            if self.conn is not None
            and self.profile_kv is not None
            and AUTHENTICITY_FEATURE_AVAILABLE
            and AuthenticityKeyService is not None
            else None
        )
        self.authenticity_manifest_service = (
            AuthenticityManifestService(
                self.conn,
                track_service=self.track_service,
                release_service=self.release_service,
                work_service=self.work_service,
                rights_service=self.rights_service,
                asset_service=self.asset_service,
                key_service=self.authenticity_key_service,
            )
            if self.conn is not None
            and self.track_service is not None
            and self.release_service is not None
            and self.work_service is not None
            and self.rights_service is not None
            and self.asset_service is not None
            and self.authenticity_key_service is not None
            and AUTHENTICITY_FEATURE_AVAILABLE
            and AuthenticityManifestService is not None
            else None
        )
        self.audio_watermark_service = (
            AudioWatermarkService()
            if self.conn is not None
            and AUTHENTICITY_FEATURE_AVAILABLE
            and AudioWatermarkService is not None
            else None
        )
        self.audio_conversion_service = AudioConversionService()
        self.audio_tag_service = AudioTagService() if self.conn is not None else None
        self.audio_authenticity_service = (
            AudioAuthenticityService(
                self.conn,
                key_service=self.authenticity_key_service,
                manifest_service=self.authenticity_manifest_service,
                watermark_service=self.audio_watermark_service,
                tag_service=self.audio_tag_service,
                app_version=self._app_version_text(),
            )
            if self.conn is not None
            and self.authenticity_key_service is not None
            and self.authenticity_manifest_service is not None
            and self.audio_watermark_service is not None
            and self.audio_tag_service is not None
            and AUTHENTICITY_FEATURE_AVAILABLE
            and AudioAuthenticityService is not None
            else None
        )
        self.repertoire_workflow_service = (
            RepertoireWorkflowService(self.conn) if self.conn is not None else None
        )
        self.global_search_service = (
            GlobalSearchService(self.conn) if self.conn is not None else None
        )
        self._refresh_audio_conversion_action_states()

    def _refresh_audio_conversion_action_states(self) -> None:
        conversion_available = bool(
            self.audio_conversion_service is not None and self.audio_conversion_service.is_available()
        )
        capabilities = (
            self.audio_conversion_service.capabilities()
            if conversion_available and self.audio_conversion_service is not None
            else None
        )
        managed_authentic_available = bool(
            self.track_service is not None
            and self.audio_authenticity_service is not None
            and capabilities is not None
            and capabilities.managed_targets
        )
        managed_lossy_available = bool(
            self.track_service is not None
            and capabilities is not None
            and capabilities.managed_lossy_targets
        )
        managed_available = bool(managed_authentic_available or managed_lossy_available)
        external_available = bool(
            conversion_available and capabilities is not None and capabilities.external_targets
        )
        if managed_available and self.audio_authenticity_service is not None:
            managed_message = (
                "Export managed audio derivatives. Lossless outputs stay on the "
                "watermark-authentic path; lossy outputs become tagged managed derivatives "
                "with derivative lineage."
            )
        elif managed_available:
            managed_message = (
                "Export managed lossy derivatives with catalog tags and derivative "
                "lineage. Lossless outputs stay unavailable until authenticity "
                "services are available in the open profile."
            )
        elif conversion_available and self.track_service is not None:
            managed_message = (
                "No supported managed derivative targets are available in this ffmpeg build."
            )
        else:
            managed_message = self._audio_conversion_unavailable_message() or "Open a profile first."
        external_message = (
            "Utility conversion only: no catalog metadata, no watermarking, and no managed derivative registration."
            if external_available
            else "External audio conversion utility requires ffmpeg on PATH."
        )
        for attr_name, enabled, status_tip in (
            ("convert_selected_audio_action", managed_available, managed_message),
            ("convert_external_audio_files_action", external_available, external_message),
        ):
            action = getattr(self, attr_name, None)
            if action is None:
                continue
            action.setEnabled(enabled)
            action.setStatusTip(status_tip)
            action.setToolTip(status_tip)
        self.relationship_explorer_service = (
            RelationshipExplorerService(self.conn) if self.conn is not None else None
        )
        self.tagged_audio_export_service = (
            TaggedAudioExportService(self.audio_tag_service)
            if self.audio_tag_service is not None
            else None
        )
        self.exchange_service = (
            ExchangeService(
                self.conn,
                self.track_service,
                self.release_service,
                self.custom_field_definitions,
                self.data_root,
            )
            if (
                self.conn is not None
                and self.track_service is not None
                and self.release_service is not None
                and self.custom_field_definitions is not None
            )
            else None
        )
        self.repertoire_exchange_service = (
            RepertoireExchangeService(
                self.conn,
                party_service=self.party_service,
                work_service=self.work_service,
                contract_service=self.contract_service,
                rights_service=self.rights_service,
                asset_service=self.asset_service,
                data_root=self.data_root,
            )
            if (
                self.conn is not None
                and self.party_service is not None
                and self.work_service is not None
                and self.contract_service is not None
                and self.rights_service is not None
                and self.asset_service is not None
            )
            else None
        )
        self.quality_service = (
            QualityDashboardService(
                self.conn,
                track_service=self.track_service,
                release_service=self.release_service,
                data_root=self.data_root,
            )
            if self.conn is not None
            and self.track_service is not None
            and self.release_service is not None
            else None
        )
        self.gs1_integration_service = (
            GS1IntegrationService(
                GS1MetadataRepository(self.conn),
                self.gs1_settings_service,
                self.track_service,
            )
            if self.conn is not None
            and self.gs1_settings_service is not None
            and self.track_service is not None
            else None
        )

    # -------------------------------------------------------------------------
    # Identity & Profiles
    # -------------------------------------------------------------------------
    def _load_identity(self):
        title = self.settings.value("identity/window_title", DEFAULT_WINDOW_TITLE, str)
        icon = self.settings.value("identity/icon_path", DEFAULT_ICON_PATH, str)
        return {"window_title": title, "icon_path": icon}

    def _apply_identity(self):
        self.setWindowTitle(self.identity.get("window_title") or DEFAULT_WINDOW_TITLE)
        icon_path = self.identity.get("icon_path") or ""
        if icon_path and Path(icon_path).exists():
            try:
                self.setWindowIcon(QIcon(icon_path))
            except Exception:
                pass

    @staticmethod
    def _theme_setting_defaults() -> dict[str, object]:
        return default_theme_settings()

    @classmethod
    def _theme_setting_keys(cls) -> tuple[str, ...]:
        return app_theme_setting_keys()

    @staticmethod
    def _normalize_theme_string(value) -> str:
        return normalize_app_theme_string(value)

    @classmethod
    def _normalize_theme_font_family(cls, value, fallback) -> str:
        return normalize_app_theme_font_family(value, fallback)

    @staticmethod
    def _normalize_theme_color(value) -> str:
        return normalize_app_theme_color(value)

    def _load_theme_settings(self) -> dict[str, object]:
        defaults = self._theme_setting_defaults()
        loaded: dict[str, object] = {}
        for key, default in defaults.items():
            settings_key = f"theme/{key}"
            if isinstance(default, bool):
                loaded[key] = self.settings.value(settings_key, default, bool)
            elif isinstance(default, int):
                loaded[key] = int(self.settings.value(settings_key, default, int))
            else:
                loaded[key] = (
                    self.settings.value(settings_key, default, str)
                    if self.settings.contains(settings_key)
                    else default
                )
        return self._normalize_theme_settings(loaded)

    def _normalize_theme_settings(self, values: dict[str, object] | None) -> dict[str, object]:
        return normalize_app_theme_settings(values)

    def _stored_theme_payload(self, values: dict[str, object] | None) -> dict[str, object]:
        payload = self._normalize_theme_settings(values)
        payload["selected_name"] = ""
        return payload

    def _sanitize_theme_library(
        self, library: dict[str, object] | None
    ) -> dict[str, dict[str, object]]:
        sanitized: dict[str, dict[str, object]] = {}
        for raw_name, raw_values in dict(library or {}).items():
            name = str(raw_name or "").strip()
            if not name:
                continue
            sanitized[name] = self._stored_theme_payload(dict(raw_values or {}))
        return sanitized

    def _load_theme_library(self) -> dict[str, dict[str, object]]:
        raw_value = self.settings.value("theme/library_json", "{}", str)
        try:
            parsed = json.loads(raw_value or "{}")
        except Exception:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        bundled = starter_theme_library()
        custom = self._sanitize_theme_library(parsed)
        custom = {name: values for name, values in custom.items() if name not in bundled}
        merged = dict(bundled)
        merged.update(custom)
        return merged

    def _save_theme_library(
        self, library: dict[str, object] | None
    ) -> dict[str, dict[str, object]]:
        sanitized = self._sanitize_theme_library(library)
        bundled_names = set(starter_theme_names())
        custom_only = {
            name: values for name, values in sanitized.items() if name not in bundled_names
        }
        self.settings.setValue("theme/library_json", json.dumps(custom_only, sort_keys=True))
        self.settings.sync()
        return sanitized

    @staticmethod
    def _color_relative_luminance(color_value: str) -> float:
        return theme_color_relative_luminance(color_value)

    @classmethod
    def _contrast_ratio(cls, fg_value: str, bg_value: str) -> float:
        return theme_contrast_ratio(fg_value, bg_value)

    @classmethod
    def _pick_contrasting_color(cls, bg_value: str) -> str:
        return pick_theme_contrasting_color(bg_value)

    @staticmethod
    def _shift_color(color_value: str, factor: int) -> str:
        return shift_theme_color(color_value, factor)

    def _effective_theme_settings(
        self, raw_values: dict[str, object] | None = None
    ) -> dict[str, object]:
        return build_effective_theme_settings(raw_values or self.theme_settings)

    def _save_theme_settings(self, values: dict[str, object]) -> dict[str, object]:
        normalized = self._normalize_theme_settings(values)
        for key in self._theme_setting_keys():
            self.settings.setValue(f"theme/{key}", normalized.get(key))
        self.settings.sync()
        self.theme_settings = normalized
        return normalized

    @staticmethod
    def _blob_icon_setting_defaults() -> dict[str, dict[str, object]]:
        return default_blob_icon_settings()

    def _load_blob_icon_settings(self) -> dict[str, dict[str, object]]:
        if self.blob_icon_settings_service is None:
            return self._blob_icon_setting_defaults()
        return normalize_blob_icon_settings(self.blob_icon_settings_service.load_settings())

    def _save_blob_icon_settings(
        self, values: dict[str, object] | None
    ) -> dict[str, dict[str, object]]:
        normalized = normalize_blob_icon_settings(values)
        if self.blob_icon_settings_service is not None:
            normalized = normalize_blob_icon_settings(
                self.blob_icon_settings_service.save_settings(normalized)
            )
        self.blob_icon_settings = normalized
        return normalized

    def _active_custom_qss(self) -> str:
        return str((self.theme_settings or {}).get("custom_qss") or "")

    def _build_theme_stylesheet(self, raw_values: dict[str, object] | None = None) -> str:
        return build_app_theme_stylesheet(raw_values or self.theme_settings)

    def _apply_theme(self, raw_values: dict[str, object] | None = None) -> None:
        app = QApplication.instance()
        if app is None:
            return
        effective = self._effective_theme_settings(raw_values)
        font = QFont(str(effective["font_family"]))
        font.setPointSize(int(effective["font_size"]))
        app.setFont(font)
        palette = build_app_theme_palette(raw_values or self.theme_settings)
        app.setPalette(palette)
        self.setPalette(palette)
        app.setStyleSheet(self._build_theme_stylesheet(raw_values))
        self._queue_top_chrome_boundary_refresh()

    def _prepare_theme_application_payload(
        self, raw_values: dict[str, object] | None = None
    ) -> dict[str, object]:
        normalized = self._normalize_theme_settings(raw_values)
        effective = self._effective_theme_settings(normalized)
        return {
            "normalized_theme": normalized,
            "effective_theme": effective,
            "stylesheet": build_app_theme_stylesheet(normalized),
        }

    def _apply_prepared_theme_payload(self, payload: dict[str, object]) -> None:
        app = QApplication.instance()
        if app is None:
            return
        effective = dict(payload.get("effective_theme") or self._effective_theme_settings())
        normalized = dict(payload.get("normalized_theme") or self.theme_settings or {})
        font = QFont(str(effective["font_family"]))
        font.setPointSize(int(effective["font_size"]))
        app.setFont(font)
        palette = build_app_theme_palette(normalized)
        app.setPalette(palette)
        self.setPalette(palette)
        app.setStyleSheet(
            str(payload.get("stylesheet") or self._build_theme_stylesheet(normalized))
        )
        self._queue_top_chrome_boundary_refresh()

    def _apply_theme_with_loading(
        self,
        raw_values: dict[str, object] | None = None,
        *,
        title: str = "Apply Theme",
        description: str = "Preparing updated theme styles...",
    ) -> None:
        prepared: dict[str, object] = {}
        failure: dict[str, TaskFailure] = {}
        cancelled = {"value": False}
        loop = QEventLoop(self)

        def _task(ctx):
            ctx.set_status("Preparing updated theme styles...")
            return self._prepare_theme_application_payload(raw_values)

        def _quit_loop() -> None:
            if loop.isRunning():
                loop.quit()

        task_id = self._submit_background_task(
            title=title,
            description=description,
            task_fn=_task,
            kind="read",
            unique_key="theme.apply.prepare",
            requires_profile=False,
            show_dialog=True,
            owner=self,
            on_success=lambda payload: (prepared.update(payload), _quit_loop()),
            on_error=lambda task_failure: (failure.setdefault("value", task_failure), _quit_loop()),
            on_cancelled=lambda: (cancelled.__setitem__("value", True), _quit_loop()),
        )
        if task_id is None:
            message = (
                failure.get("value").message if "value" in failure else "Task could not start."
            )
            raise RuntimeError(message)
        if not prepared and "value" not in failure and not cancelled["value"]:
            loop.exec()
        if "value" in failure:
            raise RuntimeError(failure["value"].message)
        if cancelled["value"]:
            return
        self._apply_prepared_theme_payload(prepared)

    def _apply_top_chrome_boundary(self) -> None:
        toolbar = getattr(self, "toolbar", None)
        if not isinstance(toolbar, QToolBar):
            return
        bottom_gap = int(self.TOP_CHROME_DOCK_GAP)
        margins = toolbar.contentsMargins()
        if (
            margins.left() != 0
            or margins.top() != 0
            or margins.right() != 0
            or margins.bottom() != bottom_gap
        ):
            toolbar.setContentsMargins(0, 0, 0, bottom_gap)
        toolbar.updateGeometry()
        toolbar.update()

    def _queue_top_chrome_boundary_refresh(self) -> None:
        timer = getattr(self, "_top_chrome_boundary_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._apply_top_chrome_boundary)
            self._top_chrome_boundary_timer = timer
        timer.start(0)

    def event(self, event):
        if event.type() == QEvent.LayoutRequest:
            self._schedule_main_dock_state_save()
        return super().event(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._queue_top_chrome_boundary_refresh()
        if self._workspace_layout_restore_pending and not self._workspace_layout_restore_scheduled:
            self._workspace_layout_restore_pending = False
            self._workspace_layout_restore_scheduled = True
            QTimer.singleShot(0, self._restore_workspace_layout_on_first_show)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._queue_top_chrome_boundary_refresh()
        self._schedule_main_window_geometry_save()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_main_window_geometry_save()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.WindowStateChange, QEvent.ActivationChange):
            self._queue_top_chrome_boundary_refresh()
        if event.type() == QEvent.WindowStateChange:
            self._schedule_main_window_geometry_save()

    @staticmethod
    def _root_object_name(widget: QWidget) -> str:
        name = (widget.objectName() or "").strip()
        if name:
            return name
        class_name = widget.metaObject().className() or "widget"
        base = class_name[0].lower() + class_name[1:] if class_name else "widget"
        widget.setObjectName(base)
        return base

    def _ensure_widget_object_names(self, root: QWidget | None) -> bool:
        return _ensure_qss_widget_object_names(root)

    @staticmethod
    def _repolish_widget_tree(root: QWidget | None) -> None:
        _repolish_qss_widget_tree(root)

    def _current_auto_snapshot_settings(self) -> tuple[bool, int]:
        if self.settings_reads is None:
            return DEFAULT_AUTO_SNAPSHOT_ENABLED, DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES
        snapshot_settings = self.settings_reads.load_auto_snapshot_settings()
        return bool(snapshot_settings.enabled), int(snapshot_settings.interval_minutes)

    def _current_history_retention_settings(self) -> HistoryRetentionSettings:
        if self.settings_reads is None:
            return HistoryRetentionSettings()
        return self.settings_reads.load_history_retention_settings()

    def open_history_cleanup_dialog(self):
        dialog = HistoryCleanupDialog(self, parent=self)
        dialog.exec()

    @staticmethod
    def _path_size_recursive(path: Path | None) -> int:
        if path is None:
            return 0
        try:
            candidate = Path(path)
        except Exception:
            return 0
        try:
            if candidate.is_dir():
                return sum(
                    file_path.stat().st_size
                    for file_path in candidate.rglob("*")
                    if file_path.is_file()
                )
            if candidate.exists():
                return int(candidate.stat().st_size)
        except Exception:
            return 0
        return 0

    def _estimate_history_snapshot_capture_bytes(self) -> int:
        if self.history_manager is None:
            return 0
        total = self._path_size_recursive(self.history_manager.db_path)
        managed_root = getattr(self.history_manager, "managed_root", None)
        if managed_root is not None:
            for dir_name in self.history_manager.MANAGED_DIRECTORIES:
                total += self._path_size_recursive(Path(managed_root) / dir_name)
        return total

    def _prepare_history_storage_for_projected_growth(
        self,
        *,
        trigger_label: str,
        additional_bytes: int,
        interactive: bool,
    ) -> bool:
        if self.history_manager is None or self.settings_reads is None:
            return True
        settings = self._current_history_retention_settings()
        cleanup_service = HistoryStorageCleanupService(self.history_manager)
        projection = cleanup_service.preview_storage_projection(
            settings,
            additional_bytes=max(0, int(additional_bytes or 0)),
        )
        if projection.budget_bytes <= 0 or projection.projected_over_budget_bytes <= 0:
            return True

        if (
            not interactive
            and settings.auto_cleanup_enabled
            and projection.candidate_items
            and projection.projected_over_budget_after_cleanup_bytes <= 0
        ):
            try:
                cleanup_result = cleanup_service.cleanup_selected(
                    [item.item_key for item in projection.candidate_items]
                )
            except HistoryCleanupBlockedError as exc:
                self.logger.warning(
                    "History cleanup could not make room before %s: %s",
                    trigger_label,
                    exc,
                )
                self.statusBar().showMessage(
                    f"Skipped {trigger_label}: history cleanup is blocked until diagnostics repairs are applied.",
                    7000,
                )
                return False
            except Exception as exc:
                self.logger.warning(
                    "Preemptive history cleanup failed before %s: %s",
                    trigger_label,
                    exc,
                )
                self.statusBar().showMessage(
                    f"Skipped {trigger_label}: the history cleanup policy could not make room safely.",
                    7000,
                )
                return False
            else:
                if cleanup_result.removed_item_keys:
                    self._refresh_history_actions()
                    if self.history_dialog is not None and self.history_dialog.isVisible():
                        self.history_dialog.refresh_data()
            return True

        if not interactive:
            message = (
                f"Skipped {trigger_label}: projected history usage "
                f"{self._human_size(projection.projected_total_bytes)} would exceed the "
                f"{self._human_size(projection.budget_bytes)} budget."
            )
            if projection.blocked_by_protected_items:
                message += (
                    " Remaining space is protected by retained history or manual restore points."
                )
            self.statusBar().showMessage(message, 7000)
            self.logger.info(
                "Skipped %s because projected history usage would exceed the budget",
                trigger_label,
            )
            return False

        details = [
            (
                f"This action is estimated to add about {self._human_size(projection.additional_bytes)} "
                f"of history data."
            ),
            (
                f"Current usage: {self._human_size(projection.current_total_bytes)} of "
                f"{self._human_size(projection.budget_bytes)}."
            ),
            (f"Projected usage: {self._human_size(projection.projected_total_bytes)}."),
        ]
        if projection.auto_cleanup_enabled and projection.reclaimable_bytes > 0:
            details.append(
                f"Current automatic cleanup policy can reclaim about {self._human_size(projection.reclaimable_bytes)}."
            )
        elif not projection.auto_cleanup_enabled:
            details.append(
                "Automatic cleanup is disabled for this profile, so no space will be reclaimed automatically."
            )
        if projection.blocked_by_protected_items:
            details.append(
                "Even after safe automatic cleanup, the profile would still be over budget because the remaining items are protected by retained history or manual restore points."
            )
        else:
            details.append(
                "The profile would cross the storage budget before the next cleanup pass."
            )
        details.append("Continue anyway, or review History Cleanup first?")

        message_box = QMessageBox(self)
        message_box.setIcon(QMessageBox.Warning)
        message_box.setWindowTitle("History Storage Budget")
        message_box.setText("\n\n".join(details))
        continue_btn = message_box.addButton("Continue", QMessageBox.AcceptRole)
        cleanup_btn = message_box.addButton("Open Cleanup", QMessageBox.ActionRole)
        cancel_btn = message_box.addButton(QMessageBox.Cancel)
        message_box.setDefaultButton(continue_btn)
        message_box.exec()
        clicked = message_box.clickedButton()
        if clicked is cleanup_btn:
            self.open_history_cleanup_dialog()
            return False
        if clicked is cancel_btn:
            return False
        return True

    def _enforce_history_storage_budget(
        self,
        *,
        trigger_label: str,
        interactive: bool = False,
    ) -> None:
        if self.history_manager is None or self.settings_reads is None:
            return
        cleanup_service = HistoryStorageCleanupService(self.history_manager)
        settings = self._current_history_retention_settings()
        try:
            result = cleanup_service.enforce_storage_budget(settings)
        except HistoryCleanupBlockedError as exc:
            self.logger.warning("History cleanup is blocked during %s: %s", trigger_label, exc)
            if interactive:
                QMessageBox.warning(
                    self,
                    "History Storage",
                    "History cleanup is currently blocked until diagnostics repairs are applied.\n\n"
                    + str(exc),
                )
            return
        except Exception as exc:
            self.logger.warning(
                "History budget enforcement failed during %s: %s", trigger_label, exc
            )
            if interactive:
                QMessageBox.warning(
                    self,
                    "History Storage",
                    f"Could not enforce the history storage policy:\n{exc}",
                )
            return

        if result.removed_item_keys:
            self._refresh_history_actions()
            if self.history_dialog is not None and self.history_dialog.isVisible():
                self.history_dialog.refresh_data()
            self.statusBar().showMessage(
                f"History cleanup removed {len(result.removed_item_keys)} item(s) after {trigger_label}.",
                5000,
            )

        if result.over_budget_bytes <= 0:
            self._last_history_budget_warning_signature = None
            return

        signature = (
            str(trigger_label),
            int(result.total_bytes or 0) // (1024 * 1024),
            int(result.budget_bytes or 0) // (1024 * 1024),
            bool(result.blocked_by_protected_items),
        )
        if not interactive and signature == self._last_history_budget_warning_signature:
            return
        self._last_history_budget_warning_signature = signature

        message_parts = [
            (
                f"History storage is using {self._human_size(result.total_bytes)} while the "
                f"profile budget is {self._human_size(result.budget_bytes)}."
            )
        ]
        if result.removed_item_keys:
            message_parts.append(
                f"Automatic cleanup already removed {len(result.removed_item_keys)} safe item(s)."
            )
        elif not settings.auto_cleanup_enabled:
            message_parts.append(
                "Automatic cleanup is disabled for this profile, so nothing was deleted automatically."
            )
        if result.blocked_by_protected_items:
            message_parts.append(
                "The remaining over-budget storage is protected by retained history references or manual restore points."
            )
        else:
            message_parts.append(
                "The profile is still over budget and may need a manual cleanup review."
            )
        message_parts.append("Open History Cleanup now?")
        if (
            QMessageBox.question(
                self,
                "History Storage Budget",
                "\n\n".join(message_parts),
                QMessageBox.Yes | QMessageBox.No,
            )
            == QMessageBox.Yes
        ):
            self.open_history_cleanup_dialog()

    def _refresh_auto_snapshot_schedule(self) -> None:
        if not hasattr(self, "auto_snapshot_timer"):
            return
        if self.history_manager is None or self.settings_reads is None:
            self.auto_snapshot_timer.stop()
            self._last_auto_snapshot_marker = None
            return

        enabled, interval_minutes = self._current_auto_snapshot_settings()
        if not enabled:
            self.auto_snapshot_timer.stop()
            self._last_auto_snapshot_marker = None
            return

        interval_minutes = max(
            MIN_AUTO_SNAPSHOT_INTERVAL_MINUTES,
            min(
                MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES,
                int(interval_minutes or DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES),
            ),
        )
        interval_ms = int(interval_minutes * 60 * 1000)
        if (
            self.auto_snapshot_timer.interval() != interval_ms
            or not self.auto_snapshot_timer.isActive()
        ):
            self.auto_snapshot_timer.start(interval_ms)

    def _current_auto_snapshot_marker(self) -> int | None:
        if self.history_manager is None:
            return None
        entry = self.history_manager.get_current_entry()
        while entry is not None:
            action_type = entry.action_type or ""
            if action_type.startswith("file.") or action_type in {
                "db.verify",
                "snapshot.create",
                "snapshot.delete",
            }:
                entry = (
                    self.history_manager.fetch_entry(entry.parent_id)
                    if entry.parent_id is not None
                    else None
                )
                continue
            return entry.entry_id
        return None

    def _on_auto_snapshot_timer(self) -> None:
        if self.history_manager is None or self.settings_reads is None:
            return
        enabled, _interval_minutes = self._current_auto_snapshot_settings()
        if not enabled:
            self.auto_snapshot_timer.stop()
            return

        marker = self._current_auto_snapshot_marker()
        if marker is None or marker == self._last_auto_snapshot_marker:
            return
        estimated_bytes = self._estimate_history_snapshot_capture_bytes()
        if not self._prepare_history_storage_for_projected_growth(
            trigger_label="automatic snapshot",
            additional_bytes=estimated_bytes,
            interactive=False,
        ):
            return

        label = f"Automatic Snapshot {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        try:
            snapshot = self.history_manager.capture_snapshot(kind="auto_interval", label=label)
            self._last_auto_snapshot_marker = marker
            self._log_event(
                "snapshot.auto.create",
                "Automatic snapshot created",
                snapshot_id=snapshot.snapshot_id,
                label=snapshot.label,
                marker=marker,
            )
            self.statusBar().showMessage(f"Automatic snapshot created: {snapshot.label}", 4000)
            if self.history_dialog is not None and self.history_dialog.isVisible():
                self.history_dialog.refresh_data()
            self._enforce_history_storage_budget(trigger_label="automatic snapshot")
        except Exception as exc:
            self.logger.exception(f"Automatic snapshot failed: {exc}")

    def _current_settings_values(self) -> dict[str, object]:
        registration = self.settings_reads.load_registration_settings()
        auto_snapshot_enabled, auto_snapshot_interval_minutes = (
            self._current_auto_snapshot_settings()
        )
        history_retention = self._current_history_retention_settings()
        gs1_defaults = (
            self.gs1_settings_service.load_profile_defaults()
            if self.gs1_settings_service is not None
            else None
        )
        gs1_contracts = (
            self.gs1_settings_service.load_contracts()
            if self.gs1_settings_service is not None
            else ()
        )
        return {
            "window_title": self.identity.get("window_title") or DEFAULT_WINDOW_TITLE,
            "icon_path": self.identity.get("icon_path") or "",
            "theme_settings": dict(self.theme_settings or self._load_theme_settings()),
            "theme_library": self._load_theme_library(),
            "blob_icon_settings": dict(self.blob_icon_settings or self._load_blob_icon_settings()),
            "artist_code": self.load_artist_code(),
            "auto_snapshot_enabled": auto_snapshot_enabled,
            "auto_snapshot_interval_minutes": auto_snapshot_interval_minutes,
            "history_retention_mode": str(history_retention.retention_mode or ""),
            "history_auto_cleanup_enabled": bool(history_retention.auto_cleanup_enabled),
            "history_storage_budget_mb": int(history_retention.storage_budget_mb),
            "history_auto_snapshot_keep_latest": int(history_retention.auto_snapshot_keep_latest),
            "history_prune_pre_restore_copies_after_days": int(
                history_retention.prune_pre_restore_copies_after_days
            ),
            "isrc_prefix": registration.isrc_prefix,
            "sena_number": registration.sena_number,
            "btw_number": registration.btw_number,
            "buma_relatie_nummer": registration.buma_relatie_nummer,
            "buma_ipi": registration.buma_ipi,
            "gs1_template_asset": (
                self.gs1_settings_service.load_template_asset()
                if self.gs1_settings_service is not None
                else None
            ),
            "gs1_contracts_csv_path": (
                self.gs1_settings_service.load_contracts_csv_path()
                if self.gs1_settings_service is not None
                else ""
            ),
            "gs1_contract_entries": tuple(gs1_contracts),
            "gs1_active_contract_number": (
                gs1_defaults.contract_number if gs1_defaults is not None else ""
            ),
            "gs1_target_market": gs1_defaults.target_market if gs1_defaults is not None else "",
            "gs1_language": gs1_defaults.language if gs1_defaults is not None else "",
            "gs1_brand": gs1_defaults.brand if gs1_defaults is not None else "",
            "gs1_subbrand": gs1_defaults.subbrand if gs1_defaults is not None else "",
            "gs1_packaging_type": gs1_defaults.packaging_type if gs1_defaults is not None else "",
            "gs1_product_classification": (
                gs1_defaults.product_classification if gs1_defaults is not None else ""
            ),
        }

    def _apply_settings_changes(
        self,
        before_values: dict[str, object],
        after_values: dict[str, object],
        *,
        show_confirmation: bool = False,
    ) -> int:
        changed_count = 0
        history_policy_changed = False

        try:
            before_identity = {
                "window_title": before_values["window_title"],
                "icon_path": before_values["icon_path"],
            }
            after_identity = {
                "window_title": after_values["window_title"],
                "icon_path": after_values["icon_path"],
            }
            if after_identity != before_identity:
                self.identity = self.settings_mutations.set_identity(
                    window_title=after_identity["window_title"],
                    icon_path=after_identity["icon_path"],
                )
                self._apply_identity()
                self.logger.info("Branding & identity updated")
                self._audit(
                    "SETTINGS",
                    "Identity",
                    ref_id="QSettings",
                    details=f"title={self.identity['window_title']}",
                )
                self._audit_commit()
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="identity",
                        label="Update Branding & Identity",
                        before_value=before_identity,
                        after_value=self.identity,
                    )
                changed_count += 1

            before_theme_library = self._sanitize_theme_library(before_values.get("theme_library"))
            after_theme_library = self._sanitize_theme_library(after_values.get("theme_library"))
            if after_theme_library != before_theme_library:
                self._save_theme_library(after_theme_library)
                self.logger.info("Theme library updated")
                self._log_event(
                    "settings.theme_library",
                    "Theme library updated",
                    stored_themes=len(after_theme_library),
                )
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="theme_library",
                        label="Update Saved Themes",
                        before_value=before_theme_library,
                        after_value=after_theme_library,
                    )
                changed_count += 1

            before_theme = self._normalize_theme_settings(before_values.get("theme_settings"))
            after_theme = self._normalize_theme_settings(after_values.get("theme_settings"))
            if (
                after_theme.get("selected_name")
                and after_theme["selected_name"] not in after_theme_library
            ):
                after_theme["selected_name"] = ""
            if after_theme != before_theme:
                self._save_theme_settings(after_theme)
                try:
                    self._apply_theme_with_loading(after_theme)
                except Exception as exc:
                    self.logger.warning(
                        "Theme preparation task failed, falling back to direct apply: %s",
                        exc,
                    )
                    self._apply_theme(after_theme)
                self.logger.info("Theme settings updated")
                self._log_event(
                    "settings.theme",
                    "Theme settings updated",
                    font_family=after_theme.get("font_family"),
                    font_size=after_theme.get("font_size"),
                )
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="theme_settings",
                        label="Update Theme Settings",
                        before_value=before_theme,
                        after_value=after_theme,
                    )
                changed_count += 1

            before_blob_icons = normalize_blob_icon_settings(
                before_values.get("blob_icon_settings")
            )
            after_blob_icons = normalize_blob_icon_settings(after_values.get("blob_icon_settings"))
            if after_blob_icons != before_blob_icons:
                self._save_blob_icon_settings(after_blob_icons)
                self.logger.info("Blob icon settings updated")
                self._log_event(
                    "settings.blob_icons",
                    "Blob icon settings updated",
                    audio=describe_blob_icon_spec(after_blob_icons.get("audio"), kind="audio"),
                    image=describe_blob_icon_spec(after_blob_icons.get("image"), kind="image"),
                )
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="blob_icon_settings",
                        label="Update Blob Icon Settings",
                        before_value=before_blob_icons,
                        after_value=after_blob_icons,
                    )
                changed_count += 1
                if hasattr(self, "table"):
                    self._apply_blob_badges()
                    self.table.viewport().update()

            if after_values["artist_code"] != before_values["artist_code"]:
                self.settings_mutations.set_artist_code(after_values["artist_code"])
                self.logger.info(
                    f"ISRC artist code set to '{after_values['artist_code']}' (profile DB)"
                )
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="artist_code",
                        label=f"Set ISRC Artist Code: {after_values['artist_code']}",
                        before_value=before_values["artist_code"],
                        after_value=after_values["artist_code"],
                    )
                changed_count += 1

            if after_values["auto_snapshot_enabled"] != before_values["auto_snapshot_enabled"]:
                self.settings_mutations.set_auto_snapshot_enabled(
                    bool(after_values["auto_snapshot_enabled"])
                )
                self._log_event(
                    "settings.auto_snapshot_enabled",
                    "Automatic snapshots setting updated",
                    enabled=bool(after_values["auto_snapshot_enabled"]),
                )
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="auto_snapshot_enabled",
                        label=(
                            "Automatic Snapshots Enabled"
                            if after_values["auto_snapshot_enabled"]
                            else "Automatic Snapshots Disabled"
                        ),
                        before_value=before_values["auto_snapshot_enabled"],
                        after_value=after_values["auto_snapshot_enabled"],
                    )
                changed_count += 1

            if (
                after_values["auto_snapshot_interval_minutes"]
                != before_values["auto_snapshot_interval_minutes"]
            ):
                self.settings_mutations.set_auto_snapshot_interval_minutes(
                    int(after_values["auto_snapshot_interval_minutes"])
                )
                self._log_event(
                    "settings.auto_snapshot_interval_minutes",
                    "Automatic snapshot interval updated",
                    interval_minutes=int(after_values["auto_snapshot_interval_minutes"]),
                )
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="auto_snapshot_interval_minutes",
                        label=f"Set Auto Snapshot Interval: {int(after_values['auto_snapshot_interval_minutes'])} minutes",
                        before_value=before_values["auto_snapshot_interval_minutes"],
                        after_value=after_values["auto_snapshot_interval_minutes"],
                    )
                changed_count += 1

            if after_values["history_retention_mode"] != before_values["history_retention_mode"]:
                self.settings_mutations.set_history_retention_mode(
                    str(after_values["history_retention_mode"])
                )
                self._log_event(
                    "settings.history_retention_mode",
                    "History retention mode updated",
                    mode=str(after_values["history_retention_mode"]),
                )
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="history_retention_mode",
                        label=(
                            "Set History Retention Level: "
                            f"{str(after_values['history_retention_mode']).replace('_', ' ').title()}"
                        ),
                        before_value=before_values["history_retention_mode"],
                        after_value=after_values["history_retention_mode"],
                    )
                changed_count += 1
                history_policy_changed = True

            if (
                after_values["history_auto_cleanup_enabled"]
                != before_values["history_auto_cleanup_enabled"]
            ):
                self.settings_mutations.set_history_auto_cleanup_enabled(
                    bool(after_values["history_auto_cleanup_enabled"])
                )
                self._log_event(
                    "settings.history_auto_cleanup_enabled",
                    "History automatic cleanup setting updated",
                    enabled=bool(after_values["history_auto_cleanup_enabled"]),
                )
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="history_auto_cleanup_enabled",
                        label=(
                            "History Automatic Cleanup Enabled"
                            if after_values["history_auto_cleanup_enabled"]
                            else "History Automatic Cleanup Disabled"
                        ),
                        before_value=before_values["history_auto_cleanup_enabled"],
                        after_value=after_values["history_auto_cleanup_enabled"],
                    )
                changed_count += 1
                history_policy_changed = True

            if (
                after_values["history_storage_budget_mb"]
                != before_values["history_storage_budget_mb"]
            ):
                self.settings_mutations.set_history_storage_budget_mb(
                    int(after_values["history_storage_budget_mb"])
                )
                self._log_event(
                    "settings.history_storage_budget_mb",
                    "History storage budget updated",
                    budget_mb=int(after_values["history_storage_budget_mb"]),
                )
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="history_storage_budget_mb",
                        label=(
                            f"Set History Storage Budget: "
                            f"{int(after_values['history_storage_budget_mb'])} MB"
                        ),
                        before_value=before_values["history_storage_budget_mb"],
                        after_value=after_values["history_storage_budget_mb"],
                    )
                changed_count += 1
                history_policy_changed = True

            if (
                after_values["history_auto_snapshot_keep_latest"]
                != before_values["history_auto_snapshot_keep_latest"]
            ):
                self.settings_mutations.set_history_auto_snapshot_keep_latest(
                    int(after_values["history_auto_snapshot_keep_latest"])
                )
                self._log_event(
                    "settings.history_auto_snapshot_keep_latest",
                    "History auto-snapshot retention updated",
                    keep_latest=int(after_values["history_auto_snapshot_keep_latest"]),
                )
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="history_auto_snapshot_keep_latest",
                        label=(
                            "Set Automatic Snapshot Retention: "
                            f"{int(after_values['history_auto_snapshot_keep_latest'])}"
                        ),
                        before_value=before_values["history_auto_snapshot_keep_latest"],
                        after_value=after_values["history_auto_snapshot_keep_latest"],
                    )
                changed_count += 1
                history_policy_changed = True

            if (
                after_values["history_prune_pre_restore_copies_after_days"]
                != before_values["history_prune_pre_restore_copies_after_days"]
            ):
                self.settings_mutations.set_history_prune_pre_restore_copies_after_days(
                    int(after_values["history_prune_pre_restore_copies_after_days"])
                )
                self._log_event(
                    "settings.history_prune_pre_restore_copies_after_days",
                    "History pre-restore backup pruning updated",
                    days=int(after_values["history_prune_pre_restore_copies_after_days"]),
                )
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="history_prune_pre_restore_copies_after_days",
                        label=(
                            "Set Pre-Restore Backup Prune Age: "
                            f"{int(after_values['history_prune_pre_restore_copies_after_days'])} days"
                        ),
                        before_value=before_values["history_prune_pre_restore_copies_after_days"],
                        after_value=after_values["history_prune_pre_restore_copies_after_days"],
                    )
                changed_count += 1
                history_policy_changed = True

            if after_values["isrc_prefix"] != before_values["isrc_prefix"]:
                self.settings_mutations.set_isrc_prefix(after_values["isrc_prefix"])
                self.logger.info(f"ISRC prefix updated to '{after_values['isrc_prefix']}'")
                self._audit(
                    "SETTINGS",
                    "ISRC_Prefix",
                    ref_id=1,
                    details=f"prefix={after_values['isrc_prefix']}",
                )
                self._audit_commit()
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="isrc_prefix",
                        label=f"Set ISRC Prefix: {after_values['isrc_prefix']}",
                        before_value=before_values["isrc_prefix"],
                        after_value=after_values["isrc_prefix"],
                    )
                changed_count += 1

            if after_values["sena_number"] != before_values["sena_number"]:
                self.settings_mutations.set_sena_number(after_values["sena_number"])
                self.logger.info("SENA number updated")
                self._audit("SETTINGS", "SENA", ref_id=1, details="updated")
                self._audit_commit()
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="sena_number",
                        label="Set SENA Number",
                        before_value=before_values["sena_number"],
                        after_value=after_values["sena_number"],
                    )
                changed_count += 1

            if after_values["btw_number"] != before_values["btw_number"]:
                self.settings_mutations.set_btw_number(after_values["btw_number"])
                self.logger.info("BTW number updated")
                self._audit("SETTINGS", "BTW", ref_id=1, details="updated")
                self._audit_commit()
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="btw_number",
                        label="Set BTW Number",
                        before_value=before_values["btw_number"],
                        after_value=after_values["btw_number"],
                    )
                changed_count += 1

            if after_values["buma_relatie_nummer"] != before_values["buma_relatie_nummer"]:
                self.settings_mutations.set_buma_relatie_nummer(after_values["buma_relatie_nummer"])
                self.logger.info("BUMA/STEMRA relatie nummer updated")
                self._audit("SETTINGS", "BUMA_STEMRA", ref_id=1, details="relatie_nummer updated")
                self._audit_commit()
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="buma_relatie_nummer",
                        label="Set BUMA/STEMRA Relation Number",
                        before_value=before_values["buma_relatie_nummer"],
                        after_value=after_values["buma_relatie_nummer"],
                    )
                changed_count += 1

            if after_values["buma_ipi"] != before_values["buma_ipi"]:
                self.settings_mutations.set_buma_ipi(after_values["buma_ipi"])
                self.logger.info("BUMA/STEMRA IPI updated")
                self._audit("SETTINGS", "BUMA_STEMRA", ref_id=1, details="ipi updated")
                self._audit_commit()
                if self.history_manager is not None:
                    self.history_manager.record_setting_change(
                        key="buma_ipi",
                        label="Set BUMA IPI",
                        before_value=before_values["buma_ipi"],
                        after_value=after_values["buma_ipi"],
                    )
                changed_count += 1

            if self.gs1_settings_service is not None:
                pending_template_path = str(
                    after_values.get("gs1_template_import_path") or ""
                ).strip()
                requested_template_storage_mode = normalize_storage_mode(
                    after_values.get("gs1_template_storage_mode"),
                    default=STORAGE_MODE_DATABASE,
                )
                before_template_asset = before_values.get("gs1_template_asset")
                before_template_storage_mode = normalize_storage_mode(
                    getattr(before_template_asset, "storage_mode", None),
                    default=STORAGE_MODE_DATABASE if before_template_asset is not None else None,
                )
                if pending_template_path:
                    if self.gs1_integration_service is not None:
                        stored_template = self.gs1_integration_service.import_template_workbook(
                            pending_template_path,
                            storage_mode=requested_template_storage_mode,
                        )
                    else:
                        stored_template = self.gs1_settings_service.import_template_from_path(
                            pending_template_path,
                            storage_mode=requested_template_storage_mode,
                        )
                    self._log_event(
                        "settings.gs1_template_workbook",
                        "GS1 template workbook stored",
                        template_path=stored_template.source_path,
                        stored_filename=stored_template.filename,
                        storage_mode=stored_template.storage_mode,
                    )
                    changed_count += 1
                elif (
                    before_template_asset is not None
                    and requested_template_storage_mode is not None
                    and requested_template_storage_mode != before_template_storage_mode
                ):
                    stored_template = self.gs1_settings_service.convert_template_storage_mode(
                        requested_template_storage_mode
                    )
                    self._log_event(
                        "settings.gs1_template_workbook",
                        "GS1 template workbook storage mode updated",
                        stored_filename=stored_template.filename,
                        storage_mode=stored_template.storage_mode,
                    )
                    changed_count += 1

                before_gs1_defaults = GS1ProfileDefaults(
                    contract_number=str(
                        before_values.get("gs1_active_contract_number") or ""
                    ).strip(),
                    target_market=str(before_values.get("gs1_target_market") or "").strip(),
                    language=str(before_values.get("gs1_language") or "").strip(),
                    brand=str(before_values.get("gs1_brand") or "").strip(),
                    subbrand=str(before_values.get("gs1_subbrand") or "").strip(),
                    packaging_type=str(before_values.get("gs1_packaging_type") or "").strip(),
                    product_classification=str(
                        before_values.get("gs1_product_classification") or ""
                    ).strip(),
                )
                after_gs1_defaults = GS1ProfileDefaults(
                    contract_number=str(
                        after_values.get("gs1_active_contract_number") or ""
                    ).strip(),
                    target_market=str(after_values.get("gs1_target_market") or "").strip(),
                    language=str(after_values.get("gs1_language") or "").strip(),
                    brand=str(after_values.get("gs1_brand") or "").strip(),
                    subbrand=str(after_values.get("gs1_subbrand") or "").strip(),
                    packaging_type=str(after_values.get("gs1_packaging_type") or "").strip(),
                    product_classification=str(
                        after_values.get("gs1_product_classification") or ""
                    ).strip(),
                )
                before_contracts = tuple(before_values.get("gs1_contract_entries") or ())
                after_contracts = tuple(after_values.get("gs1_contract_entries") or ())
                before_contracts_csv = str(
                    before_values.get("gs1_contracts_csv_path") or ""
                ).strip()
                after_contracts_csv = str(after_values.get("gs1_contracts_csv_path") or "").strip()
                if (
                    after_contracts != before_contracts
                    or after_contracts_csv != before_contracts_csv
                ):
                    if after_contracts:
                        self.gs1_settings_service.set_contracts(
                            after_contracts, source_path=after_contracts_csv
                        )
                    else:
                        self.gs1_settings_service.clear_contracts()
                    self._log_event(
                        "settings.gs1_contracts",
                        "GS1 contract list updated",
                        contract_count=len(after_contracts),
                        csv_path=after_contracts_csv,
                    )
                    changed_count += 1
                if after_gs1_defaults != before_gs1_defaults:
                    self.gs1_settings_service.set_profile_defaults(after_gs1_defaults)
                    self._log_event(
                        "settings.gs1_defaults",
                        "GS1 profile defaults updated",
                        contract_number=after_gs1_defaults.contract_number,
                        target_market=after_gs1_defaults.target_market,
                        language=after_gs1_defaults.language,
                        brand=after_gs1_defaults.brand,
                        subbrand=after_gs1_defaults.subbrand,
                        packaging_type=after_gs1_defaults.packaging_type,
                        product_classification=after_gs1_defaults.product_classification,
                    )
                    changed_count += 1
        except Exception:
            if self.conn is not None:
                self.conn.rollback()
            raise

        if changed_count:
            self._refresh_auto_snapshot_schedule()
            if history_policy_changed:
                self._enforce_history_storage_budget(
                    trigger_label="settings update",
                    interactive=True,
                )
            self._update_add_data_generated_fields()
            self._refresh_history_actions()
            if show_confirmation:
                QMessageBox.information(self, "Settings Saved", "Application settings updated.")
        return changed_count

    def open_settings_dialog(self, initial_focus: str | None = None):
        before_values = self._current_settings_values()
        dlg = ApplicationSettingsDialog(
            window_title=before_values["window_title"],
            icon_path=before_values["icon_path"],
            artist_code=before_values["artist_code"],
            auto_snapshot_enabled=before_values["auto_snapshot_enabled"],
            auto_snapshot_interval_minutes=before_values["auto_snapshot_interval_minutes"],
            isrc_prefix=before_values["isrc_prefix"],
            sena_number=before_values["sena_number"],
            btw_number=before_values["btw_number"],
            buma_relatie_nummer=before_values["buma_relatie_nummer"],
            buma_ipi=before_values["buma_ipi"],
            gs1_template_asset=before_values["gs1_template_asset"],
            gs1_contracts_csv_path=before_values["gs1_contracts_csv_path"],
            gs1_contract_entries=before_values["gs1_contract_entries"],
            gs1_active_contract_number=before_values["gs1_active_contract_number"],
            gs1_target_market=before_values["gs1_target_market"],
            gs1_language=before_values["gs1_language"],
            gs1_brand=before_values["gs1_brand"],
            gs1_subbrand=before_values["gs1_subbrand"],
            gs1_packaging_type=before_values["gs1_packaging_type"],
            gs1_product_classification=before_values["gs1_product_classification"],
            theme_settings=before_values["theme_settings"],
            stored_themes=before_values["theme_library"],
            blob_icon_settings=before_values["blob_icon_settings"],
            current_profile_path=getattr(self, "current_db_path", ""),
            history_retention_mode=before_values["history_retention_mode"],
            history_auto_cleanup_enabled=before_values["history_auto_cleanup_enabled"],
            history_storage_budget_mb=before_values["history_storage_budget_mb"],
            history_auto_snapshot_keep_latest=before_values["history_auto_snapshot_keep_latest"],
            history_prune_pre_restore_copies_after_days=before_values[
                "history_prune_pre_restore_copies_after_days"
            ],
            parent=self,
        )
        dlg.focus_field(initial_focus)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            self._apply_settings_changes(before_values, dlg.values(), show_confirmation=True)
        except Exception as e:
            self.logger.exception(f"Settings update failed: {e}")
            QMessageBox.critical(self, "Settings Error", f"Could not save settings:\n{e}")

    def _apply_single_setting_value(self, field_name: str, value: str) -> int:
        before_values = self._current_settings_values()
        after_values = dict(before_values)
        after_values[field_name] = value
        return self._apply_settings_changes(before_values, after_values)

    def edit_identity(self):
        self.open_settings_dialog(initial_focus="window_title")

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
        if val is None:
            self.open_settings_dialog(initial_focus="artist_code")
            return

        val = (val or "").strip()
        if not re.fullmatch(r"\d{2}", val):
            QMessageBox.warning(
                self, "Invalid artist code", "Artist code must be two digits (00–99)."
            )
            return

        self._apply_single_setting_value("artist_code", val)
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
        if (
            QMessageBox.question(
                self,
                "Switch Profile",
                f"Switch to database:\n{path}?",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return

        previous_path = self.current_db_path

        def _after_switch(prepared_path: str):
            self._log_event(
                "profile.switch",
                "Switched profile",
                from_path=previous_path,
                to_path=prepared_path,
            )
            self._audit("PROFILE", "Database", ref_id=prepared_path, details="switch_profile")
            self._audit_commit()
            self.session_history_manager.record_profile_switch(
                from_path=previous_path,
                to_path=prepared_path,
                action_type="profile.switch",
            )
            self._refresh_history_actions()

        self._activate_profile_in_background(
            path,
            title="Switch Profile",
            description="Preparing the selected profile database...",
            on_activated=_after_switch,
        )

    def create_new_profile(self):
        name, ok = QInputDialog.getText(
            self, "New Profile", "Database file name (no path, e.g., mylabel.db):"
        )
        if not ok or not name.strip():
            return
        previous_path = self.current_db_path
        try:
            new_path = str(self.profile_workflows.build_new_profile_path(name))
        except FileExistsError:
            QMessageBox.warning(self, "Exists", "A database with this name already exists.")
            return
        self._clear_table_settings_for_path(new_path)

        def _after_create(prepared_path: str):
            self._log_event(
                "profile.create",
                "Created new profile database",
                previous_path=previous_path,
                created_path=prepared_path,
            )
            self._audit("PROFILE", "Database", ref_id=prepared_path, details="create_new_profile")
            self._audit_commit()
            self.session_history_manager.record_profile_create(
                created_path=prepared_path,
                previous_path=previous_path,
            )
            self._refresh_history_actions()
            QMessageBox.information(self, "Profile Created", f"Database created:\n{prepared_path}")

        self._activate_profile_in_background(
            new_path,
            title="Create Profile",
            description="Creating the new profile database...",
            on_activated=_after_create,
        )

    def browse_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Database", str(self.database_dir), "SQLite DB (*.db);;All Files (*)"
        )
        if not path:
            return
        previous_path = self.current_db_path

        def _after_browse(prepared_path: str):
            self._log_event(
                "profile.browse",
                "Opened external profile database",
                previous_path=previous_path,
                path=prepared_path,
            )
            self._audit("PROFILE", "Database", ref_id=prepared_path, details="browse_profile")
            self._audit_commit()
            self.session_history_manager.record_profile_switch(
                from_path=previous_path,
                to_path=prepared_path,
                action_type="profile.browse",
                label=f"Browse Profile: {Path(prepared_path).name}",
            )
            self._refresh_history_actions()

        self._activate_profile_in_background(
            path,
            title="Open Profile",
            description="Preparing the selected profile database...",
            on_activated=_after_browse,
        )

    def remove_selected_profile(self):
        idx = self.profile_combo.currentIndex()
        if idx < 0:
            return
        path = self.profile_combo.itemData(idx)
        if not path:
            return

        if (
            QMessageBox.question(
                self,
                "Remove Profile",
                f"Delete this database file from disk?\n\n{path}\n\nThis cannot be undone.",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return

        deleting_current = getattr(self, "current_db_path", None) == path
        current_path = self.current_db_path
        removed_snapshot_path = None

        try:
            removed_snapshot_path = self.session_history_manager.capture_profile_snapshot(
                path,
                kind="profile_remove",
            )
            if deleting_current:
                self._close_database_connection()

            result = self.profile_workflows.delete_profile(
                path, getattr(self, "current_db_path", None)
            )

            self._reload_profiles_list(select_path=None)

            if result.deleting_current and result.fallback_path:
                self.open_database(result.fallback_path)
                self._reload_profiles_list(select_path=result.fallback_path)

            self.refresh_table_preserve_view()
            self.populate_all_comboboxes()
            self._log_event(
                "profile.remove",
                "Removed profile database from disk",
                level=logging.WARNING,
                path=path,
                deleting_current=result.deleting_current,
                fallback_path=result.fallback_path,
            )
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

    def open_catalog_managers_dialog(self, *, initial_tab: str = "artists"):
        if self.catalog_service is None:
            QMessageBox.warning(self, "Catalog Managers", "Open a profile first.")
            return
        dock = self._ensure_catalog_managers_dock()
        panel = dock.show_panel()
        panel.focus_tab(initial_tab)
        self.catalog_managers_dialog = panel
        self.populate_all_comboboxes()

    def _manage_stored_artists(self):
        self.open_catalog_managers_dialog(initial_tab="artists")

    def _manage_stored_albums(self):
        self.open_catalog_managers_dialog(initial_tab="albums")

    def _manage_licensees(self):
        self.open_catalog_managers_dialog(initial_tab="licensees")

    def _close_database_connection(self):
        if hasattr(self, "auto_snapshot_timer"):
            self.auto_snapshot_timer.stop()
        self._last_auto_snapshot_marker = None
        self.database_session.close(self.conn)
        self.conn = None
        self.cursor = None
        self.schema_service = None
        self.history_manager = None
        self.profile_kv = None
        self.history_cleanup_service = None
        self.settings_reads = None
        self.settings_mutations = None
        self.blob_icon_settings_service = None
        self.gs1_settings_service = None
        self.gs1_integration_service = None
        self.catalog_service = None
        self.catalog_reads = None
        self.license_service = None
        self.custom_field_definitions = None
        self.custom_field_values = None
        self.xml_export_service = None
        self.xml_import_service = None
        self.release_service = None
        self.authenticity_key_service = None
        self.authenticity_manifest_service = None
        self.audio_watermark_service = None
        self.audio_authenticity_service = None
        self.party_service = None
        self.work_service = None
        self.contract_service = None
        self.license_migration_service = None
        self.rights_service = None
        self.asset_service = None
        self.repertoire_workflow_service = None
        self.global_search_service = None
        self.relationship_explorer_service = None
        self.audio_tag_service = None
        self.tagged_audio_export_service = None
        self.exchange_service = None
        self.repertoire_exchange_service = None
        self.quality_service = None
        if hasattr(self, "background_service_factory"):
            self.background_service_factory.db_path = None
        self._background_write_lock = None
        self._refresh_catalog_workspace_docks()

    def _configure_background_runtime(self) -> None:
        settings_path = self.settings.fileName() if hasattr(self, "settings") else None
        db_path = str(getattr(self, "current_db_path", "") or "").strip() or None
        if hasattr(self, "background_service_factory"):
            self.background_service_factory.configure(
                db_path=db_path,
                settings_path=settings_path,
            )
        self._background_write_lock = (
            DatabaseWriteCoordinator.for_path(db_path) if db_path else None
        )

    def _on_background_task_state_changed(self) -> None:
        status_bar = self.statusBar() if hasattr(self, "statusBar") else None
        if status_bar is None:
            return
        if self.background_tasks.has_running_tasks():
            titles = self.background_tasks.active_task_titles()
            preview = ", ".join(titles[:3])
            if len(titles) > 3:
                preview += ", ..."
            status_bar.showMessage(f"Background tasks running: {preview}")
        else:
            status_bar.clearMessage()

    def _prepare_for_background_db_task(self) -> None:
        if getattr(self, "conn", None) is None:
            return
        try:
            self.conn.commit()
        except Exception:
            pass
        try:
            safe_wal_checkpoint(self.conn, mode="PASSIVE", logger=self.logger)
        except Exception:
            pass

    def _show_background_task_error(
        self,
        title: str,
        failure: TaskFailure,
        *,
        user_message: str,
    ) -> None:
        self.logger.error("%s: %s", title, failure.message)
        if failure.traceback_text:
            self.logger.error("%s traceback:\n%s", title, failure.traceback_text)
        QMessageBox.critical(self, title, f"{user_message}\n{failure.message}")

    def _submit_background_task(
        self,
        *,
        title: str,
        description: str,
        task_fn,
        kind: str = "read",
        unique_key: str | None = None,
        requires_profile: bool = True,
        show_dialog: bool = True,
        cancellable: bool = False,
        owner: QWidget | None = None,
        on_success=None,
        on_error=None,
        on_cancelled=None,
        on_finished=None,
        on_progress=None,
        on_status=None,
    ):
        if requires_profile and not str(getattr(self, "current_db_path", "") or "").strip():
            QMessageBox.warning(self, title, "Open a profile first.")
            return None
        if kind in {"read", "write", "exclusive"}:
            self._prepare_for_background_db_task()

        write_lock = self._background_write_lock if kind in {"write", "exclusive"} else None

        def _wrapped_task(ctx):
            ctx.set_status(description)
            if write_lock is not None:
                with write_lock.acquire():
                    ctx.raise_if_cancelled()
                    return task_fn(ctx)
            ctx.raise_if_cancelled()
            return task_fn(ctx)

        return self.background_tasks.submit(
            title=title,
            description=description,
            task_fn=_wrapped_task,
            kind=kind,
            unique_key=unique_key,
            owner=owner or self,
            show_dialog=show_dialog,
            cancellable=cancellable,
            on_success=on_success,
            on_error=on_error,
            on_cancelled=on_cancelled,
            on_finished=on_finished,
            on_progress=on_progress,
            on_status=on_status,
        )

    def _submit_background_bundle_task(
        self,
        *,
        title: str,
        description: str,
        task_fn,
        kind: str = "read",
        unique_key: str | None = None,
        requires_profile: bool = True,
        show_dialog: bool = True,
        cancellable: bool = False,
        owner: QWidget | None = None,
        on_success=None,
        on_error=None,
        on_cancelled=None,
        on_finished=None,
        on_progress=None,
        on_status=None,
    ):
        def _bundle_task(ctx):
            with self.background_service_factory.open_bundle() as bundle:
                return task_fn(bundle, ctx)

        return self._submit_background_task(
            title=title,
            description=description,
            task_fn=_bundle_task,
            kind=kind,
            unique_key=unique_key,
            requires_profile=requires_profile,
            show_dialog=show_dialog,
            cancellable=cancellable,
            owner=owner,
            on_success=on_success,
            on_error=on_error,
            on_cancelled=on_cancelled,
            on_finished=on_finished,
            on_progress=on_progress,
            on_status=on_status,
        )

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
        self._configure_background_runtime()
        self._report_startup_phase(StartupPhase.LOADING_SERVICES)
        self._init_services()

        self._migrate_artist_code_from_qsettings_if_needed()

        current_code = self.load_artist_code()

        self._log_event(
            "profile.open",
            "Opened profile database",
            path=path,
            artist_code=current_code,
        )

        self.database_session.remember_last_path(self.settings, path)
        self.logger.info("Settings synced to disk")

        # Create base tables/indices if missing
        self._report_startup_phase(StartupPhase.PREPARING_DATABASE)
        self.init_db()

        # Run schema migrations and then refresh caches that depend on schema
        try:
            self.migrate_schema()
        except Exception as e:
            self.logger.exception(f"Schema migration failed: {e}")
            self._run_startup_message_box(
                title="Migration Error",
                icon=QMessageBox.Critical,
                text=f"Database migration failed:\n{e}",
            )
            # keep going; DB might still be usable
        if self.history_manager is not None:
            self.history_manager._ensure_history_invariants()

        self.blob_icon_settings = self._load_blob_icon_settings()
        self.active_custom_fields = self.load_active_custom_fields()
        self._refresh_catalog_workspace_docks()

        # now it's safe to write AuditLog
        self._audit("PROFILE", "Database", ref_id=path, details="open_database()")
        self._audit_commit()
        self._refresh_history_actions()
        self._last_auto_snapshot_marker = self._current_auto_snapshot_marker()
        self._refresh_auto_snapshot_schedule()

    def init_db(self):
        self.schema_service.init_db()

    def _get_db_version(self) -> int:
        return self.schema_service.get_db_version()

    def migrate_schema(self):
        self.schema_service.migrate_schema()

    # --- Audit helpers ---
    def _audit(
        self,
        action: str,
        entity: str,
        ref_id: str | int | None = None,
        details: str | None = None,
        user: str | None = None,
    ):
        """Append an entry to AuditLog and write to file logger."""
        try:
            self.cursor.execute(
                "INSERT INTO AuditLog (user, action, entity, ref_id, details) VALUES (?, ?, ?, ?, ?)",
                (user, action, entity, str(ref_id) if ref_id is not None else None, details),
            )
            self._log_trace(
                "audit",
                message=f"{action} {entity}",
                action=action,
                entity=entity,
                ref_id=ref_id,
                details=details,
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

    @contextmanager
    def _suspend_table_layout_history(self):
        header = self.table.horizontalHeader() if hasattr(self, "table") else None
        previous_suspend_state = self._suspend_layout_history
        self._suspend_layout_history = True
        if header is not None:
            self._unbind_header_state_signals()
        try:
            yield
        finally:

            def _resume_layout_history():
                self._suspend_layout_history = previous_suspend_state
                try:
                    self._bind_header_state_signals()
                except Exception as exc:
                    self.logger.warning("Failed to rebind header history signals: %s", exc)

            QTimer.singleShot(0, _resume_layout_history)

    def _refresh_after_history_change(self):
        with self._suspend_table_layout_history():
            self.identity = self._load_identity()
            self.theme_settings = self._load_theme_settings()
            self.blob_icon_settings = self._load_blob_icon_settings()
            self._apply_identity()
            self._apply_theme()
            self.active_custom_fields = self.load_active_custom_fields()
            self._rebuild_table_headers()
            try:
                self._load_header_state()
            except Exception:
                pass
            self._apply_saved_hint_positions()
            try:
                self._apply_saved_view_preferences()
            except Exception:
                pass
            self.populate_all_comboboxes()
            self._update_add_data_generated_fields()
            self.refresh_table_preserve_view()
            self._refresh_catalog_workspace_docks()
            self._refresh_auto_snapshot_schedule()
            self._last_auto_snapshot_marker = self._current_auto_snapshot_marker()
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
        # Compatibility shim for older callers that still expect a single
        # layout-change hook after the split between reorder and resize events.
        if getattr(self, "_suspend_layout_history", False):
            return
        self._save_header_state()

    def _on_header_sections_reordered(self, *_args):
        if getattr(self, "_suspend_layout_history", False):
            return
        prefix = self._table_settings_prefix()
        self._save_header_state(
            action_label="Reorder Columns",
            history_entity_id=f"{prefix}/column_order",
        )

    def _on_header_sections_resized(self, *_args):
        if getattr(self, "_suspend_layout_history", False):
            return
        prefix = self._table_settings_prefix()
        self._save_header_state(
            action_label="Adjust Column Widths",
            history_entity_id=f"{prefix}/column_widths",
        )

    def _unbind_header_state_signals(self):
        if not getattr(self, "_header_layout_signals_bound", False) or not hasattr(self, "table"):
            return
        header = self.table.horizontalHeader()
        try:
            header.sectionMoved.disconnect(self._on_header_sections_reordered)
        except (RuntimeError, TypeError):
            pass
        try:
            header.sectionResized.disconnect(self._on_header_sections_resized)
        except (RuntimeError, TypeError):
            pass
        self._header_layout_signals_bound = False

    def _bind_header_state_signals(self):
        if not hasattr(self, "table"):
            return
        header = self.table.horizontalHeader()
        self._unbind_header_state_signals()
        header.sectionMoved.connect(self._on_header_sections_reordered)
        header.sectionResized.connect(self._on_header_sections_resized)
        self._header_layout_signals_bound = True

    @staticmethod
    def _set_action_checked_silently(action: QAction, enabled: bool):
        action.blockSignals(True)
        try:
            action.setChecked(bool(enabled))
        finally:
            action.blockSignals(False)

    def _apply_columns_movable_state(self, enabled: bool):
        self.table.horizontalHeader().setSectionsMovable(bool(enabled))

    def _apply_col_width_mode(self, enabled: bool):
        hh = self.table.horizontalHeader()
        if enabled:
            for i in range(self.table.columnCount()):
                hh.setSectionResizeMode(i, QHeaderView.Interactive)
            hh.setStretchLastSection(False)
            if self._col_hint_signal_bound:
                hh.sectionResized.disconnect(self._update_col_hint)
                self._col_hint_signal_bound = False
            hh.sectionResized.connect(self._update_col_hint)
            self._col_hint_signal_bound = True
            self._ensure_col_hint_label()
            self.col_hint_label.show()
            self._apply_table_view_settings()
        else:
            for i in range(self.table.columnCount()):
                hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
            hh.setStretchLastSection(True)
            if not self.col_width_action.isChecked():
                self.table.resizeColumnsToContents()
            if self._col_hint_signal_bound:
                hh.sectionResized.disconnect(self._update_col_hint)
                self._col_hint_signal_bound = False
            if self.col_hint_label:
                self.col_hint_label.hide()
            self._apply_table_view_settings()
        self._reset_hint_label()

    def _apply_row_height_mode(self, enabled: bool):
        vh = self.table.verticalHeader()
        if enabled:
            vh.setSectionResizeMode(QHeaderView.Interactive)
            if self._row_hint_signal_bound:
                vh.sectionResized.disconnect(self._update_row_hint)
                self._row_hint_signal_bound = False
            vh.sectionResized.connect(self._update_row_hint)
            self._row_hint_signal_bound = True
            self._ensure_row_hint_label()
            self.row_hint_label.show()
        else:
            vh.setSectionResizeMode(QHeaderView.Fixed)
            for i in range(self.table.rowCount()):
                self.table.setRowHeight(i, 24)
            if self._row_hint_signal_bound:
                vh.sectionResized.disconnect(self._update_row_hint)
                self._row_hint_signal_bound = False
            if self.row_hint_label:
                self.row_hint_label.hide()
        self._apply_table_view_settings()
        self._reset_hint_label()

    @staticmethod
    def _dock_state_setting_key() -> str:
        return "display/main_window_dock_state"

    @staticmethod
    def _window_geometry_setting_key() -> str:
        return "display/main_window_geometry"

    @staticmethod
    def _window_state_setting_key() -> str:
        return "display/main_window_window_state"

    @staticmethod
    def _window_normal_geometry_setting_key() -> str:
        return "display/main_window_normal_geometry"

    def _schedule_main_dock_state_save(self) -> None:
        if (
            getattr(self, "_suspend_dock_state_sync", False)
            or getattr(self, "_is_restoring_workspace_layout", False)
            or getattr(self, "_is_closing", False)
            or not getattr(self, "_workspace_layout_restore_complete", False)
        ):
            return
        timer = getattr(self, "_dock_state_save_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._save_main_dock_state)
            self._dock_state_save_timer = timer
        timer.start(75)

    def _schedule_main_window_geometry_save(self) -> None:
        if (
            getattr(self, "_is_restoring_workspace_layout", False)
            or getattr(self, "_is_closing", False)
            or not getattr(self, "_workspace_layout_restore_complete", False)
        ):
            return
        timer = getattr(self, "_window_geometry_save_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._save_main_window_geometry)
            self._window_geometry_save_timer = timer
        timer.start(75)

    def _save_main_dock_state(self, *, sync: bool = True) -> None:
        if getattr(self, "_suspend_dock_state_sync", False):
            return
        try:
            self.settings.setValue(self._dock_state_setting_key(), self.saveState(1))
            if sync:
                self.settings.sync()
        except Exception as e:
            self.logger.warning("Failed to save dock state: %s", e)

    def _restore_main_dock_state(self) -> bool:
        try:
            state = self.settings.value(self._dock_state_setting_key(), None, QByteArray)
        except Exception:
            state = None
        if not isinstance(state, QByteArray) or state.isEmpty():
            return False
        previous_suspend_state = self._suspend_dock_state_sync
        self._suspend_dock_state_sync = True
        restored = False
        try:
            restored = bool(self.restoreState(state, 1))
            if not restored:
                self.logger.warning("Qt rejected the saved dock state; keeping the default layout")
        except Exception as e:
            self.logger.warning("Failed to restore dock state: %s", e)
        finally:
            self._suspend_dock_state_sync = previous_suspend_state
        return restored

    def _save_main_window_geometry(self, *, sync: bool = True) -> None:
        try:
            self.settings.setValue(self._window_geometry_setting_key(), self.saveGeometry())
            self.settings.setValue(
                self._window_state_setting_key(),
                self._current_main_window_state_marker(),
            )
            normal_geometry = self.normalGeometry()
            if isinstance(normal_geometry, QRect) and normal_geometry.isValid():
                self.settings.setValue(
                    self._window_normal_geometry_setting_key(),
                    normal_geometry,
                )
            if sync:
                self.settings.sync()
        except Exception as e:
            self.logger.warning("Failed to save main window geometry: %s", e)

    def _restore_main_window_geometry(self) -> bool:
        try:
            geometry = self.settings.value(self._window_geometry_setting_key(), None, QByteArray)
        except Exception:
            geometry = None
        try:
            normal_geometry = self.settings.value(
                self._window_normal_geometry_setting_key(),
                None,
                QRect,
            )
        except Exception:
            normal_geometry = None
        try:
            window_state_marker = self.settings.value(self._window_state_setting_key(), "", str)
        except Exception:
            window_state_marker = ""

        has_geometry = isinstance(geometry, QByteArray) and not geometry.isEmpty()
        marker = str(window_state_marker or "").strip().lower()
        if not has_geometry and marker not in {"normal", "maximized", "fullscreen"}:
            return False

        restored = False
        if has_geometry:
            try:
                restored = bool(self.restoreGeometry(geometry))
            except Exception as e:
                self.logger.warning("Failed to restore main window geometry: %s", e)

        if marker == "fullscreen":
            self.showFullScreen()
            return True
        if marker == "maximized":
            self.showMaximized()
            return True
        if marker == "normal":
            self.showNormal()
            if isinstance(normal_geometry, QRect) and normal_geometry.isValid():
                self.setGeometry(normal_geometry)
            return True
        return restored

    def _current_main_window_state_marker(self) -> str:
        window_state = self.windowState()
        if window_state & Qt.WindowFullScreen:
            return "fullscreen"
        if window_state & Qt.WindowMaximized:
            return "maximized"
        return "normal"

    def _store_workspace_panel_visibility_preferences(self, *, sync: bool = True) -> None:
        try:
            add_data_enabled = bool(
                isinstance(getattr(self, "add_data_dock", None), QDockWidget)
                and self.add_data_dock.isVisible()
            )
            catalog_table_enabled = bool(
                isinstance(getattr(self, "catalog_table_dock", None), QDockWidget)
                and self.catalog_table_dock.isVisible()
            )
            self.settings.setValue("display/add_data_panel", add_data_enabled)
            self.settings.setValue("display/catalog_table_panel", catalog_table_enabled)
            self._set_action_checked_silently(self.add_data_action, add_data_enabled)
            self._set_action_checked_silently(
                self.catalog_table_action,
                catalog_table_enabled,
            )
            if sync:
                self.settings.sync()
        except Exception as e:
            self.logger.warning("Failed to store workspace panel visibility: %s", e)

    def _sync_dock_visibility(self, action: QAction, setting_key: str, visible: bool) -> None:
        self._set_action_checked_silently(action, visible)
        if (
            getattr(self, "_suspend_dock_state_sync", False)
            or getattr(self, "_is_restoring_workspace_layout", False)
            or getattr(self, "_is_closing", False)
            or not getattr(self, "_workspace_layout_restore_complete", False)
        ):
            return
        try:
            self.settings.setValue(setting_key, bool(visible))
            self._schedule_main_dock_state_save()
            self.settings.sync()
        except Exception as e:
            self.logger.warning("Failed to sync dock visibility for %s: %s", setting_key, e)

    def _apply_add_data_panel_state(self, enabled: bool):
        enabled = bool(enabled)
        dock = getattr(self, "add_data_dock", None)
        action = getattr(self, "add_data_action", None)
        if action is not None:
            self._set_action_checked_silently(action, enabled)
        if isinstance(dock, QDockWidget):
            dock.setVisible(enabled)
            if enabled:
                dock.raise_()

    def _apply_catalog_table_panel_state(self, enabled: bool):
        enabled = bool(enabled)
        dock = getattr(self, "catalog_table_dock", None)
        action = getattr(self, "catalog_table_action", None)
        if action is not None:
            self._set_action_checked_silently(action, enabled)
        if isinstance(dock, QDockWidget):
            dock.setVisible(enabled)
            if enabled:
                dock.raise_()

    def _create_release_browser_panel(self, parent: QWidget) -> ReleaseBrowserPanel:
        panel = ReleaseBrowserPanel(
            release_service_provider=lambda: self.release_service,
            track_title_resolver=self._get_track_title,
            selected_track_ids_provider=self._selected_track_ids,
            track_choice_provider=self._catalog_track_choices,
            parent=parent,
        )
        panel.filter_requested.connect(
            lambda track_ids: self._replace_catalog_track_filter(track_ids, source_label="release")
        )
        panel.open_track_requested.connect(self.open_selected_editor)
        panel.edit_release_requested.connect(self.open_release_editor)
        panel.duplicate_release_requested.connect(self.duplicate_release)
        panel.add_selected_tracks_requested.connect(
            lambda release_id, track_ids: self.add_selected_tracks_to_specific_release(
                release_id, track_ids
            )
        )
        panel.create_release_requested.connect(self.create_release_from_selection)
        return panel

    def _create_work_manager_panel(self, parent: QWidget) -> WorkBrowserPanel:
        panel = WorkBrowserPanel(
            work_service_provider=lambda: self.work_service,
            track_title_resolver=self._get_track_title,
            selected_track_ids_provider=self._selected_track_ids,
            track_choice_provider=self._catalog_track_choices,
            parent=parent,
        )
        panel.filter_requested.connect(
            lambda track_ids: self._replace_catalog_track_filter(track_ids, source_label="work")
        )
        panel.create_requested.connect(self.create_work)
        panel.update_requested.connect(self.update_work)
        panel.duplicate_requested.connect(self.duplicate_work)
        panel.link_tracks_requested.connect(self.link_tracks_to_work)
        panel.delete_requested.connect(self.delete_work)
        return panel

    def _create_global_search_panel(self, parent: QWidget) -> GlobalSearchPanel:
        panel = GlobalSearchPanel(
            search_service_provider=lambda: self.global_search_service,
            relationship_service_provider=lambda: self.relationship_explorer_service,
            parent=parent,
        )
        panel.open_entity_requested.connect(self._open_entity_from_relationship_search)
        return panel

    def _create_catalog_managers_panel(self, parent: QWidget) -> CatalogManagersPanel:
        return CatalogManagersPanel(self, parent=parent)

    def _create_license_browser_panel(self, parent: QWidget) -> LicensesBrowserPanel:
        return LicensesBrowserPanel(
            app=self,
            license_service_provider=lambda: self.license_service,
            parent=parent,
        )

    def _create_party_manager_panel(self, parent: QWidget) -> PartyManagerPanel:
        return PartyManagerPanel(
            party_service_provider=lambda: self.party_service,
            parent=parent,
        )

    def _create_contract_manager_panel(self, parent: QWidget) -> ContractBrowserPanel:
        return ContractBrowserPanel(
            contract_service_provider=lambda: self.contract_service,
            parent=parent,
        )

    def _create_rights_matrix_panel(self, parent: QWidget) -> RightsBrowserPanel:
        return RightsBrowserPanel(
            rights_service_provider=lambda: self.rights_service,
            party_service_provider=lambda: self.party_service,
            contract_service_provider=lambda: self.contract_service,
            parent=parent,
        )

    def _create_asset_registry_panel(self, parent: QWidget) -> AssetBrowserPanel:
        return AssetBrowserPanel(
            asset_service_provider=lambda: self.asset_service,
            parent=parent,
        )

    def _ensure_release_browser_dock(self) -> QDockWidget:
        dock = ensure_catalog_workspace_dock(
            self,
            key="release_browser",
            title="Release Browser",
            object_name="releaseBrowserDock",
            panel_factory=self._create_release_browser_panel,
        )
        self.release_browser_dock = dock
        return dock

    def _ensure_work_manager_dock(self) -> QDockWidget:
        dock = ensure_catalog_workspace_dock(
            self,
            key="work_manager",
            title="Work Manager",
            object_name="workManagerDock",
            panel_factory=self._create_work_manager_panel,
        )
        self.work_manager_dock = dock
        return dock

    def _ensure_global_search_dock(self) -> QDockWidget:
        dock = ensure_catalog_workspace_dock(
            self,
            key="global_search",
            title="Global Search and Relationships",
            object_name="globalSearchDock",
            panel_factory=self._create_global_search_panel,
        )
        self.global_search_dock = dock
        return dock

    def _ensure_catalog_managers_dock(self) -> QDockWidget:
        dock = ensure_catalog_workspace_dock(
            self,
            key="catalog_managers",
            title="Catalog Managers",
            object_name="catalogManagersDock",
            panel_factory=self._create_catalog_managers_panel,
        )
        self.catalog_managers_dock = dock
        return dock

    def _ensure_license_browser_dock(self) -> QDockWidget:
        dock = ensure_catalog_workspace_dock(
            self,
            key="license_browser",
            title="License Browser",
            object_name="licenseBrowserDock",
            panel_factory=self._create_license_browser_panel,
        )
        self.license_browser_dock = dock
        return dock

    def _ensure_party_manager_dock(self) -> QDockWidget:
        dock = ensure_catalog_workspace_dock(
            self,
            key="party_manager",
            title="Party Manager",
            object_name="partyManagerDock",
            panel_factory=self._create_party_manager_panel,
        )
        self.party_manager_dock = dock
        return dock

    def _ensure_contract_manager_dock(self) -> QDockWidget:
        dock = ensure_catalog_workspace_dock(
            self,
            key="contract_manager",
            title="Contract Manager",
            object_name="contractManagerDock",
            panel_factory=self._create_contract_manager_panel,
        )
        self.contract_manager_dock = dock
        return dock

    def _ensure_rights_matrix_dock(self) -> QDockWidget:
        dock = ensure_catalog_workspace_dock(
            self,
            key="rights_matrix",
            title="Rights Matrix",
            object_name="rightsMatrixDock",
            panel_factory=self._create_rights_matrix_panel,
        )
        self.rights_matrix_dock = dock
        return dock

    def _ensure_asset_registry_dock(self) -> QDockWidget:
        dock = ensure_catalog_workspace_dock(
            self,
            key="asset_registry",
            title="Deliverables and Asset Versions",
            object_name="assetRegistryDock",
            panel_factory=self._create_asset_registry_panel,
        )
        self.asset_registry_dock = dock
        return dock

    def _refresh_catalog_workspace_docks(self) -> None:
        refresh_catalog_workspace_docks(self)

    def _ensure_persistent_workspace_dock_shells(self) -> None:
        previous_suspend_state = self._suspend_dock_state_sync
        previous_restore_state = self._is_restoring_workspace_layout
        self._suspend_dock_state_sync = True
        self._is_restoring_workspace_layout = True
        try:
            for ensure_dock in (
                self._ensure_release_browser_dock,
                self._ensure_work_manager_dock,
                self._ensure_global_search_dock,
                self._ensure_catalog_managers_dock,
                self._ensure_license_browser_dock,
                self._ensure_party_manager_dock,
                self._ensure_contract_manager_dock,
                self._ensure_rights_matrix_dock,
                self._ensure_asset_registry_dock,
            ):
                ensure_dock()
        finally:
            self._is_restoring_workspace_layout = previous_restore_state
            self._suspend_dock_state_sync = previous_suspend_state

    def _restore_workspace_layout_on_first_show(self) -> None:
        if getattr(self, "_workspace_layout_restore_complete", False):
            return
        self._report_startup_phase(StartupPhase.RESTORING_WORKSPACE)
        self._workspace_layout_restore_scheduled = False
        previous_suspend_state = self._suspend_dock_state_sync
        previous_restore_state = self._is_restoring_workspace_layout
        self._suspend_dock_state_sync = True
        self._is_restoring_workspace_layout = True
        restored_dock_state = False
        try:
            self._restore_main_window_geometry()
            restored_dock_state = self._restore_main_dock_state()
            self._apply_saved_view_preferences(
                apply_workspace_panel_visibility=not restored_dock_state
            )
            self._refresh_workspace_dock_default_placement_flags()
            self._materialize_visible_workspace_dock_panels()
        finally:
            self._restored_main_dock_state = restored_dock_state
            self._workspace_layout_restore_complete = True
            self._is_restoring_workspace_layout = previous_restore_state
            self._suspend_dock_state_sync = previous_suspend_state
        self._store_workspace_panel_visibility_preferences(sync=False)
        self._schedule_main_window_geometry_save()
        self._schedule_main_dock_state_save()
        self.startupReady.emit()

    def _materialize_visible_workspace_dock_panels(self) -> None:
        registry = getattr(self, "_catalog_workspace_docks", {})
        for dock in list(registry.values()):
            if not isinstance(dock, QDockWidget):
                continue
            if not dock.isVisible() or getattr(dock, "_panel", None) is not None:
                continue
            panel_method = getattr(dock, "panel", None)
            if callable(panel_method):
                panel_method()
            refresh_method = getattr(dock, "refresh_panel", None)
            if callable(refresh_method):
                refresh_method()

    def _refresh_workspace_dock_default_placement_flags(self) -> None:
        registry = getattr(self, "_catalog_workspace_docks", {})
        for dock in list(registry.values()):
            if not isinstance(dock, QDockWidget):
                continue
            default_area = getattr(dock, "_default_dock_area", Qt.RightDockWidgetArea)
            has_tab_peers = bool(self.tabifiedDockWidgets(dock))
            area = self.dockWidgetArea(dock)
            dock._default_placement_pending = not (
                dock.isVisible() or has_tab_peers or area != default_area
            )

    @staticmethod
    def _action_shortcut_text(action: QAction | None) -> str:
        if action is None:
            return ""
        shortcuts = [
            seq.toString(QKeySequence.NativeText) for seq in action.shortcuts() if not seq.isEmpty()
        ]
        if shortcuts:
            return ", ".join(shortcuts)
        shortcut = action.shortcut()
        if shortcut.isEmpty():
            return ""
        return shortcut.toString(QKeySequence.NativeText)

    def _initialize_action_ribbon_registry(self):
        specs = [
            {
                "id": "save_entry",
                "label": "Save Entry",
                "category": "Edit",
                "description": "Create a new catalog row from the Add Data form.",
                "action": self.save_entry_action,
                "default": True,
            },
            {
                "id": "add_album",
                "label": "Add Album",
                "category": "Edit",
                "description": "Open the structured album-entry dialog with dynamic track sections.",
                "action": self.add_album_action,
                "default": True,
            },
            {
                "id": "edit_selected",
                "label": "Edit Selected",
                "category": "Edit",
                "description": "Open the current selected row or batch in the full editor.",
                "action": self.edit_selected_action,
                "default": True,
            },
            {
                "id": "delete_entry",
                "label": "Delete Selected",
                "category": "Edit",
                "description": "Delete the current selected row or rows after confirmation.",
                "action": self.delete_entry_action,
                "default": True,
            },
            {
                "id": "undo",
                "label": "Undo",
                "category": "Edit",
                "description": "Undo the latest reversible action from session or profile history.",
                "action": self.undo_action,
                "default": True,
            },
            {
                "id": "redo",
                "label": "Redo",
                "category": "Edit",
                "description": "Redo the next available history action.",
                "action": self.redo_action,
                "default": True,
            },
            {
                "id": "copy",
                "label": "Copy",
                "category": "Edit",
                "description": "Copy the current table selection.",
                "action": self.copy_action,
            },
            {
                "id": "copy_with_headers",
                "label": "Copy with Headers",
                "category": "Edit",
                "description": "Copy the current table selection with header labels.",
                "action": self.copy_with_headers_action,
            },
            {
                "id": "reset_form",
                "label": "Reset Form and Search",
                "category": "Edit",
                "description": "Clear the Add Data form and reset the current search filter.",
                "action": self.reset_form_action,
            },
            {
                "id": "new_profile",
                "label": "New Profile",
                "category": "File",
                "description": "Create a new profile database.",
                "action": self.new_profile_action,
            },
            {
                "id": "open_profile",
                "label": "Open Profile",
                "category": "File",
                "description": "Browse to and open an existing profile database.",
                "action": self.open_profile_action,
            },
            {
                "id": "reload_profiles",
                "label": "Reload Profile List",
                "category": "File",
                "description": "Refresh the known profile list from disk.",
                "action": self.reload_profiles_action,
            },
            {
                "id": "remove_profile",
                "label": "Remove Selected Profile",
                "category": "File",
                "description": "Remove the currently selected profile from the workspace list or disk.",
                "action": self.remove_profile_action,
            },
            {
                "id": "import_xml",
                "label": "Import XML",
                "category": "File",
                "description": "Import catalog data from a supported XML file.",
                "action": self.import_xml_action,
                "default": True,
            },
            {
                "id": "import_csv",
                "label": "Import CSV",
                "category": "File",
                "description": "Import tracks, releases, and custom-field data from CSV.",
                "action": self.import_csv_action,
            },
            {
                "id": "import_xlsx",
                "label": "Import XLSX",
                "category": "File",
                "description": "Import tracks, releases, and custom-field data from XLSX.",
                "action": self.import_xlsx_action,
            },
            {
                "id": "import_json",
                "label": "Import JSON",
                "category": "File",
                "description": "Import versioned exchange data from JSON.",
                "action": self.import_json_action,
            },
            {
                "id": "import_package",
                "label": "Import ZIP Package",
                "category": "File",
                "description": "Import a packaged ZIP export with manifest metadata and media copies.",
                "action": self.import_package_action,
            },
            {
                "id": "export_selected",
                "label": "Export Selected Catalog XML",
                "category": "File",
                "description": "Export the current selected catalog rows to XML.",
                "action": self.export_selected_action,
                "default": True,
            },
            {
                "id": "export_all",
                "label": "Export Full Catalog XML",
                "category": "File",
                "description": "Export the full active profile catalog to XML.",
                "action": self.export_all_action,
            },
            {
                "id": "export_selected_csv",
                "label": "Export Selected Exchange CSV",
                "category": "File",
                "description": "Export the current selected catalog rows as exchange CSV.",
                "action": self.export_selected_csv_action,
            },
            {
                "id": "export_selected_json",
                "label": "Export Selected Exchange JSON",
                "category": "File",
                "description": "Export the current selected catalog rows as exchange JSON.",
                "action": self.export_selected_json_action,
            },
            {
                "id": "export_package",
                "label": "Export Selected Exchange ZIP Package",
                "category": "File",
                "description": "Create an exchange ZIP package with metadata and referenced media copies.",
                "action": self.export_selected_package_action,
            },
            {
                "id": "backup",
                "label": "Backup Database",
                "category": "File",
                "description": "Create a safety backup of the current profile database.",
                "action": self.backup_action,
            },
            {
                "id": "restore",
                "label": "Restore from Backup",
                "category": "File",
                "description": "Restore the current profile from a chosen backup.",
                "action": self.restore_action,
            },
            {
                "id": "verify",
                "label": "Verify Integrity",
                "category": "File",
                "description": "Run integrity checks against the current profile database.",
                "action": self.verify_action,
            },
            {
                "id": "license_browser",
                "label": "License Browser",
                "category": "Catalog",
                "description": "Browse, preview, edit, and export stored license PDFs.",
                "action": self.license_browser_action,
            },
            {
                "id": "migrate_legacy_licenses",
                "label": "Migrate Legacy Licenses",
                "category": "Catalog",
                "description": "Convert the legacy license/licensee archive into parties, contracts, and managed contract documents.",
                "action": self.legacy_license_migration_action,
            },
            {
                "id": "catalog_managers",
                "label": "Catalog Managers",
                "category": "Catalog",
                "description": "Open the artists, albums, and licensees manager dialog.",
                "action": self.catalog_managers_action,
            },
            {
                "id": "release_browser",
                "label": "Release Browser",
                "category": "Catalog",
                "description": "Browse, edit, duplicate, and attach tracks to first-class releases.",
                "action": self.release_browser_action,
                "default": True,
            },
            {
                "id": "bulk_attach_audio",
                "label": "Bulk Attach Audio",
                "category": "Catalog",
                "description": "Match audio files to the current selection or visible catalog scope and attach them in one batch.",
                "action": self.bulk_attach_audio_action,
            },
            {
                "id": "import_tags",
                "label": "Import Tags from Audio",
                "category": "Catalog",
                "description": "Read embedded metadata from managed audio files into the catalog.",
                "action": self.import_tags_action,
            },
            {
                "id": "write_tags_audio",
                "label": "Write Tags to Exported Audio",
                "category": "Catalog",
                "description": "Export audio copies with catalog metadata written into the file tags.",
                "action": self.write_tags_to_exported_audio_action,
            },
            {
                "id": "convert_selected_audio",
                "label": "Managed Audio Derivatives",
                "category": "Catalog",
                "description": "Export managed audio derivatives with catalog tags, hashing, and derivative tracking. Lossless targets stay on the watermark-authentic path; lossy targets export as tagged managed derivatives.",
                "action": self.convert_selected_audio_action,
            },
            {
                "id": "authenticity_export_audio",
                "label": "Watermark-Authentic Masters",
                "category": "Catalog",
                "description": "Export WAV, FLAC, or AIFF master copies with a direct watermark plus a signed authenticity sidecar.",
                "action": self.export_authenticity_watermarked_audio_action,
            },
            {
                "id": "authenticity_export_provenance_audio",
                "label": "Provenance-Linked Lossy Copies",
                "category": "Catalog",
                "description": "Export lossy copies with signed lineage sidecars that point back to a verified watermark-authentic master. No managed derivative registration.",
                "action": self.export_authenticity_provenance_audio_action,
            },
            {
                "id": "authenticity_verify_audio",
                "label": "Verify Audio Authenticity",
                "category": "Catalog",
                "description": "Verify either a direct authenticity watermark or a signed provenance lineage sidecar.",
                "action": self.verify_audio_authenticity_action,
            },
            {
                "id": "convert_external_audio",
                "label": "External Conversion Utility",
                "category": "File",
                "description": "Convert one or more external audio files with the utility workflow only: no catalog metadata, no watermarking, and no derivative registration.",
                "action": self.convert_external_audio_files_action,
            },
            {
                "id": "quality_dashboard",
                "label": "Quality Dashboard",
                "category": "Catalog",
                "description": "Scan the profile for metadata, release, media, and integrity issues.",
                "action": self.quality_dashboard_action,
                "default": True,
            },
            {
                "id": "gs1_metadata",
                "label": "GS1 Metadata",
                "category": "Catalog",
                "description": "Open GS1 metadata for the current selected track or batch.",
                "action": self.gs1_metadata_action,
                "default": True,
            },
            {
                "id": "settings",
                "label": "Application Settings",
                "category": "Settings",
                "description": "Open the consolidated application and profile settings dialog.",
                "action": self.settings_action,
                "default": True,
            },
            {
                "id": "authenticity_keys",
                "label": "Audio Authenticity Keys",
                "category": "Settings",
                "description": "Generate Ed25519 keys, set the default signer, and review local key availability.",
                "action": self.authenticity_keys_action,
            },
            {
                "id": "add_custom_column",
                "label": "Add Custom Column",
                "category": "View",
                "description": "Create a new custom metadata column definition.",
                "action": self.add_custom_column_action,
            },
            {
                "id": "manage_fields",
                "label": "Manage Custom Columns",
                "category": "View",
                "description": "Rename, reorder, or update existing custom columns.",
                "action": self.manage_fields_action,
            },
            {
                "id": "show_add_data",
                "label": "Show Add Data Panel",
                "category": "Catalog",
                "description": "Toggle the Add Data dock panel.",
                "action": self.add_data_action,
            },
            {
                "id": "show_catalog_table",
                "label": "Show Catalog Table",
                "category": "Catalog",
                "description": "Toggle the Catalog Table dock panel.",
                "action": self.catalog_table_action,
            },
            {
                "id": "show_history",
                "label": "Show Undo History",
                "category": "History",
                "description": "Open the persistent history browser.",
                "action": self.show_history_action,
                "default": True,
            },
            {
                "id": "create_snapshot",
                "label": "Create Snapshot",
                "category": "History",
                "description": "Create a manual snapshot restore point for the current profile.",
                "action": self.create_snapshot_action,
                "default": True,
            },
            {
                "id": "help_contents",
                "label": "Help Contents",
                "category": "Help",
                "description": "Open the in-app help browser.",
                "action": self.help_contents_action,
            },
            {
                "id": "diagnostics",
                "label": "Diagnostics",
                "category": "Help",
                "description": "Open diagnostics and repair information for the current profile.",
                "action": self.diagnostics_action,
            },
            {
                "id": "application_log",
                "label": "Application Log",
                "category": "Help",
                "description": "Browse the human-readable and structured log views.",
                "action": self.application_log_action,
            },
        ]

        for spec in specs:
            spec["shortcut"] = self._action_shortcut_text(spec.get("action"))

        self._action_ribbon_specs = specs
        self._action_ribbon_specs_by_id = {str(spec["id"]): spec for spec in specs}
        self._action_ribbon_default_ids = [str(spec["id"]) for spec in specs if spec.get("default")]

    def _action_ribbon_setting_keys(self) -> list[str]:
        return [
            "display/action_ribbon_visible",
            "display/action_ribbon_actions_json",
        ]

    def _normalize_action_ribbon_ids(self, action_ids) -> list[str]:
        if not hasattr(self, "_action_ribbon_specs_by_id"):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for action_id in action_ids or []:
            clean_id = str(action_id or "").strip()
            if not clean_id or clean_id in seen or clean_id not in self._action_ribbon_specs_by_id:
                continue
            seen.add(clean_id)
            normalized.append(clean_id)
        return normalized

    def _load_saved_action_ribbon_action_ids(self) -> list[str]:
        setting_key = "display/action_ribbon_actions_json"
        if not self.settings.contains(setting_key):
            return list(getattr(self, "_action_ribbon_default_ids", []))

        raw_value = self.settings.value(setting_key, "[]")
        parsed_ids = raw_value
        if isinstance(raw_value, str):
            try:
                parsed_ids = json.loads(raw_value)
            except Exception:
                return list(getattr(self, "_action_ribbon_default_ids", []))
        elif not isinstance(raw_value, list):
            parsed_ids = []
        normalized_ids = self._normalize_action_ribbon_ids(parsed_ids)
        if not normalized_ids and parsed_ids:
            return list(getattr(self, "_action_ribbon_default_ids", []))
        return normalized_ids

    def _action_ribbon_button_tooltip(self, spec: dict) -> str:
        parts = [str(spec.get("label") or "").strip()]
        description = str(spec.get("description") or "").strip()
        shortcut_text = str(spec.get("shortcut") or "").strip()
        if description:
            parts.append(description)
        if shortcut_text:
            parts.append(f"Shortcut: {shortcut_text}")
        return "\n".join(part for part in parts if part)

    def _rebuild_action_ribbon_toolbar(self):
        toolbar = getattr(self, "action_ribbon_toolbar", None)
        if toolbar is None:
            return

        toolbar.clear()
        action_ids = self._normalize_action_ribbon_ids(
            getattr(self, "_action_ribbon_action_ids", [])
        )
        self._action_ribbon_action_ids = action_ids

        for action_id in action_ids:
            spec = self._action_ribbon_specs_by_id.get(action_id)
            if spec is None:
                continue
            toolbar.addAction(spec["action"])
            widget = toolbar.widgetForAction(spec["action"])
            if widget is not None:
                widget.setProperty("role", "actionRibbonButton")
                widget.setToolTip(self._action_ribbon_button_tooltip(spec))

        spacer = QWidget(toolbar)
        spacer.setObjectName("actionRibbonSpacer")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        toolbar.addAction(self.customize_action_ribbon_action)
        customize_widget = toolbar.widgetForAction(self.customize_action_ribbon_action)
        if customize_widget is not None:
            customize_widget.setProperty("role", "actionRibbonButton")
            customize_widget.setToolTip(
                "Choose which quick actions appear in the top action ribbon."
            )

    def _apply_action_ribbon_configuration(self, action_ids: list[str], visible: bool):
        self._action_ribbon_action_ids = self._normalize_action_ribbon_ids(action_ids)
        self._rebuild_action_ribbon_toolbar()
        if hasattr(self, "action_ribbon_visibility_action"):
            self._set_action_checked_silently(self.action_ribbon_visibility_action, bool(visible))
        if hasattr(self, "action_ribbon_toolbar") and self.action_ribbon_toolbar is not None:
            self.action_ribbon_toolbar.setVisible(bool(visible))

    def _apply_profiles_toolbar_visibility(self, visible: bool) -> None:
        toolbar = getattr(self, "toolbar", None)
        if toolbar is not None:
            toolbar.setVisible(bool(visible))
            toolbar.updateGeometry()
        if hasattr(self, "profiles_toolbar_visibility_action"):
            self._set_action_checked_silently(
                self.profiles_toolbar_visibility_action,
                bool(visible),
            )
        self._queue_top_chrome_boundary_refresh()

    def _open_action_ribbon_context_menu(self, pos):
        toolbar = getattr(self, "action_ribbon_toolbar", None)
        if toolbar is None:
            return
        menu = QMenu(toolbar)
        menu.addAction(self.customize_action_ribbon_action)
        menu.addSeparator()
        menu.addAction(self.action_ribbon_visibility_action)
        menu.exec(toolbar.mapToGlobal(pos))

    def _apply_saved_view_preferences(self, *, apply_workspace_panel_visibility: bool = True):
        previous_suspend_state = self._suspend_layout_history
        self._suspend_layout_history = True
        try:
            columns_movable = self.settings.value(
                f"{self._table_settings_prefix()}/columns_movable", False, bool
            )
            col_width_enabled = self.settings.value("display/interactive_col_width", False, bool)
            row_height_enabled = self.settings.value("display/interactive_row_height", False, bool)
            add_data_enabled = self.settings.value("display/add_data_panel", False, bool)
            catalog_table_enabled = self.settings.value("display/catalog_table_panel", True, bool)
            profiles_toolbar_visible = self.settings.value(
                "display/profiles_toolbar_visible",
                True,
                bool,
            )
            action_ribbon_visible = self.settings.value("display/action_ribbon_visible", True, bool)
            action_ribbon_ids = self._load_saved_action_ribbon_action_ids()

            if not apply_workspace_panel_visibility:
                add_data_dock = getattr(self, "add_data_dock", None)
                catalog_table_dock = getattr(self, "catalog_table_dock", None)
                if isinstance(add_data_dock, QDockWidget):
                    add_data_enabled = bool(add_data_dock.isVisible())
                if isinstance(catalog_table_dock, QDockWidget):
                    catalog_table_enabled = bool(catalog_table_dock.isVisible())

            self._set_action_checked_silently(self.act_reorder_columns, columns_movable)
            self._set_action_checked_silently(self.col_width_action, col_width_enabled)
            self._set_action_checked_silently(self.row_height_action, row_height_enabled)
            self._set_action_checked_silently(self.add_data_action, add_data_enabled)
            self._set_action_checked_silently(self.catalog_table_action, catalog_table_enabled)
            self._set_action_checked_silently(
                self.profiles_toolbar_visibility_action,
                profiles_toolbar_visible,
            )
            self._set_action_checked_silently(
                self.action_ribbon_visibility_action, action_ribbon_visible
            )

            self._apply_columns_movable_state(columns_movable)
            self._apply_col_width_mode(col_width_enabled)
            self._apply_row_height_mode(row_height_enabled)
            if apply_workspace_panel_visibility:
                self._apply_add_data_panel_state(add_data_enabled)
                self._apply_catalog_table_panel_state(catalog_table_enabled)
            self._apply_profiles_toolbar_visibility(profiles_toolbar_visible)
            self._apply_action_ribbon_configuration(action_ribbon_ids, action_ribbon_visible)
        finally:
            self._suspend_layout_history = previous_suspend_state

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
                self.logger.exception(
                    f"Settings rollback failed for {action_label}: {restore_error}"
                )
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
        except Exception:
            try:
                self.history_manager.restore_file_state(target_path, before_state)
            except Exception as restore_error:
                self.logger.exception(f"File rollback failed for {action_type}: {restore_error}")
            raise

    def _table_setting_keys(self, *, include_columns_movable: bool = False) -> list[str]:
        prefix = self._table_settings_prefix()
        keys = [
            f"{prefix}/header_state",
            f"{prefix}/header_labels",
            f"{prefix}/header_labels_json",
            f"{prefix}/hidden_columns_json",
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

        with self._suspend_table_layout_history():
            try:
                self.active_custom_fields = self.load_active_custom_fields()
                self._rebuild_table_headers()
                self._load_header_state()
            except Exception:
                pass

            self._reload_profiles_list(select_path=path)
            self.refresh_table_preserve_view()
            self.populate_all_comboboxes()
            self._update_add_data_generated_fields()
            self._refresh_history_actions()

    def _prepare_profile_database_background(
        self,
        path: str,
        *,
        title: str,
        description: str,
        on_success,
        on_finished=None,
    ) -> str | None:
        target_path = str(Path(path))

        def _worker(ctx):
            ctx.set_status(description)
            session = self.database_session.open(target_path)
            try:
                schema_service = DatabaseSchemaService(
                    session.conn,
                    logger=self.logger,
                    data_root=self.data_root,
                )
                schema_service.init_db()
                schema_service.migrate_schema()
                return target_path
            finally:
                self.database_session.close(session.conn)

        return self._submit_background_task(
            title=title,
            description=description,
            task_fn=_worker,
            kind="exclusive",
            unique_key=f"profile.prepare.{target_path}",
            requires_profile=False,
            show_dialog=True,
            cancellable=False,
            owner=self,
            on_success=on_success,
            on_finished=on_finished,
            on_error=lambda failure: self._show_background_task_error(
                title,
                failure,
                user_message="Could not prepare the selected profile:",
            ),
        )

    def _activate_profile_in_background(
        self,
        path: str,
        *,
        save_current_header: bool = True,
        title: str = "Open Profile",
        description: str = "Preparing the selected profile database...",
        on_activated=None,
    ) -> str | None:
        if save_current_header:
            try:
                self._save_header_state(record_history=False)
            except Exception:
                pass

        prepared = {"path": None}

        def _success(prepared_path: str):
            prepared["path"] = str(prepared_path)

        def _finished():
            prepared_path = str(prepared.get("path") or "").strip()
            if not prepared_path:
                return
            self.open_database(prepared_path)
            with self._suspend_table_layout_history():
                try:
                    self.active_custom_fields = self.load_active_custom_fields()
                    self._rebuild_table_headers()
                    self._load_header_state()
                except Exception:
                    pass
                self._reload_profiles_list(select_path=prepared_path)
                self._refresh_catalog_ui_in_background(
                    select_path=prepared_path,
                    unique_key=f"catalog.ui.profile.{prepared_path}",
                    on_finished=lambda: (
                        on_activated(prepared_path) if on_activated is not None else None
                    ),
                )

        return self._prepare_profile_database_background(
            path,
            title=title,
            description=description,
            on_success=_success,
            on_finished=_finished,
        )

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
                candidates.append(("profile", self.history_manager.get_current_visible_entry()))
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
        result = run_snapshot_history_action(
            history_manager=self.history_manager,
            action_label=action_label,
            action_type=action_type,
            mutation=mutation,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            before_kind=before_kind,
            before_label=before_label,
            after_kind=after_kind,
            after_label=after_label,
            logger=self.logger,
        )
        self._refresh_history_actions()
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
        snapshot_label = label.strip() or None
        estimated_bytes = self._estimate_history_snapshot_capture_bytes()
        if not self._prepare_history_storage_for_projected_growth(
            trigger_label="manual snapshot",
            additional_bytes=estimated_bytes,
            interactive=True,
        ):
            return

        def _worker(bundle, ctx):
            ctx.set_status("Capturing a full profile snapshot...")
            snapshot = bundle.history_manager.create_manual_snapshot(snapshot_label)
            return {"snapshot_id": snapshot.snapshot_id, "label": snapshot.label}

        def _success(result):
            self.logger.info("Created snapshot %s: %s", result["snapshot_id"], result["label"])
            QMessageBox.information(self, "Snapshot Created", f"Snapshot saved:\n{result['label']}")
            self._refresh_history_actions()
            if self.history_dialog is not None and self.history_dialog.isVisible():
                self.history_dialog.refresh_data()
            self._enforce_history_storage_budget(
                trigger_label="manual snapshot",
                interactive=True,
            )

        self._submit_background_bundle_task(
            title="Create Snapshot",
            description="Creating a manual snapshot of the current profile...",
            task_fn=_worker,
            kind="read",
            unique_key="snapshot.create",
            on_success=_success,
            on_error=lambda failure: self._show_background_task_error(
                "Snapshot Error",
                failure,
                user_message="Could not create the snapshot:",
            ),
        )

    def delete_snapshot_from_history(self, snapshot_id: int):
        if self.history_manager is None:
            return
        self.history_manager.delete_snapshot_as_action(snapshot_id)
        self._refresh_history_actions()
        if self.history_dialog is not None and self.history_dialog.isVisible():
            self.history_dialog.refresh_data()

    def delete_backup_from_history(self, backup_id: int):
        if self.history_manager is None:
            return
        self.history_manager.delete_backup(backup_id)
        self._refresh_history_actions()
        if self.history_dialog is not None and self.history_dialog.isVisible():
            self.history_dialog.refresh_data()

    def restore_snapshot_from_history(self, snapshot_id: int):
        if self.history_manager is None:
            return
        if (
            QMessageBox.question(
                self,
                "Restore Snapshot",
                "Restore this snapshot into the current profile?\n\nThe current state can be undone afterward.",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        estimated_bytes = self._estimate_history_snapshot_capture_bytes()
        if not self._prepare_history_storage_for_projected_growth(
            trigger_label="snapshot restore",
            additional_bytes=estimated_bytes,
            interactive=True,
        ):
            return
        self._submit_background_bundle_task(
            title="Restore Snapshot",
            description="Restoring the selected snapshot...",
            task_fn=lambda bundle, ctx: bundle.history_manager.restore_snapshot_as_action(
                snapshot_id
            ),
            kind="write",
            unique_key="snapshot.restore",
            on_success=lambda _result: (
                self._refresh_after_history_change(),
                self._enforce_history_storage_budget(
                    trigger_label="snapshot restore",
                    interactive=True,
                ),
            ),
            on_error=lambda failure: self._show_background_task_error(
                "Restore Snapshot",
                failure,
                user_message="Could not restore the snapshot:",
            ),
        )

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

    def _isrc_generation_state(self) -> tuple[str, str]:
        prefix = (self.load_isrc_prefix() or "").upper().strip()
        if not prefix:
            return (
                "disabled",
                "No ISRC prefix is configured. Tracks can still be saved, but ISRC auto-generation stays disabled until you add one in Settings.",
            )
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}", prefix):
            return (
                "error",
                "The saved ISRC prefix is invalid. Fix it in Settings to re-enable auto-generation.",
            )

        artist_code = self.load_artist_code()
        if not re.fullmatch(r"\d{2}", artist_code or ""):
            return (
                "error",
                "The saved ISRC artist code is invalid. Fix it in Settings to re-enable auto-generation.",
            )

        return ("ready", "")

    def _next_generated_isrc(
        self,
        *,
        release_date: QDate | None = None,
        use_release_year: bool = False,
        reserved_compacts: set[str] | None = None,
    ) -> str:
        if self.conn is None or self.cursor is None:
            return ""
        state, _message = self._isrc_generation_state()
        if state != "ready":
            return ""

        prefix = (self.load_isrc_prefix() or "").upper().strip()
        artist_code = self.load_artist_code()
        year = datetime.now().year % 100
        if use_release_year and isinstance(release_date, QDate) and release_date.isValid():
            year = release_date.year() % 100
        yy = f"{year:02d}"

        claimed_compacts = {
            str(code or "").strip().upper()
            for code in (reserved_compacts or set())
            if str(code or "").strip()
        }
        for seq in range(1, 1000):
            sss = f"{seq:03d}"
            candidate_compact = f"{prefix}{yy}{artist_code}{sss}"
            if candidate_compact in claimed_compacts:
                continue
            candidate = f"{prefix[0:2]}-{prefix[2:5]}-{yy}-{artist_code}{sss}"
            try:
                if not self.is_isrc_taken_normalized(candidate):
                    return candidate
            except Exception:
                return candidate
        return ""

    # =============================================================================
    # UI helpers
    # =============================================================================
    @staticmethod
    def _create_add_data_group(title: str) -> tuple[QGroupBox, QVBoxLayout]:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)
        return group, layout

    @staticmethod
    def _create_add_data_status_field(placeholder: str) -> QLineEdit:
        field = QLineEdit()
        field.setReadOnly(True)
        field.setMinimumWidth(240)
        field.setPlaceholderText(placeholder)
        field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return field

    @staticmethod
    def _create_add_data_row(
        label_widget: QLabel,
        field_widget: QWidget,
        *,
        top_aligned: bool = False,
        label_width: int = 132,
    ) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        label_widget.setMinimumWidth(label_width)
        label_widget.setAlignment(Qt.AlignRight | (Qt.AlignTop if top_aligned else Qt.AlignVCenter))
        if field_widget.sizePolicy().horizontalPolicy() == QSizePolicy.Preferred:
            field_widget.setSizePolicy(
                QSizePolicy.Expanding, field_widget.sizePolicy().verticalPolicy()
            )
        layout.addWidget(label_widget, 0, Qt.AlignTop if top_aligned else Qt.AlignVCenter)
        layout.addWidget(field_widget, 1, Qt.AlignTop if top_aligned else Qt.AlignVCenter)
        return row

    def _preview_generated_isrc(self) -> str:
        release_date = None
        if hasattr(self, "release_date_field"):
            try:
                release_date = self.release_date_field.selectedDate()
            except Exception:
                release_date = None
        return self._next_generated_isrc(
            release_date=release_date,
            use_release_year=bool(
                hasattr(self, "prev_release_toggle") and self.prev_release_toggle.isChecked()
            ),
        )

    def _update_add_data_generated_fields(self) -> None:
        if hasattr(self, "record_id_field"):
            self.record_id_field.clear()
        if hasattr(self, "entry_date_preview_field"):
            self.entry_date_preview_field.clear()
        if not hasattr(self, "generated_isrc_field"):
            return

        state, message = self._isrc_generation_state()
        preview = self._preview_generated_isrc()
        self.generated_isrc_field.setText(preview)
        if hasattr(self, "prev_release_toggle"):
            self.prev_release_toggle.setEnabled(state == "ready")

        if preview:
            self.generated_isrc_field.setPlaceholderText(
                "Generated automatically using the current ISRC settings."
            )
            self.generated_isrc_field.setToolTip(
                "Next available ISRC based on the current release date and ISRC settings."
            )
        elif state == "ready":
            self.generated_isrc_field.setPlaceholderText(
                "No free ISRC sequence is currently available."
            )
            self.generated_isrc_field.setToolTip(
                "ISRC auto-generation is enabled, but no free sequence is currently available for the active year and artist code."
            )
        elif state == "disabled":
            self.generated_isrc_field.setPlaceholderText(
                "Auto-generation disabled until an ISRC prefix is set."
            )
            self.generated_isrc_field.setToolTip(message)
        else:
            self.generated_isrc_field.setPlaceholderText(
                "Fix ISRC settings to re-enable auto-generation."
            )
            self.generated_isrc_field.setToolTip(message)

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
            key = 1 if t.lower() in ("1", "true", "yes", "y", "checked") else 0
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
        self._apply_saved_column_visibility()
        self._rebuild_search_column_choices()
        self._refresh_column_visibility_menu()

    @staticmethod
    def _catalog_combo_values_from_connection(conn: sqlite3.Connection) -> dict[str, list[str]]:
        def _values(query: str) -> list[str]:
            try:
                return [
                    str(row[0] or "").strip()
                    for row in conn.execute(query).fetchall()
                    if str(row[0] or "").strip()
                ]
            except sqlite3.OperationalError:
                return []

        return {
            "artists": [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT name FROM Artists WHERE name IS NOT NULL AND name != '' ORDER BY name"
                ).fetchall()
            ],
            "albums": [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT title FROM Albums WHERE title IS NOT NULL AND title != '' ORDER BY title"
                ).fetchall()
            ],
            "upcs": _values(
                """
                SELECT value
                FROM (
                    SELECT upc AS value
                    FROM Tracks
                    WHERE upc IS NOT NULL AND upc != ''
                    UNION
                    SELECT upc AS value
                    FROM Releases
                    WHERE upc IS NOT NULL AND upc != ''
                )
                ORDER BY value
                """
            ),
            "genres": [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT genre FROM Tracks WHERE genre IS NOT NULL AND genre != '' ORDER BY genre"
                ).fetchall()
            ],
            "catalog_numbers": _values(
                """
                SELECT value
                FROM (
                    SELECT catalog_number AS value
                    FROM Tracks
                    WHERE catalog_number IS NOT NULL AND catalog_number != ''
                    UNION
                    SELECT catalog_number AS value
                    FROM Releases
                    WHERE catalog_number IS NOT NULL AND catalog_number != ''
                )
                ORDER BY value
                """
            ),
        }

    def _apply_catalog_combo_values(self, combo_values: dict[str, list[str]]) -> None:
        self._populate_combobox(self.artist_field, combo_values.get("artists", []))
        self._populate_combobox(
            self.additional_artist_field, combo_values.get("artists", []), allow_empty=True
        )
        self._populate_combobox(
            self.album_title_field, combo_values.get("albums", []), allow_empty=True
        )
        self._populate_combobox(self.upc_field, combo_values.get("upcs", []), allow_empty=True)
        self._populate_combobox(self.genre_field, combo_values.get("genres", []), allow_empty=True)
        self._populate_combobox(
            self.catalog_number_field,
            combo_values.get("catalog_numbers", []),
            allow_empty=True,
        )

    def populate_all_comboboxes(self):
        if self.conn is None:
            return
        self._apply_catalog_combo_values(self._catalog_combo_values_from_connection(self.conn))

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
        self.audio_file_field.clear()
        self.album_art_field.clear()
        self.release_date_field.setSelectedDate(QDate.currentDate())
        self.iswc_field.clear()
        self.upc_field.setCurrentText("")
        self.catalog_number_field.setCurrentText("")
        self.buma_work_number_field.clear()
        self.genre_field.setCurrentText("")
        self.prev_release_toggle.setChecked(False)
        self._update_add_data_generated_fields()

    # =============================================================================
    # Search / table refresh (with view preservation)
    # =============================================================================
    def _rebuild_search_column_choices(self):
        cur_data = (
            self.search_column_combo.currentData() if self.search_column_combo.count() else -1
        )
        self.search_column_combo.blockSignals(True)
        self.search_column_combo.clear()
        self.search_column_combo.addItem("All columns", -1)

        headers = [
            self.table.horizontalHeaderItem(idx).text()
            for idx in range(self.table.columnCount())
            if self.table.horizontalHeaderItem(idx) is not None
        ]
        for idx, name in enumerate(headers):
            if self.table.isColumnHidden(idx):
                continue
            self.search_column_combo.addItem(name, idx)

        restore = self.search_column_combo.findData(cur_data)
        self.search_column_combo.setCurrentIndex(restore if restore != -1 else 0)
        self.search_column_combo.blockSignals(False)

    def apply_search_filter(self):
        text = self.search_field.text().lower()
        col_sel = self.search_column_combo.currentData()  # -1 = all
        explicit_track_ids = getattr(self, "_explicit_row_filter_track_ids", None)
        for row in range(self.table.rowCount()):
            if col_sel == -1:
                match = any(
                    self.table.item(row, c) and text in self.table.item(row, c).text().lower()
                    for c in range(self.table.columnCount())
                )
            else:
                it = self.table.item(row, int(col_sel))
                match = bool(it and text in it.text().lower())
            if explicit_track_ids is not None:
                row_track_id = self._track_id_for_table_row(row)
                match = bool(match and row_track_id in explicit_track_ids)
            self.table.setRowHidden(row, not match)
        self._update_count_label()

        self._update_duration_label()
        self._refresh_workspace_selection_scopes()

    # =============================================================================
    # Header label helpers for robust persistence (rev09)
    # =============================================================================
    def _header_labels(self):
        m = self.table.model()
        return [
            str(m.headerData(c, Qt.Horizontal, Qt.DisplayRole) or "")
            for c in range(m.columnCount())
        ]

    def _labels_with_occurrence(self, labels):
        seen = {}
        out = []
        for lbl in labels:
            n = seen.get(lbl, 0)
            out.append((lbl, n))
            seen[lbl] = n + 1
        return out

    def reset_search(self):
        self._explicit_row_filter_track_ids = None
        self.search_field.clear()
        idx = self.search_column_combo.findData(-1)  # “All columns”
        self.search_column_combo.setCurrentIndex(idx if idx != -1 else 0)
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row, False)
        self.refresh_table()
        self._update_count_label()
        self._update_duration_label()
        self._refresh_workspace_selection_scopes()

    def _load_catalog_ui_dataset(
        self,
        *,
        custom_field_definitions: CustomFieldDefinitionService | None = None,
        catalog_reads: CatalogReadService | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, object]:
        active_custom_fields = (
            custom_field_definitions.list_active_fields()
            if custom_field_definitions is not None
            else self.load_active_custom_fields()
        )
        active_catalog_reads = catalog_reads or self.catalog_reads
        active_conn = conn or self.conn
        if active_catalog_reads is None or active_conn is None:
            raise ValueError("Catalog dataset services are not available.")
        rows, cf_map = active_catalog_reads.fetch_rows_with_customs(active_custom_fields)
        return {
            "active_custom_fields": active_custom_fields,
            "rows": rows,
            "cf_map": cf_map,
            "combo_values": self._catalog_combo_values_from_connection(active_conn),
        }

    def _populate_table_from_dataset(
        self, rows: list[tuple], cf_map: dict[tuple[int, int], str]
    ) -> None:
        base_cols = len(self.BASE_HEADERS)
        self.table.setRowCount(len(rows))

        for row_idx, row_data in enumerate(rows):
            for col_idx in range(base_cols):
                header = self.table.horizontalHeaderItem(col_idx).text()
                val_raw = row_data[col_idx]
                if header == "Track Length (hh:mm:ss)":
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
                    val = "" if val_raw is None else str(val_raw)
                    self.table.setItem(row_idx, col_idx, self._make_item(col_idx, val))

            track_id = row_data[0]
            for offset, field in enumerate(self.active_custom_fields):
                val = cf_map.get((track_id, field["id"]), "")
                self.table.setItem(
                    row_idx,
                    base_cols + offset,
                    self._make_item(base_cols + offset, val, custom_def=field),
                )

    def _apply_catalog_ui_dataset(self, dataset: dict[str, object]) -> None:
        self.active_custom_fields = list(dataset.get("active_custom_fields") or [])
        self._rebuild_table_headers()
        self._populate_table_from_dataset(
            list(dataset.get("rows") or []),
            dict(dataset.get("cf_map") or {}),
        )
        self._apply_catalog_combo_values(dict(dataset.get("combo_values") or {}))
        self.table.resizeColumnsToContents()
        self._update_count_label()
        self._update_duration_label()
        self._apply_blob_badges()

    def _refresh_catalog_ui_in_background(
        self,
        *,
        focus_id: int | None = None,
        select_path: str | None = None,
        on_finished=None,
        unique_key: str = "catalog.ui.refresh",
        retry_count: int = 0,
    ) -> str | None:
        if self.conn is None:
            return None
        state = self._capture_view_state()
        sort_enabled = self.table.isSortingEnabled()
        if sort_enabled:
            self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._update_count_label()
        self._update_duration_label()

        def _worker(bundle, ctx):
            ctx.set_status("Loading catalog rows and lookup values...")
            return self._load_catalog_ui_dataset(
                custom_field_definitions=bundle.custom_field_definitions,
                catalog_reads=bundle.catalog_reads,
                conn=bundle.conn,
            )

        def _success(dataset: dict[str, object]):
            try:
                self.conn.commit()
            except Exception:
                pass
            with self._suspend_table_layout_history():
                self._apply_catalog_ui_dataset(dataset)
                try:
                    self._load_header_state()
                except Exception as e:
                    self.logger.warning("Failed to load header state: %s", e)
                self._restore_view_state(state)
                if focus_id is not None:
                    self._select_row_by_id(focus_id)
                if select_path:
                    self._reload_profiles_list(select_path=select_path)
                if sort_enabled:
                    self.table.setSortingEnabled(True)
                    try:
                        self.table.sortItems(self._last_sort_col, self._last_sort_order)
                    except Exception:
                        pass
                self._update_add_data_generated_fields()
                self._refresh_history_actions()
                if on_finished is not None:
                    on_finished()

        def _finished():
            if not sort_enabled:
                self.table.setSortingEnabled(False)

        task_id = self._submit_background_bundle_task(
            title="Load Catalog",
            description="Loading catalog rows and lookup values...",
            task_fn=_worker,
            kind="read",
            unique_key=unique_key,
            show_dialog=False,
            owner=self,
            on_success=_success,
            on_error=lambda failure: (
                QTimer.singleShot(
                    100,
                    lambda: self._refresh_catalog_ui_in_background(
                        focus_id=focus_id,
                        select_path=select_path,
                        on_finished=on_finished,
                        unique_key=unique_key,
                        retry_count=retry_count + 1,
                    ),
                )
                if retry_count < 3
                and "exclusive database task is currently running"
                in str(failure.message or "").lower()
                else self._show_background_task_error(
                    "Load Catalog",
                    failure,
                    user_message="Could not load the catalog view:",
                )
            ),
            on_finished=_finished,
        )
        return task_id

    def refresh_table(self):
        # Ensure custom fields and headers are ready
        dataset = self._load_catalog_ui_dataset()

        previous_suspend_state = self._suspend_layout_history
        self._suspend_layout_history = True
        try:
            _prev_sort_enabled = self.table.isSortingEnabled()
            if _prev_sort_enabled:
                self.table.setSortingEnabled(False)
            self.table.setSortingEnabled(False)
            self.table.setRowCount(0)
            self._apply_catalog_ui_dataset(dataset)
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
        if not hasattr(self, "duration_label") or self.duration_label is None:
            return
        # find column index for Track Length
        col_idx = -1
        try:
            for c in range(self.table.columnCount()):
                if self.table.horizontalHeaderItem(c).text() == "Track Length (hh:mm:ss)":
                    col_idx = c
                    break
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
        with self._suspend_table_layout_history():
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
                self.logger.warning("Failed to rebind sectionMoved: %s", e)

            # Then load header state (visual order + widths)
            try:
                self._load_header_state()
            except Exception as e:
                self.logger.warning("Failed to load header state: %s", e)

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

    @staticmethod
    def _media_file_filter(media_key: str) -> str:
        if media_key == "audio_file":
            return "Audio (*.wav *.aif *.aiff *.mp3 *.flac *.m4a *.aac *.ogg *.opus);;All files (*)"
        return "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff);;All files (*)"

    @staticmethod
    def _audio_format_label(suffix: str | None) -> str:
        labels = {
            ".aac": "AAC",
            ".aif": "AIFF",
            ".aiff": "AIFF",
            ".flac": "FLAC",
            ".m4a": "M4A",
            ".mp3": "MP3",
            ".mp4": "MP4",
            ".oga": "OGA",
            ".ogg": "OGG",
            ".opus": "Opus",
            ".wav": "WAV",
        }
        clean_suffix = str(suffix or "").strip().lower()
        if clean_suffix in labels:
            return labels[clean_suffix]
        if clean_suffix.startswith(".") and len(clean_suffix) > 1:
            return clean_suffix[1:].upper()
        return "audio"

    @classmethod
    def _lossy_audio_suffix_for_values(
        cls,
        *,
        path_value: str | None = None,
        filename: str | None = None,
        mime_type: str | None = None,
    ) -> str | None:
        for candidate in (filename, path_value):
            clean_candidate = str(candidate or "").strip()
            if not clean_candidate:
                continue
            suffix = Path(clean_candidate).suffix.lower()
            if suffix in PROVENANCE_ONLY_SUFFIXES:
                return suffix
        clean_mime = str(mime_type or "").strip().lower()
        mime_suffixes = {
            "audio/aac": ".aac",
            "audio/mp4": ".m4a",
            "audio/mpeg": ".mp3",
            "audio/ogg": ".ogg",
            "audio/opus": ".opus",
            "video/mp4": ".mp4",
        }
        return mime_suffixes.get(clean_mime)

    @classmethod
    def _lossy_primary_audio_warning_text(
        cls,
        *,
        path_value: str | None = None,
        filename: str | None = None,
        mime_type: str | None = None,
        short: bool = False,
    ) -> str:
        suffix = cls._lossy_audio_suffix_for_values(
            path_value=path_value,
            filename=filename,
            mime_type=mime_type,
        )
        if not suffix:
            return ""
        format_label = cls._audio_format_label(suffix)
        if short:
            return f"Lossy primary audio selected ({format_label})."
        return (
            f"Lossy primary audio selected ({format_label}). Direct watermark and master-audio "
            "workflows use WAV, FLAC, or AIFF, so this attachment will be treated as a lossy "
            "primary source."
        )

    @staticmethod
    def _set_lossy_audio_warning_label(label: QLabel | None, warning_text: str) -> None:
        if label is None:
            return
        label.setText(warning_text)
        label.setVisible(bool(warning_text))

    def _refresh_line_edit_lossy_audio_warning(self, line_edit: QLineEdit) -> None:
        warning_label = getattr(line_edit, "_lossy_audio_warning_label", None)
        warning_text = self._lossy_primary_audio_warning_text(
            path_value=line_edit.text(),
            short=True,
        )
        self._set_lossy_audio_warning_label(warning_label, warning_text)

    def _confirm_lossy_primary_audio_selection(
        self,
        values,
        *,
        title: str,
        action_label: str,
        parent_widget: QWidget | None = None,
    ) -> bool:
        entries: list[str] = []
        for value in values or []:
            clean_value = str(value or "").strip()
            suffix = self._lossy_audio_suffix_for_values(path_value=clean_value)
            if not clean_value or not suffix:
                continue
            name = Path(clean_value).name or clean_value
            entries.append(f"{name} ({self._audio_format_label(suffix)})")
        if not entries:
            return True
        extra_note = "" if len(entries) <= 8 else f"\n…and {len(entries) - 8} more."
        message = (
            f"{action_label} will keep {len(entries)} lossy audio file"
            f"{'s' if len(entries) != 1 else ''} as primary catalog audio.\n\n"
            "Lossy primary audio is shown with the lossy badge, and direct watermark/master "
            "workflows use WAV, FLAC, or AIFF.\n\n"
            "Continue?\n\n- "
            + "\n- ".join(entries[:8])
            + extra_note
        )
        return (
            QMessageBox.question(
                parent_widget or self,
                title,
                message,
                QMessageBox.Yes | QMessageBox.No,
            )
            == QMessageBox.Yes
        )

    def _browse_track_media_file(self, media_key: str, *, parent_widget=None) -> str:
        title = "Choose Audio File" if media_key == "audio_file" else "Choose Album Art"
        path, _ = QFileDialog.getOpenFileName(
            parent_widget or self,
            title,
            "",
            self._media_file_filter(media_key),
        )
        return path or ""

    def _choose_media_into_line_edit(
        self, media_key: str, line_edit: QLineEdit, *, parent_widget=None
    ) -> None:
        path = self._browse_track_media_file(media_key, parent_widget=parent_widget)
        if path:
            line_edit.setText(path)
            if media_key == "audio_file":
                self._refresh_line_edit_lossy_audio_warning(line_edit)

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
            QMessageBox.warning(
                self, "Invalid UPC/EAN", "UPC/EAN must be 12 or 13 digits (or leave empty)."
            )
            return
        try:
            # ISWC (optional)
            raw_iswc = (self.iswc_field.text() or "").strip()
            iso_iswc = None
            if raw_iswc:
                iso_iswc = to_iso_iswc(raw_iswc)
                if not iso_iswc or not is_valid_iswc_any(iso_iswc):
                    QMessageBox.warning(
                        self,
                        "Invalid ISWC",
                        "ISWC must be like T-123.456.789-0 or T1234567890 (checksum 0–9 or X), or leave empty.",
                    )
                    return

            generated_iso = ""
            comp = ""
            if self._isrc_generation_state()[0] == "ready":
                generated_iso = self.generate_isrc()
                if not generated_iso:
                    QMessageBox.critical(
                        self,
                        "ISRC Error",
                        "No free ISRC sequence is currently available for the active year and artist code.",
                    )
                    return
                comp = to_compact_isrc(generated_iso)
                if not comp or not is_valid_isrc_compact_or_iso(generated_iso):
                    QMessageBox.critical(
                        self,
                        "ISRC Error",
                        "Generated ISRC is invalid. Check prefix and artist-code settings.",
                    )
                    return

                if self.is_isrc_taken_normalized(generated_iso):
                    QMessageBox.critical(
                        self, "ISRC Error", "A track with this ISRC already exists."
                    )
                    return

            release_date_sql = self.release_date_field.selectedDate().toString("yyyy-MM-dd")

            track_seconds = hms_to_seconds(
                self.track_len_h.value(), self.track_len_m.value(), self.track_len_s.value()
            )
            self._log_trace(
                "track.create.prepare",
                message="Preparing track insert",
                isrc=generated_iso,
                isrc_compact=comp,
                track_title=self.track_title_field.text().strip(),
            )
            payload = TrackCreatePayload(
                isrc=generated_iso,
                track_title=self.track_title_field.text().strip(),
                artist_name=self.artist_field.currentText(),
                additional_artists=self._parse_additional_artists(
                    self.additional_artist_field.currentText()
                ),
                album_title=self.album_title_field.currentText().strip() or None,
                release_date=release_date_sql,
                track_length_sec=track_seconds,
                iswc=(iso_iswc or None),
                upc=(self.upc_field.currentText().strip() or None),
                genre=(self.genre_field.currentText().strip() or None),
                catalog_number=(self.catalog_number_field.currentText().strip() or None),
                buma_work_number=(self.buma_work_number_field.text().strip() or None),
                audio_file_source_path=(self.audio_file_field.text().strip() or None),
                album_art_source_path=(self.album_art_field.text().strip() or None),
            )
            if payload.audio_file_source_path and not self._confirm_lossy_primary_audio_selection(
                [payload.audio_file_source_path],
                title="Save Track Media",
                action_label="Saving this track",
            ):
                return
            media_modes = self._choose_track_media_storage_modes(
                audio_source_path=payload.audio_file_source_path,
                album_art_source_path=payload.album_art_source_path,
                title="Save Track Media",
            )
            if media_modes is None:
                return
            payload.audio_file_storage_mode, payload.album_art_storage_mode = media_modes

            def mutation():
                created_track_id = self.track_service.create_track(payload)
                release_ids = self._sync_releases_for_tracks([created_track_id])
                return created_track_id, release_ids

            track_id, release_ids = self._run_snapshot_history_action(
                action_label=f"Create Track: {payload.track_title}",
                action_type="track.create",
                entity_type="Track",
                entity_id=payload.track_title,
                payload={
                    "track_title": payload.track_title,
                    "artist_name": payload.artist_name,
                    "album_title": payload.album_title,
                },
                mutation=mutation,
            )
            self._log_event(
                "track.create",
                "Track created",
                track_id=track_id,
                isrc=generated_iso,
                track_title=self.track_title_field.text().strip(),
                release_ids=release_ids,
            )
            self._audit("CREATE", "Track", ref_id=track_id, details=f"isrc={generated_iso}")
            self._audit_commit()

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

    def open_add_album_dialog(self):
        dlg = AlbumEntryDialog(self)
        dlg.exec()

    def open_track_editor(self, track_id: int, *, batch_track_ids: list[int] | None = None):
        try:
            dlg = EditDialog(int(track_id), self, batch_track_ids=batch_track_ids)
        except ValueError as exc:
            QMessageBox.warning(self, "Edit Entry", str(exc))
            return
        dlg.exec()
        self.populate_all_comboboxes()

    def open_selected_editor(self, track_id: int | None = None):
        if isinstance(track_id, bool):
            track_id = None
        if track_id is None:
            selected_ids = self._selected_track_ids()
            if not selected_ids:
                QMessageBox.warning(
                    self,
                    "Edit Entry",
                    "Could not determine the selected track. Select one or more catalog rows and try again.",
                )
                return
            track_id = selected_ids[0]
            batch_ids = selected_ids
        else:
            try:
                track_id = int(track_id)
            except (TypeError, ValueError):
                track_id = 0
            if track_id <= 0:
                QMessageBox.warning(
                    self,
                    "Edit Entry",
                    "Could not determine the selected track. Select one or more catalog rows and try again.",
                )
                return
            batch_ids = self._selected_track_ids()
            if track_id not in batch_ids:
                batch_ids = [track_id]
        self.open_track_editor(int(track_id), batch_track_ids=batch_ids)

    def edit_entry(self, item):
        row_idx = item.row()
        track_id = self._track_id_for_table_row(row_idx)
        if track_id is None:
            QMessageBox.warning(self, "Edit Entry", "Could not determine the selected track.")
            return
        self.open_selected_editor(track_id)

    def _track_id_for_table_row(self, row_idx: int) -> int | None:
        try:
            track_id = self._get_row_pk(int(row_idx))
        except Exception:
            track_id = None
        if track_id is None:
            row_id_item = self.table.item(int(row_idx), 0)
            if row_id_item is None:
                return None
            text = (row_id_item.text() or "").strip()
            if not text.isdigit():
                return None
            track_id = int(text)
        if track_id <= 0:
            return None
        return track_id

    def _selected_track_ids(self) -> list[int]:
        track_ids: list[int] = []
        seen: set[int] = set()
        candidate_rows: list[int] = []
        candidate_row_set: set[int] = set()
        has_hidden_rows = any(self.table.isRowHidden(row) for row in range(self.table.rowCount()))

        def _remember_row(row_idx: int) -> None:
            normalized_row = int(row_idx)
            if normalized_row < 0:
                return
            if has_hidden_rows and self.table.isRowHidden(normalized_row):
                return
            if normalized_row in candidate_row_set:
                return
            candidate_row_set.add(normalized_row)
            candidate_rows.append(normalized_row)

        sel_model = self.table.selectionModel()
        if sel_model is not None:
            for index in sel_model.selectedRows():
                _remember_row(index.row())

        for selection_range in self.table.selectedRanges():
            for row_idx in range(selection_range.topRow(), selection_range.bottomRow() + 1):
                _remember_row(row_idx)

        selected_items = self.table.selectedItems()
        for item in selected_items:
            _remember_row(item.row())

        if sel_model is not None:
            for index in sel_model.selectedIndexes():
                _remember_row(index.row())

        current_row = self.table.currentRow()
        if not candidate_rows and current_row >= 0:
            _remember_row(current_row)

        for row_idx in candidate_rows:
            track_id = self._track_id_for_table_row(row_idx)
            if track_id is None or track_id in seen:
                continue
            seen.add(track_id)
            track_ids.append(track_id)
        return track_ids

    def open_gs1_dialog(self, track_id: int | None = None):
        if isinstance(track_id, bool):
            track_id = None
        if track_id is None:
            selected_ids = self._selected_track_ids()
            if not selected_ids:
                QMessageBox.information(
                    self,
                    "GS1 Metadata",
                    "Select a catalog row first, then open the GS1 metadata dialog.",
                )
                return
            track_id = selected_ids[0]
            batch_ids = selected_ids
        else:
            try:
                track_id = int(track_id)
            except (TypeError, ValueError):
                track_id = 0
            if track_id <= 0:
                selected_ids = self._selected_track_ids()
                if not selected_ids:
                    QMessageBox.warning(
                        self,
                        "GS1 Metadata",
                        "Could not determine the selected track. Select a catalog row and try again.",
                    )
                    return
                track_id = selected_ids[0]
            batch_ids = self._selected_track_ids()
            if track_id not in batch_ids:
                batch_ids.insert(0, track_id)
        if int(track_id) <= 0:
            QMessageBox.warning(
                self,
                "GS1 Metadata",
                "Could not determine the selected track. Select a catalog row and try again.",
            )
            return
        try:
            dlg = GS1MetadataDialog(
                app=self, track_id=track_id, batch_track_ids=batch_ids, parent=self
            )
        except ValueError as exc:
            QMessageBox.warning(self, "GS1 Metadata", str(exc))
            return
        dlg.exec()

    def _current_profile_name(self) -> str | None:
        path = str(getattr(self, "current_db_path", "") or "").strip()
        return Path(path).name if path else None

    @staticmethod
    def _normalize_track_ids(track_ids) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for value in track_ids or []:
            try:
                track_id = int(value)
            except (TypeError, ValueError):
                continue
            if track_id <= 0 or track_id in seen:
                continue
            seen.add(track_id)
            normalized.append(track_id)
        return normalized

    @staticmethod
    def _first_non_blank(*values):
        for value in values:
            if isinstance(value, str):
                text = value.strip()
                if text:
                    return text
            elif value not in (None, "", [], {}, ()):
                return value
        return None

    def _selected_or_visible_track_ids(self) -> list[int]:
        row_count = self.table.rowCount()
        visible_ids: list[int] = []
        if any(self.table.isRowHidden(row) for row in range(row_count)):
            for row in range(row_count):
                if self.table.isRowHidden(row):
                    continue
                track_id = self._track_id_for_table_row(row)
                if track_id is not None:
                    visible_ids.append(track_id)
            return self._normalize_track_ids(visible_ids)
        return self._normalize_track_ids(self._selected_track_ids())

    def _current_visible_track_ids(self) -> list[int]:
        visible_ids: list[int] = []
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            track_id = self._track_id_for_table_row(row)
            if track_id is not None:
                visible_ids.append(track_id)
        return self._normalize_track_ids(visible_ids)

    def _bulk_audio_attach_scope_track_ids(
        self, track_ids: list[int] | None = None
    ) -> tuple[list[int], str]:
        explicit_ids = self._normalize_track_ids(track_ids)
        if explicit_ids:
            return explicit_ids, "selected tracks"
        selected_ids = self._normalize_track_ids(self._selected_track_ids())
        if selected_ids:
            return selected_ids, "current selection"
        visible_ids = self._current_visible_track_ids()
        return visible_ids, "visible catalog rows"

    def _catalog_track_choices(self) -> list[TrackChoice]:
        header_names = {
            str(self.table.horizontalHeaderItem(column).text() or ""): column
            for column in range(self.table.columnCount())
            if self.table.horizontalHeaderItem(column) is not None
        }
        title_column = header_names.get("Track Title")
        artist_column = header_names.get("Artist")
        album_column = header_names.get("Album Title")
        choices: list[TrackChoice] = []
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            track_id = self._track_id_for_table_row(row)
            if track_id is None:
                continue
            title_item = self.table.item(row, title_column) if title_column is not None else None
            artist_item = self.table.item(row, artist_column) if artist_column is not None else None
            album_item = self.table.item(row, album_column) if album_column is not None else None
            title = (
                str(title_item.text() or "").strip()
                if title_item is not None
                else self._get_track_title(track_id)
            )
            subtitle = " / ".join(
                part
                for part in (
                    str(artist_item.text() or "").strip() if artist_item is not None else "",
                    str(album_item.text() or "").strip() if album_item is not None else "",
                )
                if part
            )
            choices.append(TrackChoice(track_id=int(track_id), title=title, subtitle=subtitle))
        return choices

    def _select_track_ids_in_table(self, track_ids, *, replace: bool = True) -> None:
        normalized_ids = set(self._normalize_track_ids(track_ids))
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return
        if replace:
            self.table.clearSelection()
        current_index = None
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            track_id = self._track_id_for_table_row(row)
            if track_id not in normalized_ids:
                continue
            index = self.table.model().index(row, 0)
            selection_model.select(
                index,
                QItemSelectionModel.Select | QItemSelectionModel.Rows,
            )
            if current_index is None:
                current_index = index
        if current_index is not None:
            selection_model.setCurrentIndex(current_index, QItemSelectionModel.NoUpdate)

    def _refresh_workspace_selection_scopes(self) -> None:
        panels = [
            getattr(self, "release_browser_dialog", None),
            getattr(self, "work_browser_dialog", None),
        ]
        for panel in panels:
            refresh_scope = getattr(panel, "refresh_selection_scope", None)
            if callable(refresh_scope):
                refresh_scope()

    def _on_catalog_selection_changed(self) -> None:
        self._refresh_workspace_selection_scopes()

    def _set_explicit_track_filter(
        self, track_ids: list[int] | None, *, source_label: str | None = None
    ) -> None:
        normalized_ids = self._normalize_track_ids(track_ids)
        self._explicit_row_filter_track_ids = set(normalized_ids) if normalized_ids else None
        self.apply_search_filter()
        if source_label:
            count = len(normalized_ids)
            message = (
                f"Filtered catalog to {count} track{'s' if count != 1 else ''} from {source_label}."
                if normalized_ids
                else f"Cleared explicit filter from {source_label}."
            )
            if self.statusBar() is not None:
                self.statusBar().showMessage(message, 5000)

    def _replace_catalog_track_filter(
        self, track_ids: list[int] | None, *, source_label: str | None = None
    ) -> None:
        normalized_ids = self._normalize_track_ids(track_ids)
        self.search_field.blockSignals(True)
        self.search_field.clear()
        self.search_field.blockSignals(False)
        self.search_column_combo.blockSignals(True)
        all_columns_index = self.search_column_combo.findData(-1)
        self.search_column_combo.setCurrentIndex(
            all_columns_index if all_columns_index != -1 else 0
        )
        self.search_column_combo.blockSignals(False)
        self._explicit_row_filter_track_ids = set(normalized_ids) if normalized_ids else None
        self.apply_search_filter()
        if normalized_ids:
            self._select_track_ids_in_table(normalized_ids)
        elif self.table.rowCount():
            self.table.clearSelection()
        if source_label and self.statusBar() is not None:
            count = len(normalized_ids)
            message = (
                f"Filtered catalog to {count} track{'s' if count != 1 else ''} from {source_label}."
                if normalized_ids
                else f"Cleared explicit filter from {source_label}."
            )
            self.statusBar().showMessage(message, 5000)
        self._refresh_workspace_selection_scopes()

    def _release_choices(self) -> list[tuple[int, str]]:
        if self.release_service is None:
            return []
        choices: list[tuple[int, str]] = []
        for release in self.release_service.list_releases():
            label = release.title
            if release.primary_artist:
                label = f"{label} — {release.primary_artist}"
            choices.append((release.id, label))
        return choices

    def _release_context_for_track(
        self,
        track_id: int,
        *,
        release_service: ReleaseService | None = None,
    ) -> tuple[ReleaseRecord | None, ReleaseTrackPlacement | None]:
        active_release_service = release_service or self.release_service
        if active_release_service is None:
            return None, None
        release = active_release_service.find_primary_release_for_track(track_id)
        if release is None:
            return None, None
        summary = active_release_service.fetch_release_summary(release.id)
        if summary is None:
            return release, None
        for placement in summary.tracks:
            if placement.track_id == int(track_id):
                return summary.release, placement
        return summary.release, None

    def _effective_artwork_payload_for_track(
        self,
        track_id: int,
        *,
        snapshot: TrackSnapshot | None = None,
        track_service: TrackService | None = None,
        load_bytes: bool = True,
    ) -> ArtworkPayload | None:
        try:
            active_track_service = track_service or self.track_service
            if active_track_service is None:
                return None
            source_snapshot = snapshot or active_track_service.fetch_track_snapshot(track_id)
            if source_snapshot is None:
                return None
            has_album_art = bool(
                source_snapshot.album_art_path
                or source_snapshot.album_art_blob_b64
                or source_snapshot.album_art_filename
                or int(source_snapshot.album_art_size_bytes or 0) > 0
            )
            if not has_album_art:
                return None
            fallback_mime_type = (
                str(source_snapshot.album_art_mime_type or "").strip() or "image/jpeg"
            )
            if not load_bytes:
                return ArtworkPayload(data=b"", mime_type=fallback_mime_type)
            data, mime_type = active_track_service.fetch_media_bytes(track_id, "album_art")
            return ArtworkPayload(data=data, mime_type=mime_type or fallback_mime_type)
        except Exception:
            return None

    @staticmethod
    def _display_tag_value(value) -> str:
        if isinstance(value, ArtworkPayload):
            return f"<Artwork {value.mime_type or 'image'}>"
        if value is None:
            return ""
        if isinstance(value, bytes):
            return f"<{len(value)} bytes>"
        return str(value)

    def _catalog_tag_data_for_track(
        self,
        track_id: int,
        *,
        snapshot: TrackSnapshot | None = None,
        track_service: TrackService | None = None,
        release_service: ReleaseService | None = None,
        include_artwork_bytes: bool = True,
    ):
        active_track_service = track_service or self.track_service
        if active_track_service is None:
            raise ValueError("Track service is not available")
        return build_catalog_tag_data(
            track_id,
            track_service=active_track_service,
            release_service=release_service or self.release_service,
            release_policy="primary",
            include_artwork_bytes=include_artwork_bytes,
        )

    def _release_payload_for_track_ids(
        self,
        track_ids: list[int],
        *,
        existing_release: ReleaseRecord | None = None,
        existing_summary=None,
        artwork_source_path: str | None = None,
        clear_artwork: bool = False,
        track_service: TrackService | None = None,
        release_service: ReleaseService | None = None,
        profile_name: str | None = None,
    ) -> ReleasePayload:
        active_track_service = track_service or self.track_service
        if active_track_service is None:
            raise ValueError("Track service is not available.")
        normalized_ids = self._normalize_track_ids(track_ids)
        snapshots = [
            snapshot
            for track_id in normalized_ids
            if (snapshot := active_track_service.fetch_track_snapshot(track_id)) is not None
        ]
        if not snapshots:
            raise ValueError("No valid tracks were available to build release metadata.")

        title = self._first_non_blank(
            *[snapshot.album_title for snapshot in snapshots],
            existing_release.title if existing_release is not None else None,
            snapshots[0].track_title,
        )
        clean_title = str(title or "").strip()
        placements: list[ReleaseTrackPlacement] = []
        existing_placements = {
            placement.track_id: placement
            for placement in (
                (existing_summary.tracks if existing_summary is not None else []) or []
            )
        }
        for sequence_number, snapshot in enumerate(snapshots, start=1):
            existing = existing_placements.get(snapshot.track_id)
            placements.append(
                ReleaseTrackPlacement(
                    track_id=snapshot.track_id,
                    disc_number=int(existing.disc_number if existing is not None else 1),
                    track_number=int(
                        existing.track_number if existing is not None else sequence_number
                    ),
                    sequence_number=sequence_number,
                )
            )

        derived_artwork_source = artwork_source_path
        if (
            not clear_artwork
            and not derived_artwork_source
            and (existing_release is None or not existing_release.artwork_path)
        ):
            for snapshot in snapshots:
                resolved = active_track_service.resolve_media_path(snapshot.album_art_path)
                if resolved is not None and resolved.exists():
                    derived_artwork_source = str(resolved)
                    break

        return ReleasePayload(
            title=clean_title or f"Release {snapshots[0].track_id}",
            version_subtitle=(
                existing_release.version_subtitle if existing_release is not None else None
            ),
            primary_artist=self._first_non_blank(
                existing_release.primary_artist if existing_release is not None else None,
                *[snapshot.artist_name for snapshot in snapshots],
            ),
            album_artist=self._first_non_blank(
                existing_release.album_artist if existing_release is not None else None,
                *[snapshot.artist_name for snapshot in snapshots],
            ),
            release_type=(
                existing_release.release_type
                if existing_release is not None and existing_release.release_type
                else ReleaseService.infer_release_type(
                    title=clean_title,
                    track_count=len(snapshots),
                )
            ),
            release_date=self._first_non_blank(
                existing_release.release_date if existing_release is not None else None,
                *[snapshot.release_date for snapshot in snapshots],
            ),
            original_release_date=(
                existing_release.original_release_date if existing_release is not None else None
            ),
            label=self._first_non_blank(
                existing_release.label if existing_release is not None else None,
                *[snapshot.publisher for snapshot in snapshots],
            ),
            sublabel=existing_release.sublabel if existing_release is not None else None,
            catalog_number=self._first_non_blank(
                existing_release.catalog_number if existing_release is not None else None,
                *[snapshot.catalog_number for snapshot in snapshots],
            ),
            upc=self._first_non_blank(
                existing_release.upc if existing_release is not None else None,
                *[snapshot.upc for snapshot in snapshots],
            ),
            territory=existing_release.territory if existing_release is not None else None,
            explicit_flag=existing_release.explicit_flag if existing_release is not None else False,
            repertoire_status=(
                existing_release.repertoire_status if existing_release is not None else None
            ),
            metadata_complete=(
                existing_release.metadata_complete if existing_release is not None else False
            ),
            contract_signed=(
                existing_release.contract_signed if existing_release is not None else False
            ),
            rights_verified=(
                existing_release.rights_verified if existing_release is not None else False
            ),
            notes=existing_release.notes if existing_release is not None else None,
            artwork_source_path=derived_artwork_source,
            clear_artwork=bool(clear_artwork),
            profile_name=profile_name or self._current_profile_name(),
            placements=placements,
        )

    def _sync_releases_for_tracks(
        self,
        track_ids,
        *,
        cursor: sqlite3.Cursor | None = None,
        track_service: TrackService | None = None,
        release_service: ReleaseService | None = None,
        profile_name: str | None = None,
    ) -> list[int]:
        active_track_service = track_service or self.track_service
        active_release_service = release_service or self.release_service
        if active_track_service is None or active_release_service is None:
            return []
        if cursor is None:
            with self.conn:
                cur = self.conn.cursor()
                return self._sync_releases_for_tracks(
                    track_ids,
                    cursor=cur,
                    track_service=active_track_service,
                    release_service=active_release_service,
                    profile_name=profile_name,
                )

        cur = cursor
        created_or_updated: list[int] = []
        processed_group_keys: set[tuple[int, ...]] = set()

        for track_id in self._normalize_track_ids(track_ids):
            group_track_ids = active_track_service.list_album_group_track_ids(track_id, cursor=cur)
            if not group_track_ids:
                group_track_ids = [track_id]
            group_key = tuple(self._normalize_track_ids(group_track_ids))
            if not group_key or group_key in processed_group_keys:
                continue
            processed_group_keys.add(group_key)

            existing_release = active_release_service.find_primary_release_for_track(track_id)
            existing_summary = (
                active_release_service.fetch_release_summary(existing_release.id)
                if existing_release is not None
                else None
            )
            existing_track_ids = {
                placement.track_id
                for placement in (existing_summary.tracks if existing_summary is not None else [])
            }
            if (
                existing_summary is not None
                and len(existing_track_ids) > 1
                and existing_track_ids != set(group_key)
            ):
                existing_release = None
                existing_summary = None

            payload = self._release_payload_for_track_ids(
                list(group_key),
                existing_release=existing_release,
                existing_summary=existing_summary,
                track_service=active_track_service,
                release_service=active_release_service,
                profile_name=profile_name,
            )
            if existing_release is None:
                release_id = active_release_service.create_release(payload, cursor=cur)
            else:
                release_id = active_release_service.update_release(
                    existing_release.id, payload, cursor=cur
                )
            created_or_updated.append(int(release_id))

        return self._normalize_track_ids(created_or_updated)

    def open_release_browser(self):
        if self.release_service is None:
            QMessageBox.warning(self, "Release Browser", "Open a profile first.")
            return
        dock = self._ensure_release_browser_dock()
        panel = dock.show_panel()
        refresh_scope = getattr(panel, "refresh_selection_scope", None)
        if callable(refresh_scope):
            refresh_scope()
        self.release_browser_dialog = panel

    def open_work_manager(self, linked_track_id: int | None = None):
        if self.work_service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        dock = self._ensure_work_manager_dock()
        panel = dock.show_panel()
        panel.set_linked_track_id(linked_track_id)
        refresh_scope = getattr(panel, "refresh_selection_scope", None)
        if callable(refresh_scope):
            refresh_scope()
        self.work_browser_dialog = panel

    def open_party_manager(self, party_id: int | None = None):
        if self.party_service is None:
            QMessageBox.warning(self, "Party Manager", "Open a profile first.")
            return
        dock = self._ensure_party_manager_dock()
        panel = dock.show_panel()
        panel.focus_party(party_id)
        self.party_manager_dialog = panel

    def open_contract_manager(self, contract_id: int | None = None):
        if self.contract_service is None:
            QMessageBox.warning(self, "Contract Manager", "Open a profile first.")
            return
        dock = self._ensure_contract_manager_dock()
        panel = dock.show_panel()
        panel.focus_contract(contract_id)
        self.contract_manager_dialog = panel

    def open_rights_matrix(self, right_id: int | None = None):
        if (
            self.rights_service is None
            or self.party_service is None
            or self.contract_service is None
        ):
            QMessageBox.warning(self, "Rights Matrix", "Open a profile first.")
            return
        dock = self._ensure_rights_matrix_dock()
        panel = dock.show_panel()
        panel.focus_right(right_id)
        self.rights_browser_dialog = panel

    def open_asset_registry(self, asset_id: int | None = None):
        if self.asset_service is None:
            QMessageBox.warning(self, "Asset Registry", "Open a profile first.")
            return
        dock = self._ensure_asset_registry_dock()
        panel = dock.show_panel()
        panel.focus_asset(asset_id)
        self.asset_browser_dialog = panel

    def open_global_search(self):
        if self.global_search_service is None or self.relationship_explorer_service is None:
            QMessageBox.warning(self, "Global Search", "Open a profile first.")
            return
        dock = self._ensure_global_search_dock()
        self.global_search_dialog = dock.show_panel()

    def _open_entity_from_relationship_search(self, entity_type: str, entity_id: int):
        normalized = str(entity_type or "").strip().lower()
        if normalized == "track":
            self.open_selected_editor(int(entity_id))
            return
        if normalized == "release":
            self.open_release_editor(int(entity_id))
            return
        if normalized == "work":
            self.open_work_manager(linked_track_id=None)
            return
        if normalized == "contract":
            self.open_contract_manager(int(entity_id))
            return
        if normalized == "party":
            self.open_party_manager(int(entity_id))
            return
        if normalized == "right":
            self.open_rights_matrix(int(entity_id))
            return
        if normalized == "asset":
            self.open_asset_registry(int(entity_id))
            return

    def export_repertoire_exchange(self, format_name: str):
        if self.repertoire_exchange_service is None:
            QMessageBox.warning(self, "Repertoire Exchange", "Open a profile first.")
            return
        normalized = str(format_name or "").strip().lower()
        if normalized == "json":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Repertoire JSON", "", "JSON Files (*.json)"
            )
            if not path:
                return
            self.repertoire_exchange_service.export_json(path)
        elif normalized == "xlsx":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Repertoire XLSX", "", "Excel Files (*.xlsx)"
            )
            if not path:
                return
            self.repertoire_exchange_service.export_xlsx(path)
        elif normalized == "csv":
            path = QFileDialog.getExistingDirectory(self, "Export Repertoire CSV Bundle")
            if not path:
                return
            self.repertoire_exchange_service.export_csv_bundle(path)
        elif normalized == "package":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Repertoire ZIP Package", "", "ZIP Files (*.zip)"
            )
            if not path:
                return
            self.repertoire_exchange_service.export_package(path)
        else:
            return
        if self.statusBar() is not None:
            self.statusBar().showMessage("Repertoire export complete.", 5000)

    def import_repertoire_exchange(self, format_name: str):
        if self.repertoire_exchange_service is None:
            QMessageBox.warning(self, "Repertoire Exchange", "Open a profile first.")
            return
        normalized = str(format_name or "").strip().lower()
        try:
            if normalized == "json":
                path, _ = QFileDialog.getOpenFileName(
                    self, "Import Repertoire JSON", "", "JSON Files (*.json)"
                )
                if not path:
                    return
                self.repertoire_exchange_service.import_json(path)
            elif normalized == "xlsx":
                path, _ = QFileDialog.getOpenFileName(
                    self, "Import Repertoire XLSX", "", "Excel Files (*.xlsx)"
                )
                if not path:
                    return
                self.repertoire_exchange_service.import_xlsx(path)
            elif normalized == "csv":
                path = QFileDialog.getExistingDirectory(self, "Import Repertoire CSV Bundle")
                if not path:
                    return
                self.repertoire_exchange_service.import_csv_bundle(path)
            elif normalized == "package":
                path, _ = QFileDialog.getOpenFileName(
                    self, "Import Repertoire ZIP Package", "", "ZIP Files (*.zip)"
                )
                if not path:
                    return
                self.repertoire_exchange_service.import_package(path)
            else:
                return
        except Exception as exc:
            QMessageBox.critical(self, "Repertoire Exchange", str(exc))
            return
        self.refresh_table_preserve_view()
        if self.statusBar() is not None:
            self.statusBar().showMessage("Repertoire import complete.", 5000)

    def open_release_editor(
        self,
        release_id: int | None = None,
        selected_track_ids: list[int] | None = None,
    ):
        if self.release_service is None:
            QMessageBox.warning(self, "Release Editor", "Open a profile first.")
            return
        summary = (
            self.release_service.fetch_release_summary(int(release_id)) if release_id else None
        )
        normalized_selection = self._normalize_track_ids(selected_track_ids)
        dlg = ReleaseEditorDialog(
            release_service=self.release_service,
            track_title_resolver=self._get_track_title,
            selected_track_ids_provider=(
                (lambda: list(normalized_selection))
                if normalized_selection
                else self._selected_track_ids
            ),
            release=summary.release if summary is not None else None,
            placements=list(summary.tracks) if summary is not None else None,
            profile_name=self._current_profile_name(),
            parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            return
        payload = dlg.payload()
        action_label = (
            f"Create Release: {payload.title}"
            if summary is None
            else f"Update Release: {payload.title}"
        )
        action_type = "release.create" if summary is None else "release.update"
        entity_id = payload.title if summary is None else summary.release.id
        existing_release_id = summary.release.id if summary is not None else None

        def _worker(bundle, ctx):
            ctx.set_status("Saving the release and track order...")

            def _mutation():
                if summary is None:
                    return bundle.release_service.create_release(payload)
                return bundle.release_service.update_release(int(summary.release.id), payload)

            return run_snapshot_history_action(
                history_manager=bundle.history_manager,
                action_label=action_label,
                action_type=action_type,
                entity_type="Release",
                entity_id=entity_id,
                payload={
                    "title": payload.title,
                    "track_count": len(payload.placements),
                    "release_id": existing_release_id,
                },
                mutation=_mutation,
                logger=self.logger,
            )

        def _success(release_pk: int):
            try:
                self.conn.commit()
            except Exception:
                pass
            self._refresh_history_actions()
            self._log_event(
                action_type,
                action_label,
                release_id=release_pk,
                title=payload.title,
                track_count=len(payload.placements),
            )
            self._audit(
                "UPDATE" if summary is not None else "CREATE",
                "Release",
                ref_id=release_pk,
                details=f"title={payload.title}; tracks={len(payload.placements)}",
            )
            self._audit_commit()
            self.refresh_table_preserve_view(
                focus_id=payload.placements[0].track_id if payload.placements else None
            )
            if self.release_browser_dialog is not None and self.release_browser_dialog.isVisible():
                self.release_browser_dialog.refresh()

        self._submit_background_bundle_task(
            title="Release Editor",
            description="Saving release metadata and track order...",
            task_fn=_worker,
            kind="write",
            unique_key=f"release.save.{existing_release_id or payload.title}",
            on_success=_success,
            on_error=lambda failure: self._show_background_task_error(
                "Release Editor",
                failure,
                user_message="Could not save the release:",
            ),
        )

    def create_release_from_selection(self, track_ids: list[int] | None = None):
        selected_ids = self._normalize_track_ids(track_ids or self._selected_track_ids())
        if not selected_ids:
            QMessageBox.information(
                self,
                "Create Release",
                "Select one or more tracks first, then create the release from that selection.",
            )
            return
        self.open_release_editor(selected_track_ids=selected_ids)

    def _prompt_for_release_choice(self, *, title: str, prompt: str) -> int | None:
        choices = self._release_choices()
        if not choices:
            QMessageBox.information(self, title, "No releases exist yet. Create one first.")
            return None
        labels = [label for _, label in choices]
        selected_label, ok = QInputDialog.getItem(self, title, prompt, labels, 0, False)
        if not ok or not selected_label:
            return None
        for release_id, label in choices:
            if label == selected_label:
                return int(release_id)
        return None

    def add_selected_tracks_to_release(self, track_ids: list[int] | None = None):
        release_id = self._prompt_for_release_choice(
            title="Add Selected Tracks to Release",
            prompt="Choose the release that should receive the current selection:",
        )
        if release_id is None:
            return
        self.add_selected_tracks_to_specific_release(release_id, track_ids)

    def add_selected_tracks_to_specific_release(
        self, release_id: int, track_ids: list[int] | None = None
    ):
        if self.release_service is None:
            QMessageBox.warning(self, "Release Browser", "Open a profile first.")
            return
        selected_ids = self._normalize_track_ids(track_ids or self._selected_track_ids())
        if not selected_ids:
            QMessageBox.information(self, "Release Browser", "Select one or more tracks first.")
            return
        summary = self.release_service.fetch_release_summary(int(release_id))
        if summary is None:
            QMessageBox.warning(self, "Release Browser", "The chosen release could not be loaded.")
            return

        def mutation():
            return self.release_service.add_tracks_to_release(int(release_id), selected_ids)

        try:
            added_track_ids = self._run_snapshot_history_action(
                action_label=f"Add Tracks to Release: {summary.release.title}",
                action_type="release.add_tracks",
                entity_type="Release",
                entity_id=release_id,
                payload={"release_id": release_id, "track_ids": selected_ids},
                mutation=mutation,
            )
            self._log_event(
                "release.add_tracks",
                "Added selected tracks to release",
                release_id=release_id,
                title=summary.release.title,
                track_ids=added_track_ids,
            )
            self._audit(
                "UPDATE",
                "Release",
                ref_id=release_id,
                details=f"add_tracks={','.join(str(track_id) for track_id in (added_track_ids or []))}",
            )
            self._audit_commit()
        except Exception as exc:
            self.conn.rollback()
            self.logger.exception(f"Add tracks to release failed: {exc}")
            QMessageBox.critical(
                self, "Release Browser", f"Could not add the selected tracks:\n{exc}"
            )
            return

        if self.release_browser_dialog is not None and self.release_browser_dialog.isVisible():
            self.release_browser_dialog.refresh()
        QMessageBox.information(
            self,
            "Release Browser",
            f"Added {len(added_track_ids or [])} track{'s' if len(added_track_ids or []) != 1 else ''} to '{summary.release.title}'.",
        )

    def _refresh_work_manager_panel(self) -> None:
        panel = getattr(self, "work_browser_dialog", None)
        if panel is not None and panel.isVisible():
            panel.refresh()
            refresh_scope = getattr(panel, "refresh_selection_scope", None)
            if callable(refresh_scope):
                refresh_scope()

    def create_work(self, payload: WorkPayload):
        if self.work_service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        payload.profile_name = payload.profile_name or self._current_profile_name()
        try:
            work_id = self._run_snapshot_history_action(
                action_label=f"Create Work: {payload.title or 'Untitled Work'}",
                action_type="work.create",
                entity_type="Work",
                entity_id=payload.title or "new",
                payload={
                    "title": payload.title,
                    "track_count": len(payload.track_ids),
                },
                mutation=lambda: self.work_service.create_work(payload),
            )
            self._log_event(
                "work.create",
                "Work created",
                work_id=work_id,
                title=payload.title,
                track_ids=list(payload.track_ids),
            )
            self._audit("CREATE", "Work", ref_id=work_id, details=f"title={payload.title}")
            self._audit_commit()
        except Exception as exc:
            self.conn.rollback()
            self.logger.exception(f"Create work failed: {exc}")
            QMessageBox.critical(self, "Work Manager", f"Could not create the work:\n{exc}")
            return
        self._refresh_history_actions()
        self._refresh_work_manager_panel()

    def update_work(self, work_id: int, payload: WorkPayload):
        if self.work_service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        payload.profile_name = payload.profile_name or self._current_profile_name()
        detail = self.work_service.fetch_work_detail(int(work_id))
        if detail is None:
            QMessageBox.warning(self, "Work Manager", "The selected work could not be loaded.")
            return
        try:
            self._run_snapshot_history_action(
                action_label=f"Update Work: {payload.title or detail.work.title}",
                action_type="work.update",
                entity_type="Work",
                entity_id=work_id,
                payload={
                    "work_id": int(work_id),
                    "title": payload.title,
                    "track_count": len(payload.track_ids),
                },
                mutation=lambda: self.work_service.update_work(int(work_id), payload),
            )
            self._log_event(
                "work.update",
                "Work updated",
                work_id=int(work_id),
                title=payload.title,
                track_ids=list(payload.track_ids),
            )
            self._audit("UPDATE", "Work", ref_id=work_id, details=f"title={payload.title}")
            self._audit_commit()
        except Exception as exc:
            self.conn.rollback()
            self.logger.exception(f"Update work failed: {exc}")
            QMessageBox.critical(self, "Work Manager", f"Could not update the work:\n{exc}")
            return
        self._refresh_history_actions()
        self._refresh_work_manager_panel()

    def duplicate_work(self, work_id: int):
        if self.work_service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        detail = self.work_service.fetch_work_detail(int(work_id))
        if detail is None:
            QMessageBox.warning(self, "Work Manager", "The selected work could not be loaded.")
            return
        try:
            new_work_id = self._run_snapshot_history_action(
                action_label=f"Duplicate Work: {detail.work.title}",
                action_type="work.duplicate",
                entity_type="Work",
                entity_id=work_id,
                payload={"work_id": int(work_id), "title": detail.work.title},
                mutation=lambda: self.work_service.duplicate_work(int(work_id)),
            )
            self._log_event(
                "work.duplicate",
                "Work duplicated",
                source_work_id=int(work_id),
                new_work_id=new_work_id,
                title=detail.work.title,
            )
            self._audit("CREATE", "Work", ref_id=new_work_id, details=f"duplicated_from={work_id}")
            self._audit_commit()
        except Exception as exc:
            self.conn.rollback()
            self.logger.exception(f"Duplicate work failed: {exc}")
            QMessageBox.critical(self, "Work Manager", f"Could not duplicate the work:\n{exc}")
            return
        self._refresh_history_actions()
        self._refresh_work_manager_panel()

    def link_tracks_to_work(self, work_id: int, track_ids: list[int]):
        if self.work_service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        normalized_ids = self._normalize_track_ids(track_ids)
        if not normalized_ids:
            QMessageBox.information(self, "Work Manager", "Select one or more tracks first.")
            return
        detail = self.work_service.fetch_work_detail(int(work_id))
        if detail is None:
            QMessageBox.warning(self, "Work Manager", "The selected work could not be loaded.")
            return
        try:
            self._run_snapshot_history_action(
                action_label=f"Link Tracks to Work: {detail.work.title}",
                action_type="work.link_tracks",
                entity_type="Work",
                entity_id=work_id,
                payload={"work_id": int(work_id), "track_ids": normalized_ids},
                mutation=lambda: self.work_service.link_tracks_to_work(
                    int(work_id), normalized_ids
                ),
            )
            self._log_event(
                "work.link_tracks",
                "Linked tracks to work",
                work_id=int(work_id),
                track_ids=normalized_ids,
            )
            self._audit(
                "UPDATE",
                "Work",
                ref_id=work_id,
                details=f"track_ids={','.join(str(track_id) for track_id in normalized_ids)}",
            )
            self._audit_commit()
        except Exception as exc:
            self.conn.rollback()
            self.logger.exception(f"Link tracks to work failed: {exc}")
            QMessageBox.critical(self, "Work Manager", f"Could not link the tracks:\n{exc}")
            return
        self._refresh_history_actions()
        self._refresh_work_manager_panel()

    def delete_work(self, work_id: int):
        if self.work_service is None:
            QMessageBox.warning(self, "Work Manager", "Open a profile first.")
            return
        detail = self.work_service.fetch_work_detail(int(work_id))
        if detail is None:
            QMessageBox.warning(self, "Work Manager", "The selected work could not be loaded.")
            return
        try:
            self._run_snapshot_history_action(
                action_label=f"Delete Work: {detail.work.title}",
                action_type="work.delete",
                entity_type="Work",
                entity_id=work_id,
                payload={"work_id": int(work_id), "title": detail.work.title},
                mutation=lambda: self.work_service.delete_work(int(work_id)),
            )
            self._log_event(
                "work.delete",
                "Work deleted",
                work_id=int(work_id),
                title=detail.work.title,
            )
            self._audit("DELETE", "Work", ref_id=work_id, details=f"title={detail.work.title}")
            self._audit_commit()
        except Exception as exc:
            self.conn.rollback()
            self.logger.exception(f"Delete work failed: {exc}")
            QMessageBox.critical(self, "Work Manager", f"Could not delete the work:\n{exc}")
            return
        self._refresh_history_actions()
        self._refresh_work_manager_panel()

    def duplicate_release(self, release_id: int):
        if self.release_service is None:
            return
        summary = self.release_service.fetch_release_summary(int(release_id))
        if summary is None:
            QMessageBox.warning(
                self, "Duplicate Release", "The selected release could not be loaded."
            )
            return
        try:
            new_release_id = self._run_snapshot_history_action(
                action_label=f"Duplicate Release: {summary.release.title}",
                action_type="release.duplicate",
                entity_type="Release",
                entity_id=release_id,
                payload={"release_id": release_id, "title": summary.release.title},
                mutation=lambda: self.release_service.duplicate_release(int(release_id)),
            )
            self._log_event(
                "release.duplicate",
                "Release duplicated",
                source_release_id=release_id,
                new_release_id=new_release_id,
                title=summary.release.title,
            )
            self._audit(
                "CREATE",
                "Release",
                ref_id=new_release_id,
                details=f"duplicated_from={release_id}",
            )
            self._audit_commit()
        except Exception as exc:
            self.conn.rollback()
            self.logger.exception(f"Duplicate release failed: {exc}")
            QMessageBox.critical(
                self, "Duplicate Release", f"Could not duplicate the release:\n{exc}"
            )
            return
        if self.release_browser_dialog is not None and self.release_browser_dialog.isVisible():
            self.release_browser_dialog.refresh()

    def _build_tag_preview_rows(
        self,
        *,
        track_id: int,
        track_title: str | None = None,
        source_path: str,
        database_values: dict[str, object],
        file_tags,
        chosen_values: dict[str, object],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        display_track_title = str(track_title or self._get_track_title(track_id) or "")
        for field_name, chosen_value in chosen_values.items():
            database_value = database_values.get(field_name)
            file_value = getattr(file_tags, field_name, None)
            if database_value == file_value and not isinstance(chosen_value, ArtworkPayload):
                continue
            rows.append(
                {
                    "track": display_track_title,
                    "field": field_name.replace("_", " ").title(),
                    "database": self._display_tag_value(database_value),
                    "file": self._display_tag_value(file_value),
                    "chosen": self._display_tag_value(chosen_value),
                    "source": source_path,
                }
            )
        return rows

    def _prepare_tag_import_preview(
        self,
        track_ids: list[int],
        *,
        policy: str,
        track_service: TrackService | None = None,
        release_service: ReleaseService | None = None,
        audio_tag_service: AudioTagService | None = None,
        progress_callback=None,
    ) -> dict[str, object]:
        active_track_service = track_service or self.track_service
        active_release_service = release_service or self.release_service
        active_audio_tag_service = audio_tag_service or self.audio_tag_service
        if active_track_service is None or active_audio_tag_service is None:
            raise ValueError("Audio tag services are not available.")

        normalized_ids = self._normalize_track_ids(track_ids)
        prepared: list[dict[str, object]] = []
        preview_rows: list[dict[str, object]] = []
        warnings: list[str] = []
        total = max(1, len(normalized_ids))
        for index, track_id in enumerate(normalized_ids, start=1):
            if callable(progress_callback):
                progress_callback(
                    index - 1, total, f"Reading audio tags for track {index} of {total}..."
                )
            snapshot = active_track_service.fetch_track_snapshot(track_id)
            if snapshot is None:
                warnings.append(f"Track {track_id} could not be loaded.")
                continue
            resolved = active_track_service.resolve_media_path(snapshot.audio_file_path)
            if resolved is None or not resolved.exists():
                warnings.append(f"{snapshot.track_title}: no managed audio file is attached.")
                continue
            try:
                file_tags = active_audio_tag_service.read_tags(resolved)
            except Exception as exc:
                warnings.append(f"{snapshot.track_title}: {exc}")
                continue
            database_values = self._catalog_tag_data_for_track(
                track_id,
                snapshot=snapshot,
                track_service=active_track_service,
                release_service=active_release_service,
            ).to_dict()
            preview = merge_imported_tags(
                database_values=database_values,
                file_tags=file_tags,
                policy=policy,
            )
            prepared.append(
                {
                    "track_id": int(track_id),
                    "track_title": snapshot.track_title,
                    "source_path": str(resolved),
                    "file_tags": file_tags,
                }
            )
            preview_rows.extend(
                self._build_tag_preview_rows(
                    track_id=track_id,
                    track_title=snapshot.track_title,
                    source_path=str(resolved),
                    database_values=database_values,
                    file_tags=file_tags,
                    chosen_values=preview.patch.values,
                )
            )

        if callable(progress_callback):
            progress_callback(total, total, "Audio tag preview ready.")

        return {
            "prepared": prepared,
            "rows": preview_rows,
            "warnings": warnings,
        }

    @staticmethod
    def _iter_audio_tag_preview_fields(tag_data: AudioTagData) -> list[tuple[str, object]]:
        return [
            (field.name, getattr(tag_data, field.name))
            for field in dataclass_fields(AudioTagData)
            if field.name not in {"raw_fields", "warnings"}
        ]

    def _build_tagged_audio_export_preview_rows(
        self,
        *,
        track_title: str,
        source_label: str,
        tag_data: AudioTagData,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for field_name, value in self._iter_audio_tag_preview_fields(tag_data):
            if value in (None, "", [], {}, ()):
                continue
            rows.append(
                {
                    "track": track_title,
                    "field": field_name.replace("_", " ").title(),
                    "database": self._display_tag_value(value),
                    "file": "",
                    "chosen": self._display_tag_value(value),
                    "source": source_label,
                }
            )
        return rows

    @staticmethod
    def _tagged_audio_export_name(track_id: int, track_title: str | None) -> str:
        safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", track_title or f"track_{track_id}").strip("_")
        return f"{track_id:05d}_{safe_title or 'track'}"

    def _prepare_tagged_audio_export_preview(
        self,
        track_ids: list[int],
        *,
        track_service: TrackService | None = None,
        release_service: ReleaseService | None = None,
        progress_callback=None,
    ) -> dict[str, object]:
        active_track_service = track_service or self.track_service
        active_release_service = release_service or self.release_service
        if active_track_service is None:
            raise ValueError("Track service is not available.")

        normalized_ids = self._normalize_track_ids(track_ids)
        prepared: list[TaggedAudioExportPlanItem] = []
        preview_rows: list[dict[str, object]] = []
        warnings: list[str] = []
        total = max(1, len(normalized_ids))
        for index, track_id in enumerate(normalized_ids, start=1):
            if callable(progress_callback):
                progress_callback(
                    index - 1,
                    total,
                    f"Preparing tagged audio export preview for track {index} of {total}...",
                )
            snapshot = active_track_service.fetch_track_snapshot(
                track_id,
                include_media_blobs=False,
            )
            if snapshot is None:
                warnings.append(f"Track {track_id} could not be loaded.")
                continue

            source_suffix = self._audio_export_source_suffix(snapshot)
            resolved = active_track_service.resolve_media_path(snapshot.audio_file_path)
            if resolved is not None and resolved.exists():
                source_label = str(resolved)
            elif (
                normalize_storage_mode(snapshot.audio_file_storage_mode, default=None)
                == STORAGE_MODE_DATABASE
            ):
                source_label = self._audio_export_source_label(snapshot)
            else:
                warnings.append(f"{snapshot.track_title}: no exportable audio file is attached.")
                continue

            tag_data = self._catalog_tag_data_for_track(
                track_id,
                snapshot=snapshot,
                track_service=active_track_service,
                release_service=active_release_service,
                include_artwork_bytes=False,
            )
            prepared.append(
                TaggedAudioExportPlanItem(
                    track_id=int(track_id),
                    track_title=str(snapshot.track_title or ""),
                    suggested_name=self._tagged_audio_export_name(track_id, snapshot.track_title),
                    source_suffix=source_suffix,
                    source_label=source_label,
                )
            )
            preview_rows.extend(
                self._build_tagged_audio_export_preview_rows(
                    track_title=str(snapshot.track_title or ""),
                    source_label=source_label,
                    tag_data=tag_data,
                )
            )

        if callable(progress_callback):
            progress_callback(total, total, "Tagged audio export preview ready.")

        return {
            "prepared": prepared,
            "rows": preview_rows,
            "warnings": warnings,
        }

    def _build_tagged_audio_export_items(
        self,
        plan_items: list[TaggedAudioExportPlanItem],
        *,
        track_service: TrackService | None = None,
        release_service: ReleaseService | None = None,
        progress_callback=None,
        is_cancelled=None,
    ) -> tuple[list[TaggedAudioExportItem], list[str]]:
        active_track_service = track_service or self.track_service
        active_release_service = release_service or self.release_service
        if active_track_service is None:
            raise ValueError("Track service is not available.")

        exports: list[TaggedAudioExportItem] = []
        warnings: list[str] = []
        total = max(1, len(plan_items))
        for index, plan_item in enumerate(plan_items, start=1):
            if callable(is_cancelled) and is_cancelled():
                raise InterruptedError("Tagged audio export cancelled.")
            if callable(progress_callback):
                progress_callback(
                    index - 1,
                    total,
                    f"Preparing exported audio copy {index} of {total}: {plan_item.suggested_name}",
                )
            snapshot = active_track_service.fetch_track_snapshot(
                plan_item.track_id,
                include_media_blobs=False,
            )
            if snapshot is None:
                warnings.append(f"Track {plan_item.track_id} could not be loaded.")
                continue
            tag_data = self._catalog_tag_data_for_track(
                plan_item.track_id,
                snapshot=snapshot,
                track_service=active_track_service,
                release_service=active_release_service,
                include_artwork_bytes=True,
            )
            resolved = active_track_service.resolve_media_path(snapshot.audio_file_path)
            if resolved is not None and resolved.exists():
                exports.append(
                    TaggedAudioExportItem(
                        suggested_name=plan_item.suggested_name,
                        tag_data=tag_data,
                        source_path=resolved,
                        source_suffix=plan_item.source_suffix,
                    )
                )
                continue
            try:
                audio_bytes, _mime_type = active_track_service.fetch_media_bytes(
                    plan_item.track_id,
                    "audio_file",
                )
            except Exception:
                warnings.append(f"{plan_item.track_title}: no exportable audio file is attached.")
                continue
            exports.append(
                TaggedAudioExportItem(
                    suggested_name=plan_item.suggested_name,
                    tag_data=tag_data,
                    source_bytes=audio_bytes,
                    source_suffix=plan_item.source_suffix,
                )
            )

        if callable(progress_callback):
            progress_callback(total, total, "Tagged audio export sources are ready.")

        return exports, warnings

    def _apply_tag_patch_to_track(
        self,
        track_id: int,
        values: dict[str, object],
        *,
        cursor: sqlite3.Cursor | None = None,
        track_service: TrackService | None = None,
    ) -> None:
        active_track_service = track_service or self.track_service
        if active_track_service is None:
            raise ValueError("Track service is not available.")
        snapshot = active_track_service.fetch_track_snapshot(track_id, cursor=cursor)
        if snapshot is None:
            raise ValueError(f"Track {track_id} not found")
        artwork = values.get("artwork")
        temp_artwork_path = None
        current_artwork = self._effective_artwork_payload_for_track(
            track_id,
            snapshot=snapshot,
            track_service=active_track_service,
        )
        if isinstance(artwork, ArtworkPayload) and artwork != current_artwork:
            suffix = mimetypes.guess_extension(artwork.mime_type or "image/jpeg") or ".img"
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            try:
                handle.write(artwork.data)
                temp_artwork_path = handle.name
            finally:
                handle.close()

        try:
            payload = TrackUpdatePayload(
                track_id=track_id,
                isrc=str(values.get("isrc") or snapshot.isrc or "").strip(),
                track_title=str(values.get("title") or snapshot.track_title or "").strip(),
                artist_name=str(values.get("artist") or snapshot.artist_name or "").strip(),
                additional_artists=list(snapshot.additional_artists),
                album_title=str(values.get("album") or snapshot.album_title or "").strip() or None,
                release_date=str(values.get("release_date") or snapshot.release_date or "").strip()
                or None,
                track_length_sec=int(snapshot.track_length_sec or 0),
                iswc=snapshot.iswc,
                upc=str(values.get("upc") or snapshot.upc or "").strip() or None,
                genre=str(values.get("genre") or snapshot.genre or "").strip() or None,
                catalog_number=snapshot.catalog_number,
                buma_work_number=snapshot.buma_work_number,
                composer=str(values.get("composer") or snapshot.composer or "").strip() or None,
                publisher=str(values.get("publisher") or snapshot.publisher or "").strip() or None,
                comments=str(values.get("comments") or snapshot.comments or "").strip() or None,
                lyrics=str(values.get("lyrics") or snapshot.lyrics or "").strip() or None,
                audio_file_source_path=None,
                album_art_source_path=temp_artwork_path,
                clear_audio_file=False,
                clear_album_art=False,
            )
            active_track_service.update_track(payload, cursor=cursor)
        finally:
            if temp_artwork_path:
                Path(temp_artwork_path).unlink(missing_ok=True)

    def bulk_attach_audio_files(self, track_ids: list[int] | None = None):
        if self.audio_tag_service is None or self.track_service is None:
            QMessageBox.warning(self, "Bulk Attach Audio Files", "Open a profile first.")
            return

        scope_track_ids, scope_label = self._bulk_audio_attach_scope_track_ids(track_ids)
        if not scope_track_ids:
            QMessageBox.information(
                self,
                "Bulk Attach Audio Files",
                "Select one or more tracks first, or leave the catalog rows visible so audio files can be matched against them.",
            )
            return

        chosen_files, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "Choose Audio Files to Attach",
            str(self.data_root),
            (
                "Audio Files (*.mp3 *.flac *.ogg *.oga *.opus *.m4a *.mp4 *.aac *.wav *.aif *.aiff);;"
                "All Files (*)"
            ),
        )
        file_paths = [str(Path(path)) for path in dict.fromkeys(chosen_files) if str(path).strip()]
        if not file_paths:
            return

        def _preview_worker(bundle, ctx):
            track_candidates: list[BulkAudioAttachTrackCandidate] = []
            total_tracks = len(scope_track_ids)
            overall_total = max(1, total_tracks + len(file_paths))
            for index, track_id in enumerate(scope_track_ids, start=1):
                snapshot = bundle.track_service.fetch_track_snapshot(track_id)
                if snapshot is not None:
                    track_candidates.append(
                        BulkAudioAttachTrackCandidate(
                            track_id=snapshot.track_id,
                            title=snapshot.track_title,
                            artist=snapshot.artist_name,
                            album=snapshot.album_title,
                            isrc=snapshot.isrc,
                        )
                    )
                ctx.report_progress(
                    value=index,
                    maximum=overall_total,
                    message=f"Loading track {index} of {total_tracks} for audio matching...",
                )

            matcher = BulkAudioAttachService(bundle.audio_tag_service)
            plan = matcher.build_plan(
                file_paths=file_paths,
                tracks=track_candidates,
                progress_callback=lambda value, maximum, message: ctx.report_progress(
                    value=total_tracks + value,
                    maximum=total_tracks + maximum,
                    message=message,
                ),
            )
            return {
                "plan": plan,
                "track_choices": [
                    (
                        candidate.track_id,
                        " / ".join(
                            part
                            for part in (
                                f"{candidate.track_id} - {candidate.title}",
                                candidate.artist or "",
                            )
                            if part
                        ),
                        candidate.artist,
                    )
                    for candidate in track_candidates
                ],
                "scope_label": scope_label,
                "scope_track_count": len(track_candidates),
            }

        def _preview_success(result: dict[str, object]):
            plan = result.get("plan")
            track_choices = list(result.get("track_choices") or [])
            if plan is None or not track_choices:
                QMessageBox.information(
                    self,
                    "Bulk Attach Audio Files",
                    "No track candidates were available for the current bulk-attach scope.",
                )
                return

            plan_items = list(getattr(plan, "items", []) or [])
            dialog_rows = []
            for item in plan_items:
                warning_parts: list[str] = []
                item_warning = str(item.warning or "").strip()
                if item_warning:
                    warning_parts.append(item_warning)
                lossy_warning = self._lossy_primary_audio_warning_text(
                    path_value=item.source_path,
                    filename=item.source_name,
                    short=True,
                )
                if lossy_warning and lossy_warning not in warning_parts:
                    warning_parts.append(lossy_warning)
                dialog_rows.append(
                    {
                        "source_path": item.source_path,
                        "source_name": item.source_name,
                        "detected_title": item.detected_title,
                        "detected_artist": item.detected_artist,
                        "matched_track_id": item.matched_track_id,
                        "matched_track_artist": item.matched_track_artist,
                        "match_basis": item.match_basis,
                        "status": item.status,
                        "warning": "\n".join(warning_parts),
                    }
                )
            dlg = BulkAudioAttachDialog(
                title="Bulk Attach Audio Files",
                intro=(
                    f"Review {len(file_paths)} audio file(s) against "
                    f"{int(result.get('scope_track_count') or 0)} track(s) from the {result.get('scope_label') or scope_label}. "
                    "You can reassign unmatched rows before the files are attached."
                ),
                items=dialog_rows,
                track_choices=track_choices,
                suggested_artist=getattr(plan, "suggested_artist", None),
                parent=self,
            )
            if dlg.exec() != QDialog.Accepted:
                return

            assignments = dlg.selected_matches()
            if not self._confirm_lossy_primary_audio_selection(
                [str(item.get("source_path") or "") for item in assignments],
                title="Bulk Attach Audio Files",
                action_label="Attaching these files",
            ):
                return
            storage_mode = _prompt_storage_mode_choice(
                self,
                title="Bulk Attach Audio Files",
                subject="the audio files",
                default_mode=STORAGE_MODE_MANAGED_FILE,
            )
            if storage_mode is None:
                return
            batch_artist = dlg.selected_artist_name()
            plan_warnings = list(getattr(plan, "warnings", []) or [])
            skipped_count = max(0, len(file_paths) - len(assignments))

            def _apply_worker(bundle, ctx):
                profile_name = self._current_profile_name()

                def _artist_payload(
                    snapshot: TrackSnapshot, artist_name: str
                ) -> TrackUpdatePayload:
                    return TrackUpdatePayload(
                        track_id=snapshot.track_id,
                        isrc=str(snapshot.isrc or "").strip(),
                        track_title=str(snapshot.track_title or "").strip(),
                        artist_name=str(artist_name or "").strip(),
                        additional_artists=list(snapshot.additional_artists),
                        album_title=str(snapshot.album_title or "").strip() or None,
                        release_date=str(snapshot.release_date or "").strip() or None,
                        track_length_sec=int(snapshot.track_length_sec or 0),
                        iswc=snapshot.iswc,
                        upc=str(snapshot.upc or "").strip() or None,
                        genre=str(snapshot.genre or "").strip() or None,
                        catalog_number=snapshot.catalog_number,
                        buma_work_number=snapshot.buma_work_number,
                        composer=str(snapshot.composer or "").strip() or None,
                        publisher=str(snapshot.publisher or "").strip() or None,
                        comments=str(snapshot.comments or "").strip() or None,
                        lyrics=str(snapshot.lyrics or "").strip() or None,
                        audio_file_source_path=None,
                        album_art_source_path=None,
                        clear_audio_file=False,
                        clear_album_art=False,
                    )

                def _mutation():
                    attached_track_ids: list[int] = []
                    artist_updated_ids: list[int] = []
                    total = max(1, len(assignments))
                    with bundle.conn:
                        cur = bundle.conn.cursor()
                        for index, assignment in enumerate(assignments, start=1):
                            track_id = int(assignment["track_id"])
                            bundle.track_service.set_media_path(
                                track_id,
                                "audio_file",
                                str(assignment["source_path"]),
                                storage_mode=storage_mode,
                                cursor=cur,
                            )
                            attached_track_ids.append(track_id)
                            if batch_artist:
                                snapshot = bundle.track_service.fetch_track_snapshot(
                                    track_id, cursor=cur
                                )
                                if (
                                    snapshot is not None
                                    and batch_artist.strip()
                                    != str(snapshot.artist_name or "").strip()
                                ):
                                    bundle.track_service.update_track(
                                        _artist_payload(snapshot, batch_artist),
                                        cursor=cur,
                                    )
                                    artist_updated_ids.append(track_id)
                            ctx.report_progress(
                                value=index,
                                maximum=total,
                                message=(
                                    f"Attaching audio file {index} of {total} to track {track_id}..."
                                ),
                            )
                        if artist_updated_ids:
                            self._sync_releases_for_tracks(
                                artist_updated_ids,
                                cursor=cur,
                                track_service=bundle.track_service,
                                release_service=bundle.release_service,
                                profile_name=profile_name,
                            )
                    return {
                        "attached_track_ids": attached_track_ids,
                        "artist_updated_ids": artist_updated_ids,
                    }

                return run_snapshot_history_action(
                    history_manager=bundle.history_manager,
                    action_label=f"Bulk Attach Audio Files ({len(assignments)} files)",
                    action_type="track.audio_file.bulk_attach",
                    entity_type="Track",
                    entity_id="batch",
                    payload={
                        "track_ids": [int(item["track_id"]) for item in assignments],
                        "storage_mode": storage_mode,
                        "scope_label": scope_label,
                        "artist_name": batch_artist,
                    },
                    mutation=_mutation,
                    logger=self.logger,
                )

            def _apply_success(result: dict[str, object]):
                attached_track_ids = list(result.get("attached_track_ids") or [])
                artist_updated_ids = list(result.get("artist_updated_ids") or [])
                warnings = plan_warnings
                try:
                    self.conn.commit()
                except Exception:
                    pass
                self._refresh_history_actions()
                self._log_event(
                    "track.audio_file.bulk_attach",
                    "Bulk attached audio files",
                    track_ids=attached_track_ids,
                    artist_updated_ids=artist_updated_ids,
                    skipped=skipped_count,
                    storage_mode=storage_mode,
                    scope_label=scope_label,
                    warnings=warnings,
                )
                self._audit(
                    "UPDATE",
                    "TrackAudio",
                    ref_id="batch",
                    details=(
                        f"attached={len(attached_track_ids)}; "
                        f"artist_updates={len(artist_updated_ids)}; "
                        f"skipped={skipped_count}; storage_mode={storage_mode}"
                    ),
                )
                self._audit_commit()
                if artist_updated_ids:
                    self.populate_all_comboboxes()
                self.refresh_table_preserve_view(
                    focus_id=attached_track_ids[0] if attached_track_ids else None
                )
                QMessageBox.information(
                    self,
                    "Bulk Attach Audio Files",
                    f"Attached audio to {len(attached_track_ids)} track(s)."
                    + (
                        f"\nUpdated the main artist on {len(artist_updated_ids)} matched track(s)."
                        if artist_updated_ids
                        else ""
                    )
                    + (
                        f"\nSkipped {skipped_count} file(s) that were left unmatched."
                        if skipped_count
                        else ""
                    )
                    + (f"\n\nWarnings:\n- " + "\n- ".join(warnings[:12]) if warnings else ""),
                )

            self._submit_background_bundle_task(
                title="Bulk Attach Audio Files",
                description="Attaching the selected audio files to matched catalog tracks...",
                task_fn=_apply_worker,
                kind="write",
                unique_key="track.audio_file.bulk_attach",
                cancellable=False,
                on_success=_apply_success,
                on_error=lambda failure: self._show_background_task_error(
                    "Bulk Attach Audio Files",
                    failure,
                    user_message="Could not attach the selected audio files:",
                ),
            )

        self._submit_background_bundle_task(
            title="Bulk Attach Audio Files",
            description="Matching selected audio files to catalog tracks...",
            task_fn=_preview_worker,
            kind="read",
            unique_key="track.audio_file.bulk_attach.preview",
            cancellable=False,
            on_success=_preview_success,
            on_error=lambda failure: self._show_background_task_error(
                "Bulk Attach Audio Files",
                failure,
                user_message="Could not prepare the bulk audio attach preview:",
            ),
        )

    def import_tags_from_audio(self, track_ids: list[int] | None = None):
        if self.audio_tag_service is None or self.track_service is None:
            QMessageBox.warning(self, "Import Tags", "Open a profile first.")
            return
        selected_ids = self._normalize_track_ids(track_ids or self._selected_track_ids())
        if not selected_ids:
            QMessageBox.information(
                self, "Import Tags", "Select one or more tracks with attached audio first."
            )
            return

        policy = str(
            self.settings.value("audio_tags/import_policy", "merge_blanks", str) or "merge_blanks"
        )

        def _preview_worker(bundle, ctx):
            return self._prepare_tag_import_preview(
                selected_ids,
                policy=policy,
                track_service=bundle.track_service,
                release_service=bundle.release_service,
                audio_tag_service=bundle.audio_tag_service,
                progress_callback=lambda value, maximum, message: ctx.report_progress(
                    value=value,
                    maximum=maximum,
                    message=message,
                ),
            )

        def _preview_success(result: dict[str, object]):
            prepared = list(result.get("prepared") or [])
            preview_rows = list(result.get("rows") or [])
            warnings = list(result.get("warnings") or [])
            if not prepared:
                QMessageBox.information(
                    self,
                    "Import Tags",
                    "No readable managed audio files were available for the selected tracks."
                    + (f"\n\nWarnings:\n- " + "\n- ".join(warnings[:12]) if warnings else ""),
                )
                return

            dlg = TagPreviewDialog(
                title="Import Tags from Audio",
                intro=(
                    "Review how embedded file tags map onto the selected catalog records. "
                    "Choose the conflict policy you want to apply before importing."
                ),
                rows=preview_rows,
                initial_policy=policy,
                allow_policy_change=True,
                parent=self,
            )
            if dlg.exec() != QDialog.Accepted:
                return

            chosen_policy = dlg.selected_policy()
            self.settings.setValue("audio_tags/import_policy", chosen_policy)
            self.settings.sync()

            def _import_worker(bundle, ctx):
                profile_name = self._current_profile_name()

                def _mutation():
                    updated_track_ids: list[int] = []
                    total = max(1, len(prepared))
                    with bundle.conn:
                        cur = bundle.conn.cursor()
                        for index, entry in enumerate(prepared, start=1):
                            track_id = int(entry["track_id"])
                            snapshot = bundle.track_service.fetch_track_snapshot(
                                track_id, cursor=cur
                            )
                            if snapshot is None:
                                continue
                            database_values = self._catalog_tag_data_for_track(
                                track_id,
                                snapshot=snapshot,
                                track_service=bundle.track_service,
                                release_service=bundle.release_service,
                            ).to_dict()
                            preview = merge_imported_tags(
                                database_values=database_values,
                                file_tags=entry["file_tags"],
                                policy=chosen_policy,
                            )
                            self._apply_tag_patch_to_track(
                                track_id,
                                preview.patch.values,
                                cursor=cur,
                                track_service=bundle.track_service,
                            )
                            updated_track_ids.append(track_id)
                            ctx.report_progress(
                                value=index,
                                maximum=total,
                                message=f"Importing tags for track {index} of {total}...",
                            )
                        self._sync_releases_for_tracks(
                            updated_track_ids,
                            cursor=cur,
                            track_service=bundle.track_service,
                            release_service=bundle.release_service,
                            profile_name=profile_name,
                        )
                    return {"changed_ids": updated_track_ids}

                return run_snapshot_history_action(
                    history_manager=bundle.history_manager,
                    action_label=f"Import Audio Tags ({len(prepared)} tracks)",
                    action_type="tags.import",
                    entity_type="Track",
                    entity_id="batch",
                    payload={
                        "track_ids": [int(entry["track_id"]) for entry in prepared],
                        "policy": chosen_policy,
                    },
                    mutation=_mutation,
                    logger=self.logger,
                )

            def _import_success(result: dict[str, object]):
                changed_ids = list(result.get("changed_ids") or [])
                try:
                    self.conn.commit()
                except Exception:
                    pass
                self._refresh_history_actions()
                self._log_event(
                    "tags.import",
                    "Imported embedded tags from audio",
                    track_ids=changed_ids,
                    policy=chosen_policy,
                    warnings=warnings,
                )
                self._audit(
                    "IMPORT",
                    "AudioTags",
                    ref_id="batch",
                    details=f"track_ids={','.join(str(track_id) for track_id in changed_ids)}; policy={chosen_policy}",
                )
                self._audit_commit()
                self.refresh_table_preserve_view(focus_id=changed_ids[0] if changed_ids else None)
                self.populate_all_comboboxes()
                QMessageBox.information(
                    self,
                    "Import Tags",
                    f"Imported tags for {len(changed_ids or [])} track{'s' if len(changed_ids or []) != 1 else ''}."
                    + (f"\n\nWarnings:\n- " + "\n- ".join(warnings[:12]) if warnings else ""),
                )

            self._submit_background_bundle_task(
                title="Import Tags from Audio",
                description="Applying imported audio tags to the selected catalog tracks...",
                task_fn=_import_worker,
                kind="write",
                unique_key="tags.import.apply",
                cancellable=False,
                on_success=_import_success,
                on_error=lambda failure: self._show_background_task_error(
                    "Import Tags",
                    failure,
                    user_message="Could not import audio tags:",
                ),
            )

        self._submit_background_bundle_task(
            title="Import Tags from Audio",
            description="Reading embedded tags from the selected audio files...",
            task_fn=_preview_worker,
            kind="read",
            unique_key="tags.import.preview",
            cancellable=False,
            on_success=_preview_success,
            on_error=lambda failure: self._show_background_task_error(
                "Import Tags",
                failure,
                user_message="Could not prepare the audio tag preview:",
            ),
        )

    def _audio_export_source_suffix(self, snapshot: TrackSnapshot) -> str:
        filename = str(snapshot.audio_file_filename or "").strip()
        if filename:
            suffix = Path(filename).suffix.strip()
            if suffix:
                return suffix
        return self._export_extension_for_mime(str(snapshot.audio_file_mime_type or ""))

    @staticmethod
    def _audio_export_source_label(snapshot: TrackSnapshot) -> str:
        filename = str(snapshot.audio_file_filename or "").strip()
        storage_mode = normalize_storage_mode(snapshot.audio_file_storage_mode, default=None)
        if storage_mode == STORAGE_MODE_DATABASE or snapshot.audio_file_blob_b64:
            if filename:
                return f"{filename} (stored in database)"
            return "Stored in database"
        return filename

    def _audio_conversion_unavailable_message(self) -> str:
        if self.audio_conversion_service is None or not self.audio_conversion_service.is_available():
            return (
                "Managed audio derivative export requires ffmpeg on PATH. "
                "Install ffmpeg to enable derivative export and the external conversion utility."
            )
        if self.track_service is None:
            return "Managed audio derivative export requires an open profile."
        return ""

    def _prompt_audio_conversion_format(
        self,
        *,
        title: str,
        prompt: str,
        capability_group: str,
    ) -> str | None:
        if self.audio_conversion_service is None:
            return None
        capabilities = self.audio_conversion_service.capabilities()
        if capability_group == "managed_authenticity":
            profiles = capabilities.managed_targets
        elif capability_group == "managed_lossy":
            profiles = capabilities.managed_lossy_targets
        elif capability_group in {"managed", "managed_any"}:
            profiles = tuple(
                list(capabilities.managed_targets)
                + [
                    profile
                    for profile in capabilities.managed_lossy_targets
                    if all(existing.id != profile.id for existing in capabilities.managed_targets)
                ]
            )
        else:
            profiles = capabilities.external_targets
        if not profiles:
            return None
        labels = [profile.label for profile in profiles]
        label, ok = QInputDialog.getItem(self, title, prompt, labels, 0, False)
        if not ok or not label:
            return None
        for profile in profiles:
            if profile.label == label:
                return profile.id
        return None

    def _selected_track_ids_with_audio(self, track_ids: list[int] | None = None) -> list[int]:
        if self.track_service is None:
            return []
        selected_ids = self._normalize_track_ids(track_ids or self._selected_or_visible_track_ids())
        return [
            track_id
            for track_id in selected_ids
            if self.track_service.has_media(track_id, "audio_file")
        ]

    def convert_selected_audio(self, track_ids: list[int] | None = None):
        title = "Export Managed Audio Derivatives"
        if self.track_service is None:
            QMessageBox.warning(self, title, "Open a profile first.")
            return
        unavailable_message = self._audio_conversion_unavailable_message()
        if unavailable_message:
            QMessageBox.warning(self, title, unavailable_message)
            return
        selected_ids = self._selected_track_ids_with_audio(track_ids)
        if not selected_ids:
            QMessageBox.information(
                self,
                title,
                "Select one or more tracks with attached primary audio first.",
            )
            return
        output_format = self._prompt_audio_conversion_format(
            title=title,
            prompt=(
                "Choose the managed derivative output format. "
                "Lossless targets stay on the watermark-authentic path; "
                "lossy targets export as tagged managed derivatives. "
                "Use the External Audio Conversion Utility when you do not want catalog metadata or derivative tracking."
            ),
            capability_group="managed_any",
        )
        if not output_format:
            return
        authenticity_required = self.audio_conversion_service is not None and self.audio_conversion_service.is_supported_target(
            output_format,
            capability_group="managed_authenticity",
        )
        if authenticity_required and self.audio_authenticity_service is None:
            QMessageBox.warning(
                self,
                title,
                "Lossless managed exports require an open profile with audio authenticity services. Choose a lossy output format or use the watermark-authentic master export workflow.",
            )
            return
        output_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose Export Folder for Managed Audio Derivatives",
            str(self.exports_dir / "managed_audio_derivatives"),
        )
        if not output_dir:
            return

        def _worker(bundle, ctx):
            coordinator = ManagedDerivativeExportCoordinator(
                conn=bundle.conn,
                track_service=bundle.track_service,
                release_service=bundle.release_service,
                tag_service=bundle.audio_tag_service,
                authenticity_service=bundle.audio_authenticity_service,
                conversion_service=AudioConversionService(),
            )
            request = ManagedDerivativeExportRequest(
                track_ids=selected_ids,
                output_dir=output_dir,
                output_format=output_format,
                derivative_kind=(
                    MANAGED_DERIVATIVE_KIND_WATERMARK_AUTHENTIC
                    if authenticity_required
                    else MANAGED_DERIVATIVE_KIND_LOSSY
                ),
                profile_name=self._current_profile_name(),
            )
            return coordinator.export(
                request,
                progress_callback=lambda value, maximum, message: ctx.report_progress(
                    value=value,
                    maximum=maximum,
                    message=message,
                ),
                is_cancelled=ctx.is_cancelled,
            )

        def _success(result: ManagedDerivativeExportResult):
            self._log_event(
                "audio.derivative_export",
                "Exported managed catalog derivatives",
                output_dir=output_dir,
                output_format=output_format,
                derivative_kind=result.derivative_kind,
                authenticity_basis=result.authenticity_basis,
                exported=result.exported,
                skipped=result.skipped,
                batch_public_id=result.batch_public_id,
                zip_path=result.zip_path,
                warnings=result.warnings,
            )
            self._audit(
                "EXPORT",
                "TrackAudioDerivative",
                ref_id=result.batch_public_id,
                details=(
                    f"exported={result.exported}; skipped={result.skipped}; format={output_format}; "
                    f"derivative_kind={result.derivative_kind}; authenticity_basis={result.authenticity_basis}"
                ),
            )
            self._audit_commit()
            target_text = result.zip_path or "\n".join(result.written_paths[:3]) or output_dir
            QMessageBox.information(
                self,
                title,
                f"Exported {result.exported} managed audio derivative file{'s' if result.exported != 1 else ''}."
                f"\n\nOutput:\n{target_text}"
                + (
                    "\n\nThese exports were finalized on the watermark-authentic path."
                    if result.watermark_applied
                    else "\n\nThese exports are managed lossy derivatives with catalog metadata and derivative lineage."
                )
                + f"\n\nSkipped: {result.skipped}"
                + (
                    "\n\nWarnings:\n- " + "\n- ".join(result.warnings[:12])
                    if result.warnings
                    else ""
                ),
            )

        self._submit_background_bundle_task(
            title=title,
            description=(
                "Converting selected catalog audio, writing tags, branching into watermark-authentic or lossy managed derivative finalization, and registering derivatives..."
            ),
            task_fn=_worker,
            kind="write",
            unique_key="audio.derivative_export",
            cancellable=True,
            on_success=_success,
            on_cancelled=lambda: self.statusBar().showMessage(
                "Managed audio derivative export cancelled.", 5000
            ),
            on_error=lambda failure: self._show_background_task_error(
                title,
                failure,
                user_message="Could not export managed audio derivatives:",
            ),
        )

    def convert_external_audio_files(self):
        title = "External Audio Conversion Utility"
        if self.audio_conversion_service is None or not self.audio_conversion_service.is_available():
            QMessageBox.warning(
                self,
                title,
                "External audio conversion utility requires ffmpeg on PATH. "
                "Install ffmpeg to enable plain file conversion.",
            )
            return
        chosen_files, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "Choose External Audio Files for Utility Conversion",
            "",
            "Audio Files (*.wav *.aif *.aiff *.mp3 *.flac *.m4a *.aac *.ogg *.oga *.opus *.mp4);;All Files (*)",
        )
        input_paths = [str(Path(path)) for path in dict.fromkeys(chosen_files) if str(path).strip()]
        if not input_paths:
            return
        output_format = self._prompt_audio_conversion_format(
            title=title,
            prompt=(
                "Choose the utility conversion output format. "
                "This does not use catalog metadata, watermarking, or derivative registration."
            ),
            capability_group="external",
        )
        if not output_format:
            return
        output_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose Output Folder for Utility Conversion",
            str(self.exports_dir / "external_audio_conversions"),
        )
        if not output_dir:
            return

        def _worker(ctx):
            coordinator = ExternalAudioConversionCoordinator(
                conversion_service=AudioConversionService()
            )
            request = ExternalAudioConversionRequest(
                input_paths=input_paths,
                output_dir=output_dir,
                output_format=output_format,
            )
            return coordinator.export(
                request,
                progress_callback=lambda value, maximum, message: ctx.report_progress(
                    value=value,
                    maximum=maximum,
                    message=message,
                ),
                is_cancelled=ctx.is_cancelled,
            )

        def _success(result: ExternalAudioConversionResult):
            self._log_event(
                "audio.external_convert",
                "Converted external audio files",
                output_dir=output_dir,
                output_format=output_format,
                exported=result.exported,
                skipped=result.skipped,
                batch_public_id=result.batch_public_id,
                zip_path=result.zip_path,
                warnings=result.warnings,
            )
            target_text = result.zip_path or "\n".join(result.written_paths[:3]) or output_dir
            QMessageBox.information(
                self,
                title,
                f"Converted {result.exported} external audio file{'s' if result.exported != 1 else ''} with the utility workflow."
                f"\n\nOutput:\n{target_text}"
                "\n\nNo catalog metadata, watermarking, or managed derivative registration was applied."
                f"\n\nSkipped: {result.skipped}"
                + (
                    "\n\nWarnings:\n- " + "\n- ".join(result.warnings[:12])
                    if result.warnings
                    else ""
                ),
            )

        self._submit_background_task(
            title=title,
            description=(
                "Converting external audio files with the utility workflow only. "
                "No catalog metadata, watermarking, or managed derivative registration..."
            ),
            task_fn=_worker,
            kind="read",
            unique_key="audio.external_convert",
            requires_profile=False,
            cancellable=True,
            on_success=_success,
            on_cancelled=lambda: self.statusBar().showMessage(
                "External audio utility conversion cancelled.", 5000
            ),
            on_error=lambda failure: self._show_background_task_error(
                title,
                failure,
                user_message="Could not run the external audio conversion utility:",
            ),
        )

    def write_tags_to_exported_audio(self, track_ids: list[int] | None = None):
        if self.tagged_audio_export_service is None or self.track_service is None:
            QMessageBox.warning(self, "Write Tags to Exported Audio", "Open a profile first.")
            return
        selected_ids = self._normalize_track_ids(track_ids or self._selected_or_visible_track_ids())
        if not selected_ids:
            QMessageBox.information(
                self,
                "Write Tags to Exported Audio",
                "Select one or more tracks or apply a filter first.",
            )
            return

        def _preview_worker(bundle, ctx):
            return self._prepare_tagged_audio_export_preview(
                selected_ids,
                track_service=bundle.track_service,
                release_service=bundle.release_service,
                progress_callback=lambda value, maximum, message: ctx.report_progress(
                    value=value,
                    maximum=maximum,
                    message=message,
                ),
            )

        def _preview_success(result: dict[str, object]):
            prepared = list(result.get("prepared") or [])
            preview_rows = list(result.get("rows") or [])
            warnings = list(result.get("warnings") or [])
            if not prepared:
                QMessageBox.information(
                    self,
                    "Write Tags to Exported Audio",
                    "No exportable audio files were available for the selected tracks."
                    + (f"\n\nWarnings:\n- " + "\n- ".join(warnings[:12]) if warnings else ""),
                )
                return

            dlg = TagPreviewDialog(
                title="Write Tags to Exported Audio",
                intro=(
                    "Preview the catalog metadata that will be written into exported audio copies. "
                    "The original stored audio stays untouched."
                ),
                rows=preview_rows,
                initial_policy="prefer_database",
                allow_policy_change=False,
                parent=self,
            )
            if dlg.exec() != QDialog.Accepted:
                return

            output_dir = QFileDialog.getExistingDirectory(
                self,
                "Choose Export Folder for Tagged Audio Copies",
                str(self.exports_dir / "tagged_audio"),
            )
            if not output_dir:
                return

            def _worker(bundle, ctx):
                overall_total = max(1, len(prepared) * 2)
                exports, prepare_warnings = self._build_tagged_audio_export_items(
                    prepared,
                    track_service=bundle.track_service,
                    release_service=bundle.release_service,
                    progress_callback=lambda value, maximum, message: ctx.report_progress(
                        value=value,
                        maximum=overall_total,
                        message=message,
                    ),
                    is_cancelled=ctx.is_cancelled,
                )
                result = bundle.tagged_audio_export_service.export_copies(
                    output_dir=output_dir,
                    exports=exports,
                    progress_callback=lambda value, maximum, message: ctx.report_progress(
                        value=max(0, len(prepared)) + value,
                        maximum=max(0, len(prepared)) + maximum,
                        message=message,
                    ),
                    is_cancelled=ctx.is_cancelled,
                )
                return {
                    "result": result,
                    "warnings": prepare_warnings,
                }

            def _success(payload: dict[str, object]):
                export_result = payload.get("result")
                if export_result is None:
                    raise ValueError("Tagged audio export did not return a result.")
                result = export_result
                all_warnings = (
                    warnings + list(payload.get("warnings") or []) + list(result.warnings)
                )
                self._log_event(
                    "tags.export_audio",
                    "Exported tagged audio copies",
                    output_dir=output_dir,
                    exported=result.exported,
                    skipped=result.skipped,
                    warnings=all_warnings,
                )
                self._audit(
                    "EXPORT",
                    "AudioTags",
                    ref_id=output_dir,
                    details=f"exported={result.exported}; skipped={result.skipped}",
                )
                self._audit_commit()
                QMessageBox.information(
                    self,
                    "Write Tags to Exported Audio",
                    f"Exported {result.exported} tagged audio cop{'y' if result.exported == 1 else 'ies'} to:\n{output_dir}"
                    f"\n\nSkipped: {result.skipped}"
                    + (
                        f"\n\nWarnings:\n- " + "\n- ".join(all_warnings[:12])
                        if all_warnings
                        else ""
                    ),
                )

            self._submit_background_bundle_task(
                title="Write Tags to Exported Audio",
                description="Writing catalog metadata into exported audio copies...",
                task_fn=_worker,
                kind="read",
                unique_key="tags.export_audio",
                cancellable=True,
                on_success=_success,
                on_cancelled=lambda: self.statusBar().showMessage(
                    "Tagged audio export cancelled.", 5000
                ),
                on_error=lambda failure: self._show_background_task_error(
                    "Write Tags to Exported Audio",
                    failure,
                    user_message="Could not export tagged audio copies:",
                ),
            )

        self._submit_background_bundle_task(
            title="Write Tags to Exported Audio",
            description="Preparing the tagged audio export preview...",
            task_fn=_preview_worker,
            kind="read",
            unique_key="tags.export_audio.preview",
            cancellable=False,
            on_success=_preview_success,
            on_error=lambda failure: self._show_background_task_error(
                "Write Tags to Exported Audio",
                failure,
                user_message="Could not prepare the tagged audio export preview:",
            ),
        )

    def open_audio_authenticity_keys_dialog(self):
        if not AUTHENTICITY_FEATURE_AVAILABLE:
            QMessageBox.warning(
                self,
                "Audio Authenticity Keys",
                authenticity_unavailable_message(),
            )
            return
        if self.authenticity_key_service is None:
            QMessageBox.warning(self, "Audio Authenticity Keys", "Open a profile first.")
            return
        AuthenticityKeysDialog(
            key_service=self.authenticity_key_service,
            parent=self,
        ).exec()

    def export_authenticity_watermarked_audio(self, track_ids: list[int] | None = None):
        title = "Export Watermark-Authentic Masters"
        if not AUTHENTICITY_FEATURE_AVAILABLE:
            QMessageBox.warning(
                self,
                title,
                authenticity_unavailable_message(),
            )
            return
        if self.audio_authenticity_service is None:
            QMessageBox.warning(
                self,
                title,
                "Open a profile first.",
            )
            return
        selected_ids = self._normalize_track_ids(track_ids or self._selected_or_visible_track_ids())
        if not selected_ids:
            QMessageBox.information(
                self,
                title,
                "Select one or more tracks or apply a filter first.",
            )
            return

        def _preview_worker(bundle, _ctx):
            return bundle.audio_authenticity_service.build_export_plan(
                selected_ids,
                profile_name=self._current_profile_name(),
            )

        def _preview_success(plan):
            ready_items = plan.ready_items()
            if not ready_items:
                QMessageBox.information(
                    self,
                    title,
                    "No supported WAV, FLAC, or AIFF master audio was available for the selected tracks."
                    + (
                        "\n\nWarnings:\n- " + "\n- ".join(plan.warnings[:12])
                        if plan.warnings
                        else ""
                    ),
                )
                return
            preview_dialog = AuthenticityExportPreviewDialog(plan=plan, parent=self)
            if preview_dialog.exec() != QDialog.Accepted:
                return
            output_dir = QFileDialog.getExistingDirectory(
                self,
                "Choose Export Folder for Watermark-Authentic Masters",
                str(self.exports_dir / "authenticity_audio"),
            )
            if not output_dir:
                return

            def _worker(bundle, ctx):
                return bundle.audio_authenticity_service.export_watermarked_audio(
                    output_dir=output_dir,
                    track_ids=[item.track_id for item in ready_items],
                    key_id=plan.key_id,
                    profile_name=self._current_profile_name(),
                    progress_callback=lambda value, maximum, message: ctx.report_progress(
                        value=value,
                        maximum=maximum,
                        message=message,
                    ),
                    is_cancelled=ctx.is_cancelled,
                )

            def _success(result):
                all_warnings = list(result.warnings)
                self._log_event(
                    "authenticity.export_audio",
                    "Exported authenticity-watermarked audio",
                    output_dir=output_dir,
                    exported=result.exported,
                    skipped=result.skipped,
                    warnings=all_warnings,
                )
                self._audit(
                    "EXPORT",
                    "AudioAuthenticity",
                    ref_id=output_dir,
                    details=f"exported={result.exported}; skipped={result.skipped}",
                )
                self._audit_commit()
                QMessageBox.information(
                    self,
                    title,
                    f"Exported {result.exported} watermark-authentic master cop{'y' if result.exported == 1 else 'ies'} to:\n{output_dir}"
                    "\n\nThese are direct-watermark master exports, not managed lossy derivatives."
                    f"\n\nSkipped: {result.skipped}"
                    + (
                        "\n\nWarnings:\n- " + "\n- ".join(all_warnings[:12]) if all_warnings else ""
                    ),
                )

            self._submit_background_bundle_task(
                title=title,
                description="Embedding direct watermarks and writing signed authenticity sidecars for master exports...",
                task_fn=_worker,
                kind="write",
                unique_key="authenticity.export_audio",
                cancellable=True,
                on_success=_success,
                on_cancelled=lambda: self.statusBar().showMessage(
                    "Watermark-authentic master export cancelled.", 5000
                ),
                on_error=lambda failure: self._show_background_task_error(
                    title,
                    failure,
                    user_message="Could not export watermark-authentic masters:",
                ),
            )

        self._submit_background_bundle_task(
            title=title,
            description="Preparing the direct-watermark master export preview...",
            task_fn=_preview_worker,
            kind="read",
            unique_key="authenticity.export_audio.preview",
            on_success=_preview_success,
            on_error=lambda failure: self._show_background_task_error(
                title,
                failure,
                user_message="Could not prepare the watermark-authentic master export preview:",
            ),
        )

    def export_authenticity_provenance_audio(self, track_ids: list[int] | None = None):
        title = "Export Provenance-Linked Lossy Copies"
        if not AUTHENTICITY_FEATURE_AVAILABLE:
            QMessageBox.warning(
                self,
                title,
                authenticity_unavailable_message(),
            )
            return
        if self.audio_authenticity_service is None:
            QMessageBox.warning(
                self,
                title,
                "Open a profile first.",
            )
            return
        selected_ids = self._normalize_track_ids(track_ids or self._selected_or_visible_track_ids())
        if not selected_ids:
            QMessageBox.information(
                self,
                title,
                "Select one or more tracks or apply a filter first.",
            )
            return

        def _preview_worker(bundle, _ctx):
            return bundle.audio_authenticity_service.build_provenance_export_plan(
                selected_ids,
                profile_name=self._current_profile_name(),
            )

        def _preview_success(plan):
            ready_items = plan.ready_items()
            if not ready_items:
                QMessageBox.information(
                    self,
                    title,
                    "No supported provenance-only attached audio was available for the selected tracks."
                    + (
                        "\n\nWarnings:\n- " + "\n- ".join(plan.warnings[:12])
                        if plan.warnings
                        else ""
                    ),
                )
                return
            preview_dialog = AuthenticityExportPreviewDialog(
                plan=plan,
                title=title,
                subtitle=(
                    "This workflow copies lossy audio as-is, writes catalog tags, and saves a signed lineage sidecar that points back to a verified watermark-authentic master. It does not create managed derivative records."
                ),
                parent=self,
            )
            if preview_dialog.exec() != QDialog.Accepted:
                return
            output_dir = QFileDialog.getExistingDirectory(
                self,
                "Choose Export Folder for Provenance-Linked Lossy Copies",
                str(self.exports_dir / "authenticity_lineage"),
            )
            if not output_dir:
                return

            def _worker(bundle, ctx):
                return bundle.audio_authenticity_service.export_provenance_audio(
                    output_dir=output_dir,
                    track_ids=[item.track_id for item in ready_items],
                    key_id=plan.key_id,
                    profile_name=self._current_profile_name(),
                    progress_callback=lambda value, maximum, message: ctx.report_progress(
                        value=value,
                        maximum=maximum,
                        message=message,
                    ),
                    is_cancelled=ctx.is_cancelled,
                )

            def _success(result):
                all_warnings = list(result.warnings)
                self._log_event(
                    "authenticity.export_provenance_audio",
                    "Exported authenticity provenance audio",
                    output_dir=output_dir,
                    exported=result.exported,
                    skipped=result.skipped,
                    warnings=all_warnings,
                )
                self._audit(
                    "EXPORT",
                    "AudioAuthenticityLineage",
                    ref_id=output_dir,
                    details=f"exported={result.exported}; skipped={result.skipped}",
                )
                self._audit_commit()
                QMessageBox.information(
                    self,
                    title,
                    f"Exported {result.exported} provenance-linked lossy cop{'y' if result.exported == 1 else 'ies'} to:\n{output_dir}"
                    "\n\nThese copies keep signed lineage sidecars, but they are not managed derivatives."
                    f"\n\nSkipped: {result.skipped}"
                    + (
                        "\n\nWarnings:\n- " + "\n- ".join(all_warnings[:12]) if all_warnings else ""
                    ),
                )

            self._submit_background_bundle_task(
                title=title,
                description="Writing lossy copies and signed provenance sidecars that point back to watermark-authentic masters...",
                task_fn=_worker,
                kind="write",
                unique_key="authenticity.export_provenance_audio",
                cancellable=True,
                on_success=_success,
                on_cancelled=lambda: self.statusBar().showMessage(
                    "Provenance-linked lossy export cancelled.", 5000
                ),
                on_error=lambda failure: self._show_background_task_error(
                    title,
                    failure,
                    user_message="Could not export provenance-linked lossy copies:",
                ),
            )

        self._submit_background_bundle_task(
            title=title,
            description="Preparing the provenance-linked lossy export preview...",
            task_fn=_preview_worker,
            kind="read",
            unique_key="authenticity.export_provenance_audio.preview",
            on_success=_preview_success,
            on_error=lambda failure: self._show_background_task_error(
                title,
                failure,
                user_message="Could not prepare the provenance-linked lossy export preview:",
            ),
        )

    def _selected_track_audio_verification_option(self):
        if self.track_service is None:
            return None
        selected_ids = self._normalize_track_ids(self._selected_track_ids())
        if len(selected_ids) != 1:
            return None
        track_id = selected_ids[0]
        snapshot = self.track_service.fetch_track_snapshot(track_id)
        if snapshot is None or not self.track_service.has_media(track_id, "audio_file"):
            return None
        suffix = Path(snapshot.audio_file_filename or snapshot.audio_file_path or "").suffix.lower()
        if suffix not in VERIFICATION_INPUT_SUFFIXES:
            return None
        return int(track_id), str(snapshot.track_title or f"Track {track_id}")

    def _selected_track_audio_verification_candidate(self, track_id: int | None = None):
        if self.track_service is None:
            return None, None
        if track_id is None:
            selected_option = self._selected_track_audio_verification_option()
            if selected_option is None:
                return None, None
            track_id = int(selected_option[0])
        snapshot = self.track_service.fetch_track_snapshot(track_id)
        if snapshot is None or not self.track_service.has_media(track_id, "audio_file"):
            return None, None
        suffix = Path(snapshot.audio_file_filename or snapshot.audio_file_path or "").suffix.lower()
        if suffix not in VERIFICATION_INPUT_SUFFIXES:
            return None, None
        resolved = self.track_service.resolve_media_path(snapshot.audio_file_path)
        if resolved is not None and resolved.exists():
            return resolved, None
        try:
            audio_bytes, _mime_type = self.track_service.fetch_media_bytes(track_id, "audio_file")
        except Exception:
            return None, None
        temp_root = Path(tempfile.mkdtemp(prefix="isrcm-auth-verify-"))
        temp_path = temp_root / (snapshot.audio_file_filename or f"track-{track_id}{suffix}")
        temp_path.write_bytes(audio_bytes)
        return temp_path, temp_root

    def _prompt_audio_authenticity_verification_source(self, track_label: str) -> str | None:
        chooser = QMessageBox(self)
        chooser.setWindowTitle("Verify Audio Authenticity")
        chooser.setIcon(QMessageBox.Question)
        chooser.setText("Choose which audio you want to verify.")
        chooser.setInformativeText(
            "Verify the selected catalog audio for "
            f"'{track_label}', or choose an external direct/provenance-supported file."
        )
        selected_button = chooser.addButton("Selected Track Audio", QMessageBox.AcceptRole)
        external_button = chooser.addButton("Choose External File…", QMessageBox.ActionRole)
        chooser.addButton("Cancel", QMessageBox.RejectRole)
        chooser.setDefaultButton(selected_button)
        chooser.exec()
        clicked = chooser.clickedButton()
        if clicked is selected_button:
            return "selected"
        if clicked is external_button:
            return "external"
        return None

    def _pick_audio_authenticity_verification_file(self) -> Path | None:
        chosen_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Choose Audio File to Verify",
            "",
            "Audio Files (*.wav *.flac *.aif *.aiff *.mp3 *.ogg *.oga *.opus *.m4a *.mp4 *.aac)",
        )
        if not chosen_path:
            return None
        return Path(chosen_path).resolve()

    def verify_audio_authenticity(self, path: str | None = None):
        if not AUTHENTICITY_FEATURE_AVAILABLE:
            QMessageBox.warning(
                self,
                "Verify Audio Authenticity",
                authenticity_unavailable_message(),
            )
            return
        if self.audio_authenticity_service is None:
            QMessageBox.warning(self, "Verify Audio Authenticity", "Open a profile first.")
            return
        verification_path = Path(path).resolve() if path else None
        cleanup_root = None
        if verification_path is None:
            selected_option = self._selected_track_audio_verification_option()
            if selected_option is not None:
                selected_track_id, selected_track_label = selected_option
                choice = self._prompt_audio_authenticity_verification_source(selected_track_label)
                if choice is None:
                    return
                if choice == "selected":
                    verification_path, cleanup_root = (
                        self._selected_track_audio_verification_candidate(selected_track_id)
                    )
                    if verification_path is None:
                        QMessageBox.warning(
                            self,
                            "Verify Audio Authenticity",
                            "The selected track no longer has a supported direct or provenance audio file. Choose an external file instead.",
                        )
                        verification_path = self._pick_audio_authenticity_verification_file()
                else:
                    verification_path = self._pick_audio_authenticity_verification_file()
            else:
                verification_path = self._pick_audio_authenticity_verification_file()
        if verification_path is None:
            return

        def _worker(bundle, _ctx):
            return bundle.audio_authenticity_service.verify_file(verification_path)

        def _finished():
            if cleanup_root is not None:
                shutil.rmtree(cleanup_root, ignore_errors=True)

        def _success(report):
            self._log_event(
                "authenticity.verify_audio",
                "Verified audio authenticity",
                path=str(verification_path),
                status=report.status,
                manifest_id=report.manifest_id,
                key_id=report.key_id,
            )
            self._audit(
                "VERIFY",
                "AudioAuthenticity",
                ref_id=str(verification_path),
                details=report.status,
            )
            self._audit_commit()
            AuthenticityVerificationDialog(report=report, parent=self).exec()

        self._submit_background_bundle_task(
            title="Verify Audio Authenticity",
            description="Verifying the direct watermark path or signed provenance lineage...",
            task_fn=_worker,
            kind="read",
            unique_key="authenticity.verify_audio",
            on_success=_success,
            on_finished=_finished,
            on_error=lambda failure: self._show_background_task_error(
                "Verify Audio Authenticity",
                failure,
                user_message="Could not verify audio authenticity:",
            ),
        )

    def import_exchange_file(self, format_name: str):
        if self.exchange_service is None:
            QMessageBox.warning(self, "Import Exchange", "Open a profile first.")
            return
        normalized_format = str(format_name or "").strip().lower()
        filters = {
            "csv": "CSV Files (*.csv)",
            "xlsx": "Excel Workbook (*.xlsx)",
            "json": "JSON Files (*.json)",
            "package": "ZIP Packages (*.zip)",
        }
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Import {normalized_format.upper()}",
            "",
            filters.get(normalized_format, "All files (*)"),
        )
        if not path:
            return

        def _inspection_worker(bundle, ctx):
            ctx.set_status(f"Inspecting {normalized_format.upper()} source file...")
            if normalized_format == "csv":
                return bundle.exchange_service.inspect_csv(path)
            if normalized_format == "xlsx":
                return bundle.exchange_service.inspect_xlsx(path)
            if normalized_format == "json":
                return bundle.exchange_service.inspect_json(path)
            if normalized_format == "package":
                return bundle.exchange_service.inspect_package(path)
            raise ValueError(f"Unsupported exchange format: {normalized_format}")

        def _inspection_success(inspection):
            supported_headers = self.exchange_service.supported_import_targets()

            def _csv_reinspect(delimiter: str | None) -> ExchangeInspection:
                return self.exchange_service.inspect_csv(path, delimiter=delimiter)

            dlg = ExchangeImportDialog(
                inspection=inspection,
                supported_headers=supported_headers,
                settings=self.settings,
                initial_mode=("create" if normalized_format == "package" else "dry_run"),
                csv_reinspect_callback=(_csv_reinspect if normalized_format == "csv" else None),
                parent=self,
            )
            if dlg.exec() != QDialog.Accepted:
                return

            mapping = dlg.mapping()
            options = dlg.import_options()
            selected_csv_delimiter = dlg.resolved_csv_delimiter()

            def _import_worker(bundle, ctx):
                ctx.set_status(f"Importing {normalized_format.upper()} exchange data...")

                def _mutation():
                    if normalized_format == "csv":
                        return bundle.exchange_service.import_csv(
                            path,
                            mapping=mapping,
                            options=options,
                            delimiter=selected_csv_delimiter,
                        )
                    if normalized_format == "xlsx":
                        return bundle.exchange_service.import_xlsx(
                            path, mapping=mapping, options=options
                        )
                    if normalized_format == "package":
                        return bundle.exchange_service.import_package(
                            path,
                            mapping=mapping,
                            options=options,
                        )
                    return bundle.exchange_service.import_json(
                        path,
                        mapping=mapping,
                        options=options,
                    )

                if options.mode == "dry_run":
                    return _mutation()

                return run_snapshot_history_action(
                    history_manager=bundle.history_manager,
                    action_label=f"Import {normalized_format.upper()}: {Path(path).name}",
                    action_type=f"import.{normalized_format}",
                    entity_type="Import",
                    entity_id=path,
                    payload={"path": path, "mode": options.mode},
                    mutation=_mutation,
                    logger=self.logger,
                )

            def _import_success(report: ExchangeImportReport):
                changed = bool(report.created_tracks or report.updated_tracks)
                try:
                    self.conn.commit()
                except Exception:
                    pass
                if options.mode != "dry_run":
                    self.active_custom_fields = self.load_active_custom_fields()
                    self._rebuild_table_headers()
                    try:
                        self._load_header_state()
                    except Exception:
                        pass
                    self._refresh_history_actions()
                if changed:
                    self.refresh_table_preserve_view(
                        focus_id=(report.created_tracks or report.updated_tracks or [None])[0]
                    )
                    self.populate_all_comboboxes()

                self._log_event(
                    f"import.{normalized_format}",
                    f"Imported {normalized_format.upper()} exchange data",
                    path=path,
                    mode=options.mode,
                    passed=report.passed,
                    failed=report.failed,
                    skipped=report.skipped,
                    warnings=report.warnings,
                    duplicates=report.duplicates,
                    unknown_fields=report.unknown_fields,
                )
                self._audit(
                    "IMPORT",
                    normalized_format.upper(),
                    ref_id=path,
                    details=(
                        f"mode={options.mode}; passed={report.passed}; failed={report.failed}; "
                        f"skipped={report.skipped}; duplicates={len(report.duplicates)}"
                    ),
                )
                self._audit_commit()
                self._show_exchange_import_report(path, report)

            self._submit_background_bundle_task(
                title=f"Import {normalized_format.upper()}",
                description=f"Importing {normalized_format.upper()} data into the current profile...",
                task_fn=_import_worker,
                kind=("read" if options.mode == "dry_run" else "write"),
                unique_key=f"exchange.import.{normalized_format}",
                on_success=_import_success,
                on_error=lambda failure: self._show_background_task_error(
                    "Import Exchange",
                    failure,
                    user_message="Could not complete the exchange import:",
                ),
            )

        self._submit_background_bundle_task(
            title=f"Inspect {normalized_format.upper()}",
            description=f"Inspecting the selected {normalized_format.upper()} source...",
            task_fn=_inspection_worker,
            kind="read",
            unique_key=f"exchange.inspect.{normalized_format}",
            on_success=_inspection_success,
            on_error=lambda failure: self._show_background_task_error(
                "Import Exchange",
                failure,
                user_message="Could not inspect the selected file:",
            ),
        )

    def reset_saved_exchange_import_choices(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Reset Saved Import Choices",
                "Clear the remembered import choices for CSV, XLSX, JSON, and ZIP package imports?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        self.settings.remove("exchange/import_preferences")
        self.settings.sync()
        QMessageBox.information(
            self,
            "Reset Saved Import Choices",
            "Saved exchange import choices were cleared.",
        )

    def _show_exchange_import_report(self, path: str, report: ExchangeImportReport) -> None:
        lines = [
            f"Format: {report.format_name.upper()}",
            f"Mode: {report.mode}",
            f"Passed: {report.passed}",
            f"Failed: {report.failed}",
            f"Skipped: {report.skipped}",
        ]
        if report.mode == "dry_run":
            lines.append("")
            lines.append(
                "No database changes were made because this run used Dry run validation mode."
            )
        if report.duplicates:
            lines.append(f"Duplicates: {len(report.duplicates)}")
        if report.unknown_fields:
            lines.append("Unknown fields: " + ", ".join(report.unknown_fields[:8]))
        if report.warnings:
            lines.append("")
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in report.warnings[:12])
        QMessageBox.information(
            self,
            f"Import {report.format_name.upper()}",
            "\n".join(lines) + f"\n\nSource:\n{path}",
        )

    def export_exchange_file(self, format_name: str, *, selected_only: bool):
        if self.exchange_service is None:
            QMessageBox.warning(self, "Export Exchange", "Open a profile first.")
            return
        normalized_format = str(format_name or "").strip().lower()
        track_ids = self._selected_or_visible_track_ids() if selected_only else None
        if selected_only and not track_ids:
            QMessageBox.information(
                self,
                "Export Exchange",
                "Select one or more rows or apply a filter first.",
            )
            return

        extension_map = {
            "csv": ("CSV Files (*.csv)", ".csv"),
            "xlsx": ("Excel Workbooks (*.xlsx)", ".xlsx"),
            "json": ("JSON Files (*.json)", ".json"),
            "package": ("ZIP Packages (*.zip)", ".zip"),
        }
        file_filter, suffix = extension_map.get(normalized_format, ("All files (*)", ""))
        default_name = f"{'selected' if selected_only else 'full'}_{normalized_format}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {normalized_format.upper()}",
            str(self.exports_dir / default_name),
            file_filter,
        )
        if not path:
            return

        def _worker(bundle, ctx):
            ctx.set_status(f"Exporting {normalized_format.upper()} exchange data...")

            def mutation():
                if normalized_format == "csv":
                    return bundle.exchange_service.export_csv(path, track_ids)
                if normalized_format == "xlsx":
                    return bundle.exchange_service.export_xlsx(path, track_ids)
                if normalized_format == "json":
                    return bundle.exchange_service.export_json(path, track_ids)
                if normalized_format == "package":
                    return bundle.exchange_service.export_package(path, track_ids)
                raise ValueError(f"Unsupported exchange format: {normalized_format}")

            return run_file_history_action(
                history_manager=bundle.history_manager,
                action_label=lambda count: f"Export {normalized_format.upper()}: {count} rows",
                action_type=f"file.export_{normalized_format}",
                target_path=path,
                mutation=mutation,
                entity_type="Export",
                entity_id=path,
                payload=lambda count: {
                    "path": path,
                    "format": normalized_format,
                    "selected_only": bool(selected_only),
                    "count": count,
                },
                logger=self.logger,
            )

        def _success(exported):
            self._refresh_history_actions()
            self._log_event(
                f"export.{normalized_format}",
                f"Exported {normalized_format.upper()} exchange data",
                path=path,
                exported=exported,
                selected_only=selected_only,
            )
            self._audit(
                "EXPORT",
                normalized_format.upper(),
                ref_id=path,
                details=f"count={exported}; selected_only={int(bool(selected_only))}",
            )
            self._audit_commit()
            QMessageBox.information(
                self,
                "Export Exchange",
                f"Exported {exported} row{'s' if exported != 1 else ''} to:\n{path}",
            )

        self._submit_background_bundle_task(
            title=f"Export {normalized_format.upper()}",
            description=f"Exporting {normalized_format.upper()} exchange data...",
            task_fn=_worker,
            kind="read",
            unique_key=f"exchange.export.{normalized_format}",
            on_success=_success,
            on_error=lambda failure: self._show_background_task_error(
                "Export Exchange",
                failure,
                user_message="Could not export the selected data:",
            ),
        )

    def open_quality_dashboard(self):
        if self.quality_service is None:
            QMessageBox.warning(self, "Data Quality Dashboard", "Open a profile first.")
            return
        dlg = QualityDashboardDialog(
            service=self.quality_service,
            scan_callback=self._scan_quality_dashboard_in_background,
            task_manager=self.background_tasks,
            release_choices_provider=self._release_choices,
            apply_fix_callback=self._apply_quality_fix,
            open_issue_callback=self._open_issue_from_dashboard,
            parent=self,
        )
        dlg.exec()

    def _scan_quality_dashboard_in_background(self):
        with self.background_service_factory.open_bundle() as bundle:
            return bundle.quality_service.scan()

    def _apply_quality_fix(self, issue: QualityIssue) -> str:
        fix_key = str(issue.fix_key or "").strip()
        if not fix_key:
            raise ValueError("The selected quality issue does not expose a suggested fix.")

        def mutation():
            return self.quality_service.apply_fix(fix_key, issue=issue)

        message = self._run_snapshot_history_action(
            action_label=f"Quality Fix: {fix_key}",
            action_type="quality.fix",
            entity_type="QualityIssue",
            entity_id=fix_key,
            payload={
                "fix_key": fix_key,
                "issue_type": issue.issue_type,
                "entity_type": issue.entity_type,
                "entity_id": issue.entity_id,
                "release_id": issue.release_id,
                "track_id": issue.track_id,
            },
            mutation=mutation,
        )
        self._log_event("quality.fix", "Applied quality fix", fix_key=fix_key, message_text=message)
        self._audit("REPAIR", "QualityIssue", ref_id=fix_key, details=message)
        self._audit_commit()
        self.refresh_table_preserve_view()
        self.populate_all_comboboxes()
        return str(message)

    def _open_issue_from_dashboard(self, issue: QualityIssue) -> None:
        if issue.entity_type == "track" and issue.track_id:
            self.open_selected_editor(issue.track_id)
            return
        if issue.entity_type == "release" and issue.release_id:
            self.open_release_editor(issue.release_id)
            return
        if issue.entity_type == "license":
            self.open_licenses_browser(track_filter_id=None)
            return

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
                    QMessageBox.warning(
                        self, "Delete", "Could not load the selected track for deletion."
                    )
                    return
                self._run_snapshot_history_action(
                    action_label=f"Delete Track: {before_snapshot.track_title}",
                    action_type="track.delete",
                    entity_type="Track",
                    entity_id=row_id,
                    payload={
                        "track_id": row_id,
                        "track_title": before_snapshot.track_title,
                        "isrc": before_snapshot.isrc,
                    },
                    mutation=lambda: self.track_service.delete_track(row_id),
                )
                self.refresh_table_preserve_view()
                self.populate_all_comboboxes()
                self._log_event(
                    "track.delete",
                    "Track deleted",
                    level=logging.WARNING,
                    track_id=row_id,
                    isrc=before_snapshot.isrc,
                    track_title=before_snapshot.track_title,
                )
                self._audit("DELETE", "Track", ref_id=row_id, details="delete_entry")
                self._audit_commit()
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
            self._update_add_data_generated_fields()
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
        self._update_add_data_generated_fields()

    # =============================================================================
    # ISRC generation (YY + AA + SSS) with strict ISO compliance
    # =============================================================================
    def generate_isrc(self) -> str:
        return self._next_generated_isrc(
            release_date=self.release_date_field.selectedDate(),
            use_release_year=bool(self.prev_release_toggle.isChecked()),
        )

    # =============================================================================
    # Export / Import (with location picker, overwrite confirm, dry-run option)
    # =============================================================================
    def export_full_to_xml(self):
        default_name = f"full_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
        default_path = str(self.exports_dir / default_name)
        path, sel = QFileDialog.getSaveFileName(
            self, "Export All to XML", default_path, "XML Files (*.xml)"
        )
        if not path:
            return

        if Path(path).exists():
            if (
                QMessageBox.question(
                    self,
                    "Overwrite?",
                    f"File exists:\n{path}\n\nOverwrite?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                != QMessageBox.Yes
            ):
                return

        def _worker(bundle, ctx):
            ctx.set_status("Exporting the full catalog to XML...")
            return run_file_history_action(
                history_manager=bundle.history_manager,
                action_label=lambda count: f"Export XML: {count} tracks",
                action_type="file.export_xml_all",
                target_path=path,
                mutation=lambda: bundle.xml_export_service.export_all(path),
                entity_type="Export",
                entity_id=path,
                payload=lambda count: {"path": path, "count": count},
                logger=self.logger,
            )

        def _success(exported):
            self._refresh_history_actions()
            QMessageBox.information(self, "Export", f"All data exported:\n{path}")
            self._log_event(
                "export.xml.all",
                "Exported full library to XML",
                path=path,
                exported=exported,
            )
            self._audit(
                "EXPORT",
                "Tracks",
                ref_id=path,
                details=f"all rows incl. duration+customs count={exported}",
            )
            self._audit_commit()

        self._submit_background_bundle_task(
            title="Export XML",
            description="Exporting the full catalog to XML...",
            task_fn=_worker,
            kind="read",
            unique_key="export.xml.all",
            on_success=_success,
            on_error=lambda failure: self._show_background_task_error(
                "Export Error",
                failure,
                user_message="Failed to export the library to XML:",
            ),
        )

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
                QMessageBox.information(
                    self, "Export Selected", "Select one or more rows (or apply a filter) first."
                )
                return
            rows = [idx.row() for idx in sel.selectedRows()]

        track_ids = sorted(
            {
                int(self.table.item(r, 0).text())
                for r in rows
                if self.table.item(r, 0) and self.table.item(r, 0).text().strip().isdigit()
            }
        )
        if not track_ids:
            QMessageBox.warning(self, "Export Selected", "No valid track IDs found to export.")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"Selected_Tracks_{ts}.xml"
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Selected to XML",
            str(self.exports_dir / default_name),
            "XML Files (*.xml)",
        )
        if not out_path:
            return

        def _worker(bundle, ctx):
            ctx.set_status("Exporting the selected tracks to XML...")
            return run_file_history_action(
                history_manager=bundle.history_manager,
                action_label=lambda count: f"Export Selected XML: {count} tracks",
                action_type="file.export_xml_selected",
                target_path=out_path,
                mutation=lambda: bundle.xml_export_service.export_selected(
                    out_path,
                    track_ids,
                    current_db_path=str(self.current_db_path),
                ),
                entity_type="Export",
                entity_id=out_path,
                payload=lambda count: {"path": out_path, "count": count, "track_ids": track_ids},
                logger=self.logger,
            )

        def _success(exported):
            self._refresh_history_actions()
            self._log_event(
                "export.xml.selected",
                "Exported selected tracks to XML",
                path=out_path,
                exported=exported,
                track_ids=track_ids,
            )
            QMessageBox.information(self, "Export Complete", f"Saved:\n{out_path}")

        self._submit_background_bundle_task(
            title="Export Selected XML",
            description="Exporting the selected tracks to XML...",
            task_fn=_worker,
            kind="read",
            unique_key="export.xml.selected",
            on_success=_success,
            on_error=lambda failure: self._show_background_task_error(
                "Export Error",
                failure,
                user_message="Could not write the selected XML export:",
            ),
        )

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
        file_path, _ = QFileDialog.getOpenFileName(self, "Import from XML", "", "XML Files (*.xml)")
        if not file_path:
            return

        dry = (
            QMessageBox.question(
                self,
                "Dry Run?",
                "Run a dry-run first (no changes will be written) to see the summary?",
                QMessageBox.Yes | QMessageBox.No,
            )
            == QMessageBox.Yes
        )

        def _inspection_worker(bundle, ctx):
            ctx.set_status("Inspecting the selected XML file...")
            return bundle.xml_import_service.inspect_file(file_path)

        def _inspection_success(inspection):
            create_missing_custom_fields = False
            if inspection.conflicting_custom_fields:
                msg = "Custom columns already exist with a different type:\n" + "\n".join(
                    f"- {name} : XML={import_type}, profile={existing_type}"
                    for name, import_type, existing_type in inspection.conflicting_custom_fields
                )
                self.logger.warning(
                    "Import aborted due to custom column type conflicts: %s",
                    inspection.conflicting_custom_fields,
                )
                self._log_trace(
                    "import.xml.custom_field_conflicts",
                    message="Import aborted due to custom column type conflicts",
                    path=file_path,
                    details=inspection.conflicting_custom_fields,
                )
                QMessageBox.critical(self, "Import Error", msg + "\n\nNo changes were made.")
                return

            if inspection.missing_custom_fields:
                msg = (
                    "This XML uses custom columns that do not exist in the current profile:\n\n"
                    + "\n".join(
                        f"- {name} : {field_type}"
                        for name, field_type in inspection.missing_custom_fields
                    )
                )
                create_missing_custom_fields = (
                    QMessageBox.question(
                        self,
                        "Create Missing Custom Columns?",
                        msg + "\n\nCreate these custom columns now and continue with the import?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    )
                    == QMessageBox.Yes
                )
                if not create_missing_custom_fields:
                    self.logger.info(
                        "Import canceled because custom columns were not created: %s",
                        inspection.missing_custom_fields,
                    )
                    self._log_trace(
                        "import.xml.missing_custom_fields_aborted",
                        message="Import canceled because missing custom columns were not created",
                        path=file_path,
                        details=inspection.missing_custom_fields,
                    )
                    return

            if dry:
                self._log_event(
                    "import.xml.dry_run",
                    "XML import dry-run completed",
                    path=file_path,
                    would_insert=inspection.would_insert,
                    duplicates=inspection.duplicate_count,
                    invalid=inspection.invalid_count,
                )
                proceed = (
                    QMessageBox.question(
                        self,
                        "Dry-run finished",
                        f"Would insert: {inspection.would_insert}\n"
                        f"Skipped (duplicates): {inspection.duplicate_count}\n"
                        f"Skipped (invalid): {inspection.invalid_count}\n"
                        f"Errors: 0\n"
                        + (
                            f"Will create custom columns: {len(inspection.missing_custom_fields)}\n"
                            if create_missing_custom_fields
                            else ""
                        )
                        + "\n"
                        f"Proceed with import now?",
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    == QMessageBox.Yes
                )
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

            def _import_worker(bundle, ctx):
                ctx.set_status("Importing XML data into the catalog...")
                return run_snapshot_history_action(
                    history_manager=bundle.history_manager,
                    action_label=f"Import XML: {Path(file_path).name}",
                    action_type="import.xml",
                    entity_type="Import",
                    entity_id=file_path,
                    payload={"path": file_path},
                    mutation=lambda: bundle.xml_import_service.execute_import(
                        file_path,
                        create_missing_custom_fields=create_missing_custom_fields,
                    ),
                    logger=self.logger,
                )

            def _import_success(result):
                try:
                    self.conn.commit()
                except Exception:
                    pass
                self.active_custom_fields = self.load_active_custom_fields()
                self._rebuild_table_headers()
                try:
                    self._load_header_state()
                except Exception:
                    pass
                self.refresh_table_preserve_view()
                self.populate_all_comboboxes()
                self._refresh_history_actions()

                mode = "Import finished" if not dry else "Import finished (after dry-run)"
                self._log_event(
                    "import.xml.commit",
                    mode,
                    path=file_path,
                    inserted=result.inserted,
                    duplicates=result.duplicate_count,
                    invalid=result.invalid_count,
                    errors=result.error_count,
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

                QMessageBox.information(
                    self,
                    mode,
                    f"Inserted: {result.inserted}\n"
                    f"Skipped (duplicates): {result.duplicate_count}\n"
                    f"Skipped (invalid): {result.invalid_count}\n"
                    f"Errors: {result.error_count}",
                )

            self._submit_background_bundle_task(
                title="Import XML",
                description="Importing XML data into the current profile...",
                task_fn=_import_worker,
                kind="write",
                unique_key="import.xml",
                on_success=_import_success,
                on_error=lambda failure: self._show_background_task_error(
                    "Import Error",
                    failure,
                    user_message="Could not complete the XML import:",
                ),
            )

        self._submit_background_bundle_task(
            title="Inspect XML",
            description="Inspecting the selected XML file...",
            task_fn=_inspection_worker,
            kind="read",
            unique_key="inspect.xml",
            on_success=_inspection_success,
            on_error=lambda failure: self._show_background_task_error(
                "Import Error",
                failure,
                user_message="Could not inspect the selected XML file:",
            ),
        )

    # =============================================================================
    # Settings (prefix / numbers) + summary dialog
    # =============================================================================
    def set_isrc_prefix(self, prefix: str | None = None):
        if prefix is None:
            self.open_settings_dialog(initial_focus="isrc_prefix")
            return

        pref = (prefix or "").strip().upper()
        if pref and not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}", pref):
            QMessageBox.warning(self, "Invalid Prefix", "Prefix must be CC+XXX (5 chars).")
            return
        try:
            self._apply_single_setting_value("isrc_prefix", pref)
        except Exception as e:
            self.logger.exception(f"Set ISRC prefix failed: {e}")
            QMessageBox.critical(self, "Error", f"Could not save prefix:\n{e}")

    def set_sena_number(self, value: str | None = None):
        if value is None:
            self.open_settings_dialog(initial_focus="sena_number")
            return
        try:
            self._apply_single_setting_value("sena_number", (value or "").strip())
        except Exception as e:
            self.logger.exception(f"Set SENA number failed: {e}")
            QMessageBox.critical(self, "Error", f"Could not save SENA number:\n{e}")

    def set_btw_number(self, value: str | None = None):
        if value is None:
            self.open_settings_dialog(initial_focus="btw_number")
            return
        try:
            self._apply_single_setting_value("btw_number", (value or "").strip())
        except Exception as e:
            self.logger.exception(f"Set BTW failed: {e}")
            QMessageBox.critical(self, "Error", f"Could not save BTW number:\n{e}")

    def set_buma_info(self, value: str | None = None):
        if value is None:
            self.open_settings_dialog(initial_focus="buma_relatie_nummer")
            return
        try:
            self._apply_single_setting_value("buma_relatie_nummer", (value or "").strip())
        except Exception as e:
            self.logger.exception(f"Set BUMA relatie nummer failed: {e}")
            QMessageBox.critical(self, "Error", f"Could not save BUMA relatie nummer:\n{e}")

    def set_ipi_info(self, value: str | None = None):
        if value is None:
            self.open_settings_dialog(initial_focus="buma_ipi")
            return
        try:
            self._apply_single_setting_value("buma_ipi", (value or "").strip())
        except Exception as e:
            self.logger.exception(f"Set BUMA IPI failed: {e}")
            QMessageBox.critical(self, "Error", f"Could not save BUMA IPI:\n{e}")

    def show_settings_summary(self):
        AboutDialog(self, parent=self).exec()

    # =============================================================================
    # View settings (interactive resize + draggable hints)
    # =============================================================================
    def _form_has_focus(self) -> bool:
        w = QApplication.focusWidget()
        return bool(
            w
            and hasattr(self, "left_widget_container")
            and self.left_widget_container.isAncestorOf(w)
        )

    def _apply_table_view_settings(self):
        self.table.horizontalHeader().setVisible(True)
        self.table.verticalHeader().setVisible(True)

    def _on_toggle_col_width(self, enabled: bool):
        enabled = bool(enabled)

        def mutation():
            self._apply_col_width_mode(enabled)
            self.settings.setValue("display/interactive_col_width", enabled)
            self.settings.sync()

        self._run_setting_bundle_history_action(
            action_label="Toggle Column Width Editing",
            setting_keys=["display/interactive_col_width"],
            mutation=mutation,
            entity_id="display/interactive_col_width",
        )

    def _on_toggle_row_height(self, enabled: bool):
        enabled = bool(enabled)

        def mutation():
            self._apply_row_height_mode(enabled)
            self.settings.setValue("display/interactive_row_height", enabled)
            self.settings.sync()

        self._run_setting_bundle_history_action(
            action_label="Toggle Row Height Editing",
            setting_keys=["display/interactive_row_height"],
            mutation=mutation,
            entity_id="display/interactive_row_height",
        )

    def _reset_hint_label(self):
        if self.col_hint_label:
            self.col_hint_label._user_moved = False
        if self.row_hint_label:
            self.row_hint_label._user_moved = False

    def _on_toggle_add_data(self, enabled: bool):
        enabled = bool(enabled)

        def mutation():
            self._apply_add_data_panel_state(enabled)
            self.settings.setValue("display/add_data_panel", enabled)
            self.settings.sync()

        self._run_setting_bundle_history_action(
            action_label="Toggle Add Data Panel",
            setting_keys=["display/add_data_panel"],
            mutation=mutation,
            entity_id="display/add_data_panel",
        )

    def _on_toggle_profiles_toolbar(self, enabled: bool):
        enabled = bool(enabled)

        def mutation():
            self._apply_profiles_toolbar_visibility(enabled)
            self.settings.setValue("display/profiles_toolbar_visible", enabled)
            self.settings.sync()

        self._run_setting_bundle_history_action(
            action_label="Toggle Profiles Ribbon",
            setting_keys=["display/profiles_toolbar_visible"],
            mutation=mutation,
            entity_id="display/profiles_toolbar_visible",
        )

    def _on_toggle_catalog_table(self, enabled: bool):
        enabled = bool(enabled)

        def mutation():
            self._apply_catalog_table_panel_state(enabled)
            self.settings.setValue("display/catalog_table_panel", enabled)
            self.settings.sync()

        self._run_setting_bundle_history_action(
            action_label="Toggle Catalog Table",
            setting_keys=["display/catalog_table_panel"],
            mutation=mutation,
            entity_id="display/catalog_table_panel",
        )

    def _on_toggle_action_ribbon(self, enabled: bool):
        enabled = bool(enabled)

        def mutation():
            self._apply_action_ribbon_configuration(
                getattr(self, "_action_ribbon_action_ids", []),
                enabled,
            )
            self._queue_top_chrome_boundary_refresh()
            self.settings.setValue("display/action_ribbon_visible", enabled)
            self.settings.sync()

        self._run_setting_bundle_history_action(
            action_label="Toggle Action Ribbon",
            setting_keys=self._action_ribbon_setting_keys(),
            mutation=mutation,
            entity_id="display/action_ribbon",
        )

    def open_action_ribbon_customizer(self):
        available_actions = [dict(spec) for spec in getattr(self, "_action_ribbon_specs", [])]
        dlg = ActionRibbonDialog(
            available_actions,
            list(getattr(self, "_action_ribbon_action_ids", [])),
            ribbon_visible=bool(
                getattr(self, "action_ribbon_toolbar", None) is not None
                and self.action_ribbon_toolbar.isVisible()
            ),
            parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            return

        new_action_ids = self._normalize_action_ribbon_ids(dlg.selected_action_ids())
        new_visible = bool(dlg.ribbon_visible())
        current_action_ids = self._normalize_action_ribbon_ids(
            getattr(self, "_action_ribbon_action_ids", [])
        )
        current_visible = bool(
            getattr(self, "action_ribbon_toolbar", None) is not None
            and self.action_ribbon_toolbar.isVisible()
        )

        if new_action_ids == current_action_ids and new_visible == current_visible:
            return

        def mutation():
            self.settings.setValue("display/action_ribbon_actions_json", json.dumps(new_action_ids))
            self.settings.setValue("display/action_ribbon_visible", new_visible)
            self.settings.sync()
            self._apply_action_ribbon_configuration(new_action_ids, new_visible)

        self._run_setting_bundle_history_action(
            action_label="Customize Action Ribbon",
            setting_keys=self._action_ribbon_setting_keys(),
            mutation=mutation,
            entity_id="display/action_ribbon",
        )

    def _ensure_col_hint_label(self):
        if self.col_hint_label is None:
            self.col_hint_label = DraggableLabel(self, settings_key="display/col_hint_pos")
            self.col_hint_label.setObjectName("colHint")
            self.col_hint_label.setProperty("role", "overlayHint")
            s = self.settings
            pos = s.value("display/col_hint_pos", type=QPoint)
            if pos:
                self.col_hint_label.move(pos)
            self.col_hint_label.hide()

    def _ensure_row_hint_label(self):
        if self.row_hint_label is None:
            self.row_hint_label = DraggableLabel(self, settings_key="display/row_hint_pos")
            self.row_hint_label.setObjectName("rowHint")
            self.row_hint_label.setProperty("role", "overlayHint")
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
    def _custom_field_config_summary(self, fields):
        return [
            {
                "id": field.get("id"),
                "name": field.get("name"),
                "field_type": field.get("field_type"),
                "options": field.get("options"),
                "blob_icon_payload": (
                    finalize_blob_icon_spec(
                        field.get("blob_icon_payload"),
                        kind="audio" if field.get("field_type") == "blob_audio" else "image",
                        allow_inherit=True,
                    )
                    if field.get("field_type") in {"blob_audio", "blob_image"}
                    else None
                ),
            }
            for field in fields
        ]

    def _apply_custom_field_configuration(
        self,
        new_fields,
        *,
        action_label: str,
        action_type: str,
    ) -> bool:
        conflicting = [
            field.get("name")
            for field in new_fields
            if (field.get("name") or "").strip() in PROMOTED_CUSTOM_FIELD_NAMES
        ]
        if conflicting:
            QMessageBox.warning(
                self,
                "Reserved Column Name",
                f"These names are now standard columns and cannot be used as custom fields:\n"
                + "\n".join(sorted(set(conflicting))),
            )
            return False

        current_summary = self._custom_field_config_summary(self.active_custom_fields)
        new_summary = self._custom_field_config_summary(new_fields)
        if current_summary == new_summary:
            return False

        before_snapshot = None
        if self.history_manager is not None:
            before_snapshot = self.history_manager.capture_snapshot(
                kind=f"pre_{action_type.replace('.', '_')}",
                label=f"Before {action_label}",
            )

        try:
            self.custom_field_definitions.sync_fields(self.active_custom_fields, new_fields)
        except Exception as e:
            if before_snapshot is not None:
                try:
                    self.history_manager.delete_snapshot(before_snapshot.snapshot_id)
                except Exception:
                    pass
            self.conn.rollback()
            self.logger.exception(f"Custom fields update failed: {e}")
            QMessageBox.critical(self, "Fields Error", f"Could not update fields:\n{e}")
            return False

        self._on_custom_fields_changed()

        try:
            changed_summary = json.dumps(
                [
                    {"id": f.get("id"), "name": f["name"], "type": f.get("field_type")}
                    for f in new_fields
                ]
            )
        except Exception:
            changed_summary = "fields changed"
        self.logger.info("Custom fields updated")
        self._audit("FIELDS", "CustomFieldDefs", ref_id="batch", details=changed_summary)
        self._audit_commit()

        if before_snapshot is not None and self.history_manager is not None:
            after_snapshot = self.history_manager.capture_snapshot(
                kind=f"post_{action_type.replace('.', '_')}",
                label=f"After {action_label}",
            )
            self.history_manager.record_snapshot_action(
                label=action_label,
                action_type=action_type,
                entity_type="CustomFieldDefs",
                entity_id="batch",
                payload={"summary": changed_summary},
                snapshot_before_id=before_snapshot.snapshot_id,
                snapshot_after_id=after_snapshot.snapshot_id,
            )
            self._refresh_history_actions()
        return True

    def _prompt_new_custom_field(self):
        name, ok = QInputDialog.getText(self, "Add Custom Column", "Column name:")
        name = (name or "").strip()
        if not (ok and name):
            return None
        if name in PROMOTED_CUSTOM_FIELD_NAMES:
            QMessageBox.warning(
                self,
                "Reserved Name",
                f"'{name}' is now a standard column and cannot be added as custom.",
            )
            return None
        if any(field.get("name") == name for field in self.active_custom_fields):
            QMessageBox.warning(self, "Exists", f"Column '{name}' already exists.")
            return None

        field_type, ok = QInputDialog.getItem(
            self, "Field Type", "Choose type:", FIELD_TYPE_CHOICES, 0, False
        )
        if not ok:
            return None

        new_field = {
            "id": None,
            "name": name,
            "field_type": field_type,
            "options": None,
            "blob_icon_payload": None,
        }
        if field_type == "dropdown":
            opts, ok = QInputDialog.getMultiLineText(
                self, "Dropdown Options", "Enter options (one per line):"
            )
            if ok:
                options = [option.strip() for option in (opts or "").splitlines() if option.strip()]
                new_field["options"] = json.dumps(options) if options else json.dumps([])
        elif field_type in {"blob_audio", "blob_image"}:
            blob_icon_dialog = BlobIconDialog(
                kind="audio" if field_type == "blob_audio" else "image",
                title=f"Icon for {name}",
                spec={"mode": "inherit"},
                allow_inherit=True,
                parent=self,
            )
            if blob_icon_dialog.exec() == QDialog.Accepted:
                new_field["blob_icon_payload"] = blob_icon_dialog.current_spec()
        return new_field

    def add_custom_column(self):
        new_field = self._prompt_new_custom_field()
        if new_field is None:
            return
        self._apply_custom_field_configuration(
            [*self.active_custom_fields, new_field],
            action_label=f"Add Custom Column: {new_field['name']}",
            action_type="fields.add",
        )

    def remove_custom_column(self):
        if not self.active_custom_fields:
            QMessageBox.information(
                self, "Remove Custom Column", "There are no custom columns to remove."
            )
            return

        choices = [
            f"{field['name']} ({field.get('field_type', 'text')})"
            for field in self.active_custom_fields
        ]
        choice, ok = QInputDialog.getItem(
            self,
            "Remove Custom Column",
            "Choose the custom column to remove:",
            choices,
            0,
            False,
        )
        if not ok or not choice:
            return

        remove_index = choices.index(choice)
        field = self.active_custom_fields[remove_index]
        if (
            QMessageBox.question(
                self,
                "Remove Custom Column",
                f"Remove custom column '{field['name']}'?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return

        remaining_fields = [
            candidate
            for idx, candidate in enumerate(self.active_custom_fields)
            if idx != remove_index
        ]
        self._apply_custom_field_configuration(
            remaining_fields,
            action_label=f"Remove Custom Column: {field['name']}",
            action_type="fields.remove",
        )

    def manage_custom_columns(self):
        dlg = CustomColumnsDialog(self.active_custom_fields, self)
        if dlg.exec() == QDialog.Accepted:
            self._apply_custom_field_configuration(
                dlg.get_fields(),
                action_label="Manage Custom Columns",
                action_type="fields.manage",
            )

    def _on_custom_fields_changed(self):
        with self._suspend_table_layout_history():
            self.active_custom_fields = self.load_active_custom_fields()
            self._rebuild_table_headers()

            # Always rebind first (safe if duplicated)
            try:
                self._bind_header_state_signals()
            except Exception as e:
                self.logger.warning(
                    "Failed to rebind sectionMoved after custom fields change: %s", e
                )

            # Then load header state (visual order + widths)
            try:
                self._load_header_state()
            except Exception as e:
                self.logger.warning("Failed to load header state after custom fields change: %s", e)

            try:
                self._save_header_state(record_history=False)
            except Exception as e:
                self.logger.warning("Failed to save header state after custom fields change: %s", e)

            self.refresh_table()
            self._update_count_label()
            self._apply_blob_badges()

    # ============================================================
    # Double-click editing: base vs custom fields
    # ============================================================
    def _on_item_double_clicked(self, item: QTableWidgetItem):
        col = item.column()
        if col < len(self.BASE_HEADERS):
            header_item = self.table.horizontalHeaderItem(col)
            header_text = header_item.text() if header_item is not None else ""
            standard_media_key = self._standard_media_key_for_header(header_text)
            if standard_media_key:
                id_item = self.table.item(item.row(), 0)
                if not id_item:
                    return
                try:
                    track_id = int(id_item.text())
                except Exception:
                    return
                self._attach_standard_media_for_track(track_id, standard_media_key)
                return
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
            new_path, _ = QFileDialog.getOpenFileName(
                self, f"Attach file: {field['name']}", "", flt
            )
            if not new_path:
                return
            storage_mode = _prompt_storage_mode_choice(
                self,
                title=f"Attach {field['name']}",
                subject=f"the file for {field['name']}",
                default_mode=STORAGE_MODE_DATABASE,
            )
            if storage_mode is None:
                return
            try:
                self._run_snapshot_history_action(
                    action_label=f"Attach Custom File: {field['name']}",
                    action_type="custom_field.blob_attach",
                    entity_type="CustomFieldValue",
                    entity_id=f"{track_id}:{field_id}",
                    payload={
                        "track_id": track_id,
                        "field_id": field_id,
                        "field_name": field["name"],
                        "storage_mode": storage_mode,
                    },
                    mutation=lambda: self.cf_save_value(
                        track_id,
                        field_id,
                        value=None,
                        blob_path=new_path,
                        storage_mode=storage_mode,
                    ),
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
                self,
                f"Edit: {field['name']}",
                field["name"],
                choices,
                current=choices.index(current_val) if current_val in choices else 0,
                editable=True,
            )
            if not ok:
                return
            if new_val and options is not None and new_val not in options:
                options.append(new_val)
            options_updated = options != original_options
        elif field_type == "checkbox":
            choice, ok = QInputDialog.getItem(
                self,
                f"Edit: {field['name']}",
                field["name"],
                ["True", "False"],
                current=0 if (current_val == "True") else 1,
                editable=False,
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
            new_val, ok = QInputDialog.getMultiLineText(
                self, f"Edit: {field['name']}", f"{field['name']}:", text=current_val
            )
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
        sel_model = self.table.selectionModel()
        if sel_model is not None:
            selected_rows = {selected.row() for selected in sel_model.selectedRows()}
            if not selected_rows:
                selected_rows = {selected.row() for selected in sel_model.selectedIndexes()}
            if row in selected_rows:
                sel_model.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
            else:
                sel_model.select(
                    index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows
                )
                sel_model.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        else:
            self.table.setCurrentCell(row, col)

        menu = QMenu(self)
        track_id = self._track_id_for_table_row(row)
        selected_ids = self._selected_track_ids()
        bulk_count = len(selected_ids) if track_id is not None and track_id in selected_ids else 1
        track_title = self._get_track_title(track_id) if track_id else ""
        edit_label = (
            "Edit Entry" if bulk_count <= 1 else f"Bulk Edit {bulk_count} Selected Entries…"
        )
        act_edit = QAction(edit_label, self)
        act_edit.triggered.connect(lambda: self.open_selected_editor(track_id))
        menu.addAction(act_edit)

        act_gs1 = QAction("GS1 Metadata…", self)
        act_gs1.triggered.connect(lambda: self.open_gs1_dialog(self._track_id_for_table_row(row)))
        menu.addAction(act_gs1)

        if track_id and self.release_service is not None:
            release = self.release_service.find_primary_release_for_track(track_id)
            if release is not None:
                act_release = QAction("Open Primary Release…", self)
                act_release.triggered.connect(lambda: self.open_release_editor(release.id))
                menu.addAction(act_release)
        if track_id and self.work_service is not None:
            linked_works = self.work_service.list_works_for_track(track_id)
            if linked_works:
                act_work = QAction("Open Linked Work(s)…", self)
                act_work.triggered.connect(lambda: self.open_work_manager(linked_track_id=track_id))
                menu.addAction(act_work)
            act_link_work = QAction("Link Selected Track(s) to Work…", self)
            act_link_work.triggered.connect(lambda: self.open_work_manager())
            menu.addAction(act_link_work)

        act_delete = QAction("Delete Entry", self)
        act_delete.triggered.connect(self.delete_entry)
        menu.addAction(act_delete)

        menu.addSeparator()
        # Licenses actions
        if track_id:
            act_add_license = QAction("Add License to this Track…", self)
            act_add_license.triggered.connect(
                lambda: self.open_license_upload(preselect_track_id=track_id)
            )
            menu.addAction(act_add_license)

            act_view_licenses = QAction("View Licenses for this Track…", self)
            act_view_licenses.triggered.connect(
                lambda: self.open_licenses_browser(track_filter_id=track_id)
            )
            menu.addAction(act_view_licenses)

            if self.track_has_media(track_id, "audio_file"):
                export_track_ids = selected_ids if track_id in selected_ids else [track_id]
                act_import_tags = QAction("Import Tags from Audio…", self)
                act_import_tags.triggered.connect(lambda: self.import_tags_from_audio([track_id]))
                menu.addAction(act_import_tags)

                act_write_tags = QAction("Write Tags to Exported Audio…", self)
                act_write_tags.triggered.connect(
                    lambda: self.write_tags_to_exported_audio(export_track_ids)
                )
                menu.addAction(act_write_tags)

                act_convert_selected_audio = QAction(
                    "Export Managed Audio Derivatives…",
                    self,
                )
                act_convert_selected_audio.triggered.connect(
                    lambda: self.convert_selected_audio(export_track_ids)
                )
                menu.addAction(act_convert_selected_audio)

                act_convert_external_audio = QAction(
                    "External Audio Conversion Utility…",
                    self,
                )
                act_convert_external_audio.triggered.connect(
                    self.convert_external_audio_files
                )
                menu.addAction(act_convert_external_audio)

                act_export_authenticity = QAction(
                    "Export Watermark-Authentic Masters…",
                    self,
                )
                act_export_authenticity.triggered.connect(
                    lambda: self.export_authenticity_watermarked_audio(export_track_ids)
                )
                menu.addAction(act_export_authenticity)

                act_export_provenance = QAction(
                    "Export Provenance-Linked Lossy Copies…",
                    self,
                )
                act_export_provenance.triggered.connect(
                    lambda: self.export_authenticity_provenance_audio(export_track_ids)
                )
                menu.addAction(act_export_provenance)

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

        header_item = self.table.horizontalHeaderItem(col)
        header_text = header_item.text() if header_item is not None else ""
        standard_media_key = self._standard_media_key_for_header(header_text)
        if track_id and standard_media_key:
            if self.track_has_media(track_id, standard_media_key):
                act_prev = QAction("Preview File…", self)
                act_prev.triggered.connect(
                    lambda: self._preview_standard_media_for_track(track_id, standard_media_key)
                )
                menu.addAction(act_prev)

            menu.addSeparator()
            act_attach_standard = QAction("Attach/Replace File…", self)
            act_attach_standard.triggered.connect(
                lambda: self._attach_standard_media_for_track(track_id, standard_media_key)
            )
            menu.addAction(act_attach_standard)

            if self.track_has_media(track_id, standard_media_key):
                export_basename = self._media_export_basename_for_track(
                    track_id,
                    standard_media_key,
                )
                act_export_standard = QAction(f"Export '{export_basename}'…", self)
                act_export_standard.triggered.connect(
                    lambda: self._export_standard_media_for_track(
                        track_id,
                        standard_media_key,
                        export_basename,
                    )
                )
                menu.addAction(act_export_standard)

                act_delete_standard = QAction("Delete File…", self)
                act_delete_standard.triggered.connect(
                    lambda: self._delete_standard_media_for_track(track_id, standard_media_key)
                )
                menu.addAction(act_delete_standard)

                current_mode = normalize_storage_mode(
                    str(
                        self.track_media_meta(track_id, standard_media_key).get("storage_mode")
                        or ""
                    ),
                    default=None,
                )
                if current_mode != STORAGE_MODE_DATABASE:
                    act_convert_standard_db = QAction("Store in Database", self)
                    act_convert_standard_db.triggered.connect(
                        lambda checked=False, tid=track_id, key=standard_media_key: self._convert_standard_media_for_track(
                            tid, key, STORAGE_MODE_DATABASE
                        )
                    )
                    menu.addAction(act_convert_standard_db)
                if current_mode != STORAGE_MODE_MANAGED_FILE:
                    act_convert_standard_file = QAction("Store as Managed File", self)
                    act_convert_standard_file.triggered.connect(
                        lambda checked=False, tid=track_id, key=standard_media_key: self._convert_standard_media_for_track(
                            tid, key, STORAGE_MODE_MANAGED_FILE
                        )
                    )
                    menu.addAction(act_convert_standard_file)

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
                            data = self.cf_fetch_blob(
                                track_id, field["id"]
                            )  # must return bytes or memoryview
                            if not data:
                                QMessageBox.information(
                                    self, "Preview", "No data stored in this cell."
                                )
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
                            QMessageBox.critical(
                                self, "Custom Field Error", f"Failed to preview file:\n{e}"
                            )

                    act_prev.triggered.connect(_do_prev)
                    menu.addAction(act_prev)

        # Blob field actions for custom columns
        if col >= len(self.BASE_HEADERS):
            field = self.active_custom_fields[col - len(self.BASE_HEADERS)]
            field_id = field["id"]
            id_item = self.table.item(row, 0)
            title_idx = self._column_index_by_header("Track Title")
            title_item = self.table.item(row, title_idx) if title_idx >= 0 else None
            if id_item and field.get("field_type") in ("blob_image", "blob_audio"):
                track_id = int(id_item.text())
                track_title = title_item.text() if title_item else f"track_{track_id}"

                menu.addSeparator()
                act_attach = QAction("Attach/Replace File…", self)
                act_attach.triggered.connect(
                    lambda: self._attach_blob_for_cell(
                        track_id, field_id, field.get("field_type"), field.get("name")
                    )
                )
                menu.addAction(act_attach)

                # Use track title for export action label
                act_export = QAction(f"Export '{track_title}'…", self)
                act_export.triggered.connect(
                    lambda: self.cf_export_blob(track_id, field_id, self, track_title)
                )
                menu.addAction(act_export)
                meta = self.cf_get_value_meta(
                    track_id,
                    field_id,
                    include_storage_details=True,
                )
                current_mode = normalize_storage_mode(meta.get("storage_mode"), default=None)
                if current_mode != STORAGE_MODE_DATABASE:
                    act_cf_db = QAction("Store in Database", self)
                    act_cf_db.triggered.connect(
                        lambda checked=False, tid=track_id, fid=field_id: self._convert_custom_blob_storage_mode(
                            tid,
                            fid,
                            STORAGE_MODE_DATABASE,
                        )
                    )
                    menu.addAction(act_cf_db)
                if current_mode != STORAGE_MODE_MANAGED_FILE:
                    act_cf_file = QAction("Store as Managed File", self)
                    act_cf_file.triggered.connect(
                        lambda checked=False, tid=track_id, fid=field_id: self._convert_custom_blob_storage_mode(
                            tid,
                            fid,
                            STORAGE_MODE_MANAGED_FILE,
                        )
                    )
                    menu.addAction(act_cf_file)

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
                            if (
                                QMessageBox.question(
                                    self,
                                    "Delete File",
                                    "Remove the stored file from this cell?",
                                    QMessageBox.Yes | QMessageBox.No,
                                )
                                == QMessageBox.Yes
                            ):
                                try:
                                    self._run_snapshot_history_action(
                                        action_label=f"Delete Custom File: {field['name']}",
                                        action_type="custom_field.blob_delete",
                                        entity_type="CustomFieldValue",
                                        entity_id=f"{track_id}:{field['id']}",
                                        payload={
                                            "track_id": track_id,
                                            "field_id": field["id"],
                                            "field_name": field["name"],
                                        },
                                        mutation=lambda: self.cf_delete_blob(track_id, field["id"]),
                                    )
                                    self.refresh_table_preserve_view(focus_id=track_id)
                                except Exception as e:
                                    self.conn.rollback()
                                    self.logger.exception(f"Delete blob failed: {e}")
                                    QMessageBox.critical(
                                        self, "Custom Field Error", f"Failed to delete file:\n{e}"
                                    )

                        act_del.triggered.connect(_do_del)
                        menu.addAction(act_del)

        media_export_spec = self._focused_media_export_spec(col)
        if bulk_count > 1 and media_export_spec is not None:
            menu.addSeparator()
            act_bulk_export = QAction(
                f"Export {bulk_count} Files from '{media_export_spec['column_label']}' Column…",
                self,
            )
            act_bulk_export.triggered.connect(
                lambda checked=False, column=col, track_ids=list(
                    selected_ids
                ): self._export_focused_media_column(
                    column,
                    track_ids=track_ids,
                )
            )
            menu.addAction(act_bulk_export)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _preview_blob_for_cell(self, row: int, col: int):
        """Directly preview the blob in the given cell (image/audio)."""
        if col < len(self.BASE_HEADERS):
            header_item = self.table.horizontalHeaderItem(col)
            header_text = header_item.text() if header_item is not None else ""
            media_key = self._standard_media_key_for_header(header_text)
            if not media_key:
                return
            id_item = self.table.item(row, 0)
            if not id_item:
                return
            self._preview_standard_media_for_track(int(id_item.text()), media_key)
            return

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
        self._preview_blob_for_cell(
            row, col
        )  ############################################################################

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
        if len(b) >= 2 and b[:2] == b"\xff\xd8":
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
        dlg.resize(1040, 780)
        dlg.setMinimumSize(900, 680)
        _apply_standard_dialog_chrome(dlg, "imagePreviewDialog")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        _add_standard_dialog_header(
            layout,
            dlg,
            title="Image Preview",
            subtitle=f"Inspect stored artwork or image media for {title}.",
            help_topic_id="media-preview",
        )

        zoom_slider = FocusWheelSlider(Qt.Horizontal)
        zoom_slider.setRange(10, 400)
        zoom_value_lbl = QLabel("")
        zoom_value_lbl.setProperty("role", "statusText")
        controls_box, controls_layout = _create_standard_section(
            dlg,
            "Preview Controls",
            "Use the zoom slider to inspect the stored image without changing the source file.",
        )
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(10)
        zoom_row.addWidget(QLabel("Zoom"), 0)
        zoom_row.addWidget(zoom_slider, 1)
        zoom_row.addWidget(zoom_value_lbl, 0)
        controls_layout.addLayout(zoom_row)
        layout.addWidget(controls_box)

        # Image area
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        base_pix = QPixmap.fromImage(img)

        sc = QScrollArea()
        sc.setWidget(lbl)
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        preview_box, preview_layout = _create_standard_section(
            dlg,
            "Image",
            "The preview scales to fit the window until you manually set a zoom level.",
        )
        preview_layout.addWidget(sc, 1)
        layout.addWidget(preview_box, 1)

        def fit_percent():
            avail_w = max(1, sc.viewport().width() - 24)
            avail_h = max(1, sc.viewport().height() - 24)
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

        detected_mime = self._detect_mime(data) or "image/png"
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)
        export_btn = QPushButton("Export Image…")
        export_btn.clicked.connect(
            lambda: self._export_bytes_with_picker(
                data,
                mime=detected_mime,
                suggested_basename=title,
                parent_widget=dlg,
                action_label="Export Image Preview: {filename}",
                action_type="file.export_image_preview",
                entity_type="Preview",
                entity_id=self._sanitize_filename(title),
                payload={"title": title, "mime_type": detected_mime},
            )
        )
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        button_row.addWidget(export_btn)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

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
                        header_texts.append(
                            header_item.text()
                            if header_item is not None
                            else str(view.model().headerData(c, Qt.Horizontal))
                        )
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
                header_texts.append(
                    header_item.text()
                    if header_item is not None
                    else str(view.model().headerData(c, Qt.Horizontal))
                )
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
    def _table_settings_prefix_for_path(self, path: str | None) -> str:
        """Per-profile (per-DB) settings namespace for table header state."""
        db = path or ""
        h = hashlib.sha1(db.encode("utf-8")).hexdigest()[:8]
        return f"table/{h}"

    def _table_settings_prefix(self) -> str:
        return self._table_settings_prefix_for_path(getattr(self, "current_db_path", "") or "")

    def _clear_table_settings_for_path(self, path: str) -> None:
        prefix = self._table_settings_prefix_for_path(path)
        for suffix in (
            "header_state",
            "header_labels",
            "header_labels_json",
            "hidden_columns_json",
            "columns_movable",
        ):
            self.settings.remove(f"{prefix}/{suffix}")
        self.settings.sync()

    def _default_header_labels(self) -> list[str]:
        return list(self.BASE_HEADERS) + [
            f["name"] for f in getattr(self, "active_custom_fields", [])
        ]

    def _apply_header_label_order(self, ordered_labels: list[str]) -> None:
        header = self.table.horizontalHeader()
        current_labels = [
            self.table.horizontalHeaderItem(i).text()
            for i in range(self.table.columnCount())
            if self.table.horizontalHeaderItem(i) is not None
        ]
        seen_pos: dict[str, int] = {}
        target_logicals: list[int] = []
        for label in ordered_labels:
            start = seen_pos.get(label, 0)
            try:
                logical_index = current_labels.index(label, start)
            except ValueError:
                continue
            target_logicals.append(logical_index)
            seen_pos[label] = logical_index + 1

        for visual_pos, logical_index in enumerate(target_logicals):
            current_visual = header.visualIndex(logical_index)
            if current_visual != -1 and current_visual != visual_pos:
                header.moveSection(current_visual, visual_pos)

    def _toggle_columns_movable(self, enabled: bool):
        try:

            def mutation():
                self.table.horizontalHeader().setSectionsMovable(bool(enabled))
                self._save_header_state(record_history=False)
                self.settings.setValue(
                    f"{self._table_settings_prefix()}/columns_movable", bool(enabled)
                )
                self.settings.sync()

            self._run_setting_bundle_history_action(
                action_label="Toggle Column Reordering",
                setting_keys=self._table_setting_keys(include_columns_movable=True),
                mutation=mutation,
                entity_id=f"{self._table_settings_prefix()}/columns_movable",
            )
        except Exception as e:
            self.logger.warning("Exception while toggling columns movable: %s", e)
            pass

    def _hidden_columns_setting_key(self) -> str:
        return f"{self._table_settings_prefix()}/hidden_columns_json"

    def _capture_hidden_columns_payload(self) -> list[dict[str, int | str]]:
        if not hasattr(self, "table"):
            return []
        payload = []
        labels = self._header_labels()
        for logical_index, (label, occurrence) in enumerate(self._labels_with_occurrence(labels)):
            if self.table.isColumnHidden(logical_index):
                payload.append({"label": label, "occurrence": occurrence})
        return payload

    def _write_hidden_columns_setting(self, *, sync: bool = True):
        try:
            payload = json.dumps(self._capture_hidden_columns_payload())
        except Exception:
            payload = "[]"
        self.settings.setValue(self._hidden_columns_setting_key(), payload)
        if sync:
            self.settings.sync()

    def _load_hidden_columns_payload(self) -> list[tuple[str, int]]:
        settings_key = self._hidden_columns_setting_key()
        if not self.settings.contains(settings_key):
            return [(name, 0) for name in sorted(DEFAULT_HIDDEN_CUSTOM_COLUMN_NAMES)]

        raw_value = self.settings.value(settings_key, "[]")
        payload = raw_value
        if isinstance(raw_value, str):
            try:
                payload = json.loads(raw_value or "[]")
            except Exception:
                payload = []
        if not isinstance(payload, list):
            payload = []

        hidden_columns = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label") or "")
            try:
                occurrence = int(entry.get("occurrence", 0))
            except (TypeError, ValueError):
                occurrence = 0
            if label:
                hidden_columns.append((label, occurrence))
        return hidden_columns

    def _apply_saved_column_visibility(self):
        if not hasattr(self, "table"):
            return

        hidden_columns = set(self._load_hidden_columns_payload())
        labels = self._header_labels()
        previous_suspend_state = self._suspend_layout_history
        self._suspend_layout_history = True
        try:
            for logical_index, token in enumerate(self._labels_with_occurrence(labels)):
                self.table.setColumnHidden(logical_index, token in hidden_columns)
        finally:
            self._suspend_layout_history = previous_suspend_state

    def _toggle_column_visibility(self, logical_index: int, visible: bool):
        if logical_index < 0 or logical_index >= self.table.columnCount():
            return

        header_item = self.table.horizontalHeaderItem(logical_index)
        column_name = (
            header_item.text() if header_item is not None else f"Column {logical_index + 1}"
        )
        action_label = f"{'Show' if visible else 'Hide'} Column: {column_name}"

        def mutation():
            previous_suspend_state = self._suspend_layout_history
            self._suspend_layout_history = True
            try:
                self.table.setColumnHidden(logical_index, not visible)
                self._save_header_state(record_history=False)
                self._rebuild_search_column_choices()
                self.apply_search_filter()
                self._refresh_column_visibility_menu()
            finally:
                self._suspend_layout_history = previous_suspend_state

        self._run_setting_bundle_history_action(
            action_label=action_label,
            setting_keys=self._table_setting_keys(include_columns_movable=False),
            mutation=mutation,
            entity_id=f"{self._table_settings_prefix()}/column_visibility",
        )

    def _refresh_column_visibility_menu(self):
        if not hasattr(self, "columns_menu"):
            return

        for action in getattr(self, "column_visibility_actions", []):
            self.columns_menu.removeAction(action)
            try:
                action.deleteLater()
            except Exception:
                pass
        self.column_visibility_actions = []

        if not hasattr(self, "table"):
            return

        header = self.table.horizontalHeader()
        logical_indices = sorted(
            range(self.table.columnCount()),
            key=lambda idx: (
                header.visualIndex(idx) if header.visualIndex(idx) >= 0 else 10_000 + idx
            ),
        )

        for logical_index in logical_indices:
            header_item = self.table.horizontalHeaderItem(logical_index)
            if header_item is None:
                continue
            action = QAction(header_item.text(), self.columns_menu)
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(logical_index))
            action.toggled.connect(
                lambda checked, idx=logical_index: self._toggle_column_visibility(idx, checked)
            )
            self.columns_menu.addAction(action)
            self.column_visibility_actions.append(action)

    def _save_header_state(
        self,
        *,
        record_history: bool = True,
        action_label: str = "Update Table Layout",
        history_entity_id: str | None = None,
    ):
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
                    self.settings.setValue(
                        f"{prefix}/header_labels_json", json.dumps(labels_visual)
                    )
                except Exception as e:
                    self.logger.warning("Failed to save header visual order JSON: %s", e)

                self._write_hidden_columns_setting(sync=False)
                self.settings.sync()

            if record_history:
                self._run_setting_bundle_history_action(
                    action_label=action_label,
                    setting_keys=self._table_setting_keys(include_columns_movable=False),
                    mutation=mutation,
                    entity_id=history_entity_id or self._table_settings_prefix(),
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
            saved_order_keys = (
                f"{prefix}/header_state",
                f"{prefix}/header_labels",
                f"{prefix}/header_labels_json",
            )

            # Current labels after (re)building headers — includes any new custom fields
            current_labels = [
                self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())
            ]

            if not any(self.settings.contains(key) for key in saved_order_keys):
                self._apply_header_label_order(self._default_header_labels())
                self._apply_saved_column_visibility()
                self._refresh_column_visibility_menu()
                self._rebuild_search_column_choices()
                return

            # Our robust, visual-order fallback list from last save
            saved_labels = self.settings.value(f"{prefix}/header_labels", [], list)

            # Native state blob (may be stale when columns changed)
            state = self.settings.value(f"{prefix}/header_state", None, QByteArray)

            native_state_restored = False

            # Only apply native restore if the label sets match (prevents dropping new columns)
            if isinstance(state, QByteArray) and not state.isEmpty():
                if saved_labels and set(saved_labels) == set(current_labels):
                    native_state_restored = bool(header.restoreState(state))
                # else: mismatch → skip native restore on purpose

            # Fallback: reorder by labels we know; any new labels remain visible at the end
            if saved_labels and not native_state_restored:
                self._apply_header_label_order(saved_labels)

            self._apply_saved_column_visibility()
            self._refresh_column_visibility_menu()
            self._rebuild_search_column_choices()
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
        src = Path(self.current_db_path)
        if not src.exists():
            QMessageBox.warning(self, "Backup", "No current database to backup.")
            return

        def _worker(bundle, ctx):
            ctx.set_status("Creating a database backup...")
            result = bundle.database_maintenance.create_backup(bundle.conn, src)
            if bundle.history_manager is not None:
                before_state = {
                    "target_path": str(result.backup_path),
                    "companion_suffixes": list(bundle.history_manager.FILE_COMPANION_SUFFIXES),
                    "exists": False,
                    "files": [],
                }
                after_state = bundle.history_manager.capture_file_state(
                    result.backup_path,
                    companion_suffixes=bundle.history_manager.FILE_COMPANION_SUFFIXES,
                )
                bundle.history_manager.record_file_write_action(
                    label="Create Database Backup",
                    action_type="file.db_backup",
                    target_path=result.backup_path,
                    before_state=before_state,
                    after_state=after_state,
                    entity_type="DB",
                    entity_id=str(result.backup_path),
                    payload={"path": str(result.backup_path), "method": result.method},
                )
                bundle.history_manager.register_backup(
                    result.backup_path,
                    kind="manual",
                    label=f"Backup: {result.backup_path.name}",
                    source_db_path=src,
                    metadata={"method": result.method},
                )
            return {"backup_path": str(result.backup_path), "method": result.method}

        def _success(result):
            self._refresh_history_actions()
            QMessageBox.information(self, "Backup", f"Backup created:\n{result['backup_path']}")
            self._log_event(
                "db.backup",
                "Database backup created",
                path=result["backup_path"],
                method=result["method"],
            )
            try:
                self._audit(
                    "BACKUP",
                    "DB",
                    ref_id=str(result["backup_path"]),
                    details=f"Full DB (schema+data), method={result['method']}",
                )
                self._audit_commit()
            except Exception:
                pass

        self._submit_background_bundle_task(
            title="Create Backup",
            description="Creating a full database backup...",
            task_fn=_worker,
            kind="read",
            unique_key="db.backup",
            on_success=_success,
            on_error=lambda failure: self._show_background_task_error(
                "Backup Error",
                failure,
                user_message="Failed to create the database backup:",
            ),
        )

    def verify_integrity(self):
        current_path = str(self.current_db_path)

        def _worker(bundle, ctx):
            ctx.set_status("Running SQLite integrity check...")
            result = bundle.database_maintenance.verify_integrity(current_path)
            if bundle.history_manager is not None:
                bundle.history_manager.record_event(
                    label=f"Verify Integrity: {result}",
                    action_type="db.verify",
                    entity_type="DB",
                    entity_id=current_path,
                    payload={"result": result, "path": current_path},
                )
            return result

        def _success(result):
            self._refresh_history_actions()
            QMessageBox.information(self, "Integrity Check", f"Result: {result}")
            self._log_event(
                "db.verify",
                "Database integrity check completed",
                result=result,
                path=current_path,
            )
            self._audit("VERIFY", "DB", ref_id=current_path, details=result)
            self._audit_commit()

        self._submit_background_bundle_task(
            title="Integrity Check",
            description="Checking the current database for corruption...",
            task_fn=_worker,
            kind="read",
            unique_key="db.verify",
            on_success=_success,
            on_error=lambda failure: self._show_background_task_error(
                "Integrity Error",
                failure,
                user_message="Failed to verify the database:",
            ),
        )

    def restore_database(self):
        """Restore the database from a backup .db file.

        This completely replaces the current DB file with the selected backup,
        ensuring that **all** schema (including user-added columns) and data are restored.
        """
        pre_restore_snapshot = None
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore...Backup", str(self.backups_dir), "SQLite DB (*.db)"
        )
        if not path:
            return

        if (
            QMessageBox.question(
                self,
                "Restore",
                f"This will replace your current database with:\n{path}\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return

        current_db_path = str(self.current_db_path)
        if self.history_manager is not None:
            pre_restore_snapshot = self.history_manager.capture_snapshot(
                kind="pre_db_restore",
                label=f"Before Database Restore: {Path(path).name}",
            )

        self._close_database_connection()

        def _worker(ctx):
            ctx.set_status("Restoring the database from backup...")
            result = self.database_maintenance.restore_database(path, current_db_path)
            return {
                "restored_path": str(result.restored_path),
                "integrity_result": result.integrity_result,
                "safety_copy_path": (
                    str(result.safety_copy_path) if result.safety_copy_path else None
                ),
            }

        def _success(result):
            try:
                self.open_database(str(result["restored_path"]))
                self.refresh_table_preserve_view()

                payload = {
                    "source_backup": str(path),
                    "restored_path": str(result["restored_path"]),
                    "safety_copy_path": result["safety_copy_path"],
                }
                if result["safety_copy_path"] is not None and self.history_manager is not None:
                    self.history_manager.register_backup(
                        result["safety_copy_path"],
                        kind="pre_restore_safety_copy",
                        label=f"Pre-Restore Safety Copy: {Path(result['safety_copy_path']).name}",
                        source_db_path=current_db_path,
                        metadata={"source_backup": str(path)},
                    )
                    payload["file_effects"] = [
                        {
                            "target_path": str(result["safety_copy_path"]),
                            "before_state": {
                                "target_path": str(result["safety_copy_path"]),
                                "companion_suffixes": list(
                                    self.history_manager.FILE_COMPANION_SUFFIXES
                                ),
                                "exists": False,
                                "files": [],
                            },
                            "after_state": self.history_manager.capture_file_state(
                                result["safety_copy_path"],
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
                QMessageBox.information(
                    self, "Restore", "Database restored successfully (schema + data)."
                )
                self._log_event(
                    "db.restore",
                    "Database restored from backup",
                    level=logging.WARNING,
                    source_backup=path,
                    restored_path=result["restored_path"],
                    safety_copy_path=result["safety_copy_path"],
                )
                try:
                    details = f"restored to {result['restored_path']}"
                    if result["safety_copy_path"] is not None:
                        details += f"; safety_copy={result['safety_copy_path']}"
                    self._audit("RESTORE", "DB", ref_id=path, details=details)
                    self._audit_commit()
                except Exception:
                    pass
            except Exception as exc:
                self.logger.exception("Restore finalization failed: %s", exc)
                if result["safety_copy_path"] is not None:
                    try:
                        self._close_database_connection()
                        self.database_maintenance.restore_database(
                            result["safety_copy_path"], current_db_path
                        )
                        self.open_database(current_db_path)
                    except Exception as rollback_error:
                        self.logger.exception(
                            "Failed to roll back database restore finalization: %s",
                            rollback_error,
                        )
                self._show_background_task_error(
                    "Restore Error",
                    TaskFailure(message=str(exc), traceback_text=""),
                    user_message="Failed to finalize the restored database:",
                )

        def _error(failure):
            try:
                self.open_database(current_db_path)
            except Exception as reopen_error:
                self.logger.exception(
                    "Failed to reopen database after restore error: %s", reopen_error
                )
            self._show_background_task_error(
                "Restore Error",
                failure,
                user_message="Failed to restore the database:",
            )

        self._submit_background_task(
            title="Restore Database",
            description="Restoring the selected backup...",
            task_fn=_worker,
            kind="exclusive",
            unique_key="db.restore",
            requires_profile=False,
            on_success=_success,
            on_error=_error,
        )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.delete_entry()
        elif event.key() == Qt.Key_Escape:
            self.init_form()
            self.reset_search()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            # Only save when the Add Data panel is active AND focus is inside that panel
            panel_enabled = (
                getattr(self, "add_data_action", None) and self.add_data_action.isChecked()
            )
            if panel_enabled and self._form_has_focus():
                self.save()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, source, event):
        """Ensure we return a bool. Handle table key events here."""
        if event.type() == QEvent.Show and isinstance(source, QWidget):
            root = source.window() if hasattr(source, "window") else source
            if isinstance(root, QWidget):
                if self._ensure_widget_object_names(root):
                    self._repolish_widget_tree(root)
            return super().eventFilter(source, event)

        if source is getattr(self, "table", None) and event.type() == QEvent.KeyPress:
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

    # ---------------------- Standard track media helpers ----------------------
    @staticmethod
    def _standard_media_header_map() -> dict[str, str]:
        return {
            label: spec.media_key
            for label, spec in standard_media_specs_by_label().items()
            if spec.media_key
        }

    @staticmethod
    def _standard_field_type_for_header(header_text: str) -> str | None:
        spec = standard_field_spec_for_label(header_text)
        return spec.field_type if spec is not None else None

    def _standard_media_key_for_header(self, header_text: str) -> str | None:
        return self._standard_media_header_map().get(header_text)

    def track_media_meta(self, track_id: int, media_key: str):
        return self.track_service.get_media_meta(track_id, media_key, cursor=self.cursor)

    def track_has_media(self, track_id: int, media_key: str) -> bool:
        return self.track_service.has_media(track_id, media_key, cursor=self.cursor)

    def track_fetch_media(self, track_id: int, media_key: str):
        return self.track_service.fetch_media_bytes(track_id, media_key, cursor=self.cursor)

    def track_set_media(
        self,
        track_id: int,
        media_key: str,
        source_path: str,
        *,
        storage_mode: str | None = None,
    ):
        return self.track_service.set_media_path(
            track_id, media_key, source_path, storage_mode=storage_mode, cursor=self.cursor
        )

    def track_clear_media(self, track_id: int, media_key: str):
        self.track_service.clear_media(track_id, media_key, cursor=self.cursor)

    def track_convert_media_storage_mode(self, track_id: int, media_key: str, target_mode: str):
        return self.track_service.convert_media_storage_mode(
            track_id,
            media_key,
            target_mode,
            cursor=self.cursor,
        )

    def _choose_track_media_storage_modes(
        self,
        *,
        audio_source_path: str | None = None,
        album_art_source_path: str | None = None,
        audio_default: str | None = None,
        album_art_default: str | None = None,
        title: str = "Choose Storage Mode",
    ) -> tuple[str | None, str | None] | None:
        audio_mode = audio_default
        album_art_mode = album_art_default
        if audio_source_path:
            audio_mode = _prompt_storage_mode_choice(
                self,
                title=title,
                subject="the audio file",
                default_mode=audio_default,
            )
            if audio_mode is None:
                return None
        if album_art_source_path:
            album_art_mode = _prompt_storage_mode_choice(
                self,
                title=title,
                subject="the artwork file",
                default_mode=album_art_default,
            )
            if album_art_mode is None:
                return None
        return audio_mode, album_art_mode

    def _attach_standard_media_for_track(self, track_id: int, media_key: str):
        path = self._browse_track_media_file(media_key)
        if not path:
            return
        header_label = "Audio File" if media_key == "audio_file" else "Album Art"
        storage_mode = _prompt_storage_mode_choice(
            self,
            title=f"Attach {header_label}",
            subject=header_label.lower(),
            default_mode=STORAGE_MODE_MANAGED_FILE,
        )
        if storage_mode is None:
            return
        if media_key == "audio_file" and not self._confirm_lossy_primary_audio_selection(
            [path],
            title=f"Attach {header_label}",
            action_label="Attaching this audio file",
        ):
            return
        try:
            self._run_snapshot_history_action(
                action_label=f"Attach {header_label}",
                action_type=f"track.{media_key}.attach",
                entity_type="Track",
                entity_id=track_id,
                payload={
                    "track_id": track_id,
                    "media_key": media_key,
                    "storage_mode": storage_mode,
                },
                mutation=lambda: self.track_set_media(
                    track_id,
                    media_key,
                    path,
                    storage_mode=storage_mode,
                ),
            )
            self.refresh_table_preserve_view(focus_id=track_id)
        except Exception as e:
            self.conn.rollback()
            self.logger.exception(f"Attach {media_key} failed: {e}")
            QMessageBox.critical(self, "Track Media Error", f"Failed to attach file:\n{e}")

    def _delete_standard_media_for_track(self, track_id: int, media_key: str):
        header_label = "Audio File" if media_key == "audio_file" else "Album Art"
        confirm_text = f"Remove the stored {header_label.lower()} from this track?"
        if media_key == "album_art" and self.track_service is not None:
            shared_track_ids = self.track_service.list_album_group_track_ids(
                track_id, cursor=self.cursor
            )
            if len(shared_track_ids) > 1:
                confirm_text = (
                    f"Remove the shared album art for this album?\n"
                    f"This will affect {len(shared_track_ids)} linked track(s)."
                )
        if (
            QMessageBox.question(
                self,
                "Delete File",
                confirm_text,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        try:
            self._run_snapshot_history_action(
                action_label=f"Delete {header_label}",
                action_type=f"track.{media_key}.delete",
                entity_type="Track",
                entity_id=track_id,
                payload={"track_id": track_id, "media_key": media_key},
                mutation=lambda: self.track_clear_media(track_id, media_key),
            )
            self.refresh_table_preserve_view(focus_id=track_id)
        except Exception as e:
            self.conn.rollback()
            self.logger.exception(f"Delete {media_key} failed: {e}")
            QMessageBox.critical(self, "Track Media Error", f"Failed to remove file:\n{e}")

    def _preview_standard_media_for_track(self, track_id: int, media_key: str):
        try:
            data, _mime = self.track_fetch_media(track_id, media_key)
            title = self._get_track_title(track_id)
            self._preview_blob_bytes(data, title)
        except Exception as e:
            self.conn.rollback()
            self.logger.exception(f"Preview {media_key} failed: {e}")
            QMessageBox.critical(self, "Track Media Error", f"Failed to preview file:\n{e}")

    def _export_bytes_with_picker(
        self,
        data,
        *,
        mime: str,
        suggested_basename: str,
        parent_widget=None,
        action_label: str,
        action_type: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        payload: dict | None = None,
        dialog_title: str = "Export file",
    ) -> None:
        if isinstance(data, memoryview):
            data = data.tobytes()
        elif isinstance(data, bytearray):
            data = bytes(data)
        default_filename = self._default_export_filename(suggested_basename, mime or "")
        dest_path, _ = QFileDialog.getSaveFileName(
            parent_widget or self, dialog_title, default_filename, "All files (*)"
        )
        if not dest_path:
            return

        try:
            self._run_file_history_action(
                action_label=action_label.format(filename=Path(dest_path).name),
                action_type=action_type,
                target_path=dest_path,
                mutation=lambda: Path(dest_path).write_bytes(data),
                entity_type=entity_type,
                entity_id=entity_id,
                payload={"path": str(dest_path), **(payload or {})},
            )
            QMessageBox.information(parent_widget or self, "Export", f"Saved:\n{dest_path}")
        except Exception as e:
            QMessageBox.critical(parent_widget or self, "Export failed", str(e))

    def _export_standard_media_for_track(
        self, track_id: int, media_key: str, suggested_basename: str | None = None
    ):
        try:
            data, mime = self.track_fetch_media(track_id, media_key)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        default_basename = suggested_basename or self._media_export_basename_for_track(
            track_id,
            media_key,
        )
        self._export_bytes_with_picker(
            data,
            mime=mime or "",
            suggested_basename=default_basename,
            parent_widget=self,
            action_label=f"Export {media_key.replace('_', ' ').title()}: {{filename}}",
            action_type=f"file.export_{media_key}",
            entity_type="Track",
            entity_id=str(track_id),
            payload={"track_id": track_id, "media_key": media_key},
        )

    @staticmethod
    def _export_extension_for_mime(mime: str) -> str:
        ext = mimetypes.guess_extension(mime or "")
        if ext == ".jpe":
            ext = ".jpg"
        if not ext:
            if str(mime or "").startswith("image/"):
                return ".png"
            if str(mime or "").startswith("audio/"):
                return ".wav"
            return ".bin"
        return ext

    def _default_export_filename(self, suggested_basename: str | None, mime: str) -> str:
        return (
            f"{sanitize_export_basename(suggested_basename)}"
            f"{self._export_extension_for_mime(mime)}"
        )

    @staticmethod
    def _deduplicate_export_destination(output_dir: Path, filename: str) -> Path:
        candidate = output_dir / filename
        if not candidate.exists():
            return candidate
        stem = candidate.stem
        suffix = candidate.suffix
        index = 2
        while True:
            deduplicated = output_dir / f"{stem} ({index}){suffix}"
            if not deduplicated.exists():
                return deduplicated
            index += 1

    def _media_export_basename_for_track(self, track_id: int, media_key: str) -> str:
        snapshot = None
        if self.track_service is not None:
            snapshot = self.track_service.fetch_track_snapshot(track_id, cursor=self.cursor)
        track_title = ""
        if snapshot is not None:
            track_title = str(snapshot.track_title or "").strip()
        if not track_title:
            try:
                track_title = self._get_track_title(track_id)
            except Exception:
                track_title = ""
        if media_key == "album_art" and snapshot is not None:
            album_title = str(snapshot.album_title or "").strip()
            if album_title and album_title.casefold() != "single":
                return album_title
        return track_title or f"track_{track_id}"

    def _custom_blob_export_basename(self, track_id: int, field_def_id: int) -> str:
        track_title = self._media_export_basename_for_track(track_id, "audio_file")
        field_name = self.custom_field_definitions.get_field_name(field_def_id)
        clean_field_name = str(field_name or "").strip()
        if clean_field_name:
            return f"{track_title} - {clean_field_name}"
        return track_title

    def _focused_media_export_spec(self, column: int) -> dict[str, object] | None:
        header_item = self.table.horizontalHeaderItem(column)
        header_text = header_item.text() if header_item is not None else ""
        media_key = self._standard_media_key_for_header(header_text)
        if media_key:
            return {
                "kind": "standard",
                "column_label": header_text or media_key.replace("_", " ").title(),
                "media_key": media_key,
            }
        if column < len(self.BASE_HEADERS):
            return None
        field_index = column - len(self.BASE_HEADERS)
        if field_index < 0 or field_index >= len(self.active_custom_fields):
            return None
        field = self.active_custom_fields[field_index]
        field_type = str(field.get("field_type") or "").strip()
        if field_type not in {"blob_audio", "blob_image"}:
            return None
        return {
            "kind": "custom_blob",
            "column_label": header_text or str(field.get("name") or "File"),
            "field_id": int(field["id"]),
            "field_name": str(field.get("name") or "").strip(),
            "field_type": field_type,
        }

    def _export_focused_media_column(
        self,
        column: int,
        *,
        track_ids: list[int] | None = None,
    ) -> None:
        spec = self._focused_media_export_spec(column)
        if spec is None:
            QMessageBox.warning(
                self,
                "Export Files",
                "Focus a stored audio, album art, or blob media column first.",
            )
            return
        selected_ids = self._normalize_track_ids(track_ids or self._selected_track_ids())
        if not selected_ids:
            QMessageBox.information(
                self,
                "Export Files",
                "Select one or more rows before exporting the focused column.",
            )
            return
        output_dir = QFileDialog.getExistingDirectory(
            self,
            f"Export {spec['column_label']} Files",
        )
        if not output_dir:
            return
        output_root = Path(output_dir)
        exported = 0
        skipped: list[str] = []
        history_changed = False
        for track_id in selected_ids:
            try:
                if spec["kind"] == "standard":
                    media_key = str(spec["media_key"])
                    if not self.track_has_media(track_id, media_key):
                        raise FileNotFoundError(
                            f"No stored {str(spec['column_label']).lower()} is available."
                        )
                    data, mime = self.track_fetch_media(track_id, media_key)
                    suggested_basename = self._media_export_basename_for_track(track_id, media_key)
                    payload = {
                        "track_id": track_id,
                        "media_key": media_key,
                        "column_label": spec["column_label"],
                    }
                    entity_id = str(track_id)
                else:
                    field_id = int(spec["field_id"])
                    if not self.cf_has_blob(track_id, field_id):
                        raise FileNotFoundError(
                            f"No stored file is available in {spec['column_label']}."
                        )
                    data, mime = self.cf_fetch_blob(track_id, field_id)
                    suggested_basename = self._custom_blob_export_basename(track_id, field_id)
                    payload = {
                        "track_id": track_id,
                        "field_id": field_id,
                        "column_label": spec["column_label"],
                    }
                    entity_id = f"{track_id}:{field_id}"
                if isinstance(data, memoryview):
                    data = data.tobytes()
                elif isinstance(data, bytearray):
                    data = bytes(data)
                dest_path = self._deduplicate_export_destination(
                    output_root,
                    self._default_export_filename(suggested_basename, mime or ""),
                )
                if self.history_manager is None:
                    dest_path.write_bytes(data)
                else:
                    run_file_history_action(
                        history_manager=self.history_manager,
                        action_label=f"Export {spec['column_label']}: {dest_path.name}",
                        action_type="file.export_bulk_media",
                        target_path=dest_path,
                        mutation=lambda data=data, dest_path=dest_path: dest_path.write_bytes(data),
                        entity_type="Export",
                        entity_id=entity_id,
                        payload={"path": str(dest_path), **payload},
                        logger=self.logger,
                    )
                    history_changed = True
                exported += 1
            except Exception as exc:
                try:
                    track_label = self._get_track_title(track_id) or f"track_{track_id}"
                except Exception:
                    track_label = f"track_{track_id}"
                skipped.append(f"{track_label}: {exc}")
        if history_changed:
            self._refresh_history_actions()
        if not exported:
            QMessageBox.warning(
                self,
                f"Export {spec['column_label']}",
                "No files were exported."
                + ("\n\nSkipped:\n" + "\n".join(skipped[:10]) if skipped else ""),
            )
            return
        message_lines = [
            f"Exported {exported} file{'s' if exported != 1 else ''} to:",
            str(output_root),
        ]
        if skipped:
            message_lines.append("")
            message_lines.append(f"Skipped {len(skipped)} row{'s' if len(skipped) != 1 else ''}:")
            message_lines.extend(skipped[:10])
        QMessageBox.information(
            self,
            f"Export {spec['column_label']}",
            "\n".join(message_lines),
        )

    def _convert_standard_media_for_track(
        self, track_id: int, media_key: str, target_mode: str
    ) -> None:
        try:
            self._run_snapshot_history_action(
                action_label=f"Convert {media_key.replace('_', ' ').title()} Storage",
                action_type=f"track.{media_key}.convert_storage_mode",
                entity_type="Track",
                entity_id=track_id,
                payload={
                    "track_id": track_id,
                    "media_key": media_key,
                    "target_mode": target_mode,
                },
                mutation=lambda: self.track_convert_media_storage_mode(
                    track_id, media_key, target_mode
                ),
            )
            self.refresh_table_preserve_view(focus_id=track_id)
        except Exception as exc:
            self.conn.rollback()
            self.logger.exception("Convert %s storage failed: %s", media_key, exc)
            QMessageBox.critical(
                self,
                "Track Media Error",
                f"Failed to convert storage mode:\n{exc}",
            )

    # ---------------------- BLOB CF helpers (DB IO + export) ----------------------
    def cf_get_field_type(self, field_def_id: int) -> str:
        return self.custom_field_definitions.get_field_type(field_def_id)

    def cf_save_value(
        self,
        track_id: int,
        field_def_id: int,
        *,
        value=None,
        blob_path: str | None = None,
        storage_mode: str | None = None,
    ):
        self.custom_field_values.save_value(
            track_id,
            field_def_id,
            value=value,
            blob_path=blob_path,
            storage_mode=storage_mode,
        )

    def cf_convert_blob_storage_mode(self, track_id: int, field_def_id: int, target_mode: str):
        return self.custom_field_values.convert_storage_mode(track_id, field_def_id, target_mode)

    def _attach_blob_for_cell(
        self, track_id: int, field_def_id: int, field_type: str, field_name: str
    ):
        if field_type == "blob_image":
            flt = "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff);;All files (*)"
        else:
            flt = "Audio (*.wav *.aif *.aiff *.mp3 *.flac *.m4a *.aac *.ogg *.opus);;All files (*)"
        p, _ = QFileDialog.getOpenFileName(self, f"Attach file: {field_name}", "", flt)
        if not p:
            return
        storage_mode = _prompt_storage_mode_choice(
            self,
            title=f"Attach {field_name}",
            subject=f"the file for {field_name}",
            default_mode=STORAGE_MODE_DATABASE,
        )
        if storage_mode is None:
            return
        try:
            self._run_snapshot_history_action(
                action_label=f"Attach Custom File: {field_name}",
                action_type="custom_field.blob_attach",
                entity_type="CustomFieldValue",
                entity_id=f"{track_id}:{field_def_id}",
                payload={
                    "track_id": track_id,
                    "field_id": field_def_id,
                    "field_name": field_name,
                    "storage_mode": storage_mode,
                },
                mutation=lambda: self.cf_save_value(
                    track_id,
                    field_def_id,
                    value=None,
                    blob_path=p,
                    storage_mode=storage_mode,
                ),
            )
            self.refresh_table_preserve_view(focus_id=track_id)
        except Exception as e:
            self.conn.rollback()
            self.logger.exception(f"Attach blob failed: {e}")
            QMessageBox.critical(self, "Custom Field Error", f"Failed to attach file:\n{e}")

    # ---------------------- BLOB CF helpers v2 (get/export/delete/format) ----------------------
    def cf_get_value_meta(
        self,
        track_id: int,
        field_def_id: int,
        *,
        include_storage_details: bool = False,
    ):
        return self.custom_field_values.get_value_meta(
            track_id,
            field_def_id,
            include_storage_details=include_storage_details,
        )

    def cf_has_blob(self, track_id: int, field_def_id: int) -> bool:
        return self.custom_field_values.has_blob(track_id, field_def_id)

    def cf_blob_size(self, track_id: int, field_def_id: int) -> int:
        return self.custom_field_values.blob_size(track_id, field_def_id)

    def cf_fetch_blob(self, track_id: int, field_def_id: int):
        return self.custom_field_values.fetch_blob(track_id, field_def_id)

    def cf_export_blob(
        self,
        track_id: int,
        field_def_id: int,
        parent_widget=None,
        suggested_basename: str | None = None,
    ):
        try:
            data, mime = self.cf_fetch_blob(track_id, field_def_id)
        except Exception as e:
            QMessageBox.critical(parent_widget or None, "Export failed", str(e))
            return
        if suggested_basename is None:
            suggested_basename = self.custom_field_definitions.get_field_name(field_def_id)
        self._export_bytes_with_picker(
            data,
            mime=mime or "",
            suggested_basename=suggested_basename,
            parent_widget=parent_widget or self,
            action_label="Export Custom File: {filename}",
            action_type="file.export_custom_blob",
            entity_type="CustomFieldValue",
            entity_id=f"{track_id}:{field_def_id}",
            payload={"track_id": track_id, "field_id": field_def_id},
        )

    def cf_delete_blob(self, track_id: int, field_def_id: int):
        self.custom_field_values.delete_blob(track_id, field_def_id)

    def _convert_custom_blob_storage_mode(
        self, track_id: int, field_def_id: int, target_mode: str
    ) -> None:
        try:
            field_name = self.custom_field_definitions.get_field_name(field_def_id)
            self._run_snapshot_history_action(
                action_label=f"Convert Custom File Storage: {field_name}",
                action_type="custom_field.blob_convert_storage_mode",
                entity_type="CustomFieldValue",
                entity_id=f"{track_id}:{field_def_id}",
                payload={
                    "track_id": track_id,
                    "field_id": field_def_id,
                    "target_mode": target_mode,
                },
                mutation=lambda: self.cf_convert_blob_storage_mode(
                    track_id,
                    field_def_id,
                    target_mode,
                ),
            )
            self.refresh_table_preserve_view(focus_id=track_id)
        except Exception as exc:
            self.conn.rollback()
            self.logger.exception("Convert custom blob storage failed: %s", exc)
            QMessageBox.critical(
                self,
                "Custom Field Error",
                f"Failed to convert storage mode:\n{exc}",
            )

    def _human_size(self, n: int) -> str:
        try:
            n = int(n or 0)
        except Exception:
            n = 0
        thresh = 1024.0
        units = ["B", "KB", "MB", "GB", "TB"]
        u = 0
        val = float(n)
        while val >= thresh and u < len(units) - 1:
            val /= thresh
            u += 1
        return f"{val:.0f} {units[u]}" if u == 0 else f"{val:.1f} {units[u]}"

    def _format_blob_badge(self, mime_type: str | None, size_bytes: int) -> str:
        _mime_type = mime_type
        return self._human_size(size_bytes)

    @staticmethod
    def _blob_icon_kind_for_standard_media(
        media_key: str,
        *,
        meta: dict[str, object] | None = None,
    ) -> str:
        if media_key == "audio_file" and bool((meta or {}).get("is_lossy")):
            return "audio_lossy"
        return "audio" if media_key == "audio_file" else "image"

    def _standard_media_badge_tooltip(
        self,
        media_key: str,
        meta: dict[str, object],
        display: str,
    ) -> str:
        if media_key != "audio_file":
            return f"Stored size: {display}"
        format_label = str(meta.get("format_label") or "").strip()
        if bool(meta.get("is_lossy")):
            if format_label:
                return f"Lossy primary audio · {format_label}\nStored size: {display}"
            return f"Lossy primary audio\nStored size: {display}"
        if format_label:
            return f"Primary audio · {format_label}\nStored size: {display}"
        return f"Primary audio\nStored size: {display}"

    def _blob_icon_spec_for_standard_media(
        self,
        media_key: str,
        *,
        meta: dict[str, object] | None = None,
    ) -> dict[str, object]:
        settings = normalize_blob_icon_settings(
            getattr(self, "blob_icon_settings", None) or default_blob_icon_settings()
        )
        return settings[self._blob_icon_kind_for_standard_media(media_key, meta=meta)]

    def _blob_icon_spec_for_custom_field(self, field: dict[str, object]) -> dict[str, object]:
        field_type = str(field.get("field_type") or "").strip().lower()
        kind = "audio" if field_type == "blob_audio" else "image"
        override = field.get("blob_icon_payload")
        if override:
            return override
        return self._blob_icon_spec_for_standard_media(
            "audio_file" if kind == "audio" else "album_art"
        )

    def _resolve_blob_badge_icon(
        self,
        *,
        spec: dict[str, object] | None,
        kind: str,
    ) -> QIcon:
        fallback_media_key = "audio_file" if kind in ("audio", "audio_lossy") else "album_art"
        fallback_meta = {"is_lossy": True} if kind == "audio_lossy" else None
        return icon_from_blob_icon_spec(
            spec,
            kind=kind,
            style=self.style() if hasattr(self, "style") else None,
            fallback_spec=self._blob_icon_spec_for_standard_media(
                fallback_media_key,
                meta=fallback_meta,
            ),
            allow_inherit=True,
            size=18,
        )

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

    def _column_index_by_header(self, header_text: str) -> int:
        for idx in range(self.table.columnCount()):
            item = self.table.horizontalHeaderItem(idx)
            if item is not None and item.text() == header_text:
                return idx
        return -1

    def _get_track_title(self, track_id: int) -> str:
        return self.track_service.fetch_track_title(track_id, cursor=self.cursor)

    def _sanitize_filename(self, text: str) -> str:
        return sanitize_export_basename(text)

    def _set_blob_indicator(self, row: int, col: int, track_id: int, field_id: int) -> None:
        try:
            meta = self.cf_get_value_meta(track_id, field_id)
        except Exception:
            meta = {"has_blob": False, "mime_type": None, "size_bytes": 0}
        display = (
            self._format_blob_badge(meta.get("mime_type"), meta.get("size_bytes", 0))
            if meta.get("has_blob")
            else "—"
        )
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem(display)
            self.table.setItem(row, col, item)
        else:
            item.setText(display)
        if meta.get("has_blob"):
            field = next(
                (
                    candidate
                    for candidate in self.active_custom_fields
                    if candidate.get("id") == field_id
                ),
                None,
            )
            if field is not None:
                kind = "audio" if field.get("field_type") == "blob_audio" else "image"
                item.setIcon(
                    self._resolve_blob_badge_icon(
                        spec=self._blob_icon_spec_for_custom_field(field),
                        kind=kind,
                    )
                )
                item.setToolTip(
                    f"{describe_blob_icon_spec(field.get('blob_icon_payload'), kind=kind, allow_inherit=True)}\nStored size: {display}"
                )
        else:
            item.setIcon(QIcon())
            item.setToolTip("")
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
        standard_media_columns = {
            header: self.BASE_HEADERS.index(header)
            for header in self._standard_media_header_map()
            if header in self.BASE_HEADERS
        }
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

            for header, media_key in self._standard_media_header_map().items():
                col = standard_media_columns.get(header)
                if col is None:
                    continue
                try:
                    meta = self.track_media_meta(pk, media_key)
                except Exception:
                    meta = {"has_media": False, "mime_type": None, "size_bytes": 0}
                display = (
                    self._format_blob_badge(meta.get("mime_type"), meta.get("size_bytes", 0))
                    if meta.get("has_media")
                    else "—"
                )
                item = self.table.item(row_idx, col)
                if item is None:
                    item = QTableWidgetItem(display)
                    self.table.setItem(row_idx, col, item)
                else:
                    item.setText(display)
                if meta.get("has_media"):
                    kind = self._blob_icon_kind_for_standard_media(media_key, meta=meta)
                    item.setIcon(
                        self._resolve_blob_badge_icon(
                            spec=self._blob_icon_spec_for_standard_media(media_key, meta=meta),
                            kind=kind,
                        )
                    )
                    item.setToolTip(self._standard_media_badge_tooltip(media_key, meta, display))
                else:
                    item.setIcon(QIcon())
                    item.setToolTip("")
                item.setData(Qt.UserRole, (pk, media_key) if meta.get("has_media") else None)

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
                if has_blob:
                    kind = "audio" if ftype == "blob_audio" else "image"
                    item.setIcon(
                        self._resolve_blob_badge_icon(
                            spec=self._blob_icon_spec_for_custom_field(cf),
                            kind=kind,
                        )
                    )
                    item.setToolTip(
                        f"{describe_blob_icon_spec(cf.get('blob_icon_payload'), kind=kind, allow_inherit=True)}\nStored size: {display}"
                    )
                else:
                    item.setIcon(QIcon())
                    item.setToolTip("")
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
            tf.write(data)
            tf.flush()
            tf.close()
        except Exception as e:
            QMessageBox.critical(self, "Preview", f"Could not create temp file: {e}")
            return

        dlg = _AudioPreviewDialog(self, tf.name, title)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)  # cleanup on close
        dlg.setWindowFlag(Qt.Window, True)  # make it a top-level window
        dlg.setModal(False)  # explicitly non-modal
        dlg.show()
        dlg._player.play()

    def _list_all_tracks(self):
        return self.catalog_reads.list_tracks()

    def _list_licensees(self):
        return self.catalog_service.list_licensee_choices()

    def migrate_legacy_licenses_to_contracts(self):
        if self.license_migration_service is None or self.history_manager is None:
            QMessageBox.warning(self, "Legacy License Migration", "Open a profile first.")
            return

        summary = self.license_migration_service.inspect()
        if summary.legacy_license_count == 0 and summary.legacy_licensee_count == 0:
            QMessageBox.information(
                self,
                "Legacy License Migration",
                "No legacy license records or legacy licensee names were found in this profile.",
            )
            return

        if not summary.ready:
            detail_lines = [issue.message for issue in summary.issues[:8]]
            extra_count = max(0, len(summary.issues) - len(detail_lines))
            if extra_count:
                detail_lines.append(f"...and {extra_count} more issue(s).")
            QMessageBox.warning(
                self,
                "Legacy License Migration Blocked",
                "\n\n".join(
                    [
                        (
                            "The migration cannot start until every legacy license row still points "
                            "to a valid managed PDF and a valid track."
                        ),
                        "\n".join(detail_lines),
                    ]
                ),
            )
            return

        confirm_message = "\n".join(
            [
                "Migrate the legacy license archive into the new party and contract model?",
                "",
                f"Legacy license PDFs to migrate: {summary.legacy_license_count}",
                f"Legacy licensee names to migrate: {summary.legacy_licensee_count}",
                f"Unused legacy licensee names to convert into parties: {summary.unused_licensee_count}",
                "",
                "This will:",
                "- create or reuse Party records for legacy licensees",
                "- create Contract records linked to the original tracks and related releases/works where found",
                "- copy each legacy PDF into managed contract-document storage and verify its checksum",
                "- remove the migrated legacy license rows, legacy licensee rows, and old managed license files only after verification",
                "- capture before/after restore points so the migration can be rolled back safely",
            ]
        )
        if (
            QMessageBox.question(
                self,
                "Legacy License Migration",
                confirm_message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return

        def _worker(bundle, ctx):
            ctx.set_status("Preparing legacy license migration...")
            return run_snapshot_history_action(
                history_manager=bundle.history_manager,
                action_label="Migrate Legacy Licenses to Contracts",
                action_type="license.migrate_legacy",
                entity_type="License",
                entity_id="legacy_migration",
                payload={
                    "legacy_license_count": summary.legacy_license_count,
                    "legacy_licensee_count": summary.legacy_licensee_count,
                },
                mutation=lambda: bundle.license_migration_service.migrate_all(ctx=ctx),
                logger=self.logger,
            )

        def _success(result):
            self._refresh_after_history_change()
            QMessageBox.information(
                self,
                "Legacy License Migration",
                "\n".join(
                    [
                        "Legacy license migration completed successfully.",
                        "",
                        f"Migrated legacy licenses: {result.migrated_license_count}",
                        f"Migrated legacy licensees: {result.migrated_licensee_count}",
                        f"Created contracts: {result.created_contract_count}",
                        f"Created contract documents: {result.created_document_count}",
                        f"Deleted old legacy files: {result.deleted_legacy_file_count}",
                    ]
                ),
            )

        self._submit_background_bundle_task(
            title="Legacy License Migration",
            description="Migrating legacy license PDFs into structured contracts...",
            task_fn=_worker,
            kind="write",
            unique_key="licenses.migrate_legacy",
            on_success=_success,
            on_error=lambda failure: self._show_background_task_error(
                "Legacy License Migration",
                failure,
                user_message="Could not migrate the legacy license archive:",
            ),
        )

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
        if self.license_service is None:
            QMessageBox.warning(self, "License Browser", "Open a profile first.")
            return
        dock = self._ensure_license_browser_dock()
        panel = dock.show_panel()
        panel.set_track_filter_id(track_filter_id)
        self.licenses_browser_dialog = panel


class _AlbumTrackSection(QWidget):
    """Reusable track-entry section for the Add Album dialog."""

    def __init__(self, dialog: "AlbumEntryDialog", number: int):
        super().__init__(dialog)
        self.dialog = dialog
        self.app = dialog.app
        self._display_title = ""
        self.setObjectName("albumTrackSection")
        self.setProperty("role", "tabPaneCanvas")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 8, 6, 10)
        root.setSpacing(12)

        self.track_note = QLabel("Track-specific metadata, timing, codes, and managed audio.")
        self.track_note.setProperty("role", "secondary")
        self.track_note.setWordWrap(True)
        root.addWidget(self.track_note)

        self.section_tabs = QTabWidget(self)
        self.section_tabs.setObjectName("albumTrackSectionTabs")
        self.section_tabs.setDocumentMode(True)
        self.section_tabs.setUsesScrollButtons(False)
        root.addWidget(self.section_tabs, 1)

        def create_tab(
            tab_title: str, section_title: str, description: str | None = None
        ) -> QVBoxLayout:
            page = QWidget(self.section_tabs)
            page.setProperty("role", "tabPaneCanvas")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(10)

            if description:
                intro = QLabel(description, page)
                intro.setWordWrap(True)
                intro.setProperty("role", "secondary")
                page_layout.addWidget(intro)

            box, box_layout = _create_standard_section(page, section_title)
            box_layout.setContentsMargins(14, 18, 14, 14)
            box_layout.setSpacing(10)
            page_layout.addWidget(box)
            page_layout.addStretch(1)
            self.section_tabs.addTab(page, tab_title)
            return box_layout

        details_layout = create_tab(
            "Details",
            "Track Details",
            "Capture the track-facing metadata and timing for this album row.",
        )
        codes_layout = create_tab(
            "Codes",
            "Track Codes",
            "Keep registration identifiers and export-facing codes together.",
        )
        media_layout = create_tab(
            "Media",
            "Managed Audio",
            "Attach the source audio file used when saving these album tracks.",
        )

        self.track_title = QLineEdit()
        self.track_title.setPlaceholderText("Track title")
        self.dialog._apply_input_height(self.track_title)
        self._add_labeled_widget(details_layout, "Track Title", self.track_title)

        self.artist_name = self.dialog._build_artist_combo(allow_empty=True)
        self.artist_name.setCurrentText("")
        self._add_labeled_widget(details_layout, "Main Artist", self.artist_name)

        self.additional_artists = self.dialog._build_artist_combo(allow_empty=True)
        self.additional_artists.setCurrentText("")
        self._add_labeled_widget(details_layout, "Additional Artists", self.additional_artists)

        self.release_date = QLineEdit()
        self.release_date.setReadOnly(True)
        self.release_date.setPlaceholderText("No release date selected")
        self.dialog._apply_input_height(self.release_date)
        release_row = QWidget(self)
        release_layout = QHBoxLayout(release_row)
        release_layout.setContentsMargins(0, 0, 0, 0)
        release_layout.setSpacing(8)
        release_layout.addWidget(self.release_date, 1)
        self.release_date_pick_button = QPushButton("Pick…")
        self.release_date_pick_button.setAutoDefault(False)
        self.dialog._apply_button_height(self.release_date_pick_button)
        self.release_date_pick_button.clicked.connect(self._pick_release_date)
        self.release_date_today_button = QPushButton("Today")
        self.release_date_today_button.setAutoDefault(False)
        self.dialog._apply_button_height(self.release_date_today_button)
        self.release_date_today_button.clicked.connect(
            lambda: self.set_release_date_iso(QDate.currentDate().toString("yyyy-MM-dd"))
        )
        self.release_date_clear_button = QPushButton("Clear")
        self.release_date_clear_button.setAutoDefault(False)
        self.dialog._apply_button_height(self.release_date_clear_button)
        self.release_date_clear_button.clicked.connect(lambda: self.set_release_date_iso(None))
        release_layout.addWidget(self.release_date_pick_button)
        release_layout.addWidget(self.release_date_today_button)
        release_layout.addWidget(self.release_date_clear_button)
        self._add_labeled_widget(details_layout, "Release Date", release_row)

        self.len_h = TwoDigitSpinBox()
        self.len_h.setRange(0, 99)
        self.len_h.setFixedWidth(60)
        self.len_m = TwoDigitSpinBox()
        self.len_m.setRange(0, 59)
        self.len_m.setFixedWidth(50)
        self.len_s = TwoDigitSpinBox()
        self.len_s.setRange(0, 59)
        self.len_s.setFixedWidth(50)
        length_group = QFrame(self)
        length_group.setProperty("role", "compactControlGroup")
        length_group.setAttribute(Qt.WA_StyledBackground, True)
        length_group.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        length_layout = QHBoxLayout(length_group)
        length_layout.setContentsMargins(10, 8, 10, 8)
        length_layout.setSpacing(6)
        length_layout.addWidget(self.len_h)
        length_layout.addWidget(QLabel(":"))
        length_layout.addWidget(self.len_m)
        length_layout.addWidget(QLabel(":"))
        length_layout.addWidget(self.len_s)
        self._add_labeled_widget(details_layout, "Track Length (hh:mm:ss)", length_group)

        self.isrc = QLineEdit()
        if self.dialog.auto_isrc_enabled:
            self.isrc.setPlaceholderText("Leave blank to auto-generate on save")
        else:
            self.isrc.setPlaceholderText("Leave blank if this track has no ISRC yet")
        self.dialog._apply_input_height(self.isrc)
        self._add_labeled_widget(codes_layout, "ISRC", self.isrc)

        isrc_note = QLabel(self.dialog.isrc_help_text)
        isrc_note.setProperty("role", "secondary")
        isrc_note.setWordWrap(True)
        codes_layout.addWidget(isrc_note)

        self.iswc = QLineEdit()
        self.iswc.setPlaceholderText("Optional ISWC")
        self.dialog._apply_input_height(self.iswc)
        self._add_labeled_widget(codes_layout, "ISWC", self.iswc)

        self.buma_work_number = QLineEdit()
        self.buma_work_number.setPlaceholderText("Optional BUMA work number")
        self.dialog._apply_input_height(self.buma_work_number)
        self._add_labeled_widget(codes_layout, "BUMA Wnr.", self.buma_work_number)

        self.audio_file = QLineEdit()
        self.audio_file.setReadOnly(True)
        self.audio_file.setPlaceholderText("No audio file selected")
        self.dialog._apply_input_height(self.audio_file)
        audio_row = QWidget(self)
        audio_layout = QHBoxLayout(audio_row)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.setSpacing(8)
        audio_layout.addWidget(self.audio_file, 1)
        self.audio_browse_button = QPushButton("Browse…")
        self.audio_browse_button.setAutoDefault(False)
        self.dialog._apply_button_height(self.audio_browse_button)
        self.audio_browse_button.clicked.connect(
            lambda: self.app._choose_media_into_line_edit(
                "audio_file", self.audio_file, parent_widget=self.dialog
            )
        )
        self.audio_clear_button = QPushButton("Clear")
        self.audio_clear_button.setAutoDefault(False)
        self.dialog._apply_button_height(self.audio_clear_button)
        self.audio_clear_button.clicked.connect(self.audio_file.clear)
        audio_layout.addWidget(self.audio_browse_button)
        audio_layout.addWidget(self.audio_clear_button)
        audio_container = QWidget(self)
        audio_container_layout = QVBoxLayout(audio_container)
        audio_container_layout.setContentsMargins(0, 0, 0, 0)
        audio_container_layout.setSpacing(6)
        audio_container_layout.addWidget(audio_row)
        self.audio_file_warning_label = QLabel("")
        self.audio_file_warning_label.setWordWrap(True)
        self.audio_file_warning_label.setProperty("role", "supportingText")
        self.audio_file_warning_label.setVisible(False)
        audio_container_layout.addWidget(self.audio_file_warning_label)
        self.audio_file._lossy_audio_warning_label = self.audio_file_warning_label
        self.audio_file.textChanged.connect(
            lambda _text: self.app._refresh_line_edit_lossy_audio_warning(self.audio_file)
        )
        self.app._refresh_line_edit_lossy_audio_warning(self.audio_file)
        self._add_labeled_widget(media_layout, "Audio File", audio_container)

        root.addStretch(1)
        self.set_track_number(number)

    @staticmethod
    def _add_labeled_widget(layout: QVBoxLayout, label_text: str, widget: QWidget) -> None:
        row = QVBoxLayout()
        row.setContentsMargins(0, 0, 0, 4)
        row.setSpacing(6)
        label = QLabel(label_text)
        row.addWidget(label)
        row.addWidget(widget)
        layout.addLayout(row)

    def set_track_number(self, number: int) -> None:
        self._display_title = f"Track {int(number):02d}"

    def title(self) -> str:
        return self._display_title

    def set_release_date_iso(self, iso_date: str | None) -> None:
        clean_value = str(iso_date or "").strip()
        self.release_date.setText(clean_value)

    def release_date_iso(self) -> str | None:
        clean_value = (self.release_date.text() or "").strip()
        return clean_value or None

    def track_length_seconds(self) -> int:
        return hms_to_seconds(self.len_h.value(), self.len_m.value(), self.len_s.value())

    def is_effectively_blank(self) -> bool:
        return all(
            (
                not (self.track_title.text() or "").strip(),
                not self.artist_name.currentText().strip(),
                not self.additional_artists.currentText().strip(),
                not self.release_date_iso(),
                self.track_length_seconds() == 0,
                not (self.isrc.text() or "").strip(),
                not (self.iswc.text() or "").strip(),
                not (self.buma_work_number.text() or "").strip(),
                not (self.audio_file.text() or "").strip(),
            )
        )

    def _pick_release_date(self) -> None:
        dlg = DatePickerDialog(
            self.dialog,
            initial_iso_date=self.release_date_iso(),
            title=f"Pick Release Date for {self.title()}",
        )
        if dlg.exec() == QDialog.Accepted:
            self.set_release_date_iso(dlg.selected_iso())


class AlbumEntryDialog(QDialog):
    """Creates multiple tracks for a shared album from one structured dialog."""

    EXTRA_QSS = """
    QDialog#albumEntryDialog QCheckBox {
        spacing: 6px;
    }
    QDialog#albumEntryDialog QTabWidget#albumEntryPrimaryTabs::pane,
    QDialog#albumEntryDialog QTabWidget#albumEntryTrackTabs::pane {
        margin-top: 8px;
    }
    QDialog#albumEntryDialog QTabBar::tab {
        min-width: 104px;
        padding: 7px 14px;
    }
    QDialog#albumEntryDialog QTabBar::tab:selected {
        font-weight: 600;
    }
    QDialog#albumEntryDialog QScrollArea {
        background: transparent;
    }
    """

    @staticmethod
    def _create_tab_page(owner: QWidget) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget(owner)
        page.setProperty("role", "workspaceCanvas")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)
        return page, layout

    @staticmethod
    def _scaled_control_height(widget: QWidget, *, extra_padding: int) -> int:
        hint_height = 0
        try:
            hint_height = int(widget.sizeHint().height())
        except Exception:
            hint_height = 0
        try:
            font_height = int(widget.fontMetrics().height())
        except Exception:
            font_height = 0
        return max(hint_height, font_height + extra_padding)

    def _apply_input_height(self, widget: QWidget) -> None:
        widget.setMinimumHeight(self._scaled_control_height(widget, extra_padding=6))

    def _apply_button_height(self, widget: QWidget) -> None:
        widget.setMinimumHeight(self._scaled_control_height(widget, extra_padding=8))

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.created_track_ids: list[int] = []
        self._track_sections: list[_AlbumTrackSection] = []
        self._track_pages: dict[_AlbumTrackSection, QWidget] = {}

        state, state_message = self.app._isrc_generation_state()
        self.auto_isrc_enabled = state == "ready"
        self.isrc_help_text = (
            "Leave ISRC blank to auto-generate it on save using the current prefix, artist code, and track release-year rule."
            if self.auto_isrc_enabled
            else state_message
        )

        self.setWindowTitle("Add Album")
        self.setModal(True)
        self.resize(960, 960)
        self.setMinimumSize(820, 760)
        _apply_standard_dialog_chrome(self, "albumEntryDialog", extra_qss=self.EXTRA_QSS)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)
        _add_standard_dialog_header(
            main_layout,
            self,
            title="Add Album",
            subtitle=(
                "Capture shared album metadata once, then use the Tracks tab to work through one tab per track. "
                "Blank track tabs are ignored when you save."
            ),
            help_topic_id="album-entry",
        )

        self.primary_tabs = QTabWidget(self)
        self.primary_tabs.setObjectName("albumEntryPrimaryTabs")
        self.primary_tabs.setDocumentMode(False)
        self.primary_tabs.setUsesScrollButtons(False)
        main_layout.addWidget(self.primary_tabs, 1)

        self.album_details_tab, album_details_layout = self._create_tab_page(self.primary_tabs)
        self.track_workspace_tab, track_workspace_layout = self._create_tab_page(self.primary_tabs)
        self.primary_tabs.addTab(self.album_details_tab, "Album Details")
        self.primary_tabs.addTab(self.track_workspace_tab, "Tracks")

        summary_box, summary_layout = _create_standard_section(
            self.album_details_tab,
            "Workflow Notes",
            "Album-level values apply to every saved track in this dialog, while each track section keeps its own metadata and audio file.",
        )
        summary_label = QLabel(
            "Album Title, UPC/EAN, Genre, Catalog#, and Album Art are shared across the new album tracks. "
            + self.isrc_help_text
        )
        summary_label.setWordWrap(True)
        summary_label.setProperty("role", "supportingText")
        summary_layout.addWidget(summary_label)
        album_details_layout.addWidget(summary_box)

        overview_box, overview_layout = _create_standard_section(
            self.album_details_tab, "Album Overview"
        )
        overview_layout.setSpacing(10)
        self.album_title = self._build_album_combo()
        self._add_labeled_widget(overview_layout, "Album Title", self.album_title)

        self.upc = self._build_upc_combo()
        self._add_labeled_widget(overview_layout, "UPC / EAN", self.upc)

        self.genre = self._build_genre_combo()
        self._add_labeled_widget(overview_layout, "Genre", self.genre)

        self.catalog_number = self._build_catalog_number_combo()
        self.catalog_number.setCurrentText("")
        self._add_labeled_widget(overview_layout, "Catalog#", self.catalog_number)

        self.album_art = QLineEdit()
        self.album_art.setReadOnly(True)
        self.album_art.setPlaceholderText("No album art selected")
        self._apply_input_height(self.album_art)
        art_row = QWidget(self)
        art_layout = QHBoxLayout(art_row)
        art_layout.setContentsMargins(0, 0, 0, 0)
        art_layout.setSpacing(8)
        art_layout.addWidget(self.album_art, 1)
        self.album_art_browse_button = QPushButton("Browse…")
        self.album_art_browse_button.setAutoDefault(False)
        self._apply_button_height(self.album_art_browse_button)
        self.album_art_browse_button.clicked.connect(
            lambda: self.app._choose_media_into_line_edit(
                "album_art", self.album_art, parent_widget=self
            )
        )
        self.album_art_clear_button = QPushButton("Clear")
        self.album_art_clear_button.setAutoDefault(False)
        self._apply_button_height(self.album_art_clear_button)
        self.album_art_clear_button.clicked.connect(self.album_art.clear)
        art_layout.addWidget(self.album_art_browse_button)
        art_layout.addWidget(self.album_art_clear_button)
        self._add_labeled_widget(overview_layout, "Album Art", art_row)

        self.use_release_year = QCheckBox(
            "Use each track release year when auto-generating blank ISRC values"
        )
        self.use_release_year.setChecked(False)
        self.use_release_year.setEnabled(self.auto_isrc_enabled)
        self.use_release_year.setToolTip(self.isrc_help_text)
        self.use_release_year.setContentsMargins(0, 4, 0, 0)
        overview_layout.addWidget(self.use_release_year)
        overview_layout.addStretch(1)
        album_details_layout.addWidget(overview_box)
        album_details_layout.addStretch(1)

        tracks_box, tracks_box_layout = _create_standard_section(
            self.track_workspace_tab,
            "Tracks",
            "Start with two track tabs, add more whenever needed, and remove the current tab when you no longer need it.",
        )
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(8)
        self.track_count_label = QLabel()
        self.track_count_label.setProperty("role", "meta")
        controls_row.addWidget(self.track_count_label)
        controls_row.addStretch(1)
        self.add_track_button = QPushButton("Add Track")
        self.add_track_button.setAutoDefault(False)
        self._apply_button_height(self.add_track_button)
        self.add_track_button.clicked.connect(self.add_track_section)
        controls_row.addWidget(self.add_track_button)
        self.remove_track_button = QPushButton("Remove Current Track")
        self.remove_track_button.setAutoDefault(False)
        self._apply_button_height(self.remove_track_button)
        self.remove_track_button.clicked.connect(self.remove_current_track_section)
        controls_row.addWidget(self.remove_track_button)
        tracks_box_layout.addLayout(controls_row)
        tracks_box_layout.addSpacing(6)

        self.track_tabs = QTabWidget(self.track_workspace_tab)
        self.track_tabs.setObjectName("albumEntryTrackTabs")
        self.track_tabs.setDocumentMode(False)
        self.track_tabs.setUsesScrollButtons(True)
        self.track_tabs.setElideMode(Qt.ElideRight)
        tracks_box_layout.addWidget(self.track_tabs, 1)
        track_workspace_layout.addWidget(tracks_box, 1)

        for _ in range(2):
            self.add_track_section()

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.save_button = QPushButton("Save Album")
        self.save_button.setDefault(True)
        self._apply_button_height(self.save_button)
        self.save_button.clicked.connect(self.save_album)
        self.cancel_button = QPushButton("Cancel")
        self._apply_button_height(self.cancel_button)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.cancel_button)
        main_layout.addLayout(buttons)

    def _combo_from_query(self, query: str, *, allow_empty: bool = True) -> FocusWheelComboBox:
        combo = FocusWheelComboBox()
        combo.setEditable(True)
        values = [
            str(row[0] or "").strip()
            for row in self.app.cursor.execute(query).fetchall()
            if str(row[0] or "").strip()
        ]
        if allow_empty:
            combo.addItem("")
        combo.addItems(values)
        completer = QCompleter(values)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        combo.setCompleter(completer)
        self._apply_input_height(combo)
        return combo

    def _build_artist_combo(self, *, allow_empty: bool) -> FocusWheelComboBox:
        return self._combo_from_query(
            "SELECT DISTINCT name FROM Artists WHERE name IS NOT NULL AND name != '' ORDER BY name",
            allow_empty=allow_empty,
        )

    def _build_album_combo(self) -> FocusWheelComboBox:
        return self._combo_from_query(
            "SELECT DISTINCT title FROM Albums WHERE title IS NOT NULL AND title != '' ORDER BY title",
            allow_empty=True,
        )

    def _build_upc_combo(self) -> FocusWheelComboBox:
        return self._combo_from_query(
            """
            SELECT value
            FROM (
                SELECT upc AS value FROM Tracks WHERE upc IS NOT NULL AND upc != ''
                UNION
                SELECT upc AS value FROM Releases WHERE upc IS NOT NULL AND upc != ''
            )
            ORDER BY value
            """,
            allow_empty=True,
        )

    def _build_genre_combo(self) -> FocusWheelComboBox:
        return self._combo_from_query(
            "SELECT DISTINCT genre FROM Tracks WHERE genre IS NOT NULL AND genre != '' ORDER BY genre",
            allow_empty=True,
        )

    def _build_catalog_number_combo(self) -> FocusWheelComboBox:
        return self._combo_from_query(
            """
            SELECT value
            FROM (
                SELECT catalog_number AS value
                FROM Tracks
                WHERE catalog_number IS NOT NULL AND catalog_number != ''
                UNION
                SELECT catalog_number AS value
                FROM Releases
                WHERE catalog_number IS NOT NULL AND catalog_number != ''
            )
            ORDER BY value
            """,
            allow_empty=True,
        )

    @staticmethod
    def _add_labeled_widget(layout: QVBoxLayout, label_text: str, widget: QWidget) -> None:
        row = QVBoxLayout()
        row.setContentsMargins(0, 0, 0, 2)
        row.setSpacing(4)
        label = QLabel(label_text)
        row.addWidget(label)
        row.addWidget(widget)
        layout.addLayout(row)

    def _refresh_track_section_titles(self) -> None:
        for index, section in enumerate(self._track_sections, start=1):
            section.set_track_number(index)
            page = self._track_pages.get(section)
            tab_index = self.track_tabs.indexOf(page) if page is not None else -1
            if tab_index >= 0:
                tab_title = section.title()
                self.track_tabs.setTabText(tab_index, tab_title)
                self.track_tabs.setTabToolTip(tab_index, tab_title)
        track_count = len(self._track_sections)
        self.track_count_label.setText(
            f"{track_count} track tab{'s' if track_count != 1 else ''} available"
        )
        self.remove_track_button.setEnabled(track_count > 1)

    def add_track_section(self) -> None:
        section = _AlbumTrackSection(self, len(self._track_sections) + 1)
        self._track_sections.append(section)
        page = QWidget(self.track_tabs)
        page.setProperty("role", "workspaceCanvas")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 6, 0, 0)
        page_layout.setSpacing(0)
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setProperty("role", "workspaceCanvas")
        viewport = scroll.viewport()
        if viewport is not None:
            viewport.setProperty("role", "workspaceCanvas")
        scroll.setWidget(section)
        page_layout.addWidget(scroll)
        self._track_pages[section] = page
        self.track_tabs.addTab(page, "")
        self._refresh_track_section_titles()
        self.track_tabs.setCurrentWidget(page)
        self.primary_tabs.setCurrentWidget(self.track_workspace_tab)

    def _focus_track_section(self, section: _AlbumTrackSection) -> None:
        page = self._track_pages.get(section)
        if page is None:
            return
        self.primary_tabs.setCurrentWidget(self.track_workspace_tab)
        self.track_tabs.setCurrentWidget(page)

    def remove_current_track_section(self) -> None:
        current_page = self.track_tabs.currentWidget()
        if current_page is None:
            return
        for section, page in list(self._track_pages.items()):
            if page is current_page:
                self.remove_track_section(section)
                break

    def remove_track_section(self, section: _AlbumTrackSection) -> None:
        if section not in self._track_sections or len(self._track_sections) <= 1:
            return
        page = self._track_pages.pop(section, None)
        current_index = self.track_tabs.indexOf(page) if page is not None else -1
        self._track_sections.remove(section)
        if current_index >= 0:
            self.track_tabs.removeTab(current_index)
        section.setParent(None)
        section.deleteLater()
        if page is not None:
            page.deleteLater()
        self._refresh_track_section_titles()
        if self.track_tabs.count() > 0:
            self.track_tabs.setCurrentIndex(max(0, min(current_index, self.track_tabs.count() - 1)))

    def _build_track_payloads(self) -> list[TrackCreatePayload] | None:
        album_title = self.album_title.currentText().strip()
        if is_blank(album_title):
            self.primary_tabs.setCurrentWidget(self.album_details_tab)
            QMessageBox.warning(
                self, "Missing Album Title", "Album Title is required when using Add Album."
            )
            return None

        upc_raw = self.upc.currentText().strip()
        if upc_raw and not valid_upc_ean(upc_raw):
            self.primary_tabs.setCurrentWidget(self.album_details_tab)
            QMessageBox.warning(
                self, "Invalid UPC/EAN", "UPC/EAN must be 12 or 13 digits (or leave empty)."
            )
            return None

        genre = self.genre.currentText().strip() or None
        catalog_number = self.catalog_number.text().strip() or None
        album_art_source_path = self.album_art.text().strip() or None
        use_release_year = bool(self.use_release_year.isChecked())
        any_audio_source_path = any(
            (section.audio_file.text() or "").strip() for section in self._track_sections
        )
        if any_audio_source_path and not self.app._confirm_lossy_primary_audio_selection(
            [
                (section.audio_file.text() or "").strip()
                for section in self._track_sections
                if (section.audio_file.text() or "").strip()
            ],
            title="Save Album Media",
            action_label="Saving this album",
        ):
            return None
        media_modes = self.app._choose_track_media_storage_modes(
            audio_source_path="present" if any_audio_source_path else None,
            album_art_source_path=album_art_source_path,
            title="Save Album Media",
        )
        if media_modes is None:
            return None
        default_audio_storage_mode, album_art_storage_mode = media_modes

        active_sections = [
            section for section in self._track_sections if not section.is_effectively_blank()
        ]
        if not active_sections:
            self.primary_tabs.setCurrentWidget(self.track_workspace_tab)
            QMessageBox.warning(
                self, "No Tracks", "Add at least one track before saving the album."
            )
            return None

        payloads: list[TrackCreatePayload] = []
        reserved_compacts: set[str] = set()

        for index, section in enumerate(active_sections, start=1):
            track_title = (section.track_title.text() or "").strip()
            artist_name = section.artist_name.currentText().strip()
            if is_blank(track_title) or is_blank(artist_name):
                self._focus_track_section(section)
                QMessageBox.warning(
                    self,
                    "Missing Track Data",
                    f"{section.title()} needs both a Track Title and a Main Artist.",
                )
                return None

            raw_isrc = (section.isrc.text() or "").strip()
            iso_isrc = ""
            compact_isrc = ""
            if raw_isrc:
                iso_isrc = to_iso_isrc(raw_isrc)
                compact_isrc = to_compact_isrc(iso_isrc)
                if not compact_isrc or not is_valid_isrc_compact_or_iso(iso_isrc):
                    self._focus_track_section(section)
                    QMessageBox.warning(
                        self,
                        "Invalid ISRC",
                        f"{section.title()} has an invalid ISRC. Use CC-XXX-YY-NNNNN or leave it blank.",
                    )
                    return None
            elif self.auto_isrc_enabled:
                release_qdate = QDate.fromString(section.release_date_iso() or "", "yyyy-MM-dd")
                iso_isrc = self.app._next_generated_isrc(
                    release_date=release_qdate if release_qdate.isValid() else None,
                    use_release_year=use_release_year,
                    reserved_compacts=reserved_compacts,
                )
                compact_isrc = to_compact_isrc(iso_isrc)
                if not compact_isrc:
                    self._focus_track_section(section)
                    QMessageBox.warning(
                        self,
                        "ISRC Exhausted",
                        f"{section.title()} could not get a new ISRC. No free sequence is available right now.",
                    )
                    return None

            if compact_isrc:
                if compact_isrc in reserved_compacts or self.app.is_isrc_taken_normalized(iso_isrc):
                    self._focus_track_section(section)
                    QMessageBox.warning(
                        self,
                        "Duplicate ISRC",
                        f"{section.title()} uses an ISRC that already exists in the current album batch or profile.",
                    )
                    return None
                reserved_compacts.add(compact_isrc)

            raw_iswc = (section.iswc.text() or "").strip()
            iso_iswc = None
            if raw_iswc:
                iso_iswc = to_iso_iswc(raw_iswc)
                if not iso_iswc or not is_valid_iswc_any(iso_iswc):
                    self._focus_track_section(section)
                    QMessageBox.warning(
                        self,
                        "Invalid ISWC",
                        f"{section.title()} has an invalid ISWC. Use T-123.456.789-0 or leave it blank.",
                    )
                    return None

            payloads.append(
                TrackCreatePayload(
                    isrc=iso_isrc,
                    track_title=track_title,
                    artist_name=artist_name,
                    additional_artists=self.app._parse_additional_artists(
                        section.additional_artists.currentText()
                    ),
                    album_title=album_title,
                    release_date=section.release_date_iso(),
                    track_length_sec=section.track_length_seconds(),
                    iswc=(iso_iswc or None),
                    upc=(upc_raw or None),
                    genre=genre,
                    catalog_number=catalog_number,
                    buma_work_number=(section.buma_work_number.text().strip() or None),
                    audio_file_source_path=(section.audio_file.text().strip() or None),
                    audio_file_storage_mode=(
                        default_audio_storage_mode
                        if (section.audio_file.text() or "").strip()
                        else None
                    ),
                    album_art_source_path=album_art_source_path if index == 1 else None,
                    album_art_storage_mode=album_art_storage_mode if index == 1 else None,
                )
            )

        return payloads

    def save_album(self) -> None:
        payloads = self._build_track_payloads()
        if payloads is None:
            return

        created_track_ids: list[int] = []
        album_title = payloads[0].album_title or "Album"

        def mutation():
            nonlocal created_track_ids
            created_track_ids = []
            for payload in payloads:
                created_track_ids.append(self.app.track_service.create_track(payload))
            release_ids = self.app._sync_releases_for_tracks(created_track_ids)

            try:
                self.app._log_event(
                    "album.create",
                    "Album created",
                    album_title=album_title,
                    track_ids=created_track_ids,
                    track_count=len(created_track_ids),
                    release_ids=release_ids,
                )
                for track_id, payload in zip(created_track_ids, payloads):
                    self.app._audit(
                        "CREATE", "Track", ref_id=track_id, details=f"isrc={payload.isrc}"
                    )
                self.app._audit_commit()
            except Exception as audit_err:
                self.app.logger.warning(f"Album create audit failed: {audit_err}")

            safe_wal_checkpoint(self.app.conn, logger=self.app.logger)
            return list(created_track_ids)

        try:
            result_ids = self.app._run_snapshot_history_action(
                action_label=f"Add Album: {album_title}",
                action_type="album.create",
                entity_type="Album",
                entity_id=album_title,
                payload={
                    "album_title": album_title,
                    "track_count": len(payloads),
                },
                mutation=mutation,
            )
        except Exception as exc:
            self.app.logger.exception(f"Album create failed: {exc}")
            QMessageBox.critical(self, "Save Album", f"Could not save the album:\n{exc}")
            return

        self.created_track_ids = list(result_ids or created_track_ids)
        focus_id = self.created_track_ids[0] if self.created_track_ids else None
        self.app.refresh_table_preserve_view(focus_id=focus_id)
        self.app.populate_all_comboboxes()
        if hasattr(self.app, "statusBar"):
            self.app.statusBar().showMessage(
                f"Saved album '{album_title}' with {len(self.created_track_ids)} track{'s' if len(self.created_track_ids) != 1 else ''}.",
                5000,
            )
        self.accept()


class EditDialog(QDialog):
    """Edits one or more Track rows, including promoted standard fields."""

    BULK_MIXED_TEXT = "{Multiple values}"
    BULK_VIEW_ONLY_FIELDS = {
        "isrc",
        "iswc",
        "track_title",
        "audio_file",
        "track_length_sec",
        "buma_work_number",
    }
    SINGLE_EDIT_ALBUM_SHARED_FIELDS = {
        "artist_name": "Artist",
        "album_title": "Album Title",
        "release_date": "Release Date",
        "upc": "UPC/EAN",
        "genre": "Genre",
        "catalog_number": "Catalog#",
        "album_art": "Album Art",
    }
    BULK_MIXED_TOOLTIP = "Selected records currently have different values. Replace this field to update every selected record."

    def __init__(self, track_id: int, parent: App, batch_track_ids: list[int] | None = None):
        super().__init__(parent)
        self.parent = parent
        self.track_id = int(track_id)
        self.batch_track_ids = self._normalize_batch_track_ids(track_id, batch_track_ids)
        self._is_bulk_edit = len(self.batch_track_ids) > 1
        self._bulk_loading = True
        self._bulk_field_state: dict[str, dict[str, object]] = {}
        self._bulk_focus_targets: dict[object, str] = {}

        self._bulk_snapshots = self._load_bulk_snapshots()
        self._album_art_edit_states = self._load_album_art_edit_states()
        self.snapshot = next(
            snapshot for snapshot in self._bulk_snapshots if snapshot.track_id == self.track_id
        )
        self._build_bulk_field_states()

        self._existing_audio_display_path = self._resolve_snapshot_media_display(
            self.snapshot.audio_file_path
        )
        self._existing_album_art_display_path = self._resolve_album_art_display(self.snapshot)
        self._album_art_hint_owner_targets: list[tuple[int, str]] = []
        self._clear_audio_file = False
        self._clear_album_art = False

        self.setWindowTitle(
            f"Bulk Edit {len(self.batch_track_ids)} Entries" if self._is_bulk_edit else "Edit Entry"
        )
        self.setModal(True)
        self.resize(760, 920 if self._is_bulk_edit else 860)
        self.setMinimumSize(700, 780)
        _apply_standard_dialog_chrome(self, "editDialog")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)
        header_subtitle = (
            "Replace only the fields you want to change across the selected records. Mixed values stay untouched unless you enter a new one."
            if self._is_bulk_edit
            else "Update track details, release metadata, registration codes, and managed media from one organized editor."
        )
        _add_standard_dialog_header(
            main_layout,
            self,
            title=(
                f"Bulk Edit {len(self.batch_track_ids)} Tracks"
                if self._is_bulk_edit
                else "Edit Track"
            ),
            subtitle=header_subtitle,
            help_topic_id="edit-entry",
        )

        if self._is_bulk_edit:
            bulk_box, bulk_layout = _create_standard_section(
                self,
                "Bulk Edit Rules",
                "Only changed fields are applied to every selected record. Locked identifiers stay view-only in this editor.",
            )
            bulk_notice = QLabel(
                f"Bulk editing {len(self.batch_track_ids)} selected tracks. "
                f"Fields showing {self.BULK_MIXED_TEXT} stay unchanged unless you replace them. "
                "ISRC, ISWC, Track Title, Audio File, Track Length, and BUMA Wnr. are view-only in this window."
            )
            bulk_notice.setWordWrap(True)
            bulk_notice.setProperty("role", "supportingText")
            bulk_layout.addWidget(bulk_notice)
            main_layout.addWidget(bulk_box)

        self.editor_tabs = QTabWidget(self)
        self.editor_tabs.setObjectName("editDialogTabs")
        self.editor_tabs.setDocumentMode(True)
        self.editor_tabs.setUsesScrollButtons(False)
        main_layout.addWidget(self.editor_tabs, 1)

        def create_tab(title: str, description: str) -> QVBoxLayout:
            page = QWidget(self.editor_tabs)
            page.setProperty("role", "workspaceCanvas")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(10)

            intro = QLabel(description, page)
            intro.setWordWrap(True)
            intro.setProperty("role", "secondary")
            page_layout.addWidget(intro)

            scroll = QScrollArea(page)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setProperty("role", "workspaceCanvas")
            viewport = scroll.viewport()
            if viewport is not None:
                viewport.setProperty("role", "workspaceCanvas")

            content = QWidget(scroll)
            content.setProperty("role", "workspaceCanvas")
            content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(12)

            scroll.setWidget(content)
            page_layout.addWidget(scroll, 1)
            self.editor_tabs.addTab(page, title)
            return content_layout

        def create_section(target_layout: QVBoxLayout, title: str, description: str | None = None):
            box, box_layout = _create_standard_section(self, title, description)
            target_layout.addWidget(box)
            return box_layout

        def add_row(target_layout, label_text, widget):
            row = QVBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            lbl = QLabel(label_text)
            row.addWidget(lbl)
            row.addWidget(widget)
            target_layout.addLayout(row)

        def combo(target_layout, label, field_name, value, source_query, allow_empty=True):
            cb = FocusWheelComboBox()
            cb.setEditable(True)
            items: list[str] = []
            seen: set[str] = set()
            for row in self.parent.cursor.execute(source_query).fetchall():
                text = str(row[0] or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                items.append(text)
            display_value = self._display_value_for_field(field_name, value).strip()
            if (
                display_value
                and display_value != self.BULK_MIXED_TEXT
                and display_value not in seen
            ):
                items.append(display_value)
            if allow_empty:
                cb.addItem("")
            cb.addItems(items)
            comp = QCompleter(items)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            cb.setCompleter(comp)
            self._configure_combo_field(cb, field_name, value)
            add_row(target_layout, label, cb)
            return cb

        track_tab_layout = create_tab(
            "Track",
            "Edit the main track-facing fields here, including credits, title, and genre.",
        )
        release_tab_layout = create_tab(
            "Release",
            "Keep album grouping, release timing, and track duration together in one place.",
        )
        codes_tab_layout = create_tab(
            "Codes",
            "Manage identifiers, registration values, and catalog metadata used by exports and rights workflows.",
        )
        media_tab_layout = create_tab(
            "Media",
            "Review and replace the managed audio and artwork files linked to this track.",
        )

        core_layout = create_section(
            track_tab_layout,
            "Core Details",
            "These fields describe the selected track directly and are shown throughout the catalog.",
        )
        album_release_layout = create_section(
            release_tab_layout,
            "Album & Release",
            "Changes here can affect release synchronization and, in single-track edit mode, shared album metadata.",
        )
        identifiers_layout = create_section(
            codes_tab_layout,
            "Identifiers",
            "ISRC and ISWC remain the primary recording and work identifiers for this track.",
        )
        registration_layout = create_section(
            codes_tab_layout,
            "Registration & Catalog",
            "Product-level codes and registration values used for distribution, GS1, and collection-society workflows.",
        )
        audio_layout_section = create_section(
            media_tab_layout,
            "Managed Audio",
            "Attach or replace the stored audio file used by preview and metadata workflows.",
        )
        artwork_layout_section = create_section(
            media_tab_layout,
            "Artwork & Shared Album Media",
            "Album art can propagate to sibling tracks when you update shared album metadata.",
        )

        self.isrc_field = QLineEdit()
        self._configure_text_field(self.isrc_field, "isrc", self.snapshot.isrc, lock_in_bulk=True)
        add_row(identifiers_layout, "ISRC", self.isrc_field)

        row_isrc_btns = QHBoxLayout()
        self.btn_isrc_copy_iso = QPushButton("Copy ISO")
        self.btn_isrc_copy_compact = QPushButton("Copy compact")
        row_isrc_btns.addWidget(self.btn_isrc_copy_iso)
        row_isrc_btns.addWidget(self.btn_isrc_copy_compact)
        row_isrc_btns.addStretch(1)
        identifiers_layout.addLayout(row_isrc_btns)
        self.btn_isrc_copy_iso.clicked.connect(self._copy_isrc_iso)
        self.btn_isrc_copy_iso.setDefault(False)
        self.btn_isrc_copy_compact.clicked.connect(self._copy_isrc_compact)

        self.entry_date_field = QLineEdit()
        self._configure_text_field(
            self.entry_date_field,
            "db_entry_date",
            self.snapshot.db_entry_date or "",
            read_only=True,
            track_changes=False,
        )

        self.track_title = QLineEdit()
        self._configure_text_field(self.track_title, "track_title", self.snapshot.track_title)
        add_row(core_layout, "Track Title", self.track_title)

        self.artist_name = combo(
            core_layout,
            "Artist",
            "artist_name",
            self.snapshot.artist_name,
            "SELECT DISTINCT name FROM Artists ORDER BY name",
            allow_empty=False,
        )
        self.additional_artist = combo(
            core_layout,
            "Additional Artist(s)",
            "additional_artists",
            ", ".join(self.snapshot.additional_artists),
            "SELECT DISTINCT name FROM Artists ORDER BY name",
        )
        self.album_title = combo(
            album_release_layout,
            "Album Title",
            "album_title",
            self.snapshot.album_title or "",
            "SELECT DISTINCT title FROM Albums ORDER BY title",
        )
        self.genre = combo(
            core_layout,
            "Genre",
            "genre",
            self.snapshot.genre or "",
            "SELECT DISTINCT genre FROM Tracks WHERE genre IS NOT NULL AND genre != '' ORDER BY genre",
        )

        self.audio_file = QLineEdit()
        self._configure_text_field(
            self.audio_file,
            "audio_file",
            self._existing_audio_display_path,
            read_only=True,
        )
        audio_row = QWidget(self)
        audio_layout = QHBoxLayout(audio_row)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.setSpacing(8)
        audio_layout.addWidget(self.audio_file, 1)
        btn_audio_browse = QPushButton("Browse…")
        btn_audio_clear = QPushButton("Clear")
        btn_audio_browse.clicked.connect(
            lambda: self._choose_track_media(
                "audio_file", self.audio_file, clear_attr="_clear_audio_file"
            )
        )
        btn_audio_clear.clicked.connect(
            lambda: self._clear_track_media(self.audio_file, clear_attr="_clear_audio_file")
        )
        if self._is_bulk_edit and self._is_bulk_locked_field("audio_file"):
            btn_audio_browse.setEnabled(False)
            btn_audio_clear.setEnabled(False)
        audio_layout.addWidget(btn_audio_browse)
        audio_layout.addWidget(btn_audio_clear)
        audio_widget = QWidget(self)
        audio_widget_layout = QVBoxLayout(audio_widget)
        audio_widget_layout.setContentsMargins(0, 0, 0, 0)
        audio_widget_layout.setSpacing(6)
        audio_widget_layout.addWidget(audio_row)
        self.audio_file_warning_label = QLabel("")
        self.audio_file_warning_label.setWordWrap(True)
        self.audio_file_warning_label.setProperty("role", "supportingText")
        self.audio_file_warning_label.setVisible(False)
        audio_widget_layout.addWidget(self.audio_file_warning_label)
        self.audio_file._lossy_audio_warning_label = self.audio_file_warning_label
        self.audio_file.textChanged.connect(
            lambda _text: self.parent._refresh_line_edit_lossy_audio_warning(self.audio_file)
        )
        self.parent._refresh_line_edit_lossy_audio_warning(self.audio_file)
        add_row(audio_layout_section, "Audio File", audio_widget)

        self.album_art = QLineEdit()
        self._configure_text_field(
            self.album_art,
            "album_art",
            self._existing_album_art_display_path,
            read_only=True,
        )
        art_row = QWidget(self)
        art_layout = QHBoxLayout(art_row)
        art_layout.setContentsMargins(0, 0, 0, 0)
        art_layout.setSpacing(8)
        art_layout.addWidget(self.album_art, 1)
        self.album_art_browse_button = QPushButton("Browse…")
        self.album_art_clear_button = QPushButton("Clear")
        self.album_art_browse_button.clicked.connect(
            lambda: self._choose_track_media(
                "album_art", self.album_art, clear_attr="_clear_album_art"
            )
        )
        self.album_art_clear_button.clicked.connect(
            lambda: self._clear_track_media(self.album_art, clear_attr="_clear_album_art")
        )
        art_layout.addWidget(self.album_art_browse_button)
        art_layout.addWidget(self.album_art_clear_button)
        add_row(artwork_layout_section, "Album Art", art_row)
        hint_row = QWidget(self)
        hint_layout = QHBoxLayout(hint_row)
        hint_layout.setContentsMargins(0, 0, 0, 0)
        hint_layout.setSpacing(8)
        self.album_art_hint_label = QLabel("")
        self.album_art_hint_label.setWordWrap(True)
        self.album_art_hint_label.setProperty("role", "supportingText")
        hint_layout.addWidget(self.album_art_hint_label, 1)
        self.album_art_open_master_button = QPushButton("Open Master Record")
        self.album_art_open_master_button.setObjectName("albumArtOpenMasterButton")
        self.album_art_open_master_button.setAutoDefault(False)
        self.album_art_open_master_button.clicked.connect(self._open_album_art_owner_from_hint)
        hint_layout.addWidget(self.album_art_open_master_button, 0, Qt.AlignTop)
        artwork_layout_section.addWidget(hint_row)
        self._refresh_album_art_controls()

        self.catalog_number = combo(
            registration_layout,
            "Catalog#",
            "catalog_number",
            self.snapshot.catalog_number or "",
            """
            SELECT DISTINCT catalog_number
            FROM Tracks
            WHERE catalog_number IS NOT NULL AND catalog_number != ''
            ORDER BY catalog_number
            """,
        )

        self.buma_work_number = QLineEdit()
        self._configure_text_field(
            self.buma_work_number,
            "buma_work_number",
            self.snapshot.buma_work_number or "",
        )

        self.release_date = FocusWheelCalendarWidget()
        self.release_date.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.release_date.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        self.release_date.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        release_iso = self.snapshot.release_date or ""
        if self._is_bulk_edit and not self._bulk_field_is_mixed("release_date"):
            release_iso = str(self._bulk_field_initial("release_date") or "")
        release_qdate = QDate.fromString(release_iso, "yyyy-MM-dd")
        self.release_date.setSelectedDate(
            release_qdate if release_qdate.isValid() else QDate.currentDate()
        )
        calendar_width = max(420, self.release_date.sizeHint().width())
        calendar_height = max(320, self.release_date.sizeHint().height())
        self.release_date.setFixedSize(calendar_width, calendar_height)
        if self._is_bulk_edit:
            self.release_date.selectionChanged.connect(
                lambda: self._mark_bulk_field_modified("release_date")
            )
            self.release_date.clicked.connect(
                lambda _date: self._mark_bulk_field_modified("release_date")
            )
        release_widget = QWidget(self)
        release_layout = QVBoxLayout(release_widget)
        release_layout.setContentsMargins(0, 0, 0, 0)
        release_layout.setSpacing(6)
        release_layout.addWidget(self.release_date, 0, Qt.AlignLeft)
        release_note = self._create_bulk_note(
            "release_date",
            "Selected tracks currently use different release dates. Pick a date to replace them all.",
        )
        if release_note is not None:
            release_layout.addWidget(release_note)
        add_row(album_release_layout, "Release Date", release_widget)

        self.len_h = TwoDigitSpinBox()
        self.len_h.setRange(0, 99)
        self.len_h.setFixedWidth(60)
        self.len_m = TwoDigitSpinBox()
        self.len_m.setRange(0, 59)
        self.len_m.setFixedWidth(50)
        self.len_s = TwoDigitSpinBox()
        self.len_s.setRange(0, 59)
        self.len_s.setFixedWidth(50)
        current_length_seconds = int(self.snapshot.track_length_sec or 0)
        if self._is_bulk_edit and not self._bulk_field_is_mixed("track_length_sec"):
            current_length_seconds = int(self._bulk_field_initial("track_length_sec") or 0)
        current_length = seconds_to_hms(current_length_seconds)
        try:
            parts = current_length.split(":")
            self.len_h.setValue(int(parts[0]))
            self.len_m.setValue(int(parts[1]))
            self.len_s.setValue(int(parts[2]))
        except Exception:
            pass
        if self._is_bulk_edit:
            self.len_h.valueChanged.connect(
                lambda _value: self._mark_bulk_field_modified("track_length_sec")
            )
            self.len_m.valueChanged.connect(
                lambda _value: self._mark_bulk_field_modified("track_length_sec")
            )
            self.len_s.valueChanged.connect(
                lambda _value: self._mark_bulk_field_modified("track_length_sec")
            )
        tl_group = QFrame(self)
        tl_group.setProperty("role", "compactControlGroup")
        tl_group.setAttribute(Qt.WA_StyledBackground, True)
        tl_group.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        tl = QHBoxLayout(tl_group)
        tl.setContentsMargins(10, 8, 10, 8)
        tl.setSpacing(6)
        tl.addWidget(self.len_h)
        tl.addWidget(QLabel(":"))
        tl.addWidget(self.len_m)
        tl.addWidget(QLabel(":"))
        tl.addWidget(self.len_s)
        tlw = QWidget()
        tlw_layout = QVBoxLayout(tlw)
        tlw_layout.setContentsMargins(0, 0, 0, 0)
        tlw_layout.setSpacing(6)
        tlw_layout.addWidget(tl_group, 0, Qt.AlignLeft)
        length_note = self._create_bulk_note(
            "track_length_sec",
            "Track Length is view-only during bulk edit. Selected tracks currently use different lengths.",
        )
        if length_note is not None:
            tlw_layout.addWidget(length_note)
        elif self._is_bulk_edit and self._is_bulk_locked_field("track_length_sec"):
            locked_length_note = QLabel("Track Length is view-only during bulk edit.")
            locked_length_note.setWordWrap(True)
            tlw_layout.addWidget(locked_length_note)
        if self._is_bulk_edit and self._is_bulk_locked_field("track_length_sec"):
            self.len_h.setEnabled(False)
            self.len_m.setEnabled(False)
            self.len_s.setEnabled(False)
        add_row(album_release_layout, "Track Length (hh:mm:ss)", tlw)

        self.iswc = QLineEdit()
        self._configure_text_field(self.iswc, "iswc", self.snapshot.iswc or "", lock_in_bulk=True)
        add_row(identifiers_layout, "ISWC", self.iswc)

        row_iswc_btns = QHBoxLayout()
        self.btn_iswc_copy_iso = QPushButton("Copy ISO")
        self.btn_iswc_copy_compact = QPushButton("Copy compact")
        row_iswc_btns.addWidget(self.btn_iswc_copy_iso)
        row_iswc_btns.addWidget(self.btn_iswc_copy_compact)
        row_iswc_btns.addStretch(1)
        identifiers_layout.addLayout(row_iswc_btns)
        self.btn_iswc_copy_iso.clicked.connect(self._copy_iswc_iso)
        self.btn_iswc_copy_iso.setDefault(False)
        self.btn_iswc_copy_compact.clicked.connect(self._copy_iswc_compact)

        self.upc = combo(
            registration_layout,
            "UPC/EAN",
            "upc",
            self.snapshot.upc or "",
            """
            SELECT value
            FROM (
                SELECT upc AS value FROM Tracks WHERE upc IS NOT NULL AND upc != ''
                UNION
                SELECT upc AS value FROM Releases WHERE upc IS NOT NULL AND upc != ''
            )
            ORDER BY value
            """,
        )
        self.upc.setInsertPolicy(QComboBox.NoInsert)
        add_row(registration_layout, "BUMA Wnr.", self.buma_work_number)
        add_row(registration_layout, "Entry Date", self.entry_date_field)

        track_tab_layout.addStretch(1)
        release_tab_layout.addStretch(1)
        codes_tab_layout.addStretch(1)
        media_tab_layout.addStretch(1)

        btns = QHBoxLayout()
        gs1_btn = QPushButton("GS1 Metadata…")
        gs1_btn.setAutoDefault(False)
        gs1_btn.clicked.connect(self._open_gs1_metadata)
        if self._is_bulk_edit:
            gs1_btn.setToolTip(
                "Open GS1 metadata for the same selected tracks shown in this bulk edit window."
            )
        btns.addWidget(gs1_btn)
        btns.addStretch(1)
        save_btn = QPushButton("Apply Changes" if self._is_bulk_edit else "Save Changes")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.save_changes)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        main_layout.addLayout(btns)

        if self._is_bulk_edit:
            self.btn_isrc_copy_iso.setEnabled(False)
            self.btn_isrc_copy_compact.setEnabled(False)
            self.btn_iswc_copy_iso.setEnabled(False)
            self.btn_iswc_copy_compact.setEnabled(False)

        self._bulk_loading = False

    @staticmethod
    def _normalize_batch_track_ids(track_id: int, batch_track_ids: list[int] | None) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        candidates = [track_id]
        if batch_track_ids:
            candidates.extend(batch_track_ids)
        for candidate in candidates:
            try:
                value = int(candidate)
            except (TypeError, ValueError):
                continue
            if value <= 0 or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        if not normalized:
            normalized.append(int(track_id))
        return normalized

    def _load_bulk_snapshots(self) -> list[TrackSnapshot]:
        snapshots: list[TrackSnapshot] = []
        for candidate_id in self.batch_track_ids:
            snapshot = self.parent.track_service.fetch_track_snapshot(candidate_id)
            if snapshot is None:
                raise ValueError(f"Track {candidate_id} not found")
            snapshots.append(snapshot)
        return snapshots

    def _load_album_art_edit_states(self) -> dict[int, object]:
        track_service = getattr(self.parent, "track_service", None)
        if track_service is None:
            return {}
        return {
            snapshot.track_id: track_service.describe_album_art_edit_state(snapshot.track_id)
            for snapshot in self._bulk_snapshots
        }

    def _resolve_snapshot_media_display(self, stored_path: str | None) -> str:
        return str(self.parent.track_service.resolve_media_path(stored_path) or "")

    def _resolve_album_art_display(self, snapshot: TrackSnapshot) -> str:
        resolved = self._resolve_snapshot_media_display(snapshot.album_art_path)
        if resolved:
            return resolved
        if (
            normalize_storage_mode(snapshot.album_art_storage_mode, default=None)
            == STORAGE_MODE_DATABASE
            or snapshot.album_art_blob_b64
        ):
            filename = str(snapshot.album_art_filename or "").strip()
            if filename:
                return f"{filename} (stored in database)"
            return "Stored in database"
        return ""

    @staticmethod
    def _album_art_owner_label(state: object) -> str:
        owner_track_id = getattr(state, "owner_track_id", None)
        owner_track_title = str(getattr(state, "owner_track_title", "") or "").strip()
        if owner_track_id is None:
            return "another track"
        if owner_track_title:
            return f'Track #{int(owner_track_id)} "{owner_track_title}"'
        return f"Track #{int(owner_track_id)}"

    def _album_art_owner_targets(self) -> list[tuple[int, str]]:
        targets: list[tuple[int, str]] = []
        seen: set[int] = set()
        for state in self._album_art_edit_states.values():
            if not bool(getattr(state, "is_shared_reference", False)):
                continue
            owner_track_id = getattr(state, "owner_track_id", None)
            if owner_track_id is None:
                continue
            owner_track_id = int(owner_track_id)
            if owner_track_id in seen:
                continue
            seen.add(owner_track_id)
            targets.append((owner_track_id, self._album_art_owner_label(state)))
        return targets

    def _single_album_art_hint_text(self) -> str:
        state = self._album_art_edit_states.get(self.track_id)
        if state is None or not bool(getattr(state, "is_shared_reference", False)):
            return ""
        return (
            "This track uses shared album art managed by "
            f"{self._album_art_owner_label(state)}. "
            "Edit that record to replace the shared image."
        )

    def _bulk_album_art_hint_text(self) -> str:
        owners: list[str] = []
        seen: set[str] = set()
        for state in self._album_art_edit_states.values():
            if not bool(getattr(state, "is_shared_reference", False)):
                continue
            label = self._album_art_owner_label(state)
            if label in seen:
                continue
            seen.add(label)
            owners.append(label)
        if not owners:
            return ""
        if len(owners) == 1:
            return (
                "Some selected tracks use shared album art managed by "
                f"{owners[0]}. Edit that record to replace the shared image."
            )
        owner_list = "; ".join(owners[:4])
        if len(owners) > 4:
            owner_list += "; …"
        return (
            "Some selected tracks use shared album art managed by "
            f"{owner_list}. Edit those records to replace the shared image."
        )

    def _open_album_art_owner_track(self, owner_track_id: int) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        parent.refresh_table_preserve_view(focus_id=int(owner_track_id))
        parent.open_track_editor(int(owner_track_id), batch_track_ids=[int(owner_track_id)])

    def _open_album_art_owner_from_hint(self) -> None:
        if len(self._album_art_hint_owner_targets) == 1:
            self._open_album_art_owner_track(self._album_art_hint_owner_targets[0][0])
            return
        if not self._album_art_hint_owner_targets:
            return
        menu = QMenu(self.album_art_open_master_button)
        for owner_track_id, owner_label in self._album_art_hint_owner_targets:
            action = menu.addAction(owner_label)
            action.triggered.connect(
                lambda _checked=False, track_id=owner_track_id: self._open_album_art_owner_track(
                    track_id
                )
            )
        menu.exec(
            self.album_art_open_master_button.mapToGlobal(
                self.album_art_open_master_button.rect().bottomLeft()
            )
        )

    def _refresh_album_art_controls(self) -> None:
        browse_enabled = True
        hint_text = ""
        if self._is_bulk_edit:
            browse_enabled = all(
                bool(getattr(state, "can_replace_directly", True))
                for state in self._album_art_edit_states.values()
            )
            hint_text = self._bulk_album_art_hint_text()
        else:
            state = self._album_art_edit_states.get(self.track_id)
            browse_enabled = bool(getattr(state, "can_replace_directly", True))
            hint_text = self._single_album_art_hint_text()
        self._album_art_hint_owner_targets = self._album_art_owner_targets()
        self.album_art_browse_button.setEnabled(browse_enabled)
        self.album_art_clear_button.setEnabled(True)
        self.album_art_hint_label.setText(hint_text)
        self.album_art_hint_label.setVisible(bool(hint_text))
        has_owner_targets = bool(self._album_art_hint_owner_targets)
        self.album_art_open_master_button.setVisible(has_owner_targets)
        self.album_art_open_master_button.setEnabled(has_owner_targets)
        if len(self._album_art_hint_owner_targets) > 1:
            self.album_art_open_master_button.setText("Open Master Record…")
            self.album_art_open_master_button.setToolTip("Choose which master record to open.")
        else:
            self.album_art_open_master_button.setText("Open Master Record")
            self.album_art_open_master_button.setToolTip("")

    def _build_bulk_field_states(self) -> None:
        if not self._is_bulk_edit:
            return
        snapshots = self._bulk_snapshots
        self._set_bulk_field_state("isrc", [snapshot.isrc or "" for snapshot in snapshots])
        self._set_bulk_field_state(
            "db_entry_date", [snapshot.db_entry_date or "" for snapshot in snapshots]
        )
        self._set_bulk_field_state(
            "track_title", [snapshot.track_title or "" for snapshot in snapshots]
        )
        self._set_bulk_field_state(
            "artist_name", [snapshot.artist_name or "" for snapshot in snapshots]
        )
        self._set_bulk_field_state(
            "additional_artists",
            [tuple(snapshot.additional_artists or []) for snapshot in snapshots],
        )
        self._set_bulk_field_state(
            "album_title", [snapshot.album_title or "" for snapshot in snapshots]
        )
        self._set_bulk_field_state("genre", [snapshot.genre or "" for snapshot in snapshots])
        self._set_bulk_field_state(
            "audio_file",
            [
                self._resolve_snapshot_media_display(snapshot.audio_file_path)
                for snapshot in snapshots
            ],
        )
        self._set_bulk_field_state(
            "album_art",
            [self._resolve_album_art_display(snapshot) for snapshot in snapshots],
        )
        self._set_bulk_field_state(
            "catalog_number", [snapshot.catalog_number or "" for snapshot in snapshots]
        )
        self._set_bulk_field_state(
            "buma_work_number", [snapshot.buma_work_number or "" for snapshot in snapshots]
        )
        self._set_bulk_field_state(
            "release_date", [snapshot.release_date or "" for snapshot in snapshots]
        )
        self._set_bulk_field_state(
            "track_length_sec", [int(snapshot.track_length_sec or 0) for snapshot in snapshots]
        )
        self._set_bulk_field_state("iswc", [snapshot.iswc or "" for snapshot in snapshots])
        self._set_bulk_field_state("upc", [snapshot.upc or "" for snapshot in snapshots])

    def _set_bulk_field_state(self, field_name: str, values) -> None:
        shared_value = shared_bulk_value(values)
        self._bulk_field_state[field_name] = {
            "mixed": shared_value is MIXED_VALUE,
            "initial": None if shared_value is MIXED_VALUE else shared_value,
            "modified": False,
        }

    @staticmethod
    def _display_value(value) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return ", ".join(str(part) for part in value if str(part).strip())
        return str(value)

    def _is_bulk_locked_field(self, field_name: str) -> bool:
        return self._is_bulk_edit and field_name in self.BULK_VIEW_ONLY_FIELDS

    def _bulk_field_is_mixed(self, field_name: str) -> bool:
        return bool(self._bulk_field_state.get(field_name, {}).get("mixed"))

    def _bulk_field_initial(self, field_name: str):
        return self._bulk_field_state.get(field_name, {}).get("initial")

    def _bulk_field_modified(self, field_name: str) -> bool:
        return bool(self._bulk_field_state.get(field_name, {}).get("modified"))

    def _mark_bulk_field_modified(self, field_name: str) -> None:
        if not self._is_bulk_edit or self._bulk_loading:
            return
        state = self._bulk_field_state.get(field_name)
        if state is None:
            return
        state["modified"] = True

    def _register_bulk_focus_target(self, widget, field_name: str) -> None:
        if not self._is_bulk_edit:
            return
        self._bulk_focus_targets[widget] = field_name
        widget.installEventFilter(self)

    def _display_value_for_field(self, field_name: str, single_value) -> str:
        if not self._is_bulk_edit or field_name not in self._bulk_field_state:
            return self._display_value(single_value)
        if self._bulk_field_is_mixed(field_name):
            return self.BULK_MIXED_TEXT
        return self._display_value(self._bulk_field_initial(field_name))

    def _set_bulk_hint(self, widget, field_name: str) -> None:
        if not self._is_bulk_edit:
            return
        tips = []
        if self._is_bulk_locked_field(field_name):
            tips.append("This field is view-only during bulk edit.")
        if self._bulk_field_is_mixed(field_name):
            tips.append(self.BULK_MIXED_TOOLTIP)
        if tips:
            widget.setToolTip(" ".join(tips))

    def _configure_text_field(
        self,
        widget: QLineEdit,
        field_name: str,
        single_value,
        *,
        read_only: bool = False,
        lock_in_bulk: bool = False,
        track_changes: bool = True,
    ) -> None:
        widget.setText(self._display_value_for_field(field_name, single_value))
        widget.setReadOnly(read_only or lock_in_bulk or self._is_bulk_locked_field(field_name))
        self._set_bulk_hint(widget, field_name)
        if self._is_bulk_edit and track_changes and not lock_in_bulk:
            widget.textChanged.connect(
                lambda _text, name=field_name: self._mark_bulk_field_modified(name)
            )
            if not widget.isReadOnly():
                self._register_bulk_focus_target(widget, field_name)

    def _configure_combo_field(self, combo: QComboBox, field_name: str, single_value) -> None:
        combo.setCurrentText(self._display_value_for_field(field_name, single_value))
        self._set_bulk_hint(combo, field_name)
        if self._is_bulk_edit:
            combo.currentTextChanged.connect(
                lambda _text, name=field_name: self._mark_bulk_field_modified(name)
            )
            line_edit = combo.lineEdit()
            if line_edit is not None:
                self._set_bulk_hint(line_edit, field_name)
                self._register_bulk_focus_target(line_edit, field_name)

    def _create_bulk_note(self, field_name: str, text: str) -> QLabel | None:
        if not self._is_bulk_edit or not self._bulk_field_is_mixed(field_name):
            return None
        label = QLabel(text)
        label.setWordWrap(True)
        return label

    def eventFilter(self, source, event):
        if (
            self._is_bulk_edit
            and event.type() == QEvent.FocusIn
            and source in self._bulk_focus_targets
        ):
            field_name = self._bulk_focus_targets[source]
            if (
                self._bulk_field_is_mixed(field_name)
                and not self._bulk_field_modified(field_name)
                and hasattr(source, "text")
                and source.text() == self.BULK_MIXED_TEXT
                and hasattr(source, "selectAll")
            ):
                QTimer.singleShot(0, source.selectAll)
        return super().eventFilter(source, event)

    def _choose_track_media(self, media_key: str, line_edit: QLineEdit, *, clear_attr: str) -> None:
        path = self.parent._browse_track_media_file(media_key, parent_widget=self)
        if path:
            setattr(self, clear_attr, False)
            line_edit.setText(path)
            if media_key == "audio_file":
                self.parent._refresh_line_edit_lossy_audio_warning(line_edit)

    def _clear_track_media(self, line_edit: QLineEdit, *, clear_attr: str) -> None:
        setattr(self, clear_attr, True)
        line_edit.clear()
        self.parent._refresh_line_edit_lossy_audio_warning(line_edit)

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

    def _open_gs1_metadata(self):
        try:
            dlg = GS1MetadataDialog(
                app=self.parent,
                track_id=self.track_id,
                batch_track_ids=list(self.batch_track_ids),
                parent=self,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "GS1 Metadata", str(exc))
            return
        dlg.exec()

    def _bulk_field_should_apply(self, field_name: str, final_value) -> bool:
        if self._is_bulk_locked_field(field_name):
            return False
        return should_apply_bulk_change(
            mixed=self._bulk_field_is_mixed(field_name),
            modified=self._bulk_field_modified(field_name),
            initial_value=self._bulk_field_initial(field_name),
            final_value=final_value,
        )

    def _bulk_media_should_apply(
        self, field_name: str, final_path: str, *, clear_attr: str
    ) -> bool:
        if self._is_bulk_locked_field(field_name):
            return False
        clear_requested = bool(getattr(self, clear_attr) and not final_path)
        if not self._is_bulk_edit:
            return bool(clear_requested or final_path)
        if not self._bulk_field_modified(field_name) and not clear_requested:
            return False
        if self._bulk_field_is_mixed(field_name):
            return True
        initial_path = self._display_value(self._bulk_field_initial(field_name))
        if clear_requested:
            return True
        return (final_path or "") != initial_path

    def _single_edit_album_field_updates(
        self,
        before_snapshot: TrackSnapshot,
        *,
        artist_name: str,
        album_title: str | None,
        release_date: str | None,
        upc: str | None,
        genre: str | None,
        catalog_number: str | None,
    ) -> dict[str, object]:
        updates: dict[str, object] = {}
        if artist_name != before_snapshot.artist_name:
            updates["artist_name"] = artist_name
        if album_title != before_snapshot.album_title:
            updates["album_title"] = album_title
        if release_date != before_snapshot.release_date:
            updates["release_date"] = release_date
        if upc != before_snapshot.upc:
            updates["upc"] = upc
        if genre != before_snapshot.genre:
            updates["genre"] = genre
        if catalog_number != before_snapshot.catalog_number:
            updates["catalog_number"] = catalog_number
        return updates

    def _single_edit_album_art_changed(self, album_art_source_path: str | None) -> bool:
        clear_requested = bool(self._clear_album_art and not album_art_source_path)
        return bool(clear_requested or album_art_source_path)

    def _album_art_upload_block_message(self, track_ids: list[int]) -> str | None:
        track_service = getattr(self.parent, "track_service", None)
        if track_service is None:
            return None
        messages: list[str] = []
        seen: set[str] = set()
        for track_id in track_ids:
            message = track_service.album_art_replacement_message(track_id)
            if not message or message in seen:
                continue
            seen.add(message)
            messages.append(message)
        if not messages:
            return None
        if len(messages) == 1:
            return messages[0]
        return "Album art cannot be replaced for some selected tracks:\n- " + "\n- ".join(
            messages[:6]
        )

    def _display_album_shared_field_names(self, field_names: list[str]) -> list[str]:
        labels: list[str] = []
        for field_name in field_names:
            label = self.SINGLE_EDIT_ALBUM_SHARED_FIELDS.get(field_name)
            if label and label not in labels:
                labels.append(label)
        return labels

    @staticmethod
    def _album_art_update_group_key(payload: TrackUpdatePayload) -> tuple[str, object]:
        album_title = str(payload.album_title or "").strip()
        if album_title and album_title.casefold() != "single":
            return ("album", album_title.casefold())
        return ("track", int(payload.track_id))

    def _deduplicate_bulk_album_art_updates(
        self,
        update_payloads: list[TrackUpdatePayload],
    ) -> None:
        seen_group_keys: set[tuple[str, object]] = set()
        for payload in update_payloads:
            if not payload.album_art_source_path:
                continue
            group_key = self._album_art_update_group_key(payload)
            if group_key in seen_group_keys:
                payload.album_art_source_path = None
                payload.album_art_storage_mode = None
                continue
            seen_group_keys.add(group_key)

    def save_changes(self):
        if self._is_bulk_edit:
            self._save_bulk_changes()
            return
        self._save_single_changes()

    def _save_single_changes(self):
        new_isrc_raw = (self.isrc_field.text() or "").strip()
        new_iswc_raw = (
            self.iswc.currentText() if hasattr(self.iswc, "currentText") else self.iswc.text()
        ).strip()
        new_upc_raw = (
            self.upc.currentText() if hasattr(self.upc, "currentText") else self.upc.text()
        ).strip()
        new_genre = (
            self.genre.currentText() if hasattr(self.genre, "currentText") else self.genre.text()
        ).strip()
        new_track_title = (self.track_title.text() or "").strip()
        new_artist_name = self.artist_name.currentText().strip()
        new_album_title = self.album_title.currentText().strip() or None
        new_release_date = self.release_date.selectedDate().toString("yyyy-MM-dd")
        new_catalog_number = (
            self.catalog_number.currentText()
            if hasattr(self.catalog_number, "currentText")
            else self.catalog_number.text()
        ).strip() or None
        new_buma_work_number = self.buma_work_number.text().strip() or None
        new_additional_artist = self.parent._parse_additional_artists(
            (
                self.additional_artist.currentText()
                if hasattr(self.additional_artist, "currentText")
                else self.additional_artist.text()
            ).strip()
        )

        iso_isrc = ""
        if new_isrc_raw:
            iso_isrc = to_iso_isrc(new_isrc_raw)
            comp = to_compact_isrc(iso_isrc)
            if not comp or not is_valid_isrc_compact_or_iso(iso_isrc):
                QMessageBox.warning(
                    self, "Invalid ISRC", "ISRC must look like CCXXXYYNNNNN or CC-XXX-YY-NNNNN."
                )
                return

        iso_iswc = None
        if new_iswc_raw:
            iso_iswc = to_iso_iswc(new_iswc_raw)
            if not iso_iswc or not is_valid_iswc_any(iso_iswc):
                QMessageBox.warning(
                    self,
                    "Invalid ISWC",
                    "ISWC must be like T-123.456.789-0 or T1234567890 (checksum 0–9 or X), or leave empty.",
                )
                return

        if is_blank(self.track_title.text()) or is_blank(new_artist_name):
            QMessageBox.warning(self, "Missing data", "Track Title and Artist are required.")
            return

        if new_upc_raw and not valid_upc_ean(new_upc_raw):
            QMessageBox.warning(
                self, "Invalid UPC/EAN", "UPC/EAN must be 12 or 13 digits (or leave empty)."
            )
            return

        try:
            parent = self.parentWidget()
            if parent is None:
                QMessageBox.critical(self, "Update Error", "No parent window set.")
                return

            row_id = int(self.track_id)
            before_snapshot = parent.track_service.fetch_track_snapshot(row_id)
            if before_snapshot is None:
                QMessageBox.warning(self, "Update Error", "Could not load the selected track.")
                return

            if iso_isrc and parent.is_isrc_taken_normalized(iso_isrc, exclude_track_id=row_id):
                QMessageBox.critical(
                    self, "Duplicate ISRC", "Another record already uses this ISRC."
                )
                return

            audio_source_path = (self.audio_file.text() or "").strip()
            album_art_source_path = (self.album_art.text() or "").strip()
            if audio_source_path == self._existing_audio_display_path:
                audio_source_path = None
            if album_art_source_path == self._existing_album_art_display_path:
                album_art_source_path = None
            if audio_source_path and not parent._confirm_lossy_primary_audio_selection(
                [audio_source_path],
                title="Update Track Media",
                action_label="Saving these changes",
            ):
                return
            if album_art_source_path:
                album_art_block_message = self._album_art_upload_block_message([row_id])
                if album_art_block_message:
                    QMessageBox.warning(
                        self,
                        "Album Art Managed Elsewhere",
                        album_art_block_message,
                    )
                    return
            media_modes = parent._choose_track_media_storage_modes(
                audio_source_path=audio_source_path,
                album_art_source_path=album_art_source_path,
                title="Update Track Media",
            )
            if media_modes is None:
                return
            audio_storage_mode, album_art_storage_mode = media_modes
            source_payload = TrackUpdatePayload(
                track_id=row_id,
                isrc=iso_isrc,
                track_title=new_track_title,
                artist_name=new_artist_name,
                additional_artists=new_additional_artist,
                album_title=new_album_title,
                release_date=new_release_date,
                track_length_sec=hms_to_seconds(
                    self.len_h.value(), self.len_m.value(), self.len_s.value()
                ),
                iswc=(iso_iswc or None),
                upc=(new_upc_raw or None),
                genre=(new_genre or None),
                catalog_number=new_catalog_number,
                buma_work_number=new_buma_work_number,
                audio_file_source_path=audio_source_path,
                audio_file_storage_mode=audio_storage_mode,
                album_art_source_path=album_art_source_path,
                album_art_storage_mode=album_art_storage_mode,
                clear_audio_file=bool(self._clear_audio_file and not audio_source_path),
                clear_album_art=bool(self._clear_album_art and not album_art_source_path),
            )

            album_field_updates = self._single_edit_album_field_updates(
                before_snapshot,
                artist_name=new_artist_name,
                album_title=new_album_title,
                release_date=new_release_date,
                upc=(new_upc_raw or None),
                genre=(new_genre or None),
                catalog_number=new_catalog_number,
            )
            album_art_changed = self._single_edit_album_art_changed(album_art_source_path)
            album_group_track_ids = parent.track_service.list_album_group_track_ids(row_id)
            propagated_track_ids = [
                track_id for track_id in album_group_track_ids if track_id != row_id
            ]
            album_shared_fields_changed = list(album_field_updates.keys())
            propagated_field_labels: list[str] = []
            if album_art_changed:
                album_shared_fields_changed.append("album_art")
            propagated_mode = bool(propagated_track_ids and album_shared_fields_changed)
            needs_peer_album_metadata_update = bool(propagated_track_ids and album_field_updates)

            if propagated_mode:
                propagated_field_labels = self._display_album_shared_field_names(
                    album_shared_fields_changed
                )

                def mutation():
                    with parent.conn:
                        cur = parent.conn.cursor()
                        parent.track_service.update_track(source_payload, cursor=cur)
                        if needs_peer_album_metadata_update:
                            parent.track_service.apply_album_metadata_to_tracks(
                                propagated_track_ids,
                                field_updates=album_field_updates,
                                cursor=cur,
                            )
                        parent._sync_releases_for_tracks(
                            [row_id, *propagated_track_ids], cursor=cur
                        )

                    safe_wal_checkpoint(parent.conn, logger=parent.logger)
                    try:
                        parent._log_event(
                            "track.update",
                            "Track updated with album-level propagation",
                            track_id=row_id,
                            isrc=iso_isrc,
                            track_title=new_track_title,
                            propagated_track_ids=propagated_track_ids,
                            propagated_fields=propagated_field_labels,
                        )
                        parent._audit(
                            "UPDATE",
                            "Track",
                            ref_id=row_id,
                            details=(
                                f"isrc={iso_isrc}; "
                                f"propagated_track_ids={','.join(str(track_id) for track_id in propagated_track_ids)}; "
                                f"propagated_fields={','.join(propagated_field_labels)}"
                            ),
                        )
                        parent._audit_commit()
                    except Exception as audit_err:
                        parent.logger.warning(f"Audit failed: {audit_err}")

                parent._run_snapshot_history_action(
                    action_label=f"Update Album Metadata: {new_track_title}",
                    action_type="track.update_album_metadata",
                    entity_type="Track",
                    entity_id=row_id,
                    payload={
                        "track_id": row_id,
                        "track_title": new_track_title,
                        "propagated_track_ids": propagated_track_ids,
                        "propagated_fields": propagated_field_labels,
                    },
                    mutation=mutation,
                )
                parent.populate_all_comboboxes()
                parent.refresh_table_preserve_view(focus_id=row_id)
                self.accept()
                return

            cleanup_artist_names, cleanup_album_titles = parent._collect_catalog_cleanup_targets(
                artist_name=new_artist_name,
                additional_artists=new_additional_artist,
                album_title=new_album_title,
            )
            profile_name = parent._current_profile_name()
            action_label = (
                f"Update Album Metadata: {new_track_title}"
                if propagated_mode
                else f"Update Track: {new_track_title}"
            )
            action_type = "track.update_album_metadata" if propagated_mode else "track.update"
            history_payload = (
                {
                    "track_id": row_id,
                    "track_title": new_track_title,
                    "propagated_track_ids": propagated_track_ids,
                    "propagated_fields": propagated_field_labels,
                }
                if propagated_mode
                else {
                    "track_id": row_id,
                    "track_title": new_track_title,
                    "cleanup_artist_names": cleanup_artist_names,
                    "cleanup_album_titles": cleanup_album_titles,
                }
            )

            def _worker(bundle, ctx):
                total_steps = 3 if needs_peer_album_metadata_update else 2

                def _mutation():
                    with bundle.conn:
                        cur = bundle.conn.cursor()
                        ctx.report_progress(0, total_steps, message="Saving track changes...")
                        bundle.track_service.update_track(source_payload, cursor=cur)
                        sync_track_ids = [row_id]
                        if propagated_mode:
                            sync_track_ids = [row_id, *propagated_track_ids]
                        if needs_peer_album_metadata_update:
                            ctx.report_progress(
                                1, total_steps, message="Propagating shared album fields..."
                            )
                            bundle.track_service.apply_album_metadata_to_tracks(
                                propagated_track_ids,
                                field_updates=album_field_updates,
                                cursor=cur,
                            )
                        ctx.report_progress(
                            total_steps - 1, total_steps, message="Synchronizing release records..."
                        )
                        parent._sync_releases_for_tracks(
                            sync_track_ids,
                            cursor=cur,
                            track_service=bundle.track_service,
                            release_service=bundle.release_service,
                            profile_name=profile_name,
                        )
                    ctx.report_progress(total_steps, total_steps, message="Track update complete.")
                    return {
                        "focus_id": row_id,
                        "propagated": propagated_mode,
                        "propagated_track_ids": list(propagated_track_ids),
                        "propagated_fields": list(propagated_field_labels),
                    }

                return run_snapshot_history_action(
                    history_manager=bundle.history_manager,
                    action_label=action_label,
                    action_type=action_type,
                    entity_type="Track",
                    entity_id=row_id,
                    payload=history_payload,
                    mutation=_mutation,
                    logger=parent.logger,
                )

            def _success(result: dict[str, object]):
                try:
                    parent.conn.commit()
                except Exception:
                    pass
                parent._refresh_history_actions()
                if propagated_mode:
                    parent._log_event(
                        "track.update",
                        "Track updated with album-level propagation",
                        track_id=row_id,
                        isrc=iso_isrc,
                        track_title=new_track_title,
                        propagated_track_ids=propagated_track_ids,
                        propagated_fields=propagated_field_labels,
                    )
                    parent._audit(
                        "UPDATE",
                        "Track",
                        ref_id=row_id,
                        details=(
                            f"isrc={iso_isrc}; "
                            f"propagated_track_ids={','.join(str(track_id) for track_id in propagated_track_ids)}; "
                            f"propagated_fields={','.join(propagated_field_labels)}"
                        ),
                    )
                else:
                    parent._log_event(
                        "track.update",
                        "Track updated",
                        track_id=row_id,
                        isrc=iso_isrc,
                        track_title=new_track_title,
                    )
                    parent._audit("UPDATE", "Track", ref_id=row_id, details=f"isrc={iso_isrc}")
                parent._audit_commit()
                parent.populate_all_comboboxes()
                parent.refresh_table_preserve_view(focus_id=row_id)
                self.accept()

            parent._submit_background_bundle_task(
                title="Update Track",
                description="Saving track changes...",
                task_fn=_worker,
                kind="write",
                unique_key=f"track.update.{row_id}",
                owner=self,
                on_success=_success,
                on_error=lambda failure: parent._show_background_task_error(
                    "Update Error",
                    failure,
                    user_message="Failed to update record:",
                ),
            )

        except Exception as e:
            parent = self.parentWidget()
            if parent and hasattr(parent, "conn"):
                parent.conn.rollback()
                parent.logger.exception(f"Update failed: {e}")
            QMessageBox.critical(self, "Update Error", f"Failed to update record:\n{e}")

    def _save_bulk_changes(self):
        parent = self.parentWidget()
        if parent is None:
            QMessageBox.critical(self, "Update Error", "No parent window set.")
            return

        new_track_title = (self.track_title.text() or "").strip()
        new_artist_name = self.artist_name.currentText().strip()
        new_additional_artist = self.parent._parse_additional_artists(
            self.additional_artist.currentText().strip()
        )
        new_album_title = self.album_title.currentText().strip()
        new_genre = self.genre.currentText().strip()
        new_upc_raw = (
            self.upc.currentText() if hasattr(self.upc, "currentText") else self.upc.text()
        ).strip()
        new_catalog_number = (
            self.catalog_number.currentText()
            if hasattr(self.catalog_number, "currentText")
            else self.catalog_number.text()
        ).strip()
        new_buma_work_number = (self.buma_work_number.text() or "").strip()
        new_release_date = self.release_date.selectedDate().toString("yyyy-MM-dd")
        new_track_length_sec = hms_to_seconds(
            self.len_h.value(), self.len_m.value(), self.len_s.value()
        )
        new_audio_path = (self.audio_file.text() or "").strip()
        new_album_art_path = (self.album_art.text() or "").strip()

        apply_track_title = self._bulk_field_should_apply("track_title", new_track_title)
        apply_artist_name = self._bulk_field_should_apply("artist_name", new_artist_name)
        apply_additional_artist = self._bulk_field_should_apply(
            "additional_artists", tuple(new_additional_artist)
        )
        apply_album_title = self._bulk_field_should_apply("album_title", new_album_title)
        apply_genre = self._bulk_field_should_apply("genre", new_genre)
        apply_release_date = self._bulk_field_should_apply("release_date", new_release_date)
        apply_track_length = self._bulk_field_should_apply("track_length_sec", new_track_length_sec)
        apply_upc = self._bulk_field_should_apply("upc", new_upc_raw)
        apply_catalog_number = self._bulk_field_should_apply("catalog_number", new_catalog_number)
        apply_buma_work_number = self._bulk_field_should_apply(
            "buma_work_number", new_buma_work_number
        )
        apply_audio = self._bulk_media_should_apply(
            "audio_file", new_audio_path, clear_attr="_clear_audio_file"
        )
        apply_album_art = self._bulk_media_should_apply(
            "album_art", new_album_art_path, clear_attr="_clear_album_art"
        )

        if apply_track_title and is_blank(new_track_title):
            QMessageBox.warning(
                self, "Missing data", "Track Title cannot be blank when bulk editing."
            )
            return
        if apply_artist_name and is_blank(new_artist_name):
            QMessageBox.warning(self, "Missing data", "Artist cannot be blank when bulk editing.")
            return
        if apply_upc and new_upc_raw and not valid_upc_ean(new_upc_raw):
            QMessageBox.warning(
                self, "Invalid UPC/EAN", "UPC/EAN must be 12 or 13 digits (or leave empty)."
            )
            return
        if apply_album_art and new_album_art_path:
            album_art_block_message = self._album_art_upload_block_message(self.batch_track_ids)
            if album_art_block_message:
                QMessageBox.warning(
                    self,
                    "Album Art Managed Elsewhere",
                    album_art_block_message,
                )
                return

        changed_fields = []
        if apply_track_title:
            changed_fields.append("Track Title")
        if apply_artist_name:
            changed_fields.append("Artist")
        if apply_additional_artist:
            changed_fields.append("Additional Artist(s)")
        if apply_album_title:
            changed_fields.append("Album Title")
        if apply_genre:
            changed_fields.append("Genre")
        if apply_release_date:
            changed_fields.append("Release Date")
        if apply_track_length:
            changed_fields.append("Track Length")
        if apply_upc:
            changed_fields.append("UPC/EAN")
        if apply_catalog_number:
            changed_fields.append("Catalog#")
        if apply_buma_work_number:
            changed_fields.append("BUMA Wnr.")
        if apply_audio:
            changed_fields.append("Audio File")
        if apply_album_art:
            changed_fields.append("Album Art")

        if not changed_fields:
            QMessageBox.information(self, "Bulk Edit", "No editable fields were changed.")
            return

        media_modes = parent._choose_track_media_storage_modes(
            audio_source_path=(
                (new_audio_path or None) if apply_audio and not self._clear_audio_file else None
            ),
            album_art_source_path=(
                (new_album_art_path or None)
                if apply_album_art and not self._clear_album_art
                else None
            ),
            title="Bulk Update Media",
        )
        if media_modes is None:
            return
        bulk_audio_storage_mode, bulk_album_art_storage_mode = media_modes

        profile_name = parent._current_profile_name()
        update_payloads = [
            TrackUpdatePayload(
                track_id=snapshot.track_id,
                isrc=snapshot.isrc,
                track_title=new_track_title if apply_track_title else snapshot.track_title,
                artist_name=new_artist_name if apply_artist_name else snapshot.artist_name,
                additional_artists=(
                    new_additional_artist
                    if apply_additional_artist
                    else list(snapshot.additional_artists)
                ),
                album_title=(
                    (new_album_title or None) if apply_album_title else snapshot.album_title
                ),
                release_date=new_release_date if apply_release_date else snapshot.release_date,
                track_length_sec=(
                    new_track_length_sec
                    if apply_track_length
                    else int(snapshot.track_length_sec or 0)
                ),
                iswc=snapshot.iswc,
                upc=(new_upc_raw or None) if apply_upc else snapshot.upc,
                genre=(new_genre or None) if apply_genre else snapshot.genre,
                catalog_number=(
                    (new_catalog_number or None)
                    if apply_catalog_number
                    else snapshot.catalog_number
                ),
                buma_work_number=(
                    (new_buma_work_number or None)
                    if apply_buma_work_number
                    else snapshot.buma_work_number
                ),
                audio_file_source_path=(
                    (new_audio_path or None) if apply_audio and not self._clear_audio_file else None
                ),
                audio_file_storage_mode=(
                    bulk_audio_storage_mode
                    if apply_audio and not self._clear_audio_file and new_audio_path
                    else None
                ),
                album_art_source_path=(
                    (new_album_art_path or None)
                    if apply_album_art and not self._clear_album_art
                    else None
                ),
                album_art_storage_mode=(
                    bulk_album_art_storage_mode
                    if apply_album_art and not self._clear_album_art and new_album_art_path
                    else None
                ),
                clear_audio_file=bool(
                    apply_audio and self._clear_audio_file and not new_audio_path
                ),
                clear_album_art=bool(
                    apply_album_art and self._clear_album_art and not new_album_art_path
                ),
            )
            for snapshot in self._bulk_snapshots
        ]
        self._deduplicate_bulk_album_art_updates(update_payloads)

        def _worker(bundle, ctx):
            total = max(1, len(update_payloads))

            def _mutation():
                with bundle.conn:
                    cur = bundle.conn.cursor()
                    for index, payload in enumerate(update_payloads, start=1):
                        ctx.report_progress(
                            value=index - 1,
                            maximum=total + 1,
                            message=f"Updating track {index} of {total}...",
                        )
                        bundle.track_service.update_track(payload, cursor=cur)
                    ctx.report_progress(
                        value=total,
                        maximum=total + 1,
                        message="Synchronizing release records...",
                    )
                    parent._sync_releases_for_tracks(
                        self.batch_track_ids,
                        cursor=cur,
                        track_service=bundle.track_service,
                        release_service=bundle.release_service,
                        profile_name=profile_name,
                    )
                ctx.report_progress(total + 1, total + 1, message="Bulk update complete.")
                return {"focus_id": self.batch_track_ids[0] if self.batch_track_ids else None}

            return run_snapshot_history_action(
                history_manager=bundle.history_manager,
                action_label=f"Bulk Edit Tracks ({len(self.batch_track_ids)})",
                action_type="track.bulk_update",
                entity_type="Track",
                entity_id="batch",
                payload={"track_ids": self.batch_track_ids, "fields": changed_fields},
                mutation=_mutation,
                logger=parent.logger,
            )

        def _success(result: dict[str, object]):
            try:
                parent.conn.commit()
            except Exception:
                pass
            parent._refresh_history_actions()
            parent._log_event(
                "track.bulk_update",
                "Bulk updated tracks",
                track_ids=self.batch_track_ids,
                changed_fields=changed_fields,
            )
            parent._audit(
                "UPDATE",
                "Track",
                ref_id="batch",
                details=(
                    f"track_ids={','.join(str(track_id) for track_id in self.batch_track_ids)}; "
                    f"fields={','.join(changed_fields)}"
                ),
            )
            parent._audit_commit()
            parent.populate_all_comboboxes()
            parent.refresh_table_preserve_view(focus_id=result.get("focus_id"))
            self.accept()

        try:
            parent._submit_background_bundle_task(
                title="Bulk Edit",
                description="Applying bulk changes to the selected tracks...",
                task_fn=_worker,
                kind="write",
                unique_key=f"track.bulk_update.{','.join(str(track_id) for track_id in self.batch_track_ids)}",
                owner=self,
                on_success=_success,
                on_error=lambda failure: parent._show_background_task_error(
                    "Update Error",
                    failure,
                    user_message="Failed to update selected records:",
                ),
            )
        except Exception as e:
            if hasattr(parent, "conn"):
                parent.conn.rollback()
                parent.logger.exception(f"Bulk update failed: {e}")
            QMessageBox.critical(self, "Update Error", f"Failed to update selected records:\n{e}")


class _AudioPreviewDialog(QDialog):
    def __init__(self, parent, file_path: str, title: str):
        super().__init__(parent)
        self._tmp_path = file_path
        self.setWindowTitle(f"Audio Preview — {title}")
        self.setMinimumSize(760, 420)
        _apply_standard_dialog_chrome(self, "audioPreviewDialog")

        if platform.system().lower() == "darwin":
            os.environ.setdefault(
                "PATH", "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")
            )
        elif platform.system().lower() == "windows":
            extra = [
                r"C:\Program Files\ffmpeg\bin",
                r"C:\ffmpeg\bin",
                r"C:\ProgramData\chocolatey\bin",  # choco install ffmpeg
                os.path.expandvars(r"%USERPROFILE%\scoop\shims"),  # scoop install ffmpeg
            ]
            os.environ["PATH"] = ";".join([*extra, os.environ.get("PATH", "")])

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(14)
        _add_standard_dialog_header(
            v,
            self,
            title="Audio Preview",
            subtitle=f"Listen back to the stored audio media for {title} and inspect its waveform when available.",
            help_topic_id="media-preview",
        )

        waveform_box, waveform_layout = _create_standard_section(
            self,
            "Waveform Preview",
            "The waveform is generated from the stored audio file when supported by the current runtime.",
        )

        # --- waveform ---
        self.wave = WaveformWidget(self)
        waveform_layout.addWidget(self.wave)
        v.addWidget(waveform_box)

        # transport row
        playback_box, playback_layout = _create_standard_section(
            self,
            "Playback Controls",
            "Use the transport buttons or the keyboard shortcuts to play, pause, stop, and scrub through the preview.",
        )
        h = QHBoxLayout()
        h.setSpacing(8)
        btn_play = QPushButton("Play")
        btn_pause = QPushButton("Pause")
        btn_stop = QPushButton("Stop")
        h.addWidget(btn_play)
        h.addWidget(btn_pause)
        h.addWidget(btn_stop)
        h.addStretch(1)
        playback_layout.addLayout(h)

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
            lambda st: (
                self._anim_timer.start()
                if st == QMediaPlayer.PlayingState
                else self._anim_timer.stop()
            )
        )

        # slider + time
        self._slider = FocusWheelSlider(Qt.Horizontal)
        self._label_time = QLabel("0:00 / 0:00")
        self._label_time.setProperty("role", "statusText")
        playback_layout.addWidget(self._slider)
        playback_layout.addWidget(self._label_time)
        v.addWidget(playback_box)

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
            waveform_box.setTitle("Waveform Preview Unavailable")
            waveform_layout.itemAt(0).widget().setText(
                "This file can still be played back, but a waveform preview could not be generated in the current environment."
            )
            self.resize(760, 380)
        else:
            self._resize_timer = QTimer(self)
            self._resize_timer.setSingleShot(True)
            self._resize_timer.setInterval(50)
            self._resize_timer.timeout.connect(self._reload_peaks_for_current_width)
            self.resize(840, 520)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        v.addLayout(button_row)

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
            e.accept()
            return

        elif e.key() == Qt.Key_Right:
            # Scrub forward
            new_pos = min(self._player.duration(), self._player.position() + STEP_MS)
            self._player.setPosition(new_pos)
            e.accept()
            return

        elif e.key() == Qt.Key_Left:
            # Scrub backward
            new_pos = max(0, self._player.position() - STEP_MS)
            self._player.setPosition(new_pos)
            e.accept()
            return

        elif e.key() == Qt.Key_Escape:
            self.close()
            e.accept()
            return

        super().keyPressEvent(e)


# ==== Licenses: helpers & actions ====
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
    if self.license_service is None:
        QMessageBox.warning(self, "License Browser", "Open a profile first.")
        return
    dock = self._ensure_license_browser_dock()
    panel = dock.show_panel()
    panel.set_track_filter_id(track_filter_id)
    self.licenses_browser_dialog = panel


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
      else fallback to QtMultimedia's decoder, then `audioread` as a last resort.
    Returns: list[(lo, hi)] in [-1.0, 1.0].
    """
    import os, struct, shutil, subprocess

    width_px = max(1, int(width_px))
    buckets = width_px * 4  # ~4 samples/bucket for smooth lines

    def _clamp_peak(value: float) -> float:
        if value < -1.0:
            return -1.0
        if value > 1.0:
            return 1.0
        return value

    def _append_pending_peak(peaks, lo: float, hi: float) -> None:
        peaks.append((_clamp_peak(lo), _clamp_peak(hi)))

    def _load_peaks_via_qt_decoder():
        decoder = QAudioDecoder()
        if not decoder.isSupported():
            return None

        state = {
            "peaks": [],
            "sample_rate": 44100,
            "target_step": None,
            "need": None,
            "lo": 1.0,
            "hi": -1.0,
            "had_buffer": False,
            "timed_out": False,
            "decode_error": None,
        }
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)

        def _sample_value(raw: bytes, offset: int, sample_format) -> float | None:
            if sample_format == QAudioFormat.SampleFormat.UInt8:
                return (raw[offset] - 128.0) / 128.0
            if sample_format == QAudioFormat.SampleFormat.Int16:
                return struct.unpack_from("<h", raw, offset)[0] / 32768.0
            if sample_format == QAudioFormat.SampleFormat.Int32:
                return struct.unpack_from("<i", raw, offset)[0] / 2147483648.0
            if sample_format == QAudioFormat.SampleFormat.Float:
                return _clamp_peak(struct.unpack_from("<f", raw, offset)[0])
            return None

        def _finish_pending_peak() -> None:
            if state["lo"] <= state["hi"]:
                _append_pending_peak(state["peaks"], state["lo"], state["hi"])
                state["lo"], state["hi"] = 1.0, -1.0

        def _on_buffer_ready() -> None:
            buf = decoder.read()
            if not buf.isValid():
                return

            fmt = buf.format()
            frame_bytes = fmt.bytesPerFrame()
            if frame_bytes <= 0:
                bytes_per_sample = fmt.bytesPerSample()
                channels = max(1, fmt.channelCount())
                frame_bytes = bytes_per_sample * channels
            if frame_bytes <= 0:
                return

            sample_format = fmt.sampleFormat()
            if sample_format not in (
                QAudioFormat.SampleFormat.UInt8,
                QAudioFormat.SampleFormat.Int16,
                QAudioFormat.SampleFormat.Int32,
                QAudioFormat.SampleFormat.Float,
            ):
                return

            if state["target_step"] is None:
                sample_rate = fmt.sampleRate() or 44100
                duration_ms = decoder.duration()
                total_samples = (
                    int((sample_rate * duration_ms) / 1000)
                    if duration_ms and duration_ms > 0
                    else None
                )
                state["sample_rate"] = sample_rate
                state["target_step"] = max(
                    1, (total_samples // buckets) if total_samples else (sample_rate // 100)
                )
                state["need"] = state["target_step"]

            raw = bytes(buf.data())
            frame_count = len(raw) // frame_bytes
            if frame_count <= 0:
                return

            state["had_buffer"] = True
            for frame_index in range(frame_count):
                offset = frame_index * frame_bytes
                value = _sample_value(raw, offset, sample_format)
                if value is None:
                    continue
                if value < state["lo"]:
                    state["lo"] = value
                if value > state["hi"]:
                    state["hi"] = value
                state["need"] -= 1
                if state["need"] == 0:
                    _finish_pending_peak()
                    state["need"] = state["target_step"]

        def _on_finished() -> None:
            loop.quit()

        def _on_error(*_args) -> None:
            state["decode_error"] = decoder.errorString() or "QtMultimedia decode failed"
            loop.quit()

        def _on_timeout() -> None:
            state["timed_out"] = True
            try:
                decoder.stop()
            finally:
                loop.quit()

        decoder.bufferReady.connect(_on_buffer_ready)
        decoder.finished.connect(_on_finished)
        decoder.error.connect(_on_error)
        timeout.timeout.connect(_on_timeout)

        decoder.setSource(QUrl.fromLocalFile(os.fspath(path)))
        decoder.start()
        timeout.start(5000)
        loop.exec()
        timeout.stop()

        _finish_pending_peak()
        if state["peaks"]:
            return state["peaks"]

        if state["had_buffer"]:
            return [(-0.0, 0.0)]

        if state["decode_error"] or state["timed_out"]:
            return None

        return None

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
                    if lo < -1.0:
                        lo = -1.0
                    if hi > 1.0:
                        hi = 1.0
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
                out = (
                    subprocess.check_output(
                        [
                            ffprobe,
                            "-v",
                            "error",
                            "-show_entries",
                            "format=duration",
                            "-of",
                            "default=nw=1:nk=1",
                            os.fspath(path),
                        ],
                        stderr=subprocess.STDOUT,
                    )
                    .decode("utf-8", "replace")
                    .strip()
                )
                if out:
                    d = float(out)
                    if d > 0:
                        total_samples = int(sr * d)
            except Exception:
                total_samples = None

        target_step = max(
            1, (total_samples // buckets) if total_samples else (sr // 100)
        )  # ~10 ms if unknown

        try:
            p = subprocess.Popen(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-nostdin",
                    "-vn",
                    "-i",
                    os.fspath(path),
                    "-f",
                    "s16le",
                    "-acodec",
                    "pcm_s16le",
                    "-ac",
                    "1",
                    "-ar",
                    str(sr),
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
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
                    data = bytes(
                        buf[off_samples * 2 : off_samples * 2 + data_len]
                    )  # copy; safe to resize buf
                    for i in range(0, len(data), 2):
                        v = _st.unpack_from("<h", data, i)[0] / fs
                        if v < lo:
                            lo = v
                        if v > hi:
                            hi = v
                    need -= take
                    off_samples += take
                    n_samples -= take

                    if need == 0:
                        peaks.append((max(-1.0, lo), min(1.0, hi)))
                        lo, hi = +1.0, -1.0
                        need = target_step

                # drop consumed bytes
                del buf[: off_samples * 2]

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

    # --- Generic path B: QtMultimedia decoder fallback -----------------------
    try:
        peaks = _load_peaks_via_qt_decoder()
        if peaks:
            return peaks
    except Exception:
        pass

    # --- Generic path C: audioread fallback (pip install audioread) ----------
    # audioread 3.0.1 still imports stdlib `aifc` via rawread, which breaks on
    # Python 3.13. Keep it only as a legacy fallback behind the Qt path.
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
            target_step = max(
                1, (total_samples // buckets) if total_samples else (sr // 100)
            )  # ~10 ms if unknown

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
                    data = bytes(
                        buf[off_frames * frame_bytes : off_frames * frame_bytes + data_len]
                    )  # copy
                    # pick channel 0 only → cheap mono
                    for i in range(0, len(data), frame_bytes):
                        v = _st.unpack_from("<h", data, i)[0] / fs
                        if v < lo:
                            lo = v
                        if v > hi:
                            hi = v
                    need -= take
                    off_frames += take
                    frames -= take
                    if need == 0:
                        peaks.append((max(-1.0, lo), min(1.0, hi)))
                        lo, hi = +1.0, -1.0
                        need = target_step

                del buf[: off_frames * frame_bytes]

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
    return run_desktop_application(
        argv=sys.argv,
        init_settings=init_settings,
        install_qt_message_filter=_install_qt_message_filter,
        enforce_single_instance=enforce_single_instance,
        window_factory=App,
    )


if __name__ == "__main__":
    sys.exit(main())

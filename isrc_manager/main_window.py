# ------------------------------------------------------------
# ruff: noqa: F401,I001
# Created by M. van de Kleut
# 22-aug-2025
#
# License:
# This software is provided "as is", without warranty of any kind.
# Free to use, copy, and distribute for any purpose, provided that
# original credits are retained. Not for resale.
# ------------------------------------------------------------

import hashlib
import json
import logging
import math
import mimetypes
import os
import platform
import random
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import monotonic

from PySide6.QtCore import (
    QByteArray,
    QCoreApplication,
    QDate,
    QEvent,
    QEventLoop,
    QItemSelectionModel,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QRegularExpression,
    QSettings,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    QtMsgType,
    QUrl,
    Signal,
    qInstallMessageHandler,
)
from PySide6.QtCore import (
    QStandardPaths as QStandardPaths,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QShortcut,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtMultimedia import (
    QAudioDecoder,
    QAudioFormat,
    QAudioOutput,
    QMediaPlayer,
    QSoundEffect,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCalendarWidget,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPinchGesture,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStatusBar,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from isrc_manager.app_bootstrap import run_desktop_application
from isrc_manager.app_dialogs import (
    AboutDialog,
    ActionRibbonDialog,
    ApplicationLogDialog,
    ApplicationStorageAdminDialog,
    CustomColumnsDialog,
    DiagnosticsDialog,
    HelpContentsDialog,
    MasterTransferExportDialog,
    ReleaseNotesDialog,
)
from isrc_manager.app_logging import JsonLogFormatter as _JsonLogFormatterTarget
from isrc_manager.application_settings_dialog import ApplicationSettingsDialog
from isrc_manager.app_services import (
    configure_foreground_exchange_services,
    initialize_foreground_services,
)
from isrc_manager import app_sound_controller
from isrc_manager import action_ribbon, isrc_registry_controller, main_window_layout
from isrc_manager.app_prompts import (
    get_name_from_editable_choice_dialog as _get_name_from_editable_choice_dialog,
    prompt_storage_mode_choice as _prompt_storage_mode_choice,
    storage_mode_choice_text as _storage_mode_choice_text_target,
)
from isrc_manager.app_sounds import (
    APP_SOUND_DEFAULTS,
    APP_SOUND_FILENAMES,
    APP_SOUND_IDS,
    APP_SOUND_NOTICE,
    APP_SOUND_SETTINGS_KEYS,
    APP_SOUND_SPECS,
    APP_SOUND_STARTUP,
    APP_SOUND_WARNING,
    coerce_sound_bool,
    normalize_app_sound_settings,
)
from isrc_manager.assets import AssetService
from isrc_manager.assets import controller as asset_controller
from isrc_manager.assets.dialogs import AssetBrowserPanel
from isrc_manager.authenticity import (
    AUTHENTICITY_FEATURE_AVAILABLE,
    PROVENANCE_ONLY_SUFFIXES,
    VERIFICATION_INPUT_SUFFIXES,
    AudioAuthenticityService,
    AudioWatermarkService,
    AuthenticityExportPreviewDialog,
    AuthenticityKeysDialog,
    AuthenticityKeyService,
    AuthenticityManifestService,
    AuthenticityVerificationDialog,
    authenticity_unavailable_message,
)
from isrc_manager.authenticity import controller as authenticity_controller
from isrc_manager.blob_icons import (
    BlobIconDialog,
    BlobIconEditorWidget,
    BlobIconSettingsService,
    default_blob_icon_settings,
    describe_blob_icon_spec,
    finalize_blob_icon_spec,
    icon_from_blob_icon_spec,
    normalize_blob_icon_settings,
    normalize_blob_icon_spec,
)
from isrc_manager.catalog_table import (
    CATALOG_ZOOM_DEFAULT_PERCENT as CATALOG_ZOOM_DEFAULT_PERCENT,
)
from isrc_manager.catalog_table import context_menu as catalog_context_menu
from isrc_manager.catalog_table import media_routing as catalog_media_routing
from isrc_manager.catalog_table import workflow as catalog_workflow
from isrc_manager.custom_fields import controller as custom_fields_controller
from isrc_manager.catalog_managers import (
    CatalogManagersPanel,
    DiagnosticsCatalogCleanupPanel,
    _CatalogAlbumsPane,
    _CatalogArtistsPane,
    _CatalogManagerPaneBase,
)
from isrc_manager.catalog_table import (
    CATALOG_ZOOM_LAYOUT_KEY,
    CATALOG_ZOOM_MAX_PERCENT,
    CATALOG_ZOOM_MIN_PERCENT,
    CATALOG_ZOOM_STEP_PERCENT,
    CatalogCellValue,
    CatalogColumnSpec,
    CatalogFilterProxyModel,
    CatalogHeaderStateManager,
    CatalogRowSnapshot,
    CatalogSnapshot,
    CatalogTableController,
    CatalogTableModel,
    CatalogZoomController,
    ColumnKeyRole,
    RawValueRole,
)
from isrc_manager.catalog_workspace import (
    CatalogWorkspaceDock,
    ensure_catalog_workspace_dock,
    refresh_catalog_workspace_docks,
)
from isrc_manager.code_registry import CatalogIdentifierField, CodeRegistryWorkspacePanel
from isrc_manager.constants import (
    BLOB_AUDIO_EXTS,
    BLOB_IMAGE_EXTS,
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
from isrc_manager.contract_templates import controller as contract_template_controller
from isrc_manager.contract_templates.dialogs import ContractTemplateWorkspacePanel
from isrc_manager.contracts import ContractPayload, ContractService
from isrc_manager.contracts import controller as contract_controller
from isrc_manager.contracts.dialogs import ContractBrowserPanel
from isrc_manager.conversion import ConversionService, ConversionTemplateStoreService
from isrc_manager.conversion.dialogs import ConversionDialog
from isrc_manager.diagnostics_progress import DiagnosticsProgressTracker
from isrc_manager.diagnostics import controller as diagnostics_controller
from isrc_manager.diagnostics import report as diagnostics_report
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
from isrc_manager.draggable_label import DraggableLabel
from isrc_manager.exchange.dialogs import ExchangeImportDialog
from isrc_manager.exchange import catalog_xml_controller
from isrc_manager.exchange import controller as exchange_controller
from isrc_manager.exchange import master_transfer_controller
from isrc_manager.exchange.master_transfer import MasterTransferService
from isrc_manager.exchange import repair_queue_controller
from isrc_manager.exchange import repertoire_controller
from isrc_manager.exchange.models import (
    ExchangeImportOptions,
    ExchangeImportReport,
    ExchangeInspection,
)
from isrc_manager.exchange.repair_dialogs import (
    TrackImportRepairEntryDialog,
    TrackImportRepairQueueDialog,
)
from isrc_manager.exchange.repertoire_service import (
    RepertoireExchangeService,
    RepertoireImportInspection,
)
from isrc_manager.exchange.service import ExchangeService
from isrc_manager.external_launch import open_external_path
from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
    ManagedFileStorage,
    bytes_from_blob,
    infer_storage_mode,
    normalize_storage_mode,
    resolve_directory_export_target,
    resolve_file_export_target,
    sanitize_export_basename,
)
from isrc_manager.forensics import (
    ForensicExportCoordinator,
    ForensicExportDialog,
    ForensicExportRequest,
    ForensicExportResult,
    ForensicInspectionDialog,
    ForensicInspectionReport,
    ForensicWatermarkService,
)
from isrc_manager.forensics import controller as forensic_controller
from isrc_manager.gs1_dialog import GS1MetadataDialog
from isrc_manager.help_content import render_help_html
from isrc_manager.history import (
    HistoryCleanupBlockedError,
    HistoryManager,
    HistoryStorageCleanupService,
    SessionHistoryManager,
)
from isrc_manager import history_retention_controller
from isrc_manager.history.dialogs import HistoryCleanupDialog, HistoryDialog
from isrc_manager.import_review_dialog import ImportReviewDialog
from isrc_manager.isrc_registry import ApplicationISRCRegistryService, ISRCRegistryConflict
from isrc_manager.main_window_shell import build_main_window_shell
from isrc_manager.media import (
    AudioConversionService,
    conversion_controller as audio_conversion_controller,
    export_controller as media_export_controller,
    player_controller as media_player_controller,
    waveform_cache_controller,
)
from isrc_manager.media.audio_visualization import (
    OscilloscopeWidget,
    SpectrumGraphWidget,
    StereoPeakMeterWidget,
    load_audio_harmonic_frames,
    load_audio_peak_meter_frames,
    load_audio_spectrum_frames,
)
from isrc_manager.media.bookmarks import (
    AudioBookmark,
    add_audio_bookmark,
    delete_audio_bookmark,
    delete_audio_bookmarks_for_track,
    load_audio_bookmarks,
)
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
from isrc_manager.media.equalizer import (
    EqualizerDialog,
    equalizer_is_enabled,
    equalizer_response_for_bins,
    load_equalizer_settings,
    normalize_equalizer_settings,
    save_equalizer_settings,
)
from isrc_manager.media.equalizer_player import LiveEqualizerPlayer, _decode_audio_file
from isrc_manager.media.preview_dialogs import (
    _AudioPreviewDialog,
    _AudioPreviewPreloadBridge,
    _AudioPreviewPreloadCancelled,
    _AudioPreviewPreparedMedia,
    _AudioPreviewPreloadResult,
    _AudioPreviewPreloadTask,
    _AudioPreviewTrackLoadResult,
    _AudioPreviewTrackLoadTask,
    _HiDpiArtworkLabel,
    _ImagePreviewDialog,
    _audio_preview_artwork_payload_for_snapshot,
    _audio_preview_detect_mime_from_bytes,
    _audio_preview_fetch_source_for_preload,
    _audio_preview_state_for_preload_task,
    _audio_preview_suffix_for_mime,
    _audio_preview_track_queue_items_for_service,
    _audio_preview_write_preload_temp_file,
    _build_audio_preview_preload,
    _build_audio_preview_track_load,
)
from isrc_manager.media.waveform import WaveformWidget, load_wav_peaks
from isrc_manager.media.waveform_cache import AudioWaveformCacheService
from isrc_manager.media.waveform_cache_worker import AudioWaveformCacheWorker
from isrc_manager import profile_session
from isrc_manager.packaged_smoke import (
    PACKAGED_SMOKE_TEST_ARGUMENT,
    run_packaged_smoke_test,
)
from isrc_manager.parties import controller as party_controller
from isrc_manager.parties import (
    PartyExchangeInspection,
    PartyExchangeService,
    PartyImportOptions,
    PartyImportReport,
    PartyPayload,
    PartyRecord,
    PartyService,
    artist_choice_label,
    artist_primary_label,
    party_authority_notifier,
)
from isrc_manager.parties.dialogs import (
    OwnerBootstrapDialog,
    PartyImportDialog,
    PartyManagerPanel,
)
from isrc_manager.paths import (
    RES_DIR,
    configure_qt_application_identity,
    resolve_app_storage_layout,
    settings_path,
    should_ignore_persisted_last_db_path,
)
from isrc_manager.promo_codes import PromoCodeLedgerPanel, PromoCodeService
from isrc_manager.promo_codes import controller as promo_code_controller
from isrc_manager.qss_autocomplete import (
    QssCodeEditor,
    validate_qss_document,
)
from isrc_manager.qss_reference import (
    QssReferenceEntry,
    collect_qss_reference_entries,
)
from isrc_manager.qss_reference import (
    ensure_widget_object_names as _ensure_qss_widget_object_names,
)
from isrc_manager.qss_reference import (
    repolish_widget_tree as _repolish_qss_widget_tree,
)
from isrc_manager.quality.dialogs import QualityDashboardDialog
from isrc_manager.quality.models import QualityIssue
from isrc_manager.quality.service import QualityDashboardService
from isrc_manager.quality import controller as quality_controller
from isrc_manager.releases import controller as release_controller
from isrc_manager.releases import (
    ReleasePayload,
    ReleaseRecord,
    ReleaseService,
    ReleaseTrackPlacement,
)
from isrc_manager.releases.dialogs import ReleaseBrowserPanel, ReleaseEditorDialog
from isrc_manager.rights import RightsService
from isrc_manager.rights import controller as rights_controller
from isrc_manager.rights.dialogs import RightsBrowserPanel
from isrc_manager.search import GlobalSearchService, RelationshipExplorerService
from isrc_manager.search.dialogs import GlobalSearchPanel
from isrc_manager.selection_scope import TrackChoice
from isrc_manager.services import (
    ApplicationSettingsTransferService,
    CatalogAdminService,
    CatalogReadService,
    CodeRegistryService,
    ContractTemplateCatalogService,
    ContractTemplateExportService,
    ContractTemplateFormService,
    ContractTemplateService,
    CustomFieldDefinitionService,
    CustomFieldValueService,
    DatabaseMaintenanceService,
    DatabaseSchemaService,
    DatabaseSessionService,
    GS1ContractEntry,
    GS1ContractImportError,
    GS1IntegrationService,
    GS1MetadataRepository,
    GS1ProfileDefaults,
    GS1SettingsService,
    GS1TemplateAsset,
    HistoryRetentionSettings,
    LegacyPromotedFieldRepairService,
    OwnerPartySettings,
    ProfileKVService,
    ProfileStoreService,
    ProfileWorkflowService,
    RepertoireWorkflowService,
    SettingsMutationService,
    SettingsReadService,
    TrackCreatePayload,
    TrackImportRepairQueueService,
    TrackService,
    TrackSnapshot,
    TrackUpdatePayload,
    UpdatePreferenceService,
    WorkPayload,
    XMLExportService,
    XMLImportService,
)
from isrc_manager.services.bulk_edit import MIXED_VALUE, shared_bulk_value, should_apply_bulk_change
from isrc_manager.services.db_access import DatabaseWriteCoordinator, SQLiteConnectionFactory
from isrc_manager.services.gs1_mapping import (
    COMMON_CLASSIFICATION_CHOICES,
    COMMON_LANGUAGE_CHOICES,
    COMMON_MARKET_CHOICES,
    COMMON_PACKAGING_CHOICES,
)
from isrc_manager.services.import_governance import GovernedImportCoordinator
from isrc_manager.services.sqlite_utils import safe_wal_checkpoint
from isrc_manager.services.track_artist_sql import track_main_artist_join_sql
from isrc_manager.services.tracks import TRACK_RELATIONSHIP_TYPES
from isrc_manager.settings import enforce_single_instance, init_settings
from isrc_manager import settings_controller, theme_controller
from isrc_manager.starter_themes import (
    STARTER_THEME_SPECS,
    starter_theme_descriptions,
    starter_theme_library,
    starter_theme_names,
)
from isrc_manager.startup_progress import (
    StartupPhase,
    StartupProgressTracker,
    startup_phase_label,
)
from isrc_manager.startup_splash import (
    StartupFeedbackProtocol,
    create_startup_splash_controller,
)
from isrc_manager.storage_admin import ApplicationStorageAdminService
from isrc_manager.storage_migration import (
    PREFERRED_STATE_CONFLICT,
    PREFERRED_STATE_RESUMABLE_STAGE,
    PREFERRED_STATE_VALID_COMPLETE,
    StorageMigrationService,
)
from isrc_manager.storage_sizes import (
    bytes_to_megabytes_floor,
    format_budget_megabytes,
    format_storage_bytes,
)
from isrc_manager.tags import (
    TAGGED_AUDIO_EXPORT_STAGE_COUNT,
    AudioTagService,
    BulkAudioAttachService,
    TaggedAudioExportService,
    build_catalog_export_tag_data,
    merge_imported_tags,
    write_catalog_export_tags,
)
from isrc_manager.tags import metadata_controller
from isrc_manager.tags.dialogs import (
    BulkAudioAttachDialog,
    DroppedAudioImportDialog,
    TagPreviewDialog,
)
from isrc_manager.tags.models import (
    ArtworkPayload,
    AudioTagData,
    BulkAudioAttachTrackCandidate,
    DroppedAudioImportItem,
    TaggedAudioExportItem,
    TaggedAudioExportPlanItem,
)
from isrc_manager.tasks import BackgroundTaskManager, TaskFailure
from isrc_manager.tasks.app_services import BackgroundAppServiceFactory
from isrc_manager.tasks.history_helpers import run_file_history_action, run_snapshot_history_action
from isrc_manager import update_controller
from isrc_manager.tracks.album_entry_dialog import AlbumEntryDialog, _AlbumTrackSection
from isrc_manager.tracks.album_ordering_dialog import (
    AlbumTrackOrderingDialog,
    _AlbumTrackOrderingTable,
)
from isrc_manager.tracks.edit_dialog import EditDialog
from isrc_manager.theme_builder import (
    THEME_COLOR_FIELD_SPECS,
    THEME_METRIC_FIELD_SPECS,
    THEME_PAGE_SPECS,
)
from isrc_manager.theme_builder import (
    build_theme_palette as build_app_theme_palette,
)
from isrc_manager.theme_builder import (
    build_theme_style as build_app_theme_style,
)
from isrc_manager.theme_builder import (
    build_theme_stylesheet as build_app_theme_stylesheet,
)
from isrc_manager.theme_builder import (
    color_relative_luminance as theme_color_relative_luminance,
)
from isrc_manager.theme_builder import (
    contrast_ratio as theme_contrast_ratio,
)
from isrc_manager.theme_builder import (
    effective_theme_settings as build_effective_theme_settings,
)
from isrc_manager.theme_builder import (
    normalize_theme_color as normalize_app_theme_color,
)
from isrc_manager.theme_builder import (
    normalize_theme_font_family as normalize_app_theme_font_family,
)
from isrc_manager.theme_builder import (
    normalize_theme_settings as normalize_app_theme_settings,
)
from isrc_manager.theme_builder import (
    normalize_theme_string as normalize_app_theme_string,
)
from isrc_manager.theme_builder import (
    pick_contrasting_color as pick_theme_contrasting_color,
)
from isrc_manager.theme_builder import (
    shift_color as shift_theme_color,
)
from isrc_manager.theme_builder import (
    theme_setting_defaults as default_theme_settings,
)
from isrc_manager.theme_builder import (
    theme_setting_keys as app_theme_setting_keys,
)
from isrc_manager.ui_common import (
    DatePickerDialog,
    FocusWheelCalendarWidget,
    FocusWheelComboBox,
    FocusWheelFontComboBox,
    FocusWheelSlider,
    FocusWheelSpinBox,
    StorageBudgetSpinBox,
    TwoDigitSpinBox,
    _add_standard_dialog_header,
    _apply_compact_dialog_control_heights,
    _apply_standard_dialog_chrome,
    _apply_standard_widget_chrome,
    _compose_widget_stylesheet,
    _configure_standard_form_layout,
    _create_action_button_grid,
    _create_round_help_button,
    _create_scrollable_dialog_content,
    _create_standard_section,
    _prompt_compact_choice_dialog,
)
from isrc_manager.update_checker import (
    DEFAULT_RELEASE_NOTES_TIMEOUT_SECONDS,
    UpdateChecker,
    UpdateCheckResult,
    UpdateCheckStatus,
    fetch_release_notes_text,
)
from isrc_manager.update_handoff import (
    cleanup_legacy_update_backups_for_version,
    cleanup_ready_update_backup,
    cleanup_update_backup_siblings,
    cleanup_update_cache_artifacts,
    mark_update_backup_ready_for_deletion,
)
from isrc_manager.update_installer import (
    HELPER_MODE_ARGUMENT,
    UpdateInstallerError,
    UpdateInstallPlan,
    detect_platform_key,
    download_update_asset,
    launch_update_helper,
    prepare_update_install_plan,
    resolve_installed_target_path,
    select_platform_asset,
    update_workspace_root,
    validate_install_target_is_replaceable,
)
from isrc_manager.version import current_app_version
from isrc_manager.works import controller as work_controller
from isrc_manager.works import WorkService
from isrc_manager.works.dialogs import (
    WorkBrowserPanel,
    WorkEditorDialog,
)
from isrc_manager.workspace_debug import (
    summarize_catalog_workspace_dock,
    summarize_panel_layout_snapshot,
    summarize_panel_layout_state,
    workspace_debug_enabled,
    workspace_debug_log,
)

_QT_MESSAGE_BOX_CLASS = QMessageBox

_RESERVED_TRACE_LOG_KEYS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
    "event",
}

_PREVIOUS_QT_MESSAGE_HANDLER = None


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
# Consolidated Application Settings Dialog
# =============================================================================


class App(QMainWindow):
    startupReady = Signal()
    BASE_HEADERS = list(DEFAULT_BASE_HEADERS)
    TOP_CHROME_DOCK_GAP = 5
    STARTUP_SOUND_ENABLED_SETTINGS_KEY = APP_SOUND_SETTINGS_KEYS[APP_SOUND_STARTUP]
    STARTUP_SOUND_FILENAME = APP_SOUND_FILENAMES[APP_SOUND_STARTUP]
    DEFAULT_STARTUP_SOUND_ENABLED = APP_SOUND_DEFAULTS[APP_SOUND_STARTUP]
    STARTUP_SOUND_DELAY_MS = 250
    APP_SOUND_VOLUMES = {
        APP_SOUND_STARTUP: 0.45,
        APP_SOUND_NOTICE: 0.42,
        APP_SOUND_WARNING: 0.50,
    }
    APP_SOUND_THROTTLE_MS = {
        APP_SOUND_NOTICE: 1500,
        APP_SOUND_WARNING: 1500,
    }
    NOTICE_MESSAGE_KEYWORDS = (
        "saved",
        "export",
        "exported",
        "imported",
        "updated",
        "created",
        "deleted",
        "done",
        "finished",
        "completed",
        "success",
    )

    def __init__(self, *, startup_feedback: StartupFeedbackProtocol | None = None):
        super().__init__()
        party_authority_notifier().changed.connect(lambda: self._on_party_authority_changed())
        self.setObjectName("mainWindow")
        configure_qt_application_identity(self)
        self._startup_feedback = startup_feedback
        self._startup_sound_has_startup_feedback = startup_feedback is not None
        self._startup_sound_played = False
        self._startup_sound_effect: QSoundEffect | None = None
        self._app_sound_effects: dict[str, QSoundEffect] = {}
        self._app_sound_last_played: dict[str, float] = {}
        self._app_sound_missing_reported: set[str] = set()
        self._app_sound_interactions_ready = False
        self._app_sound_hook_timer = QTimer(self)
        self._app_sound_hook_timer.setSingleShot(False)
        self._app_sound_hook_timer.setInterval(1000)
        self._app_sound_hook_timer.timeout.connect(lambda: self._install_app_sound_widget_hooks())
        self._startup_progress_tracker = (
            StartupProgressTracker.for_startup(startup_feedback)
            if startup_feedback is not None
            else None
        )
        self._startup_feedback_completed = False
        self._startup_ready_emitted = False
        self._startup_catalog_refresh_complete = False
        self._startup_waveform_cache_complete = False
        self._post_ready_startup_tasks_scheduled = False
        self.startupReady.connect(lambda: self.complete_startup_feedback())
        self.startupReady.connect(lambda: self._schedule_startup_sound_after_startup())
        self.startupReady.connect(lambda: self._enable_app_interaction_sounds())
        self.startupReady.connect(lambda: self._schedule_post_ready_startup_tasks())

        self.settings = QSettings(str(settings_path()), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)
        self.update_preferences = UpdatePreferenceService(self.settings)
        self.logger = logging.getLogger("ISRCManager")
        self.trace_logger = logging.getLogger("ISRCManager.trace")
        self._logging_configured = False
        self._bootstrap_log_buffer: list[tuple[str, int, str, dict | None]] = []
        self._report_startup_phase(StartupPhase.RESOLVING_STORAGE)
        self._report_storage_startup_progress(2, 100, "Locating startup storage settings...")
        self.storage_layout = resolve_app_storage_layout(settings=self.settings)
        self._report_storage_startup_progress(5, 100, "Resolved base storage directories.")
        self.storage_migration_service = StorageMigrationService(
            self.storage_layout,
            settings=self.settings,
            reporter=self._log_event,
            progress_reporter=self._report_storage_startup_progress,
        )
        startup_root = self._reconcile_startup_storage_root()
        self._report_startup_progress(
            StartupPhase.RESOLVING_STORAGE,
            value=84,
            maximum=100,
            message_override="Resolved startup storage layout.",
        )
        self._apply_storage_layout(active_data_root=startup_root)
        self._report_startup_progress(
            StartupPhase.RESOLVING_STORAGE,
            value=100,
            maximum=100,
            message_override="Applied startup storage directories.",
        )
        self._cleanup_ready_update_backup_handoff(phase="startup")

        self.sqlite_connection_factory = SQLiteConnectionFactory()
        self.database_session = DatabaseSessionService(self.sqlite_connection_factory)
        self.profile_store = ProfileStoreService(self.database_dir)
        self.profile_workflows = ProfileWorkflowService(self.database_dir, self.profile_store)
        self.database_maintenance = DatabaseMaintenanceService(self.backups_dir)
        self.application_isrc_registry = ApplicationISRCRegistryService(self.data_root)
        self.application_isrc_registry.ensure_schema()
        self.background_tasks = BackgroundTaskManager(self)
        self.background_tasks.task_state_changed.connect(
            lambda: self._on_background_task_state_changed()
        )
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
        self._report_startup_progress(
            StartupPhase.INITIALIZING_SETTINGS,
            value=1,
            maximum=3,
            message_override="Loaded application identity settings.",
        )
        self.theme_settings = self._load_theme_settings()
        self._report_startup_progress(
            StartupPhase.INITIALIZING_SETTINGS,
            value=2,
            maximum=3,
            message_override="Loaded theme and display preferences.",
        )
        self.blob_icon_settings = default_blob_icon_settings()
        self._apply_identity()
        self._report_startup_progress(
            StartupPhase.INITIALIZING_SETTINGS,
            value=3,
            maximum=3,
            message_override="Applied initial application settings.",
        )

        # --- Choose DB (last used or default) ---
        last_db = self.settings.value("db/last_path", "", str)
        existing_profiles = self.profile_store.list_profiles()
        fallback_db = existing_profiles[0] if existing_profiles else str(DB_PATH)
        if should_ignore_persisted_last_db_path(
            last_db,
            settings_path=self.settings.fileName(),
        ):
            self._log_event(
                "startup.profile_path_ignored",
                "Ignoring repo-owned demo/test database path during normal startup",
                ignored_path=last_db,
                fallback_path=fallback_db,
            )
            self.settings.setValue("db/last_path", fallback_db)
            self.settings.sync()
            last_db = fallback_db
        if not last_db:
            last_db = fallback_db
        self._report_startup_progress(
            StartupPhase.OPENING_PROFILE_DB,
            value=1,
            maximum=1,
            message_override="Selected startup profile database.",
        )

        self.conn = None
        self.cursor = None
        self.history_manager = None
        self.session_history_manager = SessionHistoryManager(self.history_dir)
        self.history_dialog = None
        self.help_dialog = None
        self.audio_preview_dialog = None
        self.image_preview_dialog = None
        self.auto_snapshot_timer = QTimer(self)
        self.auto_snapshot_timer.setSingleShot(False)
        self.auto_snapshot_timer.timeout.connect(lambda: self._on_auto_snapshot_timer())
        self._last_auto_snapshot_marker = None
        self._last_history_budget_warning_signature = None
        self._history_budget_enforcement_scheduled = False
        self._history_budget_enforcement_running = False
        self._history_budget_enforcement_trigger_label = "history update"
        self._suspend_layout_history = False
        self._suspend_dock_state_sync = False
        self._is_closing = False
        self._update_install_handoff_in_progress = False
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
        self._audio_waveform_cache_service_instance = None
        self._audio_waveform_cache_worker = None
        self.settings_reads = None
        self.settings_mutations = None
        self.blob_icon_settings_service = None
        self.gs1_settings_service = None
        self.gs1_integration_service = None
        self.catalog_service = None
        self.catalog_reads = None
        self.code_registry_service = None
        self.promo_code_service = None
        self.license_service = None
        self.license_migration_service = None
        self.profile_kv = None
        self.custom_field_definitions = None
        self.contract_template_catalog_service = None
        self.contract_template_service = None
        self.contract_template_form_service = None
        self.contract_template_export_service = None
        self.custom_field_values = None
        self.xml_export_service = None
        self.xml_import_service = None
        self.release_service = None
        self.authenticity_key_service = None
        self.authenticity_manifest_service = None
        self.audio_watermark_service = None
        self.audio_authenticity_service = None
        self.forensic_watermark_service = None
        self.forensic_export_service = None
        self.audio_tag_service = None
        self.tagged_audio_export_service = None
        self.exchange_service = None
        self.conversion_service = ConversionService()
        self.conversion_template_store_service = None
        self.party_exchange_service = None
        self.quality_service = None
        self.release_browser_dialog = None
        self.quality_dashboard_dialog = None
        self._explicit_row_filter_track_ids = None
        self._pending_work_track_context: dict[str, object] | None = None
        self._background_write_lock = None
        self._last_isrc_registry_sync_summary = None
        self._report_startup_phase(StartupPhase.OPENING_PROFILE_DB)
        startup_db_prepared = self._prepare_database_for_open_blocking(
            last_db,
            title="Open Profile",
            description="Preparing profile database...",
        )
        self.open_database(
            last_db,
            schema_prepared=startup_db_prepared,
            progress_callback=self._startup_progress_callback(StartupPhase.LOADING_SERVICES),
        )

        try:
            movable = self._catalog_header_state_manager(path=last_db).load_columns_movable_state(
                default=False
            )
        except Exception:
            movable = False

        self._report_startup_phase(StartupPhase.FINALIZING_INTERFACE)
        finalize_progress = self._startup_progress_callback(StartupPhase.FINALIZING_INTERFACE)
        build_main_window_shell(self, last_db=last_db, movable=bool(movable))
        finalize_progress(1, 5, "Built the main application shell.")
        self._configure_media_attach_drop_targets()
        self.tabifiedDockWidgetActivated.connect(
            lambda *_args: self._schedule_main_dock_state_save()
        )
        self._ensure_persistent_workspace_dock_shells()
        finalize_progress(2, 5, "Prepared persistent workspace dock shells.")

        self._apply_saved_view_preferences(apply_workspace_panel_visibility=False)
        finalize_progress(3, 5, "Applied saved workspace visibility preferences.")

        self.resize(1280, 800)
        self._refresh_history_actions()
        # Avoid installing the main window as an application-wide event filter.
        # PySide can crash while wrapping Qt Quick / WebEngine internal objects
        # during focus changes when a Python QMainWindow filters every app event.
        self._ensure_widget_object_names(self)
        finalize_progress(4, 5, "Finalized window wiring and runtime bindings.")
        self._apply_theme()
        finalize_progress(5, 5, "Applied the current theme and scheduled catalog loading.")
        startup_task_id = self._refresh_catalog_ui_in_background(
            unique_key="catalog.ui.startup",
            on_complete=self._handle_startup_catalog_refresh_complete,
            progress_callback=self._startup_progress_callback(StartupPhase.LOADING_CATALOG),
        )
        if startup_task_id is None:
            self._handle_startup_catalog_refresh_complete()

    def _report_startup_phase(
        self,
        phase: StartupPhase,
        message_override: str | None = None,
    ) -> None:
        tracker = getattr(self, "_startup_progress_tracker", None)
        if tracker is not None:
            tracker.set_phase(StartupPhase(phase), message_override)
            return
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

    def _report_startup_progress(
        self,
        phase: StartupPhase,
        *,
        value: int | float | None = None,
        maximum: int | float | None = None,
        message_override: str | None = None,
    ) -> None:
        tracker = getattr(self, "_startup_progress_tracker", None)
        if tracker is not None:
            tracker.report_progress(
                StartupPhase(phase),
                value=value,
                maximum=maximum,
                message=message_override,
            )
            return
        self._report_startup_phase(phase, message_override)

    def _startup_progress_callback(self, phase: StartupPhase):
        tracker = getattr(self, "_startup_progress_tracker", None)
        if tracker is not None:
            return tracker.progress_callback(StartupPhase(phase))

        def _fallback(value=None, maximum=None, message=None):
            del value, maximum
            self._report_startup_phase(phase, str(message or startup_phase_label(phase)))

        return _fallback

    def _report_storage_startup_progress(
        self,
        value: int | float,
        maximum: int | float,
        message: str,
    ) -> None:
        if getattr(self, "_startup_feedback_completed", False):
            return
        self._report_startup_progress(
            StartupPhase.RESOLVING_STORAGE,
            value=value,
            maximum=maximum,
            message_override=str(message or "Resolving storage layout..."),
        )
        self._drain_qt_events()

    @staticmethod
    def _drain_qt_events() -> None:
        app = QApplication.instance()
        process_events = getattr(app, "processEvents", None) if app is not None else None
        if callable(process_events):
            process_events()

    def _visible_layout_stabilization_targets(self) -> list[QWidget]:
        return main_window_layout._visible_layout_stabilization_targets(self)

    @staticmethod
    def _geometry_snapshot_for_widgets(widgets: list[QWidget]) -> tuple[tuple[object, ...], ...]:
        return main_window_layout._geometry_snapshot_for_widgets(widgets)

    def _stabilize_visible_layout_after_restore(
        self,
        *,
        progress_callback=None,
        maximum: int | None = None,
        value: int | None = None,
        stabilization_limit: int = 6,
    ) -> bool:
        return main_window_layout._stabilize_visible_layout_after_restore(
            self,
            progress_callback=progress_callback,
            maximum=maximum,
            value=value,
            stabilization_limit=stabilization_limit,
        )

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

    def _set_loading_feedback_phase(
        self,
        feedback: StartupFeedbackProtocol | None,
        phase: StartupPhase,
        message_override: str | None = None,
    ) -> None:
        if feedback is None:
            return
        set_phase = getattr(feedback, "set_phase", None)
        if callable(set_phase):
            try:
                set_phase(StartupPhase(phase), message_override)
                return
            except Exception:
                pass
        self._set_loading_feedback_status(feedback, message_override or startup_phase_label(phase))

    def _set_loading_feedback_progress(
        self,
        feedback: StartupFeedbackProtocol | None,
        *,
        progress: int,
        phase: StartupPhase | None = None,
        message_override: str | None = None,
    ) -> None:
        if feedback is None:
            return
        report_progress = getattr(feedback, "report_progress", None)
        if callable(report_progress):
            try:
                report_progress(
                    int(progress),
                    str(message_override or ""),
                    phase=StartupPhase(phase) if phase is not None else None,
                )
                return
            except Exception:
                pass
        if phase is not None:
            self._set_loading_feedback_phase(feedback, StartupPhase(phase), message_override)
        elif message_override is not None:
            self._set_loading_feedback_status(feedback, message_override)

    def _loading_feedback_progress_callback(
        self,
        feedback: StartupFeedbackProtocol | None,
        tracker: StartupProgressTracker | None,
        phase: StartupPhase,
    ):
        if tracker is not None:
            return tracker.progress_callback(StartupPhase(phase))

        def _fallback(value=None, maximum=None, message=None):
            numeric_progress = 0
            if value is not None and maximum not in (None, 0):
                try:
                    numeric_progress = int(round((float(value) / float(maximum)) * 100.0))
                except Exception:
                    numeric_progress = 0
            self._set_loading_feedback_progress(
                feedback,
                progress=numeric_progress,
                phase=StartupPhase(phase),
                message_override=str(message or startup_phase_label(phase)),
            )

        return _fallback

    def _set_loading_feedback_status(
        self,
        feedback: StartupFeedbackProtocol | None,
        message: str,
    ) -> None:
        if feedback is None:
            return
        set_status = getattr(feedback, "set_status", None)
        if callable(set_status):
            try:
                set_status(str(message or ""))
                return
            except Exception:
                pass
        current_phase = getattr(feedback, "current_phase", None)
        fallback_phase = StartupPhase(current_phase) if current_phase is not None else None
        set_phase = getattr(feedback, "set_phase", None)
        if callable(set_phase) and fallback_phase is not None:
            try:
                set_phase(fallback_phase, str(message or ""))
            except Exception:
                pass

    def _create_runtime_loading_feedback(self) -> StartupFeedbackProtocol | None:
        app = QApplication.instance()
        if app is None:
            return None
        feedback = create_startup_splash_controller(app)
        if feedback is not None:
            feedback.show()
        return feedback

    def _finish_loading_feedback(self, feedback: StartupFeedbackProtocol | None) -> None:
        finish = getattr(feedback, "finish", None)
        if callable(finish):
            try:
                finish(self)
            except Exception:
                pass

    def _handle_startup_catalog_refresh_complete(self) -> None:
        self._startup_catalog_refresh_complete = True
        self._maybe_finish_startup_loading()

    def _audio_waveform_cache_service(self, *args, **kwargs):
        return waveform_cache_controller._audio_waveform_cache_service(self, *args, **kwargs)

    def _audio_waveform_cache_worker_for_current_profile(self, *args, **kwargs):
        return waveform_cache_controller._audio_waveform_cache_worker_for_current_profile(
            self, *args, **kwargs
        )

    def _stop_audio_waveform_cache_worker(self, *args, **kwargs):
        return waveform_cache_controller._stop_audio_waveform_cache_worker(self, *args, **kwargs)

    def _queue_audio_waveform_cache_for_track(self, *args, **kwargs):
        return waveform_cache_controller._queue_audio_waveform_cache_for_track(
            self, *args, **kwargs
        )

    def _queue_startup_audio_waveform_cache_pass(self, *args, **kwargs):
        return waveform_cache_controller._queue_startup_audio_waveform_cache_pass(
            self, *args, **kwargs
        )

    def _audio_waveform_cache_for_track(self, *args, **kwargs):
        return waveform_cache_controller._audio_waveform_cache_for_track(self, *args, **kwargs)

    def _run_startup_audio_waveform_cache_pass(self, *args, **kwargs):
        return waveform_cache_controller._run_startup_audio_waveform_cache_pass(
            self, *args, **kwargs
        )

    def _maybe_finish_startup_loading(self) -> None:
        if self._startup_ready_emitted:
            return
        if not getattr(self, "_workspace_layout_restore_complete", False):
            return
        if not getattr(self, "_startup_catalog_refresh_complete", False):
            self._report_startup_phase(StartupPhase.LOADING_CATALOG)
            return
        if not getattr(self, "_startup_waveform_cache_complete", False):
            self._startup_waveform_cache_complete = True
            self._run_startup_audio_waveform_cache_pass(
                progress_callback=self._startup_progress_callback(StartupPhase.LOADING_CATALOG)
            )
        self._startup_ready_emitted = True
        self.startupReady.emit()

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
            tracker = getattr(self, "_startup_progress_tracker", None)
            if tracker is not None:
                tracker.finish()
            else:
                report_progress = getattr(controller, "report_progress", None)
                if callable(report_progress):
                    try:
                        report_progress(
                            100,
                            startup_phase_label(StartupPhase.READY),
                            phase=StartupPhase.READY,
                        )
                    except Exception:
                        pass
                else:
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
            self._startup_progress_tracker = None

    @staticmethod
    def _coerce_settings_bool(value, *, default: bool = False) -> bool:
        return app_sound_controller._coerce_settings_bool(
            value,
            default=default,
        )

    def _app_sound_enabled(self, sound_id: str) -> bool:
        return app_sound_controller._app_sound_enabled(
            self,
            sound_id,
        )

    def _startup_sound_enabled(self) -> bool:
        return app_sound_controller._startup_sound_enabled(
            self,
        )

    def _current_app_sound_settings(self) -> dict[str, bool]:
        return app_sound_controller._current_app_sound_settings(
            self,
        )

    def _app_sound_path(self, sound_id: str) -> Path:
        return app_sound_controller._app_sound_path(
            self,
            sound_id,
        )

    def _startup_sound_path(self) -> Path:
        return app_sound_controller._startup_sound_path(
            self,
        )

    def _app_sound_effect(self, sound_id: str) -> QSoundEffect:
        return app_sound_controller._app_sound_effect(
            self,
            sound_id,
        )

    def _play_app_sound(
        self,
        sound_id: str,
        *,
        throttle_key: str | None = None,
        throttle_ms: int = 0,
    ) -> None:
        return app_sound_controller._play_app_sound(
            self,
            sound_id,
            throttle_key=throttle_key,
            throttle_ms=throttle_ms,
        )

    def _schedule_startup_sound_after_startup(self) -> None:
        return app_sound_controller._schedule_startup_sound_after_startup(
            self,
        )

    def _play_startup_sound(self) -> None:
        return app_sound_controller._play_startup_sound(
            self,
        )

    def _play_notice_sound(self) -> None:
        return app_sound_controller._play_notice_sound(
            self,
        )

    def _play_warning_sound(self) -> None:
        return app_sound_controller._play_warning_sound(
            self,
        )

    def _enable_app_interaction_sounds(self) -> None:
        return app_sound_controller._enable_app_interaction_sounds(
            self,
        )

    def _install_app_sound_widget_hooks(self, root: QWidget | None = None) -> None:
        return app_sound_controller._install_app_sound_widget_hooks(
            self,
            root,
        )

    def _message_box_notice_worthy(self, message_box: QMessageBox) -> bool:
        return app_sound_controller._message_box_notice_worthy(
            self,
            message_box,
        )

    def _play_message_box_sound_once(self, widget: QWidget) -> None:
        return app_sound_controller._play_message_box_sound_once(
            self,
            widget,
        )

    def _cleanup_ready_update_backup_handoff(self, *args, **kwargs):
        return update_controller._cleanup_ready_update_backup_handoff(self, *args, **kwargs)

    def _cleanup_legacy_update_backup_siblings(self, *args, **kwargs):
        return update_controller._cleanup_legacy_update_backup_siblings(self, *args, **kwargs)

    def _cleanup_update_cache_artifacts(self, *args, **kwargs):
        return update_controller._cleanup_update_cache_artifacts(self, *args, **kwargs)

    def _finalize_update_backup_handoff(self, *args, **kwargs):
        return update_controller._finalize_update_backup_handoff(self, *args, **kwargs)

    def _mark_update_backup_handoff_ready_on_close(self, *args, **kwargs):
        return update_controller._mark_update_backup_handoff_ready_on_close(self, *args, **kwargs)

    def _schedule_post_ready_startup_tasks(self) -> None:
        if self._post_ready_startup_tasks_scheduled:
            return
        self._post_ready_startup_tasks_scheduled = True
        QTimer.singleShot(0, lambda: self._run_post_ready_startup_tasks())

    def _run_post_ready_startup_tasks(self) -> None:
        self._update_add_data_generated_fields()
        self._schedule_owner_party_bootstrap()
        self._offer_settings_on_first_launch_if_pending()
        self._finalize_update_backup_handoff(phase="startup-ready")
        self._schedule_startup_update_check()

    def _schedule_startup_update_check(self, *args, **kwargs):
        return update_controller._schedule_startup_update_check(self, *args, **kwargs)

    def _run_startup_update_check(self, *args, **kwargs):
        return update_controller._run_startup_update_check(self, *args, **kwargs)

    def check_for_updates(self, *args, **kwargs):
        return update_controller.check_for_updates(self, *args, **kwargs)

    def _build_update_checker(self, *args, **kwargs):
        return update_controller._build_update_checker(self, *args, **kwargs)

    def _start_update_check(self, *args, **kwargs):
        return update_controller._start_update_check(self, *args, **kwargs)

    def _handle_update_check_result(self, *args, **kwargs):
        return update_controller._handle_update_check_result(self, *args, **kwargs)

    def _show_update_available_message(self, *args, **kwargs):
        return update_controller._show_update_available_message(self, *args, **kwargs)

    def _confirm_and_start_update_install(self, *args, **kwargs):
        return update_controller._confirm_and_start_update_install(self, *args, **kwargs)

    def _start_update_install(self, *args, **kwargs):
        return update_controller._start_update_install(self, *args, **kwargs)

    def _launch_prepared_update(self, *args, **kwargs):
        return update_controller._launch_prepared_update(self, *args, **kwargs)

    def _show_update_release_notes(self, *args, **kwargs):
        return update_controller._show_update_release_notes(self, *args, **kwargs)

    def _present_update_release_notes(self, *args, **kwargs):
        return update_controller._present_update_release_notes(self, *args, **kwargs)

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
        return profile_session._apply_storage_layout(
            self,
            active_data_root=active_data_root,
        )

    def _reconcile_startup_storage_root(self) -> Path:
        return profile_session._reconcile_startup_storage_root(self)

    def _maybe_run_storage_layout_migration(self) -> Path:
        return profile_session._maybe_run_storage_layout_migration(self)

    def _run_storage_layout_migration(self):
        return profile_session._run_storage_layout_migration(self)

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
        timer = getattr(self, "_app_sound_hook_timer", None)
        if timer is not None:
            timer.stop()
        self._stop_audio_waveform_cache_worker(wait=False)
        self._save_main_window_geometry(sync=False)
        self._store_workspace_panel_visibility_preferences(sync=False)
        self._save_main_dock_state(sync=False)
        self.settings.sync()
        self._mark_update_backup_handoff_ready_on_close()
        self.logger.info("Settings synced to disk")
        super().closeEvent(e)

    def _configure_logging(self) -> None:
        app_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
        trace_formatter = _JsonLogFormatterTarget()
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

    @staticmethod
    def _safe_trace_field_name(key: str, existing_keys: set[str]) -> str:
        clean_key = str(key or "").strip() or "field"
        if clean_key not in _RESERVED_TRACE_LOG_KEYS and clean_key not in existing_keys:
            return clean_key
        base_key = f"field_{clean_key}"
        candidate = base_key
        suffix = 2
        while candidate in _RESERVED_TRACE_LOG_KEYS or candidate in existing_keys:
            candidate = f"{base_key}_{suffix}"
            suffix += 1
        return candidate

    def _trace_context(self, **fields) -> dict:
        payload = {
            "profile": (
                Path(self.current_db_path).name if getattr(self, "current_db_path", "") else None
            ),
            "db_path": str(self.current_db_path) if getattr(self, "current_db_path", "") else None,
        }
        payload.update(fields)
        normalized: dict[str, object] = {}
        for key, value in payload.items():
            if value in (None, "", [], {}, ()):
                continue
            safe_key = self._safe_trace_field_name(str(key), set(normalized))
            normalized[safe_key] = self._normalize_log_value(value)
        return normalized

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
            ordered_shortcuts = self._ordered_custom_shortcuts(shortcuts)
            action.setShortcuts(ordered_shortcuts)
            if self._should_register_explicit_action_shortcuts(ordered_shortcuts):
                action.setShortcutContext(Qt.WidgetShortcut)
                self._install_explicit_action_shortcuts(action, ordered_shortcuts)
        if slot is not None:
            self._connect_noarg_signal(action.triggered, action, slot)
        if toggled_slot is not None:
            self._connect_bool_signal(action.toggled, action, toggled_slot)
        self.addAction(action)
        return action

    def _media_player_icon_path(self, *args, **kwargs):
        return media_player_controller._media_player_icon_path(self, *args, **kwargs)

    MEDIA_PLAYER_ACTION_ICON_SCALE = 0.45

    def _text_scaled_icon_extent(self, *args, **kwargs):
        return media_player_controller._text_scaled_icon_extent(self, *args, **kwargs)

    @staticmethod
    def _tinted_icon_pixmap(*args, **kwargs):
        return media_player_controller._tinted_icon_pixmap(*args, **kwargs)

    def _media_player_action_icon(self, *args, **kwargs):
        return media_player_controller._media_player_action_icon(self, *args, **kwargs)

    def _configure_media_player_action_icon(self, *args, **kwargs):
        return media_player_controller._configure_media_player_action_icon(self, *args, **kwargs)

    def _action_ribbon_text_button_height(self, widget: QToolButton) -> int:
        return action_ribbon._action_ribbon_text_button_height(self, widget)

    def _configure_action_ribbon_button_widget(self, action_id: str, widget, spec: dict) -> None:
        return action_ribbon._configure_action_ribbon_button_widget(self, action_id, widget, spec)

    def _refresh_media_player_action_surfaces(self) -> None:
        return action_ribbon._refresh_media_player_action_surfaces(self)

    def _signal_noarg_wrapper(self, slot):
        def _wrapper(_checked=False, _slot=slot):
            _slot()

        return _wrapper

    def _signal_bool_wrapper(self, slot):
        def _wrapper(checked=False, _slot=slot):
            _slot(bool(checked))

        return _wrapper

    def _signal_args_wrapper(self, slot):
        def _wrapper(*args, _slot=slot):
            _slot(*args)

        return _wrapper

    def _connect_noarg_signal(self, signal, owner, slot):
        wrapper = self._signal_noarg_wrapper(slot)
        self._keep_signal_wrapper_alive(owner, wrapper)
        signal.connect(wrapper)
        return wrapper

    def _connect_bool_signal(self, signal, owner, slot):
        wrapper = self._signal_bool_wrapper(slot)
        self._keep_signal_wrapper_alive(owner, wrapper)
        signal.connect(wrapper)
        return wrapper

    def _connect_args_signal(self, signal, owner, slot):
        wrapper = self._signal_args_wrapper(slot)
        self._keep_signal_wrapper_alive(owner, wrapper)
        signal.connect(wrapper)
        return wrapper

    def _keep_signal_wrapper_alive(self, owner, wrapper) -> None:
        wrappers = getattr(owner, "_isrc_signal_wrappers", None)
        if wrappers is None:
            wrappers = []
            owner._isrc_signal_wrappers = wrappers
        wrappers.append(wrapper)

    def _should_register_explicit_action_shortcuts(
        self, shortcuts: tuple[QKeySequence, ...] | list[QKeySequence]
    ) -> bool:
        portable_texts = [
            shortcut.toString(QKeySequence.PortableText)
            for shortcut in shortcuts
            if not shortcut.isEmpty()
        ]
        return bool(portable_texts) and all(
            any(modifier in portable_text for modifier in ("Ctrl+", "Meta+"))
            for portable_text in portable_texts
        )

    def _install_explicit_action_shortcuts(
        self, action: QAction, shortcuts: tuple[QKeySequence, ...] | list[QKeySequence]
    ) -> None:
        registry = getattr(self, "_explicit_action_shortcut_registry", None)
        if registry is None:
            registry = {}
            self._explicit_action_shortcut_registry = registry

        action_shortcuts = getattr(self, "_explicit_action_shortcut_objects", None)
        if action_shortcuts is None:
            action_shortcuts = {}
            self._explicit_action_shortcut_objects = action_shortcuts

        registered_shortcuts: list[QShortcut] = []
        for shortcut_sequence in shortcuts:
            portable_text = shortcut_sequence.toString(QKeySequence.PortableText)
            if not portable_text:
                continue
            existing_action = registry.get(portable_text)
            if existing_action is not None and existing_action is not action:
                self._log_event(
                    "shortcut.duplicate_custom_binding",
                    "Skipping duplicate explicit shortcut binding.",
                    level=logging.WARNING,
                    shortcut=portable_text,
                    kept_action=str(existing_action.text() or ""),
                    skipped_action=str(action.text() or ""),
                )
                continue
            shortcut = QShortcut(shortcut_sequence, self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(
                lambda active_action=action: self._trigger_explicit_action_shortcut(active_action)
            )
            registry[portable_text] = action
            registered_shortcuts.append(shortcut)

        if registered_shortcuts:
            action_shortcuts[action] = registered_shortcuts

    def _trigger_explicit_action_shortcut(self, action: QAction) -> None:
        if action is None or not action.isEnabled():
            return
        action.trigger()

    def _ordered_custom_shortcuts(
        self, shortcuts: tuple[str, ...] | list[str] | tuple[QKeySequence, ...] | list[QKeySequence]
    ) -> list[QKeySequence]:
        """Keep menu-visible primary shortcuts aligned with the active platform."""

        parsed_shortcuts: list[
            tuple[int, QKeySequence, str, tuple[tuple[str, ...], str] | None]
        ] = []
        seen_texts: set[str] = set()
        for index, raw_shortcut in enumerate(shortcuts):
            shortcut = (
                raw_shortcut
                if isinstance(raw_shortcut, QKeySequence)
                else QKeySequence(str(raw_shortcut))
            )
            portable_text = shortcut.toString(QKeySequence.PortableText)
            if not portable_text or portable_text in seen_texts:
                continue
            seen_texts.add(portable_text)
            parsed_shortcuts.append(
                (
                    index,
                    shortcut,
                    portable_text,
                    self._platform_variant_shortcut_group(portable_text),
                )
            )

        # QKeySequence portable text uses Ctrl for the platform primary modifier
        # (Command on macOS), while Meta maps to the native Control key there.
        preferred_variant = "Ctrl"
        variant_groups: dict[
            tuple[str, ...],
            list[tuple[int, QKeySequence, str, tuple[tuple[str, ...], str]]],
        ] = {}
        for index, shortcut, portable_text, group in parsed_shortcuts:
            if group is None:
                continue
            variant_groups.setdefault(group[0], []).append((index, shortcut, portable_text, group))

        dual_variant_groups = {
            normalized_parts
            for normalized_parts, members in variant_groups.items()
            if {group[1] for _, _, _, group in members} == {"Ctrl", "Meta"}
        }

        ordered_shortcuts: list[QKeySequence] = []
        emitted_groups: set[tuple[str, ...]] = set()
        for _, shortcut, _, group in parsed_shortcuts:
            if group is None or group[0] not in dual_variant_groups:
                ordered_shortcuts.append(shortcut)
                continue
            normalized_parts = group[0]
            if normalized_parts in emitted_groups:
                continue
            emitted_groups.add(normalized_parts)
            members = variant_groups[normalized_parts]
            members.sort(
                key=lambda member: (0 if member[3][1] == preferred_variant else 1, member[0])
            )
            ordered_shortcuts.extend(member[1] for member in members)
        return ordered_shortcuts

    def _platform_variant_shortcut_group(
        self, portable_text: str
    ) -> tuple[tuple[str, ...], str] | None:
        parts = tuple(part for part in portable_text.split("+") if part)
        has_ctrl = "Ctrl" in parts
        has_meta = "Meta" in parts
        if has_ctrl == has_meta:
            return None
        variant = "Meta" if has_meta else "Ctrl"
        normalized_parts = tuple(
            "PrimaryModifier" if part in {"Ctrl", "Meta"} else part for part in parts
        )
        return normalized_parts, variant

    def _app_version_text(self) -> str:
        return current_app_version()

    def _help_html(self) -> str:
        return render_help_html(
            "Music Catalog Manager",
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
        if not open_external_path(
            target,
            source="App._open_local_path",
            metadata={"action_label": action_label},
        ):
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
        return diagnostics_report._history_snapshot_summary(
            self,
            conn,
        )

    def _custom_value_field_column_name(self, conn=None) -> str | None:
        return diagnostics_report._custom_value_field_column_name(
            self,
            conn,
        )

    def _count_orphaned_custom_values(self, conn=None) -> int:
        return diagnostics_report._count_orphaned_custom_values(
            self,
            conn,
        )

    def _legacy_promoted_field_repair_candidates(self, conn=None):
        return diagnostics_report._legacy_promoted_field_repair_candidates(
            self,
            conn,
        )

    def _diagnostics_managed_file_scan_counts(self, conn=None) -> dict[str, int]:
        return diagnostics_report._diagnostics_managed_file_scan_counts(
            self,
            conn,
        )

    def _build_diagnostics_progress_plan(
        self,
        *,
        conn=None,
        current_db_path: str | Path | None = None,
    ) -> dict[str, int]:
        return diagnostics_report._build_diagnostics_progress_plan(
            self,
            conn=conn,
            current_db_path=current_db_path,
        )

    def _preview_diagnostics_repair(self, repair_key: str, check: dict | None = None) -> str:
        return diagnostics_controller._preview_diagnostics_repair(
            self,
            repair_key,
            check,
        )

    def _run_diagnostics_repair(self, repair_key: str, check: dict | None = None) -> str:
        return diagnostics_controller._run_diagnostics_repair(
            self,
            repair_key,
            check,
        )

    def _application_storage_admin_service(self) -> ApplicationStorageAdminService:
        return diagnostics_report._application_storage_admin_service(
            self,
        )

    def _history_retention_settings_for_storage_summary(
        self,
        current_db_path: str | Path | None,
    ) -> HistoryRetentionSettings:
        return diagnostics_report._history_retention_settings_for_storage_summary(
            self,
            current_db_path,
        )

    def _application_storage_summary_payload(
        self,
        audit,
        *,
        current_db_path: str | Path | None = None,
    ) -> dict[str, object]:
        return diagnostics_report._application_storage_summary_payload(
            self,
            audit,
            current_db_path=current_db_path,
        )

    def _application_storage_item_payload(self, item) -> dict[str, object]:
        return diagnostics_report._application_storage_item_payload(
            self,
            item,
        )

    def _build_application_storage_audit_payload(
        self,
        *,
        current_db_path: str | Path | None = None,
        status_callback=None,
        progress_callback=None,
    ) -> dict[str, object]:
        return diagnostics_report._build_application_storage_audit_payload(
            self,
            current_db_path=current_db_path,
            status_callback=status_callback,
            progress_callback=progress_callback,
        )

    def _load_application_storage_audit_async(
        self,
        *,
        owner: QWidget | None = None,
        on_success=None,
        on_error=None,
        on_cancelled=None,
        on_finished=None,
        on_status=None,
    ):
        return diagnostics_controller._load_application_storage_audit_async(
            self,
            owner=owner,
            on_success=on_success,
            on_error=on_error,
            on_cancelled=on_cancelled,
            on_finished=on_finished,
            on_status=on_status,
        )

    def _run_application_storage_cleanup_async(
        self,
        item_keys: list[str] | tuple[str, ...],
        *,
        allow_warning_deletes: bool = False,
        owner: QWidget | None = None,
        on_success=None,
        on_error=None,
        on_cancelled=None,
        on_finished=None,
        on_status=None,
    ):
        return diagnostics_controller._run_application_storage_cleanup_async(
            self,
            item_keys,
            allow_warning_deletes=allow_warning_deletes,
            owner=owner,
            on_success=on_success,
            on_error=on_error,
            on_cancelled=on_cancelled,
            on_finished=on_finished,
            on_status=on_status,
        )

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
        progress_callback=None,
    ) -> dict[str, object]:
        return diagnostics_report._build_diagnostics_report(
            self,
            conn=conn,
            schema_service=schema_service,
            current_db_path=current_db_path,
            data_root=data_root,
            logs_dir=logs_dir,
            track_service=track_service,
            license_service=license_service,
            history_manager=history_manager,
            database_maintenance=database_maintenance,
            storage_migration_service=storage_migration_service,
            app_version=app_version,
            status_callback=status_callback,
            progress_callback=progress_callback,
        )

    def _load_diagnostics_report_async(
        self,
        *,
        owner: QWidget | None = None,
        on_success=None,
        on_error=None,
        on_cancelled=None,
        on_finished=None,
        on_progress=None,
        on_status=None,
    ):
        return diagnostics_controller._load_diagnostics_report_async(
            self,
            owner=owner,
            on_success=on_success,
            on_error=on_error,
            on_cancelled=on_cancelled,
            on_finished=on_finished,
            on_progress=on_progress,
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
        return diagnostics_controller._run_bundle_diagnostics_repair(
            self,
            repair_key,
            check,
            bundle=bundle,
            current_db_path=current_db_path,
            data_root=data_root,
            status_callback=status_callback,
        )

    def _apply_diagnostics_repair_result(
        self, repair_key: str, result: dict[str, object] | None
    ) -> str:
        return diagnostics_controller._apply_diagnostics_repair_result(
            self,
            repair_key,
            result,
        )

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
        return diagnostics_controller._run_diagnostics_repair_async(
            self,
            repair_key,
            check,
            owner=owner,
            on_success=on_success,
            on_error=on_error,
            on_cancelled=on_cancelled,
            on_finished=on_finished,
            on_status=on_status,
        )

    def open_application_log_dialog(self):
        ApplicationLogDialog(self, parent=self).exec()

    def open_application_storage_admin_dialog(self):
        ApplicationStorageAdminDialog(self, parent=self).exec()

    def open_diagnostics_dialog(self, *, initial_cleanup_tab: str | None = None):
        dialog = DiagnosticsDialog(self, parent=self)
        if initial_cleanup_tab:
            dialog.focus_cleanup_tab(initial_cleanup_tab)
        dialog.exec()

    def _init_services(self):
        initialize_foreground_services(self)

    def _refresh_audio_conversion_action_states(self, *args, **kwargs):
        return audio_conversion_controller._refresh_audio_conversion_action_states(
            self, *args, **kwargs
        )

    # -------------------------------------------------------------------------
    # Identity & Profiles
    # -------------------------------------------------------------------------
    def _stored_window_title_override(self) -> str:
        return settings_controller._stored_window_title_override(
            self,
        )

    def _current_owner_company_name(self) -> str:
        return settings_controller._current_owner_company_name(
            self,
        )

    def _resolve_window_title(self, override: str | None = None) -> str:
        return settings_controller._resolve_window_title(
            self,
            override,
        )

    def _load_identity(self):
        return settings_controller._load_identity(
            self,
        )

    def _apply_identity(self):
        return settings_controller._apply_identity(
            self,
        )

    @staticmethod
    def _theme_setting_defaults() -> dict[str, object]:
        return theme_controller._theme_setting_defaults()

    @classmethod
    def _theme_setting_keys(cls) -> tuple[str, ...]:
        return theme_controller._theme_setting_keys()

    @staticmethod
    def _normalize_theme_string(value) -> str:
        return theme_controller._normalize_theme_string(
            value,
        )

    @staticmethod
    def _format_theme_qss_issues(issues: list) -> str:
        return theme_controller._format_theme_qss_issues(
            issues,
        )

    @classmethod
    def _normalize_theme_font_family(cls, value, fallback) -> str:
        return theme_controller._normalize_theme_font_family(
            value,
            fallback,
        )

    @staticmethod
    def _normalize_theme_color(value) -> str:
        return theme_controller._normalize_theme_color(
            value,
        )

    def _load_theme_settings(self) -> dict[str, object]:
        return theme_controller._load_theme_settings(
            self,
        )

    def _normalize_theme_settings(self, values: dict[str, object] | None) -> dict[str, object]:
        return theme_controller._normalize_theme_settings(
            self,
            values,
        )

    def _stored_theme_payload(self, values: dict[str, object] | None) -> dict[str, object]:
        return theme_controller._stored_theme_payload(
            self,
            values,
        )

    def _sanitize_theme_library(
        self, library: dict[str, object] | None
    ) -> dict[str, dict[str, object]]:
        return theme_controller._sanitize_theme_library(
            self,
            library,
        )

    def _load_theme_library(self) -> dict[str, dict[str, object]]:
        return theme_controller._load_theme_library(
            self,
        )

    def _save_theme_library(
        self, library: dict[str, object] | None
    ) -> dict[str, dict[str, object]]:
        return theme_controller._save_theme_library(
            self,
            library,
        )

    @staticmethod
    def _color_relative_luminance(color_value: str) -> float:
        return theme_controller._color_relative_luminance(
            color_value,
        )

    @classmethod
    def _contrast_ratio(cls, fg_value: str, bg_value: str) -> float:
        return theme_controller._contrast_ratio(
            fg_value,
            bg_value,
        )

    @classmethod
    def _pick_contrasting_color(cls, bg_value: str) -> str:
        return theme_controller._pick_contrasting_color(
            bg_value,
        )

    @staticmethod
    def _shift_color(color_value: str, factor: int) -> str:
        return theme_controller._shift_color(
            color_value,
            factor,
        )

    def _effective_theme_settings(
        self, raw_values: dict[str, object] | None = None
    ) -> dict[str, object]:
        return theme_controller._effective_theme_settings(
            self,
            raw_values,
        )

    def _save_theme_settings(self, values: dict[str, object]) -> dict[str, object]:
        return theme_controller._save_theme_settings(
            self,
            values,
        )

    @staticmethod
    def _blob_icon_setting_defaults() -> dict[str, dict[str, object]]:
        return theme_controller._blob_icon_setting_defaults()

    def _load_blob_icon_settings(self) -> dict[str, dict[str, object]]:
        return theme_controller._load_blob_icon_settings(
            self,
        )

    def _save_blob_icon_settings(
        self, values: dict[str, object] | None
    ) -> dict[str, dict[str, object]]:
        return theme_controller._save_blob_icon_settings(
            self,
            values,
        )

    def _reset_blob_badge_render_cache(self) -> None:
        return theme_controller._reset_blob_badge_render_cache(
            self,
        )

    def _active_custom_qss(self) -> str:
        return theme_controller._active_custom_qss(
            self,
        )

    def _build_theme_stylesheet(self, raw_values: dict[str, object] | None = None) -> str:
        return theme_controller._build_theme_stylesheet(
            self,
            raw_values,
        )

    def _set_application_theme_stylesheet(self, app: QApplication, stylesheet: str) -> None:
        return theme_controller._set_application_theme_stylesheet(
            self,
            app,
            stylesheet,
        )

    def _apply_theme(self, raw_values: dict[str, object] | None = None) -> None:
        return theme_controller._apply_theme(
            self,
            raw_values,
        )

    def _prepare_theme_application_payload(
        self, raw_values: dict[str, object] | None = None
    ) -> dict[str, object]:
        return theme_controller._prepare_theme_application_payload(
            self,
            raw_values,
        )

    def _apply_prepared_theme_payload(self, payload: dict[str, object]) -> None:
        return theme_controller._apply_prepared_theme_payload(
            self,
            payload,
        )

    def _refresh_menu_theme_state(self) -> None:
        return theme_controller._refresh_menu_theme_state(
            self,
        )

    def _apply_theme_with_loading(
        self,
        raw_values: dict[str, object] | None = None,
        *,
        title: str = "Apply Theme",
        description: str = "Preparing updated theme styles...",
    ) -> None:
        return theme_controller._apply_theme_with_loading(
            self,
            raw_values,
            title=title,
            description=description,
        )

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
            self._connect_noarg_signal(timer.timeout, timer, self._apply_top_chrome_boundary)
            self._top_chrome_boundary_timer = timer
        timer.start(0)

    def event(self, event):
        if event.type() == QEvent.LayoutRequest:
            self._schedule_main_dock_state_save()
        return super().event(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._queue_top_chrome_boundary_refresh()
        if getattr(self, "_app_sound_interactions_ready", False):
            QTimer.singleShot(0, self._install_app_sound_widget_hooks)
        if self._workspace_layout_restore_pending and not self._workspace_layout_restore_scheduled:
            self._workspace_layout_restore_pending = False
            self._workspace_layout_restore_scheduled = True
            QTimer.singleShot(0, lambda: self._restore_workspace_layout_on_first_show())

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
        if event.type() in (
            QEvent.FontChange,
            QEvent.ApplicationFontChange,
            QEvent.PaletteChange,
            QEvent.ApplicationPaletteChange,
            QEvent.StyleChange,
        ):
            self._refresh_media_player_action_surfaces()

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
        return history_retention_controller._current_auto_snapshot_settings(
            self,
        )

    def _current_history_retention_settings(self) -> HistoryRetentionSettings:
        return history_retention_controller._current_history_retention_settings(
            self,
        )

    def _application_history_storage_budget_mb(self, *, default: int) -> int:
        return history_retention_controller._application_history_storage_budget_mb(
            self,
            default=default,
        )

    def _set_application_history_storage_budget_mb(self, value: int) -> int:
        return history_retention_controller._set_application_history_storage_budget_mb(
            self,
            value,
        )

    def _apply_history_snapshot_retention_policy(
        self,
        *,
        trigger_label: str,
        settings: HistoryRetentionSettings | None = None,
    ):
        return history_retention_controller._apply_history_snapshot_retention_policy(
            self,
            trigger_label=trigger_label,
            settings=settings,
        )

    def open_history_cleanup_dialog(self):
        dialog = HistoryCleanupDialog(self, parent=self)
        dialog.exec()

    @staticmethod
    def _path_size_recursive(path: Path | None) -> int:
        return history_retention_controller._path_size_recursive(
            path,
        )

    @staticmethod
    def _allocated_path_size(path: Path) -> int:
        return history_retention_controller._allocated_path_size(
            path,
        )

    def _estimate_history_snapshot_capture_bytes(self) -> int:
        return history_retention_controller._estimate_history_snapshot_capture_bytes(
            self,
        )

    def _prepare_history_storage_for_projected_growth(
        self,
        *,
        trigger_label: str,
        additional_bytes: int,
        interactive: bool,
    ) -> bool:
        return history_retention_controller._prepare_history_storage_for_projected_growth(
            self,
            trigger_label=trigger_label,
            additional_bytes=additional_bytes,
            interactive=interactive,
        )

    def _enforce_history_storage_budget(
        self,
        *,
        trigger_label: str,
        interactive: bool = False,
    ) -> None:
        return history_retention_controller._enforce_history_storage_budget(
            self,
            trigger_label=trigger_label,
            interactive=interactive,
        )

    def _refresh_auto_snapshot_schedule(self) -> None:
        return history_retention_controller._refresh_auto_snapshot_schedule(
            self,
        )

    def _current_auto_snapshot_marker(self) -> int | None:
        return history_retention_controller._current_auto_snapshot_marker(
            self,
        )

    def _on_auto_snapshot_timer(self) -> None:
        return history_retention_controller._on_auto_snapshot_timer(
            self,
        )

    def _current_settings_values(self) -> dict[str, object]:
        return settings_controller._current_settings_values(
            self,
        )

    def _apply_settings_changes(
        self,
        before_values: dict[str, object],
        after_values: dict[str, object],
        *,
        show_confirmation: bool = False,
    ) -> int:
        return settings_controller._apply_settings_changes(
            self,
            before_values,
            after_values,
            show_confirmation=show_confirmation,
        )

    def open_settings_dialog(self, initial_focus: str | None = None):
        return settings_controller.open_settings_dialog(
            self,
            initial_focus,
        )

    def export_application_settings_bundle(self):
        return settings_controller.export_application_settings_bundle(
            self,
        )

    def import_application_settings_bundle(self):
        return settings_controller.import_application_settings_bundle(
            self,
        )

    def _apply_single_setting_value(self, field_name: str, value: str) -> int:
        return settings_controller._apply_single_setting_value(
            self,
            field_name,
            value,
        )

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
        return profile_session._reload_profiles_list(self, select_path)

    def _on_profile_changed(self, idx: int):
        return profile_session._on_profile_changed(self, idx)

    def create_new_profile(self):
        return profile_session.create_new_profile(self)

    def browse_profile(self):
        return profile_session.browse_profile(self)

    def remove_selected_profile(self):
        return profile_session.remove_selected_profile(self)

    def open_catalog_managers_dialog(self, *, initial_tab: str = "artists"):
        if self.catalog_service is None:
            QMessageBox.warning(self, "Catalog Cleanup", "Open a profile first.")
            return None
        self.open_diagnostics_dialog(initial_cleanup_tab=initial_tab)
        return None

    def _show_workspace_panel(
        self,
        ensure_dock,
        *,
        panel_attr: str,
        legacy_attr: str | None = None,
        configure=None,
        refresh_scope: bool = False,
    ):
        dock = ensure_dock()
        panel = dock.show_panel()
        if callable(configure):
            configure(panel)
        if refresh_scope:
            refresh_selection_scope = getattr(panel, "refresh_selection_scope", None)
            if callable(refresh_selection_scope):
                refresh_selection_scope()
        setattr(self, panel_attr, panel)
        if legacy_attr:
            setattr(self, legacy_attr, panel)
        return panel

    def _manage_stored_artists(self):
        self.open_diagnostics_dialog(initial_cleanup_tab="artists")

    def _manage_stored_albums(self):
        self.open_diagnostics_dialog(initial_cleanup_tab="albums")

    def _close_database_connection(self):
        return profile_session._close_database_connection(self)

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
        if not hasattr(self, "findChildren"):
            return
        status_bars = self.findChildren(QStatusBar, options=Qt.FindDirectChildrenOnly)
        status_bar = status_bars[0] if status_bars else None
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
        self._play_warning_sound()
        QMessageBox.critical(self, title, f"{user_message}\n{failure.message}")

    @staticmethod
    def _scaled_progress_callback(progress_callback, *, start: int, end: int):
        span = max(0, int(end) - int(start))

        def _report(value=None, maximum=None, message=None):
            if progress_callback is None:
                return
            numeric_value = None
            numeric_maximum = None
            try:
                if value is not None and maximum not in (None, 0):
                    ratio = min(max(float(value) / float(maximum), 0.0), 1.0)
                    numeric_value = int(round(int(start) + (ratio * span)))
                    numeric_maximum = 100
                elif value is not None:
                    numeric_value = min(max(int(value), int(start)), int(end))
                    numeric_maximum = 100
            except Exception:
                numeric_value = None
                numeric_maximum = None
            progress_callback(
                value=numeric_value,
                maximum=numeric_maximum,
                message=str(message or ""),
            )

        return _report

    @staticmethod
    def _advance_task_ui_progress(
        ui_progress,
        *,
        value: int,
        message: str,
        maximum: int = 100,
    ) -> None:
        ui_progress.report_progress(value=int(value), maximum=int(maximum), message=message)
        app = QApplication.instance()
        if app is not None:
            app.processEvents()

    def _scaled_ui_progress_callback(self, ui_progress, *, start: int, end: int):
        span = max(0, int(end) - int(start))

        def _report(value=None, maximum=None, message=None):
            numeric_value = int(start)
            try:
                if value is not None and maximum not in (None, 0):
                    ratio = min(max(float(value) / float(maximum), 0.0), 1.0)
                    numeric_value = int(round(int(start) + (ratio * span)))
                elif value is not None:
                    numeric_value = min(max(int(value), int(start)), int(end))
            except Exception:
                numeric_value = int(start)
            self._advance_task_ui_progress(
                ui_progress,
                value=numeric_value,
                maximum=100,
                message=str(message or ""),
            )

        return _report

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
        worker_completion_progress: tuple[int, str] | None = None,
        on_success_before_cleanup=None,
        on_success=None,
        on_success_after_cleanup=None,
        on_error=None,
        on_cancelled=None,
        on_finished=None,
        on_progress=None,
        on_status=None,
    ):
        if requires_profile and not str(getattr(self, "current_db_path", "") or "").strip():
            self._play_warning_sound()
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
                    result = task_fn(ctx)
            else:
                ctx.raise_if_cancelled()
                result = task_fn(ctx)
            if worker_completion_progress is not None:
                progress_value, progress_message = worker_completion_progress
                ctx.report_progress(
                    value=int(progress_value),
                    maximum=100,
                    message=str(progress_message or ""),
                )
            return result

        return self.background_tasks.submit(
            title=title,
            description=description,
            task_fn=_wrapped_task,
            kind=kind,
            unique_key=unique_key,
            owner=owner or self,
            show_dialog=show_dialog,
            cancellable=cancellable,
            on_success_before_cleanup=on_success_before_cleanup,
            on_success=on_success,
            on_success_after_cleanup=on_success_after_cleanup,
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
        worker_completion_progress: tuple[int, str] | None = None,
        on_success_before_cleanup=None,
        on_success=None,
        on_success_after_cleanup=None,
        on_error=None,
        on_cancelled=None,
        on_finished=None,
        on_progress=None,
        on_status=None,
    ):
        def _bundle_task(ctx):
            with self.background_service_factory.open_bundle() as bundle:
                result = task_fn(bundle, ctx)
            if worker_completion_progress is not None:
                progress_value, progress_message = worker_completion_progress
                ctx.report_progress(
                    value=int(progress_value),
                    maximum=100,
                    message=str(progress_message or ""),
                )
            return result

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
            on_success_before_cleanup=on_success_before_cleanup,
            on_success=on_success,
            on_success_after_cleanup=on_success_after_cleanup,
            on_error=on_error,
            on_cancelled=on_cancelled,
            on_finished=on_finished,
            on_progress=on_progress,
            on_status=on_status,
        )

    # -------------------------------------------------------------------------
    # DB: open/init helpers + MIGRATIONS
    # -------------------------------------------------------------------------
    @staticmethod
    def _background_schema_audit_callback(conn):
        def _audit(action: str, entity: str, ref_id, details) -> None:
            try:
                conn.execute(
                    "INSERT INTO AuditLog (user, action, entity, ref_id, details) VALUES (?, ?, ?, ?, ?)",
                    (
                        None,
                        action,
                        entity,
                        str(ref_id) if ref_id is not None else None,
                        details,
                    ),
                )
            except Exception:
                pass

        return _audit

    def _prepare_database_session(self, path: str, *, progress_callback=None) -> str:
        return profile_session._prepare_database_session(
            self,
            path,
            progress_callback=progress_callback,
        )

    def _prepare_database_for_open_blocking(
        self,
        path: str,
        *,
        title: str,
        description: str,
    ) -> bool:
        return profile_session._prepare_database_for_open_blocking(
            self,
            path,
            title=title,
            description=description,
        )

    def open_database(
        self,
        path: str,
        *,
        schema_prepared: bool = False,
        progress_callback=None,
    ):
        return profile_session.open_database(
            self,
            path,
            schema_prepared=schema_prepared,
            progress_callback=progress_callback,
        )

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
        self._schedule_history_storage_budget_enforcement(trigger_label="history update")

    def _schedule_history_storage_budget_enforcement(self, *, trigger_label: str) -> None:
        return history_retention_controller._schedule_history_storage_budget_enforcement(
            self,
            trigger_label=trigger_label,
        )

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

    def _should_record_header_resize_history(self) -> bool:
        if getattr(self, "_suspend_layout_history", False):
            return False
        col_width_action = getattr(self, "col_width_action", None)
        if col_width_action is not None and not col_width_action.isChecked():
            return False
        try:
            return QApplication.mouseButtons() != Qt.NoButton
        except Exception:
            return False

    def _on_header_sections_resized(self, *_args):
        if not self._should_record_header_resize_history():
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
        moved_wrapper = getattr(self, "_header_section_moved_wrapper", None)
        resized_wrapper = getattr(self, "_header_section_resized_wrapper", None)
        try:
            header.sectionMoved.disconnect(moved_wrapper or self._on_header_sections_reordered)
        except (RuntimeError, TypeError):
            pass
        try:
            header.sectionResized.disconnect(resized_wrapper or self._on_header_sections_resized)
        except (RuntimeError, TypeError):
            pass
        self._header_section_moved_wrapper = None
        self._header_section_resized_wrapper = None
        self._header_layout_signals_bound = False

    def _bind_header_state_signals(self):
        if not hasattr(self, "table"):
            return
        header = self.table.horizontalHeader()
        self._unbind_header_state_signals()
        self._header_section_moved_wrapper = self._connect_args_signal(
            header.sectionMoved,
            header,
            self._on_header_sections_reordered,
        )
        self._header_section_resized_wrapper = self._connect_args_signal(
            header.sectionResized,
            header,
            self._on_header_sections_resized,
        )
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
            for i in range(self._catalog_view_column_count()):
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
            for i in range(self._catalog_view_column_count()):
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
            for i in range(self._catalog_view_row_count()):
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
        return main_window_layout._dock_state_setting_key()

    @staticmethod
    def _window_geometry_setting_key() -> str:
        return main_window_layout._window_geometry_setting_key()

    @staticmethod
    def _window_state_setting_key() -> str:
        return main_window_layout._window_state_setting_key()

    @staticmethod
    def _window_normal_geometry_setting_key() -> str:
        return main_window_layout._window_normal_geometry_setting_key()

    @staticmethod
    def _saved_main_window_layouts_setting_key() -> str:
        return main_window_layout._saved_main_window_layouts_setting_key()

    @staticmethod
    def _workspace_panels_setting_key() -> str:
        return main_window_layout._workspace_panels_setting_key()

    @staticmethod
    def _serialize_qbytearray_setting(value: QByteArray | None) -> str:
        return main_window_layout._serialize_qbytearray_setting(value)

    @staticmethod
    def _deserialize_qbytearray_setting(value) -> QByteArray:
        return main_window_layout._deserialize_qbytearray_setting(value)

    @staticmethod
    def _serialize_rect_setting(value: QRect | None) -> dict[str, int] | None:
        return main_window_layout._serialize_rect_setting(value)

    @staticmethod
    def _deserialize_rect_setting(value) -> QRect | None:
        return main_window_layout._deserialize_rect_setting(value)

    def _schedule_main_dock_state_save(self) -> None:
        return main_window_layout._schedule_main_dock_state_save(self)

    def _schedule_main_window_geometry_save(self) -> None:
        return main_window_layout._schedule_main_window_geometry_save(self)

    def _stop_queued_main_window_layout_persistence(self) -> None:
        return main_window_layout._stop_queued_main_window_layout_persistence(self)

    def _save_main_dock_state(self, *, sync: bool = True) -> None:
        return main_window_layout._save_main_dock_state(self, sync=sync)

    def _apply_main_dock_state_snapshot(self, state: QByteArray | None) -> bool:
        return main_window_layout._apply_main_dock_state_snapshot(self, state)

    def _restore_main_dock_state(self) -> bool:
        return main_window_layout._restore_main_dock_state(self)

    def _save_main_window_geometry(self, *, sync: bool = True) -> None:
        return main_window_layout._save_main_window_geometry(self, sync=sync)

    def _apply_main_window_geometry_snapshot(
        self,
        *,
        geometry: QByteArray | None,
        normal_geometry: QRect | None,
        window_state_marker: str,
    ) -> bool:
        return main_window_layout._apply_main_window_geometry_snapshot(
            self,
            geometry=geometry,
            normal_geometry=normal_geometry,
            window_state_marker=window_state_marker,
        )

    def _restore_main_window_geometry(self) -> bool:
        return main_window_layout._restore_main_window_geometry(self)

    def _current_main_window_state_marker(self) -> str:
        return main_window_layout._current_main_window_state_marker(self)

    def _load_saved_main_window_layouts(self) -> dict[str, dict[str, object]]:
        return main_window_layout._load_saved_main_window_layouts(self)

    def _write_saved_main_window_layouts(
        self, layouts: dict[str, dict[str, object]], *, sync: bool = True
    ) -> None:
        return main_window_layout._write_saved_main_window_layouts(self, layouts, sync=sync)

    def _load_workspace_panel_layouts(self) -> dict[str, dict[str, object]]:
        return main_window_layout._load_workspace_panel_layouts(self)

    def _write_workspace_panel_layouts(
        self, layouts: dict[str, dict[str, object]], *, sync: bool = True
    ) -> None:
        return main_window_layout._write_workspace_panel_layouts(self, layouts, sync=sync)

    def _capture_current_workspace_panel_layout_snapshot(self) -> dict[str, dict[str, object]]:
        return main_window_layout._capture_current_workspace_panel_layout_snapshot(self)

    def _contract_template_workspace_debug_summary(self) -> dict[str, object]:
        return main_window_layout._contract_template_workspace_debug_summary(self)

    def _log_contract_template_restore_checkpoint(self, event: str, **payload) -> None:
        return main_window_layout._log_contract_template_restore_checkpoint(self, event, **payload)

    def _schedule_contract_template_restore_debug_snapshots(
        self, *, event_prefix: str, layout_name: str
    ) -> None:
        return main_window_layout._schedule_contract_template_restore_debug_snapshots(
            self, event_prefix=event_prefix, layout_name=layout_name
        )

    def _apply_workspace_panel_layout_snapshot(self, snapshot: dict[str, object] | None) -> None:
        return main_window_layout._apply_workspace_panel_layout_snapshot(self, snapshot)

    def _saved_main_window_layout_names(self) -> list[str]:
        return main_window_layout._saved_main_window_layout_names(self)

    def _find_saved_main_window_layout_name(self, name: str) -> str | None:
        return main_window_layout._find_saved_main_window_layout_name(self, name)

    def _default_saved_main_window_layout_name(self) -> str:
        return main_window_layout._default_saved_main_window_layout_name(self)

    def _capture_current_main_window_layout_snapshot(self) -> dict[str, object]:
        return main_window_layout._capture_current_main_window_layout_snapshot(self)

    def _save_named_main_window_layout(self, name: str) -> str | None:
        return main_window_layout._save_named_main_window_layout(self, name)

    def _build_named_main_window_layout_switch_request(self, name: str) -> dict[str, object] | None:
        return main_window_layout._build_named_main_window_layout_switch_request(self, name)

    @staticmethod
    def _prepare_named_main_window_layout_switch_request(
        request: dict[str, object],
    ) -> dict[str, object] | None:
        return main_window_layout._prepare_named_main_window_layout_switch_request(request)

    def _suspend_saved_layout_transition_updates(self):
        return main_window_layout._suspend_saved_layout_transition_updates(self)

    def _apply_prepared_named_main_window_layout(
        self, prepared: dict[str, object], *, ui_progress=None
    ) -> bool:
        return main_window_layout._apply_prepared_named_main_window_layout(
            self, prepared, ui_progress=ui_progress
        )

    def _apply_named_main_window_layout(self, name: str) -> bool:
        return main_window_layout._apply_named_main_window_layout(self, name)

    def _start_named_main_window_layout_switch(self, name: str):
        return main_window_layout._start_named_main_window_layout_switch(self, name)

    def _delete_named_main_window_layout(self, name: str) -> bool:
        return main_window_layout._delete_named_main_window_layout(self, name)

    def _refresh_saved_layout_controls(self) -> None:
        return main_window_layout._refresh_saved_layout_controls(self)

    def _populate_saved_layouts_menu(self) -> None:
        return main_window_layout._populate_saved_layouts_menu(self)

    def add_named_main_window_layout(self) -> None:
        return main_window_layout.add_named_main_window_layout(self)

    def delete_named_main_window_layout_interactive(
        self, preferred_name: str | None = None
    ) -> None:
        return main_window_layout.delete_named_main_window_layout_interactive(self, preferred_name)

    def _on_saved_layout_selected(self, index: int) -> None:
        return main_window_layout._on_saved_layout_selected(self, index)

    def _store_workspace_panel_visibility_preferences(self, *, sync: bool = True) -> None:
        return main_window_layout._store_workspace_panel_visibility_preferences(self, sync=sync)

    def _sync_dock_visibility(self, action: QAction, setting_key: str, visible: bool) -> None:
        return main_window_layout._sync_dock_visibility(self, action, setting_key, visible)

    def _apply_add_data_panel_state(self, enabled: bool):
        return main_window_layout._apply_add_data_panel_state(self, enabled)

    def _apply_catalog_table_panel_state(self, enabled: bool):
        return main_window_layout._apply_catalog_table_panel_state(self, enabled)

    def _create_release_browser_panel(self, *args, **kwargs):
        return release_controller._create_release_browser_panel(self, *args, **kwargs)

    def _create_work_manager_panel(self, *args, **kwargs):
        return work_controller._create_work_manager_panel(self, *args, **kwargs)

    def _create_global_search_panel(self, parent: QWidget) -> GlobalSearchPanel:
        panel = GlobalSearchPanel(
            search_service_provider=lambda: self.global_search_service,
            relationship_service_provider=lambda: self.relationship_explorer_service,
            parent=parent,
        )
        panel.open_entity_requested.connect(self._open_entity_from_relationship_search)
        return panel

    def _create_diagnostics_catalog_cleanup_panel(
        self, parent: QWidget
    ) -> DiagnosticsCatalogCleanupPanel | None:
        if self.catalog_service is None:
            return None
        return DiagnosticsCatalogCleanupPanel(self, parent=parent)

    def _create_catalog_managers_panel(self, parent: QWidget) -> CatalogManagersPanel:
        return CatalogManagersPanel(self, parent=parent)

    def _create_party_manager_panel(self, *args, **kwargs):
        return party_controller._create_party_manager_panel(self, *args, **kwargs)

    def _create_contract_manager_panel(self, *args, **kwargs):
        return contract_controller._create_contract_manager_panel(self, *args, **kwargs)

    def _create_code_registry_workspace_panel(self, parent: QWidget) -> CodeRegistryWorkspacePanel:
        return CodeRegistryWorkspacePanel(
            service_provider=lambda: self.code_registry_service,
            parent=parent,
        )

    def _create_promo_code_ledger_panel(self, *args, **kwargs):
        return promo_code_controller._create_promo_code_ledger_panel(self, *args, **kwargs)

    def _create_contract_template_workspace_panel(self, *args, **kwargs):
        return contract_template_controller._create_contract_template_workspace_panel(
            self, *args, **kwargs
        )

    def _create_rights_matrix_panel(self, *args, **kwargs):
        return rights_controller._create_rights_matrix_panel(self, *args, **kwargs)

    def _create_asset_registry_panel(self, *args, **kwargs):
        return asset_controller._create_asset_registry_panel(self, *args, **kwargs)

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

    def _ensure_party_manager_dock(self, *args, **kwargs):
        return party_controller._ensure_party_manager_dock(self, *args, **kwargs)

    def _ensure_contract_manager_dock(self, *args, **kwargs):
        return contract_controller._ensure_contract_manager_dock(self, *args, **kwargs)

    def _ensure_code_registry_workspace_dock(self) -> QDockWidget:
        dock = ensure_catalog_workspace_dock(
            self,
            key="code_registry_workspace",
            title="Code Registry Workspace",
            object_name="codeRegistryWorkspaceDock",
            panel_factory=self._create_code_registry_workspace_panel,
        )
        self.code_registry_workspace_dock = dock
        return dock

    def _ensure_promo_code_ledger_dock(self, *args, **kwargs):
        return promo_code_controller._ensure_promo_code_ledger_dock(self, *args, **kwargs)

    def _ensure_contract_template_workspace_dock(self, *args, **kwargs):
        return contract_template_controller._ensure_contract_template_workspace_dock(
            self, *args, **kwargs
        )

    def _ensure_rights_matrix_dock(self, *args, **kwargs):
        return rights_controller._ensure_rights_matrix_dock(self, *args, **kwargs)

    def _ensure_asset_registry_dock(self, *args, **kwargs):
        return asset_controller._ensure_asset_registry_dock(self, *args, **kwargs)

    def _refresh_catalog_workspace_docks(self) -> None:
        refresh_catalog_workspace_docks(self)
        if hasattr(self, "identity"):
            self.identity = self._load_identity()
            self._apply_identity()

    @staticmethod
    def _party_identity_primary_label(*args, **kwargs):
        return party_controller._party_identity_primary_label(*args, **kwargs)

    @classmethod
    def _owner_party_choice_label(cls, *args, **kwargs):
        return party_controller._owner_party_choice_label(*args, **kwargs)

    def _current_owner_party_id(self, *args, **kwargs):
        return party_controller._current_owner_party_id(self, *args, **kwargs)

    def _current_owner_party_record(self, *args, **kwargs):
        return party_controller._current_owner_party_record(self, *args, **kwargs)

    def _default_authenticity_signer_label(self, *args, **kwargs):
        return authenticity_controller._default_authenticity_signer_label(self, *args, **kwargs)

    def _authenticity_signer_party_choices(self, *args, **kwargs):
        return authenticity_controller._authenticity_signer_party_choices(self, *args, **kwargs)

    @staticmethod
    def _legacy_owner_snapshot_has_data(*args, **kwargs):
        return party_controller._legacy_owner_snapshot_has_data(*args, **kwargs)

    @staticmethod
    def _owner_snapshot_name_candidates(*args, **kwargs):
        return party_controller._owner_snapshot_name_candidates(*args, **kwargs)

    @staticmethod
    def _owner_snapshot_to_party_payload(*args, **kwargs):
        return party_controller._owner_snapshot_to_party_payload(*args, **kwargs)

    @staticmethod
    def _merge_owner_snapshot_into_party(*args, **kwargs):
        return party_controller._merge_owner_snapshot_into_party(*args, **kwargs)

    def _assign_owner_party(self, *args, **kwargs):
        return party_controller._assign_owner_party(self, *args, **kwargs)

    def _migrate_legacy_owner_party_if_needed(self, *args, **kwargs):
        return party_controller._migrate_legacy_owner_party_if_needed(self, *args, **kwargs)

    def _owner_bootstrap_required(self, *args, **kwargs):
        return party_controller._owner_bootstrap_required(self, *args, **kwargs)

    def _schedule_owner_party_bootstrap(self, *args, **kwargs):
        return party_controller._schedule_owner_party_bootstrap(self, *args, **kwargs)

    def _ensure_owner_party_bootstrap(self, *args, **kwargs):
        return party_controller._ensure_owner_party_bootstrap(self, *args, **kwargs)

    def _ensure_persistent_workspace_dock_shells(self) -> None:
        return main_window_layout._ensure_persistent_workspace_dock_shells(self)

    def _restore_workspace_layout_on_first_show(self) -> None:
        return main_window_layout._restore_workspace_layout_on_first_show(self)

    def _materialize_visible_workspace_dock_panels(self, *, progress_callback=None) -> None:
        return main_window_layout._materialize_visible_workspace_dock_panels(
            self, progress_callback=progress_callback
        )

    def _validate_visible_workspace_dock_panels_after_restore(self) -> None:
        return main_window_layout._validate_visible_workspace_dock_panels_after_restore(self)

    def _refresh_workspace_dock_default_placement_flags(self) -> None:
        return main_window_layout._refresh_workspace_dock_default_placement_flags(self)

    @staticmethod
    def _action_shortcut_text(action: QAction | None) -> str:
        return action_ribbon._action_shortcut_text(action)

    def _initialize_action_ribbon_registry(self):
        return action_ribbon._initialize_action_ribbon_registry(self)

    def _action_ribbon_setting_keys(self) -> list[str]:
        return action_ribbon._action_ribbon_setting_keys(self)

    def _current_action_ribbon_visibility(self) -> bool:
        return action_ribbon._current_action_ribbon_visibility(self)

    @staticmethod
    def _normalize_action_ribbon_ids_for_known_ids(action_ids, known_action_ids) -> list[str]:
        return action_ribbon._normalize_action_ribbon_ids_for_known_ids(
            action_ids, known_action_ids
        )

    def _normalize_action_ribbon_ids(self, action_ids) -> list[str]:
        return action_ribbon._normalize_action_ribbon_ids(self, action_ids)

    def _load_saved_action_ribbon_action_ids(self) -> list[str]:
        return action_ribbon._load_saved_action_ribbon_action_ids(self)

    def _capture_current_action_ribbon_layout_snapshot(self) -> dict[str, object]:
        return action_ribbon._capture_current_action_ribbon_layout_snapshot(self)

    def _resolve_saved_layout_action_ribbon_snapshot(
        self, snapshot: dict[str, object]
    ) -> tuple[list[str], bool]:
        return action_ribbon._resolve_saved_layout_action_ribbon_snapshot(self, snapshot)

    @staticmethod
    def _resolve_saved_layout_action_ribbon_snapshot_payload(
        snapshot: dict[str, object],
        *,
        current_action_ids,
        current_visible: bool,
        default_action_ids,
        known_action_ids,
    ) -> tuple[list[str], bool]:
        return action_ribbon._resolve_saved_layout_action_ribbon_snapshot_payload(
            snapshot,
            current_action_ids=current_action_ids,
            current_visible=current_visible,
            default_action_ids=default_action_ids,
            known_action_ids=known_action_ids,
        )

    def _store_action_ribbon_preferences(
        self, action_ids, visible: bool, *, sync: bool = True
    ) -> None:
        return action_ribbon._store_action_ribbon_preferences(self, action_ids, visible, sync=sync)

    def _action_ribbon_button_tooltip(self, spec: dict) -> str:
        return action_ribbon._action_ribbon_button_tooltip(self, spec)

    def _build_saved_layout_ribbon_widget(self, parent: QWidget) -> QWidget:
        return action_ribbon._build_saved_layout_ribbon_widget(self, parent)

    def _rebuild_action_ribbon_toolbar(self):
        return action_ribbon._rebuild_action_ribbon_toolbar(self)

    def _apply_action_ribbon_configuration(self, action_ids: list[str], visible: bool):
        return action_ribbon._apply_action_ribbon_configuration(self, action_ids, visible)

    def _apply_profiles_toolbar_visibility(self, visible: bool) -> None:
        return action_ribbon._apply_profiles_toolbar_visibility(self, visible)

    def _open_action_ribbon_context_menu(self, pos):
        return action_ribbon._open_action_ribbon_context_menu(self, pos)

    def _apply_saved_view_preferences(self, *, apply_workspace_panel_visibility: bool = True):
        return main_window_layout._apply_saved_view_preferences(
            self, apply_workspace_panel_visibility=apply_workspace_panel_visibility
        )

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
            f"{prefix}/header_column_keys_json",
            f"{prefix}/hidden_columns_json",
            f"{prefix}/hidden_column_keys_json",
        ]
        if include_columns_movable:
            keys.append(f"{prefix}/columns_movable")
        return keys

    def _activate_profile(self, path: str, *, save_current_header: bool = True):
        return profile_session._activate_profile(
            self,
            path,
            save_current_header=save_current_header,
        )

    def _prepare_profile_database_background(
        self,
        path: str,
        *,
        title: str,
        description: str,
        show_dialog: bool = True,
        on_success,
        on_error=None,
        on_finished=None,
        progress_callback=None,
    ) -> str | None:
        return profile_session._prepare_profile_database_background(
            self,
            path,
            title=title,
            description=description,
            show_dialog=show_dialog,
            on_success=on_success,
            on_error=on_error,
            on_finished=on_finished,
            progress_callback=progress_callback,
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
        return profile_session._activate_profile_in_background(
            self,
            path,
            save_current_header=save_current_header,
            title=title,
            description=description,
            on_activated=on_activated,
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
        self._activate_profile_in_background(path)

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
    def load_isrc_prefix(self, *args, **kwargs):
        return isrc_registry_controller.load_isrc_prefix(self, *args, **kwargs)

    def load_active_custom_fields(self, *args, **kwargs):
        return custom_fields_controller.load_active_custom_fields(self, *args, **kwargs)

    def _profile_paths_for_isrc_registry(self, *args, **kwargs):
        return isrc_registry_controller._profile_paths_for_isrc_registry(self, *args, **kwargs)

    def _sync_application_isrc_registry(self, *args, **kwargs):
        return isrc_registry_controller._sync_application_isrc_registry(self, *args, **kwargs)

    @staticmethod
    def _format_isrc_registry_conflict(*args, **kwargs):
        return isrc_registry_controller._format_isrc_registry_conflict(*args, **kwargs)

    def _isrc_registry_conflict(self, *args, **kwargs):
        return isrc_registry_controller._isrc_registry_conflict(self, *args, **kwargs)

    def _reserve_isrc_claim_for_profile(self, *args, **kwargs):
        return isrc_registry_controller._reserve_isrc_claim_for_profile(self, *args, **kwargs)

    def _activate_isrc_claim_for_track(self, *args, **kwargs):
        return isrc_registry_controller._activate_isrc_claim_for_track(self, *args, **kwargs)

    def _release_reserved_isrc_claim(self, *args, **kwargs):
        return isrc_registry_controller._release_reserved_isrc_claim(self, *args, **kwargs)

    def _claim_next_generated_isrc(self, *args, **kwargs):
        return isrc_registry_controller._claim_next_generated_isrc(self, *args, **kwargs)

    def _isrc_generation_state(self, *args, **kwargs):
        return isrc_registry_controller._isrc_generation_state(self, *args, **kwargs)

    def _next_generated_isrc(self, *args, **kwargs):
        return isrc_registry_controller._next_generated_isrc(self, *args, **kwargs)

    # =============================================================================
    # UI helpers
    # =============================================================================
    @staticmethod
    def _create_add_data_group(
        title: str, description: str | None = None
    ) -> tuple[QGroupBox, QVBoxLayout]:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)
        if description:
            description_label = QLabel(description, group)
            description_label.setWordWrap(True)
            description_label.setProperty("role", "sectionDescription")
            layout.addWidget(description_label)
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

    def _preview_generated_isrc(self, *args, **kwargs):
        return isrc_registry_controller._preview_generated_isrc(self, *args, **kwargs)

    def _update_add_data_generated_fields(self, *args, **kwargs):
        return isrc_registry_controller._update_add_data_generated_fields(self, *args, **kwargs)

    def _initialize_catalog_table_model_view(self, *args, **kwargs):
        return catalog_workflow._initialize_catalog_table_model_view(self, *args, **kwargs)

    def _connect_catalog_selection_model(self, *args, **kwargs):
        return catalog_workflow._connect_catalog_selection_model(self, *args, **kwargs)

    def _catalog_zoom_controller(self) -> CatalogZoomController:
        controller = getattr(self, "_catalog_zoom_controller_instance", None)
        if not isinstance(controller, CatalogZoomController):
            controller = CatalogZoomController(self)
            self._connect_args_signal(
                controller.zoom_percent_changed,
                controller,
                self._sync_catalog_zoom_controls,
            )
            self._catalog_zoom_controller_instance = controller
        controller.bind_view(
            getattr(self, "table", None),
            apply_callback=self._apply_catalog_zoom_to_view,
        )
        return controller

    def _initialize_catalog_zoom_controls(self) -> None:
        slider = getattr(self, "catalog_zoom_slider", None)
        if slider is None:
            return
        slider.setRange(CATALOG_ZOOM_MIN_PERCENT, CATALOG_ZOOM_MAX_PERCENT)
        slider.setSingleStep(CATALOG_ZOOM_STEP_PERCENT)
        slider.setPageStep(CATALOG_ZOOM_STEP_PERCENT)
        controller = self._catalog_zoom_controller()
        if not getattr(self, "_catalog_zoom_slider_connected", False):
            self._connect_args_signal(
                slider.valueChanged,
                slider,
                self._on_catalog_zoom_slider_value_changed,
            )
            self._connect_noarg_signal(slider.sliderReleased, slider, self._flush_catalog_zoom)
            self._catalog_zoom_slider_connected = True
        self._sync_catalog_zoom_controls(controller.zoom_percent())
        controller.set_zoom_percent(controller.zoom_percent(), immediate=True)

    def _on_catalog_zoom_slider_value_changed(self, zoom_percent: int) -> None:
        controller = self._catalog_zoom_controller()
        controller.set_zoom_percent(int(zoom_percent), immediate=False)

    def _flush_catalog_zoom(self) -> None:
        controller = getattr(self, "_catalog_zoom_controller_instance", None)
        if isinstance(controller, CatalogZoomController):
            controller.flush_pending_apply()

    def _sync_catalog_zoom_controls(self, zoom_percent: int) -> None:
        normalized_zoom = CatalogZoomController.clamp_zoom_percent(zoom_percent)
        slider = getattr(self, "catalog_zoom_slider", None)
        if slider is not None:
            previous_state = slider.blockSignals(True)
            try:
                if slider.value() != normalized_zoom:
                    slider.setValue(normalized_zoom)
            finally:
                slider.blockSignals(previous_state)
        label = getattr(self, "catalog_zoom_value_label", None)
        if label is not None:
            label.setText(f"{normalized_zoom}%")
        decrease_button = getattr(self, "catalog_zoom_decrease_button", None)
        if decrease_button is not None:
            decrease_button.setEnabled(normalized_zoom > CATALOG_ZOOM_MIN_PERCENT)
        increase_button = getattr(self, "catalog_zoom_increase_button", None)
        if increase_button is not None:
            increase_button.setEnabled(normalized_zoom < CATALOG_ZOOM_MAX_PERCENT)

    @staticmethod
    def _scaled_catalog_zoom_font(base_font: QFont, zoom_percent: int) -> QFont:
        scale = max(0.01, float(zoom_percent) / 100.0)
        font = QFont(base_font)
        if font.pointSizeF() > 0:
            font.setPointSizeF(max(1.0, font.pointSizeF() * scale))
        elif font.pixelSize() > 0:
            font.setPixelSize(max(1, int(round(font.pixelSize() * scale))))
        return font

    def _catalog_zoom_base_metrics(self, view) -> dict[str, object]:
        metrics = getattr(self, "_catalog_zoom_metrics", None)
        if isinstance(metrics, dict):
            return metrics
        horizontal_header = view.horizontalHeader()
        vertical_header = view.verticalHeader()
        icon_size = view.iconSize()
        icon_extent = max(int(icon_size.width()), int(icon_size.height()), 18)
        header_height = max(
            int(horizontal_header.height()),
            int(horizontal_header.sizeHint().height()),
            24,
        )
        metrics = {
            "table_font": QFont(view.font()),
            "horizontal_header_font": QFont(horizontal_header.font()),
            "vertical_header_font": QFont(vertical_header.font()),
            "row_height": max(int(vertical_header.defaultSectionSize()), 24),
            "minimum_row_height": max(int(vertical_header.minimumSectionSize()), 18),
            "header_height": header_height,
            "icon_extent": icon_extent,
        }
        self._catalog_zoom_metrics = metrics
        return metrics

    def _apply_catalog_zoom_to_view(self, view, zoom_percent: int) -> None:
        if view is None:
            return
        normalized_zoom = CatalogZoomController.clamp_zoom_percent(zoom_percent)
        metrics = self._catalog_zoom_base_metrics(view)
        scale = float(normalized_zoom) / 100.0
        horizontal_header = view.horizontalHeader()
        vertical_header = view.verticalHeader()

        view.setFont(self._scaled_catalog_zoom_font(metrics["table_font"], normalized_zoom))
        horizontal_header.setFont(
            self._scaled_catalog_zoom_font(
                metrics["horizontal_header_font"],
                normalized_zoom,
            )
        )
        vertical_header.setFont(
            self._scaled_catalog_zoom_font(
                metrics["vertical_header_font"],
                normalized_zoom,
            )
        )

        row_height = max(18, int(round(int(metrics["row_height"]) * scale)))
        minimum_row_height = max(18, int(round(int(metrics["minimum_row_height"]) * scale)))
        header_height = max(24, int(round(int(metrics["header_height"]) * scale)))
        icon_extent = max(12, int(round(int(metrics["icon_extent"]) * scale)))

        vertical_header.setMinimumSectionSize(minimum_row_height)
        vertical_header.setDefaultSectionSize(row_height)
        horizontal_header.setMinimumHeight(header_height)
        view.setIconSize(QSize(icon_extent, icon_extent))
        view.updateGeometry()
        viewport = view.viewport()
        if viewport is not None:
            viewport.update()

    @staticmethod
    def _catalog_zoom_steps_from_wheel_event(event) -> int:
        pixel_delta = event.pixelDelta()
        angle_delta = event.angleDelta()
        if not pixel_delta.isNull():
            dominant = (
                pixel_delta.y() if abs(pixel_delta.y()) >= abs(pixel_delta.x()) else pixel_delta.x()
            )
            return int(round(dominant / 40.0))
        if not angle_delta.isNull():
            dominant = (
                angle_delta.y() if abs(angle_delta.y()) >= abs(angle_delta.x()) else angle_delta.x()
            )
            return int(round(dominant / 120.0))
        return 0

    def _handle_catalog_zoom_wheel_event(self, event) -> bool:
        modifiers = event.modifiers() if hasattr(event, "modifiers") else Qt.NoModifier
        if not modifiers & (Qt.ControlModifier | Qt.MetaModifier):
            return False
        steps = self._catalog_zoom_steps_from_wheel_event(event)
        if not steps:
            return False
        self._catalog_zoom_controller().step_zoom(steps, immediate=False)
        event.accept()
        return True

    def _handle_catalog_zoom_native_gesture_event(self, event) -> bool:
        gesture_type = event.gestureType() if hasattr(event, "gestureType") else None
        if gesture_type == Qt.ZoomNativeGesture:
            value = float(event.value() if hasattr(event, "value") else 0.0)
            if abs(value) < 0.0001:
                return False
            self._catalog_zoom_controller().apply_pinch_scale(1.0 + value, immediate=True)
            event.accept()
            return True
        if gesture_type == Qt.SmartZoomNativeGesture:
            self._catalog_zoom_controller().reset_zoom(immediate=True)
            event.accept()
            return True
        return False

    def _handle_catalog_zoom_pinch_gesture_event(self, event) -> bool:
        if not hasattr(event, "gesture"):
            return False
        pinch = event.gesture(Qt.PinchGesture)
        if pinch is None:
            return False
        if not pinch.changeFlags() & QPinchGesture.ScaleFactorChanged:
            return False
        last_factor = float(pinch.lastScaleFactor() or 1.0)
        scale_factor = float(pinch.scaleFactor() or 1.0)
        factor = scale_factor if abs(last_factor) < 0.0001 else scale_factor / last_factor
        if abs(factor - 1.0) < 0.001:
            return False
        self._catalog_zoom_controller().apply_pinch_scale(factor, immediate=True)
        event.accept()
        return True

    def _handle_catalog_zoom_event(self, source, event) -> bool:
        table = getattr(self, "table", None)
        if table is None:
            return False
        viewport = table.viewport()
        if source not in (table, viewport):
            return False
        event_type = event.type()
        if event_type == QEvent.Wheel:
            return self._handle_catalog_zoom_wheel_event(event)
        if event_type == QEvent.NativeGesture:
            return self._handle_catalog_zoom_native_gesture_event(event)
        if event_type == QEvent.Gesture:
            if (
                getattr(self, "_catalog_zoom_gesture_platform", platform.system().lower())
                == "darwin"
            ):
                return False
            return self._handle_catalog_zoom_pinch_gesture_event(event)
        return False

    def _catalog_zoom_layout_state(self) -> dict[str, int]:
        return self._catalog_zoom_controller().layout_state()

    def _restore_catalog_zoom_layout_state(
        self,
        payload: dict[str, object] | None,
        *,
        immediate: bool = True,
    ) -> int:
        controller = self._catalog_zoom_controller()
        restored = controller.restore_layout_state(payload, immediate=immediate)
        self._sync_catalog_zoom_controls(restored)
        return restored

    def _reset_catalog_zoom_for_profile_change(self) -> int:
        controller = self._catalog_zoom_controller()
        restored = controller.on_profile_changed(immediate=True)
        self._sync_catalog_zoom_controls(restored)
        return restored

    def _catalog_source_model(self, *args, **kwargs):
        return catalog_workflow._catalog_source_model(self, *args, **kwargs)

    def _catalog_proxy_model(self, *args, **kwargs):
        return catalog_workflow._catalog_proxy_model(self, *args, **kwargs)

    def _catalog_view_row_count(self, *args, **kwargs):
        return catalog_workflow._catalog_view_row_count(self, *args, **kwargs)

    def _catalog_view_column_count(self, *args, **kwargs):
        return catalog_workflow._catalog_view_column_count(self, *args, **kwargs)

    def _catalog_header_text_for_column(self, *args, **kwargs):
        return catalog_workflow._catalog_header_text_for_column(self, *args, **kwargs)

    def _catalog_table_column_specs_for_fields(self, *args, **kwargs):
        return catalog_workflow._catalog_table_column_specs_for_fields(self, *args, **kwargs)

    def _rebuild_table_headers(self, *args, **kwargs):
        return catalog_workflow._rebuild_table_headers(self, *args, **kwargs)

    @staticmethod
    def _catalog_combo_values_from_connection(*args, **kwargs):
        return catalog_workflow._catalog_combo_values_from_connection(*args, **kwargs)

    def _apply_catalog_combo_values(self, *args, **kwargs):
        return catalog_workflow._apply_catalog_combo_values(self, *args, **kwargs)

    def populate_all_comboboxes(self, *args, **kwargs):
        return catalog_workflow.populate_all_comboboxes(self, *args, **kwargs)

    def _artist_lookup_values(self) -> list[str]:
        if self.conn is None:
            return []
        return list(self._catalog_combo_values_from_connection(self.conn).get("artists", []))

    @staticmethod
    def _populate_combobox(combo: QComboBox, items, allow_empty=False):
        combo.clear()
        if allow_empty:
            combo.addItem("")
        combo.addItems(items)
        comp = QCompleter(items)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        combo.setCompleter(comp)

    @staticmethod
    def _artist_party_primary_label(*args, **kwargs):
        return party_controller._artist_party_primary_label(*args, **kwargs)

    @classmethod
    def _artist_party_choice_label(cls, *args, **kwargs):
        return party_controller._artist_party_choice_label(*args, **kwargs)

    def _artist_party_records(self, *args, **kwargs):
        return party_controller._artist_party_records(self, *args, **kwargs)

    def _configure_artist_party_combo(self, *args, **kwargs):
        return party_controller._configure_artist_party_combo(self, *args, **kwargs)

    def _resolve_artist_party_choice(self, *args, **kwargs):
        return party_controller._resolve_artist_party_choice(self, *args, **kwargs)

    def _resolve_party_backed_artist_name(self, *args, **kwargs):
        return party_controller._resolve_party_backed_artist_name(self, *args, **kwargs)

    def _resolve_party_backed_additional_artist_names(self, *args, **kwargs):
        return party_controller._resolve_party_backed_additional_artist_names(self, *args, **kwargs)

    def _refresh_add_track_artist_party_choices(self, *args, **kwargs):
        return party_controller._refresh_add_track_artist_party_choices(self, *args, **kwargs)

    def _work_payload_from_track_seed(self, *args, **kwargs):
        return work_controller._work_payload_from_track_seed(self, *args, **kwargs)

    @staticmethod
    def _work_track_relationship_choices(*args, **kwargs):
        return work_controller._work_track_relationship_choices(*args, **kwargs)

    @staticmethod
    def _work_track_relationship_label(*args, **kwargs):
        return work_controller._work_track_relationship_label(*args, **kwargs)

    def _normalize_work_track_relationship(self, *args, **kwargs):
        return work_controller._normalize_work_track_relationship(self, *args, **kwargs)

    @staticmethod
    def _work_track_governance_modes(*args, **kwargs):
        return work_controller._work_track_governance_modes(*args, **kwargs)

    def _refresh_add_track_lookup_sources_preserving_text(self) -> None:
        self._refresh_add_track_artist_party_choices()
        if self.conn is None:
            return

        def _set_items_preserving_text(combo: QComboBox, values) -> None:
            clean_values: list[str] = []
            seen: set[str] = set()
            for value in values:
                clean_value = str(value or "").strip()
                if not clean_value or clean_value in seen:
                    continue
                seen.add(clean_value)
                clean_values.append(clean_value)
            current_text = str(combo.currentText() or "").strip()
            previous_state = combo.blockSignals(True)
            try:
                combo.clear()
                combo.setEditable(True)
                combo.setInsertPolicy(QComboBox.NoInsert)
                combo.addItem("")
                combo.addItems(clean_values)
                if current_text and combo.findText(current_text, Qt.MatchFixedString) < 0:
                    combo.addItem(current_text)
                combo.setCurrentText(current_text)
                completer = QCompleter(clean_values, combo)
                completer.setCaseSensitivity(Qt.CaseInsensitive)
                combo.setCompleter(completer)
            finally:
                combo.blockSignals(previous_state)

        album_combo = getattr(self, "album_title_field", None)
        upc_combo = getattr(self, "upc_field", None)
        genre_combo = getattr(self, "genre_field", None)
        catalog_field = getattr(self, "catalog_number_field", None)

        combo_values = self._catalog_combo_values_from_connection(self.conn)

        if isinstance(album_combo, QComboBox):
            _set_items_preserving_text(album_combo, combo_values.get("albums", []))
        if isinstance(upc_combo, QComboBox):
            _set_items_preserving_text(upc_combo, combo_values.get("upcs", []))
        if isinstance(genre_combo, QComboBox):
            _set_items_preserving_text(genre_combo, combo_values.get("genres", []))
        if catalog_field is not None and hasattr(catalog_field, "refresh"):
            current_catalog_number = (
                str(catalog_field.currentText() or "").strip()
                if hasattr(catalog_field, "currentText")
                else ""
            )
            catalog_field.refresh()
            catalog_field.setCurrentText(current_catalog_number)

    def _ensure_add_track_panel_initialized(self) -> None:
        if not hasattr(self, "add_data_work_mode_combo"):
            return
        self._current_work_track_context()
        self._refresh_work_track_creation_context_ui()

        lookup_combos = (
            getattr(self, "album_title_field", None),
            getattr(self, "upc_field", None),
            getattr(self, "genre_field", None),
        )
        catalog_combo = getattr(getattr(self, "catalog_number_field", None), "combo", None)
        if any(isinstance(combo, QComboBox) and combo.count() == 0 for combo in lookup_combos) or (
            isinstance(catalog_combo, QComboBox) and catalog_combo.count() == 0
        ):
            self._refresh_add_track_lookup_sources_preserving_text()

    def _on_add_track_dock_visibility_changed(self, visible: bool) -> None:
        self._sync_dock_visibility(self.add_data_action, "display/add_data_panel", visible)
        if bool(visible):
            self._ensure_add_track_panel_initialized()

    def _default_work_track_context(self, *args, **kwargs):
        return work_controller._default_work_track_context(self, *args, **kwargs)

    def _set_pending_work_track_context(self, *args, **kwargs):
        return work_controller._set_pending_work_track_context(self, *args, **kwargs)

    def _current_work_track_context(self, *args, **kwargs):
        return work_controller._current_work_track_context(self, *args, **kwargs)

    def _available_work_records(self, *args, **kwargs):
        return work_controller._available_work_records(self, *args, **kwargs)

    @staticmethod
    def _work_choice_label(*args, **kwargs):
        return work_controller._work_choice_label(*args, **kwargs)

    def _focus_work_in_manager(self, *args, **kwargs):
        return work_controller._focus_work_in_manager(self, *args, **kwargs)

    def _reset_add_track_heading(self) -> None:
        self.add_data_title.setText("Add Track")
        self.add_data_subtitle.setText(
            "Add single-track musical entries here. Every new track must either link to an existing Work or create a new Work from the track before it can be saved."
        )
        self.save_button.setText("Create Work + Save Track")

    def _refresh_work_track_creation_context_ui(self, *args, **kwargs):
        return work_controller._refresh_work_track_creation_context_ui(self, *args, **kwargs)

    def _on_add_track_governance_mode_changed(self, *args, **kwargs):
        return work_controller._on_add_track_governance_mode_changed(self, *args, **kwargs)

    def _on_add_track_work_changed(self, *args, **kwargs):
        return work_controller._on_add_track_work_changed(self, *args, **kwargs)

    def _on_add_track_relationship_changed(self, *args, **kwargs):
        return work_controller._on_add_track_relationship_changed(self, *args, **kwargs)

    def _on_add_track_parent_track_changed(self, *args, **kwargs):
        return work_controller._on_add_track_parent_track_changed(self, *args, **kwargs)

    def _clear_work_track_creation_context(self, *args, **kwargs):
        return work_controller._clear_work_track_creation_context(self, *args, **kwargs)

    def _return_from_work_track_creation_context(self, *args, **kwargs):
        return work_controller._return_from_work_track_creation_context(self, *args, **kwargs)

    def open_add_track_entry(self) -> None:
        if self.track_service is None or self.conn is None:
            QMessageBox.warning(self, "Add Track", "Open a profile first.")
            return
        self._apply_add_data_panel_state(True)
        self._set_pending_work_track_context()
        self.clear_form_fields()
        self._refresh_work_track_creation_context_ui()
        self._show_add_track_details_tab()
        self.track_title_field.setFocus()

    def _begin_work_child_track_creation(self, *args, **kwargs):
        return work_controller._begin_work_child_track_creation(self, *args, **kwargs)

    def clear_form_fields(self):
        self.artist_field.setCurrentText("")
        self.additional_artist_field.setCurrentText("")
        self.track_title_field.clear()
        self.album_title_field.setCurrentText("")
        if hasattr(self, "track_number_field"):
            self.track_number_field.setValue(1)
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
    def _rebuild_search_column_choices(self, *args, **kwargs):
        return catalog_workflow._rebuild_search_column_choices(self, *args, **kwargs)

    def _selected_search_column_key(self, *args, **kwargs):
        return catalog_workflow._selected_search_column_key(self, *args, **kwargs)

    def _apply_catalog_search_filter(self, *args, **kwargs):
        return catalog_workflow._apply_catalog_search_filter(self, *args, **kwargs)

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

    def reset_search(self, *args, **kwargs):
        return catalog_workflow.reset_search(self, *args, **kwargs)

    def _set_catalog_filter_text(self, *args, **kwargs):
        return catalog_workflow._set_catalog_filter_text(self, *args, **kwargs)

    def _set_catalog_filter_from_current_cell(self, *args, **kwargs):
        return catalog_workflow._set_catalog_filter_from_current_cell(self, *args, **kwargs)

    def _load_catalog_ui_dataset(self, *args, **kwargs):
        return catalog_workflow._load_catalog_ui_dataset(self, *args, **kwargs)

    def _sort_value_for_catalog_cell(self, *args, **kwargs):
        return catalog_workflow._sort_value_for_catalog_cell(self, *args, **kwargs)

    def _catalog_cell_value(self, *args, **kwargs):
        return catalog_workflow._catalog_cell_value(self, *args, **kwargs)

    def _media_badge_cell_value(self, *args, **kwargs):
        return catalog_workflow._media_badge_cell_value(self, *args, **kwargs)

    def _catalog_snapshot_from_dataset(self, *args, **kwargs):
        return catalog_workflow._catalog_snapshot_from_dataset(self, *args, **kwargs)

    def _apply_catalog_model_dataset(self, *args, **kwargs):
        return catalog_workflow._apply_catalog_model_dataset(self, *args, **kwargs)

    def _capture_catalog_refresh_request(self, *args, **kwargs):
        return catalog_workflow._capture_catalog_refresh_request(self, *args, **kwargs)

    def _load_catalog_ui_dataset_from_bundle(self, *args, **kwargs):
        return catalog_workflow._load_catalog_ui_dataset_from_bundle(self, *args, **kwargs)

    def _apply_catalog_refresh_request(self, *args, **kwargs):
        return catalog_workflow._apply_catalog_refresh_request(self, *args, **kwargs)

    def _suspend_catalog_view_updates(self, *args, **kwargs):
        return catalog_workflow._suspend_catalog_view_updates(self, *args, **kwargs)

    def _catalog_repaint_targets(self, *args, **kwargs):
        return catalog_workflow._catalog_repaint_targets(self, *args, **kwargs)

    def _flush_pending_catalog_repaints(self, *args, **kwargs):
        return catalog_workflow._flush_pending_catalog_repaints(self, *args, **kwargs)

    def _refresh_catalog_ui_in_background(self, *args, **kwargs):
        return catalog_workflow._refresh_catalog_ui_in_background(self, *args, **kwargs)

    def refresh_table(self, *args, **kwargs):
        return catalog_workflow.refresh_table(self, *args, **kwargs)

    def _clear_catalog_table_model(self, *args, **kwargs):
        return catalog_workflow._clear_catalog_table_model(self, *args, **kwargs)

    def _sort_catalog_table(self, *args, **kwargs):
        return catalog_workflow._sort_catalog_table(self, *args, **kwargs)

    def _sync_catalog_count_label(self, *args, **kwargs):
        return catalog_workflow._sync_catalog_count_label(self, *args, **kwargs)

    def _sync_catalog_duration_label(self, *args, **kwargs):
        return catalog_workflow._sync_catalog_duration_label(self, *args, **kwargs)

    # --- Preserve view wrapper ---
    def _capture_view_state(self, *args, **kwargs):
        return catalog_workflow._capture_view_state(self, *args, **kwargs)

    def _restore_view_state(self, *args, **kwargs):
        return catalog_workflow._restore_view_state(self, *args, **kwargs)

    def _select_row_by_id(self, focus_id: int):
        controller = self._catalog_table_controller()
        index = controller.view_index_for_track_id(int(focus_id), column=0)
        if not index.isValid():
            return
        self.table.setCurrentIndex(index)
        selection_model = self.table.selectionModel()
        if selection_model is not None:
            selection_model.select(
                index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows
            )
        self.table.scrollTo(index, QAbstractItemView.PositionAtCenter)

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
            self._sync_catalog_count_label()

            if focus_id is not None:
                self._select_row_by_id(focus_id)

            # Restore sorting after refresh
            if _prev_sort_enabled:
                self.table.setSortingEnabled(True)
                self._sort_catalog_table(
                    state.get("sort_col", 0),
                    state.get("sort_order", Qt.AscendingOrder),
                )

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
            "Continue?\n\n- " + "\n- ".join(entries[:8]) + extra_note
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

    @staticmethod
    def _set_track_length_widgets(
        hours_widget,
        minutes_widget,
        seconds_widget,
        total_seconds: int,
    ) -> None:
        normalized_seconds = max(0, int(total_seconds or 0))
        hours = min(99, normalized_seconds // 3600)
        minutes = (normalized_seconds % 3600) // 60
        seconds = normalized_seconds % 60
        for widget, value in (
            (hours_widget, hours),
            (minutes_widget, minutes),
            (seconds_widget, seconds),
        ):
            previous_state = widget.blockSignals(True)
            try:
                widget.setValue(int(value))
            finally:
                widget.blockSignals(previous_state)

    def _apply_audio_duration_to_widgets(
        self,
        source_path: str | Path | None,
        *,
        hours_widget,
        minutes_widget,
        seconds_widget,
    ) -> int | None:
        if self.track_service is None:
            return None
        duration_seconds = self.track_service.derive_audio_duration_seconds(source_path)
        if duration_seconds is None:
            return None
        self._set_track_length_widgets(
            hours_widget,
            minutes_widget,
            seconds_widget,
            int(duration_seconds),
        )
        return int(duration_seconds)

    def _choose_media_into_line_edit(
        self,
        media_key: str,
        line_edit: QLineEdit,
        *,
        parent_widget=None,
        hours_widget=None,
        minutes_widget=None,
        seconds_widget=None,
    ) -> None:
        path = self._browse_track_media_file(media_key, parent_widget=parent_widget)
        if path:
            line_edit.setText(path)
            if media_key == "audio_file":
                self._refresh_line_edit_lossy_audio_warning(line_edit)
                if (
                    hours_widget is not None
                    and minutes_widget is not None
                    and seconds_widget is not None
                ):
                    self._apply_audio_duration_to_widgets(
                        path,
                        hours_widget=hours_widget,
                        minutes_widget=minutes_widget,
                        seconds_widget=seconds_widget,
                    )

    def _replace_additional_artists_for_track(self, track_id: int, names):
        self.track_service.replace_additional_artists(track_id, names, cursor=self.cursor)

    # =============================================================================
    # ISRC duplicate check across formats (uses new compact column)
    # =============================================================================
    def is_isrc_taken_normalized(self, *args, **kwargs):
        return isrc_registry_controller.is_isrc_taken_normalized(self, *args, **kwargs)

    @staticmethod
    def _normalize_track_number_value(value) -> int | None:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return None
        return normalized if normalized > 0 else None

    def _warn_duplicate_track_numbers(
        self,
        *,
        album_title: str | None,
        planned_rows: list[tuple[int | None, str | None]],
        exclude_track_ids=None,
        parent_widget: QWidget | None = None,
        title: str = "Duplicate Track Numbers",
        track_service: TrackService | None = None,
        cursor: sqlite3.Cursor | None = None,
    ) -> None:
        active_track_service = track_service or self.track_service
        clean_album_title = str(album_title or "").strip()
        if (
            active_track_service is None
            or is_blank(clean_album_title)
            or clean_album_title.casefold() == "single"
        ):
            return

        normalized_rows: list[tuple[int, str]] = []
        for index, (track_number, track_title) in enumerate(planned_rows, start=1):
            normalized_track_number = self._normalize_track_number_value(track_number)
            if normalized_track_number is None:
                continue
            clean_title = str(track_title or "").strip() or f"Track {index}"
            normalized_rows.append((normalized_track_number, clean_title))
        if not normalized_rows:
            return

        batch_duplicates: dict[int, list[str]] = {}
        for track_number, track_title in normalized_rows:
            batch_duplicates.setdefault(track_number, []).append(track_title)
        batch_duplicates = {
            track_number: titles
            for track_number, titles in batch_duplicates.items()
            if len(titles) > 1
        }

        existing_conflicts: dict[int, list[tuple[int, str]]] = {}
        for track_number, _track_title in normalized_rows:
            if track_number in existing_conflicts:
                continue
            conflicts = active_track_service.list_album_track_number_conflicts(
                clean_album_title,
                track_number,
                exclude_track_ids=exclude_track_ids,
                cursor=cursor,
            )
            if conflicts:
                existing_conflicts[track_number] = conflicts

        if not batch_duplicates and not existing_conflicts:
            return

        lines = [
            f"Album '{clean_album_title}' has duplicate stored track numbers.",
            "Saving is still allowed so you can keep adjusting the order freely.",
        ]
        if batch_duplicates:
            lines.append("")
            lines.append("This save contains duplicates:")
            for track_number, titles in sorted(batch_duplicates.items()):
                lines.append(f"- Track {track_number}: {', '.join(titles)}")
        if existing_conflicts:
            lines.append("")
            lines.append("Existing tracks on this album already use these numbers:")
            for track_number, conflicts in sorted(existing_conflicts.items()):
                labels = [
                    (
                        f'#{int(track_id)} "{track_title}"'
                        if str(track_title or "").strip()
                        else f"#{int(track_id)}"
                    )
                    for track_id, track_title in conflicts
                ]
                extra = ""
                if len(labels) > 4:
                    extra = f", and {len(labels) - 4} more"
                lines.append(f"- Track {track_number}: {', '.join(labels[:4])}{extra}")

        QMessageBox.warning(parent_widget or self, title, "\n".join(lines))

    # =============================================================================
    # Save / Edit / Delete
    # =============================================================================
    def save(self):
        work_track_context = self._current_work_track_context()
        if is_blank(self.track_title_field.text()) or is_blank(self.artist_field.currentText()):
            QMessageBox.warning(self, "Missing data", "Track Title and Artist are required.")
            return
        if (
            str(work_track_context.get("mode") or "create_new_work") == "link_existing_work"
            and work_track_context.get("work_id") is None
        ):
            QMessageBox.warning(
                self,
                "Missing Work",
                "Choose the existing Work that should govern this track, or switch the governance mode to create a new Work from the track.",
            )
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
            generation_ready = self._isrc_generation_state()[0] == "ready"

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
            selected_artist_name, selected_artist_party_id = self._resolve_artist_party_choice(
                self.artist_field
            )
            resolved_artist_name, _artist_party_id = self._resolve_party_backed_artist_name(
                selected_artist_name or self.artist_field.currentText(),
                selected_party_id=selected_artist_party_id,
                cursor=self.cursor,
            )
            resolved_additional_artists = self._resolve_party_backed_additional_artist_names(
                self._parse_additional_artists(self.additional_artist_field.currentText()),
                cursor=self.cursor,
            )
            self.artist_field.setCurrentText(resolved_artist_name)
            self.additional_artist_field.setCurrentText(", ".join(resolved_additional_artists))
            governance_mode = str(work_track_context.get("mode") or "create_new_work")
            payload = TrackCreatePayload(
                isrc=generated_iso,
                track_title=self.track_title_field.text().strip(),
                artist_name=resolved_artist_name,
                additional_artists=resolved_additional_artists,
                album_title=self.album_title_field.currentText().strip() or None,
                release_date=release_date_sql,
                track_length_sec=track_seconds,
                iswc=(iso_iswc or None),
                upc=(self.upc_field.currentText().strip() or None),
                genre=(self.genre_field.currentText().strip() or None),
                track_number=self.track_number_field.value(),
                catalog_number=(
                    self.catalog_number_field.identifier_value()
                    if hasattr(self.catalog_number_field, "identifier_value")
                    else (self.catalog_number_field.currentText().strip() or None)
                ),
                catalog_number_mode=(
                    self.catalog_number_field.identifier_mode()
                    if hasattr(self.catalog_number_field, "identifier_mode")
                    else None
                ),
                catalog_registry_entry_id=(
                    self.catalog_number_field.catalog_registry_entry_id()
                    if hasattr(self.catalog_number_field, "catalog_registry_entry_id")
                    else None
                ),
                catalog_external_code_identifier_id=(
                    self.catalog_number_field.external_code_identifier_id()
                    if hasattr(self.catalog_number_field, "external_code_identifier_id")
                    else None
                ),
                external_catalog_identifier_id=(
                    self.catalog_number_field.external_catalog_identifier_id()
                    if hasattr(self.catalog_number_field, "external_catalog_identifier_id")
                    else None
                ),
                buma_work_number=(self.buma_work_number_field.text().strip() or None),
                audio_file_source_path=(self.audio_file_field.text().strip() or None),
                album_art_source_path=(self.album_art_field.text().strip() or None),
            )
            if governance_mode == "link_existing_work":
                payload.work_id = int(work_track_context["work_id"])
                payload.parent_track_id = (
                    int(work_track_context["parent_track_id"])
                    if work_track_context.get("parent_track_id") is not None
                    else None
                )
                payload.relationship_type = str(
                    work_track_context.get("relationship_type") or "original"
                )
            else:
                payload.work_id = None
                payload.parent_track_id = None
                payload.relationship_type = "original"
            self._warn_duplicate_track_numbers(
                album_title=payload.album_title,
                planned_rows=[(payload.track_number, payload.track_title)],
                parent_widget=self,
                title="Duplicate Track Number",
                track_service=self.track_service,
                cursor=self.cursor,
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
            if generation_ready:
                generated_iso = self._claim_next_generated_isrc(
                    release_date=self.release_date_field.selectedDate(),
                    use_release_year=bool(self.prev_release_toggle.isChecked()),
                    track_title=payload.track_title,
                    parent_widget=self,
                )
                if not generated_iso:
                    QMessageBox.critical(
                        self,
                        "ISRC Error",
                        "No free ISRC sequence is currently available for the active year and artist code.",
                    )
                    return
                comp = to_compact_isrc(generated_iso)
                if not comp or not is_valid_isrc_compact_or_iso(generated_iso):
                    self._release_reserved_isrc_claim(generated_iso)
                    QMessageBox.critical(
                        self,
                        "ISRC Error",
                        "Generated ISRC is invalid. Check prefix and artist-code settings.",
                    )
                    return
                payload.isrc = generated_iso

            refresh_request = self._capture_catalog_refresh_request()
            action_label = (
                f"Create Work + Track: {payload.track_title}"
                if governance_mode == "create_new_work"
                else f"Create Track: {payload.track_title}"
            )
            action_type = (
                "track.create_governed" if governance_mode == "create_new_work" else "track.create"
            )
            profile_name = self._current_profile_name()

            def _worker(bundle, ctx):
                ctx.report_progress(
                    value=0,
                    maximum=100,
                    message="Saving track, media, and work governance...",
                )
                governed_service = GovernedImportCoordinator(
                    bundle.conn,
                    track_service=bundle.track_service,
                    party_service=bundle.party_service,
                    work_service=bundle.work_service,
                    profile_name=profile_name,
                )

                def _mutation():
                    cur = bundle.conn.cursor()
                    result = governed_service.create_governed_track(
                        payload,
                        cursor=cur,
                        governance_mode=governance_mode,
                        profile_name=profile_name,
                    )
                    created_track_id = int(result.track_id)
                    ctx.report_progress(
                        value=34,
                        maximum=100,
                        message="Synchronizing release records for the saved track...",
                    )
                    release_ids = self._sync_releases_for_tracks(
                        [created_track_id],
                        cursor=cur,
                        track_service=bundle.track_service,
                        release_service=bundle.release_service,
                        profile_name=profile_name,
                    )
                    return {
                        "work_id": int(result.work_id),
                        "track_id": created_track_id,
                        "release_ids": list(release_ids),
                    }

                result_payload = run_snapshot_history_action(
                    history_manager=bundle.history_manager,
                    action_label=action_label,
                    action_type=action_type,
                    entity_type="Track",
                    entity_id=payload.track_title,
                    payload={
                        "track_title": payload.track_title,
                        "artist_name": payload.artist_name,
                        "album_title": payload.album_title,
                        "created_work_from_track": governance_mode == "create_new_work",
                    },
                    mutation=_mutation,
                    progress_callback=ctx.report_progress,
                    post_mutation_progress=(48, "Capturing track-save history snapshot..."),
                    record_progress=(56, "Recording track-save history..."),
                    logger=self.logger,
                )
                ctx.report_progress(
                    value=60,
                    maximum=100,
                    message="Loading refreshed catalog rows, media badges, and lookup values...",
                )
                result_payload["dataset"] = self._load_catalog_ui_dataset_from_bundle(
                    bundle,
                    ctx,
                    progress_start=62,
                    progress_end=88,
                )
                return result_payload

            def _before_cleanup(result_payload: dict[str, object], ui_progress) -> None:
                try:
                    self.conn.commit()
                except Exception:
                    pass
                self._activate_isrc_claim_for_track(
                    generated_iso,
                    track_id=int(result_payload["track_id"]),
                    track_title=payload.track_title,
                    claim_kind="generated" if generation_ready else "profile_sync",
                )
                refresh_payload = dict(refresh_request)
                refresh_payload["focus_id"] = int(result_payload["track_id"])
                self._apply_catalog_refresh_request(
                    dict(result_payload.get("dataset") or {}),
                    refresh_payload,
                    progress_callback=self._scaled_ui_progress_callback(
                        ui_progress,
                        start=90,
                        end=97,
                    ),
                )
                self._advance_task_ui_progress(
                    ui_progress,
                    value=98,
                    message="Refreshing work manager and draft controls...",
                )
                self.clear_form_fields()
                if governance_mode == "create_new_work":
                    self._set_pending_work_track_context()
                self._refresh_work_track_creation_context_ui()
                self._refresh_work_manager_panel()
                if governance_mode == "create_new_work":
                    self._focus_work_in_manager(int(result_payload["work_id"]))
                self._advance_task_ui_progress(
                    ui_progress,
                    value=100,
                    message="Track saved and catalog UI is ready.",
                )

            def _after_cleanup(result_payload: dict[str, object]) -> None:
                work_id_for_refresh = int(result_payload["work_id"])
                track_id = int(result_payload["track_id"])
                release_ids = list(result_payload.get("release_ids") or [])
                if governance_mode == "create_new_work":
                    self._audit(
                        "CREATE",
                        "Work",
                        ref_id=work_id_for_refresh,
                        details=f"title={payload.track_title}",
                    )
                self._log_event(
                    "track.create",
                    "Track created",
                    track_id=track_id,
                    isrc=generated_iso,
                    track_title=payload.track_title,
                    release_ids=release_ids,
                )
                self._audit("CREATE", "Track", ref_id=track_id, details=f"isrc={generated_iso}")
                self._audit_commit()
                QMessageBox.information(self, "Success", "Track info saved successfully!")

            self._submit_background_bundle_task(
                title="Save Track",
                description="Saving track, media, and work governance...",
                task_fn=_worker,
                kind="write",
                unique_key=f"track.create.{payload.track_title.strip().casefold()}",
                owner=self,
                worker_completion_progress=(89, "Finalizing background track save..."),
                on_success_before_cleanup=_before_cleanup,
                on_success_after_cleanup=_after_cleanup,
                on_error=lambda failure: (
                    self._release_reserved_isrc_claim(generated_iso),
                    self._show_background_task_error(
                        "Save Track",
                        failure,
                        user_message="Failed to save record:",
                    ),
                ),
            )
        except sqlite3.IntegrityError as e:
            self.conn.rollback()
            self.logger.exception(f"Save failed (integrity): {e}")
            QMessageBox.critical(self, "Save Error", f"Database constraint error:\n{e}")
        except Exception as e:
            self.conn.rollback()
            self.logger.exception(f"Save failed: {e}")
            QMessageBox.critical(self, "Save Error", f"Failed to save record:\n{e}")

    def open_add_album_dialog(
        self,
        *,
        work_id: int | None = None,
        lock_work: bool = False,
        relationship_type: str | None = None,
        inherit_work_context: bool = True,
    ):
        current_context = self._current_work_track_context() if inherit_work_context else None
        effective_work_id = (
            int(work_id)
            if work_id is not None
            else (
                int(current_context["work_id"])
                if current_context is not None and current_context.get("work_id") is not None
                else None
            )
        )
        effective_relationship_type = (
            relationship_type
            if relationship_type is not None
            else (
                str(current_context.get("relationship_type") or "original")
                if current_context is not None
                else None
            )
        )
        dlg = AlbumEntryDialog(
            self,
            work_id=effective_work_id,
            lock_work=bool(lock_work and effective_work_id is not None),
            relationship_type=effective_relationship_type,
        )
        dlg.exec()

    def open_add_album_dialog_for_work(self, *args, **kwargs):
        return work_controller.open_add_album_dialog_for_work(self, *args, **kwargs)

    def open_track_editor(
        self,
        track_id: int,
        *,
        batch_track_ids: list[int] | None = None,
        initial_focus_target: str | None = None,
    ):
        try:
            dlg = EditDialog(
                int(track_id),
                self,
                batch_track_ids=batch_track_ids,
                initial_focus_target=initial_focus_target,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Edit Track", str(exc))
            return
        dlg.exec()
        self.populate_all_comboboxes()

    def open_selected_editor(
        self,
        track_id: int | None = None,
        *,
        initial_focus_target: str | None = None,
    ):
        if isinstance(track_id, bool):
            track_id = None
        if track_id is None:
            selected_ids = list(self._catalog_table_controller().selected_track_ids())
            if not selected_ids:
                QMessageBox.warning(
                    self,
                    "Edit Track",
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
                    "Edit Track",
                    "Could not determine the selected track. Select one or more catalog rows and try again.",
                )
                return
            batch_ids = list(self._catalog_table_controller().selected_track_ids())
            if track_id not in batch_ids:
                batch_ids = [track_id]
        self.open_track_editor(
            int(track_id),
            batch_track_ids=batch_ids,
            initial_focus_target=initial_focus_target,
        )

    def _current_catalog_context_track_id(self) -> int | None:
        controller = self._catalog_table_controller()
        track_id = controller.current_track_id()
        if track_id is not None:
            return int(track_id)
        selected_ids = list(controller.selected_track_ids())
        if selected_ids:
            return int(selected_ids[0])
        return None

    def open_album_track_ordering_dialog(self, track_id: int | None = None) -> None:
        if self.track_service is None or self.conn is None:
            QMessageBox.warning(self, "Album Track Ordering", "Open a profile first.")
            return
        if isinstance(track_id, bool):
            track_id = None
        if track_id is None:
            track_id = self._current_catalog_context_track_id()
        try:
            resolved_track_id = int(track_id or 0)
        except (TypeError, ValueError):
            resolved_track_id = 0
        if resolved_track_id <= 0:
            QMessageBox.information(
                self,
                "Album Track Ordering",
                "Select a catalog row that belongs to an album first.",
            )
            return

        try:
            album_snapshots = self.track_service.list_album_group_snapshots(
                resolved_track_id,
                include_media_blobs=False,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Album Track Ordering", str(exc))
            return

        if not album_snapshots:
            QMessageBox.information(
                self,
                "Album Track Ordering",
                "The selected track is not part of a saved album group.",
            )
            return

        album_title = str(album_snapshots[0].album_title or "").strip() or "Unnamed Album"
        dialog = AlbumTrackOrderingDialog(
            self,
            album_title=album_title,
            snapshots=album_snapshots,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        ordered_track_ids = dialog.ordered_track_ids()
        current_order = [int(snapshot.track_id) for snapshot in album_snapshots]
        order_already_sequential = all(
            self._normalize_track_number_value(snapshot.track_number) == index
            for index, snapshot in enumerate(album_snapshots, start=1)
        )
        if not ordered_track_ids or (
            ordered_track_ids == current_order and order_already_sequential
        ):
            if self.statusBar() is not None:
                self.statusBar().showMessage("Album track order unchanged.", 4000)
            return

        profile_name = self._current_profile_name()
        refresh_request = self._capture_catalog_refresh_request(focus_id=resolved_track_id)

        def _worker(bundle, ctx):
            total_tracks = max(1, len(ordered_track_ids))
            reorder_progress = self._scaled_progress_callback(
                ctx.report_progress,
                start=4,
                end=44,
            )
            ctx.report_progress(
                value=0,
                maximum=100,
                message="Preparing album track ordering update...",
            )

            def _mutation():
                with bundle.conn:
                    cur = bundle.conn.cursor()
                    for index, ordered_track_id in enumerate(ordered_track_ids, start=1):
                        reorder_progress(
                            index - 1,
                            total_tracks,
                            f"Saving reordered track {index} of {total_tracks}...",
                        )
                        snapshot = bundle.track_service.fetch_track_snapshot(
                            int(ordered_track_id),
                            cursor=cur,
                            include_media_blobs=False,
                        )
                        if snapshot is None:
                            raise ValueError(f"Track {int(ordered_track_id)} could not be loaded.")
                        payload = TrackUpdatePayload(
                            track_id=int(snapshot.track_id),
                            isrc=snapshot.isrc,
                            track_title=snapshot.track_title,
                            artist_name=snapshot.artist_name,
                            additional_artists=list(snapshot.additional_artists),
                            album_title=snapshot.album_title,
                            release_date=snapshot.release_date,
                            track_length_sec=int(snapshot.track_length_sec or 0),
                            iswc=snapshot.iswc,
                            upc=snapshot.upc,
                            genre=snapshot.genre,
                            track_number=index,
                            catalog_number=snapshot.catalog_number,
                            catalog_number_mode=snapshot.catalog_number_mode,
                            catalog_registry_entry_id=snapshot.catalog_registry_entry_id,
                            catalog_external_code_identifier_id=(
                                snapshot.catalog_external_code_identifier_id
                            ),
                            external_catalog_identifier_id=snapshot.external_catalog_identifier_id,
                            buma_work_number=snapshot.buma_work_number,
                            composer=snapshot.composer,
                            publisher=snapshot.publisher,
                            comments=snapshot.comments,
                            lyrics=snapshot.lyrics,
                            work_id=snapshot.work_id,
                            parent_track_id=snapshot.parent_track_id,
                            relationship_type=snapshot.relationship_type,
                            audio_file_source_path=None,
                            album_art_source_path=None,
                            clear_audio_file=False,
                            clear_album_art=False,
                        )
                        bundle.track_service.update_track(payload, cursor=cur)
                        reorder_progress(
                            index,
                            total_tracks,
                            f"Saved reordered track {index} of {total_tracks}.",
                        )
                    ctx.report_progress(
                        value=48,
                        maximum=100,
                        message="Synchronizing release records for the reordered album...",
                    )
                    release_ids = self._sync_releases_for_tracks(
                        ordered_track_ids,
                        cursor=cur,
                        track_service=bundle.track_service,
                        release_service=bundle.release_service,
                        profile_name=profile_name,
                    )
                    return {
                        "release_ids": list(release_ids),
                        "track_ids": list(ordered_track_ids),
                    }

            result_payload = run_snapshot_history_action(
                history_manager=bundle.history_manager,
                action_label=f"Album Track Ordering: {album_title}",
                action_type="track.album_order.update",
                entity_type="Album",
                entity_id=album_title,
                payload={
                    "album_title": album_title,
                    "track_ids": list(ordered_track_ids),
                },
                mutation=_mutation,
                progress_callback=ctx.report_progress,
                post_mutation_progress=(56, "Capturing album-order history snapshot..."),
                record_progress=(64, "Recording album-order history..."),
                logger=self.logger,
            )
            ctx.report_progress(
                value=68,
                maximum=100,
                message="Loading refreshed catalog rows, media badges, and lookup values...",
            )
            result_payload["dataset"] = self._load_catalog_ui_dataset_from_bundle(
                bundle,
                ctx,
                progress_start=70,
                progress_end=92,
            )
            return result_payload

        def _before_cleanup(result_payload: dict[str, object], ui_progress) -> None:
            try:
                self.conn.commit()
            except Exception:
                pass
            self._apply_catalog_refresh_request(
                dict(result_payload.get("dataset") or {}),
                refresh_request,
                progress_callback=self._scaled_ui_progress_callback(
                    ui_progress,
                    start=95,
                    end=99,
                ),
            )
            self._advance_task_ui_progress(
                ui_progress,
                value=100,
                message="Album track ordering saved and catalog UI is ready.",
            )

        def _after_cleanup(result_payload: dict[str, object]) -> None:
            release_ids = list(result_payload.get("release_ids") or [])
            self.populate_all_comboboxes()
            self._refresh_catalog_workspace_docks()
            self._log_event(
                "track.album_order.update",
                "Updated album track ordering",
                album_title=album_title,
                track_ids=list(ordered_track_ids),
                release_ids=release_ids,
            )
            if self.statusBar() is not None:
                self.statusBar().showMessage(
                    f'Updated album track ordering for "{album_title}".',
                    5000,
                )

        self._submit_background_bundle_task(
            title="Album Track Ordering",
            description="Saving album track ordering...",
            task_fn=_worker,
            kind="write",
            unique_key=f"track.album_order.update.{album_title.strip().casefold()}",
            owner=self,
            worker_completion_progress=(94, "Finalizing background album order update..."),
            on_success_before_cleanup=_before_cleanup,
            on_success_after_cleanup=_after_cleanup,
            on_error=lambda failure: self._show_background_task_error(
                "Album Track Ordering",
                failure,
                user_message="Could not save the album track order:",
            ),
        )

    def edit_entry(self, item):
        row_idx = item.row()
        column_idx = item.column() if hasattr(item, "column") else 0
        model = self.table.model()
        controller = self._catalog_table_controller()
        index = model.index(int(row_idx), int(column_idx)) if model is not None else None
        track_id = controller.track_id_for_index(index) if index is not None else None
        cell_target = controller.cell_target(
            index,
            base_column_count=len(self.BASE_HEADERS),
            custom_fields=self.active_custom_fields,
        )
        if track_id is None:
            QMessageBox.warning(self, "Edit Track", "Could not determine the selected track.")
            return
        self.open_selected_editor(
            track_id,
            initial_focus_target=self._catalog_editor_focus_target(cell_target),
        )

    def open_gs1_dialog(self, track_id: int | None = None):
        if isinstance(track_id, bool):
            track_id = None
        if track_id is None:
            selected_ids = list(self._catalog_table_controller().selected_track_ids())
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
                selected_ids = list(self._catalog_table_controller().selected_track_ids())
                if not selected_ids:
                    QMessageBox.warning(
                        self,
                        "GS1 Metadata",
                        "Could not determine the selected track. Select a catalog row and try again.",
                    )
                    return
                track_id = selected_ids[0]
            batch_ids = list(self._catalog_table_controller().selected_track_ids())
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

    def open_conversion_dialog(self, *args, **kwargs):
        return audio_conversion_controller.open_conversion_dialog(self, *args, **kwargs)

    def _start_conversion_export(self, *args, **kwargs):
        return audio_conversion_controller._start_conversion_export(self, *args, **kwargs)

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

    def _bulk_audio_attach_scope_track_ids(
        self, track_ids: list[int] | None = None
    ) -> tuple[list[int], str]:
        explicit_ids = self._normalize_track_ids(track_ids)
        if explicit_ids:
            return explicit_ids, "selected tracks"
        selected_ids = self._normalize_track_ids(
            self._catalog_table_controller().selected_track_ids()
        )
        if selected_ids:
            return selected_ids, "current selection"
        visible_ids = list(self._catalog_table_controller().visible_track_ids())
        if visible_ids:
            return visible_ids, "visible catalog rows"
        all_ids = [choice.track_id for choice in self._all_catalog_track_choices()]
        return self._normalize_track_ids(all_ids), "entire catalog"

    def _catalog_track_choices(self) -> list[TrackChoice]:
        controller = self._catalog_table_controller()
        model = controller.active_model()
        if model is None:
            return []
        title_column = controller.column_for_key("base:track_title")
        artist_column = controller.column_for_key("base:artist_name")
        album_column = controller.column_for_key("base:album_title")
        choices: list[TrackChoice] = []
        for row in range(model.rowCount()):
            row_index = model.index(row, 0)
            track_id = controller.track_id_for_index(row_index)
            if track_id is None:
                continue
            title = ""
            if title_column is not None:
                title = str(
                    model.data(model.index(row, title_column), Qt.DisplayRole) or ""
                ).strip()
            if not title:
                title = self._get_track_title(track_id)
            artist = (
                str(model.data(model.index(row, artist_column), Qt.DisplayRole) or "").strip()
                if artist_column is not None
                else ""
            )
            album = (
                str(model.data(model.index(row, album_column), Qt.DisplayRole) or "").strip()
                if album_column is not None
                else ""
            )
            subtitle = " / ".join(part for part in (artist, album) if part)
            choices.append(TrackChoice(track_id=int(track_id), title=title, subtitle=subtitle))
        return choices

    def _all_catalog_track_choices(
        self, *, conn: sqlite3.Connection | None = None
    ) -> list[TrackChoice]:
        active_conn = conn or self.conn
        if active_conn is None:
            return []
        main_artist_join_sql, main_artist_name_expr = track_main_artist_join_sql(
            active_conn,
            track_alias="t",
            artist_alias="main_artist",
        )
        rows = active_conn.execute(
            f"""
            SELECT
                t.id,
                COALESCE(t.track_title, ''),
                COALESCE({main_artist_name_expr}, ''),
                COALESCE(al.title, '')
            FROM Tracks t
            {main_artist_join_sql}
            LEFT JOIN Albums al ON al.id = t.album_id
            ORDER BY t.track_title COLLATE NOCASE, t.id
            """
        ).fetchall()
        choices: list[TrackChoice] = []
        for track_id, track_title, artist_name, album_title in rows:
            clean_title = str(track_title or "").strip() or f"Track {int(track_id)}"
            subtitle = " / ".join(
                part
                for part in (
                    str(artist_name or "").strip(),
                    str(album_title or "").strip(),
                )
                if part
            )
            choices.append(
                TrackChoice(track_id=int(track_id), title=clean_title, subtitle=subtitle)
            )
        return choices

    def _on_party_authority_changed(self, *args, **kwargs):
        return party_controller._on_party_authority_changed(self, *args, **kwargs)

    @staticmethod
    def _track_choice_tuple(choice: TrackChoice) -> tuple[int, str, str | None]:
        subtitle = str(choice.subtitle or "").strip()
        artist_name = subtitle.split(" / ", 1)[0].strip() if subtitle else None
        label = f"{int(choice.track_id)} - {choice.title}"
        if subtitle:
            label = f"{label} / {subtitle}"
        return int(choice.track_id), label, artist_name or None

    def _catalog_track_choice_tuples(
        self,
        *,
        include_hidden: bool = False,
        conn: sqlite3.Connection | None = None,
    ) -> list[tuple[int, str, str | None]]:
        choices = (
            self._all_catalog_track_choices(conn=conn)
            if include_hidden
            else self._catalog_track_choices()
        )
        return [self._track_choice_tuple(choice) for choice in choices]

    def _media_attach_track_candidates(
        self,
        track_ids,
        *,
        track_service: TrackService | None = None,
    ) -> list[BulkAudioAttachTrackCandidate]:
        active_track_service = track_service or self.track_service
        if active_track_service is None:
            return []
        candidates: list[BulkAudioAttachTrackCandidate] = []
        for track_id in self._normalize_track_ids(track_ids):
            snapshot = active_track_service.fetch_track_snapshot(int(track_id))
            if snapshot is None:
                continue
            candidates.append(
                BulkAudioAttachTrackCandidate(
                    track_id=snapshot.track_id,
                    title=snapshot.track_title,
                    artist=snapshot.artist_name,
                    album=snapshot.album_title,
                    isrc=snapshot.isrc,
                )
            )
        return candidates

    def _album_art_attach_track_ids(
        self,
        track_ids,
        *,
        track_service: TrackService | None = None,
    ) -> list[int]:
        active_track_service = track_service or self.track_service
        if active_track_service is None:
            return []
        allowed: list[int] = []
        for track_id in self._normalize_track_ids(track_ids):
            try:
                state = active_track_service.describe_album_art_edit_state(int(track_id))
            except Exception:
                continue
            if bool(getattr(state, "can_replace_directly", False)):
                allowed.append(int(track_id))
        return allowed

    @staticmethod
    def _normalize_media_attach_match_text(value: str | None) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()

    @staticmethod
    def _is_supported_media_attach_path(path: str, media_key: str) -> bool:
        suffix = Path(str(path or "")).suffix.lower()
        guessed_mime = str(mimetypes.guess_type(str(path or ""))[0] or "").strip().lower()
        if media_key == "audio_file":
            return suffix in BLOB_AUDIO_EXTS or guessed_mime.startswith("audio/")
        return suffix in BLOB_IMAGE_EXTS or guessed_mime.startswith("image/")

    def _prepare_media_attach_paths(
        self,
        media_key: str,
        raw_paths,
        *,
        title: str,
        allow_multiple: bool,
        ignored_message: str | None = None,
    ) -> list[str]:
        normalized_paths: list[str] = []
        seen: set[str] = set()
        for raw_path in raw_paths or []:
            clean = str(raw_path or "").strip()
            if not clean:
                continue
            path = str(Path(clean))
            if path in seen:
                continue
            seen.add(path)
            normalized_paths.append(path)
        supported_paths = [
            path
            for path in normalized_paths
            if Path(path).exists() and self._is_supported_media_attach_path(path, media_key)
        ]
        ignored_paths = [path for path in normalized_paths if path not in supported_paths]
        if ignored_paths and ignored_message:
            QMessageBox.information(
                self,
                title,
                ignored_message
                + "\n\nIgnored:\n- "
                + "\n- ".join(Path(path).name for path in ignored_paths[:12]),
            )
        if not supported_paths:
            QMessageBox.information(
                self,
                title,
                "No supported files were selected.",
            )
            return []
        if not allow_multiple and len(supported_paths) > 1:
            QMessageBox.information(
                self,
                title,
                "Only a single image file can be attached at a time.",
            )
            return []
        return supported_paths

    def _open_add_track_with_media_source(
        self,
        media_key: str,
        source_path: str,
    ) -> None:
        self.open_add_track_entry()
        if media_key == "audio_file":
            self.audio_file_field.setText(str(source_path or ""))
            self._refresh_line_edit_lossy_audio_warning(self.audio_file_field)
            self._apply_audio_duration_to_widgets(
                source_path,
                hours_widget=self.track_len_h,
                minutes_widget=self.track_len_m,
                seconds_widget=self.track_len_s,
            )
        else:
            self.album_art_field.setText(str(source_path or ""))
        self.track_title_field.setFocus()

    def _build_album_art_attach_plan(
        self,
        *,
        file_paths: list[str],
        tracks: list[BulkAudioAttachTrackCandidate],
        progress_callback=None,
    ) -> tuple[list[dict[str, object]], list[str]]:
        items: list[dict[str, object]] = []
        warnings: list[str] = []
        total = len(file_paths)
        for index, raw_path in enumerate(file_paths, start=1):
            path = Path(raw_path)
            if progress_callback is not None:
                progress_callback(
                    index - 1,
                    total,
                    f"Matching artwork file {index} of {total}: {path.name}",
                )
            item, warning = self._build_album_art_attach_item(path, tracks)
            items.append(item)
            if warning:
                warnings.append(warning)
        if progress_callback is not None:
            progress_callback(total, total, "Album art matching finished.")
        return items, warnings

    def _build_album_art_attach_item(
        self,
        path: Path,
        tracks: list[BulkAudioAttachTrackCandidate],
    ) -> tuple[dict[str, object], str | None]:
        title_candidates, stem_artist = BulkAudioAttachService._filename_candidates(path.stem)
        normalized_stem_artist = self._normalize_media_attach_match_text(stem_artist)
        best_tracks: list[BulkAudioAttachTrackCandidate] = []
        best_score = 0
        best_basis = ""
        for track in tracks:
            normalized_track_title = self._normalize_media_attach_match_text(track.title)
            normalized_album_title = self._normalize_media_attach_match_text(track.album)
            normalized_track_artist = self._normalize_media_attach_match_text(track.artist)
            for candidate, basis_label in title_candidates:
                normalized_candidate = self._normalize_media_attach_match_text(candidate)
                if not normalized_candidate:
                    continue
                score = 0
                basis = ""
                if normalized_album_title and normalized_candidate == normalized_album_title:
                    score = 260
                    basis = f"{basis_label} album title"
                elif normalized_track_title and normalized_candidate == normalized_track_title:
                    score = 220
                    basis = f"{basis_label} track title"
                if (
                    score > 0
                    and normalized_stem_artist
                    and normalized_track_artist
                    and normalized_stem_artist == normalized_track_artist
                ):
                    score += 25
                    basis = f"{basis} + artist"
                if score > best_score:
                    best_tracks = [track]
                    best_score = score
                    best_basis = basis
                elif score > 0 and score == best_score:
                    best_tracks.append(track)
        detected_album = title_candidates[0][0] if title_candidates else None
        if len(best_tracks) > 1 and best_score > 0:
            return (
                {
                    "source_path": str(path),
                    "source_name": path.name,
                    "detected_title": None,
                    "detected_artist": stem_artist,
                    "detected_album": detected_album,
                    "matched_track_id": None,
                    "match_basis": "Ambiguous artwork filename match",
                    "status": "ambiguous",
                    "warning": "",
                    "candidate_track_ids": [int(track.track_id) for track in best_tracks],
                },
                None,
            )
        if not best_tracks:
            return (
                {
                    "source_path": str(path),
                    "source_name": path.name,
                    "detected_title": None,
                    "detected_artist": stem_artist,
                    "detected_album": detected_album,
                    "matched_track_id": None,
                    "match_basis": "No confident catalog match",
                    "status": "unmatched",
                    "warning": "",
                    "candidate_track_ids": [],
                },
                None,
            )
        best_track = best_tracks[0]
        return (
            {
                "source_path": str(path),
                "source_name": path.name,
                "detected_title": None,
                "detected_artist": stem_artist,
                "detected_album": detected_album,
                "matched_track_id": int(best_track.track_id),
                "matched_track_artist": best_track.artist,
                "match_basis": best_basis,
                "status": "matched",
                "warning": "",
                "candidate_track_ids": [],
            },
            None,
        )

    def _select_track_ids_in_table(self, track_ids, *, replace: bool = True) -> None:
        normalized_ids = set(self._normalize_track_ids(track_ids))
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return
        if replace:
            self.table.clearSelection()
        controller = self._catalog_table_controller()
        current_index = None
        for track_id in normalized_ids:
            index = controller.view_index_for_track_id(track_id, column=0)
            if not index.isValid():
                continue
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
        self._apply_catalog_search_filter()
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
        self._apply_catalog_search_filter()
        if normalized_ids:
            self._select_track_ids_in_table(normalized_ids)
        elif self.table.model() is not None and self.table.model().rowCount() > 0:
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

    def _release_choices(self, *args, **kwargs):
        return release_controller._release_choices(self, *args, **kwargs)

    def _release_context_for_track(self, *args, **kwargs):
        return release_controller._release_context_for_track(self, *args, **kwargs)

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
    def _display_tag_value(*args, **kwargs):
        return metadata_controller._display_tag_value(*args, **kwargs)

    def _catalog_tag_data_for_track(self, *args, **kwargs):
        return metadata_controller._catalog_tag_data_for_track(self, *args, **kwargs)

    def _attempt_catalog_audio_export_metadata(self, *args, **kwargs):
        return metadata_controller._attempt_catalog_audio_export_metadata(self, *args, **kwargs)

    def _release_payload_for_track_ids(self, *args, **kwargs):
        return release_controller._release_payload_for_track_ids(self, *args, **kwargs)

    def _sync_releases_for_tracks(self, *args, **kwargs):
        return release_controller._sync_releases_for_tracks(self, *args, **kwargs)

    def open_add_track_workspace(self):
        self._apply_add_data_panel_state(True)
        self._ensure_add_track_panel_initialized()
        self._show_add_track_details_tab()
        field = getattr(self, "track_title_field", None)
        if field is not None:
            try:
                field.setFocus()
            except Exception:
                pass
        return getattr(self, "add_data_dock", None)

    def _show_add_track_details_tab(self) -> None:
        tabs = getattr(self, "add_data_tabs", None)
        if tabs is None:
            return
        try:
            track_index = int(getattr(self, "add_data_track_tab_index", 1))
            if 0 <= track_index < tabs.count():
                tabs.setCurrentIndex(track_index)
        except Exception:
            pass

    def open_catalog_workspace(self):
        self._apply_catalog_table_panel_state(True)
        table = getattr(self, "table", None)
        if table is not None:
            try:
                table.setFocus()
            except Exception:
                pass
        return getattr(self, "catalog_table_dock", None)

    def open_release_browser(self, *args, **kwargs):
        return release_controller.open_release_browser(self, *args, **kwargs)

    def _configure_work_manager_panel(self, *args, **kwargs):
        return work_controller._configure_work_manager_panel(self, *args, **kwargs)

    def open_work_manager(self, *args, **kwargs):
        return work_controller.open_work_manager(self, *args, **kwargs)

    def open_party_manager(self, *args, **kwargs):
        return party_controller.open_party_manager(self, *args, **kwargs)

    def open_contract_manager(self, *args, **kwargs):
        return contract_controller.open_contract_manager(self, *args, **kwargs)

    def open_code_registry_workspace(self):
        if self.code_registry_service is None:
            QMessageBox.warning(self, "Code Registry Workspace", "Open a profile first.")
            return
        return self._show_workspace_panel(
            self._ensure_code_registry_workspace_dock,
            panel_attr="code_registry_workspace_panel",
        )

    def open_promo_code_ledger(self, *args, **kwargs):
        return promo_code_controller.open_promo_code_ledger(self, *args, **kwargs)

    def import_bandcamp_promo_codes(self, *args, **kwargs):
        return promo_code_controller.import_bandcamp_promo_codes(self, *args, **kwargs)

    def update_promo_code_ledger(self, *args, **kwargs):
        return promo_code_controller.update_promo_code_ledger(self, *args, **kwargs)

    def _create_contract_with_history(self, *args, **kwargs):
        return contract_controller._create_contract_with_history(self, *args, **kwargs)

    def _update_contract_with_history(self, *args, **kwargs):
        return contract_controller._update_contract_with_history(self, *args, **kwargs)

    def _delete_contract_with_history(self, *args, **kwargs):
        return contract_controller._delete_contract_with_history(self, *args, **kwargs)

    def open_contract_template_workspace(self, *args, **kwargs):
        return contract_template_controller.open_contract_template_workspace(self, *args, **kwargs)

    def open_rights_matrix(self, *args, **kwargs):
        return rights_controller.open_rights_matrix(self, *args, **kwargs)

    def open_asset_registry(self, *args, **kwargs):
        return asset_controller.open_asset_registry(self, *args, **kwargs)

    def open_derivative_ledger(self, *args, **kwargs):
        return audio_conversion_controller.open_derivative_ledger(self, *args, **kwargs)

    def open_global_search(self):
        if self.global_search_service is None or self.relationship_explorer_service is None:
            QMessageBox.warning(self, "Global Search", "Open a profile first.")
            return
        return self._show_workspace_panel(
            self._ensure_global_search_dock,
            panel_attr="global_search_panel",
            legacy_attr="global_search_dialog",
        )

    def _open_entity_from_relationship_search(self, entity_type: str, entity_id: int):
        normalized = str(entity_type or "").strip().lower()
        if normalized == "track":
            self.open_selected_editor(int(entity_id))
            return
        if normalized == "release":
            self.open_release_editor(int(entity_id))
            return
        if normalized == "work":
            self.open_work_manager(work_id=int(entity_id))
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

    def _create_master_transfer_service_for_ui(self, *args, **kwargs):
        return master_transfer_controller._create_master_transfer_service_for_ui(
            self, *args, **kwargs
        )

    def _open_master_transfer_export_preview_dialog(self, *args, **kwargs):
        return master_transfer_controller._open_master_transfer_export_preview_dialog(
            self, *args, **kwargs
        )

    @staticmethod
    def _master_transfer_export_issue_prompt_lines(*args, **kwargs):
        return master_transfer_controller._master_transfer_export_issue_prompt_lines(
            *args, **kwargs
        )

    def export_master_transfer_package(self, *args, **kwargs):
        return master_transfer_controller.export_master_transfer_package(self, *args, **kwargs)

    def import_master_transfer_package(self, *args, **kwargs):
        return master_transfer_controller.import_master_transfer_package(self, *args, **kwargs)

    def export_repertoire_exchange(self, *args, **kwargs):
        return repertoire_controller.export_repertoire_exchange(self, *args, **kwargs)

    def import_repertoire_exchange(self, *args, **kwargs):
        return repertoire_controller.import_repertoire_exchange(self, *args, **kwargs)

    def _track_import_repair_entries(self, *args, **kwargs):
        return repair_queue_controller._track_import_repair_entries(self, *args, **kwargs)

    def _track_import_repair_work_choices(self, *args, **kwargs):
        return repair_queue_controller._track_import_repair_work_choices(self, *args, **kwargs)

    def _refresh_track_import_repair_queue_dialog(self, *args, **kwargs):
        return repair_queue_controller._refresh_track_import_repair_queue_dialog(
            self, *args, **kwargs
        )

    def _delete_track_import_repair_entries(self, *args, **kwargs):
        return repair_queue_controller._delete_track_import_repair_entries(self, *args, **kwargs)

    def _repair_track_import_queue_entry(self, *args, **kwargs):
        return repair_queue_controller._repair_track_import_queue_entry(self, *args, **kwargs)

    def open_track_import_repair_queue(self, *args, **kwargs):
        return repair_queue_controller.open_track_import_repair_queue(self, *args, **kwargs)

    def _selected_party_manager_ids(self, *args, **kwargs):
        return party_controller._selected_party_manager_ids(self, *args, **kwargs)

    def _open_import_review_dialog(self, *args, **kwargs):
        return exchange_controller._open_import_review_dialog(self, *args, **kwargs)

    @staticmethod
    def _party_import_review_summary(*args, **kwargs):
        return party_controller._party_import_review_summary(*args, **kwargs)

    @staticmethod
    def _exchange_import_review_summary(*args, **kwargs):
        return exchange_controller._exchange_import_review_summary(*args, **kwargs)

    @staticmethod
    def _repertoire_import_review_summary(*args, **kwargs):
        return repertoire_controller._repertoire_import_review_summary(*args, **kwargs)

    @staticmethod
    def _master_transfer_manifest_included_section_ids(*args, **kwargs):
        return master_transfer_controller._master_transfer_manifest_included_section_ids(
            *args, **kwargs
        )

    @staticmethod
    def _master_transfer_manifest_omitted_section_labels(*args, **kwargs):
        return master_transfer_controller._master_transfer_manifest_omitted_section_labels(
            *args, **kwargs
        )

    @staticmethod
    def _master_transfer_review_summary(*args, **kwargs):
        return master_transfer_controller._master_transfer_review_summary(*args, **kwargs)

    def _show_master_transfer_import_report(self, *args, **kwargs):
        return master_transfer_controller._show_master_transfer_import_report(self, *args, **kwargs)

    def _show_party_import_report(self, *args, **kwargs):
        return party_controller._show_party_import_report(self, *args, **kwargs)

    def import_party_exchange_file(self, *args, **kwargs):
        return party_controller.import_party_exchange_file(self, *args, **kwargs)

    def export_party_exchange_file(self, *args, **kwargs):
        return party_controller.export_party_exchange_file(self, *args, **kwargs)

    def open_release_editor(self, *args, **kwargs):
        return release_controller.open_release_editor(self, *args, **kwargs)

    def create_release_from_selection(self, *args, **kwargs):
        return release_controller.create_release_from_selection(self, *args, **kwargs)

    def _prompt_for_release_choice(self, *args, **kwargs):
        return release_controller._prompt_for_release_choice(self, *args, **kwargs)

    def add_selected_tracks_to_release(self, *args, **kwargs):
        return release_controller.add_selected_tracks_to_release(self, *args, **kwargs)

    def add_selected_tracks_to_specific_release(self, *args, **kwargs):
        return release_controller.add_selected_tracks_to_specific_release(self, *args, **kwargs)

    def _refresh_release_browser_panel(self, *args, **kwargs):
        return release_controller._refresh_release_browser_panel(self, *args, **kwargs)

    def _release_browser_task_owner(self, *args, **kwargs):
        return release_controller._release_browser_task_owner(self, *args, **kwargs)

    def _refresh_work_manager_panel(self, *args, **kwargs):
        return work_controller._refresh_work_manager_panel(self, *args, **kwargs)

    def _refresh_party_manager_panel(self, *args, **kwargs):
        return party_controller._refresh_party_manager_panel(self, *args, **kwargs)

    def _refresh_promo_code_ledger_panel(self, *args, **kwargs):
        return promo_code_controller._refresh_promo_code_ledger_panel(self, *args, **kwargs)

    def _work_manager_task_owner(self, *args, **kwargs):
        return work_controller._work_manager_task_owner(self, *args, **kwargs)

    def _delete_unused_albums_in_background(
        self,
        album_ids: list[int],
        *,
        owner: QWidget | None,
        title: str,
        description: str,
        action_label: str,
        action_type: str,
        on_ui_ready=None,
    ) -> None:
        target_ids = [int(album_id) for album_id in album_ids if int(album_id) > 0]
        if not target_ids:
            return

        def _worker(bundle, ctx):
            ctx.report_progress(
                value=0,
                maximum=100,
                message=description,
            )
            catalog_service = CatalogAdminService(bundle.conn)
            run_snapshot_history_action(
                history_manager=bundle.history_manager,
                action_label=action_label,
                action_type=action_type,
                entity_type="Album",
                entity_id="batch",
                payload={"album_ids": target_ids, "count": len(target_ids)},
                mutation=lambda: catalog_service.delete_albums(target_ids),
                progress_callback=ctx.report_progress,
                post_mutation_progress=(48, "Capturing album-cleanup history snapshot..."),
                record_progress=(56, "Recording album-cleanup history..."),
                logger=self.logger,
            )
            ctx.report_progress(
                value=60,
                maximum=100,
                message="Loading refreshed album lookup values...",
            )
            return {
                "combo_values": self._catalog_combo_values_from_connection(
                    bundle.conn,
                    progress_callback=self._scaled_progress_callback(
                        ctx.report_progress,
                        start=62,
                        end=88,
                    ),
                )
            }

        def _before_cleanup(result: dict[str, object], ui_progress) -> None:
            try:
                self.conn.commit()
            except Exception:
                pass
            self._advance_task_ui_progress(
                ui_progress,
                value=90,
                message="Applying refreshed album lookup values...",
            )
            self._apply_catalog_combo_values(dict(result.get("combo_values") or {}))
            self._refresh_add_track_artist_party_choices()
            self._refresh_work_track_creation_context_ui()
            self._refresh_history_actions()
            if callable(on_ui_ready):
                on_ui_ready()
            self._advance_task_ui_progress(
                ui_progress,
                value=100,
                message="Album cleanup complete and UI is ready.",
            )

        self._submit_background_bundle_task(
            title=title,
            description=description,
            task_fn=_worker,
            kind="write",
            unique_key=f"{action_type}.{','.join(str(album_id) for album_id in target_ids)}",
            owner=owner or self,
            worker_completion_progress=(89, "Finalizing background album cleanup..."),
            on_success_before_cleanup=_before_cleanup,
            on_error=lambda failure: self._show_background_task_error(
                title,
                failure,
                user_message="Could not update the stored album list:",
            ),
        )

    def create_work(self, *args, **kwargs):
        return work_controller.create_work(self, *args, **kwargs)

    def _open_work_creation_dialog(self, *args, **kwargs):
        return work_controller._open_work_creation_dialog(self, *args, **kwargs)

    def _launch_work_scoped_child_track_creation(self, *args, **kwargs):
        return work_controller._launch_work_scoped_child_track_creation(self, *args, **kwargs)

    def _current_work_manager_selected_work_id(self, *args, **kwargs):
        return work_controller._current_work_manager_selected_work_id(self, *args, **kwargs)

    def _adjacent_work_id_in_manager(self, *args, **kwargs):
        return work_controller._adjacent_work_id_in_manager(self, *args, **kwargs)

    def update_work(self, *args, **kwargs):
        return work_controller.update_work(self, *args, **kwargs)

    def duplicate_work(self, *args, **kwargs):
        return work_controller.duplicate_work(self, *args, **kwargs)

    def link_tracks_to_work(self, *args, **kwargs):
        return work_controller.link_tracks_to_work(self, *args, **kwargs)

    def delete_work(self, *args, **kwargs):
        return work_controller.delete_work(self, *args, **kwargs)

    def delete_release(self, *args, **kwargs):
        return release_controller.delete_release(self, *args, **kwargs)

    def duplicate_release(self, *args, **kwargs):
        return release_controller.duplicate_release(self, *args, **kwargs)

    def _build_tag_preview_rows(self, *args, **kwargs):
        return metadata_controller._build_tag_preview_rows(self, *args, **kwargs)

    def _prepare_tag_import_preview(self, *args, **kwargs):
        return metadata_controller._prepare_tag_import_preview(self, *args, **kwargs)

    @staticmethod
    def _iter_audio_tag_preview_fields(*args, **kwargs):
        return media_export_controller._iter_audio_tag_preview_fields(*args, **kwargs)

    def _build_tagged_audio_export_preview_rows(self, *args, **kwargs):
        return media_export_controller._build_tagged_audio_export_preview_rows(
            self, *args, **kwargs
        )

    @staticmethod
    def _tagged_audio_export_name(*args, **kwargs):
        return media_export_controller._tagged_audio_export_name(*args, **kwargs)

    def _prepare_tagged_audio_export_preview(self, *args, **kwargs):
        return media_export_controller._prepare_tagged_audio_export_preview(self, *args, **kwargs)

    def _build_tagged_audio_export_items(self, *args, **kwargs):
        return media_export_controller._build_tagged_audio_export_items(self, *args, **kwargs)

    def _apply_tag_patch_to_track(self, *args, **kwargs):
        return metadata_controller._apply_tag_patch_to_track(self, *args, **kwargs)

    @staticmethod
    def _dropped_audio_import_dialog_row(*args, **kwargs):
        return metadata_controller._dropped_audio_import_dialog_row(*args, **kwargs)

    @staticmethod
    def _materialize_artwork_payload(*args, **kwargs):
        return metadata_controller._materialize_artwork_payload(*args, **kwargs)

    def _build_dropped_audio_import_payloads(self, *args, **kwargs):
        return metadata_controller._build_dropped_audio_import_payloads(self, *args, **kwargs)

    def _create_tracks_from_dropped_audio_files(self, *args, **kwargs):
        return metadata_controller._create_tracks_from_dropped_audio_files(self, *args, **kwargs)

    def bulk_attach_audio_files(
        self,
        track_ids: list[int] | None = None,
        *,
        file_paths: list[str] | None = None,
        title: str = "Bulk Attach Audio Files",
    ):
        if self.audio_tag_service is None or self.track_service is None:
            QMessageBox.warning(self, title, "Open a profile first.")
            return

        scope_track_ids, scope_label = self._bulk_audio_attach_scope_track_ids(track_ids)
        chosen_files = list(file_paths or [])
        if not chosen_files:
            chosen_files, _selected_filter = QFileDialog.getOpenFileNames(
                self,
                "Choose Audio Files to Attach",
                str(self.data_root),
                (
                    "Audio Files (*.mp3 *.flac *.ogg *.oga *.opus *.m4a *.mp4 *.aac *.wav *.aif *.aiff);;"
                    "All Files (*)"
                ),
            )
        file_paths = self._prepare_media_attach_paths(
            "audio_file",
            chosen_files,
            title=title,
            allow_multiple=True,
            ignored_message=(
                "Only supported audio files can be attached in this workflow. "
                "Unsupported dropped or selected files were ignored."
            ),
        )
        if not file_paths:
            return
        if not scope_track_ids:
            self._create_tracks_from_dropped_audio_files(
                file_paths,
                title="Create Tracks from Audio Files",
            )
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
            all_track_choices = self._catalog_track_choice_tuples(
                include_hidden=True,
                conn=bundle.conn,
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
                "track_choices": all_track_choices,
                "scope_label": scope_label,
                "scope_track_count": len(track_candidates),
            }

        def _preview_success(result: dict[str, object]):
            plan = result.get("plan")
            track_choices = list(result.get("track_choices") or [])
            if plan is None:
                QMessageBox.information(
                    self,
                    title,
                    "The selected audio files could not be prepared for attachment.",
                )
                return
            if not track_choices:
                if len(file_paths) == 1 and (
                    QMessageBox.question(
                        self,
                        title,
                        "No existing catalog tracks are available for attachment.\n\n"
                        "Open Add Track with this audio file prefilled instead?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    )
                    == QMessageBox.Yes
                ):
                    self._open_add_track_with_media_source("audio_file", file_paths[0])
                else:
                    QMessageBox.information(
                        self,
                        title,
                        "No existing catalog tracks are available for attachment yet.",
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
                        "candidate_track_ids": list(getattr(item, "candidate_track_ids", []) or []),
                        "warning": "\n".join(warning_parts),
                    }
                )
            has_unresolved_audio = any(
                row.get("matched_track_id") in (None, "") for row in dialog_rows
            )
            dlg = BulkAudioAttachDialog(
                title=title,
                intro=(
                    f"Review {len(file_paths)} audio file(s) against "
                    f"{int(result.get('scope_track_count') or 0)} track(s) from the {result.get('scope_label') or scope_label}. "
                    "Review or reassign each file before anything is written."
                ),
                items=dialog_rows,
                track_choices=track_choices,
                media_label="audio file",
                suggested_artist=getattr(plan, "suggested_artist", None),
                party_service=self.party_service,
                default_storage_mode=STORAGE_MODE_MANAGED_FILE,
                attach_button_text="Attach Audio",
                create_track_button_text=(
                    "Create New Track from Unmatched…"
                    if len(file_paths) == 1
                    else "Create New Tracks from Unmatched…"
                ),
                allow_create_track=has_unresolved_audio,
                parent=self,
            )
            if dlg.exec() != QDialog.Accepted:
                return
            if dlg.create_track_requested():
                unmatched_paths = [
                    str(row.get("source_path") or "")
                    for row in dialog_rows
                    if row.get("matched_track_id") in (None, "")
                ]
                self._create_tracks_from_dropped_audio_files(
                    [path for path in unmatched_paths if path] or file_paths,
                    title="Create Tracks from Audio Files",
                )
                return

            assignments = dlg.selected_matches()
            if not self._confirm_lossy_primary_audio_selection(
                [str(item.get("source_path") or "") for item in assignments],
                title=title,
                action_label="Attaching these files",
            ):
                return
            storage_mode = dlg.selected_storage_mode()
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
                    title,
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
                    + ("\n\nWarnings:\n- " + "\n- ".join(warnings[:12]) if warnings else ""),
                )

            self._submit_background_bundle_task(
                title=title,
                description="Attaching the selected audio files to matched catalog tracks...",
                task_fn=_apply_worker,
                kind="write",
                unique_key="track.audio_file.bulk_attach",
                cancellable=False,
                on_success=_apply_success,
                on_error=lambda failure: self._show_background_task_error(
                    title,
                    failure,
                    user_message="Could not attach the selected audio files:",
                ),
            )

        self._submit_background_bundle_task(
            title=title,
            description="Matching selected audio files to catalog tracks...",
            task_fn=_preview_worker,
            kind="read",
            unique_key="track.audio_file.bulk_attach.preview",
            cancellable=False,
            on_success=_preview_success,
            on_error=lambda failure: self._show_background_task_error(
                title,
                failure,
                user_message="Could not prepare the bulk audio attach preview:",
            ),
        )

    def attach_album_art_file_to_catalog(
        self,
        track_ids: list[int] | None = None,
        *,
        file_paths: list[str] | None = None,
        title: str = "Attach Album Art File",
    ) -> None:
        if self.track_service is None:
            QMessageBox.warning(self, title, "Open a profile first.")
            return

        scope_track_ids, scope_label = self._bulk_audio_attach_scope_track_ids(track_ids)
        chosen_files = list(file_paths or [])
        if not chosen_files:
            chosen_path, _selected_filter = QFileDialog.getOpenFileName(
                self,
                "Choose Album Art File to Attach",
                str(self.data_root),
                self._media_file_filter("album_art"),
            )
            if chosen_path:
                chosen_files = [chosen_path]
        file_paths = self._prepare_media_attach_paths(
            "album_art",
            chosen_files,
            title=title,
            allow_multiple=False,
        )
        if not file_paths:
            return

        def _preview_worker(bundle, ctx):
            attachable_scope_ids = self._album_art_attach_track_ids(
                scope_track_ids,
                track_service=bundle.track_service,
            )
            total_tracks = len(attachable_scope_ids)
            track_candidates: list[BulkAudioAttachTrackCandidate] = []
            for index, track_id in enumerate(attachable_scope_ids, start=1):
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
                    maximum=max(1, total_tracks + len(file_paths)),
                    message=f"Loading track {index} of {total_tracks} for artwork matching...",
                )
            attachable_all_ids = self._album_art_attach_track_ids(
                [choice.track_id for choice in self._all_catalog_track_choices(conn=bundle.conn)],
                track_service=bundle.track_service,
            )
            all_track_choices = self._catalog_track_choice_tuples(
                include_hidden=True,
                conn=bundle.conn,
            )
            allowed_track_choice_ids = {int(track_id) for track_id in attachable_all_ids}
            filtered_track_choices = [
                choice for choice in all_track_choices if int(choice[0]) in allowed_track_choice_ids
            ]
            items, warnings = self._build_album_art_attach_plan(
                file_paths=file_paths,
                tracks=track_candidates,
                progress_callback=lambda value, maximum, message: ctx.report_progress(
                    value=total_tracks + value,
                    maximum=max(1, total_tracks + maximum),
                    message=message,
                ),
            )
            return {
                "items": items,
                "warnings": warnings,
                "track_choices": filtered_track_choices,
                "scope_label": scope_label,
                "scope_track_count": len(track_candidates),
            }

        def _preview_success(result: dict[str, object]) -> None:
            dialog_items = list(result.get("items") or [])
            track_choices = list(result.get("track_choices") or [])
            if not track_choices:
                if (
                    QMessageBox.question(
                        self,
                        title,
                        "No existing catalog tracks are available as direct album-art owners.\n\n"
                        "Open Add Track with this image prefilled instead?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    )
                    == QMessageBox.Yes
                ):
                    self._open_add_track_with_media_source("album_art", file_paths[0])
                return

            dlg = BulkAudioAttachDialog(
                title=title,
                intro=(
                    f"Review the selected image against "
                    f"{int(result.get('scope_track_count') or 0)} track(s) from the {result.get('scope_label') or scope_label}. "
                    "Confirm or reassign the target before artwork is attached."
                ),
                items=dialog_items,
                track_choices=track_choices,
                media_label="album art file",
                party_service=self.party_service,
                default_storage_mode=STORAGE_MODE_MANAGED_FILE,
                attach_button_text="Attach Artwork",
                allow_artist_name_update=False,
                allow_create_track=(len(file_paths) == 1),
                parent=self,
            )
            if dlg.exec() != QDialog.Accepted:
                return
            if dlg.create_track_requested():
                self._open_add_track_with_media_source("album_art", file_paths[0])
                return

            assignments = dlg.selected_matches()
            storage_mode = dlg.selected_storage_mode()
            skipped_count = max(0, len(file_paths) - len(assignments))
            plan_warnings = list(result.get("warnings") or [])

            def _apply_worker(bundle, ctx):
                total = max(1, len(assignments))

                def _mutation():
                    attached_track_ids: list[int] = []
                    with bundle.conn:
                        cur = bundle.conn.cursor()
                        for index, assignment in enumerate(assignments, start=1):
                            track_id = int(assignment["track_id"])
                            bundle.track_service.set_media_path(
                                track_id,
                                "album_art",
                                str(assignment["source_path"]),
                                storage_mode=storage_mode,
                                cursor=cur,
                            )
                            attached_track_ids.append(track_id)
                            ctx.report_progress(
                                value=index,
                                maximum=total,
                                message=f"Attaching artwork {index} of {total} to track {track_id}...",
                            )
                    return {"attached_track_ids": attached_track_ids}

                return run_snapshot_history_action(
                    history_manager=bundle.history_manager,
                    action_label=f"Attach Album Art ({len(assignments)} file{'s' if len(assignments) != 1 else ''})",
                    action_type="track.album_art.attach",
                    entity_type="Track",
                    entity_id="batch",
                    payload={
                        "track_ids": [int(item["track_id"]) for item in assignments],
                        "storage_mode": storage_mode,
                        "scope_label": scope_label,
                    },
                    mutation=_mutation,
                    logger=self.logger,
                )

            def _apply_success(result_payload: dict[str, object]) -> None:
                attached_track_ids = list(result_payload.get("attached_track_ids") or [])
                warnings = plan_warnings
                try:
                    self.conn.commit()
                except Exception:
                    pass
                self._refresh_history_actions()
                self._log_event(
                    "track.album_art.attach",
                    "Attached album art files",
                    track_ids=attached_track_ids,
                    skipped=skipped_count,
                    storage_mode=storage_mode,
                    scope_label=scope_label,
                    warnings=warnings,
                )
                self._audit(
                    "UPDATE",
                    "TrackAlbumArt",
                    ref_id="batch",
                    details=(
                        f"attached={len(attached_track_ids)}; "
                        f"skipped={skipped_count}; storage_mode={storage_mode}"
                    ),
                )
                self._audit_commit()
                self.refresh_table_preserve_view(
                    focus_id=attached_track_ids[0] if attached_track_ids else None
                )
                QMessageBox.information(
                    self,
                    title,
                    f"Attached artwork to {len(attached_track_ids)} track(s)."
                    + (
                        f"\nSkipped {skipped_count} file(s) left without a target."
                        if skipped_count
                        else ""
                    )
                    + ("\n\nWarnings:\n- " + "\n- ".join(warnings[:12]) if warnings else ""),
                )

            self._submit_background_bundle_task(
                title=title,
                description="Attaching the selected artwork to matched catalog tracks...",
                task_fn=_apply_worker,
                kind="write",
                unique_key="track.album_art.attach",
                cancellable=False,
                on_success=_apply_success,
                on_error=lambda failure: self._show_background_task_error(
                    title,
                    failure,
                    user_message="Could not attach the selected artwork file:",
                ),
            )

        self._submit_background_bundle_task(
            title=title,
            description="Matching the selected artwork file to catalog tracks...",
            task_fn=_preview_worker,
            kind="read",
            unique_key="track.album_art.attach.preview",
            cancellable=False,
            on_success=_preview_success,
            on_error=lambda failure: self._show_background_task_error(
                title,
                failure,
                user_message="Could not prepare the artwork attach preview:",
            ),
        )

    def import_tags_from_audio(self, *args, **kwargs):
        return metadata_controller.import_tags_from_audio(self, *args, **kwargs)

    def _audio_export_source_suffix(self, *args, **kwargs):
        return audio_conversion_controller._audio_export_source_suffix(self, *args, **kwargs)

    @staticmethod
    def _audio_export_source_label(*args, **kwargs):
        return audio_conversion_controller._audio_export_source_label(*args, **kwargs)

    def _audio_conversion_unavailable_message(self, *args, **kwargs):
        return audio_conversion_controller._audio_conversion_unavailable_message(
            self, *args, **kwargs
        )

    def _prompt_audio_conversion_format(self, *args, **kwargs):
        return audio_conversion_controller._prompt_audio_conversion_format(self, *args, **kwargs)

    def _selected_track_ids_with_audio(self, *args, **kwargs):
        return audio_conversion_controller._selected_track_ids_with_audio(self, *args, **kwargs)

    def convert_selected_audio(self, *args, **kwargs):
        return audio_conversion_controller.convert_selected_audio(self, *args, **kwargs)

    def export_forensic_watermarked_audio(self, *args, **kwargs):
        return forensic_controller.export_forensic_watermarked_audio(self, *args, **kwargs)

    def inspect_forensic_watermark(self, *args, **kwargs):
        return forensic_controller.inspect_forensic_watermark(self, *args, **kwargs)

    def convert_external_audio_files(self, *args, **kwargs):
        return audio_conversion_controller.convert_external_audio_files(self, *args, **kwargs)

    def export_catalog_audio_copies(self, *args, **kwargs):
        return media_export_controller.export_catalog_audio_copies(self, *args, **kwargs)

    def write_tags_to_exported_audio(self, *args, **kwargs):
        return media_export_controller.write_tags_to_exported_audio(self, *args, **kwargs)

    def open_audio_authenticity_keys_dialog(self, *args, **kwargs):
        return authenticity_controller.open_audio_authenticity_keys_dialog(self, *args, **kwargs)

    def export_authenticity_watermarked_audio(self, *args, **kwargs):
        return authenticity_controller.export_authenticity_watermarked_audio(self, *args, **kwargs)

    def export_authenticity_provenance_audio(self, *args, **kwargs):
        return authenticity_controller.export_authenticity_provenance_audio(self, *args, **kwargs)

    def _selected_track_audio_verification_option(self, *args, **kwargs):
        return authenticity_controller._selected_track_audio_verification_option(
            self, *args, **kwargs
        )

    def _selected_track_audio_verification_candidate(self, *args, **kwargs):
        return authenticity_controller._selected_track_audio_verification_candidate(
            self, *args, **kwargs
        )

    def _prompt_audio_authenticity_verification_source(self, *args, **kwargs):
        return authenticity_controller._prompt_audio_authenticity_verification_source(
            self, *args, **kwargs
        )

    def _pick_audio_authenticity_verification_file(self, *args, **kwargs):
        return authenticity_controller._pick_audio_authenticity_verification_file(
            self, *args, **kwargs
        )

    def verify_audio_authenticity(self, *args, **kwargs):
        return authenticity_controller.verify_audio_authenticity(self, *args, **kwargs)

    def import_exchange_file(self, *args, **kwargs):
        return exchange_controller.import_exchange_file(self, *args, **kwargs)

    def reset_saved_exchange_import_choices(self, *args, **kwargs):
        return exchange_controller.reset_saved_exchange_import_choices(self, *args, **kwargs)

    def _show_exchange_import_report(self, *args, **kwargs):
        return exchange_controller._show_exchange_import_report(self, *args, **kwargs)

    def export_exchange_file(self, *args, **kwargs):
        return exchange_controller.export_exchange_file(self, *args, **kwargs)

    def open_quality_dashboard(self, *args, **kwargs):
        return quality_controller.open_quality_dashboard(self, *args, **kwargs)

    def _scan_quality_dashboard_in_background(self, *args, **kwargs):
        return quality_controller._scan_quality_dashboard_in_background(self, *args, **kwargs)

    def _apply_quality_fix(self, *args, **kwargs):
        return quality_controller._apply_quality_fix(self, *args, **kwargs)

    def _open_issue_from_dashboard(self, *args, **kwargs):
        return quality_controller._open_issue_from_dashboard(self, *args, **kwargs)

    def delete_entry(self):
        current_index = self.table.currentIndex()
        if not current_index.isValid():
            QMessageBox.warning(self, "Warning", "No row selected for deletion!")
            return
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setText("Are you sure you want to delete this entry?")
        msg_box.setWindowTitle("Delete Track")
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        if msg_box.exec() == QMessageBox.Yes:
            try:
                controller = self._catalog_table_controller()
                visible_track_ids = list(controller.visible_track_ids())
                row_id = controller.track_id_for_index(current_index)
                if row_id is None:
                    QMessageBox.warning(self, "Delete", "Could not determine record ID.")
                    return
                next_focus_id = None
                try:
                    current_index = visible_track_ids.index(int(row_id))
                except ValueError:
                    current_index = -1
                if current_index >= 0:
                    remaining_ids = [
                        track_id for track_id in visible_track_ids if track_id != int(row_id)
                    ]
                    if current_index < len(remaining_ids):
                        next_focus_id = int(remaining_ids[current_index])
                    elif remaining_ids:
                        next_focus_id = int(remaining_ids[-1])
                before_snapshot = self.track_service.fetch_track_snapshot(row_id)
                if before_snapshot is None:
                    QMessageBox.warning(
                        self, "Delete", "Could not load the selected track for deletion."
                    )
                    return
                refresh_request = self._capture_catalog_refresh_request(focus_id=next_focus_id)

                def _worker(bundle, ctx):
                    ctx.report_progress(
                        value=0,
                        maximum=100,
                        message="Deleting the selected track and related history state...",
                    )
                    run_snapshot_history_action(
                        history_manager=bundle.history_manager,
                        action_label=f"Delete Track: {before_snapshot.track_title}",
                        action_type="track.delete",
                        entity_type="Track",
                        entity_id=row_id,
                        payload={
                            "track_id": row_id,
                            "track_title": before_snapshot.track_title,
                            "isrc": before_snapshot.isrc,
                        },
                        mutation=lambda: bundle.track_service.delete_track(row_id),
                        progress_callback=ctx.report_progress,
                        post_mutation_progress=(48, "Capturing track-delete history snapshot..."),
                        record_progress=(56, "Recording track-delete history..."),
                        logger=self.logger,
                    )
                    ctx.report_progress(
                        value=60,
                        maximum=100,
                        message="Loading refreshed catalog rows, media badges, and lookup values...",
                    )
                    return {
                        "dataset": self._load_catalog_ui_dataset_from_bundle(
                            bundle,
                            ctx,
                            progress_start=62,
                            progress_end=88,
                        )
                    }

                def _before_cleanup(result: dict[str, object], ui_progress) -> None:
                    try:
                        self.conn.commit()
                    except Exception:
                        pass
                    self._apply_catalog_refresh_request(
                        dict(result.get("dataset") or {}),
                        refresh_request,
                        progress_callback=self._scaled_ui_progress_callback(
                            ui_progress,
                            start=90,
                            end=99,
                        ),
                    )
                    self._advance_task_ui_progress(
                        ui_progress,
                        value=100,
                        message="Track deleted and catalog UI is ready.",
                    )

                def _after_cleanup(_result: dict[str, object]) -> None:
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

                self._submit_background_bundle_task(
                    title="Delete Track",
                    description="Deleting the selected track and refreshing the catalog...",
                    task_fn=_worker,
                    kind="write",
                    unique_key=f"track.delete.{int(row_id)}",
                    owner=self,
                    worker_completion_progress=(89, "Finalizing background track deletion..."),
                    on_success_before_cleanup=_before_cleanup,
                    on_success_after_cleanup=_after_cleanup,
                    on_error=lambda failure: self._show_background_task_error(
                        "Delete Track",
                        failure,
                        user_message="Failed to delete:",
                    ),
                )
            except Exception as e:
                self.conn.rollback()
                self.logger.exception(f"Delete failed: {e}")
                QMessageBox.critical(self, "Delete Error", f"Failed to delete:\n{e}")

    def init_form(self):
        self.refresh_table_preserve_view()
        self.populate_all_comboboxes()
        self.clear_form_fields()
        self._set_pending_work_track_context()
        self._refresh_work_track_creation_context_ui()

    # =============================================================================
    # Album autofill
    # =============================================================================
    def autofill_album_metadata(self, *args, **kwargs):
        return metadata_controller.autofill_album_metadata(self, *args, **kwargs)

    # =============================================================================
    # ISRC generation (YY + AA + SSS) with strict ISO compliance
    # =============================================================================
    def generate_isrc(self, *args, **kwargs):
        return isrc_registry_controller.generate_isrc(self, *args, **kwargs)

    # =============================================================================
    # Export / Import (with location picker, overwrite confirm, dry-run option)
    # =============================================================================
    def export_full_to_xml(self, *args, **kwargs):
        return catalog_xml_controller.export_full_to_xml(self, *args, **kwargs)

    def export_selected_to_xml(self, *args, **kwargs):
        return catalog_xml_controller.export_selected_to_xml(self, *args, **kwargs)

    def import_from_xml(self, *args, **kwargs):
        return catalog_xml_controller.import_from_xml(self, *args, **kwargs)

    # =============================================================================
    # Settings (prefix / numbers) + summary dialog
    # =============================================================================
    def set_isrc_prefix(self, *args, **kwargs):
        return isrc_registry_controller.set_isrc_prefix(self, *args, **kwargs)

    def set_sena_number(self, value: str | None = None):
        if value is None:
            self.open_settings_dialog(initial_focus="sena_number")
            return
        try:
            self._apply_single_setting_value("sena_number", (value or "").strip())
        except Exception as e:
            self.logger.exception(f"Set SENA number failed: {e}")
            QMessageBox.critical(self, "Error", f"Could not save SENA number:\n{e}")

    def _redirect_owner_registration_edit_to_party_manager(self, *args, **kwargs):
        return party_controller._redirect_owner_registration_edit_to_party_manager(
            self, *args, **kwargs
        )

    def set_btw_number(self, value: str | None = None):
        del value
        self._redirect_owner_registration_edit_to_party_manager("VAT / BTW Number")

    def set_buma_info(self, value: str | None = None):
        del value
        self._redirect_owner_registration_edit_to_party_manager("BUMA/STEMRA Relation Number")

    def set_ipi_info(self, value: str | None = None):
        del value
        self._redirect_owner_registration_edit_to_party_manager("BUMA/STEMRA IPI Number")

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
        return main_window_layout._on_toggle_col_width(self, enabled)

    def _on_toggle_row_height(self, enabled: bool):
        return main_window_layout._on_toggle_row_height(self, enabled)

    def _reset_hint_label(self):
        if self.col_hint_label:
            self.col_hint_label._user_moved = False
        if self.row_hint_label:
            self.row_hint_label._user_moved = False

    def _on_toggle_add_data(self, enabled: bool):
        return main_window_layout._on_toggle_add_data(self, enabled)

    def _on_toggle_profiles_toolbar(self, enabled: bool):
        return action_ribbon._on_toggle_profiles_toolbar(self, enabled)

    def _on_toggle_catalog_table(self, enabled: bool):
        return main_window_layout._on_toggle_catalog_table(self, enabled)

    def _on_toggle_action_ribbon(self, enabled: bool):
        return action_ribbon._on_toggle_action_ribbon(self, enabled)

    def open_action_ribbon_customizer(self):
        return action_ribbon.open_action_ribbon_customizer(self)

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
    def _custom_field_config_summary(self, *args, **kwargs):
        return custom_fields_controller._custom_field_config_summary(self, *args, **kwargs)

    def _apply_custom_field_configuration(self, *args, **kwargs):
        return custom_fields_controller._apply_custom_field_configuration(self, *args, **kwargs)

    def _prompt_new_custom_field(self, *args, **kwargs):
        return custom_fields_controller._prompt_new_custom_field(self, *args, **kwargs)

    def add_custom_column(self, *args, **kwargs):
        return custom_fields_controller.add_custom_column(self, *args, **kwargs)

    def remove_custom_column(self, *args, **kwargs):
        return custom_fields_controller.remove_custom_column(self, *args, **kwargs)

    def manage_custom_columns(self, *args, **kwargs):
        return custom_fields_controller.manage_custom_columns(self, *args, **kwargs)

    def _on_custom_fields_changed(self, *args, **kwargs):
        return custom_fields_controller._on_custom_fields_changed(self, *args, **kwargs)

    # ============================================================
    # Double-click editing: base vs custom fields
    # ============================================================
    @staticmethod
    def _catalog_editor_focus_target(*args, **kwargs):
        return custom_fields_controller._catalog_editor_focus_target(*args, **kwargs)

    def _on_catalog_index_double_clicked(self, *args, **kwargs):
        return custom_fields_controller._on_catalog_index_double_clicked(self, *args, **kwargs)

    # =============================================================================
    # Table context menu
    # =============================================================================
    def _on_catalog_table_context_menu(self, *args, **kwargs):
        return catalog_context_menu._on_catalog_table_context_menu(self, *args, **kwargs)

    def _preview_catalog_blob_for_cell(self, *args, **kwargs):
        return catalog_context_menu._preview_catalog_blob_for_cell(self, *args, **kwargs)

    def _do_prev(self, row, col):
        self._preview_catalog_blob_for_cell(
            row, col
        )  ############################################################################

    def _preview_blob_bytes(self, *args, **kwargs):
        return media_player_controller._preview_blob_bytes(self, *args, **kwargs)

    def _detect_mime(self, *args, **kwargs):
        return media_player_controller._detect_mime(self, *args, **kwargs)

    def _bring_media_window_to_front(self, *args, **kwargs):
        return media_player_controller._bring_media_window_to_front(self, *args, **kwargs)

    @staticmethod
    def _audio_preview_source_spec_for_standard_media(*args, **kwargs):
        return catalog_media_routing._audio_preview_source_spec_for_standard_media(*args, **kwargs)

    @staticmethod
    def _audio_preview_source_spec_for_custom_field(*args, **kwargs):
        return catalog_media_routing._audio_preview_source_spec_for_custom_field(*args, **kwargs)

    def _standard_media_column_key(self, *args, **kwargs):
        return catalog_media_routing._standard_media_column_key(self, *args, **kwargs)

    def _standard_media_key_for_column_key(self, *args, **kwargs):
        return catalog_media_routing._standard_media_key_for_column_key(self, *args, **kwargs)

    @staticmethod
    def _custom_field_column_key(*args, **kwargs):
        return catalog_media_routing._custom_field_column_key(*args, **kwargs)

    def _custom_field_for_column_key(self, *args, **kwargs):
        return catalog_media_routing._custom_field_for_column_key(self, *args, **kwargs)

    def _model_data_for_index(self, *args, **kwargs):
        return catalog_media_routing._model_data_for_index(self, *args, **kwargs)

    def _media_cell_has_payload(self, *args, **kwargs):
        return catalog_media_routing._media_cell_has_payload(self, *args, **kwargs)

    def _media_column_for_audio_source_spec(self, *args, **kwargs):
        return catalog_media_routing._media_column_for_audio_source_spec(self, *args, **kwargs)

    def _media_cell_has_payload_for_source_spec(self, *args, **kwargs):
        return catalog_media_routing._media_cell_has_payload_for_source_spec(self, *args, **kwargs)

    def _audio_preview_navigation_track_ids(self, *args, **kwargs):
        return media_player_controller._audio_preview_navigation_track_ids(self, *args, **kwargs)

    def _audio_preview_album_titles(self, *args, **kwargs):
        return media_player_controller._audio_preview_album_titles(self, *args, **kwargs)

    def _audio_preview_track_has_source_payload(self, *args, **kwargs):
        return media_player_controller._audio_preview_track_has_source_payload(
            self, *args, **kwargs
        )

    def _audio_preview_album_track_ids(self, *args, **kwargs):
        return media_player_controller._audio_preview_album_track_ids(self, *args, **kwargs)

    def _audio_preview_export_actions_for_track(self, *args, **kwargs):
        return media_player_controller._audio_preview_export_actions_for_track(
            self, *args, **kwargs
        )

    def _audio_preview_track_queue_items(self, *args, **kwargs):
        return media_player_controller._audio_preview_track_queue_items(self, *args, **kwargs)

    def _audio_preview_state_for_track(self, *args, **kwargs):
        return media_player_controller._audio_preview_state_for_track(self, *args, **kwargs)

    def _audio_preview_state_for_raw_bytes(self, *args, **kwargs):
        return media_player_controller._audio_preview_state_for_raw_bytes(self, *args, **kwargs)

    def _open_image_preview(self, *args, **kwargs):
        return media_player_controller._open_image_preview(self, *args, **kwargs)

    # =============================================================================
    # Copy selection helper
    # =============================================================================
    def _copy_selection_to_clipboard(self, include_headers: bool = False):
        view = self.table
        sel_model = view.selectionModel()
        model = view.model()
        if sel_model is None or model is None:
            QApplication.clipboard().setText("")
            return
        if not sel_model.hasSelection():
            view.selectAll()

        rows_out = []
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
                header_texts.append(str(model.headerData(c, Qt.Horizontal) or ""))
            rows_out.append("\t".join(header_texts))
        for r in range(r0, r1 + 1):
            line = []
            for c in range(c0, c1 + 1):
                idx = idx_set.get((r, c))
                if idx is None:
                    line.append("")
                else:
                    line.append(str(model.data(idx, Qt.DisplayRole) or ""))
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

    def _catalog_header_state_manager(
        self,
        *,
        path: str | None = None,
    ) -> CatalogHeaderStateManager:
        resolved_path = getattr(self, "current_db_path", "") if path is None else path
        return CatalogHeaderStateManager(
            self.settings,
            settings_prefix=self._table_settings_prefix_for_path(resolved_path or ""),
        )

    def _catalog_table_controller(self) -> CatalogTableController:
        controller = getattr(self, "_catalog_table_controller_instance", None)
        if controller is None:
            controller = CatalogTableController(self)
            self._catalog_table_controller_instance = controller
        table_model = self._catalog_source_model()
        filter_proxy = self._catalog_proxy_model()
        controller.bind_view(getattr(self, "table", None))
        controller.bind_models(table_model=table_model, filter_proxy=filter_proxy)
        return controller

    def _header_label_for_logical_index(self, logical_index: int) -> str:
        if not hasattr(self, "table"):
            return ""
        model = self.table.model()
        if model is None:
            return ""
        return str(model.headerData(logical_index, Qt.Horizontal, Qt.DisplayRole) or "")

    @staticmethod
    def _fallback_header_column_key(
        header_text: str,
        *,
        prefix: str,
        logical_index: int,
    ) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", str(header_text or "").strip().lower()).strip("_")
        if not slug:
            slug = "column"
        return f"{prefix}:{slug}:{logical_index}"

    def _catalog_header_column_specs(self) -> tuple[CatalogColumnSpec, ...]:
        if not hasattr(self, "table"):
            return ()

        column_specs: list[CatalogColumnSpec] = []
        table_column_count = self._catalog_view_column_count()
        base_column_count = min(len(self.BASE_HEADERS), table_column_count)
        default_hidden_names = {str(name).strip() for name in DEFAULT_HIDDEN_CUSTOM_COLUMN_NAMES}

        for logical_index in range(base_column_count):
            header_text = self._header_label_for_logical_index(logical_index)
            standard_spec = standard_field_spec_for_label(header_text)
            column_key = (
                f"base:{standard_spec.key}"
                if standard_spec is not None
                else self._fallback_header_column_key(
                    header_text,
                    prefix="base",
                    logical_index=logical_index,
                )
            )
            column_specs.append(
                CatalogColumnSpec(
                    key=column_key,
                    header_text=header_text,
                )
            )

        for logical_index in range(base_column_count, table_column_count):
            field_index = logical_index - len(self.BASE_HEADERS)
            header_text = self._header_label_for_logical_index(logical_index)
            field = (
                self.active_custom_fields[field_index]
                if 0 <= field_index < len(self.active_custom_fields)
                else {}
            )
            try:
                field_id = int(field.get("id"))
            except (TypeError, ValueError):
                field_id = None
            column_key = (
                f"custom:{field_id}"
                if field_id is not None and field_id > 0
                else self._fallback_header_column_key(
                    header_text,
                    prefix="custom",
                    logical_index=logical_index,
                )
            )
            column_specs.append(
                CatalogColumnSpec(
                    key=column_key,
                    header_text=header_text,
                    hidden_by_default=header_text in default_hidden_names,
                )
            )

        return tuple(column_specs)

    def _clear_table_settings_for_path(self, path: str) -> None:
        prefix = self._table_settings_prefix_for_path(path)
        for suffix in (
            "header_state",
            "header_labels",
            "header_labels_json",
            "header_column_keys_json",
            "hidden_columns_json",
            "hidden_column_keys_json",
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
            self._catalog_header_text_for_column(i)
            for i in range(self._catalog_view_column_count())
            if self._catalog_header_text_for_column(i)
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

        previous_suspend_state = self._suspend_layout_history
        self._suspend_layout_history = True
        try:
            self._catalog_header_state_manager().restore_visibility(
                self.table.horizontalHeader(),
                column_specs=self._catalog_header_column_specs(),
            )
        finally:
            self._suspend_layout_history = previous_suspend_state

    def _toggle_column_visibility(self, logical_index: int, visible: bool):
        if logical_index < 0 or logical_index >= self._catalog_view_column_count():
            return

        column_name = self._catalog_header_text_for_column(logical_index) or (
            f"Column {logical_index + 1}"
        )
        action_label = f"{'Show' if visible else 'Hide'} Column: {column_name}"

        def mutation():
            previous_suspend_state = self._suspend_layout_history
            self._suspend_layout_history = True
            try:
                self.table.setColumnHidden(logical_index, not visible)
                self._save_header_state(record_history=False)
                self._rebuild_search_column_choices()
                self._apply_catalog_search_filter()
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
            range(self._catalog_view_column_count()),
            key=lambda idx: (
                header.visualIndex(idx) if header.visualIndex(idx) >= 0 else 10_000 + idx
            ),
        )

        for logical_index in logical_indices:
            header_text = self._catalog_header_text_for_column(logical_index)
            if not header_text:
                continue
            action = QAction(header_text, self.columns_menu)
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
            if not hasattr(self, "table"):
                return

            def mutation():
                self._catalog_header_state_manager().save_state(
                    self.table.horizontalHeader(),
                    column_specs=self._catalog_header_column_specs(),
                )

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
        try:
            if not hasattr(self, "table"):
                return
            previous_suspend_state = self._suspend_layout_history
            self._suspend_layout_history = True
            try:
                # B1 compatibility wrapper: live header restore now routes
                # through CatalogHeaderStateManager with key-based preference.
                self._catalog_header_state_manager().restore_state(
                    self.table.horizontalHeader(),
                    column_specs=self._catalog_header_column_specs(),
                )
            finally:
                self._suspend_layout_history = previous_suspend_state
            if hasattr(self, "act_reorder_columns"):
                self._set_action_checked_silently(
                    self.act_reorder_columns,
                    bool(self.table.horizontalHeader().sectionsMovable()),
                )
            self._refresh_column_visibility_menu()
            self._rebuild_search_column_choices()
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

    def _configure_media_attach_drop_targets(self, *args, **kwargs):
        return catalog_media_routing._configure_media_attach_drop_targets(self, *args, **kwargs)

    def _drop_event_local_file_paths(self, *args, **kwargs):
        return catalog_media_routing._drop_event_local_file_paths(self, *args, **kwargs)

    def _partition_dropped_media_paths(self, *args, **kwargs):
        return catalog_media_routing._partition_dropped_media_paths(self, *args, **kwargs)

    def _route_dropped_media_paths(self, *args, **kwargs):
        return catalog_media_routing._route_dropped_media_paths(self, *args, **kwargs)

    def eventFilter(self, source, event):
        """Ensure we return a bool. Handle table key events here."""
        if event.type() == QEvent.Show and isinstance(source, QWidget):
            root = source.window() if hasattr(source, "window") else source
            if isinstance(root, QWidget):
                if self._ensure_widget_object_names(root):
                    self._repolish_widget_tree(root)
            return super().eventFilter(source, event)

        if self._handle_catalog_zoom_event(source, event):
            return True

        if isinstance(source, QWidget) and (source is self or self.isAncestorOf(source)):
            if event.type() in (QEvent.DragEnter, QEvent.DragMove):
                paths = self._drop_event_local_file_paths(event)
                audio_paths, image_paths, _unsupported_paths = self._partition_dropped_media_paths(
                    paths
                )
                if audio_paths or image_paths:
                    event.acceptProposedAction()
                    return True
            if event.type() == QEvent.Drop:
                paths = self._drop_event_local_file_paths(event)
                if paths:
                    event.acceptProposedAction()
                    return self._route_dropped_media_paths(paths)

        if source is getattr(self, "table", None) and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Space:
                idx = self.table.currentIndex()
                if idx.isValid():
                    self._preview_catalog_blob_for_cell(idx.row(), idx.column())
                event.accept()
                return True  # IMPORTANT: return bool to satisfy Qt
        # Defer to base for unhandled events
        return super().eventFilter(source, event)

    # =============================================================================
    # Edit Dialog (with Copy ISO / Copy compact buttons) + compact sync
    # =============================================================================

    # ---------------------- Standard track media helpers ----------------------
    @staticmethod
    def _standard_media_header_map(*args, **kwargs):
        return catalog_media_routing._standard_media_header_map(*args, **kwargs)

    @staticmethod
    def _standard_field_type_for_header(*args, **kwargs):
        return catalog_media_routing._standard_field_type_for_header(*args, **kwargs)

    def _standard_media_key_for_header(self, *args, **kwargs):
        return catalog_media_routing._standard_media_key_for_header(self, *args, **kwargs)

    def track_media_meta(self, *args, **kwargs):
        return catalog_media_routing.track_media_meta(self, *args, **kwargs)

    def track_has_media(self, *args, **kwargs):
        return catalog_media_routing.track_has_media(self, *args, **kwargs)

    def track_fetch_media(self, *args, **kwargs):
        return catalog_media_routing.track_fetch_media(self, *args, **kwargs)

    def track_set_media(self, *args, **kwargs):
        return catalog_media_routing.track_set_media(self, *args, **kwargs)

    def track_clear_media(self, *args, **kwargs):
        return catalog_media_routing.track_clear_media(self, *args, **kwargs)

    def track_convert_media_storage_mode(self, *args, **kwargs):
        return catalog_media_routing.track_convert_media_storage_mode(self, *args, **kwargs)

    def _media_player_default_track_id(self, *args, **kwargs):
        return media_player_controller._media_player_default_track_id(self, *args, **kwargs)

    def open_media_player(self, *args, **kwargs):
        return media_player_controller.open_media_player(self, *args, **kwargs)

    def _choose_track_media_storage_modes(self, *args, **kwargs):
        return catalog_media_routing._choose_track_media_storage_modes(self, *args, **kwargs)

    def _attach_standard_media_for_track(self, *args, **kwargs):
        return catalog_media_routing._attach_standard_media_for_track(self, *args, **kwargs)

    def _delete_standard_media_for_track(self, *args, **kwargs):
        return catalog_media_routing._delete_standard_media_for_track(self, *args, **kwargs)

    def _preview_standard_media_for_track(self, *args, **kwargs):
        return catalog_media_routing._preview_standard_media_for_track(self, *args, **kwargs)

    def _export_bytes_with_picker(self, *args, **kwargs):
        return media_export_controller._export_bytes_with_picker(self, *args, **kwargs)

    @staticmethod
    def _coerce_export_bytes(*args, **kwargs):
        return media_export_controller._coerce_export_bytes(*args, **kwargs)

    def _submit_background_audio_file_export(self, *args, **kwargs):
        return media_export_controller._submit_background_audio_file_export(self, *args, **kwargs)

    def _submit_background_audio_column_export(self, *args, **kwargs):
        return media_export_controller._submit_background_audio_column_export(self, *args, **kwargs)

    def _export_standard_media_for_track(self, *args, **kwargs):
        return media_export_controller._export_standard_media_for_track(self, *args, **kwargs)

    @staticmethod
    def _export_extension_for_mime(*args, **kwargs):
        return media_export_controller._export_extension_for_mime(*args, **kwargs)

    def _default_export_filename(self, *args, **kwargs):
        return media_export_controller._default_export_filename(self, *args, **kwargs)

    @staticmethod
    def _resolve_file_export_target(*args, **kwargs):
        return media_export_controller._resolve_file_export_target(*args, **kwargs)

    @staticmethod
    def _resolve_directory_export_target(*args, **kwargs):
        return media_export_controller._resolve_directory_export_target(*args, **kwargs)

    @staticmethod
    def _deduplicate_export_destination(*args, **kwargs):
        return media_export_controller._deduplicate_export_destination(*args, **kwargs)

    def _media_export_basename_for_track(self, *args, **kwargs):
        return media_export_controller._media_export_basename_for_track(self, *args, **kwargs)

    def _custom_blob_export_basename(self, *args, **kwargs):
        return media_export_controller._custom_blob_export_basename(self, *args, **kwargs)

    def _focused_media_export_spec(self, *args, **kwargs):
        return media_export_controller._focused_media_export_spec(self, *args, **kwargs)

    @staticmethod
    def _storage_conversion_action_label(target_mode: str, *, selection_count: int) -> str:
        clean_target = normalize_storage_mode(target_mode)
        if selection_count > 1:
            if clean_target == STORAGE_MODE_DATABASE:
                return "Store selection in database"
            return "Store selection as managed file"
        if clean_target == STORAGE_MODE_DATABASE:
            return "Store in Database"
        return "Store as Managed File"

    @staticmethod
    def _storage_conversion_target_label(target_mode: str) -> str:
        clean_target = normalize_storage_mode(target_mode)
        if clean_target == STORAGE_MODE_DATABASE:
            return "database storage"
        return "managed-file storage"

    def _classify_storage_conversion_scope(self, track_ids, *, meta_loader) -> dict[str, object]:
        normalized_ids = self._normalize_track_ids(track_ids or [])
        target_buckets = {
            STORAGE_MODE_DATABASE: {"convert_track_ids": [], "skip_track_ids": []},
            STORAGE_MODE_MANAGED_FILE: {"convert_track_ids": [], "skip_track_ids": []},
        }
        available_track_ids: list[int] = []
        missing_track_ids: list[int] = []
        modes_present: set[str] = set()
        for track_id in normalized_ids:
            try:
                meta = dict(meta_loader(int(track_id)) or {})
            except Exception:
                meta = {}
            has_payload = bool(meta.get("has_media") or meta.get("has_blob"))
            current_mode = normalize_storage_mode(meta.get("storage_mode"), default=None)
            if not has_payload or current_mode is None:
                missing_track_ids.append(int(track_id))
                continue
            available_track_ids.append(int(track_id))
            modes_present.add(current_mode)
            for target_mode, bucket in target_buckets.items():
                bucket_key = (
                    "skip_track_ids" if current_mode == target_mode else "convert_track_ids"
                )
                bucket[bucket_key].append(int(track_id))
        if modes_present == {STORAGE_MODE_MANAGED_FILE}:
            allowed_targets = [STORAGE_MODE_DATABASE]
        elif modes_present == {STORAGE_MODE_DATABASE}:
            allowed_targets = [STORAGE_MODE_MANAGED_FILE]
        elif modes_present:
            allowed_targets = [STORAGE_MODE_MANAGED_FILE, STORAGE_MODE_DATABASE]
        else:
            allowed_targets = []
        return {
            "scope_track_ids": normalized_ids,
            "available_track_ids": available_track_ids,
            "missing_track_ids": missing_track_ids,
            "modes_present": sorted(modes_present),
            "allowed_targets": allowed_targets,
            "targets": target_buckets,
        }

    def _standard_media_storage_conversion_scope(
        self,
        track_ids,
        media_key: str,
        *,
        track_service=None,
        cursor=None,
    ) -> dict[str, object]:
        service = track_service or self.track_service
        if service is None:
            return self._classify_storage_conversion_scope([], meta_loader=lambda _track_id: {})
        return self._classify_storage_conversion_scope(
            track_ids,
            meta_loader=lambda track_id: service.get_media_meta(
                int(track_id),
                media_key,
                cursor=cursor,
            ),
        )

    def _custom_blob_storage_conversion_scope(
        self,
        track_ids,
        field_id: int,
        *,
        custom_field_values=None,
    ) -> dict[str, object]:
        service = custom_field_values or self.custom_field_values
        if service is None:
            return self._classify_storage_conversion_scope([], meta_loader=lambda _track_id: {})
        return self._classify_storage_conversion_scope(
            track_ids,
            meta_loader=lambda track_id: service.get_value_meta(
                int(track_id),
                int(field_id),
                include_storage_details=True,
            ),
        )

    def _media_cell_has_payload_for_export_spec(self, *args, **kwargs):
        return media_export_controller._media_cell_has_payload_for_export_spec(
            self, *args, **kwargs
        )

    def _proxy_ordered_track_ids(self, *args, **kwargs):
        return media_export_controller._proxy_ordered_track_ids(self, *args, **kwargs)

    def _export_focused_media_column(self, *args, **kwargs):
        return media_export_controller._export_focused_media_column(self, *args, **kwargs)

    def _convert_standard_media_for_track(
        self, track_id: int | list[int], media_key: str, target_mode: str
    ) -> None:
        track_ids = track_id if isinstance(track_id, list) else [int(track_id)]
        column_label = "Audio File" if media_key == "audio_file" else "Album Art"
        self._submit_storage_conversion_task(
            track_ids=track_ids,
            target_mode=target_mode,
            scope_kind="standard",
            column_label=column_label,
            media_key=media_key,
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
        if self.cf_get_field_type(field_def_id) == "blob_audio":
            meta = self.cf_get_value_meta(
                track_id,
                field_def_id,
                include_storage_details=True,
            )
            if suggested_basename is None:
                suggested_basename = self.custom_field_definitions.get_field_name(field_def_id)
            default_filename = self._default_export_filename(
                suggested_basename,
                str(meta.get("mime_type") or ""),
            )
            dest_path, _ = QFileDialog.getSaveFileName(
                parent_widget or self,
                "Export file",
                default_filename,
                "All files (*)",
            )
            if not dest_path:
                return
            try:
                resolved_dest_path = self._resolve_file_export_target(
                    dest_path,
                    default_filename=default_filename,
                )
            except ValueError as exc:
                QMessageBox.warning(parent_widget or self, "Export", str(exc))
                return

            self._submit_background_audio_file_export(
                task_title="Export Audio File",
                task_description=("Exporting stored custom audio and recording export history..."),
                dialog_title="Export",
                resolved_dest_path=resolved_dest_path,
                action_label="Export Custom File: {filename}",
                action_type="file.export_custom_blob",
                entity_type="CustomFieldValue",
                entity_id=f"{track_id}:{field_def_id}",
                payload={"track_id": track_id, "field_id": field_def_id},
                load_source=lambda bundle: bundle.custom_field_values.fetch_blob(
                    int(track_id),
                    int(field_def_id),
                ),
                parent_widget=parent_widget or self,
            )
            return

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
        self, track_id: int | list[int], field_def_id: int, target_mode: str
    ) -> None:
        track_ids = track_id if isinstance(track_id, list) else [int(track_id)]
        field_name = self.custom_field_definitions.get_field_name(field_def_id)
        self._submit_storage_conversion_task(
            track_ids=track_ids,
            target_mode=target_mode,
            scope_kind="custom_blob",
            column_label=field_name,
            field_id=field_def_id,
        )

    def _storage_conversion_summary_lines(self, result: dict[str, object]) -> list[str]:
        column_label = str(result.get("column_label") or "media")
        target_label = self._storage_conversion_target_label(str(result.get("target_mode") or ""))
        converted_track_ids = list(result.get("converted_track_ids") or [])
        skipped_track_ids = list(result.get("skipped_track_ids") or [])
        missing_track_ids = list(result.get("missing_track_ids") or [])
        failures = list(result.get("failed") or [])
        if converted_track_ids:
            lines = [
                f"Converted {len(converted_track_ids)} selected track{'s' if len(converted_track_ids) != 1 else ''} to {target_label} for '{column_label}'."
            ]
        else:
            lines = [f"No selected tracks required conversion for '{column_label}'."]
        if skipped_track_ids:
            lines.append(
                f"Skipped {len(skipped_track_ids)} track{'s' if len(skipped_track_ids) != 1 else ''} already using {target_label}."
            )
        if missing_track_ids:
            lines.append(
                f"Skipped {len(missing_track_ids)} track{'s' if len(missing_track_ids) != 1 else ''} with no stored media in '{column_label}'."
            )
        if failures:
            lines.append("")
            lines.append(f"Failures ({len(failures)} track{'s' if len(failures) != 1 else ''}):")
            for entry in failures[:10]:
                label = str(entry.get("label") or f"Track {entry.get('track_id')}")
                message = str(entry.get("message") or "Unknown error")
                lines.append(f"- {label}: {message}")
        return lines

    def _submit_storage_conversion_task(
        self,
        *,
        track_ids: list[int],
        target_mode: str,
        scope_kind: str,
        column_label: str,
        media_key: str | None = None,
        field_id: int | None = None,
    ) -> None:
        normalized_track_ids = self._normalize_track_ids(track_ids)
        if not normalized_track_ids:
            return
        clean_target = normalize_storage_mode(target_mode)
        title = f"Convert {column_label} Storage"

        def _worker(bundle, ctx):
            ctx.report_progress(
                value=0,
                maximum=100,
                message="Collecting the selected tracks for storage conversion...",
            )
            if scope_kind == "standard":
                scope = self._standard_media_storage_conversion_scope(
                    normalized_track_ids,
                    str(media_key or ""),
                    track_service=bundle.track_service,
                    cursor=bundle.conn.cursor(),
                )
                action_type = (
                    f"track.{media_key}.bulk_convert_storage_mode"
                    if len(normalized_track_ids) > 1
                    else f"track.{media_key}.convert_storage_mode"
                )
                entity_type = "Track"
                entity_id = "batch" if len(normalized_track_ids) > 1 else normalized_track_ids[0]
            else:
                scope = self._custom_blob_storage_conversion_scope(
                    normalized_track_ids,
                    int(field_id or 0),
                    custom_field_values=bundle.custom_field_values,
                )
                action_type = (
                    "custom_field.blob_bulk_convert_storage_mode"
                    if len(normalized_track_ids) > 1
                    else "custom_field.blob_convert_storage_mode"
                )
                entity_type = "CustomFieldValue"
                entity_id = (
                    "batch"
                    if len(normalized_track_ids) > 1
                    else f"{normalized_track_ids[0]}:{int(field_id or 0)}"
                )
            ctx.report_progress(
                value=6,
                maximum=100,
                message="Classifying current media storage modes...",
            )
            conversion_plan = dict(scope["targets"][clean_target])
            result = {
                "column_label": column_label,
                "target_mode": clean_target,
                "scope_track_ids": list(normalized_track_ids),
                "converted_track_ids": [],
                "skipped_track_ids": list(conversion_plan["skip_track_ids"]),
                "missing_track_ids": list(scope["missing_track_ids"]),
                "failed": [],
            }
            to_convert = list(conversion_plan["convert_track_ids"])
            if not to_convert:
                return result

            progress_callback = self._scaled_progress_callback(
                ctx.report_progress,
                start=12,
                end=88,
            )

            def _track_label(track_id: int, cursor) -> str:
                snapshot = bundle.track_service.fetch_track_snapshot(int(track_id), cursor=cursor)
                if snapshot is not None and str(snapshot.track_title or "").strip():
                    return str(snapshot.track_title).strip()
                return f"Track {track_id}"

            def _mutation():
                converted_track_ids: list[int] = []
                failures: list[dict[str, object]] = []
                total = max(1, len(to_convert))
                with bundle.conn:
                    cur = bundle.conn.cursor()
                    for index, pending_track_id in enumerate(to_convert, start=1):
                        ctx.raise_if_cancelled()
                        try:
                            if scope_kind == "standard":
                                bundle.track_service.convert_media_storage_mode(
                                    int(pending_track_id),
                                    str(media_key or ""),
                                    clean_target,
                                    cursor=cur,
                                )
                            else:
                                bundle.custom_field_values.convert_storage_mode(
                                    int(pending_track_id),
                                    int(field_id or 0),
                                    clean_target,
                                )
                            converted_track_ids.append(int(pending_track_id))
                            progress_callback(
                                value=index,
                                maximum=total,
                                message=(
                                    f"Converting '{column_label}' to "
                                    f"{self._storage_conversion_target_label(clean_target)} "
                                    f"for {index} of {total} tracks..."
                                ),
                            )
                        except Exception as exc:
                            failures.append(
                                {
                                    "track_id": int(pending_track_id),
                                    "label": _track_label(int(pending_track_id), cur),
                                    "message": str(exc),
                                }
                            )
                            progress_callback(
                                value=index,
                                maximum=total,
                                message=(
                                    f"Processed {index} of {total} tracks while converting "
                                    f"'{column_label}'..."
                                ),
                            )
                result["converted_track_ids"] = converted_track_ids
                result["failed"] = failures
                return result

            return run_snapshot_history_action(
                history_manager=bundle.history_manager,
                action_label=(
                    f"Convert {column_label} Storage ({len(normalized_track_ids)} tracks)"
                    if len(normalized_track_ids) > 1
                    else f"Convert {column_label} Storage"
                ),
                action_type=action_type,
                entity_type=entity_type,
                entity_id=entity_id,
                payload={
                    "track_ids": list(normalized_track_ids),
                    "media_key": media_key,
                    "field_id": field_id,
                    "column_label": column_label,
                    "target_mode": clean_target,
                },
                mutation=_mutation,
                progress_callback=ctx.report_progress,
                post_mutation_progress=(92, "Capturing storage conversion history snapshot..."),
                record_progress=(94, "Recording storage conversion history..."),
                logger=self.logger,
            )

        def _before_cleanup(result: dict[str, object], ui_progress) -> None:
            focus_track_id = (
                list(result.get("converted_track_ids") or [])
                or list(result.get("scope_track_ids") or [])
                or [None]
            )[0]
            self._advance_task_ui_progress(
                ui_progress,
                value=97,
                message="Applying converted storage changes...",
            )
            try:
                self.conn.commit()
            except Exception:
                pass
            self._advance_task_ui_progress(
                ui_progress,
                value=99,
                message="Refreshing catalog media badges and history...",
            )
            if list(result.get("converted_track_ids") or []):
                self.refresh_table_preserve_view(focus_id=focus_track_id)
            else:
                self._refresh_history_actions()
                if hasattr(self, "table"):
                    self.table.viewport().update()
            self._refresh_history_actions()
            self._advance_task_ui_progress(
                ui_progress,
                value=100,
                message="Storage conversion complete.",
            )

        def _success(result: dict[str, object]) -> None:
            message_lines = self._storage_conversion_summary_lines(result)
            self._log_event(
                "storage.convert",
                "Converted catalog media storage mode",
                track_ids=list(result.get("scope_track_ids") or []),
                target_mode=result.get("target_mode"),
                column_label=result.get("column_label"),
                converted_track_ids=list(result.get("converted_track_ids") or []),
                skipped_track_ids=list(result.get("skipped_track_ids") or []),
                missing_track_ids=list(result.get("missing_track_ids") or []),
                failures=list(result.get("failed") or []),
            )
            dialog_fn = (
                QMessageBox.warning if list(result.get("failed") or []) else QMessageBox.information
            )
            dialog_fn(
                self,
                title,
                "\n".join(message_lines),
            )

        self._submit_background_bundle_task(
            title=title,
            description=(
                f"Converting '{column_label}' to "
                f"{self._storage_conversion_target_label(clean_target)} "
                "for the selected tracks..."
            ),
            task_fn=_worker,
            kind="write",
            unique_key=f"storage.convert.{scope_kind}.{media_key or field_id or column_label}",
            worker_completion_progress=(96, "Finalizing storage conversion..."),
            on_success_before_cleanup=_before_cleanup,
            on_success_after_cleanup=_success,
            on_error=lambda failure: self._show_background_task_error(
                title,
                failure,
                user_message="Could not convert storage mode:",
            ),
        )

    def _human_size(self, n: int) -> str:
        return format_storage_bytes(n, max_decimals=1)

    def _format_blob_badge(self, mime_type: str | None, size_bytes: int) -> str:
        _mime_type = mime_type
        return self._human_size(size_bytes)

    @staticmethod
    def _storage_mode_badge_label(storage_mode: str | None) -> str:
        clean_mode = normalize_storage_mode(storage_mode, default=STORAGE_MODE_DATABASE)
        if clean_mode == STORAGE_MODE_MANAGED_FILE:
            return "Managed-file storage"
        return "Database storage"

    @staticmethod
    def _blob_icon_kind_for_storage(
        media_kind: str,
        *,
        storage_mode: str | None,
        is_lossy: bool = False,
    ) -> str:
        clean_mode = normalize_storage_mode(storage_mode, default=STORAGE_MODE_DATABASE)
        storage_suffix = "managed" if clean_mode == STORAGE_MODE_MANAGED_FILE else "database"
        if str(media_kind or "").strip().lower() == "audio":
            prefix = "audio_lossy" if is_lossy else "audio"
            return f"{prefix}_{storage_suffix}"
        return f"image_{storage_suffix}"

    @classmethod
    def _blob_icon_kind_for_standard_media(
        cls,
        media_key: str,
        *,
        meta: dict[str, object] | None = None,
    ) -> str:
        if media_key == "audio_file":
            return cls._blob_icon_kind_for_storage(
                "audio",
                storage_mode=(meta or {}).get("storage_mode"),
                is_lossy=bool((meta or {}).get("is_lossy")),
            )
        return cls._blob_icon_kind_for_storage(
            "image",
            storage_mode=(meta or {}).get("storage_mode"),
        )

    def _standard_media_badge_tooltip(
        self,
        media_key: str,
        meta: dict[str, object],
        display: str,
    ) -> str:
        storage_label = self._storage_mode_badge_label(meta.get("storage_mode"))
        if media_key != "audio_file":
            return f"{storage_label}\nStored size: {display}"
        format_label = str(meta.get("format_label") or "").strip()
        if bool(meta.get("is_lossy")):
            if format_label:
                return (
                    f"Lossy primary audio · {format_label}\n"
                    f"{storage_label}\nStored size: {display}"
                )
            return f"Lossy primary audio\n{storage_label}\nStored size: {display}"
        if format_label:
            return f"Primary audio · {format_label}\n{storage_label}\nStored size: {display}"
        return f"Primary audio\n{storage_label}\nStored size: {display}"

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
        return self._blob_icon_spec_for_custom_field_with_meta(field, meta=None)

    def _blob_icon_spec_for_custom_field_with_meta(
        self,
        field: dict[str, object],
        *,
        meta: dict[str, object] | None,
    ) -> dict[str, object]:
        field_type = str(field.get("field_type") or "").strip().lower()
        kind = self._blob_icon_kind_for_storage(
            "audio" if field_type == "blob_audio" else "image",
            storage_mode=(meta or {}).get("storage_mode"),
        )
        override = field.get("blob_icon_payload")
        if override:
            return override
        settings = normalize_blob_icon_settings(
            getattr(self, "blob_icon_settings", None) or default_blob_icon_settings()
        )
        return settings[kind]

    def _resolve_blob_badge_icon(
        self,
        *,
        spec: dict[str, object] | None,
        kind: str,
        size: int = 18,
    ) -> QIcon:
        settings = normalize_blob_icon_settings(
            getattr(self, "blob_icon_settings", None) or default_blob_icon_settings()
        )
        normalized_spec = normalize_blob_icon_spec(spec, kind=kind, allow_inherit=True)
        fallback_spec = normalize_blob_icon_spec(
            settings.get(kind),
            kind=kind,
            allow_inherit=False,
        )
        try:
            cache_key = (
                str(kind or ""),
                int(size),
                json.dumps(
                    {
                        "spec": normalized_spec,
                        "fallback": fallback_spec,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        except Exception:
            cache_key = (str(kind or ""), int(size), repr((normalized_spec, fallback_spec)))
        cache = getattr(self, "_blob_badge_icon_cache", None)
        if cache is None:
            self._reset_blob_badge_render_cache()
            cache = self._blob_badge_icon_cache
        cached_icon = cache.get(cache_key)
        if isinstance(cached_icon, QIcon) and not cached_icon.isNull():
            return cached_icon
        icon = icon_from_blob_icon_spec(
            normalized_spec,
            kind=kind,
            style=self.style() if hasattr(self, "style") else None,
            fallback_spec=fallback_spec,
            allow_inherit=True,
            size=int(size),
        )
        if not icon.isNull():
            warmed_pixmap = icon.pixmap(int(size), int(size))
            if not warmed_pixmap.isNull():
                icon = QIcon(warmed_pixmap)
        cache[cache_key] = icon
        return icon

    def _custom_field_index_by_id(self, field_id: int) -> int:
        for i, f in enumerate(self.active_custom_fields):
            if f.get("id") == field_id:
                return i
        return -1

    def _get_track_title(self, track_id: int) -> str:
        return self.track_service.fetch_track_title(track_id, cursor=self.cursor)

    def _sanitize_filename(self, text: str) -> str:
        return sanitize_export_basename(text)

    def _make_default_export_filename(self, track_id: int, field_def: dict, mime: str) -> str:
        # Use track title only
        title = self._get_track_title(track_id)
        base = self._sanitize_filename(title)

        # Extension from MIME type
        ext = mimetypes.guess_extension(mime or "")
        if not ext:
            ext = ".bin"
        return base + ext

    def _open_audio_preview_for_track(self, *args, **kwargs):
        return media_player_controller._open_audio_preview_for_track(self, *args, **kwargs)

    def _open_audio_preview(self, *args, **kwargs):
        return media_player_controller._open_audio_preview(self, *args, **kwargs)

    def _list_all_tracks(self):
        return self.catalog_reads.list_tracks()


def main() -> int:
    argv = list(sys.argv)
    if HELPER_MODE_ARGUMENT in argv:
        helper_index = argv.index(HELPER_MODE_ARGUMENT)
        from isrc_manager.updater_helper import main as updater_helper_main

        return updater_helper_main(argv[helper_index + 1 :])
    if PACKAGED_SMOKE_TEST_ARGUMENT in argv:
        return run_packaged_smoke_test(argv)
    return run_desktop_application(
        argv=argv,
        init_settings=init_settings,
        install_qt_message_filter=_install_qt_message_filter,
        enforce_single_instance=enforce_single_instance,
        window_factory=App,
    )


if __name__ == "__main__":
    sys.exit(main())

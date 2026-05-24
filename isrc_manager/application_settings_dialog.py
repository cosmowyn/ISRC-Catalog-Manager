"""Application settings dialog."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.app_sounds import (
    APP_SOUND_NOTICE,
    APP_SOUND_SPECS,
    APP_SOUND_STARTUP,
    APP_SOUND_WARNING,
    normalize_app_sound_settings,
)
from isrc_manager.application_settings_gs1 import ApplicationSettingsGs1Mixin
from isrc_manager.application_settings_theme import ApplicationSettingsThemeMixin
from isrc_manager.blob_icons import (
    BlobIconEditorWidget,
    normalize_blob_icon_settings,
)
from isrc_manager.constants import (
    DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    DEFAULT_HISTORY_AUTO_CLEANUP_ENABLED,
    DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
    DEFAULT_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
    DEFAULT_HISTORY_RETENTION_MODE,
    DEFAULT_HISTORY_STORAGE_BUDGET_MB,
    DEFAULT_WINDOW_TITLE,
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
)
from isrc_manager.file_storage import (
    STORAGE_MODE_DATABASE,
    STORAGE_MODE_MANAGED_FILE,
)
from isrc_manager.parties import (
    PartyRecord,
    PartyService,
    artist_choice_label,
    artist_primary_label,
)
from isrc_manager.qss_autocomplete import validate_qss_document
from isrc_manager.qss_reference import (
    QssReferenceEntry,
)
from isrc_manager.services import (
    GS1ContractEntry,
    GS1TemplateAsset,
    OwnerPartySettings,
    WorkPayload,
)
from isrc_manager.starter_themes import (
    STARTER_THEME_SPECS,
    starter_theme_descriptions,
    starter_theme_library,
)
from isrc_manager.storage_sizes import (
    format_budget_megabytes,
    format_storage_bytes,
)
from isrc_manager.theme_builder import (
    THEME_COLOR_FIELD_SPECS,
    THEME_METRIC_FIELD_SPECS,
    THEME_PAGE_SPECS,
)
from isrc_manager.theme_builder import (
    normalize_theme_settings as normalize_app_theme_settings,
)
from isrc_manager.ui_common import (
    FocusWheelComboBox,
    FocusWheelFontComboBox,
    FocusWheelSpinBox,
    StorageBudgetSpinBox,
    _apply_compact_dialog_control_heights,
    _compose_widget_stylesheet,
    _create_round_help_button,
)


class ApplicationSettingsDialog(
    ApplicationSettingsThemeMixin, ApplicationSettingsGs1Mixin, QDialog
):
    CUSTOM_THEME_LABEL = "Custom Theme"
    COLOR_FIELD_SPECS = THEME_COLOR_FIELD_SPECS
    METRIC_FIELD_SPECS = THEME_METRIC_FIELD_SPECS
    THEME_PAGE_SPECS = THEME_PAGE_SPECS
    SMART_HISTORY_BUDGET_MARGIN_PERCENT = 25
    SMART_HISTORY_BUDGET_TRANSIENT_SNAPSHOT_COUNT = 1
    HISTORY_RETENTION_MODE_SPECS = (
        (
            HISTORY_RETENTION_MODE_MAXIMUM_SAFETY,
            "Maximum Safety",
            "Keeps more retained snapshots and never ages pre-restore safety copies automatically.",
        ),
        (
            HISTORY_RETENTION_MODE_BALANCED,
            "Balanced",
            "Balances the retained snapshot count with moderate cleanup and aged safety-copy pruning.",
        ),
        (
            HISTORY_RETENTION_MODE_LEAN,
            "Lean",
            "Uses a smaller retained snapshot count and faster cleanup for constrained storage budgets.",
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
        effective_window_title: str = DEFAULT_WINDOW_TITLE,
        owner_company_name: str = "",
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
        startup_sound_enabled: bool = True,
        app_sound_settings: dict[str, object] | None = None,
        history_retention_mode: str = DEFAULT_HISTORY_RETENTION_MODE,
        history_auto_cleanup_enabled: bool = DEFAULT_HISTORY_AUTO_CLEANUP_ENABLED,
        history_storage_budget_mb: int = DEFAULT_HISTORY_STORAGE_BUDGET_MB,
        history_auto_snapshot_keep_latest: int = DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
        history_prune_pre_restore_copies_after_days: int = (
            DEFAULT_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS
        ),
        owner_party_settings: OwnerPartySettings | None = None,
        party_service: PartyService | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("applicationSettingsDialog")
        self.setWindowTitle("Application Settings")
        self.setModal(True)
        self.setMinimumSize(1040, 720)
        self.resize(1180, 820)
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
        self._current_profile_path = Path(current_profile_path) if current_profile_path else None
        self._smart_history_budget_owner = parent
        self._smart_history_budget_source_cache: tuple[int, str] | None = None
        self._profile_database_paths = self._discover_profile_database_paths(parent)
        initial_custom_qss = str(self._theme_settings.get("custom_qss") or "")
        self._theme_last_valid_custom_qss_preview = (
            initial_custom_qss if not validate_qss_document(initial_custom_qss) else ""
        )
        self._theme_change_tracking_enabled = True
        self._history_retention_sync_enabled = True
        self._theme_original_values = normalize_app_theme_settings(self._theme_settings)
        self._app_sound_settings = normalize_app_sound_settings(
            app_sound_settings,
            startup_sound_enabled=startup_sound_enabled,
        )
        self._startup_sound_enabled = self._app_sound_settings[APP_SOUND_STARTUP]
        self._app_sound_checks: dict[str, QCheckBox] = {}
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
        self.party_service = party_service or getattr(parent, "party_service", None)
        self._gs1_template_profile = None
        self._gs1_template_asset = gs1_template_asset
        self._btw_number_value = str(btw_number or "").strip()
        self._buma_relatie_nummer_value = str(buma_relatie_nummer or "").strip()
        self._buma_ipi_value = str(buma_ipi or "").strip()
        self._owner_party_settings = owner_party_settings or OwnerPartySettings()
        self._owner_selected_party_id = (
            int(self._owner_party_settings.party_id)
            if self._owner_party_settings.party_id not in (None, "")
            else None
        )
        self._pending_gs1_template_path = ""
        self._gs1_default_option_combos: dict[str, QComboBox] = {}
        self._gs1_contract_entries = tuple(gs1_contract_entries or ())
        self._gs1_contracts_csv_path = str(gs1_contracts_csv_path or "").strip()
        self._pending_gs1_contracts_csv_bytes: bytes | None = None
        self._pending_gs1_contracts_csv_filename = ""
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
        root.setSizeConstraint(QLayout.SetMinimumSize)

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

        resolved_window_title = str(effective_window_title or DEFAULT_WINDOW_TITLE).strip()
        resolved_window_title = resolved_window_title or DEFAULT_WINDOW_TITLE
        owner_company_name = str(owner_company_name or "").strip()

        self.window_title_edit = QLineEdit((window_title or "").strip())
        self.window_title_edit.setClearButtonEnabled(True)
        self.window_title_edit.setPlaceholderText(resolved_window_title)
        self.window_title_edit.setMinimumWidth(320)
        self.window_title_edit.setMaximumWidth(460)

        title_override_widget = QWidget(self)
        title_override_row = QHBoxLayout(title_override_widget)
        title_override_row.setContentsMargins(0, 0, 0, 0)
        title_override_row.setSpacing(8)
        title_override_row.addWidget(self.window_title_edit, 1)
        self.window_title_auto_button = QPushButton("Use Automatic")
        self.window_title_auto_button.setAutoDefault(False)
        self.window_title_auto_button.clicked.connect(self.window_title_edit.clear)
        title_override_row.addWidget(self.window_title_auto_button)
        title_override_row.addStretch(1)

        if owner_company_name:
            window_title_hint = (
                f"Leave blank to use the current owner company name automatically "
                f"(currently “{owner_company_name}”), or fall back to {DEFAULT_WINDOW_TITLE}."
            )
        else:
            window_title_hint = (
                f"Leave blank to use the application name automatically "
                f"({DEFAULT_WINDOW_TITLE}) until an owner company name is available."
            )
        self._add_row(
            app_grid,
            0,
            "Window Title",
            title_override_widget,
            window_title_hint,
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
            "Choose a practical cleanup posture for retained history artifacts. The snapshot count applies to both manual and automatic snapshots.",
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
            "Allow the app to remove unreferenced bundles and aged pre-restore safety copies automatically after the retained snapshot cap is enforced.",
        )

        self.history_storage_budget_spin = StorageBudgetSpinBox()
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
        self.history_storage_budget_spin.setMinimumWidth(180)
        self.history_storage_budget_spin.setMaximumWidth(220)
        history_budget_widget = QWidget(self)
        history_budget_layout = QVBoxLayout(history_budget_widget)
        history_budget_layout.setContentsMargins(0, 0, 0, 0)
        history_budget_layout.setSpacing(4)
        history_budget_row = QHBoxLayout()
        history_budget_row.setContentsMargins(0, 0, 0, 0)
        history_budget_row.setSpacing(8)
        history_budget_row.addWidget(self.history_storage_budget_spin)
        self.history_storage_budget_smart_button = QPushButton("Use Smart Budget")
        self.history_storage_budget_smart_button.setObjectName("historyStorageSmartBudgetButton")
        self.history_storage_budget_smart_button.setAutoDefault(False)
        self.history_storage_budget_smart_button.clicked.connect(self._apply_smart_history_budget)
        history_budget_row.addWidget(self.history_storage_budget_smart_button)
        history_budget_row.addStretch(1)
        history_budget_layout.addLayout(history_budget_row)
        self.history_storage_budget_hint = self._make_hint(
            "Set the application-wide history-storage budget. Values stay exact internally. Use Smart Budget calculates from total tracked app storage, retained snapshots, one temporary snapshot slot, and a 25% margin."
        )
        history_budget_layout.addWidget(self.history_storage_budget_hint)
        self._add_row(
            snapshots_grid,
            5,
            "Storage Budget",
            history_budget_widget,
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
            "Keep Latest Snapshots",
            self.history_auto_snapshot_keep_latest_spin,
            "Retain this many live snapshots for the profile. Older live snapshots are pruned first unless the current visible undo boundary still needs them.",
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
            self._refresh_smart_history_budget_button_state
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
        self._refresh_smart_history_budget_button_state()
        self.history_auto_cleanup_enabled_check.toggled.connect(
            self._sync_history_retention_mode_from_controls
        )
        self.history_storage_budget_spin.valueChanged.connect(
            self._sync_history_retention_mode_from_controls
        )
        self.history_auto_snapshot_keep_latest_spin.valueChanged.connect(
            self._sync_history_retention_mode_from_controls
        )
        self.history_auto_snapshot_keep_latest_spin.valueChanged.connect(
            self._refresh_smart_history_budget_button_state
        )
        self.history_prune_pre_restore_copies_after_days_spin.valueChanged.connect(
            self._sync_history_retention_mode_from_controls
        )
        self._set_history_retention_mode_state(
            self._detect_history_retention_mode(preferred_mode=history_retention_mode)
        )

        general_layout.addStretch(1)
        self._general_tab_index = self.tabs.addTab(self._wrap_tab_page(general_page), "General")

        sounds_page = QWidget(self)
        sounds_page.setProperty("role", "workspaceCanvas")
        sounds_layout = QVBoxLayout(sounds_page)
        sounds_layout.setContentsMargins(10, 10, 10, 10)
        sounds_layout.setSpacing(14)

        app_sounds_box = QGroupBox("App-Wide Sounds")
        app_sounds_grid = QGridLayout(app_sounds_box)
        self._configure_grid(app_sounds_grid)
        for row, (sound_id, label, control_text, hint_text) in enumerate(APP_SOUND_SPECS):
            check = QCheckBox(control_text)
            check.setChecked(bool(self._app_sound_settings.get(sound_id, True)))
            check.setMinimumWidth(320)
            self._app_sound_checks[sound_id] = check
            setattr(self, f"{sound_id}_sound_enabled_check", check)
            self._add_row(app_sounds_grid, row, label, check, hint_text)
        self.startup_sound_enabled_check = self._app_sound_checks[APP_SOUND_STARTUP]
        sounds_layout.addWidget(app_sounds_box)
        sound_credit = QLabel(
            "All bundled application sound effects were designed and created by Aeon Cosmowyn."
        )
        sound_credit.setProperty("role", "hint")
        sound_credit.setWordWrap(True)
        sounds_layout.addWidget(sound_credit)
        sounds_layout.addStretch(1)
        self._sounds_tab_index = self.tabs.addTab(self._wrap_tab_page(sounds_page), "Sounds")

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
        self.gs1_contracts_csv_edit.setPlaceholderText("Imported GS1 contracts CSV path")
        self.gs1_contracts_csv_edit.setMinimumWidth(420)
        gs1_contracts_browse_btn = QPushButton("Import CSV…")
        gs1_contracts_browse_btn.setAutoDefault(False)
        gs1_contracts_browse_btn.clicked.connect(self._browse_gs1_contracts_csv)
        self.gs1_contracts_export_btn = QPushButton("Export…")
        self.gs1_contracts_export_btn.setAutoDefault(False)
        self.gs1_contracts_export_btn.clicked.connect(self._export_gs1_contracts_csv)
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
        gs1_contracts_row.addWidget(self.gs1_contracts_export_btn)
        gs1_contracts_row.addWidget(gs1_contracts_reload_btn)
        gs1_contracts_row.addWidget(gs1_contracts_clear_btn)
        self._add_row(
            gs1_contracts_grid,
            0,
            "Contracts CSV",
            gs1_contracts_widget,
            "Import the contracts export from your GS1 portal. GTIN contract numbers from that file become available for defaults and export routing, and Export saves the stored CSV back to disk when you need to reuse it.",
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
        self._gs1_tab_index = self.tabs.addTab(self._wrap_tab_page(gs1_page), "GS1")

        theme_page = QWidget(self)
        self.theme_page = theme_page
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

        self.theme_show_hints_check = QCheckBox("Show field hints while editing")
        self.theme_show_hints_check.setChecked(True)
        self._add_row(
            theme_library_grid,
            2,
            "Hint Text",
            self.theme_show_hints_check,
            "Show or hide the softer instructional hint text under theme controls without changing the overall builder layout.",
        )

        self.theme_show_preview_check = QCheckBox("Show preview pane while editing")
        self.theme_show_preview_check.setChecked(True)
        self._add_row(
            theme_library_grid,
            3,
            "Preview Pane",
            self.theme_show_preview_check,
            "Turn on the preview pane only when you want a side-by-side test surface while editing.",
        )

        theme_layout.addWidget(theme_library_box)

        theme_intro = QLabel(
            "The visual theme builder now covers the full application surface: typography, workspace canvases, panels, group titles, compact frames, buttons, inputs, data views, tab panes, toolbar and status chrome, the action ribbon surface, help buttons, and state styling. "
            "A dedicated Blob Icons tab keeps media badges separate from visual theme presets, and the Action Ribbon tab isolates ribbon chrome without introducing a separate ribbon-button token set in this pass."
        )
        theme_intro.setWordWrap(True)
        theme_intro.setProperty("role", "secondary")
        theme_layout.addWidget(theme_intro)

        self.theme_splitter = QSplitter(Qt.Horizontal, theme_page)

        theme_editor_host = QWidget(self.theme_splitter)
        theme_editor_layout = QVBoxLayout(theme_editor_host)
        theme_editor_layout.setContentsMargins(0, 0, 0, 0)
        theme_editor_layout.setSpacing(10)
        self.theme_builder_tabs = QTabWidget(theme_editor_host)
        self.theme_builder_tabs.setDocumentMode(True)
        theme_editor_layout.addWidget(self.theme_builder_tabs, 1)
        self._build_theme_builder_tabs()

        self.theme_preview_host = QWidget(self.theme_splitter)
        theme_preview_layout = QVBoxLayout(self.theme_preview_host)
        theme_preview_layout.setContentsMargins(0, 0, 0, 0)
        theme_preview_layout.setSpacing(10)
        preview_title = QLabel("Live Preview", self.theme_preview_host)
        preview_title.setProperty("role", "sectionTitle")
        theme_preview_layout.addWidget(preview_title)
        preview_subtitle = QLabel(
            "Hover, click, switch tabs, focus fields, and inspect disabled states here before you save the theme.",
            self.theme_preview_host,
        )
        preview_subtitle.setProperty("role", "secondary")
        preview_subtitle.setWordWrap(True)
        theme_preview_layout.addWidget(preview_subtitle)
        self.theme_preview_status_label = QLabel("", self.theme_preview_host)
        self.theme_preview_status_label.setWordWrap(True)
        self.theme_preview_status_label.setProperty("role", "secondary")
        theme_preview_layout.addWidget(self.theme_preview_status_label)
        self.theme_preview_tabs = QTabWidget(self.theme_preview_host)
        self.theme_preview_tabs.setDocumentMode(True)
        self.theme_preview_tabs.tabBar().hide()
        theme_preview_layout.addWidget(self.theme_preview_tabs, 1)
        self._build_theme_preview_tabs()

        self.theme_splitter.addWidget(theme_editor_host)
        self.theme_splitter.addWidget(self.theme_preview_host)
        self.theme_splitter.setStretchFactor(0, 3)
        self.theme_splitter.setStretchFactor(1, 2)
        theme_layout.addWidget(self.theme_splitter, 1)

        self._theme_tab_index = self.tabs.addTab(theme_page, "Theme")

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
            "window_title": (self._general_tab_index, self.window_title_edit),
            "icon_path": (self._general_tab_index, self.icon_path_edit),
            "isrc_prefix": (self._general_tab_index, self.isrc_prefix_edit),
            "artist_code": (self._general_tab_index, self.artist_code_edit),
            "auto_snapshot_enabled": (self._general_tab_index, self.auto_snapshot_enabled_check),
            "auto_snapshot_interval_minutes": (
                self._general_tab_index,
                self.auto_snapshot_interval_spin,
            ),
            "startup_sound_enabled": (
                self._sounds_tab_index,
                self.startup_sound_enabled_check,
            ),
            "notice_sound_enabled": (
                self._sounds_tab_index,
                self._app_sound_checks[APP_SOUND_NOTICE],
            ),
            "warning_sound_enabled": (
                self._sounds_tab_index,
                self._app_sound_checks[APP_SOUND_WARNING],
            ),
            "history_retention_mode": (self._general_tab_index, self.history_retention_mode_combo),
            "history_auto_cleanup_enabled": (
                self._general_tab_index,
                self.history_auto_cleanup_enabled_check,
            ),
            "history_storage_budget_mb": (
                self._general_tab_index,
                self.history_storage_budget_spin,
            ),
            "history_auto_snapshot_keep_latest": (
                self._general_tab_index,
                self.history_auto_snapshot_keep_latest_spin,
            ),
            "history_prune_pre_restore_copies_after_days": (
                self._general_tab_index,
                self.history_prune_pre_restore_copies_after_days_spin,
            ),
            "sena_number": (self._general_tab_index, self.sena_number_edit),
            "gs1_template_path": (self._gs1_tab_index, self.gs1_template_path_edit),
            "gs1_contracts_csv_path": (self._gs1_tab_index, self.gs1_contracts_csv_edit),
            "gs1_active_contract_number": (self._gs1_tab_index, self.gs1_active_contract_edit),
            "gs1_target_market": (self._gs1_tab_index, self.gs1_target_market_edit),
            "gs1_language": (self._gs1_tab_index, self.gs1_language_edit),
            "gs1_brand": (self._gs1_tab_index, self.gs1_brand_edit),
            "gs1_subbrand": (self._gs1_tab_index, self.gs1_subbrand_edit),
            "gs1_packaging_type": (self._gs1_tab_index, self.gs1_packaging_type_edit),
            "gs1_product_classification": (
                self._gs1_tab_index,
                self.gs1_product_classification_edit,
            ),
            "theme_font_family": (self._theme_tab_index, self.theme_font_family_combo),
            "theme_font_size": (self._theme_tab_index, self.theme_font_size_spin),
            "theme_custom_qss": (self._theme_tab_index, self.theme_custom_qss_edit),
            "theme_preset": (self._theme_tab_index, self.theme_preset_combo),
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
        self._set_theme_builder_hints_visible(self.theme_show_hints_check.isChecked())
        self._set_theme_preview_pane_visible(self.theme_show_preview_check.isChecked())
        _apply_compact_dialog_control_heights(self)

    @staticmethod
    def _configure_grid(grid: QGridLayout):
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

    @staticmethod
    def _ceil_div(value: int, divisor: int) -> int:
        clean_divisor = max(1, int(divisor or 1))
        clean_value = max(0, int(value or 0))
        return (clean_value + clean_divisor - 1) // clean_divisor

    @classmethod
    def _smart_history_budget_copy_count(cls, retained_snapshot_count: int) -> int:
        retained_snapshots = max(1, int(retained_snapshot_count or 1))
        transient_snapshots = max(0, int(cls.SMART_HISTORY_BUDGET_TRANSIENT_SNAPSHOT_COUNT))
        return 1 + retained_snapshots + transient_snapshots

    @classmethod
    def _smart_history_budget_mb_from_profile_footprint(
        cls,
        profile_footprint_bytes: int,
        retained_snapshot_count: int,
    ) -> int:
        size_mb = max(1, cls._ceil_div(profile_footprint_bytes, 1024 * 1024))
        copy_count = cls._smart_history_budget_copy_count(retained_snapshot_count)
        margin_percent = 100 + int(cls.SMART_HISTORY_BUDGET_MARGIN_PERCENT)
        estimate_mb = cls._ceil_div(size_mb * copy_count * margin_percent, 100)
        round_to_mb = 1024 if estimate_mb >= 1024 else 128
        rounded_mb = cls._ceil_div(estimate_mb, round_to_mb) * round_to_mb
        return max(MIN_HISTORY_STORAGE_BUDGET_MB, min(MAX_HISTORY_STORAGE_BUDGET_MB, rounded_mb))

    @classmethod
    def _smart_history_budget_mb_from_database_size(
        cls,
        database_size_bytes: int,
        retained_snapshot_count: int,
    ) -> int:
        return cls._smart_history_budget_mb_from_profile_footprint(
            database_size_bytes,
            retained_snapshot_count,
        )

    def _discover_profile_database_paths(self, owner: object | None) -> list[Path]:
        candidates: list[Path] = []
        profile_store = getattr(owner, "profile_store", None)
        if profile_store is not None and hasattr(profile_store, "list_profiles"):
            try:
                candidates.extend(Path(path) for path in profile_store.list_profiles())
            except Exception:
                pass

        database_dir = getattr(owner, "database_dir", None)
        if database_dir:
            try:
                candidates.extend(sorted(Path(database_dir).glob("*.db")))
            except Exception:
                pass

        if self._current_profile_path is None:
            return self._deduplicate_profile_database_paths(candidates)
        profile_path = self._current_profile_path
        if profile_path.parent.exists():
            try:
                candidates.extend(sorted(profile_path.parent.glob("*.db")))
            except Exception:
                pass
        candidates.append(profile_path)
        return self._deduplicate_profile_database_paths(candidates)

    @staticmethod
    def _deduplicate_profile_database_paths(candidates: list[Path]) -> list[Path]:
        seen: set[str] = set()
        paths: list[Path] = []
        for candidate in candidates:
            try:
                path = Path(candidate).expanduser()
            except TypeError:
                continue
            normalized = str(path.resolve(strict=False))
            if normalized in seen:
                continue
            seen.add(normalized)
            paths.append(path)
        return paths

    def _profile_database_collection_size_bytes(self) -> int:
        if not self._profile_database_paths:
            return 0
        total_bytes = 0
        for profile_path in self._profile_database_paths:
            total_bytes += self._profile_database_bundle_size_bytes(profile_path)
        return max(0, total_bytes)

    def _smart_history_budget_source(self) -> tuple[int, str]:
        if self._smart_history_budget_source_cache is not None:
            return self._smart_history_budget_source_cache

        profile_path = self._current_profile_path
        owner = self._smart_history_budget_owner
        service_getter = getattr(owner, "_application_storage_admin_service", None)
        if profile_path is not None and callable(service_getter):
            try:
                audit = service_getter().inspect(current_db_path=profile_path)
                app_storage_bytes = int(audit.summary.total_app_bytes or 0)
            except Exception:
                app_storage_bytes = 0
            if app_storage_bytes > 0:
                self._smart_history_budget_source_cache = (
                    app_storage_bytes,
                    "application-wide tracked storage",
                )
                return self._smart_history_budget_source_cache

        if profile_path is not None:
            profile_database_bytes = self._profile_database_bundle_size_bytes(profile_path)
            if profile_database_bytes > 0:
                self._smart_history_budget_source_cache = (
                    profile_database_bytes,
                    "current profile database files",
                )
                return self._smart_history_budget_source_cache

        self._smart_history_budget_source_cache = (
            self._profile_database_collection_size_bytes(),
            "profile database files",
        )
        return self._smart_history_budget_source_cache

    @staticmethod
    def _profile_database_bundle_size_bytes(profile_path: Path) -> int:
        candidate_paths = [
            profile_path,
            Path(str(profile_path) + ".wal"),
            Path(str(profile_path) + ".shm"),
            Path(str(profile_path) + ".journal"),
            Path(str(profile_path) + "-wal"),
            Path(str(profile_path) + "-shm"),
            Path(str(profile_path) + "-journal"),
        ]
        total_bytes = 0
        seen_paths: set[str] = set()
        for candidate in candidate_paths:
            normalized = str(candidate)
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            try:
                if candidate.exists() or candidate.is_symlink():
                    total_bytes += int(candidate.stat().st_size)
            except OSError:
                continue
        return max(0, total_bytes)

    def _refresh_smart_history_budget_button_state(self, *_args) -> None:
        source_bytes, source_label = self._smart_history_budget_source()
        auto_cleanup_enabled = self.history_auto_cleanup_enabled_check.isChecked()
        enabled = bool(auto_cleanup_enabled and source_bytes > 0)
        self.history_storage_budget_smart_button.setEnabled(enabled)
        if not auto_cleanup_enabled:
            tooltip = "Enable automatic cleanup to use the profile-size budget helper."
        elif source_bytes <= 0:
            tooltip = "Open or save a profile database before calculating a smart budget."
        else:
            keep_latest = int(self.history_auto_snapshot_keep_latest_spin.value())
            smart_budget_mb = self._smart_history_budget_mb_from_profile_footprint(
                source_bytes,
                keep_latest,
            )
            transient_snapshots = max(
                0,
                int(self.SMART_HISTORY_BUDGET_TRANSIENT_SNAPSHOT_COUNT),
            )
            tooltip = (
                f"Set budget to {format_budget_megabytes(smart_budget_mb)} "
                f"from {format_storage_bytes(source_bytes)} {source_label}: tracked app storage "
                f"+ {keep_latest} retained snapshot(s) + {transient_snapshots} temporary "
                f"snapshot slot(s) + {self.SMART_HISTORY_BUDGET_MARGIN_PERCENT}% margin."
            )
        self.history_storage_budget_smart_button.setToolTip(tooltip)

    def _apply_smart_history_budget(self) -> None:
        source_bytes, _source_label = self._smart_history_budget_source()
        if source_bytes <= 0:
            QMessageBox.information(
                self,
                "Smart Storage Budget",
                "Open or save a profile database before calculating a smart history-storage budget.",
            )
            self._refresh_smart_history_budget_button_state()
            return
        keep_latest = int(self.history_auto_snapshot_keep_latest_spin.value())
        smart_budget_mb = self._smart_history_budget_mb_from_profile_footprint(
            source_bytes,
            keep_latest,
        )
        self.history_storage_budget_spin.setValue(smart_budget_mb)
        self._refresh_smart_history_budget_button_state()

    def _history_retention_control_payload(self) -> dict[str, object]:
        return {
            "auto_cleanup_enabled": self.history_auto_cleanup_enabled_check.isChecked(),
            "storage_budget_mb": int(self.history_storage_budget_spin.value()),
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
            self.history_storage_budget_spin.setValue(
                int(payload.get("storage_budget_mb", DEFAULT_HISTORY_STORAGE_BUDGET_MB))
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
        if hint:
            editor_box = QWidget(self)
            editor_layout = QVBoxLayout(editor_box)
            editor_layout.setContentsMargins(0, 0, 0, 0)
            editor_layout.setSpacing(4)
            editor_layout.addWidget(editor)
            editor_layout.addWidget(self._make_hint(hint))
            grid.addWidget(editor_box, row, 1)
            return
        grid.addWidget(editor, row, 1)

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

    @staticmethod
    def _owner_party_choice_label(record: PartyRecord) -> str:
        primary = (
            str(record.display_name or "").strip()
            or str(record.artist_name or "").strip()
            or str(record.company_name or "").strip()
            or str(record.legal_name or "").strip()
            or f"Party #{int(record.id)}"
        )
        legal_name = str(record.legal_name or "").strip()
        if legal_name and legal_name.casefold() != primary.casefold():
            return f"{primary} ({legal_name})"
        return primary

    @staticmethod
    def _artist_party_primary_label(record: PartyRecord) -> str:
        return artist_primary_label(record)

    @classmethod
    def _artist_party_choice_label(cls, record: PartyRecord) -> str:
        return artist_choice_label(record)

    def _artist_party_records(self) -> list[PartyRecord]:
        if self.party_service is None:
            return []
        try:
            return list(self.party_service.list_artist_parties() or [])
        except Exception:
            return []

    def _configure_artist_party_combo(
        self,
        combo: QComboBox,
        *,
        allow_empty: bool = False,
        selected_party_id: int | None = None,
        current_text: str | None = None,
    ) -> None:
        clean_text_value = str(current_text or "").strip()
        labels: list[str] = []
        previous_state = combo.blockSignals(True)
        try:
            combo.clear()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)
            if allow_empty:
                combo.addItem("", None)
            for record in self._artist_party_records():
                label = self._artist_party_choice_label(record)
                combo.addItem(label, int(record.id))
                combo.setItemData(
                    combo.count() - 1, self._artist_party_primary_label(record), Qt.UserRole + 1
                )
                labels.append(label)
                labels.extend(
                    alias
                    for alias in getattr(record, "artist_aliases", ()) or ()
                    if str(alias or "").strip()
                )
            if selected_party_id is not None and combo.findData(int(selected_party_id)) < 0:
                fallback_label = clean_text_value or f"Party #{int(selected_party_id)}"
                combo.addItem(fallback_label, int(selected_party_id))
                combo.setItemData(combo.count() - 1, fallback_label, Qt.UserRole + 1)
                labels.append(fallback_label)
            completer = QCompleter(sorted({label for label in labels if label}), combo)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            combo.setCompleter(completer)
            if selected_party_id is not None:
                index = combo.findData(int(selected_party_id))
                combo.setCurrentIndex(index if index >= 0 else 0)
            elif clean_text_value:
                combo.setCurrentIndex(-1)
                combo.setEditText(clean_text_value)
            elif allow_empty:
                combo.setCurrentIndex(0)
        finally:
            combo.blockSignals(previous_state)

    def _resolve_artist_party_choice(self, combo: QComboBox) -> tuple[str, int | None]:
        clean = str(combo.currentText() or "").strip()
        if not clean:
            return "", None
        current_index = combo.currentIndex()
        if current_index >= 0:
            data = combo.itemData(current_index)
            label = str(combo.itemText(current_index) or "").strip()
            if data not in (None, "") and clean.casefold() == label.casefold():
                primary_label = str(combo.itemData(current_index, Qt.UserRole + 1) or label).strip()
                return primary_label or label, int(data)
        for index in range(combo.count()):
            label = str(combo.itemText(index) or "").strip()
            if clean.casefold() != label.casefold():
                continue
            data = combo.itemData(index)
            if data not in (None, ""):
                primary_label = str(combo.itemData(index, Qt.UserRole + 1) or label).strip()
                return primary_label or label, int(data)
        return clean, None

    def _resolve_party_backed_artist_name(
        self,
        raw_name: str,
        *,
        selected_party_id: int | None = None,
        cursor: sqlite3.Cursor | None = None,
    ) -> tuple[str, int | None]:
        clean_name = str(raw_name or "").strip()
        if not clean_name:
            return "", None
        if self.party_service is None:
            return clean_name, None
        party_id = int(selected_party_id) if selected_party_id not in (None, "") else None
        if party_id is None:
            existing_id = self.party_service.find_artist_party_id_by_name(
                clean_name,
                cursor=cursor,
            )
            if existing_id is not None:
                party_id = int(existing_id)
            else:
                party_id = int(
                    self.party_service.ensure_artist_party_by_name(
                        clean_name,
                        cursor=cursor,
                    )
                )
        record = self.party_service.fetch_party(int(party_id))
        if record is None:
            return clean_name, int(party_id)
        return self._artist_party_primary_label(record), int(record.id)

    def _resolve_party_backed_additional_artist_names(
        self,
        names: list[str],
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> list[str]:
        resolved: list[str] = []
        seen: set[str] = set()
        for raw_name in names:
            clean_name, _party_id = self._resolve_party_backed_artist_name(
                raw_name,
                cursor=cursor,
            )
            normalized = clean_name.casefold()
            if not clean_name or normalized in seen:
                continue
            seen.add(normalized)
            resolved.append(clean_name)
        return resolved

    def _refresh_add_track_artist_party_choices(self) -> None:
        for combo, allow_empty in (
            (getattr(self, "artist_field", None), False),
            (getattr(self, "additional_artist_field", None), True),
        ):
            if not isinstance(combo, QComboBox):
                continue
            current_text, selected_party_id = self._resolve_artist_party_choice(combo)
            self._configure_artist_party_combo(
                combo,
                allow_empty=allow_empty,
                selected_party_id=selected_party_id,
                current_text=current_text,
            )

    def _work_payload_from_track_seed(
        self,
        *,
        track_title: str,
        iswc: str | None,
        registration_number: str | None,
    ) -> WorkPayload:
        return WorkPayload(
            title=str(track_title or "").strip(),
            iswc=str(iswc or "").strip() or None,
            registration_number=str(registration_number or "").strip() or None,
            profile_name=self._current_profile_name(),
        )

    @staticmethod
    def _owner_party_settings_from_record(record: PartyRecord) -> OwnerPartySettings:
        return OwnerPartySettings(
            party_id=int(record.id),
            legal_name=str(record.legal_name or "").strip(),
            display_name=str(record.display_name or "").strip(),
            artist_name=str(record.artist_name or "").strip(),
            company_name=str(record.company_name or "").strip(),
            first_name=str(record.first_name or "").strip(),
            middle_name=str(record.middle_name or "").strip(),
            last_name=str(record.last_name or "").strip(),
            contact_person=str(record.contact_person or "").strip(),
            email=str(record.email or "").strip(),
            alternative_email=str(record.alternative_email or "").strip(),
            phone=str(record.phone or "").strip(),
            website=str(record.website or "").strip(),
            street_name=str(record.street_name or "").strip(),
            street_number=str(record.street_number or "").strip(),
            address_line1=str(record.address_line1 or "").strip(),
            address_line2=str(record.address_line2 or "").strip(),
            city=str(record.city or "").strip(),
            region=str(record.region or "").strip(),
            postal_code=str(record.postal_code or "").strip(),
            country=str(record.country or "").strip(),
            bank_account_number=str(record.bank_account_number or "").strip(),
            chamber_of_commerce_number=str(record.chamber_of_commerce_number or "").strip(),
            tax_id=str(record.tax_id or "").strip(),
            vat_number=str(record.vat_number or "").strip(),
            pro_affiliation=str(record.pro_affiliation or "").strip(),
            pro_number=str(record.pro_number or "").strip(),
            ipi_cae=str(record.ipi_cae or "").strip(),
            notes=str(record.notes or "").strip(),
        )

    def _owner_party_settings_payload(self) -> OwnerPartySettings:
        if self._owner_selected_party_id is None:
            return OwnerPartySettings()
        if self.party_service is not None:
            record = self.party_service.fetch_party(int(self._owner_selected_party_id))
            if record is not None:
                return self._owner_party_settings_from_record(record)
        if self._owner_party_settings.party_id == self._owner_selected_party_id:
            return OwnerPartySettings(
                party_id=self._owner_selected_party_id,
                legal_name=str(self._owner_party_settings.legal_name or "").strip(),
                display_name=str(self._owner_party_settings.display_name or "").strip(),
                artist_name=str(self._owner_party_settings.artist_name or "").strip(),
                company_name=str(self._owner_party_settings.company_name or "").strip(),
                first_name=str(self._owner_party_settings.first_name or "").strip(),
                middle_name=str(self._owner_party_settings.middle_name or "").strip(),
                last_name=str(self._owner_party_settings.last_name or "").strip(),
                contact_person=str(self._owner_party_settings.contact_person or "").strip(),
                email=str(self._owner_party_settings.email or "").strip(),
                alternative_email=str(self._owner_party_settings.alternative_email or "").strip(),
                phone=str(self._owner_party_settings.phone or "").strip(),
                website=str(self._owner_party_settings.website or "").strip(),
                street_name=str(self._owner_party_settings.street_name or "").strip(),
                street_number=str(self._owner_party_settings.street_number or "").strip(),
                address_line1=str(self._owner_party_settings.address_line1 or "").strip(),
                address_line2=str(self._owner_party_settings.address_line2 or "").strip(),
                city=str(self._owner_party_settings.city or "").strip(),
                region=str(self._owner_party_settings.region or "").strip(),
                postal_code=str(self._owner_party_settings.postal_code or "").strip(),
                country=str(self._owner_party_settings.country or "").strip(),
                bank_account_number=str(
                    self._owner_party_settings.bank_account_number or ""
                ).strip(),
                chamber_of_commerce_number=str(
                    self._owner_party_settings.chamber_of_commerce_number or ""
                ).strip(),
                tax_id=str(self._owner_party_settings.tax_id or "").strip(),
                vat_number=str(self._owner_party_settings.vat_number or "").strip(),
                pro_affiliation=str(self._owner_party_settings.pro_affiliation or "").strip(),
                pro_number=str(self._owner_party_settings.pro_number or "").strip(),
                ipi_cae=str(self._owner_party_settings.ipi_cae or "").strip(),
                notes=str(self._owner_party_settings.notes or "").strip(),
            )
        return OwnerPartySettings(party_id=self._owner_selected_party_id)

    def values(self) -> dict[str, object]:
        theme_values = self._theme_value_payload()
        blob_icon_values = self._blob_icon_value_payload()
        app_sound_values = {
            sound_id: bool(check.isChecked()) for sound_id, check in self._app_sound_checks.items()
        }
        return {
            "window_title": self.window_title_edit.text().strip(),
            "icon_path": self.icon_path_edit.text().strip(),
            "isrc_prefix": self.isrc_prefix_edit.text().strip().upper(),
            "artist_code": self.artist_code_edit.text().strip(),
            "auto_snapshot_enabled": self.auto_snapshot_enabled_check.isChecked(),
            "auto_snapshot_interval_minutes": int(self.auto_snapshot_interval_spin.value()),
            "startup_sound_enabled": app_sound_values[APP_SOUND_STARTUP],
            "notice_sound_enabled": app_sound_values[APP_SOUND_NOTICE],
            "warning_sound_enabled": app_sound_values[APP_SOUND_WARNING],
            "app_sound_settings": app_sound_values,
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
            "btw_number": self._btw_number_value,
            "buma_relatie_nummer": self._buma_relatie_nummer_value,
            "buma_ipi": self._buma_ipi_value,
            "owner_party_id": self._owner_selected_party_id,
            "owner_party_settings": self._owner_party_settings_payload(),
            "gs1_template_asset": self._gs1_template_asset,
            "gs1_template_import_path": self._pending_gs1_template_path.strip(),
            "gs1_template_storage_mode": self.gs1_template_storage_combo.currentData(),
            "gs1_contracts_csv_path": self.gs1_contracts_csv_edit.text().strip(),
            "gs1_contract_entries": tuple(self._gs1_contract_entries),
            "gs1_contracts_csv_bytes": self._pending_gs1_contracts_csv_bytes,
            "gs1_contracts_csv_filename": self._pending_gs1_contracts_csv_filename,
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
                self.tabs.setCurrentIndex(self._theme_tab_index)
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
                self.tabs.setCurrentIndex(self._theme_tab_index)
                return
        for key, edit in self._theme_color_edits.items():
            color_text = edit.text().strip()
            if color_text and not QColor(color_text).isValid():
                QMessageBox.warning(
                    self,
                    "Invalid Theme Color",
                    f"{key.replace('_', ' ').title()} must be a valid color value like #112233, #abc, or a named Qt color.",
                )
                self.tabs.setCurrentIndex(self._theme_tab_index)
                edit.setFocus(Qt.OtherFocusReason)
                edit.selectAll()
                return
        qss_issues = self._theme_qss_validation_issues(values.get("custom_qss"))
        if qss_issues:
            first_issue = qss_issues[0]
            QMessageBox.warning(
                self,
                "Invalid Advanced QSS",
                "Advanced QSS is not ready to apply yet.\n\n"
                f"Line {first_issue.line}, column {first_issue.column}: {first_issue.message}\n\n"
                "Use Ctrl+Space for completions or Insert Template from the selector catalog to start from a full working scaffold.",
            )
            self.tabs.setCurrentIndex(self._theme_tab_index)
            self.theme_qss_tabs.setCurrentIndex(0)
            self.theme_custom_qss_edit.setFocus(Qt.OtherFocusReason)
            return
        self.accept()


__all__ = ["ApplicationSettingsDialog"]

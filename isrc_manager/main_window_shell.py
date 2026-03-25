"""Main-window composition helpers for the legacy entry point."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCalendarWidget,
    QDockWidget,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenuBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.ui_common import (
    FocusWheelCalendarWidget,
    FocusWheelComboBox,
    TwoDigitSpinBox,
    _create_round_help_button,
)


def build_main_window_shell(app: Any, *, last_db: str, movable: bool) -> None:
    """Compose menus, toolbars, and dock panels for the main window."""

    _build_actions_and_menus(app, movable=movable)
    app._initialize_action_ribbon_registry()
    _build_action_ribbon_toolbar(app)
    _build_profiles_toolbar(app, last_db=last_db)
    _build_catalog_docks(app, movable=movable)
    refresh_boundary = getattr(app, "_queue_top_chrome_boundary_refresh", None)
    if callable(refresh_boundary):
        refresh_boundary()


def _build_actions_and_menus(app: Any, *, movable: bool) -> None:
    app.menu_bar = QMenuBar(app)
    app.setMenuBar(app.menu_bar)

    app.undo_action = app._create_action(
        "Undo",
        slot=app.history_undo,
        standard_key=QKeySequence.Undo,
    )
    app.redo_action = app._create_action(
        "Redo",
        slot=app.history_redo,
        standard_key=QKeySequence.Redo,
    )
    app.copy_action = app._create_action(
        "Copy",
        slot=lambda: app._copy_selection_to_clipboard(False),
        standard_key=QKeySequence.Copy,
    )
    app.copy_with_headers_action = app._create_action(
        "Copy with Headers",
        slot=lambda: app._copy_selection_to_clipboard(True),
        shortcuts=("Ctrl+Shift+C", "Meta+Shift+C"),
    )
    app.save_entry_action = app._create_action(
        "Save Track",
        slot=app.save,
        standard_key=QKeySequence.Save,
    )
    app.add_album_action = app._create_action(
        "Add Album…",
        slot=app.open_add_album_dialog,
        shortcuts=("Ctrl+Alt+A", "Meta+Alt+A"),
    )
    app.edit_selected_action = app._create_action(
        "Edit Selected…",
        slot=app.open_selected_editor,
    )
    app.delete_entry_action = app._create_action(
        "Delete Selected Track",
        slot=app.delete_entry,
        shortcuts=("Delete", "Meta+Backspace"),
    )
    app.reset_form_action = app._create_action(
        "Reset Form and Search",
        slot=lambda: (app.init_form(), app.reset_search()),
        shortcuts=("Escape",),
    )

    file_menu = app.menu_bar.addMenu("File")
    profiles_menu = file_menu.addMenu("Profiles")

    app.new_profile_action = app._create_action(
        "New Profile…",
        slot=app.create_new_profile,
        standard_key=QKeySequence.New,
    )
    profiles_menu.addAction(app.new_profile_action)

    app.open_profile_action = app._create_action(
        "Open Profile…",
        slot=app.browse_profile,
        standard_key=QKeySequence.Open,
    )
    profiles_menu.addAction(app.open_profile_action)

    app.reload_profiles_action = app._create_action(
        "Reload Profile List",
        slot=lambda: app._reload_profiles_list(select_path=app.current_db_path),
        standard_key=QKeySequence.Refresh,
    )
    profiles_menu.addAction(app.reload_profiles_action)

    app.remove_profile_action = app._create_action(
        "Remove Selected Profile…",
        slot=app.remove_selected_profile,
        shortcuts=("Ctrl+Shift+-", "Meta+Shift+-"),
    )
    profiles_menu.addAction(app.remove_profile_action)

    file_menu.addSeparator()

    import_menu = file_menu.addMenu("Import & Exchange")

    app.import_xml_action = app._create_action(
        "Import Catalog XML…",
        slot=app.import_from_xml,
        shortcuts=("Ctrl+Shift+I", "Meta+Shift+I"),
    )
    import_menu.addAction(app.import_xml_action)
    import_menu.addSeparator()

    import_exchange_menu = import_menu.addMenu("Catalog Exchange")
    app.import_csv_action = app._create_action(
        "Import CSV…",
        slot=lambda: app.import_exchange_file("csv"),
        shortcuts=("Ctrl+Alt+I", "Meta+Alt+I"),
    )
    import_exchange_menu.addAction(app.import_csv_action)
    app.import_xlsx_action = app._create_action(
        "Import XLSX…",
        slot=lambda: app.import_exchange_file("xlsx"),
    )
    import_exchange_menu.addAction(app.import_xlsx_action)
    app.import_json_action = app._create_action(
        "Import JSON…",
        slot=lambda: app.import_exchange_file("json"),
    )
    import_exchange_menu.addAction(app.import_json_action)
    app.import_package_action = app._create_action(
        "Import ZIP Package…",
        slot=lambda: app.import_exchange_file("package"),
    )
    import_exchange_menu.addAction(app.import_package_action)
    import_exchange_menu.addSeparator()
    app.reset_saved_import_choices_action = app._create_action(
        "Reset Saved Import Choices…",
        slot=app.reset_saved_exchange_import_choices,
    )
    import_exchange_menu.addAction(app.reset_saved_import_choices_action)

    repertoire_import_menu = import_menu.addMenu("Contracts and Rights")
    app.import_repertoire_json_action = app._create_action(
        "Import Contracts and Rights JSON…",
        slot=lambda: app.import_repertoire_exchange("json"),
    )
    repertoire_import_menu.addAction(app.import_repertoire_json_action)
    app.import_repertoire_xlsx_action = app._create_action(
        "Import Contracts and Rights XLSX…",
        slot=lambda: app.import_repertoire_exchange("xlsx"),
    )
    repertoire_import_menu.addAction(app.import_repertoire_xlsx_action)
    app.import_repertoire_csv_action = app._create_action(
        "Import Contracts and Rights CSV Bundle…",
        slot=lambda: app.import_repertoire_exchange("csv"),
    )
    repertoire_import_menu.addAction(app.import_repertoire_csv_action)
    app.import_repertoire_package_action = app._create_action(
        "Import Contracts and Rights ZIP Package…",
        slot=lambda: app.import_repertoire_exchange("package"),
    )
    repertoire_import_menu.addAction(app.import_repertoire_package_action)

    export_submenu = file_menu.addMenu("Export")
    app.export_selected_action = app._create_action(
        "Export Selected Catalog XML…",
        slot=app.export_selected_to_xml,
        shortcuts=("Ctrl+E", "Meta+E"),
    )
    export_submenu.addAction(app.export_selected_action)

    app.export_all_action = app._create_action(
        "Export Full Catalog XML…",
        slot=app.export_full_to_xml,
        shortcuts=("Ctrl+Shift+E", "Meta+Shift+E"),
    )
    export_submenu.addAction(app.export_all_action)

    exchange_export_menu = export_submenu.addMenu("Catalog Exchange")
    app.export_selected_csv_action = app._create_action(
        "Export Selected Exchange CSV…",
        slot=lambda: app.export_exchange_file("csv", selected_only=True),
    )
    exchange_export_menu.addAction(app.export_selected_csv_action)
    app.export_selected_xlsx_action = app._create_action(
        "Export Selected Exchange XLSX…",
        slot=lambda: app.export_exchange_file("xlsx", selected_only=True),
    )
    exchange_export_menu.addAction(app.export_selected_xlsx_action)
    app.export_selected_json_action = app._create_action(
        "Export Selected Exchange JSON…",
        slot=lambda: app.export_exchange_file("json", selected_only=True),
    )
    exchange_export_menu.addAction(app.export_selected_json_action)
    app.export_selected_package_action = app._create_action(
        "Export Selected Exchange ZIP Package…",
        slot=lambda: app.export_exchange_file("package", selected_only=True),
    )
    exchange_export_menu.addAction(app.export_selected_package_action)
    exchange_export_menu.addSeparator()
    app.export_all_csv_action = app._create_action(
        "Export Full Exchange CSV…",
        slot=lambda: app.export_exchange_file("csv", selected_only=False),
    )
    exchange_export_menu.addAction(app.export_all_csv_action)
    app.export_all_xlsx_action = app._create_action(
        "Export Full Exchange XLSX…",
        slot=lambda: app.export_exchange_file("xlsx", selected_only=False),
    )
    exchange_export_menu.addAction(app.export_all_xlsx_action)
    app.export_all_json_action = app._create_action(
        "Export Full Exchange JSON…",
        slot=lambda: app.export_exchange_file("json", selected_only=False),
    )
    exchange_export_menu.addAction(app.export_all_json_action)
    app.export_all_package_action = app._create_action(
        "Export Full Exchange ZIP Package…",
        slot=lambda: app.export_exchange_file("package", selected_only=False),
    )
    exchange_export_menu.addAction(app.export_all_package_action)

    repertoire_export_menu = export_submenu.addMenu("Contracts and Rights")
    app.export_repertoire_json_action = app._create_action(
        "Export Contracts and Rights JSON…",
        slot=lambda: app.export_repertoire_exchange("json"),
    )
    repertoire_export_menu.addAction(app.export_repertoire_json_action)
    app.export_repertoire_xlsx_action = app._create_action(
        "Export Contracts and Rights XLSX…",
        slot=lambda: app.export_repertoire_exchange("xlsx"),
    )
    repertoire_export_menu.addAction(app.export_repertoire_xlsx_action)
    app.export_repertoire_csv_action = app._create_action(
        "Export Contracts and Rights CSV Bundle…",
        slot=lambda: app.export_repertoire_exchange("csv"),
    )
    repertoire_export_menu.addAction(app.export_repertoire_csv_action)
    app.export_repertoire_package_action = app._create_action(
        "Export Contracts and Rights ZIP Package…",
        slot=lambda: app.export_repertoire_exchange("package"),
    )
    repertoire_export_menu.addAction(app.export_repertoire_package_action)

    file_menu.addSeparator()

    database_submenu = file_menu.addMenu("Profile Maintenance")
    app.backup_action = app._create_action(
        "Backup Database",
        slot=app.backup_database,
        shortcuts=("Ctrl+Alt+B", "Meta+Alt+B"),
    )
    database_submenu.addAction(app.backup_action)

    app.restore_action = app._create_action(
        "Restore from Backup…",
        slot=app.restore_database,
        shortcuts=("Ctrl+Shift+B", "Meta+Shift+B"),
    )
    database_submenu.addAction(app.restore_action)

    app.verify_action = app._create_action(
        "Verify Integrity",
        slot=app.verify_integrity,
        shortcuts=("Ctrl+Shift+V", "Meta+Shift+V"),
    )
    database_submenu.addAction(app.verify_action)

    edit_menu = app.menu_bar.addMenu("Edit")
    edit_menu.addAction(app.undo_action)
    edit_menu.addAction(app.redo_action)
    edit_menu.addSeparator()
    edit_menu.addAction(app.save_entry_action)
    edit_menu.addAction(app.add_album_action)
    edit_menu.addAction(app.edit_selected_action)
    edit_menu.addAction(app.delete_entry_action)
    edit_menu.addAction(app.reset_form_action)
    edit_menu.addSeparator()
    edit_menu.addAction(app.copy_action)
    edit_menu.addAction(app.copy_with_headers_action)

    catalog_menu = app.menu_bar.addMenu("Catalog")
    workspace_menu = catalog_menu.addMenu("Workspace")
    app.catalog_managers_action = app._create_action(
        "Catalog Managers…",
        slot=app.open_catalog_managers_dialog,
        shortcuts=("Ctrl+Alt+G", "Meta+Alt+G"),
    )
    workspace_menu.addAction(app.catalog_managers_action)
    app.release_browser_action = app._create_action(
        "Release Browser…",
        slot=app.open_release_browser,
        shortcuts=("Ctrl+Alt+Shift+R", "Meta+Alt+Shift+R"),
    )
    workspace_menu.addAction(app.release_browser_action)
    app.work_manager_action = app._create_action(
        "Work Manager…",
        slot=app.open_work_manager,
        shortcuts=("Ctrl+Alt+W", "Meta+Alt+W"),
    )
    workspace_menu.addAction(app.work_manager_action)
    app.party_manager_action = app._create_action(
        "Party Manager…",
        slot=app.open_party_manager,
        shortcuts=("Ctrl+Alt+P", "Meta+Alt+P"),
    )
    workspace_menu.addAction(app.party_manager_action)
    app.contract_manager_action = app._create_action(
        "Contract Manager…",
        slot=app.open_contract_manager,
        shortcuts=("Ctrl+Alt+C", "Meta+Alt+C"),
    )
    workspace_menu.addAction(app.contract_manager_action)
    app.contract_template_workspace_action = app._create_action(
        "Contract Template Workspace…",
        slot=app.open_contract_template_workspace,
        shortcuts=("Ctrl+Alt+Shift+T", "Meta+Alt+Shift+T"),
    )
    workspace_menu.addAction(app.contract_template_workspace_action)
    app.rights_matrix_action = app._create_action(
        "Rights Matrix…",
        slot=app.open_rights_matrix,
        shortcuts=("Ctrl+Alt+M", "Meta+Alt+M"),
    )
    workspace_menu.addAction(app.rights_matrix_action)
    app.asset_registry_action = app._create_action(
        "Deliverables & Asset Versions…",
        slot=app.open_asset_registry,
        shortcuts=("Ctrl+Alt+A", "Meta+Alt+A"),
    )
    workspace_menu.addAction(app.asset_registry_action)
    app.derivative_ledger_action = app._create_action(
        "Derivative Ledger…",
        slot=app.open_derivative_ledger,
    )
    workspace_menu.addAction(app.derivative_ledger_action)
    app.global_search_action = app._create_action(
        "Global Search and Relationships…",
        slot=app.open_global_search,
        shortcuts=("Ctrl+Alt+F", "Meta+Alt+F"),
    )
    workspace_menu.addAction(app.global_search_action)
    app.add_data_action = app._create_action(
        "Show Add Track Panel",
        checkable=True,
        checked=False,
        toggled_slot=app._on_toggle_add_data,
        shortcuts=("Ctrl+Shift+D", "Meta+Shift+D"),
    )
    workspace_menu.addSeparator()
    workspace_menu.addAction(app.add_data_action)

    app.catalog_table_action = app._create_action(
        "Show Catalog Table",
        checkable=True,
        checked=True,
        toggled_slot=app._on_toggle_catalog_table,
        shortcuts=("Ctrl+Shift+T", "Meta+Shift+T"),
    )
    workspace_menu.addAction(app.catalog_table_action)
    metadata_menu = catalog_menu.addMenu("Metadata & Standards")
    legacy_special_menu = catalog_menu.addMenu("Legacy")
    audio_menu = catalog_menu.addMenu("Audio")
    audio_ingest_menu = audio_menu.addMenu("Import & Attach")
    audio_export_menu = audio_menu.addMenu("Delivery & Conversion")
    authenticity_menu = audio_menu.addMenu("Authenticity & Provenance")
    quality_menu = catalog_menu.addMenu("Quality & Repair")
    legacy_menu = legacy_special_menu.addMenu("Legacy License Archive")
    app.license_browser_action = app._create_action(
        "License Browser…",
        slot=lambda: app.open_licenses_browser(track_filter_id=None),
        shortcuts=("Ctrl+L", "Meta+L"),
    )
    legacy_menu.addAction(app.license_browser_action)
    app.legacy_license_migration_action = app._create_action(
        "Migrate Legacy Licenses to Contracts…",
        slot=app.migrate_legacy_licenses_to_contracts,
    )
    legacy_menu.addAction(app.legacy_license_migration_action)
    app.create_release_action = app._create_action(
        "Create Release from Selection…",
        slot=app.create_release_from_selection,
    )
    app.add_selected_to_release_action = app._create_action(
        "Add Selected Tracks to Release…",
        slot=app.add_selected_tracks_to_release,
    )
    app.bulk_attach_audio_action = app._create_action(
        "Bulk Attach Audio Files…",
        slot=app.bulk_attach_audio_files,
    )
    audio_ingest_menu.addAction(app.bulk_attach_audio_action)
    app.import_tags_action = app._create_action(
        "Import Metadata from Audio Files…",
        slot=app.import_tags_from_audio,
        shortcuts=("Ctrl+Alt+T", "Meta+Alt+T"),
    )
    audio_ingest_menu.addAction(app.import_tags_action)
    app.write_tags_to_exported_audio_action = app._create_action(
        "Export Catalog Audio Copies…",
        slot=app.export_catalog_audio_copies,
    )
    app.write_tags_to_exported_audio_action.setStatusTip(
        "Export original-format catalog audio copies with automatic catalog metadata embedding. No transcode, watermarking, or derivative registration."
    )
    app.write_tags_to_exported_audio_action.setToolTip(
        app.write_tags_to_exported_audio_action.statusTip()
    )
    app.convert_selected_audio_action = app._create_action(
        "Export Audio Derivatives…",
        slot=app.convert_selected_audio,
    )
    audio_export_menu.addAction(app.convert_selected_audio_action)
    app.convert_external_audio_files_action = app._create_action(
        "Convert External Audio Files…",
        slot=app.convert_external_audio_files,
    )
    app.convert_external_audio_files_action.setStatusTip(
        "Plain external file conversion only. Source metadata is stripped, and no catalog metadata, watermarking, or derivative registration is applied."
    )
    app.convert_external_audio_files_action.setToolTip(
        app.convert_external_audio_files_action.statusTip()
    )
    audio_export_menu.addAction(app.convert_external_audio_files_action)
    audio_export_menu.addSeparator()
    audio_export_menu.addAction(app.write_tags_to_exported_audio_action)
    app.export_authenticity_watermarked_audio_action = app._create_action(
        "Export Authentic Masters…",
        slot=app.export_authenticity_watermarked_audio,
    )
    app.export_authenticity_watermarked_audio_action.setStatusTip(
        "Direct watermark master export: WAV, FLAC, or AIFF plus a signed authenticity sidecar."
    )
    app.export_authenticity_watermarked_audio_action.setToolTip(
        app.export_authenticity_watermarked_audio_action.statusTip()
    )
    authenticity_menu.addAction(app.export_authenticity_watermarked_audio_action)
    app.export_authenticity_provenance_audio_action = app._create_action(
        "Export Provenance Copies…",
        slot=app.export_authenticity_provenance_audio,
    )
    app.export_authenticity_provenance_audio_action.setStatusTip(
        "Lossy-copy export with signed lineage sidecars that point back to a watermark-authentic master. No managed derivative registration."
    )
    app.export_authenticity_provenance_audio_action.setToolTip(
        app.export_authenticity_provenance_audio_action.statusTip()
    )
    authenticity_menu.addAction(app.export_authenticity_provenance_audio_action)
    app.export_forensic_watermarked_audio_action = app._create_action(
        "Export Forensic Watermarked Audio…",
        slot=app.export_forensic_watermarked_audio,
    )
    app.export_forensic_watermarked_audio_action.setStatusTip(
        "Recipient-specific lossy delivery export with catalog metadata, a forensic watermark, derivative lineage, and optional ZIP packaging."
    )
    app.export_forensic_watermarked_audio_action.setToolTip(
        app.export_forensic_watermarked_audio_action.statusTip()
    )
    authenticity_menu.addAction(app.export_forensic_watermarked_audio_action)
    authenticity_menu.addSeparator()
    app.inspect_forensic_watermark_action = app._create_action(
        "Inspect Forensic Watermark…",
        slot=app.inspect_forensic_watermark,
    )
    app.inspect_forensic_watermark_action.setStatusTip(
        "Inspect a suspicious audio file and resolve any forensic watermark evidence against the open profile's export ledger."
    )
    app.inspect_forensic_watermark_action.setToolTip(
        app.inspect_forensic_watermark_action.statusTip()
    )
    authenticity_menu.addAction(app.inspect_forensic_watermark_action)
    app.verify_audio_authenticity_action = app._create_action(
        "Verify Audio Authenticity…",
        slot=app.verify_audio_authenticity,
    )
    authenticity_menu.addAction(app.verify_audio_authenticity_action)
    app.quality_dashboard_action = app._create_action(
        "Data Quality Dashboard…",
        slot=app.open_quality_dashboard,
        shortcuts=("Ctrl+Shift+Q", "Meta+Shift+Q"),
    )
    quality_menu.addAction(app.quality_dashboard_action)
    app.gs1_metadata_action = app._create_action(
        "GS1 Metadata…",
        slot=app.open_gs1_dialog,
        shortcuts=("Ctrl+Shift+G", "Meta+Shift+G"),
    )
    metadata_menu.addAction(app.gs1_metadata_action)

    file_menu.addSeparator()
    app.quit_action = app._create_action(
        "Quit",
        slot=app.close,
        standard_key=QKeySequence.Quit,
    )
    file_menu.addAction(app.quit_action)

    settings_menu = app.menu_bar.addMenu("Settings")
    app.settings_action = app._create_action(
        "Application Settings…",
        slot=app.open_settings_dialog,
        shortcuts=("Ctrl+,", "Meta+,"),
    )
    settings_menu.addAction(app.settings_action)
    app.authenticity_keys_action = app._create_action(
        "Audio Authenticity Keys…",
        slot=app.open_audio_authenticity_keys_dialog,
    )
    settings_menu.addAction(app.authenticity_keys_action)

    view_menu = app.menu_bar.addMenu("View")
    app.columns_menu = view_menu.addMenu("Columns")
    app.add_custom_column_action = app._create_action(
        "Add Custom Column…",
        slot=app.add_custom_column,
        shortcuts=("Ctrl+Shift+F", "Meta+Shift+F"),
    )
    app.columns_menu.addAction(app.add_custom_column_action)

    app.remove_custom_column_action = app._create_action(
        "Remove Custom Column…",
        slot=app.remove_custom_column,
        shortcuts=("Ctrl+Alt+Shift+F", "Meta+Alt+Shift+F"),
    )
    app.columns_menu.addAction(app.remove_custom_column_action)

    app.manage_fields_action = app._create_action(
        "Manage Custom Columns…",
        slot=app.manage_custom_columns,
        shortcuts=("Ctrl+Alt+F", "Meta+Alt+F"),
    )
    app.columns_menu.addAction(app.manage_fields_action)
    app.columns_menu.addSeparator()
    app.column_visibility_actions = []

    app.action_ribbon_visibility_action = app._create_action(
        "Show Action Ribbon",
        checkable=True,
        checked=True,
        toggled_slot=app._on_toggle_action_ribbon,
        shortcuts=("Ctrl+Alt+R", "Meta+Alt+R"),
    )
    app.profiles_toolbar_visibility_action = app._create_action(
        "Show Profiles Ribbon",
        checkable=True,
        checked=True,
        toggled_slot=app._on_toggle_profiles_toolbar,
    )
    view_menu.addAction(app.profiles_toolbar_visibility_action)
    view_menu.addAction(app.action_ribbon_visibility_action)

    app.customize_action_ribbon_action = app._create_action(
        "Customize Action Ribbon…",
        slot=app.open_action_ribbon_customizer,
        shortcuts=("Ctrl+Shift+R", "Meta+Shift+R"),
    )
    view_menu.addAction(app.customize_action_ribbon_action)
    view_menu.addSeparator()

    table_view_menu = view_menu.addMenu("Table Layout")
    app.col_width_action = app._create_action(
        "Edit Column Widths",
        checkable=True,
        checked=False,
        toggled_slot=app._on_toggle_col_width,
        shortcuts=("Ctrl+Alt+W", "Meta+Alt+W"),
    )
    table_view_menu.addAction(app.col_width_action)

    app.row_height_action = app._create_action(
        "Edit Row Heights",
        checkable=True,
        checked=False,
        toggled_slot=app._on_toggle_row_height,
        shortcuts=("Ctrl+Alt+H", "Meta+Alt+H"),
    )
    table_view_menu.addAction(app.row_height_action)

    app.act_reorder_columns = app._create_action(
        "Allow Column Reordering",
        checkable=True,
        checked=bool(movable),
        toggled_slot=app._toggle_columns_movable,
        shortcuts=("Ctrl+Alt+O", "Meta+Alt+O"),
    )
    table_view_menu.addAction(app.act_reorder_columns)

    history_menu = app.menu_bar.addMenu("History")
    app.show_history_action = app._create_action(
        "Show Undo History…",
        slot=app.open_history_dialog,
        shortcuts=("Ctrl+Shift+H", "Meta+Shift+H"),
    )
    history_menu.addAction(app.show_history_action)

    app.create_snapshot_action = app._create_action(
        "Create Snapshot…",
        slot=app.create_manual_snapshot,
        shortcuts=("Ctrl+Alt+S", "Meta+Alt+S"),
    )
    history_menu.addAction(app.create_snapshot_action)

    help_menu = app.menu_bar.addMenu("Help")
    app.help_contents_action = app._create_action(
        "Help Contents…",
        slot=lambda: app.open_help_dialog(topic_id="overview", parent=app),
        shortcuts=("F1",),
    )
    help_menu.addAction(app.help_contents_action)

    app.view_info_action = app._create_action(
        "About ISRC Catalog Manager…",
        slot=app.show_settings_summary,
    )
    help_menu.addAction(app.view_info_action)

    app.diagnostics_action = app._create_action(
        "Diagnostics…",
        slot=app.open_diagnostics_dialog,
        shortcuts=("Ctrl+Alt+D", "Meta+Alt+D"),
    )
    help_menu.addAction(app.diagnostics_action)

    app.application_log_action = app._create_action(
        "Application Log…",
        slot=app.open_application_log_dialog,
        shortcuts=("Ctrl+Alt+L", "Meta+Alt+L"),
    )
    help_menu.addAction(app.application_log_action)

    help_menu.addSeparator()

    app.open_logs_action = app._create_action(
        "Open Logs Folder…",
        slot=lambda: app._open_local_path(app.logs_dir, "Open Log Folder"),
        shortcuts=("Ctrl+Shift+L", "Meta+Shift+L"),
    )
    help_menu.addAction(app.open_logs_action)

    app.open_data_folder_action = app._create_action(
        "Open Data Folder…",
        slot=lambda: app._open_local_path(app.data_root, "Open Data Folder"),
        shortcuts=("Ctrl+Alt+Shift+L", "Meta+Alt+Shift+L"),
    )
    help_menu.addAction(app.open_data_folder_action)


def _build_action_ribbon_toolbar(app: Any) -> None:
    app.action_ribbon_toolbar = QToolBar("Action Ribbon", app)
    app.action_ribbon_toolbar.setObjectName("actionRibbonToolbar")
    app.action_ribbon_toolbar.setProperty("role", "actionRibbonToolbar")
    app.action_ribbon_toolbar.setAllowedAreas(Qt.TopToolBarArea)
    app.action_ribbon_toolbar.setMovable(False)
    app.action_ribbon_toolbar.setFloatable(False)
    app.action_ribbon_toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
    app.action_ribbon_toolbar.setContextMenuPolicy(Qt.CustomContextMenu)
    app.action_ribbon_toolbar.customContextMenuRequested.connect(
        app._open_action_ribbon_context_menu
    )
    app.addToolBar(Qt.TopToolBarArea, app.action_ribbon_toolbar)
    app.addToolBarBreak(Qt.TopToolBarArea)


def _build_profiles_toolbar(app: Any, *, last_db: str) -> None:
    app.toolbar = QToolBar("Profiles", app)
    app.toolbar.setObjectName("profilesToolbar")
    app.toolbar.setContentsMargins(0, 0, 0, 5)
    app.addToolBar(Qt.TopToolBarArea, app.toolbar)
    app.toolbar.setMovable(True)
    app.toolbar.addWidget(QLabel("Profile: "))
    app.profile_combo = FocusWheelComboBox()
    app.toolbar.addWidget(app.profile_combo)

    app.profile_combo.currentIndexChanged.connect(app._on_profile_changed)
    app._reload_profiles_list(select_path=last_db)

    btn_new = QPushButton("New…")
    btn_new.clicked.connect(app.create_new_profile)
    app.toolbar.addWidget(btn_new)

    btn_browse = QPushButton("Browse…")
    btn_browse.clicked.connect(app.browse_profile)
    app.toolbar.addWidget(btn_browse)

    btn_reload = QPushButton("Reload List")
    btn_reload.clicked.connect(lambda: app._reload_profiles_list(select_path=app.current_db_path))
    app.toolbar.addWidget(btn_reload)

    btn_remove = QPushButton("Remove…")
    btn_remove.clicked.connect(app.remove_selected_profile)
    app.toolbar.addWidget(btn_remove)
    app.toolbar.addSeparator()
    app.toolbar.addWidget(
        _create_round_help_button(app, "profiles", "Open help for profiles and databases")
    )

    app._action_ribbon_action_ids = []
    app._rebuild_action_ribbon_toolbar()


def _build_catalog_docks(app: Any, *, movable: bool) -> None:
    app.setDockNestingEnabled(True)
    app.setDockOptions(
        app.dockOptions()
        | QMainWindow.AllowNestedDocks
        | QMainWindow.AllowTabbedDocks
        | QMainWindow.AnimatedDocks
    )
    for area in (
        Qt.LeftDockWidgetArea,
        Qt.RightDockWidgetArea,
        Qt.TopDockWidgetArea,
        Qt.BottomDockWidgetArea,
    ):
        app.setTabPosition(area, QTabWidget.North)
    app._dock_placeholder = QWidget()
    app._dock_placeholder.setObjectName("dockPlaceholder")
    app._dock_placeholder.setProperty("role", "workspaceCanvas")
    app._dock_placeholder.setMinimumSize(0, 0)
    app._dock_placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    app.setCentralWidget(app._dock_placeholder)

    app.left_panel = QVBoxLayout()
    app.left_panel.setContentsMargins(14, 14, 14, 14)
    app.left_panel.setSpacing(14)
    app.left_panel.setAlignment(Qt.AlignTop)

    app.add_data_header = QWidget()
    app.add_data_header_layout = QVBoxLayout(app.add_data_header)
    app.add_data_header_layout.setContentsMargins(0, 0, 0, 0)
    app.add_data_header_layout.setSpacing(4)

    app.add_data_title_row = QHBoxLayout()
    app.add_data_title_row.setContentsMargins(0, 0, 0, 0)
    app.add_data_title_row.setSpacing(8)

    app.add_data_title = QLabel("Add Track")
    app.add_data_title.setProperty("role", "sectionTitle")

    app.add_data_subtitle = QLabel(
        "Create a new track with all core metadata, release details, and managed media in one place."
    )
    app.add_data_subtitle.setWordWrap(True)
    app.add_data_subtitle.setProperty("role", "secondary")

    app.add_data_title_row.addWidget(app.add_data_title)
    app.add_data_title_row.addStretch(1)
    app.add_data_title_row.addWidget(
        _create_round_help_button(app, "add-data", "Open help for the Add Track panel")
    )
    app.add_data_header_layout.addLayout(app.add_data_title_row)
    app.add_data_header_layout.addWidget(app.add_data_subtitle)
    app.left_panel.addWidget(app.add_data_header)

    app.add_data_work_context_group, add_data_work_context_layout = app._create_add_data_group(
        "Work Context"
    )
    app.add_data_work_context_summary = QLabel("")
    app.add_data_work_context_summary.setWordWrap(True)
    app.add_data_work_context_summary.setProperty("role", "sectionTitle")
    add_data_work_context_layout.addWidget(app.add_data_work_context_summary)
    app.add_data_work_context_hint = QLabel(
        "Choose the child relationship and optionally point to an existing track version under the same work."
    )
    app.add_data_work_context_hint.setWordWrap(True)
    app.add_data_work_context_hint.setProperty("role", "secondary")
    add_data_work_context_layout.addWidget(app.add_data_work_context_hint)
    app.add_data_work_relationship_label = QLabel("Child Type")
    app.add_data_work_relationship_combo = FocusWheelComboBox()
    app.add_data_work_relationship_combo.setEditable(False)
    app.add_data_work_relationship_combo.currentIndexChanged.connect(
        app._on_add_track_relationship_changed
    )
    add_data_work_context_layout.addWidget(
        app._create_add_data_row(
            app.add_data_work_relationship_label,
            app.add_data_work_relationship_combo,
        )
    )
    app.add_data_work_parent_label = QLabel("Parent Track")
    app.add_data_work_parent_combo = FocusWheelComboBox()
    app.add_data_work_parent_combo.setEditable(False)
    app.add_data_work_parent_combo.currentIndexChanged.connect(
        app._on_add_track_parent_track_changed
    )
    add_data_work_context_layout.addWidget(
        app._create_add_data_row(
            app.add_data_work_parent_label,
            app.add_data_work_parent_combo,
        )
    )
    app.add_data_work_context_actions = QWidget()
    app.add_data_work_context_actions_layout = QHBoxLayout(app.add_data_work_context_actions)
    app.add_data_work_context_actions_layout.setContentsMargins(0, 0, 0, 0)
    app.add_data_work_context_actions_layout.setSpacing(8)
    app.add_data_clear_work_context_button = QPushButton("Clear Work Context")
    app.add_data_clear_work_context_button.clicked.connect(app._clear_work_track_creation_context)
    app.add_data_work_context_actions_layout.addStretch(1)
    app.add_data_work_context_actions_layout.addWidget(app.add_data_clear_work_context_button)
    add_data_work_context_layout.addWidget(app.add_data_work_context_actions)
    app.add_data_work_context_group.setVisible(False)
    app.left_panel.addWidget(app.add_data_work_context_group)

    app.add_data_tabs = QTabWidget()
    app.add_data_tabs.setObjectName("addDataTabs")
    app.add_data_tabs.setDocumentMode(True)
    app.add_data_tabs.setUsesScrollButtons(False)
    app.left_panel.addWidget(app.add_data_tabs)

    def create_add_data_tab(title: str, description: str) -> QVBoxLayout:
        page = QWidget(app.add_data_tabs)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(10)

        intro = QLabel(description, page)
        intro.setWordWrap(True)
        intro.setProperty("role", "secondary")
        page_layout.addWidget(intro)

        app.add_data_tabs.addTab(page, title)
        return page_layout

    track_tab_layout = create_add_data_tab(
        "Track",
        "Capture the track-facing metadata that will be shown across the catalog and browsers.",
    )
    release_tab_layout = create_add_data_tab(
        "Release",
        "Keep album grouping, release timing, and track duration together while you enter the record.",
    )
    codes_tab_layout = create_add_data_tab(
        "Codes",
        "Review generated identifiers and enter the registration values used by exports and rights workflows.",
    )
    media_tab_layout = create_add_data_tab(
        "Media",
        "Attach the managed audio file and artwork stored with this track.",
    )

    app.artist_label = QLabel("Artist")
    app.artist_field = FocusWheelComboBox()
    app.artist_field.setEditable(True)
    app.artist_field.setMinimumWidth(180)

    app.additional_artist_label = QLabel("Additional Artists")
    app.additional_artist_field = FocusWheelComboBox()
    app.additional_artist_field.setEditable(True)
    app.additional_artist_field.setMinimumWidth(180)

    app.track_title_label = QLabel("Track Title")
    app.track_title_field = QLineEdit()
    app.track_title_field.setMinimumWidth(180)

    app.album_title_label = QLabel("Album Title")
    app.album_title_field = FocusWheelComboBox()
    app.album_title_field.setEditable(True)
    app.album_title_field.setCurrentText("")
    app.album_title_field.currentTextChanged.connect(app.autofill_album_metadata)
    app.album_title_field.setMinimumWidth(180)

    app.record_id_label = QLabel("ID")
    app.record_id_field = app._create_add_data_status_field(
        "Assigned automatically when you save this track."
    )

    app.generated_isrc_label = QLabel("ISRC")
    app.generated_isrc_field = app._create_add_data_status_field(
        "Generated automatically using the current ISRC settings."
    )

    app.entry_date_preview_label = QLabel("Entry Date")
    app.entry_date_preview_field = app._create_add_data_status_field(
        "Stamped automatically when the track is first saved."
    )

    app.audio_file_label = QLabel("Audio File")
    app.audio_file_field = QLineEdit()
    app.audio_file_field.setReadOnly(True)
    app.audio_file_field.setPlaceholderText("No audio file selected")
    app.audio_file_field.setMinimumWidth(200)
    app.audio_file_browse_button = QPushButton("Browse…")
    app.audio_file_browse_button.clicked.connect(
        lambda: app._choose_media_into_line_edit("audio_file", app.audio_file_field)
    )
    app.audio_file_clear_button = QPushButton("Clear")
    app.audio_file_clear_button.clicked.connect(app.audio_file_field.clear)
    app.audio_file_row = QWidget()
    app.audio_file_layout = QVBoxLayout(app.audio_file_row)
    app.audio_file_layout.setContentsMargins(0, 0, 0, 0)
    app.audio_file_layout.setSpacing(6)
    app.audio_file_input_row = QWidget()
    app.audio_file_input_layout = QHBoxLayout(app.audio_file_input_row)
    app.audio_file_input_layout.setContentsMargins(0, 0, 0, 0)
    app.audio_file_input_layout.setSpacing(8)
    app.audio_file_input_layout.addWidget(app.audio_file_field, 1)
    app.audio_file_input_layout.addWidget(app.audio_file_browse_button)
    app.audio_file_input_layout.addWidget(app.audio_file_clear_button)
    app.audio_file_layout.addWidget(app.audio_file_input_row)
    app.audio_file_warning_label = QLabel("")
    app.audio_file_warning_label.setWordWrap(True)
    app.audio_file_warning_label.setProperty("role", "supportingText")
    app.audio_file_warning_label.setVisible(False)
    app.audio_file_layout.addWidget(app.audio_file_warning_label)
    app.audio_file_field._lossy_audio_warning_label = app.audio_file_warning_label
    app.audio_file_field.textChanged.connect(
        lambda _text: app._refresh_line_edit_lossy_audio_warning(app.audio_file_field)
    )
    app.audio_file_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    app.release_date_label = QLabel("Release Date")
    app.release_date_field = FocusWheelCalendarWidget()
    app.release_date_field.setSelectedDate(QDate.currentDate())
    app.release_date_field.setMaximumHeight(220)
    app.release_date_field.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
    app.release_date_field.setGridVisible(True)
    app.release_date_field.selectionChanged.connect(app._update_add_data_generated_fields)

    app.iswc_label = QLabel("ISWC")
    app.iswc_field = QLineEdit()
    app.iswc_field.setMinimumWidth(170)

    app.upc_label = QLabel("UPC / EAN")
    app.upc_field = FocusWheelComboBox()
    app.upc_field.setEditable(True)
    app.upc_field.setCurrentText("")
    app.upc_field.setMinimumWidth(170)

    app.genre_label = QLabel("Genre")
    app.genre_field = FocusWheelComboBox()
    app.genre_field.setEditable(True)
    app.genre_field.setCurrentText("")
    app.genre_field.setMinimumWidth(170)

    app.catalog_number_label = QLabel("Catalog#")
    app.catalog_number_field = FocusWheelComboBox()
    app.catalog_number_field.setEditable(True)
    app.catalog_number_field.setMinimumWidth(170)

    app.buma_work_number_label = QLabel("BUMA Wnr.")
    app.buma_work_number_field = QLineEdit()
    app.buma_work_number_field.setMinimumWidth(170)

    app.album_art_label = QLabel("Album Art")
    app.album_art_field = QLineEdit()
    app.album_art_field.setReadOnly(True)
    app.album_art_field.setPlaceholderText("No album art selected")
    app.album_art_field.setMinimumWidth(200)
    app.album_art_browse_button = QPushButton("Browse…")
    app.album_art_browse_button.clicked.connect(
        lambda: app._choose_media_into_line_edit("album_art", app.album_art_field)
    )
    app.album_art_clear_button = QPushButton("Clear")
    app.album_art_clear_button.clicked.connect(app.album_art_field.clear)
    app.album_art_row = QWidget()
    app.album_art_layout = QHBoxLayout(app.album_art_row)
    app.album_art_layout.setContentsMargins(0, 0, 0, 0)
    app.album_art_layout.setSpacing(8)
    app.album_art_layout.addWidget(app.album_art_field, 1)
    app.album_art_layout.addWidget(app.album_art_browse_button)
    app.album_art_layout.addWidget(app.album_art_clear_button)
    app.album_art_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    app.track_len_label = QLabel("Track Length (hh:mm:ss)")
    app.track_len_h = TwoDigitSpinBox()
    app.track_len_h.setRange(0, 99)
    app.track_len_h.setFixedWidth(60)
    app.track_len_m = TwoDigitSpinBox()
    app.track_len_m.setRange(0, 59)
    app.track_len_m.setFixedWidth(50)
    app.track_len_s = TwoDigitSpinBox()
    app.track_len_s.setRange(0, 59)
    app.track_len_s.setFixedWidth(50)

    length_row = QHBoxLayout()
    length_row.setContentsMargins(0, 0, 0, 0)
    length_row.setSpacing(6)
    length_row.addWidget(app.track_len_h)
    length_row.addWidget(QLabel(":"))
    length_row.addWidget(app.track_len_m)
    length_row.addWidget(QLabel(":"))
    length_row.addWidget(app.track_len_s)
    length_row.addStretch(1)

    app.track_length_row = QWidget()
    app.track_length_layout = length_row
    app.track_length_row.setLayout(app.track_length_layout)
    app.track_length_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    app.prev_release_toggle = QRadioButton("Use release year in generated ISRC")
    app.prev_release_toggle.toggled.connect(app._update_add_data_generated_fields)
    app.isrc_rule_label = QLabel("ISRC Rule")

    status_group, status_layout = app._create_add_data_group("Generated")
    status_layout.addWidget(app._create_add_data_row(app.record_id_label, app.record_id_field))
    status_layout.addWidget(
        app._create_add_data_row(app.generated_isrc_label, app.generated_isrc_field)
    )
    status_layout.addWidget(
        app._create_add_data_row(app.entry_date_preview_label, app.entry_date_preview_field)
    )
    status_layout.addWidget(app._create_add_data_row(app.isrc_rule_label, app.prev_release_toggle))

    core_group, core_layout = app._create_add_data_group("Core Details")
    core_layout.addWidget(app._create_add_data_row(app.track_title_label, app.track_title_field))
    core_layout.addWidget(app._create_add_data_row(app.artist_label, app.artist_field))
    core_layout.addWidget(
        app._create_add_data_row(app.additional_artist_label, app.additional_artist_field)
    )
    core_layout.addWidget(app._create_add_data_row(app.genre_label, app.genre_field))

    release_group, release_layout = app._create_add_data_group("Album & Release")
    release_layout.addWidget(app._create_add_data_row(app.album_title_label, app.album_title_field))
    release_layout.addWidget(
        app._create_add_data_row(
            app.release_date_label,
            app.release_date_field,
            top_aligned=True,
        )
    )
    release_layout.addWidget(app._create_add_data_row(app.track_len_label, app.track_length_row))

    codes_group, codes_layout = app._create_add_data_group("Identifiers & Catalog")
    codes_layout.addWidget(app._create_add_data_row(app.iswc_label, app.iswc_field))
    codes_layout.addWidget(app._create_add_data_row(app.upc_label, app.upc_field))
    codes_layout.addWidget(
        app._create_add_data_row(app.catalog_number_label, app.catalog_number_field)
    )
    codes_layout.addWidget(
        app._create_add_data_row(app.buma_work_number_label, app.buma_work_number_field)
    )

    media_group, media_layout = app._create_add_data_group("Managed Media")
    media_layout.addWidget(app._create_add_data_row(app.audio_file_label, app.audio_file_row))
    media_layout.addWidget(app._create_add_data_row(app.album_art_label, app.album_art_row))

    track_tab_layout.addWidget(core_group)
    track_tab_layout.addStretch(1)
    release_tab_layout.addWidget(release_group)
    release_tab_layout.addStretch(1)
    codes_tab_layout.addWidget(status_group)
    codes_tab_layout.addWidget(codes_group)
    codes_tab_layout.addStretch(1)
    media_tab_layout.addWidget(media_group)
    media_tab_layout.addStretch(1)

    app.left_panel.addStretch(1)

    button_row = QHBoxLayout()
    button_row.setContentsMargins(0, 4, 0, 0)
    button_row.setSpacing(8)
    app.cancel_button = QPushButton("Reset Form")
    app.cancel_button.clicked.connect(app.clear_form_fields)
    app.cancel_button.setMinimumHeight(32)
    app.add_album_button = QPushButton("Add Album…")
    app.add_album_button.clicked.connect(app.open_add_album_dialog)
    app.add_album_button.setMinimumHeight(32)
    app.edit_button = QPushButton("Edit Selected")
    app.edit_button.clicked.connect(app.open_selected_editor)
    app.edit_button.setMinimumHeight(32)
    app.edit_button.setToolTip(
        "Open the selected table row, or bulk edit when multiple rows are selected."
    )
    app.save_button = QPushButton("Save Track")
    app.save_button.clicked.connect(app.save)
    app.save_button.setMinimumHeight(32)
    app.save_button.setDefault(True)
    app.delete_button = QPushButton("Delete Selected")
    app.delete_button.clicked.connect(app.delete_entry)
    app.delete_button.setMinimumHeight(32)
    app.delete_button.setToolTip("Delete the currently selected track from the table.")
    button_row.addWidget(app.cancel_button)
    button_row.addWidget(app.add_album_button)
    button_row.addStretch(1)
    button_row.addWidget(app.edit_button)
    button_row.addWidget(app.delete_button)
    button_row.addWidget(app.save_button)
    app.button_row_widget = QWidget()
    app.button_row_widget.setLayout(button_row)
    app.left_panel.addWidget(app.button_row_widget)

    app.add_data_column = QWidget()
    app.add_data_column.setLayout(app.left_panel)
    app.add_data_column.setMinimumWidth(420)
    app.add_data_column.setMaximumWidth(16777215)
    app.add_data_column.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    app.left_widget_container = QWidget()
    app.left_widget_container.setProperty("role", "workspaceCanvas")
    app.left_container_layout = QHBoxLayout(app.left_widget_container)
    app.left_container_layout.setContentsMargins(0, 0, 0, 0)
    app.left_container_layout.setSpacing(0)
    app.left_container_layout.addWidget(app.add_data_column, 0, Qt.AlignTop | Qt.AlignLeft)
    app.left_container_layout.addStretch(1)

    app.left_scroll = QScrollArea()
    app.left_scroll.setWidgetResizable(True)
    app.left_scroll.setWidget(app.left_widget_container)
    app.left_scroll.setMinimumWidth(300)
    app.add_data_dock = QDockWidget("Add Track", app)
    app.add_data_dock.setObjectName("addDataDock")
    app.add_data_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
    app.add_data_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
    app.add_data_dock.setMinimumWidth(320)
    app.add_data_dock.setWidget(app.left_scroll)
    app.addDockWidget(Qt.LeftDockWidgetArea, app.add_data_dock)
    app.add_data_dock.dockLocationChanged.connect(
        lambda *_args: app._schedule_main_dock_state_save()
    )
    app.add_data_dock.topLevelChanged.connect(lambda *_args: app._schedule_main_dock_state_save())
    app.add_data_dock.visibilityChanged.connect(
        lambda visible: app._sync_dock_visibility(
            app.add_data_action, "display/add_data_panel", visible
        )
    )

    app.table_panel_widget = QWidget()
    app.table_panel_widget.setProperty("role", "workspaceCanvas")
    right_panel = QVBoxLayout(app.table_panel_widget)
    right_panel.setContentsMargins(0, 0, 0, 0)
    right_panel.setSpacing(8)
    app.search_layout = QHBoxLayout()

    app.search_column_combo = FocusWheelComboBox()
    app.search_column_combo.setFixedHeight(25)
    app.search_column_combo.setMinimumWidth(140)
    app.search_layout.addWidget(app.search_column_combo)

    app.search_field = QLineEdit()
    app.search_field.setPlaceholderText("Search...")
    app.search_field.setMinimumHeight(25)
    app.search_field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    app.search_button = QPushButton("Reset")
    app.search_button.setMinimumHeight(25)

    app.count_label = QLabel("showing: 0 records")
    app.count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    app.count_label.setMinimumWidth(110)
    app.count_label.setProperty("role", "secondary")
    app.duration_label = QLabel("total: 00:00:00")
    app.duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    app.duration_label.setMinimumWidth(130)
    app.duration_label.setProperty("role", "secondary")

    app.search_field.textChanged.connect(app.apply_search_filter)
    app.search_column_combo.currentIndexChanged.connect(app.apply_search_filter)
    app.search_button.clicked.connect(app.reset_search)

    app.search_layout.addWidget(app.search_field)
    app.search_layout.addWidget(app.count_label, 1)
    app.search_layout.addWidget(app.duration_label)
    app.search_layout.addWidget(app.search_button)
    app.search_layout.addWidget(
        _create_round_help_button(app, "catalog-table", "Open help for the catalog table")
    )
    right_panel.addLayout(app.search_layout)

    app.table = QTableWidget()
    app._rebuild_table_headers()
    app.table.setEditTriggers(QTableWidget.NoEditTriggers)
    app.table.setSelectionBehavior(QAbstractItemView.SelectRows)
    app.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    app.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    app.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    app.table.horizontalHeader().setStretchLastSection(True)
    app.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
    app.table.setWordWrap(False)

    vertical_header = app.table.verticalHeader()
    vertical_header.setDefaultSectionSize(24)
    vertical_header.setMinimumSectionSize(24)

    app.table.setSortingEnabled(True)
    app.table.horizontalHeader().setSectionsMovable(bool(movable))
    app.table.installEventFilter(app)

    try:
        app._load_header_state()
    except Exception:
        pass
    app._bind_header_state_signals()

    try:
        if QApplication.instance() is not None:
            QApplication.instance().aboutToQuit.connect(
                lambda: app._save_header_state(record_history=False)
            )
    except Exception:
        pass

    try:
        app._rebuild_search_column_choices()
    except AttributeError:
        pass
    app._refresh_column_visibility_menu()

    app.col_hint_label = None
    app.row_hint_label = None

    app.table.itemDoubleClicked.connect(app._on_item_double_clicked)
    app.table.itemSelectionChanged.connect(app._on_catalog_selection_changed)
    app.table.setContextMenuPolicy(Qt.CustomContextMenu)
    app.table.customContextMenuRequested.connect(app._on_table_context_menu)

    right_panel.addWidget(app.table)

    app.catalog_table_dock = QDockWidget("Catalog Table", app)
    app.catalog_table_dock.setObjectName("catalogTableDock")
    app.catalog_table_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
    app.catalog_table_dock.setFeatures(
        QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
    )
    app.catalog_table_dock.setMinimumWidth(480)
    app.catalog_table_dock.setWidget(app.table_panel_widget)
    app.addDockWidget(Qt.RightDockWidgetArea, app.catalog_table_dock)
    app.catalog_table_dock.dockLocationChanged.connect(
        lambda *_args: app._schedule_main_dock_state_save()
    )
    app.catalog_table_dock.topLevelChanged.connect(
        lambda *_args: app._schedule_main_dock_state_save()
    )
    app.catalog_table_dock.visibilityChanged.connect(
        lambda visible: app._sync_dock_visibility(
            app.catalog_table_action,
            "display/catalog_table_panel",
            visible,
        )
    )

    app.resizeDocks([app.add_data_dock, app.catalog_table_dock], [460, 820], Qt.Horizontal)

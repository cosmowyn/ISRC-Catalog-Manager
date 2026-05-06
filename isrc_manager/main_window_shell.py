"""Main-window composition helpers for the workspace shell."""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPainter,
    QPalette,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCalendarWidget,
    QDockWidget,
    QGridLayout,
    QGroupBox,
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
    QTableView,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from isrc_manager.catalog_table import (
    CATALOG_ZOOM_DEFAULT_PERCENT,
    CATALOG_ZOOM_MAX_PERCENT,
    CATALOG_ZOOM_MIN_PERCENT,
    CATALOG_ZOOM_STEP_PERCENT,
)
from isrc_manager.code_registry import CatalogIdentifierField
from isrc_manager.paths import RES_DIR
from isrc_manager.theme_builder import THEME_METRIC_SPECS_BY_KEY, theme_setting_defaults
from isrc_manager.ui_common import (
    FocusWheelCalendarWidget,
    FocusWheelComboBox,
    FocusWheelSlider,
    FocusWheelSpinBox,
    TwoDigitSpinBox,
    _create_round_help_button,
)

_CATALOG_TABLE_TOOLBAR_METRIC_KEYS = (
    "catalog_toolbar_top_margin",
    "catalog_toolbar_column_gap",
    "catalog_toolbar_side_group_extra_width",
    "catalog_toolbar_group_margin",
    "catalog_toolbar_group_height",
    "catalog_toolbar_control_gap",
    "catalog_toolbar_control_height",
    "catalog_toolbar_zoom_label_height",
    "catalog_toolbar_zoom_label_font_size",
    "catalog_toolbar_zoom_row_gap",
    "catalog_toolbar_zoom_slider_height",
    "catalog_toolbar_zoom_step_button_size",
)


def build_main_window_shell(app: Any, *, last_db: str, movable: bool) -> None:
    """Compose menus, toolbars, and dock panels for the main window."""

    _build_actions_and_menus(app, movable=movable)
    app._initialize_action_ribbon_registry()
    _build_action_ribbon_toolbar(app)
    _build_profiles_toolbar(app, last_db=last_db)
    _build_catalog_docks(app, movable=movable)
    refresh_saved_layout_controls = getattr(app, "_refresh_saved_layout_controls", None)
    if callable(refresh_saved_layout_controls):
        refresh_saved_layout_controls()
    refresh_boundary = getattr(app, "_queue_top_chrome_boundary_refresh", None)
    if callable(refresh_boundary):
        refresh_boundary()


def _catalog_table_toolbar_theme_metrics(
    app: Any, theme_values: dict[str, object] | None = None
) -> dict[str, int]:
    theme: dict[str, object] = dict(theme_values or {})
    if not theme:
        effective_theme = getattr(app, "_effective_theme_settings", None)
        if callable(effective_theme):
            try:
                theme = dict(effective_theme() or {})
            except Exception:
                theme = {}
    if not theme:
        theme = dict(getattr(app, "theme_settings", {}) or {})

    defaults = theme_setting_defaults()
    metrics: dict[str, int] = {}
    for key in _CATALOG_TABLE_TOOLBAR_METRIC_KEYS:
        spec = THEME_METRIC_SPECS_BY_KEY.get(key)
        fallback = defaults.get(key, spec.default if spec is not None else 0)
        try:
            value = int(theme.get(key, fallback))
        except Exception:
            value = int(fallback)
        if spec is not None:
            value = max(spec.minimum, min(spec.maximum, value))
        else:
            value = max(0, value)
        metrics[key] = value
    return metrics


def _apply_catalog_zoom_value_label_metrics(label: QLabel, *, height: int, font_size: int) -> int:
    label_font = label.font()
    label_font.setPixelSize(font_size)
    label.setFont(label_font)
    effective_height = max(height, QFontMetrics(label_font).height())
    label.setMinimumHeight(effective_height)
    label.setMaximumHeight(effective_height)
    return effective_height


def _catalog_zoom_slider_stack_height(metrics: dict[str, int]) -> int:
    return max(
        1,
        min(
            metrics["catalog_toolbar_zoom_slider_height"],
            metrics["catalog_toolbar_zoom_step_button_size"],
        ),
    )


def _tinted_toolbar_svg_icon(icon_path: Path, color: QColor, size: QSize) -> QIcon:
    source_icon = QIcon(str(icon_path))
    pixmap = source_icon.pixmap(size)
    if pixmap.isNull():
        return source_icon
    tinted = QPixmap(pixmap.size())
    tinted.setDevicePixelRatio(pixmap.devicePixelRatioF())
    tinted.fill(Qt.transparent)
    icon_color = QColor(color)
    if not icon_color.isValid():
        icon_color = QColor("#111827")
    painter = QPainter(tinted)
    try:
        painter.drawPixmap(0, 0, pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), icon_color)
    finally:
        painter.end()
    return QIcon(tinted)


def _sync_search_filter_button_icon(app: Any) -> None:
    button = getattr(app, "search_filter_button", None)
    if button is None:
        return
    funnel_icon_path = RES_DIR() / "icons" / "funnel-fill.svg"
    if not funnel_icon_path.exists():
        button.setIcon(QIcon())
        button.setText("Filter")
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        return
    control_height = button.maximumHeight()
    if control_height <= 0 or control_height >= 10000:
        control_height = button.height()
    if control_height <= 0:
        control_height = 20
    icon_extent = max(8, min(14, control_height - 6))
    button.setIconSize(QSize(icon_extent, icon_extent))
    button.setText("")
    button.setToolButtonStyle(Qt.ToolButtonIconOnly)
    button.setIcon(
        _tinted_toolbar_svg_icon(
            funnel_icon_path,
            button.palette().color(QPalette.ButtonText),
            button.iconSize(),
        )
    )


def _apply_catalog_table_toolbar_theme_metrics(
    app: Any, theme_values: dict[str, object] | None = None
) -> None:
    toolbar_layout = getattr(app, "catalog_table_toolbar_layout", None)
    if toolbar_layout is None:
        return
    metrics = _catalog_table_toolbar_theme_metrics(app, theme_values)
    group_margin = metrics["catalog_toolbar_group_margin"]
    control_gap = metrics["catalog_toolbar_control_gap"]
    control_height = metrics["catalog_toolbar_control_height"]
    zoom_label_height = metrics["catalog_toolbar_zoom_label_height"]
    zoom_label_font_size = metrics["catalog_toolbar_zoom_label_font_size"]
    zoom_step_button_size = metrics["catalog_toolbar_zoom_step_button_size"]

    toolbar_layout.setContentsMargins(0, metrics["catalog_toolbar_top_margin"], 0, 0)
    toolbar_layout.setHorizontalSpacing(metrics["catalog_toolbar_column_gap"])
    toolbar_layout.setVerticalSpacing(0)

    for layout_name in ("search_layout", "catalog_info_layout"):
        layout = getattr(app, layout_name, None)
        if layout is not None:
            layout.setContentsMargins(group_margin, group_margin, group_margin, group_margin)
            layout.setSpacing(control_gap)

    zoom_layout = getattr(app, "catalog_zoom_layout", None)
    if zoom_layout is not None:
        zoom_layout.setContentsMargins(group_margin, group_margin, group_margin, group_margin)
        zoom_layout.setHorizontalSpacing(control_gap)
        zoom_layout.setVerticalSpacing(0)

    zoom_stack_layout = getattr(app, "catalog_zoom_stack_layout", None)
    if zoom_stack_layout is not None:
        zoom_stack_layout.setContentsMargins(0, 0, 0, 0)
        zoom_stack_layout.setSpacing(metrics["catalog_toolbar_zoom_row_gap"])

    for control_name in (
        "search_column_combo",
        "search_field",
        "search_filter_button",
        "search_button",
        "count_label",
        "duration_label",
        "catalog_zoom_reset_button",
    ):
        control = getattr(app, control_name, None)
        if control is not None:
            control.setMinimumHeight(control_height)
            control.setMaximumHeight(control_height)

    search_filter_button = getattr(app, "search_filter_button", None)
    if search_filter_button is not None:
        search_filter_button.setFixedSize(control_height, control_height)
        icon_extent = max(8, min(14, control_height - 6))
        search_filter_button.setIconSize(QSize(icon_extent, icon_extent))
        _sync_search_filter_button_icon(app)

    zoom_value_label = getattr(app, "catalog_zoom_value_label", None)
    effective_zoom_label_height = zoom_label_height
    if zoom_value_label is not None:
        effective_zoom_label_height = _apply_catalog_zoom_value_label_metrics(
            zoom_value_label,
            height=zoom_label_height,
            font_size=zoom_label_font_size,
        )

    zoom_slider = getattr(app, "catalog_zoom_slider", None)
    zoom_slider_height = _catalog_zoom_slider_stack_height(metrics)
    if zoom_slider is not None:
        zoom_slider.setMinimumHeight(zoom_slider_height)
        zoom_slider.setMaximumHeight(zoom_slider_height)

    zoom_stack = getattr(app, "catalog_zoom_stack_widget", None)
    if zoom_stack is not None:
        zoom_stack_height = max(
            zoom_step_button_size,
            effective_zoom_label_height,
            zoom_slider_height,
        )
        zoom_stack.setMinimumHeight(zoom_stack_height)
        zoom_stack.setMaximumHeight(zoom_stack_height)

    for button_name in ("catalog_zoom_decrease_button", "catalog_zoom_increase_button"):
        button = getattr(app, button_name, None)
        if button is not None:
            button.setFixedSize(zoom_step_button_size, zoom_step_button_size)

    groups = tuple(
        group
        for group in (
            getattr(app, "catalog_search_group", None),
            getattr(app, "catalog_info_group", None),
            getattr(app, "catalog_zoom_group", None),
        )
        if group is not None
    )
    if not groups:
        return
    group_height = metrics["catalog_toolbar_group_height"]
    for group in groups:
        group.setFixedHeight(group_height)

    side_group_extra_width = metrics["catalog_toolbar_side_group_extra_width"]
    for group_name in ("catalog_search_group", "catalog_zoom_group"):
        group = getattr(app, group_name, None)
        if group is None:
            continue
        group.setMinimumWidth(0)
        base_width = max(group.sizeHint().width(), group.minimumSizeHint().width())
        group.setMinimumWidth(base_width + side_group_extra_width)


def _build_actions_and_menus(app: Any, *, movable: bool) -> None:
    app.menu_bar = QMenuBar(app)
    app.menu_bar.setNativeMenuBar(False)
    app.menu_bar.setProperty("role", "menuBar")
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
    app.add_track_action = app._create_action(
        "Add Track…",
        slot=app.open_add_track_entry,
        shortcuts=("Ctrl+Alt+N", "Meta+Alt+N"),
    )
    app.add_album_action = app._create_action(
        "Add Album…",
        slot=lambda: app.open_add_album_dialog(inherit_work_context=False),
        shortcuts=("Ctrl+Alt+Shift+N", "Meta+Alt+Shift+N"),
    )
    app.save_entry_action = app._create_action(
        "Save Track",
        slot=app.save,
        standard_key=QKeySequence.Save,
    )
    app.edit_selected_action = app._create_action(
        "Edit Selected…",
        slot=app.open_selected_editor,
    )
    app.edit_selected_action.setShortcut(QKeySequence("Ctrl+Shift+Space"))
    app.edit_selected_action.setShortcutContext(Qt.WidgetShortcut)
    app.album_track_ordering_action = app._create_action(
        "Album Track Ordering",
        slot=app.open_album_track_ordering_dialog,
    )
    app.delete_entry_action = app._create_action(
        "Delete Selected Track",
        slot=app.delete_entry,
        shortcuts=("Delete", "Meta+Backspace"),
    )
    app.reset_form_action = app._create_action(
        "Reset Search Filter",
        slot=app.reset_search,
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

    master_transfer_import_menu = import_menu.addMenu("Master Catalog Transfer")
    app.import_master_transfer_action = app._create_action(
        "Import Master Transfer ZIP…",
        slot=app.import_master_transfer_package,
    )
    master_transfer_import_menu.addAction(app.import_master_transfer_action)

    import_exchange_menu = import_menu.addMenu("Catalog Exchange")
    app.import_xml_action = app._create_action(
        "Import XML…",
        slot=app.import_from_xml,
        shortcuts=("Ctrl+Shift+I", "Meta+Shift+I"),
    )
    import_exchange_menu.addAction(app.import_xml_action)
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

    party_import_menu = import_menu.addMenu("Parties")
    app.import_party_csv_action = app._create_action(
        "Import Parties CSV…",
        slot=lambda: app.import_party_exchange_file("csv"),
    )
    party_import_menu.addAction(app.import_party_csv_action)
    app.import_party_xlsx_action = app._create_action(
        "Import Parties XLSX…",
        slot=lambda: app.import_party_exchange_file("xlsx"),
    )
    party_import_menu.addAction(app.import_party_xlsx_action)
    app.import_party_json_action = app._create_action(
        "Import Parties JSON…",
        slot=lambda: app.import_party_exchange_file("json"),
    )
    party_import_menu.addAction(app.import_party_json_action)

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

    master_transfer_export_menu = export_submenu.addMenu("Master Catalog Transfer")
    app.export_master_transfer_action = app._create_action(
        "Export Master Transfer ZIP…",
        slot=app.export_master_transfer_package,
    )
    master_transfer_export_menu.addAction(app.export_master_transfer_action)

    exchange_export_menu = export_submenu.addMenu("Catalog Exchange")
    exchange_export_scope_menu = exchange_export_menu.addMenu("Current Scope")
    exchange_export_full_menu = exchange_export_menu.addMenu("Full Catalog")
    app.export_selected_action = app._create_action(
        "Export Selected Exchange XML…",
        slot=app.export_selected_to_xml,
        shortcuts=("Ctrl+E", "Meta+E"),
    )
    exchange_export_scope_menu.addAction(app.export_selected_action)
    app.export_selected_csv_action = app._create_action(
        "Export Selected Exchange CSV…",
        slot=lambda: app.export_exchange_file("csv", selected_only=True),
    )
    exchange_export_scope_menu.addAction(app.export_selected_csv_action)
    app.export_selected_xlsx_action = app._create_action(
        "Export Selected Exchange XLSX…",
        slot=lambda: app.export_exchange_file("xlsx", selected_only=True),
    )
    exchange_export_scope_menu.addAction(app.export_selected_xlsx_action)
    app.export_selected_json_action = app._create_action(
        "Export Selected Exchange JSON…",
        slot=lambda: app.export_exchange_file("json", selected_only=True),
    )
    exchange_export_scope_menu.addAction(app.export_selected_json_action)
    app.export_selected_package_action = app._create_action(
        "Export Selected Exchange ZIP Package…",
        slot=lambda: app.export_exchange_file("package", selected_only=True),
    )
    exchange_export_scope_menu.addAction(app.export_selected_package_action)
    app.export_all_action = app._create_action(
        "Export Full Exchange XML…",
        slot=app.export_full_to_xml,
        shortcuts=("Ctrl+Shift+E", "Meta+Shift+E"),
    )
    exchange_export_full_menu.addAction(app.export_all_action)
    app.export_all_csv_action = app._create_action(
        "Export Full Exchange CSV…",
        slot=lambda: app.export_exchange_file("csv", selected_only=False),
    )
    exchange_export_full_menu.addAction(app.export_all_csv_action)
    app.export_all_xlsx_action = app._create_action(
        "Export Full Exchange XLSX…",
        slot=lambda: app.export_exchange_file("xlsx", selected_only=False),
    )
    exchange_export_full_menu.addAction(app.export_all_xlsx_action)
    app.export_all_json_action = app._create_action(
        "Export Full Exchange JSON…",
        slot=lambda: app.export_exchange_file("json", selected_only=False),
    )
    exchange_export_full_menu.addAction(app.export_all_json_action)
    app.export_all_package_action = app._create_action(
        "Export Full Exchange ZIP Package…",
        slot=lambda: app.export_exchange_file("package", selected_only=False),
    )
    exchange_export_full_menu.addAction(app.export_all_package_action)

    party_export_menu = export_submenu.addMenu("Parties")
    party_export_selected_menu = party_export_menu.addMenu("Selected Parties")
    party_export_full_menu = party_export_menu.addMenu("Full Party Catalog")
    app.export_selected_parties_csv_action = app._create_action(
        "Export Selected Parties CSV…",
        slot=lambda: app.export_party_exchange_file("csv", True),
    )
    party_export_selected_menu.addAction(app.export_selected_parties_csv_action)
    app.export_selected_parties_xlsx_action = app._create_action(
        "Export Selected Parties XLSX…",
        slot=lambda: app.export_party_exchange_file("xlsx", True),
    )
    party_export_selected_menu.addAction(app.export_selected_parties_xlsx_action)
    app.export_selected_parties_json_action = app._create_action(
        "Export Selected Parties JSON…",
        slot=lambda: app.export_party_exchange_file("json", True),
    )
    party_export_selected_menu.addAction(app.export_selected_parties_json_action)
    app.export_all_parties_csv_action = app._create_action(
        "Export Full Party Catalog CSV…",
        slot=lambda: app.export_party_exchange_file("csv", False),
    )
    party_export_full_menu.addAction(app.export_all_parties_csv_action)
    app.export_all_parties_xlsx_action = app._create_action(
        "Export Full Party Catalog XLSX…",
        slot=lambda: app.export_party_exchange_file("xlsx", False),
    )
    party_export_full_menu.addAction(app.export_all_parties_xlsx_action)
    app.export_all_parties_json_action = app._create_action(
        "Export Full Party Catalog JSON…",
        slot=lambda: app.export_party_exchange_file("json", False),
    )
    party_export_full_menu.addAction(app.export_all_parties_json_action)

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

    app.conversion_action = app._create_action(
        "Conversion…",
        slot=app.open_conversion_dialog,
    )
    file_menu.addAction(app.conversion_action)

    file_menu.addSeparator()

    profiles_menu.addSeparator()
    database_submenu = profiles_menu.addMenu("Profile Maintenance")
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

    edit_menu = app.menu_bar.addMenu("Edit")
    edit_menu.addAction(app.undo_action)
    edit_menu.addAction(app.redo_action)
    edit_menu.addSeparator()
    edit_menu.addAction(app.add_track_action)
    edit_menu.addAction(app.add_album_action)
    edit_menu.addAction(app.edit_selected_action)
    edit_menu.addAction(app.album_track_ordering_action)
    edit_menu.addAction(app.delete_entry_action)
    edit_menu.addSeparator()
    edit_menu.addAction(app.copy_action)
    edit_menu.addAction(app.copy_with_headers_action)

    catalog_menu = app.menu_bar.addMenu("Catalog")
    workspace_menu = catalog_menu.addMenu("Workspace")
    workspace_create_menu = workspace_menu.addMenu("Create / Maintain")
    workspace_browse_menu = workspace_menu.addMenu("Browse / Review")
    app.work_manager_action = app._create_action(
        "Work Manager…",
        slot=app.open_work_manager,
        shortcuts=("Ctrl+Alt+W", "Meta+Alt+W"),
    )
    workspace_create_menu.addAction(app.work_manager_action)
    app.release_browser_action = app._create_action(
        "Release Browser…",
        slot=app.open_release_browser,
        shortcuts=("Ctrl+Alt+Shift+R", "Meta+Alt+Shift+R"),
    )
    workspace_browse_menu.addAction(app.release_browser_action)
    app.party_manager_action = app._create_action(
        "Party Manager…",
        slot=app.open_party_manager,
        shortcuts=("Ctrl+Alt+Shift+P", "Meta+Alt+Shift+P"),
    )
    workspace_create_menu.addAction(app.party_manager_action)
    app.contract_manager_action = app._create_action(
        "Contract Manager…",
        slot=app.open_contract_manager,
        shortcuts=("Ctrl+Alt+C", "Meta+Alt+C"),
    )
    workspace_create_menu.addAction(app.contract_manager_action)
    app.code_registry_workspace_action = app._create_action(
        "Code Registry Workspace…",
        slot=app.open_code_registry_workspace,
        shortcuts=("Ctrl+Alt+Shift+K", "Meta+Alt+Shift+K"),
    )
    workspace_create_menu.addAction(app.code_registry_workspace_action)
    app.promo_code_ledger_action = app._create_action(
        "Promo Code Ledger…",
        slot=app.open_promo_code_ledger,
        shortcuts=("Ctrl+Alt+Shift+Y", "Meta+Alt+Shift+Y"),
    )
    workspace_browse_menu.addAction(app.promo_code_ledger_action)
    app.contract_template_workspace_action = app._create_action(
        "Contract Template Workspace…",
        slot=app.open_contract_template_workspace,
        shortcuts=("Ctrl+Alt+Shift+T", "Meta+Alt+Shift+T"),
    )
    workspace_create_menu.addAction(app.contract_template_workspace_action)
    app.rights_matrix_action = app._create_action(
        "Rights Matrix…",
        slot=app.open_rights_matrix,
        shortcuts=("Ctrl+Alt+M", "Meta+Alt+M"),
    )
    workspace_create_menu.addAction(app.rights_matrix_action)
    app.asset_registry_action = app._create_action(
        "Deliverables & Asset Versions…",
        slot=app.open_asset_registry,
        shortcuts=("Ctrl+Alt+A", "Meta+Alt+A"),
    )
    workspace_browse_menu.addAction(app.asset_registry_action)
    app.derivative_ledger_action = app._create_action(
        "Derivative Ledger…",
        slot=app.open_derivative_ledger,
        shortcuts=("Ctrl+Alt+Shift+A", "Meta+Alt+Shift+A"),
    )
    workspace_browse_menu.addAction(app.derivative_ledger_action)
    app.global_search_action = app._create_action(
        "Global Search and Relationships…",
        slot=app.open_global_search,
        shortcuts=("Ctrl+Alt+F", "Meta+Alt+F"),
    )
    app.workspace_add_track_action = app._create_action(
        "Add Track",
        slot=app.open_add_track_workspace,
        shortcuts=("Shift+F2",),
    )
    workspace_create_menu.insertAction(app.work_manager_action, app.workspace_add_track_action)
    app.workspace_catalog_action = app._create_action(
        "Catalog",
        slot=app.open_catalog_workspace,
        shortcuts=("Shift+F3",),
    )
    workspace_browse_menu.insertAction(app.release_browser_action, app.workspace_catalog_action)
    app.workspace_global_search_action = app.global_search_action
    workspace_browse_menu.addAction(app.workspace_global_search_action)
    app.add_data_action = app._create_action(
        "Show Add Track Panel",
        checkable=True,
        checked=False,
        toggled_slot=app._on_toggle_add_data,
        shortcuts=("Ctrl+Shift+D", "Meta+Shift+D"),
    )

    app.catalog_table_action = app._create_action(
        "Show Catalog Table",
        checkable=True,
        checked=True,
        toggled_slot=app._on_toggle_catalog_table,
        shortcuts=("Ctrl+Shift+T", "Meta+Shift+T"),
    )
    metadata_menu = catalog_menu.addMenu("Metadata & Standards")
    audio_menu = catalog_menu.addMenu("Audio")
    audio_ingest_menu = audio_menu.addMenu("Import & Attach")
    audio_export_menu = audio_menu.addMenu("Delivery & Conversion")
    authenticity_menu = audio_menu.addMenu("Authenticity & Provenance")
    quality_menu = catalog_menu.addMenu("Quality & Repair")
    app.media_player_action = app._create_action(
        "Media Player",
        slot=app.open_media_player,
    )
    app.media_player_action.setStatusTip(
        "Open the media player for the selected or first visible track with primary audio."
    )
    app.media_player_action.setToolTip(app.media_player_action.statusTip())
    configure_media_player_icon = getattr(app, "_configure_media_player_action_icon", None)
    if callable(configure_media_player_icon):
        configure_media_player_icon()
    audio_menu.insertAction(audio_ingest_menu.menuAction(), app.media_player_action)
    audio_menu.insertSeparator(audio_ingest_menu.menuAction())
    app.track_import_repair_queue_action = app._create_action(
        "Track Import Repair Queue…",
        slot=app.open_track_import_repair_queue,
    )
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
        shortcuts=("Ctrl+Alt+U", "Meta+Alt+U"),
    )
    audio_ingest_menu.addAction(app.bulk_attach_audio_action)
    app.attach_album_art_action = app._create_action(
        "Attach Album Art File…",
        slot=app.attach_album_art_file_to_catalog,
        shortcuts=("Ctrl+Alt+Shift+U", "Meta+Alt+Shift+U"),
    )
    audio_ingest_menu.addAction(app.attach_album_art_action)
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
        shortcuts=("Ctrl+Alt+V", "Meta+Alt+V"),
    )
    authenticity_menu.addAction(app.verify_audio_authenticity_action)
    app.quality_dashboard_action = app._create_action(
        "Data Quality Dashboard…",
        slot=app.open_quality_dashboard,
        shortcuts=("Ctrl+Shift+Q", "Meta+Shift+Q"),
    )
    quality_menu.addAction(app.quality_dashboard_action)
    quality_menu.addAction(app.track_import_repair_queue_action)
    app.gs1_metadata_action = app._create_action(
        "GS1 Metadata…",
        slot=app.open_gs1_dialog,
        shortcuts=("Ctrl+Shift+G", "Meta+Shift+G"),
    )
    edit_menu.insertAction(app.copy_action, app.gs1_metadata_action)
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
    app.export_settings_action = app._create_action(
        "Export Settings…",
        slot=app.export_application_settings_bundle,
    )
    app.export_settings_action.setStatusTip(
        "Export the current General, GS1, and Theme settings plus stored GS1 assets into a portable ZIP bundle."
    )
    app.export_settings_action.setToolTip(app.export_settings_action.statusTip())
    settings_menu.addAction(app.export_settings_action)
    app.import_settings_action = app._create_action(
        "Import Settings…",
        slot=app.import_application_settings_bundle,
    )
    app.import_settings_action.setStatusTip(
        "Import a portable settings ZIP bundle and apply its General, GS1, and Theme configuration to the current profile."
    )
    app.import_settings_action.setToolTip(app.import_settings_action.statusTip())
    settings_menu.addAction(app.import_settings_action)
    settings_menu.addSeparator()
    app.authenticity_keys_action = app._create_action(
        "Audio Authenticity Keys…",
        slot=app.open_audio_authenticity_keys_dialog,
        shortcuts=("Ctrl+Alt+K", "Meta+Alt+K"),
    )
    settings_menu.addAction(app.authenticity_keys_action)

    view_menu = app.menu_bar.addMenu("View")
    app.view_menu = view_menu
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
        shortcuts=("Ctrl+Alt+Shift+M", "Meta+Alt+Shift+M"),
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

    app.layout_menu = view_menu.addMenu("Layout")
    app.saved_layouts_menu = app.layout_menu.addMenu("Saved Layouts")
    app._connect_noarg_signal(
        app.saved_layouts_menu.aboutToShow,
        app.saved_layouts_menu,
        app._populate_saved_layouts_menu,
    )
    app.add_layout_action = app._create_action("Add Layout", slot=app.add_named_main_window_layout)
    app.layout_menu.addAction(app.add_layout_action)
    app.delete_layout_action = app._create_action(
        "Delete Layout",
        slot=app.delete_named_main_window_layout_interactive,
    )
    app.layout_menu.addAction(app.delete_layout_action)
    app.layout_menu.addSeparator()

    app.catalog_table_layout_menu = app.layout_menu.addMenu("Catalog Table")

    app.col_width_action = app._create_action(
        "Edit Column Widths",
        checkable=True,
        checked=False,
        toggled_slot=app._on_toggle_col_width,
        shortcuts=("Ctrl+Alt+Shift+W", "Meta+Alt+Shift+W"),
    )
    app.catalog_table_layout_menu.addAction(app.col_width_action)

    app.row_height_action = app._create_action(
        "Edit Row Heights",
        checkable=True,
        checked=False,
        toggled_slot=app._on_toggle_row_height,
        shortcuts=("Ctrl+Alt+H", "Meta+Alt+H"),
    )
    app.catalog_table_layout_menu.addAction(app.row_height_action)

    app.act_reorder_columns = app._create_action(
        "Allow Column Reordering",
        checkable=True,
        checked=bool(movable),
        toggled_slot=app._toggle_columns_movable,
        shortcuts=("Ctrl+Alt+O", "Meta+Alt+O"),
    )
    app.catalog_table_layout_menu.addAction(app.act_reorder_columns)

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
        "About Music Catalog Manager…",
        slot=app.show_settings_summary,
    )
    help_menu.addAction(app.view_info_action)

    app.check_for_updates_action = app._create_action(
        "Check for Updates…",
        slot=app.check_for_updates,
    )
    help_menu.addAction(app.check_for_updates_action)

    app.diagnostics_action = app._create_action(
        "Diagnostics…",
        slot=app.open_diagnostics_dialog,
        shortcuts=("Ctrl+Alt+D", "Meta+Alt+D"),
    )
    help_menu.addAction(app.diagnostics_action)

    app.application_storage_admin_action = app._create_action(
        "Application Storage Admin…",
        slot=app.open_application_storage_admin_dialog,
        shortcuts=("Ctrl+Alt+Shift+D", "Meta+Alt+Shift+D"),
    )
    help_menu.addAction(app.application_storage_admin_action)

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
    app._connect_args_signal(
        app.action_ribbon_toolbar.customContextMenuRequested,
        app.action_ribbon_toolbar,
        app._open_action_ribbon_context_menu,
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

    app._connect_args_signal(
        app.profile_combo.currentIndexChanged,
        app.profile_combo,
        app._on_profile_changed,
    )
    app._reload_profiles_list(select_path=last_db)

    btn_new = QPushButton("New…")
    app._connect_noarg_signal(btn_new.clicked, btn_new, app.create_new_profile)
    app.toolbar.addWidget(btn_new)

    btn_browse = QPushButton("Browse…")
    app._connect_noarg_signal(btn_browse.clicked, btn_browse, app.browse_profile)
    app.toolbar.addWidget(btn_browse)

    btn_reload = QPushButton("Reload List")
    btn_reload.clicked.connect(lambda: app._reload_profiles_list(select_path=app.current_db_path))
    app.toolbar.addWidget(btn_reload)

    btn_remove = QPushButton("Remove…")
    app._connect_noarg_signal(btn_remove.clicked, btn_remove, app.remove_selected_profile)
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
        "Add a single track here, then decide whether it links to an existing Work or creates a new Work from the track before save."
    )
    app.add_data_subtitle.setWordWrap(True)
    app.add_data_subtitle.setProperty("role", "secondary")

    app.add_data_title_row.addWidget(app.add_data_title)
    app.add_data_title_row.addStretch(1)
    app.add_data_title_row.addWidget(
        _create_round_help_button(app, "add-data", "Open help for Add Track")
    )
    app.add_data_header_layout.addLayout(app.add_data_title_row)
    app.add_data_header_layout.addWidget(app.add_data_subtitle)
    app.left_panel.addWidget(app.add_data_header)

    app.add_data_work_context_group, add_data_work_context_layout = app._create_add_data_group(
        "Work Governance",
        "Choose how this new track relates to Work records before saving.",
    )
    app.add_data_work_context_summary = QLabel("")
    app.add_data_work_context_summary.setWordWrap(True)
    app.add_data_work_context_summary.setProperty("role", "supportingText")
    add_data_work_context_layout.addWidget(app.add_data_work_context_summary)
    app.add_data_work_context_hint = QLabel(
        "Every new track must either link to an existing Work or create a new Work from the track before it can be saved."
    )
    app.add_data_work_context_hint.setWordWrap(True)
    app.add_data_work_context_hint.setProperty("role", "secondary")
    add_data_work_context_layout.addWidget(app.add_data_work_context_hint)
    app.add_data_work_mode_label = QLabel("Governance")
    app.add_data_work_mode_combo = FocusWheelComboBox()
    app.add_data_work_mode_combo.setEditable(False)
    for value, label in app._work_track_governance_modes():
        app.add_data_work_mode_combo.addItem(label, value)
    app._connect_args_signal(
        app.add_data_work_mode_combo.currentIndexChanged,
        app.add_data_work_mode_combo,
        app._on_add_track_governance_mode_changed,
    )
    add_data_work_context_layout.addWidget(
        app._create_add_data_row(
            app.add_data_work_mode_label,
            app.add_data_work_mode_combo,
        )
    )
    app.add_data_work_work_label = QLabel("Work")
    app.add_data_work_work_combo = FocusWheelComboBox()
    app.add_data_work_work_combo.setEditable(False)
    app.add_data_work_work_combo.addItem("Choose the governing Work…", None)
    app.add_data_work_work_combo.setEnabled(False)
    app._connect_args_signal(
        app.add_data_work_work_combo.currentIndexChanged,
        app.add_data_work_work_combo,
        app._on_add_track_work_changed,
    )
    add_data_work_context_layout.addWidget(
        app._create_add_data_row(
            app.add_data_work_work_label,
            app.add_data_work_work_combo,
        )
    )
    app.add_data_work_relationship_label = QLabel("Child Type")
    app.add_data_work_relationship_combo = FocusWheelComboBox()
    app.add_data_work_relationship_combo.setEditable(False)
    for value in app._work_track_relationship_choices():
        app.add_data_work_relationship_combo.addItem(
            app._work_track_relationship_label(value),
            value,
        )
    app.add_data_work_relationship_combo.setEnabled(False)
    app._connect_args_signal(
        app.add_data_work_relationship_combo.currentIndexChanged,
        app.add_data_work_relationship_combo,
        app._on_add_track_relationship_changed,
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
    app.add_data_work_parent_combo.addItem("No direct parent track", None)
    app.add_data_work_parent_combo.setEnabled(False)
    app._connect_args_signal(
        app.add_data_work_parent_combo.currentIndexChanged,
        app.add_data_work_parent_combo,
        app._on_add_track_parent_track_changed,
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
    app.add_data_clear_work_context_button = QPushButton("Open Work Manager")
    app.add_data_clear_work_context_button.setVisible(False)
    app._connect_noarg_signal(
        app.add_data_clear_work_context_button.clicked,
        app.add_data_clear_work_context_button,
        app._return_from_work_track_creation_context,
    )
    app.add_data_work_context_actions_layout.addStretch(1)
    app.add_data_work_context_actions_layout.addWidget(app.add_data_clear_work_context_button)
    add_data_work_context_layout.addWidget(app.add_data_work_context_actions)
    app.add_data_work_context_group.setVisible(True)

    button_row = QHBoxLayout()
    button_row.setContentsMargins(0, 0, 0, 0)
    button_row.setSpacing(8)
    app.cancel_button = QPushButton("Clear Draft")
    app._connect_noarg_signal(app.cancel_button.clicked, app.cancel_button, app.clear_form_fields)
    app.cancel_button.setMinimumHeight(32)
    app.edit_button = QPushButton("Edit Selected")
    app._connect_noarg_signal(app.edit_button.clicked, app.edit_button, app.open_selected_editor)
    app.edit_button.setMinimumHeight(32)
    app.edit_button.setToolTip(
        "Open the selected table row, or bulk edit when multiple rows are selected."
    )
    app.save_button = QPushButton("Create Work + Save Track")
    app._connect_noarg_signal(app.save_button.clicked, app.save_button, app.save)
    app.save_button.setMinimumHeight(32)
    app.save_button.setDefault(True)
    app.delete_button = QPushButton("Delete Selected")
    app._connect_noarg_signal(app.delete_button.clicked, app.delete_button, app.delete_entry)
    app.delete_button.setMinimumHeight(32)
    app.delete_button.setToolTip("Delete the currently selected track from the table.")
    button_row.addWidget(app.cancel_button)
    button_row.addStretch(1)
    button_row.addWidget(app.edit_button)
    button_row.addWidget(app.delete_button)
    button_row.addWidget(app.save_button)
    app.add_data_actions_group, app.add_data_actions_layout = app._create_add_data_group(
        "Draft Actions"
    )
    app.add_data_actions_group.setObjectName("addDataActionsGroup")
    app.add_data_actions_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    app.add_data_actions_layout.addLayout(button_row)
    app.button_row_widget = app.add_data_actions_group
    app.left_panel.addWidget(app.button_row_widget)

    app.add_data_tabs = QTabWidget()
    app.add_data_tabs.setObjectName("addDataTabs")
    app.add_data_tabs.setDocumentMode(True)
    app.add_data_tabs.setUsesScrollButtons(False)
    app.add_data_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    app.left_panel.addWidget(app.add_data_tabs)

    def create_add_data_tab(title: str) -> QVBoxLayout:
        page = QWidget(app.add_data_tabs)
        page.setProperty("role", "workspaceCanvas")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(10)

        app.add_data_tabs.addTab(page, title)
        return page_layout

    governance_tab_layout = create_add_data_tab("Governance")
    app.add_data_track_tab_index = app.add_data_tabs.count()
    track_tab_layout = create_add_data_tab("Track")
    release_tab_layout = create_add_data_tab("Release")
    codes_tab_layout = create_add_data_tab("Codes")
    media_tab_layout = create_add_data_tab("Media")

    governance_tab_layout.addWidget(app.add_data_work_context_group)
    governance_tab_layout.addStretch(1)
    app.add_data_tabs.setCurrentIndex(app.add_data_track_tab_index)

    add_data_field_min_width = 100
    add_data_field_max_width = 300

    def constrain_add_data_field(widget: QWidget) -> None:
        widget.setMinimumWidth(add_data_field_min_width)
        widget.setMaximumWidth(add_data_field_max_width)
        widget.setSizePolicy(QSizePolicy.Expanding, widget.sizePolicy().verticalPolicy())

    app.artist_label = QLabel("Artist")
    app.artist_field = FocusWheelComboBox()
    app.artist_field.setEditable(True)
    constrain_add_data_field(app.artist_field)

    app.additional_artist_label = QLabel("Additional Artists")
    app.additional_artist_field = FocusWheelComboBox()
    app.additional_artist_field.setEditable(True)
    constrain_add_data_field(app.additional_artist_field)

    app.track_title_label = QLabel("Track Title")
    app.track_title_field = QLineEdit()
    constrain_add_data_field(app.track_title_field)

    app.album_title_label = QLabel("Album Title")
    app.album_title_field = FocusWheelComboBox()
    app.album_title_field.setEditable(True)
    app.album_title_field.setCurrentText("")
    app._connect_noarg_signal(
        app.album_title_field.currentTextChanged,
        app.album_title_field,
        app.autofill_album_metadata,
    )
    constrain_add_data_field(app.album_title_field)

    app.track_number_label = QLabel("Track Number")
    app.track_number_field = FocusWheelSpinBox()
    app.track_number_field.setRange(1, 9999)
    app.track_number_field.setValue(1)
    constrain_add_data_field(app.track_number_field)

    app.record_id_label = QLabel("ID")
    app.record_id_field = app._create_add_data_status_field(
        "Assigned automatically when you save this track."
    )
    constrain_add_data_field(app.record_id_field)

    app.generated_isrc_label = QLabel("ISRC")
    app.generated_isrc_field = app._create_add_data_status_field(
        "Generated automatically using the current ISRC settings."
    )
    constrain_add_data_field(app.generated_isrc_field)

    app.entry_date_preview_label = QLabel("Entry Date")
    app.entry_date_preview_field = app._create_add_data_status_field(
        "Stamped automatically when the track is first saved."
    )
    constrain_add_data_field(app.entry_date_preview_field)

    app.audio_file_label = QLabel("Audio File")
    app.audio_file_field = QLineEdit()
    app.audio_file_field.setReadOnly(True)
    app.audio_file_field.setPlaceholderText("No audio file selected")
    app.audio_file_field.setMinimumWidth(200)
    app.audio_file_browse_button = QPushButton("Browse…")
    app.audio_file_browse_button.clicked.connect(
        lambda: app._choose_media_into_line_edit(
            "audio_file",
            app.audio_file_field,
            hours_widget=app.track_len_h,
            minutes_widget=app.track_len_m,
            seconds_widget=app.track_len_s,
        )
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
    app._connect_noarg_signal(
        app.release_date_field.selectionChanged,
        app.release_date_field,
        app._update_add_data_generated_fields,
    )
    constrain_add_data_field(app.release_date_field)

    app.iswc_label = QLabel("ISWC")
    app.iswc_field = QLineEdit()
    constrain_add_data_field(app.iswc_field)

    app.upc_label = QLabel("UPC / EAN")
    app.upc_field = FocusWheelComboBox()
    app.upc_field.setEditable(True)
    app.upc_field.setCurrentText("")
    constrain_add_data_field(app.upc_field)

    app.genre_label = QLabel("Genre")
    app.genre_field = FocusWheelComboBox()
    app.genre_field.setEditable(True)
    app.genre_field.setCurrentText("")
    constrain_add_data_field(app.genre_field)

    app.catalog_number_label = QLabel("Catalog#")
    app.catalog_number_field = CatalogIdentifierField(
        service_provider=lambda: getattr(app, "code_registry_service", None),
        created_via="add_track",
        parent=app,
    )
    constrain_add_data_field(app.catalog_number_field)

    app.buma_work_number_label = QLabel("BUMA Wnr.")
    app.buma_work_number_field = QLineEdit()
    constrain_add_data_field(app.buma_work_number_field)

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
    app._connect_noarg_signal(
        app.prev_release_toggle.toggled,
        app.prev_release_toggle,
        app._update_add_data_generated_fields,
    )
    app.isrc_rule_label = QLabel("ISRC Rule")

    status_group, status_layout = app._create_add_data_group(
        "Generated",
        "Review the identifiers and entry values assigned by the current profile.",
    )
    status_layout.addWidget(app._create_add_data_row(app.record_id_label, app.record_id_field))
    status_layout.addWidget(
        app._create_add_data_row(app.generated_isrc_label, app.generated_isrc_field)
    )
    status_layout.addWidget(
        app._create_add_data_row(app.entry_date_preview_label, app.entry_date_preview_field)
    )
    status_layout.addWidget(app._create_add_data_row(app.isrc_rule_label, app.prev_release_toggle))

    core_group, core_layout = app._create_add_data_group(
        "Core Details",
        "Capture the track-facing metadata shown across the catalog and browsers.",
    )
    core_layout.addWidget(app._create_add_data_row(app.track_title_label, app.track_title_field))
    core_layout.addWidget(app._create_add_data_row(app.artist_label, app.artist_field))
    core_layout.addWidget(
        app._create_add_data_row(app.additional_artist_label, app.additional_artist_field)
    )
    core_layout.addWidget(app._create_add_data_row(app.genre_label, app.genre_field))

    release_group, release_layout = app._create_add_data_group(
        "Album & Release",
        "Keep album grouping, release timing, and track duration together while you enter the record.",
    )
    release_layout.addWidget(app._create_add_data_row(app.album_title_label, app.album_title_field))
    release_layout.addWidget(
        app._create_add_data_row(app.track_number_label, app.track_number_field)
    )
    release_layout.addWidget(
        app._create_add_data_row(
            app.release_date_label,
            app.release_date_field,
            top_aligned=True,
        )
    )
    release_layout.addWidget(app._create_add_data_row(app.track_len_label, app.track_length_row))

    codes_group, codes_layout = app._create_add_data_group(
        "Identifiers & Catalog",
        "Enter the registration values used by exports, rights workflows, and catalog numbering.",
    )
    codes_layout.addWidget(app._create_add_data_row(app.iswc_label, app.iswc_field))
    codes_layout.addWidget(app._create_add_data_row(app.upc_label, app.upc_field))
    codes_layout.addWidget(
        app._create_add_data_row(app.catalog_number_label, app.catalog_number_field)
    )
    codes_layout.addWidget(
        app._create_add_data_row(app.buma_work_number_label, app.buma_work_number_field)
    )

    media_group, media_layout = app._create_add_data_group(
        "Managed Media",
        "Attach the managed audio file and artwork stored with this track.",
    )
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
    app.add_data_dock.setFeatures(
        QDockWidget.DockWidgetClosable
        | QDockWidget.DockWidgetMovable
        | QDockWidget.DockWidgetFloatable
    )
    app.add_data_dock.setMinimumWidth(320)
    app.add_data_dock.setWidget(app.left_scroll)
    app.addDockWidget(Qt.LeftDockWidgetArea, app.add_data_dock)
    app.add_data_dock.dockLocationChanged.connect(
        lambda *_args: app._schedule_main_dock_state_save()
    )
    app.add_data_dock.topLevelChanged.connect(lambda *_args: app._schedule_main_dock_state_save())
    app._connect_bool_signal(
        app.add_data_dock.visibilityChanged,
        app.add_data_dock,
        app._on_add_track_dock_visibility_changed,
    )

    app.table_panel_widget = QWidget()
    app.table_panel_widget.setObjectName("catalogTablePanel")
    app.table_panel_widget.setProperty("role", "workspaceCanvas")
    catalog_toolbar_metrics = _catalog_table_toolbar_theme_metrics(app)
    catalog_toolbar_group_margin = catalog_toolbar_metrics["catalog_toolbar_group_margin"]
    catalog_toolbar_control_gap = catalog_toolbar_metrics["catalog_toolbar_control_gap"]
    right_panel = QVBoxLayout(app.table_panel_widget)
    right_panel.setContentsMargins(0, 0, 0, 0)
    right_panel.setSpacing(8)
    app.catalog_table_toolbar_layout = QGridLayout()
    app.catalog_table_toolbar_layout.setContentsMargins(
        0,
        catalog_toolbar_metrics["catalog_toolbar_top_margin"],
        0,
        0,
    )
    app.catalog_table_toolbar_layout.setHorizontalSpacing(
        catalog_toolbar_metrics["catalog_toolbar_column_gap"]
    )
    app.catalog_table_toolbar_layout.setVerticalSpacing(0)
    for column in range(3):
        app.catalog_table_toolbar_layout.setColumnStretch(column, 1)

    app.catalog_search_group = QGroupBox("Search")
    app.catalog_search_group.setObjectName("catalogTableSearchGroup")
    app.catalog_search_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    app.search_layout = QHBoxLayout(app.catalog_search_group)
    app.search_layout.setContentsMargins(
        catalog_toolbar_group_margin,
        catalog_toolbar_group_margin,
        catalog_toolbar_group_margin,
        catalog_toolbar_group_margin,
    )
    app.search_layout.setSpacing(catalog_toolbar_control_gap)

    app.search_column_combo = FocusWheelComboBox()
    app.search_column_combo.setMinimumWidth(140)
    app.search_column_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    app.search_layout.addWidget(app.search_column_combo, 0, Qt.AlignVCenter)

    app.search_field = QLineEdit()
    app.search_field.setPlaceholderText("Search...")
    app.search_field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    app.search_button = QPushButton("Reset")
    app.search_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    app.search_filter_button = QToolButton()
    app.search_filter_button.setObjectName("catalogTableSelectionFilterButton")
    app.search_filter_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
    app.search_filter_button.setAutoRaise(False)
    app.search_filter_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    app.search_filter_button.setIconSize(QSize(16, 16))
    app.search_filter_button.setToolTip("Filter to the current table cell.")
    app.search_filter_button.setAccessibleName("Filter to current table cell")
    _sync_search_filter_button_icon(app)

    app.catalog_info_group = QGroupBox("Catalog Totals")
    app.catalog_info_group.setObjectName("catalogTableInfoGroup")
    app.catalog_info_layout = QHBoxLayout(app.catalog_info_group)
    app.catalog_info_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    app.catalog_info_layout.setContentsMargins(
        catalog_toolbar_group_margin,
        catalog_toolbar_group_margin,
        catalog_toolbar_group_margin,
        catalog_toolbar_group_margin,
    )
    app.catalog_info_layout.setSpacing(catalog_toolbar_control_gap)

    app.count_label = QLabel("showing: 0 records")
    app.count_label.setAlignment(Qt.AlignCenter)
    app.count_label.setMinimumWidth(110)
    app.count_label.setProperty("role", "secondary")
    app.duration_label = QLabel("total: 00:00:00")
    app.duration_label.setAlignment(Qt.AlignCenter)
    app.duration_label.setMinimumWidth(130)
    app.duration_label.setProperty("role", "secondary")

    app._connect_noarg_signal(
        app.search_field.textChanged,
        app.search_field,
        app._apply_catalog_search_filter,
    )
    app._connect_noarg_signal(
        app.search_column_combo.currentIndexChanged,
        app.search_column_combo,
        app._apply_catalog_search_filter,
    )
    app._connect_noarg_signal(app.search_button.clicked, app.search_button, app.reset_search)
    app._connect_noarg_signal(
        app.search_filter_button.clicked,
        app.search_filter_button,
        app._set_catalog_filter_from_current_cell,
    )

    app.search_layout.addWidget(app.search_field, 1, Qt.AlignVCenter)
    app.search_layout.addWidget(app.search_filter_button, 0, Qt.AlignVCenter)
    app.search_layout.addWidget(app.search_button, 0, Qt.AlignVCenter)
    app.catalog_info_layout.addStretch(1)
    app.catalog_info_layout.addWidget(app.count_label, 0, Qt.AlignCenter)
    app.catalog_info_layout.addWidget(app.duration_label, 0, Qt.AlignCenter)
    app.catalog_info_layout.addStretch(1)

    app.catalog_zoom_group = QGroupBox("Zoom")
    app.catalog_zoom_group.setObjectName("catalogTableZoomGroup")
    app.catalog_zoom_layout = QGridLayout(app.catalog_zoom_group)
    app.catalog_zoom_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    app.catalog_zoom_layout.setContentsMargins(
        catalog_toolbar_group_margin,
        catalog_toolbar_group_margin,
        catalog_toolbar_group_margin,
        catalog_toolbar_group_margin,
    )
    app.catalog_zoom_layout.setHorizontalSpacing(catalog_toolbar_control_gap)
    app.catalog_zoom_layout.setVerticalSpacing(0)
    app.catalog_zoom_layout.setColumnStretch(0, 0)
    app.catalog_zoom_layout.setColumnStretch(2, 1)
    app.catalog_zoom_stack_widget = QWidget(app.catalog_zoom_group)
    app.catalog_zoom_stack_widget.setObjectName("catalogTableZoomStack")
    app.catalog_zoom_stack_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    app.catalog_zoom_stack_layout = QGridLayout(app.catalog_zoom_stack_widget)
    app.catalog_zoom_stack_layout.setContentsMargins(0, 0, 0, 0)
    app.catalog_zoom_stack_layout.setSpacing(0)
    app.catalog_zoom_value_label = QLabel(f"{CATALOG_ZOOM_DEFAULT_PERCENT}%")
    app.catalog_zoom_value_label.setObjectName("catalogTableZoomValueLabel")
    app.catalog_zoom_value_label.setMinimumWidth(42)
    app.catalog_zoom_value_label.setAlignment(Qt.AlignCenter)
    app.catalog_zoom_value_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    app.catalog_zoom_value_label.setProperty("role", "secondary")
    catalog_zoom_label_height = _apply_catalog_zoom_value_label_metrics(
        app.catalog_zoom_value_label,
        height=catalog_toolbar_metrics["catalog_toolbar_zoom_label_height"],
        font_size=catalog_toolbar_metrics["catalog_toolbar_zoom_label_font_size"],
    )
    app.catalog_zoom_value_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
    app.catalog_zoom_decrease_button = QPushButton()
    app.catalog_zoom_decrease_button.setObjectName("catalogTableZoomDecreaseButton")
    app.catalog_zoom_decrease_button.setText("-")
    app.catalog_zoom_decrease_button.setCursor(Qt.PointingHandCursor)
    app.catalog_zoom_decrease_button.setFixedSize(
        catalog_toolbar_metrics["catalog_toolbar_zoom_step_button_size"],
        catalog_toolbar_metrics["catalog_toolbar_zoom_step_button_size"],
    )
    app.catalog_zoom_decrease_button.setToolTip("Decrease catalog table zoom.")
    app.catalog_zoom_decrease_button.clicked.connect(
        lambda: app._catalog_zoom_controller().step_zoom(-1, immediate=True)
    )
    app.catalog_zoom_slider = FocusWheelSlider(Qt.Horizontal)
    app.catalog_zoom_slider.setObjectName("catalogTableZoomSlider")
    app.catalog_zoom_slider.setRange(CATALOG_ZOOM_MIN_PERCENT, CATALOG_ZOOM_MAX_PERCENT)
    app.catalog_zoom_slider.setSingleStep(CATALOG_ZOOM_STEP_PERCENT)
    app.catalog_zoom_slider.setPageStep(CATALOG_ZOOM_STEP_PERCENT)
    app.catalog_zoom_slider.setTickInterval(CATALOG_ZOOM_STEP_PERCENT)
    app.catalog_zoom_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    catalog_zoom_slider_height = _catalog_zoom_slider_stack_height(catalog_toolbar_metrics)
    app.catalog_zoom_slider.setMinimumHeight(catalog_zoom_slider_height)
    app.catalog_zoom_slider.setMaximumHeight(catalog_zoom_slider_height)
    app.catalog_zoom_slider.setToolTip("Adjust catalog table density without reloading data.")
    app.catalog_zoom_stack_widget.setMinimumHeight(
        max(
            catalog_toolbar_metrics["catalog_toolbar_zoom_step_button_size"],
            catalog_zoom_slider_height,
            catalog_zoom_label_height,
        )
    )
    app.catalog_zoom_stack_widget.setMaximumHeight(app.catalog_zoom_stack_widget.minimumHeight())
    app.catalog_zoom_stack_layout.addWidget(
        app.catalog_zoom_slider,
        0,
        0,
        Qt.AlignVCenter,
    )
    app.catalog_zoom_stack_layout.addWidget(
        app.catalog_zoom_value_label,
        0,
        0,
        Qt.AlignHCenter | Qt.AlignTop,
    )
    app.catalog_zoom_increase_button = QPushButton()
    app.catalog_zoom_increase_button.setObjectName("catalogTableZoomIncreaseButton")
    app.catalog_zoom_increase_button.setText("+")
    app.catalog_zoom_increase_button.setCursor(Qt.PointingHandCursor)
    app.catalog_zoom_increase_button.setFixedSize(
        catalog_toolbar_metrics["catalog_toolbar_zoom_step_button_size"],
        catalog_toolbar_metrics["catalog_toolbar_zoom_step_button_size"],
    )
    app.catalog_zoom_increase_button.setToolTip("Increase catalog table zoom.")
    app.catalog_zoom_increase_button.clicked.connect(
        lambda: app._catalog_zoom_controller().step_zoom(1, immediate=True)
    )
    app.catalog_zoom_reset_button = QPushButton("Reset")
    app.catalog_zoom_reset_button.setObjectName("catalogTableZoomResetButton")
    app.catalog_zoom_reset_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    app.catalog_zoom_reset_button.setToolTip("Reset catalog table zoom to 100%.")
    app.catalog_zoom_reset_button.clicked.connect(
        lambda: app._catalog_zoom_controller().reset_zoom(immediate=True)
    )
    app.catalog_zoom_layout.addWidget(app.catalog_zoom_decrease_button, 0, 1, Qt.AlignVCenter)
    app.catalog_zoom_layout.addWidget(app.catalog_zoom_stack_widget, 0, 2, Qt.AlignVCenter)
    app.catalog_zoom_layout.addWidget(app.catalog_zoom_increase_button, 0, 3, Qt.AlignVCenter)
    app.catalog_zoom_layout.addWidget(app.catalog_zoom_reset_button, 0, 4, Qt.AlignVCenter)

    catalog_toolbar_control_height = catalog_toolbar_metrics["catalog_toolbar_control_height"]
    catalog_toolbar_controls = (
        app.search_column_combo,
        app.search_field,
        app.search_filter_button,
        app.search_button,
        app.count_label,
        app.duration_label,
        app.catalog_zoom_slider,
        app.catalog_zoom_reset_button,
    )
    for control in catalog_toolbar_controls:
        control.setMaximumHeight(catalog_toolbar_control_height)
        control.setMinimumHeight(catalog_toolbar_control_height)
    app._apply_catalog_table_toolbar_theme_metrics = (
        lambda theme_values=None: _apply_catalog_table_toolbar_theme_metrics(
            app,
            theme_values,
        )
    )
    app._apply_catalog_table_toolbar_theme_metrics()

    app.catalog_table_help_button = _create_round_help_button(
        app, "catalog-table", "Open help for the catalog table"
    )
    app.catalog_table_toolbar_layout.addWidget(
        app.catalog_search_group,
        0,
        0,
        Qt.AlignLeft | Qt.AlignVCenter,
    )
    app.catalog_table_toolbar_layout.addWidget(
        app.catalog_info_group,
        0,
        1,
        Qt.AlignCenter,
    )
    app.catalog_table_toolbar_layout.addWidget(
        app.catalog_zoom_group,
        0,
        2,
        Qt.AlignRight | Qt.AlignVCenter,
    )
    app.catalog_table_toolbar_layout.addWidget(
        app.catalog_table_help_button,
        0,
        3,
        Qt.AlignRight | Qt.AlignVCenter,
    )
    right_panel.addLayout(app.catalog_table_toolbar_layout)

    app.table = QTableView()
    app._initialize_catalog_table_model_view()
    app._rebuild_table_headers()
    app.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
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
    app.table.viewport().installEventFilter(app)
    app.table.viewport().setAttribute(Qt.WA_AcceptTouchEvents, True)
    app._catalog_zoom_gesture_platform = platform.system().lower()
    if app._catalog_zoom_gesture_platform != "darwin":
        app.table.viewport().grabGesture(Qt.PinchGesture)
    app.catalog_set_filter_shortcut = QShortcut(QKeySequence.Find, app.table)
    app.catalog_set_filter_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
    app._connect_noarg_signal(
        app.catalog_set_filter_shortcut.activated,
        app.catalog_set_filter_shortcut,
        app._set_catalog_filter_from_current_cell,
    )
    app.catalog_edit_selected_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Space"), app.table)
    app.catalog_edit_selected_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
    app.catalog_edit_selected_shortcut.activated.connect(lambda: app.open_selected_editor())
    app._initialize_catalog_zoom_controls()

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

    app._connect_args_signal(
        app.table.doubleClicked,
        app.table,
        app._on_catalog_index_double_clicked,
    )
    app.table.setContextMenuPolicy(Qt.CustomContextMenu)
    app._connect_args_signal(
        app.table.customContextMenuRequested,
        app.table,
        app._on_catalog_table_context_menu,
    )

    right_panel.addWidget(app.table)

    app.catalog_table_dock = QDockWidget("Catalog Table", app)
    app.catalog_table_dock.setObjectName("catalogTableDock")
    app.catalog_table_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
    app.catalog_table_dock.setFeatures(
        QDockWidget.DockWidgetClosable
        | QDockWidget.DockWidgetMovable
        | QDockWidget.DockWidgetFloatable
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

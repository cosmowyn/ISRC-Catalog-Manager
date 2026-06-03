"""Action ribbon registry, persistence, and customization helpers."""

from __future__ import annotations

import json
import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
)

from isrc_manager.app_dialogs import ActionRibbonDialog
from isrc_manager.ui_common import FocusWheelComboBox


def _root_attr(app, name: str, fallback):
    root_module = sys.modules.get(app.__class__.__module__)
    return getattr(root_module, name, fallback) if root_module is not None else fallback


def _menu_class(app):
    return _root_attr(app, "QMenu", QMenu)


def _action_ribbon_dialog_class(app):
    return _root_attr(app, "ActionRibbonDialog", ActionRibbonDialog)


def _action_ribbon_text_button_height(app, widget: QToolButton) -> int:
    toolbar = getattr(app, "action_ribbon_toolbar", None)
    if toolbar is not None:
        for action in toolbar.actions():
            candidate = toolbar.widgetForAction(action)
            if (
                isinstance(candidate, QToolButton)
                and candidate is not widget
                and candidate.property("role") == "actionRibbonButton"
                and candidate.toolButtonStyle() == Qt.ToolButtonTextOnly
            ):
                return max(1, int(candidate.sizeHint().height()))
    original_style = widget.toolButtonStyle()
    widget.setToolButtonStyle(Qt.ToolButtonTextOnly)
    try:
        return max(1, int(widget.sizeHint().height()))
    finally:
        widget.setToolButtonStyle(original_style)


def _action_ribbon_button_object_name(action_id: str) -> str:
    suffix = "".join(part.capitalize() for part in str(action_id).split("_") if part)
    return f"actionRibbonButton{suffix or 'Unnamed'}"


def _configure_action_ribbon_button_widget(app, action_id: str, widget, spec: dict) -> None:
    if widget is None:
        return
    if isinstance(widget, QToolButton):
        widget.setObjectName(_action_ribbon_button_object_name(action_id))
    widget.setProperty("role", "actionRibbonButton")
    widget.setToolTip(app._action_ribbon_button_tooltip(spec))
    if action_id == "media_player" and isinstance(widget, QToolButton):
        button_height = app._action_ribbon_text_button_height(widget)
        widget.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        extent = app._text_scaled_icon_extent(widget.font())
        widget.setIconSize(QSize(extent, extent))
        widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        widget.setFixedHeight(button_height)


def _refresh_media_player_action_surfaces(app) -> None:
    app._configure_media_player_action_icon()
    toolbar = getattr(app, "action_ribbon_toolbar", None)
    action = getattr(app, "media_player_action", None)
    if toolbar is None or action is None:
        return
    widget = toolbar.widgetForAction(action)
    spec = getattr(app, "_action_ribbon_specs_by_id", {}).get("media_player", {})
    app._configure_action_ribbon_button_widget("media_player", widget, spec)


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


def _initialize_action_ribbon_registry(app):
    specs = [
        {
            "id": "add_track",
            "label": "Add Track",
            "category": "Catalog",
            "description": "Open the primary single-track entry workflow with mandatory Work governance.",
            "action": app.add_track_action,
            "default": True,
        },
        {
            "id": "add_album",
            "label": "Add Album",
            "category": "Catalog",
            "description": "Open the batch Add Album workflow with per-track Work governance.",
            "action": app.add_album_action,
            "default": True,
        },
        {
            "id": "media_player",
            "label": "Media Player",
            "category": "Catalog",
            "description": "Open the media player for the selected or first visible track with primary audio.",
            "action": app.media_player_action,
            "default": True,
        },
        {
            "id": "save_entry",
            "label": "Save Track",
            "category": "Edit",
            "description": "Save the current governed track draft from the Add Track panel.",
            "action": app.save_entry_action,
        },
        {
            "id": "edit_selected",
            "label": "Edit Selected",
            "category": "Edit",
            "description": "Open the current selected row or batch in the full editor.",
            "action": app.edit_selected_action,
        },
        {
            "id": "album_track_ordering",
            "label": "Album Track Ordering",
            "category": "Edit",
            "description": "Open the album-scoped ordering workspace for the current selected track.",
            "action": app.album_track_ordering_action,
        },
        {
            "id": "delete_entry",
            "label": "Delete Selected",
            "category": "Edit",
            "description": "Delete the current selected row or rows after confirmation.",
            "action": app.delete_entry_action,
        },
        {
            "id": "undo",
            "label": "Undo",
            "category": "Edit",
            "description": "Undo the latest reversible action from session or profile history.",
            "action": app.undo_action,
        },
        {
            "id": "redo",
            "label": "Redo",
            "category": "Edit",
            "description": "Redo the next available history action.",
            "action": app.redo_action,
        },
        {
            "id": "copy",
            "label": "Copy",
            "category": "Edit",
            "description": "Copy the current table selection.",
            "action": app.copy_action,
        },
        {
            "id": "copy_with_headers",
            "label": "Copy with Headers",
            "category": "Edit",
            "description": "Copy the current table selection with header labels.",
            "action": app.copy_with_headers_action,
        },
        {
            "id": "reset_form",
            "label": "Reset Search Filter",
            "category": "Edit",
            "description": "Clear the current catalog search text and restore the full table.",
            "action": app.reset_form_action,
        },
        {
            "id": "new_profile",
            "label": "New Profile",
            "category": "File",
            "description": "Create a new profile database.",
            "action": app.new_profile_action,
        },
        {
            "id": "open_profile",
            "label": "Open Profile",
            "category": "File",
            "description": "Browse to and open an existing profile database.",
            "action": app.open_profile_action,
        },
        {
            "id": "reload_profiles",
            "label": "Reload Profile List",
            "category": "File",
            "description": "Refresh the known profile list from disk.",
            "action": app.reload_profiles_action,
        },
        {
            "id": "remove_profile",
            "label": "Remove Profile",
            "category": "File",
            "description": "Choose a profile to remove from disk.",
            "action": app.remove_profile_action,
        },
        {
            "id": "import_xml",
            "label": "Import XML",
            "category": "File",
            "description": "Open the exchange import setup surface for supported XML catalog files.",
            "action": app.import_xml_action,
        },
        {
            "id": "import_csv",
            "label": "Import CSV",
            "category": "File",
            "description": "Import tracks, releases, and custom-field data from CSV.",
            "action": app.import_csv_action,
        },
        {
            "id": "import_xlsx",
            "label": "Import XLSX",
            "category": "File",
            "description": "Import tracks, releases, and custom-field data from XLSX.",
            "action": app.import_xlsx_action,
        },
        {
            "id": "import_json",
            "label": "Import JSON",
            "category": "File",
            "description": "Import versioned exchange data from JSON.",
            "action": app.import_json_action,
        },
        {
            "id": "import_package",
            "label": "Import ZIP Package",
            "category": "File",
            "description": "Import a packaged ZIP export with manifest metadata and media copies.",
            "action": app.import_package_action,
        },
        {
            "id": "export_selected",
            "label": "Export Selected Exchange XML",
            "category": "File",
            "description": "Export the current selected catalog rows as exchange XML.",
            "action": app.export_selected_action,
        },
        {
            "id": "export_all",
            "label": "Export Full Exchange XML",
            "category": "File",
            "description": "Export the full active profile catalog as exchange XML.",
            "action": app.export_all_action,
        },
        {
            "id": "export_selected_csv",
            "label": "Export Selected Exchange CSV",
            "category": "File",
            "description": "Export the current selected catalog rows as exchange CSV.",
            "action": app.export_selected_csv_action,
        },
        {
            "id": "export_selected_json",
            "label": "Export Selected Exchange JSON",
            "category": "File",
            "description": "Export the current selected catalog rows as exchange JSON.",
            "action": app.export_selected_json_action,
        },
        {
            "id": "export_package",
            "label": "Export Selected Exchange ZIP Package",
            "category": "File",
            "description": "Create an exchange ZIP package with metadata and referenced media copies.",
            "action": app.export_selected_package_action,
        },
        {
            "id": "backup",
            "label": "Backup Database",
            "category": "File",
            "description": "Create a safety backup of the current profile database.",
            "action": app.backup_action,
        },
        {
            "id": "restore",
            "label": "Restore from Backup",
            "category": "File",
            "description": "Restore the current profile from a chosen backup.",
            "action": app.restore_action,
        },
        {
            "id": "release_browser",
            "label": "Release Browser",
            "category": "Catalog",
            "description": "Browse, edit, duplicate, and attach tracks to first-class releases.",
            "action": app.release_browser_action,
            "default": True,
        },
        {
            "id": "work_manager",
            "label": "Work Manager",
            "category": "Catalog",
            "description": "Review works, manage linked tracks, and handle work governance follow-up.",
            "action": app.work_manager_action,
            "default": True,
        },
        {
            "id": "promo_code_ledger",
            "label": "Promo Code Ledger",
            "category": "Catalog",
            "description": "Import Bandcamp promo-code sheets and manage redemption ledger details.",
            "action": app.promo_code_ledger_action,
        },
        {
            "id": "bulk_attach_audio",
            "label": "Bulk Attach Audio",
            "category": "Catalog",
            "description": "Match audio files to the current selection or visible catalog scope and attach them in one batch.",
            "action": app.bulk_attach_audio_action,
        },
        {
            "id": "attach_album_art",
            "label": "Attach Album Art",
            "category": "Catalog",
            "description": "Match a single image file to an existing catalog track, confirm the target, and attach it as album art.",
            "action": app.attach_album_art_action,
        },
        {
            "id": "import_tags",
            "label": "Import Metadata from Audio Files",
            "category": "Catalog",
            "description": "Read embedded metadata from managed audio files into the catalog.",
            "action": app.import_tags_action,
        },
        {
            "id": "write_tags_audio",
            "label": "Export Catalog Audio Copies",
            "category": "Catalog",
            "description": "Export original-format catalog audio copies with automatic metadata embedding. No transcode, watermarking, or derivative registration.",
            "action": app.write_tags_to_exported_audio_action,
        },
        {
            "id": "convert_selected_audio",
            "label": "Export Audio Derivatives",
            "category": "Catalog",
            "description": "Export managed audio derivatives with catalog tags, hashing, and derivative tracking. Lossless targets stay on the watermark-authentic path; lossy targets export as tagged managed derivatives without recipient-specific forensic watermarking.",
            "action": app.convert_selected_audio_action,
        },
        {
            "id": "forensic_export_audio",
            "label": "Forensic Watermarked Audio",
            "category": "Catalog",
            "description": "Export recipient-specific forensic delivery copies for leak tracing with catalog metadata, final hashing, derivative lineage, and forensic export registration.",
            "action": app.export_forensic_watermarked_audio_action,
        },
        {
            "id": "authenticity_export_audio",
            "label": "Export Authentic Masters",
            "category": "Catalog",
            "description": "Export WAV, FLAC, or AIFF master copies with a direct watermark plus a signed authenticity sidecar.",
            "action": app.export_authenticity_watermarked_audio_action,
        },
        {
            "id": "authenticity_export_provenance_audio",
            "label": "Export Provenance Copies",
            "category": "Catalog",
            "description": "Export lossy copies with signed lineage sidecars that point back to a verified watermark-authentic master. No managed derivative registration.",
            "action": app.export_authenticity_provenance_audio_action,
        },
        {
            "id": "authenticity_verify_audio",
            "label": "Verify Audio Authenticity",
            "category": "Catalog",
            "description": "Verify either a direct authenticity watermark or a signed provenance lineage sidecar.",
            "action": app.verify_audio_authenticity_action,
        },
        {
            "id": "forensic_inspect_audio",
            "label": "Inspect Forensic Watermark",
            "category": "Catalog",
            "description": "Inspect a suspicious audio file and attempt forensic watermark resolution against the export ledger in the open profile.",
            "action": app.inspect_forensic_watermark_action,
        },
        {
            "id": "convert_external_audio",
            "label": "Convert External Audio Files",
            "category": "Catalog",
            "description": "Convert one or more external audio files with the utility workflow only: inherited source metadata is stripped, and no catalog metadata, watermarking, or derivative registration is applied.",
            "action": app.convert_external_audio_files_action,
        },
        {
            "id": "quality_dashboard",
            "label": "Quality Dashboard",
            "category": "Catalog",
            "description": "Scan the profile for metadata, release, media, and integrity issues.",
            "action": app.quality_dashboard_action,
            "default": True,
        },
        {
            "id": "track_import_repair_queue",
            "label": "Track Import Repair Queue",
            "category": "Catalog",
            "description": "Review import rows that could not be governed or validated before entering the live catalog.",
            "action": app.track_import_repair_queue_action,
        },
        {
            "id": "gs1_metadata",
            "label": "GS1 Metadata",
            "category": "Catalog",
            "description": "Open GS1 metadata for the current selected track or batch.",
            "action": app.gs1_metadata_action,
            "default": True,
        },
        {
            "id": "settings",
            "label": "Application Settings",
            "category": "Settings",
            "description": "Open the consolidated application and profile settings dialog.",
            "action": app.settings_action,
            "default": True,
        },
        {
            "id": "export_settings",
            "label": "Export Settings",
            "category": "Settings",
            "description": "Export the current General, GS1, and Theme settings into a portable ZIP bundle.",
            "action": app.export_settings_action,
        },
        {
            "id": "import_settings",
            "label": "Import Settings",
            "category": "Settings",
            "description": "Import a portable ZIP bundle and apply its General, GS1, and Theme settings to the current profile.",
            "action": app.import_settings_action,
        },
        {
            "id": "authenticity_keys",
            "label": "Audio Authenticity Keys",
            "category": "Settings",
            "description": "Generate Ed25519 keys, set the default signer, and review local key availability.",
            "action": app.authenticity_keys_action,
        },
        {
            "id": "add_custom_column",
            "label": "Add Custom Column",
            "category": "View",
            "description": "Create a new custom metadata column definition.",
            "action": app.add_custom_column_action,
        },
        {
            "id": "manage_fields",
            "label": "Manage Custom Columns",
            "category": "View",
            "description": "Rename, reorder, or update existing custom columns.",
            "action": app.manage_fields_action,
        },
        {
            "id": "show_add_data",
            "label": "Show Add Track Panel",
            "category": "View",
            "description": "Toggle the Add Track dock for single-track entry and follow-up maintenance.",
            "action": app.add_data_action,
        },
        {
            "id": "show_catalog_table",
            "label": "Show Catalog Table",
            "category": "Catalog",
            "description": "Toggle the Catalog Table dock panel.",
            "action": app.catalog_table_action,
        },
        {
            "id": "show_history",
            "label": "Show Undo History",
            "category": "History",
            "description": "Open the persistent history browser.",
            "action": app.show_history_action,
            "default": True,
        },
        {
            "id": "create_snapshot",
            "label": "Create Snapshot",
            "category": "History",
            "description": "Create a manual snapshot restore point for the current profile.",
            "action": app.create_snapshot_action,
            "default": True,
        },
        {
            "id": "help_contents",
            "label": "Help Contents",
            "category": "Help",
            "description": "Open the in-app help browser.",
            "action": app.help_contents_action,
        },
        {
            "id": "diagnostics",
            "label": "Diagnostics",
            "category": "Help",
            "description": "Open diagnostics and repair information for the current profile.",
            "action": app.diagnostics_action,
        },
        {
            "id": "application_storage_admin",
            "label": "Storage Admin",
            "category": "Help",
            "description": "Inspect and permanently clean up retained application-wide storage.",
            "action": app.application_storage_admin_action,
        },
        {
            "id": "application_log",
            "label": "Application Log",
            "category": "Help",
            "description": "Browse the human-readable and structured log views.",
            "action": app.application_log_action,
        },
    ]

    for spec in specs:
        spec["shortcut"] = app._action_shortcut_text(spec.get("action"))

    app._action_ribbon_specs = specs
    app._action_ribbon_specs_by_id = {str(spec["id"]): spec for spec in specs}
    app._action_ribbon_default_ids = [str(spec["id"]) for spec in specs if spec.get("default")]


def _action_ribbon_setting_keys(app) -> list[str]:
    return [
        "display/action_ribbon_visible",
        "display/action_ribbon_actions_json",
    ]


def _current_action_ribbon_visibility(app) -> bool:
    toolbar = getattr(app, "action_ribbon_toolbar", None)
    return bool(isinstance(toolbar, QToolBar) and toolbar.isVisible())


def _normalize_action_ribbon_ids_for_known_ids(action_ids, known_action_ids) -> list[str]:
    known_ids = {
        str(action_id or "").strip()
        for action_id in known_action_ids or []
        if str(action_id or "").strip()
    }
    normalized: list[str] = []
    seen: set[str] = set()
    for action_id in action_ids or []:
        clean_id = str(action_id or "").strip()
        if not clean_id or clean_id in seen:
            continue
        if known_ids and clean_id not in known_ids:
            continue
        seen.add(clean_id)
        normalized.append(clean_id)
    return normalized


def _normalize_action_ribbon_ids(app, action_ids) -> list[str]:
    known_action_ids = list(getattr(app, "_action_ribbon_specs_by_id", {}).keys())
    return app._normalize_action_ribbon_ids_for_known_ids(action_ids, known_action_ids)


def _load_saved_action_ribbon_action_ids(app) -> list[str]:
    setting_key = "display/action_ribbon_actions_json"
    if not app.settings.contains(setting_key):
        return list(getattr(app, "_action_ribbon_default_ids", []))

    raw_value = app.settings.value(setting_key, "[]")
    parsed_ids = raw_value
    if isinstance(raw_value, str):
        try:
            parsed_ids = json.loads(raw_value)
        except Exception:
            return list(getattr(app, "_action_ribbon_default_ids", []))
    elif not isinstance(raw_value, list):
        parsed_ids = []
    normalized_ids = app._normalize_action_ribbon_ids(parsed_ids)
    if not normalized_ids and parsed_ids:
        return list(getattr(app, "_action_ribbon_default_ids", []))
    return normalized_ids


def _capture_current_action_ribbon_layout_snapshot(app) -> dict[str, object]:
    action_ids = app._normalize_action_ribbon_ids(getattr(app, "_action_ribbon_action_ids", []))
    if not action_ids:
        action_ids = list(getattr(app, "_action_ribbon_default_ids", []))
    return {
        "schema_version": 1,
        "action_ids": action_ids,
        "visible": app._current_action_ribbon_visibility(),
    }


def _resolve_saved_layout_action_ribbon_snapshot(
    app,
    snapshot: dict[str, object],
) -> tuple[list[str], bool]:
    current_action_ids = app._normalize_action_ribbon_ids(
        getattr(app, "_action_ribbon_action_ids", [])
    )
    return app._resolve_saved_layout_action_ribbon_snapshot_payload(
        snapshot,
        current_action_ids=current_action_ids,
        current_visible=app._current_action_ribbon_visibility(),
        default_action_ids=list(getattr(app, "_action_ribbon_default_ids", [])),
        known_action_ids=list(getattr(app, "_action_ribbon_specs_by_id", {}).keys()),
    )


def _resolve_saved_layout_action_ribbon_snapshot_payload(
    snapshot: dict[str, object],
    *,
    current_action_ids,
    current_visible: bool,
    default_action_ids,
    known_action_ids,
) -> tuple[list[str], bool]:
    normalized_current_action_ids = _normalize_action_ribbon_ids_for_known_ids(
        current_action_ids,
        known_action_ids,
    )
    if not normalized_current_action_ids:
        normalized_current_action_ids = _normalize_action_ribbon_ids_for_known_ids(
            default_action_ids,
            known_action_ids,
        )

    ribbon_snapshot = snapshot.get("action_ribbon")
    if isinstance(ribbon_snapshot, dict):
        action_ids = _normalize_action_ribbon_ids_for_known_ids(
            ribbon_snapshot.get("action_ids"),
            known_action_ids,
        )
        if not action_ids:
            action_ids = list(normalized_current_action_ids)
        visible_value = ribbon_snapshot.get("visible")
        if visible_value is None:
            visible_value = snapshot.get("action_ribbon_visible", current_visible)
        return action_ids, bool(visible_value)

    legacy_visible = snapshot.get("action_ribbon_visible")
    if legacy_visible is None:
        legacy_visible = current_visible
    return list(normalized_current_action_ids), bool(legacy_visible)


def _store_action_ribbon_preferences(
    app,
    action_ids,
    visible: bool,
    *,
    sync: bool = True,
) -> None:
    normalized_ids = app._normalize_action_ribbon_ids(action_ids)
    if not normalized_ids:
        normalized_ids = list(getattr(app, "_action_ribbon_default_ids", []))
    try:
        app.settings.setValue(
            "display/action_ribbon_actions_json",
            json.dumps(normalized_ids),
        )
        app.settings.setValue("display/action_ribbon_visible", bool(visible))
        if sync:
            app.settings.sync()
    except Exception as e:
        app.logger.warning("Failed to store action ribbon preferences: %s", e)


def _action_ribbon_button_tooltip(app, spec: dict) -> str:
    parts = [str(spec.get("label") or "").strip()]
    description = str(spec.get("description") or "").strip()
    shortcut_text = str(spec.get("shortcut") or "").strip()
    if description:
        parts.append(description)
    if shortcut_text:
        parts.append(f"Shortcut: {shortcut_text}")
    return "\n".join(part for part in parts if part)


def _build_saved_layout_ribbon_widget(app, parent: QWidget) -> QWidget:
    container = QWidget(parent)
    container.setObjectName("savedLayoutRibbonControls")
    container.setProperty("role", "actionRibbonCluster")
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    selector = FocusWheelComboBox(container)
    selector.setObjectName("savedLayoutSelector")
    selector.setMinimumContentsLength(14)
    selector.setSizeAdjustPolicy(QComboBox.AdjustToContents)
    selector.setInsertPolicy(QComboBox.NoInsert)
    selector.setProperty("role", "actionRibbonSelector")
    app._connect_args_signal(selector.activated, selector, app._on_saved_layout_selected)
    layout.addWidget(selector)

    save_button = QPushButton("Save Layout", container)
    save_button.setObjectName("savedLayoutAddButton")
    save_button.setProperty("role", "actionRibbonButton")
    app._connect_noarg_signal(save_button.clicked, save_button, app.add_named_main_window_layout)
    layout.addWidget(save_button)

    delete_button = QPushButton("Delete Layout", container)
    delete_button.setObjectName("savedLayoutDeleteButton")
    delete_button.setProperty("role", "actionRibbonButton")
    delete_button.clicked.connect(
        lambda: app.delete_named_main_window_layout_interactive(selector.currentData())
    )
    layout.addWidget(delete_button)

    app.saved_layout_selector = selector
    app.saved_layout_add_button = save_button
    app.saved_layout_delete_button = delete_button
    app._refresh_saved_layout_controls()
    return container


def _rebuild_action_ribbon_toolbar(app):
    toolbar = getattr(app, "action_ribbon_toolbar", None)
    if toolbar is None:
        return

    toolbar.clear()
    action_ids = app._normalize_action_ribbon_ids(getattr(app, "_action_ribbon_action_ids", []))
    app._action_ribbon_action_ids = action_ids

    for action_id in action_ids:
        spec = app._action_ribbon_specs_by_id.get(action_id)
        if spec is None:
            continue
        toolbar.addAction(spec["action"])
        widget = toolbar.widgetForAction(spec["action"])
        app._configure_action_ribbon_button_widget(action_id, widget, spec)

    spacer = QWidget(toolbar)
    spacer.setObjectName("actionRibbonSpacer")
    spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    toolbar.addWidget(spacer)

    toolbar.addWidget(app._build_saved_layout_ribbon_widget(toolbar))

    toolbar.addAction(app.customize_action_ribbon_action)
    customize_widget = toolbar.widgetForAction(app.customize_action_ribbon_action)
    if customize_widget is not None:
        app._configure_action_ribbon_button_widget(
            "customize_action_ribbon",
            customize_widget,
            {
                "label": "Customize Action Ribbon",
                "description": "Choose which quick actions appear in the top action ribbon.",
            },
        )


def _apply_action_ribbon_configuration(app, action_ids: list[str], visible: bool):
    app._action_ribbon_action_ids = app._normalize_action_ribbon_ids(action_ids)
    app._rebuild_action_ribbon_toolbar()
    if hasattr(app, "action_ribbon_visibility_action"):
        app._set_action_checked_silently(app.action_ribbon_visibility_action, bool(visible))
    if hasattr(app, "action_ribbon_toolbar") and app.action_ribbon_toolbar is not None:
        app.action_ribbon_toolbar.setVisible(bool(visible))


def _apply_profiles_toolbar_visibility(app, visible: bool) -> None:
    toolbar = getattr(app, "toolbar", None)
    if toolbar is not None:
        toolbar.setVisible(bool(visible))
        toolbar.updateGeometry()
    if hasattr(app, "profiles_toolbar_visibility_action"):
        app._set_action_checked_silently(
            app.profiles_toolbar_visibility_action,
            bool(visible),
        )
    app._queue_top_chrome_boundary_refresh()


def _open_action_ribbon_context_menu(app, pos):
    toolbar = getattr(app, "action_ribbon_toolbar", None)
    if toolbar is None:
        return
    menu = _menu_class(app)(toolbar)
    menu.addAction(app.customize_action_ribbon_action)
    menu.addSeparator()
    menu.addAction(app.action_ribbon_visibility_action)
    menu.exec(toolbar.mapToGlobal(pos))


def _on_toggle_profiles_toolbar(app, enabled: bool):
    enabled = bool(enabled)

    def mutation():
        app._apply_profiles_toolbar_visibility(enabled)
        app.settings.setValue("display/profiles_toolbar_visible", enabled)
        app.settings.sync()

    app._run_setting_bundle_history_action(
        action_label="Toggle Profiles Ribbon",
        setting_keys=["display/profiles_toolbar_visible"],
        mutation=mutation,
        entity_id="display/profiles_toolbar_visible",
    )


def _on_toggle_action_ribbon(app, enabled: bool):
    enabled = bool(enabled)

    def mutation():
        app._apply_action_ribbon_configuration(
            getattr(app, "_action_ribbon_action_ids", []),
            enabled,
        )
        app._queue_top_chrome_boundary_refresh()
        app._store_action_ribbon_preferences(
            getattr(app, "_action_ribbon_action_ids", []),
            enabled,
        )

    app._run_setting_bundle_history_action(
        action_label="Toggle Action Ribbon",
        setting_keys=app._action_ribbon_setting_keys(),
        mutation=mutation,
        entity_id="display/action_ribbon",
    )


def open_action_ribbon_customizer(app):
    available_actions = [dict(spec) for spec in getattr(app, "_action_ribbon_specs", [])]
    dlg = _action_ribbon_dialog_class(app)(
        available_actions,
        list(getattr(app, "_action_ribbon_action_ids", [])),
        ribbon_visible=bool(
            getattr(app, "action_ribbon_toolbar", None) is not None
            and app.action_ribbon_toolbar.isVisible()
        ),
        parent=app,
    )
    if dlg.exec() != QDialog.Accepted:
        return

    new_action_ids = app._normalize_action_ribbon_ids(dlg.selected_action_ids())
    new_visible = bool(dlg.ribbon_visible())
    current_action_ids = app._normalize_action_ribbon_ids(
        getattr(app, "_action_ribbon_action_ids", [])
    )
    current_visible = bool(
        getattr(app, "action_ribbon_toolbar", None) is not None
        and app.action_ribbon_toolbar.isVisible()
    )

    if new_action_ids == current_action_ids and new_visible == current_visible:
        return

    def mutation():
        app._store_action_ribbon_preferences(new_action_ids, new_visible)
        app._apply_action_ribbon_configuration(new_action_ids, new_visible)

    app._run_setting_bundle_history_action(
        action_label="Customize Action Ribbon",
        setting_keys=app._action_ribbon_setting_keys(),
        mutation=mutation,
        entity_id="display/action_ribbon",
    )

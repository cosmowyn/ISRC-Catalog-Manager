"""Custom-field catalog workflow orchestration."""

from __future__ import annotations

import json
import re
import sys

from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox

from isrc_manager.app_dialogs import CustomColumnsDialog
from isrc_manager.app_prompts import prompt_storage_mode_choice as _prompt_storage_mode_choice
from isrc_manager.blob_icons import BlobIconDialog, finalize_blob_icon_spec
from isrc_manager.constants import FIELD_TYPE_CHOICES, PROMOTED_CUSTOM_FIELD_NAMES
from isrc_manager.file_storage import STORAGE_MODE_DATABASE
from isrc_manager.ui_common import DatePickerDialog


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def load_active_custom_fields(app):
    return app.custom_field_definitions.list_active_fields()


def _custom_field_config_summary(app, fields):
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
    app,
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
        _root_attr("QMessageBox", QMessageBox).warning(
            app,
            "Reserved Column Name",
            "These names are now standard columns and cannot be used as custom fields:\n"
            + "\n".join(sorted(set(conflicting))),
        )
        return False

    current_summary = app._custom_field_config_summary(app.active_custom_fields)
    new_summary = app._custom_field_config_summary(new_fields)
    if current_summary == new_summary:
        return False

    before_snapshot = None
    if app.history_manager is not None:
        before_snapshot = app.history_manager.capture_snapshot(
            kind=f"pre_{action_type.replace('.', '_')}",
            label=f"Before {action_label}",
        )

    try:
        app.custom_field_definitions.sync_fields(app.active_custom_fields, new_fields)
    except Exception as e:
        if before_snapshot is not None:
            try:
                app.history_manager.delete_snapshot(before_snapshot.snapshot_id)
            except Exception:
                pass
        app.conn.rollback()
        app.logger.exception(f"Custom fields update failed: {e}")
        _root_attr("QMessageBox", QMessageBox).critical(
            app, "Fields Error", f"Could not update fields:\n{e}"
        )
        return False

    app._on_custom_fields_changed()

    try:
        changed_summary = json.dumps(
            [
                {"id": f.get("id"), "name": f["name"], "type": f.get("field_type")}
                for f in new_fields
            ]
        )
    except Exception:
        changed_summary = "fields changed"
    app.logger.info("Custom fields updated")
    app._audit("FIELDS", "CustomFieldDefs", ref_id="batch", details=changed_summary)
    app._audit_commit()

    if before_snapshot is not None and app.history_manager is not None:
        after_snapshot = app.history_manager.capture_snapshot(
            kind=f"post_{action_type.replace('.', '_')}",
            label=f"After {action_label}",
        )
        app.history_manager.record_snapshot_action(
            label=action_label,
            action_type=action_type,
            entity_type="CustomFieldDefs",
            entity_id="batch",
            payload={"summary": changed_summary},
            snapshot_before_id=before_snapshot.snapshot_id,
            snapshot_after_id=after_snapshot.snapshot_id,
        )
        app._refresh_history_actions()
    return True


def _prompt_new_custom_field(app):
    name, ok = _root_attr("QInputDialog", QInputDialog).getText(
        app, "Add Custom Column", "Column name:"
    )
    name = (name or "").strip()
    if not (ok and name):
        return None
    if name in PROMOTED_CUSTOM_FIELD_NAMES:
        _root_attr("QMessageBox", QMessageBox).warning(
            app,
            "Reserved Name",
            f"'{name}' is now a standard column and cannot be added as custom.",
        )
        return None
    if any(field.get("name") == name for field in app.active_custom_fields):
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Exists", f"Column '{name}' already exists."
        )
        return None

    field_type, ok = _root_attr("QInputDialog", QInputDialog).getItem(
        app, "Field Type", "Choose type:", FIELD_TYPE_CHOICES, 0, False
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
        opts, ok = _root_attr("QInputDialog", QInputDialog).getMultiLineText(
            app, "Dropdown Options", "Enter options (one per line):"
        )
        if ok:
            options = [option.strip() for option in (opts or "").splitlines() if option.strip()]
            new_field["options"] = json.dumps(options) if options else json.dumps([])
    elif field_type in {"blob_audio", "blob_image"}:
        blob_icon_dialog = _root_attr("BlobIconDialog", BlobIconDialog)(
            kind="audio" if field_type == "blob_audio" else "image",
            title=f"Icon for {name}",
            spec={"mode": "inherit"},
            allow_inherit=True,
            parent=app,
        )
        if blob_icon_dialog.exec() == QDialog.Accepted:
            new_field["blob_icon_payload"] = blob_icon_dialog.current_spec()
    return new_field


def add_custom_column(app):
    new_field = app._prompt_new_custom_field()
    if new_field is None:
        return
    app._apply_custom_field_configuration(
        [*app.active_custom_fields, new_field],
        action_label=f"Add Custom Column: {new_field['name']}",
        action_type="fields.add",
    )


def remove_custom_column(app):
    if not app.active_custom_fields:
        _root_attr("QMessageBox", QMessageBox).information(
            app, "Remove Custom Column", "There are no custom columns to remove."
        )
        return

    choices = [
        f"{field['name']} ({field.get('field_type', 'text')})" for field in app.active_custom_fields
    ]
    choice, ok = _root_attr("QInputDialog", QInputDialog).getItem(
        app,
        "Remove Custom Column",
        "Choose the custom column to remove:",
        choices,
        0,
        False,
    )
    if not ok or not choice:
        return

    remove_index = choices.index(choice)
    field = app.active_custom_fields[remove_index]
    if (
        _root_attr("QMessageBox", QMessageBox).question(
            app,
            "Remove Custom Column",
            f"Remove custom column '{field['name']}'?",
            _root_attr("QMessageBox", QMessageBox).Yes | _root_attr("QMessageBox", QMessageBox).No,
            _root_attr("QMessageBox", QMessageBox).No,
        )
        != _root_attr("QMessageBox", QMessageBox).Yes
    ):
        return

    remaining_fields = [
        candidate for idx, candidate in enumerate(app.active_custom_fields) if idx != remove_index
    ]
    app._apply_custom_field_configuration(
        remaining_fields,
        action_label=f"Remove Custom Column: {field['name']}",
        action_type="fields.remove",
    )


def manage_custom_columns(app):
    dlg = _root_attr("CustomColumnsDialog", CustomColumnsDialog)(app.active_custom_fields, app)
    if dlg.exec() == QDialog.Accepted:
        app._apply_custom_field_configuration(
            dlg.get_fields(),
            action_label="Manage Custom Columns",
            action_type="fields.manage",
        )


def _on_custom_fields_changed(app):
    with app._suspend_table_layout_history():
        app.active_custom_fields = app.load_active_custom_fields()
        app._rebuild_table_headers()

        # Always rebind first (safe if duplicated)
        try:
            app._bind_header_state_signals()
        except Exception as e:
            app.logger.warning("Failed to rebind sectionMoved after custom fields change: %s", e)

        # Then load header state (visual order + widths)
        try:
            app._load_header_state()
        except Exception as e:
            app.logger.warning("Failed to load header state after custom fields change: %s", e)

        try:
            app._save_header_state(record_history=False)
        except Exception as e:
            app.logger.warning("Failed to save header state after custom fields change: %s", e)

        app.refresh_table()
        app._sync_catalog_count_label()
        app.table.viewport().update()


def _catalog_editor_focus_target(cell_target) -> str | None:
    if cell_target is None or getattr(cell_target, "kind", "") != "standard":
        return None
    media_key = str(getattr(cell_target, "standard_media_key", "") or "").strip()
    if media_key:
        return media_key
    standard_field_key = str(getattr(cell_target, "standard_field_key", "") or "").strip()
    return standard_field_key or None


def _on_catalog_index_double_clicked(app, index):
    controller = app._catalog_table_controller()
    cell_target = controller.cell_target(
        index,
        base_column_count=len(app.BASE_HEADERS),
        custom_fields=app.active_custom_fields,
    )
    track_id = cell_target.track_id
    if cell_target.kind == "standard":
        if track_id is None:
            _root_attr("QMessageBox", QMessageBox).warning(
                app, "Edit Track", "Could not determine the selected track."
            )
            return
        app.open_selected_editor(
            track_id,
            initial_focus_target=app._catalog_editor_focus_target(cell_target),
        )
        return

    field = cell_target.custom_field
    if field is None or track_id is None or cell_target.custom_field_id is None:
        return
    field_id = cell_target.custom_field_id
    field_type = cell_target.custom_field_type or "text"
    options = json.loads(field.get("options") or "[]") if field_type == "dropdown" else None

    # --- BLOB fields -> file picker + save, then return ---
    if field_type in ("blob_image", "blob_audio"):
        if field_type == "blob_image":
            flt = "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff);;All files (*)"
        else:
            flt = "Audio (*.wav *.aif *.aiff *.mp3 *.flac *.m4a *.aac *.ogg *.opus);;All files (*)"
        new_path, _ = _root_attr("QFileDialog", QFileDialog).getOpenFileName(
            app, f"Attach file: {field['name']}", "", flt
        )
        if not new_path:
            return
        storage_mode = _root_attr("_prompt_storage_mode_choice", _prompt_storage_mode_choice)(
            app,
            title=f"Attach {field['name']}",
            subject=f"the file for {field['name']}",
            default_mode=STORAGE_MODE_DATABASE,
        )
        if storage_mode is None:
            return
        try:
            app._run_snapshot_history_action(
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
                mutation=lambda: app.cf_save_value(
                    track_id,
                    field_id,
                    value=None,
                    blob_path=new_path,
                    storage_mode=storage_mode,
                ),
            )
            app.refresh_table_preserve_view(focus_id=track_id)
            return
        except Exception as e:
            app.conn.rollback()
            app.logger.exception(f"Custom BLOB save failed: {e}")
            _root_attr("QMessageBox", QMessageBox).critical(
                app, "Custom Field Error", f"Failed to save file:\n{e}"
            )
            return

    # --- Non-BLOB editors (unchanged) ---
    current_val = app.custom_field_values.get_text_value(track_id, field_id)

    options_updated = False
    if field_type == "dropdown":
        choices = options[:] if options else []
        original_options = list(choices)
        if current_val and current_val not in choices:
            choices.append(current_val)
        new_val, ok = _root_attr("QInputDialog", QInputDialog).getItem(
            app,
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
        choice, ok = _root_attr("QInputDialog", QInputDialog).getItem(
            app,
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
        dlg = _root_attr("DatePickerDialog", DatePickerDialog)(
            app, initial_iso_date=init, title=f"Edit: {field['name']}"
        )
        if dlg.exec() != QDialog.Accepted:
            return
        sel = dlg.selected_iso()
        new_val = "" if sel is None else sel
    else:
        new_val, ok = _root_attr("QInputDialog", QInputDialog).getMultiLineText(
            app, f"Edit: {field['name']}", f"{field['name']}:", text=current_val
        )
        if not ok:
            return

    # Upsert for non-BLOB fields
    if new_val == current_val and not options_updated:
        return
    try:

        def mutation():
            if field_type == "dropdown" and options_updated:
                app.custom_field_definitions.update_dropdown_options(field_id, options)
            app.custom_field_values.save_value(track_id, field_id, value=new_val)

        app._run_snapshot_history_action(
            action_label=f"Update Custom Field: {field['name']}",
            action_type="custom_field.value_update",
            entity_type="CustomFieldValue",
            entity_id=f"{track_id}:{field_id}",
            payload={"track_id": track_id, "field_id": field_id, "field_name": field["name"]},
            mutation=mutation,
        )
        app.refresh_table_preserve_view(focus_id=track_id)
    except Exception as e:
        app.conn.rollback()
        app.logger.exception(f"Custom field save failed: {e}")
        _root_attr("QMessageBox", QMessageBox).critical(
            app, "Custom Field Error", f"Failed to save custom field:\n{e}"
        )

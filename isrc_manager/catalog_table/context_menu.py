"""Catalog table context-menu orchestration."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QMessageBox


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback)
        if main_window_module is not None
        else fallback
    )


def _on_catalog_table_context_menu(app, pos):
    controller = app._catalog_table_controller()
    index = controller.prepare_context_menu_selection(app.table.indexAt(pos))
    if not index.isValid():
        return
    row = index.row()
    col = index.column()
    cell_target = controller.cell_target(
        index,
        base_column_count=len(app.BASE_HEADERS),
        custom_fields=app.active_custom_fields,
    )

    menu = _root_attr("QMenu", QMenu)(app)
    track_id = cell_target.track_id
    selected_ids = list(controller.selected_track_ids())
    effective_track_ids = list(
        controller.effective_context_menu_track_ids(
            track_id,
            selected_track_ids=tuple(selected_ids),
        )
    )
    ordered_effective_track_ids = (
        app._proxy_ordered_track_ids(effective_track_ids) or effective_track_ids
    )
    bulk_count = len(effective_track_ids) if effective_track_ids else 1
    edit_label = "Edit Track" if bulk_count <= 1 else f"Bulk Edit {bulk_count} Selected Tracks…"
    act_edit = QAction(edit_label, app)
    act_edit.triggered.connect(lambda: app.open_selected_editor(track_id))
    menu.addAction(act_edit)

    if track_id:
        act_album_track_order = QAction("Album Track Ordering", app)
        act_album_track_order.triggered.connect(
            lambda _checked=False, tid=track_id: app.open_album_track_ordering_dialog(tid)
        )
        menu.addAction(act_album_track_order)

    act_gs1 = QAction("GS1 Metadata…", app)
    act_gs1.triggered.connect(lambda tid=track_id: app.open_gs1_dialog(tid))
    menu.addAction(act_gs1)

    if track_id and app.release_service is not None:
        release = app.release_service.find_primary_release_for_track(track_id)
        if release is not None:
            act_release = QAction("Open Primary Release…", app)
            act_release.triggered.connect(lambda: app.open_release_editor(release.id))
            menu.addAction(act_release)
    if track_id and app.work_service is not None:
        linked_works = app.work_service.list_works_for_track(track_id)
        if linked_works:
            act_work = QAction("Open Linked Work(s)…", app)
            act_work.triggered.connect(lambda: app.open_work_manager(linked_track_id=track_id))
            menu.addAction(act_work)
        act_link_work = QAction("Link Selected Track(s) to Work…", app)
        act_link_work.triggered.connect(lambda: app.open_work_manager())
        menu.addAction(act_link_work)

    act_delete = QAction("Delete Track", app)
    act_delete.triggered.connect(app.delete_entry)
    menu.addAction(act_delete)

    if track_id:
        menu.addSeparator()
        audio_column = controller.column_for_key(app._standard_media_column_key("audio_file"))
        audio_index = (
            controller.view_index_for_track_id(track_id, column=audio_column)
            if audio_column is not None
            else None
        )
        track_has_audio = (
            app._media_cell_has_payload(audio_index, media_key="audio_file")
            if audio_index is not None and audio_index.isValid()
            else (
                app.track_has_media(track_id, "audio_file")
                if app._catalog_proxy_model() is None
                else False
            )
        )
        if track_has_audio:
            export_track_ids = list(ordered_effective_track_ids or [track_id])
            audio_menu = menu.addMenu("Audio")

            act_import_tags = QAction("Import Metadata from Audio Files…", app)
            act_import_tags.triggered.connect(lambda: app.import_tags_from_audio([track_id]))
            audio_menu.addAction(act_import_tags)

            act_convert_selected_audio = QAction(
                "Export Audio Derivatives…",
                app,
            )
            act_convert_selected_audio.triggered.connect(
                lambda: app.convert_selected_audio(export_track_ids)
            )
            audio_menu.addAction(act_convert_selected_audio)

            audio_menu.addSeparator()

            act_export_authenticity = QAction(
                "Export Authentic Masters…",
                app,
            )
            act_export_authenticity.triggered.connect(
                lambda: app.export_authenticity_watermarked_audio(export_track_ids)
            )
            audio_menu.addAction(act_export_authenticity)

            act_export_provenance = QAction(
                "Export Provenance Copies…",
                app,
            )
            act_export_provenance.triggered.connect(
                lambda: app.export_authenticity_provenance_audio(export_track_ids)
            )
            audio_menu.addAction(act_export_provenance)

            act_export_forensic = QAction(
                "Export Forensic Watermarked Audio…",
                app,
            )
            act_export_forensic.triggered.connect(
                lambda: app.export_forensic_watermarked_audio(export_track_ids)
            )
            audio_menu.addAction(act_export_forensic)

            audio_menu.addSeparator()

            act_write_tags = QAction("Export Catalog Audio Copies…", app)
            act_write_tags.triggered.connect(
                lambda: app.export_catalog_audio_copies(export_track_ids)
            )
            audio_menu.addAction(act_write_tags)

            audio_menu.addSeparator()

            act_inspect_forensic = QAction(
                "Inspect Forensic Watermark…",
                app,
            )
            act_inspect_forensic.triggered.connect(app.inspect_forensic_watermark)
            audio_menu.addAction(act_inspect_forensic)

            act_verify_authenticity = QAction(
                "Verify Audio Authenticity…",
                app,
            )
            act_verify_authenticity.triggered.connect(app.verify_audio_authenticity)
            audio_menu.addAction(act_verify_authenticity)

    menu.addSeparator()
    cell_text = str(index.data(Qt.DisplayRole) or "")
    act_filter = QAction(f"Set Filter: '{cell_text}'", app)
    act_filter.triggered.connect(
        lambda _checked=False, filter_text=cell_text: app._set_catalog_filter_text(filter_text)
    )
    menu.addAction(act_filter)

    # Copy actions
    act_copy = QAction("Copy", app)
    act_copy.triggered.connect(lambda: app._copy_selection_to_clipboard(False))
    menu.addAction(act_copy)

    act_copy_hdrs = QAction("Copy with Headers", app)
    act_copy_hdrs.triggered.connect(lambda: app._copy_selection_to_clipboard(True))
    menu.addAction(act_copy_hdrs)

    standard_media_key = cell_target.standard_media_key
    file_menu = None
    storage_menu = None

    def ensure_file_menu():
        nonlocal file_menu
        if file_menu is None:
            menu.addSeparator()
            file_menu = menu.addMenu("File")
        return file_menu

    def ensure_storage_menu():
        nonlocal storage_menu
        if storage_menu is None:
            if file_menu is None:
                menu.addSeparator()
            storage_menu = menu.addMenu("Storage")
        return storage_menu

    if track_id and standard_media_key:
        standard_file_menu = ensure_file_menu()
        focused_track_has_media = app._media_cell_has_payload(
            index,
            media_key=standard_media_key,
        )
        if app._catalog_proxy_model() is None and not focused_track_has_media:
            focused_track_has_media = app.track_has_media(track_id, standard_media_key)
        storage_scope = app._standard_media_storage_conversion_scope(
            ordered_effective_track_ids,
            standard_media_key,
        )
        if focused_track_has_media:
            act_prev = QAction("Preview File…", app)
            act_prev.triggered.connect(
                lambda: app._preview_standard_media_for_track(track_id, standard_media_key)
            )
            standard_file_menu.addAction(act_prev)

        act_attach_standard = QAction("Attach/Replace File…", app)
        act_attach_standard.triggered.connect(
            lambda: app._attach_standard_media_for_track(track_id, standard_media_key)
        )
        standard_file_menu.addAction(act_attach_standard)

        if focused_track_has_media:
            export_basename = app._media_export_basename_for_track(
                track_id,
                standard_media_key,
            )
            act_export_standard = QAction(f"Export '{export_basename}'…", app)
            act_export_standard.triggered.connect(
                lambda: app._export_standard_media_for_track(
                    track_id,
                    standard_media_key,
                    export_basename,
                )
            )
            standard_file_menu.addAction(act_export_standard)

            act_delete_standard = QAction("Delete File…", app)
            act_delete_standard.triggered.connect(
                lambda: app._delete_standard_media_for_track(track_id, standard_media_key)
            )
            standard_file_menu.addAction(act_delete_standard)

        for target_mode in storage_scope["allowed_targets"]:
            action = QAction(
                app._storage_conversion_action_label(
                    target_mode,
                    selection_count=len(ordered_effective_track_ids),
                ),
                app,
            )
            action.triggered.connect(
                lambda checked=False, track_ids=list(
                    ordered_effective_track_ids
                ), key=standard_media_key, mode=target_mode: app._convert_standard_media_for_track(
                    track_ids,
                    key,
                    mode,
                )
            )
            ensure_storage_menu().addAction(action)

    custom_field = cell_target.custom_field
    custom_field_id = cell_target.custom_field_id
    custom_field_type = str(cell_target.custom_field_type or "").strip().lower()
    if (
        track_id is not None
        and custom_field is not None
        and custom_field_id is not None
        and custom_field_type in ("blob_image", "blob_audio")
    ):
        custom_file_menu = ensure_file_menu()
        custom_cell_has_payload = app._media_cell_has_payload(index, field_id=custom_field_id)
        title_column = controller.column_for_key("base:track_title")
        title_index = index.siblingAtColumn(title_column) if title_column is not None else None
        track_title = (
            str(title_index.data(Qt.DisplayRole) or "").strip()
            if title_index is not None and title_index.isValid()
            else ""
        )
        if not track_title:
            track_title = app._get_track_title(track_id) or f"track_{track_id}"

        if custom_cell_has_payload:
            act_prev = QAction("Preview File…", app)
            act_prev.triggered.connect(lambda: app._preview_catalog_blob_for_cell(row, col))
            custom_file_menu.addAction(act_prev)

        act_attach = QAction("Attach/Replace File…", app)
        act_attach.triggered.connect(
            lambda tid=track_id, fid=custom_field_id, ftype=custom_field_type, fname=str(
                custom_field.get("name") or ""
            ): app._attach_blob_for_cell(tid, fid, ftype, fname)
        )
        custom_file_menu.addAction(act_attach)

        if custom_cell_has_payload:
            act_export = QAction(f"Export '{track_title}'…", app)
            act_export.triggered.connect(
                lambda checked=False, tid=track_id, fid=custom_field_id, title=track_title: app.cf_export_blob(
                    tid,
                    fid,
                    app,
                    title,
                )
            )
            custom_file_menu.addAction(act_export)

            def _do_del(
                tid=track_id,
                fid=custom_field_id,
                field_name=str(custom_field.get("name") or ""),
            ):
                if (
                    _root_attr("QMessageBox", QMessageBox).question(
                        app,
                        "Delete File",
                        "Remove the stored file from this cell?",
                        _root_attr("QMessageBox", QMessageBox).Yes
                        | _root_attr("QMessageBox", QMessageBox).No,
                    )
                    != _root_attr("QMessageBox", QMessageBox).Yes
                ):
                    return
                try:
                    app._run_snapshot_history_action(
                        action_label=f"Delete Custom File: {field_name}",
                        action_type="custom_field.blob_delete",
                        entity_type="CustomFieldValue",
                        entity_id=f"{tid}:{fid}",
                        payload={
                            "track_id": tid,
                            "field_id": fid,
                            "field_name": field_name,
                        },
                        mutation=lambda: app.cf_delete_blob(tid, fid),
                    )
                    app.refresh_table_preserve_view(focus_id=tid)
                except Exception as e:
                    app.conn.rollback()
                    app.logger.exception(f"Delete blob failed: {e}")
                    _root_attr("QMessageBox", QMessageBox).critical(
                        app, "Custom Field Error", f"Failed to delete file:\n{e}"
                    )

            act_del = QAction("Delete File…", app)
            act_del.triggered.connect(_do_del)
            custom_file_menu.addAction(act_del)

        storage_scope = app._custom_blob_storage_conversion_scope(
            ordered_effective_track_ids,
            int(custom_field_id),
        )
        for target_mode in storage_scope["allowed_targets"]:
            action = QAction(
                app._storage_conversion_action_label(
                    target_mode,
                    selection_count=len(ordered_effective_track_ids),
                ),
                app,
            )
            action.triggered.connect(
                lambda checked=False, track_ids=list(ordered_effective_track_ids), fid=int(
                    custom_field_id
                ), mode=target_mode: app._convert_custom_blob_storage_mode(
                    track_ids,
                    fid,
                    mode,
                )
            )
            ensure_storage_menu().addAction(action)

    media_export_spec = app._focused_media_export_spec(col)
    if bulk_count > 1 and media_export_spec is not None:
        menu.addSeparator()
        act_bulk_export = QAction(
            f"Export {bulk_count} Files from '{media_export_spec['column_label']}' Column…",
            app,
        )
        act_bulk_export.triggered.connect(
            lambda checked=False, column=col, track_ids=list(
                ordered_effective_track_ids or selected_ids
            ): app._export_focused_media_column(
                column,
                track_ids=track_ids,
            )
        )
        menu.addAction(act_bulk_export)

    menu.exec(app.table.viewport().mapToGlobal(pos))


def _preview_catalog_blob_for_cell(app, row: int, col: int):
    """Directly preview the blob in the given cell (image/audio)."""
    controller = app._catalog_table_controller()
    cell_target = controller.cell_target(
        app.table.model().index(row, col),
        base_column_count=len(app.BASE_HEADERS),
        custom_fields=app.active_custom_fields,
    )
    track_id = cell_target.track_id
    if cell_target.kind == "standard":
        if track_id is None or not cell_target.standard_media_key:
            return
        app._preview_standard_media_for_track(track_id, cell_target.standard_media_key)
        return

    field = cell_target.custom_field
    if field is None or track_id is None or cell_target.custom_field_id is None:
        return

    try:
        if not app.cf_has_blob(track_id, cell_target.custom_field_id):
            return

        field_type = str(cell_target.custom_field_type or "").strip().lower()
        field_name = ""
        try:
            field_name = (
                app.custom_field_definitions.get_field_name(cell_target.custom_field_id)
                if app.custom_field_definitions is not None
                else ""
            )
        except Exception:
            field_name = str(field.get("field_name") or field.get("name") or "").strip()
        try:
            track_title = app._get_track_title(track_id) or f"track_{track_id}"
        except Exception:
            track_title = f"track_{track_id}"
        title = track_title
        if field_type == "blob_audio":
            app._open_audio_preview_for_track(
                track_id,
                app._audio_preview_source_spec_for_custom_field(
                    cell_target.custom_field_id,
                    field_name=field_name,
                ),
                autoplay=True,
            )
            return
        data = app.cf_fetch_blob(
            track_id, cell_target.custom_field_id
        )  # must return bytes or memoryview
        if not data:
            _root_attr("QMessageBox", QMessageBox).information(
                app, "Preview", "No data stored in this cell."
            )
            return
        if field_type == "blob_image":
            preview_title = f"{track_title} — {field_name}" if field_name else track_title
            app._open_image_preview(data[0] if isinstance(data, tuple) else data, preview_title)
            return
        app._preview_blob_bytes(data, title)
    except Exception as e:
        app.conn.rollback()
        app.logger.exception("Preview blob failed: %s", e)
        _root_attr("QMessageBox", QMessageBox).critical(
            app, "Custom Field Error", f"Failed to preview file:\n{e}"
        )

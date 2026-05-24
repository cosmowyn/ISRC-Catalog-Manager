"""Work workflow orchestration for the application shell."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

from isrc_manager.services.tracks import TRACK_RELATIONSHIP_TYPES
from isrc_manager.tasks.history_helpers import run_snapshot_history_action
from isrc_manager.works import WorkPayload
from isrc_manager.works.dialogs import WorkBrowserPanel, WorkEditorDialog


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback)
        if main_window_module is not None
        else fallback
    )


def _create_work_manager_panel(app, parent: QWidget) -> WorkBrowserPanel:
    panel = _root_attr("WorkBrowserPanel", WorkBrowserPanel)(
        work_service_provider=lambda: app.work_service,
        track_title_resolver=app._get_track_title,
        selected_track_ids_provider=lambda: list(
            app._catalog_table_controller().selected_track_ids()
        ),
        track_choice_provider=app._catalog_track_choices,
        parent=parent,
    )
    panel.filter_requested.connect(
        lambda track_ids: app._replace_catalog_track_filter(track_ids, source_label="work")
    )
    panel.create_requested.connect(app.create_work)
    panel.create_child_track_requested.connect(app._begin_work_child_track_creation)
    panel.create_album_for_work_requested.connect(app.open_add_album_dialog_for_work)
    panel.update_requested.connect(app.update_work)
    panel.duplicate_requested.connect(app.duplicate_work)
    panel.link_tracks_requested.connect(app.link_tracks_to_work)
    panel.delete_requested.connect(app.delete_work)
    return panel


def _work_payload_from_track_seed(
    app,
    *,
    track_title: str,
    iswc: str | None,
    registration_number: str | None,
) -> WorkPayload:
    return WorkPayload(
        title=str(track_title or "").strip(),
        iswc=str(iswc or "").strip() or None,
        registration_number=str(registration_number or "").strip() or None,
        profile_name=app._current_profile_name(),
    )


def _work_track_relationship_choices() -> list[str]:
    ordered = [
        "original",
        "version",
        "alternate_master",
        "remix",
        "edit",
        "live",
        "instrumental",
        "derivative",
        "other",
    ]
    return [value for value in ordered if value in TRACK_RELATIONSHIP_TYPES]


def _work_track_relationship_label(value: str) -> str:
    return str(value or "original").strip().replace("_", " ").title()


def _normalize_work_track_relationship(app, value: str | None) -> str:
    clean = str(value or "").strip().lower().replace(" ", "_")
    return clean if clean in TRACK_RELATIONSHIP_TYPES else "original"


def _work_track_governance_modes() -> tuple[tuple[str, str], ...]:
    return (
        ("create_new_work", "Create New Work from This Track"),
        ("link_existing_work", "Link to Existing Work"),
    )


def _default_work_track_context(app) -> dict[str, object]:
    return {
        "mode": "create_new_work",
        "work_id": None,
        "relationship_type": "original",
        "parent_track_id": None,
        "locked_work": False,
        "return_to_work_manager": False,
    }


def _set_pending_work_track_context(app, **overrides: object) -> dict[str, object]:
    context = app._default_work_track_context()
    context.update(overrides)
    app._pending_work_track_context = context
    return app._current_work_track_context()


def _current_work_track_context(app) -> dict[str, object]:
    context = getattr(app, "_pending_work_track_context", None)
    if not isinstance(context, dict):
        context = app._default_work_track_context()
    mode = str(context.get("mode") or "create_new_work").strip().lower()
    if mode not in {"create_new_work", "link_existing_work"}:
        mode = "create_new_work"
    try:
        work_id = int(context.get("work_id"))
    except (TypeError, ValueError):
        work_id = None
    parent_track_id = context.get("parent_track_id")
    try:
        normalized_parent_track_id = (
            int(parent_track_id) if parent_track_id not in (None, "") else None
        )
    except (TypeError, ValueError):
        normalized_parent_track_id = None
    locked_work = bool(context.get("locked_work"))
    return_to_work_manager = bool(context.get("return_to_work_manager"))
    if locked_work and work_id is not None:
        mode = "link_existing_work"
    normalized = {
        "mode": mode,
        "work_id": work_id if mode == "link_existing_work" else None,
        "relationship_type": (
            app._normalize_work_track_relationship(
                str(context.get("relationship_type") or "original")
            )
            if mode == "link_existing_work"
            else "original"
        ),
        "parent_track_id": normalized_parent_track_id if mode == "link_existing_work" else None,
        "locked_work": locked_work,
        "return_to_work_manager": return_to_work_manager,
    }
    app._pending_work_track_context = normalized
    return normalized


def _available_work_records(app) -> list:
    if app.work_service is None:
        return []
    try:
        return list(app.work_service.list_works())
    except Exception:
        return []


def _work_choice_label(record) -> str:
    title = str(getattr(record, "title", "") or "").strip()
    work_id = int(getattr(record, "id", 0) or 0)
    iswc = str(getattr(record, "iswc", "") or "").strip()
    base = title or (f"Work #{work_id}" if work_id > 0 else "Untitled Work")
    return f"{base} ({iswc})" if iswc else base


def _focus_work_in_manager(app, work_id: int | None) -> None:
    if not work_id:
        return
    panel = getattr(app, "work_browser_dialog", None)
    if panel is None:
        return
    focus_work = getattr(panel, "focus_work", None)
    if callable(focus_work):
        focus_work(int(work_id))


def _refresh_work_track_creation_context_ui(app) -> None:
    context_group = getattr(app, "add_data_work_context_group", None)
    mode_combo = getattr(app, "add_data_work_mode_combo", None)
    work_combo = getattr(app, "add_data_work_work_combo", None)
    relationship_combo = getattr(app, "add_data_work_relationship_combo", None)
    parent_combo = getattr(app, "add_data_work_parent_combo", None)
    if (
        context_group is None
        or mode_combo is None
        or work_combo is None
        or relationship_combo is None
        or parent_combo is None
    ):
        return

    context = app._current_work_track_context()
    detail = None
    if context.get("work_id") is not None and app.work_service is not None:
        detail = app.work_service.fetch_work_detail(int(context["work_id"]))

    app._reset_add_track_heading()
    context_group.setVisible(True)

    previous_mode_state = mode_combo.blockSignals(True)
    try:
        mode_combo.clear()
        for value, label in app._work_track_governance_modes():
            mode_combo.addItem(label, value)
        selected_mode_index = mode_combo.findData(str(context.get("mode") or "create_new_work"))
        mode_combo.setCurrentIndex(selected_mode_index if selected_mode_index >= 0 else 0)
    finally:
        mode_combo.blockSignals(previous_mode_state)

    previous_work_state = work_combo.blockSignals(True)
    try:
        work_combo.clear()
        work_combo.addItem("Choose the governing Work…", None)
        for record in app._available_work_records():
            try:
                work_id = int(getattr(record, "id", 0) or 0)
            except (TypeError, ValueError):
                continue
            if work_id <= 0:
                continue
            work_combo.addItem(app._work_choice_label(record), work_id)
        selected_work_id = context.get("work_id")
        if selected_work_id is not None and work_combo.findData(int(selected_work_id)) < 0:
            work_combo.addItem(f"Missing Work #{int(selected_work_id)}", int(selected_work_id))
        selected_work_index = (
            work_combo.findData(int(selected_work_id)) if selected_work_id is not None else 0
        )
        work_combo.setCurrentIndex(selected_work_index if selected_work_index >= 0 else 0)
        work_combo.setEnabled(
            str(context.get("mode")) == "link_existing_work"
            and not bool(context.get("locked_work"))
        )
    finally:
        work_combo.blockSignals(previous_work_state)

    relationship_type = app._normalize_work_track_relationship(
        str(context.get("relationship_type") or "original")
    )
    track_choices: list[tuple[int, str]] = []
    if detail is not None:
        for track_id in detail.track_ids:
            title = str(app._get_track_title(int(track_id)) or "").strip()
            track_choices.append((int(track_id), title or f"Track #{int(track_id)}"))
    valid_parent_track_ids = {track_id for track_id, _title in track_choices}
    parent_track_id = context.get("parent_track_id")
    if parent_track_id not in valid_parent_track_ids:
        parent_track_id = None
    app._pending_work_track_context = {
        "mode": str(context.get("mode") or "create_new_work"),
        "work_id": int(context["work_id"]) if context.get("work_id") is not None else None,
        "relationship_type": relationship_type,
        "parent_track_id": parent_track_id,
        "locked_work": bool(context.get("locked_work")),
        "return_to_work_manager": bool(context.get("return_to_work_manager")),
    }

    if str(context.get("mode")) == "create_new_work":
        app.add_data_work_context_summary.setText(
            "Saving this track will create a new parent Work from the track title, ISWC, and registration number, then link the track immediately as the first governed original."
        )
        app.add_data_work_context_hint.setText(
            "Main artist names resolve through Party records on save. Creating the Work from this panel avoids entering the same shared metadata twice."
        )
        app.save_button.setText("Create Work + Save Track")
    elif detail is None:
        app.add_data_work_context_summary.setText(
            "Choose the existing Work that should govern this track before saving."
        )
        app.add_data_work_context_hint.setText(
            "Use child relationship and optional parent track when this entry is a version, remix, alternate master, or other derivative under an existing Work."
        )
        app.save_button.setText("Save Governed Track")
    else:
        work_title = str(detail.work.title or "").strip() or f"Work #{int(detail.work.id)}"
        relationship_label = app._work_track_relationship_label(relationship_type)
        app.add_data_work_context_summary.setText(
            f"This track will link to Work #{int(detail.work.id)}: {work_title} as {relationship_label}."
        )
        if track_choices:
            app.add_data_work_context_hint.setText(
                f"{len(track_choices)} linked track{'s' if len(track_choices) != 1 else ''} already sit under this work. "
                "Choose a parent track when this new recording derives from one of them."
            )
        else:
            app.add_data_work_context_hint.setText(
                "This Work does not have any linked tracks yet. Saving now will create the first governed track under it."
            )
        app.save_button.setText("Save Governed Track")

    previous_relationship_state = relationship_combo.blockSignals(True)
    try:
        relationship_combo.clear()
        for value in app._work_track_relationship_choices():
            relationship_combo.addItem(app._work_track_relationship_label(value), value)
        selected_relationship_index = relationship_combo.findData(relationship_type)
        relationship_combo.setCurrentIndex(
            selected_relationship_index if selected_relationship_index >= 0 else 0
        )
        relationship_combo.setEnabled(
            str(context.get("mode")) == "link_existing_work"
            and detail is not None
            and relationship_combo.count() > 0
        )
    finally:
        relationship_combo.blockSignals(previous_relationship_state)

    previous_parent_state = parent_combo.blockSignals(True)
    try:
        parent_combo.clear()
        parent_combo.addItem("No direct parent track", None)
        for track_id, title in track_choices:
            parent_combo.addItem(title, int(track_id))
        selected_parent_index = (
            parent_combo.findData(int(parent_track_id)) if parent_track_id is not None else 0
        )
        parent_combo.setCurrentIndex(selected_parent_index if selected_parent_index >= 0 else 0)
        parent_combo.setEnabled(
            str(context.get("mode")) == "link_existing_work" and bool(track_choices)
        )
    finally:
        parent_combo.blockSignals(previous_parent_state)
    app.add_data_clear_work_context_button.setVisible(bool(context.get("return_to_work_manager")))


def _on_add_track_governance_mode_changed(app, _index: int) -> None:
    context = app._current_work_track_context()
    mode = str(app.add_data_work_mode_combo.currentData() or "create_new_work")
    context["mode"] = mode
    if mode == "create_new_work":
        context["work_id"] = None
        context["relationship_type"] = "original"
        context["parent_track_id"] = None
        context["locked_work"] = False
    app._pending_work_track_context = context
    app._refresh_work_track_creation_context_ui()


def _on_add_track_work_changed(app, _index: int) -> None:
    context = app._current_work_track_context()
    work_id = app.add_data_work_work_combo.currentData()
    try:
        context["work_id"] = int(work_id) if work_id not in (None, "") else None
    except (TypeError, ValueError):
        context["work_id"] = None
    context["parent_track_id"] = None
    app._pending_work_track_context = context
    app._refresh_work_track_creation_context_ui()


def _on_add_track_relationship_changed(app, _index: int) -> None:
    context = app._current_work_track_context()
    relationship_type = app._normalize_work_track_relationship(
        app.add_data_work_relationship_combo.currentData()
    )
    context["relationship_type"] = relationship_type
    app._pending_work_track_context = context
    app._refresh_work_track_creation_context_ui()


def _on_add_track_parent_track_changed(app, _index: int) -> None:
    context = app._current_work_track_context()
    parent_track_id = app.add_data_work_parent_combo.currentData()
    try:
        context["parent_track_id"] = (
            int(parent_track_id) if parent_track_id not in (None, "") else None
        )
    except (TypeError, ValueError):
        context["parent_track_id"] = None
    app._pending_work_track_context = context


def _clear_work_track_creation_context(app) -> None:
    app._pending_work_track_context = app._default_work_track_context()
    app._refresh_work_track_creation_context_ui()


def _return_from_work_track_creation_context(app) -> None:
    context = app._current_work_track_context()
    work_id = int(context["work_id"]) if context.get("work_id") is not None else None
    app._clear_work_track_creation_context()
    app.clear_form_fields()
    app._apply_add_data_panel_state(False)
    app.open_work_manager(work_id=work_id)


def _begin_work_child_track_creation(app, work_id: int, *, seed_from_work: bool = True) -> bool:
    if app.work_service is None:
        _root_attr("QMessageBox", QMessageBox).warning(app, "Work Manager", "Open a profile first.")
        return False
    detail = app.work_service.fetch_work_detail(int(work_id))
    if detail is None:
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Work Manager", "The selected work could not be loaded."
        )
        return False
    current_context = app._current_work_track_context()
    relationship_type = (
        str(current_context.get("relationship_type") or "original")
        if int(current_context.get("work_id") or 0) == int(work_id)
        else "original"
    )
    parent_track_id = (
        current_context.get("parent_track_id")
        if int(current_context.get("work_id") or 0) == int(work_id)
        else None
    )
    app._pending_work_track_context = {
        "mode": "link_existing_work",
        "work_id": int(work_id),
        "relationship_type": app._normalize_work_track_relationship(relationship_type),
        "parent_track_id": parent_track_id,
        "locked_work": False,
        "return_to_work_manager": True,
    }
    app._apply_add_data_panel_state(True)
    app.clear_form_fields()
    if seed_from_work:
        if str(detail.work.title or "").strip():
            app.track_title_field.setText(str(detail.work.title or "").strip())
            app.track_title_field.selectAll()
        if str(detail.work.iswc or "").strip():
            app.iswc_field.setText(str(detail.work.iswc or "").strip())
    app._refresh_work_track_creation_context_ui()
    app._focus_work_in_manager(int(work_id))
    app.track_title_field.setFocus()
    return True


def open_add_album_dialog_for_work(app, work_id: int) -> None:
    app.open_add_album_dialog(
        work_id=int(work_id),
        lock_work=True,
        relationship_type="original",
        inherit_work_context=False,
    )


def _configure_work_manager_panel(
    app,
    panel,
    *,
    linked_track_id: int | None = None,
    work_id: int | None = None,
    scope_track_ids: list[int] | None = None,
) -> None:
    if str(panel.search_edit.text() or "").strip():
        previous_state = panel.search_edit.blockSignals(True)
        try:
            panel.search_edit.clear()
        finally:
            panel.search_edit.blockSignals(previous_state)
    if getattr(panel, "linked_track_id", None) is not None or linked_track_id is not None:
        panel.set_linked_track_id(None)
    if scope_track_ids is not None:
        panel.set_selection_override_track_ids(scope_track_ids)
    else:
        panel.refresh()
    if linked_track_id is not None and app.work_service is not None:
        try:
            linked_rows = app.work_service.list_works(linked_track_id=int(linked_track_id))
        except Exception:
            linked_rows = []
        if len(linked_rows) == 1:
            panel.focus_work(int(linked_rows[0].id))
    if work_id is not None:
        panel.focus_work(int(work_id))


def open_work_manager(
    app,
    linked_track_id: int | None = None,
    *,
    work_id: int | None = None,
    scope_track_ids: list[int] | None = None,
):
    if app.work_service is None:
        _root_attr("QMessageBox", QMessageBox).warning(app, "Work Manager", "Open a profile first.")
        return
    return app._show_workspace_panel(
        app._ensure_work_manager_dock,
        panel_attr="work_manager_panel",
        legacy_attr="work_browser_dialog",
        configure=lambda panel: app._configure_work_manager_panel(
            panel,
            linked_track_id=linked_track_id,
            work_id=work_id,
            scope_track_ids=scope_track_ids,
        ),
        refresh_scope=True,
    )


def _refresh_work_manager_panel(app) -> None:
    seen_panel_ids: set[int] = set()
    for attr in ("work_manager_panel", "work_browser_dialog"):
        panel = getattr(app, attr, None)
        if panel is None or not panel.isVisible():
            continue
        panel_id = id(panel)
        if panel_id in seen_panel_ids:
            continue
        seen_panel_ids.add(panel_id)
        panel.refresh()
        refresh_scope = getattr(panel, "refresh_selection_scope", None)
        if callable(refresh_scope):
            refresh_scope()


def _work_manager_task_owner(app) -> QWidget:
    for attr in ("work_manager_panel", "work_browser_dialog"):
        owner = getattr(app, attr, None)
        if isinstance(owner, QWidget) and owner.isVisible():
            return owner
    return app


def create_work(app, payload: WorkPayload):
    if app.work_service is None:
        _root_attr("QMessageBox", QMessageBox).warning(app, "Work Manager", "Open a profile first.")
        return
    payload.profile_name = payload.profile_name or app._current_profile_name()
    needs_catalog_refresh = bool(payload.track_ids)
    refresh_request = app._capture_catalog_refresh_request(
        focus_id=(payload.track_ids[0] if payload.track_ids else None)
    )

    def _worker(bundle, ctx):
        ctx.report_progress(
            value=0,
            maximum=100,
            message="Saving work metadata, contributors, and linked tracks...",
        )
        work_id = _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
            history_manager=bundle.history_manager,
            action_label=f"Create Work: {payload.title or 'Untitled Work'}",
            action_type="work.create",
            entity_type="Work",
            entity_id=payload.title or "new",
            payload={
                "title": payload.title,
                "track_count": len(payload.track_ids),
            },
            mutation=lambda: bundle.work_service.create_work(payload),
            progress_callback=ctx.report_progress,
            post_mutation_progress=(48, "Capturing work-save history snapshot..."),
            record_progress=(56, "Recording work-save history..."),
            logger=app.logger,
        )
        result_payload = {
            "work_id": int(work_id),
            "title": payload.title,
            "track_ids": list(payload.track_ids),
        }
        if needs_catalog_refresh:
            ctx.report_progress(
                value=60,
                maximum=100,
                message="Loading refreshed catalog rows, media badges, and lookup values...",
            )
            result_payload["dataset"] = app._load_catalog_ui_dataset_from_bundle(
                bundle,
                ctx,
                progress_start=62,
                progress_end=88,
            )
        return result_payload

    def _before_cleanup(result: dict[str, object], ui_progress) -> None:
        work_id = int(result["work_id"])
        try:
            app.conn.commit()
        except Exception:
            pass
        if needs_catalog_refresh:
            app._apply_catalog_refresh_request(
                dict(result.get("dataset") or {}),
                refresh_request,
                progress_callback=app._scaled_ui_progress_callback(
                    ui_progress,
                    start=90,
                    end=97,
                ),
            )
        else:
            app._advance_task_ui_progress(
                ui_progress,
                value=96,
                message="Refreshing work manager and governance controls...",
            )
            app._refresh_history_actions()
            app._refresh_add_track_artist_party_choices()
            app._refresh_work_track_creation_context_ui()
        app._refresh_work_manager_panel()
        app._focus_work_in_manager(work_id)
        app._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="Work saved and UI is ready.",
        )

    def _after_cleanup(result: dict[str, object]) -> None:
        work_id = int(result["work_id"])
        track_ids = list(result.get("track_ids") or [])
        app._log_event(
            "work.create",
            "Work created",
            work_id=work_id,
            title=payload.title,
            track_ids=track_ids,
        )
        app._audit("CREATE", "Work", ref_id=work_id, details=f"title={payload.title}")
        app._audit_commit()
        if track_ids:
            return
        response = _root_attr("QMessageBox", QMessageBox).question(
            app,
            "Work Manager",
            "Work created. Do you want to open Add Track with this Work preselected now?",
            _root_attr("QMessageBox", QMessageBox).Yes | _root_attr("QMessageBox", QMessageBox).No,
            _root_attr("QMessageBox", QMessageBox).Yes,
        )
        if response == _root_attr("QMessageBox", QMessageBox).Yes:
            app._begin_work_child_track_creation(work_id)

    app._submit_background_bundle_task(
        title="Save Work",
        description="Saving work metadata, contributors, and linked tracks...",
        task_fn=_worker,
        kind="write",
        unique_key=f"work.create.{str(payload.title or 'untitled').strip().casefold()}",
        owner=app._work_manager_task_owner(),
        worker_completion_progress=(89, "Finalizing background work save..."),
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_after_cleanup,
        on_error=lambda failure: app._show_background_task_error(
            "Work Manager",
            failure,
            user_message="Could not create the work:",
        ),
    )


def _open_work_creation_dialog(app) -> WorkPayload | None:
    if app.work_service is None:
        _root_attr("QMessageBox", QMessageBox).warning(app, "Work Manager", "Open a profile first.")
        return None
    dialog = _root_attr("WorkEditorDialog", WorkEditorDialog)(
        work_service=app.work_service,
        track_title_resolver=app._get_track_title,
        selected_track_ids_provider=lambda: [],
        track_ids=[],
        parent=app,
    )
    if dialog.exec() != QDialog.Accepted:
        return None
    return dialog.payload()


def _launch_work_scoped_child_track_creation(
    app,
    work_id: int,
    *,
    relationship_type: str = "original",
    parent_track_id: int | None = None,
    seed_from_work: bool = True,
) -> bool:
    app._pending_work_track_context = {
        "work_id": int(work_id),
        "relationship_type": app._normalize_work_track_relationship(relationship_type),
        "parent_track_id": int(parent_track_id) if parent_track_id is not None else None,
    }
    return app._begin_work_child_track_creation(int(work_id), seed_from_work=seed_from_work)


def _current_work_manager_selected_work_id(app) -> int | None:
    for attr in ("work_manager_panel", "work_browser_dialog"):
        panel = getattr(app, attr, None)
        if panel is None:
            continue
        selected_work_id = getattr(panel, "selected_work_id", None)
        if callable(selected_work_id):
            try:
                value = selected_work_id()
            except Exception:
                value = None
            if value:
                return int(value)
    return None


def _adjacent_work_id_in_manager(app, work_id: int) -> int | None:
    for attr in ("work_manager_panel", "work_browser_dialog"):
        panel = getattr(app, attr, None)
        if panel is None or not getattr(panel, "isVisible", lambda: False)():
            continue
        table = getattr(panel, "table", None)
        if table is None:
            continue
        work_ids: list[int] = []
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            try:
                work_ids.append(int(item.text()))
            except Exception:
                continue
        if not work_ids:
            continue
        try:
            index = work_ids.index(int(work_id))
        except ValueError:
            index = -1
        if index >= 0:
            if index + 1 < len(work_ids):
                return int(work_ids[index + 1])
            if index > 0:
                return int(work_ids[index - 1])
    return None


def update_work(app, work_id: int, payload: WorkPayload):
    if app.work_service is None:
        _root_attr("QMessageBox", QMessageBox).warning(app, "Work Manager", "Open a profile first.")
        return
    payload.profile_name = payload.profile_name or app._current_profile_name()
    detail = app.work_service.fetch_work_detail(int(work_id))
    if detail is None:
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Work Manager", "The selected work could not be loaded."
        )
        return
    existing_track_ids = list(detail.track_ids)
    needs_catalog_refresh = set(existing_track_ids) != set(payload.track_ids)
    focus_track_id = (
        payload.track_ids[0]
        if payload.track_ids
        else (existing_track_ids[0] if existing_track_ids else None)
    )
    refresh_request = app._capture_catalog_refresh_request(focus_id=focus_track_id)

    def _worker(bundle, ctx):
        ctx.report_progress(
            value=0,
            maximum=100,
            message="Updating work metadata, contributors, and linked tracks...",
        )
        _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
            history_manager=bundle.history_manager,
            action_label=f"Update Work: {payload.title or detail.work.title}",
            action_type="work.update",
            entity_type="Work",
            entity_id=work_id,
            payload={
                "work_id": int(work_id),
                "title": payload.title,
                "track_count": len(payload.track_ids),
            },
            mutation=lambda: bundle.work_service.update_work(int(work_id), payload),
            progress_callback=ctx.report_progress,
            post_mutation_progress=(48, "Capturing work-update history snapshot..."),
            record_progress=(56, "Recording work-update history..."),
            logger=app.logger,
        )
        result_payload = {
            "work_id": int(work_id),
            "title": payload.title,
            "track_ids": list(payload.track_ids),
        }
        if needs_catalog_refresh:
            ctx.report_progress(
                value=60,
                maximum=100,
                message="Loading refreshed catalog rows, media badges, and lookup values...",
            )
            result_payload["dataset"] = app._load_catalog_ui_dataset_from_bundle(
                bundle,
                ctx,
                progress_start=62,
                progress_end=88,
            )
        return result_payload

    def _before_cleanup(result: dict[str, object], ui_progress) -> None:
        try:
            app.conn.commit()
        except Exception:
            pass
        if needs_catalog_refresh:
            app._apply_catalog_refresh_request(
                dict(result.get("dataset") or {}),
                refresh_request,
                progress_callback=app._scaled_ui_progress_callback(
                    ui_progress,
                    start=90,
                    end=97,
                ),
            )
        else:
            app._advance_task_ui_progress(
                ui_progress,
                value=96,
                message="Refreshing work manager and governance controls...",
            )
            app._refresh_history_actions()
            app._refresh_add_track_artist_party_choices()
            app._refresh_work_track_creation_context_ui()
        app._refresh_work_manager_panel()
        app._focus_work_in_manager(int(result["work_id"]))
        app._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="Work update complete and UI is ready.",
        )

    def _after_cleanup(result: dict[str, object]) -> None:
        app._log_event(
            "work.update",
            "Work updated",
            work_id=int(result["work_id"]),
            title=payload.title,
            track_ids=list(result.get("track_ids") or []),
        )
        app._audit("UPDATE", "Work", ref_id=work_id, details=f"title={payload.title}")
        app._audit_commit()

    app._submit_background_bundle_task(
        title="Update Work",
        description="Updating work metadata, contributors, and linked tracks...",
        task_fn=_worker,
        kind="write",
        unique_key=f"work.update.{int(work_id)}",
        owner=app._work_manager_task_owner(),
        worker_completion_progress=(89, "Finalizing background work update..."),
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_after_cleanup,
        on_error=lambda failure: app._show_background_task_error(
            "Work Manager",
            failure,
            user_message="Could not update the work:",
        ),
    )


def duplicate_work(app, work_id: int):
    if app.work_service is None:
        _root_attr("QMessageBox", QMessageBox).warning(app, "Work Manager", "Open a profile first.")
        return
    detail = app.work_service.fetch_work_detail(int(work_id))
    if detail is None:
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Work Manager", "The selected work could not be loaded."
        )
        return
    try:
        new_work_id = app._run_snapshot_history_action(
            action_label=f"Duplicate Work: {detail.work.title}",
            action_type="work.duplicate",
            entity_type="Work",
            entity_id=work_id,
            payload={"work_id": int(work_id), "title": detail.work.title},
            mutation=lambda: app.work_service.duplicate_work(int(work_id)),
        )
        app._log_event(
            "work.duplicate",
            "Work duplicated",
            source_work_id=int(work_id),
            new_work_id=new_work_id,
            title=detail.work.title,
        )
        app._audit("CREATE", "Work", ref_id=new_work_id, details=f"duplicated_from={work_id}")
        app._audit_commit()
    except Exception as exc:
        app.conn.rollback()
        app.logger.exception(f"Duplicate work failed: {exc}")
        _root_attr("QMessageBox", QMessageBox).critical(
            app, "Work Manager", f"Could not duplicate the work:\n{exc}"
        )
        return
    app._refresh_history_actions()
    app._refresh_work_manager_panel()


def link_tracks_to_work(app, work_id: int, track_ids: list[int]):
    if app.work_service is None:
        _root_attr("QMessageBox", QMessageBox).warning(app, "Work Manager", "Open a profile first.")
        return
    normalized_ids = app._normalize_track_ids(track_ids)
    if not normalized_ids:
        _root_attr("QMessageBox", QMessageBox).information(
            app, "Work Manager", "Select one or more tracks first."
        )
        return
    detail = app.work_service.fetch_work_detail(int(work_id))
    if detail is None:
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Work Manager", "The selected work could not be loaded."
        )
        return
    try:
        app._run_snapshot_history_action(
            action_label=f"Link Tracks to Work: {detail.work.title}",
            action_type="work.link_tracks",
            entity_type="Work",
            entity_id=work_id,
            payload={"work_id": int(work_id), "track_ids": normalized_ids},
            mutation=lambda: app.work_service.link_tracks_to_work(int(work_id), normalized_ids),
        )
        app._log_event(
            "work.link_tracks",
            "Linked tracks to work",
            work_id=int(work_id),
            track_ids=normalized_ids,
        )
        app._audit(
            "UPDATE",
            "Work",
            ref_id=work_id,
            details=f"track_ids={','.join(str(track_id) for track_id in normalized_ids)}",
        )
        app._audit_commit()
    except Exception as exc:
        app.conn.rollback()
        app.logger.exception(f"Link tracks to work failed: {exc}")
        _root_attr("QMessageBox", QMessageBox).critical(
            app, "Work Manager", f"Could not link the tracks:\n{exc}"
        )
        return
    app._refresh_history_actions()
    app._refresh_work_manager_panel()


def delete_work(app, work_id: int):
    if app.work_service is None:
        _root_attr("QMessageBox", QMessageBox).warning(app, "Work Manager", "Open a profile first.")
        return
    detail = app.work_service.fetch_work_detail(int(work_id))
    if detail is None:
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Work Manager", "The selected work could not be loaded."
        )
        return
    needs_catalog_refresh = bool(detail.track_ids)
    refresh_request = app._capture_catalog_refresh_request(
        focus_id=(detail.track_ids[0] if detail.track_ids else None)
    )
    next_work_id = app._adjacent_work_id_in_manager(int(work_id))

    def _worker(bundle, ctx):
        ctx.report_progress(
            value=0,
            maximum=100,
            message="Deleting the selected work and linked governance state...",
        )
        _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
            history_manager=bundle.history_manager,
            action_label=f"Delete Work: {detail.work.title}",
            action_type="work.delete",
            entity_type="Work",
            entity_id=work_id,
            payload={"work_id": int(work_id), "title": detail.work.title},
            mutation=lambda: bundle.work_service.delete_work(int(work_id)),
            progress_callback=ctx.report_progress,
            post_mutation_progress=(48, "Capturing work-delete history snapshot..."),
            record_progress=(56, "Recording work-delete history..."),
            logger=app.logger,
        )
        result_payload = {
            "work_id": int(work_id),
            "next_work_id": int(next_work_id) if next_work_id is not None else None,
        }
        if needs_catalog_refresh:
            ctx.report_progress(
                value=60,
                maximum=100,
                message="Loading refreshed catalog rows, media badges, and lookup values...",
            )
            result_payload["dataset"] = app._load_catalog_ui_dataset_from_bundle(
                bundle,
                ctx,
                progress_start=62,
                progress_end=88,
            )
        return result_payload

    def _before_cleanup(result: dict[str, object], ui_progress) -> None:
        try:
            app.conn.commit()
        except Exception:
            pass
        if needs_catalog_refresh:
            app._apply_catalog_refresh_request(
                dict(result.get("dataset") or {}),
                refresh_request,
                progress_callback=app._scaled_ui_progress_callback(
                    ui_progress,
                    start=90,
                    end=97,
                ),
            )
        else:
            app._advance_task_ui_progress(
                ui_progress,
                value=96,
                message="Refreshing work manager and governance controls...",
            )
            app._refresh_history_actions()
            app._refresh_add_track_artist_party_choices()
            app._refresh_work_track_creation_context_ui()
        app._refresh_work_manager_panel()
        if result.get("next_work_id") is not None:
            app._focus_work_in_manager(int(result["next_work_id"]))
        app._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="Work deleted and UI is ready.",
        )

    def _after_cleanup(_result: dict[str, object]) -> None:
        app._log_event(
            "work.delete",
            "Work deleted",
            work_id=int(work_id),
            title=detail.work.title,
        )
        app._audit("DELETE", "Work", ref_id=work_id, details=f"title={detail.work.title}")
        app._audit_commit()

    app._submit_background_bundle_task(
        title="Delete Work",
        description="Deleting the selected work and refreshing dependent views...",
        task_fn=_worker,
        kind="write",
        unique_key=f"work.delete.{int(work_id)}",
        owner=app._work_manager_task_owner(),
        worker_completion_progress=(89, "Finalizing background work deletion..."),
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_after_cleanup,
        on_error=lambda failure: app._show_background_task_error(
            "Work Manager",
            failure,
            user_message="Could not delete the work:",
        ),
    )

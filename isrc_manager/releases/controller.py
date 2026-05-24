"""Release workflow orchestration for the application shell."""

from __future__ import annotations

import sqlite3
import sys
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox, QWidget

from isrc_manager.releases import (
    ReleasePayload,
    ReleaseRecord,
    ReleaseService,
    ReleaseTrackPlacement,
)
from isrc_manager.releases.dialogs import ReleaseBrowserPanel, ReleaseEditorDialog
from isrc_manager.tasks.history_helpers import run_snapshot_history_action

if TYPE_CHECKING:
    from isrc_manager.services import TrackService


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _create_release_browser_panel(app, parent: QWidget) -> ReleaseBrowserPanel:
    panel = _root_attr("ReleaseBrowserPanel", ReleaseBrowserPanel)(
        release_service_provider=lambda: app.release_service,
        track_title_resolver=app._get_track_title,
        selected_track_ids_provider=lambda: list(
            app._catalog_table_controller().selected_track_ids()
        ),
        track_choice_provider=app._catalog_track_choices,
        parent=parent,
    )
    panel.filter_requested.connect(
        lambda track_ids: app._replace_catalog_track_filter(track_ids, source_label="release")
    )
    panel.open_track_requested.connect(app.open_selected_editor)
    panel.edit_release_requested.connect(app.open_release_editor)
    panel.duplicate_release_requested.connect(app.duplicate_release)
    panel.delete_release_requested.connect(app.delete_release)
    panel.add_selected_tracks_requested.connect(
        lambda release_id, track_ids: app.add_selected_tracks_to_specific_release(
            release_id, track_ids
        )
    )
    panel.create_release_requested.connect(app.create_release_from_selection)
    return panel


def open_release_browser(app):
    if app.release_service is None:
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Release Browser", "Open a profile first."
        )
        return
    return app._show_workspace_panel(
        app._ensure_release_browser_dock,
        panel_attr="release_browser_panel",
        legacy_attr="release_browser_dialog",
        refresh_scope=True,
    )


def _release_choices(app) -> list[tuple[int, str]]:
    if app.release_service is None:
        return []
    choices: list[tuple[int, str]] = []
    for release in app.release_service.list_releases():
        label = release.title
        if release.primary_artist:
            label = f"{label} — {release.primary_artist}"
        choices.append((release.id, label))
    return choices


def _release_context_for_track(
    app,
    track_id: int,
    *,
    release_service: ReleaseService | None = None,
) -> tuple[ReleaseRecord | None, ReleaseTrackPlacement | None]:
    active_release_service = release_service or app.release_service
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


def _release_payload_for_track_ids(
    app,
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
    active_track_service = track_service or app.track_service
    if active_track_service is None:
        raise ValueError("Track service is not available.")
    normalized_ids = app._normalize_track_ids(track_ids)
    snapshots = [
        snapshot
        for track_id in normalized_ids
        if (snapshot := active_track_service.fetch_track_snapshot(track_id)) is not None
    ]
    if not snapshots:
        raise ValueError("No valid tracks were available to build release metadata.")

    title = app._first_non_blank(
        *[snapshot.album_title for snapshot in snapshots],
        existing_release.title if existing_release is not None else None,
        snapshots[0].track_title,
    )
    clean_title = str(title or "").strip()
    placements: list[ReleaseTrackPlacement] = []
    existing_placements = {
        placement.track_id: placement
        for placement in ((existing_summary.tracks if existing_summary is not None else []) or [])
    }
    ordered_snapshots = sorted(
        enumerate(snapshots, start=1),
        key=lambda item: (
            app._normalize_track_number_value(item[1].track_number) or int(item[0]),
            int(item[0]),
        ),
    )
    for sequence_number, (_original_position, snapshot) in enumerate(
        ordered_snapshots,
        start=1,
    ):
        existing = existing_placements.get(snapshot.track_id)
        placements.append(
            ReleaseTrackPlacement(
                track_id=snapshot.track_id,
                disc_number=int(existing.disc_number if existing is not None else 1),
                track_number=int(
                    existing.track_number
                    if existing is not None
                    else (
                        app._normalize_track_number_value(snapshot.track_number) or sequence_number
                    )
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
        primary_artist=app._first_non_blank(
            existing_release.primary_artist if existing_release is not None else None,
            *[snapshot.artist_name for snapshot in snapshots],
        ),
        album_artist=app._first_non_blank(
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
        release_date=app._first_non_blank(
            existing_release.release_date if existing_release is not None else None,
            *[snapshot.release_date for snapshot in snapshots],
        ),
        original_release_date=(
            existing_release.original_release_date if existing_release is not None else None
        ),
        label=app._first_non_blank(
            existing_release.label if existing_release is not None else None,
            *[snapshot.publisher for snapshot in snapshots],
        ),
        sublabel=existing_release.sublabel if existing_release is not None else None,
        catalog_number=app._first_non_blank(
            existing_release.catalog_number if existing_release is not None else None,
            *[snapshot.catalog_number for snapshot in snapshots],
        ),
        upc=app._first_non_blank(
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
        profile_name=profile_name or app._current_profile_name(),
        placements=placements,
    )


def _sync_releases_for_tracks(
    app,
    track_ids,
    *,
    cursor: sqlite3.Cursor | None = None,
    track_service: TrackService | None = None,
    release_service: ReleaseService | None = None,
    profile_name: str | None = None,
) -> list[int]:
    active_track_service = track_service or app.track_service
    active_release_service = release_service or app.release_service
    if active_track_service is None or active_release_service is None:
        return []
    if cursor is None:
        with app.conn:
            cur = app.conn.cursor()
            return app._sync_releases_for_tracks(
                track_ids,
                cursor=cur,
                track_service=active_track_service,
                release_service=active_release_service,
                profile_name=profile_name,
            )

    cur = cursor
    created_or_updated: list[int] = []
    processed_group_keys: set[tuple[int, ...]] = set()

    for track_id in app._normalize_track_ids(track_ids):
        group_track_ids = active_track_service.list_album_group_track_ids(track_id, cursor=cur)
        if not group_track_ids:
            group_track_ids = [track_id]
        group_key = tuple(app._normalize_track_ids(group_track_ids))
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

        payload = app._release_payload_for_track_ids(
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

    return app._normalize_track_ids(created_or_updated)


def open_release_editor(
    app,
    release_id: int | None = None,
    selected_track_ids: list[int] | None = None,
):
    if app.release_service is None:
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Release Editor", "Open a profile first."
        )
        return
    summary = app.release_service.fetch_release_summary(int(release_id)) if release_id else None
    normalized_selection = app._normalize_track_ids(selected_track_ids)
    dlg = _root_attr("ReleaseEditorDialog", ReleaseEditorDialog)(
        release_service=app.release_service,
        track_title_resolver=app._get_track_title,
        selected_track_ids_provider=(
            (lambda: list(normalized_selection))
            if normalized_selection
            else (lambda: list(app._catalog_table_controller().selected_track_ids()))
        ),
        release=summary.release if summary is not None else None,
        placements=list(summary.tracks) if summary is not None else None,
        profile_name=app._current_profile_name(),
        party_service=app.party_service,
        parent=app,
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
    focus_track_id = payload.placements[0].track_id if payload.placements else None
    operation_label = "create" if summary is None else "update"

    def _worker(bundle, ctx):
        ctx.report_progress(
            value=0,
            maximum=100,
            message=f"Preparing release {operation_label}...",
        )

        def _mutation():
            ctx.report_progress(
                value=12,
                maximum=100,
                message="Saving release metadata and track order...",
            )
            if summary is None:
                return bundle.release_service.create_release(payload)
            return bundle.release_service.update_release(int(summary.release.id), payload)

        return _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
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
            progress_callback=ctx.report_progress,
            post_mutation_progress=(48, "Capturing release-save history snapshot..."),
            record_progress=(56, "Recording release-save history..."),
            logger=app.logger,
        )

    def _before_cleanup(release_pk: int, ui_progress) -> None:
        try:
            app.conn.commit()
        except Exception:
            pass
        app._advance_task_ui_progress(
            ui_progress,
            value=72,
            message="Recording release save audit details...",
        )
        app._refresh_history_actions()
        app._log_event(
            action_type,
            action_label,
            release_id=release_pk,
            title=payload.title,
            track_count=len(payload.placements),
        )
        app._audit(
            "UPDATE" if summary is not None else "CREATE",
            "Release",
            ref_id=release_pk,
            details=f"title={payload.title}; tracks={len(payload.placements)}",
        )
        app._audit_commit()
        app._advance_task_ui_progress(
            ui_progress,
            value=82,
            message="Refreshing catalog rows affected by the release...",
        )
        app.refresh_table_preserve_view(focus_id=focus_track_id)
        app._advance_task_ui_progress(
            ui_progress,
            value=94,
            message="Refreshing Release Browser details...",
        )
        app._refresh_release_browser_panel()
        app._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="Release saved and UI is ready.",
        )

    def _after_cleanup(_release_pk: int) -> None:
        app._refresh_release_browser_panel()

    app._submit_background_bundle_task(
        title="Release Editor",
        description="Saving release metadata and track order...",
        task_fn=_worker,
        kind="write",
        unique_key=f"release.save.{existing_release_id or payload.title}",
        owner=app._release_browser_task_owner(),
        worker_completion_progress=(66, "Finalizing release save in the background..."),
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_after_cleanup,
        on_error=lambda failure: app._show_background_task_error(
            "Release Editor",
            failure,
            user_message="Could not save the release:",
        ),
    )


def create_release_from_selection(app, track_ids: list[int] | None = None):
    selected_ids = app._normalize_track_ids(
        track_ids or app._catalog_table_controller().selected_track_ids()
    )
    if not selected_ids:
        _root_attr("QMessageBox", QMessageBox).information(
            app,
            "Create Release",
            "Select one or more tracks first, then create the release from that selection.",
        )
        return
    app.open_release_editor(selected_track_ids=selected_ids)


def _prompt_for_release_choice(app, *, title: str, prompt: str) -> int | None:
    choices = app._release_choices()
    if not choices:
        _root_attr("QMessageBox", QMessageBox).information(
            app, title, "No releases exist yet. Create one first."
        )
        return None
    labels = [label for _, label in choices]
    selected_label, ok = _root_attr("QInputDialog", QInputDialog).getItem(
        app, title, prompt, labels, 0, False
    )
    if not ok or not selected_label:
        return None
    for release_id, label in choices:
        if label == selected_label:
            return int(release_id)
    return None


def add_selected_tracks_to_release(app, track_ids: list[int] | None = None):
    release_id = app._prompt_for_release_choice(
        title="Add Selected Tracks to Release",
        prompt="Choose the release that should receive the current selection:",
    )
    if release_id is None:
        return
    app.add_selected_tracks_to_specific_release(release_id, track_ids)


def add_selected_tracks_to_specific_release(
    app, release_id: int, track_ids: list[int] | None = None
):
    if app.release_service is None:
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Release Browser", "Open a profile first."
        )
        return
    selected_ids = app._normalize_track_ids(
        track_ids or app._catalog_table_controller().selected_track_ids()
    )
    if not selected_ids:
        _root_attr("QMessageBox", QMessageBox).information(
            app, "Release Browser", "Select one or more tracks first."
        )
        return
    summary = app.release_service.fetch_release_summary(int(release_id))
    if summary is None:
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Release Browser", "The chosen release could not be loaded."
        )
        return

    def _worker(bundle, ctx):
        ctx.report_progress(
            value=0,
            maximum=100,
            message="Preparing to add selected tracks to the release...",
        )

        def mutation():
            ctx.report_progress(
                value=12,
                maximum=100,
                message=(
                    f"Adding {len(selected_ids)} selected "
                    f"track{'s' if len(selected_ids) != 1 else ''} to the release..."
                ),
            )
            return bundle.release_service.add_tracks_to_release(int(release_id), selected_ids)

        return _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
            history_manager=bundle.history_manager,
            action_label=f"Add Tracks to Release: {summary.release.title}",
            action_type="release.add_tracks",
            entity_type="Release",
            entity_id=release_id,
            payload={"release_id": release_id, "track_ids": selected_ids},
            mutation=mutation,
            progress_callback=ctx.report_progress,
            post_mutation_progress=(48, "Capturing release track-link history snapshot..."),
            record_progress=(56, "Recording release track-link history..."),
            logger=app.logger,
        )

    def _before_cleanup(added_track_ids: list[int], ui_progress) -> None:
        try:
            app.conn.commit()
        except Exception:
            pass
        app._advance_task_ui_progress(
            ui_progress,
            value=72,
            message="Recording release track-link audit details...",
        )
        app._log_event(
            "release.add_tracks",
            "Added selected tracks to release",
            release_id=release_id,
            title=summary.release.title,
            track_ids=added_track_ids,
        )
        app._audit(
            "UPDATE",
            "Release",
            ref_id=release_id,
            details=f"add_tracks={','.join(str(track_id) for track_id in (added_track_ids or []))}",
        )
        app._audit_commit()
        app._advance_task_ui_progress(
            ui_progress,
            value=82,
            message="Refreshing catalog rows affected by the release track links...",
        )
        focus_track_id = (added_track_ids or selected_ids or [None])[0]
        app.refresh_table_preserve_view(focus_id=focus_track_id)
        app._advance_task_ui_progress(
            ui_progress,
            value=94,
            message="Refreshing Release Browser details...",
        )
        app._refresh_release_browser_panel()
        app._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="Selected tracks added and UI is ready.",
        )

    def _after_cleanup(added_track_ids: list[int]) -> None:
        app._refresh_release_browser_panel()
        _root_attr("QMessageBox", QMessageBox).information(
            app,
            "Release Browser",
            f"Added {len(added_track_ids or [])} track{'s' if len(added_track_ids or []) != 1 else ''} to '{summary.release.title}'.",
        )

    app._submit_background_bundle_task(
        title="Add Tracks to Release",
        description="Adding selected tracks to the release...",
        task_fn=_worker,
        kind="write",
        unique_key=f"release.add_tracks.{int(release_id)}",
        owner=app._release_browser_task_owner(),
        worker_completion_progress=(66, "Finalizing release track-link update..."),
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_after_cleanup,
        on_error=lambda failure: app._show_background_task_error(
            "Release Browser",
            failure,
            user_message="Could not add the selected tracks:",
        ),
    )


def _refresh_release_browser_panel(app) -> None:
    seen_panel_ids: set[int] = set()
    candidates = [
        getattr(app, "release_browser_panel", None),
        getattr(app, "release_browser_dialog", None),
    ]
    dock = getattr(app, "release_browser_dock", None)
    if dock is not None:
        try:
            candidates.append(dock.widget())
        except Exception:
            pass
    for panel in candidates:
        if panel is None:
            continue
        panel_id = id(panel)
        if panel_id in seen_panel_ids:
            continue
        seen_panel_ids.add(panel_id)
        refresh = getattr(panel, "refresh", None)
        if callable(refresh):
            refresh()
        refresh_scope = getattr(panel, "refresh_selection_scope", None)
        if callable(refresh_scope):
            refresh_scope()


def _release_browser_task_owner(app) -> QWidget:
    for attr in ("release_browser_panel", "release_browser_dialog"):
        owner = getattr(app, attr, None)
        if isinstance(owner, QWidget) and owner.isVisible():
            return owner
    return app


def delete_release(app, release_id: int):
    if app.release_service is None:
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Release Browser", "Open a profile first."
        )
        return
    summary = app.release_service.fetch_release_summary(int(release_id))
    if summary is None:
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Delete Release", "The selected release could not be loaded."
        )
        return
    focus_track_id = summary.tracks[0].track_id if summary.tracks else None

    def _worker(bundle, ctx):
        ctx.report_progress(
            value=0,
            maximum=100,
            message="Preparing to delete the release...",
        )

        def _mutation():
            ctx.report_progress(
                value=12,
                maximum=100,
                message="Deleting release metadata, track order, and release-level links...",
            )
            return bundle.release_service.delete_release(int(release_id))

        return _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
            history_manager=bundle.history_manager,
            action_label=f"Delete Release: {summary.release.title}",
            action_type="release.delete",
            entity_type="Release",
            entity_id=release_id,
            payload={"release_id": int(release_id), "title": summary.release.title},
            mutation=_mutation,
            progress_callback=ctx.report_progress,
            post_mutation_progress=(48, "Capturing release-delete history snapshot..."),
            record_progress=(56, "Recording release-delete history..."),
            logger=app.logger,
        )

    def _before_cleanup(_result: object, ui_progress) -> None:
        try:
            app.conn.commit()
        except Exception:
            pass
        app._advance_task_ui_progress(
            ui_progress,
            value=72,
            message="Recording release deletion audit details...",
        )
        app._log_event(
            "release.delete",
            "Release deleted",
            release_id=int(release_id),
            title=summary.release.title,
        )
        app._audit(
            "DELETE",
            "Release",
            ref_id=release_id,
            details=f"title={summary.release.title}",
        )
        app._audit_commit()
        app._refresh_history_actions()
        app._advance_task_ui_progress(
            ui_progress,
            value=82,
            message="Refreshing catalog rows affected by the deleted release...",
        )
        app.refresh_table_preserve_view(focus_id=focus_track_id)
        app._advance_task_ui_progress(
            ui_progress,
            value=94,
            message="Refreshing Release Browser details...",
        )
        app._refresh_release_browser_panel()
        app._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="Release deleted and UI is ready.",
        )

    def _after_cleanup(_result: object) -> None:
        app._refresh_release_browser_panel()

    app._submit_background_bundle_task(
        title="Delete Release",
        description="Deleting the selected release and refreshing dependent views...",
        task_fn=_worker,
        kind="write",
        unique_key=f"release.delete.{int(release_id)}",
        owner=app._release_browser_task_owner(),
        worker_completion_progress=(66, "Finalizing release deletion in the background..."),
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_after_cleanup,
        on_error=lambda failure: app._show_background_task_error(
            "Delete Release",
            failure,
            user_message="Could not delete the release:",
        ),
    )


def duplicate_release(app, release_id: int):
    if app.release_service is None:
        return
    summary = app.release_service.fetch_release_summary(int(release_id))
    if summary is None:
        _root_attr("QMessageBox", QMessageBox).warning(
            app, "Duplicate Release", "The selected release could not be loaded."
        )
        return
    focus_track_id = summary.tracks[0].track_id if summary.tracks else None

    def _worker(bundle, ctx):
        ctx.report_progress(
            value=0,
            maximum=100,
            message="Preparing to duplicate the release...",
        )

        def _mutation():
            ctx.report_progress(
                value=12,
                maximum=100,
                message="Duplicating release metadata and track order...",
            )
            return bundle.release_service.duplicate_release(int(release_id))

        return _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
            history_manager=bundle.history_manager,
            action_label=f"Duplicate Release: {summary.release.title}",
            action_type="release.duplicate",
            entity_type="Release",
            entity_id=release_id,
            payload={"release_id": release_id, "title": summary.release.title},
            mutation=_mutation,
            progress_callback=ctx.report_progress,
            post_mutation_progress=(48, "Capturing release-duplicate history snapshot..."),
            record_progress=(56, "Recording release-duplicate history..."),
            logger=app.logger,
        )

    def _before_cleanup(new_release_id: int, ui_progress) -> None:
        try:
            app.conn.commit()
        except Exception:
            pass
        app._advance_task_ui_progress(
            ui_progress,
            value=72,
            message="Recording release duplication audit details...",
        )
        app._log_event(
            "release.duplicate",
            "Release duplicated",
            source_release_id=release_id,
            new_release_id=new_release_id,
            title=summary.release.title,
        )
        app._audit(
            "CREATE",
            "Release",
            ref_id=new_release_id,
            details=f"duplicated_from={release_id}",
        )
        app._audit_commit()
        app._refresh_history_actions()
        app._advance_task_ui_progress(
            ui_progress,
            value=82,
            message="Refreshing catalog rows affected by the duplicate release...",
        )
        app.refresh_table_preserve_view(focus_id=focus_track_id)
        app._advance_task_ui_progress(
            ui_progress,
            value=94,
            message="Refreshing Release Browser details...",
        )
        app._refresh_release_browser_panel()
        app._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="Release duplicated and UI is ready.",
        )

    def _after_cleanup(_new_release_id: int) -> None:
        app._refresh_release_browser_panel()

    app._submit_background_bundle_task(
        title="Duplicate Release",
        description="Duplicating release metadata and track order...",
        task_fn=_worker,
        kind="write",
        unique_key=f"release.duplicate.{int(release_id)}",
        owner=app._release_browser_task_owner(),
        worker_completion_progress=(
            66,
            "Finalizing release duplication in the background...",
        ),
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_after_cleanup,
        on_error=lambda failure: app._show_background_task_error(
            "Duplicate Release",
            failure,
            user_message="Could not duplicate the release:",
        ),
    )

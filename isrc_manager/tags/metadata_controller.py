"""Tag and metadata workflow orchestration for the application shell."""

from __future__ import annotations

import mimetypes
import sqlite3
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDialog, QMessageBox

from isrc_manager.domain.codes import is_valid_isrc_compact_or_iso, to_compact_isrc, to_iso_isrc
from isrc_manager.file_storage import STORAGE_MODE_MANAGED_FILE
from isrc_manager.releases import ReleaseService
from isrc_manager.services.import_governance import GovernedImportCoordinator
from isrc_manager.services.tracks import (
    TrackCreatePayload,
    TrackService,
    TrackSnapshot,
    TrackUpdatePayload,
)
from isrc_manager.tags import (
    ArtworkPayload,
    AudioTagService,
    BulkAudioAttachService,
    DroppedAudioImportItem,
    build_catalog_export_tag_data,
    merge_imported_tags,
    write_catalog_export_tags,
)
from isrc_manager.tags.dialogs import DroppedAudioImportDialog, TagPreviewDialog
from isrc_manager.tasks.history_helpers import run_snapshot_history_action


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback)
        if main_window_module is not None
        else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _display_tag_value(value) -> str:
    if isinstance(value, ArtworkPayload):
        return f"<Artwork {value.mime_type or 'image'}>"
    if value is None:
        return ""
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return str(value)


def _catalog_tag_data_for_track(
    app,
    track_id: int,
    *,
    snapshot: TrackSnapshot | None = None,
    track_service: TrackService | None = None,
    release_service: ReleaseService | None = None,
    include_artwork_bytes: bool = True,
):
    active_track_service = track_service or app.track_service
    if active_track_service is None:
        raise ValueError("Track service is not available")
    return build_catalog_export_tag_data(
        track_id,
        track_service=active_track_service,
        release_service=release_service or app.release_service,
        include_artwork_bytes=include_artwork_bytes,
    )


def _attempt_catalog_audio_export_metadata(
    app,
    destination_path: str | Path,
    *,
    track_id: int,
) -> str | None:
    if app.track_service is None or app.audio_tag_service is None:
        return "catalog metadata services were unavailable"
    _metadata_embedded, metadata_warning = write_catalog_export_tags(
        destination_path,
        track_id=track_id,
        track_service=app.track_service,
        release_service=app.release_service,
        tag_service=app.audio_tag_service,
        include_artwork_bytes=True,
    )
    return metadata_warning


def _build_tag_preview_rows(
    app,
    *,
    track_id: int,
    track_title: str | None = None,
    source_path: str,
    database_values: dict[str, object],
    file_tags,
    chosen_values: dict[str, object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    display_track_title = str(track_title or app._get_track_title(track_id) or "")
    for field_name, chosen_value in chosen_values.items():
        database_value = database_values.get(field_name)
        file_value = getattr(file_tags, field_name, None)
        if database_value == file_value and not isinstance(chosen_value, ArtworkPayload):
            continue
        rows.append(
            {
                "track": display_track_title,
                "field": field_name.replace("_", " ").title(),
                "database": app._display_tag_value(database_value),
                "file": app._display_tag_value(file_value),
                "chosen": app._display_tag_value(chosen_value),
                "source": source_path,
            }
        )
    return rows


def _prepare_tag_import_preview(
    app,
    track_ids: list[int],
    *,
    policy: str,
    track_service: TrackService | None = None,
    release_service: ReleaseService | None = None,
    audio_tag_service: AudioTagService | None = None,
    progress_callback=None,
) -> dict[str, object]:
    active_track_service = track_service or app.track_service
    active_release_service = release_service or app.release_service
    active_audio_tag_service = audio_tag_service or app.audio_tag_service
    if active_track_service is None or active_audio_tag_service is None:
        raise ValueError("Audio tag services are not available.")

    normalized_ids = app._normalize_track_ids(track_ids)
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
        database_values = app._catalog_tag_data_for_track(
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
            app._build_tag_preview_rows(
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


def _apply_tag_patch_to_track(
    app,
    track_id: int,
    values: dict[str, object],
    *,
    cursor: sqlite3.Cursor | None = None,
    track_service: TrackService | None = None,
) -> None:
    active_track_service = track_service or app.track_service
    if active_track_service is None:
        raise ValueError("Track service is not available.")
    snapshot = active_track_service.fetch_track_snapshot(track_id, cursor=cursor)
    if snapshot is None:
        raise ValueError(f"Track {track_id} not found")
    artwork = values.get("artwork")
    temp_artwork_path = None
    current_artwork = app._effective_artwork_payload_for_track(
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
        next_track_number = snapshot.track_number
        incoming_track_number = values.get("track_number")
        if incoming_track_number not in (None, ""):
            next_track_number = app._normalize_track_number_value(incoming_track_number)
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
            track_number=next_track_number,
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


def _dropped_audio_import_dialog_row(
    item: DroppedAudioImportItem,
    *,
    warning: str | None = None,
) -> dict[str, object]:
    return {
        "source_path": item.source_path,
        "source_name": item.source_name,
        "title": item.title,
        "artist": item.artist,
        "album": item.album,
        "track_number": item.track_number,
        "release_date": item.release_date,
        "duration_seconds": item.duration_seconds,
        "isrc": item.isrc,
        "upc": item.upc,
        "genre": item.genre,
        "composer": item.composer,
        "publisher": item.publisher,
        "comments": item.comments,
        "lyrics": item.lyrics,
        "artwork": item.artwork,
        "warning": warning if warning is not None else item.warning,
    }


def _materialize_artwork_payload(artwork: ArtworkPayload) -> str:
    suffix = mimetypes.guess_extension(artwork.mime_type or "image/jpeg") or ".img"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(bytes(artwork.data or b""))
        return str(handle.name)
    finally:
        handle.close()


def _build_dropped_audio_import_payloads(
    app,
    rows: list[dict[str, object]],
    *,
    storage_mode: str,
) -> tuple[list[TrackCreatePayload], list[str], list[str]]:
    errors: list[str] = []
    seen_isrc: dict[str, int] = {}
    normalized_rows: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        row_errors: list[str] = []
        title = str(row.get("title") or "").strip()
        artist = str(row.get("artist") or "").strip()
        source_path = str(row.get("source_path") or "").strip()
        if not title:
            row_errors.append(f"Row {index}: track title is required.")
        if not artist:
            row_errors.append(f"Row {index}: artist is required.")
        if not source_path:
            row_errors.append(f"Row {index}: source audio path is missing.")

        iso_isrc = ""
        raw_isrc = str(row.get("isrc") or "").strip()
        if raw_isrc:
            iso_candidate = to_iso_isrc(raw_isrc)
            compact_candidate = to_compact_isrc(iso_candidate or raw_isrc)
            if (
                not iso_candidate
                or not compact_candidate
                or not is_valid_isrc_compact_or_iso(iso_candidate)
            ):
                row_errors.append(f"Row {index}: ISRC '{raw_isrc}' is not valid.")
            elif compact_candidate in seen_isrc:
                row_errors.append(
                    f"Row {index}: ISRC {iso_candidate} is already queued on row "
                    f"{seen_isrc[compact_candidate]}."
                )
            elif app.is_isrc_taken_normalized(iso_candidate):
                row_errors.append(f"Row {index}: ISRC {iso_candidate} already exists.")
            else:
                seen_isrc[compact_candidate] = index
                iso_isrc = iso_candidate

        if row_errors:
            errors.extend(row_errors)
            continue

        normalized_row = dict(row)
        normalized_row.update(
            {
                "title": title,
                "artist": artist,
                "source_path": source_path,
                "iso_isrc": iso_isrc,
            }
        )
        normalized_rows.append(normalized_row)

    if errors:
        return [], errors, []

    payloads: list[TrackCreatePayload] = []
    temp_artwork_paths: list[str] = []
    for row in normalized_rows:
        album_art_source_path = None
        artwork = row.get("artwork")
        if (
            bool(row.get("import_artwork"))
            and isinstance(artwork, ArtworkPayload)
            and artwork.data
        ):
            album_art_source_path = app._materialize_artwork_payload(artwork)
            temp_artwork_paths.append(album_art_source_path)
        payloads.append(
            TrackCreatePayload(
                isrc=str(row.get("iso_isrc") or ""),
                track_title=str(row.get("title") or ""),
                artist_name=str(row.get("artist") or ""),
                additional_artists=[],
                album_title=str(row.get("album") or "").strip() or None,
                release_date=str(row.get("release_date") or "").strip() or None,
                track_length_sec=int(row.get("duration_seconds") or 0),
                iswc=None,
                upc=str(row.get("upc") or "").strip() or None,
                genre=str(row.get("genre") or "").strip() or None,
                track_number=app._normalize_track_number_value(row.get("track_number")),
                buma_work_number=None,
                composer=str(row.get("composer") or "").strip() or None,
                publisher=str(row.get("publisher") or "").strip() or None,
                comments=str(row.get("comments") or "").strip() or None,
                lyrics=str(row.get("lyrics") or "").strip() or None,
                relationship_type="original",
                audio_file_source_path=str(row.get("source_path") or ""),
                audio_file_storage_mode=storage_mode,
                album_art_source_path=album_art_source_path,
                album_art_storage_mode=storage_mode if album_art_source_path else None,
            )
        )
    return payloads, errors, temp_artwork_paths


def _create_tracks_from_dropped_audio_files(
    app,
    file_paths: list[str],
    *,
    title: str = "Create Tracks from Audio Files",
) -> None:
    if (
        app.audio_tag_service is None
        or app.track_service is None
        or app.work_service is None
    ):
        _message_box().warning(app, title, "Open a profile first.")
        return
    prepared_paths = [
        str(path)
        for path in file_paths
        if str(path or "").strip()
        and Path(str(path)).exists()
        and app._is_supported_media_attach_path(str(path), "audio_file")
    ]
    if not prepared_paths:
        _message_box().information(app, title, "No supported audio files were selected.")
        return

    def _preview_worker(bundle, ctx):
        matcher = BulkAudioAttachService(bundle.audio_tag_service)
        plan = matcher.build_import_plan(
            file_paths=prepared_paths,
            progress_callback=lambda value, maximum, message: ctx.report_progress(
                value=value,
                maximum=maximum,
                message=message,
            ),
        )
        return {"plan": plan}

    def _preview_success(result: dict[str, object]) -> None:
        plan = result.get("plan")
        plan_items = list(getattr(plan, "items", []) or [])
        plan_warnings = list(getattr(plan, "warnings", []) or [])
        if not plan_items:
            _message_box().information(
                app,
                title,
                "The selected audio files could not be prepared for import.",
            )
            return

        dialog_rows: list[dict[str, object]] = []
        for item in plan_items:
            warning_parts: list[str] = []
            item_warning = str(getattr(item, "warning", "") or "").strip()
            if item_warning:
                warning_parts.append(item_warning)
            lossy_warning = app._lossy_primary_audio_warning_text(
                path_value=getattr(item, "source_path", ""),
                filename=getattr(item, "source_name", ""),
                short=True,
            )
            if lossy_warning and lossy_warning not in warning_parts:
                warning_parts.append(lossy_warning)
            dialog_rows.append(
                app._dropped_audio_import_dialog_row(
                    item,
                    warning="\n".join(warning_parts),
                )
            )

        dlg = _root_attr("DroppedAudioImportDialog", DroppedAudioImportDialog)(
            title=title,
            intro=(
                "Review the metadata read from the dropped audio files. "
                "Edit the prefilled fields before creating linked Works and Tracks."
            ),
            items=dialog_rows,
            party_service=app.party_service,
            default_storage_mode=STORAGE_MODE_MANAGED_FILE,
            create_button_text="Create Works + Tracks",
            parent=app,
        )
        if dlg.exec() != QDialog.Accepted:
            return

        selected_rows = dlg.selected_imports()
        selected_paths = [str(row.get("source_path") or "") for row in selected_rows]
        if not app._confirm_lossy_primary_audio_selection(
            selected_paths,
            title=title,
            action_label="Creating these tracks",
        ):
            return

        storage_mode = dlg.selected_storage_mode()
        (
            payloads,
            validation_errors,
            temp_artwork_paths,
        ) = app._build_dropped_audio_import_payloads(
            selected_rows,
            storage_mode=storage_mode,
        )
        if validation_errors:
            _message_box().warning(
                app,
                title,
                "Some dropped audio files still need attention before import.\n\n"
                + "\n".join(validation_errors[:16]),
            )
            return
        if not payloads:
            _message_box().information(app, title, "No audio files were queued for import.")
            return

        profile_name = app._current_profile_name()
        artwork_payload_count = sum(1 for payload in payloads if payload.album_art_source_path)

        def _apply_worker(bundle, ctx):
            governed_service = GovernedImportCoordinator(
                bundle.conn,
                track_service=bundle.track_service,
                party_service=bundle.party_service,
                work_service=bundle.work_service,
                profile_name=profile_name,
            )

            def _mutation():
                created_track_ids: list[int] = []
                created_work_ids: list[int] = []
                total = max(1, len(payloads))
                with bundle.conn:
                    cur = bundle.conn.cursor()
                    batch_cache: dict[str, int] = {}
                    for index, payload in enumerate(payloads, start=1):
                        result = governed_service.create_governed_track(
                            payload,
                            cursor=cur,
                            batch_cache=batch_cache,
                            governance_mode="create_new_work",
                            profile_name=profile_name,
                        )
                        created_track_ids.append(int(result.track_id))
                        if result.created_work_id is not None:
                            created_work_ids.append(int(result.created_work_id))
                        ctx.report_progress(
                            value=index,
                            maximum=total,
                            message=(
                                f"Creating track {index} of {total} from dropped audio..."
                            ),
                        )
                    release_ids = app._sync_releases_for_tracks(
                        created_track_ids,
                        cursor=cur,
                        track_service=bundle.track_service,
                        release_service=bundle.release_service,
                        profile_name=profile_name,
                    )
                return {
                    "track_ids": created_track_ids,
                    "work_ids": created_work_ids,
                    "release_ids": list(release_ids),
                }

            try:
                return _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
                    history_manager=bundle.history_manager,
                    action_label=f"Create Tracks from Audio Files ({len(payloads)} tracks)",
                    action_type="track.audio_drop_import",
                    entity_type="Track",
                    entity_id="batch",
                    payload={
                        "source_paths": [
                            payload.audio_file_source_path for payload in payloads
                        ],
                        "storage_mode": storage_mode,
                        "embedded_artwork_count": artwork_payload_count,
                    },
                    mutation=_mutation,
                    logger=app.logger,
                )
            finally:
                for temp_path in temp_artwork_paths:
                    Path(temp_path).unlink(missing_ok=True)

        def _apply_success(apply_result: dict[str, object]) -> None:
            created_track_ids = list(apply_result.get("track_ids") or [])
            created_work_ids = list(apply_result.get("work_ids") or [])
            release_ids = list(apply_result.get("release_ids") or [])
            try:
                app.conn.commit()
            except Exception:
                pass
            app._sync_application_isrc_registry()
            app._refresh_history_actions()
            app._log_event(
                "track.audio_drop_import",
                "Created tracks from dropped audio files",
                track_ids=created_track_ids,
                work_ids=created_work_ids,
                release_ids=release_ids,
                storage_mode=storage_mode,
                embedded_artwork_count=artwork_payload_count,
                warnings=plan_warnings,
            )
            app._audit(
                "CREATE",
                "DroppedAudioImport",
                ref_id="batch",
                details=(
                    f"tracks={len(created_track_ids)}; works={len(created_work_ids)}; "
                    f"embedded_artwork={artwork_payload_count}; storage_mode={storage_mode}"
                ),
            )
            app._audit_commit()
            app.populate_all_comboboxes()
            app.refresh_table_preserve_view(
                focus_id=created_track_ids[0] if created_track_ids else None
            )
            try:
                app._refresh_work_manager_panel()
                app._refresh_release_browser_panel()
            except Exception:
                pass
            _message_box().information(
                app,
                title,
                f"Created {len(created_track_ids)} track(s) and "
                f"{len(created_work_ids)} linked Work(s) from dropped audio."
                + (
                    f"\nAttached embedded album art to {artwork_payload_count} track(s)."
                    if artwork_payload_count
                    else ""
                )
                + (
                    "\n\nWarnings:\n- " + "\n- ".join(plan_warnings[:12])
                    if plan_warnings
                    else ""
                ),
            )

        app._submit_background_bundle_task(
            title=title,
            description="Creating catalog tracks from dropped audio files...",
            task_fn=_apply_worker,
            kind="write",
            unique_key="track.audio_drop_import",
            cancellable=False,
            on_success=_apply_success,
            on_error=lambda failure: app._show_background_task_error(
                title,
                failure,
                user_message="Could not create tracks from the dropped audio files:",
            ),
        )

    app._submit_background_bundle_task(
        title=title,
        description="Reading metadata from dropped audio files...",
        task_fn=_preview_worker,
        kind="read",
        unique_key="track.audio_drop_import.preview",
        cancellable=False,
        on_success=_preview_success,
        on_error=lambda failure: app._show_background_task_error(
            title,
            failure,
            user_message="Could not prepare the dropped audio import preview:",
        ),
    )


def import_tags_from_audio(app, track_ids: list[int] | None = None):
    title = "Import Metadata from Audio Files"
    if app.audio_tag_service is None or app.track_service is None:
        _message_box().warning(app, title, "Open a profile first.")
        return
    selected_ids = app._normalize_track_ids(
        track_ids or app._catalog_table_controller().selected_track_ids()
    )
    if not selected_ids:
        _message_box().information(
            app, title, "Select one or more tracks with attached audio first."
        )
        return

    policy = str(
        app.settings.value("audio_tags/import_policy", "merge_blanks", str) or "merge_blanks"
    )

    def _preview_worker(bundle, ctx):
        return app._prepare_tag_import_preview(
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
            _message_box().information(
                app,
                title,
                "No readable managed audio files were available for the selected tracks."
                + ("\n\nWarnings:\n- " + "\n- ".join(warnings[:12]) if warnings else ""),
            )
            return

        dlg = _root_attr("TagPreviewDialog", TagPreviewDialog)(
            title=title,
            intro=(
                "Review how embedded file tags map onto the selected catalog records. "
                "Choose the conflict policy you want to apply before importing."
            ),
            rows=preview_rows,
            initial_policy=policy,
            allow_policy_change=True,
            parent=app,
        )
        if dlg.exec() != QDialog.Accepted:
            return

        chosen_policy = dlg.selected_policy()
        app.settings.setValue("audio_tags/import_policy", chosen_policy)
        app.settings.sync()

        def _import_worker(bundle, ctx):
            profile_name = app._current_profile_name()
            import_progress = app._scaled_progress_callback(
                ctx.report_progress, start=0, end=90
            )

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
                        database_values = app._catalog_tag_data_for_track(
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
                        app._apply_tag_patch_to_track(
                            track_id,
                            preview.patch.values,
                            cursor=cur,
                            track_service=bundle.track_service,
                        )
                        updated_track_ids.append(track_id)
                        import_progress(
                            value=index,
                            maximum=total,
                            message=f"Importing tags for track {index} of {total}...",
                        )
                    app._sync_releases_for_tracks(
                        updated_track_ids,
                        cursor=cur,
                        track_service=bundle.track_service,
                        release_service=bundle.release_service,
                        profile_name=profile_name,
                    )
                return {"changed_ids": updated_track_ids}

            return _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
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
                progress_callback=ctx.report_progress,
                post_mutation_progress=(92, "Capturing tag import history snapshot..."),
                record_progress=(94, "Recording tag import history..."),
                logger=app.logger,
            )

        def _import_before_cleanup(result: dict[str, object], ui_progress) -> None:
            changed_ids = list(result.get("changed_ids") or [])
            app._advance_task_ui_progress(
                ui_progress,
                value=97,
                message="Applying imported tag changes...",
            )
            try:
                app.conn.commit()
            except Exception:
                pass
            app._advance_task_ui_progress(
                ui_progress,
                value=99,
                message="Refreshing catalog views and history...",
            )
            app.refresh_table_preserve_view(focus_id=changed_ids[0] if changed_ids else None)
            app.populate_all_comboboxes()
            app._refresh_history_actions()
            app._advance_task_ui_progress(
                ui_progress,
                value=100,
                message="Audio tag import complete.",
            )

        def _import_success(result: dict[str, object]):
            changed_ids = list(result.get("changed_ids") or [])
            app._log_event(
                "tags.import",
                "Imported embedded tags from audio",
                track_ids=changed_ids,
                policy=chosen_policy,
                warnings=warnings,
            )
            app._audit(
                "IMPORT",
                "AudioTags",
                ref_id="batch",
                details=f"track_ids={','.join(str(track_id) for track_id in changed_ids)}; policy={chosen_policy}",
            )
            app._audit_commit()
            _message_box().information(
                app,
                title,
                f"Imported tags for {len(changed_ids or [])} track{'s' if len(changed_ids or []) != 1 else ''}."
                + ("\n\nWarnings:\n- " + "\n- ".join(warnings[:12]) if warnings else ""),
            )

        app._submit_background_bundle_task(
            title=title,
            description="Applying imported audio tags to the selected catalog tracks...",
            task_fn=_import_worker,
            kind="write",
            unique_key="tags.import.apply",
            cancellable=False,
            worker_completion_progress=(96, "Finalizing background tag import..."),
            on_success_before_cleanup=_import_before_cleanup,
            on_success_after_cleanup=_import_success,
            on_error=lambda failure: app._show_background_task_error(
                title,
                failure,
                user_message="Could not import audio tags:",
            ),
        )

    app._submit_background_bundle_task(
        title=title,
        description="Reading embedded tags from the selected audio files...",
        task_fn=_preview_worker,
        kind="read",
        unique_key="tags.import.preview",
        cancellable=False,
        on_success=_preview_success,
        on_error=lambda failure: app._show_background_task_error(
            title,
            failure,
            user_message="Could not prepare the audio tag preview:",
        ),
    )


def autofill_album_metadata(app):
    title = (app.album_title_field.currentText() or "").strip()
    if not title:
        app._update_add_data_generated_fields()
        return
    row = app.catalog_reads.find_album_metadata(title)
    if row:
        rd, upc, genre = row
        if rd:
            qd = QDate.fromString(rd, "yyyy-MM-dd")
            app.release_date_field.setSelectedDate(qd if qd.isValid() else QDate.currentDate())
        if upc:
            app.upc_field.setCurrentText(upc)
        if genre:
            app.genre_field.setCurrentText(genre)
        app.prev_release_toggle.setChecked(True)
    app._update_add_data_generated_fields()

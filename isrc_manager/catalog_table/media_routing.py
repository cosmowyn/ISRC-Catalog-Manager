"""Catalog media/blob routing and standard-media helpers."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QMessageBox, QWidget

from isrc_manager.app_prompts import prompt_storage_mode_choice as _prompt_storage_mode_choice
from isrc_manager.catalog_table import RawValueRole
from isrc_manager.domain.standard_fields import (
    standard_field_spec_for_label,
    standard_media_specs_by_label,
)
from isrc_manager.file_storage import STORAGE_MODE_MANAGED_FILE
from isrc_manager.tasks.history_helpers import run_snapshot_history_action


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _audio_preview_source_spec_for_standard_media(media_key: str) -> dict[str, object]:
    return {
        "kind": "standard",
        "media_key": str(media_key or "").strip() or "audio_file",
    }


def _audio_preview_source_spec_for_custom_field(
    field_id: int,
    *,
    field_name: str | None = None,
) -> dict[str, object]:
    return {
        "kind": "custom",
        "field_id": int(field_id),
        "field_name": str(field_name or "").strip(),
    }


def _standard_media_column_key(app, media_key: str) -> str | None:
    clean_media_key = str(media_key or "").strip()
    for header_text, candidate_media_key in app._standard_media_header_map().items():
        if candidate_media_key != clean_media_key:
            continue
        standard_spec = standard_field_spec_for_label(header_text)
        if standard_spec is not None:
            return f"base:{standard_spec.key}"
        return app._fallback_header_column_key(
            header_text,
            prefix="base",
            logical_index=(
                app.BASE_HEADERS.index(header_text) if header_text in app.BASE_HEADERS else 0
            ),
        )
    return None


def _standard_media_key_for_column_key(app, column_key: str | None) -> str | None:
    normalized_key = str(column_key or "").strip()
    if not normalized_key.startswith("base:"):
        return None
    field_key = normalized_key.split(":", 1)[1]
    for spec in standard_media_specs_by_label().values():
        if spec.key == field_key:
            return spec.media_key
    return None


def _custom_field_column_key(field_id: int) -> str:
    return f"custom:{int(field_id)}"


def _custom_field_for_column_key(app, column_key: str | None) -> dict[str, object] | None:
    normalized_key = str(column_key or "").strip()
    if not normalized_key.startswith("custom:"):
        return None
    try:
        field_id = int(normalized_key.split(":", 1)[1])
    except TypeError, ValueError:
        return None
    return next(
        (field for field in app.active_custom_fields if int(field.get("id") or 0) == field_id),
        None,
    )


def _model_data_for_index(app, index, role: int):
    if index is None or not index.isValid():
        return None
    model = index.model()
    return model.data(index, role) if model is not None else None


def _media_cell_has_payload(
    app,
    index,
    *,
    media_key: str | None = None,
    field_id: int | None = None,
) -> bool:
    raw_value = app._model_data_for_index(index, RawValueRole)
    if isinstance(raw_value, tuple) and len(raw_value) >= 2:
        try:
            raw_track_id = int(raw_value[0])
        except TypeError, ValueError:
            raw_track_id = None
        target_track_id = app._catalog_table_controller().track_id_for_index(index)
        if (
            raw_track_id is not None
            and target_track_id is not None
            and raw_track_id != int(target_track_id)
        ):
            return False
        if media_key is not None:
            return str(raw_value[1]) == str(media_key)
        if field_id is not None:
            try:
                return int(raw_value[1]) == int(field_id)
            except TypeError, ValueError:
                return False
        return True
    return False


def _media_column_for_audio_source_spec(
    app,
    source_spec: dict[str, object] | None,
) -> int | None:
    if not source_spec:
        return None
    kind = str(source_spec.get("kind") or "").strip().lower()
    controller = app._catalog_table_controller()
    if kind == "custom":
        try:
            field_id = int(source_spec.get("field_id") or 0)
        except TypeError, ValueError:
            return None
        if field_id <= 0:
            return None
        return controller.column_for_key(app._custom_field_column_key(field_id))
    media_key = str(source_spec.get("media_key") or "audio_file").strip() or "audio_file"
    return controller.column_for_key(app._standard_media_column_key(media_key))


def _media_cell_has_payload_for_source_spec(
    app,
    index,
    source_spec: dict[str, object] | None,
) -> bool:
    if not source_spec:
        return True
    kind = str(source_spec.get("kind") or "").strip().lower()
    if kind == "custom":
        try:
            field_id = int(source_spec.get("field_id") or 0)
        except TypeError, ValueError:
            return False
        return app._media_cell_has_payload(index, field_id=field_id)
    media_key = str(source_spec.get("media_key") or "audio_file").strip() or "audio_file"
    return app._media_cell_has_payload(index, media_key=media_key)


def _configure_media_attach_drop_targets(app) -> None:
    for widget in (
        app,
        app.centralWidget(),
        getattr(app, "table_panel_widget", None),
        getattr(app, "left_widget_container", None),
        getattr(app, "table", None),
        getattr(getattr(app, "table", None), "viewport", lambda: None)(),
    ):
        if isinstance(widget, QWidget):
            widget.setAcceptDrops(True)
            try:
                widget.removeEventFilter(app)
            except Exception:
                pass
            widget.installEventFilter(app)


def _drop_event_local_file_paths(app, event) -> list[str]:
    mime_data = getattr(event, "mimeData", lambda: None)()
    if mime_data is None:
        return []
    urls = getattr(mime_data, "urls", lambda: [])()
    paths: list[str] = []
    seen: set[str] = set()
    for url in urls or []:
        try:
            is_local = bool(url.isLocalFile())
        except Exception:
            is_local = False
        if not is_local:
            continue
        try:
            path = str(url.toLocalFile() or "").strip()
        except Exception:
            path = ""
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _partition_dropped_media_paths(
    app,
    paths: list[str],
) -> tuple[list[str], list[str], list[str]]:
    audio_paths: list[str] = []
    image_paths: list[str] = []
    unsupported_paths: list[str] = []
    for path in paths:
        if app._is_supported_media_attach_path(path, "audio_file"):
            audio_paths.append(path)
        elif app._is_supported_media_attach_path(path, "album_art"):
            image_paths.append(path)
        else:
            unsupported_paths.append(path)
    return audio_paths, image_paths, unsupported_paths


def _route_dropped_media_paths(app, paths: list[str]) -> bool:
    audio_paths, image_paths, unsupported_paths = app._partition_dropped_media_paths(paths)
    title = "Attach Dropped Media"
    if len(paths) > 1:
        if audio_paths:
            app.bulk_attach_audio_files(
                file_paths=list(paths),
                title="Attach Dropped Audio Files",
            )
            return True
        if image_paths:
            _root_attr("QMessageBox", QMessageBox).information(
                app,
                title,
                "Only audio files are accepted in multi-file drops.\n\n"
                "Drop a single image file when attaching album art.",
            )
            return True
        if unsupported_paths:
            _root_attr("QMessageBox", QMessageBox).information(
                app,
                title,
                "The dropped files were not supported audio or image files.",
            )
            return True
        return False
    if audio_paths:
        app.bulk_attach_audio_files(
            file_paths=list(paths),
            title="Attach Dropped Audio File",
        )
        return True
    if image_paths:
        app.attach_album_art_file_to_catalog(
            file_paths=list(paths),
            title="Attach Dropped Album Art",
        )
        return True
    if unsupported_paths:
        _root_attr("QMessageBox", QMessageBox).information(
            app,
            title,
            "The dropped file was not a supported audio or image file.",
        )
        return True
    return False


def _standard_media_header_map() -> dict[str, str]:
    return {
        label: spec.media_key
        for label, spec in standard_media_specs_by_label().items()
        if spec.media_key
    }


def _standard_field_type_for_header(header_text: str) -> str | None:
    spec = standard_field_spec_for_label(header_text)
    return spec.field_type if spec is not None else None


def _standard_media_key_for_header(app, header_text: str) -> str | None:
    return app._standard_media_header_map().get(header_text)


def track_media_meta(app, track_id: int, media_key: str):
    return app.track_service.get_media_meta(track_id, media_key, cursor=app.cursor)


def track_has_media(app, track_id: int, media_key: str) -> bool:
    return app.track_service.has_media(track_id, media_key, cursor=app.cursor)


def track_fetch_media(app, track_id: int, media_key: str):
    return app.track_service.fetch_media_bytes(track_id, media_key, cursor=app.cursor)


def track_set_media(
    app,
    track_id: int,
    media_key: str,
    source_path: str,
    *,
    storage_mode: str | None = None,
):
    return app.track_service.set_media_path(
        track_id, media_key, source_path, storage_mode=storage_mode, cursor=app.cursor
    )


def track_clear_media(app, track_id: int, media_key: str):
    app.track_service.clear_media(track_id, media_key, cursor=app.cursor)


def track_convert_media_storage_mode(app, track_id: int, media_key: str, target_mode: str):
    return app.track_service.convert_media_storage_mode(
        track_id,
        media_key,
        target_mode,
        cursor=app.cursor,
    )


def _choose_track_media_storage_modes(
    app,
    *,
    audio_source_path: str | None = None,
    album_art_source_path: str | None = None,
    audio_default: str | None = None,
    album_art_default: str | None = None,
    title: str = "Choose Storage Mode",
) -> tuple[str | None, str | None] | None:
    audio_mode = audio_default
    album_art_mode = album_art_default
    if audio_source_path:
        audio_mode = _root_attr("_prompt_storage_mode_choice", _prompt_storage_mode_choice)(
            app,
            title=title,
            subject="the audio file",
            default_mode=audio_default,
        )
        if audio_mode is None:
            return None
    if album_art_source_path:
        album_art_mode = _root_attr("_prompt_storage_mode_choice", _prompt_storage_mode_choice)(
            app,
            title=title,
            subject="the artwork file",
            default_mode=album_art_default,
        )
        if album_art_mode is None:
            return None
    return audio_mode, album_art_mode


def _attach_standard_media_for_track(app, track_id: int, media_key: str):
    path = app._browse_track_media_file(media_key)
    if not path:
        return
    header_label = "Audio File" if media_key == "audio_file" else "Album Art"
    storage_mode = _root_attr("_prompt_storage_mode_choice", _prompt_storage_mode_choice)(
        app,
        title=f"Attach {header_label}",
        subject=header_label.lower(),
        default_mode=STORAGE_MODE_MANAGED_FILE,
    )
    if storage_mode is None:
        return
    if media_key == "audio_file" and not app._confirm_lossy_primary_audio_selection(
        [path],
        title=f"Attach {header_label}",
        action_label="Attaching this audio file",
    ):
        return
    refresh_request = app._capture_catalog_refresh_request(focus_id=int(track_id))
    try:

        def _worker(bundle, ctx):
            attach_progress = app._scaled_progress_callback(
                ctx.report_progress,
                start=6,
                end=74,
            )
            ctx.report_progress(
                value=0,
                maximum=100,
                message=f"Preparing {header_label.lower()} attachment...",
            )

            def _mutation():
                with bundle.conn:
                    cur = bundle.conn.cursor()
                    bundle.track_service.set_media_path(
                        int(track_id),
                        media_key,
                        path,
                        storage_mode=storage_mode,
                        progress_callback=attach_progress,
                        cursor=cur,
                    )
                return {"track_id": int(track_id)}

            result_payload = _root_attr("run_snapshot_history_action", run_snapshot_history_action)(
                history_manager=bundle.history_manager,
                action_label=f"Attach {header_label}",
                action_type=f"track.{media_key}.attach",
                entity_type="Track",
                entity_id=int(track_id),
                payload={
                    "track_id": int(track_id),
                    "media_key": media_key,
                    "storage_mode": storage_mode,
                },
                mutation=_mutation,
                progress_callback=ctx.report_progress,
                post_mutation_progress=(
                    80,
                    f"Capturing {header_label.lower()} history snapshot...",
                ),
                record_progress=(88, f"Recording {header_label.lower()} history..."),
                logger=app.logger,
            )
            ctx.report_progress(
                value=92,
                maximum=100,
                message="Loading refreshed catalog rows, media badges, and lookup values...",
            )
            result_payload["dataset"] = app._load_catalog_ui_dataset_from_bundle(
                bundle,
                ctx,
                progress_start=93,
                progress_end=98,
            )
            return result_payload

        def _before_cleanup(result_payload: dict[str, object], ui_progress) -> None:
            try:
                app.conn.commit()
            except Exception:
                pass
            app._apply_catalog_refresh_request(
                dict(result_payload.get("dataset") or {}),
                refresh_request,
                progress_callback=app._scaled_ui_progress_callback(
                    ui_progress,
                    start=99,
                    end=99,
                ),
            )
            app._advance_task_ui_progress(
                ui_progress,
                value=100,
                message=f"{header_label} attached and catalog UI is ready.",
            )

        def _after_cleanup(_result_payload: dict[str, object]) -> None:
            app._refresh_history_actions()
            if app.statusBar() is not None:
                app.statusBar().showMessage(
                    f"Attached {header_label.lower()} to track {int(track_id)}.",
                    5000,
                )

        app._submit_background_bundle_task(
            title=f"Attach {header_label}",
            description=f"Attaching the selected {header_label.lower()} to the track...",
            task_fn=_worker,
            kind="write",
            unique_key=f"track.{media_key}.attach.{int(track_id)}",
            owner=app,
            on_success_before_cleanup=_before_cleanup,
            on_success_after_cleanup=_after_cleanup,
            on_error=lambda failure: app._show_background_task_error(
                "Track Media Error",
                failure,
                user_message="Failed to attach file:",
            ),
        )
    except Exception as e:
        app.conn.rollback()
        app.logger.exception(f"Attach {media_key} failed: {e}")
        _root_attr("QMessageBox", QMessageBox).critical(
            app, "Track Media Error", f"Failed to attach file:\n{e}"
        )


def _delete_standard_media_for_track(app, track_id: int, media_key: str):
    header_label = "Audio File" if media_key == "audio_file" else "Album Art"
    confirm_text = f"Remove the stored {header_label.lower()} from this track?"
    if media_key == "album_art" and app.track_service is not None:
        shared_track_ids = app.track_service.list_album_group_track_ids(track_id, cursor=app.cursor)
        if len(shared_track_ids) > 1:
            confirm_text = (
                f"Remove the shared album art for this album?\n"
                f"This will affect {len(shared_track_ids)} linked track(s)."
            )
    if (
        _root_attr("QMessageBox", QMessageBox).question(
            app,
            "Delete File",
            confirm_text,
            _root_attr("QMessageBox", QMessageBox).Yes | _root_attr("QMessageBox", QMessageBox).No,
            _root_attr("QMessageBox", QMessageBox).No,
        )
        != _root_attr("QMessageBox", QMessageBox).Yes
    ):
        return
    try:
        app.__root_attr("run_snapshot_history_action", run_snapshot_history_action)(
            action_label=f"Delete {header_label}",
            action_type=f"track.{media_key}.delete",
            entity_type="Track",
            entity_id=track_id,
            payload={"track_id": track_id, "media_key": media_key},
            mutation=lambda: app.track_clear_media(track_id, media_key),
        )
        app.refresh_table_preserve_view(focus_id=track_id)
    except Exception as e:
        app.conn.rollback()
        app.logger.exception(f"Delete {media_key} failed: {e}")
        _root_attr("QMessageBox", QMessageBox).critical(
            app, "Track Media Error", f"Failed to remove file:\n{e}"
        )


def _preview_standard_media_for_track(app, track_id: int, media_key: str):
    media_label = "audio file" if media_key == "audio_file" else "album art"
    try:
        if not app.track_has_media(track_id, media_key):
            _root_attr("QMessageBox", QMessageBox).information(
                app,
                "Track Media",
                f"No stored {media_label} is available for this track.",
            )
            return
        if media_key == "audio_file":
            app._open_audio_preview_for_track(
                int(track_id),
                app._audio_preview_source_spec_for_standard_media(media_key),
                autoplay=True,
            )
            return
        data, _mime = app.track_fetch_media(track_id, media_key)
        title = app._get_track_title(track_id)
        app._open_image_preview(data, title)
    except FileNotFoundError as e:
        app.logger.warning("Preview %s skipped for track %s: %s", media_key, track_id, e)
        _root_attr("QMessageBox", QMessageBox).information(
            app,
            "Track Media",
            (
                f"The stored {media_label} could not be found. "
                "Reattach it or run storage diagnostics."
            ),
        )
    except Exception as e:
        app.conn.rollback()
        app.logger.exception(f"Preview {media_key} failed: {e}")
        _root_attr("QMessageBox", QMessageBox).critical(
            app, "Track Media Error", f"Failed to preview file:\n{e}"
        )

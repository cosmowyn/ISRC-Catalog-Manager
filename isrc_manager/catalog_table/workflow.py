"""Catalog table dataset, search, refresh, and view-state orchestration."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDockWidget, QWidget

from isrc_manager.blob_icons import describe_blob_icon_spec
from isrc_manager.catalog_table import (
    CatalogCellValue,
    CatalogColumnSpec,
    CatalogFilterProxyModel,
    CatalogRowSnapshot,
    CatalogSnapshot,
    CatalogTableModel,
    ColumnKeyRole,
    RawValueRole,
)
from isrc_manager.constants import DEFAULT_HIDDEN_CUSTOM_COLUMN_NAMES
from isrc_manager.domain.standard_fields import standard_field_spec_for_label
from isrc_manager.domain.timecode import parse_hms_text, seconds_to_hms
from isrc_manager.parties import PartyService, artist_primary_label
from isrc_manager.tasks import TaskFailure

if TYPE_CHECKING:
    from isrc_manager.services import (
        CatalogReadService,
        CustomFieldDefinitionService,
        CustomFieldValueService,
        TrackService,
    )


def _initialize_catalog_table_model_view(app) -> None:
    table_model = CatalogTableModel(parent=app)
    filter_proxy = CatalogFilterProxyModel(parent=app)
    filter_proxy.setSourceModel(table_model)
    app._catalog_table_model = table_model
    app._catalog_filter_proxy_model = filter_proxy
    app.table.setModel(filter_proxy)
    app.table.setSortingEnabled(True)
    app.table.sortByColumn(0, Qt.AscendingOrder)
    app._connect_catalog_selection_model()


def _connect_catalog_selection_model(app) -> None:
    selection_model = app.table.selectionModel() if hasattr(app, "table") else None
    if selection_model is None:
        return
    if getattr(app, "_catalog_selection_model_connection", None) is selection_model:
        return
    try:
        selection_model.selectionChanged.connect(lambda *_args: app._on_catalog_selection_changed())
    except Exception:
        pass
    app._catalog_selection_model_connection = selection_model


def _catalog_source_model(app) -> CatalogTableModel | None:
    model = getattr(app, "_catalog_table_model", None)
    return model if isinstance(model, CatalogTableModel) else None


def _catalog_proxy_model(app) -> CatalogFilterProxyModel | None:
    proxy = getattr(app, "_catalog_filter_proxy_model", None)
    return proxy if isinstance(proxy, CatalogFilterProxyModel) else None


def _catalog_view_row_count(app) -> int:
    model = app.table.model() if hasattr(app, "table") else None
    return int(model.rowCount()) if model is not None else 0


def _catalog_view_column_count(app) -> int:
    model = app.table.model() if hasattr(app, "table") else None
    return int(model.columnCount()) if model is not None else 0


def _catalog_header_text_for_column(app, column: int) -> str:
    model = app.table.model() if hasattr(app, "table") else None
    if model is None:
        return ""
    if column < 0 or column >= model.columnCount():
        return ""
    return str(model.headerData(int(column), Qt.Horizontal, Qt.DisplayRole) or "")


def _catalog_table_column_specs_for_fields(
    app,
    active_custom_fields: list[dict[str, object]] | None = None,
) -> tuple[CatalogColumnSpec, ...]:
    fields = (
        list(active_custom_fields)
        if active_custom_fields is not None
        else list(getattr(app, "active_custom_fields", []) or [])
    )
    default_hidden_names = {str(name).strip() for name in DEFAULT_HIDDEN_CUSTOM_COLUMN_NAMES}
    column_specs: list[CatalogColumnSpec] = []
    for logical_index, header_text in enumerate(app.BASE_HEADERS):
        standard_spec = standard_field_spec_for_label(header_text)
        column_key = (
            f"base:{standard_spec.key}"
            if standard_spec is not None
            else app._fallback_header_column_key(
                header_text,
                prefix="base",
                logical_index=logical_index,
            )
        )
        column_specs.append(CatalogColumnSpec(key=column_key, header_text=header_text))

    for field_index, field in enumerate(fields):
        header_text = str(field.get("name") or "").strip() or f"Custom {field_index + 1}"
        try:
            field_id = int(field.get("id"))
        except TypeError, ValueError:
            field_id = None
        logical_index = len(app.BASE_HEADERS) + field_index
        column_key = (
            f"custom:{field_id}"
            if field_id is not None and field_id > 0
            else app._fallback_header_column_key(
                header_text,
                prefix="custom",
                logical_index=logical_index,
            )
        )
        column_specs.append(
            CatalogColumnSpec(
                key=column_key,
                header_text=header_text,
                hidden_by_default=header_text in default_hidden_names,
            )
        )
    return tuple(column_specs)


def _rebuild_table_headers(app):
    source_model = app._catalog_source_model()
    if source_model is not None:
        source_model.set_snapshot(
            CatalogSnapshot(
                column_specs=app._catalog_table_column_specs_for_fields(),
                rows=(),
            )
        )
    app._apply_saved_column_visibility()
    app._rebuild_search_column_choices()
    app._refresh_column_visibility_menu()


def _catalog_combo_values_from_connection(
    conn: sqlite3.Connection,
    *,
    progress_callback=None,
) -> dict[str, list[str]]:
    artist_values: list[str] = []
    seen_artist_values: set[str] = set()

    def _values(query: str) -> list[str]:
        try:
            return [
                str(row[0] or "").strip()
                for row in conn.execute(query).fetchall()
                if str(row[0] or "").strip()
            ]
        except sqlite3.OperationalError:
            return []

    try:
        party_service = PartyService(conn)
        for record in party_service.list_artist_parties():
            primary = artist_primary_label(record)
            for candidate in (primary, *list(getattr(record, "artist_aliases", ()) or ())):
                clean_value = str(candidate or "").strip()
                if not clean_value or clean_value in seen_artist_values:
                    continue
                seen_artist_values.add(clean_value)
                artist_values.append(clean_value)
    except Exception:
        artist_values = []

    combo_values = {"artists": sorted(artist_values, key=str.casefold)}
    if callable(progress_callback):
        progress_callback(1, 5, "Loaded Artist lookup values.")
    combo_values["albums"] = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT title FROM Albums WHERE title IS NOT NULL AND title != '' ORDER BY title"
        ).fetchall()
    ]
    if callable(progress_callback):
        progress_callback(2, 5, "Loaded Album lookup values.")
    combo_values["upcs"] = _values("""
            SELECT value
            FROM (
                SELECT upc AS value
                FROM Tracks
                WHERE upc IS NOT NULL AND upc != ''
                UNION
                SELECT upc AS value
                FROM Releases
                WHERE upc IS NOT NULL AND upc != ''
            )
            ORDER BY value
            """)
    if callable(progress_callback):
        progress_callback(3, 5, "Loaded UPC lookup values.")
    combo_values["genres"] = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT genre FROM Tracks WHERE genre IS NOT NULL AND genre != '' ORDER BY genre"
        ).fetchall()
    ]
    if callable(progress_callback):
        progress_callback(4, 5, "Loaded Genre lookup values.")
    combo_values["catalog_numbers"] = _values("""
            SELECT value
            FROM (
                SELECT catalog_number AS value
                FROM Tracks
                WHERE catalog_number IS NOT NULL AND catalog_number != ''
                UNION
                SELECT catalog_number AS value
                FROM Releases
                WHERE catalog_number IS NOT NULL AND catalog_number != ''
            )
            ORDER BY value
            """)
    if callable(progress_callback):
        progress_callback(5, 5, "Loaded catalog number lookup values.")
    return combo_values


def _apply_catalog_combo_values(app, combo_values: dict[str, list[str]]) -> None:
    app._populate_combobox(app.artist_field, combo_values.get("artists", []))
    app._populate_combobox(
        app.additional_artist_field, combo_values.get("artists", []), allow_empty=True
    )
    app._populate_combobox(app.album_title_field, combo_values.get("albums", []), allow_empty=True)
    app._populate_combobox(app.upc_field, combo_values.get("upcs", []), allow_empty=True)
    app._populate_combobox(app.genre_field, combo_values.get("genres", []), allow_empty=True)
    if hasattr(app.catalog_number_field, "refresh"):
        app.catalog_number_field.refresh()
    else:
        app._populate_combobox(
            app.catalog_number_field,
            combo_values.get("catalog_numbers", []),
            allow_empty=True,
        )


def populate_all_comboboxes(app):
    if app.conn is None:
        return
    app._apply_catalog_combo_values(app._catalog_combo_values_from_connection(app.conn))
    app._refresh_add_track_artist_party_choices()


def _rebuild_search_column_choices(app):
    cur_data = app.search_column_combo.currentData() if app.search_column_combo.count() else -1
    app.search_column_combo.blockSignals(True)
    app.search_column_combo.clear()
    app.search_column_combo.addItem("All columns", -1)

    model = app.table.model()
    column_count = model.columnCount() if model is not None else 0
    for idx in range(column_count):
        if app.table.isColumnHidden(idx):
            continue
        name = str(model.headerData(idx, Qt.Horizontal, Qt.DisplayRole) or "")
        if not name:
            continue
        column_key = str(model.headerData(idx, Qt.Horizontal, ColumnKeyRole) or "")
        app.search_column_combo.addItem(name, column_key or idx)

    restore = app.search_column_combo.findData(cur_data)
    app.search_column_combo.setCurrentIndex(restore if restore != -1 else 0)
    app.search_column_combo.blockSignals(False)


def _selected_search_column_key(app) -> str | None:
    data = app.search_column_combo.currentData()
    if data in (-1, None, ""):
        return None
    if isinstance(data, str):
        return data
    try:
        logical_index = int(data)
    except TypeError, ValueError:
        return None
    model = app.table.model()
    if model is None or logical_index < 0 or logical_index >= model.columnCount():
        return None
    return str(model.headerData(logical_index, Qt.Horizontal, ColumnKeyRole) or "") or None


def _apply_catalog_search_filter(app):
    proxy = app._catalog_proxy_model()
    if proxy is not None:
        proxy.set_search_text(app.search_field.text())
        proxy.set_search_column_key(app._selected_search_column_key())
        proxy.set_explicit_track_ids(getattr(app, "_explicit_row_filter_track_ids", None))
    app._sync_catalog_count_label()
    app._sync_catalog_duration_label()
    app._refresh_workspace_selection_scopes()


def reset_search(app):
    app._explicit_row_filter_track_ids = None
    app.search_field.blockSignals(True)
    app.search_field.clear()
    app.search_field.blockSignals(False)
    app.search_column_combo.blockSignals(True)
    idx = app.search_column_combo.findData(-1)  # “All columns”
    app.search_column_combo.setCurrentIndex(idx if idx != -1 else 0)
    app.search_column_combo.blockSignals(False)
    app._apply_catalog_search_filter()


def _set_catalog_filter_text(app, filter_text: str) -> None:
    clean_text = str(filter_text or "")
    app.search_field.setText(clean_text)


def _set_catalog_filter_from_current_cell(app) -> None:
    table = getattr(app, "table", None)
    if table is None:
        return
    index = table.currentIndex()
    if not index.isValid():
        selection_model = table.selectionModel()
        selected_indexes = selection_model.selectedIndexes() if selection_model is not None else []
        index = selected_indexes[0] if selected_indexes else index
    if not index.isValid():
        return
    app._set_catalog_filter_text(str(index.data(Qt.DisplayRole) or ""))


def _load_catalog_ui_dataset(
    app,
    *,
    custom_field_definitions: CustomFieldDefinitionService | None = None,
    catalog_reads: CatalogReadService | None = None,
    track_service: TrackService | None = None,
    custom_field_values: CustomFieldValueService | None = None,
    conn: sqlite3.Connection | None = None,
    progress_callback=None,
) -> dict[str, object]:
    active_custom_fields = (
        custom_field_definitions.list_active_fields()
        if custom_field_definitions is not None
        else app.load_active_custom_fields()
    )
    if callable(progress_callback):
        progress_callback(
            6,
            100,
            f"Loaded {len(active_custom_fields)} active custom fields.",
        )
    active_catalog_reads = catalog_reads or app.catalog_reads
    active_conn = conn or app.conn
    if active_catalog_reads is None or active_conn is None:
        raise ValueError("Catalog dataset services are not available.")
    rows, cf_map = active_catalog_reads.fetch_rows_with_customs(
        active_custom_fields,
        progress_callback=(
            app._scaled_progress_callback(
                progress_callback,
                start=10,
                end=44,
            )
            if callable(progress_callback)
            else None
        ),
    )
    track_ids = [int(row[0]) for row in rows if row and row[0] is not None]
    blob_badges = active_catalog_reads.fetch_blob_badge_payload(
        track_ids,
        active_custom_fields,
        track_service=track_service or app.track_service,
        custom_field_values=custom_field_values or app.custom_field_values,
        progress_callback=(
            app._scaled_progress_callback(
                progress_callback,
                start=46,
                end=64,
            )
            if callable(progress_callback)
            else None
        ),
    )
    combo_values = app._catalog_combo_values_from_connection(
        active_conn,
        progress_callback=(
            app._scaled_progress_callback(
                progress_callback,
                start=68,
                end=84,
            )
            if callable(progress_callback)
            else None
        ),
    )
    if callable(progress_callback):
        progress_callback(88, 100, f"Prepared catalog dataset with {len(rows)} rows.")
    return {
        "active_custom_fields": active_custom_fields,
        "rows": rows,
        "cf_map": cf_map,
        "blob_badges": blob_badges,
        "combo_values": combo_values,
    }


def _sort_value_for_catalog_cell(
    app,
    *,
    header_text: str,
    display_text: str,
    raw_value,
    custom_def: dict[str, object] | None = None,
):
    text = str(display_text or "")
    try:
        if header_text == "ID":
            return int(raw_value if raw_value not in (None, "") else text)
        if header_text == "Track Length (hh:mm:ss)":
            return int(raw_value or parse_hms_text(text))
        if header_text in ("Entry Date", "Release Date"):
            return int(text.replace("-", "")) if text else 0
        if custom_def and custom_def.get("field_type") == "date":
            return int(text.replace("-", "")) if text else 0
        if custom_def and custom_def.get("field_type") == "checkbox":
            return 1 if text.lower() in ("1", "true", "yes", "y", "checked") else 0
        return float(text) if "." in text else int(text)
    except Exception:
        return text


def _catalog_cell_value(
    app,
    value,
    *,
    header_text: str,
    display_text: str | None = None,
    custom_def: dict[str, object] | None = None,
    tooltip: str | None = None,
) -> CatalogCellValue:
    resolved_display = "" if value is None else str(value)
    if display_text is not None:
        resolved_display = str(display_text)
    return CatalogCellValue(
        display_text=resolved_display,
        sort_value=app._sort_value_for_catalog_cell(
            header_text=header_text,
            display_text=resolved_display,
            raw_value=value,
            custom_def=custom_def,
        ),
        search_text=resolved_display,
        raw_value=value,
        tooltip=tooltip,
    )


def _media_badge_cell_value(
    app,
    meta: dict[str, object] | None,
    *,
    track_id: int,
    header_text: str,
    media_key: str | None = None,
    field: dict[str, object] | None = None,
) -> CatalogCellValue:
    meta = dict(meta or {})
    has_payload = bool(meta.get("has_media") or meta.get("has_blob"))
    display = (
        app._format_blob_badge(meta.get("mime_type"), meta.get("size_bytes", 0))
        if has_payload
        else "—"
    )
    tooltip = ""
    raw_value = ""
    icon = None
    decoration_key = None
    if has_payload and media_key:
        kind = app._blob_icon_kind_for_standard_media(media_key, meta=meta)
        tooltip = app._standard_media_badge_tooltip(media_key, meta, display)
        raw_value = (int(track_id), media_key)
        icon = app._resolve_blob_badge_icon(
            spec=app._blob_icon_spec_for_standard_media(media_key, meta=meta),
            kind=kind,
        )
        decoration_key = kind
    elif has_payload and field is not None:
        field_type = str(field.get("field_type") or "").strip().lower()
        kind = app._blob_icon_kind_for_storage(
            "audio" if field_type == "blob_audio" else "image",
            storage_mode=meta.get("storage_mode"),
        )
        tooltip = (
            f"{describe_blob_icon_spec(field.get('blob_icon_payload'), kind=kind, allow_inherit=True)}\n"
            f"{app._storage_mode_badge_label(meta.get('storage_mode'))}\n"
            f"Stored size: {display}"
        )
        raw_value = (int(track_id), int(field["id"]))
        icon = app._resolve_blob_badge_icon(
            spec=app._blob_icon_spec_for_custom_field_with_meta(field, meta=meta),
            kind=kind,
        )
        decoration_key = kind
    return CatalogCellValue(
        display_text=display,
        sort_value=display,
        search_text=display if has_payload else "",
        raw_value=raw_value,
        tooltip=tooltip or None,
        decoration_key=decoration_key,
        decoration=icon,
    )


def _catalog_snapshot_from_dataset(
    app,
    rows: list[tuple],
    cf_map: dict[tuple[int, int], str],
    *,
    blob_badges: dict[str, object] | None = None,
    progress_callback=None,
) -> CatalogSnapshot:
    column_specs = app._catalog_table_column_specs_for_fields(app.active_custom_fields)
    standard_meta = dict((blob_badges or {}).get("standard_media") or {})
    custom_meta = dict((blob_badges or {}).get("custom_fields") or {})
    base_cols = len(app.BASE_HEADERS)
    snapshot_rows: list[CatalogRowSnapshot] = []
    total_rows = len(rows)
    if total_rows <= 0:
        if callable(progress_callback):
            progress_callback(1, 1, "No catalog rows needed to be applied.")
        return CatalogSnapshot(column_specs=column_specs, rows=())
    batch_size = max(1, min(100, total_rows // 20 or 1))

    for row_idx, row_data in enumerate(rows):
        track_id = int(row_data[0])
        cells_by_key: dict[str, CatalogCellValue] = {}
        for col_idx in range(base_cols):
            column_spec = column_specs[col_idx]
            header = column_spec.header_text
            val_raw = row_data[col_idx]
            if header == "Track Length (hh:mm:ss)":
                secs = 0
                try:
                    secs = int(val_raw or 0)
                except Exception:
                    secs = parse_hms_text(str(val_raw))
                cells_by_key[column_spec.key] = app._catalog_cell_value(
                    secs,
                    header_text=header,
                    display_text=seconds_to_hms(secs),
                )
            elif header in app._standard_media_header_map():
                media_key = app._standard_media_key_for_header(header)
                cells_by_key[column_spec.key] = app._media_badge_cell_value(
                    standard_meta.get((track_id, media_key)),
                    track_id=track_id,
                    header_text=header,
                    media_key=media_key,
                )
            else:
                cells_by_key[column_spec.key] = app._catalog_cell_value(
                    val_raw,
                    header_text=header,
                )

        for offset, field in enumerate(app.active_custom_fields):
            column_spec = column_specs[base_cols + offset]
            field_type = str(field.get("field_type") or "").strip().lower()
            if field_type in ("blob_image", "blob_audio"):
                cells_by_key[column_spec.key] = app._media_badge_cell_value(
                    custom_meta.get((track_id, int(field["id"]))),
                    track_id=track_id,
                    header_text=column_spec.header_text,
                    field=field,
                )
            else:
                val = cf_map.get((track_id, field["id"]), "")
                cells_by_key[column_spec.key] = app._catalog_cell_value(
                    val,
                    header_text=column_spec.header_text,
                    custom_def=field,
                )
        snapshot_rows.append(CatalogRowSnapshot(track_id=track_id, cells_by_key=cells_by_key))
        if callable(progress_callback) and (
            row_idx == total_rows - 1 or ((row_idx + 1) % batch_size) == 0
        ):
            progress_callback(
                row_idx + 1,
                total_rows,
                f"Applied {row_idx + 1} of {total_rows} catalog rows.",
            )
    return CatalogSnapshot(column_specs=column_specs, rows=tuple(snapshot_rows))


def _apply_catalog_model_dataset(
    app,
    dataset: dict[str, object],
    *,
    progress_callback=None,
) -> None:
    app.active_custom_fields = list(dataset.get("active_custom_fields") or [])
    app._rebuild_table_headers()
    if callable(progress_callback):
        progress_callback(76, 100, "Rebuilt catalog table headers.")
    snapshot = app._catalog_snapshot_from_dataset(
        list(dataset.get("rows") or []),
        dict(dataset.get("cf_map") or {}),
        blob_badges=dict(dataset.get("blob_badges") or {}),
        progress_callback=(
            app._scaled_progress_callback(
                progress_callback,
                start=78,
                end=90,
            )
            if callable(progress_callback)
            else None
        ),
    )
    source_model = app._catalog_source_model()
    if source_model is not None:
        source_model.set_snapshot(snapshot)
    app._apply_catalog_search_filter()
    app._apply_catalog_combo_values(dict(dataset.get("combo_values") or {}))
    if callable(progress_callback):
        progress_callback(91, 100, "Applied catalog lookup values.")
    app.table.resizeColumnsToContents()
    if callable(progress_callback):
        progress_callback(93, 100, "Resized catalog table columns.")
    app._sync_catalog_count_label()
    app._sync_catalog_duration_label()
    if callable(progress_callback):
        progress_callback(95, 100, "Updated catalog counts and duration.")
    if callable(progress_callback):
        progress_callback(98, 100, "Applied prepared media badges to catalog model.")


def _capture_catalog_refresh_request(
    app,
    *,
    focus_id: int | None = None,
    select_path: str | None = None,
) -> dict[str, object]:
    return {
        "view_state": app._capture_view_state(),
        "sort_enabled": bool(app.table.isSortingEnabled()),
        "focus_id": int(focus_id) if focus_id is not None else None,
        "select_path": str(select_path) if select_path else None,
    }


def _load_catalog_ui_dataset_from_bundle(
    app,
    bundle,
    ctx,
    *,
    progress_start: int,
    progress_end: int,
) -> dict[str, object]:
    return app._load_catalog_ui_dataset(
        custom_field_definitions=bundle.custom_field_definitions,
        catalog_reads=bundle.catalog_reads,
        track_service=bundle.track_service,
        custom_field_values=bundle.custom_field_values,
        conn=bundle.conn,
        progress_callback=app._scaled_progress_callback(
            ctx.report_progress,
            start=progress_start,
            end=progress_end,
        ),
    )


def _apply_catalog_refresh_request(
    app,
    dataset: dict[str, object],
    refresh_request: dict[str, object],
    *,
    progress_callback=None,
    refresh_history_actions: bool = True,
    refresh_add_track_controls: bool = True,
) -> None:
    state = dict(refresh_request.get("view_state") or {})
    sort_enabled = bool(refresh_request.get("sort_enabled"))
    focus_id = refresh_request.get("focus_id")
    select_path = refresh_request.get("select_path")
    current_sort_enabled = bool(app.table.isSortingEnabled())

    with app._suspend_table_layout_history():
        with app._suspend_catalog_view_updates():
            if current_sort_enabled:
                app.table.setSortingEnabled(False)

            app._apply_catalog_model_dataset(
                dataset,
                progress_callback=(
                    app._scaled_progress_callback(
                        progress_callback,
                        start=0,
                        end=74,
                    )
                    if callable(progress_callback)
                    else None
                ),
            )

            if callable(progress_callback):
                progress_callback(76, 100, "Restoring saved catalog headers and view state...")
            try:
                app._load_header_state()
            except Exception as exc:
                app.logger.warning("Failed to load header state: %s", exc)

            app._restore_view_state(state)
            if focus_id is not None:
                app._select_row_by_id(int(focus_id))
            if select_path:
                app._reload_profiles_list(select_path=str(select_path))
            if sort_enabled:
                app.table.setSortingEnabled(True)
                app._sort_catalog_table(
                    state.get("sort_col", 0),
                    state.get("sort_order", Qt.AscendingOrder),
                )
            elif current_sort_enabled:
                app.table.setSortingEnabled(True)

            if callable(progress_callback):
                progress_callback(90, 100, "Refreshing generated fields and history state...")
            app._update_add_data_generated_fields()
            if refresh_history_actions:
                app._refresh_history_actions()

            if refresh_add_track_controls:
                if callable(progress_callback):
                    progress_callback(96, 100, "Refreshing add-track governance controls...")
                app._refresh_add_track_artist_party_choices()
                app._refresh_work_track_creation_context_ui()
        app._flush_pending_catalog_repaints(
            progress_callback=progress_callback,
            value=98,
            maximum=100,
            message="Painting refreshed catalog icons and widgets...",
        )


@contextmanager
def _suspend_catalog_view_updates(app):
    table = getattr(app, "table", None)
    widgets: list[QWidget] = []
    for candidate in (
        table,
        getattr(table, "viewport", lambda: None)(),
        getattr(table, "horizontalHeader", lambda: None)(),
        getattr(getattr(table, "horizontalHeader", lambda: None)(), "viewport", lambda: None)(),
        getattr(table, "verticalHeader", lambda: None)(),
        getattr(getattr(table, "verticalHeader", lambda: None)(), "viewport", lambda: None)(),
    ):
        if isinstance(candidate, QWidget):
            widgets.append(candidate)

    previous_states: list[tuple[QWidget, bool]] = []
    for widget in widgets:
        try:
            previous_states.append((widget, widget.updatesEnabled()))
        except Exception:
            continue
    for widget, _previous_state in previous_states:
        try:
            widget.setUpdatesEnabled(False)
        except Exception:
            continue
    try:
        yield
    finally:
        for widget, previous_state in previous_states:
            try:
                widget.setUpdatesEnabled(previous_state)
                widget.updateGeometry()
                widget.update()
            except Exception:
                continue


def _catalog_repaint_targets(app) -> list[QWidget]:
    seen: set[int] = set()
    targets: list[QWidget] = []

    def _add_target(widget) -> None:
        if not isinstance(widget, QWidget):
            return
        widget_id = id(widget)
        if widget_id in seen:
            return
        seen.add(widget_id)
        targets.append(widget)

    _add_target(app)
    _add_target(app.centralWidget())
    _add_target(app.table)
    try:
        _add_target(app.table.viewport())
    except Exception:
        pass
    try:
        header = app.table.horizontalHeader()
        _add_target(header)
        _add_target(header.viewport())
    except Exception:
        pass
    try:
        header = app.table.verticalHeader()
        _add_target(header)
        _add_target(header.viewport())
    except Exception:
        pass
    try:
        _add_target(app.statusBar())
    except Exception:
        pass
    for dock in app.findChildren(QDockWidget):
        _add_target(dock)
        try:
            _add_target(dock.widget())
        except Exception:
            continue
    return targets


def _flush_pending_catalog_repaints(
    app,
    *,
    progress_callback=None,
    value: int | None = None,
    maximum: int | None = None,
    message: str = "Painting refreshed catalog icons and widgets...",
    passes: int = 3,
) -> None:
    if callable(progress_callback):
        progress_callback(value, maximum, message)
    qapp = QApplication.instance()
    if qapp is None:
        return
    targets = app._catalog_repaint_targets()
    for _ in range(max(1, int(passes))):
        for widget in targets:
            try:
                if not widget.isVisible():
                    continue
            except Exception:
                continue
            try:
                widget.updateGeometry()
            except Exception:
                pass
            try:
                widget.update()
            except Exception:
                pass
        try:
            qapp.processEvents()
        except Exception:
            pass
        if QCoreApplication is not None:
            for event_type in (
                int(QEvent.LayoutRequest),
                int(QEvent.UpdateRequest),
                int(QEvent.Paint),
                int(QEvent.DeferredDelete),
            ):
                try:
                    QCoreApplication.sendPostedEvents(None, event_type)
                except Exception:
                    continue
        for widget in targets:
            try:
                if widget.isVisible():
                    widget.repaint()
            except Exception:
                continue
        try:
            qapp.processEvents()
        except Exception:
            pass


def _refresh_catalog_ui_in_background(
    app,
    *,
    focus_id: int | None = None,
    select_path: str | None = None,
    show_dialog: bool = False,
    on_finished=None,
    on_complete=None,
    unique_key: str = "catalog.ui.refresh",
    retry_count: int = 0,
    progress_callback=None,
) -> str | None:
    if app.conn is None:
        if on_complete is not None:
            on_complete()
        return None
    refresh_request = app._capture_catalog_refresh_request(
        focus_id=focus_id,
        select_path=select_path,
    )
    if bool(refresh_request.get("sort_enabled")):
        app.table.setSortingEnabled(False)
    app._clear_catalog_table_model()
    app._sync_catalog_count_label()
    app._sync_catalog_duration_label()
    completion_notified = False

    def _notify_complete() -> None:
        nonlocal completion_notified
        if completion_notified:
            return
        completion_notified = True
        if on_complete is not None:
            on_complete()

    def _worker(bundle, ctx):
        ctx.set_status("Loading catalog rows, media badges, and lookup values...")
        return app._load_catalog_ui_dataset_from_bundle(
            bundle,
            ctx,
            progress_start=0,
            progress_end=74,
        )

    def _before_cleanup(dataset: dict[str, object], ui_progress):
        try:
            app.conn.commit()
        except Exception:
            pass
        app._apply_catalog_refresh_request(
            dataset,
            refresh_request,
            progress_callback=app._scaled_ui_progress_callback(
                ui_progress,
                start=76,
                end=99,
            ),
        )
        app._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="Catalog view fully restored and ready.",
        )
        if on_finished is not None:
            on_finished()

    def _after_cleanup(_dataset: dict[str, object]) -> None:
        _notify_complete()

    def _finished():
        if not bool(refresh_request.get("sort_enabled")):
            app.table.setSortingEnabled(False)

    def _handle_error(failure: TaskFailure) -> None:
        retry_message = str(failure.message or "").lower()
        if retry_count < 3 and "exclusive database task is currently running" in retry_message:
            QTimer.singleShot(
                100,
                lambda: app._refresh_catalog_ui_in_background(
                    focus_id=focus_id,
                    select_path=select_path,
                    show_dialog=show_dialog,
                    on_finished=on_finished,
                    on_complete=on_complete,
                    unique_key=unique_key,
                    retry_count=retry_count + 1,
                ),
            )
            return
        try:
            app._show_background_task_error(
                "Load Catalog",
                failure,
                user_message="Could not load the catalog view:",
            )
        finally:
            _notify_complete()

    task_id = app._submit_background_bundle_task(
        title="Load Catalog",
        description="Loading catalog rows, media badges, and lookup values...",
        task_fn=_worker,
        kind="read",
        unique_key=unique_key,
        show_dialog=show_dialog,
        owner=app,
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_after_cleanup,
        on_error=_handle_error,
        on_finished=_finished,
        on_progress=(
            (lambda update: progress_callback(update.value, update.maximum, update.message))
            if callable(progress_callback)
            else None
        ),
    )
    if task_id is None:
        _notify_complete()
    return task_id


def refresh_table(app):
    # Ensure custom fields and headers are ready
    dataset = app._load_catalog_ui_dataset()

    previous_suspend_state = app._suspend_layout_history
    app._suspend_layout_history = True
    try:
        _prev_sort_enabled = app.table.isSortingEnabled()
        header = app.table.horizontalHeader()
        sort_col = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        if _prev_sort_enabled:
            app.table.setSortingEnabled(False)
        app._clear_catalog_table_model()
        app._apply_catalog_model_dataset(dataset)
        app.table.setSortingEnabled(_prev_sort_enabled)
        if _prev_sort_enabled:
            app._sort_catalog_table(sort_col, sort_order)
    finally:
        app._suspend_layout_history = previous_suspend_state


def _clear_catalog_table_model(app) -> None:
    source_model = app._catalog_source_model()
    if source_model is not None:
        source_model.set_snapshot(
            CatalogSnapshot(column_specs=app._catalog_table_column_specs_for_fields(), rows=())
        )
    proxy = app._catalog_proxy_model()
    if proxy is not None:
        proxy.set_explicit_track_ids(getattr(app, "_explicit_row_filter_track_ids", None))


def _sort_catalog_table(app, column: int | None, order: Qt.SortOrder) -> None:
    try:
        sort_column = int(column if column is not None else 0)
    except TypeError, ValueError:
        sort_column = 0
    if 0 <= sort_column < app._catalog_view_column_count():
        app.table.sortByColumn(sort_column, order)


def _sync_catalog_count_label(app):
    # updates 'showing: N records'
    if not hasattr(app, "count_label") or app.count_label is None:
        return
    visible = app.table.model().rowCount() if app.table.model() is not None else 0
    app.count_label.setText(f"showing: {visible} record{'s' if visible != 1 else ''}")


def _sync_catalog_duration_label(app):
    if not hasattr(app, "duration_label") or app.duration_label is None:
        return
    col_idx = app._catalog_table_controller().column_for_key("base:track_length_sec")
    if col_idx is None:
        col_idx = -1
    if col_idx == -1:
        app.duration_label.setText("")
        return
    total_sec = 0
    try:
        for r in range(app._catalog_view_row_count()):
            index = app.table.model().index(r, col_idx)
            v = app.table.model().data(index, RawValueRole)
            if isinstance(v, (int, float)):
                total_sec += int(v)
            else:
                total_sec += parse_hms_text(str(app.table.model().data(index) or ""))
    except Exception:
        pass
    app.duration_label.setText(f"total: {seconds_to_hms(total_sec)}")


def _capture_view_state(app):
    hh = app.table.horizontalHeader()
    state = {
        "filter_text": app.search_field.text(),
        "search_column_data": app.search_column_combo.currentData(),
        "sort_col": hh.sortIndicatorSection(),
        "sort_order": hh.sortIndicatorOrder(),
        "v_scroll": app.table.verticalScrollBar().value(),
        "h_scroll": app.table.horizontalScrollBar().value(),
        "selected_track_ids": list(app._catalog_table_controller().selected_track_ids()),
        "current_track_id": app._catalog_table_controller().current_track_id(),
    }
    return state


def _restore_view_state(app, state):
    filter_text = str(state.get("filter_text") or "")
    search_field_state = app.search_field.blockSignals(True)
    try:
        app.search_field.setText(filter_text)
    finally:
        app.search_field.blockSignals(search_field_state)

    search_column_data = state.get("search_column_data", -1)
    search_column_state = app.search_column_combo.blockSignals(True)
    try:
        column_index = app.search_column_combo.findData(search_column_data)
        if column_index < 0:
            column_index = app.search_column_combo.findData(-1)
        app.search_column_combo.setCurrentIndex(column_index if column_index >= 0 else 0)
    finally:
        app.search_column_combo.blockSignals(search_column_state)

    sort_col = state.get("sort_col", 0)
    sort_order = state.get("sort_order", Qt.AscendingOrder)
    app._sort_catalog_table(sort_col, sort_order)
    app._apply_catalog_search_filter()
    selected_track_ids = app._normalize_track_ids(state.get("selected_track_ids") or [])
    if selected_track_ids:
        app._select_track_ids_in_table(selected_track_ids)
    current_track_id = state.get("current_track_id")
    if current_track_id is not None:
        app._select_row_by_id(int(current_track_id))
    app.table.verticalScrollBar().setValue(state.get("v_scroll", 0))
    app.table.horizontalScrollBar().setValue(state.get("h_scroll", 0))

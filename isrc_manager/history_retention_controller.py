"""History retention, auto-snapshot, and storage-budget orchestration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from isrc_manager.constants import (
    DEFAULT_AUTO_SNAPSHOT_ENABLED,
    DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    MIN_AUTO_SNAPSHOT_INTERVAL_MINUTES,
)
from isrc_manager.history import HistoryCleanupBlockedError, HistoryStorageCleanupService
from isrc_manager.services import HistoryRetentionSettings
from isrc_manager.storage_sizes import bytes_to_megabytes_floor


def _current_auto_snapshot_settings(app) -> tuple[bool, int]:
    if app.settings_reads is None:
        return DEFAULT_AUTO_SNAPSHOT_ENABLED, DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES
    snapshot_settings = app.settings_reads.load_auto_snapshot_settings()
    return bool(snapshot_settings.enabled), int(snapshot_settings.interval_minutes)


def _current_history_retention_settings(app) -> HistoryRetentionSettings:
    if app.settings_reads is None:
        settings = HistoryRetentionSettings()
    else:
        settings = app.settings_reads.load_history_retention_settings()
    settings.storage_budget_mb = app._application_history_storage_budget_mb(
        default=settings.storage_budget_mb
    )
    return settings


def _application_history_storage_budget_mb(app, *, default: int) -> int:
    registry = getattr(app, "application_isrc_registry", None)
    if registry is None:
        return int(default)
    try:
        return int(registry.read_history_storage_budget_mb(default))
    except Exception:
        return int(default)


def _set_application_history_storage_budget_mb(app, value: int) -> int:
    registry = getattr(app, "application_isrc_registry", None)
    if registry is None:
        return int(value)
    return int(registry.write_history_storage_budget_mb(int(value)))


def _apply_history_snapshot_retention_policy(
    app,
    *,
    trigger_label: str,
    settings: HistoryRetentionSettings | None = None,
):
    if app.history_manager is None or app.settings_reads is None:
        return None
    cleanup_service = HistoryStorageCleanupService(app.history_manager)
    active_settings = settings or app._current_history_retention_settings()
    result = cleanup_service.enforce_snapshot_retention(active_settings)
    if result.pruned_snapshot_ids or result.quarantined_entry_ids:
        app._refresh_history_actions()
        if result.pruned_snapshot_ids:
            app.statusBar().showMessage(
                (
                    f"Applied snapshot retention after {trigger_label}: "
                    f"removed {len(result.pruned_snapshot_ids)} live snapshot(s)."
                ),
                5000,
            )
    return result


def _path_size_recursive(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        candidate = Path(path)
    except Exception:
        return 0
    try:
        if candidate.is_dir():
            total = _allocated_path_size(candidate)
            for child_path in candidate.rglob("*"):
                total += _allocated_path_size(child_path)
            return total
        if candidate.exists():
            return _allocated_path_size(candidate)
    except Exception:
        return 0
    return 0


def _allocated_path_size(path: Path) -> int:
    try:
        stat_result = path.stat()
    except Exception:
        return 0
    blocks = getattr(stat_result, "st_blocks", 0)
    if blocks:
        return int(blocks) * 512
    return int(stat_result.st_size or 0)


def _estimate_history_snapshot_capture_bytes(app) -> int:
    if app.history_manager is None:
        return 0
    total = app._path_size_recursive(app.history_manager.db_path)
    managed_root = getattr(app.history_manager, "managed_root", None)
    if managed_root is not None:
        for dir_name in app.history_manager.MANAGED_DIRECTORIES:
            total += app._path_size_recursive(Path(managed_root) / dir_name)
    return total


def _prepare_history_storage_for_projected_growth(
    app,
    *,
    trigger_label: str,
    additional_bytes: int,
    interactive: bool,
) -> bool:
    if app.history_manager is None or app.settings_reads is None:
        return True
    settings = app._current_history_retention_settings()
    app._apply_history_snapshot_retention_policy(
        trigger_label=trigger_label,
        settings=settings,
    )
    cleanup_service = HistoryStorageCleanupService(app.history_manager)
    projection = cleanup_service.preview_storage_projection(
        settings,
        additional_bytes=max(0, int(additional_bytes or 0)),
    )
    if projection.budget_bytes <= 0 or projection.projected_over_budget_bytes <= 0:
        return True

    if (
        not interactive
        and settings.auto_cleanup_enabled
        and projection.candidate_items
        and projection.projected_over_budget_after_cleanup_bytes <= 0
    ):
        try:
            cleanup_result = cleanup_service.cleanup_selected(
                [item.item_key for item in projection.candidate_items]
            )
        except HistoryCleanupBlockedError as exc:
            app.logger.warning(
                "History cleanup could not make room before %s: %s",
                trigger_label,
                exc,
            )
            app.statusBar().showMessage(
                f"Skipped {trigger_label}: history cleanup is blocked until diagnostics repairs are applied.",
                7000,
            )
            return False
        except Exception as exc:
            app.logger.warning(
                "Preemptive history cleanup failed before %s: %s",
                trigger_label,
                exc,
            )
            app.statusBar().showMessage(
                f"Skipped {trigger_label}: the history cleanup policy could not make room safely.",
                7000,
            )
            return False
        else:
            if cleanup_result.removed_item_keys:
                app._refresh_history_actions()
                if app.history_dialog is not None and app.history_dialog.isVisible():
                    app.history_dialog.refresh_data()
        return True

    if not interactive:
        message = (
            f"Skipped {trigger_label}: projected history usage "
            f"{app._human_size(projection.projected_total_bytes)} would exceed the "
            f"{app._human_size(projection.budget_bytes)} budget."
        )
        if projection.blocked_by_protected_items:
            message += " Remaining space is still required by the current undo boundary or retained recovery artifacts."
        app.statusBar().showMessage(message, 7000)
        app.logger.info(
            "Skipped %s because projected history usage would exceed the budget",
            trigger_label,
        )
        return False

    details = [
        (
            f"This action is estimated to add about {app._human_size(projection.additional_bytes)} "
            f"of history data."
        ),
        (
            f"Current usage: {app._human_size(projection.current_total_bytes)} of "
            f"{app._human_size(projection.budget_bytes)}."
        ),
        (f"Projected usage: {app._human_size(projection.projected_total_bytes)}."),
    ]
    if projection.auto_cleanup_enabled and projection.reclaimable_bytes > 0:
        details.append(
            f"Current automatic cleanup policy can reclaim about {app._human_size(projection.reclaimable_bytes)}."
        )
    elif not projection.auto_cleanup_enabled:
        details.append(
            "Automatic cleanup is disabled for this profile, so no space will be reclaimed automatically."
        )
    if projection.blocked_by_protected_items:
        details.append(
            "Even after safe automatic cleanup, the profile would still be over budget because the remaining items are still needed by the current undo boundary or retained recovery artifacts."
        )
    else:
        details.append("The profile would cross the storage budget before the next cleanup pass.")
    details.append("Continue anyway, or review Application Storage Admin first?")

    message_box = QMessageBox(app)
    message_box.setIcon(QMessageBox.Warning)
    message_box.setWindowTitle("History Storage Budget")
    message_box.setText("\n\n".join(details))
    continue_btn = message_box.addButton("Continue", QMessageBox.AcceptRole)
    cleanup_btn = message_box.addButton(
        "Open Application Storage Admin",
        QMessageBox.ActionRole,
    )
    cancel_btn = message_box.addButton(QMessageBox.Cancel)
    message_box.setDefaultButton(continue_btn)
    message_box.exec()
    clicked = message_box.clickedButton()
    if clicked is cleanup_btn:
        app.open_application_storage_admin_dialog()
        return False
    if clicked is cancel_btn:
        return False
    return True


def _enforce_history_storage_budget(
    app,
    *,
    trigger_label: str,
    interactive: bool = False,
) -> None:
    if app.history_manager is None or app.settings_reads is None:
        return
    cleanup_service = HistoryStorageCleanupService(app.history_manager)
    settings = app._current_history_retention_settings()
    app._apply_history_snapshot_retention_policy(
        trigger_label=trigger_label,
        settings=settings,
    )
    try:
        result = cleanup_service.enforce_storage_budget(settings)
    except HistoryCleanupBlockedError as exc:
        app.logger.warning("History cleanup is blocked during %s: %s", trigger_label, exc)
        if interactive:
            QMessageBox.warning(
                app,
                "History Storage",
                "History cleanup is currently blocked until diagnostics repairs are applied.\n\n"
                + str(exc),
            )
        return
    except Exception as exc:
        app.logger.warning("History budget enforcement failed during %s: %s", trigger_label, exc)
        if interactive:
            QMessageBox.warning(
                app,
                "History Storage",
                f"Could not enforce the history storage policy:\n{exc}",
            )
        return

    if result.removed_item_keys:
        app._refresh_history_actions()
        if app.history_dialog is not None and app.history_dialog.isVisible():
            app.history_dialog.refresh_data()
        app.statusBar().showMessage(
            f"History cleanup removed {len(result.removed_item_keys)} item(s) after {trigger_label}.",
            5000,
        )

    if result.over_budget_bytes <= 0:
        app._last_history_budget_warning_signature = None
        return

    signature = (
        str(trigger_label),
        bytes_to_megabytes_floor(result.total_bytes),
        bytes_to_megabytes_floor(result.budget_bytes),
        bool(result.blocked_by_protected_items),
    )
    if not interactive and signature == app._last_history_budget_warning_signature:
        return
    app._last_history_budget_warning_signature = signature

    message_parts = [
        (
            f"History storage is using {app._human_size(result.total_bytes)} while the "
            f"profile budget is {app._human_size(result.budget_bytes)}."
        )
    ]
    if result.removed_item_keys:
        message_parts.append(
            f"Automatic cleanup already removed {len(result.removed_item_keys)} safe item(s)."
        )
    elif not settings.auto_cleanup_enabled:
        message_parts.append(
            "Automatic cleanup is disabled for this profile, so nothing was deleted automatically."
        )
    if result.blocked_by_protected_items:
        message_parts.append(
            "The remaining over-budget storage is still needed by the current undo boundary or retained recovery artifacts."
        )
    else:
        message_parts.append(
            "The profile is still over budget and may need application-wide storage cleanup."
        )
    message_parts.append("Open Application Storage Admin now?")
    if (
        QMessageBox.question(
            app,
            "History Storage Budget",
            "\n\n".join(message_parts),
            QMessageBox.Yes | QMessageBox.No,
        )
        == QMessageBox.Yes
    ):
        app.open_application_storage_admin_dialog()


def _refresh_auto_snapshot_schedule(app) -> None:
    if not hasattr(app, "auto_snapshot_timer"):
        return
    if app.history_manager is None or app.settings_reads is None:
        app.auto_snapshot_timer.stop()
        app._last_auto_snapshot_marker = None
        return

    enabled, interval_minutes = app._current_auto_snapshot_settings()
    if not enabled:
        app.auto_snapshot_timer.stop()
        app._last_auto_snapshot_marker = None
        return

    interval_minutes = max(
        MIN_AUTO_SNAPSHOT_INTERVAL_MINUTES,
        min(
            MAX_AUTO_SNAPSHOT_INTERVAL_MINUTES,
            int(interval_minutes or DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES),
        ),
    )
    interval_ms = int(interval_minutes * 60 * 1000)
    if app.auto_snapshot_timer.interval() != interval_ms or not app.auto_snapshot_timer.isActive():
        app.auto_snapshot_timer.start(interval_ms)


def _current_auto_snapshot_marker(app) -> int | None:
    if app.history_manager is None:
        return None
    entry = app.history_manager.get_current_entry()
    while entry is not None:
        action_type = entry.action_type or ""
        if action_type.startswith("file.") or action_type in {
            "db.verify",
            "snapshot.create",
            "snapshot.delete",
        }:
            entry = (
                app.history_manager.fetch_entry(entry.parent_id)
                if entry.parent_id is not None
                else None
            )
            continue
        return entry.entry_id
    return None


def _on_auto_snapshot_timer(app) -> None:
    if app.history_manager is None or app.settings_reads is None:
        return
    enabled, _interval_minutes = app._current_auto_snapshot_settings()
    if not enabled:
        app.auto_snapshot_timer.stop()
        return

    marker = app._current_auto_snapshot_marker()
    if marker is None or marker == app._last_auto_snapshot_marker:
        return
    estimated_bytes = app._estimate_history_snapshot_capture_bytes()
    if not app._prepare_history_storage_for_projected_growth(
        trigger_label="automatic snapshot",
        additional_bytes=estimated_bytes,
        interactive=False,
    ):
        return

    label = f"Automatic Snapshot {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    try:
        snapshot = app.history_manager.capture_snapshot(kind="auto_interval", label=label)
        app._last_auto_snapshot_marker = marker
        app._log_event(
            "snapshot.auto.create",
            "Automatic snapshot created",
            snapshot_id=snapshot.snapshot_id,
            label=snapshot.label,
            marker=marker,
        )
        app.statusBar().showMessage(f"Automatic snapshot created: {snapshot.label}", 4000)
        if app.history_dialog is not None and app.history_dialog.isVisible():
            app.history_dialog.refresh_data()
        app._enforce_history_storage_budget(trigger_label="automatic snapshot")
    except Exception as exc:
        app.logger.exception(f"Automatic snapshot failed: {exc}")


def _schedule_history_storage_budget_enforcement(app, *, trigger_label: str) -> None:
    app._history_budget_enforcement_trigger_label = str(trigger_label or "history update")
    if app._history_budget_enforcement_scheduled or app._history_budget_enforcement_running:
        return
    app._history_budget_enforcement_scheduled = True

    def _run() -> None:
        app._history_budget_enforcement_scheduled = False
        if app._history_budget_enforcement_running:
            return
        app._history_budget_enforcement_running = True
        try:
            app._enforce_history_storage_budget(
                trigger_label=app._history_budget_enforcement_trigger_label,
                interactive=False,
            )
        finally:
            app._history_budget_enforcement_running = False

    QTimer.singleShot(0, _run)

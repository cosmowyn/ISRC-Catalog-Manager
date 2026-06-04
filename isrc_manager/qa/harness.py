"""Headless UI PQ harness for ISRC Catalog Manager."""

from __future__ import annotations

import os
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from .deviations import DeviationRecorder
from .evidence import EvidenceRecorder
from .inventory import UIInventoryItem, discover_ui_inventory, write_inventory
from .mocks import NoNetworkGuard
from .scenarios import (
    run_accounting_workflow,
    run_assets_deliverables_workflow,
    run_authenticity_workflow,
    run_catalog_workflow,
    run_contract_workflow,
    run_diagnostics_workflow,
    run_generated_output_qualification_workflow,
    run_help_documentation_workflow,
    run_media_audio_workflow,
    run_menu_inventory,
    run_relationship_workflow,
    run_soundcloud_workflow,
    run_startup_smoke,
    run_visual_qualification_workflow,
)
from .traceability import TraceabilityRow, build_traceability_matrix, write_traceability_matrix

_QUALIFICATION_FONT_FAMILY = "Arial"
_QUALIFICATION_FONT_POINT_SIZE = 11
_QUALIFICATION_WINDOW_WIDTH = 1472
_QUALIFICATION_WINDOW_HEIGHT = 800


def _no_background_refresh(_self: Any, *args: Any, **kwargs: Any) -> None:
    on_finished = kwargs.get("on_finished")
    on_complete = kwargs.get("on_complete")
    if callable(on_finished):
        on_finished()
    if callable(on_complete):
        on_complete()


def _no_op(_self: Any, *args: Any, **kwargs: Any) -> None:
    del args, kwargs


class _ImmediateTaskProgress:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []
        self.statuses: list[str] = []

    def report_progress(
        self,
        value: int | None = None,
        maximum: int | None = None,
        message: str | None = None,
    ) -> None:
        self.updates.append(
            {
                "value": value,
                "maximum": maximum,
                "message": str(message or ""),
            }
        )

    def set_status(self, message: str) -> None:
        self.statuses.append(str(message or ""))

    def raise_if_cancelled(self) -> None:
        return


class _ImmediateServiceBundle:
    _ALIASES = {
        "track_import_repair_queue": "track_import_repair_queue_service",
        "workflow_service": "repertoire_workflow_service",
    }

    def __init__(self, app: Any) -> None:
        self.conn = app.conn
        self.settings = app.settings
        for name in (
            "code_registry_service",
            "track_service",
            "release_service",
            "license_service",
            "catalog_reads",
            "custom_field_definitions",
            "custom_field_values",
            "xml_export_service",
            "xml_import_service",
            "exchange_service",
            "conversion_service",
            "repertoire_exchange_service",
            "party_exchange_service",
            "master_transfer_service",
            "quality_service",
            "party_service",
            "work_service",
            "contract_service",
            "license_migration_service",
            "rights_service",
            "asset_service",
            "global_search_service",
            "relationship_explorer_service",
            "gs1_settings_service",
            "gs1_integration_service",
            "audio_tag_service",
            "tagged_audio_export_service",
            "history_manager",
            "database_maintenance",
            "settings_reads",
            "settings_mutations",
            "profile_kv",
            "authenticity_key_service",
            "authenticity_manifest_service",
            "audio_watermark_service",
            "audio_authenticity_service",
            "forensic_watermark_service",
            "forensic_export_service",
        ):
            setattr(self, name, getattr(app, name, None))
        for bundle_name, app_name in self._ALIASES.items():
            setattr(self, bundle_name, getattr(app, app_name, None))


def _finish_immediate_task(
    kwargs: dict[str, Any], result: object, progress: _ImmediateTaskProgress
) -> None:
    on_success_before_cleanup = kwargs.get("on_success_before_cleanup")
    on_success = kwargs.get("on_success")
    on_success_after_cleanup = kwargs.get("on_success_after_cleanup")
    on_finished = kwargs.get("on_finished")
    if callable(on_success_before_cleanup):
        on_success_before_cleanup(result, progress)
    if callable(on_success):
        on_success(result)
    if callable(on_success_after_cleanup):
        on_success_after_cleanup(result)
    if callable(on_finished):
        on_finished()


def _run_background_task_immediately(_self: Any, *args: Any, **kwargs: Any) -> object | None:
    del args
    task_fn = kwargs.get("task_fn")
    if not callable(task_fn):
        return None
    progress = _ImmediateTaskProgress()
    try:
        progress.set_status(str(kwargs.get("description") or ""))
        result = task_fn(progress)
        _finish_immediate_task(kwargs, result, progress)
        return result
    except Exception as exc:
        on_error = kwargs.get("on_error")
        if callable(on_error):
            from isrc_manager.tasks.manager import TaskFailure

            on_error(TaskFailure(message=str(exc), traceback_text=""))
            return None
        raise


def _run_background_bundle_task_immediately(
    self: Any,
    *args: Any,
    **kwargs: Any,
) -> object | None:
    del args
    task_fn = kwargs.get("task_fn")
    if not callable(task_fn):
        return None
    progress = _ImmediateTaskProgress()
    try:
        progress.set_status(str(kwargs.get("description") or ""))
        result = task_fn(_ImmediateServiceBundle(self), progress)
        _finish_immediate_task(kwargs, result, progress)
        return result
    except Exception as exc:
        on_error = kwargs.get("on_error")
        if callable(on_error):
            from isrc_manager.tasks.manager import TaskFailure

            on_error(TaskFailure(message=str(exc), traceback_text=""))
            return None
        raise


class UIQualificationHarness:
    """Creates a temporary no-network application session and writes UI PQ artifacts."""

    def __init__(self, artifact_dir: Path | str = "artifacts/ui_pq") -> None:
        self.artifact_dir = Path(artifact_dir)
        self.evidence = EvidenceRecorder(self.artifact_dir)
        self.deviations = DeviationRecorder(self.artifact_dir / "deviations.csv")
        self.inventory: list[UIInventoryItem] = []
        self.traceability_rows: list[TraceabilityRow] = []
        self.window: Any | None = None
        self.app: QApplication | None = None
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self._patchers: list[Any] = []
        self._network_guard: NoNetworkGuard | None = None
        self._has_run = False
        self.qa_data: dict[str, int] = {}
        self._original_app_font: QFont | None = None
        self._original_app_stylesheet: str | None = None

    @property
    def database_path(self) -> str:
        if self.window is None:
            return ""
        return str(getattr(self.window, "current_db_path", "") or "")

    @property
    def connection(self) -> Any:
        if self.window is None or getattr(self.window, "conn", None) is None:
            raise RuntimeError("UI PQ harness has no active database connection.")
        return self.window.conn

    def __enter__(self) -> "UIQualificationHarness":
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        local_appdata = root / "local-appdata"
        qt_settings = root / "qt-settings"
        local_appdata.mkdir(parents=True, exist_ok=True)
        qt_settings.mkdir(parents=True, exist_ok=True)

        from isrc_manager import main_window as app_module

        def _fake_writable_location(location: object) -> str:
            location_name = getattr(location, "name", str(location)).replace("/", "_")
            path = qt_settings / location_name
            path.mkdir(parents=True, exist_ok=True)
            return str(path)

        self._patchers = [
            mock.patch.dict(
                os.environ,
                {
                    "CI": "1",
                    "ISRC_QA_MODE": "1",
                    "LOCALAPPDATA": str(local_appdata),
                    "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen"),
                    "XDG_CACHE_HOME": str(root / "xdg-cache"),
                    "XDG_CONFIG_HOME": str(root / "xdg-config"),
                    "XDG_DATA_HOME": str(root / "xdg-data"),
                },
                clear=False,
            ),
            mock.patch.object(
                QStandardPaths, "writableLocation", side_effect=_fake_writable_location
            ),
            mock.patch.object(
                app_module.App,
                "_refresh_catalog_ui_in_background",
                _no_background_refresh,
            ),
            mock.patch.object(
                app_module.App,
                "_submit_background_task",
                _run_background_task_immediately,
            ),
            mock.patch.object(
                app_module.App,
                "_submit_background_bundle_task",
                _run_background_bundle_task_immediately,
            ),
            mock.patch.object(app_module.App, "_schedule_owner_party_bootstrap", _no_op),
            mock.patch.object(app_module.App, "_schedule_startup_update_check", _no_op),
            mock.patch.object(app_module.App, "_schedule_startup_sound_after_startup", _no_op),
            mock.patch.object(app_module.App, "_enable_app_interaction_sounds", _no_op),
            mock.patch.object(app_module.App, "_apply_theme", _no_op),
            mock.patch.object(
                app_module.App,
                "_prepare_database_for_open_blocking",
                return_value=False,
            ),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No),
        ]
        for patcher in self._patchers:
            patcher.start()
        self._network_guard = NoNetworkGuard()
        self._network_guard.__enter__()

        self.app = QApplication.instance() or QApplication([])
        self._original_app_font = QFont(self.app.font())
        self._original_app_stylesheet = self.app.styleSheet()
        qualification_font = QFont(_QUALIFICATION_FONT_FAMILY)
        qualification_font.setPointSize(_QUALIFICATION_FONT_POINT_SIZE)
        self.app.setFont(qualification_font)
        self.app.setStyleSheet("")
        self.window = app_module.App()
        self.window.show()
        self.window.resize(_QUALIFICATION_WINDOW_WIDTH, _QUALIFICATION_WINDOW_HEIGHT)
        self.process_events()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        try:
            if self.window is not None:
                self.window.close()
                close_db = getattr(self.window, "_close_database_connection", None)
                if callable(close_db):
                    close_db()
                self.window.deleteLater()
                self.process_events()
        finally:
            self.window = None
            if self.app is not None:
                if self._original_app_font is not None:
                    self.app.setFont(self._original_app_font)
                if self._original_app_stylesheet is not None:
                    self.app.setStyleSheet(self._original_app_stylesheet)
            self._original_app_font = None
            self._original_app_stylesheet = None
            if self._network_guard is not None:
                self._network_guard.__exit__(None, None, None)
                self._network_guard = None
            for patcher in reversed(self._patchers):
                patcher.stop()
            self._patchers = []
            if self._tmpdir is not None:
                self._tmpdir.cleanup()
                self._tmpdir = None

    def process_events(self, cycles: int = 4) -> None:
        if self.app is None:
            return
        for _ in range(max(1, int(cycles))):
            self.app.processEvents()

    def run_full_qualification(self) -> None:
        if self._has_run:
            return
        self._has_run = True
        self._run_step("UI-PQ-INV-001", "inventory", self.run_inventory)
        self._run_step("UI-PQ-SMOKE-001", "startup smoke", lambda: run_startup_smoke(self))
        self._run_step("UI-PQ-MENU-001", "menu/action inventory", lambda: run_menu_inventory(self))
        self._run_step(
            "UI-PQ-SET-001",
            "visual/theme/dialog workflow",
            lambda: run_visual_qualification_workflow(self),
        )
        self._run_step(
            "UI-PQ-HELP-001",
            "help documentation coverage",
            lambda: run_help_documentation_workflow(self),
        )
        track_id = self._run_step(
            "UI-PQ-CAT-001", "catalog workflow", lambda: run_catalog_workflow(self)
        )
        if isinstance(track_id, int):
            self.qa_data["track_id"] = track_id
        ids = None
        if isinstance(track_id, int):
            ids = self._run_step(
                "UI-PQ-REL-001",
                "relationship workflow",
                lambda: run_relationship_workflow(self, track_id=track_id),
            )
        if ids is not None:
            updated_ids = self._run_step(
                "UI-PQ-CON-001",
                "contract workflow",
                lambda: run_contract_workflow(self, ids),
            )
            if updated_ids is not None:
                ids = updated_ids
            self.qa_data.update(
                {
                    "party_id": ids.party_id,
                    "work_id": ids.work_id,
                    "release_id": ids.release_id,
                    "contract_id": ids.contract_id,
                    "right_id": ids.right_id,
                }
            )
            self._run_step(
                "UI-PQ-ACC-001",
                "accounting workflow",
                lambda: run_accounting_workflow(self, ids),
            )
            self._run_step(
                "UI-PQ-SC-001",
                "soundcloud workflow",
                lambda: run_soundcloud_workflow(self, ids),
            )
        self._run_step(
            "UI-PQ-DIAG-001",
            "diagnostics workflow",
            lambda: run_diagnostics_workflow(self),
        )
        self._run_step(
            "UI-PQ-IMP-001",
            "generated output workflow",
            lambda: run_generated_output_qualification_workflow(self),
        )
        workflow_track_id = int(self.qa_data.get("track_id") or track_id or 0)
        if workflow_track_id > 0:
            self._run_step(
                "UI-PQ-ASSET-001",
                "assets, deliverables, and derivative ledger workflow",
                lambda: run_assets_deliverables_workflow(self, track_id=workflow_track_id),
            )
            self._run_step(
                "UI-PQ-AUTH-001",
                "authenticity, watermark, and forensic workflow",
                lambda: run_authenticity_workflow(self, track_id=workflow_track_id),
            )
            self._run_step(
                "UI-PQ-MEDIA-001",
                "media player, audio attachment, conversion, and derivative ledger workflow",
                lambda: run_media_audio_workflow(self, track_id=workflow_track_id),
            )
        else:
            raise RuntimeError(
                "UI PQ media/authenticity workflows require the catalog workflow track id."
            )
        self.finalize()

    def run_help_documentation_qualification(self) -> None:
        if self._has_run:
            return
        self._has_run = True
        self._run_step("UI-PQ-INV-001", "inventory", self.run_inventory)
        self._run_step("UI-PQ-SMOKE-001", "startup smoke", lambda: run_startup_smoke(self))
        self._run_step("UI-PQ-MENU-001", "menu/action inventory", lambda: run_menu_inventory(self))
        self._run_step(
            "UI-PQ-SET-001",
            "visual/theme/dialog workflow",
            lambda: run_visual_qualification_workflow(self),
        )
        self._run_step(
            "UI-PQ-HELP-001",
            "help documentation coverage",
            lambda: run_help_documentation_workflow(self),
        )
        self.finalize()

    def run_inventory(self) -> None:
        if self.window is None:
            raise RuntimeError("Cannot inventory UI before the main window is open.")
        self.inventory = discover_ui_inventory(self.window)
        inventory_path = self.artifact_dir / "ui_inventory.json"
        write_inventory(inventory_path, self.inventory)
        self.traceability_rows = build_traceability_matrix(
            self.inventory,
            deviations=self.deviations,
            database_path=self.database_path,
            evidence_path=str(self.evidence.evidence_path),
        )
        write_traceability_matrix(
            self.artifact_dir / "traceability_matrix.csv",
            self.traceability_rows,
        )
        self.evidence.record(
            "UI-PQ-INV-001",
            status="passed",
            message="Runtime UI inventory and traceability matrix were generated.",
            data={
                "inventory_count": len(self.inventory),
                "traceability_rows": len(self.traceability_rows),
                "inventory_path": str(inventory_path),
            },
        )

    def finalize(self) -> None:
        self.evidence.write_json()
        self.deviations.write()
        automated_count = sum(
            1 for row in self.traceability_rows if row.coverage_status == "covered"
        )
        pending_count = max(0, len(self.traceability_rows) - automated_count)
        deviation_statuses = Counter(deviation.status for deviation in self.deviations.deviations)
        deviation_coverages = Counter(
            deviation.coverage_status for deviation in self.deviations.deviations
        )
        self.evidence.write_summary(
            inventory_count=len(self.inventory),
            traceability_count=len(self.traceability_rows),
            deviation_count=len(self.deviations.deviations),
            automated_count=automated_count,
            pending_count=pending_count,
            database_path=self.database_path,
            open_deviation_count=int(deviation_statuses.get("open", 0)),
            pending_deviation_count=int(deviation_statuses.get("pending_manual", 0)),
            object_name_gap_count=int(deviation_coverages.get("object_name_gap", 0)),
        )

    def _run_step(self, test_id: str, label: str, func: Callable[[], Any]) -> Any:
        try:
            return func()
        except Exception as exc:
            self.deviations.record_exception(
                test_id=test_id,
                ui_area="ui_pq",
                workflow=label,
                ui_object="UIQualificationHarness",
                step="Execute qualification step",
                expected="Step completes without unhandled exception.",
                exc=exc,
                database_path=self.database_path,
                evidence_path=str(self.evidence.evidence_path),
            )
            self.evidence.record(
                test_id,
                status="failed",
                message=f"{label} failed: {type(exc).__name__}: {exc}",
            )
            return None

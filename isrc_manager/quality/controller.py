"""Quality dashboard workflow orchestration for the application shell."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QMessageBox

from isrc_manager.quality.dialogs import QualityDashboardDialog
from isrc_manager.quality.models import QualityIssue


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def open_quality_dashboard(self):
    if self.quality_service is None:
        _message_box().warning(self, "Data Quality Dashboard", "Open a profile first.")
        return
    existing_dialog = getattr(self, "quality_dashboard_dialog", None)
    if existing_dialog is not None:
        existing_dialog.refresh_scan()
        existing_dialog.show()
        existing_dialog.raise_()
        existing_dialog.activateWindow()
        return existing_dialog

    self.quality_dashboard_dialog = _root_attr("QualityDashboardDialog", QualityDashboardDialog)(
        service=self.quality_service,
        scan_callback=self._scan_quality_dashboard_in_background,
        task_manager=self.background_tasks,
        release_choices_provider=self._release_choices,
        apply_fix_callback=self._apply_quality_fix,
        open_issue_callback=self._open_issue_from_dashboard,
        parent=self,
    )
    self.quality_dashboard_dialog.show()
    self.quality_dashboard_dialog.raise_()
    self.quality_dashboard_dialog.activateWindow()
    return self.quality_dashboard_dialog


def _scan_quality_dashboard_in_background(self):
    with self.background_service_factory.open_bundle() as bundle:
        return bundle.quality_service.scan()


def _apply_quality_fix(self, issue: QualityIssue) -> str:
    fix_key = str(issue.fix_key or "").strip()
    if not fix_key:
        raise ValueError("The selected quality issue does not expose a suggested fix.")

    def mutation():
        return self.quality_service.apply_fix(fix_key, issue=issue)

    message = self._run_snapshot_history_action(
        action_label=f"Quality Fix: {fix_key}",
        action_type="quality.fix",
        entity_type="QualityIssue",
        entity_id=fix_key,
        payload={
            "fix_key": fix_key,
            "issue_type": issue.issue_type,
            "entity_type": issue.entity_type,
            "entity_id": issue.entity_id,
            "release_id": issue.release_id,
            "track_id": issue.track_id,
        },
        mutation=mutation,
    )
    self._log_event("quality.fix", "Applied quality fix", fix_key=fix_key, message_text=message)
    self._audit("REPAIR", "QualityIssue", ref_id=fix_key, details=message)
    self._audit_commit()
    self.refresh_table_preserve_view()
    self.populate_all_comboboxes()
    return str(message)


def _open_issue_from_dashboard(self, issue: QualityIssue) -> None:
    if issue.entity_type == "work" and issue.entity_id:
        self.open_work_manager(work_id=int(issue.entity_id))
        return
    if issue.issue_type == "track_missing_linked_work" and issue.track_id:
        self.open_work_manager(scope_track_ids=[int(issue.track_id)])
        return
    if issue.entity_type == "track" and issue.track_id:
        self.open_selected_editor(issue.track_id)
        return
    if issue.entity_type == "release" and issue.release_id:
        self.open_release_editor(issue.release_id)
        return

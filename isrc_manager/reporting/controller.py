"""Application-facing reporting controller helpers."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QDialog, QMessageBox

from .crash_detection import CrashSession
from .dialogs import CrashReportPromptDialog, ManualBugReportDialog, ReportPreviewDialog
from .github import ReportSubmissionResult
from .service import ReportingService


def initialize_reporting(app: Any) -> None:
    """Create the reporting service and start the runtime session marker."""

    try:
        service = ReportingService.from_environment(
            data_root=Path(app.data_root),
            logs_dir=Path(app.logs_dir),
            app_version=str(app._app_version_text()),
            logger=logging.getLogger("ISRCManager.reporting"),
        )
        app.reporting_service = service
        app._crash_report_startup_checks_enabled = _startup_crash_reports_enabled()
        app._pending_crash_report_session = (
            service.start_session() if app._crash_report_startup_checks_enabled else None
        )
    except Exception:
        logger = getattr(app, "logger", logging.getLogger("ISRCManager"))
        logger.exception("Crash reporting initialization failed.")
        app.reporting_service = None
        app._pending_crash_report_session = None


def prompt_for_pending_crash_report(app: Any) -> None:
    if not _startup_crash_reports_enabled(app):
        app._pending_crash_report_session = None
        return
    crash_session = getattr(app, "_pending_crash_report_session", None)
    if not isinstance(crash_session, CrashSession):
        return
    service = _service(app)
    if service is None:
        return

    prompt = CrashReportPromptDialog(parent=app)
    if prompt.exec() != QDialog.Accepted:
        return
    try:
        report = service.create_crash_report(
            crash_session,
            include_os_context=prompt.include_os_context(),
        )
    except Exception:
        _log_exception(app, "Crash report generation failed.")
        QMessageBox.warning(
            app,
            "Crash Report",
            "The crash report could not be generated. No information was sent.",
        )
        return
    _preview_and_submit(app, service, report)


def open_bug_report_dialog(app: Any) -> None:
    service = _service(app)
    if service is None:
        initialize_reporting(app)
        service = _service(app)
    if service is None:
        QMessageBox.warning(
            app,
            "Report a Bug",
            "Bug reporting is unavailable because the local reporting service could not start.",
        )
        return

    dialog = ManualBugReportDialog(parent=app)
    if dialog.exec() != QDialog.Accepted:
        return
    try:
        report = service.create_manual_report(dialog.fields())
    except Exception:
        _log_exception(app, "Bug report generation failed.")
        QMessageBox.warning(
            app,
            "Report a Bug",
            "The bug report could not be generated. No information was sent.",
        )
        return
    _preview_and_submit(app, service, report)


def mark_clean_shutdown(app: Any) -> None:
    if not _startup_crash_reports_enabled(app):
        return
    service = _service(app)
    if service is not None:
        service.mark_clean_shutdown()


def record_app_event(app: Any, event: str, message: str) -> None:
    if not _startup_crash_reports_enabled(app):
        return
    service = _service(app)
    if service is not None:
        service.record_event(event=event, message=message, workflow=_active_workflow(app))


def _preview_and_submit(app: Any, service: ReportingService, report) -> None:
    safe_report = service.sanitize_report(report)
    preview = safe_report.to_markdown()
    dialog = ReportPreviewDialog(safe_report, preview, parent=app)
    if dialog.exec() != QDialog.Accepted or not dialog.submit_requested:
        return

    try:
        result = service.submit_or_save(safe_report)
    except Exception:
        _log_exception(app, "Report submission failed.")
        result = ReportSubmissionResult(False, "Submission failed before the report left the app.")
    _show_submission_result(app, result)


def _show_submission_result(app: Any, result: ReportSubmissionResult) -> None:
    if result.success:
        details = f"\n\nIssue: {result.issue_url}" if result.issue_url else ""
        QMessageBox.information(app, "Report Submitted", f"{result.message}{details}")
        return
    if result.pending_path:
        QMessageBox.information(
            app,
            "Report Saved Locally",
            (
                f"{result.message}\n\n"
                f"Pending report path:\n{result.pending_path}\n\n"
                "No report was submitted because the secure report endpoint is unavailable "
                "or rejected the request."
            ),
        )
        return
    QMessageBox.warning(app, "Report Not Submitted", result.message or "Report submission failed.")


def _service(app: Any) -> ReportingService | None:
    service = getattr(app, "reporting_service", None)
    return service if isinstance(service, ReportingService) else None


def _startup_crash_reports_enabled(app: Any | None = None) -> bool:
    configured = getattr(app, "_crash_report_startup_checks_enabled", None)
    if isinstance(configured, bool):
        return configured
    return bool(getattr(sys, "frozen", False))


def _active_workflow(app: Any) -> str:
    try:
        dock = getattr(app, "main_workspace_stack", None)
        current = dock.currentWidget() if dock is not None else None
        if current is not None:
            return str(current.objectName() or current.windowTitle() or type(current).__name__)
    except Exception:
        return ""
    return ""


def _log_exception(app: Any, message: str) -> None:
    logger = getattr(app, "logger", logging.getLogger("ISRCManager"))
    logger.exception(message)

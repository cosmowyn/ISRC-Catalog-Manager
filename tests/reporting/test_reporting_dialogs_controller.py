from __future__ import annotations

import logging
from types import SimpleNamespace

from PySide6.QtWidgets import QDialog, QWidget

from isrc_manager.reporting import controller
from isrc_manager.reporting.crash_detection import CrashSession
from isrc_manager.reporting.dialogs import (
    CrashReportPromptDialog,
    ManualBugReportDialog,
    ReportPreviewDialog,
)
from isrc_manager.reporting.github import ReportSubmissionResult
from isrc_manager.reporting.models import ManualBugReportFields, ReportPayload, ReportSection
from isrc_manager.reporting.service import ReportingService
from tests.qt_test_helpers import require_qapplication


class _FakeSubmitter:
    def __init__(self, result: ReportSubmissionResult):
        self.result = result
        self.submitted: list[ReportPayload] = []

    def submit(self, report: ReportPayload) -> ReportSubmissionResult:
        self.submitted.append(report)
        return self.result


class _FakeLogger:
    def __init__(self):
        self.messages: list[str] = []

    def exception(self, message: str) -> None:
        self.messages.append(message)


def _report() -> ReportPayload:
    return ReportPayload(
        report_id="isrc-bug-test",
        kind="bug",
        created_at="2026-06-01T00:00:00Z",
        summary="Preview title",
        app_version="5.0.0",
        repository="owner/repo",
        sections=(ReportSection("Diagnostics", "clean body"),),
    )


def _service(tmp_path, result: ReportSubmissionResult | None = None) -> ReportingService:
    return ReportingService(
        data_root=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        app_version="5.0.0",
        repository="owner/repo",
        submitter=_FakeSubmitter(result or ReportSubmissionResult(True, "created")),
    )


def test_reporting_dialogs_collect_validate_copy_and_submit(monkeypatch) -> None:
    app = require_qapplication()
    warnings: list[str] = []
    monkeypatch.setattr(
        "isrc_manager.reporting.dialogs.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )

    prompt = CrashReportPromptDialog()
    manual = ManualBugReportDialog()
    manual._accept_if_valid()
    manual.summary_edit.setText("Bug title")
    manual.description_edit.setPlainText("Description")
    manual.steps_edit.setPlainText("Steps")
    manual.expected_edit.setPlainText("Expected")
    manual.actual_edit.setPlainText("Actual")
    manual.include_logs_checkbox.setChecked(False)
    manual.include_system_checkbox.setChecked(False)
    fields = manual.fields()

    preview = ReportPreviewDialog(_report(), "## Preview\nbody")
    preview._copy_report()
    preview._submit()

    assert prompt.windowTitle() == "Send Crash Report?"
    assert warnings == ["Enter a short summary before previewing."]
    assert fields == ManualBugReportFields(
        summary="Bug title",
        description="Description",
        steps_to_reproduce="Steps",
        expected_behavior="Expected",
        actual_behavior="Actual",
        include_logs=False,
        include_system_details=False,
    )
    assert app.clipboard().text() == "## Preview\nbody"
    assert preview.submit_requested is True
    assert preview.result() == QDialog.Accepted

    for dialog in (prompt, manual, preview):
        dialog.close()
        dialog.deleteLater()


def test_controller_initializes_reporting_and_handles_failure(tmp_path) -> None:
    app = SimpleNamespace(
        data_root=tmp_path / "app-data",
        logs_dir=tmp_path / "logs",
        _app_version_text=lambda: "5.0.0",
    )

    controller.initialize_reporting(app)

    assert isinstance(app.reporting_service, ReportingService)
    assert app._pending_crash_report_session is None

    logger = _FakeLogger()
    broken = SimpleNamespace(logger=logger)
    controller.initialize_reporting(broken)

    assert broken.reporting_service is None
    assert broken._pending_crash_report_session is None
    assert logger.messages == ["Crash reporting initialization failed."]


def test_manual_bug_report_uses_preview_submission_pipeline(monkeypatch, tmp_path) -> None:
    app = QWidget()
    app.reporting_service = _service(
        tmp_path,
        ReportSubmissionResult(True, "created", issue_url="https://github.test/1"),
    )
    app.logger = logging.getLogger("test.reporting")
    info_messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "isrc_manager.reporting.controller.QMessageBox.information",
        lambda _parent, title, message: info_messages.append((str(title), str(message))),
    )

    class _ManualDialog:
        def __init__(self, *, parent=None):
            self.parent = parent

        def exec(self):
            return QDialog.Accepted

        def fields(self):
            return ManualBugReportFields(
                summary="Cannot export",
                description="Description",
                steps_to_reproduce="Steps",
                expected_behavior="Expected",
                actual_behavior="Actual",
                include_logs=False,
                include_system_details=False,
            )

    class _PreviewDialog:
        submit_requested = True

        def __init__(self, report, preview, *, parent=None):
            self.report = report
            self.preview = preview
            self.parent = parent

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(controller, "ManualBugReportDialog", _ManualDialog)
    monkeypatch.setattr(controller, "ReportPreviewDialog", _PreviewDialog)

    controller.open_bug_report_dialog(app)

    assert info_messages == [("Report Submitted", "created\n\nIssue: https://github.test/1")]
    app.deleteLater()


def test_controller_handles_unavailable_cancel_and_submission_error_edges(
    monkeypatch, tmp_path
) -> None:
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "isrc_manager.reporting.controller.QMessageBox.warning",
        lambda _parent, title, message: warnings.append((str(title), str(message))),
    )
    monkeypatch.setattr(controller, "initialize_reporting", lambda app: None)

    unavailable = SimpleNamespace(reporting_service=None)
    controller.prompt_for_pending_crash_report(unavailable)
    controller.open_bug_report_dialog(unavailable)

    class _CancelManualDialog:
        def __init__(self, *, parent=None):
            self.parent = parent

        def exec(self):
            return QDialog.Rejected

    manual_cancel = QWidget()
    manual_cancel.reporting_service = _service(tmp_path / "cancel")
    monkeypatch.setattr(controller, "ManualBugReportDialog", _CancelManualDialog)
    controller.open_bug_report_dialog(manual_cancel)

    class _BrokenManualDialog:
        def __init__(self, *, parent=None):
            self.parent = parent

        def exec(self):
            return QDialog.Accepted

        def fields(self):
            return ManualBugReportFields(
                summary="Broken",
                description="Description",
                steps_to_reproduce="Steps",
                expected_behavior="Expected",
                actual_behavior="Actual",
            )

    broken = QWidget()
    broken.logger = _FakeLogger()
    broken.reporting_service = _service(tmp_path / "broken")
    broken.reporting_service.create_manual_report = lambda _fields: (_ for _ in ()).throw(
        RuntimeError("generation")
    )
    monkeypatch.setattr(controller, "ManualBugReportDialog", _BrokenManualDialog)
    controller.open_bug_report_dialog(broken)

    class _AcceptedPreview:
        submit_requested = True

        def __init__(self, report, preview, *, parent=None):
            self.report = report
            self.preview = preview
            self.parent = parent

        def exec(self):
            return QDialog.Accepted

    submit_app = QWidget()
    submit_app.logger = _FakeLogger()
    submit_service = _service(tmp_path / "submit")
    submit_service.submit_or_save = lambda _report: (_ for _ in ()).throw(RuntimeError("submit"))
    monkeypatch.setattr(controller, "ReportPreviewDialog", _AcceptedPreview)
    controller._preview_and_submit(submit_app, submit_service, _report())

    class _CancelPreview(_AcceptedPreview):
        submit_requested = False

    monkeypatch.setattr(controller, "ReportPreviewDialog", _CancelPreview)
    controller._preview_and_submit(submit_app, _service(tmp_path / "preview-cancel"), _report())

    captured_workflows: list[str] = []
    submit_app.reporting_service = _service(tmp_path / "workflow")
    submit_app.reporting_service.record_event = (
        lambda *, event, message, workflow: captured_workflows.append(workflow)
    )
    submit_app.main_workspace_stack = SimpleNamespace(
        currentWidget=lambda: (_ for _ in ()).throw(RuntimeError("stack"))
    )
    controller.record_app_event(submit_app, "event", "message")

    assert warnings[0] == (
        "Report a Bug",
        "Bug reporting is unavailable because the local reporting service could not start.",
    )
    assert "The bug report could not be generated. No information was sent." in warnings[1][1]
    assert warnings[-1] == (
        "Report Not Submitted",
        "Submission failed before the report left the app.",
    )
    assert broken.logger.messages == ["Bug report generation failed."]
    assert submit_app.logger.messages == ["Report submission failed."]
    assert captured_workflows == [""]
    for widget in (manual_cancel, broken, submit_app):
        widget.deleteLater()


def test_controller_crash_prompt_handles_cancel_generation_error_and_pending(
    monkeypatch, tmp_path
) -> None:
    warnings: list[tuple[str, str]] = []
    infos: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "isrc_manager.reporting.controller.QMessageBox.warning",
        lambda _parent, title, message: warnings.append((str(title), str(message))),
    )
    monkeypatch.setattr(
        "isrc_manager.reporting.controller.QMessageBox.information",
        lambda _parent, title, message: infos.append((str(title), str(message))),
    )

    class _CrashPrompt:
        result = QDialog.Accepted

        def __init__(self, *, parent=None):
            self.parent = parent

        def exec(self):
            return self.result

    class _PreviewDialog:
        submit_requested = True

        def __init__(self, report, preview, *, parent=None):
            self.report = report
            self.preview = preview

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(controller, "CrashReportPromptDialog", _CrashPrompt)
    monkeypatch.setattr(controller, "ReportPreviewDialog", _PreviewDialog)

    app = QWidget()
    app.logger = _FakeLogger()
    app.reporting_service = _service(tmp_path, ReportSubmissionResult(False, "offline"))
    app._pending_crash_report_session = CrashSession(
        session_id="session-1",
        started_at="2026-06-01T00:00:00Z",
        last_seen_at="2026-06-01T00:01:00Z",
        app_version="5.0.0",
        pid=123,
        last_event="editing",
    )

    original_create = app.reporting_service.create_crash_report
    app.reporting_service.create_crash_report = lambda _session: (_ for _ in ()).throw(
        RuntimeError("boom")
    )
    controller.prompt_for_pending_crash_report(app)
    app.reporting_service.create_crash_report = original_create
    controller.prompt_for_pending_crash_report(app)
    controller._show_submission_result(app, ReportSubmissionResult(False, "rejected"))

    _CrashPrompt.result = QDialog.Rejected
    controller.prompt_for_pending_crash_report(app)

    assert warnings == [
        ("Crash Report", "The crash report could not be generated. No information was sent."),
        ("Report Not Submitted", "rejected"),
    ]
    assert any(title == "Report Saved Locally" for title, _message in infos)
    assert app.logger.messages == ["Crash report generation failed."]
    app.deleteLater()


def test_controller_records_events_and_active_workflow(tmp_path) -> None:
    service = _service(tmp_path)
    service.start_session()
    workflow_widget = SimpleNamespace(objectName=lambda: "royaltiesPanel", windowTitle=lambda: "")
    app = SimpleNamespace(
        reporting_service=service,
        main_workspace_stack=SimpleNamespace(currentWidget=lambda: workflow_widget),
    )

    controller.record_app_event(app, "view-opened", "Opened royalties")
    controller.mark_clean_shutdown(app)

    marker = service.session_marker.marker_path.read_text(encoding="utf-8")
    assert "view-opened" in marker
    assert "royaltiesPanel" in marker
    assert "clean_shutdown" in marker

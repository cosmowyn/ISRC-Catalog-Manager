"""Crash and manual bug report orchestration."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from .collectors import collect_recent_logs, collect_system_context, collect_traceback_files
from .config import DEFAULT_REPOSITORY, load_reporting_configuration
from .crash_detection import CrashSession, SessionMarkerStore
from .github import BackendProxySubmitter, ReportSubmissionResult
from .models import ManualBugReportFields, ReportPayload, ReportSection, utc_timestamp
from .rate_limit import LocalReportRateLimiter
from .sanitizer import ReportSanitizer
from .storage import PendingReportStore


class ReportingService:
    """Single reporting pipeline used by crash and manual bug workflows."""

    def __init__(
        self,
        *,
        data_root: Path,
        logs_dir: Path,
        app_version: str,
        repository: str = DEFAULT_REPOSITORY,
        proxy_url: str | None = None,
        logger: logging.Logger | None = None,
        sanitizer: ReportSanitizer | None = None,
        submitter: BackendProxySubmitter | None = None,
        rate_limiter: LocalReportRateLimiter | None = None,
    ):
        self.data_root = Path(data_root)
        self.logs_dir = Path(logs_dir)
        self.app_version = app_version
        self.repository = repository
        self.reporting_dir = self.data_root / "reports"
        self.runtime_dir = self.reporting_dir / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger or logging.getLogger("ISRCManager.reporting")
        self.sanitizer = sanitizer or ReportSanitizer()
        self.session_marker = SessionMarkerStore(self.runtime_dir / "session.json")
        self.pending_store = PendingReportStore(self.reporting_dir / "pending")
        self.rate_limiter = rate_limiter or LocalReportRateLimiter(
            self.reporting_dir / "rate_limit.json"
        )
        self.submitter = submitter or BackendProxySubmitter(proxy_url)

    @classmethod
    def from_environment(
        cls,
        *,
        data_root: Path,
        logs_dir: Path,
        app_version: str,
        logger: logging.Logger | None = None,
    ) -> ReportingService:
        config = load_reporting_configuration()
        return cls(
            data_root=data_root,
            logs_dir=logs_dir,
            app_version=app_version,
            repository=config.repository,
            proxy_url=config.proxy_url,
            logger=logger,
        )

    def start_session(self) -> CrashSession | None:
        try:
            return self.session_marker.start_session(app_version=self.app_version)
        except Exception:
            self.logger.exception("Reporter failed to start the session marker.")
            return None

    def mark_clean_shutdown(self) -> None:
        try:
            self.session_marker.mark_clean_shutdown()
        except Exception:
            self.logger.exception("Reporter failed to mark clean shutdown.")

    def record_event(self, *, event: str, message: str = "", workflow: str = "") -> None:
        try:
            self.session_marker.record_event(event=event, message=message, workflow=workflow)
        except Exception:
            self.logger.debug("Reporter could not update the session marker.", exc_info=True)

    def create_crash_report(self, crash_session: CrashSession) -> ReportPayload:
        system_context = collect_system_context(
            app_version=self.app_version,
            sanitizer=self.sanitizer,
        )
        sections = [
            ReportSection(
                "Previous Session",
                self.sanitizer.sanitize_text(
                    "\n".join(
                        (
                            f"session_id={crash_session.session_id}",
                            f"started_at={crash_session.started_at}",
                            f"last_seen_at={crash_session.last_seen_at}",
                            f"previous_app_version={crash_session.app_version}",
                            f"pid={crash_session.pid}",
                            f"last_event={crash_session.last_event}",
                            f"last_message={crash_session.last_message}",
                            f"last_workflow={crash_session.last_workflow}",
                        )
                    )
                ),
            ),
            ReportSection("System Context", _format_mapping(system_context)),
        ]
        sections.extend(self._diagnostic_file_sections(include_logs=True))
        summary = (
            f"Unexpected termination after {crash_session.last_event}"
            if crash_session.last_event
            else "Unexpected application termination"
        )
        return ReportPayload(
            report_id=_report_id("crash"),
            kind="crash",
            created_at=utc_timestamp(),
            summary=self.sanitizer.sanitize_text(summary, max_chars=220),
            app_version=self.app_version,
            repository=self.repository,
            sections=tuple(sections),
            metadata={
                "session_id": crash_session.session_id,
                "last_seen_at": crash_session.last_seen_at,
            },
            labels=("bug", "crash-report", "user-report"),
        )

    def create_manual_report(self, fields: ManualBugReportFields) -> ReportPayload:
        sections = [
            ReportSection(
                "User Description",
                self.sanitizer.sanitize_text(fields.description, max_chars=12_000),
            ),
            ReportSection(
                "Steps to Reproduce",
                self.sanitizer.sanitize_text(fields.steps_to_reproduce, max_chars=12_000),
            ),
            ReportSection(
                "Expected Behaviour",
                self.sanitizer.sanitize_text(fields.expected_behavior, max_chars=8_000),
            ),
            ReportSection(
                "Actual Behaviour",
                self.sanitizer.sanitize_text(fields.actual_behavior, max_chars=8_000),
            ),
        ]
        if fields.include_system_details:
            sections.append(
                ReportSection(
                    "System Context",
                    _format_mapping(
                        collect_system_context(
                            app_version=self.app_version,
                            sanitizer=self.sanitizer,
                        )
                    ),
                )
            )
        if fields.include_logs:
            sections.extend(self._diagnostic_file_sections(include_logs=True))
        return ReportPayload(
            report_id=_report_id("bug"),
            kind="bug",
            created_at=utc_timestamp(),
            summary=self.sanitizer.sanitize_text(fields.summary, max_chars=220),
            app_version=self.app_version,
            repository=self.repository,
            sections=tuple(sections),
            labels=("bug", "user-report"),
        )

    def preview_text(self, report: ReportPayload) -> str:
        sanitized_report = self.sanitize_report(report)
        return sanitized_report.to_markdown()

    def submit_or_save(self, report: ReportPayload) -> ReportSubmissionResult:
        sanitized_report = self.sanitize_report(report)
        preview = sanitized_report.to_markdown()
        if len(preview.encode("utf-8")) > 180_000:
            return ReportSubmissionResult(False, "The report is too large to submit safely.")
        decision = self.rate_limiter.check(deduplication_key=sanitized_report.deduplication_key)
        if not decision.allowed:
            return ReportSubmissionResult(False, decision.reason)

        result = self.submitter.submit(sanitized_report)
        if result.success:
            self.rate_limiter.record_submission(
                deduplication_key=sanitized_report.deduplication_key
            )
            self.logger.info("Submitted report %s", sanitized_report.report_id)
            return result

        self.rate_limiter.record_failure()
        reference = self.pending_store.save(sanitized_report)
        self.logger.info("Saved pending report %s", sanitized_report.report_id)
        return ReportSubmissionResult(
            False,
            f"{result.message} Pending report saved locally.",
            pending_path=str(reference.markdown_path),
            status_code=result.status_code,
        )

    def sanitize_report(self, report: ReportPayload) -> ReportPayload:
        sections = tuple(
            ReportSection(
                title=self.sanitizer.sanitize_text(section.title, max_chars=220),
                body=self.sanitizer.sanitize_text(section.body),
                kind=section.kind,
                collapsed=section.collapsed,
            )
            for section in report.sections
        )
        return ReportPayload(
            report_id=self.sanitizer.sanitize_text(report.report_id, max_chars=80),
            kind="crash" if report.kind == "crash" else "bug",
            created_at=self.sanitizer.sanitize_text(report.created_at, max_chars=80),
            summary=self.sanitizer.sanitize_text(report.summary, max_chars=220),
            app_version=self.sanitizer.sanitize_text(report.app_version, max_chars=80),
            repository=self.repository,
            sections=sections,
            metadata=self.sanitizer.sanitize_mapping(report.metadata, max_chars=500),
            labels=report.labels,
            schema_version=report.schema_version,
            sanitized=True,
        )

    def _diagnostic_file_sections(self, *, include_logs: bool) -> list[ReportSection]:
        sections: list[ReportSection] = []
        if include_logs:
            for file_name, body in collect_recent_logs(self.logs_dir, sanitizer=self.sanitizer):
                sections.append(ReportSection(f"Sanitised Log: {file_name}", body))
        tracebacks = collect_traceback_files(
            [self.logs_dir, self.reporting_dir, self.data_root],
            sanitizer=self.sanitizer,
        )
        for file_name, body in tracebacks:
            sections.append(ReportSection(f"Sanitised Exception File: {file_name}", body))
        if not sections:
            sections.append(
                ReportSection(
                    "Diagnostics",
                    "No recent readable log, traceback, exception, or faulthandler files were found.",
                )
            )
        return sections


def _format_mapping(values: dict[str, str]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in sorted(values.items()))


def _report_id(kind: str) -> str:
    digest = hashlib.sha256(f"{kind}:{utc_timestamp()}:{os.getpid()}:{os.urandom(8)!r}".encode())
    return f"isrc-{kind}-{digest.hexdigest()[:16]}"

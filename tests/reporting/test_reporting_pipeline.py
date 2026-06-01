import json
import urllib.error
from pathlib import Path

import pytest

from isrc_manager.reporting import collectors
from isrc_manager.reporting.config import ReportingConfiguration, load_reporting_configuration
from isrc_manager.reporting.crash_detection import SessionMarkerStore, _record_from_mapping
from isrc_manager.reporting.github import BackendProxySubmitter, ReportSubmissionResult
from isrc_manager.reporting.models import ManualBugReportFields, ReportPayload, ReportSection
from isrc_manager.reporting.rate_limit import LocalReportRateLimiter
from isrc_manager.reporting.sanitizer import ReportSanitizer
from isrc_manager.reporting.service import ReportingService


class FakeSubmitter:
    def __init__(self, result: ReportSubmissionResult):
        self.result = result
        self.submitted = []

    def submit(self, report):
        self.submitted.append(report)
        return self.result


def _report_payload() -> ReportPayload:
    return ReportPayload(
        report_id="isrc-test",
        kind="bug",
        created_at="2026-06-01T00:00:00Z",
        summary="Bug title",
        app_version="5.0.0",
        repository="owner/repo",
        sections=(ReportSection("Details", "Body"),),
    )


def test_reporting_configuration_uses_environment_before_bundled_config(tmp_path) -> None:
    resources = tmp_path / "bundle"
    config_dir = resources / "resources"
    config_dir.mkdir(parents=True)
    (config_dir / "reporting.json").write_text(
        json.dumps(
            {
                "proxy_url": "https://bundled.example.test/report",
                "repository": "bundled/repo",
            }
        ),
        encoding="utf-8",
    )

    bundled = load_reporting_configuration(environ={}, resource_root=resources)
    overridden = load_reporting_configuration(
        environ={
            "ISRC_REPORT_PROXY_URL": "https://env.example.test/report",
            "ISRC_REPORT_REPOSITORY": "env/repo",
        },
        resource_root=resources,
    )
    disabled = load_reporting_configuration(
        environ={"ISRC_REPORT_PROXY_URL": ""},
        resource_root=resources,
    )

    assert bundled == ReportingConfiguration(
        repository="bundled/repo",
        proxy_url="https://bundled.example.test/report",
        source="bundled:resources/reporting.json",
    )
    assert overridden == ReportingConfiguration(
        repository="env/repo",
        proxy_url="https://env.example.test/report",
        source="environment",
    )
    assert disabled.proxy_url == ""
    assert disabled.source == "environment"


def test_reporting_service_from_environment_uses_bundled_public_proxy_config(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "isrc_manager.reporting.service.load_reporting_configuration",
        lambda: ReportingConfiguration(
            repository="owner/repo",
            proxy_url="https://reports.example.test/submit",
            source="bundled",
        ),
    )

    service = ReportingService.from_environment(
        data_root=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        app_version="5.0.0",
    )

    assert service.repository == "owner/repo"
    assert service.submitter.endpoint_url == "https://reports.example.test/submit"


def test_manual_report_is_sanitised_before_preview_and_pending_storage(tmp_path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "app.log").write_text(
        "ERROR user=mervyn@example.com access_token=secret-token path=/Users/cosmowyn/private\n",
        encoding="utf-8",
    )
    service = ReportingService(
        data_root=tmp_path / "data",
        logs_dir=logs_dir,
        app_version="1.2.3",
        repository="owner/repo",
        submitter=FakeSubmitter(ReportSubmissionResult(False, "offline")),
    )

    report = service.create_manual_report(
        ManualBugReportFields(
            summary="Cannot export",
            description="Export fails for /Users/cosmowyn/Music/song.wav",
            steps_to_reproduce="Open catalog, export, observe legal@example.com",
            expected_behavior="File exports",
            actual_behavior="Traceback with password=hunter2",
        )
    )
    preview = service.preview_text(report)

    assert "mervyn@example.com" not in preview
    assert "legal@example.com" not in preview
    assert "/Users/cosmowyn" not in preview
    assert "secret-token" not in preview
    assert "hunter2" not in preview
    assert "Sanitised Log: app.log" in preview

    result = service.submit_or_save(report)

    assert not result.success
    assert result.pending_path
    pending_markdown = (tmp_path / "data" / "reports" / "pending").glob("*.md")
    saved_text = next(pending_markdown).read_text(encoding="utf-8")
    assert "secret-token" not in saved_text
    assert "<REDACTED_EMAIL_" in saved_text


def test_successful_submission_uses_restricted_issue_payload(tmp_path) -> None:
    submitter = FakeSubmitter(
        ReportSubmissionResult(True, "created", issue_url="https://example/i")
    )
    service = ReportingService(
        data_root=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        app_version="1.2.3",
        repository="owner/repo",
        submitter=submitter,
    )
    report = service.create_manual_report(
        ManualBugReportFields(
            summary="Bug title",
            description="Description",
            steps_to_reproduce="Step",
            expected_behavior="Expected",
            actual_behavior="Actual",
            include_logs=False,
            include_system_details=False,
        )
    )

    result = service.submit_or_save(report)
    payload = submitter.submitted[0].to_issue_payload()

    assert result.success
    assert payload["title"] == "[Bug Report] Bug title"
    assert payload["repository"] == "owner/repo"
    assert payload["labels"] == ["bug", "user-report"]
    assert "Privacy Notice" in payload["body"]


def test_report_payload_markdown_title_and_crash_marker_edges(tmp_path: Path) -> None:
    long_report = ReportPayload(
        report_id="isrc-long",
        kind="crash",
        created_at="2026-06-01T00:00:00Z",
        summary="Very long summary " * 20,
        app_version="5.0.0",
        repository="owner/repo",
        sections=(
            ReportSection("Markdown", "Line one\r\nLine two\x00", kind="markdown"),
            ReportSection("Code", "```secret```"),
        ),
        metadata={"session_id": "session-1", "blank": ""},
        labels=("bug", "user-report", "invalid"),
        sanitized=False,
    )

    markdown = long_report.to_markdown()

    assert long_report.issue_title.startswith("[Crash Report] Very long summary")
    assert long_report.issue_title.endswith("...")
    assert len(long_report.issue_title) <= 120
    assert long_report.safe_labels == ("bug", "user-report")
    assert "Line one\nLine two" in markdown
    assert "\x00" not in markdown
    assert "` ` `secret` ` `" in markdown
    assert "blank" not in markdown

    store = SessionMarkerStore(tmp_path / "session.json")
    store.mark_clean_shutdown()
    store.marker_path.write_text("[]", encoding="utf-8")
    assert store._load_record() is None
    assert _record_from_mapping({"session_id": "missing required fields"}) is None


def test_submission_boundary_sanitises_direct_report_payloads(tmp_path) -> None:
    submitter = FakeSubmitter(ReportSubmissionResult(True, "created"))
    service = ReportingService(
        data_root=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        app_version="1.2.3",
        repository="owner/repo",
        submitter=submitter,
    )
    report = ReportPayload(
        report_id="isrc-test",
        kind="bug",
        created_at="2026-06-01T00:00:00Z",
        summary="Leak from legal@example.com",
        app_version="1.2.3",
        repository="owner/repo",
        sections=(
            ReportSection(
                "Raw diagnostics",
                "password=hunter2 access_token=secret-token /Users/cosmowyn/private",
            ),
        ),
    )

    result = service.submit_or_save(report)
    submitted_body = submitter.submitted[0].to_markdown()

    assert result.success
    assert "legal@example.com" not in submitted_body
    assert "hunter2" not in submitted_body
    assert "secret-token" not in submitted_body
    assert "/Users/cosmowyn" not in submitted_body
    assert "<REDACTED_EMAIL_1>" in submitted_body


def test_rate_limiter_blocks_duplicates_hourly_limits_and_failure_cooldown(tmp_path) -> None:
    limiter = LocalReportRateLimiter(
        tmp_path / "rate.json",
        max_per_hour=2,
        max_per_day=3,
        failure_cooldown_seconds=600,
        failure_threshold=2,
    )

    assert limiter.check(deduplication_key="a", now=1_000).allowed
    limiter.record_submission(deduplication_key="a", now=1_000)
    assert not limiter.check(deduplication_key="a", now=1_100).allowed

    assert limiter.check(deduplication_key="b", now=1_100).allowed
    limiter.record_submission(deduplication_key="b", now=1_100)
    assert not limiter.check(deduplication_key="c", now=1_200).allowed

    limiter.record_failure(now=5_000)
    limiter.record_failure(now=5_100)
    decision = limiter.check(deduplication_key="z", now=5_101)
    assert not decision.allowed
    assert "cooldown" in decision.reason.lower()


def test_collectors_sanitise_context_logs_tracebacks_and_file_errors(
    monkeypatch, tmp_path: Path
) -> None:
    sanitizer = ReportSanitizer()
    monkeypatch.setenv("ISRC_BUILD_COMMIT", "abc123")
    context = collectors.collect_system_context(app_version="5.0.0", sanitizer=sanitizer)
    assert context["application_version"] == "5.0.0"
    assert context["build_commit"] == "abc123"
    assert context["python_version"]

    assert collectors.collect_recent_logs(tmp_path / "missing", sanitizer=sanitizer) == []
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "old.log").write_text("older", encoding="utf-8")
    latest = logs_dir / "latest.log"
    latest.write_text(
        "prefix " + ("x" * 80) + " user=person@example.test access_token=secret",
        encoding="utf-8",
    )
    (logs_dir / "ignore.bin").write_bytes(b"binary")
    logs = collectors.collect_recent_logs(
        logs_dir,
        sanitizer=sanitizer,
        max_files=1,
        max_bytes_per_file=32,
    )
    assert logs[0][0] == "latest.log"
    assert logs[0][1].startswith("[tail of diagnostic file]")
    assert "secret" not in logs[0][1]

    traceback_file = tmp_path / "traceback-report.txt"
    traceback_file.write_text("Traceback legal@example.test", encoding="utf-8")
    assert collectors.collect_traceback_files([tmp_path / "missing"], sanitizer=sanitizer) == []
    traces = collectors.collect_traceback_files([tmp_path], sanitizer=sanitizer)
    assert traces == [("traceback-report.txt", "Traceback <REDACTED_EMAIL_1>")]

    assert "Unable to read" in collectors._read_tail(
        tmp_path / "does-not-exist.log",
        max_bytes=10,
        sanitizer=sanitizer,
    )

    original_iterdir = Path.iterdir

    def _raise_for_logs(path: Path):
        if path == logs_dir:
            raise OSError("blocked")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", _raise_for_logs)
    assert collectors.collect_recent_logs(logs_dir, sanitizer=sanitizer) == []
    assert collectors.collect_traceback_files([logs_dir], sanitizer=sanitizer) == []

    monkeypatch.setattr(Path, "stat", lambda _path: (_ for _ in ()).throw(OSError("blocked")))
    monkeypatch.setattr(Path, "is_file", lambda _path: (_ for _ in ()).throw(OSError("blocked")))
    assert collectors._safe_mtime(latest) == 0.0
    assert collectors._safe_is_file(latest) is False


def test_reporting_sanitizer_and_rate_limit_edge_paths(monkeypatch, tmp_path: Path) -> None:
    sanitizer = ReportSanitizer()
    assert sanitizer.sanitize_text(None) == ""
    assert sanitizer.sanitize_text(b"binary") == "<BINARY_DATA_REMOVED>"
    assert "<REDACTED_EMAIL_1>" in sanitizer.sanitize_text("a@example.test")
    assert "[truncated" in ReportSanitizer(max_chars=12).sanitize_text("x" * 40)
    monkeypatch.setattr("isrc_manager.reporting.sanitizer.getpass.getuser", lambda: "root")
    assert sanitizer.sanitize_text("root") == "root"
    monkeypatch.setattr(
        "isrc_manager.reporting.sanitizer.getpass.getuser",
        lambda: (_ for _ in ()).throw(RuntimeError("no user")),
    )
    assert sanitizer.sanitize_text("local-user") == "local-user"
    assert sanitizer.sanitize_text("date 2026-06-01 phone 12345678901234567890").endswith(
        "12345678901234567890"
    )
    mapped = sanitizer.sanitize_mapping({"empty": "", "email": "a@example.test"})
    assert mapped == {"empty": "", "email": "<REDACTED_EMAIL_1>"}

    limiter = LocalReportRateLimiter(
        tmp_path / "rate.json",
        max_per_hour=10,
        max_per_day=1,
        failure_cooldown_seconds=60,
        failure_threshold=2,
    )
    limiter.record_submission(deduplication_key="a", now=1)
    assert not limiter.check(deduplication_key="b", now=2).allowed
    assert limiter.check(deduplication_key="b", now=90_000).allowed
    limiter.state_path.write_text("not json", encoding="utf-8")
    assert limiter.check(deduplication_key="c", now=90_001).allowed
    limiter.state_path.write_text("[]", encoding="utf-8")
    assert limiter.check(deduplication_key="d", now=90_002).allowed
    assert limiter._recent("bad", now=10, window=10) == []
    assert limiter._recent(["bad", 9], now=10, window=10) == [9.0]


def test_reporting_service_handles_marker_rate_limit_and_large_payload_edges(
    tmp_path: Path,
) -> None:
    service = ReportingService(
        data_root=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        app_version="5.0.0",
        repository="owner/repo",
        submitter=FakeSubmitter(ReportSubmissionResult(True, "created")),
    )

    service.session_marker.start_session = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError("x")
    )
    service.session_marker.mark_clean_shutdown = lambda: (_ for _ in ()).throw(RuntimeError("x"))
    service.session_marker.record_event = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("x"))
    assert service.start_session() is None
    service.mark_clean_shutdown()
    service.record_event(event="ui", message="message", workflow="workflow")

    large_report = ReportPayload(
        report_id="isrc-large",
        kind="bug",
        created_at="2026-06-01T00:00:00Z",
        summary="Large",
        app_version="5.0.0",
        repository="owner/repo",
        sections=(
            ReportSection("Big 1", "x" * 181_000),
            ReportSection("Big 2", "x" * 181_000),
            ReportSection("Big 3", "x" * 181_000),
        ),
    )
    result = service.submit_or_save(large_report)
    assert not result.success
    assert "too large" in result.message

    class _BlockedLimiter:
        def check(self, *, deduplication_key):
            return type("Decision", (), {"allowed": False, "reason": "blocked"})()

    service.rate_limiter = _BlockedLimiter()
    result = service.submit_or_save(_report_payload())
    assert not result.success
    assert result.message == "blocked"

    traces_dir = tmp_path / "logs"
    traces_dir.mkdir(exist_ok=True)
    (traces_dir / "exception.txt").write_text("Traceback", encoding="utf-8")
    sections = service._diagnostic_file_sections(include_logs=False)
    assert sections[0].title == "Sanitised Exception File: exception.txt"


def test_proxy_submitter_requires_secure_endpoint() -> None:
    with pytest.raises(ValueError):
        BackendProxySubmitter("http://example.com/report")

    assert BackendProxySubmitter("http://localhost:8080/report").endpoint_url
    result = BackendProxySubmitter("").submit(_report_payload())
    assert not result.success
    assert "No secure report proxy" in result.message
    assert "ISRC_REPORT_PROXY_URL" in result.message


def test_proxy_submitter_posts_structured_json_and_parses_response(monkeypatch) -> None:
    requests = []

    class _Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return json.dumps(
                {
                    "issue_url": "https://github.test/owner/repo/issues/1",
                    "message": "Issue created",
                }
            ).encode("utf-8")

    def _fake_urlopen(request, *, timeout):
        requests.append((request, timeout))
        return _Response()

    monkeypatch.setattr("isrc_manager.reporting.github.urllib.request.urlopen", _fake_urlopen)

    result = BackendProxySubmitter("https://reports.example.test/submit").submit(_report_payload())

    request, timeout = requests[0]
    submitted = json.loads(request.data.decode("utf-8"))
    assert result.success
    assert result.message == "Issue created"
    assert result.issue_url.endswith("/issues/1")
    assert result.status_code == 202
    assert timeout == 15
    assert submitted["repository"] == "owner/repo"
    assert request.headers["Content-type"] == "application/json"
    assert "5.0.0" in request.headers["User-agent"]


def test_proxy_submitter_handles_response_and_network_failures(monkeypatch) -> None:
    class _EmptyResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return b"not-json"

    monkeypatch.setattr(
        "isrc_manager.reporting.github.urllib.request.urlopen",
        lambda *_args, **_kwargs: _EmptyResponse(),
    )
    result = BackendProxySubmitter("https://reports.example.test/submit").submit(_report_payload())
    assert result.success
    assert result.message == "Report submitted."
    assert result.issue_url == ""

    class _NoBodyResponse(_EmptyResponse):
        def read(self, _size):
            return b""

    monkeypatch.setattr(
        "isrc_manager.reporting.github.urllib.request.urlopen",
        lambda *_args, **_kwargs: _NoBodyResponse(),
    )
    result = BackendProxySubmitter("https://reports.example.test/submit").submit(_report_payload())
    assert result.success
    assert result.message == "Report submitted."

    def _raise_http(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://reports.example.test/submit",
            429,
            "Too Many Requests",
            {},
            None,
        )

    monkeypatch.setattr("isrc_manager.reporting.github.urllib.request.urlopen", _raise_http)
    result = BackendProxySubmitter("https://reports.example.test/submit").submit(_report_payload())
    assert not result.success
    assert result.status_code == 429
    assert "HTTP 429" in result.message

    monkeypatch.setattr(
        "isrc_manager.reporting.github.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    result = BackendProxySubmitter("https://reports.example.test/submit").submit(_report_payload())
    assert not result.success
    assert "offline" in result.message


def test_proxy_submitter_rejects_oversized_payload_without_network(tmp_path) -> None:
    service = ReportingService(
        data_root=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        app_version="1.2.3",
        repository="owner/repo",
        submitter=BackendProxySubmitter("http://localhost/report", max_payload_bytes=10),
    )
    report = service.create_manual_report(
        ManualBugReportFields(
            summary="Bug",
            description="Large body",
            steps_to_reproduce="Step",
            expected_behavior="Expected",
            actual_behavior="Actual",
            include_logs=False,
            include_system_details=False,
        )
    )

    result = service.submitter.submit(report)

    assert not result.success
    assert "payload limit" in result.message

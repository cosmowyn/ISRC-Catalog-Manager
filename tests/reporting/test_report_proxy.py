import io
import json
import urllib.error

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from isrc_manager.reporting.proxy import (
    GitHubAppIssueClient,
    InMemoryProxyRateLimiter,
    ProxyValidationError,
    ReportProxyApp,
    ReportProxyConfig,
    _github_json_request,
    _int_env,
    _parse_github_expiration,
    _read_limited_body,
    create_wsgi_app_from_environment,
    github_app_jwt,
    validate_proxy_payload,
)
from isrc_manager.reporting.sanitizer import ReportSanitizer


class FakeIssueClient:
    def __init__(self):
        self.created = []

    def create_issue(self, *, repository, issue_payload):
        self.created.append((repository, issue_payload))
        return {"html_url": "https://github.com/owner/repo/issues/1"}


def _valid_payload(**overrides):
    payload = {
        "schema_version": "1.0",
        "repository": "owner/repo",
        "title": "[Bug Report] Export failure",
        "body": "Report body with legal@example.com and password=hunter2",
        "labels": ["bug", "user-report"],
        "report_id": "isrc-bug-1234567890abcdef",
        "kind": "bug",
        "app_version": "1.2.3",
    }
    payload.update(overrides)
    return payload


def test_proxy_payload_validation_sanitises_and_fixes_labels() -> None:
    config = ReportProxyConfig(repository="owner/repo")

    issue = validate_proxy_payload(
        _valid_payload(labels=["bug", "user-report"]),
        config=config,
        sanitizer=ReportSanitizer(),
    )

    assert issue["labels"] == ["bug", "user-report"]
    assert "legal@example.com" not in issue["body"]
    assert "hunter2" not in issue["body"]
    assert "<REDACTED_EMAIL_1>" in issue["body"]


def test_proxy_payload_validation_rejects_wrong_repo_and_unknown_labels() -> None:
    config = ReportProxyConfig(repository="owner/repo")

    with pytest.raises(ProxyValidationError):
        validate_proxy_payload(
            _valid_payload(repository="other/repo"),
            config=config,
            sanitizer=ReportSanitizer(),
        )

    with pytest.raises(ProxyValidationError):
        validate_proxy_payload(
            _valid_payload(labels=["bug", "admin"]),
            config=config,
            sanitizer=ReportSanitizer(),
        )


def test_proxy_payload_validation_rejects_schema_kind_version_prefix_and_body() -> None:
    config = ReportProxyConfig(repository="owner/repo", allowed_versions=("5.0.0",))
    sanitizer = ReportSanitizer()

    invalid_payloads = [
        {"schema_version": "2.0"},
        {"kind": "feature"},
        {"app_version": "4.9.9"},
        {"title": "Wrong prefix"},
        {"body": ""},
    ]

    for override in invalid_payloads:
        with pytest.raises(ProxyValidationError):
            validate_proxy_payload(_valid_payload(**override), config=config, sanitizer=sanitizer)

    with pytest.raises(ProxyValidationError):
        validate_proxy_payload([], config=config, sanitizer=sanitizer)

    with pytest.raises(ProxyValidationError, match="exceeds"):
        validate_proxy_payload(
            _valid_payload(body="x" * 64),
            config=ReportProxyConfig(repository="owner/repo", max_payload_bytes=10),
            sanitizer=sanitizer,
        )


def test_crash_proxy_payload_receives_fixed_crash_labels() -> None:
    config = ReportProxyConfig(repository="owner/repo")

    issue = validate_proxy_payload(
        _valid_payload(
            kind="crash",
            title="[Crash Report] Unexpected termination",
            labels=["bug", "user-report", "crash-report"],
        ),
        config=config,
        sanitizer=ReportSanitizer(),
    )

    assert issue["labels"] == ["bug", "user-report", "crash-report"]


def test_wsgi_proxy_creates_issue_and_rate_limits() -> None:
    client = FakeIssueClient()
    app = ReportProxyApp(
        config=ReportProxyConfig(repository="owner/repo", per_ip_hour_limit=1),
        issue_client=client,
        rate_limiter=InMemoryProxyRateLimiter(max_per_hour=1),
    )
    body = json.dumps(_valid_payload()).encode("utf-8")

    statuses = []
    response = app(_environ(body), lambda status, _headers: statuses.append(status))

    assert statuses == ["201 Created"]
    assert json.loads(b"".join(response))["issue_url"].endswith("/issues/1")
    assert client.created[0][0] == "owner/repo"

    statuses.clear()
    response = app(_environ(body), lambda status, _headers: statuses.append(status))

    assert statuses == ["429 Too Many Requests"]
    assert "rate limit" in json.loads(b"".join(response))["error"].lower()

    limiter = InMemoryProxyRateLimiter(max_per_hour=1)
    assert limiter.allow("client", now=0)
    assert limiter.allow("client", now=3601)


def test_wsgi_proxy_rejects_method_bad_json_and_upstream_failure() -> None:
    failing_client = FakeIssueClient()
    app = ReportProxyApp(
        config=ReportProxyConfig(repository="owner/repo"),
        issue_client=failing_client,
        rate_limiter=InMemoryProxyRateLimiter(max_per_hour=10),
    )

    statuses = []
    response = app(
        {**_environ(b"{}"), "REQUEST_METHOD": "GET"},
        lambda status, _headers: statuses.append(status),
    )
    assert statuses == ["405 Method Not Allowed"]
    assert "post" in json.loads(b"".join(response))["error"].lower()

    statuses.clear()
    response = app(
        _environ(b"{not-json"),
        lambda status, _headers: statuses.append(status),
    )
    assert statuses == ["400 Bad Request"]
    assert "valid json" in json.loads(b"".join(response))["error"].lower()

    class _BrokenClient:
        def create_issue(self, *, repository, issue_payload):
            raise RuntimeError("github unavailable")

    statuses.clear()
    response = ReportProxyApp(
        config=ReportProxyConfig(repository="owner/repo"),
        issue_client=_BrokenClient(),
        rate_limiter=InMemoryProxyRateLimiter(max_per_hour=10),
    )(
        _environ(json.dumps(_valid_payload()).encode("utf-8")),
        lambda status, _h: statuses.append(status),
    )
    assert statuses == ["502 Bad Gateway"]
    assert "could not create" in json.loads(b"".join(response))["error"].lower()


def test_proxy_app_can_be_created_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_APP_ID", "123")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "456")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "not-used-until-request")
    monkeypatch.setenv("ISRC_REPORT_PROXY_REPOSITORY", "owner/repo")
    monkeypatch.setenv("ISRC_REPORT_PROXY_ALLOWED_VERSIONS", "1.2.3,1.2.4")

    app = create_wsgi_app_from_environment()

    assert isinstance(app, ReportProxyApp)
    assert app.config.repository == "owner/repo"
    assert app.config.allowed_versions == ("1.2.3", "1.2.4")


def test_proxy_environment_reads_private_key_file_and_integer_defaults(
    monkeypatch, tmp_path
) -> None:
    key_path = tmp_path / "app-key.pem"
    key_path.write_text("not-used-until-request", encoding="utf-8")
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_FILE", str(key_path))
    monkeypatch.setenv("GITHUB_APP_ID", "123")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "456")
    monkeypatch.setenv("ISRC_REPORT_PROXY_REPOSITORY", "owner/repo")
    monkeypatch.setenv("ISRC_REPORT_PROXY_MAX_BYTES", "bad-int")

    app = create_wsgi_app_from_environment()

    assert isinstance(app, ReportProxyApp)
    assert app.config.max_payload_bytes == 180_000
    assert _int_env("ISRC_REPORT_PROXY_MAX_BYTES", 99) == 99


def test_proxy_environment_requires_github_app_credentials(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_INSTALLATION_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY_FILE", raising=False)

    with pytest.raises(RuntimeError):
        create_wsgi_app_from_environment()


def test_read_limited_body_validates_size_length_and_stream() -> None:
    with pytest.raises(ProxyValidationError):
        _read_limited_body({"CONTENT_LENGTH": "x"}, limit=10)
    with pytest.raises(ProxyValidationError):
        _read_limited_body({"CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO()}, limit=10)
    with pytest.raises(ProxyValidationError) as oversized:
        _read_limited_body({"CONTENT_LENGTH": "11", "wsgi.input": io.BytesIO(b"x" * 11)}, limit=10)
    with pytest.raises(ProxyValidationError):
        _read_limited_body({"CONTENT_LENGTH": "1", "wsgi.input": object()}, limit=10)

    assert oversized.value.status == "413 Payload Too Large"
    assert _read_limited_body(_environ(b"ok"), limit=10) == b"ok"


def test_github_app_jwt_client_token_cache_and_json_request(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    jwt_token = github_app_jwt("123", pem, now=1_700_000_000)
    assert jwt_token.count(".") == 2

    calls: list[tuple[str, dict[str, object]]] = []

    def _fake_request(method, url, *, token, payload):
        calls.append((url, payload))
        if url.endswith("/access_tokens"):
            return {"token": "installation-token", "expires_at": "2099-01-01T00:00:00Z"}
        return {"html_url": "https://github.test/owner/repo/issues/7"}

    monkeypatch.setattr("isrc_manager.reporting.proxy._github_json_request", _fake_request)
    client = GitHubAppIssueClient(
        app_id="123",
        installation_id="456",
        private_key_pem=pem,
        api_base="https://api.github.test",
    )

    first = client.create_issue(repository="owner/repo", issue_payload={"title": "One"})
    second = client.create_issue(repository="owner/repo", issue_payload={"title": "Two"})

    assert first["html_url"].endswith("/7")
    assert second["html_url"].endswith("/7")
    assert [payload for _url, payload in calls] == [
        {},
        {"title": "One"},
        {"title": "Two"},
    ]

    monkeypatch.setattr("isrc_manager.reporting.proxy.github_app_jwt", lambda *_args: "jwt")
    monkeypatch.setattr(
        "isrc_manager.reporting.proxy._github_json_request",
        lambda *_args, **_kwargs: {},
    )
    missing_token_client = GitHubAppIssueClient(
        app_id="123",
        installation_id="456",
        private_key_pem=pem,
    )
    with pytest.raises(RuntimeError, match="installation token"):
        missing_token_client._token()


def test_github_json_request_parses_empty_non_dict_and_http_error(monkeypatch) -> None:
    class _Response:
        status = 201

        def __init__(self, body: bytes):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return self.body

    bodies = [b"", b"[1, 2]", b'{"ok": true}']

    def _fake_urlopen(_request, timeout):
        del timeout
        return _Response(bodies.pop(0))

    monkeypatch.setattr("isrc_manager.reporting.proxy.urllib.request.urlopen", _fake_urlopen)

    assert _github_json_request("POST", "https://api.github.test", token="t", payload={}) == {}
    assert _github_json_request("POST", "https://api.github.test", token="t", payload={}) == {}
    assert _github_json_request("POST", "https://api.github.test", token="t", payload={}) == {
        "ok": True
    }

    def _raise_http(_request, timeout):
        del timeout
        raise urllib.error.HTTPError("https://api.github.test", 500, "fail", {}, None)

    monkeypatch.setattr("isrc_manager.reporting.proxy.urllib.request.urlopen", _raise_http)
    with pytest.raises(urllib.error.HTTPError):
        _github_json_request("POST", "https://api.github.test", token="t", payload={})


def test_parse_github_expiration_uses_fallback_for_empty_or_invalid() -> None:
    assert _parse_github_expiration("") > 0
    assert _parse_github_expiration("not-a-date") > 0
    assert _parse_github_expiration("2099-01-01T00:00:00Z") > 0


def _environ(body: bytes):
    return {
        "REQUEST_METHOD": "POST",
        "REMOTE_ADDR": "127.0.0.1",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }

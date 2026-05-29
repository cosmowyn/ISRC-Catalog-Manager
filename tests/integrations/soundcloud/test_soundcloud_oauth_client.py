import re
import unittest
import urllib.request
from dataclasses import dataclass, field
from unittest import mock

from isrc_manager.integrations.soundcloud.client import (
    SoundCloudAPIClient,
    SoundCloudAPIError,
    SoundCloudMalformedResponseError,
    SoundCloudTransportResponse,
    parse_rate_limit_error,
    redact_headers,
    redact_text,
)
from isrc_manager.integrations.soundcloud.models import (
    SoundCloudOAuthTokenBundle,
    SoundCloudTokenKind,
)
from isrc_manager.integrations.soundcloud.oauth import (
    build_authorization_url,
    build_code_challenge,
    generate_pkce_verifier,
    generate_state,
    parse_authorization_callback,
    verify_state,
)
from isrc_manager.integrations.soundcloud.token_storage import (
    KeychainSoundCloudTokenStore,
    KeyringSoundCloudCredentialStore,
    SessionOnlySoundCloudCredentialStore,
    SessionOnlySoundCloudTokenStore,
    SoundCloudCredentialManager,
    SoundCloudTokenStorageError,
    SoundCloudTokenStore,
    detect_keychain_backend,
)


@dataclass(slots=True)
class FakeSecureBackend:
    available: bool = True
    fail_writes: bool = False
    values: dict[tuple[str, str], str] = field(default_factory=dict)

    def get_password(self, service_name: str, account_key: str):
        return self.values.get((service_name, account_key))

    def set_password(self, service_name: str, account_key: str, value: str):
        if self.fail_writes:
            raise RuntimeError("secure store offline")
        self.values[(service_name, account_key)] = value

    def delete_password(self, service_name: str, account_key: str):
        self.values.pop((service_name, account_key), None)


class FakeInsecureBackend(FakeSecureBackend):
    pass


FakeInsecureBackend.__module__ = "keyrings.alt.file"


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected transport call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class SoundCloudOAuthClientTests(unittest.TestCase):
    def test_pkce_challenge_shape_matches_pkce_format(self):
        verifier = generate_pkce_verifier(64)
        challenge = build_code_challenge(verifier)

        self.assertTrue(43 <= len(verifier) <= 128)
        self.assertTrue(43 <= len(challenge) <= 88)
        self.assertIsNotNone(re.match(r"^[A-Za-z0-9_\-]+$", verifier))
        self.assertIsNotNone(re.match(r"^[A-Za-z0-9_\-]+$", challenge))

    def test_state_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "state mismatch"):
            verify_state("expected-state", "other")

    def test_authorization_callback_parsing(self):
        callback = "https://example.local/callback?code=abc123&state=s1&error_description=none"
        parsed = parse_authorization_callback(callback)

        self.assertEqual(parsed.code, "abc123")
        self.assertEqual(parsed.state, "s1")
        self.assertIsNone(parsed.error)

    def test_authorization_url_includes_pkce_and_state(self):
        verifier = generate_pkce_verifier(43)
        challenge = build_code_challenge(verifier)
        state = generate_state(40)

        url = build_authorization_url(
            "https://soundcloud.com/connect",
            client_id="client-id",
            redirect_uri="https://example.local/callback",
            scopes=["non-expiring", "upload"],
            code_challenge=challenge,
            state=state,
        )

        self.assertIn("response_type=code", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn(f"state={state}", url)

    def test_callback_redaction_replaces_secret_query_values(self):
        url = "https://example.local/callback?code=auth-code-123&state=abc&access_token=abc123&refresh_token=rt-456&client_secret=shh"
        redacted = redact_text(url)
        self.assertNotIn("auth-code-123", redacted)
        self.assertNotIn("state=abc", redacted)
        self.assertIn("callback?***", redacted)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("rt-456", redacted)
        self.assertNotIn("shh", redacted)

    def test_redact_token_and_callback_fragments(self):
        raw = (
            "Authorization: Bearer secret-token-abc; "
            "Authorization: OAuth another-token; "
            "access_token=abc123&refresh_token=xyz&client_secret=topsecret&code=xyzabc"
        )

        redacted = redact_text(raw)
        self.assertNotIn("secret-token-abc", redacted)
        self.assertNotIn("another-token", redacted)
        self.assertIn("access_token=***", redacted)
        self.assertIn("refresh_token=***", redacted)
        self.assertIn("client_secret=***", redacted)
        self.assertIn("code=***", redacted)

    def test_headers_redaction_masks_authorization(self):
        redacted = redact_headers(
            {
                "Authorization": "Bearer very-secret-token",
                "X-Request-Id": "abc",
            }
        )

        self.assertNotIn("very-secret-token", redacted["Authorization"])
        self.assertEqual(redacted["X-Request-Id"], "abc")

    def test_rate_limit_error_parsing_from_body_and_headers(self):
        headers = {
            "X-RateLimit-Limit": "1200",
            "X-RateLimit-Remaining": "1",
            "Retry-After": "7",
            "X-Request-Id": "req-1",
        }
        body = {"error": "rate limit", "message": "Too many requests"}
        error = parse_rate_limit_error(429, headers=headers, body=body)

        self.assertIsNotNone(error)
        self.assertEqual(error.message, "Too many requests")
        self.assertEqual(error.limit, 1200)
        self.assertEqual(error.remaining, 1)
        self.assertEqual(error.retry_after_seconds, 7)
        self.assertEqual(error.request_id, "req-1")

    def test_oauth_token_exchange_success_uses_fake_transport(self):
        transport = FakeTransport(
            [
                SoundCloudTransportResponse(
                    status_code=200,
                    headers={},
                    body={
                        "access_token": "access-1",
                        "refresh_token": "refresh-1",
                        "expires_in": 3600,
                        "scope": "upload",
                    },
                )
            ]
        )
        client = SoundCloudAPIClient(transport=transport)

        bundle = client.exchange_authorization_code(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="isrc://callback",
            code="auth-code",
            code_verifier="verifier",
        )

        self.assertEqual(bundle.access_token, "access-1")
        self.assertEqual(bundle.refresh_token, "refresh-1")
        self.assertEqual(transport.requests[0][0], "POST")
        self.assertIn("/oauth/token", transport.requests[0][1])

    def test_api_logging_omits_oauth_request_and_response_secrets(self):
        transport = FakeTransport(
            [
                SoundCloudTransportResponse(
                    status_code=200,
                    headers={"X-Request-Id": "req-1"},
                    body={
                        "access_token": "access-secret-value",
                        "refresh_token": "refresh-secret-value",
                        "expires_in": 3600,
                        "scope": "upload",
                    },
                )
            ]
        )
        client = SoundCloudAPIClient(transport=transport)

        with self.assertLogs("ISRCManager.soundcloud", level="INFO") as captured:
            client.exchange_authorization_code(
                client_id="client-id",
                client_secret="client-secret-value",
                redirect_uri="isrc://callback",
                code="auth-code-value",
                code_verifier="verifier-secret-value",
            )

        log_text = "\n".join(captured.output)
        self.assertIn("/oauth/token", log_text)
        self.assertIn("req-1", log_text)
        self.assertNotIn("client-secret-value", log_text)
        self.assertNotIn("auth-code-value", log_text)
        self.assertNotIn("verifier-secret-value", log_text)
        self.assertNotIn("access-secret-value", log_text)
        self.assertNotIn("refresh-secret-value", log_text)

    def test_oauth_token_exchange_failure_is_redacted(self):
        transport = FakeTransport(
            [
                SoundCloudTransportResponse(
                    status_code=401,
                    headers={},
                    body={"error": "invalid client_secret=very-secret&code=auth-code"},
                )
            ]
        )
        client = SoundCloudAPIClient(transport=transport)

        with self.assertRaises(SoundCloudAPIError) as raised:
            client.exchange_authorization_code(
                client_id="client-id",
                client_secret="very-secret",
                redirect_uri="isrc://callback",
                code="auth-code",
                code_verifier="verifier",
            )

        message = str(raised.exception)
        self.assertNotIn("very-secret", message)
        self.assertNotIn("auth-code", message)
        self.assertIn("client_secret=***", message)

    def test_api_failure_logging_redacts_secret_response_values(self):
        transport = FakeTransport(
            [
                SoundCloudTransportResponse(
                    status_code=401,
                    headers={},
                    body={"error": "invalid client_secret=very-secret&code=auth-code"},
                )
            ]
        )
        client = SoundCloudAPIClient(transport=transport)

        with self.assertLogs("ISRCManager.soundcloud", level="WARNING") as captured:
            with self.assertRaises(SoundCloudAPIError):
                client.exchange_authorization_code(
                    client_id="client-id",
                    client_secret="very-secret",
                    redirect_uri="isrc://callback",
                    code="auth-code",
                    code_verifier="verifier",
                )

        log_text = "\n".join(captured.output)
        self.assertIn("client_secret=***", log_text)
        self.assertIn("code=***", log_text)
        self.assertNotIn("very-secret", log_text)
        self.assertNotIn("auth-code", log_text)

    def test_refresh_token_success_and_malformed_response(self):
        transport = FakeTransport(
            [
                SoundCloudTransportResponse(
                    status_code=200,
                    headers={},
                    body={"access_token": "new-access", "refresh_token": "new-refresh"},
                ),
                SoundCloudTransportResponse(
                    status_code=200, headers={}, body={"access_token": "x"}
                ),
            ]
        )
        client = SoundCloudAPIClient(transport=transport)

        bundle = client.refresh_token(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="old-refresh",
        )
        self.assertEqual(bundle.refresh_token, "new-refresh")
        with self.assertRaises(SoundCloudMalformedResponseError):
            client.refresh_token(
                client_id="client-id",
                client_secret="client-secret",
                refresh_token="new-refresh",
            )

    def test_api_rate_limit_raises_redacted_error(self):
        transport = FakeTransport(
            [
                SoundCloudTransportResponse(
                    status_code=429,
                    headers={"Retry-After": "12", "X-RateLimit-Remaining": "0"},
                    body={"message": "Too many requests"},
                )
            ]
        )
        client = SoundCloudAPIClient(transport=transport)

        with self.assertRaises(SoundCloudAPIError) as raised:
            client.get_me("access-token")

        self.assertIsNotNone(raised.exception.rate_limit)
        self.assertEqual(raised.exception.rate_limit.retry_after_seconds, 12)
        request_headers = transport.requests[0][2]["headers"]
        self.assertEqual(request_headers["Authorization"], "OAuth access-token")

    def test_client_uses_injected_transport_without_network(self):
        transport = FakeTransport(
            [
                SoundCloudTransportResponse(
                    status_code=200,
                    headers={},
                    body={"id": 123, "username": "Offline"},
                )
            ]
        )
        client = SoundCloudAPIClient(transport=transport)

        with mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("network")):
            account = client.get_me("access-token")

        self.assertEqual(account["username"], "Offline")

    def test_token_store_uses_persistent_backend_when_available(self):
        backend = FakeSecureBackend(available=True)
        store = SoundCloudTokenStore(persistent_backend=backend)
        bundle = SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r")

        kind = store.save_bundle("acct", bundle)
        loaded = store.load_bundle("acct")
        raw = next(iter(backend.values.values()))

        self.assertEqual(kind, SoundCloudTokenKind.PERSISTENT)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.refresh_token, "r")
        self.assertIn("account_identifier", raw)
        self.assertIn("created_at", raw)
        self.assertIn("updated_at", raw)

    def test_token_bundle_repr_redacts_secret_values(self):
        bundle = SoundCloudOAuthTokenBundle(
            access_token="access-secret",
            refresh_token="refresh-secret",
        )

        text = repr(bundle)

        self.assertNotIn("access-secret", text)
        self.assertNotIn("refresh-secret", text)
        self.assertIn("***", text)

    def test_keychain_detection_accepts_safe_fake_and_rejects_insecure_backend(self):
        safe_report = detect_keychain_backend(FakeSecureBackend(available=True))
        unsafe_report = detect_keychain_backend(FakeInsecureBackend(available=True))
        unavailable_report = detect_keychain_backend(FakeSecureBackend(available=False))

        self.assertTrue(safe_report.usable)
        self.assertFalse(unsafe_report.usable)
        self.assertIn("not considered safe", unsafe_report.reason)
        self.assertFalse(unavailable_report.usable)

    def test_token_store_session_only_fallback_when_keyring_unavailable(self):
        backend = FakeSecureBackend(available=False)
        store = SoundCloudTokenStore(persistent_backend=backend)
        bundle = SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r")

        kind = store.save_bundle("acct", bundle)

        self.assertEqual(kind, SoundCloudTokenKind.SESSION)
        self.assertEqual(store.load_bundle("acct").access_token, "a")
        self.assertEqual(backend.values, {})
        fresh_store = SoundCloudTokenStore(persistent_backend=backend)
        self.assertIsNone(fresh_store.load_bundle("acct"))

    def test_keychain_store_save_load_delete_through_fake_keyring(self):
        backend = FakeSecureBackend(available=True)
        store = KeychainSoundCloudTokenStore(backend=backend)

        kind = store.save_bundle(
            "soundcloud:user:abc",
            SoundCloudOAuthTokenBundle(access_token="access", refresh_token="refresh"),
        )
        loaded = store.load_bundle("soundcloud:user:abc")
        store.delete_bundle("soundcloud:user:abc")

        self.assertEqual(kind, SoundCloudTokenKind.PERSISTENT)
        self.assertEqual(loaded.access_token, "access")
        self.assertIsNone(store.load_bundle("soundcloud:user:abc"))

    def test_named_credential_store_implementations_and_manager_selection(self):
        backend = FakeSecureBackend(available=True)
        keyring_store = KeyringSoundCloudCredentialStore(backend=backend)
        session_store = SessionOnlySoundCloudCredentialStore()
        manager = SoundCloudCredentialManager(persistent_backend=backend)
        fallback = SoundCloudCredentialManager(
            persistent_backend=FakeSecureBackend(available=False)
        )

        self.assertTrue(keyring_store.persistent_available)
        self.assertFalse(session_store.persistent_available)
        self.assertEqual(manager.active_storage_mode, SoundCloudTokenKind.PERSISTENT)
        self.assertEqual(fallback.active_storage_mode, SoundCloudTokenKind.SESSION)

    def test_client_secret_uses_keychain_or_session_only_without_echo(self):
        backend = FakeSecureBackend(available=True)
        store = SoundCloudTokenStore(persistent_backend=backend)

        kind = store.save_client_secret("client-id", "client-secret-value")
        store.save_client_secret("client-id", "replacement-secret-value")
        loaded = store.load_client_secret("client-id")
        raw = "\n".join(backend.values.values())
        store.delete_client_secret("client-id")

        self.assertEqual(kind, SoundCloudTokenKind.PERSISTENT)
        self.assertEqual(loaded, "replacement-secret-value")
        self.assertNotIn("client-secret-value", raw)
        self.assertNotIn("client-id", raw)
        self.assertIsNone(store.load_client_secret("client-id"))

        session_store = SessionOnlySoundCloudTokenStore()
        session_store.save_client_secret("client-id", "session-secret")
        self.assertEqual(session_store.load_client_secret("client-id"), "session-secret")
        self.assertIsNone(SessionOnlySoundCloudTokenStore().load_client_secret("client-id"))

    def test_secure_store_write_failure_is_not_silent(self):
        store = SoundCloudTokenStore(
            persistent_backend=FakeSecureBackend(available=True, fail_writes=True)
        )

        with self.assertRaises(SoundCloudTokenStorageError):
            store.save_bundle(
                "acct",
                SoundCloudOAuthTokenBundle(access_token="a", refresh_token="r"),
            )

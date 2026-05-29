"""PKCE and OAuth authorization helper routines (no network calls)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from .client import SoundCloudAPIClient, redact_text
from .persistence import SoundCloudSQLiteRepository
from .token_store import SoundCloudCredentialStore

LOGGER = logging.getLogger("ISRCManager.soundcloud")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def generate_pkce_verifier(length: int = 64) -> str:
    """Generate a PKCE verifier."""

    if length < 43 or length > 128:
        raise ValueError("PKCE verifier length must be between 43 and 128 characters.")
    entropy = secrets.token_bytes(length)
    verifier = _b64url(entropy)[:length]
    return verifier


def build_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url(digest)


def generate_state(length: int = 48) -> str:
    return secrets.token_urlsafe(length)[:length]


def verify_state(expected: str, received: str) -> None:
    if not expected or not received:
        raise ValueError("OAuth state is missing.")
    if not hmac.compare_digest(expected, received):
        raise ValueError("OAuth state mismatch.")


def build_authorization_url(
    authorization_endpoint: str,
    *,
    client_id: str,
    redirect_uri: str,
    scopes: str | list[str] | tuple[str, ...] | None,
    code_challenge: str,
    state: str,
) -> str:
    """Build an authorization URL for user consent."""

    values = [
        ("response_type", "code"),
        ("client_id", client_id),
        ("redirect_uri", redirect_uri),
        ("state", state),
        ("code_challenge", code_challenge),
        ("code_challenge_method", "S256"),
    ]
    scope_text = ""
    if isinstance(scopes, str):
        scope_text = scopes.strip()
    elif scopes:
        scope_text = " ".join(scopes)
    if scope_text:
        values.append(("scope", scope_text))

    url = urlparse(authorization_endpoint)
    return urlunparse(
        (
            url.scheme,
            url.netloc,
            url.path,
            url.params,
            urlencode(values),
            "",
        )
    )


@dataclass(frozen=True, slots=True)
class OAuthCallback:
    """Parsed OAuth callback fragments."""

    code: str | None
    state: str | None
    error: str | None
    error_description: str | None


def parse_authorization_callback(callback_url: str) -> OAuthCallback:
    parsed = urlparse(callback_url)
    query = parse_qs(parsed.query)
    code = query.get("code", [None])[0] or None
    state = query.get("state", [None])[0] or None
    error = query.get("error", [None])[0] or None
    error_description = query.get("error_description", [None])[0] or None
    if not code and not state and error is None:
        raise ValueError("Callback URL does not contain OAuth parameters.")
    return OAuthCallback(code=code, state=state, error=error, error_description=error_description)


@dataclass(frozen=True, slots=True)
class SoundCloudConnectionResult:
    """Non-secret account connection result."""

    account_id: int
    account_key: str
    token_kind: str
    username: str | None = None


def soundcloud_account_key(account_payload: dict[str, object] | object) -> str:
    if isinstance(account_payload, dict):
        user_id = str(account_payload.get("id") or "").strip()
        permalink = str(account_payload.get("permalink") or "").strip()
    else:
        user_id = str(getattr(account_payload, "id", "") or "").strip()
        permalink = str(getattr(account_payload, "permalink", "") or "").strip()
    if user_id:
        return f"soundcloud:user:{user_id}"
    if permalink:
        return f"soundcloud:permalink:{permalink}"
    raise ValueError("SoundCloud account response did not include a stable account identifier.")


class SoundCloudOAuthService:
    """Completes SoundCloud OAuth and refreshes stored token bundles."""

    def __init__(
        self,
        *,
        client: SoundCloudAPIClient,
        token_store: SoundCloudCredentialStore,
        repository: SoundCloudSQLiteRepository,
    ) -> None:
        self.client = client
        self.token_store = token_store
        self.repository = repository

    def complete_authorization_callback(
        self,
        *,
        callback_url: str,
        expected_state: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> SoundCloudConnectionResult:
        LOGGER.info(
            "SoundCloud OAuth callback received; validating state.",
            extra={
                "event": "soundcloud.oauth.callback.received",
                "action": "oauth_callback",
                "entity": "soundcloud_account",
            },
        )
        callback = parse_authorization_callback(callback_url)
        if callback.error:
            detail = callback.error_description or callback.error
            LOGGER.warning(
                "SoundCloud OAuth authorization failed: error=%s",
                redact_text(str(detail)),
                extra={
                    "event": "soundcloud.oauth.callback.failed",
                    "action": "oauth_callback",
                    "entity": "soundcloud_account",
                    "status": "failed",
                    "details": {"error": redact_text(str(detail))},
                },
            )
            raise ValueError(redact_text(f"SoundCloud authorization failed: {detail}"))
        verify_state(expected_state, callback.state or "")
        if not callback.code:
            raise ValueError("SoundCloud authorization callback did not include an auth code.")
        LOGGER.info(
            "SoundCloud OAuth token exchange starting.",
            extra={
                "event": "soundcloud.oauth.token_exchange.started",
                "action": "token_exchange",
                "entity": "soundcloud_account",
            },
        )
        bundle = self.client.exchange_authorization_code(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            code=callback.code,
            code_verifier=code_verifier,
        )
        account_payload = dict(self.client.get_me(bundle.access_token))
        account_key = soundcloud_account_key(account_payload)
        try:
            token_kind = self.token_store.save_bundle(account_key, bundle)
        except Exception as exc:
            LOGGER.error(
                "SoundCloud OAuth token persistence failed; reconnect required: account_key=%s error=%s",
                account_key,
                redact_text(str(exc)),
                extra={
                    "event": "soundcloud.oauth.token_persist.failed",
                    "action": "token_persist",
                    "entity": "soundcloud_account",
                    "entity_id": account_key,
                    "status": "failed",
                    "details": {"error": redact_text(str(exc))},
                },
            )
            raise
        account_id = self.repository.upsert_connected_account(
            account_key=account_key,
            token_store_key=account_key,
            token_kind=token_kind,
            account_payload=account_payload,
            scope=bundle.scope,
            token_expires_at=bundle.expires_at,
        )
        LOGGER.info(
            "SoundCloud OAuth connection completed: account_id=%s account_key=%s token_store=%s",
            account_id,
            account_key,
            token_kind.value,
            extra={
                "event": "soundcloud.oauth.connection.completed",
                "action": "connect",
                "entity": "soundcloud_account",
                "entity_id": account_id,
                "status": "connected",
                "details": {"account_key": account_key, "token_store": token_kind.value},
            },
        )
        return SoundCloudConnectionResult(
            account_id=account_id,
            account_key=account_key,
            token_kind=token_kind.value,
            username=(
                str(account_payload.get("username"))
                if account_payload.get("username") is not None
                else None
            ),
        )

    def refresh_account(
        self,
        account_id: int,
        *,
        client_id: str,
        client_secret: str,
    ) -> SoundCloudConnectionResult:
        LOGGER.info(
            "SoundCloud token refresh starting: account_id=%s",
            account_id,
            extra={
                "event": "soundcloud.oauth.refresh.started",
                "action": "refresh",
                "entity": "soundcloud_account",
                "entity_id": account_id,
            },
        )
        account = self.repository.account_by_id(account_id)
        if account is None or account.connection_status != "connected":
            raise ValueError("SoundCloud account is not connected.")
        current_bundle = self.token_store.load_bundle(account.token_store_key)
        if current_bundle is None:
            raise ValueError("SoundCloud token bundle is unavailable; reconnect is required.")
        refreshed = self.client.refresh_token(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=current_bundle.refresh_token,
        )
        LOGGER.info(
            "SoundCloud token refresh response received; persisting new token bundle first: account_id=%s",
            account_id,
            extra={
                "event": "soundcloud.oauth.refresh.persist_started",
                "action": "refresh",
                "entity": "soundcloud_account",
                "entity_id": account_id,
            },
        )
        try:
            token_kind = self.token_store.save_bundle(account.token_store_key, refreshed)
        except Exception as exc:
            LOGGER.error(
                "SoundCloud token refresh persistence failed; reconnect required: account_id=%s error=%s",
                account_id,
                redact_text(str(exc)),
                extra={
                    "event": "soundcloud.oauth.refresh.persist_failed",
                    "action": "refresh",
                    "entity": "soundcloud_account",
                    "entity_id": account_id,
                    "status": "failed",
                    "details": {"error": redact_text(str(exc))},
                },
            )
            raise
        self.repository.record_token_refresh(
            account.id,
            token_kind=token_kind,
            scope=refreshed.scope,
            token_expires_at=refreshed.expires_at,
        )
        LOGGER.info(
            "SoundCloud token refresh completed: account_id=%s token_store=%s",
            account.id,
            token_kind.value,
            extra={
                "event": "soundcloud.oauth.refresh.completed",
                "action": "refresh",
                "entity": "soundcloud_account",
                "entity_id": account.id,
                "status": "connected",
                "details": {"token_store": token_kind.value},
            },
        )
        return SoundCloudConnectionResult(
            account_id=account.id,
            account_key=account.account_key,
            token_kind=token_kind.value,
            username=account.username,
        )

    def token_for_account(
        self,
        account_id: int,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> str:
        account = self.repository.account_by_id(account_id)
        if account is None or account.connection_status != "connected":
            raise ValueError("SoundCloud account is not connected.")
        bundle = self.token_store.load_bundle(account.token_store_key)
        if bundle is None:
            raise ValueError("SoundCloud token bundle is unavailable; reconnect is required.")
        if bundle.is_expired():
            if not client_id or not client_secret:
                raise ValueError("SoundCloud token is expired; reconnect is required.")
            LOGGER.info(
                "SoundCloud access token expired; refresh required: account_id=%s",
                account_id,
                extra={
                    "event": "soundcloud.oauth.token.expired",
                    "action": "refresh",
                    "entity": "soundcloud_account",
                    "entity_id": account_id,
                },
            )
            self.refresh_account(account_id, client_id=client_id, client_secret=client_secret)
            refreshed = self.token_store.load_bundle(account.token_store_key)
            if refreshed is None:
                raise ValueError("SoundCloud token refresh did not persist; reconnect is required.")
            return refreshed.access_token
        return bundle.access_token

    def disconnect_account(self, account_id: int) -> None:
        LOGGER.info(
            "SoundCloud disconnect started: account_id=%s",
            account_id,
            extra={
                "event": "soundcloud.oauth.disconnect.started",
                "action": "disconnect",
                "entity": "soundcloud_account",
                "entity_id": account_id,
            },
        )
        account = self.repository.account_by_id(account_id)
        if account is None:
            LOGGER.info(
                "SoundCloud disconnect skipped; account was not found: account_id=%s",
                account_id,
                extra={
                    "event": "soundcloud.oauth.disconnect.skipped",
                    "action": "disconnect",
                    "entity": "soundcloud_account",
                    "entity_id": account_id,
                    "status": "not_found",
                },
            )
            return
        error: str | None = None
        bundle = self.token_store.load_bundle(account.token_store_key)
        if bundle is not None:
            try:
                self.client.sign_out(bundle.access_token)
            except Exception as exc:
                error = redact_text(str(exc))
                LOGGER.warning(
                    "SoundCloud remote sign-out failed; local disconnect continuing: account_id=%s error=%s",
                    account_id,
                    error,
                    extra={
                        "event": "soundcloud.oauth.sign_out.failed",
                        "action": "disconnect",
                        "entity": "soundcloud_account",
                        "entity_id": account_id,
                        "status": "remote_sign_out_failed",
                        "details": {"error": error},
                    },
                )
        self.token_store.delete_bundle(account.token_store_key)
        self.repository.mark_disconnected(account.id, error=error)
        LOGGER.info(
            "SoundCloud disconnect completed: account_id=%s",
            account.id,
            extra={
                "event": "soundcloud.oauth.disconnect.completed",
                "action": "disconnect",
                "entity": "soundcloud_account",
                "entity_id": account.id,
                "status": "disconnected",
            },
        )


__all__ = [
    "OAuthCallback",
    "SoundCloudConnectionResult",
    "SoundCloudOAuthService",
    "build_authorization_url",
    "build_code_challenge",
    "generate_pkce_verifier",
    "generate_state",
    "parse_authorization_callback",
    "soundcloud_account_key",
    "verify_state",
]

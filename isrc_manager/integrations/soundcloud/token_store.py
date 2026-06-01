"""Secure SoundCloud token and credential storage.

Tokens and client secrets are stored only in an OS keychain/keyring backend when a safe backend is
available. A session-only in-memory fallback is used otherwise. No plaintext file, environment
variable, or SQLite fallback is provided.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .client import redact_text
from .models import SoundCloudOAuthTokenBundle, SoundCloudTokenKind

DEFAULT_SOUNDCLOUD_KEYCHAIN_SERVICE = "isrc-catalog-manager.soundcloud"
CLIENT_SECRET_KEY_PREFIX = "soundcloud:client-secret:"


class SoundCloudTokenStorageError(RuntimeError):
    """Raised when secure credential persistence cannot complete safely."""


class SoundCloudTokenStorageBackend(Protocol):
    """Subset of the Python keyring backend API used by the integration."""

    @property
    def available(self) -> bool: ...

    def get_password(self, service_name: str, account_key: str) -> str | None: ...

    def set_password(self, service_name: str, account_key: str, value: str) -> None: ...

    def delete_password(self, service_name: str, account_key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class SoundCloudKeychainAvailability:
    """Runtime report for whether a keychain backend can be used safely."""

    available: bool
    safe: bool
    backend_name: str
    reason: str

    @property
    def usable(self) -> bool:
        return self.available and self.safe


class SoundCloudCredentialStore(Protocol):
    """Narrow credential-store interface used by SoundCloud OAuth services."""

    @property
    def availability(self) -> SoundCloudKeychainAvailability: ...

    @property
    def persistent_available(self) -> bool: ...

    def save_bundle(
        self,
        account_key: str,
        bundle: SoundCloudOAuthTokenBundle,
    ) -> SoundCloudTokenKind: ...

    def load_bundle(self, account_key: str) -> SoundCloudOAuthTokenBundle | None: ...

    def delete_bundle(self, account_key: str) -> None: ...

    def save_client_secret(self, client_id: str, client_secret: str) -> SoundCloudTokenKind: ...

    def load_client_secret(self, client_id: str) -> str | None: ...

    def delete_client_secret(self, client_id: str) -> None: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backend_name(backend: object | None) -> str:
    if backend is None:
        return "none"
    cls = backend.__class__
    module = str(getattr(cls, "__module__", "") or "")
    name = str(getattr(cls, "__name__", "") or "")
    return f"{module}.{name}".strip(".") or repr(cls)


def detect_keychain_backend(
    backend: SoundCloudTokenStorageBackend | object | None = None,
) -> SoundCloudKeychainAvailability:
    """Return a conservative safety report for a keyring-compatible backend."""

    if backend is None:
        try:
            keyring = importlib.import_module("keyring")
        except Exception:
            return SoundCloudKeychainAvailability(
                available=False,
                safe=False,
                backend_name="none",
                reason="Python keyring is not installed.",
            )
        try:
            backend = keyring.get_keyring()
        except Exception:
            return SoundCloudKeychainAvailability(
                available=False,
                safe=False,
                backend_name="unavailable",
                reason="Python keyring did not provide a backend.",
            )

    name = _backend_name(backend)
    lower_name = name.lower()
    explicit_available = bool(getattr(backend, "available", True))
    if not explicit_available:
        return SoundCloudKeychainAvailability(
            available=False,
            safe=False,
            backend_name=name,
            reason="Keychain backend reports unavailable.",
        )

    unsafe_fragments = (
        "keyrings.alt",
        "plaintext",
        "plain",
        "null",
        "fail",
    )
    if any(fragment in lower_name for fragment in unsafe_fragments):
        return SoundCloudKeychainAvailability(
            available=True,
            safe=False,
            backend_name=name,
            reason="Keychain backend is not considered safe for persistent SoundCloud tokens.",
        )

    priority = getattr(backend, "priority", None)
    try:
        if priority is not None and float(priority) <= 0:
            return SoundCloudKeychainAvailability(
                available=True,
                safe=False,
                backend_name=name,
                reason="Keychain backend priority indicates an unavailable or fallback backend.",
            )
    except Exception:
        pass

    required_methods = ("get_password", "set_password", "delete_password")
    if not all(callable(getattr(backend, method, None)) for method in required_methods):
        return SoundCloudKeychainAvailability(
            available=False,
            safe=False,
            backend_name=name,
            reason="Keychain backend does not expose the required credential methods.",
        )

    return SoundCloudKeychainAvailability(
        available=True,
        safe=True,
        backend_name=name,
        reason="Safe OS keychain/keyring backend is available.",
    )


def _token_payload(
    account_identifier: str,
    bundle: SoundCloudOAuthTokenBundle,
    *,
    created_at: str | None = None,
) -> dict[str, object]:
    now = _utc_now()
    return {
        **bundle.to_record(),
        "account_identifier": account_identifier,
        "created_at": created_at or now,
        "updated_at": now,
    }


def _client_secret_account_key(client_id: str) -> str:
    digest = hashlib.sha256(str(client_id).encode("utf-8")).hexdigest()
    return f"{CLIENT_SECRET_KEY_PREFIX}{digest}"


class SessionOnlySoundCloudTokenStore:
    """Session-only storage. Data disappears with the Python process."""

    availability = SoundCloudKeychainAvailability(
        available=False,
        safe=False,
        backend_name="session-only",
        reason="Session-only fallback is active.",
    )

    def __init__(self) -> None:
        self._tokens: dict[str, SoundCloudOAuthTokenBundle] = {}
        self._client_secrets: dict[str, str] = {}

    @property
    def persistent_available(self) -> bool:
        return False

    def save_bundle(
        self, account_key: str, bundle: SoundCloudOAuthTokenBundle
    ) -> SoundCloudTokenKind:
        self._tokens[str(account_key)] = bundle
        return SoundCloudTokenKind.SESSION

    def load_bundle(self, account_key: str) -> SoundCloudOAuthTokenBundle | None:
        return self._tokens.get(str(account_key))

    def delete_bundle(self, account_key: str) -> None:
        self._tokens.pop(str(account_key), None)

    def save_client_secret(self, client_id: str, client_secret: str) -> SoundCloudTokenKind:
        self._client_secrets[_client_secret_account_key(client_id)] = str(client_secret)
        return SoundCloudTokenKind.SESSION

    def load_client_secret(self, client_id: str) -> str | None:
        return self._client_secrets.get(_client_secret_account_key(client_id))

    def delete_client_secret(self, client_id: str) -> None:
        self._client_secrets.pop(_client_secret_account_key(client_id), None)


class KeyringSoundCloudTokenStorageBackend:
    """Adapter for the optional Python keyring package."""

    def __init__(self) -> None:
        try:
            keyring = importlib.import_module("keyring")
        except Exception:
            self._keyring = None
            self._backend = None
        else:
            self._keyring = keyring
            try:
                self._backend = keyring.get_keyring()
            except Exception:
                self._backend = None

    @property
    def available(self) -> bool:
        return self._keyring is not None and detect_keychain_backend(self._backend).usable

    def get_password(self, service_name: str, account_key: str) -> str | None:
        if self._keyring is None:
            return None
        value = self._keyring.get_password(service_name, account_key)
        return str(value) if value is not None else None

    def set_password(self, service_name: str, account_key: str, value: str) -> None:
        if self._keyring is None:
            raise SoundCloudTokenStorageError("No safe OS keychain/keyring backend is available.")
        self._keyring.set_password(service_name, account_key, value)

    def delete_password(self, service_name: str, account_key: str) -> None:
        if self._keyring is None:
            return
        try:
            self._keyring.delete_password(service_name, account_key)
        except Exception:
            return


class KeychainSoundCloudTokenStore:
    """OS keychain/keyring-backed SoundCloud token and client-secret storage."""

    def __init__(
        self,
        *,
        backend: SoundCloudTokenStorageBackend | object | None = None,
        service_name: str = DEFAULT_SOUNDCLOUD_KEYCHAIN_SERVICE,
    ) -> None:
        self.backend = backend
        if self.backend is None:
            try:
                keyring = importlib.import_module("keyring")
            except Exception:
                self.backend = None
            else:
                try:
                    self.backend = keyring.get_keyring()
                except Exception:
                    self.backend = None
        self.service_name = service_name
        self.availability = detect_keychain_backend(self.backend)

    @property
    def persistent_available(self) -> bool:
        return self.availability.usable

    def _require_backend(self) -> SoundCloudTokenStorageBackend:
        if not self.availability.usable or self.backend is None:
            raise SoundCloudTokenStorageError(
                "Safe OS keychain/keyring storage is unavailable; reconnect is required."
            )
        return self.backend  # type: ignore[return-value]

    def _read_json(self, account_key: str) -> dict[str, Any] | None:
        backend = self._require_backend()
        try:
            raw = backend.get_password(self.service_name, account_key)
        except Exception:
            raise SoundCloudTokenStorageError(
                "Secure SoundCloud credential retrieval failed; reconnect is required."
            ) from None
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except Exception:
            raise SoundCloudTokenStorageError(
                "Stored SoundCloud credential bundle is unreadable; reconnect is required."
            ) from None
        if not isinstance(payload, dict):
            raise SoundCloudTokenStorageError(
                "Stored SoundCloud credential bundle is malformed; reconnect is required."
            )
        return payload

    def _write_json(self, account_key: str, payload: dict[str, object]) -> None:
        backend = self._require_backend()
        try:
            backend.set_password(
                self.service_name,
                account_key,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
            )
        except Exception:
            raise SoundCloudTokenStorageError(
                "Secure SoundCloud credential persistence failed; reconnect is required."
            ) from None

    def save_bundle(
        self, account_key: str, bundle: SoundCloudOAuthTokenBundle
    ) -> SoundCloudTokenKind:
        key = str(account_key)
        existing = self._read_json(key)
        self._write_json(
            key,
            _token_payload(
                key,
                bundle,
                created_at=str((existing or {}).get("created_at") or "") or None,
            ),
        )
        return SoundCloudTokenKind.PERSISTENT

    def load_bundle(self, account_key: str) -> SoundCloudOAuthTokenBundle | None:
        payload = self._read_json(str(account_key))
        if payload is None:
            return None
        return SoundCloudOAuthTokenBundle.from_record(payload)

    def delete_bundle(self, account_key: str) -> None:
        try:
            backend = self._require_backend()
            backend.delete_password(self.service_name, str(account_key))
        except SoundCloudTokenStorageError:
            return
        except Exception:
            return

    def save_client_secret(self, client_id: str, client_secret: str) -> SoundCloudTokenKind:
        clean_client_id = str(client_id or "").strip()
        clean_secret = str(client_secret or "")
        if not clean_client_id or not clean_secret:
            raise SoundCloudTokenStorageError(
                "SoundCloud client id and client secret are required."
            )
        key = _client_secret_account_key(clean_client_id)
        existing = self._read_json(key)
        now = _utc_now()
        self._write_json(
            key,
            {
                "client_id_hash": hashlib.sha256(clean_client_id.encode("utf-8")).hexdigest(),
                "client_secret": clean_secret,
                "created_at": str((existing or {}).get("created_at") or "") or now,
                "updated_at": now,
            },
        )
        return SoundCloudTokenKind.PERSISTENT

    def load_client_secret(self, client_id: str) -> str | None:
        payload = self._read_json(_client_secret_account_key(str(client_id or "").strip()))
        if payload is None:
            return None
        secret = str(payload.get("client_secret") or "")
        return secret or None

    def delete_client_secret(self, client_id: str) -> None:
        try:
            backend = self._require_backend()
            backend.delete_password(self.service_name, _client_secret_account_key(client_id))
        except Exception:
            return


class KeyringSoundCloudCredentialStore(KeychainSoundCloudTokenStore):
    """OS keychain/keyring-backed SoundCloud credential store."""


class SessionOnlySoundCloudCredentialStore(SessionOnlySoundCloudTokenStore):
    """Session-only SoundCloud credential store."""


class SoundCloudTokenStore:
    """Keychain-first token store with secure session-only fallback."""

    def __init__(
        self,
        *,
        service_name: str = DEFAULT_SOUNDCLOUD_KEYCHAIN_SERVICE,
        persistent_backend: SoundCloudTokenStorageBackend | object | None = None,
        session_store: SessionOnlySoundCloudTokenStore | None = None,
        prefer_persistent: bool = True,
    ) -> None:
        self.service_name = service_name
        self.keychain_store = KeyringSoundCloudCredentialStore(
            backend=persistent_backend,
            service_name=service_name,
        )
        self.session_store = session_store or SessionOnlySoundCloudTokenStore()
        self.prefer_persistent = bool(prefer_persistent)

    @classmethod
    def create_default(cls) -> "SoundCloudTokenStore":
        return cls()

    @property
    def availability(self) -> SoundCloudKeychainAvailability:
        return self.keychain_store.availability

    @property
    def persistent_available(self) -> bool:
        return self.keychain_store.persistent_available

    @property
    def active_storage_mode(self) -> SoundCloudTokenKind:
        if self.prefer_persistent and self.persistent_available:
            return SoundCloudTokenKind.PERSISTENT
        return SoundCloudTokenKind.SESSION

    def save_bundle(
        self,
        account_key: str,
        bundle: SoundCloudOAuthTokenBundle,
    ) -> SoundCloudTokenKind:
        if self.prefer_persistent and self.persistent_available:
            return self.keychain_store.save_bundle(account_key, bundle)
        return self.session_store.save_bundle(account_key, bundle)

    def load_bundle(self, account_key: str) -> SoundCloudOAuthTokenBundle | None:
        if self.prefer_persistent and self.persistent_available:
            loaded = self.keychain_store.load_bundle(account_key)
            if loaded is not None:
                return loaded
        return self.session_store.load_bundle(account_key)

    def delete_bundle(self, account_key: str) -> None:
        self.keychain_store.delete_bundle(account_key)
        self.session_store.delete_bundle(account_key)

    def save_client_secret(self, client_id: str, client_secret: str) -> SoundCloudTokenKind:
        if self.prefer_persistent and self.persistent_available:
            return self.keychain_store.save_client_secret(client_id, client_secret)
        return self.session_store.save_client_secret(client_id, client_secret)

    def load_client_secret(self, client_id: str) -> str | None:
        if self.prefer_persistent and self.persistent_available:
            loaded = self.keychain_store.load_client_secret(client_id)
            if loaded:
                return loaded
        return self.session_store.load_client_secret(client_id)

    def delete_client_secret(self, client_id: str) -> None:
        self.keychain_store.delete_client_secret(client_id)
        self.session_store.delete_client_secret(client_id)


class SoundCloudCredentialManager(SoundCloudTokenStore):
    """Keyring-first SoundCloud credential manager with session-only fallback."""


SessionSoundCloudTokenStore = SessionOnlySoundCloudTokenStore


def safe_storage_error_message(exc: Exception) -> str:
    return redact_text(str(exc))


__all__ = [
    "CLIENT_SECRET_KEY_PREFIX",
    "DEFAULT_SOUNDCLOUD_KEYCHAIN_SERVICE",
    "KeychainSoundCloudTokenStore",
    "KeyringSoundCloudCredentialStore",
    "KeyringSoundCloudTokenStorageBackend",
    "SessionOnlySoundCloudCredentialStore",
    "SessionOnlySoundCloudTokenStore",
    "SessionSoundCloudTokenStore",
    "SoundCloudCredentialManager",
    "SoundCloudCredentialStore",
    "SoundCloudKeychainAvailability",
    "SoundCloudTokenStorageBackend",
    "SoundCloudTokenStorageError",
    "SoundCloudTokenStore",
    "detect_keychain_backend",
    "safe_storage_error_message",
]

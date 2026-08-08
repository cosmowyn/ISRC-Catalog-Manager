"""Strict macOS reset boundary for application-owned Keychain items."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .credential_namespaces import (
    APP_CREDENTIAL_SERVICES,
    DATABASE_CREDENTIAL_SERVICE,
    SOUNDCLOUD_CREDENTIAL_SERVICE,
)

MACOS_SECURITY_TOOL = "/usr/bin/security"
KEYCHAIN_ITEM_NOT_FOUND_STATUS = 44
MAX_DELETE_ATTEMPTS_PER_SERVICE = 4096
SECURITY_COMMAND_TIMEOUT_SECONDS = 30.0

_TEST_EXTERNAL_LAUNCH_BLOCK_ENV_VAR = "ISRC_MANAGER_BLOCK_EXTERNAL_LAUNCHES"

CredentialResetRunner = Callable[..., subprocess.CompletedProcess[Any]]


@dataclass(frozen=True, slots=True)
class CredentialResetResult:
    """Counts of application-owned generic-password items deleted by namespace."""

    database_items_deleted: int = 0
    soundcloud_items_deleted: int = 0

    @property
    def total_items_deleted(self) -> int:
        return self.database_items_deleted + self.soundcloud_items_deleted


@dataclass(frozen=True, slots=True)
class CredentialResetFailure:
    """Sanitized failure details for one fixed application credential namespace."""

    service_name: str
    reason: str
    returncode: int | None = None


class CredentialResetError(RuntimeError):
    """Raised when an application credential reset cannot complete safely."""

    def __init__(
        self,
        message: str,
        *,
        result: CredentialResetResult | None = None,
        failures: tuple[CredentialResetFailure, ...] = (),
    ) -> None:
        super().__init__(message)
        self.result = result or CredentialResetResult()
        self.failures = tuple(failures)


class MacOSCredentialResetService:
    """Deletes only the two fixed generic-password services owned by this app."""

    def __init__(
        self,
        *,
        runner: CredentialResetRunner | None = None,
        platform: str | None = None,
        keychain_path: str | Path | None = None,
    ) -> None:
        self._uses_default_runner = runner is None
        self._runner = subprocess.run if runner is None else runner
        self._platform = sys.platform if platform is None else str(platform)
        self._keychain_path = self._normalize_keychain_path(keychain_path)

    @staticmethod
    def _normalize_keychain_path(keychain_path: str | Path | None) -> str | None:
        if keychain_path is None:
            return None
        raw_path = os.fspath(keychain_path).strip()
        if not raw_path:
            raise ValueError("Explicit keychain path cannot be blank.")
        return str(Path(raw_path).expanduser().resolve(strict=False))

    @property
    def supported(self) -> bool:
        return self._platform == "darwin" and (
            not self._uses_default_runner or Path(MACOS_SECURITY_TOOL).is_file()
        )

    def reset(self) -> CredentialResetResult:
        """Delete all matching items, or raise with sanitized partial-result details."""

        if self._platform != "darwin":
            raise CredentialResetError("Application Keychain reset is supported only on macOS.")
        if not self.supported:
            raise CredentialResetError("The fixed macOS security tool is unavailable.")
        if (
            os.environ.get(_TEST_EXTERNAL_LAUNCH_BLOCK_ENV_VAR) == "1"
            and self._keychain_path is None
        ):
            raise CredentialResetError(
                "Application Keychain reset is disabled for test processes unless an isolated "
                "keychain path is supplied."
            )

        deleted_counts: dict[str, int] = {}
        failures: list[CredentialResetFailure] = []
        for service_name in APP_CREDENTIAL_SERVICES:
            deleted_count, failure = self._delete_all_for_service(service_name)
            deleted_counts[service_name] = deleted_count
            if failure is not None:
                failures.append(failure)

        result = CredentialResetResult(
            database_items_deleted=deleted_counts.get(DATABASE_CREDENTIAL_SERVICE, 0),
            soundcloud_items_deleted=deleted_counts.get(SOUNDCLOUD_CREDENTIAL_SERVICE, 0),
        )
        if failures:
            failure_summary = "; ".join(
                f"{failure.service_name}: {failure.reason}" for failure in failures
            )
            raise CredentialResetError(
                "Application Keychain reset was incomplete after removing "
                f"{result.total_items_deleted} app-owned credential item(s). "
                f"{failure_summary}",
                result=result,
                failures=tuple(failures),
            )
        return result

    def _delete_all_for_service(
        self,
        service_name: str,
    ) -> tuple[int, CredentialResetFailure | None]:
        command = [
            MACOS_SECURITY_TOOL,
            "delete-generic-password",
            "-s",
            service_name,
        ]
        if self._keychain_path is not None:
            command.append(self._keychain_path)

        deleted_count = 0
        for _attempt in range(MAX_DELETE_ATTEMPTS_PER_SERVICE):
            try:
                completed = self._runner(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    shell=False,
                    timeout=SECURITY_COMMAND_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                return deleted_count, CredentialResetFailure(
                    service_name=service_name,
                    reason="The macOS security tool timed out.",
                )
            except OSError:
                return deleted_count, CredentialResetFailure(
                    service_name=service_name,
                    reason="The macOS security tool could not be executed.",
                )
            except Exception:
                return deleted_count, CredentialResetFailure(
                    service_name=service_name,
                    reason="The macOS security tool failed unexpectedly.",
                )

            returncode = int(completed.returncode)
            if returncode == 0:
                deleted_count += 1
                continue
            if returncode == KEYCHAIN_ITEM_NOT_FOUND_STATUS:
                return deleted_count, None
            return deleted_count, CredentialResetFailure(
                service_name=service_name,
                reason=f"The macOS security tool exited with status {returncode}.",
                returncode=returncode,
            )

        return deleted_count, CredentialResetFailure(
            service_name=service_name,
            reason=(
                "The bounded Keychain deletion limit was reached before the namespace was empty."
            ),
        )


__all__ = [
    "CredentialResetError",
    "CredentialResetFailure",
    "CredentialResetResult",
    "MacOSCredentialResetService",
]

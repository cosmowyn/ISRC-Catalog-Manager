from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

import isrc_manager.credential_reset as credential_reset
from isrc_manager.credential_namespaces import (
    APP_CREDENTIAL_SERVICES,
    DATABASE_CREDENTIAL_SERVICE,
    SOUNDCLOUD_CREDENTIAL_SERVICE,
)
from isrc_manager.credential_reset import (
    KEYCHAIN_ITEM_NOT_FOUND_STATUS,
    MACOS_SECURITY_TOOL,
    CredentialResetError,
    MacOSCredentialResetService,
)
from isrc_manager.integrations.soundcloud.token_store import (
    DEFAULT_SOUNDCLOUD_KEYCHAIN_SERVICE,
)
from isrc_manager.services.database_security import DEFAULT_DATABASE_KEYRING_SERVICE

TEST_BLOCK_ENV_VAR = "ISRC_MANAGER_BLOCK_EXTERNAL_LAUNCHES"


class FakeSecurityRunner:
    def __init__(self, responses: dict[str, Sequence[int | BaseException]]) -> None:
        self.responses = {service: list(values) for service, values in responses.items()}
        self.calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    def __call__(self, command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        normalized_command = tuple(str(part) for part in command)
        self.calls.append((normalized_command, dict(kwargs)))
        service_name = normalized_command[3]
        response = self.responses[service_name].pop(0)
        if isinstance(response, BaseException):
            raise response
        return subprocess.CompletedProcess(
            normalized_command,
            response,
            stdout=b"raw-output-must-not-be-used",
            stderr=b"raw-error-must-not-be-used",
        )


def _isolated_keychain_path(tmp_path: Path) -> Path:
    return tmp_path / "credential-reset-tests.keychain-db"


def test_credential_service_constants_are_single_sourced() -> None:
    assert APP_CREDENTIAL_SERVICES == (
        "isrc-catalog-manager.database",
        "isrc-catalog-manager.soundcloud",
    )
    assert DEFAULT_DATABASE_KEYRING_SERVICE == DATABASE_CREDENTIAL_SERVICE
    assert DEFAULT_SOUNDCLOUD_KEYCHAIN_SERVICE == SOUNDCLOUD_CREDENTIAL_SERVICE


def test_reset_repeats_exact_service_only_deletions_and_suppresses_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TEST_BLOCK_ENV_VAR, "1")
    runner = FakeSecurityRunner(
        {
            DATABASE_CREDENTIAL_SERVICE: [0, 0, KEYCHAIN_ITEM_NOT_FOUND_STATUS],
            SOUNDCLOUD_CREDENTIAL_SERVICE: [0, KEYCHAIN_ITEM_NOT_FOUND_STATUS],
        }
    )
    keychain_path = _isolated_keychain_path(tmp_path)
    service = MacOSCredentialResetService(
        runner=runner,
        platform="darwin",
        keychain_path=keychain_path,
    )

    result = service.reset()

    assert service.supported is True
    assert result.database_items_deleted == 2
    assert result.soundcloud_items_deleted == 1
    assert result.total_items_deleted == 3
    expected_prefixes = [
        (MACOS_SECURITY_TOOL, "delete-generic-password", "-s", DATABASE_CREDENTIAL_SERVICE),
        (MACOS_SECURITY_TOOL, "delete-generic-password", "-s", DATABASE_CREDENTIAL_SERVICE),
        (MACOS_SECURITY_TOOL, "delete-generic-password", "-s", DATABASE_CREDENTIAL_SERVICE),
        (MACOS_SECURITY_TOOL, "delete-generic-password", "-s", SOUNDCLOUD_CREDENTIAL_SERVICE),
        (MACOS_SECURITY_TOOL, "delete-generic-password", "-s", SOUNDCLOUD_CREDENTIAL_SERVICE),
    ]
    assert [command[:-1] for command, _kwargs in runner.calls] == expected_prefixes
    assert all(command[-1] == str(keychain_path.resolve()) for command, _kwargs in runner.calls)
    for command, kwargs in runner.calls:
        assert "dump-keychain" not in command
        assert "-a" not in command
        assert "-l" not in command
        assert "*" not in command
        assert kwargs == {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "check": False,
            "shell": False,
            "timeout": credential_reset.SECURITY_COMMAND_TIMEOUT_SECONDS,
        }


def test_reset_is_idempotent_when_namespaces_are_already_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TEST_BLOCK_ENV_VAR, "1")
    runner = FakeSecurityRunner(
        {
            DATABASE_CREDENTIAL_SERVICE: [KEYCHAIN_ITEM_NOT_FOUND_STATUS],
            SOUNDCLOUD_CREDENTIAL_SERVICE: [KEYCHAIN_ITEM_NOT_FOUND_STATUS],
        }
    )
    service = MacOSCredentialResetService(
        runner=runner,
        platform="darwin",
        keychain_path=_isolated_keychain_path(tmp_path),
    )

    result = service.reset()

    assert result.total_items_deleted == 0
    assert len(runner.calls) == 2


def test_reset_attempts_both_namespaces_and_reports_sanitized_partial_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TEST_BLOCK_ENV_VAR, "1")
    runner = FakeSecurityRunner(
        {
            DATABASE_CREDENTIAL_SERVICE: [51],
            SOUNDCLOUD_CREDENTIAL_SERVICE: [0, KEYCHAIN_ITEM_NOT_FOUND_STATUS],
        }
    )
    service = MacOSCredentialResetService(
        runner=runner,
        platform="darwin",
        keychain_path=_isolated_keychain_path(tmp_path),
    )

    with pytest.raises(CredentialResetError) as caught:
        service.reset()

    error = caught.value
    assert error.result.database_items_deleted == 0
    assert error.result.soundcloud_items_deleted == 1
    assert error.result.total_items_deleted == 1
    assert len(error.failures) == 1
    assert error.failures[0].service_name == DATABASE_CREDENTIAL_SERVICE
    assert error.failures[0].returncode == 51
    assert "after removing 1 app-owned credential item(s)" in str(error)
    assert DATABASE_CREDENTIAL_SERVICE in str(error)
    assert "exited with status 51" in str(error)
    assert "raw-output-must-not-be-used" not in str(error)
    assert "raw-error-must-not-be-used" not in str(error)
    assert any(command[3] == SOUNDCLOUD_CREDENTIAL_SERVICE for command, _kwargs in runner.calls)


@pytest.mark.parametrize(
    ("runner_error", "expected_reason"),
    [
        (
            subprocess.TimeoutExpired("raw-secret-command", 1),
            "The macOS security tool timed out.",
        ),
        (OSError("raw-secret-os-error"), "The macOS security tool could not be executed."),
        (
            RuntimeError("raw-secret-unexpected-error"),
            "The macOS security tool failed unexpectedly.",
        ),
    ],
)
def test_reset_sanitizes_runner_exceptions_and_still_attempts_second_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_error: BaseException,
    expected_reason: str,
) -> None:
    monkeypatch.setenv(TEST_BLOCK_ENV_VAR, "1")
    runner = FakeSecurityRunner(
        {
            DATABASE_CREDENTIAL_SERVICE: [runner_error],
            SOUNDCLOUD_CREDENTIAL_SERVICE: [KEYCHAIN_ITEM_NOT_FOUND_STATUS],
        }
    )
    service = MacOSCredentialResetService(
        runner=runner,
        platform="darwin",
        keychain_path=_isolated_keychain_path(tmp_path),
    )

    with pytest.raises(CredentialResetError) as caught:
        service.reset()

    assert caught.value.failures[0].reason == expected_reason
    assert "raw-secret" not in str(caught.value)
    assert "raw-secret" not in caught.value.failures[0].reason
    assert any(command[3] == SOUNDCLOUD_CREDENTIAL_SERVICE for command, _kwargs in runner.calls)


def test_reset_bounds_each_namespace_deletion_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TEST_BLOCK_ENV_VAR, "1")
    monkeypatch.setattr(credential_reset, "MAX_DELETE_ATTEMPTS_PER_SERVICE", 2)
    runner = FakeSecurityRunner(
        {
            DATABASE_CREDENTIAL_SERVICE: [0, 0],
            SOUNDCLOUD_CREDENTIAL_SERVICE: [0, 0],
        }
    )
    service = MacOSCredentialResetService(
        runner=runner,
        platform="darwin",
        keychain_path=_isolated_keychain_path(tmp_path),
    )

    with pytest.raises(CredentialResetError) as caught:
        service.reset()

    assert caught.value.result.total_items_deleted == 4
    assert len(caught.value.failures) == 2
    assert len(runner.calls) == 4


def test_reset_refuses_unsupported_platform_without_calling_runner() -> None:
    runner = FakeSecurityRunner({})
    service = MacOSCredentialResetService(runner=runner, platform="linux")

    assert service.supported is False
    with pytest.raises(CredentialResetError, match="only on macOS"):
        service.reset()
    assert runner.calls == []


def test_default_runner_requires_fixed_security_tool_to_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(credential_reset, "MACOS_SECURITY_TOOL", "/missing/usr/bin/security")

    service = MacOSCredentialResetService(platform="darwin")

    assert service.supported is False
    with pytest.raises(CredentialResetError, match="security tool is unavailable"):
        service.reset()


def test_test_guard_refuses_default_keychain_search_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TEST_BLOCK_ENV_VAR, "1")
    runner = FakeSecurityRunner({})
    service = MacOSCredentialResetService(runner=runner, platform="darwin")

    with pytest.raises(CredentialResetError, match="isolated keychain path"):
        service.reset()
    assert runner.calls == []


def _run_security(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [MACOS_SECURITY_TOOL, *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        shell=False,
        timeout=30,
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Keychain integration test")
def test_reset_preserves_unrelated_canary_in_isolated_temporary_keychain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TEST_BLOCK_ENV_VAR, "1")
    keychain_path = _isolated_keychain_path(tmp_path)
    keychain = str(keychain_path)
    test_password = "isolated-test-keychain-password"
    created = _run_security("create-keychain", "-p", test_password, keychain)
    if created.returncode != 0:
        pytest.skip("Could not create an isolated temporary macOS Keychain.")

    try:
        assert _run_security("unlock-keychain", "-p", test_password, keychain).returncode == 0
        seeded_items = (
            (DATABASE_CREDENTIAL_SERVICE, "database-test-password"),
            (DATABASE_CREDENTIAL_SERVICE, "database-test-timestamp"),
            (SOUNDCLOUD_CREDENTIAL_SERVICE, "soundcloud-test-token"),
            ("unrelated.canary.service", "unrelated-canary-account"),
        )
        for service_name, account_name in seeded_items:
            assert (
                _run_security(
                    "add-generic-password",
                    "-s",
                    service_name,
                    "-a",
                    account_name,
                    "-w",
                    "test-value",
                    keychain,
                ).returncode
                == 0
            )

        result = MacOSCredentialResetService(
            platform="darwin",
            keychain_path=keychain_path,
        ).reset()

        assert result.database_items_deleted == 2
        assert result.soundcloud_items_deleted == 1
        for service_name in APP_CREDENTIAL_SERVICES:
            assert (
                _run_security("find-generic-password", "-s", service_name, keychain).returncode
                == KEYCHAIN_ITEM_NOT_FOUND_STATUS
            )
        assert (
            _run_security(
                "find-generic-password",
                "-s",
                "unrelated.canary.service",
                keychain,
            ).returncode
            == 0
        )
    finally:
        _run_security("delete-keychain", keychain)

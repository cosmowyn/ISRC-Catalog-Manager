from __future__ import annotations

import io
import json
import subprocess
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from scripts import cleanup_github_builds as cleanup
from scripts.cleanup_github_builds import (
    AuditRecorder,
    CleanupApplyError,
    GitHubApi,
    SemVer,
    build_parser,
    cleanup_repository,
    main,
    parse_stable_version,
    public_download_versions_from_repository,
    render_summary,
    retained_versions,
    version_from_build_name,
)


def release(version: str, asset_id: int, **overrides: Any) -> dict[str, Any]:
    tag = str(overrides.pop("tag_name", f"v{version}"))
    package_name = (
        f"ISRCManager-v{version}-linux-x64.tar.gz"
        if parse_stable_version(version) is not None
        else f"unclassified-{version}.zip"
    )
    item: dict[str, Any] = {
        "id": asset_id + 1_000_000,
        "tag_name": tag,
        "name": tag,
        "body": "",
        "html_url": f"https://github.example/releases/tag/{tag}",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "id": asset_id,
                "name": package_name,
                "size": 1_000,
                "browser_download_url": f"https://github.example/download/{package_name}",
            },
            {
                "id": asset_id + 100_000,
                "name": "SHA256SUMS.txt",
                "size": 100,
                "browser_download_url": "https://github.example/download/SHA256SUMS.txt",
            },
            {
                "id": asset_id + 200_000,
                "name": "latest.json",
                "size": 200,
                "browser_download_url": "https://github.example/download/latest.json",
            },
        ],
    }
    item.update(overrides)
    return item


def workflow_run(
    version: str,
    *,
    status: str = "completed",
    path: str = ".github/workflows/release-build.yml",
    event: str = "push",
) -> dict[str, Any]:
    return {
        "status": status,
        "conclusion": "success" if status == "completed" else None,
        "path": path,
        "event": event,
        "head_branch": f"v{version}",
    }


def artifact(
    version: str,
    artifact_id: int,
    *,
    run_id: int | None = None,
    expired: bool = False,
    name: str | None = None,
    size: int = 2_000,
) -> dict[str, Any]:
    run_id = artifact_id + 2_000_000 if run_id is None else run_id
    artifact_name = name or f"ISRCManager-v{version}-windows-x64.zip"
    return {
        "id": artifact_id,
        "name": artifact_name,
        "size_in_bytes": size,
        "expired": expired,
        "archive_download_url": f"https://api.github.example/artifacts/{artifact_id}/zip",
        "workflow_run": {"id": run_id} if run_id else None,
    }


class FakeApi:
    repository = "owner/repository"

    def __init__(
        self,
        releases: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        *,
        runs: dict[int, dict[str, Any] | None] | None = None,
        deployments: list[dict[str, Any]] | None = None,
        deployment_states: dict[int, str | None] | None = None,
        latest_release: dict[str, Any] | None = None,
        default_branch_head: tuple[str, str] = ("main", "a" * 40),
    ):
        self.releases = releases
        self.artifacts = artifacts
        self.runs = runs or {}
        self.deployments = deployments or []
        self.deployment_states = deployment_states or {}
        self.latest_release = latest_release or self._default_latest_release()
        self.default_branch_head = default_branch_head
        self.deleted_release_assets: list[int] = []
        self.deleted_artifacts: list[int] = []
        self.workflow_run_calls: list[int] = []
        self.fail_release_asset_ids: set[int] = set()
        self.fail_artifact_ids: set[int] = set()
        self.already_absent_release_asset_ids: set[int] = set()
        self.already_absent_artifact_ids: set[int] = set()

    def _default_latest_release(self) -> dict[str, Any] | None:
        stable = [
            item
            for item in self.releases
            if not item.get("draft")
            and not item.get("prerelease")
            and parse_stable_version(str(item.get("tag_name") or "")) is not None
        ]
        if not stable:
            return None
        return max(stable, key=lambda item: parse_stable_version(item["tag_name"]))

    def list_releases(self) -> list[dict[str, Any]]:
        return self.releases

    def get_latest_release(self) -> dict[str, Any] | None:
        return self.latest_release

    def get_default_branch_head(self) -> tuple[str, str]:
        return self.default_branch_head

    def list_artifacts(self) -> list[dict[str, Any]]:
        return self.artifacts

    def list_deployments(self) -> list[dict[str, Any]]:
        return self.deployments

    def get_latest_deployment_status(self, deployment_id: int) -> str | None:
        return self.deployment_states.get(deployment_id)

    def get_workflow_run(self, run_id: int) -> dict[str, Any] | None:
        self.workflow_run_calls.append(run_id)
        return self.runs.get(run_id)

    def delete_release_asset(self, asset_id: int | None) -> bool:
        assert asset_id is not None
        if asset_id in self.fail_release_asset_ids:
            raise RuntimeError(f"simulated release asset failure {asset_id}")
        self.deleted_release_assets.append(asset_id)
        return asset_id not in self.already_absent_release_asset_ids

    def delete_artifact(self, artifact_id: int | None) -> bool:
        assert artifact_id is not None
        if artifact_id in self.fail_artifact_ids:
            raise RuntimeError(f"simulated artifact failure {artifact_id}")
        self.deleted_artifacts.append(artifact_id)
        return artifact_id not in self.already_absent_artifact_ids


def test_retention_policy_keeps_exact_requested_release_lines() -> None:
    versions = {
        SemVer(6, 4, 5),
        SemVer(6, 4, 4),
        SemVer(6, 4, 3),
        SemVer(6, 4, 2),
        SemVer(6, 4, 1),
        SemVer(6, 3, 9),
        SemVer(6, 3, 8),
        SemVer(6, 2, 7),
        SemVer(6, 1, 99),
        SemVer(5, 9, 4),
        SemVer(5, 8, 20),
        SemVer(4, 99, 99),
    }

    assert retained_versions(versions) == {
        SemVer(6, 4, 5),
        SemVer(6, 4, 4),
        SemVer(6, 4, 3),
        SemVer(6, 4, 2),
        SemVer(6, 3, 9),
        SemVer(6, 2, 7),
        SemVer(5, 9, 4),
    }


@pytest.mark.parametrize("value", ["1.2", "1.2.3-rc.1", "1.2.3+build.4", "01.2.3", "release-1.2.3"])
def test_stable_parser_rejects_partial_prerelease_metadata_and_unparseable_values(
    value: str,
) -> None:
    assert parse_stable_version(value) is None


def test_build_name_parser_accepts_only_established_stable_packages() -> None:
    for name in (
        "ISRCManager-v6.1.3-linux-x64.tar.gz",
        "ISRCManager-v6.1.3-macos-arm64.zip",
        "ISRCManager-v6.1.3-windows-x64.zip",
    ):
        assert version_from_build_name(name) == (
            SemVer(6, 1, 3),
            "established stable build package",
        )

    for name in (
        "ISRCManager-v6.1.3-linux-rc.1.zip",
        "ISRCManager-v6.1.3-windows-beta.zip",
        "diagnostics-v6.1.3-windows-x64.zip",
        "sourcecode-v6.1.3-linux-x64.tar.gz",
        " ISRCManager-v6.1.3-linux-x64.tar.gz",
    ):
        assert version_from_build_name(name)[0] is None


def test_repository_public_reference_scan_is_narrow_and_versioned(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "README.md").write_text(
        "https://github.test/o/r/releases/download/v1.2.3/package.zip\n",
        encoding="utf-8",
    )
    (docs / "download.json").write_text(
        '{"url":"https://github.test/o/r/releases/download/v2.3.4/package.zip"}',
        encoding="utf-8",
    )
    (tmp_path / "private.py").write_text(
        "https://github.test/o/r/releases/download/v9.9.9/package.zip\n",
        encoding="utf-8",
    )

    assert public_download_versions_from_repository(tmp_path) == {
        SemVer(1, 2, 3),
        SemVer(2, 3, 4),
    }


def test_dry_run_never_deletes_and_audits_every_release_asset() -> None:
    old_run_id = 2_000_040
    api = FakeApi(
        [release("2.0.0", 10), release("1.0.0", 20), release("0.9.0", 30)],
        [
            artifact("0.9.0", 40, run_id=old_run_id),
            artifact("0.8.0", 41, name="coverage-data"),
            artifact("0.8.0", 42, name="ISRCManager-v0.8.0-linux-rc.1.zip"),
        ],
        runs={old_run_id: workflow_run("0.9.0")},
    )

    entries, keep = cleanup_repository(api)

    assert keep == {SemVer(2, 0, 0), SemVer(1, 0, 0)}
    assert api.deleted_release_assets == []
    assert api.deleted_artifacts == []
    assert {(entry.resource_id, entry.action) for entry in entries} >= {
        (30, "would-delete"),
        (40, "would-delete"),
        (41, "skip"),
        (42, "skip"),
    }
    release_asset_entries = [entry for entry in entries if entry.resource == "release-asset"]
    assert len(release_asset_entries) == 9
    assert all(entry.repository == "owner/repository" for entry in release_asset_entries)
    assert all(entry.timestamp_utc for entry in release_asset_entries)
    assert next(entry for entry in entries if entry.resource_id == 100_030).action == "keep"
    assert next(entry for entry in entries if entry.resource_id == 200_030).action == "keep"


def test_apply_deletes_only_completed_established_obsolete_builds(tmp_path: Path) -> None:
    old_run_id = 2_000_060
    prerelease = release(
        "1.4.0-rc.1",
        40,
        tag_name="v1.4.0-rc.1",
        prerelease=True,
    )
    api = FakeApi(
        [
            release("3.0.0", 10),
            release("2.0.0", 20),
            release("1.5.0", 30),
            prerelease,
            release("not-semver", 50),
        ],
        [
            artifact("1.5.0", 60, run_id=old_run_id),
            artifact("3.0.0", 61),
            artifact("1.0.0", 62, name="logs-v1.0.0.zip"),
        ],
        runs={old_run_id: workflow_run("1.5.0")},
    )
    audit_path = tmp_path / "audit.jsonl"

    with AuditRecorder(audit_path) as recorder:
        entries, _keep = cleanup_repository(
            api,
            apply=True,
            recorder=recorder,
            pre_delete_guard=lambda: None,
        )

    assert api.deleted_release_assets == [30]
    assert api.deleted_artifacts == [60]
    assert next(entry for entry in entries if entry.resource_id == 30).action == "deleted"
    assert next(entry for entry in entries if entry.resource_id == 60).action == "deleted"
    assert next(entry for entry in entries if entry.resource_id == 100_030).action == "keep"
    assert next(entry for entry in entries if entry.resource_id == 1_000_040).action == "skip"
    assert next(entry for entry in entries if entry.resource_id == 1_000_050).action == "skip"
    assert next(entry for entry in entries if entry.resource_id == 62).action == "skip"
    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert any(event["action"] == "deleting" for event in events)
    assert any(event["action"] == "deleted" for event in events)


def test_apply_requires_and_runs_a_pre_delete_repository_guard(tmp_path: Path) -> None:
    api = FakeApi(
        [release("3.0.0", 10), release("2.0.0", 20), release("1.5.0", 30)],
        [],
    )
    with AuditRecorder(tmp_path / "missing-guard.jsonl") as recorder:
        with pytest.raises(ValueError, match="pre-delete safety guard"):
            cleanup_repository(api, apply=True, recorder=recorder)

    def block_stale_checkout() -> None:
        raise RuntimeError("default branch advanced")

    with AuditRecorder(tmp_path / "blocked-guard.jsonl") as recorder:
        with pytest.raises(CleanupApplyError, match="repository guard failed") as error:
            cleanup_repository(
                api,
                apply=True,
                recorder=recorder,
                pre_delete_guard=block_stale_checkout,
            )

    assert api.deleted_release_assets == []
    assert any(
        entry.name == "pre-delete repository guard" and entry.action == "blocked"
        for entry in error.value.entries
    )


def test_apply_aborts_when_protection_state_changes_during_revalidation(
    tmp_path: Path,
) -> None:
    class ChangingApi(FakeApi):
        release_reads = 0

        def list_releases(self) -> list[dict[str, Any]]:
            self.release_reads += 1
            if self.release_reads == 2:
                self.releases[-1]["draft"] = True
            return super().list_releases()

    api = ChangingApi(
        [release("3.0.0", 10), release("2.0.0", 20), release("1.5.0", 30)],
        [],
    )

    with AuditRecorder(tmp_path / "audit.jsonl") as recorder:
        with pytest.raises(CleanupApplyError, match="inventory changed") as error:
            cleanup_repository(
                api,
                apply=True,
                recorder=recorder,
                pre_delete_guard=lambda: None,
            )

    assert api.deleted_release_assets == []
    assert api.deleted_artifacts == []
    assert any(
        entry.action == "blocked" and entry.name == "pre-delete inventory revalidation"
        for entry in error.value.entries
    )


def test_draft_and_prerelease_version_cores_protect_actions_artifacts() -> None:
    draft = release("1.5.0", 30, draft=True)
    prerelease = release(
        "1.4.0-rc.1",
        40,
        tag_name="v1.4.0-rc.1",
        prerelease=True,
    )
    api = FakeApi(
        [release("3.0.0", 10), release("2.0.0", 20), draft, prerelease],
        [artifact("1.5.0", 50), artifact("1.4.0", 51)],
    )

    entries, _keep = cleanup_repository(api)

    assert next(entry for entry in entries if entry.resource_id == 50).action == "keep"
    assert next(entry for entry in entries if entry.resource_id == 51).action == "keep"
    assert api.workflow_run_calls == []


@pytest.mark.parametrize("deployment_state", ["success", "in_progress", None])
def test_active_or_unknown_deployment_ref_protects_version(deployment_state: str | None) -> None:
    deployment = {"id": 700, "ref": "refs/tags/v1.5.0", "payload": {}}
    api = FakeApi(
        [release("3.0.0", 10), release("2.0.0", 20), release("1.5.0", 30)],
        [artifact("1.5.0", 60)],
        deployments=[deployment],
        deployment_states={700: deployment_state},
    )

    entries, _keep = cleanup_repository(api)

    assert next(entry for entry in entries if entry.resource_id == 30).action == "keep"
    assert next(entry for entry in entries if entry.resource_id == 60).action == "keep"


def test_inactive_deployment_does_not_block_completed_obsolete_build() -> None:
    run_id = 2_000_060
    deployment = {"id": 700, "ref": "v1.5.0", "payload": {}}
    api = FakeApi(
        [release("3.0.0", 10), release("2.0.0", 20), release("1.5.0", 30)],
        [artifact("1.5.0", 60, run_id=run_id)],
        runs={run_id: workflow_run("1.5.0")},
        deployments=[deployment],
        deployment_states={700: "inactive"},
    )

    entries, _keep = cleanup_repository(api)

    assert next(entry for entry in entries if entry.resource_id == 30).action == "would-delete"
    assert next(entry for entry in entries if entry.resource_id == 60).action == "would-delete"


def test_latest_release_and_explicit_public_links_protect_old_versions() -> None:
    current = release("3.0.0", 10, body="/releases/download/v1.4.0/package.zip")
    previous = release("2.0.0", 20)
    public_latest = release("1.5.0", 30)
    linked = release("1.4.0", 40)
    api = FakeApi(
        [current, previous, public_latest, linked],
        [artifact("1.5.0", 60), artifact("1.4.0", 61)],
        latest_release=public_latest,
    )

    entries, _keep = cleanup_repository(api)

    assert next(entry for entry in entries if entry.resource_id == 30).action == "keep"
    assert next(entry for entry in entries if entry.resource_id == 40).action == "keep"
    assert next(entry for entry in entries if entry.resource_id == 60).action == "keep"
    assert next(entry for entry in entries if entry.resource_id == 61).action == "keep"


def test_actions_artifact_requires_completed_matching_release_build_producer() -> None:
    artifacts = [
        artifact("1.5.0", 60, run_id=100),
        artifact("1.5.0", 61, run_id=101),
        artifact("1.5.0", 62, run_id=102),
        artifact("1.5.0", 63, run_id=103),
        artifact("1.5.0", 64, run_id=104),
        artifact("1.5.0", 65, run_id=105, expired=True),
        artifact("1.5.0", 66, run_id=0),
        artifact("1.5.0", 67, run_id=100, name="ISRCManager-v1.5.0-macos-arm64.zip"),
    ]
    mismatched = workflow_run("1.6.0")
    api = FakeApi(
        [release("3.0.0", 10), release("2.0.0", 20), release("1.5.0", 30)],
        artifacts,
        runs={
            100: workflow_run("1.5.0"),
            101: workflow_run("1.5.0", status="in_progress"),
            102: workflow_run("1.5.0", path=".github/workflows/ci.yml"),
            103: workflow_run("1.5.0", event="workflow_dispatch"),
            104: mismatched,
        },
    )

    entries, _keep = cleanup_repository(api)

    decisions = {
        entry.resource_id: entry.action for entry in entries if entry.resource_id in range(60, 68)
    }
    assert decisions == {
        60: "would-delete",
        61: "skip",
        62: "skip",
        63: "skip",
        64: "skip",
        65: "skip",
        66: "skip",
        67: "would-delete",
    }
    assert api.workflow_run_calls.count(100) == 1
    assert 105 not in api.workflow_run_calls


@pytest.mark.parametrize(
    ("max_deletions", "max_delete_bytes"),
    [(0, 10_000), (10, 999)],
)
def test_apply_ceiling_blocks_before_any_delete(
    tmp_path: Path, max_deletions: int, max_delete_bytes: int
) -> None:
    api = FakeApi(
        [release("3.0.0", 10), release("2.0.0", 20), release("1.5.0", 30)],
        [],
    )

    with AuditRecorder(tmp_path / "audit.jsonl") as recorder:
        with pytest.raises(CleanupApplyError, match="deletion ceilings") as error:
            cleanup_repository(
                api,
                apply=True,
                recorder=recorder,
                max_deletions=max_deletions,
                max_delete_bytes=max_delete_bytes,
                pre_delete_guard=lambda: None,
            )

    assert api.deleted_release_assets == []
    assert any(entry.action == "blocked" for entry in error.value.entries)


def test_partial_apply_failure_keeps_durable_per_item_audit(tmp_path: Path) -> None:
    old = release("1.5.0", 30)
    second_asset = {
        "id": 31,
        "name": "ISRCManager-v1.5.0-windows-x64.zip",
        "size": 1_500,
        "browser_download_url": "https://github.example/download/windows.zip",
    }
    old["assets"].append(second_asset)
    api = FakeApi([release("3.0.0", 10), release("2.0.0", 20), old], [])
    api.fail_release_asset_ids.add(31)
    audit_path = tmp_path / "audit.jsonl"

    with AuditRecorder(audit_path) as recorder:
        with pytest.raises(CleanupApplyError, match="simulated release asset failure") as error:
            cleanup_repository(
                api,
                apply=True,
                recorder=recorder,
                pre_delete_guard=lambda: None,
            )

    assert api.deleted_release_assets == [30]
    assert (
        next(entry for entry in error.value.entries if entry.resource_id == 30).action == "deleted"
    )
    assert next(entry for entry in error.value.entries if entry.resource_id == 31).action == "error"
    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert any(event["resource_id"] == 30 and event["action"] == "deleted" for event in events)
    assert any(event["resource_id"] == 31 and event["action"] == "error" for event in events)


def test_already_absent_delete_is_an_idempotent_success(tmp_path: Path) -> None:
    api = FakeApi(
        [release("3.0.0", 10), release("2.0.0", 20), release("1.5.0", 30)],
        [],
    )
    api.already_absent_release_asset_ids.add(30)

    with AuditRecorder(tmp_path / "audit.jsonl") as recorder:
        entries, _keep = cleanup_repository(
            api,
            apply=True,
            recorder=recorder,
            pre_delete_guard=lambda: None,
        )

    assert next(entry for entry in entries if entry.resource_id == 30).action == "already-absent"


def test_api_distinguishes_delete_204_from_idempotent_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = GitHubApi("owner/repository", "token", "https://api.example.test")

    class EmptyResponse:
        def __enter__(self) -> EmptyResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b""

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: EmptyResponse())
    assert api.delete_artifact(123) is True

    def not_found(*_args: Any, **_kwargs: Any) -> Any:
        raise urllib.error.HTTPError(
            "https://api.example.test/resource",
            404,
            "Not Found",
            {},
            io.BytesIO(b'{"message":"not found"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", not_found)
    assert api.delete_artifact(123) is False


def test_api_paginates_and_rejects_malformed_or_incomplete_collections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = GitHubApi("owner/repository", "token", "https://api.example.test")
    calls: list[str] = []

    def request(_method: str, path: str) -> Any:
        calls.append(path)
        if path.endswith("page=1"):
            return {"total_count": 101, "artifacts": [{"id": index} for index in range(100)]}
        return {"total_count": 101, "artifacts": [{"id": 100}]}

    monkeypatch.setattr(api, "request", request)
    assert len(api.list_artifacts()) == 101
    assert calls[-1].endswith("page=2")

    for payload, message in (
        ({"total_count": 0}, "did not contain"),
        ({"total_count": 1, "artifacts": "invalid"}, "invalid collection"),
        ({"total_count": 1, "artifacts": [None]}, "invalid item"),
        ({"total_count": 2, "artifacts": [{"id": 1}]}, "returned 1 of 2"),
    ):
        monkeypatch.setattr(api, "request", lambda *_args, value=payload: value)
        with pytest.raises(RuntimeError, match=message):
            api.list_artifacts()


def test_api_resolves_and_validates_the_current_default_branch_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = GitHubApi("owner/repository", "token", "https://api.example.test")
    calls: list[str] = []

    def request(_method: str, path: str) -> Any:
        calls.append(path)
        if path == "/repos/owner/repository":
            return {"default_branch": "release/current"}
        return {"sha": "a" * 40}

    monkeypatch.setattr(api, "request", request)

    assert api.get_default_branch_head() == ("release/current", "a" * 40)
    assert calls[-1] == "/repos/owner/repository/commits/release%2Fcurrent"

    monkeypatch.setattr(api, "request", lambda *_args, **_kwargs: {"default_branch": ""})
    with pytest.raises(RuntimeError, match="default branch"):
        api.get_default_branch_head()


def test_apply_checkout_attestation_rejects_stale_sha_and_non_root_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = "a" * 40
    api = FakeApi([], [], default_branch_head=("main", expected))
    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        cleanup,
        "_repository_head_with_clean_public_surfaces",
        lambda _root: expected,
    )

    cleanup._verify_apply_checkout(api, repository_root, expected)
    api.default_branch_head = ("main", "b" * 40)
    with pytest.raises(RuntimeError, match="current main tip"):
        cleanup._verify_apply_checkout(api, repository_root, expected)
    with pytest.raises(RuntimeError, match="40 lowercase hex"):
        cleanup._verify_apply_checkout(api, repository_root, "not-a-sha")

    monkeypatch.undo()
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    subprocess.run(["git", "init", "-q", str(repository_root)], check=True, timeout=30)
    (repository_root / "scripts").mkdir()
    with pytest.raises(RuntimeError, match="Git worktree root"):
        cleanup._repository_head_with_clean_public_surfaces(repository_root / "scripts")


@pytest.mark.parametrize(
    "index_records",
    [
        b"S docs/releases/latest.json\0",
        b"h README.md\0",
    ],
)
def test_apply_checkout_rejects_incomplete_public_index(index_records: bytes) -> None:
    with pytest.raises(RuntimeError, match="skip-worktree or assume-unchanged"):
        cleanup._reject_incomplete_public_index(index_records)

    cleanup._reject_incomplete_public_index(
        b"H README.md\0H RELEASE_NOTES.md\0H docs/releases/latest.json\0"
    )


def test_cleanup_rejects_malformed_inventory_before_delete() -> None:
    malformed = artifact("1.5.0", 60)
    malformed.pop("size_in_bytes")
    api = FakeApi(
        [release("3.0.0", 10), release("2.0.0", 20), release("1.5.0", 30)],
        [malformed],
    )

    with pytest.raises(RuntimeError, match="invalid artifact 0 size"):
        cleanup_repository(api)

    assert api.deleted_release_assets == []
    assert api.deleted_artifacts == []


def test_api_reports_http_errors_without_exposing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    api = GitHubApi("owner/repository", "top-secret-token", "https://api.example.test")

    def fail_request(*_args: Any, **_kwargs: Any) -> Any:
        raise urllib.error.HTTPError(
            "https://api.example.test/resource",
            403,
            "Forbidden",
            {},
            io.BytesIO(b'{"message":"permission denied"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", fail_request)
    with pytest.raises(RuntimeError, match="HTTP 403") as error:
        api.request("GET", "/resource")
    assert "top-secret-token" not in str(error.value)


def test_summary_reports_sizes_and_apply_requires_audit_log() -> None:
    api = FakeApi(
        [release("3.0.0", 10), release("2.0.0", 20), release("1.5.0", 30)],
        [],
    )
    entries, keep = cleanup_repository(api)

    summary = render_summary(entries, keep, apply=False)

    assert "| would-delete | 1 | 0.000 GiB |" in summary
    assert "| Resource | ID | Name | Version | Size |" in summary
    assert build_parser().parse_args([]).apply is False
    with pytest.raises(SystemExit, match="--audit-log is required"):
        main(["--repository", "owner/repository", "--apply"])
    with pytest.raises(SystemExit, match="--expected-default-sha is required"):
        main(
            [
                "--repository",
                "owner/repository",
                "--audit-log",
                "audit.jsonl",
                "--apply",
            ]
        )


def test_cleanup_workflow_separates_read_only_plan_and_guarded_apply() -> None:
    workflow = Path(".github/workflows/cleanup-build-artifacts.yml").read_text(encoding="utf-8")

    assert "plan:" in workflow
    assert "actions: read" in workflow
    assert "contents: read" in workflow
    assert "apply:" in workflow
    assert "github.event_name == 'schedule'" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "github.ref == format('refs/heads/{0}'" in workflow
    assert 'current_default_sha="$(' in workflow
    assert 'current_default_sha" != "$GITHUB_SHA' in workflow
    assert "refusing stale public-link analysis" in workflow
    assert '--expected-default-sha "$GITHUB_SHA"' in workflow
    assert "--apply" in workflow
    assert workflow.count("retention-days: 30") == 2

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import trusted_ci_artifacts as trust

REPOSITORY = "cosmowyn/ISRC-Catalog-Manager"
REPOSITORY_ID = 4242
DEFAULT_BRANCH = "main"
TRUSTED_SHA = "a" * 40
FORGED_SHA = "b" * 40


def _run(
    run_id: int,
    source_commit: str,
    *,
    event: str = "push",
    conclusion: str = "success",
    repository: str = REPOSITORY,
    repository_id: int = REPOSITORY_ID,
) -> dict[str, object]:
    return {
        "id": run_id,
        "event": event,
        "status": "completed",
        "conclusion": conclusion,
        "head_branch": DEFAULT_BRANCH,
        "head_sha": source_commit,
        "path": ".github/workflows/ci.yml",
        "repository": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
        "head_repository": {"id": repository_id, "full_name": repository},
    }


def _artifact(
    artifact_id: int,
    run_id: int,
    source_commit: str,
    *,
    name: str = "ui-pq-canonical",
    created_at: str = "2026-08-08T10:00:00Z",
    repository_id: int = REPOSITORY_ID,
) -> dict[str, object]:
    return {
        "id": artifact_id,
        "name": name,
        "expired": False,
        "created_at": created_at,
        "workflow_run": {
            "id": run_id,
            "repository_id": repository_id,
            "head_repository_id": repository_id,
            "head_branch": DEFAULT_BRANCH,
            "head_sha": source_commit,
        },
    }


def test_latest_baseline_ignores_newer_fork_pr_named_main() -> None:
    trusted = _run(10, TRUSTED_SHA)
    forged = _run(
        20,
        FORGED_SHA,
        event="pull_request",
        repository="attacker/ISRC-Catalog-Manager",
        repository_id=9999,
    )
    artifacts = {
        "artifacts": [
            _artifact(200, 20, FORGED_SHA, created_at="2026-08-08T12:00:00Z"),
            _artifact(100, 10, TRUSTED_SHA, created_at="2026-08-08T10:00:00Z"),
        ]
    }

    selected = trust.select_latest_artifact(
        artifacts,
        {"workflow_runs": [forged, trusted]},
        artifact_name="ui-pq-canonical",
        repository=REPOSITORY,
        repository_id=REPOSITORY_ID,
        default_branch=DEFAULT_BRANCH,
        current_run_id=30,
    )

    assert selected == trust.ArtifactCandidate(
        artifact_id=100,
        run_id=10,
        source_commit=TRUSTED_SHA,
    )


@pytest.mark.parametrize(
    "override",
    [
        {"event": "pull_request"},
        {"conclusion": "failure"},
        {"path": ".github/workflows/release-build.yml"},
        {"head_repository": {"id": 9999, "full_name": "attacker/repository"}},
    ],
)
def test_exact_run_artifact_rejects_untrusted_producer(override: dict[str, object]) -> None:
    producer = _run(10, TRUSTED_SHA)
    producer.update(override)

    with pytest.raises(trust.ArtifactTrustError, match="producer run is not trusted"):
        trust.select_run_artifact(
            {"artifacts": [_artifact(100, 10, TRUSTED_SHA, name="help-documentation-pq")]},
            producer,
            artifact_name="help-documentation-pq",
            repository=REPOSITORY,
            repository_id=REPOSITORY_ID,
            default_branch=DEFAULT_BRANCH,
            expected_run_id=10,
            expected_source_commit=TRUSTED_SHA,
        )


def test_exact_run_artifact_rejects_mismatched_artifact_provenance() -> None:
    selected = trust.select_run_artifact(
        {
            "artifacts": [
                _artifact(
                    100,
                    10,
                    FORGED_SHA,
                    name="help-documentation-pq",
                )
            ]
        },
        _run(10, TRUSTED_SHA),
        artifact_name="help-documentation-pq",
        repository=REPOSITORY,
        repository_id=REPOSITORY_ID,
        default_branch=DEFAULT_BRANCH,
        expected_run_id=10,
        expected_source_commit=TRUSTED_SHA,
    )

    assert selected is None


def test_cli_writes_only_validated_numeric_and_commit_outputs(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts.json"
    runs = tmp_path / "runs.json"
    output = tmp_path / "github-output.txt"
    artifacts.write_text(json.dumps({"artifacts": [_artifact(100, 10, TRUSTED_SHA)]}))
    runs.write_text(json.dumps({"workflow_runs": [_run(10, TRUSTED_SHA)]}))

    status = trust.main(
        [
            "latest",
            "--artifacts",
            str(artifacts),
            "--runs",
            str(runs),
            "--artifact-name",
            "ui-pq-canonical",
            "--repository",
            REPOSITORY,
            "--repository-id",
            str(REPOSITORY_ID),
            "--default-branch",
            DEFAULT_BRANCH,
            "--current-run-id",
            "30",
            "--github-output",
            str(output),
        ]
    )

    assert status == 0
    assert output.read_text(encoding="utf-8").splitlines() == [
        "available=true",
        "artifact_id=100",
        "run_id=10",
        f"source_commit={TRUSTED_SHA}",
    ]


def test_workflows_bind_reuse_and_privileged_help_publish_to_trusted_runs() -> None:
    root = Path(__file__).resolve().parents[1]
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    help_workflow = (root / ".github" / "workflows" / "help-docs-refresh.yml").read_text(
        encoding="utf-8"
    )

    assert "scripts/trusted_ci_artifacts.py latest" in ci
    assert '--baseline-source-commit "$BASELINE_SOURCE_COMMIT"' in ci
    assert "scripts/qa_pq_runtime.py capture" in ci
    assert "scripts/qa_pq_runtime.py verify" in ci
    assert "github.event.workflow_run.event == 'push'" in help_workflow
    assert "github.event.workflow_run.head_repository.id == github.event.repository.id" in (
        help_workflow
    )
    assert "scripts/trusted_ci_artifacts.py run" in help_workflow
    assert "artifact-ids: ${{ steps.artifact.outputs.artifact_id }}" in help_workflow
    assert "scripts/apply_help_screenshots.py" in help_workflow
    assert 'commit_subject" == "Update QA/PQ dashboard data [skip ci]' in help_workflow
    assert "docs/validation/qa_pq_history.csv|" in help_workflow
    assert "git diff --name-only --no-renames -z" in help_workflow
    assert 'git switch --detach "$current_sha"' in help_workflow
    assert "cp -R" not in help_workflow

"""Select GitHub artifacts only after attesting their CI producer run."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


class ArtifactTrustError(ValueError):
    """Raised when GitHub inventory cannot be validated safely."""


@dataclass(frozen=True)
class TrustedRun:
    run_id: int
    repository_id: int
    source_commit: str
    head_branch: str


@dataclass(frozen=True)
class ArtifactCandidate:
    artifact_id: int
    run_id: int
    source_commit: str


def load_object(path: Path) -> dict[str, Any]:
    """Load one fail-closed GitHub API response object."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactTrustError(f"cannot read GitHub inventory {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactTrustError(f"GitHub inventory must be an object: {path}")
    return value


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _repository_identity(value: object) -> tuple[int | None, str]:
    if not isinstance(value, Mapping):
        return None, ""
    name = value.get("full_name")
    return _positive_int(value.get("id")), name if isinstance(name, str) else ""


def attest_ci_run(
    run: Mapping[str, Any],
    *,
    repository: str,
    repository_id: int,
    default_branch: str,
    expected_run_id: int | None = None,
    expected_source_commit: str | None = None,
) -> TrustedRun | None:
    """Attest a completed base-repository CI push to the default branch."""
    run_id = _positive_int(run.get("id"))
    source_commit = run.get("head_sha")
    workflow_path = str(run.get("path") or "").split("@", 1)[0]
    repo_id, repo_name = _repository_identity(run.get("repository"))
    head_repo_id, head_repo_name = _repository_identity(run.get("head_repository"))
    if (
        run_id is None
        or (expected_run_id is not None and run_id != expected_run_id)
        or run.get("event") != "push"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("head_branch") != default_branch
        or workflow_path != CI_WORKFLOW_PATH
        or not isinstance(source_commit, str)
        or _SHA_PATTERN.fullmatch(source_commit) is None
        or (expected_source_commit is not None and source_commit != expected_source_commit)
        or repo_id != repository_id
        or head_repo_id != repository_id
        or repo_name.casefold() != repository.casefold()
        or head_repo_name.casefold() != repository.casefold()
    ):
        return None
    return TrustedRun(
        run_id=run_id,
        repository_id=repository_id,
        source_commit=source_commit,
        head_branch=default_branch,
    )


def _artifact_candidate(
    artifact: Mapping[str, Any],
    *,
    artifact_name: str,
    trusted_run: TrustedRun,
) -> tuple[str, int, ArtifactCandidate] | None:
    artifact_id = _positive_int(artifact.get("id"))
    producer = artifact.get("workflow_run")
    created_at = artifact.get("created_at")
    if (
        artifact.get("name") != artifact_name
        or artifact.get("expired") is not False
        or artifact_id is None
        or not isinstance(producer, Mapping)
        or not isinstance(created_at, str)
        or not created_at
        or producer.get("id") != trusted_run.run_id
        or producer.get("repository_id") != trusted_run.repository_id
        or producer.get("head_repository_id") != trusted_run.repository_id
        or producer.get("head_branch") != trusted_run.head_branch
        or producer.get("head_sha") != trusted_run.source_commit
    ):
        return None
    return (
        created_at,
        artifact_id,
        ArtifactCandidate(
            artifact_id=artifact_id,
            run_id=trusted_run.run_id,
            source_commit=trusted_run.source_commit,
        ),
    )


def _artifact_list(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise ArtifactTrustError("artifact inventory has no artifacts list")
    if not all(isinstance(artifact, Mapping) for artifact in artifacts):
        raise ArtifactTrustError("artifact inventory contains a non-object")
    return artifacts


def select_latest_artifact(
    artifacts_payload: Mapping[str, Any],
    runs_payload: Mapping[str, Any],
    *,
    artifact_name: str,
    repository: str,
    repository_id: int,
    default_branch: str,
    current_run_id: int,
) -> ArtifactCandidate | None:
    """Select the newest named artifact from a trusted prior CI main push."""
    runs = runs_payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise ArtifactTrustError("workflow-run inventory has no workflow_runs list")
    if not all(isinstance(run, Mapping) for run in runs):
        raise ArtifactTrustError("workflow-run inventory contains a non-object")

    trusted: dict[int, TrustedRun] = {}
    for run in runs:
        attested = attest_ci_run(
            run,
            repository=repository,
            repository_id=repository_id,
            default_branch=default_branch,
        )
        if attested is None or attested.run_id == current_run_id:
            continue
        if attested.run_id in trusted:
            raise ArtifactTrustError(f"duplicate workflow run id: {attested.run_id}")
        trusted[attested.run_id] = attested

    candidates: list[tuple[str, int, ArtifactCandidate]] = []
    for artifact in _artifact_list(artifacts_payload):
        producer = artifact.get("workflow_run")
        run_id = producer.get("id") if isinstance(producer, Mapping) else None
        trusted_run = trusted.get(run_id) if isinstance(run_id, int) else None
        if trusted_run is None:
            continue
        candidate = _artifact_candidate(
            artifact,
            artifact_name=artifact_name,
            trusted_run=trusted_run,
        )
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def select_run_artifact(
    artifacts_payload: Mapping[str, Any],
    run_payload: Mapping[str, Any],
    *,
    artifact_name: str,
    repository: str,
    repository_id: int,
    default_branch: str,
    expected_run_id: int,
    expected_source_commit: str,
) -> ArtifactCandidate | None:
    """Select a named artifact from one externally identified trusted CI run."""
    trusted_run = attest_ci_run(
        run_payload,
        repository=repository,
        repository_id=repository_id,
        default_branch=default_branch,
        expected_run_id=expected_run_id,
        expected_source_commit=expected_source_commit,
    )
    if trusted_run is None:
        raise ArtifactTrustError("the requested CI producer run is not trusted")
    candidates = [
        candidate
        for artifact in _artifact_list(artifacts_payload)
        if (
            candidate := _artifact_candidate(
                artifact,
                artifact_name=artifact_name,
                trusted_run=trusted_run,
            )
        )
        is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def _write_github_output(path: Path, candidate: ArtifactCandidate | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values: dict[str, object] = {"available": candidate is not None}
    if candidate is not None:
        values.update(asdict(candidate))
    with path.open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            serialized = str(value).lower() if isinstance(value, bool) else str(value)
            stream.write(f"{key}={serialized}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--artifacts", type=Path, required=True)
    common.add_argument("--artifact-name", required=True)
    common.add_argument("--repository", required=True)
    common.add_argument("--repository-id", type=int, required=True)
    common.add_argument("--default-branch", required=True)
    common.add_argument("--github-output", type=Path, required=True)

    latest = subparsers.add_parser("latest", parents=[common])
    latest.add_argument("--runs", type=Path, required=True)
    latest.add_argument("--current-run-id", type=int, required=True)

    exact = subparsers.add_parser("run", parents=[common])
    exact.add_argument("--run", type=Path, required=True)
    exact.add_argument("--expected-run-id", type=int, required=True)
    exact.add_argument("--expected-source-commit", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        artifacts = load_object(args.artifacts)
        common = {
            "artifact_name": args.artifact_name,
            "repository": args.repository,
            "repository_id": args.repository_id,
            "default_branch": args.default_branch,
        }
        if args.command == "latest":
            candidate = select_latest_artifact(
                artifacts,
                load_object(args.runs),
                current_run_id=args.current_run_id,
                **common,
            )
        else:
            candidate = select_run_artifact(
                artifacts,
                load_object(args.run),
                expected_run_id=args.expected_run_id,
                expected_source_commit=args.expected_source_commit,
                **common,
            )
    except ArtifactTrustError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _write_github_output(args.github_output, candidate)
    json.dump(asdict(candidate) if candidate is not None else None, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

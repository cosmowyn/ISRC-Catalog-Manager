"""Conservatively remove obsolete GitHub build artifacts and release assets."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import subprocess
import sys
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    from .github_build_cleanup_audit import (
        AuditContext,
        AuditEntry,
        AuditRecorder,
        CleanupApplyError,
        SemVer,
        render_summary,
    )
    from .github_cleanup_api import (
        GitHubApi,
        positive_int,
        validate_inventory,
        validate_workflow_run,
    )
except ImportError:  # Direct ``python scripts/cleanup_github_builds.py`` execution.
    from github_build_cleanup_audit import (  # type: ignore[import-not-found,no-redef]
        AuditContext,
        AuditEntry,
        AuditRecorder,
        CleanupApplyError,
        SemVer,
        render_summary,
    )
    from github_cleanup_api import (  # type: ignore[import-not-found,no-redef]
        GitHubApi,
        positive_int,
        validate_inventory,
        validate_workflow_run,
    )

STABLE_VERSION_RE = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
VERSION_CORE_RE = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")
BUILD_NAME_RE = re.compile(
    r"^ISRCManager-v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-"
    r"(?:linux-x64\.tar\.gz|macos-arm64\.zip|windows-x64\.zip)$"
)
PUBLIC_DOWNLOAD_VERSION_RE = re.compile(
    r"/releases/download/v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)/"
)
PUBLIC_TEXT_SUFFIXES = {".html", ".json", ".md", ".rst", ".txt"}
PUBLIC_TEXT_ROOT_FILES = {"README.md", "RELEASE_NOTES.md"}
RELEASE_WORKFLOW_PATH = ".github/workflows/release-build.yml"
RELEASE_WORKFLOW_EVENT = "push"
INACTIVE_DEPLOYMENT_STATES = {"error", "failure", "inactive"}
DEFAULT_MAX_DELETIONS = 500
DEFAULT_MAX_DELETE_BYTES = 120 * 1024 * 1024 * 1024
MAX_PUBLIC_TEXT_BYTES = 5 * 1024 * 1024


def parse_stable_version(value: str) -> SemVer | None:
    """Parse only complete, stable SemVer values, with an optional leading ``v``."""
    match = STABLE_VERSION_RE.fullmatch(value.strip())
    if match is None:
        return None
    return SemVer(*(int(part) for part in match.groups()))


def parse_version_core(value: str) -> SemVer | None:
    """Return a SemVer core from a stable or prerelease tag for protection only."""
    match = VERSION_CORE_RE.fullmatch(value.strip())
    if match is None:
        return None
    return SemVer(*(int(part) for part in match.groups()))


def retained_versions(versions: Iterable[SemVer]) -> set[SemVer]:
    """Select versions retained by the project's strict stable-release policy."""
    available = set(versions)
    if not available:
        return set()

    current = max(available)
    retained = {current}
    current_line = sorted(
        (
            version
            for version in available
            if (version.major, version.minor) == (current.major, current.minor)
        ),
        reverse=True,
    )
    retained.update(current_line[1:4])

    for minor in (current.minor - 1, current.minor - 2):
        if minor < 0:
            continue
        line = [
            version
            for version in available
            if version.major == current.major and version.minor == minor
        ]
        if line:
            retained.add(max(line))

    preceding_major = [version for version in available if version.major == current.major - 1]
    if preceding_major:
        retained.add(max(preceding_major))
    return retained


def version_from_build_name(name: str) -> tuple[SemVer | None, str]:
    """Extract a version only from the repository's exact release-package names."""
    match = BUILD_NAME_RE.fullmatch(name)
    if match is None:
        return None, "not an established ISRCManager release package name"
    return SemVer(*(int(part) for part in match.groups())), "established stable build package"


def is_downloadable_build_name(name: str) -> bool:
    return BUILD_NAME_RE.fullmatch(name) is not None


def public_download_versions_from_text(text: str) -> set[SemVer]:
    return {
        SemVer(*(int(part) for part in match.groups()))
        for match in PUBLIC_DOWNLOAD_VERSION_RE.finditer(text)
    }


def public_download_versions_from_repository(root: Path) -> set[SemVer]:
    """Find explicit versioned download links in the repository's public text surfaces."""
    if not root.is_dir():
        raise RuntimeError(f"repository root is not a directory: {root}")

    paths = {root / name for name in PUBLIC_TEXT_ROOT_FILES if (root / name).exists()}
    docs_root = root / "docs"
    if docs_root.exists():
        if docs_root.is_symlink() or not docs_root.is_dir():
            raise RuntimeError("public docs path must be a real directory")
        paths.update(
            path for path in docs_root.rglob("*") if path.suffix.lower() in PUBLIC_TEXT_SUFFIXES
        )

    versions: set[SemVer] = set()
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"public text path is not a regular file: {path}")
        if path.stat().st_size > MAX_PUBLIC_TEXT_BYTES:
            raise RuntimeError(f"public text path exceeds the safety limit: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(f"could not inspect public download references in {path}") from exc
        versions.update(public_download_versions_from_text(text))
    return versions


def _workflow_run_id(item: dict[str, Any]) -> int | None:
    workflow_run = item.get("workflow_run")
    if not isinstance(workflow_run, dict):
        return None
    run_id = workflow_run.get("id")
    return run_id if type(run_id) is int and run_id > 0 else None


def _entry(
    context: AuditContext,
    resource: str,
    item: dict[str, Any],
    version: SemVer | None,
    action: str,
    reason: str,
) -> AuditEntry:
    resource_id = item.get("id")
    if resource == "release-asset":
        size_bytes = item.get("size", 0)
        url = item.get("browser_download_url", "")
    elif resource == "actions-artifact":
        size_bytes = item.get("size_in_bytes", 0)
        url = item.get("archive_download_url", "")
    else:
        size_bytes = 0
        url = item.get("html_url", "")
    return AuditEntry(
        resource=resource,
        name=str(item.get("name") or item.get("tag_name") or "<unnamed>"),
        version=str(version) if version else None,
        action=action,
        reason=reason,
        repository=context.repository,
        mode=context.mode,
        timestamp_utc=datetime.now(UTC).isoformat(),
        resource_id=resource_id if type(resource_id) is int else None,
        size_bytes=size_bytes if type(size_bytes) is int else 0,
        expired=item.get("expired") is True,
        url=url if isinstance(url, str) else "",
        workflow_run_id=_workflow_run_id(item),
    )


def _policy_entry(
    context: AuditContext,
    name: str,
    action: str,
    reason: str,
    version: SemVer | None = None,
) -> AuditEntry:
    return AuditEntry(
        resource="policy",
        name=name,
        version=str(version) if version else None,
        action=action,
        reason=reason,
        repository=context.repository,
        mode=context.mode,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )


def _release_kind(release: dict[str, Any]) -> tuple[SemVer | None, str]:
    tag = release["tag_name"]
    stable_version = parse_stable_version(tag)
    if release["draft"]:
        return stable_version, "draft release protected"
    if release["prerelease"]:
        return stable_version, "prerelease protected"
    if stable_version is None:
        return None, "unparseable or non-stable tag protected"
    return stable_version, "stable release"


def _ref_version(ref: str) -> SemVer | None:
    if ref.startswith("refs/tags/"):
        ref = ref.removeprefix("refs/tags/")
    return parse_version_core(ref)


def _protected_versions(
    api: GitHubApi,
    releases: list[dict[str, Any]],
    deployments: list[dict[str, Any]],
    latest_release: dict[str, Any] | None,
    explicit_public_versions: Iterable[SemVer],
) -> dict[SemVer, set[str]]:
    protected: dict[SemVer, set[str]] = {}

    def protect(version: SemVer | None, reason: str) -> None:
        if version is not None:
            protected.setdefault(version, set()).add(reason)

    for release in releases:
        tag_core = parse_version_core(release["tag_name"])
        if release["draft"]:
            protect(tag_core, "draft release")
        if release["prerelease"] or parse_stable_version(release["tag_name"]) is None:
            protect(tag_core, "prerelease or non-stable release")
        for version in public_download_versions_from_text(release.get("body") or ""):
            protect(version, "explicit release-note download link")

    if latest_release is not None:
        latest_version = parse_version_core(latest_release["tag_name"])
        if latest_version is None:
            raise RuntimeError("GitHub's public latest release tag is not parseable")
        protect(latest_version, "GitHub public latest release")

    for version in explicit_public_versions:
        protect(version, "repository public download link")

    for deployment in deployments:
        candidates = public_download_versions_from_text(json.dumps(deployment, sort_keys=True))
        ref_version = _ref_version(deployment["ref"])
        if ref_version is not None:
            candidates.add(ref_version)
        if not candidates:
            continue
        deployment_id = positive_int(deployment["id"], "deployment id")
        state = api.get_latest_deployment_status(deployment_id)
        if state not in INACTIVE_DEPLOYMENT_STATES:
            for version in candidates:
                protect(version, f"active deployment {deployment_id}")
    return protected


def _protection_reason(protected: dict[SemVer, set[str]], version: SemVer) -> str:
    return "version protected by " + ", ".join(sorted(protected[version]))


def _candidate_signature(entries: Iterable[AuditEntry]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                entry.resource,
                entry.resource_id,
                entry.version,
                entry.name,
                entry.size_bytes,
            )
            for entry in entries
            if entry.action == "would-delete"
        )
    )


def cleanup_repository(
    api: GitHubApi,
    *,
    apply: bool = False,
    public_download_versions: Iterable[SemVer] = (),
    max_deletions: int = DEFAULT_MAX_DELETIONS,
    max_delete_bytes: int = DEFAULT_MAX_DELETE_BYTES,
    recorder: AuditRecorder | None = None,
    pre_delete_guard: Callable[[], None] | None = None,
) -> tuple[list[AuditEntry], set[SemVer]]:
    """Plan or apply cleanup; releases, tags, notes, and source archives always remain."""
    if max_deletions < 0 or max_delete_bytes < 0:
        raise ValueError("deletion ceilings cannot be negative")
    if apply and recorder is None:
        raise ValueError("apply requires a durable audit recorder")
    if apply and pre_delete_guard is None:
        raise ValueError("apply requires a pre-delete safety guard")
    public_download_versions = tuple(public_download_versions)

    context = AuditContext(
        repository=str(getattr(api, "repository", "unknown/unknown")),
        mode="apply" if apply else "dry-run",
    )
    releases = api.list_releases()
    latest_release = api.get_latest_release()
    artifacts = api.list_artifacts()
    deployments = api.list_deployments()
    validate_inventory(releases, artifacts, deployments, latest_release)

    stable_releases = [
        (release, version)
        for release in releases
        if not release["draft"]
        and not release["prerelease"]
        and (version := parse_stable_version(release["tag_name"])) is not None
    ]
    keep = retained_versions(version for _, version in stable_releases)
    current = max((version for _, version in stable_releases), default=None)
    protected = _protected_versions(
        api,
        releases,
        deployments,
        latest_release,
        public_download_versions,
    )

    entries: list[AuditEntry] = []
    candidate_indexes: list[int] = []
    for release in releases:
        version, kind = _release_kind(release)
        if kind == "stable release" and version in keep:
            release_reason = (
                "retained stable release; release record, tag, notes, and sources retained"
            )
            release_action = "keep"
        elif kind == "stable release":
            release_reason = "release record, tag, notes, and source archives always retained"
            release_action = "keep"
        else:
            release_reason = kind
            release_action = "skip"
        entries.append(_entry(context, "release", release, version, release_action, release_reason))

        for asset in release["assets"]:
            asset_name = asset["name"]
            asset_version, asset_reason = version_from_build_name(asset_name)
            if kind != "stable release" or version is None:
                action, reason = "skip", f"parent {kind}"
            elif version in keep:
                action, reason = "keep", "asset belongs to a retained stable version"
            elif version in protected:
                action, reason = "keep", _protection_reason(protected, version)
            elif asset_version is None:
                action, reason = "keep", f"non-build release asset retained: {asset_reason}"
            elif asset_version != version:
                action, reason = (
                    "skip",
                    "asset package version does not match its stable release tag",
                )
            else:
                action, reason = "would-delete", "obsolete stable release build"
            entries.append(_entry(context, "release-asset", asset, version, action, reason))
            if action == "would-delete":
                candidate_indexes.append(len(entries) - 1)

    if current is None:
        entries.append(
            _policy_entry(
                context,
                "stable release inventory",
                "blocked",
                "no stable releases found; no artifacts are eligible for deletion",
            )
        )

    run_cache: dict[int, dict[str, Any] | None] = {}
    for artifact in artifacts:
        name = artifact["name"]
        version, version_reason = version_from_build_name(name)
        if artifact["expired"]:
            action, reason = "skip", "artifact is already expired"
        elif version is None:
            action, reason = "skip", version_reason
        elif current is None:
            action, reason = "skip", "no stable release inventory"
        elif version in keep:
            action, reason = "keep", "artifact belongs to a retained stable version"
        elif version in protected:
            action, reason = "keep", _protection_reason(protected, version)
        elif version >= current:
            action, reason = "skip", "artifact is not older than the current stable release"
        else:
            run_id = _workflow_run_id(artifact)
            if run_id is None:
                action, reason = "skip", "artifact has no numeric producer workflow run id"
            else:
                if run_id not in run_cache:
                    run_cache[run_id] = api.get_workflow_run(run_id)
                run = run_cache[run_id]
                if run is None:
                    action, reason = "skip", "producer workflow run no longer exists"
                else:
                    validate_workflow_run(run, run_id)
                    run_version = parse_stable_version(str(run.get("head_branch") or ""))
                    if run["status"] != "completed":
                        action, reason = "skip", "producer workflow run is not completed"
                    elif run["path"] != RELEASE_WORKFLOW_PATH:
                        action, reason = "skip", "artifact was not produced by release-build.yml"
                    elif run["event"] != RELEASE_WORKFLOW_EVENT:
                        action, reason = "skip", "release-build producer was not a tag push"
                    elif run_version != version:
                        action, reason = "skip", "producer tag does not match artifact version"
                    else:
                        action, reason = "would-delete", "obsolete completed release-build artifact"
        entries.append(_entry(context, "actions-artifact", artifact, version, action, reason))
        if action == "would-delete":
            candidate_indexes.append(len(entries) - 1)

    delete_count = len(candidate_indexes)
    delete_bytes = sum(entries[index].size_bytes for index in candidate_indexes)
    limit_reasons: list[str] = []
    if delete_count > max_deletions:
        limit_reasons.append(f"{delete_count} candidates exceeds the {max_deletions} item ceiling")
    if delete_bytes > max_delete_bytes:
        limit_reasons.append(
            f"{delete_bytes} candidate bytes exceeds the {max_delete_bytes} byte ceiling"
        )
    if limit_reasons:
        entries.append(
            _policy_entry(
                context,
                "deletion ceilings",
                "blocked",
                "; ".join(limit_reasons),
            )
        )

    if recorder is not None:
        recorder.record_all(entries)
        recorder.sync()

    if not apply:
        return entries, keep
    if limit_reasons:
        raise CleanupApplyError("cleanup apply blocked by deletion ceilings", entries, keep)
    if recorder is None:  # narrowed by the apply precondition above
        raise AssertionError("apply requires a durable audit recorder")

    revalidated_entries, revalidated_keep = cleanup_repository(
        api,
        public_download_versions=public_download_versions,
        max_deletions=max_deletions,
        max_delete_bytes=max_delete_bytes,
    )
    if revalidated_keep != keep or _candidate_signature(
        revalidated_entries
    ) != _candidate_signature(entries):
        blocked = _policy_entry(
            context,
            "pre-delete inventory revalidation",
            "blocked",
            "release, deployment, link, or artifact state changed after the destructive plan",
        )
        entries.append(blocked)
        recorder.record(blocked)
        recorder.sync()
        raise CleanupApplyError("cleanup inventory changed before deletion", entries, keep)
    revalidated = _policy_entry(
        context,
        "pre-delete inventory revalidation",
        "keep",
        "fresh protection inventory and candidate fingerprint match the destructive plan",
    )
    entries.append(revalidated)
    recorder.record(revalidated)
    recorder.sync()

    if pre_delete_guard is None:  # narrowed by the apply precondition above
        raise AssertionError("apply requires a pre-delete safety guard")
    try:
        pre_delete_guard()
    except Exception as exc:
        blocked = _policy_entry(
            context,
            "pre-delete repository guard",
            "blocked",
            f"default-branch or public-link checkout validation failed: {exc}",
        )
        entries.append(blocked)
        recorder.record(blocked)
        recorder.sync()
        raise CleanupApplyError("cleanup repository guard failed", entries, keep) from exc

    for index in candidate_indexes:
        planned = entries[index]
        if planned.resource_id is None:  # candidate construction validates every API id
            raise AssertionError("cleanup candidate has no resource id")
        deleting = dataclasses.replace(
            planned,
            action="deleting",
            reason="destructive request about to be issued",
            timestamp_utc=datetime.now(UTC).isoformat(),
        )
        recorder.record(deleting)
        recorder.sync()
        try:
            if planned.resource == "release-asset":
                deleted = api.delete_release_asset(planned.resource_id)
            elif planned.resource == "actions-artifact":
                deleted = api.delete_artifact(planned.resource_id)
            else:  # pragma: no cover - candidate construction controls this invariant
                raise RuntimeError(f"unsupported cleanup resource {planned.resource!r}")
        except Exception as exc:
            failed = dataclasses.replace(
                planned,
                action="error",
                reason=f"delete failed: {exc}",
                timestamp_utc=datetime.now(UTC).isoformat(),
            )
            entries[index] = failed
            recorder.record(failed)
            recorder.sync()
            raise CleanupApplyError(str(exc), entries, keep) from exc

        outcome = dataclasses.replace(
            planned,
            action="deleted" if deleted else "already-absent",
            reason=(
                "obsolete build deleted"
                if deleted
                else "resource was already absent; treated as an idempotent success"
            ),
            timestamp_utc=datetime.now(UTC).isoformat(),
        )
        entries[index] = outcome
        recorder.record(outcome)
        recorder.sync()
    return entries, keep


def _nonnegative_cli_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument(
        "--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com")
    )
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--expected-default-sha",
        help="Required for apply; must equal both the checkout and current default-branch SHA",
    )
    parser.add_argument("--audit-log", type=Path)
    parser.add_argument("--summary", type=Path, default=os.environ.get("GITHUB_STEP_SUMMARY"))
    parser.add_argument(
        "--max-deletions",
        type=_nonnegative_cli_int,
        default=DEFAULT_MAX_DELETIONS,
    )
    parser.add_argument(
        "--max-delete-bytes",
        type=_nonnegative_cli_int,
        default=DEFAULT_MAX_DELETE_BYTES,
    )
    parser.add_argument(
        "--apply", action="store_true", help="Perform eligible deletions (default is dry-run)"
    )
    return parser


def _write_summary(path: Path | None, summary: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(summary)


def _reject_incomplete_public_index(index_records: bytes) -> None:
    for record in index_records.split(b"\0"):
        marker = record[:1]
        if marker == b"S" or marker.islower():
            raise RuntimeError(
                "public-link surfaces use skip-worktree or assume-unchanged index flags"
            )


def _repository_head_with_clean_public_surfaces(root: Path) -> str:
    try:
        if root.is_symlink():
            raise RuntimeError("cleanup repository root must not be a symlink")
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"cannot resolve cleanup repository root: {exc}") from exc
    if not resolved_root.is_dir():
        raise RuntimeError("cleanup repository root must be a directory")
    try:
        top_level = subprocess.run(
            ["git", "-C", str(resolved_root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        if Path(top_level).resolve() != resolved_root:
            raise RuntimeError("cleanup repository root must be the Git worktree root")
        sparse_checkout = subprocess.run(
            ["git", "-C", str(resolved_root), "config", "--bool", "core.sparseCheckout"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if sparse_checkout.returncode not in {0, 1}:
            raise RuntimeError("cannot determine whether the cleanup checkout is sparse")
        if sparse_checkout.stdout.strip().lower() == "true":
            raise RuntimeError("cleanup apply requires a non-sparse checkout")
        head = subprocess.run(
            ["git", "-C", str(resolved_root), "rev-parse", "--verify", "HEAD^{commit}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        public_index = subprocess.run(
            [
                "git",
                "-C",
                str(resolved_root),
                "ls-files",
                "-v",
                "-z",
                "--",
                "README.md",
                "RELEASE_NOTES.md",
                "docs",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
        _reject_incomplete_public_index(public_index)
        public_changes = subprocess.run(
            [
                "git",
                "-C",
                str(resolved_root),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--",
                "README.md",
                "RELEASE_NOTES.md",
                "docs",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"cannot validate cleanup repository checkout: {exc}") from exc
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise RuntimeError("cleanup repository HEAD is not a full commit SHA")
    if public_changes:
        raise RuntimeError("public-link surfaces differ from the validated checkout")
    return head


def _verify_apply_checkout(api: GitHubApi, repository_root: Path, expected_sha: str) -> None:
    expected = expected_sha.strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", expected) is None:
        raise RuntimeError("expected default-branch SHA must be 40 lowercase hex characters")
    checkout_sha = _repository_head_with_clean_public_surfaces(repository_root)
    default_branch, current_sha = api.get_default_branch_head()
    if checkout_sha != expected or current_sha != expected:
        raise RuntimeError(
            f"checkout is not the current {default_branch} tip; refusing stale public-link analysis"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.repository:
        raise SystemExit("--repository or GITHUB_REPOSITORY is required")
    if args.apply and args.audit_log is None:
        raise SystemExit("--audit-log is required with --apply")
    if args.apply and not args.expected_default_sha:
        raise SystemExit("--expected-default-sha is required with --apply")
    token = os.environ.get(args.token_env)
    if not token:
        raise SystemExit(f"GitHub token environment variable {args.token_env!r} is required")

    context = AuditContext(args.repository, "apply" if args.apply else "dry-run")
    manager = AuditRecorder(args.audit_log) if args.audit_log else nullcontext(None)
    exit_code = 0
    with manager as recorder:
        try:
            api = GitHubApi(args.repository, token, args.api_url)
            pre_delete_guard: Callable[[], None] | None = None
            if args.apply:
                expected_sha = str(args.expected_default_sha)
                _verify_apply_checkout(api, args.repository_root, expected_sha)

                def verify_pre_delete_checkout() -> None:
                    _verify_apply_checkout(api, args.repository_root, expected_sha)

                pre_delete_guard = verify_pre_delete_checkout
            public_versions = public_download_versions_from_repository(args.repository_root)
            entries, keep = cleanup_repository(
                api,
                apply=args.apply,
                public_download_versions=public_versions,
                max_deletions=args.max_deletions,
                max_delete_bytes=args.max_delete_bytes,
                recorder=recorder,
                pre_delete_guard=pre_delete_guard,
            )
        except CleanupApplyError as exc:
            entries, keep = exc.entries, exc.keep
            sys.stderr.write(f"Cleanup apply failed safely: {exc}\n")
            exit_code = 1
        except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
            failure = _policy_entry(context, "cleanup execution", "error", str(exc))
            entries, keep = [failure], set()
            if recorder is not None:
                recorder.record(failure)
                recorder.sync()
            sys.stderr.write(f"Cleanup failed safely: {exc}\n")
            exit_code = 1

        summary = render_summary(entries, keep, apply=args.apply)
        sys.stdout.write(summary)
        _write_summary(args.summary, summary)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

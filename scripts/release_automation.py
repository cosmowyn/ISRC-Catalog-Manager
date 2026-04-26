"""Automated SemVer bump and release-note generation for CI."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from isrc_manager.versioning import SemVer, bump_version  # noqa: E402

PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
VERSION_MODULE_PATH = PROJECT_ROOT / "isrc_manager" / "version.py"
RELEASES_DIR = PROJECT_ROOT / "docs" / "releases"
LATEST_MANIFEST_PATH = RELEASES_DIR / "latest.json"
RELEASE_NOTES_PATH = PROJECT_ROOT / "RELEASE_NOTES.md"
RELEASE_NOTES_URL_TEMPLATE = (
    "https://github.com/cosmowyn/ISRC-Catalog-Manager/blob/main/docs/releases/v{version}.md"
)
GENERATED_PATH_PREFIXES = ("docs/releases/",)
GENERATED_PATHS = {
    "RELEASE_NOTES.md",
    "isrc_manager/version.py",
    "pyproject.toml",
}
SKIP_MARKERS = ("[skip version]", "semver: none", "skip-version: true")
BUMP_ORDER = {"patch": 0, "minor": 1, "major": 2}


@dataclass(frozen=True, slots=True)
class CommitInfo:
    sha: str
    subject: str
    body: str = ""
    author_name: str = ""
    author_email: str = ""
    files: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        return f"{self.subject}\n{self.body}".strip()


@dataclass(frozen=True, slots=True)
class ReleasePlan:
    current_version: str
    next_version: str
    bump_level: str
    commits: tuple[CommitInfo, ...]


def read_project_version(pyproject_path: Path | None = None) -> str:
    pyproject_path = pyproject_path or PYPROJECT_PATH
    text = pyproject_path.read_text(encoding="utf-8")
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if in_project and stripped.startswith("[") and stripped.endswith("]"):
            break
        if in_project:
            match = re.fullmatch(r'version\s*=\s*"([^"]+)"', stripped)
            if match:
                return match.group(1)
    raise RuntimeError(f"Could not find [project].version in {pyproject_path}")


def write_project_version(version: str, pyproject_path: Path | None = None) -> None:
    pyproject_path = pyproject_path or PYPROJECT_PATH
    text = pyproject_path.read_text(encoding="utf-8")
    pattern = re.compile(r'(?ms)(^\[project\].*?^\s*version\s*=\s*")([^"]+)(")')
    updated, count = pattern.subn(rf"\g<1>{version}\3", text, count=1)
    if count != 1:
        raise RuntimeError(f"Could not update [project].version in {pyproject_path}")
    pyproject_path.write_text(updated, encoding="utf-8")


def write_version_module(version: str, version_module_path: Path | None = None) -> None:
    version_module_path = version_module_path or VERSION_MODULE_PATH
    text = version_module_path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(?m)^__version__\s*=\s*"[^"]+"$',
        f'__version__ = "{version}"',
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError(f"Could not update __version__ in {version_module_path}")
    version_module_path.write_text(updated, encoding="utf-8")


def has_skip_marker(commits: Iterable[CommitInfo]) -> bool:
    for commit in commits:
        lowered = commit.message.lower()
        if any(marker in lowered for marker in SKIP_MARKERS):
            return True
    return False


def is_bot_release_commit(commit: CommitInfo) -> bool:
    author = f"{commit.author_name} {commit.author_email}".lower()
    subject = commit.subject.lower()
    return (
        "github-actions[bot]" in author
        or "github-actions" in author
        or (subject.startswith("chore(release):") and "[skip version]" in subject)
    )


def is_generated_only_commit(commit: CommitInfo) -> bool:
    if not commit.files:
        return False
    return all(_is_generated_path(path) for path in commit.files)


def _is_generated_path(path: str) -> bool:
    clean_path = str(path or "").strip().replace("\\", "/")
    return clean_path in GENERATED_PATHS or clean_path.startswith(GENERATED_PATH_PREFIXES)


def releasable_commits(commits: Iterable[CommitInfo]) -> tuple[CommitInfo, ...]:
    selected = []
    for commit in commits:
        if is_bot_release_commit(commit):
            continue
        if is_generated_only_commit(commit):
            continue
        selected.append(commit)
    return tuple(selected)


def classify_bump(commits: Iterable[CommitInfo]) -> str | None:
    candidates = releasable_commits(commits)
    if not candidates or has_skip_marker(candidates):
        return None
    level = "patch"
    for commit in candidates:
        commit_level = classify_commit(commit)
        if BUMP_ORDER[commit_level] > BUMP_ORDER[level]:
            level = commit_level
    return level


def classify_commit(commit: CommitInfo) -> str:
    message = commit.message
    lowered = message.lower()
    subject = commit.subject.strip()
    if (
        "breaking change" in lowered
        or "semver: major" in lowered
        or re.match(r"^[a-z]+(?:\([^)]+\))?!:", subject)
    ):
        return "major"
    if "semver: minor" in lowered or re.match(r"^feat(?:\([^)]+\))?:", subject):
        return "minor"
    if any(_path_suggests_user_feature(path) for path in commit.files) and re.search(
        r"\b(add|new|implement|introduce|support)\b",
        subject,
        re.IGNORECASE,
    ):
        return "minor"
    return "patch"


def _path_suggests_user_feature(path: str) -> bool:
    clean_path = str(path or "").replace("\\", "/")
    return clean_path.startswith("isrc_manager/") or clean_path == "ISRC_manager.py"


def build_release_plan(current_version: str, commits: Iterable[CommitInfo]) -> ReleasePlan | None:
    selected = releasable_commits(commits)
    level = classify_bump(selected)
    if level is None:
        return None
    next_version = bump_version(current_version, level)
    return ReleasePlan(
        current_version=str(SemVer.parse(current_version)),
        next_version=next_version,
        bump_level=level,
        commits=selected,
    )


def generate_release_markdown(
    *,
    version: str,
    released_at: str,
    bump_level: str,
    commits: Iterable[CommitInfo],
) -> str:
    groups = group_release_notes(commits)
    lines = [
        f"# ISRC Catalog Manager {version}",
        "",
        f"Version: {version}",
        f"Date: {released_at}",
        f"Type of update: {bump_level.title()}",
        "",
        "## Highlights",
        *_bullet_lines(groups["highlights"]),
        "",
        "## Fixes",
        *_bullet_lines(groups["fixes"]),
        "",
        "## Internal/technical changes",
        *_bullet_lines(groups["internal"]),
        "",
    ]
    return "\n".join(lines)


def group_release_notes(commits: Iterable[CommitInfo]) -> dict[str, list[str]]:
    groups = {"highlights": [], "fixes": [], "internal": []}
    for commit in commits:
        subject = normalize_subject(commit.subject)
        if not subject:
            continue
        lowered = commit.subject.lower()
        if lowered.startswith("fix") or "bug" in lowered or "repair" in lowered:
            groups["fixes"].append(subject)
        elif lowered.startswith("feat") or re.search(
            r"\b(add|new|implement|introduce|support)\b",
            lowered,
        ):
            groups["highlights"].append(subject)
        else:
            groups["internal"].append(subject)
    fallback = "No clearly described changes were identified from commit metadata."
    for key, value in groups.items():
        if not value:
            groups[key] = [fallback]
    return groups


def _bullet_lines(items: Iterable[str]) -> list[str]:
    return [f"- {item}" for item in items]


def normalize_subject(subject: str) -> str:
    clean = re.sub(r"^[a-z]+(?:\([^)]+\))?!?:\s*", "", str(subject or "").strip())
    clean = re.sub(r"\s+", " ", clean)
    return clean[:160].rstrip()


def manifest_summary(commits: Iterable[CommitInfo]) -> str:
    groups = group_release_notes(commits)
    for key in ("highlights", "fixes", "internal"):
        first = groups[key][0]
        if not first.startswith("No clearly described"):
            return first
    return "Maintenance update generated from repository commit metadata."


def write_release_metadata(plan: ReleasePlan, *, released_at: str | None = None) -> None:
    release_date = released_at or datetime.now(timezone.utc).date().isoformat()
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    release_path = RELEASES_DIR / f"v{plan.next_version}.md"
    markdown = generate_release_markdown(
        version=plan.next_version,
        released_at=release_date,
        bump_level=plan.bump_level,
        commits=plan.commits,
    )
    release_path.write_text(markdown, encoding="utf-8")
    RELEASE_NOTES_PATH.write_text(markdown, encoding="utf-8")
    manifest = {
        "version": plan.next_version,
        "released_at": release_date,
        "summary": manifest_summary(plan.commits),
        "release_notes_url": RELEASE_NOTES_URL_TEMPLATE.format(version=plan.next_version),
        "minimum_supported_version": None,
    }
    LATEST_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def apply_release_plan(plan: ReleasePlan) -> None:
    write_project_version(plan.next_version)
    write_version_module(plan.next_version)
    write_release_metadata(plan)


def git(args: list[str], *, cwd: Path = PROJECT_ROOT) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def collect_commits(base_ref: str, head_ref: str = "HEAD") -> tuple[CommitInfo, ...]:
    shas_text = git(["rev-list", "--reverse", f"{base_ref}..{head_ref}"])
    shas = [line.strip() for line in shas_text.splitlines() if line.strip()]
    commits = []
    for sha in shas:
        metadata = git(["show", "-s", "--format=%H%x1f%s%x1f%b%x1f%an%x1f%ae", sha])
        parts = metadata.split("\x1f")
        files_text = git(["diff-tree", "--no-commit-id", "--name-only", "-r", sha])
        commits.append(
            CommitInfo(
                sha=parts[0],
                subject=parts[1] if len(parts) > 1 else "",
                body=parts[2] if len(parts) > 2 else "",
                author_name=parts[3] if len(parts) > 3 else "",
                author_email=parts[4] if len(parts) > 4 else "",
                files=tuple(line.strip() for line in files_text.splitlines() if line.strip()),
            )
        )
    return tuple(commits)


def resolve_base_ref(raw_base_ref: str) -> str:
    base_ref = str(raw_base_ref or "").strip()
    if base_ref and set(base_ref) != {"0"}:
        return base_ref
    try:
        return git(["rev-parse", "HEAD~1"])
    except Exception:
        return git(["rev-list", "--max-parents=0", "HEAD"]).splitlines()[0]


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default="")
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    base_ref = resolve_base_ref(args.base_ref)
    commits = collect_commits(base_ref, args.head_ref)
    current_version = read_project_version()
    plan = build_release_plan(current_version, commits)
    if plan is None:
        print("No version bump required.")
        return 0
    print(f"{plan.current_version} -> {plan.next_version} ({plan.bump_level})")
    if not args.dry_run:
        apply_release_plan(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

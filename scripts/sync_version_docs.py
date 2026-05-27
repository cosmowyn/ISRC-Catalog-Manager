"""Synchronize current public version references from pyproject.toml."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = "pyproject.toml"
LATEST_MANIFEST_PATH = "docs/releases/latest.json"
RELEASE_NOTES_PATH = "RELEASE_NOTES.md"
RELEASE_NOTES_URL_TEMPLATE = (
    "https://github.com/cosmowyn/ISRC-Catalog-Manager/blob/main/docs/releases/v{version}.md"
)
SYNC_START = "<!-- version:sync:start -->"
SYNC_END = "<!-- version:sync:end -->"


class VersionSyncError(RuntimeError):
    """Raised when version-synced public references cannot be updated safely."""


@dataclass(frozen=True, slots=True)
class MarkerTarget:
    path: str
    body_template: str

    def render(self, version: str) -> str:
        return "\n".join(
            (
                SYNC_START,
                self.body_template.format(version=version),
                SYNC_END,
            )
        )


@dataclass(frozen=True, slots=True)
class SyncChange:
    path: str
    description: str


MARKER_TARGETS = (
    MarkerTarget(
        path="README.md",
        body_template=(
            "Current source release: `{version}` (`v{version}`).\n"
            "Latest repository metadata: [`docs/releases/latest.json`](docs/releases/latest.json).\n"
            "Latest release notes: [`RELEASE_NOTES.md`](RELEASE_NOTES.md)."
        ),
    ),
    MarkerTarget(
        path="docs/release-builds.md",
        body_template=(
            "Current canonical source version: `{version}` (`v{version}`).\n"
            "Repository latest metadata: [`docs/releases/latest.json`](releases/latest.json).\n"
            "Latest release notes: [`RELEASE_NOTES.md`](../RELEASE_NOTES.md)."
        ),
    ),
)


def read_project_version(root: Path = PROJECT_ROOT) -> str:
    """Read the canonical application version from pyproject.toml."""

    pyproject_path = root / PYPROJECT_PATH
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VersionSyncError(f"Could not read {PYPROJECT_PATH}: {exc}") from exc
    project = pyproject.get("project")
    if not isinstance(project, dict):
        raise VersionSyncError(f"Could not find [project] in {PYPROJECT_PATH}")
    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        raise VersionSyncError(f"Could not find [project].version in {PYPROJECT_PATH}")
    return version.strip()


def sync_version_docs(root: Path = PROJECT_ROOT, *, check: bool = False) -> tuple[SyncChange, ...]:
    """Update or check current public version references under ``root``."""

    version = read_project_version(root)
    changes = [
        *_sync_marker_targets(root, version, check=check),
        *_sync_latest_manifest(root, version, check=check),
        *_sync_release_notes(root, version, check=check),
    ]
    _validate_current_release_doc(root, version)
    return tuple(changes)


def _sync_marker_targets(root: Path, version: str, *, check: bool) -> tuple[SyncChange, ...]:
    changes = []
    for target in MARKER_TARGETS:
        path = root / target.path
        original = _read_text(path, target.path)
        updated = _replace_marker_block(
            original,
            replacement=target.render(version),
            display_path=target.path,
        )
        if updated != original:
            changes.append(SyncChange(target.path, "version marker block"))
            if not check:
                path.write_text(updated, encoding="utf-8")
    return tuple(changes)


def _sync_latest_manifest(root: Path, version: str, *, check: bool) -> tuple[SyncChange, ...]:
    path = root / LATEST_MANIFEST_PATH
    original = _read_text(path, LATEST_MANIFEST_PATH)
    try:
        manifest = json.loads(original)
    except json.JSONDecodeError as exc:
        raise VersionSyncError(f"Could not parse {LATEST_MANIFEST_PATH}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise VersionSyncError(f"{LATEST_MANIFEST_PATH} must contain a JSON object")

    updated_manifest: dict[str, Any] = dict(manifest)
    updated_manifest["version"] = version
    updated_manifest["release_notes_url"] = RELEASE_NOTES_URL_TEMPLATE.format(version=version)
    updated = json.dumps(updated_manifest, indent=2) + "\n"
    if updated == original:
        return ()
    if not check:
        path.write_text(updated, encoding="utf-8")
    return (SyncChange(LATEST_MANIFEST_PATH, "latest release metadata"),)


def _sync_release_notes(root: Path, version: str, *, check: bool) -> tuple[SyncChange, ...]:
    path = root / RELEASE_NOTES_PATH
    original = _read_text(path, RELEASE_NOTES_PATH)
    updated, heading_count = re.subn(
        r"(?m)^# ISRC Catalog Manager .+$",
        f"# ISRC Catalog Manager {version}",
        original,
        count=1,
    )
    updated, version_count = re.subn(
        r"(?m)^Version: .+$",
        f"Version: {version}",
        updated,
        count=1,
    )
    if heading_count != 1 or version_count != 1:
        raise VersionSyncError(
            f"{RELEASE_NOTES_PATH} must contain one current release heading and Version line"
        )
    if updated == original:
        return ()
    if not check:
        path.write_text(updated, encoding="utf-8")
    return (SyncChange(RELEASE_NOTES_PATH, "current release notes header"),)


def _replace_marker_block(text: str, *, replacement: str, display_path: str) -> str:
    pattern = re.compile(
        rf"{re.escape(SYNC_START)}.*?{re.escape(SYNC_END)}",
        flags=re.DOTALL,
    )
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise VersionSyncError(
            f"{display_path} must contain exactly one {SYNC_START} / {SYNC_END} block"
        )
    return updated


def _validate_current_release_doc(root: Path, version: str) -> None:
    release_doc = root / "docs" / "releases" / f"v{version}.md"
    if not release_doc.is_file():
        raise VersionSyncError(
            f"Missing current release document {release_doc.relative_to(root).as_posix()}"
        )


def _read_text(path: Path, display_path: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VersionSyncError(f"Could not read {display_path}: {exc}") from exc


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail if synced version docs are stale"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT,
        help="repository root to synchronize",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        changes = sync_version_docs(args.root, check=args.check)
    except VersionSyncError as exc:
        print(f"version docs sync failed: {exc}", file=sys.stderr)
        return 1

    if args.check:
        if changes:
            print("version docs are stale:", file=sys.stderr)
            for change in changes:
                print(f"- {change.path}: {change.description}", file=sys.stderr)
            return 1
        print("version docs are in sync")
    elif changes:
        for change in changes:
            print(f"updated {change.path}: {change.description}")
    else:
        print("version docs already in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

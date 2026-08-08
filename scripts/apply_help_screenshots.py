"""Safely apply attested Help screenshot artifacts to a trusted checkout."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_SCREENSHOTS = 256
MAX_SCREENSHOT_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.png")


class HelpArtifactError(RuntimeError):
    """Raised when a Help artifact cannot be applied safely."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HelpArtifactError(f"invalid JSON file {path}: {exc}") from exc


def _validate_ancestors(path: Path, boundary: Path) -> None:
    boundary = boundary.absolute()
    path = path.absolute()
    try:
        relative = path.relative_to(boundary)
    except ValueError as exc:
        raise HelpArtifactError(f"path escapes its trusted boundary: {path}") from exc
    current = boundary
    if current.is_symlink() or not current.is_dir():
        raise HelpArtifactError(f"trusted boundary is not a real directory: {boundary}")
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise HelpArtifactError(f"symlinked path is not allowed: {current}")


def _validate_provenance(artifact_root: Path, expected_source_commit: str) -> None:
    provenance = _read_json(artifact_root / "artifacts" / "ui_pq" / "provenance.json")
    if (
        not isinstance(provenance, dict)
        or provenance.get("schema_version") != 2
        or not isinstance(provenance.get("bundle"), dict)
        or not isinstance(provenance.get("fingerprints"), dict)
        or not isinstance(provenance["fingerprints"].get("runtime"), dict)
    ):
        raise HelpArtifactError("Help artifact provenance is missing or malformed")
    if provenance["bundle"].get("source_commit") != expected_source_commit:
        raise HelpArtifactError("Help artifact source commit does not match its attested CI run")

    evidence = _read_json(artifact_root / "artifacts" / "ui_pq" / "evidence.json")
    if not isinstance(evidence, list) or not any(
        isinstance(event, dict)
        and event.get("test_id") == "UI-PQ-HELP-001"
        and event.get("status") == "passed"
        for event in evidence
    ):
        raise HelpArtifactError("Help artifact has no passing UI-PQ-HELP-001 evidence")


def apply_help_screenshots(
    *,
    artifact_root: Path,
    repository_root: Path,
    destination: Path,
    expected_source_commit: str,
) -> dict[str, int]:
    """Validate and atomically copy the flat PNG allowlist from a Help artifact."""
    if re.fullmatch(r"[0-9a-f]{40}", expected_source_commit) is None:
        raise HelpArtifactError("expected source commit must be a full Git SHA")
    artifact_root = artifact_root.absolute()
    repository_root = repository_root.absolute()
    destination = destination.absolute()
    source = artifact_root / "docs" / "help" / "screenshots"
    _validate_ancestors(source, artifact_root)
    _validate_ancestors(destination, repository_root)
    if not source.is_dir() or not destination.is_dir():
        raise HelpArtifactError("source and destination screenshot paths must be directories")
    _validate_provenance(artifact_root, expected_source_commit)

    source_entries = sorted(source.iterdir(), key=lambda path: path.name)
    if not source_entries or len(source_entries) > MAX_SCREENSHOTS:
        raise HelpArtifactError("Help artifact has an invalid screenshot count")
    for existing in destination.iterdir():
        if existing.is_symlink() or not existing.is_file() or existing.suffix.lower() != ".png":
            raise HelpArtifactError(f"unsafe destination entry: {existing}")

    total_bytes = 0
    validated: list[tuple[Path, int]] = []
    for source_file in source_entries:
        if (
            source_file.is_symlink()
            or not source_file.is_file()
            or _SAFE_NAME.fullmatch(source_file.name) is None
        ):
            raise HelpArtifactError(f"unsafe Help screenshot entry: {source_file}")
        size = source_file.stat().st_size
        total_bytes += size
        if size > MAX_SCREENSHOT_BYTES or total_bytes > MAX_TOTAL_BYTES:
            raise HelpArtifactError("Help screenshot artifact exceeds its size limit")
        with source_file.open("rb") as stream:
            if stream.read(len(PNG_SIGNATURE)) != PNG_SIGNATURE:
                raise HelpArtifactError(f"Help screenshot is not a PNG: {source_file.name}")
        target = destination / source_file.name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise HelpArtifactError(f"unsafe Help screenshot target: {target}")
        validated.append((source_file, size))

    copied = 0
    for source_file, _size in validated:
        temporary_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination,
                prefix=f".{source_file.stem}-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                with source_file.open("rb") as source_stream:
                    shutil.copyfileobj(source_stream, temporary)
                temporary.flush()
                os.fsync(temporary.fileno())
                os.fchmod(temporary.fileno(), 0o644)
            os.replace(temporary_name, destination / source_file.name)
            copied += 1
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
    return {"copied": copied, "total_bytes": total_bytes}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        result = apply_help_screenshots(
            artifact_root=args.artifact_root,
            repository_root=args.repository_root,
            destination=args.destination,
            expected_source_commit=args.expected_source_commit,
        )
    except HelpArtifactError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    json.dump(result, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

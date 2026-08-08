"""Compute QA/PQ impact targets and provenance input fingerprints."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import runpy
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any


class FingerprintDefinitionError(RuntimeError):
    """Raised when the canonical QA/PQ impact definitions are unavailable or invalid."""


def stable_hash(value: object) -> str:
    """Return a deterministic, tagged SHA-256 hash for a JSON-compatible value."""
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a file without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expand_braces(pattern: str) -> tuple[str, ...]:
    start = pattern.find("{")
    if start < 0:
        return (pattern,)
    end = pattern.find("}", start + 1)
    if end < 0:
        return (pattern,)
    choices = pattern[start + 1 : end].split(",")
    if not choices:
        return (pattern,)
    expanded: list[str] = []
    for choice in choices:
        expanded.extend(_expand_braces(pattern[:start] + choice + pattern[end + 1 :]))
    return tuple(expanded)


def _repository_files(repo_root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for path in repo_root.rglob("*"):
        relative = path.relative_to(repo_root)
        if ".git" in relative.parts or "__pycache__" in relative.parts:
            continue
        if path.is_symlink():
            continue
        if path.is_file():
            files.append(path)
    return tuple(sorted(files, key=lambda item: item.relative_to(repo_root).as_posix()))


def _fingerprint_patterns(
    repo_root: Path,
    files: Sequence[Path],
    patterns: Iterable[str],
    file_hashes: dict[Path, str],
) -> str:
    normalized_patterns = sorted({str(pattern).replace("\\", "/") for pattern in patterns})
    expanded = tuple(
        expanded_pattern
        for pattern in normalized_patterns
        for expanded_pattern in _expand_braces(pattern)
    )
    matched: list[tuple[str, str]] = []
    for path in files:
        relative = path.relative_to(repo_root).as_posix()
        if not any(fnmatch.fnmatchcase(relative, pattern) for pattern in expanded):
            continue
        digest = file_hashes.get(path)
        if digest is None:
            digest = sha256_file(path)
            file_hashes[path] = digest
        matched.append((relative, digest))
    return stable_hash({"patterns": normalized_patterns, "files": matched})


def _fingerprint_files(
    repo_root: Path,
    files: Iterable[Path],
    file_hashes: dict[Path, str],
) -> str:
    payload: list[tuple[str, str]] = []
    for path in sorted(set(files), key=lambda item: item.relative_to(repo_root).as_posix()):
        digest = file_hashes.get(path)
        if digest is None:
            digest = sha256_file(path)
            file_hashes[path] = digest
        payload.append((path.relative_to(repo_root).as_posix(), digest))
    return stable_hash(payload)


def _impact_definitions(repo_root: Path) -> dict[str, Any]:
    impact_path = repo_root / "isrc_manager" / "qa" / "impact.py"
    if not impact_path.is_file():
        raise FingerprintDefinitionError(f"QA/PQ impact map is missing: {impact_path}")
    return runpy.run_path(str(impact_path))


def compute_input_fingerprints(repo_root: Path) -> dict[str, dict[str, str]]:
    """Hash every canonical component and shared provenance-input group."""
    definitions = _impact_definitions(repo_root)
    components = definitions.get("COMPONENTS")
    shared = definitions.get("SHARED_PROVENANCE_INPUTS")
    if not isinstance(components, tuple) or not isinstance(shared, dict):
        raise FingerprintDefinitionError("QA/PQ impact map did not expose canonical inputs")
    files = _repository_files(repo_root)
    file_hashes: dict[Path, str] = {}
    classify_path = definitions.get("classify_path")
    if not callable(classify_path):
        raise FingerprintDefinitionError("QA/PQ impact map has no path classifier")
    classified_components: dict[str, list[Path]] = {
        str(component.name): [] for component in components
    }
    classified_shared: list[Path] = []
    for path in files:
        relative = path.relative_to(repo_root).as_posix()
        impact = classify_path(relative)
        for name in getattr(impact, "components", ()):
            classified_components[str(name)].append(path)
        if bool(getattr(impact, "force_full", False)):
            classified_shared.append(path)
    component_hashes: dict[str, str] = {}
    for component in components:
        name = getattr(component, "name", None)
        patterns = getattr(component, "provenance_inputs", None)
        if not isinstance(name, str) or not isinstance(patterns, tuple):
            raise FingerprintDefinitionError("invalid component provenance definition")
        component_hashes[name] = stable_hash(
            {
                "classified": _fingerprint_files(
                    repo_root,
                    classified_components[name],
                    file_hashes,
                ),
                "declared": _fingerprint_patterns(
                    repo_root,
                    files,
                    patterns,
                    file_hashes,
                ),
            }
        )
    shared_hashes = {
        str(name): _fingerprint_patterns(repo_root, files, patterns, file_hashes)
        for name, patterns in sorted(shared.items())
    }
    shared_hashes["classified-cross-cutting"] = _fingerprint_files(
        repo_root,
        classified_shared,
        file_hashes,
    )
    return {"components": component_hashes, "shared": shared_hashes}


def all_targets(repo_root: Path) -> tuple[list[str], list[str]]:
    """Return every canonical component and full-validation pytest target."""
    definitions = _impact_definitions(repo_root)
    components = definitions["COMPONENTS"]
    names = sorted(str(component.name) for component in components)
    targets = {
        str(target) for component in components for target in getattr(component, "test_targets")
    }
    targets.update(str(target) for target in definitions["FULL_ONLY_TEST_TARGETS"])
    return names, sorted(targets)

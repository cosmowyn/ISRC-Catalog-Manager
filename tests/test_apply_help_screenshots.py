from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import apply_help_screenshots as help_artifact

SOURCE_COMMIT = "a" * 40


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture_roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    artifact_root = tmp_path / "artifact"
    repository_root = tmp_path / "repository"
    source = artifact_root / "docs" / "help" / "screenshots"
    destination = repository_root / "docs" / "help" / "screenshots"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    _write_json(
        artifact_root / "artifacts" / "ui_pq" / "provenance.json",
        {
            "schema_version": 2,
            "bundle": {"source_commit": SOURCE_COMMIT},
            "fingerprints": {"runtime": {"fingerprint": "sha256:runtime"}},
        },
    )
    _write_json(
        artifact_root / "artifacts" / "ui_pq" / "evidence.json",
        [{"test_id": "UI-PQ-HELP-001", "status": "passed"}],
    )
    return artifact_root, repository_root, destination


def test_apply_help_screenshots_copies_only_attested_png_files(tmp_path: Path) -> None:
    artifact_root, repository_root, destination = _fixture_roots(tmp_path)
    source_file = artifact_root / "docs" / "help" / "screenshots" / "chapter_help.png"
    source_file.write_bytes(help_artifact.PNG_SIGNATURE + b"qualified")
    (destination / "chapter_help.png").write_bytes(help_artifact.PNG_SIGNATURE + b"old")

    result = help_artifact.apply_help_screenshots(
        artifact_root=artifact_root,
        repository_root=repository_root,
        destination=destination,
        expected_source_commit=SOURCE_COMMIT,
    )

    assert result == {"copied": 1, "total_bytes": source_file.stat().st_size}
    assert (destination / "chapter_help.png").read_bytes().endswith(b"qualified")


def test_apply_help_screenshots_rejects_source_commit_mismatch(tmp_path: Path) -> None:
    artifact_root, repository_root, destination = _fixture_roots(tmp_path)
    (artifact_root / "docs" / "help" / "screenshots" / "chapter_help.png").write_bytes(
        help_artifact.PNG_SIGNATURE + b"qualified"
    )

    with pytest.raises(help_artifact.HelpArtifactError, match="source commit"):
        help_artifact.apply_help_screenshots(
            artifact_root=artifact_root,
            repository_root=repository_root,
            destination=destination,
            expected_source_commit="b" * 40,
        )


def test_apply_help_screenshots_rejects_symlinked_destination(tmp_path: Path) -> None:
    artifact_root, repository_root, destination = _fixture_roots(tmp_path)
    (artifact_root / "docs" / "help" / "screenshots" / "chapter_help.png").write_bytes(
        help_artifact.PNG_SIGNATURE + b"qualified"
    )
    destination.rmdir()
    destination.symlink_to(repository_root / ".git", target_is_directory=True)

    with pytest.raises(help_artifact.HelpArtifactError, match="symlinked path"):
        help_artifact.apply_help_screenshots(
            artifact_root=artifact_root,
            repository_root=repository_root,
            destination=destination,
            expected_source_commit=SOURCE_COMMIT,
        )


@pytest.mark.parametrize("unsafe_name", ["payload.txt", "nested"])
def test_apply_help_screenshots_rejects_non_png_or_nested_entries(
    tmp_path: Path, unsafe_name: str
) -> None:
    artifact_root, repository_root, destination = _fixture_roots(tmp_path)
    unsafe = artifact_root / "docs" / "help" / "screenshots" / unsafe_name
    if unsafe_name == "nested":
        unsafe.mkdir()
    else:
        unsafe.write_text("not a screenshot", encoding="utf-8")

    with pytest.raises(help_artifact.HelpArtifactError, match="unsafe Help screenshot entry"):
        help_artifact.apply_help_screenshots(
            artifact_root=artifact_root,
            repository_root=repository_root,
            destination=destination,
            expected_source_commit=SOURCE_COMMIT,
        )

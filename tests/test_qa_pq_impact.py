from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from isrc_manager.qa.impact import ALL_COMPONENT_NAMES, plan_qa_pq_impact
from scripts.qa_pq_impact import main


@pytest.fixture(autouse=True)
def _isolate_github_actions_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ("GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_SHA"):
        monkeypatch.delenv(variable, raising=False)


def plan(*paths: str, **overrides: object) -> dict[str, object]:
    return plan_qa_pq_impact(paths, **overrides)


def test_documentation_only_change_selects_no_pq_work() -> None:
    result = plan("README.md", "docs/architecture/component-map.md")

    assert result["mode"] == "none"
    assert result["full_validation"] is False
    assert result["has_pq_work"] is False
    assert result["selected_components"] == []
    assert result["test_targets"] == []
    assert result["reasons"] == ["no-pq-impact"]


def test_help_documentation_and_screenshots_select_visual_help_with_dependencies() -> None:
    result = plan(
        "isrc_manager/help_content.py",
        "docs/help/screenshots/chapter_catalog-table.png",
    )

    assert result["mode"] == "incremental"
    assert result["direct_components"] == ["visual-help"]
    assert result["dependency_components"] == ["core-inventory"]
    assert result["selected_components"] == ["core-inventory", "visual-help"]
    assert "tests/ui_qa/test_ui_pq_help_documentation.py" in result["test_targets"]
    assert "help-chapters" in result["screenshot_scopes"]


def test_isolated_component_change_selects_component_and_dependency_closure() -> None:
    result = plan("isrc_manager/assets/service.py")

    assert result["full_validation"] is False
    assert result["direct_components"] == ["assets"]
    assert result["dependency_components"] == ["catalog", "core-inventory"]
    assert result["selected_components"] == ["assets", "catalog", "core-inventory"]
    assert "tests/ui_qa/test_ui_pq_assets_deliverables_workflow.py" in result["test_targets"]
    assert "tests/ui_qa/test_ui_pq_authenticity_workflow.py" not in result["test_targets"]


def test_soundcloud_closure_includes_media_relationship_and_contract_setup() -> None:
    result = plan("isrc_manager/integrations/soundcloud/service.py")

    assert result["direct_components"] == ["soundcloud"]
    assert result["dependency_components"] == [
        "catalog",
        "contracts-rights",
        "core-inventory",
        "media-audio",
        "relationships-releases-parties",
    ]


def test_history_component_closure_includes_catalog_track_setup() -> None:
    result = plan("isrc_manager/history/replay_controller.py")

    assert result["direct_components"] == ["diagnostics-history-storage"]
    assert result["dependency_components"] == ["catalog", "core-inventory"]


def test_shared_dependency_change_forces_full_validation() -> None:
    result = plan("pyproject.toml")

    assert result["mode"] == "full"
    assert result["full_validation"] is True
    assert result["selected_components"] == sorted(ALL_COMPONENT_NAMES)
    assert "shared-infrastructure" in result["reasons"]


def test_dashboard_renderer_change_forces_full_validation() -> None:
    result = plan("scripts/update_qa_pq_history.py")

    assert result["full_validation"] is True
    assert "shared-infrastructure" in result["reasons"]
    assert len(result["test_targets"]) > 12


def test_full_plan_contains_every_ui_pq_test_target() -> None:
    result = plan("pyproject.toml")
    discovered = {path.as_posix() for path in Path("tests/ui_qa").glob("test_*.py")}

    assert set(result["test_targets"]) == discovered


def test_component_screenshot_test_change_is_incremental() -> None:
    result = plan("M\ttests/ui_qa/test_ui_pq_catalog_workflow.py")

    assert result["full_validation"] is False
    assert result["direct_components"] == ["catalog"]
    assert result["selected_components"] == ["catalog", "core-inventory"]
    assert result["changes"] == [
        {
            "path": "tests/ui_qa/test_ui_pq_catalog_workflow.py",
            "status": "modified",
        }
    ]


def test_lockfile_change_forces_full_validation() -> None:
    result = plan("uv.lock")

    assert result["full_validation"] is True
    assert result["path_impacts"] == [
        {
            "path": "uv.lock",
            "category": "shared-infrastructure",
            "components": (),
            "force_full": True,
        }
    ]


def test_release_tag_forces_full_even_for_documentation_change() -> None:
    result = plan("README.md", event_type="push", ref="refs/tags/v6.2.0")

    assert result["full_validation"] is True
    assert result["reasons"] == ["release-full-validation"]
    assert result["selected_components"] == sorted(ALL_COMPONENT_NAMES)


def test_manual_full_validation_request_forces_full() -> None:
    result = plan(
        "isrc_manager/assets/service.py",
        event_type="workflow_dispatch",
        full_validation=True,
    )

    assert result["full_validation"] is True
    assert "manual-full-validation" in result["reasons"]
    assert result["direct_components"] == ["assets"]
    assert "accounting" in result["forced_components"]


def test_scheduled_run_and_release_event_each_force_full() -> None:
    scheduled = plan("README.md", event_type="schedule")
    release = plan("README.md", event_type="release")

    assert scheduled["full_validation"] is True
    assert scheduled["reasons"] == ["scheduled-full-validation"]
    assert release["full_validation"] is True
    assert release["reasons"] == ["release-full-validation"]


@pytest.mark.parametrize(
    ("changed_path", "category"),
    [
        ("isrc_manager/new_feature/service.py", "unknown-production-path"),
        ("tests/test_new_unmapped_behavior.py", "unknown-test-path"),
        (".github/workflows/ci.yml", "shared-infrastructure"),
        ("isrc_manager/main_window.py", "shared-infrastructure"),
        ("isrc_manager/services/db_access.py", "shared-infrastructure"),
        ("isrc_manager/qa/visual.py", "shared-infrastructure"),
        ("isrc_manager/qa/impact.py", "shared-infrastructure"),
        ("isrc_manager/qa/impact_rules.py", "shared-infrastructure"),
        ("scripts/qa_pq_artifacts.py", "shared-infrastructure"),
        ("scripts/qa_pq_fingerprints.py", "shared-infrastructure"),
        ("scripts/qa_pq_provenance.py", "shared-infrastructure"),
        ("scripts/qa_pq_runtime.py", "shared-infrastructure"),
        ("scripts/trusted_ci_artifacts.py", "shared-infrastructure"),
        ("scripts/apply_help_screenshots.py", "shared-infrastructure"),
        ("tests/test_qa_pq_artifacts.py", "shared-infrastructure"),
        ("tests/test_trusted_ci_artifacts.py", "shared-infrastructure"),
        ("tests/test_apply_help_screenshots.py", "shared-infrastructure"),
        ("isrc_manager/tags/validation.py", "shared-validation-rules"),
        (
            "artifacts/ui_pq/visual/baselines/main_window.png",
            "shared-screenshot-baseline",
        ),
    ],
)
def test_unknown_and_shared_paths_fall_back_conservatively(
    changed_path: str, category: str
) -> None:
    result = plan(changed_path)

    assert result["full_validation"] is True
    assert category in result["reasons"]


def test_generated_dashboard_updates_do_not_create_pq_work() -> None:
    result = plan(
        "docs/validation/qa_pq_history.csv",
        "artifacts/ui_pq/evidence.json",
        "coverage.json",
    )

    assert result["mode"] == "none"
    assert result["has_pq_work"] is False
    assert result["provenance"]["input_categories"] == {
        "generated-output": [
            "artifacts/ui_pq/evidence.json",
            "coverage.json",
            "docs/validation/qa_pq_history.csv",
        ]
    }


def test_renamed_and_deleted_paths_keep_old_and_new_impacts_conservatively() -> None:
    result = plan(
        "D\tisrc_manager/media/bookmarks.py",
        "R100\tisrc_manager/assets/service.py\tisrc_manager/new_feature/assets_service.py",
    )

    assert result["full_validation"] is True
    assert result["direct_components"] == ["assets", "media-audio"]
    assert result["changed_paths"] == [
        "isrc_manager/assets/service.py",
        "isrc_manager/media/bookmarks.py",
        "isrc_manager/new_feature/assets_service.py",
    ]
    assert {change["status"] for change in result["changes"]} == {
        "deleted",
        "renamed-from",
        "renamed-to",
    }
    assert "unknown-production-path" in result["reasons"]


def test_incomplete_rename_record_forces_full_validation() -> None:
    result = plan("R100\tisrc_manager/assets/service.py")

    assert result["full_validation"] is True
    assert result["uncertainties"] == ["incomplete-rename-or-copy-record"]
    assert "uncertain-change-input" in result["reasons"]


def test_braced_rename_notation_expands_both_paths() -> None:
    result = plan("isrc_manager/assets/{models.py => asset_models.py}")

    assert result["full_validation"] is False
    assert result["direct_components"] == ["assets"]
    assert result["changed_paths"] == [
        "isrc_manager/assets/asset_models.py",
        "isrc_manager/assets/models.py",
    ]


def test_empty_or_outside_repository_input_forces_full() -> None:
    empty = plan()
    outside = plan("../external.py")

    assert empty["full_validation"] is True
    assert empty["reasons"] == ["no-changed-paths"]
    assert outside["full_validation"] is True
    assert "uncertain-path" in outside["reasons"]


def test_component_unions_and_hashes_are_deterministic() -> None:
    paths = [
        "isrc_manager/assets/service.py",
        "isrc_manager/media/bookmarks.py",
        "isrc_manager/assets/service.py",
    ]
    first = plan_qa_pq_impact(
        paths,
        source_commit="abc123",
        provenance_hashes={"dependencies": "sha256:deadbeef"},
    )
    second = plan_qa_pq_impact(
        reversed(paths),
        source_commit="abc123",
        provenance_hashes={"dependencies": "sha256:deadbeef"},
    )

    assert first == second
    assert first["direct_components"] == ["assets", "media-audio"]
    assert first["selected_components"] == [
        "assets",
        "catalog",
        "core-inventory",
        "media-audio",
    ]
    assert first["plan_hash"].startswith("sha256:")
    assert first["provenance"]["supplied_hashes"] == {"dependencies": "sha256:deadbeef"}


def test_cli_reads_change_file_and_writes_json_and_github_outputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    changes_path = tmp_path / "changes.txt"
    changes_path.write_text(
        "M\tisrc_manager/media/bookmarks.py\nD\tdocs/obsolete-guide.md\n",
        encoding="utf-8",
    )
    json_path = tmp_path / "plan.json"
    github_output_path = tmp_path / "github-output.txt"

    exit_code = main(
        [
            "--changed-file",
            str(changes_path),
            "--event-type",
            "pull_request",
            "--source-commit",
            "abc123",
            "--provenance-hash",
            "dependencies=sha256:cafe",
            "--output",
            str(json_path),
            "--github-output",
            str(github_output_path),
            "--compact",
        ]
    )

    assert exit_code == 0
    stdout_plan = json.loads(capsys.readouterr().out)
    assert json.loads(json_path.read_text(encoding="utf-8")) == stdout_plan
    assert stdout_plan["event"] == {"ref": "", "type": "pull_request"}
    assert stdout_plan["direct_components"] == ["media-audio"]

    outputs = dict(
        line.split("=", maxsplit=1)
        for line in github_output_path.read_text(encoding="utf-8").splitlines()
    )
    assert outputs["full_validation"] == "false"
    assert outputs["has_pq_work"] == "true"
    assert json.loads(outputs["selected_components"]) == [
        "catalog",
        "core-inventory",
        "media-audio",
    ]
    assert json.loads(outputs["plan_json"])["plan_hash"] == outputs["plan_hash"]


def test_cli_accepts_boolean_workflow_input_and_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("README.md\n"))

    assert main(["--stdin", "--full-validation", "true", "--compact"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["full_validation"] is True
    assert result["reasons"] == ["manual-full-validation"]


def test_cli_entrypoint_uses_only_the_standard_library() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "scripts/qa_pq_impact.py",
            "--changed",
            "README.md",
            "--compact",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout)["mode"] == "none"

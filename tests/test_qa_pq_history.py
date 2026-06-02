from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts import update_qa_pq_history as history


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read_history(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_qa_pq_history_appends_snapshot_with_code_loc_delta(tmp_path):
    repo_root = tmp_path
    package = repo_root / "isrc_manager"
    package.mkdir()
    (repo_root / "ISRC_manager.py").write_text("print('entry')\n", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "main.py").write_text(
        "# comment\n" "\n" "def run():\n" "    value = 1\n" "    return value\n",
        encoding="utf-8",
    )
    (package / "help_content.py").write_text(
        "HELP = '''excluded manual prose'''\n",
        encoding="utf-8",
    )
    coverage = repo_root / "coverage.json"
    _write_json(
        coverage,
        {
            "totals": {
                "percent_covered": 90.5,
                "percent_statements_covered": 93.25,
                "percent_branches_covered": 81.0,
            }
        },
    )
    artifacts = repo_root / "artifacts" / "ui_pq"
    _write_json(
        artifacts / "evidence.json",
        [
            {"test_id": "UI-PQ-ONE", "status": "passed"},
            {"test_id": "UI-PQ-TWO", "status": "failed"},
            {"test_id": "UI-PQ-THREE", "status": "partial"},
        ],
    )
    _write_csv(
        artifacts / "deviations.csv",
        [
            {"status": "open"},
            {"status": "pending_manual"},
            {"status": "pending_manual"},
        ],
        ["status"],
    )
    _write_csv(
        artifacts / "traceability_matrix.csv",
        [
            {"coverage_status": "covered"},
            {"coverage_status": "covered"},
            {"coverage_status": "pending_manual"},
        ],
        ["coverage_status"],
    )
    _write_json(
        artifacts / "visual" / "visual_manifest.json",
        {"comparisons": [{"passed": True}, {"passed": False}]},
    )
    _write_json(
        artifacts / "visual" / "business_workflow_manifest.json",
        {"comparisons": [{"passed": True}]},
    )
    _write_json(
        artifacts / "visual" / "generated_output_manifest.json",
        {"comparisons": []},
    )
    history_path = repo_root / "docs" / "validation" / "qa_pq_history.csv"
    _write_csv(
        history_path,
        [{"app_loc": "3", "timestamp": "2026-05-31T00:00:00Z"}],
        list(history.HISTORY_COLUMNS),
    )

    assert (
        history.main(
            [
                "--repo-root",
                str(repo_root),
                "--coverage",
                str(coverage),
                "--pq-artifacts",
                str(artifacts),
                "--history",
                str(history_path),
                "--timestamp",
                "2026-06-02T12:00:00Z",
                "--source",
                "test",
                "--branch",
                "main",
                "--commit-sha",
                "abc123",
            ]
        )
        == 0
    )

    rows = _read_history(history_path)
    assert len(rows) == 2
    snapshot = rows[-1]
    assert snapshot["timestamp"] == "2026-06-02T12:00:00Z"
    assert snapshot["source"] == "test"
    assert snapshot["branch"] == "main"
    assert snapshot["commit_sha"] == "abc123"
    assert snapshot["app_loc"] == "4"
    assert snapshot["app_loc_delta"] == "1"
    assert snapshot["total_coverage"] == "90.5000"
    assert snapshot["statement_coverage"] == "93.2500"
    assert snapshot["branch_coverage"] == "81.0000"
    assert snapshot["total_tests"] == "3"
    assert snapshot["passed_tests"] == "1"
    assert snapshot["failed_tests"] == "1"
    assert snapshot["partial_tests"] == "1"
    assert snapshot["total_deviations"] == "3"
    assert snapshot["open_deviations"] == "1"
    assert snapshot["pending_manual_deviations"] == "2"
    assert snapshot["traceability_rows"] == "3"
    assert snapshot["traceability_covered"] == "2"
    assert snapshot["visual_checks_total"] == "3"
    assert snapshot["visual_checks_failed"] == "1"

    (package / "main.py").write_text(
        "def run():\n" "    value = 1\n" "    other = 2\n" "    return value + other\n",
        encoding="utf-8",
    )
    assert (
        history.main(
            [
                "--repo-root",
                str(repo_root),
                "--coverage",
                str(coverage),
                "--pq-artifacts",
                str(artifacts),
                "--history",
                str(history_path),
                "--timestamp",
                "2026-06-02T13:00:00Z",
                "--source",
                "test",
                "--branch",
                "main",
                "--commit-sha",
                "def456",
            ]
        )
        == 0
    )
    rows = _read_history(history_path)
    assert len(rows) == 3
    assert rows[-1]["app_loc"] == "5"
    assert rows[-1]["app_loc_delta"] == "1"


def test_ci_workflow_updates_dashboard_history_after_coverage_report():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Upload UI PQ artifacts" in workflow
    assert "coverage json -o ../coverage.json" in workflow
    assert "scripts/update_qa_pq_history.py" in workflow
    assert "docs/validation/qa_pq_history.csv" in workflow
    assert "Upload QA/PQ dashboard history" in workflow
    assert "Update QA/PQ dashboard history [skip ci]" in workflow

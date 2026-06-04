from __future__ import annotations

import csv
import json
import tempfile
import unittest
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


class QAPQHistoryTests(unittest.TestCase):
    def test_qa_pq_history_appends_snapshot_with_code_loc_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
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
                    "meta": {"timestamp": "2026-06-02T11:59:00"},
                    "totals": {
                        "percent_covered": 90.5,
                        "percent_statements_covered": 93.25,
                        "percent_branches_covered": 81.0,
                        "covered_lines": 905,
                        "num_statements": 1000,
                        "missing_lines": 95,
                        "covered_branches": 81,
                        "missing_branches": 19,
                    },
                    "files": {
                        str(repo_root / "isrc_manager" / "low.py"): {
                            "summary": {
                                "percent_covered": 55.125,
                                "percent_branches_covered": 25.0,
                                "missing_lines": 9,
                                "num_statements": 20,
                            }
                        },
                        "isrc_manager/high.py": {
                            "summary": {
                                "percent_covered": 98.75,
                                "percent_branches_covered": 95.0,
                                "missing_lines": 1,
                                "num_statements": 80,
                            }
                        },
                    },
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
            coverage_snapshot_path = repo_root / "docs" / "validation" / "coverage_snapshot.json"
            _write_csv(
                history_path,
                [{"app_loc": "3", "timestamp": "2026-05-31T00:00:00Z"}],
                list(history.HISTORY_COLUMNS),
            )

            self.assertEqual(
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
                        "--coverage-snapshot",
                        str(coverage_snapshot_path),
                        "--timestamp",
                        "2026-06-02T12:00:00Z",
                        "--source",
                        "test",
                        "--branch",
                        "main",
                        "--commit-sha",
                        "abc123",
                    ]
                ),
                0,
            )

            rows = _read_history(history_path)
            self.assertEqual(len(rows), 2)
            snapshot = rows[-1]
            self.assertEqual(snapshot["timestamp"], "2026-06-02T12:00:00Z")
            self.assertEqual(snapshot["source"], "test")
            self.assertEqual(snapshot["branch"], "main")
            self.assertEqual(snapshot["commit_sha"], "abc123")
            self.assertEqual(snapshot["app_loc"], "4")
            self.assertEqual(snapshot["app_loc_delta"], "1")
            self.assertEqual(snapshot["total_coverage"], "90.5000")
            self.assertEqual(snapshot["statement_coverage"], "93.2500")
            self.assertEqual(snapshot["branch_coverage"], "81.0000")
            self.assertEqual(snapshot["total_tests"], "3")
            self.assertEqual(snapshot["passed_tests"], "1")
            self.assertEqual(snapshot["failed_tests"], "1")
            self.assertEqual(snapshot["partial_tests"], "1")
            self.assertEqual(snapshot["total_deviations"], "3")
            self.assertEqual(snapshot["open_deviations"], "1")
            self.assertEqual(snapshot["pending_manual_deviations"], "2")
            self.assertEqual(snapshot["traceability_rows"], "3")
            self.assertEqual(snapshot["traceability_covered"], "2")
            self.assertEqual(snapshot["visual_checks_total"], "3")
            self.assertEqual(snapshot["visual_checks_failed"], "1")

            coverage_snapshot = json.loads(coverage_snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(coverage_snapshot["timestamp"], "2026-06-02T11:59:00")
            self.assertEqual(coverage_snapshot["linePercent"], 90.5)
            self.assertEqual(coverage_snapshot["statementPercent"], 93.25)
            self.assertEqual(coverage_snapshot["branchPercent"], 81.0)
            self.assertEqual(coverage_snapshot["coveredLines"], 905)
            self.assertEqual(coverage_snapshot["filesMeasured"], 2)
            self.assertEqual(coverage_snapshot["lowestFiles"][0]["path"], "isrc_manager/low.py")
            self.assertEqual(coverage_snapshot["lowestFiles"][0]["percent"], 55.12)
            self.assertEqual(
                coverage_snapshot["coverageWins"][0]["path"],
                "isrc_manager/high.py",
            )

            (package / "main.py").write_text(
                "def run():\n" "    value = 1\n" "    other = 2\n" "    return value + other\n",
                encoding="utf-8",
            )
            self.assertEqual(
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
                ),
                0,
            )
            rows = _read_history(history_path)
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[-1]["app_loc"], "5")
            self.assertEqual(rows[-1]["app_loc_delta"], "1")

    def test_ci_workflow_updates_dashboard_history_after_coverage_report(self) -> None:
        workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("Upload UI PQ artifacts", workflow)
        self.assertIn("coverage json -o ../coverage.json", workflow)
        self.assertIn("scripts/update_qa_pq_history.py", workflow)
        self.assertIn("docs/validation/qa_pq_history.csv", workflow)
        self.assertIn("docs/validation/coverage_snapshot.json", workflow)
        self.assertIn("Upload QA/PQ dashboard data", workflow)
        self.assertIn("Update QA/PQ dashboard data [skip ci]", workflow)


if __name__ == "__main__":
    unittest.main()

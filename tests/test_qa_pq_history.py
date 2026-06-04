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
            qa_package = package / "qa"
            qa_package.mkdir()
            (repo_root / "ISRC_manager.py").write_text("print('entry')\n", encoding="utf-8")
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "main.py").write_text(
                "# comment\n" "\n" "def run():\n" "    value = 1\n" "    return value\n",
                encoding="utf-8",
            )
            (qa_package / "scenarios.py").write_text(
                "def validate_dashboard():\n" "    return 'qa-only'\n",
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
                        "percent_covered": 99.9,
                        "percent_statements_covered": 99.8,
                        "percent_branches_covered": 99.7,
                        "covered_lines": 999,
                        "num_statements": 1000,
                        "missing_lines": 1,
                        "covered_branches": 997,
                        "num_branches": 1000,
                        "missing_branches": 3,
                    },
                    "files": {
                        str(repo_root / "isrc_manager" / "low.py"): {
                            "summary": {
                                "covered_lines": 11,
                                "missing_lines": 9,
                                "num_statements": 20,
                                "covered_branches": 1,
                                "missing_branches": 3,
                                "num_branches": 4,
                            }
                        },
                        "isrc_manager/high.py": {
                            "summary": {
                                "covered_lines": 79,
                                "missing_lines": 1,
                                "num_statements": 80,
                                "covered_branches": 19,
                                "missing_branches": 1,
                                "num_branches": 20,
                            }
                        },
                        "isrc_manager/qa/scenarios.py": {
                            "summary": {
                                "covered_lines": 100,
                                "missing_lines": 0,
                                "num_statements": 100,
                                "covered_branches": 40,
                                "missing_branches": 0,
                                "num_branches": 40,
                            }
                        },
                        "tests/test_dashboard.py": {
                            "summary": {
                                "covered_lines": 50,
                                "missing_lines": 0,
                                "num_statements": 50,
                                "covered_branches": 20,
                                "missing_branches": 0,
                                "num_branches": 20,
                            }
                        },
                        "scripts/dashboard_tool.py": {
                            "summary": {
                                "covered_lines": 30,
                                "missing_lines": 0,
                                "num_statements": 30,
                                "covered_branches": 10,
                                "missing_branches": 0,
                                "num_branches": 10,
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
            self.assertEqual(snapshot["total_coverage"], "88.7097")
            self.assertEqual(snapshot["statement_coverage"], "90.0000")
            self.assertEqual(snapshot["branch_coverage"], "83.3333")
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
            self.assertEqual(coverage_snapshot["linePercent"], 88.71)
            self.assertEqual(coverage_snapshot["statementPercent"], 90.0)
            self.assertEqual(coverage_snapshot["branchPercent"], 83.33)
            self.assertEqual(coverage_snapshot["coveredLines"], 90)
            self.assertEqual(coverage_snapshot["statements"], 100)
            self.assertEqual(coverage_snapshot["coveredBranches"], 20)
            self.assertEqual(coverage_snapshot["missingBranches"], 4)
            self.assertEqual(coverage_snapshot["filesMeasured"], 2)
            self.assertEqual(coverage_snapshot["filesExcluded"], 3)
            self.assertIn("isrc_manager/qa/scenarios.py", coverage_snapshot["excludedFiles"])
            self.assertIn("tests/test_dashboard.py", coverage_snapshot["excludedFiles"])
            self.assertIn("scripts/dashboard_tool.py", coverage_snapshot["excludedFiles"])
            self.assertEqual(coverage_snapshot["lowestFiles"][0]["path"], "isrc_manager/low.py")
            self.assertEqual(coverage_snapshot["lowestFiles"][0]["percent"], 50.0)
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

    def test_dashboard_html_requires_live_coverage_artifacts(self) -> None:
        dashboard = Path("docs/validation/qa_pq_dashboard.html").read_text(encoding="utf-8")

        self.assertNotIn("initial-dashboard-data", dashboard)
        self.assertNotIn("Waiting for live published artifacts", dashboard)
        self.assertNotIn("reloadArtifactsButton", dashboard)
        self.assertNotIn("resetSnapshotButton", dashboard)
        self.assertNotIn("Reload artifacts", dashboard)
        self.assertNotIn("Clear live data", dashboard)
        self.assertIn('coverage: "coverage_snapshot.json"', dashboard)
        self.assertIn("artifactPollIntervalMs", dashboard)
        self.assertIn("pollLiveArtifacts", dashboard)
        self.assertIn("window.setInterval(pollLiveArtifacts, artifactPollIntervalMs)", dashboard)
        self.assertIn("fetchLiveArtifactBundle", dashboard)
        self.assertIn("fetchText(artifactPaths.coverage)", dashboard)
        self.assertIn("requireCoverageNumber", dashboard)
        self.assertIn("No static coverage values are shown", dashboard)
        self.assertIn("let dashboardData = null", dashboard)


if __name__ == "__main__":
    unittest.main()

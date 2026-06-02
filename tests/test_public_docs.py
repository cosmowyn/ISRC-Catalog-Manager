from __future__ import annotations

import csv
import json
import re
import unittest
from pathlib import Path


class PublicDocsTests(unittest.TestCase):
    def _markdown_targets(self, path: Path) -> list[Path]:
        root = path.parent
        targets: list[Path] = []
        for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            raw_target = match.group(1).strip()
            if not raw_target or raw_target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = raw_target.split("#", 1)[0]
            if not target:
                continue
            targets.append((root / target).resolve())
        return targets

    def test_public_doc_entrypoints_only_link_to_existing_local_targets(self):
        repo_root = Path(__file__).resolve().parents[1]
        entrypoints = [
            repo_root / "README.md",
            repo_root / "docs" / "README.md",
        ]

        for entrypoint in entrypoints:
            for target in self._markdown_targets(entrypoint):
                self.assertTrue(
                    target.exists(), f"Missing local doc target from {entrypoint}: {target}"
                )

    def test_docs_hub_positions_in_app_help_as_primary_manual(self):
        repo_root = Path(__file__).resolve().parents[1]
        docs_hub = (repo_root / "docs" / "README.md").read_text(encoding="utf-8")
        readme = (repo_root / "README.md").read_text(encoding="utf-8")

        self.assertIn("primary user-facing manual", docs_hub)
        self.assertIn("integrated manual", readme)

    def test_readme_links_to_live_qa_pq_dashboard_badge(self):
        repo_root = Path(__file__).resolve().parents[1]
        readme = (repo_root / "README.md").read_text(encoding="utf-8")

        self.assertIn("[![QA/PQ Dashboard]", readme)
        self.assertIn("https://img.shields.io/badge/QA%2FPQ-dashboard-live-success", readme)
        self.assertIn("https://cosmowyn.github.io/ISRC-Catalog-Manager/validation/", readme)

    def test_qa_pq_dashboard_is_static_and_artifact_backed(self):
        repo_root = Path(__file__).resolve().parents[1]
        dashboard = (repo_root / "docs" / "validation" / "qa_pq_dashboard.html").read_text(
            encoding="utf-8"
        )
        dashboard_entrypoint = (repo_root / "docs" / "validation" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("QA/QC and UI PQ Dashboard", dashboard)
        self.assertIn('id="initial-dashboard-data"', dashboard)
        self.assertIn('id="chartGrid"', dashboard)
        self.assertIn('id="historyGraph"', dashboard)
        self.assertIn('id="historyGranularity"', dashboard)
        self.assertIn("renderHistory", dashboard)
        self.assertIn("refreshHistoryFromCsv", dashboard)
        self.assertIn("reloadArtifactsButton", dashboard)
        self.assertIn("renderCharts", dashboard)
        self.assertIn("conic-gradient", dashboard)
        self.assertIn("stacked-graph", dashboard)
        self.assertIn("qa_pq_history.csv", dashboard)
        self.assertIn("../../coverage.json", dashboard)
        self.assertIn("../../artifacts/ui_pq/evidence.json", dashboard)
        self.assertIn("../../artifacts/ui_pq/deviations.csv", dashboard)
        self.assertNotIn("<script src=", dashboard)
        self.assertNotIn("https://", dashboard)
        self.assertNotIn("http://", dashboard)
        self.assertIn("qa_pq_dashboard.html", dashboard_entrypoint)
        self.assertIn('rel="canonical"', dashboard_entrypoint)

        match = re.search(
            r'<script id="initial-dashboard-data" type="application/json">\s*(\{.*?\})\s*</script>',
            dashboard,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Dashboard must include parseable embedded data")
        snapshot = json.loads(match.group(1))

        self.assertGreaterEqual(snapshot["coverage"]["linePercent"], 0)
        self.assertGreaterEqual(snapshot["coverage"]["branchPercent"], 0)
        self.assertTrue(snapshot["coverage"]["lowestFiles"])
        self.assertIn(
            "UI-PQ-HELP-001",
            {event["testId"] for event in snapshot["pq"]["events"]},
        )
        self.assertTrue(snapshot["pq"]["visualManifests"])
        self.assertTrue(snapshot["history"])

    def test_qa_pq_history_csv_has_dashboard_columns(self):
        repo_root = Path(__file__).resolve().parents[1]
        history_path = repo_root / "docs" / "validation" / "qa_pq_history.csv"

        with history_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        self.assertTrue(rows)
        self.assertIn("timestamp", rows[0])
        self.assertIn("app_loc", rows[0])
        self.assertIn("app_loc_delta", rows[0])
        self.assertIn("total_coverage", rows[0])
        self.assertIn("failed_tests", rows[0])
        self.assertIn("total_deviations", rows[0])


if __name__ == "__main__":
    unittest.main()

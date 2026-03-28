from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()

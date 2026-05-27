import tempfile
import unittest
from pathlib import Path

from scripts import sync_version_docs as sync

STALE_MARKER = (
    f"{sync.SYNC_START}\n"
    "Current source release: `0.0.1` (`v0.0.1`).\n"
    "Latest repository metadata: [`docs/releases/latest.json`](docs/releases/latest.json).\n"
    "Latest release notes: [`RELEASE_NOTES.md`](RELEASE_NOTES.md).\n"
    f"{sync.SYNC_END}"
)


class VersionDocsSyncTests(unittest.TestCase):
    def test_sync_updates_only_current_public_version_surfaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            historical = self._write_repo_fixture(root, version="3.2.1")
            historical_before = historical.read_text(encoding="utf-8")

            changes = sync.sync_version_docs(root)

            changed_paths = {change.path for change in changes}
            self.assertEqual(
                changed_paths,
                {
                    "README.md",
                    "docs/release-builds.md",
                    "docs/releases/latest.json",
                    "RELEASE_NOTES.md",
                },
            )
            self.assertIn("Current source release: `3.2.1`", (root / "README.md").read_text())
            self.assertIn(
                "Current canonical source version: `3.2.1`",
                (root / "docs" / "release-builds.md").read_text(),
            )
            self.assertIn(
                '"version": "3.2.1"', (root / "docs" / "releases" / "latest.json").read_text()
            )
            self.assertIn(
                "docs/releases/v3.2.1.md",
                (root / "docs" / "releases" / "latest.json").read_text(),
            )
            self.assertIn("# ISRC Catalog Manager 3.2.1", (root / "RELEASE_NOTES.md").read_text())
            self.assertEqual(historical.read_text(encoding="utf-8"), historical_before)
            self.assertEqual(sync.sync_version_docs(root, check=True), ())

    def test_check_mode_detects_stale_docs_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_repo_fixture(root, version="3.2.1")
            stale_readme = (root / "README.md").read_text(encoding="utf-8")

            self.assertEqual(sync.main(["--check", "--root", str(root)]), 1)
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), stale_readme)

            self.assertEqual(sync.main(["--root", str(root)]), 0)
            self.assertEqual(sync.main(["--check", "--root", str(root)]), 0)

    def test_missing_marker_is_rejected_instead_of_broad_rewrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_repo_fixture(root, version="3.2.1")
            readme = root / "README.md"
            readme.write_text("Version 0.0.1 appears here but is not marked.\n", encoding="utf-8")

            with self.assertRaises(sync.VersionSyncError):
                sync.sync_version_docs(root)

            self.assertEqual(
                readme.read_text(encoding="utf-8"),
                "Version 0.0.1 appears here but is not marked.\n",
            )

    def _write_repo_fixture(self, root: Path, *, version: str) -> Path:
        docs = root / "docs"
        releases = docs / "releases"
        releases.mkdir(parents=True)
        (root / "pyproject.toml").write_text(
            '[project]\nname = "isrc-catalog-manager"\nversion = "' + version + '"\n',
            encoding="utf-8",
        )
        (root / "README.md").write_text("# Project\n\n" + STALE_MARKER + "\n", encoding="utf-8")
        (docs / "release-builds.md").write_text(
            "# Release Build Automation\n\n" + STALE_MARKER + "\n",
            encoding="utf-8",
        )
        (root / "RELEASE_NOTES.md").write_text(
            "# ISRC Catalog Manager 0.0.1\n\nVersion: 0.0.1\n",
            encoding="utf-8",
        )
        (releases / "latest.json").write_text(
            "{\n"
            '  "version": "0.0.1",\n'
            '  "released_at": "2026-04-26",\n'
            '  "summary": "Old summary",\n'
            '  "release_notes_url": "https://example.invalid/v0.0.1.md",\n'
            '  "minimum_supported_version": null\n'
            "}\n",
            encoding="utf-8",
        )
        (releases / f"v{version}.md").write_text(
            "# Existing generated current release note\n\nVersion: 0.0.1\n",
            encoding="utf-8",
        )
        historical = releases / "v1.0.0.md"
        historical.write_text("# Historical\n\nVersion: 1.0.0\n", encoding="utf-8")
        return historical


if __name__ == "__main__":
    unittest.main()

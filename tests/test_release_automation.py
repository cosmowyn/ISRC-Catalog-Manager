import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import release_automation as automation


class ReleaseAutomationTests(unittest.TestCase):
    def test_classifies_major_minor_patch_and_skip_cases(self):
        self.assertEqual(
            automation.classify_bump(
                [automation.CommitInfo(sha="1", subject="feat: add update checks")]
            ),
            "minor",
        )
        self.assertEqual(
            automation.classify_bump(
                [automation.CommitInfo(sha="1", subject="fix: repair update manifest")]
            ),
            "patch",
        )
        self.assertEqual(
            automation.classify_bump(
                [automation.CommitInfo(sha="1", subject="feat!: change package format")]
            ),
            "major",
        )
        self.assertIsNone(
            automation.classify_bump(
                [automation.CommitInfo(sha="1", subject="docs: skip this [skip version]")]
            )
        )

    def test_bot_and_generated_only_commits_are_ignored(self):
        commits = [
            automation.CommitInfo(
                sha="1",
                subject="chore(release): v3.2.1 [skip version]",
                author_name="github-actions[bot]",
                files=("pyproject.toml", "docs/releases/latest.json"),
            ),
            automation.CommitInfo(
                sha="2",
                subject="docs: update release metadata",
                files=("docs/releases/latest.json", "RELEASE_NOTES.md"),
            ),
        ]

        self.assertEqual(automation.releasable_commits(commits), ())
        self.assertIsNone(automation.classify_bump(commits))

    def test_release_notes_group_commit_messages_without_invention(self):
        markdown = automation.generate_release_markdown(
            version="3.2.1",
            released_at="2026-04-26",
            bump_level="minor",
            commits=[
                automation.CommitInfo(sha="1", subject="feat: add update notification"),
                automation.CommitInfo(sha="2", subject="fix: avoid startup crash"),
                automation.CommitInfo(sha="3", subject="refactor: split version helpers"),
            ],
        )

        self.assertIn("- add update notification", markdown)
        self.assertIn("- avoid startup crash", markdown)
        self.assertIn("- split version helpers", markdown)
        self.assertNotIn("download", markdown.lower())

    def test_apply_release_plan_updates_expected_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pyproject = root / "pyproject.toml"
            version_module = root / "version.py"
            releases_dir = root / "docs" / "releases"
            notes_path = root / "RELEASE_NOTES.md"
            pyproject.write_text(
                '[project]\nname = "isrc-catalog-manager"\nversion = "3.2.0"\n',
                encoding="utf-8",
            )
            version_module.write_text('__version__ = "3.2.0"\n', encoding="utf-8")
            plan = automation.ReleasePlan(
                current_version="3.2.0",
                next_version="3.2.1",
                bump_level="patch",
                commits=(automation.CommitInfo(sha="1", subject="fix: repair update checks"),),
            )

            with (
                mock.patch.object(automation, "PYPROJECT_PATH", pyproject),
                mock.patch.object(automation, "VERSION_MODULE_PATH", version_module),
                mock.patch.object(automation, "RELEASES_DIR", releases_dir),
                mock.patch.object(automation, "LATEST_MANIFEST_PATH", releases_dir / "latest.json"),
                mock.patch.object(automation, "RELEASE_NOTES_PATH", notes_path),
            ):
                automation.apply_release_plan(plan)

            self.assertIn('version = "3.2.1"', pyproject.read_text(encoding="utf-8"))
            self.assertIn('__version__ = "3.2.1"', version_module.read_text(encoding="utf-8"))
            self.assertTrue((releases_dir / "latest.json").is_file())
            self.assertTrue((releases_dir / "v3.2.1.md").is_file())
            self.assertTrue(notes_path.is_file())

    def test_write_project_version_only_updates_project_section(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject = Path(tmpdir) / "pyproject.toml"
            pyproject.write_text(
                '[project]\nname = "isrc-catalog-manager"\n\n'
                '[tool.example]\nversion = "9.9.9"\n',
                encoding="utf-8",
            )

            with self.assertRaises(RuntimeError):
                automation.write_project_version("3.14.4", pyproject)

            self.assertIn('version = "9.9.9"', pyproject.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import release_automation as automation
from scripts import sync_version_docs as version_sync


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
                files=(
                    "docs/releases/latest.json",
                    "RELEASE_NOTES.md",
                    "README.md",
                    "docs/release-builds.md",
                ),
            ),
        ]

        self.assertEqual(automation.releasable_commits(commits), ())
        self.assertIsNone(automation.classify_bump(commits))

    def test_production_code_fingerprint_gates_automatic_bump(self):
        support_commits = (
            automation.CommitInfo(
                sha="1",
                subject="test: refresh qualification evidence",
                files=("tests/ui_qa/test_ui_pq_help_documentation.py",),
            ),
        )
        production_commits = (
            automation.CommitInfo(
                sha="2",
                subject="fix: repair crash reporting submission",
                files=("isrc_manager/reporting/service.py",),
            ),
        )
        support_only = automation.ApplicationChangeFingerprint()
        production_change = automation.ApplicationChangeFingerprint(changed_files=1, added_lines=1)

        self.assertFalse(automation.should_create_release(support_commits, support_only))
        self.assertTrue(automation.should_create_release(production_commits, production_change))
        self.assertIsNone(
            automation.build_release_plan(
                "5.0.0",
                support_commits,
                fingerprint=support_only,
                require_release_gate=True,
            )
        )
        self.assertEqual(
            automation.build_release_plan(
                "5.0.0",
                production_commits,
                fingerprint=production_change,
                require_release_gate=True,
            ).next_version,
            "5.0.1",
        )

    def test_explicit_bump_marker_overrides_application_fingerprint_gate(self):
        commits = (
            automation.CommitInfo(
                sha="1",
                subject="docs: prepare release [bump version]",
                files=("docs/manual.md",),
            ),
        )
        plan = automation.build_release_plan(
            "5.0.0",
            commits,
            fingerprint=automation.ApplicationChangeFingerprint(
                changed_files=0,
                added_lines=0,
                deleted_lines=0,
            ),
            require_release_gate=True,
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan.next_version, "5.0.1")

    def test_parse_application_numstat_handles_binary_rows(self):
        fingerprint = automation.parse_application_numstat(
            [
                "12\t8\tisrc_manager/main_window.py",
                "7\t3\tisrc_manager/qa/help_validation.py",
                "4\t2\tisrc_manager/help_content.py",
                "6\t2\tisrc_manager/version.py",
                "1\t1\ttests/test_release_automation.py",
                "5\t0\tdocs/release-builds.md",
                "2\t2\tisrc_manager/reporting/service.py",
                "-\t-\tisrc_manager/assets/logo.png",
                "2\t0\tresources/reporting.json",
                "3\t0\tbuild.py",
            ]
        )

        self.assertEqual(fingerprint.changed_files, 5)
        self.assertEqual(fingerprint.added_lines, 19)
        self.assertEqual(fingerprint.deleted_lines, 10)
        self.assertEqual(fingerprint.touched_lines, 29)

    def test_write_github_output_is_noop_without_output_path(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            automation.write_github_output(bumped="false")

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
            (root / "docs").mkdir(parents=True)
            pyproject.write_text(
                '[project]\nname = "isrc-catalog-manager"\nversion = "3.2.0"\n',
                encoding="utf-8",
            )
            version_module.write_text('__version__ = "3.2.0"\n', encoding="utf-8")
            (root / "README.md").write_text(
                f"{version_sync.SYNC_START}\nstale\n{version_sync.SYNC_END}\n",
                encoding="utf-8",
            )
            (root / "docs" / "release-builds.md").write_text(
                f"{version_sync.SYNC_START}\nstale\n{version_sync.SYNC_END}\n",
                encoding="utf-8",
            )
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
            self.assertIn("Current source release: `3.2.1`", (root / "README.md").read_text())
            self.assertIn(
                "Current canonical source version: `3.2.1`",
                (root / "docs" / "release-builds.md").read_text(),
            )

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

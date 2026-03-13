import tempfile
import unittest
from pathlib import Path

from isrc_manager.services import ProfileStoreService, ProfileWorkflowService


class ProfileWorkflowServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.database_dir = Path(self.tmpdir.name) / "Database"
        self.database_dir.mkdir(parents=True, exist_ok=True)
        self.profile_store = ProfileStoreService(self.database_dir)
        self.service = ProfileWorkflowService(self.database_dir, self.profile_store)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_list_profile_choices_includes_external_current_database(self):
        local_profile = self.profile_store.build_profile_path("Local")
        local_profile.write_text("local", encoding="utf-8")
        external_profile = Path(self.tmpdir.name) / "external.db"
        external_profile.write_text("external", encoding="utf-8")

        choices = self.service.list_profile_choices(str(external_profile))

        self.assertEqual(
            [(choice.label, choice.path) for choice in choices],
            [
                (local_profile.name, str(local_profile)),
                (f"{external_profile.name} (external)", str(external_profile)),
            ],
        )

    def test_build_new_profile_path_rejects_existing_file(self):
        existing = self.profile_store.build_profile_path("Existing")
        existing.write_text("existing", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            self.service.build_new_profile_path("Existing")

    def test_delete_current_profile_returns_fallback_choice(self):
        current = self.profile_store.build_profile_path("Current")
        other = self.profile_store.build_profile_path("Other")
        current.write_text("current", encoding="utf-8")
        other.write_text("other", encoding="utf-8")

        result = self.service.delete_profile(current, current_db_path=str(current))

        self.assertTrue(result.deleting_current)
        self.assertEqual(result.fallback_path, str(other))
        self.assertFalse(current.exists())

    def test_delete_last_current_profile_falls_back_to_default_library_path(self):
        current = self.profile_store.build_profile_path("Current")
        current.write_text("current", encoding="utf-8")

        result = self.service.delete_profile(current, current_db_path=str(current))

        self.assertTrue(result.deleting_current)
        self.assertEqual(result.fallback_path, str(self.database_dir / "library.db"))
        self.assertFalse(current.exists())


if __name__ == "__main__":
    unittest.main()

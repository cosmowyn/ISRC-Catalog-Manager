import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager.constants import MAX_HISTORY_STORAGE_BUDGET_MB
from isrc_manager.isrc_registry import ApplicationISRCRegistryService


class ApplicationISRCRegistryServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.data_root = self.root / "data"
        self.profile_dir = self.data_root / "Database"
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.service = ApplicationISRCRegistryService(self.data_root)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _create_profile(
        self,
        name: str,
        tracks: list[tuple[int, str, str]],
        *,
        prefix: str = "NLABC",
        artist_code: str = "00",
    ) -> Path:
        path = self.profile_dir / name
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE ISRC_Prefix(id INTEGER PRIMARY KEY, prefix TEXT NOT NULL)")
            conn.execute("INSERT INTO ISRC_Prefix(id, prefix) VALUES (1, ?)", (prefix,))
            conn.execute("CREATE TABLE app_kv(key TEXT PRIMARY KEY, value TEXT)")
            conn.execute(
                "INSERT INTO app_kv(key, value) VALUES ('isrc_artist_code', ?)",
                (artist_code,),
            )
            conn.execute("""
                CREATE TABLE Tracks(
                    id INTEGER PRIMARY KEY,
                    track_title TEXT NOT NULL,
                    isrc TEXT NOT NULL,
                    isrc_compact TEXT
                )
                """)
            for track_id, title, isrc in tracks:
                compact = isrc.replace("-", "").upper()
                conn.execute(
                    "INSERT INTO Tracks(id, track_title, isrc, isrc_compact) VALUES (?, ?, ?, ?)",
                    (track_id, title, isrc, compact),
                )
            conn.commit()
        finally:
            conn.close()
        return path

    def test_sync_indexes_all_known_profiles_not_just_pairwise(self):
        profile_a = self._create_profile("a.db", [(1, "One", "NL-ABC-26-00001")])
        profile_b = self._create_profile("b.db", [(2, "Two", "NL-ABC-26-00002")])
        profile_c = self._create_profile("c.db", [(3, "Three", "NL-ABC-26-00003")])

        summary = self.service.sync_profiles([profile_a, profile_b, profile_c])

        self.assertEqual(summary.profile_count, 3)
        self.assertEqual(summary.claim_count, 3)
        self.assertIsNotNone(self.service.find_conflict("NL-ABC-26-00003", profile_path=profile_a))

    def test_sync_reports_cross_profile_duplicate_without_replacing_original_claim(self):
        profile_a = self._create_profile("a.db", [(1, "Original", "NL-ABC-26-00001")])
        profile_b = self._create_profile("b.db", [(2, "Duplicate", "NL-ABC-26-00001")])

        summary = self.service.sync_profiles([profile_a, profile_b])

        self.assertEqual(summary.conflict_count, 1)
        conflict = self.service.find_conflict("NLABC2600001", profile_path=profile_b)
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.profile_name, "a.db")
        self.assertEqual(conflict.track_title, "Original")

    def test_reservation_blocks_claims_from_other_profiles_and_can_activate(self):
        profile_a = self._create_profile("a.db", [])
        profile_b = self._create_profile("b.db", [])
        self.service.sync_profiles([profile_a, profile_b])

        conflict = self.service.reserve_isrc(
            "NL-ABC-26-00077",
            profile_path=profile_a,
            profile_name="a.db",
            track_title="Reserved",
        )
        self.assertIsNone(conflict)

        conflict = self.service.reserve_isrc(
            "NL-ABC-26-00077",
            profile_path=profile_b,
            profile_name="b.db",
            track_title="Blocked",
        )
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.profile_name, "a.db")

        activation_conflict = self.service.activate_isrc(
            "NL-ABC-26-00077",
            profile_path=profile_a,
            profile_name="a.db",
            track_id=42,
            track_title="Reserved",
        )
        self.assertIsNone(activation_conflict)
        self.assertIsNone(
            self.service.find_conflict(
                "NL-ABC-26-00077",
                profile_path=profile_a,
                exclude_track_id=42,
            )
        )

    def test_sync_removes_claims_for_profiles_no_longer_active(self):
        profile_a = self._create_profile("a.db", [(1, "One", "NL-ABC-26-00001")])
        profile_b = self._create_profile("b.db", [(2, "Two", "NL-ABC-26-00002")])
        self.service.sync_profiles([profile_a, profile_b])

        self.service.sync_profiles([profile_a])

        self.assertIsNone(self.service.find_conflict("NL-ABC-26-00002", profile_path=profile_a))

    def test_empty_sync_and_invalid_codes_are_noop(self):
        profile_a = self._create_profile("a.db", [(1, "One", "NL-ABC-26-00001")])
        self.service.sync_profiles([profile_a])

        summary = self.service.sync_profiles([])

        self.assertEqual(summary.profile_count, 0)
        self.assertEqual(summary.claim_count, 0)
        self.assertIsNone(self.service.find_conflict("NL-ABC-26-00001", profile_path=profile_a))
        self.assertIsNone(self.service.find_conflict("not-an-isrc"))
        self.assertIsNone(
            self.service.reserve_isrc(
                "not-an-isrc",
                profile_path=profile_a,
                profile_name="a.db",
            )
        )
        self.assertIsNone(
            self.service.activate_isrc(
                "not-an-isrc",
                profile_path=profile_a,
                profile_name="a.db",
            )
        )
        self.assertIsNone(self.service.release_reserved_isrc("not-an-isrc", profile_path=profile_a))
        self.assertEqual(
            ApplicationISRCRegistryService._normalize_profile_paths(
                ["", self.root / "missing.db", profile_a, profile_a]
            ),
            [str(profile_a.resolve())],
        )
        self.assertIsNone(ApplicationISRCRegistryService._normalize_existing_or_raw_path(None))
        self.assertIsNone(ApplicationISRCRegistryService._normalize_existing_or_raw_path("   "))

    def test_reserve_activate_and_release_reuse_existing_claims(self):
        profile_a = self._create_profile("a.db", [])
        profile_b = self._create_profile("b.db", [])
        self.service.sync_profiles([profile_a, profile_b])

        self.assertIsNone(
            self.service.reserve_isrc(
                "NL-ABC-26-00077",
                profile_path=profile_a,
                profile_name="a.db",
                track_title="Draft",
            )
        )
        self.assertIsNone(
            self.service.reserve_isrc(
                "NL-ABC-26-00077",
                profile_path=profile_a,
                profile_name="a.db",
                track_title="Retitled Draft",
            )
        )
        same_profile_conflict = self.service.find_conflict(
            "NL-ABC-26-00077",
            profile_path=profile_b,
        )
        self.assertIsNotNone(same_profile_conflict)
        self.assertEqual(same_profile_conflict.track_title, "Retitled Draft")

        self.service.release_reserved_isrc("NL-ABC-26-00077", profile_path=profile_a)
        self.assertIsNone(self.service.find_conflict("NL-ABC-26-00077", profile_path=profile_b))

        self.assertIsNone(
            self.service.activate_isrc(
                "NL-ABC-26-00088",
                profile_path=profile_a,
                profile_name="a.db",
                track_id=88,
                track_title="Activated",
            )
        )
        activation_conflict = self.service.activate_isrc(
            "NL-ABC-26-00088",
            profile_path=profile_b,
            profile_name="b.db",
            track_id=99,
            track_title="Blocked",
        )
        self.assertIsNotNone(activation_conflict)
        self.assertEqual(activation_conflict.profile_name, "a.db")
        self.assertIsNone(
            self.service.find_conflict(
                "NL-ABC-26-00088",
                profile_path=profile_a,
                exclude_track_id=88,
            )
        )

    def test_abandoned_claim_can_be_reserved_by_another_profile(self):
        profile_a = self._create_profile("a.db", [])
        profile_b = self._create_profile("b.db", [])
        self.service.sync_profiles([profile_a, profile_b])
        self.service.reserve_isrc("NL-ABC-26-00099", profile_path=profile_a, profile_name="a.db")
        with sqlite3.connect(self.service.registry_path) as conn:
            conn.execute(
                "UPDATE registry_isrc_claims SET claim_status='abandoned' WHERE isrc_compact=?",
                ("NLABC2600099",),
            )

        conflict = self.service.reserve_isrc(
            "NL-ABC-26-00099",
            profile_path=profile_b,
            profile_name="b.db",
            track_title="Recovered",
        )

        self.assertIsNone(conflict)
        updated = self.service.find_conflict("NL-ABC-26-00099", profile_path=profile_a)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.profile_name, "b.db")
        self.assertEqual(updated.claim_status, "reserved")

    def test_sync_tolerates_unreadable_minimal_and_invalid_track_profiles(self):
        unreadable_profile = self.profile_dir / "not-a-database"
        unreadable_profile.mkdir()
        minimal_profile = self.profile_dir / "minimal.db"
        with sqlite3.connect(minimal_profile) as conn:
            conn.execute("CREATE TABLE Tracks(id INTEGER PRIMARY KEY)")
        invalid_track_profile = self.profile_dir / "invalid_track.db"
        with sqlite3.connect(invalid_track_profile) as conn:
            conn.execute("""
                CREATE TABLE Tracks(
                    id INTEGER PRIMARY KEY,
                    track_title TEXT,
                    isrc TEXT,
                    isrc_compact TEXT
                )
                """)
            conn.execute(
                "INSERT INTO Tracks(id, track_title, isrc, isrc_compact) VALUES(1, 'Bad', 'bad', '')"
            )

        summary = self.service.sync_profiles(
            [unreadable_profile, minimal_profile, invalid_track_profile]
        )

        self.assertEqual(summary.profile_count, 3)
        self.assertEqual(summary.claim_count, 0)
        self.assertEqual(summary.conflict_count, 0)

    def test_app_wide_history_budget_is_persisted_and_clamped(self):
        self.assertEqual(self.service.read_history_storage_budget_mb(2048), 2048)

        saved = self.service.write_history_storage_budget_mb(MAX_HISTORY_STORAGE_BUDGET_MB + 8192)

        self.assertEqual(saved, MAX_HISTORY_STORAGE_BUDGET_MB)
        self.assertEqual(
            self.service.read_history_storage_budget_mb(2048),
            MAX_HISTORY_STORAGE_BUDGET_MB,
        )

    def test_history_budget_invalid_value_and_path_fallbacks(self):
        self.service.ensure_schema()
        with sqlite3.connect(self.service.registry_path) as conn:
            conn.execute(
                "INSERT INTO app_settings(key, value) VALUES('history_storage_budget_mb', 'oops')"
            )

        self.assertEqual(self.service.read_history_storage_budget_mb(512), 512)
        self.assertEqual(
            ApplicationISRCRegistryService._profile_fingerprint(self.root / "missing.db"),
            "",
        )
        with mock.patch(
            "isrc_manager.isrc_registry.Path.resolve",
            side_effect=RuntimeError("path failure"),
        ):
            self.assertEqual(
                ApplicationISRCRegistryService._normalize_existing_or_raw_path("relative.db"),
                "relative.db",
            )


if __name__ == "__main__":
    unittest.main()

import sqlite3
import unittest

from isrc_manager.constants import (
    DEFAULT_AUTO_SNAPSHOT_ENABLED,
    DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES,
    DEFAULT_HISTORY_AUTO_CLEANUP_ENABLED,
    DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
    DEFAULT_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS,
    DEFAULT_HISTORY_RETENTION_MODE,
    DEFAULT_HISTORY_STORAGE_BUDGET_MB,
)
from isrc_manager.services import (
    AutoSnapshotSettings,
    HistoryRetentionSettings,
    OwnerPartySettings,
    RegistrationSettings,
    SettingsReadService,
)


def make_settings_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE ISRC_Prefix (
            id INTEGER PRIMARY KEY,
            prefix TEXT NOT NULL
        );
        CREATE TABLE SENA (
            id INTEGER PRIMARY KEY,
            number TEXT
        );
        CREATE TABLE BTW (
            id INTEGER PRIMARY KEY,
            nr TEXT
        );
        CREATE TABLE BUMA_STEMRA (
            id INTEGER PRIMARY KEY,
            relatie_nummer TEXT,
            ipi TEXT
        );
        CREATE TABLE app_kv (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    return conn


class SettingsReadServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_settings_conn()
        self.service = SettingsReadService(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_load_registration_settings_returns_blank_defaults(self):
        self.assertEqual(self.service.load_registration_settings(), RegistrationSettings())

    def test_load_registration_settings_reads_singleton_values(self):
        with self.conn:
            self.conn.execute("INSERT INTO ISRC_Prefix (id, prefix) VALUES (1, ?)", (" NLABC ",))
            self.conn.execute("INSERT INTO SENA (id, number) VALUES (1, ?)", (" SENA-1 ",))
            self.conn.execute("INSERT INTO BTW (id, nr) VALUES (1, ?)", (" BTW-2 ",))
            self.conn.execute(
                "INSERT INTO BUMA_STEMRA (id, relatie_nummer, ipi) VALUES (1, ?, ?)",
                (" REL-3 ", " IPI-4 "),
            )

        self.assertEqual(
            self.service.load_registration_settings(),
            RegistrationSettings(
                isrc_prefix="NLABC",
                sena_number="SENA-1",
                btw_number="BTW-2",
                buma_relatie_nummer="REL-3",
                buma_ipi="IPI-4",
            ),
        )

    def test_load_auto_snapshot_settings_returns_defaults(self):
        self.assertEqual(
            self.service.load_auto_snapshot_settings(),
            AutoSnapshotSettings(
                enabled=DEFAULT_AUTO_SNAPSHOT_ENABLED,
                interval_minutes=DEFAULT_AUTO_SNAPSHOT_INTERVAL_MINUTES,
            ),
        )

    def test_load_auto_snapshot_settings_reads_profile_values(self):
        with self.conn:
            self.conn.execute(
                "INSERT INTO app_kv(key, value) VALUES(?, ?)",
                ("auto_snapshot_enabled", "0"),
            )
            self.conn.execute(
                "INSERT INTO app_kv(key, value) VALUES(?, ?)",
                ("auto_snapshot_interval_minutes", "45"),
            )

        self.assertEqual(
            self.service.load_auto_snapshot_settings(),
            AutoSnapshotSettings(enabled=False, interval_minutes=45),
        )

    def test_load_owner_party_settings_merges_profile_fields_with_registration_values(self):
        with self.conn:
            self.conn.execute("INSERT INTO BTW (id, nr) VALUES (1, ?)", (" BTW-2 ",))
            self.conn.execute(
                "INSERT INTO BUMA_STEMRA (id, relatie_nummer, ipi) VALUES (1, ?, ?)",
                (" REL-3 ", " IPI-4 "),
            )
            self.conn.executemany(
                "INSERT INTO app_kv(key, value) VALUES(?, ?)",
                [
                    ("owner_display_name", " Moonwake Records "),
                    ("owner_legal_name", " Moonwake Records B.V. "),
                    ("owner_artist_name", " Lyra Moonwake "),
                    ("owner_company_name", " Moonwake Records "),
                    ("owner_first_name", " Lyra "),
                    ("owner_last_name", " Moonwake "),
                    ("owner_email", " hello@moonwake.test "),
                    ("owner_alternative_email", " legal@moonwake.test "),
                    ("owner_street_name", " Forest Lane "),
                    ("owner_street_number", " 42A "),
                    ("owner_city", " Amsterdam "),
                    ("owner_postal_code", " 1234AB "),
                    ("owner_country", " Netherlands "),
                    ("owner_bank_account_number", " NL91TEST0123456789 "),
                    ("owner_chamber_of_commerce_number", " CoC-556677 "),
                    ("owner_pro_affiliation", " BUMA/STEMRA "),
                ],
            )

        self.assertEqual(
            self.service.load_owner_party_settings(),
            OwnerPartySettings(
                legal_name="Moonwake Records B.V.",
                display_name="Moonwake Records",
                artist_name="Lyra Moonwake",
                company_name="Moonwake Records",
                first_name="Lyra",
                middle_name="",
                last_name="Moonwake",
                contact_person="",
                email="hello@moonwake.test",
                alternative_email="legal@moonwake.test",
                phone="",
                website="",
                street_name="Forest Lane",
                street_number="42A",
                address_line1="",
                address_line2="",
                city="Amsterdam",
                region="",
                postal_code="1234AB",
                country="Netherlands",
                bank_account_number="NL91TEST0123456789",
                chamber_of_commerce_number="CoC-556677",
                tax_id="",
                vat_number="BTW-2",
                pro_affiliation="BUMA/STEMRA",
                pro_number="REL-3",
                ipi_cae="IPI-4",
                notes="",
            ),
        )

    def test_load_history_retention_settings_returns_defaults(self):
        self.assertEqual(
            self.service.load_history_retention_settings(),
            HistoryRetentionSettings(
                retention_mode=DEFAULT_HISTORY_RETENTION_MODE,
                auto_cleanup_enabled=DEFAULT_HISTORY_AUTO_CLEANUP_ENABLED,
                storage_budget_mb=DEFAULT_HISTORY_STORAGE_BUDGET_MB,
                auto_snapshot_keep_latest=DEFAULT_HISTORY_AUTO_SNAPSHOT_KEEP_LATEST,
                prune_pre_restore_copies_after_days=(
                    DEFAULT_HISTORY_PRUNE_PRE_RESTORE_COPIES_AFTER_DAYS
                ),
            ),
        )

    def test_load_history_retention_settings_reads_profile_values(self):
        with self.conn:
            self.conn.executemany(
                "INSERT INTO app_kv(key, value) VALUES(?, ?)",
                [
                    ("history_retention_mode", "lean"),
                    ("history_auto_cleanup_enabled", "0"),
                    ("history_storage_budget_mb", "4096"),
                    ("history_auto_snapshot_keep_latest", "12"),
                    ("history_prune_pre_restore_copies_after_days", "21"),
                ],
            )

        self.assertEqual(
            self.service.load_history_retention_settings(),
            HistoryRetentionSettings(
                retention_mode="lean",
                auto_cleanup_enabled=False,
                storage_budget_mb=4096,
                auto_snapshot_keep_latest=12,
                prune_pre_restore_copies_after_days=21,
            ),
        )


if __name__ == "__main__":
    unittest.main()

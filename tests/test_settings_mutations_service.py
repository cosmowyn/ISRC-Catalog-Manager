import sqlite3
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings

from isrc_manager.services import OwnerPartySettings, SettingsMutationService


def make_settings_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE app_kv (
            key TEXT PRIMARY KEY,
            value TEXT
        );
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
        """
    )
    return conn


class SettingsMutationServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_settings_conn()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmpdir.name) / "settings.ini"
        self.settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)
        self.service = SettingsMutationService(self.conn, self.settings)

    def tearDown(self):
        self.settings.clear()
        self.conn.close()
        self.tmpdir.cleanup()

    def test_set_identity_updates_qsettings(self):
        identity = self.service.set_identity(window_title="Catalog Pro", icon_path="/tmp/icon.ico")

        self.assertEqual(identity, {"window_title": "Catalog Pro", "icon_path": "/tmp/icon.ico"})
        self.assertEqual(self.settings.value("identity/window_title", "", str), "Catalog Pro")
        self.assertEqual(self.settings.value("identity/icon_path", "", str), "/tmp/icon.ico")

    def test_singleton_tables_and_profile_values_are_written(self):
        self.service.set_artist_code("42")
        self.service.set_auto_snapshot_enabled(False)
        self.service.set_auto_snapshot_interval_minutes(45)
        self.service.set_history_retention_mode("lean")
        self.service.set_history_auto_cleanup_enabled(False)
        self.service.set_history_storage_budget_mb(4096)
        self.service.set_history_auto_snapshot_keep_latest(12)
        self.service.set_history_prune_pre_restore_copies_after_days(21)
        self.service.set_isrc_prefix("NLABC")
        self.service.set_sena_number("SENA-1")
        self.service.set_btw_number("BTW-2")
        self.service.set_buma_relatie_nummer("REL-3")
        self.service.set_buma_ipi("IPI-4")

        self.assertEqual(
            self.conn.execute("SELECT value FROM app_kv WHERE key='isrc_artist_code'").fetchone(),
            ("42",),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT value FROM app_kv WHERE key='auto_snapshot_enabled'"
            ).fetchone(),
            ("0",),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT value FROM app_kv WHERE key='auto_snapshot_interval_minutes'"
            ).fetchone(),
            ("45",),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT value FROM app_kv WHERE key='history_retention_mode'"
            ).fetchone(),
            ("lean",),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT value FROM app_kv WHERE key='history_auto_cleanup_enabled'"
            ).fetchone(),
            ("0",),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT value FROM app_kv WHERE key='history_storage_budget_mb'"
            ).fetchone(),
            ("4096",),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT value FROM app_kv WHERE key='history_auto_snapshot_keep_latest'"
            ).fetchone(),
            ("12",),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT value FROM app_kv WHERE key='history_prune_pre_restore_copies_after_days'"
            ).fetchone(),
            ("21",),
        )
        self.assertEqual(
            self.conn.execute("SELECT prefix FROM ISRC_Prefix WHERE id=1").fetchone(), ("NLABC",)
        )
        self.assertEqual(
            self.conn.execute("SELECT number FROM SENA WHERE id=1").fetchone(), ("SENA-1",)
        )
        self.assertEqual(self.conn.execute("SELECT nr FROM BTW WHERE id=1").fetchone(), ("BTW-2",))
        self.assertEqual(
            self.conn.execute("SELECT relatie_nummer, ipi FROM BUMA_STEMRA WHERE id=1").fetchone(),
            ("REL-3", "IPI-4"),
        )

    def test_set_owner_party_settings_persists_profile_fields_without_touching_registration(self):
        saved = self.service.set_owner_party_settings(
            OwnerPartySettings(
                legal_name="Moonwake Records B.V.",
                display_name="Moonwake Records",
                artist_name="Lyra Moonwake",
                company_name="Moonwake Records",
                first_name="Lyra",
                last_name="Moonwake",
                email="hello@moonwake.test",
                alternative_email="legal@moonwake.test",
                street_name="Forest Lane",
                street_number="42A",
                city="Amsterdam",
                postal_code="1234AB",
                country="Netherlands",
                bank_account_number="NL91TEST0123456789",
                chamber_of_commerce_number="CoC-556677",
                tax_id="TAX-778899",
                vat_number="BTW-2",
                pro_affiliation="BUMA/STEMRA",
                pro_number="REL-3",
                ipi_cae="IPI-4",
                notes="Primary owner identity",
            )
        )

        self.assertEqual(saved.display_name, "Moonwake Records")
        self.assertEqual(
            self.conn.execute("SELECT value FROM app_kv WHERE key='owner_display_name'").fetchone(),
            ("Moonwake Records",),
        )
        self.assertEqual(
            self.conn.execute("SELECT value FROM app_kv WHERE key='owner_tax_id'").fetchone(),
            ("TAX-778899",),
        )
        self.assertIsNone(self.conn.execute("SELECT nr FROM BTW WHERE id=1").fetchone())
        self.assertIsNone(
            self.conn.execute("SELECT relatie_nummer, ipi FROM BUMA_STEMRA WHERE id=1").fetchone()
        )


if __name__ == "__main__":
    unittest.main()

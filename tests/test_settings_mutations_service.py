import sqlite3
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings

from isrc_manager.services import OwnerPartySettings, SettingsMutationService


def make_settings_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
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
        CREATE TABLE Parties (
            id INTEGER PRIMARY KEY,
            legal_name TEXT NOT NULL,
            display_name TEXT,
            artist_name TEXT,
            company_name TEXT,
            first_name TEXT,
            middle_name TEXT,
            last_name TEXT,
            party_type TEXT,
            contact_person TEXT,
            email TEXT,
            alternative_email TEXT,
            phone TEXT,
            website TEXT,
            street_name TEXT,
            street_number TEXT,
            address_line1 TEXT,
            address_line2 TEXT,
            city TEXT,
            region TEXT,
            postal_code TEXT,
            country TEXT,
            bank_account_number TEXT,
            chamber_of_commerce_number TEXT,
            tax_id TEXT,
            vat_number TEXT,
            pro_affiliation TEXT,
            pro_number TEXT,
            ipi_cae TEXT,
            notes TEXT,
            profile_name TEXT,
            created_at TEXT,
            updated_at TEXT
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
        identity = self.service.set_identity(
            window_title_override="Catalog Pro",
            icon_path="/tmp/icon.ico",
        )

        self.assertEqual(
            identity,
            {
                "window_title_override": "Catalog Pro",
                "icon_path": "/tmp/icon.ico",
            },
        )
        self.assertEqual(self.settings.value("identity/window_title", "", str), "Catalog Pro")
        self.assertEqual(
            self.settings.value("identity/window_title_override", "", str),
            "Catalog Pro",
        )
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

    def test_set_owner_party_settings_only_persists_owner_binding(self):
        with self.conn:
            self.conn.execute(
                "INSERT INTO Parties(id, legal_name, display_name) VALUES (?, ?, ?)",
                (12, "Canonical Owner B.V.", "Canonical Owner"),
            )
            self.conn.executemany(
                "INSERT INTO app_kv(key, value) VALUES(?, ?)",
                [
                    ("owner_display_name", "Legacy Owner"),
                    ("owner_legal_name", "Legacy Owner B.V."),
                    ("owner_email", "legacy@owner.test"),
                ],
            )

        saved = self.service.set_owner_party_settings(
            OwnerPartySettings(
                party_id=12,
                legal_name="Canonical Owner B.V.",
                display_name="Canonical Owner",
            )
        )

        self.assertEqual(saved, OwnerPartySettings(party_id=12))
        self.assertEqual(
            self.conn.execute("SELECT party_id FROM ApplicationOwnerBinding WHERE id=1").fetchone(),
            (12,),
        )
        self.assertIsNone(
            self.conn.execute("SELECT value FROM app_kv WHERE key='owner_display_name'").fetchone()
        )
        self.assertIsNone(
            self.conn.execute("SELECT value FROM app_kv WHERE key='owner_email'").fetchone()
        )

    def test_set_owner_party_settings_clears_binding_when_party_is_removed(self):
        with self.conn:
            self.conn.execute(
                "INSERT INTO Parties(id, legal_name, display_name) VALUES (?, ?, ?)",
                (12, "Canonical Owner B.V.", "Canonical Owner"),
            )
        self.service.set_owner_party_settings(
            OwnerPartySettings(party_id=12, legal_name="Canonical Owner B.V.")
        )

        cleared = self.service.set_owner_party_settings(
            OwnerPartySettings(
                party_id=None,
            )
        )

        self.assertEqual(cleared, OwnerPartySettings())
        self.assertIsNone(
            self.conn.execute("SELECT party_id FROM ApplicationOwnerBinding WHERE id=1").fetchone()
        )

    def test_registration_writes_update_owner_party_when_bound(self):
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO Parties(id, legal_name, vat_number, pro_number, ipi_cae)
                VALUES (?, ?, ?, ?, ?)
                """,
                (7, "Moonwake Records B.V.", "", "", ""),
            )
            self.conn.execute("INSERT INTO BTW (id, nr) VALUES (1, ?)", ("LEGACY-BTW",))
            self.conn.execute(
                "INSERT INTO BUMA_STEMRA (id, relatie_nummer, ipi) VALUES (1, ?, ?)",
                ("LEGACY-PRO", "LEGACY-IPI"),
            )
        self.service.set_owner_party_id(7)

        self.service.set_btw_number("BTW-2")
        self.service.set_buma_relatie_nummer("REL-3")
        self.service.set_buma_ipi("IPI-4")

        self.assertEqual(
            self.conn.execute(
                "SELECT vat_number, pro_number, ipi_cae FROM Parties WHERE id=7"
            ).fetchone(),
            ("BTW-2", "REL-3", "IPI-4"),
        )
        self.assertIsNone(self.conn.execute("SELECT nr FROM BTW WHERE id=1").fetchone())
        self.assertIsNone(
            self.conn.execute("SELECT relatie_nummer, ipi FROM BUMA_STEMRA WHERE id=1").fetchone()
        )


if __name__ == "__main__":
    unittest.main()

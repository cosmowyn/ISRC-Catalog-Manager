import sqlite3
import unittest

from isrc_manager.services import RegistrationSettings, SettingsReadService


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


if __name__ == "__main__":
    unittest.main()

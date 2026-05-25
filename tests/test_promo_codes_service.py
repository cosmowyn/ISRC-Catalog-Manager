import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isrc_manager.promo_codes.service import (
    PromoCodeService,
    _clean_multiline_text,
    _clean_text,
    _is_probable_code,
    _metadata_key,
    _parse_int,
)


class PromoCodeServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.service = PromoCodeService(self.conn)

    def tearDown(self):
        self.conn.close()

    def _write_csv(self, text: str) -> str:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".csv", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(text)
            return handle.name

    def test_cleaning_helpers_cover_edge_cases(self):
        self.assertEqual(_clean_text("  spaced text  "), "spaced text")
        self.assertIsNone(_clean_text("   "))
        self.assertIsNone(_clean_multiline_text(None))
        self.assertEqual(_clean_multiline_text(" line1\nline2  "), "line1\nline2")
        self.assertEqual(_parse_int(" 12abc34 "), 1234)
        self.assertIsNone(_parse_int("abc"))
        self.assertEqual(_metadata_key("Name of code set!"), "name_of_code_set")
        self.assertFalse(_is_probable_code(" code"))
        self.assertFalse(_is_probable_code("https://example.com"))
        self.assertTrue(_is_probable_code("ABC-123"))

    def test_parse_bandcamp_csv_extracts_metadata_and_unique_codes(self):
        source = self._write_csv(
            "Name of code set:,Bundle Promo\n"
            "Album:,Bundle Album\n"
            "Quantity created:, 10\n"
            "Date created:,2026-01-01\n"
            "Send your fans here:https://bandcamp.com/redeem\n"
            "code,used\n"
            "ABC-111,Yes\n"
            "ABC-111,No\n"
            "https://bad.example.com\n"
            "XYZ-777,Other\n"
            "\n"
            "\n"
        )
        parsed = self.service.parse_bandcamp_csv(source)

        self.assertEqual(parsed.code_set_name, "Bundle Promo")
        self.assertEqual(parsed.album, "Bundle Album")
        self.assertEqual(parsed.quantity_created, 10)
        self.assertEqual(parsed.quantity_redeemed_to_date, None)
        self.assertEqual(parsed.redeem_url, "https://bandcamp.com/redeem")
        self.assertEqual(parsed.codes, ("ABC-111", "XYZ-777"))

    def test_parse_bandcamp_csv_empty_codes_raise_on_import(self):
        source = self._write_csv(
            "Name of code set:,No Codes\n"
            "Album:,No Codes\n"
            "code,\n"
            "https://example.com/ignore\n"
        )
        with self.assertRaisesRegex(ValueError, "No promo codes were found"):
            self.service.import_bandcamp_csv(source)

    def test_matching_sheet_id_raises_on_ambiguous_matches(self):
        self.service.ensure_schema()
        self.conn.execute(
            """
            INSERT INTO PromoCodeSheets (
                code_set_name,
                album,
                source_sha256,
                code_sequence_sha256
            ) VALUES (?, ?, ?, ?)
            """,
            ("Bundle", "Album", "sha-a", "seq-a"),
        )
        self.conn.execute(
            """
            INSERT INTO PromoCodeSheets (
                code_set_name,
                album,
                source_sha256,
                code_sequence_sha256
            ) VALUES (?, ?, ?, ?)
            """,
            ("Bundle", "Album", "sha-b", "seq-b"),
        )
        self.conn.commit()

        source = self._write_csv("Name of code set:,Bundle\n" "Album:,Album\n" "code\n" "ONE-1\n")
        parsed = self.service.parse_bandcamp_csv(source)

        with self.assertRaisesRegex(
            ValueError,
            "Multiple existing promo-code sheets match this Bandcamp sheet metadata",
        ):
            self.service._matching_sheet_id(parsed)

    def test_import_bandcamp_csv_updates_existing_sheet_lifecycle(self):
        source = self._write_csv(
            "Name of code set:,Summer\n" "Album:,Promo\n" "code\n" "CODE-A\n" "CODE-B\n"
        )
        first = self.service.import_bandcamp_csv(source)
        self.assertFalse(first.updated_existing_sheet)

        progress: list[tuple[int, int, str]] = []
        second = self.service.import_bandcamp_csv(
            source,
            progress_callback=lambda value, _max, message: progress.append((value, _max, message)),
        )

        self.assertTrue(second.updated_existing_sheet)
        self.assertEqual(second.sheet_id, first.sheet_id)
        self.assertEqual(second.inserted_codes, 0)
        self.assertEqual(progress[0][0], 0)

    def test_update_existing_sheet_from_active_codes_reconcilers_new_and_redeemed_codes(self):
        source = self._write_csv(
            "Name of code set:,Summer\n" "Album:,Promo\n" "code\n" "CODE-A\n" "CODE-B\n" "CODE-C\n"
        )
        imported = self.service.import_bandcamp_csv(source)

        self.conn.execute(
            "UPDATE PromoCodes SET redeemed = CASE code WHEN 'CODE-A' THEN 1 WHEN 'CODE-B' THEN 0 ELSE redeemed END "
            "WHERE sheet_id = ?",
            (imported.sheet_id,),
        )
        self.conn.commit()

        new_source = self._write_csv(
            "Name of code set:,Summer\n" "Album:,Promo\n" "code\n" "CODE-A\n" "CODE-D\n"
        )
        parsed = self.service.parse_bandcamp_csv(new_source)

        progress: list[tuple[int, int, str]] = []
        inserted, marked, reactivated = self.service._update_existing_sheet_from_active_codes(
            imported.sheet_id,
            parsed,
            progress_callback=lambda value, _max, message: progress.append((value, _max, message)),
        )

        self.assertEqual(inserted, 1)
        self.assertEqual(marked, 2)
        self.assertEqual(reactivated, 1)
        self.assertEqual(len(progress), 0)

        rows = self.conn.execute(
            "SELECT code, redeemed FROM PromoCodes WHERE sheet_id = ? ORDER BY sort_order",
            (imported.sheet_id,),
        ).fetchall()
        flags = {str(code): int(redeemed) for code, redeemed in rows}
        self.assertEqual(flags["CODE-A"], 0)
        self.assertEqual(flags["CODE-B"], 1)
        self.assertEqual(flags["CODE-C"], 1)
        self.assertEqual(flags["CODE-D"], 0)

    def test_matching_sheet_id_respects_profile_filter_and_date_ambiguity(self):
        source = self._write_csv(
            "Name of code set:,Bundle\n"
            "Album:,Album\n"
            "Date created:,2026-01-01\n"
            "code\n"
            "CODE-1\n"
        )
        parsed = self.service.parse_bandcamp_csv(source)
        self.service.ensure_schema()
        self.conn.execute(
            """
            INSERT INTO PromoCodeSheets (
                code_set_name,
                album,
                bandcamp_date_created,
                code_sequence_sha256,
                source_sha256,
                profile_name
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                parsed.code_set_name,
                parsed.album,
                parsed.bandcamp_date_created,
                parsed.code_sequence_sha256,
                parsed.source_sha256,
                "alpha",
            ),
        )
        self.conn.execute(
            """
            INSERT INTO PromoCodeSheets (
                code_set_name,
                album,
                bandcamp_date_created,
                code_sequence_sha256,
                source_sha256,
                profile_name
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                parsed.code_set_name,
                parsed.album,
                parsed.bandcamp_date_created,
                parsed.code_sequence_sha256,
                parsed.source_sha256,
                "beta",
            ),
        )
        self.conn.commit()

        # Without profile filter, row is selected by source hash.
        self.assertEqual(self.service._matching_sheet_id(parsed), 1)

        # Profile filters should route to exact profile matches.
        self.assertEqual(self.service._matching_sheet_id(parsed, profile_name="beta"), 2)
        self.assertEqual(self.service._matching_sheet_id(parsed, profile_name="alpha"), 1)

    def test_matching_sheet_id_date_ambiguity_raises_when_no_profile(self):
        self.service.ensure_schema()
        self.conn.execute(
            """
            INSERT INTO PromoCodeSheets (
                code_set_name,
                album,
                code_sequence_sha256,
                bandcamp_date_created
            ) VALUES (?, ?, ?, ?)
            """,
            ("Bundle", "Album", "seq-a", "2026-01-01"),
        )
        self.conn.execute(
            """
            INSERT INTO PromoCodeSheets (
                code_set_name,
                album,
                code_sequence_sha256,
                bandcamp_date_created
            ) VALUES (?, ?, ?, ?)
            """,
            ("Bundle", "Album", "seq-b", "2026-01-01"),
        )
        self.conn.commit()

        source = self._write_csv(
            "Name of code set:,Bundle\n"
            "Album:,Album\n"
            "Date created:,2026-01-01\n"
            "code\n"
            "CODE-1\n"
        )
        parsed = self.service.parse_bandcamp_csv(source)

        with self.assertRaisesRegex(ValueError, "Multiple existing promo-code sheets"):
            self.service._matching_sheet_id(parsed)

    def test_sheet_and_code_row_helpers_normalize_payload_rows(self):
        self.service.ensure_schema()
        sheet = self.service.import_bandcamp_csv(
            self._write_csv("Name of code set:,Gamma\n" "Album:,Album Gamma\n" "code\n" "GAM-1\n")
        )
        fetched = self.conn.execute(
            """
            SELECT id, code_set_name, album, bandcamp_date_created, bandcamp_date_exported,
                   quantity_created, quantity_redeemed_to_date, redeem_url, source_filename,
                   source_path, source_sha256, code_sequence_sha256, profile_name,
                   imported_at, updated_at,
                   (SELECT COUNT(*) FROM PromoCodes WHERE sheet_id = PromoCodeSheets.id),
                   (SELECT COALESCE(SUM(CASE WHEN redeemed THEN 1 ELSE 0 END), 0)
                    FROM PromoCodes WHERE sheet_id = PromoCodeSheets.id)
            FROM PromoCodeSheets WHERE id=?
            """,
            (sheet.sheet_id,),
        ).fetchone()

        sheet_record = self.service._sheet_from_row(fetched)
        self.assertEqual(sheet_record.id, sheet.sheet_id)
        self.assertEqual(sheet_record.code_set_name, "Gamma")
        self.assertEqual(sheet_record.available_codes, 1)

        code_row = self.conn.execute(
            "SELECT * FROM PromoCodes WHERE sheet_id=? ORDER BY id LIMIT 1",
            (sheet.sheet_id,),
        ).fetchone()
        code_record = self.service._code_from_row(code_row)
        self.assertEqual(code_record.code, "GAM-1")
        self.assertEqual(code_record.sheet_id, sheet.sheet_id)

    def test_update_code_ledger_records_timestamps_with_and_without_recipient(self):
        source = self._write_csv("Name of code set:,Delta\n" "Album:,Album\n" "code\n" "DELTA-1\n")
        imported = self.service.import_bandcamp_csv(source)
        code = self.conn.execute(
            "SELECT id FROM PromoCodes WHERE sheet_id=? ORDER BY id LIMIT 1",
            (imported.sheet_id,),
        ).fetchone()
        assert code is not None
        code_id = int(code[0])

        redeemed = self.service.update_code_ledger(
            code_id,
            redeemed=True,
            recipient_name="Alex",
            recipient_email="alex@example.com",
            ledger_notes="Delivered",
        )
        self.assertTrue(redeemed.redeemed)
        self.assertEqual(redeemed.recipient_name, "Alex")
        self.assertIsNotNone(redeemed.provided_at)
        self.assertIsNotNone(redeemed.redeemed_at)

        unchanged = self.service.update_code_ledger(
            code_id,
            redeemed=False,
            recipient_name=None,
            recipient_email=None,
            ledger_notes=None,
        )
        self.assertFalse(unchanged.redeemed)
        self.assertIsNone(unchanged.provided_at)
        self.assertIsNone(unchanged.redeemed_at)

    def test_update_code_ledger_invalid_code_raises(self):
        with self.assertRaisesRegex(ValueError, "Promo code not found"):
            self.service.update_code_ledger(9999, redeemed=True)

    @mock.patch("isrc_manager.promo_codes.service._metadata_key")
    def test_parse_metadata_key_uses_replace_cleanup(self, metadata_key):
        metadata_key.return_value = "album_title"
        source_path = self._write_csv(
            "Code,foo\n" "Name of code set:,Album Set\n" "Album:,Album Name\n" "code\n" "ALB-1\n"
        )
        parsed = self.service.parse_bandcamp_csv(source_path)

        self.assertEqual(metadata_key.call_count, 10)
        self.assertEqual(parsed.code_set_name, Path(source_path).stem)


if __name__ == "__main__":
    unittest.main()

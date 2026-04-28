"""Service layer for importing and managing Bandcamp promo-code sheets."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import sqlite3
from pathlib import Path
from typing import Callable

from .models import (
    ParsedBandcampPromoCsv,
    PromoCodeImportResult,
    PromoCodeRecord,
    PromoCodeSheetRecord,
)

ProgressCallback = Callable[[int | None, int | None, str | None], None]

_URL_PREFIXES = ("http://", "https://")
_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{2,}$")


def _clean_text(value: object | None) -> str | None:
    text = " ".join(str(value or "").split()).strip()
    return text or None


def _clean_multiline_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_int(value: object | None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _metadata_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _is_probable_code(value: str) -> bool:
    clean = str(value or "").strip()
    if not clean or clean.casefold() == "code":
        return False
    if clean.startswith(_URL_PREFIXES):
        return False
    return bool(_CODE_PATTERN.match(clean))


class PromoCodeService:
    """Imports Bandcamp promo-code CSV files and maintains redemption ledger rows."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def ensure_schema(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS PromoCodeSheets (
                id INTEGER PRIMARY KEY,
                code_set_name TEXT NOT NULL,
                album TEXT,
                bandcamp_date_created TEXT,
                bandcamp_date_exported TEXT,
                quantity_created INTEGER,
                quantity_redeemed_to_date INTEGER,
                redeem_url TEXT,
                source_path TEXT,
                source_filename TEXT,
                source_sha256 TEXT,
                code_sequence_sha256 TEXT NOT NULL,
                profile_name TEXT,
                imported_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                notes TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS PromoCodes (
                id INTEGER PRIMARY KEY,
                sheet_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                redeemed INTEGER NOT NULL DEFAULT 0,
                recipient_name TEXT,
                recipient_email TEXT,
                ledger_notes TEXT,
                provided_at TEXT,
                redeemed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (sheet_id) REFERENCES PromoCodeSheets(id) ON DELETE CASCADE,
                UNIQUE(sheet_id, code)
            )
            """
        )
        self._ensure_column("PromoCodeSheets", "source_sha256", "TEXT")
        self._ensure_column("PromoCodeSheets", "code_sequence_sha256", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("PromoCodeSheets", "profile_name", "TEXT")
        self._ensure_column("PromoCodeSheets", "updated_at", "TEXT")
        self._ensure_column("PromoCodeSheets", "notes", "TEXT")
        self._ensure_column("PromoCodes", "provided_at", "TEXT")
        self._ensure_column("PromoCodes", "updated_at", "TEXT")
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_promo_code_sheets_source_sha256
            ON PromoCodeSheets(source_sha256)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_promo_code_sheets_sequence
            ON PromoCodeSheets(code_sequence_sha256)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_promo_codes_sheet_status
            ON PromoCodes(sheet_id, redeemed, sort_order)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_promo_codes_code
            ON PromoCodes(code)
            """
        )
        self.conn.commit()

    def _ensure_column(self, table_name: str, column_name: str, column_sql: str) -> None:
        columns = {
            str(row[1] or "")
            for row in self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            if row and row[1]
        }
        if column_name not in columns:
            self.conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")

    @staticmethod
    def parse_bandcamp_csv(path: str | Path) -> ParsedBandcampPromoCsv:
        source_path = Path(path)
        data = source_path.read_bytes()
        source_sha256 = hashlib.sha256(data).hexdigest()
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = data.decode("utf-8", errors="replace")

        metadata: dict[str, str] = {}
        codes: list[str] = []
        seen_codes: set[str] = set()
        code_column_index: int | None = None
        pending_redeem_url = False

        reader = csv.reader(io.StringIO(text))
        for row in reader:
            raw_cells = [str(cell or "").strip() for cell in row]
            cells = [cell for cell in raw_cells if cell]
            if not cells:
                continue

            first = cells[0]
            first_key = first.casefold()
            if pending_redeem_url and first.startswith(_URL_PREFIXES):
                metadata["redeem_url"] = first
                pending_redeem_url = False
                continue

            if code_column_index is None:
                header_index = next(
                    (
                        index
                        for index, cell in enumerate(raw_cells)
                        if _metadata_key(cell) == "code"
                    ),
                    None,
                )
                if header_index is not None:
                    code_column_index = int(header_index)
                    continue

                if first_key.startswith("send your fans here"):
                    pending_redeem_url = True
                    _, separator, remainder = first.partition(":")
                    if separator and remainder.strip().startswith(_URL_PREFIXES):
                        metadata["redeem_url"] = remainder.strip()
                        pending_redeem_url = False
                    continue

                if ":" in first:
                    key, value = first.split(":", 1)
                    clean_key = _metadata_key(key)
                    clean_value = value.strip()
                    if not clean_value and len(cells) > 1:
                        clean_value = cells[1]
                    if clean_key:
                        metadata[clean_key] = clean_value
                    continue

                continue

            candidate = ""
            if code_column_index < len(raw_cells):
                candidate = raw_cells[code_column_index].strip()
            if not candidate and cells:
                candidate = cells[0]
            if not _is_probable_code(candidate):
                continue
            normalized_code = candidate.strip()
            code_key = normalized_code.casefold()
            if code_key in seen_codes:
                continue
            seen_codes.add(code_key)
            codes.append(normalized_code)

        code_set_name = (
            _clean_text(metadata.get("name_of_code_set"))
            or _clean_text(metadata.get("code_set"))
            or source_path.stem
        )
        code_sequence_sha256 = hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest()
        return ParsedBandcampPromoCsv(
            code_set_name=code_set_name,
            album=_clean_text(metadata.get("album")),
            bandcamp_date_created=_clean_text(metadata.get("date_created")),
            bandcamp_date_exported=_clean_text(metadata.get("date_exported")),
            quantity_created=_parse_int(metadata.get("quantity_created")),
            quantity_redeemed_to_date=_parse_int(metadata.get("quantity_redeemed_to_date")),
            redeem_url=_clean_text(metadata.get("redeem_url")),
            codes=tuple(codes),
            source_path=str(source_path),
            source_filename=source_path.name,
            source_sha256=source_sha256,
            code_sequence_sha256=code_sequence_sha256,
        )

    def import_bandcamp_csv(
        self,
        path: str | Path,
        *,
        profile_name: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> PromoCodeImportResult:
        def report(value: int, message: str) -> None:
            if progress_callback is not None:
                progress_callback(int(value), 100, message)

        report(0, "Reading Bandcamp promo-code CSV...")
        parsed = self.parse_bandcamp_csv(path)
        if not parsed.codes:
            raise ValueError(
                "No promo codes were found in the selected Bandcamp CSV.\n\n"
                "Choose a Bandcamp promo-code export with code-set metadata and a 'code' "
                "column. Bandcamp digital catalog/product exports cannot update the promo "
                "code ledger."
            )

        report(10, f"Parsed {len(parsed.codes)} promo code(s).")
        self.ensure_schema()
        report(14, "Checking whether this promo-code sheet already exists...")

        existing_sheet_id = self._matching_sheet_id(parsed, profile_name=profile_name)
        if existing_sheet_id is not None:
            inserted_codes, marked_redeemed_codes, reactivated_codes = (
                self._update_existing_sheet_from_active_codes(
                    int(existing_sheet_id),
                    parsed,
                    profile_name=profile_name,
                    progress_callback=progress_callback,
                )
            )
            total_codes = self._count_codes_for_sheet(int(existing_sheet_id))
            report(100, "Existing promo-code sheet updated from active codes.")
            return PromoCodeImportResult(
                sheet_id=int(existing_sheet_id),
                sheet_name=parsed.code_set_name,
                album=parsed.album,
                total_codes=total_codes,
                inserted_codes=inserted_codes,
                updated_existing_sheet=True,
                source_path=parsed.source_path,
                active_codes=len(parsed.codes),
                marked_redeemed_codes=marked_redeemed_codes,
                reactivated_codes=reactivated_codes,
            )

        inserted_codes = 0
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO PromoCodeSheets (
                    code_set_name,
                    album,
                    bandcamp_date_created,
                    bandcamp_date_exported,
                    quantity_created,
                    quantity_redeemed_to_date,
                    redeem_url,
                    source_path,
                    source_filename,
                    source_sha256,
                    code_sequence_sha256,
                    profile_name,
                    imported_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    parsed.code_set_name,
                    parsed.album,
                    parsed.bandcamp_date_created,
                    parsed.bandcamp_date_exported,
                    parsed.quantity_created,
                    parsed.quantity_redeemed_to_date,
                    parsed.redeem_url,
                    parsed.source_path,
                    parsed.source_filename,
                    parsed.source_sha256,
                    parsed.code_sequence_sha256,
                    _clean_text(profile_name),
                ),
            )
            sheet_id = int(cursor.lastrowid)
            total_codes = len(parsed.codes)
            for index, code in enumerate(parsed.codes, start=1):
                result = self.conn.execute(
                    """
                    INSERT OR IGNORE INTO PromoCodes (
                        sheet_id,
                        code,
                        sort_order,
                        redeemed,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, 0, datetime('now'), datetime('now'))
                    """,
                    (sheet_id, code, index),
                )
                inserted_codes += max(0, int(result.rowcount or 0))
                if index == total_codes or index % 10 == 0:
                    progress = 15 + int((index / max(1, total_codes)) * 80)
                    report(progress, f"Stored {index} of {total_codes} promo code(s)...")

        report(100, "Promo-code sheet import complete.")
        return PromoCodeImportResult(
            sheet_id=sheet_id,
            sheet_name=parsed.code_set_name,
            album=parsed.album,
            total_codes=len(parsed.codes),
            inserted_codes=inserted_codes,
            updated_existing_sheet=False,
            source_path=parsed.source_path,
            active_codes=len(parsed.codes),
        )

    def _matching_sheet_id(
        self,
        parsed: ParsedBandcampPromoCsv,
        *,
        profile_name: str | None = None,
    ) -> int | None:
        clean_profile = _clean_text(profile_name)
        profile_filter = ""
        profile_args: tuple[str, ...] = ()
        if clean_profile:
            profile_filter = " AND COALESCE(profile_name, '') = ?"
            profile_args = (clean_profile,)

        source_row = self.conn.execute(
            f"""
            SELECT id
            FROM PromoCodeSheets
            WHERE source_sha256 = ?
              {profile_filter}
            ORDER BY id
            LIMIT 1
            """,
            (parsed.source_sha256, *profile_args),
        ).fetchone()
        if source_row is not None:
            return int(source_row[0])

        album_key = str(parsed.album or "").casefold()
        sequence_row = self.conn.execute(
            f"""
            SELECT id
            FROM PromoCodeSheets
            WHERE lower(code_set_name) = lower(?)
              AND lower(COALESCE(album, '')) = ?
              AND code_sequence_sha256 = ?
              {profile_filter}
            ORDER BY id
            LIMIT 1
            """,
            (parsed.code_set_name, album_key, parsed.code_sequence_sha256, *profile_args),
        ).fetchone()
        if sequence_row is not None:
            return int(sequence_row[0])

        date_filter = ""
        date_args: tuple[str, ...] = ()
        if parsed.bandcamp_date_created:
            date_filter = " AND lower(COALESCE(bandcamp_date_created, '')) = lower(?)"
            date_args = (parsed.bandcamp_date_created,)

        sheet_rows = self.conn.execute(
            f"""
            SELECT id
            FROM PromoCodeSheets
            WHERE lower(code_set_name) = lower(?)
              AND lower(COALESCE(album, '')) = ?
              {date_filter}
              {profile_filter}
            ORDER BY id DESC
            """,
            (parsed.code_set_name, album_key, *date_args, *profile_args),
        ).fetchall()
        if len(sheet_rows) == 1:
            return int(sheet_rows[0][0])
        if len(sheet_rows) > 1:
            raise ValueError(
                "Multiple existing promo-code sheets match this Bandcamp sheet metadata. "
                "The update would be ambiguous, so no database changes were made."
            )
        return None

    def _update_existing_sheet(
        self,
        sheet_id: int,
        parsed: ParsedBandcampPromoCsv,
        *,
        profile_name: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE PromoCodeSheets
            SET code_set_name=?,
                album=?,
                bandcamp_date_created=?,
                bandcamp_date_exported=?,
                quantity_created=?,
                quantity_redeemed_to_date=?,
                redeem_url=?,
                source_path=?,
                source_filename=?,
                source_sha256=?,
                code_sequence_sha256=?,
                profile_name=COALESCE(?, profile_name),
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                parsed.code_set_name,
                parsed.album,
                parsed.bandcamp_date_created,
                parsed.bandcamp_date_exported,
                parsed.quantity_created,
                parsed.quantity_redeemed_to_date,
                parsed.redeem_url,
                parsed.source_path,
                parsed.source_filename,
                parsed.source_sha256,
                parsed.code_sequence_sha256,
                _clean_text(profile_name),
                int(sheet_id),
            ),
        )

    def _update_existing_sheet_from_active_codes(
        self,
        sheet_id: int,
        parsed: ParsedBandcampPromoCsv,
        *,
        profile_name: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[int, int, int]:
        active_codes = {
            str(code or "").casefold(): (index, code)
            for index, code in enumerate(parsed.codes, start=1)
        }
        existing_rows = self.conn.execute(
            """
            SELECT id, code, redeemed
            FROM PromoCodes
            WHERE sheet_id = ?
            """,
            (int(sheet_id),),
        ).fetchall()
        existing_by_key = {str(row[1] or "").casefold(): row for row in existing_rows}
        inserted_codes = 0
        marked_redeemed_codes = 0
        reactivated_codes = 0
        total_steps = max(1, len(active_codes) + len(existing_rows))

        def report(done: int, message: str) -> None:
            if progress_callback is None:
                return
            progress = 15 + int((min(done, total_steps) / total_steps) * 80)
            progress_callback(progress, 100, message)

        with self.conn:
            self._update_existing_sheet(int(sheet_id), parsed, profile_name=profile_name)
            done = 0
            for code_key, (sort_order, code) in active_codes.items():
                existing = existing_by_key.get(code_key)
                if existing is None:
                    result = self.conn.execute(
                        """
                        INSERT OR IGNORE INTO PromoCodes (
                            sheet_id,
                            code,
                            sort_order,
                            redeemed,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, 0, datetime('now'), datetime('now'))
                        """,
                        (int(sheet_id), code, int(sort_order)),
                    )
                    inserted_codes += max(0, int(result.rowcount or 0))
                else:
                    was_redeemed = bool(int(existing[2] or 0))
                    if was_redeemed:
                        reactivated_codes += 1
                    self.conn.execute(
                        """
                        UPDATE PromoCodes
                        SET sort_order=?,
                            redeemed=0,
                            redeemed_at=NULL,
                            updated_at=datetime('now')
                        WHERE id=?
                        """,
                        (int(sort_order), int(existing[0])),
                    )
                done += 1
                if done == total_steps or done % 10 == 0:
                    report(done, f"Applied {done} active promo code(s)...")

            for row in existing_rows:
                code_key = str(row[1] or "").casefold()
                if code_key in active_codes:
                    done += 1
                    continue
                result = self.conn.execute(
                    """
                    UPDATE PromoCodes
                    SET redeemed=1,
                        redeemed_at=COALESCE(NULLIF(redeemed_at, ''), datetime('now')),
                        updated_at=datetime('now')
                    WHERE id=? AND redeemed=0
                    """,
                    (int(row[0]),),
                )
                marked_redeemed_codes += max(0, int(result.rowcount or 0))
                done += 1
                if done == total_steps or done % 10 == 0:
                    report(done, f"Checked {done} stored promo code(s)...")

        return inserted_codes, marked_redeemed_codes, reactivated_codes

    def list_sheets(self) -> list[PromoCodeSheetRecord]:
        self.ensure_schema()
        rows = self.conn.execute(
            """
            SELECT
                s.id,
                s.code_set_name,
                s.album,
                s.bandcamp_date_created,
                s.bandcamp_date_exported,
                s.quantity_created,
                s.quantity_redeemed_to_date,
                s.redeem_url,
                s.source_filename,
                s.source_path,
                s.source_sha256,
                s.code_sequence_sha256,
                s.profile_name,
                s.imported_at,
                s.updated_at,
                COUNT(c.id) AS total_codes,
                COALESCE(SUM(CASE WHEN c.redeemed THEN 1 ELSE 0 END), 0) AS redeemed_codes
            FROM PromoCodeSheets s
            LEFT JOIN PromoCodes c ON c.sheet_id = s.id
            GROUP BY s.id
            ORDER BY datetime(s.imported_at) DESC, s.id DESC
            """
        ).fetchall()
        return [self._sheet_from_row(row) for row in rows]

    def _sheet_from_row(self, row: sqlite3.Row | tuple[object, ...]) -> PromoCodeSheetRecord:
        return PromoCodeSheetRecord(
            id=int(row[0]),
            code_set_name=str(row[1] or ""),
            album=_clean_text(row[2]),
            bandcamp_date_created=_clean_text(row[3]),
            bandcamp_date_exported=_clean_text(row[4]),
            quantity_created=_parse_int(row[5]),
            quantity_redeemed_to_date=_parse_int(row[6]),
            redeem_url=_clean_text(row[7]),
            source_filename=_clean_text(row[8]),
            source_path=_clean_text(row[9]),
            source_sha256=_clean_text(row[10]),
            code_sequence_sha256=str(row[11] or ""),
            profile_name=_clean_text(row[12]),
            imported_at=_clean_text(row[13]),
            updated_at=_clean_text(row[14]),
            total_codes=int(row[15] or 0),
            redeemed_codes=int(row[16] or 0),
        )

    def list_codes(self, sheet_id: int) -> list[PromoCodeRecord]:
        self.ensure_schema()
        rows = self.conn.execute(
            """
            SELECT
                id,
                sheet_id,
                code,
                sort_order,
                redeemed,
                recipient_name,
                recipient_email,
                ledger_notes,
                provided_at,
                redeemed_at,
                created_at,
                updated_at
            FROM PromoCodes
            WHERE sheet_id = ?
            ORDER BY sort_order, id
            """,
            (int(sheet_id),),
        ).fetchall()
        return [self._code_from_row(row) for row in rows]

    def fetch_code(self, code_id: int) -> PromoCodeRecord | None:
        self.ensure_schema()
        row = self.conn.execute(
            """
            SELECT
                id,
                sheet_id,
                code,
                sort_order,
                redeemed,
                recipient_name,
                recipient_email,
                ledger_notes,
                provided_at,
                redeemed_at,
                created_at,
                updated_at
            FROM PromoCodes
            WHERE id = ?
            """,
            (int(code_id),),
        ).fetchone()
        return self._code_from_row(row) if row is not None else None

    def _code_from_row(self, row: sqlite3.Row | tuple[object, ...]) -> PromoCodeRecord:
        return PromoCodeRecord(
            id=int(row[0]),
            sheet_id=int(row[1]),
            code=str(row[2] or ""),
            sort_order=int(row[3] or 0),
            redeemed=bool(int(row[4] or 0)),
            recipient_name=_clean_text(row[5]),
            recipient_email=_clean_text(row[6]),
            ledger_notes=_clean_multiline_text(row[7]),
            provided_at=_clean_text(row[8]),
            redeemed_at=_clean_text(row[9]),
            created_at=_clean_text(row[10]),
            updated_at=_clean_text(row[11]),
        )

    def update_code_ledger(
        self,
        code_id: int,
        *,
        redeemed: bool,
        recipient_name: str | None = None,
        recipient_email: str | None = None,
        ledger_notes: str | None = None,
    ) -> PromoCodeRecord:
        self.ensure_schema()
        current = self.fetch_code(int(code_id))
        if current is None:
            raise ValueError("Promo code not found.")
        clean_name = _clean_text(recipient_name)
        clean_email = _clean_text(recipient_email)
        clean_notes = _clean_multiline_text(ledger_notes)
        has_recipient = bool(clean_name or clean_email)
        with self.conn:
            self.conn.execute(
                """
                UPDATE PromoCodes
                SET redeemed=?,
                    recipient_name=?,
                    recipient_email=?,
                    ledger_notes=?,
                    provided_at=CASE
                        WHEN ? = 1 AND (provided_at IS NULL OR provided_at = '')
                        THEN datetime('now')
                        WHEN ? = 0 AND ? = 0
                        THEN NULL
                        ELSE provided_at
                    END,
                    redeemed_at=CASE
                        WHEN ? = 1 AND (redeemed_at IS NULL OR redeemed_at = '')
                        THEN datetime('now')
                        WHEN ? = 0
                        THEN NULL
                        ELSE redeemed_at
                    END,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    1 if redeemed else 0,
                    clean_name,
                    clean_email,
                    clean_notes,
                    1 if has_recipient else 0,
                    1 if has_recipient else 0,
                    1 if redeemed else 0,
                    1 if redeemed else 0,
                    1 if redeemed else 0,
                    int(code_id),
                ),
            )
            self.conn.execute(
                """
                UPDATE PromoCodeSheets
                SET updated_at=datetime('now')
                WHERE id=?
                """,
                (int(current.sheet_id),),
            )
        updated = self.fetch_code(int(code_id))
        if updated is None:
            raise ValueError("Promo code not found after update.")
        return updated

    def _count_codes_for_sheet(self, sheet_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM PromoCodes WHERE sheet_id=?",
            (int(sheet_id),),
        ).fetchone()
        return int(row[0] or 0) if row is not None else 0

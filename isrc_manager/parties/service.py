"""Party/contact registry services."""

from __future__ import annotations

import sqlite3

from isrc_manager.domain.repertoire import clean_text, normalized_name

from .models import (
    PARTY_TYPE_CHOICES,
    PartyArtistAliasRecord,
    PartyDuplicate,
    PartyPayload,
    PartyRecord,
    PartyUsageSummary,
)


class PartyService:
    """Owns canonical party records and duplicate/merge helpers."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _clean_party_type(value: str | None) -> str:
        clean = str(value or "organization").strip().lower().replace(" ", "_")
        if clean not in PARTY_TYPE_CHOICES:
            return "other"
        return clean

    @staticmethod
    def _normalized_artist_alias_rows(
        alias_values: list[str] | tuple[str, ...],
    ) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw_value in alias_values:
            clean_alias = clean_text(raw_value)
            normalized_alias = normalized_name(clean_alias)
            if not clean_alias or not normalized_alias or normalized_alias in seen:
                continue
            seen.add(normalized_alias)
            rows.append((str(clean_alias), normalized_alias))
        return rows

    @staticmethod
    def _person_name_parts(payload: PartyPayload) -> tuple[str | None, str | None, str | None]:
        return (
            clean_text(payload.first_name),
            clean_text(payload.middle_name),
            clean_text(payload.last_name),
        )

    @staticmethod
    def _joined_person_name(
        first_name: str | None,
        middle_name: str | None,
        last_name: str | None,
    ) -> str | None:
        parts = [part for part in (first_name, middle_name, last_name) if part]
        if not parts:
            return None
        return " ".join(parts)

    def _row_to_record(self, row, *, artist_aliases: tuple[str, ...] = ()) -> PartyRecord:
        return PartyRecord(
            id=int(row[0]),
            legal_name=str(row[1] or ""),
            display_name=clean_text(row[2]),
            artist_name=clean_text(row[3]),
            company_name=clean_text(row[4]),
            first_name=clean_text(row[5]),
            middle_name=clean_text(row[6]),
            last_name=clean_text(row[7]),
            party_type=str(row[8] or "organization"),
            contact_person=clean_text(row[9]),
            email=clean_text(row[10]),
            alternative_email=clean_text(row[11]),
            phone=clean_text(row[12]),
            website=clean_text(row[13]),
            street_name=clean_text(row[14]),
            street_number=clean_text(row[15]),
            address_line1=clean_text(row[16]),
            address_line2=clean_text(row[17]),
            city=clean_text(row[18]),
            region=clean_text(row[19]),
            postal_code=clean_text(row[20]),
            country=clean_text(row[21]),
            bank_account_number=clean_text(row[22]),
            chamber_of_commerce_number=clean_text(row[23]),
            tax_id=clean_text(row[24]),
            vat_number=clean_text(row[25]),
            pro_affiliation=clean_text(row[26]),
            pro_number=clean_text(row[27]),
            ipi_cae=clean_text(row[28]),
            notes=clean_text(row[29]),
            profile_name=clean_text(row[30]),
            created_at=clean_text(row[31]),
            updated_at=clean_text(row[32]),
            artist_aliases=artist_aliases,
        )

    @staticmethod
    def _row_to_alias_record(row) -> PartyArtistAliasRecord:
        return PartyArtistAliasRecord(
            id=int(row[0]),
            party_id=int(row[1]),
            alias_name=str(row[2] or ""),
            normalized_alias=str(row[3] or ""),
            sort_order=int(row[4] or 0),
            created_at=clean_text(row[5]),
            updated_at=clean_text(row[6]),
        )

    def _artist_aliases_by_party_ids(self, party_ids: list[int]) -> dict[int, tuple[str, ...]]:
        if not party_ids:
            return {}
        placeholders = ",".join("?" for _ in party_ids)
        rows = self.conn.execute(
            f"""
            SELECT party_id, alias_name
            FROM PartyArtistAliases
            WHERE party_id IN ({placeholders})
            ORDER BY party_id, sort_order, id
            """,
            [int(party_id) for party_id in party_ids],
        ).fetchall()
        grouped: dict[int, list[str]] = {}
        for row in rows:
            grouped.setdefault(int(row[0]), []).append(str(row[1] or ""))
        return {party_id: tuple(values) for party_id, values in grouped.items()}

    def _select_party_rows(
        self,
        *,
        where_sql: str = "",
        params: list[object] | None = None,
    ) -> list[PartyRecord]:
        rows = self.conn.execute(
            f"""
            SELECT
                id,
                legal_name,
                display_name,
                artist_name,
                company_name,
                first_name,
                middle_name,
                last_name,
                party_type,
                contact_person,
                email,
                alternative_email,
                phone,
                website,
                street_name,
                street_number,
                address_line1,
                address_line2,
                city,
                region,
                postal_code,
                country,
                bank_account_number,
                chamber_of_commerce_number,
                tax_id,
                vat_number,
                pro_affiliation,
                pro_number,
                ipi_cae,
                notes,
                profile_name,
                created_at,
                updated_at
            FROM Parties
            {where_sql}
            """,
            params or [],
        ).fetchall()
        alias_map = self._artist_aliases_by_party_ids([int(row[0]) for row in rows])
        return [
            self._row_to_record(row, artist_aliases=alias_map.get(int(row[0]), ())) for row in rows
        ]

    def _normalize_and_validate_artist_aliases(
        self,
        payload: PartyPayload,
        *,
        party_id: int | None,
        cursor: sqlite3.Cursor,
    ) -> tuple[list[tuple[str, str]], list[str]]:
        alias_rows = self._normalized_artist_alias_rows(payload.artist_aliases)
        errors: list[str] = []
        clean_artist_name = clean_text(payload.artist_name)
        normalized_artist_name = normalized_name(clean_artist_name) or None
        if normalized_artist_name:
            artist_conflict = cursor.execute(
                """
                SELECT id
                FROM Parties
                WHERE lower(coalesce(artist_name, '')) = lower(?)
                  AND (? IS NULL OR id != ?)
                LIMIT 1
                """,
                (str(clean_artist_name or ""), party_id, party_id),
            ).fetchone()
            if artist_conflict:
                errors.append("Another party already uses this artist name.")
            alias_conflict = cursor.execute(
                """
                SELECT party_id
                FROM PartyArtistAliases
                WHERE normalized_alias=?
                  AND (? IS NULL OR party_id != ?)
                LIMIT 1
                """,
                (normalized_artist_name, party_id, party_id),
            ).fetchone()
            if alias_conflict:
                errors.append("This artist name is already stored as an alias on another party.")
        for clean_alias, normalized_alias in alias_rows:
            if normalized_artist_name and normalized_alias == normalized_artist_name:
                errors.append("Artist aliases must not repeat the canonical artist name.")
                continue
            artist_conflict = cursor.execute(
                """
                SELECT id
                FROM Parties
                WHERE lower(coalesce(artist_name, '')) = lower(?)
                  AND (? IS NULL OR id != ?)
                LIMIT 1
                """,
                (clean_alias, party_id, party_id),
            ).fetchone()
            if artist_conflict:
                errors.append(
                    f"Artist alias '{clean_alias}' is already the artist name of another party."
                )
                continue
            alias_conflict = cursor.execute(
                """
                SELECT party_id
                FROM PartyArtistAliases
                WHERE normalized_alias=?
                  AND (? IS NULL OR party_id != ?)
                LIMIT 1
                """,
                (normalized_alias, party_id, party_id),
            ).fetchone()
            if alias_conflict:
                errors.append(f"Artist alias '{clean_alias}' is already linked to another party.")
        return alias_rows, errors

    @staticmethod
    def _validate_cross_email_uniqueness(
        cursor: sqlite3.Cursor,
        email_value: str,
        *,
        party_id: int | None,
        label: str,
    ) -> str | None:
        row = cursor.execute(
            """
            SELECT id
            FROM Parties
            WHERE (
                lower(coalesce(email, '')) = lower(?)
                OR lower(coalesce(alternative_email, '')) = lower(?)
            )
            AND (? IS NULL OR id != ?)
            LIMIT 1
            """,
            (email_value, email_value, party_id, party_id),
        ).fetchone()
        if row:
            return f"Another party already uses this {label.lower()}."
        return None

    def validate_party(
        self,
        payload: PartyPayload,
        *,
        party_id: int | None = None,
        cursor: sqlite3.Cursor | None = None,
    ) -> list[str]:
        cur = cursor or self.conn.cursor()
        errors: list[str] = []
        legal_name = clean_text(payload.legal_name)
        if not legal_name:
            errors.append("Legal name is required.")
        person_name = self._joined_person_name(*self._person_name_parts(payload))
        if not legal_name and not person_name:
            errors.append("Provide either a legal name or a structured person name.")
        email = clean_text(payload.email)
        if email:
            message = self._validate_cross_email_uniqueness(
                cur,
                email,
                party_id=party_id,
                label="Email Address",
            )
            if message:
                errors.append(message)
        alternative_email = clean_text(payload.alternative_email)
        if alternative_email:
            message = self._validate_cross_email_uniqueness(
                cur,
                alternative_email,
                party_id=party_id,
                label="Alternative Email Address",
            )
            if message:
                errors.append(message)
        ipi_cae = clean_text(payload.ipi_cae)
        if ipi_cae:
            row = cur.execute(
                """
                SELECT id
                FROM Parties
                WHERE ipi_cae=?
                  AND (? IS NULL OR id != ?)
                LIMIT 1
                """,
                (ipi_cae, party_id, party_id),
            ).fetchone()
            if row:
                errors.append("Another party already uses this IPI/CAE.")
        chamber_number = clean_text(payload.chamber_of_commerce_number)
        if chamber_number:
            row = cur.execute(
                """
                SELECT id
                FROM Parties
                WHERE chamber_of_commerce_number=?
                  AND (? IS NULL OR id != ?)
                LIMIT 1
                """,
                (chamber_number, party_id, party_id),
            ).fetchone()
            if row:
                errors.append("Another party already uses this Chamber of Commerce Number.")
        pro_number = clean_text(payload.pro_number)
        if pro_number:
            row = cur.execute(
                """
                SELECT id
                FROM Parties
                WHERE pro_number=?
                  AND (? IS NULL OR id != ?)
                LIMIT 1
                """,
                (pro_number, party_id, party_id),
            ).fetchone()
            if row:
                errors.append("Another party already uses this PRO Number.")
        _alias_rows, alias_errors = self._normalize_and_validate_artist_aliases(
            payload,
            party_id=party_id,
            cursor=cur,
        )
        errors.extend(alias_errors)
        return errors

    def _replace_artist_aliases(
        self,
        party_id: int,
        artist_aliases: list[str],
        *,
        cursor: sqlite3.Cursor,
    ) -> list[PartyArtistAliasRecord]:
        alias_rows = self._normalized_artist_alias_rows(artist_aliases)
        cursor.execute("DELETE FROM PartyArtistAliases WHERE party_id=?", (int(party_id),))
        for sort_order, (alias_name, normalized_alias) in enumerate(alias_rows, start=1):
            cursor.execute(
                """
                INSERT INTO PartyArtistAliases(
                    party_id,
                    alias_name,
                    normalized_alias,
                    sort_order
                )
                VALUES (?, ?, ?, ?)
                """,
                (int(party_id), alias_name, normalized_alias, int(sort_order)),
            )
        rows = cursor.execute(
            """
            SELECT
                id,
                party_id,
                alias_name,
                normalized_alias,
                sort_order,
                created_at,
                updated_at
            FROM PartyArtistAliases
            WHERE party_id=?
            ORDER BY sort_order, id
            """,
            (int(party_id),),
        ).fetchall()
        return [self._row_to_alias_record(row) for row in rows]

    def create_party(self, payload: PartyPayload, *, cursor: sqlite3.Cursor | None = None) -> int:
        cur = cursor or self.conn.cursor()
        errors = self.validate_party(payload, cursor=cur)
        if errors:
            raise ValueError("\n".join(errors))
        first_name, middle_name, last_name = self._person_name_parts(payload)
        cur.execute(
            """
            INSERT INTO Parties (
                legal_name,
                display_name,
                artist_name,
                company_name,
                first_name,
                middle_name,
                last_name,
                party_type,
                contact_person,
                email,
                alternative_email,
                phone,
                website,
                street_name,
                street_number,
                address_line1,
                address_line2,
                city,
                region,
                postal_code,
                country,
                bank_account_number,
                chamber_of_commerce_number,
                tax_id,
                vat_number,
                pro_affiliation,
                pro_number,
                ipi_cae,
                notes,
                profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(clean_text(payload.legal_name) or ""),
                clean_text(payload.display_name),
                clean_text(payload.artist_name),
                clean_text(payload.company_name),
                first_name,
                middle_name,
                last_name,
                self._clean_party_type(payload.party_type),
                clean_text(payload.contact_person),
                clean_text(payload.email),
                clean_text(payload.alternative_email),
                clean_text(payload.phone),
                clean_text(payload.website),
                clean_text(payload.street_name),
                clean_text(payload.street_number),
                clean_text(payload.address_line1),
                clean_text(payload.address_line2),
                clean_text(payload.city),
                clean_text(payload.region),
                clean_text(payload.postal_code),
                clean_text(payload.country),
                clean_text(payload.bank_account_number),
                clean_text(payload.chamber_of_commerce_number),
                clean_text(payload.tax_id),
                clean_text(payload.vat_number),
                clean_text(payload.pro_affiliation),
                clean_text(payload.pro_number),
                clean_text(payload.ipi_cae),
                clean_text(payload.notes),
                clean_text(payload.profile_name),
            ),
        )
        party_id = int(cur.lastrowid)
        self._replace_artist_aliases(party_id, payload.artist_aliases, cursor=cur)
        if cursor is None:
            self.conn.commit()
        return party_id

    def update_party(
        self,
        party_id: int,
        payload: PartyPayload,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> None:
        cur = cursor or self.conn.cursor()
        errors = self.validate_party(payload, party_id=int(party_id), cursor=cur)
        if errors:
            raise ValueError("\n".join(errors))
        first_name, middle_name, last_name = self._person_name_parts(payload)
        cur.execute(
            """
            UPDATE Parties
            SET legal_name=?,
                display_name=?,
                artist_name=?,
                company_name=?,
                first_name=?,
                middle_name=?,
                last_name=?,
                party_type=?,
                contact_person=?,
                email=?,
                alternative_email=?,
                phone=?,
                website=?,
                street_name=?,
                street_number=?,
                address_line1=?,
                address_line2=?,
                city=?,
                region=?,
                postal_code=?,
                country=?,
                bank_account_number=?,
                chamber_of_commerce_number=?,
                tax_id=?,
                vat_number=?,
                pro_affiliation=?,
                pro_number=?,
                ipi_cae=?,
                notes=?,
                profile_name=?,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                str(clean_text(payload.legal_name) or ""),
                clean_text(payload.display_name),
                clean_text(payload.artist_name),
                clean_text(payload.company_name),
                first_name,
                middle_name,
                last_name,
                self._clean_party_type(payload.party_type),
                clean_text(payload.contact_person),
                clean_text(payload.email),
                clean_text(payload.alternative_email),
                clean_text(payload.phone),
                clean_text(payload.website),
                clean_text(payload.street_name),
                clean_text(payload.street_number),
                clean_text(payload.address_line1),
                clean_text(payload.address_line2),
                clean_text(payload.city),
                clean_text(payload.region),
                clean_text(payload.postal_code),
                clean_text(payload.country),
                clean_text(payload.bank_account_number),
                clean_text(payload.chamber_of_commerce_number),
                clean_text(payload.tax_id),
                clean_text(payload.vat_number),
                clean_text(payload.pro_affiliation),
                clean_text(payload.pro_number),
                clean_text(payload.ipi_cae),
                clean_text(payload.notes),
                clean_text(payload.profile_name),
                int(party_id),
            ),
        )
        self._replace_artist_aliases(int(party_id), payload.artist_aliases, cursor=cur)
        if cursor is None:
            self.conn.commit()

    def delete_party(self, party_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM Parties WHERE id=?", (int(party_id),))

    def list_artist_aliases(self, party_id: int) -> list[PartyArtistAliasRecord]:
        rows = self.conn.execute(
            """
            SELECT
                id,
                party_id,
                alias_name,
                normalized_alias,
                sort_order,
                created_at,
                updated_at
            FROM PartyArtistAliases
            WHERE party_id=?
            ORDER BY sort_order, id
            """,
            (int(party_id),),
        ).fetchall()
        return [self._row_to_alias_record(row) for row in rows]

    def fetch_party(self, party_id: int) -> PartyRecord | None:
        records = self._select_party_rows(where_sql="WHERE id=?", params=[int(party_id)])
        return records[0] if records else None

    def list_parties(
        self, *, search_text: str | None = None, party_type: str | None = None
    ) -> list[PartyRecord]:
        clauses: list[str] = []
        params: list[object] = []
        clean_search = clean_text(search_text)
        if clean_search:
            like = f"%{clean_search}%"
            clauses.append(
                """
                (
                    legal_name LIKE ?
                    OR COALESCE(display_name, '') LIKE ?
                    OR COALESCE(artist_name, '') LIKE ?
                    OR COALESCE(company_name, '') LIKE ?
                    OR COALESCE(first_name, '') LIKE ?
                    OR COALESCE(middle_name, '') LIKE ?
                    OR COALESCE(last_name, '') LIKE ?
                    OR COALESCE(contact_person, '') LIKE ?
                    OR COALESCE(email, '') LIKE ?
                    OR COALESCE(alternative_email, '') LIKE ?
                    OR COALESCE(ipi_cae, '') LIKE ?
                    OR COALESCE(pro_number, '') LIKE ?
                    OR COALESCE(chamber_of_commerce_number, '') LIKE ?
                    OR EXISTS(
                        SELECT 1
                        FROM PartyArtistAliases alias
                        WHERE alias.party_id = Parties.id
                          AND alias.alias_name LIKE ?
                    )
                )
                """
            )
            params.extend([like] * 14)
        clean_party_type = clean_text(party_type)
        if clean_party_type:
            clauses.append("party_type=?")
            params.append(self._clean_party_type(clean_party_type))
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        records = self._select_party_rows(
            where_sql=(
                where_sql
                + " ORDER BY COALESCE(display_name, artist_name, company_name, legal_name), legal_name, id"
            ),
            params=params,
        )
        return records

    def find_party_id_by_name(
        self,
        name: str,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> int | None:
        clean_name = clean_text(name)
        if not clean_name:
            return None
        cur = cursor or self.conn.cursor()
        normalized_lookup = normalized_name(clean_name)
        if normalized_lookup:
            alias_row = cur.execute(
                """
                SELECT party_id
                FROM PartyArtistAliases
                WHERE normalized_alias=?
                ORDER BY party_id
                LIMIT 1
                """,
                (normalized_lookup,),
            ).fetchone()
            if alias_row:
                return int(alias_row[0])
        artist_row = cur.execute(
            """
            SELECT id
            FROM Parties
            WHERE lower(coalesce(artist_name, '')) = lower(?)
            ORDER BY id
            LIMIT 1
            """,
            (clean_name,),
        ).fetchone()
        if artist_row:
            return int(artist_row[0])
        full_name = clean_name
        row = cur.execute(
            """
            SELECT id
            FROM Parties
            WHERE lower(legal_name)=lower(?)
               OR lower(coalesce(display_name, ''))=lower(?)
               OR lower(coalesce(company_name, ''))=lower(?)
               OR lower(trim(
                    coalesce(first_name, '')
                    || CASE
                        WHEN coalesce(middle_name, '') <> '' THEN ' ' || middle_name
                        ELSE ''
                    END
                    || CASE
                        WHEN coalesce(last_name, '') <> '' THEN ' ' || last_name
                        ELSE ''
                    END
               )) = lower(?)
            ORDER BY id
            LIMIT 1
            """,
            (clean_name, clean_name, clean_name, full_name),
        ).fetchone()
        return int(row[0]) if row else None

    def ensure_party_by_name(
        self,
        name: str,
        *,
        party_type: str = "other",
        cursor: sqlite3.Cursor | None = None,
    ) -> int:
        clean_name = clean_text(name)
        if not clean_name:
            raise ValueError("Party name is required.")
        cur = cursor or self.conn.cursor()
        existing_id = self.find_party_id_by_name(clean_name, cursor=cur)
        if existing_id is not None:
            return int(existing_id)
        return self.create_party(
            PartyPayload(
                legal_name=clean_name,
                display_name=clean_name,
                party_type=party_type,
            ),
            cursor=cur,
        )

    def usage_summary(self, party_id: int) -> PartyUsageSummary:
        table_names = {
            str(row[0])
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if row and row[0]
        }
        work_queries = ["SELECT work_id FROM WorkContributors WHERE party_id=?"]
        work_params: list[object] = [int(party_id)]
        if "WorkContributionEntries" in table_names:
            work_queries.append("SELECT work_id FROM WorkContributionEntries WHERE party_id=?")
            work_params.append(int(party_id))
        if "WorkOwnershipInterests" in table_names:
            work_queries.append("SELECT work_id FROM WorkOwnershipInterests WHERE party_id=?")
            work_params.append(int(party_id))
        work_count = self.conn.execute(
            f"SELECT COUNT(DISTINCT work_id) FROM ({' UNION '.join(work_queries)})",
            work_params,
        ).fetchone()
        contract_count = self.conn.execute(
            "SELECT COUNT(*) FROM ContractParties WHERE party_id=?",
            (int(party_id),),
        ).fetchone()
        rights_count = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM RightsRecords
            WHERE granted_by_party_id=? OR granted_to_party_id=? OR retained_by_party_id=?
            """,
            (int(party_id), int(party_id), int(party_id)),
        ).fetchone()
        return PartyUsageSummary(
            work_count=int(work_count[0] or 0),
            contract_count=int(contract_count[0] or 0),
            rights_count=int(rights_count[0] or 0),
        )

    def detect_duplicates(self) -> list[PartyDuplicate]:
        rows = self.list_parties()
        duplicates: list[PartyDuplicate] = []
        for index, left in enumerate(rows):
            left_legal_name = normalized_name(left.legal_name)
            left_email = normalized_name(left.email)
            left_alternative_email = normalized_name(left.alternative_email)
            left_ipi = normalized_name(left.ipi_cae)
            left_artist_name = normalized_name(left.artist_name)
            left_chamber_number = normalized_name(left.chamber_of_commerce_number)
            left_pro_number = normalized_name(left.pro_number)
            for right in rows[index + 1 :]:
                if left_legal_name and left_legal_name == normalized_name(right.legal_name):
                    duplicates.append(
                        PartyDuplicate(
                            "legal_name",
                            left.id,
                            right.id,
                            f"{left.legal_name} appears more than once.",
                        )
                    )
                if left_email and left_email == normalized_name(right.email):
                    duplicates.append(
                        PartyDuplicate(
                            "email",
                            left.id,
                            right.id,
                            f"{left.email} is attached to multiple party records.",
                        )
                    )
                if left_alternative_email and left_alternative_email == normalized_name(
                    right.alternative_email
                ):
                    duplicates.append(
                        PartyDuplicate(
                            "alternative_email",
                            left.id,
                            right.id,
                            f"{left.alternative_email} is attached to multiple party records.",
                        )
                    )
                if left_ipi and left_ipi == normalized_name(right.ipi_cae):
                    duplicates.append(
                        PartyDuplicate(
                            "ipi_cae",
                            left.id,
                            right.id,
                            f"{left.ipi_cae} is attached to multiple party records.",
                        )
                    )
                if left_artist_name and left_artist_name == normalized_name(right.artist_name):
                    duplicates.append(
                        PartyDuplicate(
                            "artist_name",
                            left.id,
                            right.id,
                            f"{left.artist_name} appears more than once as a canonical artist name.",
                        )
                    )
                if left_chamber_number and left_chamber_number == normalized_name(
                    right.chamber_of_commerce_number
                ):
                    duplicates.append(
                        PartyDuplicate(
                            "chamber_of_commerce_number",
                            left.id,
                            right.id,
                            (
                                f"{left.chamber_of_commerce_number} is attached to multiple "
                                "party records."
                            ),
                        )
                    )
                if left_pro_number and left_pro_number == normalized_name(right.pro_number):
                    duplicates.append(
                        PartyDuplicate(
                            "pro_number",
                            left.id,
                            right.id,
                            f"{left.pro_number} is attached to multiple party records.",
                        )
                    )
        return duplicates

    def merge_parties(self, primary_party_id: int, duplicate_party_ids: list[int]) -> PartyRecord:
        primary_party_id = int(primary_party_id)
        duplicates = [
            int(party_id) for party_id in duplicate_party_ids if int(party_id) != primary_party_id
        ]
        if not duplicates:
            record = self.fetch_party(primary_party_id)
            if record is None:
                raise ValueError("Primary party not found.")
            return record

        primary_record = self.fetch_party(primary_party_id)
        if primary_record is None:
            raise ValueError("Primary party not found.")
        merged_alias_values = list(primary_record.artist_aliases)
        merged_artist_name = clean_text(primary_record.artist_name)

        with self.conn:
            cur = self.conn.cursor()
            table_names = {
                str(row[0])
                for row in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                if row and row[0]
            }
            for duplicate_id in duplicates:
                duplicate_record = self.fetch_party(duplicate_id)
                if duplicate_record is None:
                    continue
                duplicate_artist_name = clean_text(duplicate_record.artist_name)
                if duplicate_artist_name:
                    if merged_artist_name is None:
                        merged_artist_name = duplicate_artist_name
                    elif normalized_name(duplicate_artist_name) != normalized_name(
                        merged_artist_name
                    ):
                        merged_alias_values.append(str(duplicate_artist_name))
                merged_alias_values.extend(list(duplicate_record.artist_aliases))
                cur.execute(
                    "UPDATE WorkContributors SET party_id=? WHERE party_id=?",
                    (primary_party_id, duplicate_id),
                )
                if "WorkContributionEntries" in table_names:
                    cur.execute(
                        "UPDATE WorkContributionEntries SET party_id=? WHERE party_id=?",
                        (primary_party_id, duplicate_id),
                    )
                if "WorkOwnershipInterests" in table_names:
                    cur.execute(
                        "UPDATE WorkOwnershipInterests SET party_id=? WHERE party_id=?",
                        (primary_party_id, duplicate_id),
                    )
                if "RecordingContributionEntries" in table_names:
                    cur.execute(
                        "UPDATE RecordingContributionEntries SET party_id=? WHERE party_id=?",
                        (primary_party_id, duplicate_id),
                    )
                if "RecordingOwnershipInterests" in table_names:
                    cur.execute(
                        "UPDATE RecordingOwnershipInterests SET party_id=? WHERE party_id=?",
                        (primary_party_id, duplicate_id),
                    )
                cur.execute(
                    """
                    INSERT OR IGNORE INTO ContractParties(contract_id, party_id, role_label, is_primary, notes)
                    SELECT contract_id, ?, role_label, is_primary, notes
                    FROM ContractParties
                    WHERE party_id=?
                    """,
                    (primary_party_id, duplicate_id),
                )
                cur.execute("DELETE FROM ContractParties WHERE party_id=?", (duplicate_id,))
                for column_name in (
                    "granted_by_party_id",
                    "granted_to_party_id",
                    "retained_by_party_id",
                ):
                    cur.execute(
                        f"UPDATE RightsRecords SET {column_name}=? WHERE {column_name}=?",
                        (primary_party_id, duplicate_id),
                    )
                cur.execute("DELETE FROM PartyArtistAliases WHERE party_id=?", (duplicate_id,))
                cur.execute("DELETE FROM Parties WHERE id=?", (duplicate_id,))
            merged_payload = PartyPayload(
                legal_name=primary_record.legal_name,
                display_name=primary_record.display_name,
                artist_name=merged_artist_name,
                company_name=primary_record.company_name,
                first_name=primary_record.first_name,
                middle_name=primary_record.middle_name,
                last_name=primary_record.last_name,
                party_type=primary_record.party_type,
                contact_person=primary_record.contact_person,
                email=primary_record.email,
                alternative_email=primary_record.alternative_email,
                phone=primary_record.phone,
                website=primary_record.website,
                street_name=primary_record.street_name,
                street_number=primary_record.street_number,
                address_line1=primary_record.address_line1,
                address_line2=primary_record.address_line2,
                city=primary_record.city,
                region=primary_record.region,
                postal_code=primary_record.postal_code,
                country=primary_record.country,
                bank_account_number=primary_record.bank_account_number,
                chamber_of_commerce_number=primary_record.chamber_of_commerce_number,
                tax_id=primary_record.tax_id,
                vat_number=primary_record.vat_number,
                pro_affiliation=primary_record.pro_affiliation,
                pro_number=primary_record.pro_number,
                ipi_cae=primary_record.ipi_cae,
                notes=primary_record.notes,
                profile_name=primary_record.profile_name,
                artist_aliases=merged_alias_values,
            )
            errors = self.validate_party(
                merged_payload,
                party_id=primary_party_id,
                cursor=cur,
            )
            if errors:
                raise ValueError("\n".join(errors))
            cur.execute(
                """
                UPDATE Parties
                SET artist_name=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (merged_artist_name, primary_party_id),
            )
            self._replace_artist_aliases(primary_party_id, merged_alias_values, cursor=cur)
        merged = self.fetch_party(primary_party_id)
        if merged is None:
            raise ValueError("Merged party could not be loaded.")
        return merged

    def export_rows(self) -> list[dict[str, object]]:
        return [record.to_dict() for record in self.list_parties()]

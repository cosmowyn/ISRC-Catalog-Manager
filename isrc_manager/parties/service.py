"""Party/contact registry services."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict

from isrc_manager.domain.repertoire import clean_text, normalized_name

from .models import PARTY_TYPE_CHOICES, PartyDuplicate, PartyPayload, PartyRecord, PartyUsageSummary


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

    def _row_to_record(self, row) -> PartyRecord:
        return PartyRecord(
            id=int(row[0]),
            legal_name=str(row[1] or ""),
            display_name=clean_text(row[2]),
            party_type=str(row[3] or "organization"),
            contact_person=clean_text(row[4]),
            email=clean_text(row[5]),
            phone=clean_text(row[6]),
            website=clean_text(row[7]),
            address_line1=clean_text(row[8]),
            address_line2=clean_text(row[9]),
            city=clean_text(row[10]),
            region=clean_text(row[11]),
            postal_code=clean_text(row[12]),
            country=clean_text(row[13]),
            tax_id=clean_text(row[14]),
            vat_number=clean_text(row[15]),
            pro_affiliation=clean_text(row[16]),
            ipi_cae=clean_text(row[17]),
            notes=clean_text(row[18]),
            profile_name=clean_text(row[19]),
            created_at=clean_text(row[20]),
            updated_at=clean_text(row[21]),
        )

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
        if clean_text(payload.email):
            params: list[object] = [clean_text(payload.email)]
            sql = "SELECT id FROM Parties WHERE email=?"
            if party_id is not None:
                sql += " AND id != ?"
                params.append(int(party_id))
            sql += " LIMIT 1"
            if cur.execute(sql, params).fetchone():
                errors.append("Another party already uses this email address.")
        if clean_text(payload.ipi_cae):
            params = [clean_text(payload.ipi_cae)]
            sql = "SELECT id FROM Parties WHERE ipi_cae=?"
            if party_id is not None:
                sql += " AND id != ?"
                params.append(int(party_id))
            sql += " LIMIT 1"
            if cur.execute(sql, params).fetchone():
                errors.append("Another party already uses this IPI/CAE.")
        return errors

    def create_party(self, payload: PartyPayload, *, cursor: sqlite3.Cursor | None = None) -> int:
        cur = cursor or self.conn.cursor()
        errors = self.validate_party(payload, cursor=cur)
        if errors:
            raise ValueError("\n".join(errors))
        cur.execute(
            """
            INSERT INTO Parties (
                legal_name,
                display_name,
                party_type,
                contact_person,
                email,
                phone,
                website,
                address_line1,
                address_line2,
                city,
                region,
                postal_code,
                country,
                tax_id,
                vat_number,
                pro_affiliation,
                ipi_cae,
                notes,
                profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(clean_text(payload.legal_name) or ""),
                clean_text(payload.display_name),
                self._clean_party_type(payload.party_type),
                clean_text(payload.contact_person),
                clean_text(payload.email),
                clean_text(payload.phone),
                clean_text(payload.website),
                clean_text(payload.address_line1),
                clean_text(payload.address_line2),
                clean_text(payload.city),
                clean_text(payload.region),
                clean_text(payload.postal_code),
                clean_text(payload.country),
                clean_text(payload.tax_id),
                clean_text(payload.vat_number),
                clean_text(payload.pro_affiliation),
                clean_text(payload.ipi_cae),
                clean_text(payload.notes),
                clean_text(payload.profile_name),
            ),
        )
        if cursor is None:
            self.conn.commit()
        return int(cur.lastrowid)

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
        cur.execute(
            """
            UPDATE Parties
            SET legal_name=?,
                display_name=?,
                party_type=?,
                contact_person=?,
                email=?,
                phone=?,
                website=?,
                address_line1=?,
                address_line2=?,
                city=?,
                region=?,
                postal_code=?,
                country=?,
                tax_id=?,
                vat_number=?,
                pro_affiliation=?,
                ipi_cae=?,
                notes=?,
                profile_name=?,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                str(clean_text(payload.legal_name) or ""),
                clean_text(payload.display_name),
                self._clean_party_type(payload.party_type),
                clean_text(payload.contact_person),
                clean_text(payload.email),
                clean_text(payload.phone),
                clean_text(payload.website),
                clean_text(payload.address_line1),
                clean_text(payload.address_line2),
                clean_text(payload.city),
                clean_text(payload.region),
                clean_text(payload.postal_code),
                clean_text(payload.country),
                clean_text(payload.tax_id),
                clean_text(payload.vat_number),
                clean_text(payload.pro_affiliation),
                clean_text(payload.ipi_cae),
                clean_text(payload.notes),
                clean_text(payload.profile_name),
                int(party_id),
            ),
        )
        if cursor is None:
            self.conn.commit()

    def delete_party(self, party_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM Parties WHERE id=?", (int(party_id),))

    def fetch_party(self, party_id: int) -> PartyRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                legal_name,
                display_name,
                party_type,
                contact_person,
                email,
                phone,
                website,
                address_line1,
                address_line2,
                city,
                region,
                postal_code,
                country,
                tax_id,
                vat_number,
                pro_affiliation,
                ipi_cae,
                notes,
                profile_name,
                created_at,
                updated_at
            FROM Parties
            WHERE id=?
            """,
            (int(party_id),),
        ).fetchone()
        return self._row_to_record(row) if row else None

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
                    OR COALESCE(email, '') LIKE ?
                    OR COALESCE(ipi_cae, '') LIKE ?
                )
                """
            )
            params.extend([like, like, like, like])
        clean_party_type = clean_text(party_type)
        if clean_party_type:
            clauses.append("party_type=?")
            params.append(self._clean_party_type(clean_party_type))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT
                id,
                legal_name,
                display_name,
                party_type,
                contact_person,
                email,
                phone,
                website,
                address_line1,
                address_line2,
                city,
                region,
                postal_code,
                country,
                tax_id,
                vat_number,
                pro_affiliation,
                ipi_cae,
                notes,
                profile_name,
                created_at,
                updated_at
            FROM Parties
            {where}
            ORDER BY COALESCE(display_name, legal_name), legal_name, id
            """,
            params,
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

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
        row = cur.execute(
            """
            SELECT id
            FROM Parties
            WHERE lower(legal_name)=lower(?) OR lower(COALESCE(display_name, ''))=lower(?)
            ORDER BY id
            LIMIT 1
            """,
            (clean_name, clean_name),
        ).fetchone()
        if row:
            return int(row[0])
        return self.create_party(
            PartyPayload(legal_name=clean_name, display_name=clean_name, party_type=party_type),
            cursor=cur,
        )

    def usage_summary(self, party_id: int) -> PartyUsageSummary:
        work_count = self.conn.execute(
            "SELECT COUNT(*) FROM WorkContributors WHERE party_id=?",
            (int(party_id),),
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
            left_name = normalized_name(left.legal_name)
            left_email = normalized_name(left.email)
            left_ipi = normalized_name(left.ipi_cae)
            for right in rows[index + 1 :]:
                if left_name and left_name == normalized_name(right.legal_name):
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
                if left_ipi and left_ipi == normalized_name(right.ipi_cae):
                    duplicates.append(
                        PartyDuplicate(
                            "ipi_cae",
                            left.id,
                            right.id,
                            f"{left.ipi_cae} is attached to multiple party records.",
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
        with self.conn:
            for duplicate_id in duplicates:
                self.conn.execute(
                    "UPDATE WorkContributors SET party_id=? WHERE party_id=?",
                    (primary_party_id, duplicate_id),
                )
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO ContractParties(contract_id, party_id, role_label, is_primary, notes)
                    SELECT contract_id, ?, role_label, is_primary, notes
                    FROM ContractParties
                    WHERE party_id=?
                    """,
                    (primary_party_id, duplicate_id),
                )
                self.conn.execute("DELETE FROM ContractParties WHERE party_id=?", (duplicate_id,))
                for column_name in (
                    "granted_by_party_id",
                    "granted_to_party_id",
                    "retained_by_party_id",
                ):
                    self.conn.execute(
                        f"UPDATE RightsRecords SET {column_name}=? WHERE {column_name}=?",
                        (primary_party_id, duplicate_id),
                    )
                self.conn.execute("DELETE FROM Parties WHERE id=?", (duplicate_id,))
        merged = self.fetch_party(primary_party_id)
        if merged is None:
            raise ValueError("Merged party could not be loaded.")
        return merged

    def export_rows(self) -> list[dict[str, object]]:
        return [asdict(record) for record in self.list_parties()]

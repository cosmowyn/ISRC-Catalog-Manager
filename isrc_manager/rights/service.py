"""Rights grant CRUD, ownership summaries, and conflict detection."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import Iterable

from isrc_manager.domain.repertoire import clean_text, normalized_territory, ranges_overlap

from .models import (
    OWNERSHIP_ROLE_CHOICES,
    RIGHT_TYPE_CHOICES,
    OwnershipInterestPayload,
    OwnershipInterestRecord,
    OwnershipSummary,
    RightPayload,
    RightRecord,
    RightsConflict,
)


class RightsService:
    """Owns structured rights grants linked to works, tracks, releases, and contracts."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _clean_type(value: str | None) -> str:
        clean = str(value or "other").strip().lower().replace(" ", "_")
        if clean not in RIGHT_TYPE_CHOICES:
            return "other"
        return clean

    @staticmethod
    def _clean_share(value: float | int | str | None) -> float | None:
        if value in (None, ""):
            return None
        try:
            return round(float(value), 4)
        except Exception:
            return None

    @staticmethod
    def _clean_ownership_role(value: str | None, *, entity_type: str) -> str:
        clean = str(value or "").strip().lower().replace(" ", "_")
        if clean in OWNERSHIP_ROLE_CHOICES:
            return clean
        return "publisher" if entity_type == "work" else "master_owner"

    @staticmethod
    def _ownership_table_spec(entity_type: str) -> tuple[str, str]:
        clean = str(entity_type or "").strip().lower()
        if clean == "work":
            return ("WorkOwnershipInterests", "work_id")
        if clean == "track":
            return ("RecordingOwnershipInterests", "track_id")
        raise ValueError("Ownership interests only support work or track entities.")

    @staticmethod
    def _dedupe_names(values: Iterable[str | None]) -> list[str]:
        names: list[str] = []
        for value in values:
            clean_value = clean_text(value)
            if clean_value and clean_value not in names:
                names.append(clean_value)
        return names

    def _track_columns(self) -> set[str]:
        return {
            str(row[1])
            for row in self.conn.execute("PRAGMA table_info(Tracks)").fetchall()
            if row and row[1]
        }

    @staticmethod
    def _row_to_record(row) -> RightRecord:
        return RightRecord(
            id=int(row[0]),
            title=clean_text(row[1]),
            right_type=str(row[2] or "other"),
            exclusive_flag=bool(row[3]),
            territory=clean_text(row[4]),
            media_use_type=clean_text(row[5]),
            start_date=clean_text(row[6]),
            end_date=clean_text(row[7]),
            perpetual_flag=bool(row[8]),
            granted_by_party_id=int(row[9]) if row[9] is not None else None,
            granted_by_name=clean_text(row[10]),
            granted_to_party_id=int(row[11]) if row[11] is not None else None,
            granted_to_name=clean_text(row[12]),
            retained_by_party_id=int(row[13]) if row[13] is not None else None,
            retained_by_name=clean_text(row[14]),
            source_contract_id=int(row[15]) if row[15] is not None else None,
            source_contract_title=clean_text(row[16]),
            work_id=int(row[17]) if row[17] is not None else None,
            track_id=int(row[18]) if row[18] is not None else None,
            release_id=int(row[19]) if row[19] is not None else None,
            notes=clean_text(row[20]),
            profile_name=clean_text(row[21]),
            created_at=clean_text(row[22]),
            updated_at=clean_text(row[23]),
        )

    @staticmethod
    def _row_to_ownership_record(row, *, entity_type: str) -> OwnershipInterestRecord:
        return OwnershipInterestRecord(
            id=int(row[0]),
            entity_type=entity_type,
            entity_id=int(row[1]),
            party_id=int(row[2]) if row[2] is not None else None,
            party_name=clean_text(row[3]),
            display_name=clean_text(row[4]),
            ownership_role=str(row[5] or "other"),
            share_percent=float(row[6]) if row[6] is not None else None,
            territory=clean_text(row[7]),
            source_contract_id=int(row[8]) if row[8] is not None else None,
            source_contract_title=clean_text(row[9]),
            notes=clean_text(row[10]),
            created_at=clean_text(row[11]),
            updated_at=clean_text(row[12]),
        )

    def validate_right(self, payload: RightPayload) -> list[str]:
        errors: list[str] = []
        if not any((payload.work_id, payload.track_id, payload.release_id)):
            errors.append("Rights records must link to a work, track, or release.")
        if (
            payload.start_date
            and payload.end_date
            and str(payload.start_date) > str(payload.end_date)
        ):
            errors.append("Rights end date cannot be earlier than the start date.")
        return errors

    def create_right(self, payload: RightPayload) -> int:
        errors = self.validate_right(payload)
        if errors:
            raise ValueError("\n".join(errors))
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO RightsRecords (
                    title,
                    right_type,
                    exclusive_flag,
                    territory,
                    media_use_type,
                    start_date,
                    end_date,
                    perpetual_flag,
                    granted_by_party_id,
                    granted_to_party_id,
                    retained_by_party_id,
                    source_contract_id,
                    work_id,
                    track_id,
                    release_id,
                    notes,
                    profile_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_text(payload.title),
                    self._clean_type(payload.right_type),
                    1 if payload.exclusive_flag else 0,
                    clean_text(payload.territory),
                    clean_text(payload.media_use_type),
                    clean_text(payload.start_date),
                    clean_text(payload.end_date),
                    1 if payload.perpetual_flag else 0,
                    payload.granted_by_party_id,
                    payload.granted_to_party_id,
                    payload.retained_by_party_id,
                    payload.source_contract_id,
                    payload.work_id,
                    payload.track_id,
                    payload.release_id,
                    clean_text(payload.notes),
                    clean_text(payload.profile_name),
                ),
            )
            return int(cursor.lastrowid)

    def update_right(self, right_id: int, payload: RightPayload) -> None:
        errors = self.validate_right(payload)
        if errors:
            raise ValueError("\n".join(errors))
        with self.conn:
            self.conn.execute(
                """
                UPDATE RightsRecords
                SET title=?,
                    right_type=?,
                    exclusive_flag=?,
                    territory=?,
                    media_use_type=?,
                    start_date=?,
                    end_date=?,
                    perpetual_flag=?,
                    granted_by_party_id=?,
                    granted_to_party_id=?,
                    retained_by_party_id=?,
                    source_contract_id=?,
                    work_id=?,
                    track_id=?,
                    release_id=?,
                    notes=?,
                    profile_name=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    clean_text(payload.title),
                    self._clean_type(payload.right_type),
                    1 if payload.exclusive_flag else 0,
                    clean_text(payload.territory),
                    clean_text(payload.media_use_type),
                    clean_text(payload.start_date),
                    clean_text(payload.end_date),
                    1 if payload.perpetual_flag else 0,
                    payload.granted_by_party_id,
                    payload.granted_to_party_id,
                    payload.retained_by_party_id,
                    payload.source_contract_id,
                    payload.work_id,
                    payload.track_id,
                    payload.release_id,
                    clean_text(payload.notes),
                    clean_text(payload.profile_name),
                    int(right_id),
                ),
            )

    def delete_right(self, right_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM RightsRecords WHERE id=?", (int(right_id),))

    def fetch_right(self, right_id: int) -> RightRecord | None:
        rows = self.list_rights(right_id=int(right_id))
        return rows[0] if rows else None

    def list_rights(
        self,
        *,
        search_text: str | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        right_id: int | None = None,
    ) -> list[RightRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if right_id is not None:
            clauses.append("rr.id=?")
            params.append(int(right_id))
        clean_search = clean_text(search_text)
        if clean_search:
            like = f"%{clean_search}%"
            clauses.append(
                """
                (
                    COALESCE(rr.title, '') LIKE ?
                    OR COALESCE(rr.right_type, '') LIKE ?
                    OR COALESCE(rr.territory, '') LIKE ?
                    OR COALESCE(rr.media_use_type, '') LIKE ?
                    OR COALESCE(granted_to.legal_name, '') LIKE ?
                    OR COALESCE(retained_by.legal_name, '') LIKE ?
                    OR COALESCE(c.title, '') LIKE ?
                )
                """
            )
            params.extend([like, like, like, like, like, like, like])
        if entity_type and entity_id is not None:
            column_name = {
                "work": "rr.work_id",
                "track": "rr.track_id",
                "release": "rr.release_id",
            }.get(str(entity_type))
            if column_name:
                clauses.append(f"{column_name}=?")
                params.append(int(entity_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT
                rr.id,
                rr.title,
                rr.right_type,
                rr.exclusive_flag,
                rr.territory,
                rr.media_use_type,
                rr.start_date,
                rr.end_date,
                rr.perpetual_flag,
                rr.granted_by_party_id,
                COALESCE(granted_by.display_name, granted_by.legal_name),
                rr.granted_to_party_id,
                COALESCE(granted_to.display_name, granted_to.legal_name),
                rr.retained_by_party_id,
                COALESCE(retained_by.display_name, retained_by.legal_name),
                rr.source_contract_id,
                c.title,
                rr.work_id,
                rr.track_id,
                rr.release_id,
                rr.notes,
                rr.profile_name,
                rr.created_at,
                rr.updated_at
            FROM RightsRecords rr
            LEFT JOIN Parties granted_by ON granted_by.id = rr.granted_by_party_id
            LEFT JOIN Parties granted_to ON granted_to.id = rr.granted_to_party_id
            LEFT JOIN Parties retained_by ON retained_by.id = rr.retained_by_party_id
            LEFT JOIN Contracts c ON c.id = rr.source_contract_id
            {where}
            ORDER BY rr.right_type, rr.id
            """,
            params,
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def detect_conflicts(self) -> list[RightsConflict]:
        rights = [item for item in self.list_rights() if item.exclusive_flag]
        conflicts: list[RightsConflict] = []
        for index, left in enumerate(rights):
            left_entity = (
                ("work", left.work_id)
                if left.work_id
                else ("track", left.track_id) if left.track_id else ("release", left.release_id)
            )
            for right in rights[index + 1 :]:
                right_entity = (
                    ("work", right.work_id)
                    if right.work_id
                    else (
                        ("track", right.track_id)
                        if right.track_id
                        else ("release", right.release_id)
                    )
                )
                if left_entity != right_entity:
                    continue
                if left.right_type != right.right_type:
                    continue
                left_territory = normalized_territory(left.territory)
                right_territory = normalized_territory(right.territory)
                if left_territory and right_territory and left_territory != right_territory:
                    continue
                if not ranges_overlap(
                    left.start_date,
                    left.end_date,
                    left.perpetual_flag,
                    right.start_date,
                    right.end_date,
                    right.perpetual_flag,
                ):
                    continue
                territory_label = left.territory or right.territory or "Worldwide / unspecified"
                conflicts.append(
                    RightsConflict(
                        left_right_id=left.id,
                        right_right_id=right.id,
                        right_type=left.right_type,
                        territory=territory_label,
                        message=(
                            f"Exclusive {left.right_type.replace('_', ' ')} rights overlap in {territory_label}."
                        ),
                    )
                )
        return conflicts

    def rights_missing_source_contract(self) -> list[RightRecord]:
        return [
            item
            for item in self.list_rights()
            if item.source_contract_id is None
            and (item.exclusive_flag or item.granted_to_party_id is not None)
            and item.right_type != "promotional"
        ]

    def list_ownership_interests(
        self,
        *,
        entity_type: str,
        entity_id: int,
    ) -> list[OwnershipInterestRecord]:
        table_name, entity_column = self._ownership_table_spec(entity_type)
        rows = self.conn.execute(
            f"""
            SELECT
                o.id,
                o.{entity_column},
                o.party_id,
                COALESCE(p.display_name, p.legal_name, o.display_name),
                o.display_name,
                o.ownership_role,
                o.share_percent,
                o.territory,
                o.source_contract_id,
                c.title,
                o.notes,
                o.created_at,
                o.updated_at
            FROM {table_name} o
            LEFT JOIN Parties p ON p.id = o.party_id
            LEFT JOIN Contracts c ON c.id = o.source_contract_id
            WHERE o.{entity_column}=?
            ORDER BY o.id
            """,
            (int(entity_id),),
        ).fetchall()
        return [
            self._row_to_ownership_record(row, entity_type=entity_type)
            for row in rows
        ]

    def list_work_ownership_interests(self, work_id: int) -> list[OwnershipInterestRecord]:
        return self.list_ownership_interests(entity_type="work", entity_id=int(work_id))

    def list_recording_ownership_interests(self, track_id: int) -> list[OwnershipInterestRecord]:
        return self.list_ownership_interests(entity_type="track", entity_id=int(track_id))

    def replace_ownership_interests(
        self,
        *,
        entity_type: str,
        entity_id: int,
        payloads: Iterable[OwnershipInterestPayload],
    ) -> None:
        table_name, entity_column = self._ownership_table_spec(entity_type)
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(f"DELETE FROM {table_name} WHERE {entity_column}=?", (int(entity_id),))
            for payload in payloads:
                display_name = clean_text(payload.name)
                party_id = int(payload.party_id) if payload.party_id is not None else None
                if party_id is None and not display_name:
                    continue
                cur.execute(
                    f"""
                    INSERT INTO {table_name}(
                        {entity_column},
                        party_id,
                        display_name,
                        ownership_role,
                        share_percent,
                        territory,
                        source_contract_id,
                        notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(entity_id),
                        party_id,
                        display_name,
                        self._clean_ownership_role(payload.role, entity_type=entity_type),
                        self._clean_share(payload.share_percent),
                        clean_text(payload.territory),
                        int(payload.source_contract_id)
                        if payload.source_contract_id is not None
                        else None,
                        clean_text(payload.notes),
                    ),
                )

    def replace_work_ownership_interests(
        self, work_id: int, payloads: Iterable[OwnershipInterestPayload]
    ) -> None:
        self.replace_ownership_interests(
            entity_type="work",
            entity_id=int(work_id),
            payloads=payloads,
        )

    def replace_recording_ownership_interests(
        self, track_id: int, payloads: Iterable[OwnershipInterestPayload]
    ) -> None:
        self.replace_ownership_interests(
            entity_type="track",
            entity_id=int(track_id),
            payloads=payloads,
        )

    def _linked_work_id_for_track(self, track_id: int) -> int | None:
        track_columns = self._track_columns()
        if "work_id" in track_columns:
            row = self.conn.execute(
                "SELECT work_id FROM Tracks WHERE id=?",
                (int(track_id),),
            ).fetchone()
            if row and row[0] is not None:
                return int(row[0])
        row = self.conn.execute(
            """
            SELECT work_id
            FROM WorkTrackLinks
            WHERE track_id=?
            ORDER BY is_primary DESC, work_id
            LIMIT 1
            """,
            (int(track_id),),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def ownership_summary(self, *, entity_type: str, entity_id: int) -> OwnershipSummary:
        rights = self.list_rights(entity_type=entity_type, entity_id=entity_id)
        linked_work_id = (
            self._linked_work_id_for_track(entity_id) if entity_type == "track" else None
        )
        master_control = self._dedupe_names(
            item.party_name or item.display_name
            for item in (
                self.list_recording_ownership_interests(entity_id)
                if entity_type == "track"
                else []
            )
        )
        publishing_control = self._dedupe_names(
            item.party_name or item.display_name
            for item in (
                self.list_work_ownership_interests(entity_id)
                if entity_type == "work"
                else (
                    self.list_work_ownership_interests(linked_work_id)
                    if entity_type == "track" and linked_work_id is not None
                    else []
                )
            )
        )
        exclusive_territories: list[str] = []
        for item in rights:
            controller = (
                item.granted_to_name
                or item.retained_by_name
                or item.granted_by_name
                or "Unassigned"
            )
            if item.right_type == "master" and controller not in master_control:
                master_control.append(controller)
            if (
                item.right_type == "composition_publishing"
                and controller not in publishing_control
            ):
                publishing_control.append(controller)
            if item.exclusive_flag:
                territory = item.territory or "Worldwide / unspecified"
                label = f"{territory}: {controller}"
                if label not in exclusive_territories:
                    exclusive_territories.append(label)
        return OwnershipSummary(
            entity_type=entity_type,
            entity_id=int(entity_id),
            master_control=master_control,
            publishing_control=publishing_control,
            exclusive_territories=exclusive_territories,
        )

    def export_rows(self) -> list[dict[str, object]]:
        return [asdict(item) for item in self.list_rights()]

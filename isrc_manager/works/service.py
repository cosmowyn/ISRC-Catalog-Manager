"""CRUD, linking, and validation logic for musical works."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Iterable

from isrc_manager.domain.repertoire import clean_text, clean_text_list, dumps_json, loads_json_list
from isrc_manager.parties import PartyService

from .models import (
    WORK_CREATOR_ROLE_CHOICES,
    WORK_STATUS_CHOICES,
    WorkContributorPayload,
    WorkContributorRecord,
    WorkDetail,
    WorkPayload,
    WorkRecord,
    WorkValidationIssue,
)


class WorkService:
    """Owns first-class composition records and track links."""

    CREATOR_ROLES = frozenset({"songwriter", "composer", "lyricist"})

    def __init__(self, conn: sqlite3.Connection, *, party_service: PartyService | None = None):
        self.conn = conn
        self.party_service = party_service

    @staticmethod
    def _clean_status(value: str | None) -> str | None:
        clean = str(value or "").strip().lower().replace(" ", "_")
        if not clean:
            return None
        if clean not in WORK_STATUS_CHOICES:
            return "blocked" if clean == "blocked" else "metadata_incomplete"
        return clean

    @staticmethod
    def _clean_role(value: str | None) -> str:
        clean = str(value or "songwriter").strip().lower().replace(" ", "_")
        if clean not in WORK_CREATOR_ROLE_CHOICES:
            return "songwriter"
        return clean

    @staticmethod
    def _clean_share(value: float | int | str | None) -> float | None:
        if value in (None, ""):
            return None
        try:
            numeric = round(float(value), 4)
        except Exception:
            return None
        return numeric

    @staticmethod
    def _row_to_record(row) -> WorkRecord:
        return WorkRecord(
            id=int(row[0]),
            title=str(row[1] or ""),
            alternate_titles=loads_json_list(row[2]),
            version_subtitle=clean_text(row[3]),
            language=clean_text(row[4]),
            lyrics_flag=bool(row[5]),
            instrumental_flag=bool(row[6]),
            genre_notes=clean_text(row[7]),
            iswc=clean_text(row[8]),
            registration_number=clean_text(row[9]),
            work_status=clean_text(row[10]),
            metadata_complete=bool(row[11]),
            contract_signed=bool(row[12]),
            rights_verified=bool(row[13]),
            notes=clean_text(row[14]),
            profile_name=clean_text(row[15]),
            created_at=clean_text(row[16]),
            updated_at=clean_text(row[17]),
            track_count=int(row[18] or 0),
            contributor_count=int(row[19] or 0),
        )

    @staticmethod
    def _row_to_contributor(row) -> WorkContributorRecord:
        return WorkContributorRecord(
            id=int(row[0]),
            work_id=int(row[1]),
            party_id=int(row[2]) if row[2] is not None else None,
            display_name=clean_text(row[3]),
            role=str(row[4] or "songwriter"),
            share_percent=float(row[5]) if row[5] is not None else None,
            role_share_percent=float(row[6]) if row[6] is not None else None,
            notes=clean_text(row[7]),
        )

    def _resolve_party_id(
        self,
        contributor: WorkContributorPayload,
        *,
        cursor: sqlite3.Cursor,
    ) -> int | None:
        if contributor.party_id:
            return int(contributor.party_id)
        if self.party_service is None:
            return None
        clean_name = clean_text(contributor.name)
        if not clean_name:
            return None
        party_type = (
            "publisher"
            if self._clean_role(contributor.role) in {"publisher", "subpublisher"}
            else "person"
        )
        return self.party_service.ensure_party_by_name(
            clean_name, party_type=party_type, cursor=cursor
        )

    def _table_names(self, *, cursor: sqlite3.Cursor) -> set[str]:
        return {
            str(row[0])
            for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if row and row[0]
        }

    def _track_columns(self, *, cursor: sqlite3.Cursor) -> set[str]:
        if "Tracks" not in self._table_names(cursor=cursor):
            return set()
        return {
            str(row[1])
            for row in cursor.execute("PRAGMA table_info(Tracks)").fetchall()
            if row and row[1]
        }

    def _normalize_primary_track(self, work_id: int, *, cursor: sqlite3.Cursor) -> None:
        primary_row = cursor.execute(
            """
            SELECT track_id
            FROM WorkTrackLinks
            WHERE work_id=?
            ORDER BY is_primary DESC, track_id
            LIMIT 1
            """,
            (int(work_id),),
        ).fetchone()
        cursor.execute("UPDATE WorkTrackLinks SET is_primary=0 WHERE work_id=?", (int(work_id),))
        if primary_row is not None:
            cursor.execute(
                """
                UPDATE WorkTrackLinks
                SET is_primary=1
                WHERE work_id=? AND track_id=?
                """,
                (int(work_id), int(primary_row[0])),
            )

    def _set_track_governing_work(
        self,
        track_id: int,
        work_id: int | None,
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        track_columns = self._track_columns(cursor=cursor)
        if "work_id" not in track_columns:
            return
        assignments = ["work_id=?"]
        params: list[object] = [int(work_id) if work_id is not None else None]
        if "relationship_type" in track_columns:
            assignments.append(
                "relationship_type=COALESCE(NULLIF(trim(relationship_type), ''), 'original')"
            )
        cursor.execute(
            f"""
            UPDATE Tracks
            SET {", ".join(assignments)}
            WHERE id=?
            """,
            (*params, int(track_id)),
        )

    def validate_work(
        self,
        payload: WorkPayload,
        *,
        work_id: int | None = None,
        cursor: sqlite3.Cursor | None = None,
    ) -> list[WorkValidationIssue]:
        cur = cursor or self.conn.cursor()
        issues: list[WorkValidationIssue] = []
        if not clean_text(payload.title):
            issues.append(WorkValidationIssue("error", "title", "Work title is required."))
        iswc = clean_text(payload.iswc)
        if iswc:
            params: list[object] = [iswc]
            sql = "SELECT id, title FROM Works WHERE iswc=?"
            if work_id is not None:
                sql += " AND id != ?"
                params.append(int(work_id))
            sql += " ORDER BY id LIMIT 1"
            duplicate = cur.execute(sql, params).fetchone()
            if duplicate:
                issues.append(
                    WorkValidationIssue(
                        "warning",
                        "iswc",
                        f"ISWC already exists on work '{duplicate[1]}'.",
                    )
                )

        cleaned_contributors = [
            WorkContributorPayload(
                role=self._clean_role(item.role),
                name=str(clean_text(item.name) or ""),
                share_percent=self._clean_share(item.share_percent),
                role_share_percent=self._clean_share(item.role_share_percent),
                party_id=int(item.party_id) if item.party_id else None,
                notes=clean_text(item.notes),
            )
            for item in payload.contributors
            if clean_text(item.name)
        ]
        if not any(item.role in self.CREATOR_ROLES for item in cleaned_contributors):
            issues.append(
                WorkValidationIssue(
                    "warning",
                    "contributors",
                    "Work does not have a songwriter, composer, or lyricist linked yet.",
                )
            )
        if not cleaned_contributors:
            issues.append(
                WorkValidationIssue(
                    "warning",
                    "contributors",
                    "Work does not have any linked creators or publishers yet.",
                )
            )

        overall_shares = [
            item.share_percent for item in cleaned_contributors if item.share_percent is not None
        ]
        if overall_shares:
            total = round(sum(overall_shares), 4)
            if abs(total - 100.0) > 0.01:
                issues.append(
                    WorkValidationIssue(
                        "error",
                        "share_percent",
                        f"Creator shares add up to {total:.2f}% instead of 100%.",
                    )
                )
        role_totals: dict[str, float] = defaultdict(float)
        role_counts: dict[str, int] = defaultdict(int)
        for item in cleaned_contributors:
            if item.role_share_percent is None:
                continue
            role_totals[item.role] += float(item.role_share_percent)
            role_counts[item.role] += 1
        for role, total in role_totals.items():
            if role_counts[role] and abs(round(total, 4) - 100.0) > 0.01:
                issues.append(
                    WorkValidationIssue(
                        "warning",
                        "role_share_percent",
                        f"{role.replace('_', ' ').title()} role shares add up to {total:.2f}% instead of 100%.",
                    )
                )

        if payload.lyrics_flag and payload.instrumental_flag:
            issues.append(
                WorkValidationIssue(
                    "warning",
                    "instrumental_flag",
                    "Work is marked as both lyrics-based and instrumental.",
                )
            )
        return issues

    def create_work(self, payload: WorkPayload, *, cursor: sqlite3.Cursor | None = None) -> int:
        cur = cursor or self.conn.cursor()
        issues = self.validate_work(payload, cursor=cur)
        errors = [issue.message for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError("\n".join(errors))
        cur.execute(
            """
            INSERT INTO Works (
                title,
                alternate_titles,
                version_subtitle,
                language,
                lyrics_flag,
                instrumental_flag,
                genre_notes,
                iswc,
                registration_number,
                work_status,
                metadata_complete,
                contract_signed,
                rights_verified,
                notes,
                profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(clean_text(payload.title) or ""),
                dumps_json(clean_text_list(payload.alternate_titles)),
                clean_text(payload.version_subtitle),
                clean_text(payload.language),
                1 if payload.lyrics_flag else 0,
                1 if payload.instrumental_flag else 0,
                clean_text(payload.genre_notes),
                clean_text(payload.iswc),
                clean_text(payload.registration_number),
                self._clean_status(payload.work_status),
                1 if payload.metadata_complete else 0,
                1 if payload.contract_signed else 0,
                1 if payload.rights_verified else 0,
                clean_text(payload.notes),
                clean_text(payload.profile_name),
            ),
        )
        work_id = int(cur.lastrowid)
        self._replace_contributors(work_id, payload.contributors, cursor=cur)
        self._replace_track_links(work_id, payload.track_ids, cursor=cur)
        if cursor is None:
            self.conn.commit()
        return work_id

    def update_work(
        self,
        work_id: int,
        payload: WorkPayload,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> None:
        cur = cursor or self.conn.cursor()
        issues = self.validate_work(payload, work_id=int(work_id), cursor=cur)
        errors = [issue.message for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError("\n".join(errors))
        cur.execute(
            """
            UPDATE Works
            SET title=?,
                alternate_titles=?,
                version_subtitle=?,
                language=?,
                lyrics_flag=?,
                instrumental_flag=?,
                genre_notes=?,
                iswc=?,
                registration_number=?,
                work_status=?,
                metadata_complete=?,
                contract_signed=?,
                rights_verified=?,
                notes=?,
                profile_name=?,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                str(clean_text(payload.title) or ""),
                dumps_json(clean_text_list(payload.alternate_titles)),
                clean_text(payload.version_subtitle),
                clean_text(payload.language),
                1 if payload.lyrics_flag else 0,
                1 if payload.instrumental_flag else 0,
                clean_text(payload.genre_notes),
                clean_text(payload.iswc),
                clean_text(payload.registration_number),
                self._clean_status(payload.work_status),
                1 if payload.metadata_complete else 0,
                1 if payload.contract_signed else 0,
                1 if payload.rights_verified else 0,
                clean_text(payload.notes),
                clean_text(payload.profile_name),
                int(work_id),
            ),
        )
        self._replace_contributors(int(work_id), payload.contributors, cursor=cur)
        self._replace_track_links(int(work_id), payload.track_ids, cursor=cur)
        if cursor is None:
            self.conn.commit()

    def delete_work(self, work_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM Works WHERE id=?", (int(work_id),))

    def duplicate_work(self, work_id: int) -> int:
        detail = self.fetch_work_detail(int(work_id))
        if detail is None:
            raise ValueError("Work not found.")
        payload = WorkPayload(
            title=f"{detail.work.title} (Copy)",
            alternate_titles=list(detail.work.alternate_titles),
            version_subtitle=detail.work.version_subtitle,
            language=detail.work.language,
            lyrics_flag=detail.work.lyrics_flag,
            instrumental_flag=detail.work.instrumental_flag,
            genre_notes=detail.work.genre_notes,
            iswc=None,
            registration_number=None,
            work_status=detail.work.work_status,
            metadata_complete=detail.work.metadata_complete,
            contract_signed=detail.work.contract_signed,
            rights_verified=detail.work.rights_verified,
            notes=detail.work.notes,
            profile_name=detail.work.profile_name,
            contributors=[
                WorkContributorPayload(
                    role=item.role,
                    name=str(clean_text(item.display_name) or ""),
                    share_percent=item.share_percent,
                    role_share_percent=item.role_share_percent,
                    party_id=item.party_id,
                    notes=item.notes,
                )
                for item in detail.contributors
            ],
            track_ids=list(detail.track_ids),
        )
        return self.create_work(payload)

    def _replace_contributors(
        self,
        work_id: int,
        contributors: Iterable[WorkContributorPayload],
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        table_names = self._table_names(cursor=cursor)
        cursor.execute("DELETE FROM WorkContributors WHERE work_id=?", (int(work_id),))
        if "WorkContributionEntries" in table_names:
            cursor.execute("DELETE FROM WorkContributionEntries WHERE work_id=?", (int(work_id),))
        for contributor in contributors:
            name = clean_text(contributor.name)
            if not name:
                continue
            party_id = self._resolve_party_id(contributor, cursor=cursor)
            clean_role = self._clean_role(contributor.role)
            clean_share = self._clean_share(contributor.share_percent)
            clean_role_share = self._clean_share(contributor.role_share_percent)
            clean_notes = clean_text(contributor.notes)
            cursor.execute(
                """
                INSERT INTO WorkContributors(
                    work_id,
                    party_id,
                    display_name,
                    role,
                    share_percent,
                    role_share_percent,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(work_id),
                    party_id,
                    name,
                    clean_role,
                    clean_share,
                    clean_role_share,
                    clean_notes,
                ),
            )
            if "WorkContributionEntries" in table_names:
                cursor.execute(
                    """
                    INSERT INTO WorkContributionEntries(
                        work_id,
                        party_id,
                        display_name,
                        role,
                        share_percent,
                        role_share_percent,
                        notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(work_id),
                        party_id,
                        name,
                        clean_role,
                        clean_share,
                        clean_role_share,
                        clean_notes,
                    ),
                )

    def _replace_track_links(
        self,
        work_id: int,
        track_ids: Iterable[int],
        *,
        cursor: sqlite3.Cursor,
    ) -> None:
        clean_track_ids: list[int] = []
        for raw_track_id in track_ids:
            try:
                track_id = int(raw_track_id)
            except Exception:
                continue
            if track_id > 0 and track_id not in clean_track_ids:
                clean_track_ids.append(track_id)
        existing_rows = cursor.execute(
            "SELECT track_id FROM WorkTrackLinks WHERE work_id=? ORDER BY is_primary DESC, track_id",
            (int(work_id),),
        ).fetchall()
        existing_track_ids = {int(row[0]) for row in existing_rows if row and row[0] is not None}
        for track_id in sorted(existing_track_ids - set(clean_track_ids)):
            self._set_track_governing_work(track_id, None, cursor=cursor)
        affected_work_ids = {int(work_id)}
        for track_id in clean_track_ids:
            previous_work_rows = cursor.execute(
                "SELECT work_id FROM WorkTrackLinks WHERE track_id=?",
                (int(track_id),),
            ).fetchall()
            affected_work_ids.update(
                int(row[0]) for row in previous_work_rows if row and row[0] is not None
            )
            self._set_track_governing_work(track_id, int(work_id), cursor=cursor)
        cursor.execute("DELETE FROM WorkTrackLinks WHERE work_id=?", (int(work_id),))
        if clean_track_ids:
            cursor.executemany(
                "DELETE FROM WorkTrackLinks WHERE track_id=? AND work_id!=?",
                [(int(track_id), int(work_id)) for track_id in clean_track_ids],
            )
        for position, track_id in enumerate(clean_track_ids):
            cursor.execute(
                """
                INSERT INTO WorkTrackLinks(work_id, track_id, is_primary)
                VALUES (?, ?, ?)
                """,
                (int(work_id), track_id, 1 if position == 0 else 0),
            )
        for affected_work_id in sorted(affected_work_ids):
            self._normalize_primary_track(affected_work_id, cursor=cursor)

    def fetch_work(self, work_id: int) -> WorkRecord | None:
        row = self.conn.execute(
            """
            SELECT
                w.id,
                w.title,
                w.alternate_titles,
                w.version_subtitle,
                w.language,
                w.lyrics_flag,
                w.instrumental_flag,
                w.genre_notes,
                w.iswc,
                w.registration_number,
                w.work_status,
                w.metadata_complete,
                w.contract_signed,
                w.rights_verified,
                w.notes,
                w.profile_name,
                w.created_at,
                w.updated_at,
                COUNT(DISTINCT wt.track_id) AS track_count,
                COUNT(DISTINCT wc.id) AS contributor_count
            FROM Works w
            LEFT JOIN WorkTrackLinks wt ON wt.work_id = w.id
            LEFT JOIN WorkContributors wc ON wc.work_id = w.id
            WHERE w.id=?
            GROUP BY w.id
            """,
            (int(work_id),),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def fetch_work_detail(self, work_id: int) -> WorkDetail | None:
        work = self.fetch_work(int(work_id))
        if work is None:
            return None
        contributor_rows = self.conn.execute(
            """
            SELECT
                wc.id,
                wc.work_id,
                wc.party_id,
                COALESCE(p.display_name, p.legal_name, wc.display_name),
                wc.role,
                wc.share_percent,
                wc.role_share_percent,
                wc.notes
            FROM WorkContributors wc
            LEFT JOIN Parties p ON p.id = wc.party_id
            WHERE wc.work_id=?
            ORDER BY wc.id
            """,
            (int(work_id),),
        ).fetchall()
        track_rows = self.conn.execute(
            """
            SELECT track_id
            FROM WorkTrackLinks
            WHERE work_id=?
            ORDER BY is_primary DESC, track_id
            """,
            (int(work_id),),
        ).fetchall()
        return WorkDetail(
            work=work,
            contributors=[self._row_to_contributor(row) for row in contributor_rows],
            track_ids=[int(row[0]) for row in track_rows],
        )

    def list_works(
        self,
        *,
        search_text: str | None = None,
        status: str | None = None,
        linked_track_id: int | None = None,
    ) -> list[WorkRecord]:
        clauses: list[str] = []
        params: list[object] = []
        clean_search = clean_text(search_text)
        if clean_search:
            like = f"%{clean_search}%"
            clauses.append(
                """
                (
                    w.title LIKE ?
                    OR COALESCE(w.version_subtitle, '') LIKE ?
                    OR COALESCE(w.iswc, '') LIKE ?
                    OR COALESCE(w.registration_number, '') LIKE ?
                    OR COALESCE(w.alternate_titles, '') LIKE ?
                )
                """
            )
            params.extend([like, like, like, like, like])
        clean_status = self._clean_status(status)
        if clean_status:
            clauses.append("COALESCE(w.work_status, '')=?")
            params.append(clean_status)
        if linked_track_id is not None:
            clauses.append(
                "EXISTS (SELECT 1 FROM WorkTrackLinks wt2 WHERE wt2.work_id=w.id AND wt2.track_id=?)"
            )
            params.append(int(linked_track_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT
                w.id,
                w.title,
                w.alternate_titles,
                w.version_subtitle,
                w.language,
                w.lyrics_flag,
                w.instrumental_flag,
                w.genre_notes,
                w.iswc,
                w.registration_number,
                w.work_status,
                w.metadata_complete,
                w.contract_signed,
                w.rights_verified,
                w.notes,
                w.profile_name,
                w.created_at,
                w.updated_at,
                COUNT(DISTINCT wt.track_id) AS track_count,
                COUNT(DISTINCT wc.id) AS contributor_count
            FROM Works w
            LEFT JOIN WorkTrackLinks wt ON wt.work_id = w.id
            LEFT JOIN WorkContributors wc ON wc.work_id = w.id
            {where}
            GROUP BY w.id
            ORDER BY w.title, w.id
            """,
            params,
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_works_for_track(self, track_id: int) -> list[WorkRecord]:
        return self.list_works(linked_track_id=int(track_id))

    def link_tracks_to_work(self, work_id: int, track_ids: Iterable[int]) -> None:
        with self.conn:
            cur = self.conn.cursor()
            existing = {
                int(row[0])
                for row in cur.execute(
                    "SELECT track_id FROM WorkTrackLinks WHERE work_id=?",
                    (int(work_id),),
                ).fetchall()
            }
            affected_work_ids = {int(work_id)}
            is_first = not existing
            for raw_track_id in track_ids:
                try:
                    track_id = int(raw_track_id)
                except Exception:
                    continue
                if track_id <= 0 or track_id in existing:
                    continue
                previous_work_rows = cur.execute(
                    "SELECT work_id FROM WorkTrackLinks WHERE track_id=?",
                    (track_id,),
                ).fetchall()
                affected_work_ids.update(
                    int(row[0]) for row in previous_work_rows if row and row[0] is not None
                )
                self._set_track_governing_work(track_id, int(work_id), cursor=cur)
                cur.execute(
                    "DELETE FROM WorkTrackLinks WHERE track_id=? AND work_id!=?",
                    (track_id, int(work_id)),
                )
                cur.execute(
                    """
                    INSERT INTO WorkTrackLinks(work_id, track_id, is_primary)
                    VALUES (?, ?, ?)
                    """,
                    (int(work_id), track_id, 1 if is_first else 0),
                )
                existing.add(track_id)
                is_first = False
            for affected_work_id in sorted(affected_work_ids):
                self._normalize_primary_track(affected_work_id, cursor=cur)

    def unlink_track(self, work_id: int, track_id: int) -> None:
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                "DELETE FROM WorkTrackLinks WHERE work_id=? AND track_id=?",
                (int(work_id), int(track_id)),
            )
            self._set_track_governing_work(int(track_id), None, cursor=cur)
            self._normalize_primary_track(int(work_id), cursor=cur)

    def export_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for work in self.list_works():
            detail = self.fetch_work_detail(work.id)
            if detail is None:
                continue
            payload = work.to_dict()
            payload["contributors"] = [
                {
                    "party_id": contributor.party_id,
                    "display_name": contributor.display_name,
                    "role": contributor.role,
                    "share_percent": contributor.share_percent,
                    "role_share_percent": contributor.role_share_percent,
                    "notes": contributor.notes,
                }
                for contributor in detail.contributors
            ]
            payload["track_ids"] = list(detail.track_ids)
            rows.append(payload)
        return rows

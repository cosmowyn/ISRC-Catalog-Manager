"""Operational repertoire workflow helpers for works, tracks, and releases."""

from __future__ import annotations

import sqlite3
from collections import Counter

from isrc_manager.domain.repertoire import clean_text

REPERTOIRE_STATUS_CHOICES = (
    "idea",
    "demo",
    "in_production",
    "final_master_received",
    "metadata_incomplete",
    "contract_pending",
    "contract_signed",
    "rights_verified",
    "cleared",
    "blocked",
    "archived",
)


class RepertoireWorkflowService:
    """Applies and summarizes workflow states across repertoire entities."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _clean_status(value: str | None) -> str | None:
        clean = str(value or "").strip().lower().replace(" ", "_")
        if not clean:
            return None
        if clean not in REPERTOIRE_STATUS_CHOICES:
            return "metadata_incomplete"
        return clean

    def _bulk_update(
        self,
        table_name: str,
        row_ids: list[int],
        *,
        status: str | None = None,
        metadata_complete: bool | None = None,
        contract_signed: bool | None = None,
        rights_verified: bool | None = None,
    ) -> int:
        clean_ids = sorted({int(item) for item in row_ids if int(item) > 0})
        if not clean_ids:
            return 0
        status_column = "work_status" if table_name == "Works" else "repertoire_status"
        assignments: list[str] = []
        params: list[object] = []
        if status is not None:
            assignments.append(f"{status_column}=?")
            params.append(self._clean_status(status))
        if metadata_complete is not None:
            assignments.append("metadata_complete=?")
            params.append(1 if metadata_complete else 0)
        if contract_signed is not None:
            assignments.append("contract_signed=?")
            params.append(1 if contract_signed else 0)
        if rights_verified is not None:
            assignments.append("rights_verified=?")
            params.append(1 if rights_verified else 0)
        if not assignments:
            return 0
        placeholders = ",".join("?" for _ in clean_ids)
        with self.conn:
            self.conn.execute(
                f"UPDATE {table_name} SET {', '.join(assignments)} WHERE id IN ({placeholders})",
                params + clean_ids,
            )
        return len(clean_ids)

    def set_work_status(self, work_ids: list[int], **kwargs) -> int:
        return self._bulk_update("Works", work_ids, **kwargs)

    def set_track_status(self, track_ids: list[int], **kwargs) -> int:
        return self._bulk_update("Tracks", track_ids, **kwargs)

    def set_release_status(self, release_ids: list[int], **kwargs) -> int:
        return self._bulk_update("Releases", release_ids, **kwargs)

    def readiness_snapshot(self, entity_type: str, entity_id: int) -> dict[str, object]:
        entity_type = str(entity_type).strip().lower()
        entity_id = int(entity_id)
        if entity_type == "work":
            row = self.conn.execute(
                """
                SELECT metadata_complete, contract_signed, rights_verified
                FROM Works
                WHERE id=?
                """,
                (entity_id,),
            ).fetchone()
            creator_count = self.conn.execute(
                "SELECT COUNT(*) FROM WorkContributors WHERE work_id=?",
                (entity_id,),
            ).fetchone()
            return {
                "metadata_complete": bool(row[0]) if row else False,
                "contract_signed": bool(row[1]) if row else False,
                "rights_verified": bool(row[2]) if row else False,
                "creator_linked": bool(creator_count and creator_count[0]),
            }
        if entity_type == "track":
            row = self.conn.execute(
                """
                SELECT
                    metadata_complete,
                    contract_signed,
                    rights_verified,
                    (COALESCE(audio_file_path, '') != '' OR audio_file_blob IS NOT NULL)
                FROM Tracks
                WHERE id=?
                """,
                (entity_id,),
            ).fetchone()
            work_count = self.conn.execute(
                "SELECT COUNT(*) FROM WorkTrackLinks WHERE track_id=?",
                (entity_id,),
            ).fetchone()
            return {
                "metadata_complete": bool(row[0]) if row else False,
                "contract_signed": bool(row[1]) if row else False,
                "rights_verified": bool(row[2]) if row else False,
                "audio_attached": bool(row[3]) if row else False,
                "work_linked": bool(work_count and work_count[0]),
            }
        if entity_type == "release":
            row = self.conn.execute(
                """
                SELECT
                    metadata_complete,
                    contract_signed,
                    rights_verified,
                    (COALESCE(artwork_path, '') != '' OR artwork_blob IS NOT NULL)
                FROM Releases
                WHERE id=?
                """,
                (entity_id,),
            ).fetchone()
            track_count = self.conn.execute(
                "SELECT COUNT(*) FROM ReleaseTracks WHERE release_id=?",
                (entity_id,),
            ).fetchone()
            return {
                "metadata_complete": bool(row[0]) if row else False,
                "contract_signed": bool(row[1]) if row else False,
                "rights_verified": bool(row[2]) if row else False,
                "artwork_present": bool(row[3]) if row else False,
                "has_tracks": bool(track_count and track_count[0]),
            }
        return {}

    def summary_counts(self) -> dict[str, dict[str, int]]:
        summary: dict[str, dict[str, int]] = {}
        for entity_type, table_name, status_column in (
            ("works", "Works", "work_status"),
            ("tracks", "Tracks", "repertoire_status"),
            ("releases", "Releases", "repertoire_status"),
        ):
            rows = self.conn.execute(
                f"SELECT COALESCE({status_column}, '') FROM {table_name}"
            ).fetchall()
            counter = Counter(clean_text(row[0]) or "unspecified" for row in rows)
            summary[entity_type] = dict(counter)
        return summary

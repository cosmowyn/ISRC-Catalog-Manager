"""Shared import-governance helpers for catalog import services."""

from __future__ import annotations

import re
import sqlite3

from isrc_manager.domain.repertoire import clean_text
from isrc_manager.parties import PartyRecord, PartyService
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService

_CONTRIBUTOR_SPLIT_RE = re.compile(r"[;,]")


class GovernedImportCoordinator:
    """Normalizes imported identity and guarantees per-track work governance."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        party_service: PartyService | None = None,
        work_service: WorkService | None = None,
        profile_name: str | None = None,
    ) -> None:
        self.conn = conn
        self.party_service = party_service or PartyService(conn)
        self.work_service = work_service or WorkService(conn, party_service=self.party_service)
        self.profile_name = clean_text(profile_name)

    @staticmethod
    def _artist_party_primary_label(record: PartyRecord) -> str:
        return (
            str(record.artist_name or "").strip()
            or str(record.display_name or "").strip()
            or str(record.company_name or "").strip()
            or str(record.legal_name or "").strip()
            or f"Party #{int(record.id)}"
        )

    @staticmethod
    def _split_names(value: str | None) -> list[str]:
        parts = [clean_text(part) for part in _CONTRIBUTOR_SPLIT_RE.split(str(value or ""))]
        return [str(part) for part in parts if part]

    def resolve_party_backed_artist_name(
        self,
        raw_name: str,
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> str:
        clean_name = str(raw_name or "").strip()
        if not clean_name:
            return ""
        party_id = int(
            self.party_service.ensure_party_by_name(
                clean_name,
                party_type="artist",
                cursor=cursor,
            )
        )
        record = self.party_service.fetch_party(party_id)
        if record is None:
            return clean_name
        return self._artist_party_primary_label(record)

    def resolve_party_backed_additional_artist_names(
        self,
        names: list[str],
        *,
        cursor: sqlite3.Cursor | None = None,
    ) -> list[str]:
        resolved: list[str] = []
        seen: set[str] = set()
        for raw_name in names:
            clean_name = self.resolve_party_backed_artist_name(raw_name, cursor=cursor)
            normalized = clean_name.casefold()
            if not clean_name or normalized in seen:
                continue
            seen.add(normalized)
            resolved.append(clean_name)
        return resolved

    def _find_existing_work_id(
        self,
        *,
        work_title: str,
        iswc: str | None,
        registration_number: str | None,
        cursor: sqlite3.Cursor,
    ) -> int | None:
        clean_iswc = str(iswc or "").strip()
        if clean_iswc:
            rows = cursor.execute(
                """
                SELECT id
                FROM Works
                WHERE lower(coalesce(iswc, '')) = lower(?)
                ORDER BY id
                LIMIT 2
                """,
                (clean_iswc,),
            ).fetchall()
            if len(rows) == 1:
                return int(rows[0][0])
            if len(rows) > 1:
                return None

        clean_title = str(work_title or "").strip()
        clean_registration = str(registration_number or "").strip()
        if clean_title and clean_registration:
            rows = cursor.execute(
                """
                SELECT id
                FROM Works
                WHERE lower(title) = lower(?)
                  AND lower(coalesce(registration_number, '')) = lower(?)
                ORDER BY id
                LIMIT 2
                """,
                (clean_title, clean_registration),
            ).fetchall()
            if len(rows) == 1:
                return int(rows[0][0])
        return None

    @staticmethod
    def _work_cache_key(
        *,
        work_title: str,
        iswc: str | None,
        registration_number: str | None,
    ) -> str | None:
        clean_iswc = str(iswc or "").strip().casefold()
        if clean_iswc:
            return f"iswc:{clean_iswc}"
        clean_title = str(work_title or "").strip().casefold()
        clean_registration = str(registration_number or "").strip().casefold()
        if clean_title and clean_registration:
            return f"title+registration:{clean_title}|{clean_registration}"
        return None

    def _work_contributors_from_import(
        self,
        *,
        composer: str | None,
        publisher: str | None,
    ) -> list[WorkContributorPayload]:
        contributors: list[WorkContributorPayload] = []
        for name in self._split_names(composer):
            contributors.append(WorkContributorPayload(role="composer", name=name))
        for name in self._split_names(publisher):
            contributors.append(WorkContributorPayload(role="publisher", name=name))
        return contributors

    def ensure_governed_work_id(
        self,
        *,
        track_title: str,
        iswc: str | None,
        registration_number: str | None,
        composer: str | None,
        publisher: str | None,
        cursor: sqlite3.Cursor,
        batch_cache: dict[str, int],
        work_title: str | None = None,
        existing_work_id: int | None = None,
    ) -> int:
        if existing_work_id is not None:
            return int(existing_work_id)

        resolved_work_title = str(work_title or track_title or "").strip()
        existing_match = self._find_existing_work_id(
            work_title=resolved_work_title,
            iswc=iswc,
            registration_number=registration_number,
            cursor=cursor,
        )
        cache_key = self._work_cache_key(
            work_title=resolved_work_title,
            iswc=iswc,
            registration_number=registration_number,
        )
        if existing_match is not None:
            if cache_key:
                batch_cache[cache_key] = int(existing_match)
            return int(existing_match)
        if cache_key and cache_key in batch_cache:
            return int(batch_cache[cache_key])

        work_payload = WorkPayload(
            title=resolved_work_title,
            iswc=str(iswc or "").strip() or None,
            registration_number=str(registration_number or "").strip() or None,
            profile_name=self.profile_name,
            contributors=self._work_contributors_from_import(
                composer=composer,
                publisher=publisher,
            ),
        )
        work_id = int(self.work_service.create_work(work_payload, cursor=cursor))
        if cache_key:
            batch_cache[cache_key] = work_id
        return work_id

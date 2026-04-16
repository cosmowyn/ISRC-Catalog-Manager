"""Shared governed track-creation helpers for catalog creation and import services."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from isrc_manager.domain.repertoire import clean_text
from isrc_manager.parties import PartyRecord, PartyService
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService

_CONTRIBUTOR_SPLIT_RE = re.compile(r"[;,]")

if TYPE_CHECKING:
    from .tracks import TrackCreatePayload, TrackService


@dataclass(slots=True)
class GovernedWorkResolution:
    work_id: int
    created_work_id: int | None = None


@dataclass(slots=True)
class GovernedTrackCreateResult:
    track_id: int
    work_id: int
    created_work_id: int | None = None


class GovernedImportCoordinator:
    """Normalizes identity and guarantees per-track work governance."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        track_service: TrackService | None = None,
        party_service: PartyService | None = None,
        work_service: WorkService | None = None,
        profile_name: str | None = None,
    ) -> None:
        self.conn = conn
        self.track_service = track_service
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

    @staticmethod
    def _normalize_governance_mode(value: str | None) -> str:
        clean = str(value or "").strip().lower().replace(" ", "_")
        if clean in {"link_existing_work", "create_new_work", "match_or_create_work"}:
            return clean
        return "create_new_work"

    def build_work_payload_from_track(
        self,
        payload: TrackCreatePayload,
        *,
        profile_name: str | None = None,
        work_title: str | None = None,
    ) -> WorkPayload:
        return WorkPayload(
            title=str(work_title or payload.track_title or "").strip(),
            lyrics_flag=bool(str(payload.lyrics or "").strip()),
            genre_notes=str(payload.genre or "").strip() or None,
            iswc=str(payload.iswc or "").strip() or None,
            registration_number=str(payload.buma_work_number or "").strip() or None,
            notes=str(payload.comments or "").strip() or None,
            profile_name=clean_text(profile_name) or self.profile_name,
            contributors=self._work_contributors_from_import(
                composer=payload.composer,
                publisher=payload.publisher,
            ),
        )

    def _work_exists(self, work_id: int, *, cursor: sqlite3.Cursor) -> bool:
        row = cursor.execute("SELECT 1 FROM Works WHERE id=? LIMIT 1", (int(work_id),)).fetchone()
        return row is not None

    def resolve_governed_work(
        self,
        *,
        payload: TrackCreatePayload,
        cursor: sqlite3.Cursor,
        batch_cache: dict[str, int] | None = None,
        governance_mode: str | None = None,
        work_title: str | None = None,
        profile_name: str | None = None,
    ) -> GovernedWorkResolution:
        mode = self._normalize_governance_mode(
            governance_mode or getattr(payload, "governance_mode", None)
        )
        existing_work_id = int(payload.work_id) if payload.work_id is not None else None
        if existing_work_id is not None:
            if not self._work_exists(existing_work_id, cursor=cursor):
                raise ValueError(f"Work {existing_work_id} was not found.")
            return GovernedWorkResolution(work_id=existing_work_id, created_work_id=None)
        if mode == "link_existing_work":
            raise ValueError("Track creation requires an existing Work selection.")
        if mode == "match_or_create_work":
            return self.resolve_governed_work_id(
                track_title=payload.track_title,
                iswc=payload.iswc,
                registration_number=payload.buma_work_number,
                composer=payload.composer,
                publisher=payload.publisher,
                cursor=cursor,
                batch_cache=batch_cache or {},
                work_title=work_title,
                allow_existing_match=True,
            )

        work_payload = self.build_work_payload_from_track(
            payload,
            profile_name=profile_name,
            work_title=work_title,
        )
        work_id = int(self.work_service.create_work(work_payload, cursor=cursor))
        return GovernedWorkResolution(work_id=work_id, created_work_id=work_id)

    def create_governed_track(
        self,
        payload: TrackCreatePayload,
        *,
        cursor: sqlite3.Cursor | None = None,
        batch_cache: dict[str, int] | None = None,
        governance_mode: str | None = None,
        work_title: str | None = None,
        profile_name: str | None = None,
    ) -> GovernedTrackCreateResult:
        if self.track_service is None:
            raise ValueError("Governed track creation requires a TrackService.")
        effective_mode = self._normalize_governance_mode(
            governance_mode or getattr(payload, "governance_mode", None)
        )

        def _create(cur: sqlite3.Cursor) -> GovernedTrackCreateResult:
            payload.artist_name = self.resolve_party_backed_artist_name(
                payload.artist_name,
                cursor=cur,
            )
            payload.additional_artists = self.resolve_party_backed_additional_artist_names(
                list(payload.additional_artists),
                cursor=cur,
            )
            resolution = self.resolve_governed_work(
                payload=payload,
                cursor=cur,
                batch_cache=batch_cache,
                governance_mode=effective_mode,
                work_title=work_title,
                profile_name=profile_name,
            )
            payload.work_id = int(resolution.work_id)
            if resolution.created_work_id is not None:
                payload.parent_track_id = None
                payload.relationship_type = "original"
            track_id = int(self.track_service.create_track(payload, cursor=cur))
            return GovernedTrackCreateResult(
                track_id=track_id,
                work_id=int(payload.work_id),
                created_work_id=resolution.created_work_id,
            )

        if cursor is not None:
            return _create(cursor)
        with self.conn:
            return _create(self.conn.cursor())

    def create_governed_tracks_batch(
        self,
        payloads: list[TrackCreatePayload],
        *,
        cursor: sqlite3.Cursor | None = None,
        profile_name: str | None = None,
        progress_callback=None,
    ) -> list[GovernedTrackCreateResult]:
        batch_cache: dict[str, int] = {}

        def _create(cur: sqlite3.Cursor) -> list[GovernedTrackCreateResult]:
            total = max(1, len(payloads))
            results: list[GovernedTrackCreateResult] = []
            for index, payload in enumerate(payloads, start=1):
                if callable(progress_callback):
                    progress_callback(
                        index - 1,
                        total,
                        f"Creating album track {index} of {total}...",
                    )
                results.append(
                    self.create_governed_track(
                    payload,
                    cursor=cur,
                    batch_cache=batch_cache,
                    profile_name=profile_name,
                    )
                )
                if callable(progress_callback):
                    progress_callback(
                        index,
                        total,
                        f"Created album track {index} of {total}.",
                    )
            return results

        if cursor is not None:
            return _create(cursor)
        with self.conn:
            return _create(self.conn.cursor())

    def resolve_governed_work_id(
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
        allow_existing_match: bool = True,
    ) -> GovernedWorkResolution:
        if existing_work_id is not None:
            if not self._work_exists(int(existing_work_id), cursor=cursor):
                raise ValueError(f"Work {int(existing_work_id)} was not found.")
            return GovernedWorkResolution(work_id=int(existing_work_id), created_work_id=None)

        resolved_work_title = str(work_title or track_title or "").strip()
        cache_key = self._work_cache_key(
            work_title=resolved_work_title,
            iswc=iswc,
            registration_number=registration_number,
        )
        if allow_existing_match:
            existing_match = self._find_existing_work_id(
                work_title=resolved_work_title,
                iswc=iswc,
                registration_number=registration_number,
                cursor=cursor,
            )
            if existing_match is not None:
                if cache_key:
                    batch_cache[cache_key] = int(existing_match)
                return GovernedWorkResolution(work_id=int(existing_match), created_work_id=None)
            if cache_key and cache_key in batch_cache:
                return GovernedWorkResolution(
                    work_id=int(batch_cache[cache_key]),
                    created_work_id=None,
                )

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
        return GovernedWorkResolution(work_id=work_id, created_work_id=work_id)

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
        allow_existing_match: bool = True,
    ) -> int:
        return self.resolve_governed_work_id(
            track_title=track_title,
            iswc=iswc,
            registration_number=registration_number,
            composer=composer,
            publisher=publisher,
            cursor=cursor,
            batch_cache=batch_cache,
            work_title=work_title,
            existing_work_id=existing_work_id,
            allow_existing_match=allow_existing_match,
        ).work_id

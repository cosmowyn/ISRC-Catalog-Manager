"""Deterministic data fixtures for UI PQ scenarios."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from isrc_manager.contracts import ContractPartyPayload, ContractPayload, ContractService
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.rights import RightPayload, RightsService
from isrc_manager.services import TrackCreatePayload, TrackService
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService


@dataclass(slots=True)
class QARepertoireIds:
    track_id: int
    party_id: int
    work_id: int
    release_id: int
    contract_id: int
    right_id: int


def create_qa_track(conn: sqlite3.Connection) -> int:
    return TrackService(conn).create_track(
        TrackCreatePayload(
            isrc="NL-QAA-26-00001",
            track_title="UI PQ Qualification Track",
            artist_name="UI PQ Artist",
            additional_artists=[],
            album_title="UI PQ Release",
            release_date="2026-05-31",
            track_length_sec=181,
            iswc=None,
            upc=None,
            genre="Qualification",
        )
    )


def create_qa_repertoire(conn: sqlite3.Connection, *, track_id: int) -> QARepertoireIds:
    party_service = PartyService(conn)
    party_id = party_service.create_party(
        PartyPayload(
            legal_name="UI PQ Rights Holder BV",
            display_name="UI PQ Rights Holder",
            party_type="publisher",
            email="ui-pq@example.test",
        )
    )
    work_id = WorkService(conn, party_service=party_service).create_work(
        WorkPayload(
            title="UI PQ Qualification Work",
            iswc="T-000.000.001-0",
            metadata_complete=True,
            contract_signed=True,
            rights_verified=True,
            contributors=[
                WorkContributorPayload(
                    role="composer",
                    name="UI PQ Writer",
                    share_percent=100.0,
                    party_id=party_id,
                )
            ],
            track_ids=[track_id],
        )
    )
    release_id = ReleaseService(conn).create_release(
        ReleasePayload(
            title="UI PQ Release",
            primary_artist="UI PQ Artist",
            release_type="single",
            release_date="2026-05-31",
            metadata_complete=True,
            contract_signed=True,
            rights_verified=True,
            placements=[ReleaseTrackPlacement(track_id=track_id, track_number=1)],
        )
    )
    contract_id = ContractService(conn, party_service=party_service).create_contract(
        ContractPayload(
            title="UI PQ License Agreement",
            contract_type="license",
            status="active",
            parties=[
                ContractPartyPayload(
                    party_id=party_id,
                    role_label="rights_holder",
                    is_primary=True,
                )
            ],
            work_ids=[work_id],
            track_ids=[track_id],
            release_ids=[release_id],
        )
    )
    right_id = RightsService(conn).create_right(
        RightPayload(
            title="UI PQ Digital Grant",
            right_type="digital",
            exclusive_flag=False,
            territory="Worldwide",
            granted_to_party_id=party_id,
            source_contract_id=contract_id,
            work_id=work_id,
            track_id=track_id,
            release_id=release_id,
        )
    )
    return QARepertoireIds(
        track_id=track_id,
        party_id=party_id,
        work_id=work_id,
        release_id=release_id,
        contract_id=contract_id,
        right_id=right_id,
    )

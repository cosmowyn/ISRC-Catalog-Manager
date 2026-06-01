import sqlite3

import pytest

from isrc_manager.contracts import ContractPartyPayload, ContractPayload, ContractService
from isrc_manager.invoicing import (
    ContractRoyaltyTermPayload,
    RoyaltyIntegrationService,
    RoyaltySourceEventPayload,
    RoyaltyTermScopePayload,
)
from isrc_manager.invoicing.royalty_integration import (
    ContractRoyaltyTermRecord,
    RoyaltyReadinessIssue,
    RoyaltySourceEventRecord,
    RoyaltyTermScopeRecord,
)
from isrc_manager.invoicing.royalty_service import RoyaltyAccountingService
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.rights import OwnershipInterestPayload, RightPayload, RightsService
from isrc_manager.services import DatabaseSchemaService
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    schema = DatabaseSchemaService(conn)
    schema.init_db()
    schema.migrate_schema()
    return conn


def _party(conn: sqlite3.Connection, name: str, *, party_type: str = "person") -> int:
    return PartyService(conn).create_party(
        PartyPayload(
            legal_name=name,
            display_name=name,
            artist_name=name if party_type == "artist" else None,
            party_type=party_type,
        )
    )


def _integrated_contract_fixture(conn: sqlite3.Connection) -> tuple[int, int, int, int]:
    party_service = PartyService(conn)
    writer_id = _party(conn, "Integrated Writer")
    publisher_id = _party(conn, "Integrated Publisher", party_type="publisher")
    work_id = WorkService(conn, party_service=party_service).create_work(
        WorkPayload(
            title="Integrated Work",
            metadata_complete=True,
            contract_signed=True,
            rights_verified=True,
            contributors=[
                WorkContributorPayload(
                    role="composer",
                    name="Integrated Writer",
                    share_percent=100.0,
                    party_id=writer_id,
                )
            ],
        )
    )
    contract_id = ContractService(conn, party_service=party_service).create_contract(
        ContractPayload(
            title="Integrated Publishing Agreement",
            contract_type="publishing",
            status="active",
            parties=[
                ContractPartyPayload(
                    party_id=writer_id,
                    role_label="writer",
                    is_primary=True,
                )
            ],
            work_ids=[work_id],
        )
    )
    rights = RightsService(conn)
    right_id = rights.create_right(
        RightPayload(
            title="Publishing grant",
            right_type="composition_publishing",
            exclusive_flag=True,
            territory="Worldwide",
            perpetual_flag=True,
            granted_to_party_id=publisher_id,
            source_contract_id=contract_id,
            work_id=work_id,
        )
    )
    rights.replace_work_ownership_interests(
        work_id,
        [
            OwnershipInterestPayload(
                role="publisher",
                party_id=publisher_id,
                share_percent=100.0,
                territory="Worldwide",
                source_contract_id=contract_id,
            )
        ],
    )
    return contract_id, work_id, publisher_id, right_id


def test_royalty_integration_schema_is_available():
    conn = _connection()

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    royalty_calculation_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(RoyaltyCalculations)").fetchall()
    }
    royalty_line_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(RoyaltyCalculationLines)").fetchall()
    }

    assert {
        "ContractRoyaltyTerms",
        "ContractRoyaltyTermScopes",
        "RoyaltySourceEvents",
        "RoyaltyCalculationSourceLinks",
    } <= tables
    assert {"contract_id", "context_snapshot_json"} <= royalty_calculation_columns
    assert {
        "contract_id",
        "work_id",
        "right_id",
        "contract_royalty_term_id",
        "source_event_id",
    } <= royalty_line_columns

    conn.close()


def test_contract_royalty_context_builds_from_works_rights_terms_and_source_events():
    conn = _connection()
    contract_id, work_id, publisher_id, right_id = _integrated_contract_fixture(conn)
    service = RoyaltyIntegrationService(conn)
    term = service.create_contract_royalty_term(
        ContractRoyaltyTermPayload(
            contract_id=contract_id,
            party_id=publisher_id,
            right_type="composition_publishing",
            royalty_basis="net",
            rate_basis_points=1_500,
            territory="Worldwide",
        ),
        scopes=(RoyaltyTermScopePayload("work", work_id),),
    )
    event = service.record_source_event(
        RoyaltySourceEventPayload(
            contract_id=contract_id,
            work_id=work_id,
            source_type="statement",
            source_id="DSP-2026-01",
            description="DSP statement January",
            period_start="2026-01-01",
            period_end="2026-01-31",
            gross_amount_minor=12_000,
            net_amount_minor=10_000,
            metadata={"provider": "DSP"},
        )
    )

    context = service.build_context(
        contract_id,
        period_start="2026-01-01",
        period_end="2026-01-31",
    )

    assert context.is_ready
    assert context.work_ids == (work_id,)
    assert context.right_ids == (right_id,)
    assert context.terms == (term,)
    assert context.source_events == (event,)
    assert [issue.severity for issue in context.issues] == []

    conn.close()


def test_contract_royalty_source_events_generate_linked_draft_calculations_without_posting():
    conn = _connection()
    contract_id, work_id, publisher_id, right_id = _integrated_contract_fixture(conn)
    service = RoyaltyIntegrationService(conn)
    term = service.create_contract_royalty_term(
        ContractRoyaltyTermPayload(
            contract_id=contract_id,
            party_id=publisher_id,
            right_type="composition_publishing",
            royalty_basis="net",
            rate_basis_points=1_500,
        ),
        scopes=(RoyaltyTermScopePayload("work", work_id),),
    )
    event = service.record_source_event(
        RoyaltySourceEventPayload(
            contract_id=contract_id,
            work_id=work_id,
            description="DSP statement January",
            period_start="2026-01-01",
            period_end="2026-01-31",
            gross_amount_minor=12_000,
            net_amount_minor=10_000,
        )
    )

    calculations = service.create_draft_calculations_from_contract(
        contract_id,
        period_start="2026-01-01",
        period_end="2026-01-31",
        created_by="tester",
    )
    calculation = calculations[0]
    line = conn.execute(
        """
        SELECT
            net_payable_minor,
            source_type,
            source_id,
            contract_id,
            work_id,
            right_id,
            contract_royalty_term_id,
            source_event_id
        FROM RoyaltyCalculationLines
        WHERE calculation_id=?
        """,
        (calculation.id,),
    ).fetchone()
    source_link = conn.execute(
        """
        SELECT
            calculation_id,
            source_event_id,
            contract_id,
            work_id,
            right_id,
            contract_royalty_term_id,
            amount_minor,
            currency
        FROM RoyaltyCalculationSourceLinks
        WHERE calculation_id=?
        """,
        (calculation.id,),
    ).fetchone()
    calculation_row = conn.execute(
        """
        SELECT contract_id, context_snapshot_json, ledger_transaction_id
        FROM RoyaltyCalculations
        WHERE id=?
        """,
        (calculation.id,),
    ).fetchone()

    assert len(calculations) == 1
    assert calculation.party_id == publisher_id
    assert calculation.net_payable_minor == 1_500
    assert calculation.status == "calculated"
    assert line == (
        1_500,
        "royalty_source_event",
        str(event.id),
        contract_id,
        work_id,
        right_id,
        term.id,
        event.id,
    )
    assert source_link == (
        calculation.id,
        event.id,
        contract_id,
        work_id,
        right_id,
        term.id,
        1_500,
        "EUR",
    )
    assert calculation_row[0] == contract_id
    assert '"contract_id": ' in calculation_row[1]
    assert calculation_row[2] is None
    assert conn.execute("SELECT COUNT(*) FROM AccountingTransactions").fetchone()[0] == 0

    conn.close()


def test_royalty_readiness_blocks_unintegrated_contracts_and_bad_splits():
    conn = _connection()
    party_service = PartyService(conn)
    writer_id = _party(conn, "Unready Writer")
    work_id = WorkService(conn, party_service=party_service).create_work(
        WorkPayload(
            title="Unready Work",
            contributors=[
                WorkContributorPayload(
                    role="composer",
                    name="Unready Writer",
                    share_percent=100.0,
                    party_id=writer_id,
                )
            ],
        )
    )
    contract_id = ContractService(conn, party_service=party_service).create_contract(
        ContractPayload(
            title="Draft Royalty Agreement",
            status="draft",
            work_ids=[work_id],
        )
    )
    RightsService(conn).replace_work_ownership_interests(
        work_id,
        [
            OwnershipInterestPayload(
                role="publisher",
                party_id=writer_id,
                share_percent=50.0,
                source_contract_id=contract_id,
            )
        ],
    )
    service = RoyaltyIntegrationService(conn)

    context = service.build_context(contract_id)
    codes = {issue.code for issue in context.issues}

    assert not context.is_ready
    assert {
        "contract_not_active",
        "contract_has_no_royalty_terms",
        "contract_has_no_rights_records",
        "work_ownership_split_not_100",
    } <= codes
    with pytest.raises(ValueError, match="not royalty-ready"):
        service.create_draft_calculations_from_contract(contract_id)

    conn.close()


def test_royalty_integration_records_serialize_and_recover_bad_event_metadata():
    conn = _connection()
    contract_id, work_id, publisher_id, _right_id = _integrated_contract_fixture(conn)
    service = RoyaltyIntegrationService(conn)
    term = service.create_contract_royalty_term(
        ContractRoyaltyTermPayload(
            contract_id=contract_id,
            party_id=publisher_id,
            rate_basis_points=1_250,
            notes="Publisher share",
        ),
        scopes=(RoyaltyTermScopePayload("work", work_id, relation_type=""),),
    )
    event = service.record_source_event(
        RoyaltySourceEventPayload(
            contract_id=contract_id,
            work_id=work_id,
            description="DSP export",
            gross_amount_minor=2_000,
            net_amount_minor=1_500,
            metadata={"run": "A"},
        )
    )
    conn.execute(
        "UPDATE RoyaltySourceEvents SET metadata_json=? WHERE id=?",
        ("{not-json", event.id),
    )

    scope = service.list_term_scopes(term.id)[0]
    reloaded_event = service.fetch_source_event(event.id)
    issue = RoyaltyReadinessIssue("warning", "sample", "Sample issue", "contract", contract_id)

    assert term.to_dict()["notes"] == "Publisher share"
    assert scope.to_dict()["relation_type"] == "applies_to"
    assert reloaded_event is not None
    assert reloaded_event.to_dict()["metadata"] == {}
    assert issue.to_dict()["code"] == "sample"

    conn.close()


def test_royalty_integration_validates_terms_events_and_missing_contracts():
    conn = _connection()
    contract_id, work_id, publisher_id, _right_id = _integrated_contract_fixture(conn)
    service = RoyaltyIntegrationService(conn)

    with pytest.raises(ValueError, match="Contract 9999 was not found"):
        service.create_contract_royalty_term(
            ContractRoyaltyTermPayload(
                contract_id=9999,
                party_id=publisher_id,
                rate_basis_points=100,
            )
        )
    with pytest.raises(ValueError, match="payee party 9999 was not found"):
        service.create_contract_royalty_term(
            ContractRoyaltyTermPayload(
                contract_id=contract_id,
                party_id=9999,
                rate_basis_points=100,
            )
        )
    with pytest.raises(ValueError, match="gross' or 'net"):
        service.create_contract_royalty_term(
            ContractRoyaltyTermPayload(
                contract_id=contract_id,
                party_id=publisher_id,
                royalty_basis="receipts",
                rate_basis_points=100,
            )
        )
    with pytest.raises(ValueError, match="greater than zero"):
        service.create_contract_royalty_term(
            ContractRoyaltyTermPayload(
                contract_id=contract_id,
                party_id=publisher_id,
                rate_basis_points=0,
            )
        )
    with pytest.raises(ValueError, match="effective end"):
        service.create_contract_royalty_term(
            ContractRoyaltyTermPayload(
                contract_id=contract_id,
                party_id=publisher_id,
                rate_basis_points=100,
                effective_start="2026-02-01",
                effective_end="2026-01-31",
            )
        )
    with pytest.raises(ValueError, match="Unsupported royalty scope type"):
        service.create_contract_royalty_term(
            ContractRoyaltyTermPayload(
                contract_id=contract_id,
                party_id=publisher_id,
                rate_basis_points=100,
            ),
            scopes=(RoyaltyTermScopePayload("album", work_id),),
        )
    with pytest.raises(ValueError, match="description is required"):
        service.record_source_event(
            RoyaltySourceEventPayload(description="", gross_amount_minor=100)
        )
    with pytest.raises(ValueError, match="non-negative"):
        service.record_source_event(
            RoyaltySourceEventPayload(description="Bad event", gross_amount_minor=-1)
        )
    with pytest.raises(ValueError, match="gross or net amount"):
        service.record_source_event(RoyaltySourceEventPayload(description="Empty event"))
    with pytest.raises(ValueError, match="Contract 9999 was not found"):
        service.build_context(9999)

    inactive = service.create_contract_royalty_term(
        ContractRoyaltyTermPayload(
            contract_id=contract_id,
            party_id=publisher_id,
            rate_basis_points=100,
            active=False,
        )
    )

    assert inactive not in service.list_contract_royalty_terms(contract_id)
    assert inactive in service.list_contract_royalty_terms(contract_id, active_only=False)

    conn.close()


def test_royalty_readiness_covers_empty_contracts_missing_works_and_contributors():
    conn = _connection()
    party_service = PartyService(conn)
    writer_id = _party(conn, "Fallback Writer")
    contract_id = ContractService(conn, party_service=party_service).create_contract(
        ContractPayload(title="Empty Active Agreement", status="active")
    )
    service = RoyaltyIntegrationService(conn)

    empty_context = service.build_context(contract_id)
    empty_codes = {issue.code for issue in empty_context.issues}

    assert {
        "contract_has_no_works",
        "contract_has_no_royalty_terms",
        "contract_has_no_rights_records",
        "contract_has_no_source_events",
    } <= empty_codes
    assert service._work_readiness_issues(9999)[0].code == "linked_work_missing"

    work_id = WorkService(conn, party_service=party_service).create_work(
        WorkPayload(
            title="Contributor Fallback Work",
            contributors=[
                WorkContributorPayload(
                    role="composer",
                    name="Fallback Writer",
                    share_percent=100.0,
                    party_id=writer_id,
                )
            ],
        )
    )
    conn.execute(
        """
        UPDATE WorkContributors
        SET share_percent=?, party_id=NULL
        WHERE work_id=?
        """,
        (50.0, work_id),
    )

    contributor_codes = {issue.code for issue in service._work_readiness_issues(work_id)}

    assert {
        "work_rights_not_verified",
        "work_contributor_split_not_100",
        "work_contributor_party_missing",
    } <= contributor_codes

    conn.close()


def test_royalty_term_matching_supports_scope_variants_and_missing_rights():
    conn = _connection()
    contract_id, work_id, _publisher_id, right_id = _integrated_contract_fixture(conn)
    service = RoyaltyIntegrationService(conn)
    term = ContractRoyaltyTermRecord(
        id=1,
        contract_id=contract_id,
        party_id=1,
        right_type=None,
        royalty_basis="net",
        rate_basis_points=100,
        territory=None,
        effective_start=None,
        effective_end=None,
        source_document_id=None,
        notes=None,
        active=True,
        created_at=None,
        updated_at=None,
    )
    inactive_term = ContractRoyaltyTermRecord(
        id=2,
        contract_id=contract_id,
        party_id=1,
        right_type=None,
        royalty_basis="net",
        rate_basis_points=100,
        territory=None,
        effective_start=None,
        effective_end=None,
        source_document_id=None,
        notes=None,
        active=False,
        created_at=None,
        updated_at=None,
    )
    event = RoyaltySourceEventRecord(
        id=1,
        source_type="statement",
        source_id="1",
        contract_id=contract_id,
        work_id=work_id,
        track_id=77,
        release_id=88,
        event_date=None,
        period_start=None,
        period_end=None,
        description="Scoped event",
        currency="EUR",
        gross_amount_minor=1_000,
        net_amount_minor=800,
        metadata={},
        created_at=None,
    )
    track_scope = RoyaltyTermScopeRecord(1, term.id, "track", 77, "applies_to", None)
    release_scope = RoyaltyTermScopeRecord(2, term.id, "release", 88, "applies_to", None)
    missing_right_scope = RoyaltyTermScopeRecord(3, term.id, "right", 9999, "applies_to", None)
    right_scope = RoyaltyTermScopeRecord(4, term.id, "right", right_id, "applies_to", None)
    unmatched_scope = RoyaltyTermScopeRecord(5, term.id, "track", 999, "applies_to", None)
    event_without_entity = RoyaltySourceEventRecord(
        id=2,
        source_type=None,
        source_id=None,
        contract_id=contract_id,
        work_id=None,
        track_id=None,
        release_id=None,
        event_date=None,
        period_start=None,
        period_end=None,
        description="No entity",
        currency="EUR",
        gross_amount_minor=1_000,
        net_amount_minor=800,
        metadata={},
        created_at=None,
    )

    assert not service._term_matches_event(inactive_term, (), event)
    assert service._term_matches_event(term, (), event)
    assert service._term_matches_event(term, (track_scope,), event)
    assert service._term_matches_event(term, (release_scope,), event)
    assert not service._term_matches_event(term, (missing_right_scope,), event)
    assert service._term_matches_event(term, (right_scope,), event)
    assert not service._term_matches_event(term, (unmatched_scope,), event)
    assert service._matching_right_id(term, event, ()) is None
    assert service._matching_right_id(term, event_without_entity, (right_id,)) is None

    conn.close()


def test_royalty_draft_generation_skips_unmatched_and_zero_value_lines():
    conn = _connection()
    contract_id, work_id, publisher_id, _right_id = _integrated_contract_fixture(conn)
    service = RoyaltyIntegrationService(conn)
    service.create_contract_royalty_term(
        ContractRoyaltyTermPayload(
            contract_id=contract_id,
            party_id=publisher_id,
            royalty_basis="net",
            rate_basis_points=1_000,
        ),
        scopes=(RoyaltyTermScopePayload("track", 9999),),
    )
    service.create_contract_royalty_term(
        ContractRoyaltyTermPayload(
            contract_id=contract_id,
            party_id=publisher_id,
            royalty_basis="net",
            rate_basis_points=1_000,
        ),
        scopes=(RoyaltyTermScopePayload("work", work_id),),
    )
    service.record_source_event(
        RoyaltySourceEventPayload(
            contract_id=contract_id,
            work_id=work_id,
            description="Gross-only event",
            gross_amount_minor=100,
            net_amount_minor=0,
        )
    )

    assert service.create_draft_calculations_from_contract(contract_id) == ()

    conn.close()


def test_royalty_source_links_are_immutable_after_posting():
    conn = _connection()
    contract_id, work_id, publisher_id, _right_id = _integrated_contract_fixture(conn)
    service = RoyaltyIntegrationService(conn)
    service.create_contract_royalty_term(
        ContractRoyaltyTermPayload(
            contract_id=contract_id,
            party_id=publisher_id,
            rate_basis_points=1_500,
        ),
        scopes=(RoyaltyTermScopePayload("work", work_id),),
    )
    service.record_source_event(
        RoyaltySourceEventPayload(
            contract_id=contract_id,
            work_id=work_id,
            description="DSP statement",
            gross_amount_minor=10_000,
            net_amount_minor=10_000,
        )
    )
    calculation = service.create_draft_calculations_from_contract(contract_id)[0]
    RoyaltyAccountingService(conn).approve_and_post_calculation(
        calculation.id,
        command_key="post-integrated-royalty",
        created_by="tester",
    )
    source_link_id = conn.execute(
        "SELECT id FROM RoyaltyCalculationSourceLinks WHERE calculation_id=?",
        (calculation.id,),
    ).fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE RoyaltyCalculationSourceLinks SET amount_minor=? WHERE id=?",
            (1, source_link_id),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM RoyaltyCalculationSourceLinks WHERE id=?", (source_link_id,))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            """
            INSERT INTO RoyaltyCalculationSourceLinks(
                calculation_id,
                source_event_id,
                contract_id,
                contract_royalty_term_id,
                relation_type,
                amount_minor,
                currency
            )
            VALUES (?, ?, ?, ?, 'royalty_source', ?, ?)
            """,
            (calculation.id, 1, contract_id, 1, 100, "EUR"),
        )

    conn.close()

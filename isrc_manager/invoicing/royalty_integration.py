"""Contract/work/right integration layer for royalty accounting."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import Iterable

from isrc_manager.domain.repertoire import clean_text
from isrc_manager.rights.service import RightsService

from .models import (
    DEFAULT_CURRENCY,
    RoyaltyCalculationLinePayload,
    RoyaltyCalculationPayload,
    RoyaltyCalculationRecord,
)
from .money import normalize_currency
from .royalty_service import RoyaltyAccountingService

ROYALTY_BASIS_NET = "net"
ROYALTY_BASIS_GROSS = "gross"
ROYALTY_BASIS_CHOICES = frozenset({ROYALTY_BASIS_NET, ROYALTY_BASIS_GROSS})

ROYALTY_SCOPE_TYPES = frozenset(
    {
        "work",
        "track",
        "release",
        "right",
        "work_ownership_interest",
        "recording_ownership_interest",
    }
)


@dataclass(frozen=True, slots=True)
class RoyaltyTermScopePayload:
    scope_type: str
    scope_id: int
    relation_type: str = "applies_to"


@dataclass(frozen=True, slots=True)
class ContractRoyaltyTermPayload:
    contract_id: int
    party_id: int
    rate_basis_points: int
    royalty_basis: str = ROYALTY_BASIS_NET
    right_type: str | None = None
    territory: str | None = None
    effective_start: str | None = None
    effective_end: str | None = None
    source_document_id: int | None = None
    notes: str | None = None
    active: bool = True


@dataclass(slots=True)
class ContractRoyaltyTermRecord:
    id: int
    contract_id: int
    party_id: int
    right_type: str | None
    royalty_basis: str
    rate_basis_points: int
    territory: str | None
    effective_start: str | None
    effective_end: str | None
    source_document_id: int | None
    notes: str | None
    active: bool
    created_at: str | None
    updated_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RoyaltyTermScopeRecord:
    id: int
    term_id: int
    scope_type: str
    scope_id: int
    relation_type: str
    created_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RoyaltySourceEventPayload:
    description: str
    gross_amount_minor: int = 0
    net_amount_minor: int = 0
    currency: str = DEFAULT_CURRENCY
    source_type: str | None = None
    source_id: str | int | None = None
    contract_id: int | None = None
    work_id: int | None = None
    track_id: int | None = None
    release_id: int | None = None
    event_date: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(slots=True)
class RoyaltySourceEventRecord:
    id: int
    source_type: str | None
    source_id: str | None
    contract_id: int | None
    work_id: int | None
    track_id: int | None
    release_id: int | None
    event_date: str | None
    period_start: str | None
    period_end: str | None
    description: str
    currency: str
    gross_amount_minor: int
    net_amount_minor: int
    metadata: dict[str, object]
    created_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RoyaltyReadinessIssue:
    severity: str
    code: str
    message: str
    entity_type: str | None = None
    entity_id: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RoyaltyIntegrationContext:
    contract_id: int
    contract_title: str
    contract_status: str
    work_ids: tuple[int, ...]
    track_ids: tuple[int, ...]
    release_ids: tuple[int, ...]
    right_ids: tuple[int, ...]
    ownership_interest_ids: tuple[int, ...]
    terms: tuple[ContractRoyaltyTermRecord, ...]
    source_events: tuple[RoyaltySourceEventRecord, ...]
    issues: tuple[RoyaltyReadinessIssue, ...]

    @property
    def is_ready(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _GeneratedRoyaltyLine:
    payload: RoyaltyCalculationLinePayload
    source_event: RoyaltySourceEventRecord
    term: ContractRoyaltyTermRecord
    work_id: int | None
    track_id: int | None
    release_id: int | None
    right_id: int | None
    ownership_interest_id: int | None
    ownership_interest_type: str | None


def _clean_relation_type(value: str | None) -> str:
    return clean_text(value) or "applies_to"


def _clean_scope_type(value: str | None) -> str:
    clean = str(value or "").strip().lower()
    if clean not in ROYALTY_SCOPE_TYPES:
        raise ValueError(f"Unsupported royalty scope type {value!r}.")
    return clean


def _clean_basis(value: str | None) -> str:
    clean = str(value or ROYALTY_BASIS_NET).strip().lower()
    if clean not in ROYALTY_BASIS_CHOICES:
        raise ValueError("Royalty basis must be 'gross' or 'net'.")
    return clean


def _to_basis_points(percent_value: object | None) -> int | None:
    if percent_value in (None, ""):
        return None
    try:
        return int(round(float(percent_value) * 100))
    except Exception:
        return None


def _basis_points_amount(amount_minor: int, basis_points: int) -> int:
    return (int(amount_minor) * int(basis_points) + 5_000) // 10_000


class RoyaltyIntegrationService:
    """Builds royalty context from contracts, works, rights, and source events."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.royalties = RoyaltyAccountingService(conn)

    def create_contract_royalty_term(
        self,
        payload: ContractRoyaltyTermPayload,
        *,
        scopes: Iterable[RoyaltyTermScopePayload] = (),
    ) -> ContractRoyaltyTermRecord:
        contract_id = int(payload.contract_id)
        party_id = int(payload.party_id)
        if self._contract_row(contract_id) is None:
            raise ValueError(f"Contract {contract_id} was not found.")
        if self._party_exists(party_id) is False:
            raise ValueError(f"Royalty payee party {party_id} was not found.")
        basis = _clean_basis(payload.royalty_basis)
        rate = int(payload.rate_basis_points)
        if rate <= 0:
            raise ValueError("Royalty rate must be greater than zero basis points.")
        if payload.effective_start and payload.effective_end:
            if str(payload.effective_start) > str(payload.effective_end):
                raise ValueError("Royalty term effective end cannot be before the start.")
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO ContractRoyaltyTerms(
                    contract_id,
                    party_id,
                    right_type,
                    royalty_basis,
                    rate_basis_points,
                    territory,
                    effective_start,
                    effective_end,
                    source_document_id,
                    notes,
                    active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contract_id,
                    party_id,
                    clean_text(payload.right_type),
                    basis,
                    rate,
                    clean_text(payload.territory),
                    clean_text(payload.effective_start),
                    clean_text(payload.effective_end),
                    (
                        int(payload.source_document_id)
                        if payload.source_document_id is not None
                        else None
                    ),
                    clean_text(payload.notes),
                    1 if payload.active else 0,
                ),
            )
            term_id = int(cursor.lastrowid)
            for scope in scopes:
                self._insert_term_scope(cursor, term_id=term_id, payload=scope)
        record = self.fetch_contract_royalty_term(term_id)
        if record is None:
            raise RuntimeError("Contract royalty term could not be reloaded.")
        return record

    def fetch_contract_royalty_term(self, term_id: int) -> ContractRoyaltyTermRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                contract_id,
                party_id,
                right_type,
                royalty_basis,
                rate_basis_points,
                territory,
                effective_start,
                effective_end,
                source_document_id,
                notes,
                active,
                created_at,
                updated_at
            FROM ContractRoyaltyTerms
            WHERE id=?
            """,
            (int(term_id),),
        ).fetchone()
        return self._row_to_term(row) if row else None

    def list_contract_royalty_terms(
        self,
        contract_id: int,
        *,
        active_only: bool = True,
    ) -> tuple[ContractRoyaltyTermRecord, ...]:
        where = "WHERE contract_id=?"
        params: list[object] = [int(contract_id)]
        if active_only:
            where += " AND active=1"
        rows = self.conn.execute(
            f"""
            SELECT
                id,
                contract_id,
                party_id,
                right_type,
                royalty_basis,
                rate_basis_points,
                territory,
                effective_start,
                effective_end,
                source_document_id,
                notes,
                active,
                created_at,
                updated_at
            FROM ContractRoyaltyTerms
            {where}
            ORDER BY active DESC, id
            """,
            params,
        ).fetchall()
        return tuple(self._row_to_term(row) for row in rows)

    def list_term_scopes(self, term_id: int) -> tuple[RoyaltyTermScopeRecord, ...]:
        rows = self.conn.execute(
            """
            SELECT id, term_id, scope_type, scope_id, relation_type, created_at
            FROM ContractRoyaltyTermScopes
            WHERE term_id=?
            ORDER BY id
            """,
            (int(term_id),),
        ).fetchall()
        return tuple(
            RoyaltyTermScopeRecord(
                id=int(row[0]),
                term_id=int(row[1]),
                scope_type=str(row[2] or ""),
                scope_id=int(row[3]),
                relation_type=str(row[4] or "applies_to"),
                created_at=clean_text(row[5]),
            )
            for row in rows
        )

    def record_source_event(self, payload: RoyaltySourceEventPayload) -> RoyaltySourceEventRecord:
        description = clean_text(payload.description)
        if description is None:
            raise ValueError("Royalty source event description is required.")
        currency = normalize_currency(payload.currency)
        gross_amount = int(payload.gross_amount_minor)
        net_amount = int(payload.net_amount_minor)
        if gross_amount < 0 or net_amount < 0:
            raise ValueError("Royalty source event amounts must be non-negative.")
        if gross_amount <= 0 and net_amount <= 0:
            raise ValueError("Royalty source event must have a gross or net amount.")
        metadata_json = json.dumps(payload.metadata or {}, sort_keys=True)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO RoyaltySourceEvents(
                    source_type,
                    source_id,
                    contract_id,
                    work_id,
                    track_id,
                    release_id,
                    event_date,
                    period_start,
                    period_end,
                    description,
                    currency,
                    gross_amount_minor,
                    net_amount_minor,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_text(payload.source_type),
                    clean_text(payload.source_id),
                    int(payload.contract_id) if payload.contract_id is not None else None,
                    int(payload.work_id) if payload.work_id is not None else None,
                    int(payload.track_id) if payload.track_id is not None else None,
                    int(payload.release_id) if payload.release_id is not None else None,
                    clean_text(payload.event_date),
                    clean_text(payload.period_start),
                    clean_text(payload.period_end),
                    description,
                    currency,
                    gross_amount,
                    net_amount,
                    metadata_json,
                ),
            )
            event_id = int(cursor.lastrowid)
        record = self.fetch_source_event(event_id)
        if record is None:
            raise RuntimeError("Royalty source event could not be reloaded.")
        return record

    def fetch_source_event(self, event_id: int) -> RoyaltySourceEventRecord | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                source_type,
                source_id,
                contract_id,
                work_id,
                track_id,
                release_id,
                event_date,
                period_start,
                period_end,
                description,
                currency,
                gross_amount_minor,
                net_amount_minor,
                metadata_json,
                created_at
            FROM RoyaltySourceEvents
            WHERE id=?
            """,
            (int(event_id),),
        ).fetchone()
        return self._row_to_source_event(row) if row else None

    def build_context(
        self,
        contract_id: int,
        *,
        period_start: str | None = None,
        period_end: str | None = None,
    ) -> RoyaltyIntegrationContext:
        contract = self._contract_row(int(contract_id))
        if contract is None:
            raise ValueError(f"Contract {int(contract_id)} was not found.")
        work_ids = self._linked_ids("ContractWorkLinks", "work_id", contract_id)
        track_ids = self._tracks_for_works(work_ids)
        release_ids: tuple[int, ...] = ()
        right_ids = self._right_ids(contract_id, work_ids, track_ids, release_ids)
        ownership_ids = self._work_ownership_ids(work_ids)
        terms = self.list_contract_royalty_terms(contract_id)
        source_events = self._source_events_for_context(
            contract_id=contract_id,
            work_ids=work_ids,
            track_ids=track_ids,
            release_ids=release_ids,
            period_start=period_start,
            period_end=period_end,
        )
        issues = self._readiness_issues(
            contract_id=contract_id,
            contract_status=str(contract[2] or ""),
            work_ids=work_ids,
            track_ids=track_ids,
            right_ids=right_ids,
            terms=terms,
            source_events=source_events,
        )
        return RoyaltyIntegrationContext(
            contract_id=int(contract[0]),
            contract_title=str(contract[1] or ""),
            contract_status=str(contract[2] or ""),
            work_ids=work_ids,
            track_ids=track_ids,
            release_ids=release_ids,
            right_ids=right_ids,
            ownership_interest_ids=ownership_ids,
            terms=terms,
            source_events=source_events,
            issues=tuple(issues),
        )

    def create_draft_calculations_from_contract(
        self,
        contract_id: int,
        *,
        period_start: str | None = None,
        period_end: str | None = None,
        created_by: str | None = None,
    ) -> tuple[RoyaltyCalculationRecord, ...]:
        context = self.build_context(
            contract_id,
            period_start=period_start,
            period_end=period_end,
        )
        errors = [issue.message for issue in context.issues if issue.severity == "error"]
        if errors:
            raise ValueError("Contract is not royalty-ready: " + "; ".join(errors))
        grouped: dict[tuple[int, str], list[_GeneratedRoyaltyLine]] = {}
        for term in context.terms:
            scopes = self.list_term_scopes(term.id)
            for event in context.source_events:
                if not self._term_matches_event(term, scopes, event):
                    continue
                base_amount = (
                    event.gross_amount_minor
                    if term.royalty_basis == ROYALTY_BASIS_GROSS
                    else event.net_amount_minor
                )
                amount = _basis_points_amount(base_amount, term.rate_basis_points)
                if amount <= 0:
                    continue
                line = _GeneratedRoyaltyLine(
                    payload=RoyaltyCalculationLinePayload(
                        description=(
                            f"{event.description} - {term.rate_basis_points / 100:.2f}% "
                            f"{term.royalty_basis} royalty"
                        ),
                        net_payable_minor=amount,
                        source_type="royalty_source_event",
                        source_id=event.id,
                    ),
                    source_event=event,
                    term=term,
                    work_id=event.work_id,
                    track_id=event.track_id,
                    release_id=event.release_id,
                    right_id=self._matching_right_id(term, event, context.right_ids),
                    ownership_interest_id=None,
                    ownership_interest_type=None,
                )
                grouped.setdefault((term.party_id, event.currency), []).append(line)
        calculations: list[RoyaltyCalculationRecord] = []
        for (party_id, currency), lines in sorted(grouped.items()):
            calculation = self.royalties.create_calculation(
                RoyaltyCalculationPayload(
                    party_id=party_id,
                    currency=currency,
                    period_start=period_start,
                    period_end=period_end,
                    lines=tuple(line.payload for line in lines),
                    created_by=created_by,
                )
            )
            self._attach_context_links(calculation.id, context=context, generated_lines=lines)
            refreshed = self.royalties.fetch_calculation(calculation.id)
            if refreshed is None:
                raise RuntimeError("Royalty calculation could not be reloaded after linking.")
            calculations.append(refreshed)
        return tuple(calculations)

    @staticmethod
    def _row_to_term(row) -> ContractRoyaltyTermRecord:
        return ContractRoyaltyTermRecord(
            id=int(row[0]),
            contract_id=int(row[1]),
            party_id=int(row[2]),
            right_type=clean_text(row[3]),
            royalty_basis=str(row[4] or ROYALTY_BASIS_NET),
            rate_basis_points=int(row[5]),
            territory=clean_text(row[6]),
            effective_start=clean_text(row[7]),
            effective_end=clean_text(row[8]),
            source_document_id=int(row[9]) if row[9] is not None else None,
            notes=clean_text(row[10]),
            active=bool(row[11]),
            created_at=clean_text(row[12]),
            updated_at=clean_text(row[13]),
        )

    @staticmethod
    def _row_to_source_event(row) -> RoyaltySourceEventRecord:
        try:
            metadata = json.loads(str(row[14] or "{}"))
        except json.JSONDecodeError:
            metadata = {}
        return RoyaltySourceEventRecord(
            id=int(row[0]),
            source_type=clean_text(row[1]),
            source_id=clean_text(row[2]),
            contract_id=int(row[3]) if row[3] is not None else None,
            work_id=int(row[4]) if row[4] is not None else None,
            track_id=int(row[5]) if row[5] is not None else None,
            release_id=int(row[6]) if row[6] is not None else None,
            event_date=clean_text(row[7]),
            period_start=clean_text(row[8]),
            period_end=clean_text(row[9]),
            description=str(row[10] or ""),
            currency=str(row[11] or DEFAULT_CURRENCY),
            gross_amount_minor=int(row[12] or 0),
            net_amount_minor=int(row[13] or 0),
            metadata=metadata if isinstance(metadata, dict) else {},
            created_at=clean_text(row[15]),
        )

    def _insert_term_scope(
        self,
        cursor: sqlite3.Cursor,
        *,
        term_id: int,
        payload: RoyaltyTermScopePayload,
    ) -> None:
        cursor.execute(
            """
            INSERT OR IGNORE INTO ContractRoyaltyTermScopes(
                term_id,
                scope_type,
                scope_id,
                relation_type
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                int(term_id),
                _clean_scope_type(payload.scope_type),
                int(payload.scope_id),
                _clean_relation_type(payload.relation_type),
            ),
        )

    def _contract_row(self, contract_id: int):
        return self.conn.execute(
            """
            SELECT id, title, status
            FROM Contracts
            WHERE id=?
            """,
            (int(contract_id),),
        ).fetchone()

    def _party_exists(self, party_id: int) -> bool:
        row = self.conn.execute("SELECT 1 FROM Parties WHERE id=?", (int(party_id),)).fetchone()
        return row is not None

    def _linked_ids(self, table_name: str, column_name: str, contract_id: int) -> tuple[int, ...]:
        rows = self.conn.execute(
            f"""
            SELECT {column_name}
            FROM {table_name}
            WHERE contract_id=?
            ORDER BY {column_name}
            """,
            (int(contract_id),),
        ).fetchall()
        return tuple(int(row[0]) for row in rows)

    def _tracks_for_works(self, work_ids: tuple[int, ...]) -> tuple[int, ...]:
        if not work_ids:
            return ()
        placeholders = ", ".join("?" for _ in work_ids)
        rows = self.conn.execute(
            f"""
            SELECT track_id
            FROM WorkTrackLinks
            WHERE work_id IN ({placeholders})
            ORDER BY track_id
            """,
            work_ids,
        ).fetchall()
        return tuple(int(row[0]) for row in rows)

    def _right_ids(
        self,
        contract_id: int,
        work_ids: tuple[int, ...],
        track_ids: tuple[int, ...],
        release_ids: tuple[int, ...],
    ) -> tuple[int, ...]:
        clauses = ["source_contract_id=?"]
        params: list[object] = [int(contract_id)]
        for column_name, values in (
            ("work_id", work_ids),
            ("track_id", track_ids),
            ("release_id", release_ids),
        ):
            if values:
                placeholders = ", ".join("?" for _ in values)
                clauses.append(f"{column_name} IN ({placeholders})")
                params.extend(values)
        rows = self.conn.execute(
            f"""
            SELECT id
            FROM RightsRecords
            WHERE {" OR ".join(clauses)}
            ORDER BY id
            """,
            params,
        ).fetchall()
        return tuple(int(row[0]) for row in rows)

    def _work_ownership_ids(self, work_ids: tuple[int, ...]) -> tuple[int, ...]:
        if not work_ids:
            return ()
        placeholders = ", ".join("?" for _ in work_ids)
        rows = self.conn.execute(
            f"""
            SELECT id
            FROM WorkOwnershipInterests
            WHERE work_id IN ({placeholders})
            ORDER BY id
            """,
            work_ids,
        ).fetchall()
        return tuple(int(row[0]) for row in rows)

    def _source_events_for_context(
        self,
        *,
        contract_id: int,
        work_ids: tuple[int, ...],
        track_ids: tuple[int, ...],
        release_ids: tuple[int, ...],
        period_start: str | None,
        period_end: str | None,
    ) -> tuple[RoyaltySourceEventRecord, ...]:
        clauses = ["contract_id=?"]
        params: list[object] = [int(contract_id)]
        for column_name, values in (
            ("work_id", work_ids),
            ("track_id", track_ids),
            ("release_id", release_ids),
        ):
            if values:
                placeholders = ", ".join("?" for _ in values)
                clauses.append(f"{column_name} IN ({placeholders})")
                params.extend(values)
        where = f"WHERE ({' OR '.join(clauses)})"
        start = clean_text(period_start)
        end = clean_text(period_end)
        if start:
            where += " AND COALESCE(period_end, event_date, period_start, '') >= ?"
            params.append(start)
        if end:
            where += " AND COALESCE(period_start, event_date, period_end, '') <= ?"
            params.append(end)
        rows = self.conn.execute(
            f"""
            SELECT
                id,
                source_type,
                source_id,
                contract_id,
                work_id,
                track_id,
                release_id,
                event_date,
                period_start,
                period_end,
                description,
                currency,
                gross_amount_minor,
                net_amount_minor,
                metadata_json,
                created_at
            FROM RoyaltySourceEvents
            {where}
            ORDER BY COALESCE(period_start, event_date, created_at), id
            """,
            params,
        ).fetchall()
        return tuple(self._row_to_source_event(row) for row in rows)

    def _readiness_issues(
        self,
        *,
        contract_id: int,
        contract_status: str,
        work_ids: tuple[int, ...],
        track_ids: tuple[int, ...],
        right_ids: tuple[int, ...],
        terms: tuple[ContractRoyaltyTermRecord, ...],
        source_events: tuple[RoyaltySourceEventRecord, ...],
    ) -> list[RoyaltyReadinessIssue]:
        issues: list[RoyaltyReadinessIssue] = []
        if contract_status != "active":
            issues.append(
                RoyaltyReadinessIssue(
                    "error",
                    "contract_not_active",
                    "Royalty accounting requires an active contract.",
                    "contract",
                    int(contract_id),
                )
            )
        if not work_ids:
            message = "Contract has no linked musical works."
            if track_ids:
                message = (
                    "Contract only has direct recording links. Link the musical work and rights "
                    "split records before royalty accounting; recordings remain traceability "
                    "context, not the top-level royalty source."
                )
            issues.append(
                RoyaltyReadinessIssue(
                    "error",
                    "contract_has_no_works",
                    message,
                    "contract",
                    int(contract_id),
                )
            )
        if not terms:
            issues.append(
                RoyaltyReadinessIssue(
                    "error",
                    "contract_has_no_royalty_terms",
                    "Contract has no active royalty terms.",
                    "contract",
                    int(contract_id),
                )
            )
        if not right_ids:
            issues.append(
                RoyaltyReadinessIssue(
                    "error",
                    "contract_has_no_rights_records",
                    "Contract and linked works have no rights records for royalty traceability.",
                    "contract",
                    int(contract_id),
                )
            )
        if not source_events:
            issues.append(
                RoyaltyReadinessIssue(
                    "warning",
                    "contract_has_no_source_events",
                    "No royalty source events are available for the selected period.",
                    "contract",
                    int(contract_id),
                )
            )
        for term in terms:
            if term.rate_basis_points <= 0:
                issues.append(
                    RoyaltyReadinessIssue(
                        "error",
                        "royalty_term_has_no_rate",
                        "Royalty term has no positive rate.",
                        "contract_royalty_term",
                        term.id,
                    )
                )
            if not self._party_exists(term.party_id):
                issues.append(
                    RoyaltyReadinessIssue(
                        "error",
                        "royalty_term_payee_missing",
                        "Royalty term payee party is missing.",
                        "contract_royalty_term",
                        term.id,
                    )
                )
        for work_id in work_ids:
            issues.extend(self._work_readiness_issues(int(work_id)))
        context_right_ids = set(right_ids)
        for conflict in RightsService(self.conn).detect_conflicts():
            if (
                conflict.left_right_id in context_right_ids
                or conflict.right_right_id in context_right_ids
            ):
                issues.append(
                    RoyaltyReadinessIssue(
                        "error",
                        "rights_conflict",
                        conflict.message,
                        "right",
                        int(conflict.left_right_id),
                    )
                )
        return issues

    def _work_readiness_issues(self, work_id: int) -> list[RoyaltyReadinessIssue]:
        issues: list[RoyaltyReadinessIssue] = []
        work_row = self.conn.execute(
            "SELECT title, rights_verified FROM Works WHERE id=?",
            (int(work_id),),
        ).fetchone()
        if work_row is None:
            issues.append(
                RoyaltyReadinessIssue(
                    "error",
                    "linked_work_missing",
                    "Linked work is missing.",
                    "work",
                    int(work_id),
                )
            )
            return issues
        if not bool(work_row[1]):
            issues.append(
                RoyaltyReadinessIssue(
                    "warning",
                    "work_rights_not_verified",
                    f"Work '{work_row[0]}' is not marked rights verified.",
                    "work",
                    int(work_id),
                )
            )
        ownership_rows = self.conn.execute(
            """
            SELECT id, party_id, display_name, share_percent
            FROM WorkOwnershipInterests
            WHERE work_id=?
            ORDER BY id
            """,
            (int(work_id),),
        ).fetchall()
        if ownership_rows:
            shares = [_to_basis_points(row[3]) for row in ownership_rows if row[3] is not None]
            if shares and sum(value for value in shares if value is not None) != 10_000:
                issues.append(
                    RoyaltyReadinessIssue(
                        "error",
                        "work_ownership_split_not_100",
                        f"Work '{work_row[0]}' ownership split does not total 100%.",
                        "work",
                        int(work_id),
                    )
                )
            for row in ownership_rows:
                if row[1] is None:
                    issues.append(
                        RoyaltyReadinessIssue(
                            "error",
                            "work_ownership_payee_missing",
                            "Work ownership interest has no linked party.",
                            "work_ownership_interest",
                            int(row[0]),
                        )
                    )
            return issues

        contributor_rows = self.conn.execute(
            """
            SELECT id, party_id, display_name, share_percent
            FROM WorkContributors
            WHERE work_id=?
            ORDER BY id
            """,
            (int(work_id),),
        ).fetchall()
        if not contributor_rows:
            issues.append(
                RoyaltyReadinessIssue(
                    "error",
                    "work_has_no_contributors",
                    f"Work '{work_row[0]}' has no linked contributors or ownership interests.",
                    "work",
                    int(work_id),
                )
            )
            return issues
        shares = [_to_basis_points(row[3]) for row in contributor_rows if row[3] is not None]
        if shares and sum(value for value in shares if value is not None) != 10_000:
            issues.append(
                RoyaltyReadinessIssue(
                    "error",
                    "work_contributor_split_not_100",
                    f"Work '{work_row[0]}' contributor split does not total 100%.",
                    "work",
                    int(work_id),
                )
            )
        for row in contributor_rows:
            if row[1] is None:
                issues.append(
                    RoyaltyReadinessIssue(
                        "warning",
                        "work_contributor_party_missing",
                        "Work contributor has no linked party.",
                        "work_contributor",
                        int(row[0]),
                    )
                )
        return issues

    def _term_matches_event(
        self,
        term: ContractRoyaltyTermRecord,
        scopes: tuple[RoyaltyTermScopeRecord, ...],
        event: RoyaltySourceEventRecord,
    ) -> bool:
        if not term.active:
            return False
        if not scopes:
            return True
        for scope in scopes:
            if scope.scope_type == "work" and event.work_id == scope.scope_id:
                return True
            if scope.scope_type == "track" and event.track_id == scope.scope_id:
                return True
            if scope.scope_type == "release" and event.release_id == scope.scope_id:
                return True
            if scope.scope_type == "right" and self._event_matches_right(scope.scope_id, event):
                return True
        return False

    def _event_matches_right(self, right_id: int, event: RoyaltySourceEventRecord) -> bool:
        row = self.conn.execute(
            """
            SELECT work_id, track_id, release_id
            FROM RightsRecords
            WHERE id=?
            """,
            (int(right_id),),
        ).fetchone()
        if row is None:
            return False
        return any(
            (
                row[0] is not None and event.work_id == int(row[0]),
                row[1] is not None and event.track_id == int(row[1]),
                row[2] is not None and event.release_id == int(row[2]),
            )
        )

    def _matching_right_id(
        self,
        term: ContractRoyaltyTermRecord,
        event: RoyaltySourceEventRecord,
        context_right_ids: tuple[int, ...],
    ) -> int | None:
        if not context_right_ids:
            return None
        placeholders = ", ".join("?" for _ in context_right_ids)
        entity_clauses = []
        params: list[object] = list(context_right_ids)
        if event.work_id is not None:
            entity_clauses.append("work_id=?")
            params.append(int(event.work_id))
        if event.track_id is not None:
            entity_clauses.append("track_id=?")
            params.append(int(event.track_id))
        if event.release_id is not None:
            entity_clauses.append("release_id=?")
            params.append(int(event.release_id))
        if not entity_clauses:
            return None
        right_type = clean_text(term.right_type)
        if right_type:
            params.append(right_type)
        row = self.conn.execute(
            f"""
            SELECT id
            FROM RightsRecords
            WHERE id IN ({placeholders})
              AND ({" OR ".join(entity_clauses)})
              {"AND right_type=?" if right_type else ""}
            ORDER BY id
            LIMIT 1
            """,
            params,
        ).fetchone()
        return int(row[0]) if row else None

    def _attach_context_links(
        self,
        calculation_id: int,
        *,
        context: RoyaltyIntegrationContext,
        generated_lines: list[_GeneratedRoyaltyLine],
    ) -> None:
        line_rows = self.conn.execute(
            """
            SELECT id
            FROM RoyaltyCalculationLines
            WHERE calculation_id=?
            ORDER BY sort_order, id
            """,
            (int(calculation_id),),
        ).fetchall()
        if len(line_rows) != len(generated_lines):
            raise RuntimeError("Generated royalty line count does not match persisted lines.")
        with self.conn:
            self.conn.execute(
                """
                UPDATE RoyaltyCalculations
                SET contract_id=?,
                    context_snapshot_json=?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    int(context.contract_id),
                    json.dumps(context.to_dict(), sort_keys=True),
                    int(calculation_id),
                ),
            )
            for row, generated in zip(line_rows, generated_lines):
                line_id = int(row[0])
                self.conn.execute(
                    """
                    UPDATE RoyaltyCalculationLines
                    SET contract_id=?,
                        work_id=?,
                        track_id=?,
                        release_id=?,
                        right_id=?,
                        ownership_interest_type=?,
                        ownership_interest_id=?,
                        contract_royalty_term_id=?,
                        source_event_id=?
                    WHERE id=?
                    """,
                    (
                        int(context.contract_id),
                        generated.work_id,
                        generated.track_id,
                        generated.release_id,
                        generated.right_id,
                        generated.ownership_interest_type,
                        generated.ownership_interest_id,
                        int(generated.term.id),
                        int(generated.source_event.id),
                        line_id,
                    ),
                )
                self.conn.execute(
                    """
                    INSERT INTO RoyaltyCalculationSourceLinks(
                        calculation_id,
                        calculation_line_id,
                        source_event_id,
                        contract_id,
                        work_id,
                        track_id,
                        release_id,
                        right_id,
                        ownership_interest_type,
                        ownership_interest_id,
                        contract_royalty_term_id,
                        relation_type,
                        amount_minor,
                        currency
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'royalty_source', ?, ?)
                    """,
                    (
                        int(calculation_id),
                        line_id,
                        int(generated.source_event.id),
                        int(context.contract_id),
                        generated.work_id,
                        generated.track_id,
                        generated.release_id,
                        generated.right_id,
                        generated.ownership_interest_type,
                        generated.ownership_interest_id,
                        int(generated.term.id),
                        int(generated.payload.net_payable_minor),
                        generated.source_event.currency,
                    ),
                )

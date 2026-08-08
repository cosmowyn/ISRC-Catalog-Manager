"""Reversible history workflows for destructive Party actions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol, TypeVar

from isrc_manager.parties.models import PartyRecord
from isrc_manager.parties.service import PartyService

_MutationResult = TypeVar("_MutationResult")


class PartyHistoryPanel(Protocol):
    """Panel callback seam used by the Party controller."""

    delete_party_handler: Callable[[list[int]], object] | None
    merge_party_handler: Callable[[int, list[int]], object] | None


class PartyHistoryHost(Protocol):
    """Application services required by destructive Party history workflows."""

    party_service: PartyService | None

    def _run_snapshot_history_action(
        self,
        *,
        action_label: str,
        action_type: str,
        mutation: Callable[[], _MutationResult],
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        payload: dict[str, object] | None = None,
    ) -> _MutationResult: ...


def _normalized_party_ids(party_ids: Iterable[int]) -> list[int]:
    normalized: set[int] = set()
    for party_id in party_ids:
        value = int(party_id)
        if value > 0:
            normalized.add(value)
    return sorted(normalized)


def configure_party_history_handlers(
    panel: PartyHistoryPanel,
    app: PartyHistoryHost,
    *,
    party_label: Callable[[PartyRecord], str],
) -> None:
    """Route destructive Party panel actions through reversible history."""
    panel.delete_party_handler = lambda party_ids: delete_parties_with_history(
        app,
        party_ids,
        party_label=party_label,
    )
    panel.merge_party_handler = lambda primary_id, duplicate_ids: merge_parties_with_history(
        app,
        primary_id,
        duplicate_ids,
        party_label=party_label,
    )


def delete_parties_with_history(
    app: PartyHistoryHost,
    party_ids: Iterable[int],
    *,
    party_label: Callable[[PartyRecord], str],
) -> int:
    """Delete one or more Parties as one reversible user action."""
    service = app.party_service
    if service is None:
        raise ValueError("Party service is unavailable.")

    normalized_ids = _normalized_party_ids(party_ids)
    if not normalized_ids:
        return 0
    records = [service.fetch_party(party_id) for party_id in normalized_ids]
    labels = [party_label(record) for record in records if record is not None]
    action_label = (
        f"Delete Party: {labels[0]}"
        if len(normalized_ids) == 1 and labels
        else f"Delete Parties: {len(normalized_ids)}"
    )

    def mutation() -> int:
        for party_id in normalized_ids:
            service.delete_party(party_id)
        return len(normalized_ids)

    return int(
        app._run_snapshot_history_action(
            action_label=action_label,
            action_type="party.delete",
            entity_type="Party",
            entity_id=(normalized_ids[0] if len(normalized_ids) == 1 else "batch"),
            payload={
                "party_ids": normalized_ids,
                "party_labels": labels,
                "count": len(normalized_ids),
            },
            mutation=mutation,
        )
    )


def merge_parties_with_history(
    app: PartyHistoryHost,
    primary_party_id: int,
    duplicate_party_ids: Iterable[int],
    *,
    party_label: Callable[[PartyRecord], str],
) -> PartyRecord:
    """Merge duplicate Parties and all dependent links as one reversible action."""
    service = app.party_service
    if service is None:
        raise ValueError("Party service is unavailable.")

    primary_id = int(primary_party_id)
    duplicate_ids = [
        party_id
        for party_id in _normalized_party_ids(duplicate_party_ids)
        if party_id != primary_id
    ]
    primary = service.fetch_party(primary_id)
    if primary is None:
        raise ValueError("Primary party not found.")
    if not duplicate_ids:
        return primary

    duplicate_records = [service.fetch_party(party_id) for party_id in duplicate_ids]
    duplicate_labels = [party_label(record) for record in duplicate_records if record is not None]
    primary_label = party_label(primary)
    result = app._run_snapshot_history_action(
        action_label=f"Merge Parties into: {primary_label}",
        action_type="party.merge",
        entity_type="Party",
        entity_id=primary_id,
        payload={
            "primary_party_id": primary_id,
            "primary_party_label": primary_label,
            "duplicate_party_ids": duplicate_ids,
            "duplicate_party_labels": duplicate_labels,
            "count": len(duplicate_ids),
        },
        mutation=lambda: service.merge_parties(primary_id, duplicate_ids),
    )
    if not isinstance(result, PartyRecord):
        raise RuntimeError("Party merge did not return the merged Party record.")
    return result

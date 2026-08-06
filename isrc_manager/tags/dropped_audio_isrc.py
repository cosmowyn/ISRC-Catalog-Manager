"""Canonical ISRC generation and reservation for dropped-audio imports."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QDate

from isrc_manager.domain.codes import is_valid_isrc_compact_or_iso, to_compact_isrc

if TYPE_CHECKING:
    from isrc_manager.services.tracks import TrackCreatePayload


@dataclass(frozen=True, slots=True)
class DroppedAudioIsrcReservation:
    """Result of reserving every ISRC required by one dropped-audio batch."""

    isrcs: tuple[str, ...] = ()
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error_message is None


def assign_generated_isrc_candidates(
    app: Any,
    rows: list[dict[str, object]],
    *,
    supplied_compacts: Iterable[str],
) -> list[str]:
    """Fill blank rows with batch-unique candidates when generation is configured."""
    generation_state = "disabled"
    generation_state_reader = getattr(app, "_isrc_generation_state", None)
    if callable(generation_state_reader):
        generation_state, _generation_message = generation_state_reader()
    if generation_state != "ready":
        return []

    errors: list[str] = []
    reserved_compacts = set(supplied_compacts)
    for index, row in enumerate(rows, start=1):
        if row.get("iso_isrc"):
            continue
        release_qdate = QDate.fromString(str(row.get("release_date") or ""), "yyyy-MM-dd")
        generated_isrc = app._next_generated_isrc(
            release_date=release_qdate if release_qdate.isValid() else None,
            use_release_year=False,
            reserved_compacts=reserved_compacts,
        )
        generated_compact = to_compact_isrc(generated_isrc)
        if not generated_compact or not is_valid_isrc_compact_or_iso(generated_isrc):
            errors.append(
                f"Row {index}: no free ISRC sequence is currently available for this import."
            )
            continue
        if generated_compact in reserved_compacts or app.is_isrc_taken_normalized(generated_isrc):
            errors.append(f"Row {index}: generated ISRC {generated_isrc} is already in use.")
            continue
        reserved_compacts.add(generated_compact)
        row["iso_isrc"] = generated_isrc
    return errors


def release_dropped_audio_isrcs(app: Any, isrcs: Iterable[str]) -> None:
    """Release temporary cross-profile claims created for a failed import batch."""
    release_claim = getattr(app, "_release_reserved_isrc_claim", None)
    if not callable(release_claim):
        return
    for isrc in isrcs:
        release_claim(isrc)


def reserve_dropped_audio_isrcs(
    app: Any,
    payloads: Sequence[TrackCreatePayload],
    selected_rows: Sequence[dict[str, object]],
    *,
    parent_widget: Any,
) -> DroppedAudioIsrcReservation:
    """Atomically reserve supplied and generated codes before queuing a write."""
    reserved_isrcs: list[str] = []
    reserved_compacts: set[str] = set()
    for index, payload in enumerate(payloads):
        selected_row = selected_rows[index] if index < len(selected_rows) else {}
        if not str(selected_row.get("isrc") or "").strip():
            continue
        compact_isrc = to_compact_isrc(str(getattr(payload, "isrc", "") or ""))
        if compact_isrc:
            reserved_compacts.add(compact_isrc)

    reserve_claim = getattr(app, "_reserve_isrc_claim_for_profile", None)
    claim_generated_isrc = getattr(app, "_claim_next_generated_isrc", None)
    if not callable(reserve_claim) and not callable(claim_generated_isrc):
        return DroppedAudioIsrcReservation()

    for index, payload in enumerate(payloads):
        isrc = str(getattr(payload, "isrc", "") or "").strip()
        if not isrc:
            continue
        selected_row = selected_rows[index] if index < len(selected_rows) else {}
        supplied_isrc = str(selected_row.get("isrc") or "").strip()
        if not supplied_isrc and callable(claim_generated_isrc):
            release_qdate = QDate.fromString(
                str(selected_row.get("release_date") or ""),
                "yyyy-MM-dd",
            )
            isrc = claim_generated_isrc(
                release_date=release_qdate if release_qdate.isValid() else None,
                use_release_year=False,
                reserved_compacts=set(reserved_compacts),
                track_title=str(getattr(payload, "track_title", "") or ""),
                parent_widget=parent_widget,
            )
            compact_isrc = to_compact_isrc(isrc)
            if (
                not compact_isrc
                or compact_isrc in reserved_compacts
                or not is_valid_isrc_compact_or_iso(isrc)
            ):
                release_dropped_audio_isrcs(app, reserved_isrcs)
                return DroppedAudioIsrcReservation(
                    error_message=(
                        "No free canonical ISRC could be reserved for the dropped track batch. "
                        "No tracks were queued."
                    )
                )
            payload.isrc = isrc
            reserved_isrcs.append(isrc)
            reserved_compacts.add(compact_isrc)
            continue
        if not callable(reserve_claim):
            continue
        if not reserve_claim(
            isrc,
            track_title=str(getattr(payload, "track_title", "") or ""),
            claim_kind="audio_drop_import",
            parent_widget=parent_widget,
        ):
            release_dropped_audio_isrcs(app, reserved_isrcs)
            # The registry helper already displayed the actionable conflict.
            return DroppedAudioIsrcReservation(error_message="")
        reserved_isrcs.append(isrc)
        compact_isrc = to_compact_isrc(isrc)
        if compact_isrc:
            reserved_compacts.add(compact_isrc)

    return DroppedAudioIsrcReservation(isrcs=tuple(reserved_isrcs))

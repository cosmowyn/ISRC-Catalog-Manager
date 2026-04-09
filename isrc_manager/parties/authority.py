"""Shared Party artist authority helpers."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal


class PartyAuthorityNotifier(QObject):
    """Broadcasts Party authority changes to any open selector surface."""

    changed = Signal()


_NOTIFIER: PartyAuthorityNotifier | None = None


def party_authority_notifier() -> PartyAuthorityNotifier:
    global _NOTIFIER
    if _NOTIFIER is None:
        _NOTIFIER = PartyAuthorityNotifier()
    return _NOTIFIER


def emit_party_authority_changed() -> None:
    party_authority_notifier().changed.emit()


def artist_display_name_from_values(
    artist_name: str | None,
    display_name: str | None,
    company_name: str | None,
    legal_name: str | None,
    *,
    fallback_id: int | None = None,
) -> str:
    for value in (artist_name, display_name, company_name, legal_name):
        clean = str(value or "").strip()
        if clean:
            return clean
    if fallback_id is not None:
        return f"Party #{int(fallback_id)}"
    return ""


def artist_primary_label(record: Any) -> str:
    return artist_display_name_from_values(
        getattr(record, "artist_name", None),
        getattr(record, "display_name", None),
        getattr(record, "company_name", None),
        getattr(record, "legal_name", None),
        fallback_id=getattr(record, "id", None),
    )


def artist_choice_label(record: Any) -> str:
    primary = artist_primary_label(record)
    legal_name = str(getattr(record, "legal_name", "") or "").strip()
    if legal_name and primary and legal_name.casefold() != primary.casefold():
        return f"{primary} ({legal_name})"
    return primary or legal_name

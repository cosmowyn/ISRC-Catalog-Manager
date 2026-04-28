"""Data models for Bandcamp promo-code sheet management."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromoCodeSheetRecord:
    id: int
    code_set_name: str
    album: str | None
    bandcamp_date_created: str | None
    bandcamp_date_exported: str | None
    quantity_created: int | None
    quantity_redeemed_to_date: int | None
    redeem_url: str | None
    source_filename: str | None
    source_path: str | None
    source_sha256: str | None
    code_sequence_sha256: str
    profile_name: str | None
    imported_at: str | None
    updated_at: str | None
    total_codes: int
    redeemed_codes: int

    @property
    def available_codes(self) -> int:
        return max(0, int(self.total_codes or 0) - int(self.redeemed_codes or 0))

    @property
    def display_name(self) -> str:
        label = str(self.code_set_name or "").strip() or f"Promo Sheet #{int(self.id)}"
        album = str(self.album or "").strip()
        if album:
            return f"{label} - {album}"
        return label


@dataclass(frozen=True, slots=True)
class PromoCodeRecord:
    id: int
    sheet_id: int
    code: str
    sort_order: int
    redeemed: bool
    recipient_name: str | None
    recipient_email: str | None
    ledger_notes: str | None
    provided_at: str | None
    redeemed_at: str | None
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class ParsedBandcampPromoCsv:
    code_set_name: str
    album: str | None
    bandcamp_date_created: str | None
    bandcamp_date_exported: str | None
    quantity_created: int | None
    quantity_redeemed_to_date: int | None
    redeem_url: str | None
    codes: tuple[str, ...]
    source_path: str
    source_filename: str
    source_sha256: str
    code_sequence_sha256: str


@dataclass(frozen=True, slots=True)
class PromoCodeImportResult:
    sheet_id: int
    sheet_name: str
    album: str | None
    total_codes: int
    inserted_codes: int
    updated_existing_sheet: bool
    source_path: str
    active_codes: int = 0
    marked_redeemed_codes: int = 0
    reactivated_codes: int = 0

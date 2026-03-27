"""Shared data models for catalog exchange adapters."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ExchangeInspection:
    file_path: str
    format_name: str
    headers: list[str]
    preview_rows: list[dict[str, object]]
    suggested_mapping: dict[str, str]
    warnings: list[str] = field(default_factory=list)
    resolved_delimiter: str | None = None


@dataclass(slots=True)
class ExchangeImportOptions:
    mode: str = "dry_run"
    match_by_internal_id: bool = True
    match_by_isrc: bool = True
    match_by_upc_title: bool = True
    heuristic_match: bool = False
    create_missing_custom_fields: bool = True
    skip_targets: list[str] = field(default_factory=list)
    preview_apply_mode: str | None = None


@dataclass(slots=True)
class ExchangeImportReport:
    format_name: str
    mode: str
    passed: int
    failed: int
    skipped: int
    warnings: list[str]
    duplicates: list[str]
    unknown_fields: list[str]
    evaluated_mode: str | None = None
    would_create_tracks: int = 0
    would_update_tracks: int = 0
    created_tracks: list[int] = field(default_factory=list)
    updated_tracks: list[int] = field(default_factory=list)
    repair_queue_entry_ids: list[int] = field(default_factory=list)

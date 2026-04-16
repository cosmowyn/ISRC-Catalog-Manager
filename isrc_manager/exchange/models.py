"""Shared data models for exchange adapters and identifier review."""

from __future__ import annotations

from dataclasses import dataclass, field

from isrc_manager.code_registry import BUILTIN_CATEGORY_CATALOG_NUMBER


@dataclass(slots=True)
class ExchangeIdentifierClassificationOutcome:
    row_index: int
    field_name: str
    category_system_key: str
    value: str
    classification: str
    outcome: str
    category_label: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class ExchangeInspection:
    file_path: str
    format_name: str
    headers: list[str]
    preview_rows: list[dict[str, object]]
    suggested_mapping: dict[str, str]
    warnings: list[str] = field(default_factory=list)
    resolved_delimiter: str | None = None
    identifier_review_rows: list["ExchangeIdentifierReviewRow"] = field(default_factory=list)


@dataclass(slots=True)
class ExchangeIdentifierReviewRow:
    review_key: str
    row_index: int
    source_header: str
    target_field_name: str
    suggested_category_system_key: str
    value: str
    reason: str | None = None


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
    preserve_source_package_identity: bool = False
    identifier_overrides: dict[str, str] = field(default_factory=dict)


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
    source_track_id_map: dict[int, int] = field(default_factory=dict)
    source_release_id_map: dict[int, int] = field(default_factory=dict)
    identifier_totals: dict[str, dict[str, int]] = field(default_factory=dict)
    identifier_classifications: list[ExchangeIdentifierClassificationOutcome] = field(
        default_factory=list
    )

    @staticmethod
    def _count_from_totals(
        totals: dict[str, dict[str, int]],
        category_system_key: str,
        bucket: str,
    ) -> int:
        category_counts = totals.get(category_system_key) or {}
        return int(category_counts.get(bucket) or 0)

    @property
    def internal_identifiers(self) -> int:
        return sum(
            int(category_counts.get("internal") or 0)
            for category_counts in self.identifier_totals.values()
        )

    @property
    def external_identifiers(self) -> int:
        return sum(
            int(category_counts.get("external") or 0)
            for category_counts in self.identifier_totals.values()
        )

    @property
    def mismatched_identifiers(self) -> int:
        return sum(
            int(category_counts.get("mismatch") or 0)
            for category_counts in self.identifier_totals.values()
        )

    @property
    def skipped_identifiers(self) -> int:
        return sum(
            int(category_counts.get("skipped") or 0)
            for category_counts in self.identifier_totals.values()
        )

    @property
    def merged_identifiers(self) -> int:
        return sum(
            int(category_counts.get("merged") or 0)
            for category_counts in self.identifier_totals.values()
        )

    @property
    def conflicted_identifiers(self) -> int:
        return sum(
            int(category_counts.get("conflicted") or 0)
            for category_counts in self.identifier_totals.values()
        )

    @property
    def internal_catalog_identifiers(self) -> int:
        return self._count_from_totals(
            self.identifier_totals,
            BUILTIN_CATEGORY_CATALOG_NUMBER,
            "internal",
        )

    @property
    def external_catalog_identifiers(self) -> int:
        return self._count_from_totals(
            self.identifier_totals,
            BUILTIN_CATEGORY_CATALOG_NUMBER,
            "external",
        )

    @property
    def mismatched_catalog_identifiers(self) -> int:
        return self._count_from_totals(
            self.identifier_totals,
            BUILTIN_CATEGORY_CATALOG_NUMBER,
            "mismatch",
        )

    @property
    def skipped_catalog_identifiers(self) -> int:
        return self._count_from_totals(
            self.identifier_totals,
            BUILTIN_CATEGORY_CATALOG_NUMBER,
            "skipped",
        )

    @property
    def merged_catalog_identifiers(self) -> int:
        return self._count_from_totals(
            self.identifier_totals,
            BUILTIN_CATEGORY_CATALOG_NUMBER,
            "merged",
        )

    @property
    def conflicted_catalog_identifiers(self) -> int:
        return self._count_from_totals(
            self.identifier_totals,
            BUILTIN_CATEGORY_CATALOG_NUMBER,
            "conflicted",
        )

    @property
    def catalog_classifications(self) -> list[ExchangeIdentifierClassificationOutcome]:
        return [
            item
            for item in self.identifier_classifications
            if item.category_system_key == BUILTIN_CATEGORY_CATALOG_NUMBER
        ]


ExchangeCatalogClassificationOutcome = ExchangeIdentifierClassificationOutcome

"""Models for global search and relationship exploration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class GlobalSearchResult:
    entity_type: str
    entity_id: int
    title: str
    subtitle: str
    status: str | None = None
    match_text: str | None = None


@dataclass(slots=True)
class SavedSearchRecord:
    id: int
    name: str
    query_text: str
    entity_types: list[str]


@dataclass(slots=True)
class RelationshipSection:
    section_title: str
    results: list[GlobalSearchResult]

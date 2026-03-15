"""Helpers for bulk edit UI state and save decisions."""

from __future__ import annotations

from typing import Any, Iterable


MIXED_VALUE = object()


def shared_bulk_value(values: Iterable[Any]) -> Any:
    items = list(values)
    if not items:
        return ""
    first = items[0]
    for item in items[1:]:
        if item != first:
            return MIXED_VALUE
    return first


def should_apply_bulk_change(
    *,
    mixed: bool,
    modified: bool,
    initial_value: Any,
    final_value: Any,
) -> bool:
    if not modified:
        return False
    if mixed:
        return True
    return final_value != initial_value

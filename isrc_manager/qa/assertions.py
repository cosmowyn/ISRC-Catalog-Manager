"""Reusable assertions for UI PQ tests."""

from __future__ import annotations

from pathlib import Path

from .inventory import UIInventoryItem


def require_artifact(path: Path) -> Path:
    if not path.exists():
        raise AssertionError(f"Expected UI PQ artifact does not exist: {path}")
    if path.stat().st_size <= 0:
        raise AssertionError(f"Expected UI PQ artifact is empty: {path}")
    return path


def require_inventory_area(inventory: list[UIInventoryItem], ui_area: str) -> None:
    if not any(item.ui_area == ui_area for item in inventory):
        raise AssertionError(f"Expected discovered UI inventory area: {ui_area}")


def require_evidence_status(events: list[object], test_id: str, status: str = "passed") -> None:
    for event in events:
        if getattr(event, "test_id", "") == test_id and getattr(event, "status", "") == status:
            return
    raise AssertionError(f"Expected evidence event {test_id!r} with status {status!r}")

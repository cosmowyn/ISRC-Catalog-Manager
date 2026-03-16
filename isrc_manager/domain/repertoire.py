"""Shared helpers for the repertoire, rights, and contract domain."""

from __future__ import annotations

import json
from datetime import date


def clean_text(value: object | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def clean_text_list(values: list[object] | tuple[object, ...] | None) -> list[str]:
    cleaned: list[str] = []
    for value in values or []:
        text = clean_text(value)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def dumps_json(value: object | None) -> str | None:
    if value in (None, "", [], {}, ()):
        return None
    return json.dumps(value, ensure_ascii=True)


def loads_json_list(value: object | None) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return [line.strip() for line in text.splitlines() if line.strip()]
    if isinstance(parsed, list):
        return clean_text_list(parsed)
    return []


def normalized_name(value: object | None) -> str:
    return " ".join(str(value or "").split()).casefold()


def parse_iso_date(value: object | None) -> date | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def normalized_territory(value: object | None) -> str:
    return normalized_name(value)


def ranges_overlap(
    start_a: object | None,
    end_a: object | None,
    perpetual_a: bool,
    start_b: object | None,
    end_b: object | None,
    perpetual_b: bool,
) -> bool:
    start_left = parse_iso_date(start_a) or date.min
    start_right = parse_iso_date(start_b) or date.min
    end_left = date.max if perpetual_a else (parse_iso_date(end_a) or date.max)
    end_right = date.max if perpetual_b else (parse_iso_date(end_b) or date.max)
    return start_left <= end_right and start_right <= end_left

"""Shared validation helpers for audio tag payloads."""

from __future__ import annotations

from dataclasses import fields as dataclass_fields

from .models import AudioTagData


def has_exportable_catalog_tag_data(tag_data: AudioTagData) -> bool:
    for field in dataclass_fields(AudioTagData):
        if field.name in {"raw_fields", "warnings"}:
            continue
        value = getattr(tag_data, field.name)
        if value not in (None, "", [], {}, ()):
            return True
    return False

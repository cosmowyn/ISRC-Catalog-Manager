"""Adapter interfaces for conversion template and source formats."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import (
    ConversionExportResult,
    ConversionPreview,
    ConversionSourceProfile,
    ConversionTemplateProfile,
)


class TemplateAdapter(ABC):
    format_name: str

    @abstractmethod
    def inspect_template(self, path: str | Path) -> ConversionTemplateProfile:
        raise NotImplementedError

    @abstractmethod
    def select_scope(
        self,
        profile: ConversionTemplateProfile,
        scope_key: str,
    ) -> ConversionTemplateProfile:
        raise NotImplementedError

    @abstractmethod
    def build_preview(
        self,
        profile: ConversionTemplateProfile,
        rendered_field_rows: list[dict[str, object]],
    ) -> tuple[
        tuple[str, ...],
        tuple[tuple[str, ...], ...],
        str,
        tuple[str, ...],
        dict[str, object],
    ]:
        raise NotImplementedError

    @abstractmethod
    def export_preview(
        self,
        preview: ConversionPreview,
        output_path: str | Path,
        *,
        progress_callback=None,
    ) -> ConversionExportResult:
        raise NotImplementedError


class SourceAdapter(ABC):
    format_name: str

    @abstractmethod
    def inspect_source(
        self,
        source,
        *,
        preferred_csv_delimiter: str | None = None,
    ) -> ConversionSourceProfile:
        raise NotImplementedError

    @abstractmethod
    def select_scope(
        self,
        profile: ConversionSourceProfile,
        scope_key: str,
    ) -> ConversionSourceProfile:
        raise NotImplementedError

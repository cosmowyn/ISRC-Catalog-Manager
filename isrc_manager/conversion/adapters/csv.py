"""CSV template and source adapters for conversion."""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

from ..mapping import normalize_field_name
from ..models import (
    REQUIRED_STATUS_OPTIONAL,
    REQUIRED_STATUS_REQUIRED,
    SOURCE_MODE_FILE,
    ConversionExportResult,
    ConversionSourceProfile,
    ConversionTargetField,
    ConversionTemplateProfile,
)
from .base import SourceAdapter, TemplateAdapter

_CSV_DELIMITERS = ",;\t|"


def _column_letter(index: int) -> str:
    letters = ""
    value = int(index)
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters or "A"


def _sniff_dialect(text: str, *, preferred_delimiter: str | None = None):
    if preferred_delimiter:

        class _Preferred(csv.Dialect):
            delimiter = preferred_delimiter
            quotechar = '"'
            escapechar = None
            doublequote = True
            skipinitialspace = False
            lineterminator = "\n"
            quoting = csv.QUOTE_MINIMAL

        return _Preferred
    try:
        return csv.Sniffer().sniff(text or "", delimiters=_CSV_DELIMITERS)
    except csv.Error:
        return csv.excel


def _rows_from_text(
    text: str,
    *,
    preferred_delimiter: str | None = None,
) -> tuple[list[list[str]], csv.Dialect]:
    dialect = _sniff_dialect(text[:4096], preferred_delimiter=preferred_delimiter)
    reader = csv.reader(StringIO(text), dialect=dialect)
    rows = [list(row) for row in reader]
    return rows, dialect


def _load_rows(
    path: Path, *, preferred_delimiter: str | None = None
) -> tuple[list[list[str]], csv.Dialect]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return _rows_from_text(text, preferred_delimiter=preferred_delimiter)


def _load_rows_from_bytes(
    data: bytes, *, preferred_delimiter: str | None = None
) -> tuple[list[list[str]], csv.Dialect]:
    text = bytes(data).decode("utf-8-sig", errors="replace")
    return _rows_from_text(text, preferred_delimiter=preferred_delimiter)


def _first_non_empty_row(rows: list[list[str]]) -> int:
    for index, row in enumerate(rows):
        if any(str(value or "").strip() for value in row):
            return index
    raise ValueError("The CSV file does not contain a non-empty header row.")


def _sample_region(rows: list[list[str]], header_row_index: int) -> tuple[int, int]:
    sample_start = header_row_index + 1
    if sample_start >= len(rows):
        return sample_start, sample_start - 1
    sample_end = len(rows) - 1
    for index in range(sample_start, len(rows)):
        if not any(str(value or "").strip() for value in rows[index]):
            sample_end = index - 1
            break
    return sample_start, sample_end


class CsvTemplateAdapter(TemplateAdapter):
    format_name = "csv"

    def inspect_template(self, path: str | Path) -> ConversionTemplateProfile:
        template_path = Path(path)
        rows, dialect = _load_rows(template_path)
        header_row_index = _first_non_empty_row(rows)
        header_row = rows[header_row_index]
        sample_start, sample_end = _sample_region(rows, header_row_index)
        target_fields: list[ConversionTargetField] = []
        for column_index, header in enumerate(header_row, start=1):
            clean_header = str(header or "").strip()
            if not clean_header:
                continue
            required_status = (
                REQUIRED_STATUS_REQUIRED if clean_header.endswith("*") else REQUIRED_STATUS_OPTIONAL
            )
            target_fields.append(
                ConversionTargetField(
                    field_key=normalize_field_name(clean_header),
                    display_name=clean_header,
                    location=f"CSV!{_column_letter(column_index)}{header_row_index + 1}",
                    required_status=required_status,
                    kind="column",
                    metadata={"column_index": column_index - 1},
                )
            )
        signature = self._template_signature(target_fields)
        return ConversionTemplateProfile(
            template_path=template_path,
            format_name=self.format_name,
            output_suffix=template_path.suffix.lower() or ".csv",
            structure_label=f"CSV row template ({template_path.name})",
            target_fields=tuple(target_fields),
            template_signature=signature,
            chosen_scope="csv",
            adapter_state={
                "dialect": {
                    "delimiter": getattr(dialect, "delimiter", ","),
                    "quotechar": getattr(dialect, "quotechar", '"'),
                    "quoting": int(getattr(dialect, "quoting", csv.QUOTE_MINIMAL)),
                    "lineterminator": getattr(dialect, "lineterminator", "\n"),
                },
                "header_row_index": header_row_index,
                "sample_start": sample_start,
                "sample_end": sample_end,
                "header_row": list(header_row),
            },
        )

    def select_scope(
        self,
        profile: ConversionTemplateProfile,
        scope_key: str,
    ) -> ConversionTemplateProfile:
        del scope_key
        return profile

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
        headers = tuple(field.display_name for field in profile.target_fields)
        rows: list[tuple[str, ...]] = []
        for rendered in rendered_field_rows:
            rows.append(
                tuple(str(rendered.get(field.field_key, "")) for field in profile.target_fields)
            )
        return headers, tuple(rows), "", (), {}

    def export_preview(
        self,
        preview,
        output_path: str | Path,
        *,
        progress_callback=None,
    ) -> ConversionExportResult:
        template_path = preview.template_profile.template_path
        if preview.template_profile.template_bytes is not None:
            rows, dialect = _load_rows_from_bytes(preview.template_profile.template_bytes)
        else:
            rows, dialect = _load_rows(template_path)
        header_row_index = int(preview.template_profile.adapter_state.get("header_row_index", 0))
        sample_start = int(
            preview.template_profile.adapter_state.get("sample_start", header_row_index + 1)
        )
        sample_end = int(preview.template_profile.adapter_state.get("sample_end", sample_start - 1))
        sample_break_index = sample_end + 1
        output_rows = rows[: header_row_index + 1]
        for rendered in preview.rendered_rows:
            rendered_row = list(preview.template_profile.adapter_state.get("header_row") or [])
            if len(rendered_row) < len(rendered):
                rendered_row.extend("" for _ in range(len(rendered) - len(rendered_row)))
            for field, value in zip(preview.template_profile.target_fields, rendered):
                column_index = int(field.metadata.get("column_index", 0))
                while column_index >= len(rendered_row):
                    rendered_row.append("")
                rendered_row[column_index] = str(value)
            output_rows.append(rendered_row)
        if 0 <= sample_break_index < len(rows):
            output_rows.extend(rows[sample_break_index:])
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if callable(progress_callback):
            progress_callback(20, 100, "Preparing CSV conversion export...")
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(
                handle,
                delimiter=getattr(dialect, "delimiter", ","),
                quotechar=getattr(dialect, "quotechar", '"'),
                quoting=int(getattr(dialect, "quoting", csv.QUOTE_MINIMAL)),
                lineterminator=getattr(dialect, "lineterminator", "\n"),
            )
            for row in output_rows:
                writer.writerow(row)
        if callable(progress_callback):
            progress_callback(90, 100, "CSV conversion export written.")
        return ConversionExportResult(
            output_path=target,
            target_format=self.format_name,
            exported_row_count=len(preview.rendered_rows),
            summary_lines=(
                f"Template: {template_path.name}",
                f"Rows written: {len(preview.rendered_rows)}",
            ),
        )

    @staticmethod
    def _template_signature(target_fields: list[ConversionTargetField]) -> str:
        field_ids = ",".join(field.field_key for field in target_fields)
        return f"csv|csv|{field_ids}"


class CsvSourceAdapter(SourceAdapter):
    format_name = "csv"

    def inspect_source(
        self,
        source,
        *,
        preferred_csv_delimiter: str | None = None,
    ) -> ConversionSourceProfile:
        source_path = Path(source)
        rows, dialect = _load_rows(source_path, preferred_delimiter=preferred_csv_delimiter)
        header_row_index = _first_non_empty_row(rows)
        header_row = [str(value or "").strip() for value in rows[header_row_index]]
        row_dicts: list[dict[str, object]] = []
        for row in rows[header_row_index + 1 :]:
            if not any(str(value or "").strip() for value in row):
                continue
            row_dicts.append(
                {
                    header_row[index]: (row[index] if index < len(row) else "")
                    for index in range(len(header_row))
                    if header_row[index]
                }
            )
        resolved_delimiter = str(getattr(dialect, "delimiter", ",") or ",")
        return ConversionSourceProfile(
            source_mode=SOURCE_MODE_FILE,
            format_name=self.format_name,
            source_label=str(source_path),
            source_path=str(source_path),
            headers=tuple(header for header in header_row if header),
            rows=tuple(row_dicts),
            preview_rows=tuple(row_dicts[:10]),
            adapter_state={"header_row_index": header_row_index},
            resolved_delimiter=resolved_delimiter,
        )

    def select_scope(
        self,
        profile: ConversionSourceProfile,
        scope_key: str,
    ) -> ConversionSourceProfile:
        del scope_key
        return profile

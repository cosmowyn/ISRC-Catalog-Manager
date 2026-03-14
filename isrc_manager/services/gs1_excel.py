"""Excel-first GS1 export implementation using verified official workbooks."""

from __future__ import annotations

from copy import copy
from pathlib import Path

from .gs1_mapping import localize_export_value
from .gs1_models import GS1ExportResult, GS1PreparedRecord, GS1TemplateProfile


def _load_openpyxl():
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - exercised by UI on systems without the dependency
        from .gs1_models import GS1DependencyError

        raise GS1DependencyError(
            "GS1 workbook export requires the 'openpyxl' package to be installed."
        ) from exc
    return load_workbook


class GS1ExcelExportService:
    """Writes canonical GS1 data into the detected export sheet of an official workbook."""

    def export(
        self,
        template_profile: GS1TemplateProfile,
        records: list[GS1PreparedRecord],
        output_path: str | Path,
    ) -> GS1ExportResult:
        if not records:
            raise ValueError("At least one GS1 record is required for export")

        load_workbook = _load_openpyxl()
        workbook = load_workbook(
            filename=str(template_profile.workbook_path),
            read_only=False,
            data_only=False,
            keep_vba=template_profile.workbook_path.suffix.lower() == ".xlsm",
        )
        worksheet = workbook[template_profile.sheet_name]
        start_row = self._find_start_row(worksheet, template_profile)
        style_template_row = template_profile.header_row + 1 if worksheet.max_row >= template_profile.header_row + 1 else None

        row_numbers: list[int] = []
        for offset, record in enumerate(records, start=1):
            row_number = start_row + offset - 1
            if style_template_row is not None and row_number > worksheet.max_row:
                self._clone_row_style(worksheet, style_template_row, row_number)
            self._write_record_row(
                worksheet,
                row_number=row_number,
                template_profile=template_profile,
                prepared_record=record,
                sequence_number=offset,
            )
            row_numbers.append(row_number)

        final_output_path = Path(output_path)
        final_output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(str(final_output_path))
        return GS1ExportResult(
            output_path=final_output_path,
            exported_count=len(records),
            sheet_name=template_profile.sheet_name,
            row_numbers=row_numbers,
        )

    def _find_start_row(self, worksheet, template_profile: GS1TemplateProfile) -> int:
        mapped_columns = list(template_profile.column_map.values())
        row_number = template_profile.header_row + 1
        while row_number <= max(worksheet.max_row, template_profile.header_row + 1):
            if all(self._is_blank(worksheet.cell(row=row_number, column=column_index).value) for column_index in mapped_columns):
                return row_number
            row_number += 1
        return max(worksheet.max_row + 1, template_profile.header_row + 1)

    @staticmethod
    def _is_blank(value) -> bool:
        return value is None or str(value).strip() == ""

    def _clone_row_style(self, worksheet, source_row: int, target_row: int) -> None:
        if source_row <= 0 or source_row > worksheet.max_row or target_row <= worksheet.max_row:
            return
        for column_index in range(1, worksheet.max_column + 1):
            source_cell = worksheet.cell(row=source_row, column=column_index)
            target_cell = worksheet.cell(row=target_row, column=column_index)
            if source_cell.has_style:
                target_cell._style = copy(source_cell._style)
            if source_cell.number_format:
                target_cell.number_format = source_cell.number_format
            if source_cell.font:
                target_cell.font = copy(source_cell.font)
            if source_cell.fill:
                target_cell.fill = copy(source_cell.fill)
            if source_cell.border:
                target_cell.border = copy(source_cell.border)
            if source_cell.alignment:
                target_cell.alignment = copy(source_cell.alignment)
            if source_cell.protection:
                target_cell.protection = copy(source_cell.protection)
        source_dimension = worksheet.row_dimensions.get(source_row)
        if source_dimension is not None:
            worksheet.row_dimensions[target_row].height = source_dimension.height
            worksheet.row_dimensions[target_row].hidden = source_dimension.hidden

    def _write_record_row(
        self,
        worksheet,
        *,
        row_number: int,
        template_profile: GS1TemplateProfile,
        prepared_record: GS1PreparedRecord,
        sequence_number: int,
    ) -> None:
        metadata = prepared_record.metadata
        values = {
            "gtin_request_number": str(sequence_number),
            "status": metadata.status,
            "product_classification": metadata.product_classification,
            "consumer_unit_flag": metadata.consumer_unit_flag,
            "packaging_type": metadata.packaging_type,
            "target_market": metadata.target_market,
            "product_description": metadata.product_description,
            "language": metadata.language,
            "brand": metadata.brand,
            "subbrand": metadata.subbrand,
            "quantity": metadata.quantity,
            "unit": metadata.unit,
            "image_url": metadata.image_url,
        }
        for field_name, column_index in template_profile.column_map.items():
            if field_name not in values:
                continue
            worksheet.cell(
                row=row_number,
                column=column_index,
                value=localize_export_value(field_name, values[field_name], template_profile.locale_hint),
            )


"""Workbook verification for user-supplied official GS1 Excel templates."""

from __future__ import annotations

from pathlib import Path

from .gs1_mapping import (
    detect_template_locale,
    missing_core_template_fields,
    normalize_gs1_text,
    optional_template_fields,
    resolve_header_row,
)
from .gs1_models import GS1TemplateCandidate, GS1TemplateProfile, GS1TemplateVerificationError


def _load_openpyxl():
    try:
        from openpyxl import load_workbook
        from openpyxl.utils.exceptions import InvalidFileException
    except ImportError as exc:  # pragma: no cover - exercised by UI on systems without the dependency
        from .gs1_models import GS1DependencyError

        raise GS1DependencyError(
            "GS1 workbook support requires the 'openpyxl' package to be installed."
        ) from exc
    return load_workbook, InvalidFileException


class GS1TemplateVerificationService:
    """Verifies a workbook by scanning sheets and scoring likely GS1 export headers."""

    ALLOWED_SUFFIXES = {".xlsx", ".xlsm", ".xltx", ".xltm"}
    MAX_SCAN_ROWS = 25
    MAX_SCAN_COLUMNS = 40
    KEYWORD_MARKERS = (
        "gs1",
        "gtin",
        "gpc",
        "consumer",
        "packaging",
        "productomschrijving",
        "product description",
        "merk",
        "brand",
        "target market",
        "upload",
        "excel uploaden",
    )
    GENERIC_SHEET_NAMES = {
        "instructions",
        "instruction",
        "instructies",
        "reference data",
        "reference",
        "lookup",
        "reference lists",
        "codelijst",
        "code list",
        "template",
        "example",
    }

    def verify(self, workbook_path: str | Path) -> GS1TemplateProfile:
        path = Path(workbook_path)
        if not path.exists():
            raise GS1TemplateVerificationError(f"Configured GS1 workbook was not found:\n{path}")
        if path.suffix.lower() not in self.ALLOWED_SUFFIXES:
            raise GS1TemplateVerificationError(
                "The selected file is not a supported Excel workbook. Choose an .xlsx, .xlsm, .xltx, or .xltm file."
            )

        load_workbook, invalid_file_exc = _load_openpyxl()
        try:
            workbook = load_workbook(
                filename=str(path),
                read_only=True,
                data_only=False,
                keep_vba=path.suffix.lower() == ".xlsm",
            )
        except invalid_file_exc as exc:
            raise GS1TemplateVerificationError(
                "The selected file could not be opened as an Excel workbook."
            ) from exc
        except OSError as exc:
            raise GS1TemplateVerificationError(
                f"The selected workbook could not be read:\n{exc}"
            ) from exc

        workbook_markers = self._collect_workbook_markers(workbook)
        candidates: list[GS1TemplateCandidate] = []
        for sheet in workbook.worksheets:
            candidates.extend(self._scan_sheet_candidates(sheet, workbook_markers))

        if not candidates:
            raise GS1TemplateVerificationError(
                "This workbook does not look like a recognized GS1 upload template. "
                "Choose the official workbook from your GS1 portal or environment."
            )

        best = max(
            candidates,
            key=lambda candidate: (
                candidate.score,
                self._sheet_name_priority(candidate.sheet_name),
                -candidate.header_row,
            ),
        )
        missing_fields = missing_core_template_fields(best.column_map)
        if missing_fields:
            missing_text = ", ".join(field.replace("_", " ") for field in missing_fields)
            raise GS1TemplateVerificationError(
                "The workbook looks close to a GS1 template, but required export columns are missing: "
                f"{missing_text}."
            )

        locale_hint = detect_template_locale(best.matched_headers, best.workbook_markers)
        return GS1TemplateProfile(
            workbook_path=path,
            sheet_name=best.sheet_name,
            header_row=best.header_row,
            column_map=dict(best.column_map),
            matched_headers=dict(best.matched_headers),
            score=best.score,
            workbook_markers=list(best.workbook_markers),
            locale_hint=locale_hint,
            missing_optional_fields=optional_template_fields(best.column_map),
        )

    def _collect_workbook_markers(self, workbook) -> list[str]:
        markers: list[str] = []
        for sheet in workbook.worksheets:
            sheet_name = str(sheet.title or "").strip()
            if sheet_name:
                markers.append(sheet_name)
            for row in sheet.iter_rows(
                min_row=1,
                max_row=min(self.MAX_SCAN_ROWS, max(1, sheet.max_row)),
                max_col=min(self.MAX_SCAN_COLUMNS, max(1, sheet.max_column)),
                values_only=True,
            ):
                for value in row:
                    text = str(value or "").strip()
                    normalized = normalize_gs1_text(text)
                    if normalized and any(keyword in normalized for keyword in self.KEYWORD_MARKERS):
                        markers.append(text)
        return markers

    def _scan_sheet_candidates(self, sheet, workbook_markers: list[str]) -> list[GS1TemplateCandidate]:
        candidates: list[GS1TemplateCandidate] = []
        max_rows = min(self.MAX_SCAN_ROWS, max(1, sheet.max_row))
        max_cols = min(self.MAX_SCAN_COLUMNS, max(1, sheet.max_column))
        for row_index, row in enumerate(
            sheet.iter_rows(min_row=1, max_row=max_rows, max_col=max_cols, values_only=True),
            start=1,
        ):
            if not any(str(value or "").strip() for value in row):
                continue
            column_map, matched_headers, score = resolve_header_row(row)
            if len(column_map) < 6:
                continue
            if "gtin_request_number" not in column_map or "product_description" not in column_map:
                continue
            bonus = 0.0
            if "status" in column_map:
                bonus += 1.0
            if "brand" in column_map:
                bonus += 1.0
            if "quantity" in column_map and "unit" in column_map:
                bonus += 1.0
            bonus += self._sheet_name_priority(sheet.title)
            if workbook_markers:
                bonus += 0.5
            candidates.append(
                GS1TemplateCandidate(
                    sheet_name=str(sheet.title or ""),
                    header_row=row_index,
                    column_map=column_map,
                    matched_headers=matched_headers,
                    score=score + bonus,
                    workbook_markers=list(workbook_markers),
                )
            )
        return candidates

    def _sheet_name_priority(self, sheet_name: str) -> float:
        normalized = normalize_gs1_text(sheet_name)
        if not normalized:
            return 0.0
        if normalized in self.GENERIC_SHEET_NAMES:
            return -2.0
        if "{" in sheet_name or "}" in sheet_name:
            return -1.0
        if any(keyword in normalized for keyword in ("contract", "upload", "product", "gtin", "gs1")):
            return 1.25
        if any(ch.isdigit() for ch in sheet_name):
            return 1.0
        return 0.0


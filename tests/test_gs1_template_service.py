from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zipfile import ZipFile

import pytest

from isrc_manager.services.gs1_models import (
    CORE_GS1_TEMPLATE_FIELDS,
    GS1TemplateCandidate,
    GS1TemplateVerificationError,
)
from isrc_manager.services.gs1_template import GS1TemplateVerificationService


class _FakeSheet:
    def __init__(self, title: str, rows):
        self.title = title
        self._rows = list(rows)
        self.max_row = len(self._rows)
        self.max_column = max((len(row) for row in self._rows), default=1)

    def iter_rows(self, **kwargs):
        min_row = max(1, int(kwargs.get("min_row", 1)))
        max_row = min(self.max_row, int(kwargs.get("max_row", self.max_row)))
        min_col = max(1, int(kwargs.get("min_col", 1)))
        max_col = min(self.max_column, int(kwargs.get("max_col", self.max_column)))
        rows = []
        for row in self._rows[min_row - 1 : max_row]:
            rows.append(tuple(row[min_col - 1 : max_col]))
        return iter(rows)


class _FakeWorkbook:
    def __init__(self, sheets: dict[str, _FakeSheet], *, defined_names=None):
        self._sheets = dict(sheets)
        self.worksheets = list(self._sheets.values())
        self.defined_names = defined_names or SimpleNamespace(get=lambda _name: None)
        self.closed = False

    def __getitem__(self, sheet_name: str):
        try:
            return self._sheets[sheet_name]
        except KeyError as exc:
            raise KeyError(sheet_name) from exc

    def close(self):
        self.closed = True


def _write_zip(path: Path, files: dict[str, str]) -> None:
    with ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)


def test_verify_wraps_workbook_open_failures(tmp_path):
    service = GS1TemplateVerificationService()
    with pytest.raises(GS1TemplateVerificationError, match="was not found"):
        service.verify(tmp_path / "missing.xlsx")

    wrong_suffix = tmp_path / "template.txt"
    wrong_suffix.write_text("not a workbook", encoding="utf-8")
    with pytest.raises(GS1TemplateVerificationError, match="supported Excel workbook"):
        service.verify(wrong_suffix)

    workbook_path = tmp_path / "template.xlsx"
    workbook_path.write_bytes(b"placeholder")

    class InvalidWorkbook(Exception):
        pass

    def raise_invalid(**_kwargs):
        raise InvalidWorkbook("bad workbook")

    with mock.patch(
        "isrc_manager.services.gs1_template._load_openpyxl",
        return_value=(raise_invalid, InvalidWorkbook),
    ):
        with pytest.raises(GS1TemplateVerificationError, match="could not be opened"):
            service.verify(workbook_path)

    def raise_os_error(**_kwargs):
        raise OSError("locked")

    with mock.patch(
        "isrc_manager.services.gs1_template._load_openpyxl",
        return_value=(raise_os_error, InvalidWorkbook),
    ):
        with pytest.raises(GS1TemplateVerificationError, match="could not be read"):
            service.verify(workbook_path)


def test_verify_reports_no_candidates_and_missing_core_columns(tmp_path):
    service = GS1TemplateVerificationService()
    workbook_path = tmp_path / "template.xlsx"
    workbook_path.write_bytes(b"placeholder")
    workbook = _FakeWorkbook({"Input": _FakeSheet("Input", [])})

    with (
        mock.patch(
            "isrc_manager.services.gs1_template._load_openpyxl",
            return_value=(mock.Mock(return_value=workbook), RuntimeError),
        ),
        mock.patch.object(service, "_collect_workbook_markers", return_value=[]),
        mock.patch.object(service, "_scan_sheet_candidates", return_value=[]),
    ):
        with pytest.raises(GS1TemplateVerificationError, match="recognized GS1 upload template"):
            service.verify(workbook_path)

    partial_candidate = GS1TemplateCandidate(
        sheet_name="Input",
        header_row=1,
        column_map={
            "gtin_request_number": 1,
            "product_description": 2,
            "target_market": 3,
            "packaging_type": 4,
            "product_classification": 5,
            "consumer_unit_flag": 6,
        },
        matched_headers={},
        score=25.0,
        workbook_markers=[],
    )
    with (
        mock.patch(
            "isrc_manager.services.gs1_template._load_openpyxl",
            return_value=(mock.Mock(return_value=workbook), RuntimeError),
        ),
        mock.patch.object(service, "_collect_workbook_markers", return_value=[]),
        mock.patch.object(service, "_scan_sheet_candidates", return_value=[partial_candidate]),
    ):
        with pytest.raises(GS1TemplateVerificationError, match="required export columns"):
            service.verify(workbook_path)


def test_verify_preserves_profile_when_field_option_extraction_fails(tmp_path):
    service = GS1TemplateVerificationService()
    workbook_path = tmp_path / "template.xlsx"
    workbook_path.write_bytes(b"placeholder")
    workbook = _FakeWorkbook({"{Template}": _FakeSheet("{Template}", [])})
    column_map = {field: index for index, field in enumerate(CORE_GS1_TEMPLATE_FIELDS, start=1)}
    candidate = GS1TemplateCandidate(
        sheet_name="{Template}",
        header_row=2,
        column_map=column_map,
        matched_headers={field: field for field in column_map},
        score=50.0,
        workbook_markers=["GS1"],
    )

    with (
        mock.patch(
            "isrc_manager.services.gs1_template._load_openpyxl",
            return_value=(mock.Mock(return_value=workbook), RuntimeError),
        ),
        mock.patch.object(service, "_collect_workbook_markers", return_value=["GS1"]),
        mock.patch.object(service, "_scan_sheet_candidates", return_value=[candidate]),
        mock.patch.object(
            service, "_extract_field_options", side_effect=RuntimeError("xml failed")
        ),
    ):
        profile = service.verify(workbook_path)

    assert profile.sheet_name == "{Template}"
    assert profile.field_options == {}
    assert workbook.closed is True


def test_verify_merges_sheet_field_options_without_duplicates(tmp_path):
    service = GS1TemplateVerificationService()
    workbook_path = tmp_path / "template.xlsx"
    workbook_path.write_bytes(b"placeholder")
    workbook = _FakeWorkbook(
        {
            "Input": _FakeSheet("Input", []),
            "Upload": _FakeSheet("Upload", []),
        }
    )
    column_map = {field: index for index, field in enumerate(CORE_GS1_TEMPLATE_FIELDS, start=1)}
    candidates = [
        GS1TemplateCandidate(
            sheet_name="Input",
            header_row=2,
            column_map=column_map,
            matched_headers={field: field for field in column_map},
            score=50.0,
            workbook_markers=["GS1"],
        ),
        GS1TemplateCandidate(
            sheet_name="Upload",
            header_row=2,
            column_map=column_map,
            matched_headers={field: field for field in column_map},
            score=49.0,
            workbook_markers=["GS1"],
        ),
    ]

    with (
        mock.patch(
            "isrc_manager.services.gs1_template._load_openpyxl",
            return_value=(mock.Mock(return_value=workbook), RuntimeError),
        ),
        mock.patch.object(service, "_collect_workbook_markers", return_value=["GS1"]),
        mock.patch.object(service, "_scan_sheet_candidates", return_value=candidates),
        mock.patch.object(
            service,
            "_extract_field_options",
            side_effect=[
                {"brand": ("Acme", "Other")},
                {"brand": ("Other", "New"), "language": ("", "en")},
            ],
        ),
    ):
        profile = service.verify(workbook_path)

    assert profile.field_options == {"brand": ("Acme", "Other", "New"), "language": ("en",)}


def test_scan_sheet_candidates_skips_blank_and_incomplete_rows():
    service = GS1TemplateVerificationService()
    sheet = _FakeSheet(
        "Input 2",
        [
            ("", "", ""),
            (
                "GTIN",
                "Product Description",
                "GPC",
                "Consumer Unit",
                "Packaging Type",
                "Target Market",
            ),
            (
                "GTIN",
                "Status",
                "GPC",
                "Consumer Unit",
                "Packaging Type",
                "Target Market",
                "Brand",
            ),
            (
                "GTIN",
                "Status",
                "GPC",
                "Consumer Unit",
                "Packaging Type",
                "Target Market",
                "Product Description",
                "Language",
                "Brand",
                "Quantity",
                "Unit",
            ),
        ],
    )

    candidates = service._scan_sheet_candidates(sheet, workbook_markers=[])

    assert [candidate.header_row for candidate in candidates] == [2, 4]
    assert all(candidate.sheet_name == "Input 2" for candidate in candidates)


def test_sheet_name_priority_handles_empty_generic_placeholder_and_neutral_names():
    service = GS1TemplateVerificationService()

    assert service._sheet_name_priority("") == 0.0
    assert service._sheet_name_priority("Instructions") == -2.0
    assert service._sheet_name_priority("{Template}") == -1.0
    assert service._sheet_name_priority("GS1 Upload") == 1.25
    assert service._sheet_name_priority("Input 2") == 1.0
    assert service._sheet_name_priority("Metadata") == 0.0


def test_collect_workbook_markers_skips_blank_titles_and_non_keywords():
    service = GS1TemplateVerificationService()
    workbook = _FakeWorkbook({"": _FakeSheet("", [("ordinary", None)])})

    assert service._collect_workbook_markers(workbook) == []


def test_extract_field_options_collects_existing_values_when_validation_is_missing(tmp_path):
    service = GS1TemplateVerificationService()
    worksheet = _FakeSheet(
        "Input",
        [
            ("Brand",),
            ("Acme",),
            ("",),
            ("Acme",),
            ("Other",),
        ],
    )
    workbook = _FakeWorkbook({"Input": worksheet})

    with mock.patch.object(service, "_validation_options_from_sheet_xml", return_value={}):
        options = service._extract_field_options(
            tmp_path / "template.xlsx",
            workbook,
            {"brand": 1},
            "Input",
            1,
        )

    assert options == {"brand": ("Acme", "Other")}

    with mock.patch.object(
        service,
        "_validation_options_from_sheet_xml",
        return_value={"brand": ["Template Brand"]},
    ):
        options = service._extract_field_options(
            tmp_path / "template.xlsx",
            workbook,
            {"brand": 1},
            "Input",
            1,
        )

    assert options == {"brand": ("Template Brand",)}


def test_validation_options_skip_unmapped_empty_and_duplicate_values(tmp_path):
    service = GS1TemplateVerificationService()

    with (
        mock.patch.object(
            service, "_resolve_sheet_xml_path", return_value="xl/worksheets/sheet1.xml"
        ),
        mock.patch.object(
            service,
            "_read_validation_entries",
            return_value=[
                ("Z2:Z5", '"Ignored"'),
                ("A2:A5", ""),
                ("A2:A5", '"Active,Active,Inactive"'),
            ],
        ),
    ):
        options = service._validation_options_from_sheet_xml(
            tmp_path / "template.xlsx",
            workbook=object(),
            column_map={"status": 1},
            sheet_name="Input",
        )

    assert options == {"status": ["Active", "Inactive"]}

    with (
        mock.patch.object(
            service, "_resolve_sheet_xml_path", return_value="xl/worksheets/sheet1.xml"
        ),
        mock.patch.object(service, "_read_validation_entries", return_value=[("A2:A5", "Named")]),
        mock.patch.object(
            service,
            "_resolve_validation_formula_values",
            return_value=["Active", "Active", "Inactive"],
        ),
    ):
        assert service._validation_options_from_sheet_xml(
            tmp_path / "template.xlsx",
            workbook=object(),
            column_map={"status": 1},
            sheet_name="Input",
        ) == {"status": ["Active", "Inactive"]}

    with mock.patch.object(service, "_resolve_sheet_xml_path", side_effect=RuntimeError("zip")):
        assert (
            service._validation_options_from_sheet_xml(
                tmp_path / "template.xlsx",
                workbook=object(),
                column_map={"status": 1},
                sheet_name="Input",
            )
            == {}
        )

    with mock.patch.object(service, "_resolve_sheet_xml_path", return_value=""):
        assert (
            service._validation_options_from_sheet_xml(
                tmp_path / "template.xlsx",
                workbook=object(),
                column_map={"status": 1},
                sheet_name="Input",
            )
            == {}
        )


def test_resolve_sheet_xml_path_handles_relative_absolute_and_missing_targets(tmp_path):
    service = GS1TemplateVerificationService()
    workbook_path = tmp_path / "template.xlsx"

    workbook_xml = """\
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Input" sheetId="1" r:id="rId1"/>
    <sheet name="Absolute" sheetId="2" r:id="rId2"/>
    <sheet name="Broken" sheetId="3" r:id="rId3"/>
  </sheets>
</workbook>
"""
    rels_xml = """\
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Target="/xl/worksheets/sheet2.xml"/>
</Relationships>
"""
    _write_zip(
        workbook_path,
        {
            "xl/workbook.xml": workbook_xml,
            "xl/_rels/workbook.xml.rels": rels_xml,
        },
    )

    assert service._resolve_sheet_xml_path(workbook_path, "Input") == "xl/worksheets/sheet1.xml"
    assert service._resolve_sheet_xml_path(workbook_path, "Absolute") == "xl/worksheets/sheet2.xml"
    assert service._resolve_sheet_xml_path(workbook_path, "Missing") == ""
    assert service._resolve_sheet_xml_path(workbook_path, "Broken") == ""


def test_read_validation_entries_supports_modern_and_legacy_excel_xml(tmp_path):
    service = GS1TemplateVerificationService()
    workbook_path = tmp_path / "template.xlsx"
    worksheet_xml = """\
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
           xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"
           xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main">
  <x14:dataValidations>
    <x14:dataValidation type="whole" sqref="A2"><x14:formula1><xm:f>"Skip"</xm:f></x14:formula1><xm:sqref>A2</xm:sqref></x14:dataValidation>
    <x14:dataValidation type="list"><x14:formula1><xm:f>"A,B"</xm:f></x14:formula1><xm:sqref>A2:A3</xm:sqref></x14:dataValidation>
    <x14:dataValidation type="list" sqref="B2:B3"><x14:formula1><xm:f>"C,D"</xm:f></x14:formula1></x14:dataValidation>
    <x14:dataValidation type="list" sqref="D2:D3"></x14:dataValidation>
  </x14:dataValidations>
  <dataValidations>
    <dataValidation type="whole" sqref="C2"><formula1>"Skip"</formula1></dataValidation>
    <dataValidation type="list" sqref="C2:C3"><formula1>"E,F"</formula1></dataValidation>
    <dataValidation type="list" sqref="D2:D3"></dataValidation>
  </dataValidations>
</worksheet>
"""
    _write_zip(workbook_path, {"xl/worksheets/sheet1.xml": worksheet_xml})

    entries = service._read_validation_entries(workbook_path, "xl/worksheets/sheet1.xml")

    assert entries == [
        ("A2:A3", '"A,B"'),
        ("B2:B3", '"C,D"'),
        ("C2:C3", '"E,F"'),
    ]


def test_validation_formula_values_cover_inline_ranges_defined_names_and_failures():
    service = GS1TemplateVerificationService()
    worksheet = _FakeSheet("Lists", [("Active",), ("",), ("Inactive",), ("Active",)])

    class _DefinedNames:
        def get(self, name):
            if name == "Broken":
                raise RuntimeError("unreadable names")
            if name == "NamedChoices":
                return SimpleNamespace(destinations=[("Lists", "$A$1:$A$4")])
            return None

    workbook = _FakeWorkbook({"Lists": worksheet}, defined_names=_DefinedNames())

    assert service._resolve_validation_formula_values(workbook, "") == []
    assert service._resolve_validation_formula_values(workbook, '="One, Two, One"') == [
        "One",
        "Two",
    ]
    assert service._resolve_validation_formula_values(workbook, "'Lists'!$A$1:$A$4") == [
        "Active",
        "Inactive",
    ]
    assert service._resolve_validation_formula_values(workbook, "NamedChoices") == [
        "Active",
        "Inactive",
    ]
    assert service._resolve_validation_formula_values(workbook, "Broken") == []
    assert service._read_cell_range_values(workbook, "Lists", "") == []
    assert service._read_cell_range_values(workbook, "Missing", "$A$1:$A$4") == []
    assert service._read_cell_range_values(workbook, "Lists", "not-a-range") == []


def test_field_name_for_sqref_uses_first_mapped_column_and_skips_invalid_tokens():
    service = GS1TemplateVerificationService()

    assert service._field_name_for_sqref("1:3 AAAA1 $Z$2 $B$4:$B$9", {2: "brand"}) == "brand"
    assert service._field_name_for_sqref("1:3 $Z$2", {2: "brand"}) == ""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest
from openpyxl import Workbook

from isrc_manager.invoicing.royalty_import import RoyaltySourceImportService
from isrc_manager.invoicing.royalty_integration import RoyaltySourceEventPayload


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE Works(id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE Tracks(id INTEGER PRIMARY KEY, isrc TEXT, track_title TEXT);
        CREATE TABLE Releases(id INTEGER PRIMARY KEY, title TEXT);
        """)
    return conn


def _csv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_preview_import_reports_mapping_validation_and_status_edges(tmp_path: Path) -> None:
    conn = _connection()
    conn.executemany(
        "INSERT INTO Tracks(id, isrc, track_title) VALUES (?, ?, ?)",
        [
            (1, "GBAAA2600001", "Unique Recording"),
            (2, "GBAAA2600002", "Duplicate Recording"),
            (3, "GBAAA2600003", "Duplicate Recording"),
        ],
    )
    conn.execute("INSERT INTO Releases(id, title) VALUES (7, 'Known Release')")
    path = _csv(
        tmp_path / "royalties.csv",
        "\n".join(
            [
                "description,contract_id,track_isrc,track_title,release_title,source_type,source_id,period_start,currency,gross_amount,gross_amount_minor,net_amount,net_amount_minor",
                ",not-number,,,,,,,,1.00,,,",
                ",,GBAAA2600001,,,Spotify,,2026-02,,0.001,,,",
                ",,,,,Bandcamp,,,,not money,,,",
                ",,,,,,TX-10,,,2.00,,,",
                ",,,,Missing Release,,TX-9,,EURO,,abc,,5",
                ",,,Duplicate Recording,Missing Release,,,,USD,1.23,,,",
            ]
        ),
    )
    service = RoyaltySourceImportService(conn)
    report = service.preview_import(
        path,
        {
            "description": "description",
            "contract_id": "contract_id",
            "track_isrc": "track_isrc",
            "track_title": "track_title",
            "release_title": "release_title",
            "source_type": "source_type",
            "source_id": "source_id",
            "period_start": "period_start",
            "currency": "currency",
            "gross_amount": "gross_amount",
            "gross_amount_minor": "gross_amount_minor",
            "net_amount": "net_amount",
            "net_amount_minor": "net_amount_minor",
            "ignored": "not-a-target",
        },
    )

    assert report.format_name == "csv"
    assert report.mode == "preview"
    assert report.passed == 1
    assert report.failed == 4
    assert report.skipped == 1
    assert report.preview_rows[0].issues == ("description is required",)
    assert report.preview_rows[0].contract_id is None
    assert report.preview_rows[1].description == "Spotify royalty revenue 2026-02"
    assert report.preview_rows[1].status == "skipped"
    assert report.preview_rows[1].period_start == "2026-02-01"
    assert report.preview_rows[1].period_end == "2026-02-28"
    assert report.preview_rows[1].issues == ("amount rounds below one minor unit; skipped",)
    assert report.preview_rows[2].description == "Bandcamp royalty revenue"
    assert any("gross_amount" in issue for issue in report.preview_rows[2].issues)
    assert report.preview_rows[3].description == "Royalty source TX-10"
    assert report.preview_rows[3].status == "ready"
    assert report.preview_rows[4].description == "Missing Release"
    assert "Currency must be a three-letter ISO code." in report.preview_rows[4].issues
    assert "gross_amount_minor must be an integer" in report.preview_rows[4].issues
    assert (
        "release title did not match an existing record: Missing Release"
        in report.preview_rows[5].issues
    )
    assert (
        "track title matched multiple records: Duplicate Recording" in report.preview_rows[5].issues
    )
    assert report.summary_lines == [
        "Format: CSV",
        "Rows would import: 1",
        "Rows failed: 4",
        "Rows skipped: 1",
    ]
    assert (
        report.preview_rows[4].to_preview_dict()["Issues"].startswith("release title did not match")
    )

    conn.close()


@dataclass(slots=True)
class _RecordedEvent:
    id: int


class _FakeIntegration:
    def __init__(self) -> None:
        self.payloads: list[RoyaltySourceEventPayload] = []

    def record_source_event(self, payload: RoyaltySourceEventPayload) -> _RecordedEvent:
        self.payloads.append(payload)
        return _RecordedEvent(id=100 + len(self.payloads))


def test_apply_import_records_only_ready_rows_with_import_metadata(tmp_path: Path) -> None:
    conn = _connection()
    path = _csv(
        tmp_path / "ready.csv",
        "\n".join(
            [
                "description,source_type,source_id,event_date,net_amount",
                "Streaming payout,DSP,stmt-1,2026-03,12.34",
                ",,,,",
            ]
        ),
    )
    service = RoyaltySourceImportService(conn)
    fake_integration = _FakeIntegration()
    service.integration = fake_integration

    report = service.apply_import(
        path,
        {
            "description": "description",
            "source_type": "source_type",
            "source_id": "source_id",
            "event_date": "event_date",
            "net_amount": "net_amount",
        },
        default_contract_id=42,
    )

    assert report.mode == "apply"
    assert report.passed == 1
    assert report.failed == 1
    assert report.created_event_ids == (101,)
    payload = fake_integration.payloads[0]
    assert payload.contract_id == 42
    assert payload.description == "Streaming payout"
    assert payload.event_date == "2026-03-01"
    assert payload.net_amount_minor == 1234
    assert payload.metadata == {"import_format": "csv", "import_row_number": 1}

    conn.close()


def test_inspect_file_handles_empty_csv_and_unsupported_suffix(tmp_path: Path) -> None:
    conn = _connection()
    service = RoyaltySourceImportService(conn)
    empty_path = _csv(tmp_path / "empty.csv", "")

    inspection = service.inspect_file(empty_path)

    assert inspection.format_name == "csv"
    assert inspection.headers == []
    assert inspection.preview_rows == []
    assert inspection.suggested_mapping == {}
    with pytest.raises(ValueError, match="CSV, XML, and XLSX"):
        service.inspect_file(tmp_path / "statement.txt")

    conn.close()


def test_xlsx_reader_skips_blank_rows_and_promotes_first_nonblank_header(
    tmp_path: Path,
) -> None:
    conn = _connection()
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([None, None])
    sheet.append(["Track title", "Total USD", None])
    sheet.append([None, None, None])
    sheet.append(["Workbook Track", "7.89", "ignored"])
    path = tmp_path / "royalties.xlsx"
    workbook.save(path)
    workbook.close()

    service = RoyaltySourceImportService(conn)
    inspection = service.inspect_file(path)

    assert inspection.format_name == "xlsx"
    assert inspection.headers == ["Track title", "Total USD", "Column 3"]
    assert inspection.preview_rows == [
        {"Track title": "Workbook Track", "Total USD": "7.89", "Column 3": "ignored"}
    ]
    assert inspection.suggested_mapping == {
        "Track title": "description",
        "Total USD": "net_amount",
    }

    blank_workbook = Workbook()
    blank_path = tmp_path / "blank.xlsx"
    blank_workbook.save(blank_path)
    blank_workbook.close()
    assert service.inspect_file(blank_path).preview_rows == []

    conn.close()


def test_xml_reader_flattens_attributes_unique_children_and_empty_roots(
    tmp_path: Path,
) -> None:
    conn = _connection()
    service = RoyaltySourceImportService(conn)
    attributed_root = tmp_path / "attributed.xml"
    attributed_root.write_text('<statement id="root-1" total="4.56" />', encoding="utf-8")
    unique_children = tmp_path / "unique.xml"
    unique_children.write_text(
        """
        <statement>
            <line id="l1"><track isrc="GBAAA2600001">Title A</track></line>
            <summary currency="EUR">12.34</summary>
        </statement>
        """,
        encoding="utf-8",
    )
    empty_root = tmp_path / "empty.xml"
    empty_root.write_text("<statement />", encoding="utf-8")

    attributed = service.inspect_file(attributed_root)
    unique = service.inspect_file(unique_children)
    empty = service.inspect_file(empty_root)

    assert attributed.preview_rows == [{"id": "root-1", "total": "4.56"}]
    assert unique.preview_rows == [
        {"id": "l1", "track": "Title A", "track.isrc": "GBAAA2600001"},
        {"currency": "EUR"},
    ]
    assert empty.preview_rows == []
    assert empty.warnings == ["No row-like XML elements were found."]

    conn.close()


def test_match_optional_id_handles_missing_lookup_table() -> None:
    conn = sqlite3.connect(":memory:")
    service = RoyaltySourceImportService(conn)
    issues: list[str] = []

    assert (
        service._match_optional_id(
            "Works",
            "id",
            "title",
            "Missing Work",
            label="work title",
            issues=issues,
        )
        is None
    )
    assert issues == ["work title cannot be matched in this profile"]

    conn.close()

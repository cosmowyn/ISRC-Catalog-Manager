import sqlite3

from openpyxl import Workbook
from PySide6.QtWidgets import QApplication, QComboBox

from isrc_manager.contracts import ContractPartyPayload, ContractPayload, ContractService
from isrc_manager.invoicing.royalty_import import (
    ROYALTY_IMPORT_SKIP_TARGET,
    RoyaltySourceImportService,
)
from isrc_manager.invoicing.royalty_import_dialog import RoyaltySourceImportDialog
from isrc_manager.parties import PartyPayload, PartyService
from isrc_manager.rights import OwnershipInterestPayload, RightPayload, RightsService
from isrc_manager.services import DatabaseSchemaService
from isrc_manager.works import WorkContributorPayload, WorkPayload, WorkService


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    schema = DatabaseSchemaService(conn)
    schema.init_db()
    schema.migrate_schema()
    return conn


def _integrated_contract_fixture(conn: sqlite3.Connection) -> tuple[int, int, int, int]:
    party_service = PartyService(conn)
    writer_id = party_service.create_party(
        PartyPayload(
            legal_name="Import Writer",
            display_name="Import Writer",
            party_type="artist",
            artist_name="Import Writer",
        )
    )
    publisher_id = party_service.create_party(
        PartyPayload(
            legal_name="Import Publisher",
            display_name="Import Publisher",
            party_type="publisher",
        )
    )
    work_id = WorkService(conn, party_service=party_service).create_work(
        WorkPayload(
            title="Import Work",
            metadata_complete=True,
            contract_signed=True,
            rights_verified=True,
            contributors=(
                WorkContributorPayload(
                    role="composer",
                    name="Import Writer",
                    share_percent=100.0,
                    party_id=writer_id,
                ),
            ),
        )
    )
    contract_id = ContractService(conn, party_service=party_service).create_contract(
        ContractPayload(
            title="Import Publishing Agreement",
            contract_type="publishing",
            status="active",
            parties=(
                ContractPartyPayload(
                    party_id=writer_id,
                    role_label="writer",
                    is_primary=True,
                ),
            ),
            work_ids=(work_id,),
        )
    )
    right_id = RightsService(conn).create_right(
        RightPayload(
            title="Import publishing grant",
            right_type="composition_publishing",
            exclusive_flag=True,
            territory="Worldwide",
            perpetual_flag=True,
            granted_to_party_id=publisher_id,
            source_contract_id=contract_id,
            work_id=work_id,
        )
    )
    RightsService(conn).replace_work_ownership_interests(
        work_id,
        (
            OwnershipInterestPayload(
                role="publisher",
                party_id=publisher_id,
                share_percent=100.0,
                territory="Worldwide",
                source_contract_id=contract_id,
            ),
        ),
    )
    return contract_id, work_id, publisher_id, right_id


def test_royalty_source_import_csv_previews_and_applies_valid_rows(tmp_path):
    conn = _connection()
    contract_id, work_id, _publisher_id, _right_id = _integrated_contract_fixture(conn)
    path = tmp_path / "dsp.csv"
    path.write_text(
        "Provider,Statement ID,Work Title,Period Start,Period End,Gross,Net,Currency,Ignore Me\n"
        "Spotify,sp-1,Import Work,2026-01-01,2026-01-31,12.34,10.00,EUR,omit\n"
        "Spotify,sp-2,Import Work,2026-01-01,2026-01-31,0,0,EUR,omit\n".format(),
        encoding="utf-8",
    )
    service = RoyaltySourceImportService(conn)

    inspection = service.inspect_file(path)
    mapping = dict(inspection.suggested_mapping)
    mapping.pop("Ignore Me", None)
    preview = service.preview_import(path, mapping, default_contract_id=contract_id)
    applied = service.apply_import(path, mapping, default_contract_id=contract_id)
    event = conn.execute("""
        SELECT contract_id, work_id, source_type, source_id, description,
               gross_amount_minor, net_amount_minor
        FROM RoyaltySourceEvents
        """).fetchone()

    assert inspection.format_name == "csv"
    assert inspection.suggested_mapping["Work Title"] == "work_title"
    assert inspection.suggested_mapping["Provider"] == "source_type"
    assert preview.preview_rows[0].work_id == work_id
    assert preview.passed == 1
    assert preview.failed == 0
    assert preview.skipped == 1
    assert "amount rounds below one minor unit; skipped" in preview.preview_rows[1].issues
    assert applied.passed == 1
    assert applied.created_event_ids == (1,)
    assert event == (contract_id, work_id, "Spotify", "sp-1", "Import Work", 1234, 1000)

    conn.close()


def test_royalty_source_import_reads_xlsx_and_xml_provider_rows(tmp_path):
    conn = _connection()
    contract_id, work_id, _publisher_id, _right_id = _integrated_contract_fixture(conn)
    xlsx_path = tmp_path / "provider.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Title", "DSP", "Transaction ID", "Work ID", "Net"])
    sheet.append(["Workbook Play", "Apple", "apple-1", work_id, "2.50"])
    workbook.save(xlsx_path)
    xml_path = tmp_path / "provider.xml"
    xml_path.write_text(
        """
        <statement>
          <line>
            <title>XML Play</title>
            <provider>Deezer</provider>
            <transaction_id>deezer-1</transaction_id>
            <work_id>{work_id}</work_id>
            <net>3.75</net>
          </line>
        </statement>
        """.format(work_id=work_id),
        encoding="utf-8",
    )
    service = RoyaltySourceImportService(conn)

    xlsx_inspection = service.inspect_file(xlsx_path)
    xlsx_preview = service.preview_import(
        xlsx_path,
        xlsx_inspection.suggested_mapping,
        default_contract_id=contract_id,
    )
    xml_inspection = service.inspect_file(xml_path)
    xml_preview = service.preview_import(
        xml_path,
        xml_inspection.suggested_mapping,
        default_contract_id=contract_id,
    )

    assert xlsx_inspection.format_name == "xlsx"
    assert xlsx_preview.preview_rows[0].description == "Workbook Play"
    assert xlsx_preview.preview_rows[0].net_amount_minor == 250
    assert xml_inspection.format_name == "xml"
    assert xml_preview.preview_rows[0].description == "XML Play"
    assert xml_preview.preview_rows[0].source_type == "Deezer"
    assert xml_preview.preview_rows[0].net_amount_minor == 375

    conn.close()


def test_royalty_source_import_dialog_supports_mapping_and_omit(tmp_path):
    _app()
    conn = _connection()
    contract_id, _work_id, _publisher_id, _right_id = _integrated_contract_fixture(conn)
    path = tmp_path / "dialog.csv"
    path.write_text(
        "Title,Provider,Net,Unused\nDialog Play,Tidal,1.25,ignored\n",
        encoding="utf-8",
    )
    service = RoyaltySourceImportService(conn)
    inspection = service.inspect_file(path)
    dialog = RoyaltySourceImportDialog(
        inspection=inspection,
        preview_callback=lambda mapping: service.preview_import(
            path,
            mapping,
            default_contract_id=contract_id,
        ),
    )

    unused_row = inspection.headers.index("Unused")
    combo = dialog.mapping_table.cellWidget(unused_row, 1)
    assert isinstance(combo, QComboBox)
    combo.setCurrentIndex(combo.findData(ROYALTY_IMPORT_SKIP_TARGET))
    mapping = dialog.mapping()
    dialog.refresh_resolved_preview()

    assert "Unused" not in mapping
    assert mapping["Title"] == "description"
    assert dialog.content_tabs.objectName() == "royaltySourceImportTabs"
    assert dialog.resolved_table.rowCount() == 1
    assert dialog.import_button.isEnabled()

    dialog.deleteLater()
    conn.close()

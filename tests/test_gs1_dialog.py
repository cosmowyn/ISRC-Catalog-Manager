import unittest

try:
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - environment-specific fallback
    QApplication = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None

from isrc_manager.gs1_dialog import GS1MetadataEditorPage
from isrc_manager.services import (
    GS1ContractEntry,
    GS1MetadataGroup,
    GS1MetadataRecord,
    GS1RecordContext,
)


def _sample_group() -> GS1MetadataGroup:
    record = GS1MetadataRecord(
        track_id=7,
        contract_number="NL-TEST-001",
        status="Concept",
        product_classification="Muziek - Digitaal",
        consumer_unit_flag=True,
        packaging_type="Verpakt, geen specificatie",
        target_market="Global Market",
        language="English",
        product_description="Tales of the Subconscious",
        brand="Cosmowyn Records",
        subbrand="Aeon Cosmowyn",
        quantity="1",
        unit="Each",
        export_enabled=True,
    )
    context = GS1RecordContext(
        track_id=7,
        track_title="Tales of the Subconscious",
        album_title="Tales of the Subconscious",
        artist_name="Aeon Cosmowyn",
        upc="8720892724649",
    )
    return GS1MetadataGroup(
        group_id="group-7",
        tab_title="Album",
        display_title="Tales of the Subconscious",
        mode="album",
        track_ids=(7,),
        contexts=(context,),
        record=record,
        default_record=record.copy(),
    )


class GS1DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest(f"PySide6 QtWidgets unavailable: {QT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def test_editor_page_uses_compact_field_metrics(self):
        page = GS1MetadataEditorPage(
            _sample_group(),
            contract_entries=[GS1ContractEntry(contract_number="NL-TEST-001")],
        )
        try:
            line_height = page.description_edit.fontMetrics().lineSpacing()
            combo_line_height = page.contract_combo.fontMetrics().lineSpacing()

            self.assertLessEqual(page.description_edit.minimumHeight(), line_height + 18)
            self.assertLessEqual(page.contract_combo.minimumHeight(), combo_line_height + 18)
            self.assertLessEqual(page.description_edit.minimumWidth(), 380)
            self.assertLessEqual(page.brand_edit.minimumWidth(), 240)
            self.assertLess(page.notes_edit.minimumHeight(), 176)
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()

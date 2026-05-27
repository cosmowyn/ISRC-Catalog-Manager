"""Additional behavioral coverage for the conversion workflow dialog."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QComboBox, QLineEdit, QMessageBox

from isrc_manager.conversion.dialogs import ConversionDialog
from isrc_manager.conversion.models import (
    MAPPING_KIND_CONSTANT,
    MAPPING_KIND_SOURCE,
    MAPPING_KIND_UNMAPPED,
    SOURCE_MODE_DATABASE_TRACKS,
    SOURCE_MODE_FILE,
    ConversionMappingEntry,
    ConversionPreview,
    ConversionSession,
    ConversionSourceProfile,
    ConversionTargetField,
    ConversionTemplateProfile,
    SavedConversionTemplateRecord,
)
from tests.qt_test_helpers import pump_events, require_qapplication


def _target_fields() -> tuple[ConversionTargetField, ...]:
    return (
        ConversionTargetField(
            field_key="title",
            display_name="Title",
            location="Column A",
            required_status="required",
        ),
        ConversionTargetField(
            field_key="year",
            display_name="Year",
            location="Column B",
            required_status="optional",
        ),
    )


def _template_profile(
    *,
    format_name: str = "csv",
    output_suffix: str = ".csv",
    available_scopes: tuple[tuple[str, str], ...] = (),
    chosen_scope: str = "",
) -> ConversionTemplateProfile:
    return ConversionTemplateProfile(
        template_path=Path(f"template{output_suffix}"),
        format_name=format_name,
        output_suffix=output_suffix,
        structure_label="Flat rows",
        target_fields=_target_fields(),
        template_signature=f"{format_name}-signature",
        template_bytes=b"title,year\n",
        available_scopes=available_scopes,
        chosen_scope=chosen_scope,
        adapter_state={"source_label": "Template bytes"},
    )


def _source_profile() -> ConversionSourceProfile:
    rows = ({"title": "Orbit"},)
    return ConversionSourceProfile(
        source_mode=SOURCE_MODE_FILE,
        format_name="csv",
        source_label="source.csv",
        headers=("title",),
        rows=rows,
        preview_rows=rows,
        source_path="source.csv",
        resolved_delimiter=",",
    )


class _DialogService:
    def __init__(self) -> None:
        self.build_preview_calls = 0
        self.deserialize_payloads: list[str] = []
        self.inspect_source_calls: list[tuple[str, str | None]] = []
        self.selected_template_scopes: list[str] = []
        self.serialized_entries: list[tuple[ConversionMappingEntry, ...]] = []
        self.deserialize_entries: tuple[ConversionMappingEntry, ...] = (
            ConversionMappingEntry(
                target_field_key="title",
                target_display_name="Title",
                mapping_kind=MAPPING_KIND_SOURCE,
                source_field="title",
            ),
            ConversionMappingEntry(
                target_field_key="title",
                target_display_name="Title",
                mapping_kind=MAPPING_KIND_CONSTANT,
                constant_value="Archived title",
            ),
            ConversionMappingEntry(
                target_field_key="year",
                target_display_name="Year",
                mapping_kind=MAPPING_KIND_SOURCE,
                source_field="missing_year",
            ),
        )

    def inspect_template_bytes(
        self,
        filename: str,
        template_bytes: bytes,
        *,
        source_label: str,
        source_path: str = "",
    ) -> ConversionTemplateProfile:
        profile = _template_profile(
            available_scopes=(("main", "Main sheet"),),
        )
        return replace(
            profile,
            template_path=Path(filename),
            template_bytes=template_bytes,
            adapter_state={"source_label": source_label, "source_path": source_path},
        )

    def select_template_scope(
        self,
        profile: ConversionTemplateProfile,
        scope_key: str,
    ) -> ConversionTemplateProfile:
        self.selected_template_scopes.append(scope_key)
        return replace(profile, chosen_scope=scope_key)

    def inspect_source_file(
        self,
        path: str,
        *,
        preferred_csv_delimiter: str | None = None,
    ) -> ConversionSourceProfile:
        self.inspect_source_calls.append((path, preferred_csv_delimiter))
        return replace(
            _source_profile(),
            source_label=Path(path).name,
            source_path=str(path),
            resolved_delimiter=preferred_csv_delimiter or ",",
        )

    def build_session(
        self,
        template_profile: ConversionTemplateProfile,
        source_profile: ConversionSourceProfile,
    ) -> ConversionSession:
        return ConversionSession(
            template_profile=template_profile,
            source_profile=source_profile,
            mapping_entries=tuple(
                ConversionMappingEntry(
                    target_field_key=field.field_key,
                    target_display_name=field.display_name,
                )
                for field in template_profile.target_fields
            ),
            included_row_indices=tuple(range(len(source_profile.rows))),
        )

    def suggest_mapping(
        self,
        session: ConversionSession,
    ) -> dict[str, ConversionMappingEntry]:
        return {
            "title": ConversionMappingEntry(
                target_field_key="title",
                target_display_name="Title",
                mapping_kind=MAPPING_KIND_SOURCE,
                source_field="title",
                origin="suggested",
            )
        }

    def deserialize_mapping_entries(
        self,
        payload: str,
        _template_profile: ConversionTemplateProfile,
    ) -> tuple[ConversionMappingEntry, ...]:
        self.deserialize_payloads.append(payload)
        return self.deserialize_entries

    def serialize_mapping_entries(
        self,
        entries: tuple[ConversionMappingEntry, ...],
    ) -> str:
        self.serialized_entries.append(tuple(entries))
        return "serialized-mapping"

    def build_preview(self, session: ConversionSession) -> ConversionPreview:
        self.build_preview_calls += 1
        field_by_key = {field.field_key: field for field in session.template_profile.target_fields}
        feedback_entries: list[ConversionMappingEntry] = []
        rendered_rows: list[tuple[str, ...]] = []
        blocking_issues: list[str] = []

        for entry in session.mapping_entries:
            field = field_by_key[entry.target_field_key]
            status = "unmapped"
            message = ""
            sample_value = ""
            if entry.mapping_kind == MAPPING_KIND_SOURCE:
                first_row = session.source_profile.rows[0] if session.source_profile.rows else {}
                sample_value = str(first_row.get(entry.source_field, ""))
                status = "mapped" if sample_value else "missing"
                if not sample_value:
                    message = f"{entry.target_display_name} has no source value."
            elif entry.mapping_kind == MAPPING_KIND_CONSTANT:
                sample_value = entry.constant_value
                status = "constant"
            elif entry.mapping_kind == MAPPING_KIND_UNMAPPED:
                if field.required_status == "required":
                    message = f"{field.display_name} is required."
                    blocking_issues.append(message)
            feedback_entries.append(
                replace(
                    entry,
                    status=status,
                    message=message,
                    sample_value=sample_value,
                )
            )

        headers = tuple(field.display_name for field in session.template_profile.target_fields)
        for row_index in session.included_row_indices:
            source_row = session.source_profile.rows[row_index]
            rendered_row: list[str] = []
            for entry in session.mapping_entries:
                if entry.mapping_kind == MAPPING_KIND_SOURCE:
                    rendered_row.append(str(source_row.get(entry.source_field, "")))
                elif entry.mapping_kind == MAPPING_KIND_CONSTANT:
                    rendered_row.append(entry.constant_value)
                else:
                    rendered_row.append("")
            rendered_rows.append(tuple(rendered_row))

        return ConversionPreview(
            template_profile=session.template_profile,
            source_profile=session.source_profile,
            mapping_entries=tuple(feedback_entries),
            included_row_indices=tuple(session.included_row_indices),
            rendered_headers=headers,
            rendered_rows=tuple(rendered_rows),
            blocking_issues=tuple(dict.fromkeys(blocking_issues)),
        )


class _SavedTemplateStore:
    def __init__(self, records: tuple[SavedConversionTemplateRecord, ...] = ()) -> None:
        self.records = list(records)
        self.save_calls: list[dict[str, object]] = []
        self._next_id = max((record.id for record in self.records), default=0) + 1

    def list_saved_templates(self) -> tuple[SavedConversionTemplateRecord, ...]:
        return tuple(self.records)

    def load_saved_template(self, template_id: int) -> SavedConversionTemplateRecord:
        for record in self.records:
            if record.id == template_id:
                return record
        raise ValueError(f"missing saved template {template_id}")

    def save_template(self, **kwargs) -> SavedConversionTemplateRecord:
        self.save_calls.append(dict(kwargs))
        profile = kwargs["template_profile"]
        assert isinstance(profile, ConversionTemplateProfile)
        record = SavedConversionTemplateRecord(
            id=self._next_id,
            name=str(kwargs["name"]),
            filename=profile.template_path.name,
            format_name=profile.format_name,
            source_mode=str(kwargs.get("source_mode") or ""),
            mapping_payload=str(kwargs.get("mapping_payload") or ""),
        )
        self._next_id += 1
        self.records.append(record)
        return record


class ConversionDialogCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = require_qapplication()

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.settings = QSettings(str(self.root / "conversion.ini"), QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)

    def tearDown(self) -> None:
        self.settings.clear()
        self.settings.sync()
        self.tmpdir.cleanup()

    def _dialog(
        self,
        *,
        service: _DialogService | None = None,
        template_store_service=None,
        profile_available: bool = False,
        export_callback=None,
    ) -> ConversionDialog:
        return ConversionDialog(
            service=service or _DialogService(),
            settings=self.settings,
            template_store_service=template_store_service,
            export_callback=export_callback or (lambda _preview, _path: None),
            exports_dir=self.root,
            profile_available=profile_available,
            parent=None,
        )

    def _load_template_and_source(
        self,
        dialog: ConversionDialog,
        service: _DialogService,
    ) -> None:
        dialog.template_profile = service.inspect_template_bytes(
            "template.csv",
            b"title,year\n",
            source_label="Template bytes",
        )
        dialog._populate_scope_combo(
            dialog.template_scope_combo,
            dialog.template_profile.available_scopes,
        )
        dialog._inspect_source_file(str(self.root / "source.csv"))
        pump_events(app=self.app)

    def test_saved_template_payload_filters_incompatible_duplicates_and_keeps_file_mode(
        self,
    ) -> None:
        record = SavedConversionTemplateRecord(
            id=7,
            name="Profile Template",
            filename="profile-template.csv",
            format_name="csv",
            chosen_scope="main",
            source_mode=SOURCE_MODE_DATABASE_TRACKS,
            mapping_payload="stored-payload",
            template_bytes=b"title,year\n",
        )
        service = _DialogService()
        store = _SavedTemplateStore((record,))
        dialog = self._dialog(
            service=service,
            template_store_service=store,
            profile_available=False,
        )
        try:
            dialog._load_selected_saved_template()

            self.assertEqual(service.selected_template_scopes, ["main"])
            self.assertEqual(dialog.source_mode_combo.currentData(), SOURCE_MODE_FILE)
            self.assertEqual(dialog._pending_saved_template_mapping_payload, "stored-payload")
            self.assertIsNone(dialog.session)

            dialog._inspect_source_file(str(self.root / "source.csv"))
            pump_events(app=self.app)

            self.assertEqual(service.deserialize_payloads, ["stored-payload"])
            self.assertEqual(dialog._pending_saved_template_mapping_payload, "")
            self.assertIsNotNone(dialog.preview)

            title_row = next(
                row
                for row in range(dialog.mapping_table.rowCount())
                if dialog.mapping_table.item(row, 0).text() == "Title"
            )
            title_combo = dialog.mapping_table.cellWidget(title_row, 2)
            title_constant = dialog.mapping_table.cellWidget(title_row, 3)
            self.assertIsInstance(title_combo, QComboBox)
            self.assertIsInstance(title_constant, QLineEdit)
            self.assertEqual(title_combo.currentData(), "__conversion_constant__")
            self.assertEqual(title_constant.text(), "Archived title")

            year_row = next(
                row
                for row in range(dialog.mapping_table.rowCount())
                if dialog.mapping_table.item(row, 0).text() == "Year"
            )
            year_combo = dialog.mapping_table.cellWidget(year_row, 2)
            self.assertIsInstance(year_combo, QComboBox)
            self.assertEqual(year_combo.currentData(), "__conversion_unmapped__")
        finally:
            dialog.close()

    def test_source_table_ignores_non_use_column_and_sync_guard_until_user_change(
        self,
    ) -> None:
        service = _DialogService()
        dialog = self._dialog(service=service)
        try:
            self._load_template_and_source(dialog, service)
            initial_preview_calls = service.build_preview_calls
            self.assertEqual(dialog.session.included_row_indices, (0,))

            data_item = dialog.source_table.item(0, 1)
            self.assertIsNotNone(data_item)
            dialog._on_source_table_item_changed(data_item)
            self.assertEqual(service.build_preview_calls, initial_preview_calls)
            self.assertEqual(dialog.session.included_row_indices, (0,))

            use_item = dialog.source_table.item(0, 0)
            self.assertIsNotNone(use_item)
            dialog._source_table_sync = True
            use_item.setCheckState(Qt.Unchecked)
            dialog._on_source_table_item_changed(use_item)
            dialog._source_table_sync = False

            self.assertEqual(service.build_preview_calls, initial_preview_calls)
            self.assertEqual(dialog.session.included_row_indices, (0,))

            dialog._on_source_table_item_changed(use_item)

            self.assertEqual(service.build_preview_calls, initial_preview_calls + 1)
            self.assertEqual(dialog.session.included_row_indices, ())
            self.assertEqual(dialog.output_table.rowCount(), 0)
            self.assertFalse(dialog.export_button.isEnabled())
        finally:
            dialog.close()

    def test_output_preview_reports_blocking_warnings_and_toggles_xml_preview(
        self,
    ) -> None:
        dialog = self._dialog()
        try:
            source_profile = _source_profile()
            xml_template = _template_profile(format_name="xml", output_suffix=".xml")
            dialog.preview = ConversionPreview(
                template_profile=xml_template,
                source_profile=source_profile,
                mapping_entries=(),
                included_row_indices=(0,),
                rendered_headers=("Title",),
                rendered_rows=(("Orbit",),),
                rendered_xml_text="<release><title>Orbit</title></release>",
                warnings=("Optional year is empty.",),
                blocking_issues=("Title is required.",),
            )

            dialog._update_output_ui()

            self.assertIn("Blocking issues", dialog.output_status_label.text())
            self.assertIn("Title is required", dialog.output_status_label.text())
            self.assertIn("Warnings", dialog.output_status_label.text())
            self.assertEqual(dialog.output_table.rowCount(), 1)
            self.assertEqual(dialog.output_table.item(0, 0).text(), "Orbit")
            self.assertEqual(
                dialog.xml_preview_edit.toPlainText(),
                "<release><title>Orbit</title></release>",
            )
            self.assertFalse(dialog.xml_preview_edit.isHidden())
            self.assertFalse(dialog.export_button.isEnabled())

            dialog.preview = replace(
                dialog.preview,
                template_profile=_template_profile(),
                rendered_rows=(),
                rendered_xml_text="",
                warnings=(),
                blocking_issues=(),
            )
            dialog._update_output_ui()

            self.assertTrue(dialog.xml_preview_edit.isHidden())
            self.assertFalse(dialog.export_button.isEnabled())
        finally:
            dialog.close()

    def test_saved_template_labels_preserve_selection_and_empty_mapping_save_payload(
        self,
    ) -> None:
        records = (
            SavedConversionTemplateRecord(
                id=1,
                name="Template",
                filename="template",
                format_name="csv",
            ),
            SavedConversionTemplateRecord(
                id=2,
                name="Producer Export",
                filename="producer-template.csv",
                format_name="csv",
            ),
        )
        service = _DialogService()
        store = _SavedTemplateStore(records)
        dialog = self._dialog(service=service, template_store_service=store)
        try:
            self.assertEqual(dialog.saved_template_combo.itemText(0), "Template")
            self.assertEqual(
                dialog.saved_template_combo.itemText(1),
                "Producer Export (producer-template.csv)",
            )

            dialog.saved_template_combo.setCurrentIndex(1)
            store.records = [records[1], records[0]]
            dialog._reload_saved_template_names()
            self.assertEqual(dialog.saved_template_combo.currentData(), 2)

            dialog.template_profile = _template_profile()
            dialog.saved_template_name_edit.setText("No Mapping Template")
            dialog.include_mapping_in_saved_template_checkbox.setChecked(True)
            with mock.patch.object(QMessageBox, "information", return_value=None) as information:
                dialog._save_template_to_profile()

            self.assertEqual(store.save_calls[-1]["name"], "No Mapping Template")
            self.assertEqual(store.save_calls[-1]["mapping_payload"], "")
            self.assertEqual(store.save_calls[-1]["source_mode"], SOURCE_MODE_FILE)
            self.assertEqual(service.serialized_entries, [])
            self.assertNotIn("mapping was stored", information.call_args.args[2])
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()

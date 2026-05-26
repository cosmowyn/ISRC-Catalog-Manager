import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import isrc_manager.contract_templates.export_service as export_service_module
from isrc_manager.code_registry import (
    BUILTIN_CATEGORY_CATALOG_NUMBER,
    BUILTIN_CATEGORY_CONTRACT_NUMBER,
    BUILTIN_CATEGORY_LICENSE_NUMBER,
)
from isrc_manager.contract_templates import (
    ContractTemplateCatalogService,
    ContractTemplateExportError,
    ContractTemplateExportService,
    ContractTemplatePayload,
    ContractTemplateRevisionPayload,
    ContractTemplateService,
    QtWebEngineHtmlPdfAdapter,
)
from isrc_manager.contract_templates.models import (
    build_contract_template_indexed_selection_key,
    build_contract_template_selector_scope_key,
)
from isrc_manager.contracts import ContractPayload, ContractService
from isrc_manager.releases import ReleasePayload, ReleaseService, ReleaseTrackPlacement
from isrc_manager.services import (
    ContractTemplateDraftPayload,
    DatabaseSchemaService,
    PartyPayload,
    PartyService,
    SettingsReadService,
    TrackCreatePayload,
    TrackService,
)
from tests.contract_templates._support import (
    FakeDocxHtmlAdapter,
    FakeHtmlPdfAdapter,
    FakePagesAdapter,
    make_docx_bytes,
)
from tests.qt_test_helpers import require_qapplication


class _FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self._callbacks):
            callback(*args)


class _FakeApplication:
    _instance = None

    def __init__(self, *_args):
        type(self)._instance = self

    @classmethod
    def instance(cls):
        return cls._instance


class _FakeEventLoop:
    def __init__(self):
        self.quit_count = 0

    def exec(self):
        return None

    def quit(self):
        self.quit_count += 1


class _FakeTimer:
    callbacks = []

    @staticmethod
    def singleShot(_timeout_ms, callback):
        _FakeTimer.callbacks.append(callback)
        callback()


class _FakeWebEngineView:
    def __init__(self, parent=None):
        self.parent = parent


class _FakeWebEnginePage:
    load_ok = True
    pdf_success = True
    write_output = True
    instances = []

    def __init__(self):
        self.loadFinished = _FakeSignal()
        self.pdfPrintingFinished = _FakeSignal()
        self.loaded_url = None
        self.html_text = None
        self.base_url = None
        type(self).instances.append(self)

    def load(self, url):
        self.loaded_url = url
        self.loadFinished.emit(type(self).load_ok)

    def setHtml(self, html_text, base_url):
        self.html_text = html_text
        self.base_url = base_url
        self.loadFinished.emit(type(self).load_ok)

    def printToPdf(self, path):
        if type(self).pdf_success and type(self).write_output:
            Path(path).write_bytes(b"%PDF-1.4\n% fake-webengine\n")
        self.pdfPrintingFinished.emit(str(path), type(self).pdf_success)


class ContractTemplateExportServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = require_qapplication()

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        schema = DatabaseSchemaService(self.conn, data_root=self.root)
        schema.init_db()
        schema.migrate_schema()
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_kv (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        self.track_service = TrackService(self.conn, self.root)
        self.primary_track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-00601",
                track_title="Export Service Song",
                artist_name="Moonwake",
                additional_artists=[],
                album_title="Export Coverage",
                release_date="2026-03-25",
                track_length_sec=221,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
            )
        )
        self.legacy_track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-00602",
                track_title="Legacy Conflict Song",
                artist_name="Lyra",
                additional_artists=[],
                album_title="Export Coverage",
                release_date="2026-03-26",
                track_length_sec=225,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
            )
        )
        self.release_service = ReleaseService(self.conn, self.root)
        self.party_service = PartyService(self.conn)
        self.contract_service = ContractService(
            self.conn,
            self.root,
            party_service=self.party_service,
        )
        self.party_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Aeonium Holdings B.V.",
                display_name="Aeonium",
                artist_name="Aeonium Official",
                company_name="Aeonium Holdings",
                email="hello@moonium.test",
                alternative_email="legal@moonium.test",
                chamber_of_commerce_number="CoC-778899",
                vat_number="PARTY-VAT",
                pro_number="PRO-778899",
                ipi_cae="PARTY-IPI",
                artist_aliases=["Aeonium Alias", "Lyra Cosmos"],
            )
        )
        self.owner_party_id = self.party_service.create_party(
            PartyPayload(
                legal_name="Moonwake Records B.V.",
                display_name="Moonwake Records",
                artist_name="Lyra Moonwake",
                company_name="Moonwake Records",
                email="hello@moonwake.test",
                country="Netherlands",
                vat_number="BTW-OWNER",
                pro_number="REL-OWNER",
                ipi_cae="IPI-OWNER",
                party_type="organization",
            )
        )
        with self.conn:
            self.conn.execute(
                "INSERT INTO ApplicationOwnerBinding(id, party_id) VALUES(1, ?)",
                (self.owner_party_id,),
            )
        self.release_id = self.release_service.create_release(
            ReleasePayload(
                title="Export Coverage Release",
                primary_artist="Moonwake",
                release_date="2026-03-25",
                placements=[ReleaseTrackPlacement(track_id=self.primary_track_id)],
            )
        )
        self.contract_id = self.contract_service.create_contract(
            ContractPayload(
                title="Export Registry Contract",
                contract_type="license",
                status="draft",
            )
        )
        self.settings_reads = SettingsReadService(self.conn)
        self.catalog_service = ContractTemplateCatalogService(self.conn)
        self.template_service = ContractTemplateService(self.conn, data_root=self.root)
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Export Template",
                description="Phase 6 export coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "export-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Track ", "{{db.track.track_title}}"),
                    ("Date ", "{{manual.license_date}}"),
                ),
                header_paragraphs=(("Artist ", "{{db.track.artist_name}}"),),
            )
        )
        self.revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        self.draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=self.revision.revision_id,
                name="Export Draft",
                editable_payload={
                    "revision_id": self.revision.revision_id,
                    "db_selections": {
                        "{{db.track.track_title}}": "1",
                        "{{db.track.artist_name}}": "1",
                    },
                    "manual_values": {
                        "{{manual.license_date}}": "2026-03-31",
                    },
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )
        self.html_adapter = FakeDocxHtmlAdapter()
        self.html_pdf_adapter = FakeHtmlPdfAdapter()
        self.pages_adapter = FakePagesAdapter()
        self.export_service = ContractTemplateExportService(
            template_service=self.template_service,
            catalog_service=self.catalog_service,
            settings_reads=self.settings_reads,
            track_service=self.track_service,
            release_service=self.release_service,
            contract_service=self.contract_service,
            party_service=self.party_service,
            html_adapter=self.html_adapter,
            html_pdf_adapter=self.html_pdf_adapter,
            pages_adapter=self.pages_adapter,
        )

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _patched_webengine(
        self,
        *,
        load_ok: bool = True,
        pdf_success: bool = True,
        write_output: bool = True,
    ) -> ExitStack:
        _FakeApplication._instance = None
        _FakeTimer.callbacks = []
        _FakeWebEnginePage.instances = []
        _FakeWebEnginePage.load_ok = load_ok
        _FakeWebEnginePage.pdf_success = pdf_success
        _FakeWebEnginePage.write_output = write_output
        stack = ExitStack()
        stack.enter_context(patch.object(export_service_module, "QApplication", _FakeApplication))
        stack.enter_context(
            patch.object(export_service_module, "QWebEnginePage", _FakeWebEnginePage)
        )
        stack.enter_context(
            patch.object(export_service_module, "QWebEngineView", _FakeWebEngineView)
        )
        stack.enter_context(patch.object(export_service_module, "QEventLoop", _FakeEventLoop))
        stack.enter_context(patch.object(export_service_module, "QTimer", _FakeTimer))
        return stack

    def _set_registry_prefix(self, system_key: str, prefix: str | None) -> None:
        registry = self.track_service.code_registry_service()
        category = registry.fetch_category_by_system_key(system_key)
        self.assertIsNotNone(category)
        assert category is not None
        registry.update_category(category.id, prefix=prefix)

    def _create_registry_draft(
        self,
        *,
        name: str,
        document_paragraphs: tuple[tuple[str, str], ...],
        db_selections: dict[str, str],
    ):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name=name,
                description="Registry-backed export coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / f"{name.lower().replace(' ', '-')}.docx"
        source_path.write_bytes(make_docx_bytes(document_paragraphs=document_paragraphs))
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name=f"{name} Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": dict(db_selections),
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )
        return revision, draft

    def _export_service_with(self, **overrides):
        dependencies = {
            "template_service": self.template_service,
            "catalog_service": self.catalog_service,
            "settings_reads": self.settings_reads,
            "track_service": self.track_service,
            "release_service": self.release_service,
            "contract_service": self.contract_service,
            "party_service": self.party_service,
            "html_adapter": self.html_adapter,
            "html_pdf_adapter": self.html_pdf_adapter,
            "pages_adapter": self.pages_adapter,
        }
        dependencies.update(overrides)
        return ContractTemplateExportService(**dependencies)

    def test_qt_webengine_adapter_renders_with_deterministic_page_and_base_urls(self):
        source = self.root / "native-preview.html"
        source.write_text("<html><body>{{current.year}}</body></html>", encoding="utf-8")
        file_output = self.root / "file-output.pdf"
        html_output = self.root / "html-output.pdf"

        with self._patched_webengine():
            adapter = QtWebEngineHtmlPdfAdapter(timeout_ms=5)

            self.assertEqual(adapter.timeout_ms, 1000)
            self.assertTrue(adapter.is_available())
            self.assertIsNone(adapter.availability_message())
            self.assertIsInstance(adapter.create_view(parent="preview"), _FakeWebEngineView)

            rendered_file = adapter.render_file_to_pdf(source, file_output)
            rendered_html = adapter.render_html_to_pdf(
                "<p>Resolved HTML</p>",
                base_url=source,
                output_path=html_output,
            )

            self.assertEqual(rendered_file, file_output)
            self.assertEqual(rendered_html, html_output)
            self.assertTrue(file_output.read_bytes().startswith(b"%PDF"))
            self.assertTrue(html_output.read_bytes().startswith(b"%PDF"))
            self.assertEqual(len(_FakeTimer.callbacks), 2)
            self.assertEqual(
                _FakeWebEnginePage.instances[0].loaded_url.toLocalFile(),
                str(source.resolve()),
            )
            self.assertEqual(_FakeWebEnginePage.instances[1].html_text, "<p>Resolved HTML</p>")
            self.assertEqual(
                _FakeWebEnginePage.instances[1].base_url.toLocalFile(),
                f"{source.parent.resolve()}/",
            )
            self.assertEqual(adapter._as_base_url(None).toString(), "")

    def test_qt_webengine_adapter_reports_load_print_and_missing_output_failures(self):
        missing_source = self.root / "missing.html"
        source = self.root / "native-preview.html"
        source.write_text("<html><body>Native preview</body></html>", encoding="utf-8")

        with self._patched_webengine():
            adapter = QtWebEngineHtmlPdfAdapter(timeout_ms=5)
            with self.assertRaisesRegex(ContractTemplateExportError, "source does not exist"):
                adapter.render_file_to_pdf(missing_source, self.root / "missing.pdf")

        with self._patched_webengine(load_ok=False):
            adapter = QtWebEngineHtmlPdfAdapter(timeout_ms=5)
            with self.assertRaisesRegex(ContractTemplateExportError, "Failed to load HTML source"):
                adapter.render_file_to_pdf(source, self.root / "load-failed.pdf")

        with self._patched_webengine(pdf_success=False):
            adapter = QtWebEngineHtmlPdfAdapter(timeout_ms=5)
            with self.assertRaisesRegex(ContractTemplateExportError, "failed to write PDF"):
                adapter.render_html_to_pdf(
                    "<p>Print failure</p>",
                    base_url=self.root,
                    output_path=self.root / "print-failed.pdf",
                )

        with self._patched_webengine(write_output=False):
            adapter = QtWebEngineHtmlPdfAdapter(timeout_ms=5)
            with self.assertRaisesRegex(ContractTemplateExportError, "did not produce"):
                adapter.render_html_to_pdf(
                    "<p>No output</p>",
                    base_url=None,
                    output_path=self.root / "no-output.pdf",
                )

    def test_qt_webengine_adapter_reports_file_print_html_load_and_trailing_base_edges(self):
        source = self.root / "print-failure.html"
        source.write_text("<html><body>print failure</body></html>", encoding="utf-8")

        with self._patched_webengine(pdf_success=False):
            adapter = QtWebEngineHtmlPdfAdapter(timeout_ms=5)
            with self.assertRaisesRegex(ContractTemplateExportError, "failed to write PDF"):
                adapter.render_file_to_pdf(source, self.root / "file-print-failure.pdf")

        with self._patched_webengine(load_ok=False):
            adapter = QtWebEngineHtmlPdfAdapter(timeout_ms=5)
            with self.assertRaisesRegex(ContractTemplateExportError, "Failed to load HTML content"):
                adapter.render_html_to_pdf(
                    "<p>load failure</p>",
                    base_url=f"{self.root}/",
                    output_path=self.root / "html-load-failure.pdf",
                )

        base = QtWebEngineHtmlPdfAdapter._as_base_url(f"{self.root}/")
        self.assertTrue(base.toLocalFile().endswith("/"))

    def test_export_draft_to_pdf_creates_snapshot_and_artifacts(self):
        result = self.export_service.export_draft_to_pdf(self.draft.draft_id)

        updated_draft = self.template_service.fetch_draft(self.draft.draft_id)
        self.assertIsNotNone(updated_draft)
        self.assertEqual(updated_draft.last_resolved_snapshot_id, result.snapshot.snapshot_id)
        self.assertEqual(result.pdf_artifact.artifact_type, "pdf")
        self.assertEqual(result.resolved_docx_artifact.artifact_type, "resolved_docx")
        self.assertIsNotNone(result.resolved_html_artifact)
        self.assertEqual(result.resolved_html_artifact.artifact_type, "resolved_html")
        self.assertTrue(result.pdf_artifact.output_path.endswith(".pdf"))
        self.assertTrue(result.resolved_docx_artifact.output_path.endswith(".docx"))
        self.assertTrue(result.resolved_html_artifact.output_path.endswith(".html"))
        self.assertTrue(Path(result.pdf_artifact.output_path).exists())
        self.assertTrue(Path(result.resolved_docx_artifact.output_path).exists())
        self.assertTrue(Path(result.resolved_html_artifact.output_path).exists())
        self.assertTrue(Path(result.pdf_artifact.output_path).read_bytes().startswith(b"%PDF"))
        resolved_docx_bytes = Path(result.resolved_docx_artifact.output_path).read_bytes()
        self.assertEqual(
            self.template_service.docx_scanner.scan_bytes(resolved_docx_bytes).placeholders,
            (),
        )
        artifacts = self.template_service.list_output_artifacts(
            snapshot_id=result.snapshot.snapshot_id
        )
        self.assertEqual(
            [artifact.artifact_type for artifact in artifacts],
            ["pdf", "resolved_docx", "resolved_html"],
        )
        self.assertEqual(len(self.pages_adapter.pdf_calls), 0)
        self.assertEqual(len(self.html_adapter.calls), 0)
        self.assertEqual(
            result.snapshot.resolved_values,
            {
                "{{db.track.artist_name}}": "Moonwake",
                "{{db.track.track_title}}": "Export Service Song",
                "{{manual.license_date}}": "31.Mar.2026",
            },
        )
        self.assertEqual(
            result.snapshot.preview_payload.get("renderer"),
            "fake_html_pdf",
        )
        self.assertEqual(result.snapshot.preview_payload.get("source_format"), "docx")
        self.assertEqual(result.snapshot.preview_payload.get("working_format"), "html")

    def test_export_draft_to_pdf_rejects_missing_manual_values(self):
        broken = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=self.revision.revision_id,
                name="Broken Export Draft",
                editable_payload={
                    "revision_id": self.revision.revision_id,
                    "db_selections": {
                        "{{db.track.track_title}}": "1",
                        "{{db.track.artist_name}}": "1",
                    },
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        with self.assertRaises(ContractTemplateExportError):
            self.export_service.export_draft_to_pdf(broken.draft_id)

    def test_export_rejects_missing_draft_revision_template_and_unsupported_revision(self):
        with self.assertRaisesRegex(ContractTemplateExportError, "draft 999999 not found"):
            self.export_service.export_draft_to_pdf(999999)

        with patch.object(self.template_service, "fetch_revision", return_value=None):
            with self.assertRaisesRegex(ContractTemplateExportError, "revision 999999 not found"):
                self.export_service.export_editable_payload_to_pdf(
                    revision_id=999999,
                    editable_payload={},
                    draft_id=self.draft.draft_id,
                )

        with patch.object(self.template_service, "fetch_template", return_value=None):
            with self.assertRaisesRegex(ContractTemplateExportError, "template .* not found"):
                self.export_service.export_editable_payload_to_pdf(
                    revision_id=self.revision.revision_id,
                    editable_payload=self.template_service.fetch_draft_payload(self.draft.draft_id),
                    draft_id=self.draft.draft_id,
                )

        with patch.object(
            self.template_service,
            "revision_supports_html_working_draft",
            return_value=False,
        ):
            with self.assertRaisesRegex(ContractTemplateExportError, "cannot be normalized"):
                self.export_service.export_editable_payload_to_pdf(
                    revision_id=self.revision.revision_id,
                    editable_payload=self.template_service.fetch_draft_payload(self.draft.draft_id),
                    draft_id=self.draft.draft_id,
                )

    def test_export_helper_edges_for_duplicate_index_and_date_controls(self):
        self.assertEqual(
            self.export_service._runtime_replacements_for_text("{{current.year}}", {}),
            {"{{current.year}}": str(date.today().year)},
        )
        self.assertEqual(self.export_service._runtime_replacements_for_text("static", {}), {})
        self.assertEqual(self.export_service._resolve_current_value("quarter"), "")
        self.assertEqual(
            self.export_service._apply_index_controls(
                "{{page.index}}/{{page.total}} {{page.index}} {{custom.index}} {{custom.index}}"
            ),
            "1/2 2 1 2",
        )
        self.assertEqual(
            self.export_service._html_output_filename("My Draft: Final?", "source.html"),
            "My-Draft-Final.html",
        )
        self.assertEqual(
            self.export_service._html_output_filename(None, "source template.html"),
            "source-template.html",
        )
        self.assertEqual(self.export_service._coerce_record_id(" 12 "), 12)
        self.assertIsNone(self.export_service._coerce_record_id("0"))
        self.assertIsNone(self.export_service._coerce_record_id("not an id"))

        date_placeholder = SimpleNamespace(
            inferred_field_type="",
            placeholder_key="renewal_deadline",
        )
        text_placeholder = SimpleNamespace(
            inferred_field_type="",
            placeholder_key="description",
        )
        self.assertTrue(
            self.export_service._is_manual_date_placeholder(date_placeholder, binding=None)
        )
        self.assertFalse(
            self.export_service._is_manual_date_placeholder(
                text_placeholder,
                binding=SimpleNamespace(validation={"field_type": "text"}),
            )
        )

    def test_duplicate_controls_preview_strict_and_indexed_warning_paths(self):
        html = "A{{duplicate.start}}" "{{db.track.track_title}} #{{db.index}}" "{{duplicate.end}}Z"
        rendered, warnings = self.export_service._apply_duplicate_controls(
            html,
            {
                "manual_values": {},
                "db_selections": {
                    build_contract_template_indexed_selection_key(
                        "{{db.track.track_title}}",
                        1,
                    ): str(self.primary_track_id),
                },
            },
            strict=False,
        )

        self.assertIn("{{db.track.track_title}} #1", rendered)
        self.assertIn("Duplicate block preview uses one copy", warnings[0])
        indexed_warnings: list[str] = []
        indexed = self.export_service._indexed_db_replacements(
            symbols=("{{db.track.track_title}}",),
            index=1,
            db_selections={
                build_contract_template_indexed_selection_key(
                    "{{db.track.track_title}}",
                    1,
                ): str(self.primary_track_id),
            },
            draft_id=None,
            allow_registry_generation=False,
            strict=True,
            warnings=indexed_warnings,
        )
        self.assertEqual(indexed, {"{{db.track.track_title}}": "Export Service Song"})
        self.assertEqual(indexed_warnings, [])

        missing_index_warnings: list[str] = []
        missing_index = self.export_service._indexed_db_replacements(
            symbols=("{{db.track.track_title}}",),
            index=2,
            db_selections={},
            draft_id=None,
            allow_registry_generation=False,
            strict=False,
            warnings=missing_index_warnings,
        )
        self.assertEqual(missing_index, {"{{db.track.track_title}}": ""})
        self.assertIn("does not have a selected record", missing_index_warnings[0])
        with self.assertRaisesRegex(ContractTemplateExportError, "does not have a selected record"):
            self.export_service._indexed_db_replacements(
                symbols=("{{db.track.track_title}}",),
                index=2,
                db_selections={},
                draft_id=None,
                allow_registry_generation=False,
                strict=True,
                warnings=[],
            )

        stale_index_warnings: list[str] = []
        stale_index = self.export_service._indexed_db_replacements(
            symbols=("{{db.track.track_title}}",),
            index=3,
            db_selections={
                build_contract_template_indexed_selection_key(
                    "{{db.track.track_title}}",
                    3,
                ): "999999",
            },
            draft_id=None,
            allow_registry_generation=False,
            strict=False,
            warnings=stale_index_warnings,
        )
        self.assertEqual(stale_index, {})
        self.assertIn("could not be resolved", stale_index_warnings[0])

        repeated, repeat_warnings = self.export_service._apply_duplicate_controls(
            "{{duplicate.start}}X{{duplicate.end}}",
            {"manual_values": {"{{duplicate.number}}": "3"}},
            strict=True,
        )
        self.assertEqual(repeated, "XXX")
        self.assertEqual(repeat_warnings, ())

        malformed, malformed_warnings = self.export_service._apply_duplicate_controls(
            "{{duplicate.end}} stray",
            {"manual_values": {"{{duplicate.number}}": "1"}},
            strict=False,
        )
        self.assertEqual(malformed, " stray")
        self.assertIn("Duplicate cymbols must use", malformed_warnings[0])
        with self.assertRaises(ContractTemplateExportError):
            self.export_service._apply_duplicate_controls(
                "{{duplicate.end}}",
                {"manual_values": {"{{duplicate.number}}": "1"}},
                strict=True,
            )

    def test_duplicate_copy_count_validation_errors_are_explicit(self):
        self.assertIsNone(self.export_service._duplicate_copy_count("", strict=False))
        self.assertEqual(self.export_service._duplicate_copy_count("2", strict=True), 2)
        for value, message in (
            ("", "Duplicate Number is required"),
            ("1.5", "whole number"),
            ("-1", "cannot be negative"),
            ("201", "cannot be greater"),
        ):
            with self.subTest(value=value):
                with self.assertRaises(ContractTemplateExportError) as exc_info:
                    self.export_service._duplicate_copy_count(value, strict=True)
                self.assertIn(message, str(exc_info.exception))

    def test_resolve_payload_values_reports_removed_catalog_and_duplicate_edges(self):
        duplicate_template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Duplicate Control Export Template",
                description="Strict duplicate control coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        duplicate_source = self.root / "duplicate-control-export-template.docx"
        duplicate_source.write_bytes(
            make_docx_bytes(document_paragraphs=(("Copies ", "{{duplicate.number}}"),))
        )
        duplicate_revision = self.template_service.import_revision_from_path(
            duplicate_template.template_id,
            duplicate_source,
            payload=ContractTemplateRevisionPayload(source_filename=duplicate_source.name),
        ).revision

        with self.assertRaisesRegex(ContractTemplateExportError, "does not have a saved value"):
            self.export_service._resolve_payload_values(
                duplicate_revision.revision_id,
                {"manual_values": {}},
                strict=True,
            )
        resolved, warnings = self.export_service._resolve_payload_values(
            duplicate_revision.revision_id,
            {"manual_values": {}},
            strict=False,
        )
        self.assertEqual(resolved, {"{{duplicate.number}}": ""})
        self.assertEqual(warnings, ())

        orphan_template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Removed Catalog Export Template",
                description="Removed catalog symbol coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        orphan_source = self.root / "removed-catalog-export-template.docx"
        orphan_source.write_bytes(
            make_docx_bytes(document_paragraphs=(("Unknown ", "{{db.unknown.value}}"),))
        )
        orphan_revision = self.template_service.import_revision_from_path(
            orphan_template.template_id,
            orphan_source,
            payload=ContractTemplateRevisionPayload(source_filename=orphan_source.name),
        ).revision

        with self.assertRaisesRegex(
            ContractTemplateExportError, "not present in the symbol catalog"
        ):
            self.export_service._resolve_payload_values(
                orphan_revision.revision_id, {}, strict=True
            )
        resolved, warnings = self.export_service._resolve_payload_values(
            orphan_revision.revision_id,
            {},
            strict=False,
        )
        self.assertEqual(resolved, {})
        self.assertEqual(
            warnings,
            (
                "Skipped {{db.unknown.value}} because it is no longer present in the symbol catalog.",
            ),
        )

        track_template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Track Selection Export Template",
                description="Selected track boundary coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        track_source = self.root / "track-selection-export-template.docx"
        track_source.write_bytes(
            make_docx_bytes(document_paragraphs=(("Track ", "{{db.track.track_title}}"),))
        )
        track_revision = self.template_service.import_revision_from_path(
            track_template.template_id,
            track_source,
            payload=ContractTemplateRevisionPayload(source_filename=track_source.name),
        ).revision

        with self.assertRaisesRegex(ContractTemplateExportError, "selected record"):
            self.export_service._resolve_payload_values(track_revision.revision_id, {}, strict=True)
        resolved, warnings = self.export_service._resolve_payload_values(
            track_revision.revision_id,
            {},
            strict=False,
        )
        self.assertEqual(resolved, {})
        self.assertEqual(warnings, ())
        resolved, warnings = self.export_service._resolve_payload_values(
            track_revision.revision_id,
            {},
            strict=True,
            duplicate_iterated_symbols={"{{db.track.track_title}}"},
        )
        self.assertEqual(resolved, {"{{db.track.track_title}}": ""})
        self.assertEqual(warnings, ())
        resolved, warnings = self.export_service._resolve_payload_values(
            track_revision.revision_id,
            {"db_selections": {"{{db.track.track_title}}": "999999"}},
            strict=False,
        )
        self.assertEqual(resolved, {})
        self.assertEqual(
            warnings,
            (
                "Skipped {{db.track.track_title}} because its selected record could not be resolved.",
            ),
        )

    def test_resolve_catalog_value_reports_service_record_and_registry_boundaries(self):
        def entry(namespace, key, *, canonical=None, custom_field_id=None):
            return SimpleNamespace(
                namespace=namespace,
                key=key,
                canonical_symbol=canonical or f"{{{{db.{namespace}.{key}}}}}",
                custom_field_id=custom_field_id,
            )

        with self.assertRaisesRegex(ContractTemplateExportError, "settings reads are missing"):
            self._export_service_with(settings_reads=None)._resolve_catalog_value(
                catalog_entry=entry("owner", "display_name"),
                selection_value=None,
            )

        cases = (
            (
                self._export_service_with(track_service=None),
                entry("track", "track_title"),
                1,
                "Track service",
            ),
            (self.export_service, entry("track", "track_title"), 999999, "Track #999999"),
            (
                self._export_service_with(release_service=None),
                entry("release", "title"),
                1,
                "Release service",
            ),
            (self.export_service, entry("release", "title"), 999999, "Release #999999"),
            (
                self._export_service_with(contract_service=None),
                entry("contract", "title"),
                1,
                "Contract service",
            ),
            (self.export_service, entry("contract", "title"), 999999, "Contract #999999"),
            (
                self._export_service_with(party_service=None),
                entry("party", "display_name"),
                1,
                "Party service",
            ),
            (self.export_service, entry("party", "display_name"), 999999, "Party #999999"),
            (self.export_service, entry("work", "title"), 1, "Work service"),
            (self.export_service, entry("right", "title"), 1, "Rights service"),
            (self.export_service, entry("asset", "title"), 1, "Asset service"),
            (
                self.export_service,
                entry("custom", "cf_7", custom_field_id=7),
                1,
                "Custom field value service",
            ),
            (
                self.export_service,
                entry("unsupported", "value"),
                1,
                "Unsupported placeholder namespace",
            ),
        )
        for service, catalog_entry, selection_value, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(ContractTemplateExportError) as exc_info:
                    service._resolve_catalog_value(
                        catalog_entry=catalog_entry,
                        selection_value=selection_value,
                    )
                self.assertIn(message, str(exc_info.exception))

        for symbol, service, message in (
            (
                "{{db.contract.contract_number}}",
                self._export_service_with(contract_service=None),
                "Contract service is unavailable",
            ),
            (
                "{{db.track.catalog_number}}",
                self._export_service_with(track_service=None),
                "Track service is unavailable",
            ),
            (
                "{{db.release.catalog_number}}",
                self._export_service_with(release_service=None),
                "Release service is unavailable",
            ),
            (
                "{{db.track.catalog_number}}",
                self._export_service_with(
                    track_service=SimpleNamespace(code_registry_service=lambda: None)
                ),
                "Code registry service is unavailable",
            ),
        ):
            binding = export_service_module.registry_binding_for_symbol(symbol)
            self.assertIsNotNone(binding)
            with self.subTest(symbol=symbol, message=message):
                with self.assertRaises(ContractTemplateExportError) as exc_info:
                    service._registry_service_for_binding(binding)
                self.assertIn(message, str(exc_info.exception))

    def test_selected_record_labels_cover_available_service_namespaces(self):
        self.assertEqual(
            self.export_service._selected_record_label(
                namespace="track",
                selection_value=self.primary_track_id,
            ),
            "Export Service Song",
        )
        self.assertEqual(
            self.export_service._selected_record_label(
                namespace="release",
                selection_value=self.release_id,
            ),
            "Export Coverage Release",
        )
        self.assertEqual(
            self.export_service._selected_record_label(
                namespace="contract",
                selection_value=self.contract_id,
            ),
            "Export Registry Contract",
        )
        self.assertEqual(
            self.export_service._selected_record_label(
                namespace="party",
                selection_value=self.party_id,
            ),
            "Aeonium",
        )
        self.assertIsNone(
            self.export_service._selected_record_label(namespace="asset", selection_value=123456)
        )
        self.assertIsNone(
            self.export_service._selected_record_label(
                namespace="track",
                selection_value=999999,
            )
        )
        self.assertIsNone(
            self.export_service._selected_record_label(
                namespace="release",
                selection_value=999999,
            )
        )
        self.assertIsNone(
            self.export_service._selected_record_label(
                namespace="contract",
                selection_value=999999,
            )
        )
        self.assertIsNone(
            self.export_service._selected_record_label(
                namespace="party",
                selection_value=999999,
            )
        )
        named_services = self._export_service_with(
            work_service=SimpleNamespace(fetch_work=lambda _id: SimpleNamespace(title="Work Name")),
            rights_service=SimpleNamespace(
                fetch_right=lambda _id: SimpleNamespace(title="", name="Right Name")
            ),
            asset_service=SimpleNamespace(
                fetch_asset=lambda _id: SimpleNamespace(title="", name="", filename="asset.wav")
            ),
        )
        self.assertEqual(
            named_services._selected_record_label(namespace="work", selection_value=1),
            "Work Name",
        )
        self.assertEqual(
            named_services._selected_record_label(namespace="right", selection_value=1),
            "Right Name",
        )
        self.assertEqual(
            named_services._selected_record_label(namespace="asset", selection_value=1),
            "asset.wav",
        )
        missing_services = self._export_service_with(
            work_service=SimpleNamespace(fetch_work=lambda _id: None),
            rights_service=SimpleNamespace(fetch_right=lambda _id: None),
            asset_service=SimpleNamespace(fetch_asset=lambda _id: None),
        )
        for namespace in ("work", "right", "asset"):
            with self.subTest(namespace=namespace):
                self.assertIsNone(
                    missing_services._selected_record_label(namespace=namespace, selection_value=1)
                )

        placeholder = SimpleNamespace(
            canonical_symbol="{{db.track.track_title}}",
            display_label="Track Title",
        )
        catalog_entry = SimpleNamespace(namespace="track", display_label="")
        self.assertIn(
            '"Export Service Song"',
            self.export_service._missing_required_value_message(
                placeholder=placeholder,
                catalog_entry=catalog_entry,
                selection_value=self.primary_track_id,
            ),
        )
        self.assertIn(
            "#999999",
            self.export_service._missing_required_value_message(
                placeholder=placeholder,
                catalog_entry=catalog_entry,
                selection_value=999999,
            ),
        )
        self.assertEqual(
            self.export_service._missing_required_value_message(
                placeholder=placeholder,
                catalog_entry=catalog_entry,
                selection_value=None,
            ),
            "Track Title is blank for {{db.track.track_title}}.",
        )

    def test_html_preview_sync_rejects_missing_sources_and_prunes_sessions(self):
        with patch.object(self.template_service, "fetch_draft", return_value=None):
            with self.assertRaisesRegex(ContractTemplateExportError, "draft 999999 not found"):
                self.export_service.synchronize_html_draft(999999)

        with patch.object(self.template_service, "fetch_revision", return_value=None):
            with self.assertRaisesRegex(
                ContractTemplateExportError,
                f"revision {self.revision.revision_id} not found",
            ):
                self.export_service.synchronize_html_draft(self.draft.draft_id)

        with patch.object(
            self.template_service,
            "ensure_html_revision_source_path",
            return_value=None,
        ):
            with self.assertRaisesRegex(ContractTemplateExportError, "source is unavailable"):
                self.export_service.synchronize_html_draft(self.draft.draft_id)
            with self.assertRaisesRegex(ContractTemplateExportError, "source is unavailable"):
                self.export_service.materialize_html_preview_session(
                    revision_id=self.revision.revision_id,
                    editable_payload=self.template_service.fetch_draft_payload(self.draft.draft_id),
                )

        with patch.object(self.template_service, "fetch_revision", return_value=None):
            with self.assertRaisesRegex(
                ContractTemplateExportError,
                "revision 999999 not found",
            ):
                self.export_service.materialize_html_preview_session(
                    revision_id=999999,
                    editable_payload={},
                )

        preview_root = self.root / "preview-sessions"
        keep_session = preview_root / "keep"
        stale_session = preview_root / "stale"
        keep_session.mkdir(parents=True)
        stale_session.mkdir()

        class BrokenPath:
            def __fspath__(self):
                raise RuntimeError("cannot resolve keep path")

        with patch.object(
            self.export_service,
            "html_preview_sessions_root",
            return_value=preview_root,
        ):
            self.export_service.prune_html_preview_sessions(keep_paths=(keep_session, BrokenPath()))

        self.assertTrue(keep_session.exists())
        self.assertFalse(stale_session.exists())

    def test_export_html_draft_to_pdf_uses_native_html_working_copy_and_preserves_source(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="HTML Export Template",
                description="Native HTML export coverage",
                template_family="contract",
                source_format="html",
            )
        )
        html_root = self.root / "html-export-template"
        (html_root / "assets").mkdir(parents=True)
        (html_root / "assets" / "banner.png").write_bytes(b"banner-bytes")
        source_path = html_root / "agreement.html"
        original_html = (
            "<html><body><img src='assets/banner.png'><style>p{color:#205090;}</style>"
            "<p>{{manual.license_date}}</p></body></html>"
        )
        source_path.write_text(original_html, encoding="utf-8")
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="HTML Export Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {},
                    "manual_values": {"{{manual.license_date}}": "2026-04-05"},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        working_path = self.export_service.synchronize_html_draft(draft.draft_id)
        self.assertTrue(working_path.exists())
        result = self.export_service.export_draft_to_pdf(draft.draft_id)
        source_copy = self.template_service.resolve_html_revision_source_path(revision.revision_id)
        refreshed_draft = self.template_service.fetch_draft(draft.draft_id)
        self.assertIsNotNone(refreshed_draft)
        refreshed_working_path = self.template_service.resolve_draft_working_path(draft.draft_id)
        self.assertIsNotNone(refreshed_working_path)

        self.assertTrue(refreshed_working_path.exists())
        self.assertTrue((refreshed_working_path.parent / "assets" / "banner.png").exists())
        self.assertEqual(result.resolved_docx_artifact, None)
        self.assertIsNotNone(result.resolved_html_artifact)
        self.assertEqual(result.resolved_html_artifact.artifact_type, "resolved_html")
        self.assertTrue(Path(result.resolved_html_artifact.output_path).exists())
        self.assertTrue(Path(result.pdf_artifact.output_path).read_bytes().startswith(b"%PDF"))
        self.assertIn("05.Apr.2026", Path(result.resolved_html_artifact.output_path).read_text())
        self.assertIn("05.Apr.2026", refreshed_working_path.read_text(encoding="utf-8"))
        self.assertNotIn(
            "{{manual.license_date}}",
            refreshed_working_path.read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(source_copy)
        self.assertEqual(source_copy.read_text(encoding="utf-8"), original_html)
        self.assertIsNotNone(refreshed_draft.working_file_path)
        self.assertEqual(result.snapshot.preview_payload.get("renderer"), "fake_html_pdf")
        self.assertEqual(result.snapshot.preview_payload.get("source_format"), "html")
        self.assertEqual(result.snapshot.preview_payload.get("working_format"), "html")
        self.assertEqual(
            result.snapshot.preview_payload.get("working_copy_path"),
            str(refreshed_working_path),
        )
        self.assertEqual(len(self.html_pdf_adapter.file_calls), 1)
        self.assertEqual(len(self.html_pdf_adapter.html_calls), 0)
        self.assertEqual(len(self.pages_adapter.pdf_calls), 0)
        self.assertEqual(len(self.html_adapter.calls), 0)
        rendered_source, rendered_pdf = self.html_pdf_adapter.file_calls[0]
        self.assertEqual(rendered_source, Path(result.resolved_html_artifact.output_path))
        self.assertEqual(rendered_pdf, Path(result.pdf_artifact.output_path))

    def test_html_export_applies_current_year_date_format_and_duplicate_controls(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Runtime Control Template",
                description="Current year and duplicate block coverage",
                template_family="contract",
                source_format="html",
            )
        )
        source_path = self.root / "runtime-control.html"
        source_path.write_text(
            "<html><body><main>{{duplicate.start}}"
            "<section><p>{{current.year}}</p><p>{{manual.license_date}}</p>"
            "<p>{{page.index}}/{{page.total}}</p><p>{{custom.index}}</p>"
            "<span>{{duplicate.number}}</span></section>"
            "{{duplicate.end}}</main></body></html>",
            encoding="utf-8",
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Runtime Control Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {},
                    "manual_values": {
                        "{{manual.license_date}}": "2026-04-05",
                        "{{duplicate.number}}": 3,
                    },
                    "manual_formats": {"{{manual.license_date}}": "d.mmm.yy"},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)
        rendered_html = Path(result.resolved_html_artifact.output_path).read_text(encoding="utf-8")

        self.assertEqual(rendered_html.count("<section>"), 3)
        self.assertEqual(rendered_html.count(str(date.today().year)), 3)
        self.assertEqual(rendered_html.count("5.Apr.26"), 3)
        self.assertIn("<p>1/3</p><p>1</p>", rendered_html)
        self.assertIn("<p>2/3</p><p>2</p>", rendered_html)
        self.assertIn("<p>3/3</p><p>3</p>", rendered_html)
        self.assertNotIn("{{duplicate.start}}", rendered_html)
        self.assertNotIn("{{duplicate.end}}", rendered_html)
        self.assertNotIn("{{duplicate.number}}", rendered_html)
        self.assertNotIn("{{page.index}}", rendered_html)
        self.assertNotIn("{{page.total}}", rendered_html)
        self.assertNotIn("{{custom.index}}", rendered_html)
        self.assertEqual(
            result.snapshot.resolved_values["{{current.year}}"], str(date.today().year)
        )
        self.assertEqual(result.snapshot.resolved_values["{{manual.license_date}}"], "5.Apr.26")

    def test_html_export_formats_track_length_as_timecode(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Track Length Template",
                description="Track length cymbol formatting coverage",
                template_family="contract",
                source_format="html",
            )
        )
        source_path = self.root / "track-length.html"
        source_path.write_text(
            "<html><body><p>{{db.track.track_length_sec}}</p></body></html>",
            encoding="utf-8",
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Track Length Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {
                        "{{db.track.track_length_sec}}": str(self.primary_track_id),
                    },
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)
        rendered_html = Path(result.resolved_html_artifact.output_path).read_text(encoding="utf-8")

        self.assertIn("<p>00:03:41</p>", rendered_html)
        self.assertEqual(
            result.snapshot.resolved_values["{{db.track.track_length_sec}}"],
            "00:03:41",
        )
        self.assertNotIn("<p>221</p>", rendered_html)

    def test_html_duplicate_track_block_uses_indexed_db_selections(self):
        second_track_id = self.track_service.create_track(
            TrackCreatePayload(
                isrc="NL-TST-26-00603",
                track_title="Album Continuation",
                artist_name="Moonwake",
                additional_artists=[],
                album_title="Export Coverage",
                release_date="2026-03-25",
                track_length_sec=199,
                iswc=None,
                upc=None,
                genre="Ambient",
                catalog_number=None,
            )
        )
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Indexed Track Duplicate Template",
                description="Duplicate block indexed track context coverage",
                template_family="contract",
                source_format="html",
            )
        )
        source_path = self.root / "indexed-track-duplicate.html"
        source_path.write_text(
            "<html><body><h1>{{db.release.title}}</h1>{{duplicate.number}}"
            "{{duplicate.start}}<section><p>{{db.index}}</p>"
            "<p>{{db.track.track_title.indexed}}</p><p>{{db.track.isrc.indexed}}</p>"
            "<p>{{db.track.track_length_sec.indexed}}</p></section>"
            "{{duplicate.end}}</body></html>",
            encoding="utf-8",
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        release_scope_key = build_contract_template_selector_scope_key(
            "release",
            "release_selection_required",
        )
        title_symbol = "{{db.track.track_title.indexed}}"
        isrc_symbol = "{{db.track.isrc.indexed}}"
        length_symbol = "{{db.track.track_length_sec.indexed}}"
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Indexed Track Duplicate Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {
                        release_scope_key: str(self.release_id),
                        build_contract_template_indexed_selection_key(title_symbol, 1): str(
                            self.primary_track_id
                        ),
                        build_contract_template_indexed_selection_key(isrc_symbol, 1): str(
                            self.primary_track_id
                        ),
                        build_contract_template_indexed_selection_key(length_symbol, 1): str(
                            self.primary_track_id
                        ),
                        build_contract_template_indexed_selection_key(title_symbol, 2): str(
                            second_track_id
                        ),
                        build_contract_template_indexed_selection_key(isrc_symbol, 2): str(
                            second_track_id
                        ),
                        build_contract_template_indexed_selection_key(length_symbol, 2): str(
                            second_track_id
                        ),
                    },
                    "manual_values": {"{{duplicate.number}}": 2},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)
        rendered_html = Path(result.resolved_html_artifact.output_path).read_text(encoding="utf-8")

        self.assertEqual(rendered_html.count("<section>"), 2)
        self.assertIn("<h1>Export Coverage Release</h1>", rendered_html)
        self.assertIn(
            "<p>1</p><p>Export Service Song</p><p>NL-TST-26-00601</p><p>00:03:41</p>",
            rendered_html,
        )
        self.assertIn(
            "<p>2</p><p>Album Continuation</p><p>NL-TST-26-00603</p><p>00:03:19</p>",
            rendered_html,
        )
        self.assertEqual(rendered_html.count("Export Service Song"), 1)
        self.assertNotIn("{{db.track.track_title.indexed}}", rendered_html)
        self.assertNotIn("{{db.track.isrc.indexed}}", rendered_html)
        self.assertNotIn("{{db.track.track_length_sec.indexed}}", rendered_html)
        self.assertNotIn("{{db.index}}", rendered_html)
        self.assertNotIn("{{duplicate.number}}", rendered_html)

    def test_html_preview_replaces_current_year_even_when_scan_inventory_is_stale(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Stale Runtime Inventory Template",
                description="Runtime symbol preview coverage",
                template_family="contract",
                source_format="html",
            )
        )
        source_path = self.root / "stale-runtime.html"
        source_path.write_text(
            "<html><body><p>{{current.year}}</p><p>{{page.index}}/{{page.total}}</p>"
            "<p>{{custom.index}}</p></body></html>",
            encoding="utf-8",
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        self.template_service.replace_revision_placeholder_inventory(
            revision.revision_id,
            placeholders=(),
        )

        _preview_root, preview_html, _warnings = (
            self.export_service.materialize_html_preview_session(
                revision_id=revision.revision_id,
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {},
                    "manual_values": {},
                    "type_overrides": {},
                },
                strict=False,
            )
        )

        rendered_html = preview_html.read_text(encoding="utf-8")
        self.assertIn(str(date.today().year), rendered_html)
        self.assertIn("<p>1/1</p>", rendered_html)
        self.assertIn("<p>1</p>", rendered_html)
        self.assertNotIn("{{current.year}}", rendered_html)
        self.assertNotIn("{{page.index}}", rendered_html)
        self.assertNotIn("{{page.total}}", rendered_html)
        self.assertNotIn("{{custom.index}}", rendered_html)

    def test_export_normalizes_conflicting_legacy_track_selections_to_one_scope(self):
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=self.revision.revision_id,
                name="Legacy Conflict Draft",
                editable_payload={
                    "revision_id": self.revision.revision_id,
                    "db_selections": {
                        "{{db.track.track_title}}": "1",
                        "{{db.track.artist_name}}": "2",
                    },
                    "manual_values": {
                        "{{manual.license_date}}": "2026-03-31",
                    },
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)

        resolved_pair = (
            result.snapshot.resolved_values["{{db.track.track_title}}"],
            result.snapshot.resolved_values["{{db.track.artist_name}}"],
        )
        self.assertIn(
            resolved_pair,
            {
                ("Export Service Song", "Moonwake"),
                ("Legacy Conflict Song", "Lyra"),
            },
        )
        self.assertTrue(
            any("conflicting saved selections" in warning for warning in result.warnings)
        )

    def test_export_resolves_expanded_party_placeholders_from_one_selected_party(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Party Export Template",
                description="Expanded party export coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "party-export-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Display ", "{{db.party.display_name}}"),
                    ("Artist ", "{{db.party.artist_name}}"),
                    ("Aliases ", "{{db.party.artist_aliases}}"),
                    ("Company ", "{{db.party.company_name}}"),
                    ("Alt Email ", "{{db.party.alternative_email}}"),
                    ("CoC ", "{{db.party.chamber_of_commerce_number}}"),
                    ("PRO ", "{{db.party.pro_number}}"),
                ),
            )
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Party Export Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {
                        "{{db.party.company_name}}": str(self.party_id),
                    },
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)

        self.assertEqual(
            result.snapshot.resolved_values,
            {
                "{{db.party.alternative_email}}": "legal@moonium.test",
                "{{db.party.artist_aliases}}": "Aeonium Alias, Lyra Cosmos",
                "{{db.party.artist_name}}": "Aeonium Official",
                "{{db.party.chamber_of_commerce_number}}": "CoC-778899",
                "{{db.party.company_name}}": "Aeonium Holdings",
                "{{db.party.display_name}}": "Aeonium",
                "{{db.party.pro_number}}": "PRO-778899",
            },
        )
        resolved_docx_bytes = Path(result.resolved_docx_artifact.output_path).read_bytes()
        self.assertEqual(
            self.template_service.docx_scanner.scan_bytes(resolved_docx_bytes).placeholders,
            (),
        )

    def test_export_resolves_owner_placeholders_from_current_owner_party_without_selection(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Owner Export Template",
                description="Owner settings export coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "owner-export-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Owner ", "{{db.owner.legal_name}}"),
                    ("Owner Email ", "{{db.owner.email}}"),
                    ("Owner VAT ", "{{db.owner.vat_number}}"),
                    ("Owner IPI ", "{{db.owner.ipi_cae}}"),
                ),
            )
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Owner Export Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {},
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)

        self.assertEqual(
            result.snapshot.resolved_values,
            {
                "{{db.owner.email}}": "hello@moonwake.test",
                "{{db.owner.ipi_cae}}": "IPI-OWNER",
                "{{db.owner.legal_name}}": "Moonwake Records B.V.",
                "{{db.owner.vat_number}}": "BTW-OWNER",
            },
        )

    def test_export_resolves_owner_placeholders_from_linked_owner_party_without_selection(self):
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ApplicationOwnerBinding(id, party_id)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET party_id=excluded.party_id
                """,
                (self.party_id,),
            )
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Linked Owner Export Template",
                description="Owner party export coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "linked-owner-export-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Owner ", "{{db.owner.legal_name}}"),
                    ("Owner Display ", "{{db.owner.display_name}}"),
                    ("Owner Email ", "{{db.owner.email}}"),
                    ("Owner VAT ", "{{db.owner.vat_number}}"),
                ),
            )
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Linked Owner Export Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {},
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)

        self.assertEqual(
            result.snapshot.resolved_values,
            {
                "{{db.owner.display_name}}": "Aeonium",
                "{{db.owner.email}}": "hello@moonium.test",
                "{{db.owner.legal_name}}": "Aeonium Holdings B.V.",
                "{{db.owner.vat_number}}": "PARTY-VAT",
            },
        )

    def test_export_rejects_blank_owner_placeholder_values(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Owner Blank Export Template",
                description="Owner settings validation coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "owner-blank-export-template.docx"
        source_path.write_bytes(
            make_docx_bytes(
                document_paragraphs=(
                    ("Owner ", "{{db.owner.legal_name}}"),
                    ("Owner Email ", "{{db.owner.email}}"),
                ),
            )
        )
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Owner Blank Export Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {},
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )
        with self.conn:
            self.conn.execute(
                "UPDATE Parties SET email='' WHERE id=?",
                (self.owner_party_id,),
            )

        with self.assertRaises(ContractTemplateExportError) as exc:
            self.export_service.export_draft_to_pdf(draft.draft_id)

        self.assertIn(
            "Current Owner Party",
            str(exc.exception),
        )
        self.assertIn("{{db.owner.email}}", str(exc.exception))

    def test_export_replaces_owner_placeholders_inside_docx_attributes(self):
        template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Owner Attribute Export Template",
                description="Owner attribute replacement coverage",
                template_family="contract",
                source_format="docx",
            )
        )
        source_path = self.root / "owner-attribute-export-template.docx"
        source_path.write_bytes(self._docx_with_owner_attribute("{{db.owner.company_name}}"))
        revision = self.template_service.import_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(source_filename=source_path.name),
        ).revision
        draft = self.template_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Owner Attribute Export Draft",
                editable_payload={
                    "revision_id": revision.revision_id,
                    "db_selections": {},
                    "manual_values": {},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)
        resolved_xml = self._resolved_document_xml(result.resolved_docx_artifact.output_path)

        self.assertNotIn("{{db.owner.company_name}}", resolved_xml)
        self.assertIn('owner="Moonwake Records"', resolved_xml)

    def test_docx_replacement_artifact_storage_and_render_helper_edges(self):
        docx_bytes = make_docx_bytes(
            document_paragraphs=(
                ("Track ", "{{db.", "track.track_title", "}}"),
                ("Date ", "{{manual.", "\t", "license_date}}"),
            ),
            header_paragraphs=(("Corrupt me",),),
        )
        corrupt_docx = BytesIO()
        with ZipFile(BytesIO(docx_bytes)) as source_archive:
            with ZipFile(corrupt_docx, "w", compression=ZIP_DEFLATED) as target_archive:
                for part_name in source_archive.namelist():
                    payload = source_archive.read(part_name)
                    if part_name == "word/header1.xml":
                        payload = b"<broken"
                    target_archive.writestr(part_name, payload)

        rewritten_bytes, warnings = self.export_service._replace_docx_placeholders(
            corrupt_docx.getvalue(),
            {
                "{{db.track.track_title}}": "Export Service Song",
                "{{manual.license_date}}": "2026-03-31",
            },
        )
        with ZipFile(BytesIO(rewritten_bytes)) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8", "replace")
            self.assertEqual(archive.read("word/header1.xml"), b"<broken")
        self.assertIn("Export Service Song", document_xml)
        self.assertIn("{{manual.", document_xml)
        self.assertTrue(any("Collapsed paragraph styling" in warning for warning in warnings))
        self.assertTrue(any("Skipped unparsable DOCX part" in warning for warning in warnings))

        self.assertEqual(self.export_service._render_output_value(None), "")
        self.assertEqual(self.export_service._render_output_value(True), "Yes")
        self.assertEqual(self.export_service._render_output_value(False), "No")
        self.assertEqual(self.export_service._render_output_value([" A ", "", "B"]), "A, B")
        self.assertEqual(self.export_service._render_track_length(None), "")
        self.assertEqual(self.export_service._render_track_length(""), "")
        self.assertEqual(self.export_service._render_track_length("not seconds"), "not seconds")
        self.assertEqual(self.export_service._render_track_length("-5"), "-5")

        result = self.export_service.export_draft_to_pdf(self.draft.draft_id)
        artifact = self.export_service._write_pdf_artifact(
            snapshot_id=result.snapshot.snapshot_id,
            docx_bytes=make_docx_bytes(document_paragraphs=(("Pages direct",),)),
            source_filename="direct.pages",
            stem="direct-pages",
            subdir=f"snapshots/{result.snapshot.snapshot_id}/direct",
        )
        self.assertTrue(Path(artifact.output_path).read_bytes().startswith(b"%PDF"))
        self.assertEqual(self.export_service._pdf_renderer_name(), "fake_pages_bridge_pdf")
        self.assertTrue(self.pages_adapter.pdf_calls)

        html_fallback_service = self._export_service_with(
            pages_adapter=FakePagesAdapter(available=False)
        )
        html_artifact = html_fallback_service._write_pdf_artifact(
            snapshot_id=result.snapshot.snapshot_id,
            docx_bytes=make_docx_bytes(document_paragraphs=(("HTML fallback",),)),
            source_filename="fallback.docx",
            stem="html-fallback",
            subdir=f"snapshots/{result.snapshot.snapshot_id}/html-fallback",
        )
        self.assertTrue(Path(html_artifact.output_path).read_bytes().startswith(b"%PDF"))
        self.assertEqual(html_fallback_service._pdf_renderer_name(), "fake_docx_html")
        self.assertTrue(self.html_adapter.calls)

        with patch.object(self.template_service.artifact_store, "resolve", return_value=None):
            with self.assertRaisesRegex(ContractTemplateExportError, "storage is not configured"):
                self.export_service._write_resolved_docx_artifact(
                    snapshot_id=result.snapshot.snapshot_id,
                    docx_bytes=make_docx_bytes(document_paragraphs=(("No storage",),)),
                    stem="no-storage",
                    subdir=f"snapshots/{result.snapshot.snapshot_id}/broken",
                )

        with patch.object(self.template_service.artifact_store, "resolve", return_value=None):
            with self.assertRaisesRegex(ContractTemplateExportError, "storage is not configured"):
                self.export_service._write_pdf_artifact(
                    snapshot_id=result.snapshot.snapshot_id,
                    docx_bytes=make_docx_bytes(document_paragraphs=(("No PDF storage",),)),
                    source_filename="no-pdf-storage.docx",
                    stem="no-pdf-storage",
                    subdir=f"snapshots/{result.snapshot.snapshot_id}/broken-pdf",
                )

        unsupported_revision = SimpleNamespace(
            revision_id=self.revision.revision_id,
            source_format="rtf",
            source_filename="contract-template.rtf",
        )
        with self.assertRaisesRegex(ContractTemplateExportError, "Unsupported template source"):
            self.export_service._export_source_as_docx(revision=unsupported_revision)

        pages_revision = SimpleNamespace(
            revision_id=self.revision.revision_id,
            source_format="pages",
            source_filename="contract-template.pages",
        )
        pages_missing_service = self._export_service_with()
        pages_missing_service.pages_adapter = None
        with self.assertRaisesRegex(ContractTemplateExportError, "unavailable on this machine"):
            pages_missing_service._export_source_as_docx(revision=pages_revision)
        with self.assertRaisesRegex(ContractTemplateExportError, "Pages bridge unavailable"):
            self._export_service_with(
                pages_adapter=FakePagesAdapter(available=False)
            )._export_source_as_docx(revision=pages_revision)

        _FakeApplication._instance = None
        service = self._export_service_with()
        with patch.object(export_service_module, "QApplication", _FakeApplication):
            first = service._ensure_qapplication()
            second = service._ensure_qapplication()
        self.assertIs(first, second)

    def test_export_pages_revision_preserves_source_and_renders_pdf_from_html_working_draft(self):
        pages_template = self.template_service.create_template(
            ContractTemplatePayload(
                name="Pages Export Template",
                description="Pages import/export normalization coverage",
                template_family="contract",
                source_format="pages",
            )
        )
        pages_service = ContractTemplateService(
            self.conn,
            data_root=self.root,
            pages_adapter=FakePagesAdapter(
                docx_bytes=make_docx_bytes(
                    document_paragraphs=(
                        ("Track ", "{{db.track.track_title}}"),
                        ("Date ", "{{manual.license_date}}"),
                    )
                )
            ),
            docx_html_adapter=FakeDocxHtmlAdapter(
                html_text=(
                    "<html><body><p>{{db.track.track_title}}</p>"
                    "<p>{{manual.license_date}}</p></body></html>"
                )
            ),
        )
        pages_revision = pages_service.import_revision_from_bytes(
            pages_template.template_id,
            b"original-pages-template",
            payload=ContractTemplateRevisionPayload(source_filename="license.pages"),
        ).revision
        pages_draft = pages_service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=pages_revision.revision_id,
                name="Pages Export Draft",
                editable_payload={
                    "revision_id": pages_revision.revision_id,
                    "db_selections": {"{{db.track.track_title}}": "1"},
                    "manual_values": {"{{manual.license_date}}": "2026-04-06"},
                    "type_overrides": {},
                },
                storage_mode="database",
            )
        )
        export_service = ContractTemplateExportService(
            template_service=pages_service,
            catalog_service=self.catalog_service,
            settings_reads=self.settings_reads,
            track_service=self.track_service,
            party_service=self.party_service,
            html_adapter=FakeDocxHtmlAdapter(),
            html_pdf_adapter=self.html_pdf_adapter,
            pages_adapter=pages_service.pages_adapter,
        )

        result = export_service.export_draft_to_pdf(pages_draft.draft_id)

        self.assertEqual(
            pages_service.load_revision_source_bytes(pages_revision.revision_id),
            b"original-pages-template",
        )
        self.assertEqual(result.snapshot.preview_payload.get("source_format"), "pages")
        self.assertEqual(result.snapshot.preview_payload.get("working_format"), "html")
        self.assertEqual(result.snapshot.preview_payload.get("renderer"), "fake_html_pdf")
        self.assertIsNotNone(result.resolved_docx_artifact)
        self.assertIsNotNone(result.resolved_html_artifact)
        self.assertEqual(len(self.html_pdf_adapter.file_calls), 1)
        self.assertEqual(len(pages_service.pages_adapter.pdf_calls), 0)

    def test_export_generates_and_assigns_registry_backed_values_for_blank_records(self):
        self._set_registry_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        self._set_registry_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        self._set_registry_prefix(BUILTIN_CATEGORY_LICENSE_NUMBER, "LIC")
        revision, draft = self._create_registry_draft(
            name="Registry Export",
            document_paragraphs=(
                ("Track Catalog ", "{{db.track.catalog_number}}"),
                ("Release Catalog ", "{{db.release.catalog_number}}"),
                ("Contract Number ", "{{db.contract.contract_number}}"),
                ("License Number ", "{{db.contract.license_number}}"),
                ("Registry Key ", "{{db.contract.registry_sha256_key}}"),
            ),
            db_selections={},
        )

        result = self.export_service.export_draft_to_pdf(draft.draft_id)
        assignments = self.template_service.list_draft_registry_assignments(draft.draft_id)
        track = self.track_service.fetch_track_snapshot(self.primary_track_id)
        release = self.release_service.fetch_release(self.release_id)
        contract = self.contract_service.fetch_contract(self.contract_id)

        self.assertIsNotNone(track)
        self.assertIsNotNone(release)
        self.assertIsNotNone(contract)
        assert track is not None
        assert release is not None
        assert contract is not None
        self.assertEqual(len(assignments), 5)
        assignment_values = {
            assignment.canonical_symbol: assignment.registry_value for assignment in assignments
        }
        self.assertEqual(
            result.snapshot.resolved_values["{{db.track.catalog_number}}"],
            assignment_values["{{db.track.catalog_number}}"],
        )
        self.assertEqual(
            result.snapshot.resolved_values["{{db.release.catalog_number}}"],
            assignment_values["{{db.release.catalog_number}}"],
        )
        self.assertEqual(
            result.snapshot.resolved_values["{{db.contract.contract_number}}"],
            assignment_values["{{db.contract.contract_number}}"],
        )
        self.assertEqual(
            result.snapshot.resolved_values["{{db.contract.license_number}}"],
            assignment_values["{{db.contract.license_number}}"],
        )
        self.assertEqual(
            result.snapshot.resolved_values["{{db.contract.registry_sha256_key}}"],
            assignment_values["{{db.contract.registry_sha256_key}}"],
        )
        self.assertTrue(assignment_values["{{db.track.catalog_number}}"].startswith("ACR"))
        self.assertTrue(assignment_values["{{db.release.catalog_number}}"].startswith("ACR"))
        self.assertTrue(assignment_values["{{db.contract.contract_number}}"].startswith("CTR"))
        self.assertTrue(assignment_values["{{db.contract.license_number}}"].startswith("LIC"))
        self.assertRegex(
            assignment_values["{{db.contract.registry_sha256_key}}"],
            r"^[0-9a-f]{64}$",
        )
        self.assertIsNone(track.catalog_registry_entry_id)
        self.assertIsNone(release.catalog_registry_entry_id)
        self.assertIsNone(contract.contract_registry_entry_id)
        self.assertIsNone(contract.license_registry_entry_id)
        self.assertIsNone(contract.registry_sha256_key_entry_id)
        self.assertEqual(revision.revision_id, draft.revision_id)

    def test_export_reuses_existing_registry_assignments_instead_of_generating_duplicates(self):
        self._set_registry_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        self._set_registry_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        self._set_registry_prefix(BUILTIN_CATEGORY_LICENSE_NUMBER, "LIC")
        _, draft = self._create_registry_draft(
            name="Registry Reuse Export",
            document_paragraphs=(
                ("Track Catalog ", "{{db.track.catalog_number}}"),
                ("Release Catalog ", "{{db.release.catalog_number}}"),
                ("Contract Number ", "{{db.contract.contract_number}}"),
                ("License Number ", "{{db.contract.license_number}}"),
                ("Registry Key ", "{{db.contract.registry_sha256_key}}"),
            ),
            db_selections={},
        )
        assignment_values = self.export_service.ensure_registry_assignments_for_draft(
            draft.draft_id,
            created_via="test.preassigned",
        )
        count_before = self.conn.execute("SELECT COUNT(*) FROM CodeRegistryEntries").fetchone()[0]

        result = self.export_service.export_draft_to_pdf(draft.draft_id)
        count_after = self.conn.execute("SELECT COUNT(*) FROM CodeRegistryEntries").fetchone()[0]

        self.assertEqual(count_after, count_before)
        self.assertEqual(
            result.snapshot.resolved_values["{{db.track.catalog_number}}"],
            assignment_values["{{db.track.catalog_number}}"],
        )
        self.assertEqual(
            result.snapshot.resolved_values["{{db.release.catalog_number}}"],
            assignment_values["{{db.release.catalog_number}}"],
        )
        self.assertEqual(
            result.snapshot.resolved_values["{{db.contract.contract_number}}"],
            assignment_values["{{db.contract.contract_number}}"],
        )
        self.assertEqual(
            result.snapshot.resolved_values["{{db.contract.license_number}}"],
            assignment_values["{{db.contract.license_number}}"],
        )
        self.assertEqual(
            result.snapshot.resolved_values["{{db.contract.registry_sha256_key}}"],
            assignment_values["{{db.contract.registry_sha256_key}}"],
        )

    def test_preview_session_does_not_generate_registry_values(self):
        self._set_registry_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        self._set_registry_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        self._set_registry_prefix(BUILTIN_CATEGORY_LICENSE_NUMBER, "LIC")
        revision, _draft = self._create_registry_draft(
            name="Registry Preview",
            document_paragraphs=(
                ("Track Catalog ", "{{db.track.catalog_number}}"),
                ("Release Catalog ", "{{db.release.catalog_number}}"),
                ("Contract Number ", "{{db.contract.contract_number}}"),
                ("License Number ", "{{db.contract.license_number}}"),
                ("Registry Key ", "{{db.contract.registry_sha256_key}}"),
            ),
            db_selections={},
        )
        count_before = self.conn.execute("SELECT COUNT(*) FROM CodeRegistryEntries").fetchone()[0]

        preview_root, preview_html, warnings = self.export_service.materialize_html_preview_session(
            revision_id=revision.revision_id,
            editable_payload={
                "revision_id": revision.revision_id,
                "db_selections": {},
                "manual_values": {},
                "type_overrides": {},
            },
            strict=False,
        )

        count_after = self.conn.execute("SELECT COUNT(*) FROM CodeRegistryEntries").fetchone()[0]
        track = self.track_service.fetch_track_snapshot(self.primary_track_id)
        release = self.release_service.fetch_release(self.release_id)
        contract = self.contract_service.fetch_contract(self.contract_id)
        self.assertTrue(preview_root.exists())
        self.assertTrue(preview_html.exists())
        self.assertIsInstance(warnings, tuple)
        self.assertEqual(count_after, count_before)
        self.assertIsNotNone(track)
        self.assertIsNotNone(release)
        self.assertIsNotNone(contract)
        assert track is not None
        assert release is not None
        assert contract is not None
        self.assertEqual(
            self.template_service.list_draft_registry_assignments(_draft.draft_id),
            [],
        )
        self.assertIsNone(track.catalog_registry_entry_id)
        self.assertIsNone(release.catalog_registry_entry_id)
        self.assertIsNone(contract.contract_registry_entry_id)
        self.assertIsNone(contract.license_registry_entry_id)
        self.assertIsNone(contract.registry_sha256_key_entry_id)

    def test_export_blocks_registry_generation_when_required_prefix_is_missing(self):
        self._set_registry_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        self._set_registry_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, None)
        _, draft = self._create_registry_draft(
            name="Registry Prefix Required",
            document_paragraphs=(("Contract Number ", "{{db.contract.contract_number}}"),),
            db_selections={},
        )

        with self.assertRaises(ContractTemplateExportError) as exc_info:
            self.export_service.export_draft_to_pdf(draft.draft_id)

        self.assertIn("Configure a prefix/namespace", str(exc_info.exception))
        self.assertIn("Contract Number", str(exc_info.exception))

    def test_draft_linked_registry_entries_are_protected_from_deletion(self):
        self._set_registry_prefix(BUILTIN_CATEGORY_CATALOG_NUMBER, "ACR")
        self._set_registry_prefix(BUILTIN_CATEGORY_CONTRACT_NUMBER, "CTR")
        self._set_registry_prefix(BUILTIN_CATEGORY_LICENSE_NUMBER, "LIC")
        _, draft = self._create_registry_draft(
            name="Registry Draft Protection",
            document_paragraphs=(
                ("Contract Number ", "{{db.contract.contract_number}}"),
                ("Registry Key ", "{{db.contract.registry_sha256_key}}"),
            ),
            db_selections={},
        )
        self.export_service.ensure_registry_assignments_for_draft(draft.draft_id)
        assignment = self.template_service.fetch_draft_registry_assignment(
            draft.draft_id,
            "{{db.contract.contract_number}}",
        )
        self.assertIsNotNone(assignment)
        assert assignment is not None
        registry = self.track_service.code_registry_service()

        with self.assertRaises(ValueError) as exc_info:
            registry.delete_entry(assignment.registry_entry_id)

        usage = registry.usage_for_entry(assignment.registry_entry_id)
        self.assertIn("not linked to any record", str(exc_info.exception))
        self.assertTrue(
            any(
                link.subject_kind == "draft" and int(link.subject_id) == int(draft.draft_id)
                for link in usage
            )
        )

    def _docx_with_owner_attribute(self, token: str) -> bytes:
        base_bytes = make_docx_bytes(document_paragraphs=(("Owner ", token),))
        output = BytesIO()
        with ZipFile(BytesIO(base_bytes)) as source_archive:
            with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
                for part_name in source_archive.namelist():
                    payload = source_archive.read(part_name)
                    if part_name == "word/document.xml":
                        text = payload.decode("utf-8", "replace")
                        text = text.replace(
                            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
                            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:meta="urn:test-owner" meta:owner="'
                            + token
                            + '">',
                        )
                        payload = text.encode("utf-8")
                    archive.writestr(part_name, payload)
        return output.getvalue()

    @staticmethod
    def _resolved_document_xml(path: str | Path) -> str:
        with ZipFile(Path(path)) as archive:
            return archive.read("word/document.xml").decode("utf-8", "replace")


if __name__ == "__main__":
    unittest.main()
